import config
from agents.leads._common import LeadWiring
from shared_models import OpsLeadRequest, WORKER_REQUEST_TYPES, WORKER_RESPONSE_TYPES

ops_lead = config.build_agent("ops_lead")

_WORKER_NAMES = ["ops_entity", "ops_tax", "ops_permits", "ops_health", "ops_food_handler", "ops_insurance"]
_WORKERS = {
    name: (WORKER_REQUEST_TYPES[name], WORKER_RESPONSE_TYPES[name], f"ops.{name.split('_', 1)[1]}")
    for name in _WORKER_NAMES
}


def _select(msg) -> list:
    # msg.ops_team is decided by orchestrator from intake["business_type"]
    # (config.OPS_TEAM_BY_BUSINESS_TYPE) -- same code path here every run,
    # different width depending on what's actually in ops_team.
    return [name for name in msg.ops_team if name in _WORKERS]


wiring = LeadWiring(ops_lead, team="ops_lead", request_type=OpsLeadRequest, workers=_WORKERS, select_workers=_select)
