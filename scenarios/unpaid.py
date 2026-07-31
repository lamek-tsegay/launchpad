"""Unpaid tier: orchestrator only wakes brand_lead and content_lead --
market_lead and ops_lead never run, and the Payment Protocol is never
invoked at all (payment_gate skips straight to orchestrator for
tier=unpaid, spec section 3).

Run the four launchpad processes first, then:  python3 scenarios/unpaid.py
"""

from _client import run_scenario

if __name__ == "__main__":
    run_scenario(
        "unpaid",
        "I'm opening a small boutique clothing shop downtown. tier=unpaid",
    )
