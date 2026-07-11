"""HTTP request schemas for the Done API."""

from __future__ import annotations

from typing import Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class MissionCreateRequest(BaseModel):
    """Create a mission from a transcript.

    Both ``transcript`` and ``text`` are accepted so the same deterministic
    endpoint can back the microphone flow and the hidden demo text fallback.
    """

    transcript: str | None = Field(default=None, min_length=3, max_length=4_000)
    text: str | None = Field(default=None, min_length=3, max_length=4_000)
    locale: str = Field(default="pl-PL", min_length=2, max_length=32)
    timezone: str = Field(default="Europe/Warsaw", min_length=1, max_length=64)

    @model_validator(mode="after")
    def require_transcript(self) -> "MissionCreateRequest":
        value = (self.transcript or self.text or "").strip()
        if not value:
            raise ValueError("transcript or text is required")
        self.transcript = value
        return self


class ApprovalResolveRequest(BaseModel):
    choice: Literal["approve", "review", "cancel"]
    voice_transcript: str | None = Field(default=None, max_length=4_000)
    expected_revision: int | None = Field(default=None, ge=1)
    amount: float | None = Field(default=None, gt=0)
    currency: Literal["PLN", "EUR", "USD"] | None = None
    plan_hash: str | None = Field(default=None, min_length=8, max_length=200)
    merchant_id: str | None = Field(default=None, min_length=1, max_length=200)


class ActionResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    choice: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_]+$")
    voice_transcript: str | None = Field(default=None, max_length=4_000)
    expected_revision: int | None = Field(default=None, ge=1)


class HumanSupportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)
    expected_revision: int | None = Field(default=None, ge=1)


class FailureInjectionRequest(BaseModel):
    mission_id: str
    failure_type: Literal[
        "product_unavailable",
        "out_of_stock",
        "price_changed",
        "delivery_slot_lost",
        "payment_soft_decline",
        "payment_hard_decline",
    ]


class MissionCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correction: str = Field(min_length=3, max_length=4_000)
    expected_revision: int | None = Field(default=None, ge=1)

    @field_validator("correction")
    @classmethod
    def normalize_correction(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("correction must contain at least three characters")
        return normalized


class ReplanMissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int | None = Field(default=None, ge=1)


class MissionCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int | None = Field(default=None, ge=1)


class DeliveryOptionSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivery_option_id: str = Field(
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("option_id", "delivery_option_id"),
    )
    expected_revision: int | None = Field(default=None, ge=1)

    @field_validator("delivery_option_id")
    @classmethod
    def normalize_delivery_option_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("delivery_option_id cannot be empty")
        return normalized


class RealtimeClientSecretRequest(BaseModel):
    """Client preferences accepted while minting a live voice session."""

    model_config = ConfigDict(extra="forbid")

    language: str = Field(default="pl-PL", min_length=2, max_length=32)
    mission_id: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("language cannot be empty")
        return normalized
