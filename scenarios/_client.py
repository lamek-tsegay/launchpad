"""Shared driver for scenario scripts: sends one ChatMessage to `gateway`
as `user_proxy` (config.py's fixed-identity stand-in for "the chat user")
and prints whatever comes back, or times out. Run as its own short-lived
process -- the five launchpad processes (run_gateway/run_core/
run_creative/run_market/run_ops) must already be running against the same
UAGENTS_TRACE_DB.

Uses `config.build_agent("user_proxy")` like every other Launchpad agent
-- no special-casing needed here. `config._RESOLVER_RULES` already
includes `gateway`'s real local route for every agent (see the comment
there): mailbox is about how a genuinely external ASI:One user reaches
gateway, not about how agents we run ourselves reach it, so this scripted
test client (like `payment_gate`) talks to `gateway` over plain loopback
HTTP regardless of the mailbox connection's state.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uagents import Bureau, Context  # noqa: E402
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, TextContent  # noqa: E402

import config  # noqa: E402

DEFAULT_TIMEOUT_SECONDS = 45.0


def run_scenario(name: str, text: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
    user_proxy = config.build_agent("user_proxy")
    _started = {"t": None, "session": None}

    @user_proxy.on_interval(period=2.0)
    async def send_once(ctx: Context) -> None:
        if _started["t"] is not None:
            return
        _started["t"] = time.time()
        print(f"[{name}] user_proxy address: {user_proxy.address}")
        print(f"[{name}] sending: {text!r}")
        message = ChatMessage(content=[TextContent(text=text)])
        await ctx.send(config.AGENT_ADDRESSES["gateway"], message)
        _started["session"] = str(ctx.session)
        print(f"[{name}] send-side session (trace_id candidate): {_started['session']}")

    @user_proxy.on_message(model=ChatAcknowledgement)
    async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
        print(f"[{name}] gateway acked msg {msg.acknowledged_msg_id}")

    @user_proxy.on_message(model=ChatMessage)
    async def handle_reply(ctx: Context, sender: str, msg: ChatMessage) -> None:
        print(f"[{name}] FINAL REPLY (receive-side session: {ctx.session})")
        print("-" * 72)
        print(msg.text())
        print("-" * 72)
        sys.stdout.flush()
        os._exit(0)

    @user_proxy.on_interval(period=5.0)
    async def watchdog(ctx: Context) -> None:
        if _started["t"] is None:
            return
        elapsed = time.time() - _started["t"]
        if elapsed > timeout:
            print(f"[{name}] no final reply within {timeout}s -- giving up (this may be expected, see FINDINGS.md)")
            sys.stdout.flush()
            os._exit(1)

    bureau = Bureau(agents=[user_proxy], port=config.process_port("client"), endpoint=f"http://127.0.0.1:{config.process_port('client')}/submit")
    bureau.run()
