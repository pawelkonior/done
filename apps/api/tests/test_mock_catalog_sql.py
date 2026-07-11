from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


CATALOG_SQL = Path(__file__).resolve().parents[1] / "sql" / "mock_catalog.sql"
CATALOG_JSON = (
    Path(__file__).resolve().parents[1] / "data" / "child_birthday_catalog.json"
)


def test_mock_catalog_import_is_repeatable_and_consistent(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "mock_catalog.sqlite3")
    connection.row_factory = sqlite3.Row
    sql = CATALOG_SQL.read_text(encoding="utf-8")

    try:
        connection.executescript(sql)
        connection.executescript(sql)

        assert connection.execute("SELECT COUNT(*) FROM catalog_stores").fetchone()[0] == 7
        assert connection.execute(
            "SELECT COUNT(*) FROM catalog_products"
        ).fetchone()[0] == 140
        assert connection.execute("SELECT COUNT(*) FROM catalog_offers").fetchone()[0] == 140

        statuses = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT availability_status FROM catalog_offers"
            )
        }
        assert statuses == {"available", "low_stock", "out_of_stock"}

        inconsistent_offer_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM catalog_offers
            WHERE is_available != CASE
                WHEN availability_status IN ('available', 'low_stock')
                     AND quantity > 0
                THEN 1
                ELSE 0
            END
            """
        ).fetchone()[0]
        assert inconsistent_offer_count == 0

        unavailable_rows = connection.execute(
            """
            SELECT COUNT(*)
            FROM catalog_availability
            WHERE effective_status = 'out_of_stock'
              AND is_available = 0
            """
        ).fetchone()[0]
        assert unavailable_rows == 7

        banana_price = connection.execute(
            """
            SELECT price_cents
            FROM catalog_availability
            WHERE product_id = 'product-delio-a0000718' AND is_available = 1
            """
        ).fetchone()[0]
        assert banana_price == 589

        invalid_urls = connection.execute(
            "SELECT COUNT(*) FROM catalog_offers WHERE product_url NOT GLOB 'https://*'"
        ).fetchone()[0]
        assert invalid_urls == 0

        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                UPDATE catalog_offers
                SET availability_status = 'available', quantity = 0
                WHERE store_id = 'store-delio'
                  AND product_id = 'product-delio-a0000718'
                """
            )
    finally:
        connection.close()


def test_json_dataset_matches_sql_projection(tmp_path: Path) -> None:
    dataset = json.loads(CATALOG_JSON.read_text(encoding="utf-8"))
    assert len(dataset) == 140
    assert len({row["sku"] for row in dataset}) == 140
    assert len({row["product_url"] for row in dataset}) == 140
    assert {row["category"] for row in dataset}.issuperset(
        {"tableware", "cakes", "sweets", "fruit", "gifts"}
    )
    minecraft = [
        row
        for row in dataset
        if "minecraft" in f"{row['product_name']} {row['brand']}".casefold()
    ]
    assert len(minecraft) == 29
    assert {row["store_name"] for row in minecraft}.issuperset(
        {"Allegro", "Kaufland Marketplace", "Lidl", "Smyk"}
    )

    connection = sqlite3.connect(tmp_path / "catalog.sqlite3")
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(CATALOG_SQL.read_text(encoding="utf-8"))
        rows = connection.execute(
            """
            SELECT store_id, product_id, sku, product_url, price_cents, quantity,
                   inventory_status, effective_status, is_available
            FROM catalog_availability
            ORDER BY store_id, product_id
            """
        ).fetchall()
    finally:
        connection.close()

    projected_json = sorted(
        (
            row["store_id"],
            row["product_id"],
            row["sku"],
            row["product_url"],
            row["price_cents"],
            row["quantity"],
            row["inventory_status"],
            row["effective_status"],
            int(row["is_available"]),
        )
        for row in dataset
    )
    projected_sql = [tuple(row) for row in rows]
    assert projected_sql == projected_json
