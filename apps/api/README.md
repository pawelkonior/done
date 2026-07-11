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

Main endpoints:

- `GET /health`
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
