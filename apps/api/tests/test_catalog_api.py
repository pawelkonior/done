from __future__ import annotations

from fastapi.testclient import TestClient


OFFER_KEYS = {
    "store_id",
    "store_name",
    "city",
    "store_status",
    "product_id",
    "sku",
    "product_name",
    "brand",
    "category",
    "unit_label",
    "price_cents",
    "currency",
    "price",
    "price_display",
    "quantity",
    "inventory_status",
    "effective_status",
    "is_available",
    "updated_at",
}


def test_catalog_returns_seeded_store_offers(client: TestClient) -> None:
    response = client.get("/v1/catalog/offers")
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["total"] == 54
    assert payload["limit"] == 100
    assert payload["offset"] == 0
    assert len(payload["offers"]) == 54
    assert payload["items"] == payload["offers"]
    assert set(payload["offers"][0]) == OFFER_KEYS
    assert isinstance(payload["offers"][0]["is_available"], bool)
    assert payload["offers"][0]["price_cents"] >= 0
    assert payload["offers"][0]["quantity"] >= 0
    water = next(
        offer
        for offer in payload["offers"]
        if offer["store_id"] == "store-budget"
        and offer["product_id"] == "product-water"
    )
    assert water["price_cents"] == 299
    assert water["price"] == 2.99
    assert water["price_display"] == "2.99 PLN"
    assert water["quantity"] == 120
    assert water["effective_status"] == "available"


def test_catalog_filters_store_category_and_availability(client: TestClient) -> None:
    response = client.get(
        "/v1/catalog/offers",
        params={
            "store_id": "store-budget",
            "category": "drinks",
            "available": "true",
            "sort": "price_asc",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["total"] == 2
    assert [offer["price_cents"] for offer in payload["offers"]] == [299, 699]
    assert all(offer["store_id"] == "store-budget" for offer in payload["offers"])
    assert all(offer["is_available"] for offer in payload["offers"])


def test_catalog_uses_effective_store_availability(client: TestClient) -> None:
    closed = client.get(
        "/v1/catalog/offers",
        params={"effective_status": "store_unavailable"},
    )
    assert closed.status_code == 200, closed.text
    closed_payload = closed.json()

    assert closed_payload["total"] == 5
    assert all(offer["store_id"] == "store-weekend" for offer in closed_payload["offers"])
    assert all(not offer["is_available"] for offer in closed_payload["offers"])
    assert {
        offer["inventory_status"] for offer in closed_payload["offers"]
    } == {"available", "low_stock"}

    available_water = client.get(
        "/v1/catalog/offers",
        params={
            "product_id": "product-water",
            "available": "true",
            "sort": "price_asc",
        },
    ).json()
    assert available_water["total"] == 4
    assert available_water["offers"][0]["price_cents"] == 299

    low_stock = client.get(
        "/v1/catalog/offers", params={"effective_status": "low_stock"}
    ).json()
    assert low_stock["total"] == 6


def test_catalog_search_price_range_and_pagination(client: TestClient) -> None:
    search = client.get("/v1/catalog/offers", params={"q": "cupcakes"})
    assert search.status_code == 200
    assert search.json()["total"] == 1
    assert search.json()["offers"][0]["product_id"] == "product-cupcakes"

    ranged = client.get(
        "/v1/catalog/offers",
        params={
            "min_price_cents": 1000,
            "max_price_cents": 2000,
            "sort": "price_desc",
            "limit": 2,
            "offset": 1,
        },
    )
    assert ranged.status_code == 200, ranged.text
    payload = ranged.json()
    assert payload["total"] > 2
    assert len(payload["offers"]) == 2
    assert payload["limit"] == 2
    assert payload["offset"] == 1
    assert all(1000 <= offer["price_cents"] <= 2000 for offer in payload["offers"])


def test_catalog_empty_and_invalid_filters(client: TestClient) -> None:
    empty = client.get(
        "/v1/catalog/offers", params={"store_id": "store-does-not-exist"}
    )
    assert empty.status_code == 200
    assert empty.json()["offers"] == []
    assert empty.json()["items"] == []
    assert empty.json()["total"] == 0

    invalid_status = client.get(
        "/v1/catalog/offers", params={"effective_status": "sometimes"}
    )
    assert invalid_status.status_code == 422

    invalid_range = client.get(
        "/v1/catalog/offers",
        params={"min_price_cents": 2000, "max_price_cents": 1000},
    )
    assert invalid_range.status_code == 422
    assert invalid_range.json()["detail"]["error"] == "invalid_catalog_query"
