# Kontrakt HTTP

## Konwencje

- Publiczny backend to FastAPI `Done API`, wersja `1.0.0`.
- Wszystkie identyfikatory są nieprzezroczystymi stringami z prefiksem, np.
  `mis_`, `apr_`, `del_`.
- Daty w odpowiedziach są ISO 8601. Mission deadlines zachowują timezone
  użytkownika; znaczniki audytowe są zwykle UTC.
- Kwoty w bazie są integer minor units, ale API zwraca number w major units.
- Każda odpowiedź otrzymuje `X-Request-ID`. Wartość można przekazać w request;
  bez niej API wygeneruje identyfikator.
- Odpowiedzi `/v1/*` mają `Cache-Control: no-store`.
- API nie emituje obecnie `ETag`; klient bierze wersję do `If-Match` z
  `mission.revision`.
- FastAPI udostępnia również `/docs`, `/redoc` i `/openapi.json`.

## Kształty błędów

Walidacja parametrów lub body wykonana przez FastAPI/Pydantic:

```json
{
  "error": "validation_error",
  "message": "Request validation failed",
  "fields": [
    {
      "location": "body.field",
      "message": "...",
      "type": "..."
    }
  ]
}
```

Jawne błędy HTTP endpointu, np. niepoprawny `If-Match`, mają standardowy
kształt FastAPI:

```json
{"detail":"If-Match must contain a positive mission revision"}
```

Błąd domenowy workflow:

```json
{
  "error": "workflow_conflict",
  "message": "Mission revision changed from 7 to 8"
}
```

Brak misji:

```json
{"error":"mission_not_found","message":"Mission ... was not found."}
```

Brak approval ma analogicznie `error: "approval_not_found"`.

Walidacja profilu/settings jest zwracana przez `HTTPException`, więc ma
zagnieżdżony `detail`:

```json
{
  "detail": {
    "error": "invalid_user_data",
    "message": "Unknown or inactive merchants: merchant-x"
  }
}
```

## Endpointy systemowe

### `GET /health`

Alias niewidoczny w OpenAPI: `GET /v1/health`.

Sprawdza połączenie SQLite i liczbę produktów. Nie odpytuje opcjonalnych usług OpenAI.

```json
{
  "status": "ok",
  "service": "done-api",
  "version": "1.0.0",
  "database": "ok",
  "seeded_products": 14
}
```

Status: `200` albo błąd serwera, jeżeli SQLite jest niedostępne.

### `GET /v1/runtime/capabilities`

Zwraca konfigurację i health opcjonalnych adapterów głosowych OpenAI. Endpoint
zwraca `200` również wtedy, gdy adapter raportuje `unavailable`.

```json
{
  "speech_to_text": {
    "status": "disabled",
    "detail": "Set DONE_STT_ENABLED=true to enable OpenAI speech recognition."
  },
  "realtime": {
    "status": "disabled",
    "provider": "openai",
    "model": "gpt-realtime-2",
    "detail": "Set DONE_REALTIME_ENABLED=true to enable live voice."
  },
  "demo_failures": true,
  "demo_endpoints": true
}
```

Sekcja `speech_to_text` zawiera model, status dostępności OpenAI i bezpieczny
`detail`. Sekcja `realtime` raportuje analogicznie stan sesji Live. Endpoint nie
zwraca sekcji ogólnego AI, ponieważ tekstowe misje są interpretowane
deterministycznie i nie korzystają z zewnętrznego modelu.

### `POST /v1/realtime/client-secret`

Tworzy krótko żyjący sekret do bezpośredniej sesji WebRTC. Request:

```json
{ "language": "pl-PL" }
```

Odpowiedź `200`:

```json
{
  "value": "ek_...",
  "expires_at": 1783761114,
  "model": "gpt-realtime-2",
  "voice": "marin"
}
```

`value` jest sekretem tymczasowym i nie powinien być logowany ani utrwalany.
Endpoint ma `Cache-Control: no-store`. Standardowy `OPENAI_API_KEY` nigdy nie
jest zwracany. Serwer dodaje `OpenAI-Safety-Identifier` jako stabilny hash
wewnętrznego ID. `503 realtime_unavailable` oznacza wyłączoną konfigurację,
błąd sieci, credentials, quota albo niepoprawną odpowiedź dostawcy.

## Misje

### `POST /v1/missions/text`

Request JSON:

```json
{
  "transcript": "Jutro urodziny dla 10 dzieci do 300 PLN, bez orzechów, przed 16:00.",
  "locale": "pl-PL",
  "timezone": "Europe/Warsaw"
}
```

`text` jest akceptowany jako alternatywa dla `transcript`. Transcript ma 3–4000
znaków po normalizacji. Domyślne wartości to `pl-PL` i `Europe/Warsaw`.

Status `201`; odpowiedź to `MissionDetail`. Przy domyślnej polityce `always`
misja kończy tworzenie w `approval_required`. Polityka użytkownika może
spowodować bezpośrednie, synchroniczne wykonanie i odpowiedź `completed`.

Możliwe błędy: `422` dla niepoprawnego JSON/transcriptu, `409` dla naruszenia
twardej polityki.

### `POST /v1/missions/voice`

Endpoint ma dwa realne tryby.

#### JSON compatibility mode

Przyjmuje ten sam JSON co endpoint tekstowy. Misja ma `input_mode: "voice"`, ale
nie jest uruchamiany STT. Ten tryb działa również, gdy STT jest wyłączone.

#### Multipart audio mode

`Content-Type: multipart/form-data`:

| Pole | Wymagane | Znaczenie |
| --- | --- | --- |
| `file` | tak | audio z nazwą i content type |
| `locale` | nie | domyślnie `pl-PL`, maks. 32 znaki |
| `timezone` | nie | domyślnie `Europe/Warsaw`, maks. 64 znaki |
| `language` | nie | kod STT; bez niego pierwszy segment locale |

```bash
curl -X POST http://localhost:8001/v1/missions/voice \
  -F 'file=@command.m4a;type=audio/m4a' \
  -F 'locale=pl-PL' \
  -F 'timezone=Europe/Warsaw' \
  -F 'language=pl'
```

Odpowiedź `201` to `MissionDetail` z dodatkowym polem:

```json
{
  "transcription": {
    "text": "...",
    "language": "pl",
    "duration_ms": 1585,
    "model": "gpt-4o-transcribe"
  }
}
```

Limity i błędy:

- `413` — upload przekracza `DONE_TRANSCRIPTION_MAX_UPLOAD_BYTES`;
- `422` — brak pola `file`, pusty/nieobsługiwany plik albo pusty transcript;
- `503` — STT wyłączone, OpenAI niedostępne, brak credentials/quota albo błąd dostawcy;
- `201` — transkrypcja i utworzenie misji zakończone.

### `GET /v1/missions`

Query params:

| Parametr | Wartość |
| --- | --- |
| `status` | pojedynczy status, lista po przecinku lub specjalne `active` |
| `q` | wyszukiwanie case-insensitive w title/subtitle, 1–200 znaków |
| `completed_from` | ISO date albo datetime, inclusive |
| `completed_to` | ISO date albo datetime, inclusive; sama data obejmuje cały dzień |
| `sort` | `newest`, `oldest`, `updated`, `deadline` |
| `requires_action` | boolean; `true` oznacza `approval_required` |

Statusy misji:

```text
created, transcribing, understanding, clarification_required, planning,
searching, optimizing, validating, approval_required, executing, recovering,
completed, failed, cancelled
```

Response `200`:

```json
{
  "missions": [
    {
      "id": "mis_...",
      "title": "Birthday party for 10 children",
      "subtitle": "10 children · up to 300 PLN · nut-free · by 16:00",
      "status": "approval_required",
      "current_step": 5,
      "total_steps": 6,
      "progress": 0.83,
      "latest_update": "Approve the complete basket for 200.72 PLN.",
      "created_at": "...",
      "completed_at": null,
      "recovered_failures": 0
    }
  ],
  "items": ["ten sam zestaw co missions"],
  "total": 1
}
```

`422` jest zwracane dla niepoprawnej daty, odwróconego zakresu albo nieznanego
wariantu `sort`.

### `GET /v1/missions/{mission_id}`

Response `200`, `MissionDetail`:

```text
mission
contract
basket
approval
approvals
events
metrics
delivery_options
payment_attempts
order
summary
```

Najważniejsze elementy:

- `mission.revision` służy do optimistic concurrency;
- `contract.version` rośnie po correction;
- `basket.items` zawiera ceny, alergeny, tags i informację o zamienniku;
- `approval` może być `null`, gdy policy pozwoliła na wykonanie bez interruptu;
- `delivery_options` zawiera `selected` i `available`;
- `order` i `summary` są `null` przed zakończeniem.

Brak misji: `404`.

### `GET /v1/missions/{mission_id}/events`

Query: `after_id`, integer `>= 0`, domyślnie `0`.

```json
{
  "events": [
    {
      "id": 12,
      "mission_id": "mis_...",
      "type": "product.replaced",
      "event_type": "product.replaced",
      "actor": "agent",
      "title": "Product replaced safely",
      "description": "...",
      "severity": "info",
      "payload": {},
      "created_at": "..."
    }
  ],
  "items": ["ten sam zestaw co events"],
  "cursor": 12,
  "mission_status": "recovering",
  "revision": 9,
  "updated_at": "..."
}
```

Polling powinien przekazywać poprzedni `cursor` jako następne `after_id`.

### `PUT /v1/missions/{mission_id}/delivery-option`

Request:

```json
{
  "delivery_option_id": "del_...",
  "expected_revision": 7
}
```

Alias inputu: `option_id`. `expected_revision` jest opcjonalne. Zamiast niego
można użyć `If-Match: 7`, `If-Match: "7"` albo `If-Match: W/"7"`.
`If-Match: *` jest traktowane jak brak oczekiwanej revision. Jeżeli body i
header zawierają różne revision, odpowiedzią jest `409`.

Zmiana jest dozwolona przed execution. Opcja musi należeć do misji, być
dostępna, mieścić się w deadline i budżecie. Zmiana przelicza total, zwiększa
revision, unieważnia poprzedni approval i tworzy nowy. Response `200` to
`MissionDetail`.

Błędy: `404` brak misji, `409` stale revision/niedozwolony stan/niezgodna opcja,
`422` niepoprawny request lub `If-Match`.

### `POST /v1/missions/{mission_id}/corrections`

```json
{
  "correction": "Set budget to 350 PLN",
  "expected_revision": 7
}
```

`expected_revision` i `If-Match` działają jak przy delivery selection. Obecny
deterministyczny parser korekty rozpoznaje zmianę budget, godziny deadline,
liczby dzieci oraz constraints `no nuts`/`no plastic`. Nie jest to ogólny
interpreter dowolnej korekty.

Korekta zachowuje mission ID, tworzy kolejną wersję kontraktu, zwiększa revision
i wymaga świeżego approval. Jeśli istniejący koszyk nie spełnia nowego hard
constraint, operacja kończy się `409` zamiast automatycznego re-planningu.

### `POST /v1/missions/{mission_id}/cancel`

Brak body. Response `200` to `MissionDetail` ze statusem `cancelled`. Ponowne
cancel jest idempotentne. Misji `completed`/`failed` nie można anulować (`409`).

## Approvals

### `POST /v1/approvals/{approval_id}/resolve`

```json
{
  "choice": "approve",
  "voice_transcript": null
}
```

`choice`: `approve`, `review` albo `cancel`.

- `approve` uruchamia synchroniczne execution i zwraca wynikowy `MissionDetail`;
- `review` zapisuje event i pozostawia approval jako pending;
- `cancel` anuluje approval, misję i koszyk;
- powtórzenie tej samej rozstrzygniętej decyzji jest idempotentne;
- approval jest sprawdzane pod kątem `expires_at`; wygasłe zwraca `409`.

Brak approval: `404`; konflikt lub inna decyzja po resolve: `409`.

## Demo controls

Endpointy zwracają `404`, gdy `DONE_DEMO_ENDPOINTS_ENABLED=false`.

### `POST /v1/demo/failures`

Status `201`.

```json
{
  "mission_id": "mis_...",
  "failure_type": "payment_soft_decline"
}
```

Typy:

```text
product_unavailable, out_of_stock, price_changed, delivery_slot_lost,
payment_soft_decline, payment_hard_decline
```

`out_of_stock` jest aliasem `product_unavailable`. Powtórzenie już queued failure
zwraca istniejący rekord z `already_queued: true`.

### `POST /v1/demo/reset`

Status `200`. Brak wymaganego body. Usuwa misje i odtwarza seed użytkownika, ustawień,
merchantów i produktów.

```json
{
  "status": "reset",
  "missions_deleted": 3,
  "seeded_products": 14
}
```

## Profil i ustawienia

### `GET /v1/users/me`

```json
{
  "id": "demo-user",
  "name": "Pawel",
  "email": "pawel@example.com",
  "locale": "pl-PL",
  "currency": "PLN",
  "timezone": "Europe/Warsaw",
  "autonomy_level": "balanced",
  "delivery_address": {
    "label": "Home",
    "line1": "ul. Marszałkowska 1",
    "city": "Warsaw",
    "postal_code": "00-001",
    "country": "PL"
  },
  "payment_method": {
    "token": "pm_demo_visa_4242",
    "brand": "Visa",
    "last4": "4242",
    "expiry_month": 12,
    "expiry_year": 2028,
    "is_demo": true
  },
  "default_constraints": [
    "Never exceed the mission budget",
    "Never relax allergen constraints",
    "Deliver before the stated deadline"
  ],
  "contact_preference": "only_when_needed",
  "stats": {"missions": 0, "recoveries": 0, "saved": 0.0}
}
```

`stats.saved` sumuje dodatnią różnicę budżet–koszyk dla zakończonych misji w
walucie profilu.

### `PATCH /v1/users/me`

Partial JSON. Dozwolone pola:

```text
name, email, locale, currency, timezone, autonomy_level,
delivery_address, payment_method, default_constraints, contact_preference
```

Nested `delivery_address` i `payment_method` również są partial. Payment method
akceptuje wyłącznie `token`, `brand`, `last4`, `expiry_month`, `expiry_year` i
`is_demo`; surowe dane karty oraz nieznane pola zwracają `422`.

`contact_preference`:

```text
only_when_needed, important_updates, all_updates
```

Response `200` ma ten sam kształt co GET.

### `GET /v1/users/me/settings`

```json
{
  "voice_language": "en-PL",
  "confirmation_voice_enabled": true,
  "safe_recovery_enabled": true,
  "approval_policy": "always",
  "approval_threshold": 0.0,
  "notifications_enabled": true,
  "preferred_merchant_ids": ["merchant-b"]
}
```

### `PATCH /v1/users/me/settings`

Partial JSON z tym samym zestawem pól. `approval_policy`:

```text
always, above_threshold, autonomous_low_risk
```

`approval_threshold` jest number w major units. Dla `above_threshold` musi być
większe od zera. Preferred merchant IDs muszą istnieć i być aktywne.

### `GET /v1/merchants`

```json
{
  "merchants": [
    {
      "id": "merchant-b",
      "name": "Party Market",
      "reliability_score": 0.94,
      "payment_success_rate": 0.96,
      "delivery_success_rate": 0.95,
      "active": true,
      "preferred": true
    }
  ],
  "items": ["ten sam zestaw co merchants"],
  "total": 3
}
```

### `GET /v1/users/me/export`

```json
{
  "schema_version": 1,
  "generated_at": "...",
  "profile": {"...": "pełny UserProfileResponse"},
  "settings": {"...": "pełny UserSettingsResponse"}
}
```

## Serwerowa granica STT

Aplikacja mobilna nie wywołuje OpenAI bezpośrednio dla nagrań plikowych. Wysyła
multipart do `/v1/missions/voice`, a `OpenAITranscriptionAdapter` przekazuje
audio do `POST /v1/audio/transcriptions` z modelem `gpt-4o-transcribe`.
Standardowy `OPENAI_API_KEY` pozostaje wyłącznie po stronie API. Odpowiedź
dostawcy jest mapowana na publiczne pole `transcription`, a treści błędów
dostawcy i credentials nie są zwracane klientowi.
