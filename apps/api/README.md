# Done demo API

Deterministic FastAPI backend for the mobile demo. It uses only the Python
standard-library SQLite driver, so no database service is required.

```bash
cd apps/api
uv sync --python 3.13 --extra dev
uv run uvicorn app.main:app --reload --port 8001
```

The database defaults to `apps/api/done.sqlite3`. Override it with
`DONE_DB_PATH=/absolute/path/to/file.sqlite3`.

## Mock store catalog

`sql/mock_catalog.sql` contains an idempotent SQLite schema and mock data for
stores, products, store-specific prices, inventory quantities, statuses and
availability. Prices use integer minor units (`1299` means `12.99 PLN`). The API
loads this catalog automatically when it initializes a database.

Create a separate mock catalog database:

```bash
cd apps/api
sqlite3 mock_catalog.sqlite3 < sql/mock_catalog.sql
```

Inspect products that can currently be purchased, ordered by price:

```bash
sqlite3 -header -column mock_catalog.sqlite3 \
  "SELECT store_name, product_name, price_display, quantity, effective_status \
   FROM catalog_availability \
   WHERE is_available = 1 \
   ORDER BY price_cents, product_name;"
```

The source tables are `catalog_stores`, `catalog_products` and
`catalog_offers`. Query `catalog_availability` when you need the effective
status: it also marks stocked products unavailable when their store is closed.

The same data is available through `GET /v1/catalog/offers`. Filters compose
with one another:

```bash
curl "http://localhost:8001/v1/catalog/offers?category=drinks&available=true&sort=price_asc"
```

Supported filters are `q`, `store_id`, `product_id`, `category`,
`effective_status`, `available`, `min_price_cents`, `max_price_cents`, `sort`,
`limit` and `offset`.

Main endpoints:

- `GET /health`
- `GET /v1/catalog/offers`
- `POST /v1/missions/text`
- `POST /v1/missions/voice`
- `GET /v1/missions`
- `GET /v1/missions/{mission_id}`
- `GET /v1/missions/{mission_id}/events?after_id=0`
- `PUT /v1/missions/{mission_id}/delivery-option`
- `POST /v1/missions/{mission_id}/corrections`
- `POST /v1/approvals/{approval_id}/resolve`
- `POST /v1/demo/failures`
- `POST /v1/demo/reset`
- `GET|PATCH /v1/users/me`
- `GET|PATCH /v1/users/me/settings`
- `GET /v1/users/me/export`
- `GET /v1/merchants`

Both creation endpoints accept JSON such as:

```json
{
  "transcript": "Jutro urodziny dla 10 dzieci, do 300 PLN, bez orzechów, dostawa przed 16:00",
  "locale": "pl-PL",
  "timezone": "Europe/Warsaw"
}
```

Mission creation returns the same aggregate as the detail endpoint. Mission
lists use `{ "missions": [...], "items": [...], "total": 1 }`, where each
entry has `id`, `title`, `subtitle`, `status`, `current_step`, `total_steps`,
`progress`, `latest_update`, `created_at`, `completed_at` and
`recovered_failures`.

Approve the deterministic purchase with:

```json
POST /v1/approvals/{approval_id}/resolve
{"choice":"approve"}
```

The response is already completed and includes the full event sequence for UI
animation: unavailable product, compliant substitution, retryable PSP_A decline,
reroute to PSP_B and order confirmation. Poll incremental events with
`GET /v1/missions/{mission_id}/events?after_id={cursor}`.

Mission lists support `status`, `q`, `completed_from`, `completed_to`, `sort`
(`newest`, `oldest`, `updated`, `deadline`) and `requires_action`. Corrections
and delivery changes accept an optional `expected_revision`; clients may instead
send `If-Match: "{revision}"`. A stale revision returns `409` and every material
plan change replaces the pending approval.

## User profile and settings

The demo user profile is persisted in SQLite. PATCH requests are partial,
including nested address and tokenized payment-method fields. Raw card data and
unknown fields are rejected with `422`.

`GET /v1/users/me` includes live statistics derived from persisted missions:
mission count, successfully recovered failures and the amount left under budget
for completed missions. `approval_threshold` in settings uses major currency
units. `GET /v1/users/me/export` returns the versioned profile/settings export.
