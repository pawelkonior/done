from __future__ import annotations

from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.common import DomainError, Money
from app.domain.mission.funding import (
    FundingContext,
    FundingDeniedError,
    FundingGate,
    FundingViolationCode,
    GuardrailAttestation,
    PlanFingerprint,
    ReservationSnapshot,
    UserApproval,
    VirtualCardSpec,
)


NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)


def plan(
    *,
    plan_hash: str = "sha256:final-plan",
    merchant_id: str = "merchant_1",
    total: Money = Money(50_000, "PLN"),
) -> PlanFingerprint:
    return PlanFingerprint(
        mission_id="mission_1",
        plan_hash=plan_hash,
        merchant_id=merchant_id,
        all_in_total=total,
    )


def valid_context() -> FundingContext:
    checkout = plan()
    return FundingContext(
        checkout=checkout,
        budget=Money(50_000, "PLN"),
        guardrails=GuardrailAttestation(
            plan=checkout,
            passed=True,
            attested_at=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(minutes=10),
        ),
        approval=UserApproval(
            plan=checkout,
            approved=True,
            approved_amount=Money(50_000, "PLN"),
            approved_at=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(minutes=10),
        ),
        reservation=ReservationSnapshot(
            plan=checkout,
            valid=True,
            reserved_at=NOW - timedelta(seconds=30),
            expires_at=NOW + timedelta(minutes=3),
        ),
        idempotency_key="fund:mission_1:sha256-final-plan",
    )


def codes(context: FundingContext) -> set[FundingViolationCode]:
    return {violation.code for violation in FundingGate().evaluate(context, now=NOW).violations}


def test_gate_creates_an_exact_restricted_short_lived_card_spec() -> None:
    decision = FundingGate().evaluate(valid_context(), now=NOW)

    assert decision.approved is True
    assert decision.allowed is True
    assert decision.violations == ()
    assert decision.card_spec == VirtualCardSpec(
        mission_id="mission_1",
        plan_hash="sha256:final-plan",
        max_amount=Money(50_000, "PLN"),
        merchant_lock="merchant_1",
        currency="PLN",
        single_use=True,
        no_cash=True,
        no_recurring=True,
        issued_at=NOW,
        # A card cannot outlive the earliest piece of funding evidence.
        expires_at=NOW + timedelta(minutes=3),
        idempotency_key="fund:mission_1:sha256-final-plan",
    )


def test_require_fails_closed_with_typed_plan_hash_violation() -> None:
    context = valid_context()
    changed = plan(plan_hash="sha256:changed-plan")
    context = replace(context, checkout=changed)

    decision = FundingGate().evaluate(context, now=NOW)
    assert decision.approved is False
    assert decision.card_spec is None
    assert FundingViolationCode.PLAN_HASH_MISMATCH in {
        violation.code for violation in decision.violations
    }

    with pytest.raises(FundingDeniedError) as error:
        FundingGate().require(context, now=NOW)
    assert FundingViolationCode.PLAN_HASH_MISMATCH in error.value.codes


def test_every_plan_hash_must_be_nonempty() -> None:
    context = valid_context()
    blank = plan(plan_hash="  ")
    context = replace(
        context,
        checkout=blank,
        guardrails=replace(context.guardrails, plan=blank),  # type: ignore[arg-type]
        approval=replace(context.approval, plan=blank),  # type: ignore[arg-type]
        reservation=replace(context.reservation, plan=blank),  # type: ignore[arg-type]
    )
    assert FundingViolationCode.PLAN_HASH_MISSING in codes(context)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (
            lambda context: replace(
                context,
                guardrails=replace(context.guardrails, passed=False),  # type: ignore[arg-type]
            ),
            FundingViolationCode.GUARDRAILS_NOT_PASSED,
        ),
        (
            lambda context: replace(
                context,
                guardrails=GuardrailAttestation(
                    plan=context.checkout,  # type: ignore[arg-type]
                    passed=True,
                    attested_at=NOW - timedelta(minutes=2),
                    expires_at=NOW,
                ),
            ),
            FundingViolationCode.GUARDRAILS_EXPIRED,
        ),
        (
            lambda context: replace(
                context,
                approval=replace(context.approval, approved=False),  # type: ignore[arg-type]
            ),
            FundingViolationCode.APPROVAL_NOT_GRANTED,
        ),
        (
            lambda context: replace(
                context,
                approval=UserApproval(
                    plan=context.checkout,  # type: ignore[arg-type]
                    approved=True,
                    approved_amount=Money(50_000, "PLN"),
                    approved_at=NOW - timedelta(minutes=2),
                    expires_at=NOW,
                ),
            ),
            FundingViolationCode.APPROVAL_EXPIRED,
        ),
        (
            lambda context: replace(
                context,
                reservation=replace(context.reservation, valid=False),  # type: ignore[arg-type]
            ),
            FundingViolationCode.RESERVATION_INVALID,
        ),
        (
            lambda context: replace(
                context,
                reservation=ReservationSnapshot(
                    plan=context.checkout,  # type: ignore[arg-type]
                    valid=True,
                    reserved_at=NOW - timedelta(minutes=2),
                    expires_at=NOW,
                ),
            ),
            FundingViolationCode.RESERVATION_EXPIRED,
        ),
        (
            lambda context: replace(context, unresolved_actions=("action_1",)),
            FundingViolationCode.UNRESOLVED_ACTIONS,
        ),
    ],
)
def test_gate_requires_live_evidence_and_no_open_actions(mutation, expected) -> None:
    context = mutation(valid_context())
    assert expected in codes(context)


def test_total_must_fit_both_the_approval_and_budget() -> None:
    context = valid_context()
    context = replace(
        context,
        budget=Money(49_999, "PLN"),
        approval=replace(
            context.approval,  # type: ignore[arg-type]
            approved_amount=Money(49_998, "PLN"),
        ),
    )
    assert {
        FundingViolationCode.BUDGET_EXCEEDED,
        FundingViolationCode.APPROVED_AMOUNT_EXCEEDED,
    }.issubset(codes(context))


def test_plan_merchant_currency_and_total_are_bound_at_every_gate() -> None:
    context = valid_context()
    other = plan(merchant_id="merchant_2", total=Money(40_000, "EUR"))
    context = replace(
        context,
        reservation=replace(context.reservation, plan=other),  # type: ignore[arg-type]
    )
    assert {
        FundingViolationCode.MERCHANT_MISMATCH,
        FundingViolationCode.CURRENCY_MISMATCH,
    }.issubset(codes(context))


def test_zero_total_and_missing_idempotency_key_never_fund() -> None:
    context = valid_context()
    zero = plan(total=Money(0, "PLN"))
    context = replace(
        context,
        checkout=zero,
        guardrails=replace(context.guardrails, plan=zero),  # type: ignore[arg-type]
        approval=replace(context.approval, plan=zero),  # type: ignore[arg-type]
        reservation=replace(context.reservation, plan=zero),  # type: ignore[arg-type]
        idempotency_key="",
    )
    assert {
        FundingViolationCode.FINAL_TOTAL_NOT_POSITIVE,
        FundingViolationCode.IDEMPOTENCY_KEY_MISSING,
    }.issubset(codes(context))


def test_funding_timestamps_must_be_timezone_aware() -> None:
    with pytest.raises(DomainError, match="timezone"):
        GuardrailAttestation(
            plan=plan(),
            passed=True,
            attested_at=datetime(2026, 7, 11, 12, 0),
            expires_at=datetime(2026, 7, 11, 12, 5),
        )


def test_virtual_card_model_has_no_raw_card_secrets() -> None:
    field_names = {field.name.casefold() for field in fields(VirtualCardSpec)}
    assert "pan" not in field_names
    assert "cvv" not in field_names
    assert "cvc" not in field_names
