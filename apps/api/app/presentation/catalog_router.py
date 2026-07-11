"""FastAPI presentation adapter for the store catalog."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from app.application.catalog_service import (
    CatalogApplicationService,
    CatalogEffectiveStatus,
    CatalogOffer,
    CatalogSort,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CatalogOfferResponse(StrictModel):
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
    price: float
    price_display: str
    quantity: int
    inventory_status: str
    effective_status: str
    is_available: bool
    updated_at: datetime


class CatalogOfferListResponse(StrictModel):
    offers: list[CatalogOfferResponse]
    items: list[CatalogOfferResponse]
    total: int
    limit: int
    offset: int


def _offer_response(offer: CatalogOffer) -> CatalogOfferResponse:
    return CatalogOfferResponse(
        store_id=offer.store_id,
        store_name=offer.store_name,
        city=offer.city,
        store_status=offer.store_status,
        product_id=offer.product_id,
        sku=offer.sku,
        product_name=offer.product_name,
        brand=offer.brand,
        category=offer.category,
        unit_label=offer.unit_label,
        product_url=offer.product_url,
        price_cents=offer.price_cents,
        currency=offer.currency,
        price=offer.price_cents / 100,
        price_display=offer.price_display,
        quantity=offer.quantity,
        inventory_status=offer.inventory_status,
        effective_status=offer.effective_status,
        is_available=offer.is_available,
        updated_at=offer.updated_at,
    )


def create_catalog_router(service: CatalogApplicationService) -> APIRouter:
    router = APIRouter(tags=["catalog"])

    @router.get(
        "/v1/catalog/offers",
        response_model=CatalogOfferListResponse,
        summary="List store products, prices and availability",
    )
    def list_catalog_offers(
        q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
        store_id: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
        product_id: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
        category: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
        effective_status: Annotated[CatalogEffectiveStatus | None, Query()] = None,
        available: Annotated[bool | None, Query()] = None,
        min_price_cents: Annotated[int | None, Query(ge=0)] = None,
        max_price_cents: Annotated[int | None, Query(ge=0)] = None,
        sort: Annotated[CatalogSort, Query()] = "product",
        limit: Annotated[int, Query(ge=1, le=150)] = 150,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> CatalogOfferListResponse:
        try:
            page = service.list_offers(
                search=q,
                store_id=store_id,
                product_id=product_id,
                category=category,
                effective_status=effective_status,
                available=available,
                min_price_cents=min_price_cents,
                max_price_cents=max_price_cents,
                sort=sort,
                limit=limit,
                offset=offset,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"error": "invalid_catalog_query", "message": str(exc)},
            ) from exc

        offers = [_offer_response(offer) for offer in page.offers]
        return CatalogOfferListResponse(
            offers=offers,
            items=offers,
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    return router
