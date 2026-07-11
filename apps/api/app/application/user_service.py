"""Use cases and output ports for the User/Profile/Settings bounded context."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Callable, Protocol

from app.domain.common import DomainError, Money
from app.domain.user.model import (
    ApprovalPolicy,
    ContactPreference,
    UserProfile,
    UserSettings,
)


class UserNotFoundError(LookupError):
    """Raised when the authenticated user has no persisted profile."""


@dataclass(frozen=True, slots=True)
class UserStats:
    missions: int
    recoveries: int
    saved: Money


@dataclass(frozen=True, slots=True)
class ProfileDetails:
    profile: UserProfile
    stats: UserStats


@dataclass(frozen=True, slots=True)
class MerchantSummary:
    id: str
    name: str
    reliability_score: float
    payment_success_rate: float
    delivery_success_rate: float
    active: bool
    preferred: bool = False


@dataclass(frozen=True, slots=True)
class UserDataExport:
    schema_version: int
    generated_at: datetime
    profile: ProfileDetails
    settings: UserSettings


class UserRepository(Protocol):
    """Persistence port owned by the application layer."""

    def get_profile(self, user_id: str) -> UserProfile: ...

    def save_profile(self, profile: UserProfile) -> None: ...

    def save_profile_and_settings(
        self, profile: UserProfile, settings: UserSettings
    ) -> None: ...

    def get_settings(self, user_id: str) -> UserSettings: ...

    def save_settings(self, settings: UserSettings) -> None: ...

    def get_stats(self, user_id: str) -> UserStats: ...

    def list_merchants(self) -> tuple[MerchantSummary, ...]: ...


class UserApplicationService:
    """Application facade for the single authenticated demo user."""

    def __init__(
        self,
        repository: UserRepository,
        *,
        current_user_id: str = "demo-user",
        clock: Callable[[], datetime] | None = None,
    ):
        self._repository = repository
        self._current_user_id = current_user_id
        self._clock = clock or (lambda: datetime.now(UTC))

    def get_profile(self) -> ProfileDetails:
        profile = self._repository.get_profile(self._current_user_id)
        return ProfileDetails(
            profile=profile,
            stats=self._repository.get_stats(self._current_user_id),
        )

    def patch_profile(self, changes: dict[str, object]) -> ProfileDetails:
        current = self._repository.get_profile(self._current_user_id)

        address = current.delivery_address
        if "delivery_address" in changes:
            raw_address = changes["delivery_address"]
            if not isinstance(raw_address, dict):
                raise DomainError("delivery_address cannot be null")
            if any(value is None for value in raw_address.values()):
                raise DomainError("Delivery address fields cannot be null")
            address = replace(address, **raw_address)

        payment_method = current.payment_method
        if "payment_method" in changes:
            raw_payment = changes["payment_method"]
            if not isinstance(raw_payment, dict):
                raise DomainError("payment_method cannot be null")
            if any(value is None for value in raw_payment.values()):
                raise DomainError("Payment method fields cannot be null")
            payment_method = replace(payment_method, **raw_payment)
            now = self._clock()
            if (payment_method.expiry_year, payment_method.expiry_month) < (
                now.year,
                now.month,
            ):
                raise DomainError("Payment method is expired")

        scalar = {
            field_name: changes.get(field_name, getattr(current, field_name))
            for field_name in (
                "name",
                "email",
                "locale",
                "currency",
                "timezone",
                "autonomy_level",
            )
        }
        if any(value is None for value in scalar.values()):
            raise DomainError("Profile fields cannot be null")

        raw_constraints = changes.get("default_constraints", current.default_constraints)
        if raw_constraints is None:
            raise DomainError("default_constraints cannot be null")
        constraints = tuple(str(value).strip() for value in raw_constraints)
        if any(not value for value in constraints):
            raise DomainError("Default constraints cannot contain empty values")
        if len(set(constraints)) != len(constraints):
            raise DomainError("Default constraints must be unique")

        raw_contact = changes.get("contact_preference", current.contact_preference)
        if raw_contact is None:
            raise DomainError("contact_preference cannot be null")

        updated = UserProfile(
            id=current.id,
            name=str(scalar["name"]).strip(),
            email=str(scalar["email"]).strip().lower(),
            locale=str(scalar["locale"]),
            currency=str(scalar["currency"]).upper(),
            timezone=str(scalar["timezone"]),
            autonomy_level=str(scalar["autonomy_level"]),
            delivery_address=address,
            payment_method=payment_method,
            default_constraints=constraints,
            contact_preference=ContactPreference(raw_contact),
        )

        if updated.currency != current.currency:
            settings = self._repository.get_settings(self._current_user_id)
            settings = replace(
                settings,
                approval_threshold=Money(
                    settings.approval_threshold.minor,
                    updated.currency,
                ),
            )
            self._repository.save_profile_and_settings(updated, settings)
        else:
            self._repository.save_profile(updated)
        return ProfileDetails(updated, self._repository.get_stats(self._current_user_id))

    def get_settings(self) -> UserSettings:
        return self._repository.get_settings(self._current_user_id)

    def patch_settings(self, changes: dict[str, object]) -> UserSettings:
        current = self._repository.get_settings(self._current_user_id)
        profile = self._repository.get_profile(self._current_user_id)
        normalized = dict(changes)

        if "approval_policy" in normalized:
            value = normalized["approval_policy"]
            if value is None:
                raise DomainError("approval_policy cannot be null")
            normalized["approval_policy"] = ApprovalPolicy(value)

        if "approval_threshold" in normalized:
            threshold = normalized.pop("approval_threshold")
            if threshold is None:
                raise DomainError("approval_threshold cannot be null")
            normalized["approval_threshold"] = Money.from_major(
                threshold, profile.currency
            )

        if "preferred_merchant_ids" in normalized:
            raw_ids = normalized["preferred_merchant_ids"]
            if raw_ids is None:
                raise DomainError("preferred_merchant_ids cannot be null")
            merchant_ids = tuple(str(value) for value in raw_ids)
            if len(set(merchant_ids)) != len(merchant_ids):
                raise DomainError("Preferred merchants must be unique")
            available = {
                merchant.id for merchant in self._repository.list_merchants() if merchant.active
            }
            unknown = set(merchant_ids) - available
            if unknown:
                raise DomainError(
                    f"Unknown or inactive merchants: {', '.join(sorted(unknown))}"
                )
            normalized["preferred_merchant_ids"] = merchant_ids

        if any(value is None for value in normalized.values()):
            raise DomainError("Settings fields cannot be null")

        updated = current.patch(**normalized)
        if (
            updated.approval_policy == ApprovalPolicy.ABOVE_THRESHOLD
            and updated.approval_threshold.minor <= 0
        ):
            raise DomainError(
                "approval_threshold must be greater than zero for above_threshold policy"
            )
        self._repository.save_settings(updated)
        return updated

    def list_merchants(self) -> tuple[MerchantSummary, ...]:
        preferred = set(self.get_settings().preferred_merchant_ids)
        return tuple(
            replace(merchant, preferred=merchant.id in preferred)
            for merchant in self._repository.list_merchants()
        )

    def export_current_user(self) -> UserDataExport:
        return UserDataExport(
            schema_version=1,
            generated_at=self._clock(),
            profile=self.get_profile(),
            settings=self.get_settings(),
        )
