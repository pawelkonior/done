"""Use case that turns a mission contract and market snapshot into a decision."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
import sqlite3
from uuid import uuid4

from app.domain.portfolio.enums import PortfolioDecisionStatus, PortfolioTrigger
from app.domain.portfolio.model import (
    CandidateAction,
    MarketSnapshot,
    PlanState,
    PortfolioDecision,
)
from app.domain.portfolio.policies import PostSolveValidator, TimingGate
from app.infrastructure.forecasting.heuristic_price_forecaster import HeuristicPriceForecaster
from app.infrastructure.optimization.ortools_cp_sat_optimizer import OrToolsCpSatOptimizer
from app.infrastructure.persistence.portfolio_repository import PortfolioRepository
from app.infrastructure.risk.heuristic_failure_risk import HeuristicFailureRiskModel
from app.infrastructure.risk.lptb import LPTBCalculator


class PortfolioPlanningService:
    """Deterministic application service; it never invokes an LLM."""

    def __init__(
        self,
        *,
        repository: PortfolioRepository | None = None,
        price_forecaster: HeuristicPriceForecaster | None = None,
        failure_risk: HeuristicFailureRiskModel | None = None,
        lptb: LPTBCalculator | None = None,
        timing_gate: TimingGate | None = None,
        optimizer: OrToolsCpSatOptimizer | None = None,
        post_validator: PostSolveValidator | None = None,
    ) -> None:
        self.repository = repository or PortfolioRepository()
        self.price_forecaster = price_forecaster or HeuristicPriceForecaster()
        self.failure_risk = failure_risk or HeuristicFailureRiskModel()
        self.lptb = lptb or LPTBCalculator()
        self.timing_gate = timing_gate or TimingGate()
        self.optimizer = optimizer or OrToolsCpSatOptimizer()
        self.post_validator = post_validator or PostSolveValidator()

    def run(
        self,
        connection: sqlite3.Connection,
        *,
        mission_id: str,
        trigger: PortfolioTrigger,
        preferred_merchants: tuple[str, ...] = (),
        now: datetime | None = None,
    ) -> PortfolioDecision:
        now = now or datetime.now(UTC)
        state = self.repository.get_or_create_plan_state(connection, mission_id)
        snapshot = self.repository.capture_market_snapshot(
            connection, mission_id=mission_id, now=now
        )
        idempotency_key = sha256(
            f"{mission_id}:{state.contract_version}:{snapshot.id}:{trigger.value}".encode()
        ).hexdigest()
        existing = self.repository.decision_for_idempotency_key(connection, idempotency_key)
        if existing is not None:
            return existing
        actions = self._build_actions(connection, state, snapshot, now)
        solver_result = self.optimizer.optimize(
            state, actions, preferred_merchants=preferred_merchants
        )
        status = solver_result.status
        constraint_report = solver_result.diagnostics
        selected = solver_result.selected_actions
        if status in {PortfolioDecisionStatus.FEASIBLE, PortfolioDecisionStatus.WAITING}:
            validation_issues = self.post_validator.validate(state, selected)
            if validation_issues:
                status = PortfolioDecisionStatus.INTERNAL_VALIDATION_ERROR
                constraint_report = validation_issues
                selected = ()

        explanations = self._explanations(selected, constraint_report)
        decision = PortfolioDecision(
            id=f"pde_{uuid4().hex}",
            mission_id=mission_id,
            plan_state_id=state.id,
            snapshot_id=snapshot.id,
            trigger=trigger,
            idempotency_key=idempotency_key,
            status=status,
            selected_actions=selected,
            selected_merchant_id=(solver_result.selected_merchant_id if selected else None),
            total_cents=(solver_result.total_cents if selected else 0),
            currency=state.currency,
            constraint_report=constraint_report,
            explanations=explanations,
            solver_metadata={
                "solver": "ortools_cp_sat",
                "single_merchant_checkout": True,
                "contract_version": state.contract_version,
                "catalog_hash": snapshot.catalog_hash,
                "actions_considered": len(actions),
            },
            created_at=now,
        )
        self.repository.persist_decision(
            connection,
            decision,
            considered_actions=actions,
            wall_time_ms=solver_result.wall_time_ms,
            diagnostics=solver_result.diagnostics,
        )
        return decision

    def _build_actions(
        self,
        connection: sqlite3.Connection,
        state: PlanState,
        snapshot: MarketSnapshot,
        now: datetime,
    ) -> tuple[CandidateAction, ...]:
        requires_nut_free = any(
            str(constraint.get("type", "")).casefold() == "allergen"
            and str(constraint.get("value", "")).casefold() == "nuts"
            for constraint in state.hard_constraints
            if isinstance(constraint, dict)
        )
        actions: list[CandidateAction] = []
        for need in state.needs:
            for offer in snapshot.offers:
                if (
                    offer.category != need.category
                    or offer.stock < need.quantity
                    or not offer.available
                ):
                    continue
                if now + timedelta(days=offer.p95_delivery_days) > state.deadline:
                    continue
                if requires_nut_free and not offer.nut_free:
                    continue
                if not set(need.required_tags).issubset(set(offer.tags)):
                    continue
                history = self.repository.price_history(connection, offer.product_id)
                price = self.price_forecaster.forecast(offer, history)
                risk = self.failure_risk.estimate(offer)
                lptb = self.lptb.calculate(offer, state.deadline.date())
                actions.extend(
                    self.timing_gate.build_actions(
                        need=need,
                        offer=offer,
                        price=price,
                        risk=risk,
                        lptb=lptb,
                        today=now.date(),
                    )
                )
        return tuple(actions)

    @staticmethod
    def _explanations(
        selected: tuple[CandidateAction, ...], diagnostics: tuple[str, ...]
    ) -> tuple[str, ...]:
        if diagnostics:
            return diagnostics
        messages = []
        for action in selected:
            if action.timing_mode.value == "orange":
                assert action.lptb is not None
                messages.append(
                    f"{action.need_id}: buy now because its latest point to buy is "
                    f"{action.lptb.lptb.isoformat()}."
                )
            elif action.action.value == "wait":
                assert action.lptb is not None
                messages.append(
                    f"{action.need_id}: waiting is safe until {action.lptb.lptb.isoformat()}."
                )
        return tuple(messages or ["The selected portfolio satisfies all hard constraints."])
