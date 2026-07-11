from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.common import DomainError, Money
from app.domain.mission.model import ConstraintKind, MissionContract


@dataclass(frozen=True, slots=True)
class BasketLine:
    product_id: str
    category: str
    quantity: int
    unit_price: Money
    allergens: frozenset[str]
    tags: frozenset[str]
    available_quantity: int | None = None

    @property
    def total(self) -> Money:
        return Money(self.quantity * self.unit_price.minor, self.unit_price.currency)


@dataclass(frozen=True, slots=True)
class BasketSnapshot:
    lines: tuple[BasketLine, ...]
    delivery_cost: Money
    delivery_at: datetime

    @property
    def total(self) -> Money:
        result = self.delivery_cost
        for line in self.lines:
            result = result.add(line.total)
        return result


@dataclass(frozen=True, slots=True)
class PolicyViolation:
    code: str
    message: str
    hard: bool = True
    repairable: bool = False


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    approved: bool
    violations: tuple[PolicyViolation, ...]
    approval_required: bool


@dataclass(frozen=True, slots=True)
class MissionExecutionPolicy:
    """Snapshot of user-controlled execution boundaries for one mission."""

    approval_mode: str = "always"
    approval_threshold: Money = Money(0, "PLN")
    safe_recovery_enabled: bool = True
    preferred_merchant_ids: tuple[str, ...] = ()
    default_constraints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        allowed = {"always", "above_threshold", "autonomous_low_risk"}
        if self.approval_mode not in allowed:
            raise DomainError(f"Unsupported approval mode: {self.approval_mode}")
        if (
            self.approval_mode == "above_threshold"
            and self.approval_threshold.minor <= 0
        ):
            raise DomainError("Approval threshold must be positive")

    def requires_approval(self, total: Money, *, risk_level: int) -> bool:
        if total.currency != self.approval_threshold.currency:
            raise DomainError("Approval threshold and basket currencies differ")
        if self.approval_mode == "always":
            return True
        if self.approval_mode == "above_threshold":
            return total.minor >= self.approval_threshold.minor
        # Autonomous mode is intentionally bounded.  High-risk plans still
        # interrupt even if the user selected maximum autonomy.
        return risk_level >= 70


class BasketPolicy:
    """Deterministic safety boundary for every proposed basket."""

    def evaluate(self, contract: MissionContract, basket: BasketSnapshot) -> PolicyDecision:
        violations: list[PolicyViolation] = []
        if basket.total.currency != contract.budget.currency:
            violations.append(
                PolicyViolation("CURRENCY_MISMATCH", "Basket and budget currencies differ")
            )
        elif basket.total.minor > contract.budget.minor:
            difference = basket.total.minor - contract.budget.minor
            violations.append(
                PolicyViolation(
                    "BUDGET_EXCEEDED",
                    f"Basket exceeds budget by {Money(difference, contract.budget.currency).major}",
                    repairable=True,
                )
            )
        if basket.delivery_at > contract.deadline:
            violations.append(
                PolicyViolation(
                    "DEADLINE_MISSED",
                    "Selected delivery is after the hard deadline",
                    repairable=True,
                )
            )

        supported_operators = {
            ConstraintKind.ALLERGEN: "exclude",
            ConstraintKind.PROHIBITED_CATEGORY: "exclude",
            ConstraintKind.MATERIAL: "exclude",
            ConstraintKind.CUSTOM: "require",
            ConstraintKind.BUDGET: "less_than_or_equal",
            ConstraintKind.DEADLINE: "before_or_at",
        }
        for constraint in contract.hard_constraints:
            expected_operator = supported_operators.get(constraint.kind)
            if expected_operator is None or constraint.operator != expected_operator:
                violations.append(
                    PolicyViolation(
                        "UNSUPPORTED_HARD_CONSTRAINT",
                        (
                            f"Constraint {constraint.kind.value}:{constraint.operator} "
                            "cannot be proven by the policy engine"
                        ),
                    )
                )

        excluded_allergens = {
            str(constraint.value).casefold()
            for constraint in contract.hard_constraints
            if constraint.kind == ConstraintKind.ALLERGEN
            and constraint.operator == "exclude"
        }
        prohibited_categories = {
            str(constraint.value).casefold()
            for constraint in contract.hard_constraints
            if constraint.kind == ConstraintKind.PROHIBITED_CATEGORY
            and constraint.operator == "exclude"
        }
        prohibited_materials = {
            str(constraint.value).casefold()
            for constraint in contract.hard_constraints
            if constraint.kind == ConstraintKind.MATERIAL
            and constraint.operator == "exclude"
        }
        dietary_requirements = {
            str(constraint.value).casefold()
            for constraint in contract.hard_constraints
            if constraint.kind == ConstraintKind.CUSTOM
            and constraint.operator == "require"
        }
        unsupported_custom = dietary_requirements - {"vegan", "vegetarian"}
        for value in sorted(unsupported_custom):
            violations.append(
                PolicyViolation(
                    "UNSUPPORTED_HARD_CONSTRAINT",
                    f"Custom hard constraint {value!r} cannot be proven",
                )
            )
        food_categories = {"snacks", "drinks", "cake", "food", "beverages"}
        for line in basket.lines:
            if (
                line.available_quantity is not None
                and line.quantity > line.available_quantity
            ):
                violations.append(
                    PolicyViolation(
                        "INSUFFICIENT_INVENTORY",
                        f"Product {line.product_id} does not have enough stock",
                        repairable=True,
                    )
                )
            allergens = {allergen.casefold() for allergen in line.allergens}
            if excluded_allergens & allergens:
                violations.append(
                    PolicyViolation(
                        "ALLERGEN_VIOLATION",
                        f"Product {line.product_id} contains an excluded allergen",
                    )
                )
            if line.category.casefold() in prohibited_categories:
                violations.append(
                    PolicyViolation(
                        "PROHIBITED_CATEGORY",
                        f"Product {line.product_id} is in a prohibited category",
                    )
                )
            tags = {tag.casefold() for tag in line.tags}
            if line.category.casefold() in food_categories:
                for requirement in dietary_requirements & {"vegan", "vegetarian"}:
                    if requirement not in tags:
                        violations.append(
                            PolicyViolation(
                                "DIETARY_CONSTRAINT_VIOLATION",
                                (
                                    f"Product {line.product_id} is not verified "
                                    f"as {requirement}"
                                ),
                                repairable=True,
                            )
                        )
            if prohibited_materials and not all(
                f"{material}-free" in tags for material in prohibited_materials
            ):
                violations.append(
                    PolicyViolation(
                        "MATERIAL_VIOLATION",
                        f"Product {line.product_id} does not satisfy the material policy",
                        repairable=True,
                    )
                )
        return PolicyDecision(
            approved=not any(violation.hard for violation in violations),
            violations=tuple(violations),
            approval_required=contract.approval_policy != "autonomous",
        )
