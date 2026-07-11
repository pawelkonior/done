from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.domain.common import DomainError, DomainEvent, InvalidStateTransition, Money, utc_now


class MissionStatus(StrEnum):
    CREATED = "created"
    TRANSCRIBING = "transcribing"
    UNDERSTANDING = "understanding"
    CLARIFICATION_REQUIRED = "clarification_required"
    PLANNING = "planning"
    SEARCHING = "searching"
    OPTIMIZING = "optimizing"
    VALIDATING = "validating"
    APPROVAL_REQUIRED = "approval_required"
    EXECUTING = "executing"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {self.COMPLETED, self.FAILED, self.CANCELLED}


ALLOWED_TRANSITIONS: dict[MissionStatus, frozenset[MissionStatus]] = {
    MissionStatus.CREATED: frozenset({MissionStatus.TRANSCRIBING, MissionStatus.UNDERSTANDING}),
    MissionStatus.TRANSCRIBING: frozenset({MissionStatus.UNDERSTANDING, MissionStatus.FAILED}),
    MissionStatus.UNDERSTANDING: frozenset(
        {MissionStatus.CLARIFICATION_REQUIRED, MissionStatus.PLANNING, MissionStatus.FAILED}
    ),
    MissionStatus.CLARIFICATION_REQUIRED: frozenset(
        {MissionStatus.UNDERSTANDING, MissionStatus.CANCELLED}
    ),
    MissionStatus.PLANNING: frozenset({MissionStatus.SEARCHING, MissionStatus.FAILED}),
    MissionStatus.SEARCHING: frozenset({MissionStatus.OPTIMIZING, MissionStatus.FAILED}),
    MissionStatus.OPTIMIZING: frozenset({MissionStatus.VALIDATING, MissionStatus.FAILED}),
    MissionStatus.VALIDATING: frozenset(
        {
            MissionStatus.APPROVAL_REQUIRED,
            MissionStatus.EXECUTING,
            MissionStatus.RECOVERING,
            MissionStatus.FAILED,
        }
    ),
    MissionStatus.APPROVAL_REQUIRED: frozenset(
        {
            MissionStatus.PLANNING,
            MissionStatus.EXECUTING,
            MissionStatus.CANCELLED,
        }
    ),
    MissionStatus.EXECUTING: frozenset(
        {MissionStatus.RECOVERING, MissionStatus.COMPLETED, MissionStatus.FAILED}
    ),
    MissionStatus.RECOVERING: frozenset(
        {
            MissionStatus.VALIDATING,
            MissionStatus.EXECUTING,
            MissionStatus.COMPLETED,
            MissionStatus.APPROVAL_REQUIRED,
            MissionStatus.FAILED,
        }
    ),
    MissionStatus.COMPLETED: frozenset(),
    MissionStatus.FAILED: frozenset(),
    MissionStatus.CANCELLED: frozenset(),
}


class ConstraintKind(StrEnum):
    BUDGET = "budget"
    DEADLINE = "delivery_deadline"
    ALLERGEN = "allergen"
    PROHIBITED_CATEGORY = "prohibited_category"
    MATERIAL = "material"
    CUSTOM = "custom"


class FailureKind(StrEnum):
    PRODUCT_UNAVAILABLE = "product_unavailable"
    PRICE_CHANGED = "price_changed"
    DELIVERY_SLOT_LOST = "delivery_slot_lost"
    PAYMENT_SOFT_DECLINE = "payment_soft_decline"
    PAYMENT_HARD_DECLINE = "payment_hard_decline"
    MERCHANT_UNAVAILABLE = "merchant_unavailable"
    POLICY_VIOLATION = "policy_violation"


@dataclass(frozen=True, slots=True)
class Constraint:
    kind: ConstraintKind
    operator: str
    value: Any
    hard: bool = True

    def __post_init__(self) -> None:
        if not self.operator.strip():
            raise DomainError("Constraint operator cannot be empty")
        if self.value is None or self.value == "":
            raise DomainError("Constraint value cannot be empty")


@dataclass(frozen=True, slots=True)
class MissionContract:
    mission_id: str
    goal: str
    participants: int
    budget: Money
    deadline: datetime
    hard_constraints: tuple[Constraint, ...]
    soft_preferences: tuple[str, ...]
    approval_policy: str
    confidence: float
    version: int = 1

    def __post_init__(self) -> None:
        if not self.goal.strip():
            raise DomainError("Mission goal cannot be empty")
        if self.participants < 1:
            raise DomainError("Participants must be at least one")
        if not 0 <= self.confidence <= 1:
            raise DomainError("Confidence must be between zero and one")
        if self.version < 1:
            raise DomainError("Contract version must be positive")
        if self.deadline.tzinfo is None:
            raise DomainError("Mission deadline must include a timezone")

    def revise(
        self,
        *,
        budget: Money | None = None,
        deadline: datetime | None = None,
        hard_constraints: tuple[Constraint, ...] | None = None,
        soft_preferences: tuple[str, ...] | None = None,
    ) -> "MissionContract":
        return replace(
            self,
            budget=budget or self.budget,
            deadline=deadline or self.deadline,
            hard_constraints=hard_constraints or self.hard_constraints,
            soft_preferences=soft_preferences or self.soft_preferences,
            version=self.version + 1,
        )


@dataclass(slots=True)
class Mission:
    id: str
    user_id: str
    title: str
    status: MissionStatus
    current_step: int
    total_steps: int
    contract: MissionContract | None = None
    revision: int = 1
    events: list[DomainEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.id or not self.user_id:
            raise DomainError("Mission and user identifiers are required")
        if not 0 <= self.current_step <= self.total_steps:
            raise DomainError("Current step must be within mission bounds")

    def transition(self, target: MissionStatus, *, step: int, reason: str) -> DomainEvent:
        if target == self.status:
            raise InvalidStateTransition(f"Mission is already {target.value}")
        allowed = ALLOWED_TRANSITIONS.get(self.status, frozenset())
        if target not in allowed:
            raise InvalidStateTransition(
                f"Transition {self.status.value} -> {target.value} is not allowed"
            )
        if not 0 <= step <= self.total_steps:
            raise DomainError("Target step is outside mission bounds")
        previous = self.status
        self.status = target
        self.current_step = step
        self.revision += 1
        event = DomainEvent(
            type="mission.state_changed",
            aggregate_id=self.id,
            title=f"Mission {target.value.replace('_', ' ')}",
            description=reason,
            payload={"from": previous.value, "to": target.value, "step": step},
            occurred_at=utc_now(),
        )
        self.events.append(event)
        return event

    def revise_contract(self, contract: MissionContract) -> DomainEvent:
        if self.status.terminal:
            raise DomainError("A terminal mission cannot be revised")
        if contract.mission_id != self.id:
            raise DomainError("Contract belongs to another mission")
        if self.contract and contract.version != self.contract.version + 1:
            raise DomainError("Contract revisions must be sequential")
        self.contract = contract
        self.revision += 1
        event = DomainEvent(
            type="contract.revised",
            aggregate_id=self.id,
            title="Mission contract updated",
            description=f"Contract version {contract.version} is now active.",
            payload={"version": contract.version},
            occurred_at=utc_now(),
        )
        self.events.append(event)
        return event

