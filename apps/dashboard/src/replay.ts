import type { LoopEvent } from "./types";

export interface ReplayStep extends Omit<LoopEvent, "created_at"> {
  /** Milliseconds to wait before the next step. */
  delay: number;
}

/**
 * Scripted mission used when the API has no data (or is offline), so the
 * loop can always be demonstrated. It mirrors the seeded demo scenario:
 * birthday mission, price-change feedback, replan, PSP reroute, order.
 */
export const REPLAY_SCRIPT: readonly ReplayStep[] = [
  { type: "mission.created", title: "Misja utworzona z komendy głosowej", severity: "info", delay: 1600 },
  { type: "voice.transcribed", title: "„Urodziny Zosi, sobota, 12 dzieci, do 250 zł, bez orzechów”", severity: "info", delay: 2000 },
  { type: "intent.parsed", title: "Budżet, deadline i ograniczenia odczytane deterministycznie", severity: "info", delay: 1700 },
  { type: "contract.created", title: "Kontrakt v1 · 250 PLN · nut-free · sobota 12:00", severity: "info", delay: 1900 },
  { type: "market.snapshot_captured", title: "Snapshot rynku: 14 ofert od 3 merchantów", severity: "info", delay: 1900 },
  { type: "basket.optimized", title: "CP-SAT: 7× BUY_NOW, 1× WAIT · 128,41 PLN", severity: "info", delay: 2300 },
  { type: "policy.validated", title: "BasketPolicy: budżet, alergeny i termin spełnione", severity: "info", delay: 1600 },
  { type: "approval.requested", title: "Koszyk czeka na akceptację użytkownika", severity: "info", delay: 2600 },
  { type: "price.changed", title: "Cena precli +20% — sygnał wraca do modelu", severity: "warning", delay: 2100 },
  { type: "portfolio.replanned", title: "Replan: krakersy zastępują precle w tym samym budżecie", severity: "info", delay: 2200 },
  { type: "approval.superseded", title: "Poprzednia zgoda unieważniona po replanie", severity: "warning", delay: 1900 },
  { type: "approval.resolved", title: "Użytkownik zatwierdził 128,41 PLN", severity: "info", delay: 2000 },
  { type: "execution.started", title: "Start zakupu u Party Market", severity: "info", delay: 1500 },
  { type: "inventory.unavailable", title: "Mini precle niedostępne — start recovery", severity: "warning", delay: 1900 },
  { type: "product.replaced", title: "Bezpieczny zamiennik dobrany w budżecie (nut-free)", severity: "info", delay: 1700 },
  { type: "inventory.reserved", title: "Stock zarezerwowany u merchanta", severity: "info", delay: 1400 },
  { type: "payment.attempted", title: "Płatność tokenem karty przez PSP_A", severity: "info", delay: 1400 },
  { type: "payment.declined", title: "PSP_A: soft decline (DO_NOT_HONOR)", severity: "warning", delay: 1700 },
  { type: "payment.rerouted", title: "Przekierowanie płatności do PSP_B", severity: "info", delay: 1400 },
  { type: "payment.authorized", title: "PSP_B autoryzował 128,41 PLN", severity: "info", delay: 1700 },
  { type: "order.confirmed", title: "Zamówienie potwierdzone · dostawa w piątek", severity: "info", delay: 2000 },
  { type: "mission.completed", title: "Misja ukończona · 121,59 PLN pod budżetem · 2 awarie odzyskane", severity: "info", delay: 6500 },
];

export const REPLAY_MISSION_TITLE = "Urodziny Zosi — misja demonstracyjna";
