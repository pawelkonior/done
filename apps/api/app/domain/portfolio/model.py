"""Immutable inputs, signals and outputs of a portfolio decision run."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from .enums import (
    ActionKind,
    PortfolioDecisionStatus,
    PortfolioTrigger,
    PriceSignalKind,
    TimingMode,
)


@dataclass(frozen=True, slots=True)
class NeedSpec:
    id: str
    category: str
    quantity: int
    required_tags: tuple[str, ...] = ()
    must: bool = True

    def __post_init__(self) -> None:
        if not self.id or not self.category:
            raise ValueError("Need id and category are required")
        if self.quantity <= 0:
            raise ValueError("Need quantity must be positive")


@dataclass(frozen=True, slots=True)
class PlanState:
    id: str
    mission_id: str
    contract_version: int
    needs: tuple[NeedSpec, ...]
    budget_cents: int
    currency: str
    deadline: datetime
    approval_policy: str
    hard_constraints: tuple[dict[str, object], ...] = ()
    soft_preferences: tuple[dict[str, object], ...] = ()

    def __post_init__(self) -> None:
        if not self.mission_id or not self.id:
            raise ValueError("Plan state and mission ids are required")
        if self.contract_version <= 0:
            raise ValueError("Contract version must be positive")
        if self.budget_cents < 0:
            raise ValueError("Budget cannot be negative")
        if not self.needs:
            raise ValueError("Plan state must contain at least one need")
        if self.deadline.tzinfo is None:
            raise ValueError("Plan deadline must be timezone-aware")


@dataclass(frozen=True, slots=True)
class CandidateOffer:
    id: str
    snapshot_id: str
    product_id: str
    merchant_id: str
    category: str
    price_cents: int
    currency: str
    stock: int
    rating: float
    merchant_reliability: float
    delivery_success_rate: float
    p95_delivery_days: int
    tags: tuple[str, ...] = ()
    nut_free: bool = False
    available: bool = True

    def __post_init__(self) -> None:
        if self.price_cents < 0 or self.stock < 0:
            raise ValueError("Offer price and stock cannot be negative")
        if self.p95_delivery_days < 0:
            raise ValueError("Delivery days cannot be negative")


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    id: str
    mission_id: str
    captured_at: datetime
    freshness_deadline: datetime
    catalog_hash: str
    offers: tuple[CandidateOffer, ...]

    def __post_init__(self) -> None:
        if self.captured_at.tzinfo is None or self.freshness_deadline.tzinfo is None:
            raise ValueError("Snapshot times must be timezone-aware")
        if self.freshness_deadline < self.captured_at:
            raise ValueError("Snapshot freshness deadline cannot precede capture")


@dataclass(frozen=True, slots=True)
class PriceSignal:
    kind: PriceSignalKind
    expected_price_cents: int
    lower_cents: int
    upper_cents: int
    confidence: float
    reason: str

    def __post_init__(self) -> None:
        if min(self.expected_price_cents, self.lower_cents, self.upper_cents) < 0:
            raise ValueError("Price signal values cannot be negative")
        if self.lower_cents > self.upper_cents:
            raise ValueError("Price interval is invalid")
        if not 0 <= self.confidence <= 1:
            raise ValueError("Price signal confidence must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class FailureRiskSignal:
    probability: float
    reason: str

    def __post_init__(self) -> None:
        if not 0 <= self.probability <= 1:
            raise ValueError("Failure probability must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class LPTBSignal:
    lptb: date
    p95_delivery_days: int
    safety_buffer_days: int
    reason: str

    def __post_init__(self) -> None:
        if self.p95_delivery_days < 0 or self.safety_buffer_days < 0:
            raise ValueError("LPTB inputs cannot be negative")


@dataclass(frozen=True, slots=True)
class CandidateAction:
    id: str
    need_id: str
    quantity: int
    offer: CandidateOffer
    action: ActionKind
    timing_mode: TimingMode
    price_signal: PriceSignal
    failure_risk: FailureRiskSignal
    lptb: LPTBSignal | None
    objective_cost_cents: int
    explanation: str

    def __post_init__(self) -> None:
        if self.objective_cost_cents < 0:
            raise ValueError("Objective cost cannot be negative")
        if self.quantity <= 0:
            raise ValueError("Action quantity must be positive")
        if self.action is ActionKind.WAIT and self.lptb is None:
            raise ValueError("WAIT actions require an LPTB")


@dataclass(frozen=True, slots=True)
class PortfolioDecision:
    id: str
    mission_id: str
    plan_state_id: str
    snapshot_id: str
    trigger: PortfolioTrigger
    idempotency_key: str
    status: PortfolioDecisionStatus
    selected_actions: tuple[CandidateAction, ...] = ()
    selected_merchant_id: str | None = None
    total_cents: int = 0
    currency: str = "PLN"
    constraint_report: tuple[str, ...] = ()
    explanations: tuple[str, ...] = ()
    solver_metadata: dict[str, object] = field(default_factory=dict)
    execution_mode: str = "active"
    created_at: datetime | None = None

    @property
    def is_waiting(self) -> bool:
        return self.status is PortfolioDecisionStatus.WAITING

    @property
    def is_feasible(self) -> bool:
        return self.status in {
            PortfolioDecisionStatus.FEASIBLE,
            PortfolioDecisionStatus.WAITING,
        }
