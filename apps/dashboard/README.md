# Done — Live Loop dashboard

Prezentacyjny dashboard pokazujący na żywo, gdzie w pętli decyzyjnej znajduje
się aplikacja Done i jakie akcje właśnie wykonuje. Jeden ekran: graf pętli
(7 węzłów + krawędź zwrotna) i ticker ostatnich zdarzeń. Szczegóły koncepcji:
`docs/executive_plan_dashboard.md`.

Dashboard jest czystą projekcją read-only — nie zawiera logiki biznesowej,
niczego nie zapisuje i nie wymaga zmian w API.

## Uruchomienie

```bash
npm run dashboard        # http://localhost:8090
```

Dashboard oczekuje API pod `http://localhost:8001` (nadpisanie:
`VITE_API_URL`). Port `8090` jest domyślnie dopuszczony w CORS API.

## Tryby

- **live** — auto-follow najnowszej aktywnej misji z `GET /v1/missions`,
  polling `GET /v1/missions/{id}/events?after_id=<cursor>` co 1 s;
- **replay** — gdy nie ma żadnej misji albo API jest niedostępne, graf
  odtwarza w pętli skryptowany scenariusz demo (`src/replay.ts`), żeby
  prezentacja nigdy nie pokazywała pustego ekranu.

## Struktura

```text
src/mapping.ts   słownik event → węzeł grafu (jedyna „logika”)
src/graph.ts     statyczny SVG grafu + stany węzłów/krawędzi
src/ticker.ts    ostatnie zdarzenia, jedna linia każde
src/api.ts       klient HTTP (fetch + cursor)
src/replay.ts    skryptowany scenariusz awaryjny
src/main.ts      polling i orkiestracja trybów
```
