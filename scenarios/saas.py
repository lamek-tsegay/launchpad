"""Narrowest ops fan-out: business_type=saas pulls in just ops_entity and
ops_tax. Paid tier, so market_lead still runs (competitor/scout depth is
independent of business_type).

Run the four launchpad processes first, then:  python3 scenarios/saas.py
"""

from _client import run_scenario

if __name__ == "__main__":
    run_scenario(
        "saas",
        "I'm building a subscription SaaS platform for scheduling freelance tutors, based remotely. tier=paid amount=5.0",
    )
