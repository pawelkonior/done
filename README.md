# Done — działająca aplikacja voice-first

Done to mobilny, voice-first agent zakupowy, który przyjmuje cel użytkownika, buduje bezpieczny koszyk, prosi o jedną akceptację, a następnie samodzielnie naprawia problemy z dostępnością i płatnością.

Projekt realizuje kompletny scenariusz z `assets/execution_plan.md`:

```text
komenda głosowa / tekstowa
        ↓
kontrakt misji i twarde ograniczenia
        ↓
optymalizacja koszyka i dostawy
        ↓
akceptacja użytkownika
        ↓
produkt niedostępny → bezpieczny zamiennik
        ↓
soft decline → przekierowanie PSP_A → PSP_B
        ↓
ukończona misja + transparentny log i metryki
```

## Co jest gotowe

- Expo + React Native + Expo Router, działające na webie i przygotowane do iOS/Android.
- Pięć zakładek: Now, Missions, Completed, Settings i Profile.
- Interfejs odtworzony na podstawie screenów z `assets/`: ciemny motyw, neonowe akcenty, voice orb, karty, timeline, koszyk, opcje dostawy i ekran wyniku.
- Rozmowa głosowa ChatGPT Live przez WebRTC, `gpt-realtime-1.5`, głos `marin`, live transcript i function calling do bezpiecznego use case'u misji.
- Prawdziwe nagrywanie po długim przytrzymaniu mikrofonu przez `expo-audio` oraz lokalna transkrypcja Whisper jako niezależny fallback.
- Ollama `qwen2.5:7b` wzbogaca opis misji; budżet, termin, uczestnicy, alergeny i approval pozostają deterministyczne.
- FastAPI + trwałe SQLite, 14 produktów, 3 merchantów, kontrakty, eventy, koszyki, akceptacje, płatności, zamówienia i awarie.
- Obowiązkowa akceptacja przed symulowanym zakupem.
- Dwie automatyczne naprawy zachowujące budżet, termin i ograniczenie `nut-free`.
- Polling stanu z API, lokalne powiadomienia, reset demo, CORS, idempotentna akceptacja i idempotentne próby płatności.
- Clean Architecture i DDD: domain, application ports/use cases, infrastructure adapters i composition root.
- 45 testów API, 15 testów mobilnych, 2 testy STT, TypeScript strict, Expo Doctor 20/20, eksport webowy i natywna kompilacja Xcode.

## Szybki start

Wymagania: Node 20+, Python 3.13 oraz `uv`.

```bash
cp .env.example .env
# wpisz OPENAI_API_KEY wyłącznie w lokalnym .env, jeżeli używasz ChatGPT Live
npm run setup
npm run dev
```

Po uruchomieniu:

- aplikacja webowa: [http://localhost:8081](http://localhost:8081)
- API: [http://localhost:8001](http://localhost:8001)
- dokumentacja API: [http://localhost:8001/docs](http://localhost:8001/docs)

Jeśli port 8001 jest zajęty, uruchom API na innym porcie i przekaż adres aplikacji:

```bash
cd apps/api
uv run uvicorn app.main:app --reload --port 8010
EXPO_PUBLIC_API_URL=http://localhost:8010 npm run web
```

## Scenariusz demo

1. Na ekranie `Now` dotknij voice orb, aby rozpocząć ChatGPT Live; przytrzymaj go, aby użyć lokalnego Whispera, albo wybierz formularz tekstowy.
2. Powiedz przygotowaną komendę urodzinową. Live dopyta o brakujące dane i przekaże kompletną misję do deterministycznej walidacji.
3. Na ekranie szczegółów sprawdź kontrakt, dostawę i koszyk.
4. Wybierz „Approve purchase”.
5. Done zasymuluje brak produktu, dobierze zgodny zamiennik, obsłuży soft decline płatności i potwierdzi zamówienie.
6. Ekran końcowy pokaże dwie odzyskane awarie, dwie próby płatności, oszczędność względem budżetu i pełny event log.

## Testy i build

```bash
npm test
npm run build:web
npm run doctor
```

Natywny development build z WebRTC (Expo Go nie zawiera tego modułu):

```bash
cd apps/mobile
npx expo prebuild --platform ios
npx expo run:ios
```

Sam backend można uruchomić także przez Docker:

```bash
docker compose up --build api
```

## Architektura

```text
apps/mobile   Expo / React Native / WebRTC / Notifications / TanStack Query
apps/api      FastAPI / DDD / application ports / SQLite / bezpieczne adaptery AI
apps/stt      prywatny sidecar Whisper / ffmpeg
assets        logo, referencje UI i pełny execution plan
```

Backend jest celowo modularnym monolitem. Standardowy klucz OpenAI pozostaje wyłącznie na serwerze; aplikacja dostaje tylko krótko żyjący sekret Realtime. Warstwa workflow ma stabilne granice, dzięki czemu silnik można rozbudować bez zmiany API i interfejsu mobilnego. Wszystkie płatności, merchanty i zamówienia są nadal wyłącznie symulowane — publiczne real-commerce wymaga osobnych integracji, uwierzytelniania i zgodności PCI.
