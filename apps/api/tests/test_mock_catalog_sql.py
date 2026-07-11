from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


CATALOG_SQL = Path(__file__).resolve().parents[1] / "sql" / "mock_catalog.sql"


def test_mock_catalog_import_is_repeatable_and_consistent(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "mock_catalog.sqlite3")
    connection.row_factory = sqlite3.Row
    sql = CATALOG_SQL.read_text(encoding="utf-8")

    try:
        connection.executescript(sql)
        connection.executescript(sql)

        assert connection.execute(
            "SELECT COUNT(*) FROM catalog_stores"
        ).fetchone()[0] == 5
        assert connection.execute(
            "SELECT COUNT(*) FROM catalog_products"
        ).fetchone()[0] == 20
        assert connection.execute(
            "SELECT COUNT(*) FROM catalog_offers"
        ).fetchone()[0] == 54

        statuses = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT availability_status FROM catalog_offers"
            )
        }
        assert statuses == {
            "available",
            "low_stock",
            "out_of_stock",
            "discontinued",
        }

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

        closed_store_rows = connection.execute(
            """
            SELECT COUNT(*)
            FROM catalog_availability
            WHERE store_id = 'store-weekend'
              AND effective_status = 'store_unavailable'
              AND is_available = 0
            """
        ).fetchone()[0]
        assert closed_store_rows == 5

        lowest_available_water_price = connection.execute(
            """
            SELECT MIN(price_cents)
            FROM catalog_availability
            WHERE product_id = 'product-water' AND is_available = 1
            """
        ).fetchone()[0]
        assert lowest_available_water_price == 299

        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                UPDATE catalog_offers
                SET availability_status = 'available', quantity = 0
                WHERE store_id = 'store-budget' AND product_id = 'product-water'
                """
            )
    finally:
        connection.close()
