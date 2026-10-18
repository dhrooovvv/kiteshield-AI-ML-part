"""Authenticated advisory checks. These routes never authorize execution."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.logging import correlation_id_var
from app.core.security import verify_api_key
from app.schemas import APIResponse
from app.schemas.economics import EconomicCheckRequest, EconomicCheckResponse
from app.services.economic_guard import evaluate_gas_economics

router = APIRouter(prefix="/security", tags=["Security"])


@router.post("/economic-check", response_model=APIResponse)
async def economic_check(
    request: EconomicCheckRequest,
    _: Annotated[str, Depends(verify_api_key)],
) -> APIResponse:
    """Fee advice from supplied estimates; does not create or execute proposals."""
    assessment = evaluate_gas_economics(
        value_wei=int(request.value_wei),
        estimated_gas=request.estimated_gas,
        gas_price_wei=int(request.gas_price_gwei * 10**9),
        max_gas_price_wei=int(request.max_gas_price_gwei * 10**9),
    )
    return APIResponse(
        data=EconomicCheckResponse(
            is_economically_viable=assessment.is_economically_viable,
            gas_cost_wei=assessment.gas_cost_wei,
            gas_cost_eth=assessment.gas_cost_eth,
            gas_to_value_ratio=assessment.gas_to_value_ratio,
            warnings=list(assessment.warnings),
            estimated_gas=request.estimated_gas,
            gas_price_gwei=str(request.gas_price_gwei),
            max_gas_price_gwei=str(request.max_gas_price_gwei),
            value_wei=request.value_wei,
        ),
        meta={"correlation_id": correlation_id_var.get()},
    )
