import { productName } from "./detail";
import type { CheckoutRoute, CheckoutSimulationPhase } from "./store-batches";
import type { BasketItem, MissionDetail, NodeDetail, NodeDetails, NodeId, NodeSubtitles, ProductStoreRoute } from "./types";

type ItemState =
  | "planned"
  | "awaiting_approval"
  | "ready_to_purchase"
  | "processing"
  | "payment_failed"
  | "paid"
  | "purchased"
  | "recovered";

interface ItemProgress {
  item: BasketItem;
  node: NodeId;
  state: ItemState;
  simulated: boolean;
  route?: CheckoutRoute;
}

export interface PortfolioSnapshot {
  subtitles: NodeSubtitles;
  details: NodeDetails;
  topology: ProductStoreRoute[];
}

export interface PortfolioFlow {
  update(detail: MissionDetail, routes: CheckoutRoute[], phase: CheckoutSimulationPhase): PortfolioSnapshot;
  reset(): void;
}

const STATE_LABEL: Record<ItemState, string> = {
  planned: "Planned",
  awaiting_approval: "Awaiting approval",
  ready_to_purchase: "Queued for purchase",
  processing: "Payment in progress",
  payment_failed: "Payment failed",
  paid: "Paid - confirming order",
  purchased: "Purchased",
  recovered: "Retry passed",
};

function simulatedProgress(item: BasketItem, route: CheckoutRoute | undefined, phase: CheckoutSimulationPhase): ItemProgress | null {
  if (phase === "idle") return null;
  if (!route) return null;
  if (phase === "batch2_rerouted") {
    return route.batch === 1
      ? { item, node: "result", state: "purchased", simulated: true, route }
      : { item, node: "purchase", state: "processing", simulated: true, route };
  }
  if (route.batch === 1) {
    if (phase === "batch1_processing") return { item, node: "purchase", state: "processing", simulated: true, route };
    return { item, node: "result", state: "purchased", simulated: true, route };
  }
  if (phase === "batch2_declined") return { item, node: "purchase", state: "payment_failed", simulated: true, route };
  if (phase === "batch1_purchased") return { item, node: "purchase", state: "ready_to_purchase", simulated: true, route };
  return { item, node: "model", state: "planned", simulated: true, route };
}

function progressFor(item: BasketItem, detail: MissionDetail, routes: CheckoutRoute[], phase: CheckoutSimulationPhase): ItemProgress {
  const route = routes.find((candidate) => candidate.items.some((entry) => entry.product_id === item.product_id));
  const simulated = simulatedProgress(item, route, phase);
  if (simulated) return simulated;

  const lineDeclines = detail.payment_attempts.filter(
    (payment) => payment.status === "declined" && payment.product_id === item.product_id,
  );
  const lineRecovered = detail.payment_attempts.some(
    (payment) => payment.status === "authorized" && payment.product_id === item.product_id,
  );
  const simulatedFailure = lineDeclines.some((payment) => payment.simulated);
  const globalDecline = detail.payment_attempts.some(
    (payment) => payment.status === "declined" && !payment.product_id,
  );
  const hasAuthorisedPayment = detail.payment_attempts.some((payment) => payment.status === "authorized");

  if (lineDeclines.length > 0 && !lineRecovered) return { item, node: "purchase", state: "payment_failed", simulated: simulatedFailure, route };
  if (lineRecovered) return { item, node: detail.order ? "result" : "purchase", state: "recovered", simulated: simulatedFailure, route };
  if (globalDecline && !hasAuthorisedPayment && !detail.order) return { item, node: "purchase", state: "payment_failed", simulated: false, route };
  if (detail.order || detail.basket?.status === "ordered") return { item, node: "result", state: "purchased", simulated: false, route };
  if (hasAuthorisedPayment) return { item, node: "purchase", state: "paid", simulated: false, route };
  if (detail.approval?.status === "pending") return { item, node: "guardrails", state: "awaiting_approval", simulated: false, route };
  if (detail.approval?.status === "approved" || detail.funding.status !== "not_ready") return { item, node: "purchase", state: "ready_to_purchase", simulated: false, route };
  return { item, node: "model", state: "planned", simulated: false, route };
}

function detailFor(progress: ItemProgress): NodeDetail {
  const tone = progress.state === "payment_failed"
    ? "error"
    : progress.state === "purchased" || progress.state === "paid"
      ? "ok"
      : progress.state === "planned"
        ? "info"
        : "warn";
  const routeState = progress.state === "payment_failed"
    ? "error"
    : progress.state === "purchased" || progress.state === "recovered"
      ? "ok"
      : "default";
  const destination = progress.state === "payment_failed"
    ? "Purchase blocked"
    : progress.state === "purchased" || progress.state === "recovered"
      ? "Result"
      : "Purchase";
  return {
    title: productName(progress.item.product_id),
    meta: `${progress.item.quantity} × ${STATE_LABEL[progress.state]}`,
    description: progress.route
      ? `Endpoint: ${progress.route.endpoint}${progress.simulated ? " · checkout simulation" : ""}`
      : "Connected to the default checkout route.",
    route: progress.route
      ? {
          label: `ROUTE B${progress.route.batch}: ${progress.route.storeName} → Snapshot → ${destination}`,
          state: routeState,
        }
      : {
          label: "ROUTE: default store → Snapshot → Purchase",
          state: "default",
        },
    tone,
  };
}

function subtitles(items: ItemProgress[]): NodeSubtitles {
  const byNode = (node: NodeId) => items.filter((item) => item.node === node);
  const planned = byNode("model");
  const approval = byNode("guardrails");
  const purchase = byNode("purchase");
  const result = byNode("result");
  const failed = purchase.filter((item) => item.state === "payment_failed");
  const activePurchase = purchase.filter((item) => item.state !== "payment_failed");
  const output: NodeSubtitles = { model: `${items.length} cart items` };
  if (planned.length > 0) output.model = `${planned.length} planned`;
  if (approval.length > 0) output.guardrails = `${approval.length} awaiting approval`;
  if (failed.length > 0 || activePurchase.length > 0) {
    output.purchase = [
      failed.length > 0 ? `${failed.length} failed` : null,
      activePurchase.length > 0 ? `${activePurchase.length} in purchase` : null,
    ].filter(Boolean).join(" · ");
  }
  if (result.length > 0) output.result = `${result.length} purchased`;
  return output;
}

function topologyRoute(progress: ItemProgress): ProductStoreRoute {
  const route = progress.route ?? {
    batch: 1 as const,
    storeId: "store-delio",
    storeName: "delio",
    endpoint: "GET /v1/catalog/offers?store_id=store-delio&available=true",
    items: [],
  };
  const state = progress.state === "payment_failed"
    ? "failed"
    : progress.state === "processing"
      ? "processing"
      : progress.state === "purchased" || progress.state === "recovered"
        ? "purchased"
        : "planned";
  return {
    productId: progress.item.product_id,
    title: productName(progress.item.product_id),
    quantity: progress.item.quantity,
    storeId: route.storeId,
    storeName: route.storeName,
    endpoint: route.endpoint,
    state,
    simulated: progress.simulated,
  };
}

export function createPortfolioFlow(): PortfolioFlow {
  return {
    update(detail, routes, phase) {
      if (!detail.basket) return { subtitles: {}, details: {}, topology: [] };
      const items = detail.basket.items.map((item) => progressFor(item, detail, routes, phase));
      const details: NodeDetails = {};
      for (const item of items) {
        const list = details[item.node] ?? [];
        list.push(detailFor(item));
        details[item.node] = list;
      }
      return { subtitles: subtitles(items), details, topology: items.map(topologyRoute) };
    },
    reset() {},
  };
}
