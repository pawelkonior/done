from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from app.domain.common import DomainError, Money
from app.domain.mission.intake import ShoppingScope
from app.domain.mission.model import Constraint, ConstraintKind


_AGE_TAG = re.compile(r"^age-(?P<minimum>\d{1,3})-(?P<maximum>\d{1,3})$")


class CatalogPlanNotFound(DomainError):
    """No single-merchant plan can satisfy the explicit contract."""


@dataclass(frozen=True, slots=True)
class ProductOffer:
    product_id: str
    merchant_id: str
    merchant_reliability: float
    category: str
    price: Money
    stock: int
    allergens: frozenset[str]
    tags: frozenset[str]
    rating: float
    substitute_group: str | None = None

    def __post_init__(self) -> None:
        if not self.product_id.strip() or not self.merchant_id.strip():
            raise DomainError("Catalog product and merchant identifiers are required")
        if self.stock < 0:
            raise DomainError("Catalog stock cannot be negative")
        if not 0 <= self.merchant_reliability <= 1:
            raise DomainError("Merchant reliability must be between zero and one")
        if not 0 <= self.rating <= 5:
            raise DomainError("Product rating must be between zero and five")


@dataclass(frozen=True, slots=True)
class PlannedCatalogLine:
    product_id: str
    quantity: int

    def __post_init__(self) -> None:
        if not self.product_id.strip() or self.quantity < 1:
            raise DomainError("A planned catalog line requires a product and quantity")


@dataclass(frozen=True, slots=True)
class CatalogPlan:
    merchant_id: str
    lines: tuple[PlannedCatalogLine, ...]
    subtotal: Money
    candidates_considered: int


@dataclass(frozen=True, slots=True)
class CatalogSearchRequest:
    scope: ShoppingScope
    participants: int
    recipient_age: int | None
    budget: Money
    delivery_reserve: Money
    allowed_categories: frozenset[str]
    forbidden_categories: frozenset[str]
    hard_constraints: tuple[Constraint, ...]
    preferred_merchant_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.scope == ShoppingScope.AMBIGUOUS:
            raise DomainError("Shopping scope must be explicit before catalog search")
        if self.participants < 1:
            raise DomainError("Participant count must be known before catalog search")
        if self.budget.currency != self.delivery_reserve.currency:
            raise DomainError("Budget and delivery reserve currencies differ")


@dataclass(frozen=True, slots=True)
class _Requirement:
    category: str
    quantity: int
    substitute_group: str | None = None


class CatalogPlanningAgent:
    """Build a constraint-safe single-merchant plan from live catalog offers.

    The agent never names a product in its rules. Party rules describe needs
    by category/substitution group, and gift selection is driven by age tags,
    stock, quality, price and the user's merchant preference.
    """

    def plan(
        self,
        request: CatalogSearchRequest,
        offers: tuple[ProductOffer, ...],
    ) -> CatalogPlan:
        spendable = request.budget.minor - request.delivery_reserve.minor
        if spendable <= 0:
            raise CatalogPlanNotFound("Budget does not cover a safe delivery reserve")

        supported_custom = {"vegan", "vegetarian"}
        unknown_custom = {
            str(item.value).casefold()
            for item in request.hard_constraints
            if item.kind == ConstraintKind.CUSTOM
            and str(item.value).casefold() not in supported_custom
        }
        if unknown_custom:
            raise CatalogPlanNotFound(
                "Catalog cannot prove hard constraints: "
                + ", ".join(sorted(unknown_custom))
            )

        eligible = tuple(
            offer
            for offer in offers
            if offer.stock > 0
            and offer.price.currency == request.budget.currency
            and self._offer_satisfies_contract(offer, request)
        )
        by_merchant: dict[str, list[ProductOffer]] = defaultdict(list)
        for offer in eligible:
            by_merchant[offer.merchant_id].append(offer)

        plans: list[CatalogPlan] = []
        for merchant_id, merchant_offers in by_merchant.items():
            if request.scope == ShoppingScope.PARTY_SUPPLIES:
                lines = self._party_lines(request, merchant_offers)
            else:
                lines = self._gift_lines(request, merchant_offers, spendable)
            if lines is None:
                continue
            price_by_id = {offer.product_id: offer.price.minor for offer in merchant_offers}
            subtotal_minor = sum(
                price_by_id[line.product_id] * line.quantity for line in lines
            )
            if subtotal_minor > spendable:
                continue
            plans.append(
                CatalogPlan(
                    merchant_id=merchant_id,
                    lines=lines,
                    subtotal=Money(subtotal_minor, request.budget.currency),
                    candidates_considered=len(eligible),
                )
            )
        if not plans:
            raise CatalogPlanNotFound(
                "No single merchant has a stocked plan within every hard constraint"
            )

        preferred = set(request.preferred_merchant_ids)
        reliability = {
            offer.merchant_id: offer.merchant_reliability for offer in eligible
        }
        return min(
            plans,
            key=lambda plan: (
                0 if plan.merchant_id in preferred else 1,
                -reliability.get(plan.merchant_id, 0),
                plan.subtotal.minor,
                plan.merchant_id,
            ),
        )

    @staticmethod
    def _offer_satisfies_contract(
        offer: ProductOffer,
        request: CatalogSearchRequest,
    ) -> bool:
        category = offer.category.casefold()
        if request.allowed_categories and category not in request.allowed_categories:
            return False
        if category in request.forbidden_categories:
            return False
        allergens = {value.casefold() for value in offer.allergens}
        tags = {value.casefold() for value in offer.tags}
        for constraint in request.hard_constraints:
            value = str(constraint.value).casefold()
            if constraint.kind == ConstraintKind.ALLERGEN and value in allergens:
                return False
            if constraint.kind == ConstraintKind.PROHIBITED_CATEGORY and category == value:
                return False
            if constraint.kind == ConstraintKind.MATERIAL and f"{value}-free" not in tags:
                return False
            if constraint.kind == ConstraintKind.CUSTOM:
                if value == "vegan" and "vegan" not in tags:
                    return False
                if value == "vegetarian" and not ({"vegetarian", "vegan"} & tags):
                    return False
        return True

    @staticmethod
    def _party_lines(
        request: CatalogSearchRequest,
        offers: list[ProductOffer],
    ) -> tuple[PlannedCatalogLine, ...] | None:
        people = request.participants
        requirements = [
            _Requirement("snacks", max(1, (people + 3) // 4), "savory-kids"),
            _Requirement("drinks", max(1, (people + 2) // 3), "juice"),
            _Requirement("drinks", max(1, (people + 3) // 4), "water"),
            _Requirement("cake", max(1, (people + 11) // 12), "birthday-cake"),
            _Requirement("decorations", max(1, (people + 19) // 20), "balloons"),
            _Requirement("decorations", 1, "banner"),
            _Requirement("tableware", max(1, (people + 11) // 12), "plates"),
            _Requirement("tableware", max(1, (people + 11) // 12), "cups"),
            _Requirement("napkins", max(1, (people + 19) // 20), "napkins"),
        ]
        if request.recipient_age is not None:
            requirements.append(
                _Requirement(
                    "candles",
                    max(1, (request.recipient_age + 9) // 10),
                    "candles",
                )
            )

        result: list[PlannedCatalogLine] = []
        for requirement in requirements:
            candidates = [
                offer
                for offer in offers
                if offer.category.casefold() == requirement.category
                and (
                    requirement.substitute_group is None
                    or offer.substitute_group == requirement.substitute_group
                )
                and offer.stock >= requirement.quantity
            ]
            if not candidates:
                return None
            selected = min(
                candidates,
                key=lambda offer: (
                    offer.price.minor,
                    -offer.rating,
                    offer.product_id,
                ),
            )
            result.append(PlannedCatalogLine(selected.product_id, requirement.quantity))
        return tuple(result)

    @staticmethod
    def _gift_lines(
        request: CatalogSearchRequest,
        offers: list[ProductOffer],
        spendable: int,
    ) -> tuple[PlannedCatalogLine, ...] | None:
        candidates = [
            offer
            for offer in offers
            if "gift" in {tag.casefold() for tag in offer.tags}
            and CatalogPlanningAgent._age_compatible(offer.tags, request.recipient_age)
        ]
        candidates.sort(
            key=lambda offer: (
                -offer.rating,
                offer.price.minor,
                offer.product_id,
            )
        )
        if not candidates:
            return None

        quantities: dict[str, int] = defaultdict(int)
        remaining = spendable
        for index in range(request.participants):
            people_left = request.participants - index
            affordable_average = remaining // people_left
            available = [
                offer
                for offer in candidates
                if quantities[offer.product_id] < offer.stock
                and offer.price.minor <= affordable_average
            ]
            if not available:
                return None
            # Rotate equally-rated candidates to avoid assigning everyone the
            # same present when the catalog has safe variety.
            selected = available[index % len(available)]
            quantities[selected.product_id] += 1
            remaining -= selected.price.minor
        return tuple(
            PlannedCatalogLine(product_id, quantity)
            for product_id, quantity in sorted(quantities.items())
        )

    @staticmethod
    def _age_compatible(tags: frozenset[str], age: int | None) -> bool:
        if age is None:
            return False
        ranges = []
        for tag in tags:
            match = _AGE_TAG.fullmatch(tag.casefold())
            if match:
                ranges.append((int(match.group("minimum")), int(match.group("maximum"))))
        return any(minimum <= age <= maximum for minimum, maximum in ranges)


def plan_savings_ratio(plan: CatalogPlan, budget: Money) -> Decimal:
    """Small audit metric used by scoring/evaluation without float drift."""

    if plan.subtotal.currency != budget.currency or budget.minor <= 0:
        raise DomainError("Plan and budget currencies must match")
    return Decimal(budget.minor - plan.subtotal.minor) / Decimal(budget.minor)


__all__ = [
    "CatalogPlan",
    "CatalogPlanNotFound",
    "CatalogPlanningAgent",
    "CatalogSearchRequest",
    "PlannedCatalogLine",
    "ProductOffer",
    "plan_savings_ratio",
]
