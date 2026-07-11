import "./styles.css";

import { fetchCatalogOffers, fetchEvents, fetchMissionDetail, fetchMissions } from "./api";
import { displayMissionTitle } from "./copy";
import { replayDetail, simulateLineItemPaymentFailure } from "./detail";
import { createGraph } from "./graph";
import { EVENT_NODE, FEEDBACK_EVENTS, WARN_EVENTS, WARN_SEVERITIES } from "./mapping";
import { createPortfolioFlow } from "./portfolio";
import {
  buildCheckoutRoutes,
  rerouteDeclinedBatch,
  storeBatchDetails,
  storeRouteDetails,
  type CheckoutRoute,
  type CheckoutSimulationPhase,
} from "./store-batches";
import { REPLAY_MISSION_TITLE, REPLAY_SCRIPT } from "./replay";
import { createTicker } from "./ticker";
import type { CatalogOffer, LoopEvent, MissionDetail, NodeDetail, NodeDetails } from "./types";

const EVENTS_POLL_MS = 1000;
const MISSIONS_POLL_MS = 5000;

type Mode = "connecting" | "live" | "replay";

const graph = createGraph(document.getElementById("graph")!);
const portfolioFlow = createPortfolioFlow();
const ticker = createTicker(document.getElementById("ticker")!);
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
let checkoutPhase: CheckoutSimulationPhase = "idle";
let checkoutRevision = 0;
let checkoutTimers: number[] = [];
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
  latestDetail = null;
  lineItemFailureSimulation = false;
  clearCheckoutSimulation();
  updateSimulationButton();
  cursor = 0;
  generation += 1;
}

function clearCheckoutSimulation(): void {
  for (const timer of checkoutTimers) window.clearTimeout(timer);
  checkoutTimers = [];
  checkoutPhase = "idle";
  checkoutRevision = 0;
}

function updateSimulationButton(): void {
  const available = Boolean(latestDetail?.basket?.items.length);
  simulateLineItemButton.disabled = !available;
  simulateLineItemButton.dataset.active = String(lineItemFailureSimulation);
  simulateLineItemButton.textContent = lineItemFailureSimulation
    ? "clear line-item failure"
    : "simulate line-item failure";
  simulateBatchTwoButton.disabled = !latestDetail?.basket?.items.length;
  simulateBatchTwoButton.dataset.active = String(checkoutPhase !== "idle");
  simulateBatchTwoButton.textContent = checkoutPhase === "idle"
    ? "simulate checkout loop"
    : "clear checkout simulation";
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

function baseNodeDetails(detail: MissionDetail, routes: CheckoutRoute[]): NodeDetails {
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
      description: "Constraints and intent are locked before the cart can be purchased.",
      tone: "info",
    }],
  };
  const snapshot: NodeDetail[] = [];
  if (storeCount > 0) {
    snapshot.push({
      title: `${catalogOffers.length} live catalog offers`,
      meta: `${storeCount} store endpoints`,
      description: "GET /v1/catalog/offers supplies price and availability snapshots.",
      tone: "info",
    });
  }
  snapshot.push(...storeRouteDetails(routes));
  if (snapshot.length > 0) details.snapshot = snapshot;
  if (checkoutPhase !== "idle") {
    const event = checkoutPhase === "batch1_purchased"
      ? "payment.authorized"
      : checkoutPhase === "batch2_declined"
        ? "payment.declined"
        : checkoutPhase === "batch2_rerouted"
          ? "portfolio.replanned"
          : "payment.attempted";
    details.model = [{
      title: `Projection recalculated · revision ${checkoutRevision}`,
      meta: `Hook fired from ${event}`,
      description: "The dashboard refreshes after this event and continues its one-second live poll.",
      tone: checkoutPhase === "batch2_declined" || checkoutPhase === "batch2_rerouted" ? "warn" : "ok",
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

function checkoutPresentation(detail: MissionDetail, routes: CheckoutRoute[]): MissionDetail {
  if (checkoutPhase === "idle" || !detail.basket) return detail;

  const totalFor = (batch: number): number => routes
    .find((route) => route.batch === batch)
    ?.items.reduce((sum, item) => sum + item.line_total, 0) ?? 0;
  const firstStore = routes.find((route) => route.batch === 1)?.storeName ?? "store group 1";
  const secondStore = routes.find((route) => route.batch === 2)?.storeName ?? "store group 2";
  const retryPayments: MissionDetail["payment_attempts"] = routes
    .filter((route) => route.batch !== 1)
    .map((route) => ({
      provider: `PSP_SIM / ${route.storeName}`,
      amount: totalFor(route.batch),
      currency: detail.basket!.currency,
      status: "attempted",
      decline_code: null,
      simulated: true,
    }));
  const payments: MissionDetail["payment_attempts"] = checkoutPhase === "batch1_processing"
    ? [{ provider: `PSP_SIM / ${firstStore}`, amount: totalFor(1), currency: detail.basket.currency, status: "attempted", decline_code: null, simulated: true }]
    : checkoutPhase === "batch1_purchased"
      ? [{ provider: `PSP_SIM / ${firstStore}`, amount: totalFor(1), currency: detail.basket.currency, status: "authorized", decline_code: null, simulated: true }]
      : checkoutPhase === "batch2_rerouted"
        ? [
            { provider: `PSP_SIM / ${firstStore}`, amount: totalFor(1), currency: detail.basket.currency, status: "authorized", decline_code: null, simulated: true },
            { provider: "PSP_SIM / Smyk", amount: retryPayments.reduce((sum, payment) => sum + payment.amount, 0), currency: detail.basket.currency, status: "declined", decline_code: "SIMULATED_BATCH_2_DECLINE", simulated: true },
            ...retryPayments,
          ]
        : [
            { provider: `PSP_SIM / ${firstStore}`, amount: totalFor(1), currency: detail.basket.currency, status: "authorized", decline_code: null, simulated: true },
            { provider: `PSP_SIM / ${secondStore}`, amount: totalFor(2), currency: detail.basket.currency, status: "declined", decline_code: "SIMULATED_BATCH_2_DECLINE", simulated: true },
          ];
  const status = checkoutPhase === "batch1_processing"
    ? "checkout_in_progress"
    : checkoutPhase === "batch1_purchased"
      ? "batch_1_purchased"
      : checkoutPhase === "batch2_rerouted"
        ? "replacement_portfolio_processing"
        : "payment_retry_required";

  return {
    ...detail,
    basket: { ...detail.basket, status },
    order: null,
    payment_attempts: payments,
  };
}

function renderWorkflow(detail: MissionDetail): void {
  const plannedRoutes = buildCheckoutRoutes(detail.basket?.items ?? [], catalogOffers);
  const routes = checkoutPhase === "batch2_rerouted" ? rerouteDeclinedBatch(plannedRoutes) : plannedRoutes;
  const portfolio = portfolioFlow.update(detail, routes, checkoutPhase);
  graph.setCartSnapshot({
    status: detail.mission.status,
    progress: detail.mission.progress,
    budgetLimit: detail.mission.budget_limit,
    currency: detail.mission.currency,
    recoveredFailures: detail.metrics.recovered_failures,
    latestUpdate: detail.mission.latest_update,
  });
  graph.setCartCheckout(checkoutPresentation(detail, routes));
  graph.setTopology(portfolio.topology);
  graph.setNodeSubtitles({
    ...portfolio.subtitles,
    snapshot: routes.length > 0 ? `${routes.length} identified stores` : undefined,
  });
  const batchDetails = storeBatchDetails(routes, checkoutPhase);
  graph.setNodeDetails(mergeNodeDetails(baseNodeDetails(detail, routes), portfolio.details, { purchase: batchDetails }));
}

function renderDetail(detail: MissionDetail): void {
  latestDetail = detail;
  const renderedDetail = lineItemFailureSimulation ? simulateLineItemPaymentFailure(detail) : detail;
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
  renderWorkflow(replayDetail(step.type));
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
  renderWorkflow(replayDetail("mission.created"));
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
  if (!latestDetail?.basket?.items.length) return;
  if (checkoutPhase !== "idle") {
    clearCheckoutSimulation();
    renderDetail(latestDetail);
    return;
  }

  checkoutPhase = "batch1_processing";
  checkoutRevision = 0;
  dispatch({
    type: "payment.attempted",
    title: "Batch 1 payment started",
    severity: "info",
    created_at: new Date().toISOString(),
  });
  renderDetail(latestDetail);
  checkoutTimers = [
    window.setTimeout(() => {
      checkoutPhase = "batch1_purchased";
      checkoutRevision = 1;
      dispatch({
        type: "payment.authorized",
        title: "Batch 1 purchased — projection recalculated",
        severity: "info",
        created_at: new Date().toISOString(),
      });
      if (latestDetail) renderDetail(latestDetail);
    }, 1400),
    window.setTimeout(() => {
      checkoutPhase = "batch2_declined";
      checkoutRevision = 2;
      dispatch({
        type: "payment.declined",
        title: "Batch 2 declined — remaining cart recalculated",
        severity: "warning",
        created_at: new Date().toISOString(),
      });
      if (latestDetail) renderDetail(latestDetail);
    }, 3000),
    window.setTimeout(() => {
      checkoutPhase = "batch2_rerouted";
      checkoutRevision = 3;
      dispatch({
        type: "portfolio.replanned",
        title: "New portfolio split the failed group across Party&Co and Fresh Day",
        severity: "info",
        created_at: new Date().toISOString(),
      });
      dispatch({
        type: "payment.attempted",
        title: "Replacement-store payment retries started",
        severity: "info",
        created_at: new Date().toISOString(),
      });
      if (latestDetail) renderDetail(latestDetail);
    }, 4600),
  ];
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
