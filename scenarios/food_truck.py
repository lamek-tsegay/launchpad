"""Widest ops fan-out: business_type=food pulls in all six ops workers,
including the never-started ops_insurance. Paid tier, so market_lead and
its competitor/scout depth run too.

Run the four launchpad processes first (run_core/run_creative/run_market/
run_ops.py), then:  python3 scenarios/food_truck.py
"""

from _client import run_scenario

if __name__ == "__main__":
    run_scenario(
        "food-truck",
        "I want to start a food truck serving Ethiopian food in Austin, Texas. tier=paid amount=5.0",
    )
