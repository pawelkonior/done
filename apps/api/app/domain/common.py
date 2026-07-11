from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


class DomainError(ValueError):
    """Base class for violations of an invariant owned by the domain."""


class InvalidStateTransition(DomainError):
    pass


class PolicyViolationError(DomainError):
    pass


@dataclass(frozen=True, slots=True)
class Money:
    minor: int
    currency: str = "PLN"

    def __post_init__(self) -> None:
        if self.minor < 0:
            raise DomainError("Money cannot be negative")
        normalized = self.currency.upper().strip()
        if len(normalized) != 3:
            raise DomainError("Currency must be a three-letter ISO code")
        object.__setattr__(self, "currency", normalized)

    @classmethod
    def from_major(cls, value: int | float | str | Decimal, currency: str = "PLN") -> "Money":
        decimal_value = Decimal(str(value).replace(",", "."))
        minor = int((decimal_value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return cls(minor=minor, currency=currency)

    @property
    def major(self) -> Decimal:
        return Decimal(self.minor) / Decimal(100)

    def add(self, other: "Money") -> "Money":
        self._ensure_same_currency(other)
        return Money(self.minor + other.minor, self.currency)

    def subtract(self, other: "Money") -> "Money":
        self._ensure_same_currency(other)
        if other.minor > self.minor:
            raise DomainError("Money subtraction cannot produce a negative value")
        return Money(self.minor - other.minor, self.currency)

    def _ensure_same_currency(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise DomainError("Currencies must match")


@dataclass(frozen=True, slots=True)
class DomainEvent:
    type: str
    aggregate_id: str
    title: str
    description: str
    payload: dict[str, Any]
    occurred_at: datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def entity_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"

