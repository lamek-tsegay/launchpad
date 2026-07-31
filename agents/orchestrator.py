import config
from shared_models import BrandLeadRequest, ContentLeadRequest, MarketLeadRequest, OpsLeadRequest, OrchestratorRequest
from uagents import Context
from uagents_trace import trace, traced_send

orchestrator = config.build_agent("orchestrator")


@orchestrator.on_message(model=OrchestratorRequest)
@trace
async def handle_orchestrator_request(ctx: Context, sender: str, msg: OrchestratorRequest) -> None:
    intake = msg.intake

    await traced_send(ctx, config.AGENT_ADDRESSES["brand_lead"], BrandLeadRequest(intake=intake))
    await traced_send(ctx, config.AGENT_ADDRESSES["content_lead"], ContentLeadRequest(intake=intake))

    if intake.get("tier") == "paid":
        await traced_send(ctx, config.AGENT_ADDRESSES["market_lead"], MarketLeadRequest(intake=intake))
        business_type = intake.get("business_type", "services")
        ops_team = config.OPS_TEAM_BY_BUSINESS_TYPE.get(business_type, config.OPS_TEAM_BY_BUSINESS_TYPE["services"])
        await traced_send(ctx, config.AGENT_ADDRESSES["ops_lead"], OpsLeadRequest(intake=intake, ops_team=ops_team))
