from __future__ import annotations

import pytest

from app.domain.common import Money
from app.domain.mission.catalog import (
    CatalogPlanNotFound,
    CatalogPlanningAgent,
    CatalogSearchRequest,
    ProductOffer,
)
from app.domain.mission.intake import ShoppingScope
from app.domain.mission.model import Constraint, ConstraintKind


def offer(
    product_id: str,
    category: str,
    price: int,
    *,
    merchant: str = "merchant-a",
    tags: tuple[str, ...] = (),
    allergens: tuple[str, ...] = (),
    group: str | None = None,
    stock: int = 20,
) -> ProductOffer:
    return ProductOffer(
        product_id=product_id,
        merchant_id=merchant,
        merchant_reliability=0.95,
        category=category,
        price=Money(price, "PLN"),
        stock=stock,
        allergens=frozenset(allergens),
        tags=frozenset(tags),
        rating=4.8,
        substitute_group=group,
    )


def gift_request(*constraints: Constraint) -> CatalogSearchRequest:
    return CatalogSearchRequest(
        scope=ShoppingScope.GIFTS,
        participants=5,
        recipient_age=10,
        budget=Money(50_000, "PLN"),
        delivery_reserve=Money(1_299, "PLN"),
        allowed_categories=frozenset({"books", "games", "creative"}),
        forbidden_categories=frozenset(),
        hard_constraints=constraints,
    )


def test_gift_search_uses_age_stock_budget_and_real_offers() -> None:
    offers = (
        offer("book", "books", 3_999, tags=("gift", "age-9-12", "vegan")),
        offer("game", "games", 6_499, tags=("gift", "age-8-12", "vegan")),
        offer("toddler", "games", 999, tags=("gift", "age-3-5", "vegan")),
    )

    plan = CatalogPlanningAgent().plan(gift_request(), offers)

    assert sum(line.quantity for line in plan.lines) == 5
    assert all(line.product_id != "toddler" for line in plan.lines)
    assert plan.subtotal.add(Money(1_299, "PLN")).minor <= 50_000


def test_unknown_hard_constraint_fails_closed() -> None:
    request = gift_request(
        Constraint(ConstraintKind.CUSTOM, "require", "certified-fair-trade")
    )
    offers = (offer("book", "books", 3_999, tags=("gift", "age-9-12")),)

    with pytest.raises(CatalogPlanNotFound, match="cannot prove"):
        CatalogPlanningAgent().plan(request, offers)


def test_vegan_filter_never_accepts_an_unverified_offer() -> None:
    request = gift_request(Constraint(ConstraintKind.CUSTOM, "require", "vegan"))
    offers = (
        offer("unknown", "books", 2_000, tags=("gift", "age-9-12")),
        offer("verified", "books", 3_000, tags=("gift", "age-9-12", "vegan")),
    )

    plan = CatalogPlanningAgent().plan(request, offers)

    assert {line.product_id for line in plan.lines} == {"verified"}


def test_material_constraint_blocks_incomplete_catalog_coverage() -> None:
    request = gift_request(Constraint(ConstraintKind.MATERIAL, "exclude", "plastic"))
    offers = (offer("plastic", "books", 2_000, tags=("gift", "age-9-12")),)

    with pytest.raises(CatalogPlanNotFound):
        CatalogPlanningAgent().plan(request, offers)
