"""Paid tier, but the requested amount exceeds gateway's policy max (10.0
FET) -- produces the RequestPayment -> RejectPayment leg of the ladder
instead of RequestPayment -> CommitPayment -> CompletePayment. payment_gate
still forwards to orchestrator afterward, downgraded to unpaid features
(spec section 1: the pipeline never hard-fails).

Run the four launchpad processes first, then:
    python3 scenarios/rejected_payment.py
"""

from _client import run_scenario

if __name__ == "__main__":
    run_scenario(
        "rejected-payment",
        "I'm opening a small boutique clothing shop downtown. tier=paid amount=15.0",
    )
