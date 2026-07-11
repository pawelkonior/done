from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum

from app.domain.common import DomainError, Money


class ApprovalPolicy(StrEnum):
    ALWAYS = "always"
    ABOVE_THRESHOLD = "above_threshold"
    AUTONOMOUS_LOW_RISK = "autonomous_low_risk"


class ContactPreference(StrEnum):
    ONLY_WHEN_NEEDED = "only_when_needed"
    IMPORTANT_UPDATES = "important_updates"
    ALL_UPDATES = "all_updates"


@dataclass(frozen=True, slots=True)
class DeliveryAddress:
    label: str
    line1: str
    city: str
    postal_code: str
    country: str = "PL"

    def __post_init__(self) -> None:
        if not all((self.label.strip(), self.line1.strip(), self.city.strip(), self.postal_code.strip())):
            raise DomainError("A complete delivery address is required")
        if len(self.country.strip()) != 2:
            raise DomainError("Country must be an ISO alpha-2 code")


@dataclass(frozen=True, slots=True)
class PaymentMethod:
    token: str
    brand: str
    last4: str
    expiry_month: int
    expiry_year: int
    is_demo: bool = True

    def __post_init__(self) -> None:
        if not self.token.startswith("pm_"):
            raise DomainError("Only tokenized payment methods are accepted")
        if len(self.last4) != 4 or not self.last4.isdigit():
            raise DomainError("Payment last4 must contain four digits")
        if not 1 <= self.expiry_month <= 12:
            raise DomainError("Invalid payment expiry month")


@dataclass(frozen=True, slots=True)
class UserSettings:
    user_id: str
    voice_language: str = "en-PL"
    confirmation_voice_enabled: bool = True
    safe_recovery_enabled: bool = True
    approval_policy: ApprovalPolicy = ApprovalPolicy.ALWAYS
    approval_threshold: Money = field(default_factory=lambda: Money(0, "PLN"))
    notifications_enabled: bool = True
    preferred_merchant_ids: tuple[str, ...] = ()

    def patch(self, **changes: object) -> "UserSettings":
        allowed = {
            "voice_language",
            "confirmation_voice_enabled",
            "safe_recovery_enabled",
            "approval_policy",
            "approval_threshold",
            "notifications_enabled",
            "preferred_merchant_ids",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise DomainError(f"Unknown settings: {', '.join(sorted(unknown))}")
        return replace(self, **changes)


@dataclass(frozen=True, slots=True)
class UserProfile:
    id: str
    name: str
    email: str
    locale: str
    currency: str
    timezone: str
    autonomy_level: str
    delivery_address: DeliveryAddress
    payment_method: PaymentMethod
    default_constraints: tuple[str, ...]
    contact_preference: ContactPreference

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise DomainError("User name cannot be empty")
        if "@" not in self.email:
            raise DomainError("A valid email address is required")

