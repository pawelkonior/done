from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from decimal import Decimal
from enum import StrEnum
from typing import Any

from app.domain.common import DomainError, Money
from app.domain.mission.model import Constraint, ConstraintKind


class Occasion(StrEnum):
    BIRTHDAY = "birthday"
    GENERAL = "general"


class ShoppingScope(StrEnum):
    GIFTS = "gifts"
    PARTY_SUPPLIES = "party_supplies"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class IntentFieldEvidence:
    """A transcript fragment that supports one interpreted field.

    Offsets point to the original transcript, not its normalized copy.  They
    make the result suitable for audit logs and for highlighting what the app
    understood during a voice clarification.
    """

    field: str
    value: Any
    source_text: str
    start: int
    end: int
    rule: str
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not self.field:
            raise DomainError("Evidence field cannot be empty")
        if self.start < 0 or self.end < self.start:
            raise DomainError("Evidence span is invalid")
        if not 0 <= self.confidence <= 1:
            raise DomainError("Evidence confidence must be between zero and one")


@dataclass(frozen=True, slots=True)
class MissionDraft:
    transcript: str
    occasion: Occasion
    shopping_scope: ShoppingScope
    recipient_age: int | None
    participants: int | None
    budget: Money | None
    deadline_date: date | None
    deadline_time: time | None
    constraints: tuple[Constraint, ...]
    evidence: tuple[IntentFieldEvidence, ...]
    missing_fields: tuple[str, ...]
    ambiguities: tuple[str, ...]
    deadline_timezone: tzinfo

    @property
    def deadline(self) -> datetime | None:
        """Return an aware deadline only when both date and time were spoken."""

        if self.deadline_date is None or self.deadline_time is None:
            return None
        return datetime.combine(
            self.deadline_date,
            self.deadline_time,
            tzinfo=self.deadline_timezone,
        )

    @property
    def ready_for_planning(self) -> bool:
        return not self.missing_fields

    def evidence_for(self, field: str) -> tuple[IntentFieldEvidence, ...]:
        return tuple(item for item in self.evidence if item.field == field)


_POLISH_ASCII_TRANSLATION = str.maketrans(
    {
        "ą": "a",
        "ć": "c",
        "ę": "e",
        "ł": "l",
        "ń": "n",
        "ó": "o",
        "ś": "s",
        "ź": "z",
        "ż": "z",
    }
)


def _fold(value: str) -> str:
    # The explicit Polish translation is needed because ł has no canonical
    # Unicode decomposition.  Every replacement is one character long, so
    # regex offsets still address the original transcript.
    lowered = value.casefold().translate(_POLISH_ASCII_TRANSLATION)
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", lowered)
        if not unicodedata.combining(character)
    )


_NUMBER_WORDS = {
    # Polish cardinal forms commonly produced by speech-to-text.
    "jeden": 1,
    "jedna": 1,
    "jedno": 1,
    "dwa": 2,
    "dwie": 2,
    "dwoje": 2,
    "dwoch": 2,
    "trzy": 3,
    "troje": 3,
    "trzech": 3,
    "cztery": 4,
    "czworo": 4,
    "czterech": 4,
    "piec": 5,
    "pieciu": 5,
    "szesc": 6,
    "szesciu": 6,
    "siedem": 7,
    "siedmiu": 7,
    "osiem": 8,
    "osmiu": 8,
    "dziewiec": 9,
    "dziewieciu": 9,
    "dziesiec": 10,
    "dziesieciu": 10,
    "jedenascie": 11,
    "jedenastu": 11,
    "dwanascie": 12,
    "dwunastu": 12,
    "trzynascie": 13,
    "trzynastu": 13,
    "czternascie": 14,
    "czternastu": 14,
    "pietnascie": 15,
    "pietnastu": 15,
    "szesnascie": 16,
    "szesnastu": 16,
    "siedemnascie": 17,
    "siedemnastu": 17,
    "osiemnascie": 18,
    "osiemnastu": 18,
    "dziewietnascie": 19,
    "dziewietnastu": 19,
    "dwadziescia": 20,
    "dwudziestu": 20,
    # English.
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}
_NUMBER_WORD_PATTERN = "|".join(
    re.escape(word) for word in sorted(_NUMBER_WORDS, key=len, reverse=True)
)
_NUMBER_PATTERN = rf"(?:\d{{1,3}}|{_NUMBER_WORD_PATTERN})"


def _number(value: str) -> int:
    return int(value) if value.isdigit() else _NUMBER_WORDS[value]


_BIRTHDAY_RE = re.compile(r"\b(?:urodzin\w*|birthday(?:s)?|b[ -]?day)\b")
_GIFT_RE = re.compile(r"\b(?:prezent\w*|upomink\w*|gift(?:s)?|present(?:s)?)\b")
_PARTY_SUPPLIES_RE = re.compile(
    r"\b(?:"
    r"dekoracj\w*|balon\w*|tort\w*|serwet\w*|swiecz\w*|naczyn\w*|"
    r"artykul\w*\s+imprezow\w*|wyposazen\w*\s+imprez\w*|"
    r"party\s+(?:supplies|decorations)|balloons?|cake|tableware"
    r")\b"
)
_PARTICIPANTS_RE = re.compile(
    rf"\b(?P<number>{_NUMBER_PATTERN})\s*"
    r"(?P<unit>osob(?:a|y)?|oosb|dzieci|dziecko|gosci|"
    r"kids?|children|people|persons?|guests?)\b"
)
_JOINT_RECIPIENT_RE = re.compile(
    rf"\b(?P<count>{_NUMBER_PATTERN})\s+(?P<age>{_NUMBER_PATTERN})\s*[- ]*"
    r"(?:latk(?:ow|i|a)?|year\s*[- ]*olds?)\b"
)
_AGE_RES = (
    re.compile(
        rf"\b(?P<age>{_NUMBER_PATTERN})\s*[- ]*"
        r"(?:latk(?:ow|i|a)?|letni\w*|year\s*[- ]*olds?|years?\s+old|y/?o)\b"
    ),
    re.compile(rf"\b(?:w\s+wieku|aged?|age)\s+(?P<age>{_NUMBER_PATTERN})(?:\s+lat)?\b"),
)

_RELATIVE_DATE_RE = re.compile(
    r"\b(?P<day_after>pojutrze|day\s+after\s+tomorrow)\b|"
    r"\b(?P<week>za\s+tydzien|in\s+(?:a|one|1)\s+week|a\s+week\s+from\s+today)\b|"
    r"\b(?P<tomorrow>jutro|tomorrow)\b|"
    r"\b(?P<today>dzisiaj|dzis|today)\b"
)
_CUED_TIME_RE = re.compile(
    r"\b(?:o|na|do|godz(?:ina|iny)?\.?|at|by)\s*"
    r"(?P<hour>[01]?\d|2[0-3])"
    r"(?:[:.](?P<minute>[0-5]\d))?\s*"
    r"(?P<ampm>a\.?m\.?|p\.?m\.?)?\b"
)
_COLON_TIME_RE = re.compile(
    r"(?<![\d.,])(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)(?!\d)"
)
_AMPM_TIME_RE = re.compile(
    r"(?<!\d)(?P<hour>0?[1-9]|1[0-2])"
    r"(?:[:.](?P<minute>[0-5]\d))?\s*(?P<ampm>a\.?m\.?|p\.?m\.?)\b"
)

_AMOUNT = r"(?P<amount>\d{1,7}(?:[.,]\d{1,2})?)"
_CURRENCY = (
    r"(?P<currency>pln|zl(?:ot(?:y|e|ych)?)?|eur|euro|€|usd|"
    r"dollars?|dol(?:ar(?:y|ow)?)?|\$|gbp|pounds?|funt(?:y|ow)?|£)"
)
_BUDGET_STRONG_RE = re.compile(
    rf"\b(?:budzet|budget|koszt|cost|limit|max(?:imum)?|maksymalnie|"
    rf"nie\s+wiecej\s+niz|not\s+more\s+than|up\s+to|under)\b"
    rf"(?:\s*(?:wynosi|is|of|to|na|:|max(?:imum)?|maksymalnie))*\s*"
    rf"{_AMOUNT}\s*{_CURRENCY}?"
)
_BUDGET_DO_RE = re.compile(rf"\bdo\s+{_AMOUNT}\s*{_CURRENCY}")
_BUDGET_TRAILING_RE = re.compile(
    rf"{_AMOUNT}\s*{_CURRENCY}\s*"
    r"(?:max(?:imum)?|maksymalnie|budget|budzet|limit)\b"
)

_CURRENCY_CODES = {
    "pln": "PLN",
    "zl": "PLN",
    "zloty": "PLN",
    "zlote": "PLN",
    "zlotych": "PLN",
    "eur": "EUR",
    "euro": "EUR",
    "€": "EUR",
    "usd": "USD",
    "dollar": "USD",
    "dollars": "USD",
    "dolar": "USD",
    "dolary": "USD",
    "dolarow": "USD",
    "$": "USD",
    "gbp": "GBP",
    "pound": "GBP",
    "pounds": "GBP",
    "funt": "GBP",
    "funty": "GBP",
    "funtow": "GBP",
    "£": "GBP",
}

_CONSTRAINT_RULES: tuple[tuple[str, Constraint, re.Pattern[str]], ...] = (
    (
        "explicit_nut_exclusion",
        Constraint(ConstraintKind.ALLERGEN, "exclude", "nuts"),
        re.compile(
            r"\b(?:bez\s+orzech\w*|nut[ -]?free|no\s+nuts?|"
            r"alergi\w*\s+na\s+orzech\w*|allergic\s+to\s+nuts?)\b"
        ),
    ),
    (
        "explicit_gluten_exclusion",
        Constraint(ConstraintKind.ALLERGEN, "exclude", "gluten"),
        re.compile(r"\b(?:bez\s+glutenu|gluten[ -]?free|no\s+gluten)\b"),
    ),
    (
        "explicit_lactose_exclusion",
        Constraint(ConstraintKind.ALLERGEN, "exclude", "lactose"),
        re.compile(r"\b(?:bez\s+laktozy|lactose[ -]?free|no\s+lactose)\b"),
    ),
    (
        "explicit_alcohol_exclusion",
        Constraint(ConstraintKind.PROHIBITED_CATEGORY, "exclude", "alcohol"),
        re.compile(r"\b(?:bez\s+alkoholu|alcohol[ -]?free|no\s+alcohol)\b"),
    ),
    (
        "explicit_plastic_exclusion",
        Constraint(ConstraintKind.MATERIAL, "exclude", "plastic"),
        re.compile(r"\b(?:bez\s+plastiku|plastic[ -]?free|no\s+plastic)\b"),
    ),
    (
        "explicit_vegan_preference",
        Constraint(ConstraintKind.CUSTOM, "require", "vegan"),
        re.compile(r"\b(?:wegansk\w*|vegan)\b"),
    ),
    (
        "explicit_vegetarian_preference",
        Constraint(ConstraintKind.CUSTOM, "require", "vegetarian"),
        re.compile(r"\b(?:wegetariansk\w*|vegetarian)\b"),
    ),
)


@dataclass(frozen=True, slots=True)
class _BudgetCandidate:
    amount: Decimal
    currency: str | None
    start: int
    end: int
    amount_start: int
    amount_end: int
    currency_start: int | None
    currency_end: int | None
    rule: str


class TranscriptInterpreter:
    """Deterministic PL/EN extraction for the voice mission intake.

    This component intentionally does not fill absent critical fields.  A
    caller can use ``missing_fields`` and ``ambiguities`` to drive the next
    voice question before constructing a ``MissionContract``.
    """

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))

    def __call__(self, transcript: str) -> MissionDraft:
        return self.interpret(transcript)

    def parse(self, transcript: str) -> MissionDraft:
        return self.interpret(transcript)

    def interpret(self, transcript: str) -> MissionDraft:
        if not isinstance(transcript, str) or not transcript.strip():
            raise DomainError("Transcript cannot be empty")

        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise DomainError("Transcript interpreter clock must be timezone-aware")

        normalized = _fold(transcript)
        evidence: list[IntentFieldEvidence] = []
        ambiguities: list[str] = []

        occasion = self._occasion(transcript, normalized, evidence)
        scope = self._scope(transcript, normalized, evidence, ambiguities)
        recipient_age = self._recipient_age(transcript, normalized, evidence, ambiguities)
        participants = self._participants(transcript, normalized, evidence, ambiguities)
        budget = self._budget(transcript, normalized, evidence, ambiguities)
        deadline_date = self._deadline_date(
            transcript,
            normalized,
            now,
            evidence,
            ambiguities,
        )
        deadline_time = self._deadline_time(transcript, normalized, evidence, ambiguities)
        constraints = self._constraints(transcript, normalized, evidence)

        missing_fields: list[str] = []
        if scope == ShoppingScope.AMBIGUOUS:
            missing_fields.append("shopping_scope")
        elif scope == ShoppingScope.GIFTS and recipient_age is None:
            # The connected gift catalog is age-banded. Asking is safer than
            # silently recommending a child/adult product from a birthday cue.
            missing_fields.append("recipient_age")
        if participants is None:
            missing_fields.append("participants")
        if budget is None:
            if "budget_currency_missing" in ambiguities:
                missing_fields.append("budget_currency")
            else:
                missing_fields.append("budget")
        if deadline_date is None:
            missing_fields.append("deadline")
        elif deadline_time is None:
            missing_fields.append("deadline_time")

        evidence.sort(key=lambda item: (item.start, item.end, item.field))
        return MissionDraft(
            transcript=transcript,
            occasion=occasion,
            shopping_scope=scope,
            recipient_age=recipient_age,
            participants=participants,
            budget=budget,
            deadline_date=deadline_date,
            deadline_time=deadline_time,
            constraints=constraints,
            evidence=tuple(evidence),
            missing_fields=tuple(missing_fields),
            ambiguities=tuple(dict.fromkeys(ambiguities)),
            deadline_timezone=now.tzinfo,
        )

    @staticmethod
    def _evidence(
        transcript: str,
        match: re.Match[str],
        *,
        field: str,
        value: Any,
        rule: str,
        group: str | int = 0,
    ) -> IntentFieldEvidence:
        start, end = match.span(group)
        return IntentFieldEvidence(
            field=field,
            value=value,
            source_text=transcript[start:end],
            start=start,
            end=end,
            rule=rule,
        )

    def _occasion(
        self,
        transcript: str,
        normalized: str,
        evidence: list[IntentFieldEvidence],
    ) -> Occasion:
        match = _BIRTHDAY_RE.search(normalized)
        if match is None:
            return Occasion.GENERAL
        evidence.append(
            self._evidence(
                transcript,
                match,
                field="occasion",
                value=Occasion.BIRTHDAY,
                rule="birthday_keyword",
            )
        )
        return Occasion.BIRTHDAY

    def _scope(
        self,
        transcript: str,
        normalized: str,
        evidence: list[IntentFieldEvidence],
        ambiguities: list[str],
    ) -> ShoppingScope:
        gift_matches = list(_GIFT_RE.finditer(normalized))
        supplies_matches = list(_PARTY_SUPPLIES_RE.finditer(normalized))
        for match in gift_matches:
            evidence.append(
                self._evidence(
                    transcript,
                    match,
                    field="shopping_scope",
                    value=ShoppingScope.GIFTS,
                    rule="gift_keyword",
                )
            )
        for match in supplies_matches:
            evidence.append(
                self._evidence(
                    transcript,
                    match,
                    field="shopping_scope",
                    value=ShoppingScope.PARTY_SUPPLIES,
                    rule="party_supplies_keyword",
                )
            )
        if gift_matches and not supplies_matches:
            return ShoppingScope.GIFTS
        if supplies_matches and not gift_matches:
            return ShoppingScope.PARTY_SUPPLIES
        if gift_matches and supplies_matches:
            ambiguities.append("shopping_scope_conflicting_signals")
        else:
            ambiguities.append("shopping_scope_not_explicit")
        return ShoppingScope.AMBIGUOUS

    def _recipient_age(
        self,
        transcript: str,
        normalized: str,
        evidence: list[IntentFieldEvidence],
        ambiguities: list[str],
    ) -> int | None:
        found: list[int] = []
        seen_spans: set[tuple[int, int]] = set()
        for pattern in _AGE_RES:
            for match in pattern.finditer(normalized):
                span = match.span("age")
                if span in seen_spans:
                    continue
                seen_spans.add(span)
                age = _number(match.group("age"))
                if not 0 < age <= 120:
                    continue
                found.append(age)
                evidence.append(
                    self._evidence(
                        transcript,
                        match,
                        field="recipient_age",
                        value=age,
                        rule="recipient_age_phrase",
                    )
                )
        values = set(found)
        if len(values) == 1:
            return next(iter(values))
        if len(values) > 1:
            ambiguities.append("recipient_age_conflicting_values")
        return None

    def _participants(
        self,
        transcript: str,
        normalized: str,
        evidence: list[IntentFieldEvidence],
        ambiguities: list[str],
    ) -> int | None:
        matches: list[tuple[int, re.Match[str], str]] = []
        for match in _PARTICIPANTS_RE.finditer(normalized):
            matches.append((_number(match.group("number")), match, "participant_count_phrase"))
        for match in _JOINT_RECIPIENT_RE.finditer(normalized):
            matches.append((_number(match.group("count")), match, "count_and_age_phrase"))

        values: set[int] = set()
        seen: set[tuple[int, int, int]] = set()
        for value, match, rule in matches:
            marker = (*match.span(), value)
            if marker in seen or value < 1:
                continue
            seen.add(marker)
            values.add(value)
            evidence.append(
                self._evidence(
                    transcript,
                    match,
                    field="participants",
                    value=value,
                    rule=rule,
                )
            )
        if len(values) == 1:
            return next(iter(values))
        if len(values) > 1:
            ambiguities.append("participants_conflicting_values")
        return None

    def _budget(
        self,
        transcript: str,
        normalized: str,
        evidence: list[IntentFieldEvidence],
        ambiguities: list[str],
    ) -> Money | None:
        candidates = self._budget_candidates(normalized)
        if not candidates:
            return None

        for candidate in candidates:
            evidence.append(
                IntentFieldEvidence(
                    field="budget_amount",
                    value=candidate.amount,
                    source_text=transcript[candidate.amount_start : candidate.amount_end],
                    start=candidate.amount_start,
                    end=candidate.amount_end,
                    rule=candidate.rule,
                )
            )
            if candidate.currency is not None:
                evidence.append(
                    IntentFieldEvidence(
                        field="budget_currency",
                        value=candidate.currency,
                        source_text=transcript[
                            candidate.currency_start : candidate.currency_end
                        ],
                        start=candidate.currency_start or 0,
                        end=candidate.currency_end or 0,
                        rule=candidate.rule,
                    )
                )

        values = {(candidate.amount, candidate.currency) for candidate in candidates}
        if len(values) > 1:
            ambiguities.append("budget_conflicting_values")
            return None
        amount, currency = next(iter(values))
        if currency is None:
            ambiguities.append("budget_currency_missing")
            return None
        return Money.from_major(amount, currency)

    @staticmethod
    def _budget_candidates(normalized: str) -> tuple[_BudgetCandidate, ...]:
        candidates: list[_BudgetCandidate] = []
        occupied: list[tuple[int, int]] = []
        patterns = (
            ("budget_keyword", _BUDGET_STRONG_RE),
            ("polish_budget_limit", _BUDGET_DO_RE),
            ("trailing_budget_keyword", _BUDGET_TRAILING_RE),
        )
        for rule, pattern in patterns:
            for match in pattern.finditer(normalized):
                start, end = match.span()
                overlaps = any(
                    start < other_end and other_start < end
                    for other_start, other_end in occupied
                )
                if overlaps:
                    continue
                raw_currency = match.groupdict().get("currency")
                currency = _CURRENCY_CODES.get(raw_currency) if raw_currency else None
                currency_start: int | None = None
                currency_end: int | None = None
                if raw_currency:
                    currency_start, currency_end = match.span("currency")
                amount_start, amount_end = match.span("amount")
                candidates.append(
                    _BudgetCandidate(
                        amount=Decimal(match.group("amount").replace(",", ".")),
                        currency=currency,
                        start=start,
                        end=end,
                        amount_start=amount_start,
                        amount_end=amount_end,
                        currency_start=currency_start,
                        currency_end=currency_end,
                        rule=rule,
                    )
                )
                occupied.append((start, end))
        return tuple(sorted(candidates, key=lambda candidate: candidate.start))

    def _deadline_date(
        self,
        transcript: str,
        normalized: str,
        now: datetime,
        evidence: list[IntentFieldEvidence],
        ambiguities: list[str],
    ) -> date | None:
        values: set[date] = set()
        for match in _RELATIVE_DATE_RE.finditer(normalized):
            if match.group("day_after"):
                days = 2
            elif match.group("week"):
                days = 7
            elif match.group("tomorrow"):
                days = 1
            else:
                days = 0
            value = now.date() + timedelta(days=days)
            values.add(value)
            evidence.append(
                self._evidence(
                    transcript,
                    match,
                    field="deadline_date",
                    value=value,
                    rule="relative_deadline",
                )
            )
        if len(values) == 1:
            return next(iter(values))
        if len(values) > 1:
            ambiguities.append("deadline_conflicting_dates")
        return None

    def _deadline_time(
        self,
        transcript: str,
        normalized: str,
        evidence: list[IntentFieldEvidence],
        ambiguities: list[str],
    ) -> time | None:
        candidates: list[tuple[time, re.Match[str], str]] = []
        occupied: list[tuple[int, int]] = []
        for rule, pattern in (
            ("cued_delivery_time", _CUED_TIME_RE),
            ("colon_delivery_time", _COLON_TIME_RE),
            ("ampm_delivery_time", _AMPM_TIME_RE),
        ):
            for match in pattern.finditer(normalized):
                start, end = match.span()
                overlaps = any(
                    start < other_end and other_start < end
                    for other_start, other_end in occupied
                )
                if overlaps:
                    continue
                hour = int(match.group("hour"))
                minute = int(match.groupdict().get("minute") or 0)
                ampm = (match.groupdict().get("ampm") or "").replace(".", "")
                if ampm:
                    if hour == 12:
                        hour = 0
                    if ampm == "pm":
                        hour += 12
                value = time(hour, minute)
                candidates.append((value, match, rule))
                occupied.append((start, end))

        values: set[time] = set()
        for value, match, rule in candidates:
            values.add(value)
            evidence.append(
                self._evidence(
                    transcript,
                    match,
                    field="deadline_time",
                    value=value,
                    rule=rule,
                )
            )
        if len(values) == 1:
            return next(iter(values))
        if len(values) > 1:
            ambiguities.append("deadline_time_conflicting_values")
        return None

    def _constraints(
        self,
        transcript: str,
        normalized: str,
        evidence: list[IntentFieldEvidence],
    ) -> tuple[Constraint, ...]:
        found: list[tuple[int, Constraint]] = []
        seen: set[Constraint] = set()
        for rule, constraint, pattern in _CONSTRAINT_RULES:
            for match in pattern.finditer(normalized):
                if constraint in seen:
                    continue
                seen.add(constraint)
                found.append((match.start(), constraint))
                evidence.append(
                    self._evidence(
                        transcript,
                        match,
                        field="constraints",
                        value=constraint,
                        rule=rule,
                    )
                )
        return tuple(constraint for _, constraint in sorted(found, key=lambda item: item[0]))


def interpret_transcript(
    transcript: str,
    *,
    clock: Callable[[], datetime] | None = None,
) -> MissionDraft:
    """Convenience entry point for callers that do not need a reusable parser."""

    return TranscriptInterpreter(clock=clock).interpret(transcript)


def critical_fields() -> Iterable[str]:
    """Stable field names a conversation layer can use when asking follow-ups."""

    return (
        "shopping_scope",
        "recipient_age",
        "participants",
        "budget",
        "deadline",
        "deadline_time",
    )


__all__ = [
    "IntentFieldEvidence",
    "MissionDraft",
    "Occasion",
    "ShoppingScope",
    "TranscriptInterpreter",
    "critical_fields",
    "interpret_transcript",
]
