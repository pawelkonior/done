#!/usr/bin/env python3
"""Generate the API-ready birthday catalog JSON and standalone SQLite seed."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any


API_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = API_ROOT / "data" / "child_birthday_catalog_research.tsv"
JSON_PATH = API_ROOT / "data" / "child_birthday_catalog.json"
SQL_PATH = API_ROOT / "sql" / "mock_catalog.sql"

INVENTORY_STATUSES = {"available", "low_stock", "out_of_stock", "discontinued"}
STORE_STATUSES = {"open", "temporarily_closed", "inactive"}


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if not normalized:
        raise ValueError(f"cannot derive an identifier from {value!r}")
    return normalized


def _read_source() -> list[dict[str, str]]:
    with SOURCE_PATH.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not 100 <= len(rows) <= 150:
        raise ValueError(f"catalog must contain 100-150 rows, got {len(rows)}")
    return rows


def build_offers(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    offers: list[dict[str, Any]] = []
    seen_skus: set[str] = set()
    seen_urls: set[str] = set()

    for index, row in enumerate(rows, start=2):
        missing = [key for key, value in row.items() if value is None or not value.strip()]
        if missing:
            raise ValueError(f"row {index}: empty fields: {', '.join(missing)}")

        store_status = row["store_status"]
        inventory_status = row["inventory_status"]
        if store_status not in STORE_STATUSES:
            raise ValueError(f"row {index}: unsupported store_status {store_status!r}")
        if inventory_status not in INVENTORY_STATUSES:
            raise ValueError(
                f"row {index}: unsupported inventory_status {inventory_status!r}"
            )

        price_cents = int(row["price_cents"])
        quantity = int(row["quantity"])
        if price_cents < 0 or quantity < 0:
            raise ValueError(f"row {index}: price and quantity must be non-negative")
        if inventory_status == "available" and quantity < 6:
            raise ValueError(f"row {index}: available offers require quantity >= 6")
        if inventory_status == "low_stock" and not 1 <= quantity <= 5:
            raise ValueError(f"row {index}: low_stock offers require quantity 1-5")
        if inventory_status in {"out_of_stock", "discontinued"} and quantity != 0:
            raise ValueError(f"row {index}: unavailable offers require quantity 0")

        if row["sku"] in seen_skus:
            raise ValueError(f"row {index}: duplicate sku {row['sku']!r}")
        if row["product_url"] in seen_urls:
            raise ValueError(f"row {index}: duplicate product_url {row['product_url']!r}")
        if not row["product_url"].startswith("https://"):
            raise ValueError(f"row {index}: product_url must use HTTPS")
        seen_skus.add(row["sku"])
        seen_urls.add(row["product_url"])

        effective_status = (
            inventory_status if store_status == "open" else "store_unavailable"
        )
        is_available = (
            store_status == "open"
            and inventory_status in {"available", "low_stock"}
            and quantity > 0
        )
        store_key = _slug(row["store_id"].removeprefix("store-"))
        product_id = f"product-{store_key}-{_slug(row['sku'])}"
        offers.append(
            {
                "store_id": row["store_id"],
                "store_name": row["store_name"],
                "city": row["city"],
                "store_status": store_status,
                "product_id": product_id,
                "sku": row["sku"],
                "product_name": row["product_name"],
                "brand": row["brand"],
                "category": row["category"],
                "unit_label": row["unit_label"],
                "product_url": row["product_url"],
                "price_cents": price_cents,
                "currency": "PLN",
                "price": price_cents / 100,
                "price_display": f"{price_cents / 100:.2f} PLN",
                "quantity": quantity,
                "inventory_status": inventory_status,
                "effective_status": effective_status,
                "is_available": is_available,
                "updated_at": row["updated_at"],
            }
        )
    return offers


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_values(rows: list[tuple[object, ...]]) -> str:
    return ",\n".join(
        "    (" + ", ".join(_sql_quote(str(value)) for value in row) + ")"
        for row in rows
    )


def render_sql(offers: list[dict[str, Any]]) -> str:
    stores: dict[str, tuple[object, ...]] = {}
    products: list[tuple[object, ...]] = []
    offer_rows: list[tuple[object, ...]] = []

    for offer in offers:
        store_id = offer["store_id"]
        store = (
            store_id,
            _slug(store_id.removeprefix("store-")),
            offer["store_name"],
            offer["city"],
            "PL",
            offer["store_status"],
            offer["updated_at"],
            offer["updated_at"],
        )
        previous = stores.get(store_id)
        if previous is None:
            stores[store_id] = store
        elif previous[:6] != store[:6]:
            raise ValueError(f"inconsistent store metadata for {store_id}")
        else:
            stores[store_id] = (
                *previous[:6],
                min(str(previous[6]), offer["updated_at"]),
                max(str(previous[7]), offer["updated_at"]),
            )

        description = (
            f"Researched birthday catalog product from {offer['store_name']}; "
            f"price observed on {offer['updated_at'][:10]}."
        )
        products.append(
            (
                offer["product_id"],
                offer["sku"],
                offer["product_name"],
                offer["brand"],
                offer["category"],
                offer["unit_label"],
                description,
                offer["updated_at"],
                offer["updated_at"],
            )
        )
        offer_rows.append(
            (
                store_id,
                offer["product_id"],
                offer["product_url"],
                offer["price_cents"],
                offer["currency"],
                offer["quantity"],
                offer["inventory_status"],
                offer["updated_at"],
            )
        )

    return f"""-- Generated by scripts/generate_birthday_catalog.py. Do not edit by hand.
-- Prices and URLs are a research snapshot; non-Delio quantities are demo inventory.
-- Money is stored in minor units: 1299 means 12.99 PLN.

PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

DROP VIEW IF EXISTS catalog_availability;
DROP TABLE IF EXISTS catalog_offers;
DROP TABLE IF EXISTS catalog_products;
DROP TABLE IF EXISTS catalog_stores;

CREATE TABLE catalog_stores (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    country_code TEXT NOT NULL DEFAULT 'PL' CHECK (length(country_code) = 2),
    status TEXT NOT NULL CHECK (status IN ('open', 'temporarily_closed', 'inactive')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE catalog_products (
    id TEXT PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    brand TEXT NOT NULL,
    category TEXT NOT NULL,
    unit_label TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE catalog_offers (
    store_id TEXT NOT NULL REFERENCES catalog_stores(id) ON DELETE CASCADE,
    product_id TEXT NOT NULL REFERENCES catalog_products(id) ON DELETE CASCADE,
    product_url TEXT NOT NULL CHECK (product_url GLOB 'https://*'),
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    currency TEXT NOT NULL DEFAULT 'PLN' CHECK (length(currency) = 3),
    quantity INTEGER NOT NULL CHECK (quantity >= 0),
    availability_status TEXT NOT NULL CHECK (
        availability_status IN ('available', 'low_stock', 'out_of_stock', 'discontinued')
    ),
    is_available INTEGER GENERATED ALWAYS AS (
        CASE
            WHEN availability_status IN ('available', 'low_stock') AND quantity > 0 THEN 1
            ELSE 0
        END
    ) STORED,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (store_id, product_id),
    CHECK (
        (availability_status = 'available' AND quantity >= 6)
        OR (availability_status = 'low_stock' AND quantity BETWEEN 1 AND 5)
        OR (availability_status IN ('out_of_stock', 'discontinued') AND quantity = 0)
    )
);

CREATE INDEX idx_catalog_products_category ON catalog_products(category, name);
CREATE INDEX idx_catalog_offers_product_price ON catalog_offers(product_id, price_cents);
CREATE INDEX idx_catalog_offers_status ON catalog_offers(availability_status, store_id);

INSERT INTO catalog_stores
    (id, slug, name, city, country_code, status, created_at, updated_at)
VALUES
{_sql_values(sorted(stores.values()))};

INSERT INTO catalog_products
    (id, sku, name, brand, category, unit_label, description, created_at, updated_at)
VALUES
{_sql_values(products)};

INSERT INTO catalog_offers
    (store_id, product_id, product_url, price_cents, currency, quantity,
     availability_status, updated_at)
VALUES
{_sql_values(offer_rows)};

CREATE VIEW catalog_availability AS
SELECT
    s.id AS store_id,
    s.name AS store_name,
    s.city,
    s.status AS store_status,
    p.id AS product_id,
    p.sku,
    p.name AS product_name,
    p.brand,
    p.category,
    p.unit_label,
    o.product_url,
    o.price_cents,
    o.currency,
    ROUND(o.price_cents / 100.0, 2) AS price,
    printf('%.2f %s', o.price_cents / 100.0, o.currency) AS price_display,
    o.quantity,
    o.availability_status AS inventory_status,
    CASE
        WHEN s.status <> 'open' THEN 'store_unavailable'
        ELSE o.availability_status
    END AS effective_status,
    CASE
        WHEN s.status = 'open' AND o.is_available = 1 THEN 1
        ELSE 0
    END AS is_available,
    o.updated_at
FROM catalog_offers AS o
JOIN catalog_stores AS s ON s.id = o.store_id
JOIN catalog_products AS p ON p.id = o.product_id;

COMMIT;
"""


def render_json(offers: list[dict[str, Any]]) -> str:
    return json.dumps(offers, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when generated artifacts differ instead of rewriting them",
    )
    args = parser.parse_args()

    offers = build_offers(_read_source())
    generated = {
        JSON_PATH: render_json(offers),
        SQL_PATH: render_sql(offers),
    }
    stale = [
        path
        for path, content in generated.items()
        if not path.exists() or path.read_text(encoding="utf-8") != content
    ]
    if args.check:
        if stale:
            print("stale generated catalog files:")
            for path in stale:
                print(f"- {path.relative_to(API_ROOT)}")
            return 1
        print(f"catalog artifacts are current ({len(offers)} offers)")
        return 0

    for path, content in generated.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    print(f"generated {len(offers)} offers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
