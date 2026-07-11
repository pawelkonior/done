from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.common import DomainError, InvalidStateTransition, Money
from app.domain.mission.model import (
    Constraint,
    ConstraintKind,
    Mission,
    MissionContract,
    MissionStatus,
)
from app.domain.mission.policies import (
    BasketLine,
    BasketPolicy,
    BasketSnapshot,
    MissionExecutionPolicy,
)
from app.domain.user.model import DeliveryAddress, PaymentMethod


def contract(*, budget: int = 30_000) -> MissionContract:
    deadline = datetime.now(UTC) + timedelta(days=1)
    return MissionContract(
        mission_id="mis_1",
        goal="Prepare a birthday party",
        participants=10,
        budget=Money(budget, "PLN"),
        deadline=deadline,
        hard_constraints=(
            Constraint(ConstraintKind.ALLERGEN, "exclude", "nuts"),
        ),
        soft_preferences=("single delivery",),
        approval_policy="always",
        confidence=0.97,
    )


def test_money_uses_minor_units_and_requires_one_currency() -> None:
    assert Money.from_major("200.72", "pln").minor == 20_072
    assert Money(100, "PLN").add(Money(250, "PLN")) == Money(350, "PLN")
    with pytest.raises(DomainError):
        Money(100, "PLN").add(Money(100, "EUR"))


def test_mission_aggregate_enforces_transitions_and_terminal_state() -> None:
    mission = Mission(
        id="mis_1",
        user_id="usr_1",
        title="Party",
        status=MissionStatus.CREATED,
        current_step=0,
        total_steps=6,
    )
    event = mission.transition(
        MissionStatus.UNDERSTANDING,
        step=1,
        reason="Voice transcript received",
    )
    assert event.payload["from"] == "created"
    assert mission.revision == 2
    with pytest.raises(InvalidStateTransition):
        mission.transition(MissionStatus.COMPLETED, step=6, reason="Skip everything")


def test_contract_revisions_are_immutable_and_sequential() -> None:
    first = contract()
    second = first.revise(budget=Money(35_000, "PLN"))
    assert first.version == 1
    assert first.budget == Money(30_000, "PLN")
    assert second.version == 2
    assert second.budget == Money(35_000, "PLN")


def test_policy_rejects_budget_allergen_and_deadline_violations() -> None:
    current_contract = contract(budget=10_00)
    basket = BasketSnapshot(
        lines=(
            BasketLine(
                product_id="unsafe-cake",
                category="cake",
                quantity=1,
                unit_price=Money(1_100, "PLN"),
                allergens=frozenset({"nuts"}),
                tags=frozenset(),
            ),
        ),
        delivery_cost=Money(100, "PLN"),
        delivery_at=current_contract.deadline + timedelta(hours=1),
    )
    decision = BasketPolicy().evaluate(current_contract, basket)
    assert decision.approved is False
    assert {violation.code for violation in decision.violations} == {
        "BUDGET_EXCEEDED",
        "DEADLINE_MISSED",
        "ALLERGEN_VIOLATION",
    }


def test_profile_value_objects_never_accept_raw_card_data() -> None:
    address = DeliveryAddress("Home", "Prosta 1", "Warsaw", "00-001")
    assert address.country == "PL"
    method = PaymentMethod("pm_demo_4242", "Visa", "4242", 12, 2030)
    assert method.is_demo is True
    with pytest.raises(DomainError):
        PaymentMethod("4242424242424242", "Visa", "4242", 12, 2030)


def test_execution_policy_enforces_threshold_and_high_risk_boundary() -> None:
    threshold = MissionExecutionPolicy(
        approval_mode="above_threshold",
        approval_threshold=Money(20_000, "PLN"),
    )
    assert threshold.requires_approval(Money(19_999, "PLN"), risk_level=1) is False
    assert threshold.requires_approval(Money(20_000, "PLN"), risk_level=1) is True

    autonomous = MissionExecutionPolicy(approval_mode="autonomous_low_risk")
    assert autonomous.requires_approval(Money(30_000, "PLN"), risk_level=42) is False
    assert autonomous.requires_approval(Money(30_000, "PLN"), risk_level=80) is True
