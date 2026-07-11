"""Application contracts and use cases for the mock store catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


CatalogEffectiveStatus = Literal[
    "available",
    "low_stock",
    "out_of_stock",
    "discontinued",
    "store_unavailable",
]
CatalogSort = Literal["price_asc", "price_desc", "product", "store"]


@dataclass(frozen=True, slots=True)
class CatalogOffer:
    store_id: str
    store_name: str
    city: str
    store_status: str
    product_id: str
    sku: str
    product_name: str
    brand: str
    category: str
    unit_label: str
    product_url: str
    price_cents: int
    currency: str
    price_display: str
    quantity: int
    inventory_status: str
    effective_status: str
    is_available: bool
    updated_at: str


@dataclass(frozen=True, slots=True)
class CatalogQuery:
    search: str | None = None
    store_id: str | None = None
    product_id: str | None = None
    category: str | None = None
    effective_status: CatalogEffectiveStatus | None = None
    available: bool | None = None
    min_price_cents: int | None = None
    max_price_cents: int | None = None
    sort: CatalogSort = "product"
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True, slots=True)
class CatalogPage:
    offers: tuple[CatalogOffer, ...]
    total: int
    limit: int
    offset: int


class CatalogRepository(Protocol):
    def list_offers(self, query: CatalogQuery) -> CatalogPage: ...


class CatalogApplicationService:
    def __init__(self, repository: CatalogRepository):
        self._repository = repository

    def list_offers(
        self,
        *,
        search: str | None = None,
        store_id: str | None = None,
        product_id: str | None = None,
        category: str | None = None,
        effective_status: CatalogEffectiveStatus | None = None,
        available: bool | None = None,
        min_price_cents: int | None = None,
        max_price_cents: int | None = None,
        sort: CatalogSort = "product",
        limit: int = 50,
        offset: int = 0,
    ) -> CatalogPage:
        if (
            min_price_cents is not None
            and max_price_cents is not None
            and min_price_cents > max_price_cents
        ):
            raise ValueError("min_price_cents cannot be greater than max_price_cents")

        return self._repository.list_offers(
            CatalogQuery(
                search=search.strip() if search else None,
                store_id=store_id,
                product_id=product_id,
                category=category.strip() if category else None,
                effective_status=effective_status,
                available=available,
                min_price_cents=min_price_cents,
                max_price_cents=max_price_cents,
                sort=sort,
                limit=limit,
                offset=offset,
            )
        )
