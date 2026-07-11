import { productName } from "./detail";
import type { BasketItem, MissionDetail, NodeDetail, NodeDetails, NodeId, NodeSubtitles } from "./types";

type ItemState =
  | "planned"
  | "awaiting_approval"
  | "ready_to_purchase"
  | "payment_failed"
  | "paid"
  | "purchased"
  | "recovered";

interface ItemProgress {
  item: BasketItem;
  node: NodeId;
  state: ItemState;
  simulated: boolean;
}

export interface PortfolioSnapshot {
  subtitles: NodeSubtitles;
  details: NodeDetails;
}

export interface PortfolioFlow {
  update(detail: MissionDetail): PortfolioSnapshot;
  reset(): void;
}

const STATE_LABEL: Record<ItemState, string> = {
  planned: "Planned",
  awaiting_approval: "Awaiting approval",
  ready_to_purchase: "Queued for purchase",
  payment_failed: "Payment failed",
  paid: "Paid - confirming order",
  purchased: "Purchased",
  recovered: "Retry passed",
};

function progressFor(item: BasketItem, detail: MissionDetail): ItemProgress {
  const lineDeclines = detail.payment_attempts.filter(
    (payment) => payment.status === "declined" && payment.product_id === item.product_id,
  );
  const lineRecovered = detail.payment_attempts.some(
    (payment) => payment.status === "authorized" && payment.product_id === item.product_id,
  );
  const simulated = lineDeclines.some((payment) => payment.simulated);
  const globalDecline = detail.payment_attempts.some(
    (payment) => payment.status === "declined" && !payment.product_id,
  );
  const hasAuthorisedPayment = detail.payment_attempts.some((payment) => payment.status === "authorized");

  if (lineDeclines.length > 0 && !lineRecovered) return { item, node: "purchase", state: "payment_failed", simulated };
  if (lineRecovered) return { item, node: detail.order ? "result" : "purchase", state: "recovered", simulated };
  if (globalDecline && !hasAuthorisedPayment && !detail.order) return { item, node: "purchase", state: "payment_failed", simulated: false };
  if (detail.order || detail.basket?.status === "ordered") return { item, node: "result", state: "purchased", simulated: false };
  if (hasAuthorisedPayment) return { item, node: "purchase", state: "paid", simulated: false };
  if (detail.approval?.status === "pending") return { item, node: "guardrails", state: "awaiting_approval", simulated: false };
  if (detail.approval?.status === "approved" || detail.funding.status !== "not_ready") return { item, node: "purchase", state: "ready_to_purchase", simulated: false };
  return { item, node: "model", state: "planned", simulated: false };
}

function detailFor(progress: ItemProgress): NodeDetail {
  const tone = progress.state === "payment_failed"
    ? "error"
    : progress.state === "purchased" || progress.state === "paid"
      ? "ok"
      : progress.state === "planned"
        ? "info"
        : "warn";
  return {
    title: productName(progress.item.product_id),
    meta: `${progress.item.quantity} × ${STATE_LABEL[progress.state]}`,
    description: progress.simulated ? "Dashboard simulation" : undefined,
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
  const output: NodeSubtitles = { model: `${items.length} basket items` };
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

export function createPortfolioFlow(): PortfolioFlow {
  return {
    update(detail) {
      if (!detail.basket) return { subtitles: {}, details: {} };
      const items = detail.basket.items.map((item) => progressFor(item, detail));
      const details: NodeDetails = {};
      for (const item of items) {
        const list = details[item.node] ?? [];
        list.push(detailFor(item));
        details[item.node] = list;
      }
      return { subtitles: subtitles(items), details };
    },
    reset() {},
  };
}
