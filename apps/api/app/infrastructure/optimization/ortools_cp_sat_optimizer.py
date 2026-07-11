"""CP-SAT adapter for the single-merchant checkout portfolio model."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

try:  # The declared runtime dependency is preferred whenever it is available.
    from ortools.sat.python import cp_model
except ModuleNotFoundError:  # pragma: no cover - exercised only in constrained dev environments.
    cp_model = None  # type: ignore[assignment]

from app.domain.portfolio.enums import (
    ActionKind,
    PortfolioDecisionStatus,
    PriceSignalKind,
)
from app.domain.portfolio.model import CandidateAction, PlanState


@dataclass(frozen=True, slots=True)
class SolverResult:
    status: PortfolioDecisionStatus
    selected_actions: tuple[CandidateAction, ...] = ()
    selected_merchant_id: str | None = None
    total_cents: int = 0
    diagnostics: tuple[str, ...] = ()
    wall_time_ms: int = 0


class OrToolsCpSatOptimizer:
    """Selects exactly one permitted action per need with a single merchant."""

    def __init__(
        self, *, max_time_seconds: float = 1.0, delivery_cost_cents: int = 1299
    ) -> None:
        self.max_time_seconds = max_time_seconds
        self.delivery_cost_cents = delivery_cost_cents

    def optimize(
        self,
        state: PlanState,
        actions: tuple[CandidateAction, ...],
        *,
        preferred_merchants: tuple[str, ...] = (),
    ) -> SolverResult:
        started = perf_counter()
        actions_by_need = {
            need.id: tuple(action for action in actions if action.need_id == need.id)
            for need in state.needs
        }
        missing = [need_id for need_id, candidates in actions_by_need.items() if not candidates]
        if missing:
            return SolverResult(
                status=PortfolioDecisionStatus.INFEASIBLE_PLAN,
                diagnostics=(f"No eligible offers for mandatory needs: {', '.join(missing)}",),
            )
        if cp_model is None:
            return self._fallback(
                state,
                actions_by_need,
                preferred_merchants,
                self.delivery_cost_cents,
                started,
            )

        model = cp_model.CpModel()
        variables = [model.NewBoolVar(f"action_{index}") for index in range(len(actions))]
        action_index = {action.id: index for index, action in enumerate(actions)}
        for need in state.needs:
            candidates = actions_by_need[need.id]
            model.Add(sum(variables[action_index[action.id]] for action in candidates) == 1)

        merchant_ids = sorted({action.offer.merchant_id for action in actions})
        merchant_vars = {
            merchant_id: model.NewBoolVar(f"merchant_{merchant_id}") for merchant_id in merchant_ids
        }
        model.Add(sum(merchant_vars.values()) == 1)
        for action, variable in zip(actions, variables, strict=True):
            model.Add(variable <= merchant_vars[action.offer.merchant_id])

        total_cost = sum(
            variable * action.objective_cost_cents * action.quantity
            for action, variable in zip(actions, variables, strict=True)
        )
        model.Add(total_cost + self.delivery_cost_cents <= state.budget_cents)

        objective_terms = []
        for action, variable in zip(actions, variables, strict=True):
            risk_penalty = round(action.failure_risk.probability * 800)
            quality_credit = round(action.offer.rating * 20)
            wait_adjustment = 0
            if action.action is ActionKind.WAIT:
                wait_adjustment = (
                    -250
                    if action.price_signal.kind is PriceSignalKind.WAIT_PREFERRED
                    else 500
                )
            merchant_adjustment = -80 if action.offer.merchant_id in preferred_merchants else 0
            objective_terms.append(
                variable
                * (
                    action.objective_cost_cents * action.quantity
                    + risk_penalty
                    - quality_credit
                    + wait_adjustment
                    + merchant_adjustment
                )
            )
        model.Minimize(sum(objective_terms))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.max_time_seconds
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = 0
        status = solver.Solve(model)
        wall_time_ms = round((perf_counter() - started) * 1000)
        if status not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
            diagnostics = self._diagnose(state, actions_by_need)
            return SolverResult(
                status=PortfolioDecisionStatus.INFEASIBLE_PLAN,
                diagnostics=diagnostics,
                wall_time_ms=wall_time_ms,
            )

        selected = tuple(
            action
            for action, variable in zip(actions, variables, strict=True)
            if solver.Value(variable)
        )
        merchants = {action.offer.merchant_id for action in selected}
        assert len(merchants) == 1
        return SolverResult(
            status=(
                PortfolioDecisionStatus.WAITING
                if any(action.action is ActionKind.WAIT for action in selected)
                else PortfolioDecisionStatus.FEASIBLE
            ),
            selected_actions=selected,
            selected_merchant_id=next(iter(merchants)),
            total_cents=(
                sum(action.objective_cost_cents * action.quantity for action in selected)
                + self.delivery_cost_cents
            ),
            wall_time_ms=wall_time_ms,
        )

    @staticmethod
    def _fallback(
        state: PlanState,
        actions_by_need: dict[str, tuple[CandidateAction, ...]],
        preferred_merchants: tuple[str, ...],
        delivery_cost_cents: int,
        started: float,
    ) -> SolverResult:
        """Bounded local fallback used only when the declared solver is unavailable.

        It evaluates one best action per need for every merchant.  The product
        catalog is deliberately capped in the demo; production uses CP-SAT.
        """

        merchant_ids = sorted(
            {action.offer.merchant_id for candidates in actions_by_need.values() for action in candidates}
        )
        candidates: list[tuple[int, tuple[CandidateAction, ...], str]] = []
        for merchant_id in merchant_ids:
            selected: list[CandidateAction] = []
            for need in state.needs:
                for_merchant = [
                    action
                    for action in actions_by_need[need.id]
                    if action.offer.merchant_id == merchant_id
                ]
                if not for_merchant:
                    selected = []
                    break
                selected.append(
                    min(
                        for_merchant,
                        key=lambda action: OrToolsCpSatOptimizer._fallback_score(
                            action, preferred_merchants
                        ),
                    )
                )
            total = sum(action.objective_cost_cents * action.quantity for action in selected)
            if selected and total + delivery_cost_cents <= state.budget_cents:
                candidates.append((total, tuple(selected), merchant_id))
        wall_time_ms = round((perf_counter() - started) * 1000)
        if not candidates:
            return SolverResult(
                status=PortfolioDecisionStatus.INFEASIBLE_PLAN,
                diagnostics=OrToolsCpSatOptimizer._diagnose(state, actions_by_need),
                wall_time_ms=wall_time_ms,
            )
        total, selected, merchant_id = min(
            candidates,
            key=lambda item: sum(
                OrToolsCpSatOptimizer._fallback_score(action, preferred_merchants)
                for action in item[1]
            ),
        )
        return SolverResult(
            status=(
                PortfolioDecisionStatus.WAITING
                if any(action.action is ActionKind.WAIT for action in selected)
                else PortfolioDecisionStatus.FEASIBLE
            ),
            selected_actions=selected,
            selected_merchant_id=merchant_id,
            total_cents=total + delivery_cost_cents,
            wall_time_ms=wall_time_ms,
        )

    @staticmethod
    def _fallback_score(
        action: CandidateAction, preferred_merchants: tuple[str, ...]
    ) -> int:
        risk_penalty = round(action.failure_risk.probability * 800)
        quality_credit = round(action.offer.rating * 20)
        wait_adjustment = (
            -250
            if action.action is ActionKind.WAIT
            and action.price_signal.kind is PriceSignalKind.WAIT_PREFERRED
            else 500 if action.action is ActionKind.WAIT else 0
        )
        merchant_adjustment = -80 if action.offer.merchant_id in preferred_merchants else 0
        return (
            action.objective_cost_cents * action.quantity
            + risk_penalty
            - quality_credit
            + wait_adjustment
            + merchant_adjustment
        )

    @staticmethod
    def _diagnose(
        state: PlanState, actions_by_need: dict[str, tuple[CandidateAction, ...]]
    ) -> tuple[str, ...]:
        minimum_total = sum(
            min(action.objective_cost_cents * action.quantity for action in actions_by_need[need.id])
            for need in state.needs
            if actions_by_need[need.id]
        )
        diagnostics = ["No portfolio satisfies all hard constraints."]
        if minimum_total > state.budget_cents:
            diagnostics.append(
                f"Lowest available candidate total ({minimum_total}) exceeds budget ({state.budget_cents})."
            )
        merchants_by_need = [
            {action.offer.merchant_id for action in actions_by_need[need.id]}
            for need in state.needs
        ]
        if merchants_by_need and not set.intersection(*merchants_by_need):
            diagnostics.append("No single merchant can cover every mandatory need.")
        return tuple(diagnostics)
