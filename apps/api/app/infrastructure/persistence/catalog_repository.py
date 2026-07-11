"""SQLite adapter for catalog search and availability reads."""

from __future__ import annotations

import unicodedata

from app.application.catalog_service import (
    CatalogOffer,
    CatalogPage,
    CatalogQuery,
    CatalogSort,
)
from app.database import Database


_SORT_SQL: dict[CatalogSort, str] = {
    "price_asc": "price_cents ASC, product_name COLLATE NOCASE, store_name COLLATE NOCASE",
    "price_desc": "price_cents DESC, product_name COLLATE NOCASE, store_name COLLATE NOCASE",
    "product": "product_name COLLATE NOCASE, price_cents ASC, store_name COLLATE NOCASE",
    "store": "store_name COLLATE NOCASE, product_name COLLATE NOCASE, price_cents ASC",
}


def _normalize_search_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


class SQLiteCatalogRepository:
    def __init__(self, database: Database):
        self._database = database

    def list_offers(self, query: CatalogQuery) -> CatalogPage:
        clauses: list[str] = []
        parameters: list[object] = []

        if query.search:
            search = _normalize_search_text(query.search)
            clauses.append(
                """
                (INSTR(NORMALIZE_CASEFOLD(product_name), ?) > 0
                 OR INSTR(NORMALIZE_CASEFOLD(brand), ?) > 0
                 OR INSTR(NORMALIZE_CASEFOLD(sku), ?) > 0
                 OR INSTR(NORMALIZE_CASEFOLD(store_name), ?) > 0)
                """
            )
            parameters.extend([search, search, search, search])
        if query.store_id:
            clauses.append("store_id = ?")
            parameters.append(query.store_id)
        if query.product_id:
            clauses.append("product_id = ?")
            parameters.append(query.product_id)
        if query.category:
            clauses.append("LOWER(category) = ?")
            parameters.append(query.category.casefold())
        if query.effective_status:
            clauses.append("effective_status = ?")
            parameters.append(query.effective_status)
        if query.available is not None:
            clauses.append("is_available = ?")
            parameters.append(int(query.available))
        if query.min_price_cents is not None:
            clauses.append("price_cents >= ?")
            parameters.append(query.min_price_cents)
        if query.max_price_cents is not None:
            clauses.append("price_cents <= ?")
            parameters.append(query.max_price_cents)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order_sql = _SORT_SQL[query.sort]

        with self._database.reader() as connection:
            connection.create_function(
                "NORMALIZE_CASEFOLD",
                1,
                _normalize_search_text,
                deterministic=True,
            )
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) AS count FROM catalog_availability {where_sql}",
                    parameters,
                ).fetchone()["count"]
            )
            rows = connection.execute(
                f"""
                SELECT store_id, store_name, city, store_status,
                       product_id, sku, product_name, brand, category, unit_label,
                       product_url,
                       price_cents, currency, price_display, quantity,
                       inventory_status, effective_status, is_available, updated_at
                FROM catalog_availability
                {where_sql}
                ORDER BY {order_sql}
                LIMIT ? OFFSET ?
                """,
                [*parameters, query.limit, query.offset],
            ).fetchall()

        offers = tuple(
            CatalogOffer(
                store_id=row["store_id"],
                store_name=row["store_name"],
                city=row["city"],
                store_status=row["store_status"],
                product_id=row["product_id"],
                sku=row["sku"],
                product_name=row["product_name"],
                brand=row["brand"],
                category=row["category"],
                unit_label=row["unit_label"],
                product_url=row["product_url"],
                price_cents=int(row["price_cents"]),
                currency=row["currency"],
                price_display=row["price_display"],
                quantity=int(row["quantity"]),
                inventory_status=row["inventory_status"],
                effective_status=row["effective_status"],
                is_available=bool(row["is_available"]),
                updated_at=row["updated_at"],
            )
            for row in rows
        )
        return CatalogPage(
            offers=offers,
            total=total,
            limit=query.limit,
            offset=query.offset,
        )
