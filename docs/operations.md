# Operacje i uruchamianie

## Zakres

Ten runbook opisuje aktualny kod. Done działa z API, SQLite oraz opcjonalnymi
serwerowymi usługami OpenAI dla transkrypcji audio i Realtime. Określenie
**production-like** oznacza tutaj konfigurację procesu, trwałą bazę, wyłączone
mechanizmy demo i sekrety przechowywane po stronie serwera. Nie oznacza gotowości do
produkcyjnej sprzedaży: catalog, inventory, delivery, payment i order nadal są
symulatorem, a aplikacja nie ma authentication, TLS ani tenant isolation.

## Wymagania

- Node.js 20 lub nowszy i npm;
- Python 3.13 oraz `uv`;
- standardowy `OPENAI_API_KEY` tylko po stronie API, jeżeli
  `DONE_STT_ENABLED=true` lub `DONE_REALTIME_ENABLED=true`.

Proces setup instaluje zależności API i aplikacji:

```bash
npm run setup
```

## Tryb developerski

Pełny lokalny stack:

```bash
npm run dev
```

Uruchamiane są równolegle:

- API na `http://127.0.0.1:8001`;
- Expo web, zwykle na `http://localhost:8081`.

Skrypt `npm run api` włącza serwerową transkrypcję OpenAI. Realtime jest
kontrolowany przez `DONE_REALTIME_ENABLED` w środowisku. Brak połączenia z OpenAI
blokuje prawdziwe audio multipart i Live, ale nie endpoint tekstowy ani JSON
compatibility mode endpointu voice. Interpretacja tekstu jest zawsze lokalna i
deterministyczna.
Rootowy `.env` jest ładowany przez skrypt API. Nie używaj prefiksu
`EXPO_PUBLIC_` dla sekretów; wartości z tym prefiksem trafiają do bundla.

Minimalny backend bez opcjonalnych usług głosowych OpenAI:

```bash
cd apps/api
DONE_STT_ENABLED=false \
DONE_REALTIME_ENABLED=false \
uv run uvicorn app.main:app --reload --port 8001
```

## Tryb production-like

Hostowy skrypt ustawia jeden worker, włącza transkrypcję OpenAI oraz wyłącza
automatyczne awarie i endpointy demo. Realtime pozostaje sterowany przez
`DONE_REALTIME_ENABLED`:

```bash
DONE_DB_PATH=/var/lib/done/done.sqlite3 \
DONE_CORS_ORIGINS=https://app.example.com \
npm run api:production
```

Proces powinien działać za reverse proxy zapewniającym TLS, limity requestów i
kontrolę dostępu. Utrzymuj jeden proces zapisujący API: blokada zapisu w kodzie
jest process-local, a SQLite nie zastępuje koordynacji wielu instancji.

Jeżeli zewnętrzne usługi głosowe mają pozostać wyłączone, użyj bezpośredniego
polecenia zamiast `npm run api:production`:

```bash
cd apps/api
DONE_DB_PATH=/var/lib/done/done.sqlite3 \
DONE_CORS_ORIGINS=https://app.example.com \
DONE_STT_ENABLED=false \
DONE_REALTIME_ENABLED=false \
DONE_DEMO_FAILURES_ENABLED=false \
DONE_DEMO_ENDPOINTS_ENABLED=false \
uv run uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 1
```

### Docker Compose

Aktualny `docker-compose.yml` uruchamia API i montuje SQLite w volume
`done_data`. Transkrypcja i Realtime łączą się bezpośrednio z OpenAI, jeżeli ich
flagi są włączone i proces otrzymał `OPENAI_API_KEY`.

```bash
DONE_DEMO_FAILURES_ENABLED=false \
DONE_DEMO_ENDPOINTS_ENABLED=false \
DONE_CORS_ORIGINS=https://app.example.com \
docker compose up --build -d
```

Port API jest domyślnie zbindowany do `127.0.0.1`. To właściwa granica dla
reverse proxy na tym samym hoście, ale fizyczny telefon nie połączy się z takim
bindingiem bez proxy lub jawnej zmiany mapowania portu. Po starcie zawsze
sprawdź capabilities API.

## Zmienne środowiskowe

Konfiguracja jest odczytywana przy starcie procesu. Po zmianie env wymagany jest
restart.

### Mobile/web

| Zmienna | Domyślna wartość | Znaczenie |
| --- | --- | --- |
| `EXPO_PUBLIC_API_URL` | Android emulator: `http://10.0.2.2:8001`; pozostałe platformy: `http://localhost:8001` | publiczny adres Done API |

Dla fizycznego telefonu ustaw `EXPO_PUBLIC_API_URL` na osiągalny adres LAN albo
HTTPS reverse proxy. Błąd backendu jest zawsze pokazywany w interfejsie i nigdy
nie jest maskowany lokalnymi danymi demonstracyjnymi.

### API i granice demo

| Zmienna | Domyślna wartość | Znaczenie |
| --- | --- | --- |
| `DONE_DB_PATH` | `apps/api/done.sqlite3` | plik SQLite |
| `DONE_CORS_ORIGINS` | `http://localhost:8081,http://127.0.0.1:8081` | lista originów po przecinku |
| `DONE_STT_ENABLED` | `false` | tworzy adapter OpenAI `gpt-4o-transcribe` |
| `DONE_DEMO_FAILURES_ENABLED` | `true` | automatyczne syntetyczne awarie w nowych misjach |
| `DONE_DEMO_ENDPOINTS_ENABLED` | `true` | endpointy reset/fault injection; po wyłączeniu zwracają `404` |
| `DONE_PORTFOLIO_SHADOW_MODE` | `false` | uruchamia porównawczą ocenę portfolio bez checkoutu, płatności, koszyka i approval |
| `DONE_PORTFOLIO_AUTONOMY_ENABLED` | `false` | ręcznie kontrolowana flaga ograniczonej autonomii; domyślnie wyłączona |
| `DONE_PORTFOLIO_SHADOW_MIN_RUNS` | `100` | minimalna liczba shadow runów przed przeglądem promocji |
| `DONE_PORTFOLIO_SHADOW_MAX_RECOMMENDATION_DIFF_RATE` | `0.01` | maks. 1% różnic rekomendacji w bramce promocji |
| `DONE_PORTFOLIO_SHADOW_MAX_PRICE_DELTA_RATE` | `0.02` | maks. 2% średniej bezwzględnej różnicy ceny w bramce promocji |

Wartości boolean akceptują `1/0`, `true/false`, `yes/no` i `on/off`.

### OpenAI Realtime

| Zmienna | Domyślna wartość |
| --- | --- |
| `OPENAI_API_KEY` | brak |
| `DONE_REALTIME_ENABLED` | `false` |
| `DONE_REALTIME_BASE_URL` | `https://api.openai.com` |
| `DONE_REALTIME_MODEL` | `gpt-realtime-2` |
| `DONE_REALTIME_VOICE` | `marin` |
| `DONE_REALTIME_TRANSCRIPTION_MODEL` | `gpt-realtime-whisper` |
| `DONE_REALTIME_CONNECT_TIMEOUT_SECONDS` | `5` |
| `DONE_REALTIME_REQUEST_TIMEOUT_SECONDS` | `20` |

Standardowy klucz ma pozostać wyłącznie w sekretnym środowisku procesu API.
Endpoint `/v1/realtime/client-secret` zwraca tylko sekret krótkotrwały, ma
`no-store` i nie loguje odpowiedzi. Po ujawnieniu klucza w chacie, logach lub
shell history należy go natychmiast unieważnić i wygenerować nowy.

### OpenAI transcription

| Zmienna | Domyślna wartość |
| --- | --- |
| `OPENAI_API_KEY` | brak |
| `DONE_TRANSCRIPTION_BASE_URL` | `https://api.openai.com` |
| `DONE_TRANSCRIPTION_MODEL` | `gpt-4o-transcribe` |
| `DONE_TRANSCRIPTION_CONNECT_TIMEOUT_SECONDS` | `5` |
| `DONE_TRANSCRIPTION_REQUEST_TIMEOUT_SECONDS` | `120` |
| `DONE_TRANSCRIPTION_MAX_CONCURRENCY` | `2` |
| `DONE_TRANSCRIPTION_MAX_UPLOAD_BYTES` | `26214400` |
| `DONE_TRANSCRIPTION_DEFAULT_LANGUAGE` | `pl` |

Audio jest wysyłane z API bezpośrednio do OpenAI jako multipart. Standardowy
klucz nigdy nie trafia do bundla mobilnego.

## Health i gotowość

Podstawowy probe API:

```bash
curl -fsS http://127.0.0.1:8001/health
```

Sprawdza zapytanie do SQLite i zwraca liczbę seedowanych produktów. Nie odpytuje
opcjonalnych usług OpenAI. Alias `/v1/health` ma ten sam wynik, ale jest ukryty
w OpenAPI.

Pełna diagnostyka opcjonalnego runtime:

```bash
curl -fsS http://127.0.0.1:8001/v1/runtime/capabilities
```

`/v1/runtime/capabilities` również zwraca HTTP `200`, gdy komponent ma status
`disabled`, `degraded` lub `unavailable`; automat musi sprawdzać pola JSON.
Dla działającego audio wymagane są poprawny `OPENAI_API_KEY`, quota i dostęp do
modelu `gpt-4o-transcribe`.

Rekomendowany podział probe'ów:

- liveness API: proces odpowiada na `/health`;
- readiness podstawowego text flow: `/health` ma `status=ok`, a oddzielny
  kontrolowany smoke test potwierdza zapis; sam health wykonuje tylko odczyt;
- readiness audio: `speech_to_text.status=available`;
- readiness ChatGPT Live: `realtime.status=available`.

Tekstowy flow nie zależy od OpenAI: interpreter i walidacja kontraktu działają
deterministycznie w procesie API.

## SQLite: utrzymanie, backup i restore

SQLite działa w WAL, z foreign keys, `busy_timeout=30s`, połączeniem na operację
i `BEGIN IMMEDIATE` dla zapisów. Katalog wskazany przez `DONE_DB_PATH` jest
tworzony automatycznie, ale użytkownik procesu musi mieć do niego prawa zapisu.

### Backup online

Nie kopiuj wyłącznie głównego pliku bazy podczas pracy API; aktywne dane mogą
znajdować się w plikach `-wal` i `-shm`. Użyj SQLite Online Backup API, np. CLI:

```bash
mkdir -p /var/backups/done
sqlite3 /var/lib/done/done.sqlite3 \
  ".backup '/var/backups/done/done-$(date +%F-%H%M%S).sqlite3'"
sqlite3 /var/backups/done/done-2026-07-11-120000.sqlite3 \
  "PRAGMA integrity_check;"
```

Drugie polecenie wymaga podstawienia nazwy właśnie utworzonego pliku. Oczekiwany
wynik to `ok`. Backup należy przenieść poza host i chronić jak dane osobowe:
zawiera adres, token płatniczy, ustawienia oraz transkrypty misji.

Najprostszy bezpieczny backup offline to zatrzymanie jedynego procesu API,
checkpoint WAL i skopiowanie kompletnej bazy. Nie ma endpointu backupu ani
wbudowanego harmonogramu.

### Restore

1. Zatrzymaj API i upewnij się, że żaden proces nie ma otwartej bazy.
2. Zweryfikuj backup przez `PRAGMA integrity_check`.
3. Zachowaj kopię obecnej bazy, następnie umieść backup pod `DONE_DB_PATH`.
4. Przy zatrzymanym API usuń stare pliki `-wal` i `-shm` należące do poprzedniej
   bazy oraz ustaw właściwego właściciela i prawa.
5. Uruchom API i sprawdź `/health`, liczbę produktów oraz kilka read endpointów.

Repozytorium nie ma Alembic ani tabeli wersji schematu. `CREATE TABLE IF NOT
EXISTS` i addytywny bootstrap nie zastępują migracji. Przed wdrożeniem kodu
zmieniającego schemat wykonaj backup i test restore na kopii.

## Bezpieczeństwo

Aktualnie zaimplementowane mechanizmy:

- jawna allowlista CORS, bez credentials;
- `Cache-Control: no-store` dla `/v1/*` i `X-Request-ID` w odpowiedziach;
- walidacja requestów Pydantic oraz optimistic concurrency dla wybranych zmian;
- token płatniczy zamiast PAN/CVV w domenie i API;
- allowlista formatów i limit rozmiaru audio;
- limit współbieżności transkrypcji oraz allowlista funkcji Realtime;
- osobne flagi wyłączające automatyczne awarie i endpointy demo;
- deterministyczna interpretacja i policies nadrzędne wobec wejścia z Realtime;
- standardowy klucz OpenAI tylko na serwerze, krótkotrwały sekret WebRTC,
  zahashowany safety identifier i redagowane błędy dostawcy;

Braki blokujące publiczną produkcję:

- brak authentication, authorization i tenant isolation; wszystkie operacje
  dotyczą stałego `demo-user`;
- brak TLS termination, rate limiting, WAF i limitu wielkości requestu przed
  aplikacją;
- brak encryption-at-rest, secrets managera i rotacji tokenów;
- profil, adres, token, eksport użytkownika i transkrypty są w SQLite w postaci
  jawnej;
- dokumentacja OpenAPI, health i capabilities są publiczne;
- brak audytu dostępu, centralnych logów, alertów i polityki retencji;
- brak ochrony webhooków, ponieważ realne webhooki jeszcze nie istnieją.

Przed wystawieniem usługi poza zaufany host: wyłącz oba demo flags, zawęź CORS,
umieść API za TLS i authentication, ogranicz request body, chroń klucz OpenAI,
zaszyfruj backupy i przeprowadź restore drill. CORS nie jest kontrolą dostępu.

## Obserwowalność i reagowanie

Obecnie dostępne są logi Uvicorn, response request ID, health/capabilities oraz
trwała timeline zdarzeń biznesowych misji. `metrics` zwracane w `MissionDetail`
są danymi demonstracyjnymi, nie metrykami operacyjnymi. Nie ma Prometheus,
distributed tracing, centralnego error reporting ani automatycznych alertów.

Typowe symptomy:

| Symptom | Sprawdzenie | Zachowanie/akcja |
| --- | --- | --- |
| audio zwraca `503` | capabilities STT i request ID | sprawdź klucz, quota, model, sieć i timeout |
| Realtime `unavailable` | capabilities Realtime i request ID | sprawdź flagę, klucz, quota, model i sieć |
| `database is locked` | liczba workerów/procesów i dysk | pozostaw jednego writera; znajdź długą transakcję |
| health ma inną liczbę produktów niż `14` | stan bazy/seed | sprawdź restore lub kontrolowany reset tylko w demo |

Mission events są przeznaczone dla UX i audytu przebiegu misji, nie gwarantują
kompletnego technicznego audit logu. `X-Request-ID` jest zwracany klientowi, ale
kod nie dodaje go jeszcze do kontekstu każdego logu.

## Granica przyszłych realnych integracji

Realne commerce integrations **nie są zaimplementowane**. Obecny
`MissionWorkflow` wykonuje catalog, inventory, delivery, payment i order jako
lokalne SQL/symulację. Nie wolno zastąpić pojedynczych wywołań SQL klientem HTTP
wewnątrz aktualnej długiej transakcji.

Docelowe porty powinny należeć do application layer, np.:

| Port | Odpowiedzialność adaptera |
| --- | --- |
| `CatalogPort` | wyszukiwanie ofert i mapowanie vendor SKU do stabilnych DTO |
| `InventoryPort` | availability, idempotentna rezerwacja i zwolnienie stocku |
| `DeliveryPort` | wycena, rezerwacja slotu, anulowanie i tracking |
| `PaymentPort` | authorization/capture/refund na tokenie, bez danych karty |
| `OrderPort` | idempotentne złożenie/anulowanie i pobieranie statusu zamówienia |

Adaptery infrastruktury powinny tłumaczyć błędy dostawcy na jawne wyniki
application/domain i nie przeciekać vendor SDK do domeny. Zewnętrzne I/O należy
wykonywać poza transakcją SQLite, z trwałym command/outbox, idempotency keys,
retry z limitem, reconciliation i obsługą podpisanych webhooków. Stan misji musi
odzwierciedlać niepewność, np. timeout płatności nie może automatycznie oznaczać
odrzucenia bez późniejszego reconciliation.

Istniejące `SpeechToTextPort`, `RealtimeSessionPort`, `MissionWorkflowPort` i
`UserRepository` pokazują kierunek dependency inversion.
`OpenAITranscriptionAdapter`, `OpenAIRealtimeAdapter` i `SQLiteUserRepository`
są adapterami; symulator commerce nie ma jeszcze analogicznej granicy.

## Shadow mode portfolio i próg promocji

`DONE_PORTFOLIO_SHADOW_MODE=false` jest bezpiecznym ustawieniem domyślnym.
Po włączeniu aktywny workflow działa jak dotychczas, a dodatkowy planner wykonuje
się na rzeczywistym snapshotcie katalogu w `execution_mode=shadow`. Shadow zapisuje
decyzję, `optimizer_runs`, rekord porównawczy i event `portfolio.shadow_audit`, ale
nie może zmienić koszyka, approval, płatności, zamówienia, statusu ani revision misji.

Operator może sprawdzić:

- `GET /v1/portfolio/shadow/telemetry` — wykonalność, Orange Mode, średni czas
  solvera, replan rate oraz różnice ceny i rekomendacji;
- `GET /v1/missions/{id}/portfolio-shadow-audits` — audyt snapshotu, triggera,
  rekomendacji aktywnej i shadow oraz powód niewykonania;
- `POST /v1/missions/{id}/portfolio-shadow` — jawny shadow run, dostępny tylko
  przy włączonej fladze.

Rekomendowany próg przejścia do ograniczonej autonomii: co najmniej 100 shadow
runów z wykonalnością monitorowaną przez operatora, różnicą rekomendacji <=1%,
średnią bezwzględną różnicą ceny <=2% oraz bez niezaakceptowanych regresji Orange
Mode. Po spełnieniu progu wymagana jest osobna, ręczna zmiana konfiguracji i
canary dla ograniczonej klasy niskiego ryzyka; pełne automatyczne zakupy nadal
nie są domyślne.

## Weryfikacja przed wydaniem

```bash
npm run typecheck
npm run test:mobile
npm run test:api
npm run lint:api
npm run build:web
npm run doctor
```

`npm run test` łączy typecheck oraz testy mobile i API, ale nie uruchamia lintów,
web builda ani Expo Doctor. Po testach wykonaj smoke test `/health`, capabilities,
utworzenia misji tekstowej i — jeżeli transkrypcja jest wymagana — jednego
prawdziwego nagrania wysłanego do OpenAI.
