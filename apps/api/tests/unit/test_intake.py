from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.domain.common import DomainError, Money
from app.domain.mission.intake import Occasion, ShoppingScope, TranscriptInterpreter
from app.domain.mission.model import ConstraintKind


WARSAW = ZoneInfo("Europe/Warsaw")
NOW = datetime(2026, 7, 11, 13, 30, tzinfo=WARSAW)


def interpreter() -> TranscriptInterpreter:
    return TranscriptInterpreter(clock=lambda: NOW)


def test_polish_birthday_example_keeps_scope_and_delivery_time_unresolved() -> None:
    draft = interpreter().interpret(
        "Rzeczy na urodziny 10-latków, 5 osób, za tydzień, koszt max 500 zł"
    )

    assert draft.occasion == Occasion.BIRTHDAY
    assert draft.shopping_scope == ShoppingScope.AMBIGUOUS
    assert draft.recipient_age == 10
    assert draft.participants == 5
    assert draft.budget == Money.from_major(500, "PLN")
    assert draft.deadline_date == date(2026, 7, 18)
    assert draft.deadline_time is None
    assert draft.deadline is None
    assert draft.constraints == ()
    assert draft.missing_fields == ("shopping_scope", "deadline_time")
    assert "shopping_scope_not_explicit" in draft.ambiguities

    age_evidence = draft.evidence_for("recipient_age")[0]
    assert age_evidence.source_text == "10-latków"
    assert draft.transcript[age_evidence.start : age_evidence.end] == age_evidence.source_text


def test_common_voice_transcription_typo_does_not_change_participant_count() -> None:
    draft = interpreter().interpret(
        "rzeczy na urodziny 10 latkow, 5 oosb, za tydzien, koszt max 500zl"
    )

    assert draft.recipient_age == 10
    assert draft.participants == 5
    assert draft.budget == Money(50_000, "PLN")
    assert draft.deadline_date == date(2026, 7, 18)


def test_english_gift_request_with_explicit_time_is_ready_without_invented_constraints() -> None:
    draft = interpreter().interpret(
        "Buy gifts for five kids aged ten, in a week at 4:30 pm, budget 120 EUR"
    )

    assert draft.occasion == Occasion.GENERAL
    assert draft.shopping_scope == ShoppingScope.GIFTS
    assert draft.recipient_age == 10
    assert draft.participants == 5
    assert draft.budget == Money(12_000, "EUR")
    assert draft.deadline_date == date(2026, 7, 18)
    assert draft.deadline_time == time(16, 30)
    assert draft.deadline == datetime(2026, 7, 18, 16, 30, tzinfo=WARSAW)
    assert draft.constraints == ()
    assert draft.missing_fields == ()
    assert draft.ready_for_planning is True


def test_party_supplies_and_only_explicit_constraints_are_extracted() -> None:
    draft = interpreter().interpret(
        "Potrzebuję balonów i dekoracji na urodziny dla 8 dzieci jutro o 17, "
        "budżet 300 PLN, bez orzechów i bez plastiku"
    )

    assert draft.shopping_scope == ShoppingScope.PARTY_SUPPLIES
    assert draft.participants == 8
    assert draft.deadline == datetime(2026, 7, 12, 17, 0, tzinfo=WARSAW)
    assert {(item.kind, item.operator, item.value) for item in draft.constraints} == {
        (ConstraintKind.ALLERGEN, "exclude", "nuts"),
        (ConstraintKind.MATERIAL, "exclude", "plastic"),
    }


@pytest.mark.parametrize(
    ("phrase", "expected_date"),
    [
        ("today at 18:00", date(2026, 7, 11)),
        ("tomorrow at 18:00", date(2026, 7, 12)),
        ("day after tomorrow at 18:00", date(2026, 7, 13)),
        ("dzisiaj o 18:00", date(2026, 7, 11)),
        ("jutro o 18:00", date(2026, 7, 12)),
        ("pojutrze o 18:00", date(2026, 7, 13)),
    ],
)
def test_relative_deadlines_use_injected_local_clock(phrase: str, expected_date: date) -> None:
    draft = interpreter().interpret(f"Gifts for 2 kids {phrase}, budget 50 USD")

    assert draft.deadline_date == expected_date
    assert draft.deadline_time == time(18, 0)


def test_absent_critical_fields_are_reported_instead_of_defaulted() -> None:
    draft = interpreter().interpret("Kup mi coś fajnego")

    assert draft.shopping_scope == ShoppingScope.AMBIGUOUS
    assert draft.participants is None
    assert draft.budget is None
    assert draft.deadline_date is None
    assert draft.deadline_time is None
    assert draft.constraints == ()
    assert draft.missing_fields == (
        "shopping_scope",
        "participants",
        "budget",
        "deadline",
    )


def test_amount_without_currency_requests_currency_clarification() -> None:
    draft = interpreter().interpret("gifts for 2 kids tomorrow at 9, budget 200")

    assert draft.budget is None
    assert draft.evidence_for("budget_amount")[0].value == Decimal("200")
    assert "budget_currency" in draft.missing_fields
    assert "budget_currency_missing" in draft.ambiguities


def test_conflicting_critical_values_are_not_silently_selected() -> None:
    draft = interpreter().interpret(
        "gifts for 4 kids, actually 5 kids, tomorrow at 10, budget 100 EUR"
    )

    assert draft.participants is None
    assert "participants" in draft.missing_fields
    assert "participants_conflicting_values" in draft.ambiguities


def test_naive_clock_is_rejected() -> None:
    parser = TranscriptInterpreter(clock=lambda: datetime(2026, 7, 11, 12, 0))

    with pytest.raises(DomainError, match="timezone-aware"):
        parser.interpret("gifts for 2 kids tomorrow at 9, budget 50 EUR")
