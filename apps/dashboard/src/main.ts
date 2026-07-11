import "./styles.css";

import { fetchCatalogOffers, fetchEvents, fetchMissionDetail, fetchMissions } from "./api";
import { displayMissionTitle } from "./copy";
import { createDetailPanel, simulateLineItemPaymentFailure } from "./detail";
import { createGraph } from "./graph";
import { EVENT_NODE, FEEDBACK_EVENTS, WARN_EVENTS, WARN_SEVERITIES } from "./mapping";
import { createPortfolioFlow } from "./portfolio";
import { storeBatchDetails } from "./store-batches";
import { REPLAY_MISSION_TITLE, REPLAY_SCRIPT } from "./replay";
import { createTicker } from "./ticker";
import type { CatalogOffer, LoopEvent, MissionDetail, NodeDetails } from "./types";

const EVENTS_POLL_MS = 1000;
const MISSIONS_POLL_MS = 5000;

type Mode = "connecting" | "live" | "replay";

const graph = createGraph(document.getElementById("graph")!);
const portfolioFlow = createPortfolioFlow();
const ticker = createTicker(document.getElementById("ticker")!);
const detailPanel = createDetailPanel(document.getElementById("detail-panel")!);
const missionTitleEl = document.getElementById("mission-title")!;
const missionStatusEl = document.getElementById("mission-status")!;
const modeBadgeEl = document.getElementById("mode-badge")!;
const simulateLineItemButton = document.getElementById("simulate-line-item-failure") as HTMLButtonElement;
const simulateBatchTwoButton = document.getElementById("simulate-batch-two-decline") as HTMLButtonElement;
const clockEl = document.getElementById("clock")!;

let mode: Mode = "connecting";
let missionId: string | null = null;
let cursor = 0;
let eventsInFlight = false;
let detailInFlight = false;
let latestDetail: MissionDetail | null = null;
let lineItemFailureSimulation = false;
let catalogOffers: CatalogOffer[] = [];
let batchTwoFailureSimulation = false;
let replayTimer: number | undefined;
/** Bumped on every view reset so stale in-flight responses are discarded. */
let generation = 0;

function setMode(next: Mode, text: string): void {
  mode = next;
  modeBadgeEl.dataset.mode = next;
  modeBadgeEl.textContent = text;
}

function setMission(title: string, status: string | null): void {
  missionTitleEl.textContent = displayMissionTitle(title);
  if (status) {
    missionStatusEl.hidden = false;
    missionStatusEl.textContent = status.replaceAll("_", " ");
    missionStatusEl.dataset.status = status;
  } else {
    missionStatusEl.hidden = true;
  }
}

function dispatch(event: LoopEvent): void {
  if (FEEDBACK_EVENTS.has(event.type)) graph.flashFeedback();
  const node = EVENT_NODE[event.type];
  if (node) {
    const warn = WARN_EVENTS.has(event.type) || WARN_SEVERITIES.has(event.severity);
    graph.setActive(node, warn);
  }
  ticker.push(event);
}

function resetView(): void {
  graph.reset();
  portfolioFlow.reset();
  ticker.reset();
  detailPanel.reset();
  latestDetail = null;
  lineItemFailureSimulation = false;
  batchTwoFailureSimulation = false;
  updateSimulationButton();
  cursor = 0;
  generation += 1;
}

function updateSimulationButton(): void {
  const available = Boolean(latestDetail?.basket?.items.length);
  simulateLineItemButton.disabled = !available;
  simulateLineItemButton.dataset.active = String(lineItemFailureSimulation);
  simulateLineItemButton.textContent = lineItemFailureSimulation
    ? "clear line-item failure"
    : "simulate line-item failure";
  simulateBatchTwoButton.disabled = catalogOffers.length === 0;
  simulateBatchTwoButton.dataset.active = String(batchTwoFailureSimulation);
  simulateBatchTwoButton.textContent = batchTwoFailureSimulation
    ? "clear Batch 2 decline"
    : "simulate Batch 2 decline";
}

function mergeNodeDetails(...sources: NodeDetails[]): NodeDetails {
  const merged: NodeDetails = {};
  for (const source of sources) {
    for (const [node, details] of Object.entries(source)) {
      if (!details) continue;
      const target = node as keyof NodeDetails;
      merged[target] = [...(merged[target] ?? []), ...details];
    }
  }
  return merged;
}

function baseNodeDetails(detail: MissionDetail): NodeDetails {
  const storeCount = new Set(catalogOffers.map((offer) => offer.store_id)).size;
  const details: NodeDetails = {
    intake: [{
      title: "Mission received",
      meta: detail.mission.status.replaceAll("_", " "),
      description: detail.mission.latest_update,
      tone: "info",
    }],
    contract: [{
      title: `Budget ${detail.mission.budget_limit.toFixed(2)} ${detail.mission.currency}`,
      meta: `${detail.mission.current_step} of ${detail.mission.total_steps} steps`,
      description: "Constraints and intent are locked before a basket can be purchased.",
      tone: "info",
    }],
  };
  if (storeCount > 0) {
    details.snapshot = [{
      title: `${catalogOffers.length} live catalog offers`,
      meta: `${storeCount} store endpoints`,
      description: "GET /v1/catalog/offers supplies price and availability snapshots.",
      tone: "info",
    }];
  }
  if (detail.order) {
    details.result = [{
      title: `Order ${detail.order.confirmation_code}`,
      meta: detail.order.status,
      description: "The confirmed order is the final state for successfully purchased items.",
      tone: "ok",
    }];
  }
  return details;
}

function renderWorkflow(detail: MissionDetail): void {
  const portfolio = portfolioFlow.update(detail);
  graph.setNodeSubtitles(portfolio.subtitles);
  const batchDetails = storeBatchDetails(catalogOffers, batchTwoFailureSimulation);
  graph.setNodeDetails(mergeNodeDetails(baseNodeDetails(detail), portfolio.details, { purchase: batchDetails }));
}

function renderDetail(detail: MissionDetail): void {
  latestDetail = detail;
  const renderedDetail = lineItemFailureSimulation ? simulateLineItemPaymentFailure(detail) : detail;
  detailPanel.update(renderedDetail);
  renderWorkflow(renderedDetail);
  updateSimulationButton();
}

function stopReplay(): void {
  window.clearTimeout(replayTimer);
  replayTimer = undefined;
}

function scheduleReplayStep(index: number): void {
  const step = REPLAY_SCRIPT[index % REPLAY_SCRIPT.length];
  if (index > 0 && index % REPLAY_SCRIPT.length === 0) resetView();
  renderWorkflow(detailPanel.showReplay(step.type));
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
  renderWorkflow(detailPanel.showReplay("mission.created"));
  scheduleReplayStep(0);
}

function enterLive(id: string, title: string, status: string): void {
  if (missionId !== id) {
    stopReplay();
    missionId = id;
    resetView();
    void pollEvents();
    void pollDetail();
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
    if (requestGeneration !== generation) return;
    cursor = page.cursor;
    for (const event of page.events) dispatch(event);
    missionStatusEl.textContent = page.mission_status.replaceAll("_", " ");
    missionStatusEl.dataset.status = page.mission_status;
  } catch {
    // Mission polling determines whether the dashboard should fall back to replay.
  } finally {
    eventsInFlight = false;
  }
}

async function pollDetail(): Promise<void> {
  if (mode !== "live" || !missionId || detailInFlight) return;
  detailInFlight = true;
  const requestGeneration = generation;
  try {
    const detail = await fetchMissionDetail(missionId);
    if (requestGeneration !== generation) return;
    setMission(detail.mission.title, detail.mission.status);
    renderDetail(detail);
  } catch {
    // The graph and event ticker remain available if this read-only request fails.
  } finally {
    detailInFlight = false;
  }
}

async function pollMissions(): Promise<void> {
  try {
    const missions = await fetchMissions();
    // Follow the most recently touched mission, keeping a completed finale visible.
    const followed = missions[0];
    if (followed) {
      enterLive(followed.id, followed.title, followed.status);
    } else {
      enterReplay("replay · no missions");
    }
  } catch {
    enterReplay("replay · API offline");
  }
}

window.setInterval(() => {
  clockEl.textContent = new Date().toLocaleTimeString("en-GB", { hour12: false });
}, 1000);

simulateLineItemButton.addEventListener("click", () => {
  if (!latestDetail?.basket?.items.length) return;
  lineItemFailureSimulation = !lineItemFailureSimulation;
  renderDetail(latestDetail);
});

simulateBatchTwoButton.addEventListener("click", () => {
  if (catalogOffers.length === 0) return;
  batchTwoFailureSimulation = !batchTwoFailureSimulation;
  if (latestDetail) renderDetail(latestDetail);
  updateSimulationButton();
});

async function loadStoreBatches(): Promise<void> {
  try {
    catalogOffers = await fetchCatalogOffers();
    if (latestDetail) renderDetail(latestDetail);
  } catch {
    catalogOffers = [];
  } finally {
    updateSimulationButton();
  }
}

updateSimulationButton();
void loadStoreBatches();

void pollMissions();
window.setInterval(() => void pollMissions(), MISSIONS_POLL_MS);
window.setInterval(() => {
  void pollEvents();
  void pollDetail();
}, EVENTS_POLL_MS);
