"""FastAPI presentation adapter for User/Profile/Settings use cases."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Callable, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.application.user_service import (
    MerchantSummary,
    ProfileDetails,
    UserApplicationService,
    UserDataExport,
    UserNotFoundError,
)
from app.domain.common import DomainError
from app.domain.user.model import ApprovalPolicy, ContactPreference, UserSettings


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeliveryAddressPatch(StrictModel):
    label: str | None = Field(default=None, min_length=1, max_length=40)
    line1: str | None = Field(default=None, min_length=1, max_length=160)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    postal_code: str | None = Field(default=None, min_length=2, max_length=20)
    country: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")

    @field_validator("label", "line1", "city", "postal_code")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None


class PaymentMethodPatch(StrictModel):
    token: str | None = Field(default=None, min_length=4, max_length=160, pattern=r"^pm_")
    brand: str | None = Field(default=None, min_length=1, max_length=40)
    last4: str | None = Field(default=None, pattern=r"^\d{4}$")
    expiry_month: int | None = Field(default=None, ge=1, le=12)
    expiry_year: int | None = Field(default=None, ge=2024, le=2100)
    is_demo: bool | None = None

    @field_validator("brand")
    @classmethod
    def strip_brand(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class UserProfilePatchRequest(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    email: str | None = Field(default=None, min_length=3, max_length=254)
    locale: str | None = Field(
        default=None, pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z]{2,4})?$"
    )
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    autonomy_level: str | None = Field(
        default=None, pattern=r"^[a-z][a-z0-9_-]{1,31}$"
    )
    delivery_address: DeliveryAddressPatch | None = None
    payment_method: PaymentMethodPatch | None = None
    default_constraints: list[Annotated[str, Field(min_length=1, max_length=200)]] | None = Field(
        default=None, max_length=30
    )
    contact_preference: ContactPreference | None = None

    @field_validator("name", "email")
    @classmethod
    def strip_identity(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("A valid email address is required")
        return value.lower() if value is not None else None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except ZoneInfoNotFoundError as exc:
                raise ValueError("Unknown IANA timezone") from exc
        return value

    @field_validator("default_constraints")
    @classmethod
    def validate_constraints(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = [constraint.strip() for constraint in value]
        if len(set(normalized)) != len(normalized):
            raise ValueError("Default constraints must be unique")
        return normalized


class UserSettingsPatchRequest(StrictModel):
    voice_language: str | None = Field(
        default=None, pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z]{2,4})?$"
    )
    confirmation_voice_enabled: bool | None = None
    safe_recovery_enabled: bool | None = None
    approval_policy: ApprovalPolicy | None = None
    approval_threshold: float | None = Field(default=None, ge=0, le=1_000_000)
    notifications_enabled: bool | None = None
    preferred_merchant_ids: list[
        Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")]
    ] | None = Field(default=None, max_length=50)

    @field_validator("preferred_merchant_ids")
    @classmethod
    def validate_merchant_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("Preferred merchants must be unique")
        return value


class DeliveryAddressResponse(StrictModel):
    label: str
    line1: str
    city: str
    postal_code: str
    country: str


class PaymentMethodResponse(StrictModel):
    token: str
    brand: str
    last4: str
    expiry_month: int
    expiry_year: int
    is_demo: bool


class UserStatsResponse(StrictModel):
    missions: int
    recoveries: int
    saved: float


class UserProfileResponse(StrictModel):
    id: str
    name: str
    email: str
    locale: str
    currency: str
    timezone: str
    autonomy_level: str
    delivery_address: DeliveryAddressResponse
    payment_method: PaymentMethodResponse
    default_constraints: list[str]
    contact_preference: ContactPreference
    stats: UserStatsResponse


class UserSettingsResponse(StrictModel):
    voice_language: str
    confirmation_voice_enabled: bool
    safe_recovery_enabled: bool
    approval_policy: ApprovalPolicy
    approval_threshold: float
    notifications_enabled: bool
    preferred_merchant_ids: list[str]


class MerchantResponse(StrictModel):
    id: str
    name: str
    reliability_score: float
    payment_success_rate: float
    delivery_success_rate: float
    active: bool
    preferred: bool


class MerchantListResponse(StrictModel):
    merchants: list[MerchantResponse]
    items: list[MerchantResponse]
    total: int


class UserExportResponse(StrictModel):
    schema_version: int
    generated_at: datetime
    profile: UserProfileResponse
    settings: UserSettingsResponse


def _profile_response(details: ProfileDetails) -> UserProfileResponse:
    profile = details.profile
    return UserProfileResponse(
        id=profile.id,
        name=profile.name,
        email=profile.email,
        locale=profile.locale,
        currency=profile.currency,
        timezone=profile.timezone,
        autonomy_level=profile.autonomy_level,
        delivery_address=DeliveryAddressResponse(
            label=profile.delivery_address.label,
            line1=profile.delivery_address.line1,
            city=profile.delivery_address.city,
            postal_code=profile.delivery_address.postal_code,
            country=profile.delivery_address.country,
        ),
        payment_method=PaymentMethodResponse(
            token=profile.payment_method.token,
            brand=profile.payment_method.brand,
            last4=profile.payment_method.last4,
            expiry_month=profile.payment_method.expiry_month,
            expiry_year=profile.payment_method.expiry_year,
            is_demo=profile.payment_method.is_demo,
        ),
        default_constraints=list(profile.default_constraints),
        contact_preference=profile.contact_preference,
        stats=UserStatsResponse(
            missions=details.stats.missions,
            recoveries=details.stats.recoveries,
            saved=float(details.stats.saved.major),
        ),
    )


def _settings_response(settings: UserSettings) -> UserSettingsResponse:
    return UserSettingsResponse(
        voice_language=settings.voice_language,
        confirmation_voice_enabled=settings.confirmation_voice_enabled,
        safe_recovery_enabled=settings.safe_recovery_enabled,
        approval_policy=settings.approval_policy,
        approval_threshold=float(settings.approval_threshold.major),
        notifications_enabled=settings.notifications_enabled,
        preferred_merchant_ids=list(settings.preferred_merchant_ids),
    )


def _merchant_response(merchant: MerchantSummary) -> MerchantResponse:
    return MerchantResponse(
        id=merchant.id,
        name=merchant.name,
        reliability_score=merchant.reliability_score,
        payment_success_rate=merchant.payment_success_rate,
        delivery_success_rate=merchant.delivery_success_rate,
        active=merchant.active,
        preferred=merchant.preferred,
    )


T = TypeVar("T")


def _execute(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "user_not_found", "message": f"User {exc} was not found."},
        ) from exc
    except (DomainError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "invalid_user_data", "message": str(exc)},
        ) from exc


def create_user_router(service: UserApplicationService) -> APIRouter:
    router = APIRouter(tags=["user"])

    @router.get("/v1/users/me", response_model=UserProfileResponse)
    def get_profile() -> UserProfileResponse:
        return _profile_response(_execute(service.get_profile))

    @router.patch("/v1/users/me", response_model=UserProfileResponse)
    def patch_profile(payload: UserProfilePatchRequest) -> UserProfileResponse:
        changes = payload.model_dump(exclude_unset=True)
        return _profile_response(_execute(lambda: service.patch_profile(changes)))

    @router.get("/v1/users/me/settings", response_model=UserSettingsResponse)
    def get_settings() -> UserSettingsResponse:
        return _settings_response(_execute(service.get_settings))

    @router.patch("/v1/users/me/settings", response_model=UserSettingsResponse)
    def patch_settings(payload: UserSettingsPatchRequest) -> UserSettingsResponse:
        changes = payload.model_dump(exclude_unset=True)
        return _settings_response(_execute(lambda: service.patch_settings(changes)))

    @router.get("/v1/merchants", response_model=MerchantListResponse)
    def list_merchants() -> MerchantListResponse:
        items = [_merchant_response(item) for item in _execute(service.list_merchants)]
        return MerchantListResponse(merchants=items, items=items, total=len(items))

    @router.get("/v1/users/me/export", response_model=UserExportResponse)
    def export_user() -> UserExportResponse:
        exported: UserDataExport = _execute(service.export_current_user)
        return UserExportResponse(
            schema_version=exported.schema_version,
            generated_at=exported.generated_at,
            profile=_profile_response(exported.profile),
            settings=_settings_response(exported.settings),
        )

    return router
