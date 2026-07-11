import "./styles.css";

import { fetchEvents, fetchMissions } from "./api";
import { createGraph } from "./graph";
import { EVENT_NODE, FEEDBACK_EVENTS, WARN_EVENTS, WARN_SEVERITIES } from "./mapping";
import { REPLAY_MISSION_TITLE, REPLAY_SCRIPT } from "./replay";
import { createTicker } from "./ticker";
import type { LoopEvent } from "./types";

const EVENTS_POLL_MS = 1000;
const MISSIONS_POLL_MS = 5000;

type Mode = "connecting" | "live" | "replay";

const graph = createGraph(document.getElementById("graph")!);
const ticker = createTicker(document.getElementById("ticker")!);
const missionTitleEl = document.getElementById("mission-title")!;
const missionStatusEl = document.getElementById("mission-status")!;
const modeBadgeEl = document.getElementById("mode-badge")!;
const clockEl = document.getElementById("clock")!;

let mode: Mode = "connecting";
let missionId: string | null = null;
let cursor = 0;
let eventsInFlight = false;
let replayTimer: number | undefined;
/** Bumped on every view reset so stale in-flight responses are discarded. */
let generation = 0;

function setMode(next: Mode, label: string): void {
  mode = next;
  modeBadgeEl.dataset.mode = next;
  modeBadgeEl.textContent = label;
}

function setMission(title: string, status: string | null): void {
  missionTitleEl.textContent = title;
  if (status) {
    missionStatusEl.hidden = false;
    missionStatusEl.textContent = status;
    missionStatusEl.dataset.status = status;
  } else {
    missionStatusEl.hidden = true;
  }
}

function dispatch(event: LoopEvent): void {
  if (FEEDBACK_EVENTS.has(event.type)) {
    graph.flashFeedback();
  }
  const node = EVENT_NODE[event.type];
  if (node) {
    const warn = WARN_EVENTS.has(event.type) || WARN_SEVERITIES.has(event.severity);
    graph.setActive(node, warn);
  }
  ticker.push(event);
}

function resetView(): void {
  graph.reset();
  ticker.reset();
  cursor = 0;
  generation += 1;
}

// ---------------------------------------------------------------- replay

function stopReplay(): void {
  window.clearTimeout(replayTimer);
  replayTimer = undefined;
}

function scheduleReplayStep(index: number): void {
  const step = REPLAY_SCRIPT[index % REPLAY_SCRIPT.length];
  if (index > 0 && index % REPLAY_SCRIPT.length === 0) {
    resetView();
  }
  dispatch({ ...step, created_at: new Date().toISOString() });
  replayTimer = window.setTimeout(() => scheduleReplayStep(index + 1), step.delay);
}

function enterReplay(reason: string): void {
  if (mode === "replay") return;
  stopReplay();
  missionId = null;
  resetView();
  setMode("replay", reason);
  setMission(REPLAY_MISSION_TITLE, null);
  scheduleReplayStep(0);
}

// ---------------------------------------------------------------- live

function enterLive(id: string, title: string, status: string): void {
  if (missionId !== id) {
    stopReplay();
    missionId = id;
    resetView();
    void pollEvents(); // Fill the new mission's history without waiting a tick.
  }
  setMode("live", "live");
  setMission(title, status);
}

async function pollEvents(): Promise<void> {
  if (mode !== "live" || !missionId || eventsInFlight) return;
  eventsInFlight = true;
  const requestGeneration = generation;
  try {
    const page = await fetchEvents(missionId, cursor);
    if (requestGeneration !== generation) {
      return; // The view switched missions while this request was in flight.
    }
    cursor = page.cursor;
    for (const event of page.events) {
      dispatch(event);
    }
    missionStatusEl.textContent = page.mission_status;
    missionStatusEl.dataset.status = page.mission_status;
  } catch {
    // A transient failure keeps the last known state; mission polling
    // decides whether to fall back to replay.
  } finally {
    eventsInFlight = false;
  }
}

async function pollMissions(): Promise<void> {
  try {
    const missions = await fetchMissions();
    // Follow whatever the system touched last (the list is sorted by
    // updated_at). A mission that just completed stays on screen instead
    // of losing the finale to a stale clarification draft.
    const followed = missions[0];
    if (followed) {
      enterLive(followed.id, followed.title, followed.status);
    } else {
      enterReplay("replay · brak misji");
    }
  } catch {
    enterReplay("replay · API offline");
  }
}

// ---------------------------------------------------------------- boot

window.setInterval(() => {
  clockEl.textContent = new Date().toLocaleTimeString("pl-PL", { hour12: false });
}, 1000);

void pollMissions();
window.setInterval(() => void pollMissions(), MISSIONS_POLL_MS);
window.setInterval(() => void pollEvents(), EVENTS_POLL_MS);
