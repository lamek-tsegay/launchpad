"""Run the four launchpad processes with LAUNCHPAD_FAILURES unset (or set
to config.py's default) so all three failure modes are live:
ops_insurance=unreachable, brand_logo_brief=slow, market_scout_3=raises.

Unlike the other four scenarios, this one is *expected* not to produce a
final reply within the timeout: market_competitor_finder waits for every
scout it dispatched before replying to market_lead, and market_scout_3
never replies at all (its handler raises), so market_lead never completes
and the run never reaches delivery. That stall is itself the point --
inspect the partial trace with `uagents-trace show <trace_id>` (the
send-side session printed below) to see exactly how far it got. See
FINDINGS.md for the trace ID from the reference run and what each failure
mode looked like in the spans.

Run the four launchpad processes first (with LAUNCHPAD_FAILURES unset),
then:  python3 scenarios/failures_enabled.py
"""

from _client import run_scenario

if __name__ == "__main__":
    run_scenario(
        "failures-enabled",
        "I want to start a food truck serving Ethiopian food in Austin, Texas. tier=paid amount=5.0",
        timeout=30,
    )
