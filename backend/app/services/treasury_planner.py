"""Pure integer-wei planner. No network, database, signing, or refill authority."""

from dataclasses import asdict, dataclass
from enum import StrEnum


class PlanState(StrEnum):
    DISABLED = "DISABLED"
    BELOW_TARGET = "BELOW_TARGET"
    WITHIN_TARGET_BAND = "WITHIN_TARGET_BAND"
    ELIGIBLE = "ELIGIBLE"
    COOLDOWN = "COOLDOWN_ACTIVE"
    DAILY_LIMIT = "DAILY_ACTION_LIMIT"
    OUTSTANDING = "OUTSTANDING_EXECUTION"
    INVALIDATED = "INVALIDATED_MANDATE"
    POLICY = "POLICY_RESTRICTED"
    NETWORK = "NETWORK_UNAVAILABLE"
    STALE = "STALE_SNAPSHOT"
    UNAVAILABLE = "EXECUTION_UNAVAILABLE"


@dataclass(frozen=True)
class PlanInput:
    balance: int | None
    target: int
    sweep_maximum: int
    minimum_excess: int
    maximum_fee_reserve: int
    enabled: bool = True
    valid: bool = True
    verified: bool = True
    fresh: bool = True
    outstanding: bool = False
    cooldown: bool = False
    daily_limit_reached: bool = False
    policy_allowed: bool = True
    execution_available: bool = True
    execute_mode: bool = False

    def __post_init__(self):
        for value in (
            self.target,
            self.sweep_maximum,
            self.minimum_excess,
            self.maximum_fee_reserve,
        ):
            if type(value) is not int:
                raise ValueError("Planner amounts must be exact integer wei")
        if self.balance is not None and type(self.balance) is not int:
            raise ValueError("Observed balance must be integer wei or unavailable")


@dataclass(frozen=True)
class TreasuryPlan:
    state: PlanState
    reason: str
    available_excess_wei: str = "0"
    proposed_amount_wei: str = "0"

    def to_dict(self) -> dict:
        return asdict(self)


def plan_sweep(i: PlanInput) -> TreasuryPlan:
    if min(i.target, i.maximum_fee_reserve) < 0 or min(i.sweep_maximum, i.minimum_excess) <= 0:
        raise ValueError("Invalid integer-wei planner bounds")
    for condition, state in (
        (not i.enabled, PlanState.DISABLED),
        (not i.valid, PlanState.INVALIDATED),
        (not i.verified or i.balance is None, PlanState.NETWORK),
        (not i.fresh, PlanState.STALE),
        (i.outstanding, PlanState.OUTSTANDING),
        (i.cooldown, PlanState.COOLDOWN),
        (i.daily_limit_reached, PlanState.DAILY_LIMIT),
    ):
        if condition:
            return TreasuryPlan(state, state.value)
    if i.balance < 0:
        return TreasuryPlan(PlanState.NETWORK, "INVALID_BALANCE")
    if i.balance < i.target:
        return TreasuryPlan(PlanState.BELOW_TARGET, "HUMAN_REFILL_ONLY")
    excess = i.balance - i.target - i.maximum_fee_reserve
    if excess < i.minimum_excess:
        return TreasuryPlan(PlanState.WITHIN_TARGET_BAND, "EXCESS_BELOW_MINIMUM", str(excess))
    amount = min(excess, i.sweep_maximum)
    if not i.policy_allowed:
        return TreasuryPlan(PlanState.POLICY, "UNATTENDED_SCOPE_RESTRICTED", str(excess))
    if i.execute_mode and not i.execution_available:
        return TreasuryPlan(PlanState.UNAVAILABLE, "GLOBAL_EXECUTION_UNAVAILABLE", str(excess))
    return TreasuryPlan(PlanState.ELIGIBLE, "BOUNDED_SWEEP", str(excess), str(amount))
