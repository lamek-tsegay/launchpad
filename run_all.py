"""Bring up all five Launchpad processes and confirm every agent is alive
(process listening on its port) and registered (visible in Agentverse's
public Almanac, `status: active`) -- one command, one readable table.

`ops_insurance` is deliberately never started (spec section 1) -- reported
as INTENTIONALLY DOWN, not missing, so it never looks like a failure.

Almanac registration is automatic uAgents behavior for any agent with a
non-empty `endpoint` (no AGENTVERSE_API_KEY needed for this) -- it does
*not* require `mailbox=True`. This script only checks that automatic
registration; it does not set up mailbox/chat-reachability (see
AGENTVERSE.md for that, which is a separate decision).

Usage:
    ./.venv/bin/python3 run_all.py            # start + verify, then exit (processes keep running)
    ./.venv/bin/python3 run_all.py --stop     # stop everything this script started
    ./.venv/bin/python3 run_all.py --status   # just re-check status, don't (re)start anything
    ./.venv/bin/python3 run_all.py --demo     # demo config (see DEMO.md): stops anything stale first,
                                               # runs fast+failure-safe, mailbox scoped to gateway only,
                                               # prints the ASI:One entry point at the end
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# --demo sets these (only where the caller hasn't already set them -- an
# explicit export always wins) *before* `import config`, since config.py
# reads LAUNCHPAD_MODE/LAUNCHPAD_FAILURES/LAUNCHPAD_MAILBOX_AGENTS at
# import time, not lazily -- setting them after the import would be too
# late for anything config.py already computed from them (MAILBOX_AGENTS,
# FAILURES, DEMO_MODE-derived timeouts).
if "--demo" in sys.argv:
    os.environ["LAUNCHPAD_MODE"] = "demo"
    os.environ.setdefault("LAUNCHPAD_FAILURES", "{}")  # ops_insurance still fails -- structural, not FAILURES-gated
    os.environ.setdefault("LAUNCHPAD_MAILBOX_AGENTS", "gateway")  # only gateway chat-discoverable -- see AGENTVERSE.md
    os.environ.setdefault("UAGENTS_TRACE_DB", str(Path(__file__).resolve().parent / "uagents_trace.db"))

import config

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / ".run_all_logs"
PID_FILE = ROOT / ".run_all.pids"

PROCESSES = {
    "gateway": "run_gateway.py",
    "core": "run_core.py",
    "creative": "run_creative.py",
    "market": "run_market.py",
    "ops": "run_ops.py",
}

ALMANAC_AGENT_URL = "https://agentverse.ai/v1/almanac/agents/{address}"
PORT_WAIT_TIMEOUT_SECONDS = 30
ALMANAC_CHECK_ROUNDS = 5
ALMANAC_ROUND_INTERVAL_SECONDS = 3
ALMANAC_CONCURRENCY = 16


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _wait_for_port(port: int, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open(port):
            return True
        time.sleep(0.5)
    return False


def _listening_pid(port: int) -> int | None:
    """PID of the process currently LISTENing on `port`, or None if either
    nothing is or the check itself couldn't run (`lsof` missing/failed) --
    callers must not conflate those two cases (see start()'s use of this).
    """
    try:
        result = subprocess.run(
            ["lsof", f"-iTCP:{port}", "-sTCP:LISTEN", "-n", "-P", "-t"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    pids = [int(p) for p in result.stdout.split() if p.strip().isdigit()]
    return pids[0] if pids else None


def _almanac_status(address: str) -> dict | None:
    """None if not found / not yet registered / request failed.

    Sets a plain browser-ish User-Agent -- Agentverse's edge (Cloudflare)
    returns a bare 403 for `urllib`'s default `Python-urllib/3.x` UA, no
    body, indistinguishable from "agent not registered" unless you notice
    the status code. curl isn't blocked, which is why a manual `curl`
    sanity check can look fine while this silently returns nothing.
    """
    url = ALMANAC_AGENT_URL.format(address=address)
    req = urllib.request.Request(url, headers={"User-Agent": "launchpad-run_all/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read())
    except urllib.error.HTTPError:
        return None
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def start(*, force: bool = False) -> None:
    if PID_FILE.exists():
        if not force:
            print(f"{PID_FILE} already exists -- run with --stop first, or delete it if the processes are already gone.")
            sys.exit(1)
        print(f"{PID_FILE} already exists -- stopping the stale run first (--demo always starts clean).")
        stop()

    LOG_DIR.mkdir(exist_ok=True)
    pids: dict[str, int] = {}

    print(f"Starting {len(PROCESSES)} processes...")
    for process, script in PROCESSES.items():
        log_path = LOG_DIR / f"{process}.log"
        with open(log_path, "w") as log_file:
            proc = subprocess.Popen(
                [sys.executable, script],
                cwd=ROOT,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        pids[process] = proc.pid
        print(f"  {process:10s} pid={proc.pid:<8} log={log_path}")

    PID_FILE.write_text(json.dumps(pids))

    print(f"\nWaiting for all {len(PROCESSES)} ports to come up...")
    all_up = True
    for process, port in config.PROCESS_PORTS.items():
        if process not in PROCESSES:
            continue  # e.g. "client" -- not a Launchpad process, scenarios/_client.py owns that port

        up = _wait_for_port(port, PORT_WAIT_TIMEOUT_SECONDS)
        if not up:
            print(f"  {process:10s} :{port}  TIMED OUT")
            all_up = False
            continue

        # A port being open doesn't mean *our* process bound it -- an
        # orphaned process from an earlier run can already be squatting it,
        # in which case the process we just spawned failed to bind and
        # likely exited, but the port check above would report "up" anyway
        # (something IS listening, just not what we started). Confirm the
        # PID actually matches.
        expected_pid = pids[process]
        actual_pid = _listening_pid(port)
        if actual_pid is None:
            print(f"  {process:10s} :{port}  up (pid unverified -- 'lsof' unavailable or check failed; not treating this as confirmed)")
        elif actual_pid != expected_pid:
            print(
                f"  {process:10s} :{port}  WRONG PROCESS LISTENING -- pid {actual_pid} owns this port, "
                f"not the pid {expected_pid} we just spawned. Likely an orphaned process from an earlier "
                f"run still squatting this port; `kill {actual_pid}` and retry. Check .run_all_logs/{process}.log "
                f"for why pid {expected_pid} failed to bind."
            )
            all_up = False
        else:
            print(f"  {process:10s} :{port}  up (pid {actual_pid} confirmed)")

    if not all_up:
        print("\nOne or more processes did not come up correctly -- see above and check .run_all_logs/*.log")
        sys.exit(1)

    print()
    status()


def stop() -> None:
    if not PID_FILE.exists():
        print("No .run_all.pids file -- nothing to stop (or it wasn't started with this script).")
        return
    pids = json.loads(PID_FILE.read_text())
    for process, pid in pids.items():
        try:
            subprocess.run(["kill", str(pid)], check=False)
            print(f"stopped {process} (pid={pid})")
        except Exception as exc:
            print(f"failed to stop {process} (pid={pid}): {exc}")
    PID_FILE.unlink()


def _check_almanac_batch(names: list[str]) -> dict[str, dict | None]:
    """Checks many agents concurrently (one thread pool, not one blocking
    request per agent) -- sequential per-agent retries would mean up to
    32 x several-second waits stacking end to end.
    """
    with ThreadPoolExecutor(max_workers=ALMANAC_CONCURRENCY) as pool:
        results = pool.map(lambda n: _almanac_status(config.AGENT_ADDRESSES[n]), names)
    return dict(zip(names, results))


def _expected_almanac_type(name: str) -> str:
    return "mailbox" if name in config.MAILBOX_AGENTS else "local"


def status() -> None:
    print("Checking Agentverse Almanac registration (this can take a few seconds after startup)...\n")

    startable = [n for n in config.LAUNCHPAD_AGENT_NAMES if n not in config.NEVER_STARTED]
    local_alive = {n: _port_open(config.PROCESS_PORTS[config.AGENT_PROCESS[n]]) for n in startable}

    # One round-trip per round for *all* pending agents at once, not one
    # timeout window per agent -- registration usually lands within the
    # first round or two; a handful of rounds with a short shared sleep
    # between them covers the rest without making 32 agents each pay their
    # own worst-case wait. "Pending" means not just "registered at all" but
    # "registered with the `type` this agent is supposed to have" --
    # `type` flips from a stale prior value (e.g. "local" left over from
    # before an agent joined MAILBOX_AGENTS) to the correct one on the next
    # registration cycle, not instantly, so re-checking matters here.
    pending = list(startable)
    results: dict[str, dict | None] = {}
    for round_num in range(ALMANAC_CHECK_ROUNDS):
        if not pending:
            break
        batch = _check_almanac_batch(pending)
        still_pending = []
        for name, info in batch.items():
            if info is not None:
                results[name] = info
            if info is None or info.get("type") != _expected_almanac_type(name):
                still_pending.append(name)
        pending = still_pending
        if pending and round_num < ALMANAC_CHECK_ROUNDS - 1:
            time.sleep(ALMANAC_ROUND_INTERVAL_SECONDS)
    for name in pending:
        results.setdefault(name, None)

    rows = []
    for name in config.LAUNCHPAD_AGENT_NAMES:
        process = config.AGENT_PROCESS[name]

        if name in config.NEVER_STARTED:
            rows.append((name, process, "INTENTIONALLY DOWN", "-", "never started (spec section 1) -- not a failure"))
            continue

        local = "alive" if local_alive[name] else "DOWN"
        info = results.get(name)
        expected_type = _expected_almanac_type(name)
        if info is None:
            almanac = "NOT REGISTERED"
            note = "not found in Almanac -- check network access / process logs"
        else:
            almanac_status_val = info.get("status", "?")
            almanac_type = info.get("type", "?")
            almanac = f"{almanac_status_val} ({almanac_type})"
            if almanac_status_val != "active":
                note = "unexpected Almanac status"
            elif almanac_type != expected_type:
                note = f"expected type={expected_type} (in MAILBOX_AGENTS: {name in config.MAILBOX_AGENTS}) -- still updating, or not yet mailbox-connected via the agent inspector"
            else:
                note = ""

        rows.append((name, process, local, almanac, note))

    name_w = max(len(r[0]) for r in rows)
    process_w = max(len(r[1]) for r in rows)
    local_w = max(len(r[2]) for r in rows)
    almanac_w = max(len(r[3]) for r in rows)

    header = f"{'AGENT':<{name_w}}  {'PROCESS':<{process_w}}  {'LOCAL':<{local_w}}  {'AGENTVERSE':<{almanac_w}}  NOTES"
    print(header)
    print("-" * len(header))
    for name, process, local_alive, almanac, note in rows:
        print(f"{name:<{name_w}}  {process:<{process_w}}  {local_alive:<{local_w}}  {almanac:<{almanac_w}}  {note}")

    down = [r for r in rows if r[2] == "DOWN"]
    unregistered = [r for r in rows if r[3] == "NOT REGISTERED"]
    wrong_type = [r for r in rows if r[4].startswith("expected type=")]
    print()
    if not down and not unregistered and not wrong_type:
        print(f"All {len(rows) - 1} startable agents alive and Almanac-registered; ops_insurance intentionally down.")
    else:
        if down:
            print(f"DOWN (unexpected): {', '.join(r[0] for r in down)}")
        if unregistered:
            print(f"NOT REGISTERED (unexpected): {', '.join(r[0] for r in unregistered)}")
        if wrong_type:
            print(f"WRONG ALMANAC TYPE (re-check in a bit, or see AGENTVERSE.md): {', '.join(r[0] for r in wrong_type)}")

    if config.MAILBOX_AGENTS:
        print("\nAgent inspector links (mailbox agents only -- see AGENTVERSE.md's \"connect\" step):")
        for name in sorted(config.MAILBOX_AGENTS):
            port = config.PROCESS_PORTS[config.AGENT_PROCESS[name]]
            uri = urllib.parse.quote(f"http://127.0.0.1:{port}", safe="")
            print(f"  {name}: https://agentverse.ai/inspect/?uri={uri}&address={config.AGENT_ADDRESSES[name]}")


def _print_asi_one_entry_point() -> None:
    address = config.AGENT_ADDRESSES["gateway"]
    handle = config._AGENT_DETAILS.get("gateway", {}).get("handle")
    print("\n" + "=" * 72)
    print("ASI:One entry point -- this is the only chat-addressable agent.")
    if handle:
        print(f"  Search Agentverse/ASI:One for: {handle}")
    print(f"  Address (unambiguous fallback): {address}")
    print("=" * 72)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--demo", action="store_true", help="stop anything stale, start in demo config, print the ASI:One entry point")
    args = parser.parse_args()

    if args.stop:
        stop()
    elif args.status:
        status()
    elif args.demo:
        start(force=True)
        _print_asi_one_entry_point()
    else:
        start()
