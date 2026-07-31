import config
from agents.leads._common import LeadWiring
from shared_models import ContentLeadRequest, WORKER_REQUEST_TYPES, WORKER_RESPONSE_TYPES

content_lead = config.build_agent("content_lead")

_WORKER_NAMES = ["content_hero", "content_about", "content_services", "content_faq", "content_email"]
_WORKERS = {
    name: (WORKER_REQUEST_TYPES[name], WORKER_RESPONSE_TYPES[name], f"content.{name.split('_', 1)[1]}")
    for name in _WORKER_NAMES
}

wiring = LeadWiring(content_lead, team="content_lead", request_type=ContentLeadRequest, workers=_WORKERS)
