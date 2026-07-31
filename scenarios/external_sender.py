"""Verifies the one thing scenarios/*.py can't: that the pipeline works for
a sender that ISN'T `user_proxy` -- a fresh, random identity, generated
here and now, never added to `config.AGENT_ADDRESSES` or
`config._RESOLVER_RULES`. This is the closest local stand-in for a real
ASI:One user: `delivery`'s reply has to fall through to `GlobalResolver`
(config.py's `_FallbackResolver`) instead of finding this address in the
local table the way every scripted scenario's `user_proxy` always does.

What this proves: the pipeline runs end to end for an unknown sender, and
`delivery` addresses its reply to the RIGHT (fresh, random) address, not a
wrong or substituted one. What it can't prove: that a real Agentverse
mailbox actually delivers cross-machine -- this identity was never
registered on Almanac, so GlobalResolver legitimately can't find live
endpoints for it either; expect delivery's send to fail with "unable to
resolve" for that reason, not a wrong-address bug. That last mile needs a
real Agentverse account (see AGENTVERSE.md's "Not done" section) and,
ultimately, a real ASI:One browser session -- this script is the part of
the demo path that doesn't need either.

Run the five launchpad processes first, then:
    python3 scenarios/external_sender.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uagents import Agent, Bureau, Context  # noqa: E402
from uagents.crypto import Identity  # noqa: E402
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, TextContent  # noqa: E402

import config  # noqa: E402

TIMEOUT_SECONDS = 45.0
CLIENT_PORT = 8106  # one above config.PROCESS_PORTS["client"] (8105) -- avoid colliding with scenarios/_client.py


def main() -> None:
    fresh_seed = f"external-sender-{int(time.time())}"
    identity = Identity.from_seed(fresh_seed, 0)
    print(f"[external-sender] fresh identity (not in config.AGENT_ADDRESSES): {identity.address}")

    stranger = Agent(name="stranger", seed=fresh_seed, port=CLIENT_PORT, endpoint=[f"http://127.0.0.1:{CLIENT_PORT}/submit"])
    started = {"t": None}

    @stranger.on_interval(period=2.0)
    async def send_once(ctx: Context) -> None:
        if started["t"] is not None:
            return
        started["t"] = time.time()
        text = "I want to start a food truck serving Ethiopian food in Austin, Texas. tier=paid amount=5.0"
        print(f"[external-sender] sending: {text!r}")
        message = ChatMessage(content=[TextContent(text=text)])
        await ctx.send(config.AGENT_ADDRESSES["gateway"], message)
        print(f"[external-sender] send-side session (trace_id candidate): {ctx.session}")

    @stranger.on_message(model=ChatAcknowledgement)
    async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
        print(f"[external-sender] gateway acked msg {msg.acknowledged_msg_id}")

    @stranger.on_message(model=ChatMessage)
    async def handle_reply(ctx: Context, sender: str, msg: ChatMessage) -> None:
        print(f"[external-sender] FINAL REPLY (receive-side session: {ctx.session})")
        print("-" * 72)
        print(msg.text())
        print("-" * 72)
        sys.stdout.flush()
        os._exit(0)

    @stranger.on_interval(period=5.0)
    async def watchdog(ctx: Context) -> None:
        if started["t"] is None:
            return
        if time.time() - started["t"] > TIMEOUT_SECONDS:
            print(
                f"[external-sender] no final reply within {TIMEOUT_SECONDS}s -- giving up.\n"
                "This can mean either a real pipeline problem, or (if you see a 'dropped' /\n"
                "'unable to resolve' span for delivery -> this address in the trace) that\n"
                "GlobalResolver legitimately can't reach an unregistered identity -- expected\n"
                "for this script, see its own module docstring."
            )
            sys.stdout.flush()
            os._exit(1)

    Bureau(agents=[stranger], port=CLIENT_PORT, endpoint=f"http://127.0.0.1:{CLIENT_PORT}/submit").run()


if __name__ == "__main__":
    main()
