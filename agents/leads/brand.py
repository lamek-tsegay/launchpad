import config
from agents.leads._common import LeadWiring
from shared_models import BrandLeadRequest, WORKER_REQUEST_TYPES, WORKER_RESPONSE_TYPES

brand_lead = config.build_agent("brand_lead")

_WORKER_NAMES = ["brand_name", "brand_palette", "brand_logo_brief", "brand_voice"]
_WORKERS = {
    name: (WORKER_REQUEST_TYPES[name], WORKER_RESPONSE_TYPES[name], f"brand.{name.split('_', 1)[1]}")
    for name in _WORKER_NAMES
}

wiring = LeadWiring(brand_lead, team="brand_lead", request_type=BrandLeadRequest, workers=_WORKERS)
