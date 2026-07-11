"""Hard timing and post-solve rules for the deterministic planner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .enums import ActionKind, TimingMode
from .model import (
    CandidateAction,
    CandidateOffer,
    FailureRiskSignal,
    LPTBSignal,
    NeedSpec,
    PlanState,
    PriceSignal,
)


@dataclass(frozen=True, slots=True)
class TimingPolicy:
    max_wait_failure_risk: float = 0.55

    def __post_init__(self) -> None:
        if not 0 <= self.max_wait_failure_risk <= 1:
            raise ValueError("Maximum wait risk must be in [0, 1]")


class TimingGate:
    """Creates actions while enforcing the per-offer Normal/Orange decision."""

    def __init__(self, policy: TimingPolicy | None = None) -> None:
        self.policy = policy or TimingPolicy()

    def mode_for(
        self, *, today: date, lptb: LPTBSignal, risk: FailureRiskSignal
    ) -> TimingMode:
        if today >= lptb.lptb or risk.probability >= self.policy.max_wait_failure_risk:
            return TimingMode.ORANGE
        return TimingMode.NORMAL

    def build_actions(
        self,
        *,
        need: NeedSpec,
        offer: CandidateOffer,
        price: PriceSignal,
        risk: FailureRiskSignal,
        lptb: LPTBSignal,
        today: date,
    ) -> tuple[CandidateAction, ...]:
        mode = self.mode_for(today=today, lptb=lptb, risk=risk)
        buy_now = CandidateAction(
            id=f"{offer.id}:buy_now",
            need_id=need.id,
            quantity=need.quantity,
            offer=offer,
            action=ActionKind.BUY_NOW,
            timing_mode=mode,
            price_signal=price,
            failure_risk=risk,
            lptb=lptb,
            objective_cost_cents=offer.price_cents,
            explanation="Buy now remains feasible for this offer.",
        )
        if mode is TimingMode.ORANGE:
            return (buy_now,)
        wait = CandidateAction(
            id=f"{offer.id}:wait",
            need_id=need.id,
            quantity=need.quantity,
            offer=offer,
            action=ActionKind.WAIT,
            timing_mode=mode,
            price_signal=price,
            failure_risk=risk,
            lptb=lptb,
            objective_cost_cents=price.expected_price_cents,
            explanation="Waiting is safe until the calculated latest point to buy.",
        )
        return (buy_now, wait)


class PostSolveValidator:
    """Independently validates an adapter result before it reaches checkout."""

    def validate(
        self, state: PlanState, actions: tuple[CandidateAction, ...]
    ) -> tuple[str, ...]:
        issues: list[str] = []
        selected_need_ids = {action.need_id for action in actions}
        missing = [
            need.id
            for need in state.needs
            if need.must and need.id not in selected_need_ids
        ]
        if missing:
            issues.append(f"Missing mandatory needs: {', '.join(sorted(missing))}")
        if len(selected_need_ids) != len(actions):
            issues.append("More than one action was selected for a need")
        merchants = {action.offer.merchant_id for action in actions}
        if len(merchants) > 1:
            issues.append("Selected actions violate single_merchant_checkout")
        total = sum(action.objective_cost_cents * action.quantity for action in actions)
        if total > state.budget_cents:
            issues.append("Selected actions exceed the mission budget")
        for action in actions:
            if action.offer.stock <= 0 or not action.offer.available:
                issues.append(f"Selected offer {action.offer.product_id} is unavailable")
            if action.action is ActionKind.WAIT and action.lptb is None:
                issues.append(f"WAIT action for {action.need_id} has no LPTB")
        return tuple(issues)
