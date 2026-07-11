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
    "product_url",
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

    assert payload["total"] == 140
    assert payload["limit"] == 150
    assert payload["offset"] == 0
    assert len(payload["offers"]) == 140
    assert payload["items"] == payload["offers"]
    assert set(payload["offers"][0]) == OFFER_KEYS
    assert isinstance(payload["offers"][0]["is_available"], bool)
    assert payload["offers"][0]["product_url"].startswith("https://")
    assert payload["offers"][0]["price_cents"] >= 0
    assert payload["offers"][0]["quantity"] >= 0
    banana = next(
        offer
        for offer in payload["offers"]
        if offer["store_id"] == "store-delio"
        and offer["product_id"] == "product-delio-a0000718"
    )
    assert banana["price_cents"] == 589
    assert banana["price"] == 5.89
    assert banana["price_display"] == "5.89 PLN"
    assert banana["quantity"] == 199
    assert banana["effective_status"] == "available"
    assert banana["product_url"] == "https://delio.com.pl/products/A0000718-banan"


def test_catalog_filters_store_category_and_availability(client: TestClient) -> None:
    response = client.get(
        "/v1/catalog/offers",
        params={
            "store_id": "store-delio",
            "category": "fruit",
            "available": "true",
            "sort": "price_asc",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["total"] == 15
    assert payload["offers"][0]["price_cents"] == 219
    assert all(offer["store_id"] == "store-delio" for offer in payload["offers"])
    assert all(offer["category"] == "fruit" for offer in payload["offers"])
    assert all(offer["is_available"] for offer in payload["offers"])


def test_catalog_exposes_low_and_out_of_stock_offers(client: TestClient) -> None:
    unavailable = client.get(
        "/v1/catalog/offers", params={"effective_status": "out_of_stock"}
    )
    assert unavailable.status_code == 200, unavailable.text
    unavailable_payload = unavailable.json()

    assert unavailable_payload["total"] == 7
    assert all(not offer["is_available"] for offer in unavailable_payload["offers"])
    assert all(offer["quantity"] == 0 for offer in unavailable_payload["offers"])
    assert {offer["store_id"] for offer in unavailable_payload["offers"]} == {
        "store-delio",
        "store-lidl",
    }

    available_banana = client.get(
        "/v1/catalog/offers",
        params={
            "product_id": "product-delio-a0000718",
            "available": "true",
            "sort": "price_asc",
        },
    ).json()
    assert available_banana["total"] == 1
    assert available_banana["offers"][0]["price_cents"] == 589

    low_stock = client.get(
        "/v1/catalog/offers", params={"effective_status": "low_stock"}
    ).json()
    assert low_stock["total"] == 5


def test_catalog_search_price_range_and_pagination(client: TestClient) -> None:
    search = client.get("/v1/catalog/offers", params={"q": "CzuCzu"})
    assert search.status_code == 200
    assert search.json()["total"] == 1
    assert search.json()["offers"][0]["sku"] == "SMYK-8103798"

    minecraft = client.get(
        "/v1/catalog/offers", params={"q": "Minecraft", "limit": 150}
    )
    assert minecraft.status_code == 200
    assert minecraft.json()["total"] == 29
    assert len(minecraft.json()["offers"]) == 29

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

    invalid_limit = client.get("/v1/catalog/offers", params={"limit": 151})
    assert invalid_limit.status_code == 422

    invalid_range = client.get(
        "/v1/catalog/offers",
        params={"min_price_cents": 2000, "max_price_cents": 1000},
    )
    assert invalid_range.status_code == 422
    assert invalid_range.json()["detail"]["error"] == "invalid_catalog_query"
