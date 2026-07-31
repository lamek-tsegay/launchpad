"""Chat protocol entry point (spec section 1). Acks every ChatMessage
immediately (hard constraint #3) before any dedup/cooldown check, so a
dropped duplicate still looks acknowledged from the sender's side.

Also plays the buyer's role in the Payment Protocol side-conversation with
`payment_gate` (spec section 6 in the flow diagram is simplified and
doesn't draw this, but `payment_gate` needs a counterparty and gateway is
the only agent here already standing in for "the user").
"""

import time
import uuid

import config
from shared_models import ParseRequest
from uagents import Context
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage
from uagents_core.contrib.protocols.payment import CommitPayment, CompletePayment, RejectPayment, RequestPayment
from uagents_trace import trace, traced_send

gateway = config.build_agent("gateway")

COOLDOWN_SECONDS = 30
DEDUP_WINDOW_SECONDS = 120
MAX_ACCEPTED_FET = 10.0

_last_reply_time: dict = {}
_seen_texts: dict = {}


@gateway.on_message(model=ChatMessage)
@trace
async def handle_chat_message(ctx: Context, sender: str, msg: ChatMessage) -> None:
    # Hard constraint #3: ack first, always -- even messages we're about to
    # drop for cooldown/dedup (anti-echo, spec section 8).
    await ctx.send(sender, ChatAcknowledgement(timestamp=msg.timestamp, acknowledged_msg_id=msg.msg_id))

    text = msg.text()
    now = time.time()

    text_key = (sender, text)
    last_seen = _seen_texts.get(text_key)
    if last_seen is not None and now - last_seen < DEDUP_WINDOW_SECONDS:
        ctx.logger.info(f"gateway: dropping exact-duplicate text from {sender} (anti-echo dedup)")
        return
    _seen_texts[text_key] = now

    last_reply = _last_reply_time.get(sender)
    if last_reply is not None and now - last_reply < COOLDOWN_SECONDS:
        ctx.logger.info(f"gateway: dropping message from {sender} (cooldown)")
        return
    _last_reply_time[sender] = now

    await traced_send(ctx, config.AGENT_ADDRESSES["parser"], ParseRequest(text=text, chat_sender=sender))


@gateway.on_message(model=RequestPayment)
@trace
async def handle_request_payment(ctx: Context, sender: str, msg: RequestPayment) -> None:
    funds = msg.accepted_funds[0]
    if float(funds.amount) > MAX_ACCEPTED_FET:
        ctx.logger.info(f"gateway: rejecting {funds.amount} {funds.currency} -- above {MAX_ACCEPTED_FET} policy max")
        await traced_send(ctx, sender, RejectPayment(reason=f"amount exceeds {MAX_ACCEPTED_FET} FET policy max"))
        return

    ctx.logger.info(f"gateway: committing to {funds.amount} {funds.currency}")
    await traced_send(
        ctx,
        sender,
        CommitPayment(funds=funds, recipient=ctx.agent.address, transaction_id=str(uuid.uuid4()), reference=msg.reference),
    )


@gateway.on_message(model=CompletePayment)
@trace
async def handle_complete_payment(ctx: Context, sender: str, msg: CompletePayment) -> None:
    ctx.logger.info(f"gateway: payment complete, tx {msg.transaction_id}")
