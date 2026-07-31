"""Gates the paid tier (spec section 1/3). Unpaid intake skips the Payment
Protocol entirely and goes straight to `orchestrator`. Paid intake starts a
real RequestPayment -> CommitPayment/RejectPayment -> CompletePayment
exchange with `gateway` (standing in for the user's wallet) before
forwarding on -- a rejected payment still reaches `orchestrator`, just
downgraded to the unpaid feature set, matching "the pipeline must never
hard-fail" elsewhere in this spec.
"""

from dataclasses import dataclass
from typing import Dict

import config
from shared_models import OrchestratorRequest, PaymentGateRequest
from uagents import Context
from uagents_core.contrib.protocols.payment import CommitPayment, CompletePayment, Funds, RejectPayment, RequestPayment
from uagents_trace import trace, traced_send

payment_gate = config.build_agent("payment_gate")


@dataclass
class _PendingPayment:
    intake: Dict


_state: Dict[str, _PendingPayment] = {}


@payment_gate.on_message(model=PaymentGateRequest)
@trace
async def handle_payment_gate_request(ctx: Context, sender: str, msg: PaymentGateRequest) -> None:
    intake = msg.intake

    if intake.get("tier") != "paid":
        await traced_send(ctx, config.AGENT_ADDRESSES["orchestrator"], OrchestratorRequest(intake=intake))
        return

    session = str(ctx.session)
    _state[session] = _PendingPayment(intake=intake)
    amount = str(intake.get("payment_amount", "5.0"))
    await traced_send(
        ctx,
        config.AGENT_ADDRESSES["gateway"],
        RequestPayment(
            accepted_funds=[Funds(amount=amount, currency="FET")],
            recipient=payment_gate.address,
            deadline_seconds=30,
            reference=session,
        ),
    )


@payment_gate.on_message(model=CommitPayment)
@trace
async def handle_commit(ctx: Context, sender: str, msg: CommitPayment) -> None:
    session = str(ctx.session)
    pending = _state.pop(session, None)
    if pending is None:
        ctx.logger.warning(f"payment_gate: CommitPayment for unknown session {session}")
        return

    await traced_send(ctx, sender, CompletePayment(transaction_id=msg.transaction_id))
    await traced_send(ctx, config.AGENT_ADDRESSES["orchestrator"], OrchestratorRequest(intake=pending.intake))


@payment_gate.on_message(model=RejectPayment)
@trace
async def handle_reject(ctx: Context, sender: str, msg: RejectPayment) -> None:
    session = str(ctx.session)
    pending = _state.pop(session, None)
    if pending is None:
        ctx.logger.warning(f"payment_gate: RejectPayment for unknown session {session}")
        return

    ctx.logger.info(f"payment_gate: payment rejected -- {msg.reason}; continuing at unpaid tier")
    downgraded = {**pending.intake, "tier": "unpaid"}
    await traced_send(ctx, config.AGENT_ADDRESSES["orchestrator"], OrchestratorRequest(intake=downgraded))
