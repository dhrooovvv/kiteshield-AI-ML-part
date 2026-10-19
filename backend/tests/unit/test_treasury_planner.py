from dataclasses import replace

import pytest

from app.schemas.treasury import MandateInput
from app.services.treasury_planner import PlanInput, PlanState, plan_sweep

BASE = PlanInput(
    balance=1040, target=1000, sweep_maximum=30, minimum_excess=20, maximum_fee_reserve=10
)


@pytest.mark.parametrize(
    "balance,state,amount",
    [
        (999, PlanState.BELOW_TARGET, "0"),
        (1000, PlanState.WITHIN_TARGET_BAND, "0"),
        (1029, PlanState.WITHIN_TARGET_BAND, "0"),
        (1030, PlanState.ELIGIBLE, "20"),
        (1040, PlanState.ELIGIBLE, "30"),
        (10**40, PlanState.ELIGIBLE, "30"),
    ],
)
def test_integer_boundaries(balance, state, amount):
    result = plan_sweep(replace(BASE, balance=balance))
    assert result.state == state and result.proposed_amount_wei == amount


@pytest.mark.parametrize(
    "kwargs,state",
    [
        ({"enabled": False}, PlanState.DISABLED),
        ({"valid": False}, PlanState.INVALIDATED),
        ({"balance": None}, PlanState.NETWORK),
        ({"fresh": False}, PlanState.STALE),
        ({"outstanding": True}, PlanState.OUTSTANDING),
        ({"cooldown": True}, PlanState.COOLDOWN),
        ({"daily_limit_reached": True}, PlanState.DAILY_LIMIT),
        ({"policy_allowed": False}, PlanState.POLICY),
        ({"execute_mode": True, "execution_available": False}, PlanState.UNAVAILABLE),
    ],
)
def test_suppressed_states(kwargs, state):
    assert plan_sweep(replace(BASE, **kwargs)).state == state


@pytest.mark.parametrize("value", [1.2, "-1", "1.1", "1e3", "", "9" * 79])
def test_mandate_invalid_amount(value):
    with pytest.raises(ValueError):
        MandateInput(
            expected_version=0,
            sender="0x" + "11" * 20,
            recipient="0x" + "22" * 20,
            target_balance_wei="0",
            sweep_maximum_wei=value,
            minimum_excess_wei="1",
        )
