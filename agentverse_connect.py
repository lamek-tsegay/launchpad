"""One-time script: connect every mailbox-enabled Launchpad agent
(config.MAILBOX_AGENTS, default all 32 running agents) to your Agentverse
account, so they show up as connected/reachable in the Agentverse UI
rather than just Almanac-`active`.

Reuses uAgents' own `/connect` REST handler logic directly (the same code
path the agent inspector's "Connect" button triggers) rather than
reimplementing the registration protocol -- see `register_in_agentverse`
in `uagents/mailbox.py` for what actually happens underneath.

None of the five Launchpad processes need to be running for this --
each agent is constructed in-process just long enough to run its own
`/connect` handler once, then discarded. Idempotent: safe to re-run,
already-connected agents just get reconfirmed.

I (the agent that wrote this) have not been able to run this end to end:
this environment has no AGENTVERSE_API_KEY. Set one from your Agentverse
account settings (Profile -> API Keys) and run it yourself -- this script
never prints or logs the key itself, only pass/fail per agent.

Usage:
    export AGENTVERSE_API_KEY=...
    ./.venv/bin/python3 agentverse_connect.py                       # connect every agent in config.MAILBOX_AGENTS
    ./.venv/bin/python3 agentverse_connect.py --only parser,gateway # connect specific agents only
    ./.venv/bin/python3 agentverse_connect.py --dry-run             # print who *would* be connected, make no API calls
"""

import argparse
import asyncio
import os
import sys

import config
from uagents.mailbox import AgentverseConnectRequest


async def connect_one(name: str, api_key: str) -> tuple[str, bool, str]:
    if name in config.NEVER_STARTED:
        return name, False, "never started (spec section 1) -- intentionally not connected"
    if name not in config.MAILBOX_AGENTS:
        return name, False, "not in config.MAILBOX_AGENTS -- would connect a mailbox this agent isn't configured to use (mailbox=True); skipped"

    agent = config.build_agent(name)
    if agent.agent_type != "mailbox":
        return name, False, f"config.build_agent({name!r}) did not come back as a mailbox agent (got {agent.agent_type!r}) -- config drifted from MAILBOX_AGENTS, not connecting"

    request = AgentverseConnectRequest(user_token=api_key, agent_type=agent.agent_type)
    try:
        response = await agent.handle_rest("POST", "/connect", request)
    except Exception as exc:  # noqa: BLE001 -- report per-agent, don't let one failure stop the batch
        return name, False, f"exception: {exc}"

    if response is None:
        return name, False, "no /connect handler responded (unexpected -- enable_agent_inspector should always register one)"
    success = getattr(response, "success", False)
    detail = getattr(response, "detail", None) or ("connected" if success else "failed, no detail given")
    return name, success, detail


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="comma-separated agent names to connect (default: everyone in config.MAILBOX_AGENTS)")
    parser.add_argument("--dry-run", action="store_true", help="print who would be connected; make no API calls")
    args = parser.parse_args()

    names = [n.strip() for n in args.only.split(",")] if args.only else sorted(config.MAILBOX_AGENTS)

    if args.dry_run:
        print(f"Would connect {len(names)} agent(s):")
        for name in names:
            print(f"  {name}")
        return

    api_key = os.environ.get("AGENTVERSE_API_KEY")
    if not api_key:
        print("AGENTVERSE_API_KEY not set -- export it from your Agentverse account's API key settings first.")
        sys.exit(1)

    print(f"Connecting {len(names)} agent(s)...\n")
    results = []
    for name in names:
        result = await connect_one(name, api_key)
        results.append(result)
        name_, success, detail = result
        status = "OK" if success else "FAILED"
        print(f"  {name_:28s} {status:7s} {detail}")

    failed = [r for r in results if not r[1]]
    print()
    if failed:
        print(f"{len(results) - len(failed)}/{len(results)} connected. Failed: {', '.join(r[0] for r in failed)}")
        sys.exit(1)
    print(f"All {len(results)} connected.")


if __name__ == "__main__":
    asyncio.run(main())
