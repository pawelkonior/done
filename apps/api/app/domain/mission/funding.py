from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from app.domain.common import DomainError, Money, utc_now


DEFAULT_VIRTUAL_CARD_TTL = timedelta(minutes=5)
MAX_VIRTUAL_CARD_TTL = timedelta(minutes=15)


def _is_timezone_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _require_timezone_aware(value: datetime, field_name: str) -> None:
    if not _is_timezone_aware(value):
        raise DomainError(f"{field_name} must include a timezone")


def _require_valid_window(start: datetime, end: datetime, label: str) -> None:
    _require_timezone_aware(start, f"{label} start")
    _require_timezone_aware(end, f"{label} expiry")
    if end <= start:
        raise DomainError(f"{label} expiry must be after its start")


@dataclass(frozen=True, slots=True)
class PlanFingerprint:
    """Security-relevant identity of the exact plan presented at each gate."""

    mission_id: str
    plan_hash: str
    merchant_id: str
    all_in_total: Money

    def __post_init__(self) -> None:
        # Empty values are deliberately preserved as invalid values.  This lets
        # FundingGate reject persisted/incomplete snapshots with typed reasons.
        object.__setattr__(self, "mission_id", self.mission_id.strip())
        object.__setattr__(self, "plan_hash", self.plan_hash.strip())
        object.__setattr__(self, "merchant_id", self.merchant_id.strip())

    @property
    def currency(self) -> str:
        return self.all_in_total.currency


@dataclass(frozen=True, slots=True)
class GuardrailAttestation:
    plan: PlanFingerprint
    passed: bool
    attested_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _require_valid_window(self.attested_at, self.expires_at, "Guardrail attestation")


@dataclass(frozen=True, slots=True)
class UserApproval:
    plan: PlanFingerprint
    approved: bool
    approved_amount: Money
    approved_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _require_valid_window(self.approved_at, self.expires_at, "User approval")


@dataclass(frozen=True, slots=True)
class ReservationSnapshot:
    plan: PlanFingerprint
    valid: bool
    reserved_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _require_valid_window(self.reserved_at, self.expires_at, "Reservation")


@dataclass(frozen=True, slots=True)
class FundingContext:
    """All evidence required before a virtual-card request can be constructed."""

    checkout: PlanFingerprint | None
    budget: Money
    guardrails: GuardrailAttestation | None = None
    approval: UserApproval | None = None
    reservation: ReservationSnapshot | None = None
    unresolved_actions: tuple[str, ...] = ()
    idempotency_key: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "unresolved_actions", tuple(self.unresolved_actions))
        object.__setattr__(self, "idempotency_key", self.idempotency_key.strip())


@dataclass(frozen=True, slots=True)
class VirtualCardSpec:
    """Issuer-facing restrictions only; this object never contains PAN or CVV."""

    mission_id: str
    plan_hash: str
    max_amount: Money
    merchant_lock: str
    currency: str
    single_use: bool
    no_cash: bool
    no_recurring: bool
    issued_at: datetime
    expires_at: datetime
    idempotency_key: str

    def __post_init__(self) -> None:
        mission_id = self.mission_id.strip()
        plan_hash = self.plan_hash.strip()
        merchant_lock = self.merchant_lock.strip()
        currency = self.currency.upper().strip()
        idempotency_key = self.idempotency_key.strip()
        if not mission_id or not plan_hash or not merchant_lock or not idempotency_key:
            raise DomainError("Virtual card identifiers and restrictions cannot be empty")
        if self.max_amount.minor <= 0:
            raise DomainError("Virtual card limit must be positive")
        if currency != self.max_amount.currency:
            raise DomainError("Virtual card currency must match its limit")
        if not self.single_use or not self.no_cash or not self.no_recurring:
            raise DomainError("Virtual cards must be single-use, cash-free, and non-recurring")
        _require_valid_window(self.issued_at, self.expires_at, "Virtual card")
        if self.expires_at - self.issued_at > MAX_VIRTUAL_CARD_TTL:
            raise DomainError("Virtual card TTL exceeds the safety maximum")
        object.__setattr__(self, "mission_id", mission_id)
        object.__setattr__(self, "plan_hash", plan_hash)
        object.__setattr__(self, "merchant_lock", merchant_lock)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "idempotency_key", idempotency_key)


class FundingViolationCode(StrEnum):
    CHECKOUT_PLAN_MISSING = "CHECKOUT_PLAN_MISSING"
    MISSION_ID_MISSING = "MISSION_ID_MISSING"
    PLAN_HASH_MISSING = "PLAN_HASH_MISSING"
    PLAN_HASH_MISMATCH = "PLAN_HASH_MISMATCH"
    MISSION_MISMATCH = "MISSION_MISMATCH"
    MERCHANT_MISSING = "MERCHANT_MISSING"
    MERCHANT_MISMATCH = "MERCHANT_MISMATCH"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    PLAN_TOTAL_MISMATCH = "PLAN_TOTAL_MISMATCH"
    FINAL_TOTAL_NOT_POSITIVE = "FINAL_TOTAL_NOT_POSITIVE"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    GUARDRAILS_MISSING = "GUARDRAILS_MISSING"
    GUARDRAILS_NOT_PASSED = "GUARDRAILS_NOT_PASSED"
    GUARDRAILS_NOT_YET_VALID = "GUARDRAILS_NOT_YET_VALID"
    GUARDRAILS_EXPIRED = "GUARDRAILS_EXPIRED"
    APPROVAL_MISSING = "APPROVAL_MISSING"
    APPROVAL_NOT_GRANTED = "APPROVAL_NOT_GRANTED"
    APPROVAL_NOT_YET_VALID = "APPROVAL_NOT_YET_VALID"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    APPROVED_AMOUNT_EXCEEDED = "APPROVED_AMOUNT_EXCEEDED"
    RESERVATION_MISSING = "RESERVATION_MISSING"
    RESERVATION_INVALID = "RESERVATION_INVALID"
    RESERVATION_NOT_YET_VALID = "RESERVATION_NOT_YET_VALID"
    RESERVATION_EXPIRED = "RESERVATION_EXPIRED"
    UNRESOLVED_ACTIONS = "UNRESOLVED_ACTIONS"
    IDEMPOTENCY_KEY_MISSING = "IDEMPOTENCY_KEY_MISSING"


@dataclass(frozen=True, slots=True)
class FundingViolation:
    code: FundingViolationCode
    message: str
    source: str | None = None


@dataclass(frozen=True, slots=True)
class FundingDecision:
    approved: bool
    violations: tuple[FundingViolation, ...]
    card_spec: VirtualCardSpec | None

    @property
    def allowed(self) -> bool:
        return self.approved


class FundingDeniedError(DomainError):
    def __init__(self, violations: tuple[FundingViolation, ...]) -> None:
        self.violations = violations
        codes = ", ".join(violation.code.value for violation in violations)
        super().__init__(f"Funding denied: {codes}")

    @property
    def codes(self) -> tuple[FundingViolationCode, ...]:
        return tuple(violation.code for violation in self.violations)


class FundingGate:
    """Fail-closed boundary between an approved plan and card issuance."""

    def __init__(self, *, card_ttl: timedelta = DEFAULT_VIRTUAL_CARD_TTL) -> None:
        if card_ttl <= timedelta(0) or card_ttl > MAX_VIRTUAL_CARD_TTL:
            raise DomainError("Card TTL must be positive and no longer than 15 minutes")
        self._card_ttl = card_ttl

    def evaluate(
        self,
        context: FundingContext,
        *,
        now: datetime | None = None,
    ) -> FundingDecision:
        evaluated_at = now or utc_now()
        _require_timezone_aware(evaluated_at, "Funding evaluation time")
        violations: list[FundingViolation] = []

        checkout = context.checkout
        if checkout is None:
            violations.append(
                FundingViolation(
                    FundingViolationCode.CHECKOUT_PLAN_MISSING,
                    "The final checkout plan is missing",
                    "checkout",
                )
            )
        else:
            self._validate_checkout(checkout, context, violations)

        self._validate_guardrails(context.guardrails, evaluated_at, violations)
        self._validate_approval(context.approval, evaluated_at, violations)
        self._validate_reservation(context.reservation, evaluated_at, violations)

        if context.unresolved_actions:
            violations.append(
                FundingViolation(
                    FundingViolationCode.UNRESOLVED_ACTIONS,
                    "All action requests must be resolved before funding",
                    "actions",
                )
            )
        if not context.idempotency_key:
            violations.append(
                FundingViolation(
                    FundingViolationCode.IDEMPOTENCY_KEY_MISSING,
                    "A stable idempotency key is required",
                    "funding",
                )
            )

        if checkout is not None:
            evidence = (
                ("guardrails", context.guardrails.plan if context.guardrails else None),
                ("approval", context.approval.plan if context.approval else None),
                ("reservation", context.reservation.plan if context.reservation else None),
            )
            self._validate_plan_identity(checkout, evidence, violations)
            self._validate_approved_amount(checkout, context.approval, violations)

        if violations or checkout is None:
            return FundingDecision(False, tuple(violations), None)

        # All evidence is non-null here because missing evidence is a violation.
        assert context.guardrails is not None
        assert context.approval is not None
        assert context.reservation is not None
        expires_at = min(
            evaluated_at + self._card_ttl,
            context.guardrails.expires_at,
            context.approval.expires_at,
            context.reservation.expires_at,
        )
        spec = VirtualCardSpec(
            mission_id=checkout.mission_id,
            plan_hash=checkout.plan_hash,
            max_amount=checkout.all_in_total,
            merchant_lock=checkout.merchant_id,
            currency=checkout.currency,
            single_use=True,
            no_cash=True,
            no_recurring=True,
            issued_at=evaluated_at,
            expires_at=expires_at,
            idempotency_key=context.idempotency_key,
        )
        return FundingDecision(True, (), spec)

    def require(
        self,
        context: FundingContext,
        *,
        now: datetime | None = None,
    ) -> VirtualCardSpec:
        decision = self.evaluate(context, now=now)
        if not decision.approved or decision.card_spec is None:
            raise FundingDeniedError(decision.violations)
        return decision.card_spec

    @staticmethod
    def _validate_checkout(
        checkout: PlanFingerprint,
        context: FundingContext,
        violations: list[FundingViolation],
    ) -> None:
        if not checkout.mission_id:
            violations.append(
                FundingViolation(
                    FundingViolationCode.MISSION_ID_MISSING,
                    "The checkout mission identifier is missing",
                    "checkout",
                )
            )
        if not checkout.plan_hash:
            violations.append(
                FundingViolation(
                    FundingViolationCode.PLAN_HASH_MISSING,
                    "The checkout plan hash is missing",
                    "checkout",
                )
            )
        if not checkout.merchant_id:
            violations.append(
                FundingViolation(
                    FundingViolationCode.MERCHANT_MISSING,
                    "The checkout merchant lock is missing",
                    "checkout",
                )
            )
        if checkout.all_in_total.minor <= 0:
            violations.append(
                FundingViolation(
                    FundingViolationCode.FINAL_TOTAL_NOT_POSITIVE,
                    "The final all-in total must be positive",
                    "checkout",
                )
            )
        if checkout.currency != context.budget.currency:
            violations.append(
                FundingViolation(
                    FundingViolationCode.CURRENCY_MISMATCH,
                    "Checkout and budget currencies differ",
                    "budget",
                )
            )
        elif checkout.all_in_total.minor > context.budget.minor:
            violations.append(
                FundingViolation(
                    FundingViolationCode.BUDGET_EXCEEDED,
                    "The final all-in total exceeds the mission budget",
                    "budget",
                )
            )

    @staticmethod
    def _validate_guardrails(
        attestation: GuardrailAttestation | None,
        now: datetime,
        violations: list[FundingViolation],
    ) -> None:
        if attestation is None:
            violations.append(
                FundingViolation(
                    FundingViolationCode.GUARDRAILS_MISSING,
                    "A guardrail attestation is required",
                    "guardrails",
                )
            )
            return
        if not attestation.passed:
            violations.append(
                FundingViolation(
                    FundingViolationCode.GUARDRAILS_NOT_PASSED,
                    "Guardrails did not pass",
                    "guardrails",
                )
            )
        if attestation.attested_at > now:
            violations.append(
                FundingViolation(
                    FundingViolationCode.GUARDRAILS_NOT_YET_VALID,
                    "Guardrail attestation is dated in the future",
                    "guardrails",
                )
            )
        if attestation.expires_at <= now:
            violations.append(
                FundingViolation(
                    FundingViolationCode.GUARDRAILS_EXPIRED,
                    "Guardrail attestation has expired",
                    "guardrails",
                )
            )

    @staticmethod
    def _validate_approval(
        approval: UserApproval | None,
        now: datetime,
        violations: list[FundingViolation],
    ) -> None:
        if approval is None:
            violations.append(
                FundingViolation(
                    FundingViolationCode.APPROVAL_MISSING,
                    "Explicit user approval is required",
                    "approval",
                )
            )
            return
        if not approval.approved:
            violations.append(
                FundingViolation(
                    FundingViolationCode.APPROVAL_NOT_GRANTED,
                    "The user did not approve this plan",
                    "approval",
                )
            )
        if approval.approved_at > now:
            violations.append(
                FundingViolation(
                    FundingViolationCode.APPROVAL_NOT_YET_VALID,
                    "User approval is dated in the future",
                    "approval",
                )
            )
        if approval.expires_at <= now:
            violations.append(
                FundingViolation(
                    FundingViolationCode.APPROVAL_EXPIRED,
                    "User approval has expired",
                    "approval",
                )
            )

    @staticmethod
    def _validate_reservation(
        reservation: ReservationSnapshot | None,
        now: datetime,
        violations: list[FundingViolation],
    ) -> None:
        if reservation is None:
            violations.append(
                FundingViolation(
                    FundingViolationCode.RESERVATION_MISSING,
                    "A current stock and price reservation is required",
                    "reservation",
                )
            )
            return
        if not reservation.valid:
            violations.append(
                FundingViolation(
                    FundingViolationCode.RESERVATION_INVALID,
                    "The stock or price reservation is invalid",
                    "reservation",
                )
            )
        if reservation.reserved_at > now:
            violations.append(
                FundingViolation(
                    FundingViolationCode.RESERVATION_NOT_YET_VALID,
                    "Reservation is dated in the future",
                    "reservation",
                )
            )
        if reservation.expires_at <= now:
            violations.append(
                FundingViolation(
                    FundingViolationCode.RESERVATION_EXPIRED,
                    "The stock or price reservation is stale",
                    "reservation",
                )
            )

    @staticmethod
    def _validate_plan_identity(
        checkout: PlanFingerprint,
        evidence: tuple[tuple[str, PlanFingerprint | None], ...],
        violations: list[FundingViolation],
    ) -> None:
        for source, plan in evidence:
            if plan is None:
                continue
            if not plan.plan_hash:
                violations.append(
                    FundingViolation(
                        FundingViolationCode.PLAN_HASH_MISSING,
                        f"{source.capitalize()} plan hash is missing",
                        source,
                    )
                )
            elif checkout.plan_hash and plan.plan_hash != checkout.plan_hash:
                violations.append(
                    FundingViolation(
                        FundingViolationCode.PLAN_HASH_MISMATCH,
                        f"{source.capitalize()} applies to a different plan",
                        source,
                    )
                )
            if plan.mission_id != checkout.mission_id:
                violations.append(
                    FundingViolation(
                        FundingViolationCode.MISSION_MISMATCH,
                        f"{source.capitalize()} belongs to another mission",
                        source,
                    )
                )
            if plan.merchant_id != checkout.merchant_id:
                violations.append(
                    FundingViolation(
                        FundingViolationCode.MERCHANT_MISMATCH,
                        f"{source.capitalize()} applies to another merchant",
                        source,
                    )
                )
            if plan.currency != checkout.currency:
                violations.append(
                    FundingViolation(
                        FundingViolationCode.CURRENCY_MISMATCH,
                        f"{source.capitalize()} uses another currency",
                        source,
                    )
                )
            elif plan.all_in_total.minor != checkout.all_in_total.minor:
                violations.append(
                    FundingViolation(
                        FundingViolationCode.PLAN_TOTAL_MISMATCH,
                        f"{source.capitalize()} applies to another total",
                        source,
                    )
                )

    @staticmethod
    def _validate_approved_amount(
        checkout: PlanFingerprint,
        approval: UserApproval | None,
        violations: list[FundingViolation],
    ) -> None:
        if approval is None:
            return
        if approval.approved_amount.currency != checkout.currency:
            violations.append(
                FundingViolation(
                    FundingViolationCode.CURRENCY_MISMATCH,
                    "Approved amount and checkout currencies differ",
                    "approval",
                )
            )
        elif checkout.all_in_total.minor > approval.approved_amount.minor:
            violations.append(
                FundingViolation(
                    FundingViolationCode.APPROVED_AMOUNT_EXCEEDED,
                    "The final all-in total exceeds the user-approved amount",
                    "approval",
                )
            )
