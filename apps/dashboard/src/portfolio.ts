import { productName } from "./detail";
import { NODES } from "./mapping";
import type { BasketItem, MissionDetail, NodeId, NodeSubtitles } from "./types";

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

export interface PortfolioFlow {
  update(detail: MissionDetail): NodeSubtitles;
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
  const hasAuthorisedPayment = detail.payment_attempts.some(
    (payment) => payment.status === "authorized",
  );

  if (lineDeclines.length > 0 && !lineRecovered) {
    return { item, node: "purchase", state: "payment_failed", simulated };
  }
  if (lineRecovered) {
    return {
      item,
      node: detail.order ? "result" : "purchase",
      state: "recovered",
      simulated,
    };
  }
  if (globalDecline && !hasAuthorisedPayment && !detail.order) {
    return { item, node: "purchase", state: "payment_failed", simulated: false };
  }
  if (detail.order || detail.basket?.status === "ordered") {
    return { item, node: "result", state: "purchased", simulated: false };
  }
  if (hasAuthorisedPayment) {
    return { item, node: "purchase", state: "paid", simulated: false };
  }
  if (detail.approval?.status === "pending") {
    return { item, node: "guardrails", state: "awaiting_approval", simulated: false };
  }
  if (detail.approval?.status === "approved" || detail.funding.status !== "not_ready") {
    return { item, node: "purchase", state: "ready_to_purchase", simulated: false };
  }
  return { item, node: "model", state: "planned", simulated: false };
}

function makeCard(progress: ItemProgress): HTMLElement {
  const card = document.createElement("div");
  card.className = "portfolio-card";
  card.dataset.state = progress.state;
  const name = document.createElement("strong");
  name.textContent = productName(progress.item.product_id);
  const status = document.createElement("span");
  status.textContent = `${progress.item.quantity} × ${STATE_LABEL[progress.state]}${progress.simulated ? " · simulation" : ""}`;
  card.append(name, status);
  return card;
}

function nodeSubtitles(items: ItemProgress[]): NodeSubtitles {
  const byNode = (node: NodeId) => items.filter((item) => item.node === node);
  const planned = byNode("model");
  const pendingApproval = byNode("guardrails");
  const purchase = byNode("purchase");
  const bought = byNode("result");
  const failed = purchase.filter((item) => item.state === "payment_failed");
  const paid = purchase.filter((item) => item.state === "paid" || item.state === "ready_to_purchase");
  const subtitles: NodeSubtitles = { model: `${items.length} basket items` };
  if (planned.length > 0) subtitles.model = `${planned.length} planned`;
  if (pendingApproval.length > 0) subtitles.guardrails = `${pendingApproval.length} awaiting approval`;
  if (failed.length > 0 || paid.length > 0) {
    subtitles.purchase = [
      failed.length > 0 ? `${failed.length} failed` : null,
      paid.length > 0 ? `${paid.length} in purchase` : null,
    ].filter(Boolean).join(" · ");
  }
  if (bought.length > 0) subtitles.result = `${bought.length} purchased`;
  return subtitles;
}

export function createPortfolioFlow(container: HTMLElement): PortfolioFlow {
  return {
    update(detail) {
      container.replaceChildren();
      if (!detail.basket) {
        container.textContent = "Basket items will attach to the workflow after planning.";
        container.className = "basket-flow basket-flow-empty";
        return {};
      }

      container.className = "basket-flow";
      const heading = document.createElement("div");
      heading.className = "basket-flow-heading";
      const title = document.createElement("strong");
      title.textContent = "Cart attached to workflow nodes";
      const hint = document.createElement("span");
      hint.textContent = "Each item sits at its latest confirmed step.";
      heading.append(title, hint);

      const progress = detail.basket.items.map((item) => progressFor(item, detail));
      const track = document.createElement("div");
      track.className = "basket-flow-track";
      for (const node of NODES) {
        const column = document.createElement("section");
        column.className = "portfolio-node";
        column.dataset.node = node.id;
        const nodeName = document.createElement("span");
        nodeName.className = "portfolio-node-name";
        nodeName.textContent = `${node.num}. ${node.name}`;
        const cards = document.createElement("div");
        cards.className = "portfolio-cards";
        for (const item of progress.filter((entry) => entry.node === node.id)) cards.append(makeCard(item));
        column.append(nodeName, cards);
        track.append(column);
      }

      container.append(heading, track);
      return nodeSubtitles(progress);
    },
    reset() {
      container.replaceChildren();
      container.className = "basket-flow basket-flow-empty";
    },
  };
}
