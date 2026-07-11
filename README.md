# Done — działająca aplikacja voice-first

Done to mobilny, voice-first agent zakupowy, który zamienia wypowiedź w audytowalny kontrakt, dopytuje zamiast zgadywać, przeszukuje podłączony katalog i zatrzymuje wykonanie zawsze, gdy nie potrafi udowodnić zgodności z ograniczeniami. Każda zmiana produktu, ceny, dostawy albo merchanta unieważnia wcześniejszą zgodę.

Projekt realizuje kompletny scenariusz z `assets/execution_plan.md`:

```text
komenda głosowa / tekstowa
        ↓
draft intencji + pytania o brakujące fakty
        ↓
kontrakt + wyszukiwanie i optymalizacja katalogu
        ↓
deterministyczne guardraile + akceptacja dokładnego planu
        ↓
rezerwacja ceny/stocku → ponowna walidacja
        ↓
specyfikacja karty jednorazowej ograniczona kwotą i merchantem
        ↓
checkout albo trwałe action request / wsparcie człowieka
```

## Co jest gotowe

- Expo + React Native + Expo Router, działające na webie i przygotowane do iOS/Android.
- Pięć zakładek: Now, Missions, Completed, Settings i Profile.
- Interfejs odtworzony na podstawie screenów z `assets/`: ciemny motyw, neonowe akcenty, voice orb, karty, timeline, koszyk, opcje dostawy i ekran wyniku.
- Rozmowa głosowa przez OpenAI Realtime i WebRTC: intake, korekty, odczyt stanu, dokładna akceptacja zakupu, wybór recovery, anulowanie i wezwanie człowieka są obsługiwane jako typowane komendy głosowe.
- Prawdziwe nagrywanie po długim przytrzymaniu mikrofonu przez `expo-audio`; API wysyła audio bezpośrednio do OpenAI Transcription z modelem `gpt-4o-transcribe`.
- Deterministyczny interpreter zachowuje evidence z transkryptu i nie uzupełnia krytycznych pól domyślnymi wartościami. Niejasne „rzeczy na urodziny” powodują pytanie „prezenty czy wyposażenie przyjęcia?”, a brak godziny — osobne pytanie o termin.
- Planista katalogowy wybiera produkty na podstawie wieku, liczby odbiorców, kategorii, ceny, stocku, merchanta i jawnych ograniczeń; obsługuje wyposażenie przyjęcia oraz neutralne wiekowo prezenty z podłączonego katalogu.
- FastAPI + trwałe SQLite, 14 produktów, 3 merchantów, kontrakty, eventy, koszyki, akceptacje, płatności, zamówienia i awarie.
- Akceptacja jest związana z revision, plan hash, merchantem, kwotą i walutą. Stara albo niepełna zgoda nie może uruchomić rezerwacji, karty ani płatności.
- Funding gate wymaga tego samego fingerprintu dla guardraili, akceptacji i aktywnej rezerwacji. Zapisywana jest wyłącznie restrykcyjna specyfikacja karty — bez PAN/CVV.
- Brak zgodnego produktu, twardy decline, utrata dostawy lub nierozpoznane ograniczenie tworzą trwałe `action_request`; misja przechodzi do `waiting_for_user` lub `waiting_for_support` bez rozluźniania guardraili.
- Polling stanu z API, lokalne powiadomienia, reset demo, CORS, idempotentna akceptacja i idempotentne próby płatności.
- Clean Architecture i DDD: domain, application ports/use cases, infrastructure adapters i composition root.
- Testy API i aplikacji mobilnej, TypeScript strict, Expo Doctor, eksport webowy i natywna kompilacja Xcode.

## Szybki start

Wymagania: Node 20+, Python 3.13 oraz `uv`.

```bash
cp .env.example .env
# wpisz OPENAI_API_KEY wyłącznie w lokalnym .env, jeżeli używasz Realtime lub transkrypcji audio
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

1. Na ekranie `Now` dotknij voice orb, aby rozpocząć sesję OpenAI Realtime; przytrzymaj go, aby nagrać komendę wysyłaną przez API do OpenAI Transcription, albo wybierz formularz tekstowy.
2. Powiedz np. „Rzeczy na urodziny 10-latków, 5 osób, za tydzień, maksymalnie 500 zł”. Live dopyta, czy chodzi o prezenty czy wyposażenie przyjęcia, oraz o godzinę dostawy.
3. Na ekranie szczegółów sprawdź kontrakt, dostawę i koszyk.
4. Wybierz „Approve purchase”.
5. W trybie demonstracyjnym można włączyć brak produktu. Done dobierze zgodny zamiennik, ale ponieważ plan się zmienił, poprosi głosowo o świeżą akceptację przed jakimkolwiek fundingiem.
6. Ekran końcowy pokaże naprawy, próby płatności, oszczędność względem budżetu i pełny event log. Jeśli bezpieczna naprawa nie istnieje, pokaże pytanie lub kolejkę wsparcia zamiast udawać sukces.

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
apps/api      FastAPI / DDD / deterministyczny workflow / SQLite / OpenAI voice adapters
assets        logo, referencje UI i pełny execution plan
```

Backend jest celowo modularnym monolitem. Standardowy klucz OpenAI pozostaje wyłącznie na serwerze; aplikacja dostaje tylko krótko żyjący sekret Realtime, związany z bieżącym stanem misji.

`DONE_COMMERCE_MODE=demo|sandbox` używa lokalnego katalogu i kontrolowanej symulacji checkoutu. `DONE_COMMERCE_MODE=live` działa fail-closed: wymaga uwierzytelnienia API i zatrzyma misję przed rezerwacją/kartą, dopóki nie zostaną podłączone prawdziwe adaptery merchanta oraz issuera. Repozytorium nie zawiera i nie udaje produkcyjnego dostępu do sprzedawców, danych karty ani zgodności PCI.
