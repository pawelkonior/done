import { FEEDBACK_EVENTS, WARN_EVENTS, WARN_SEVERITIES } from "./mapping";
import type { LoopEvent } from "./types";

const MAX_ROWS = 5;

export interface Ticker {
  push(event: LoopEvent): void;
  reset(): void;
}

function tone(event: LoopEvent): string {
  if (WARN_EVENTS.has(event.type) || WARN_SEVERITIES.has(event.severity)) return "warn";
  if (FEEDBACK_EVENTS.has(event.type)) return "feedback";
  if (event.type === "order.confirmed" || event.type === "mission.completed") return "ok";
  return "info";
}

function timeOf(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("pl-PL", { hour12: false });
}

export function createTicker(container: HTMLElement): Ticker {
  return {
    push(event) {
      const row = document.createElement("div");
      row.className = "ticker-row";
      row.dataset.tone = tone(event);

      const time = document.createElement("span");
      time.className = "t-time";
      time.textContent = timeOf(event.created_at);

      const type = document.createElement("span");
      type.className = "t-type";
      type.textContent = event.type;

      const title = document.createElement("span");
      title.className = "t-title";
      title.textContent = event.title;

      row.append(time, type, title);
      container.prepend(row);
      while (container.childElementCount > MAX_ROWS) {
        container.lastElementChild?.remove();
      }
    },
    reset() {
      container.replaceChildren();
    },
  };
}
