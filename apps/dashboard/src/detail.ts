import type { MissionDetail, PaymentAttempt } from "./types";

export interface DetailPanel {
  update(detail: MissionDetail): void;
  showReplay(eventType: string): void;
  reset(): void;
}

type Tone = "info" | "warn" | "ok";

const ENGLISH_PRODUCT_NAMES: Record<string, string> = {
  "cake-vanilla": "Nut-free vanilla cake",
  "candles-ten": "Birthday candles",
  "decor-balloons": "Biodegradable balloons",
  "decor-banner": "Happy Birthday banner",
  "drink-apple": "Apple juice 1 L",
  "drink-water": "Still water 1.5 L",
  "napkins-color": "Colourful napkins",
  "snack-pretzels": "Mini pretzels",
  "snack-crackers": "Nut-free crackers",
  "table-cups": "Paper cups",
  "table-plates": "Paper plates",
};

function productName(productId: string | null | undefined): string {
  if (productId && ENGLISH_PRODUCT_NAMES[productId]) return ENGLISH_PRODUCT_NAMES[productId];
  const identifier = productId?.replace(/^product-/, "").toUpperCase() || "UNSPECIFIED";
  return `Catalog item ${identifier}`;
}

function element(tag: string, className?: string): HTMLElement {
  const item = document.createElement(tag);
  if (className) item.className = className;
  return item;
}

function label(value: string | null | undefined): string {
  if (!value) return "Not ready";
  return value
    .split(/[_-]/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function money(value: number | null | undefined, currency?: string | null): string {
  if (value == null || !Number.isFinite(value)) return "—";
  try {
    return new Intl.NumberFormat("en-GB", {
      style: "currency",
      currency: currency ?? "PLN",
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${value.toFixed(2)} ${currency ?? ""}`.trim();
  }
}

function dateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}

function section(title: string): { root: HTMLElement; body: HTMLElement } {
  const root = element("section", "detail-section");
  const heading = element("h2", "detail-heading");
  heading.textContent = title;
  const body = element("div", "detail-body");
  root.append(heading, body);
  return { root, body };
}

function metric(labelText: string, value: string): HTMLElement {
  const root = element("div", "metric");
  const name = element("span", "metric-label");
  name.textContent = labelText;
  const content = element("strong", "metric-value");
  content.textContent = value;
  root.append(name, content);
  return root;
}

function note(text: string): HTMLElement {
  const root = element("p", "detail-note");
  root.textContent = text;
  return root;
}

function paymentRow(payment: PaymentAttempt): HTMLElement {
  const root = element("div", "payment-row");
  root.dataset.tone = payment.status === "authorized" ? "ok" : payment.status === "declined" ? "warn" : "info";
  const provider = element("strong");
  provider.textContent = payment.provider;
  const status = element("span", "payment-status");
  status.textContent = label(payment.status);
  const detail = element("span", "payment-detail");
  detail.textContent = [
    money(payment.amount, payment.currency),
    payment.product_id ? `Line item: ${productName(payment.product_id)}` : null,
    payment.decline_code,
  ].filter(Boolean).join(" · ");
  root.append(provider, status, detail);
  return root;
}

function paymentIncident(detail: MissionDetail): HTMLElement | null {
  const declined = detail.payment_attempts.find((payment) => payment.status === "declined");
  if (!declined) return null;

  const recoveredBy = declined.simulated
    ? undefined
    : detail.payment_attempts.find((payment) => payment.status === "authorized");
  const root = element("div", "payment-incident");
  root.dataset.recovered = String(Boolean(recoveredBy));
  const title = element("strong");
  title.textContent = declined.simulated
    ? "Simulated line-item payment failure"
    : recoveredBy ? "Payment failure recovered" : "Payment failed";
  const body = element("span");
  const failedAttempt = `${declined.provider} declined ${money(declined.amount, declined.currency)}${declined.decline_code ? ` (${declined.decline_code})` : ""}`;
  const failedLine = declined.product_id ? ` for ${productName(declined.product_id)}` : "";
  body.textContent = declined.simulated
    ? `${failedAttempt}${failedLine}. This is a dashboard-only simulation: it does not change the API, reservation or order.`
    : recoveredBy
    ? `${failedAttempt}. The failed attempt created no order; ${recoveredBy.provider} authorised the retry.`
    : `${failedAttempt}. No order has been confirmed from this attempt; the workflow is waiting to reroute or request action.`;
  root.append(title, body);
  return root;
}

function purchaseState(detail: MissionDetail): { title: string; body: string; tone: Tone } {
  const pendingAction = detail.action_requests.find((item) => item.status === "pending");
  const lastPayment = detail.payment_attempts.at(-1);

  if (detail.order) {
    return {
      title: "Purchased",
      body: `Order ${detail.order.confirmation_code} is ${label(detail.order.status).toLowerCase()}. Delivery: ${dateTime(detail.order.delivery_at)}.`,
      tone: "ok",
    };
  }
  if (pendingAction) {
    return { title: "Input needed", body: pendingAction.question, tone: "warn" };
  }
  if (detail.approval?.status === "pending") {
    return {
      title: "Waiting for approval",
      body: `${detail.approval.question} Nothing is reserved or charged until this approval is resolved.`,
      tone: "warn",
    };
  }
  if (lastPayment?.status === "declined") {
    return {
      title: "Retrying payment",
      body: `${lastPayment.provider} declined the charge${lastPayment.decline_code ? ` (${lastPayment.decline_code})` : ""}. The workflow can reroute to another provider.`,
      tone: "warn",
    };
  }
  if (lastPayment?.status === "authorized") {
    return {
      title: "Payment authorised",
      body: "The charge is authorised. The workflow is confirming the order and delivery.",
      tone: "ok",
    };
  }
  if (detail.funding.status !== "not_ready") {
    return {
      title: "Ready to purchase",
      body: "After approval, stock is reserved, a tokenised card is requested, then the payment and order confirmation run.",
      tone: "info",
    };
  }
  if (detail.basket) {
    return {
      title: "Basket planned",
      body: "The basket is being checked against policy before any inventory or payment action.",
      tone: "info",
    };
  }
  return { title: "Planning in progress", body: "The workflow is collecting the information needed to build a safe basket.", tone: "info" };
}

function purchasePath(detail: MissionDetail): HTMLElement {
  const hasPayment = detail.payment_attempts.length > 0;
  const approved = detail.approval?.status === "approved" || detail.approval?.status === "skipped" || hasPayment || detail.order != null;
  const reserved = hasPayment || detail.funding.status !== "not_ready" || detail.order != null;
  const charged = detail.payment_attempts.some((payment) => payment.status === "authorized") || detail.order != null;
  const confirmed = detail.order != null;
  const stages = [
    ["1. Approve", approved],
    ["2. Reserve", reserved],
    ["3. Charge", charged],
    ["4. Confirm", confirmed],
  ] as const;
  const activeIndex = stages.findIndex(([, complete]) => !complete);
  const path = element("div", "purchase-path");
  for (const [index, [name, complete]] of stages.entries()) {
    const step = element("span", "purchase-step");
    step.dataset.state = complete ? "done" : index === activeIndex ? "active" : "idle";
    step.textContent = name;
    path.append(step);
  }
  return path;
}

/**
 * A client-only demonstration of one split-payment line failing. It never
 * writes to the API and is deliberately labelled as simulated in the UI.
 */
export function simulateLineItemPaymentFailure(detail: MissionDetail): MissionDetail {
  const target = detail.basket?.items.at(-1);
  if (!target || detail.payment_attempts.some((payment) => payment.simulated)) return detail;
  return {
    ...detail,
    payment_attempts: [
      ...detail.payment_attempts,
      {
        provider: "PSP_SIM",
        amount: target.line_total,
        currency: target.currency,
        status: "declined",
        decline_code: "SIMULATED_LINE_ITEM_DECLINE",
        product_id: target.product_id,
        product_name: target.name,
        simulated: true,
      },
    ],
  };
}

function render(container: HTMLElement, detail: MissionDetail): void {
  container.replaceChildren();

  const snapshot = section("Mission snapshot");
  const metricGrid = element("div", "metric-grid");
  metricGrid.append(
    metric("Progress", `${Math.round(detail.mission.progress * 100)}%`),
    metric("Budget", money(detail.mission.budget_limit, detail.mission.currency)),
    metric("Recovered", String(detail.metrics.recovered_failures)),
  );
  snapshot.body.append(metricGrid, note(detail.mission.latest_update));

  const basketSection = section("Basket");
  if (!detail.basket) {
    basketSection.body.append(note("No basket yet. Items will appear here as soon as the plan is created."));
  } else {
    const merchant = element("div", "basket-meta");
    merchant.textContent = `${detail.basket.merchant?.name ?? "Merchant pending"} · ${detail.basket.item_count} items · ${label(detail.basket.status)}`;
    const list = element("div", "basket-list");
    const failedLineItems = new Set(
      detail.payment_attempts
        .filter((payment) => payment.status === "declined" && payment.product_id)
        .map((payment) => payment.product_id),
    );
    for (const item of detail.basket.items) {
      const row = element("div", "basket-item");
      const failed = failedLineItems.has(item.product_id);
      row.classList.toggle("payment-failed", failed);
      const name = element("strong", "basket-name");
      name.textContent = productName(item.product_id);
      const price = element("span", "basket-price");
      price.textContent = `${item.quantity} × ${money(item.unit_price, item.currency)} = ${money(item.line_total, item.currency)}`;
      row.append(name, price);
      if (item.replaced_product_name) {
        const replacement = element("span", "basket-replacement");
        replacement.textContent = `Replaced: ${productName(item.replaced_product_id)}`;
        row.append(replacement);
      }
      if (failed) {
        const paymentFailure = element("span", "basket-payment-failure");
        paymentFailure.textContent = "Line-item payment failed";
        row.append(paymentFailure);
      }
      list.append(row);
    }
    const total = element("div", "basket-total");
    total.textContent = `Total  ${money(detail.basket.total, detail.basket.currency)}`;
    basketSection.body.append(merchant, list, total);
  }

  const purchase = section("Purchase state");
  const state = purchaseState(detail);
  const stateCard = element("div", "purchase-state");
  stateCard.dataset.tone = state.tone;
  const stateTitle = element("strong");
  stateTitle.textContent = state.title;
  const stateBody = element("span");
  stateBody.textContent = state.body;
  stateCard.append(stateTitle, stateBody);
  purchase.body.append(stateCard, purchasePath(detail));

  const payments = section("Payment trail");
  const incident = paymentIncident(detail);
  if (incident) payments.body.append(incident);
  if (detail.payment_attempts.length === 0) {
    payments.body.append(note("No payment attempt has been made."));
  } else {
    const list = element("div", "payment-list");
    for (const payment of detail.payment_attempts) list.append(paymentRow(payment));
    payments.body.append(list);
  }

  container.append(snapshot.root, basketSection.root, purchase.root, payments.root);
}

function replayDetail(eventType: string): MissionDetail {
  const paymentFailureVisible = ["payment.declined", "payment.rerouted", "payment.authorized", "order.confirmed", "mission.completed"].includes(eventType);
  const paid = ["payment.authorized", "order.confirmed", "mission.completed"].includes(eventType);
  const ordered = ["order.confirmed", "mission.completed"].includes(eventType);
  const waitingForApproval = ["approval.requested", "price.changed", "portfolio.replanned", "approval.superseded"].includes(eventType);
  const paymentAttempts: PaymentAttempt[] = paymentFailureVisible
    ? [
        {
          provider: "PSP_A",
          amount: 20.97,
          currency: "PLN",
          status: "declined",
          decline_code: "DO_NOT_HONOR",
          product_id: "snack-pretzels",
          product_name: "Mini pretzels",
          simulated: true,
        },
        ...(paid
          ? [{ provider: "PSP_B", amount: 20.97, currency: "PLN", status: "authorized", decline_code: null, product_id: "snack-pretzels", product_name: "Mini pretzels", simulated: true }]
          : []),
      ]
    : [];

  return {
    mission: {
      id: "replay",
      title: "Maya's birthday - sample mission",
      status: ordered ? "completed" : waitingForApproval ? "approval_required" : "planning",
      created_at: new Date().toISOString(),
      current_step: ordered ? 7 : 4,
      total_steps: 7,
      progress: ordered ? 1 : 0.57,
      latest_update: "Sample data - connect the API to inspect a live mission.",
      budget_limit: 250,
      currency: "PLN",
    },
    basket: {
      merchant: { id: "party-market", name: "Party Market", reliability_score: 0.96 },
      item_count: 6,
      total: 128.41,
      currency: "PLN",
      status: ordered ? "ordered" : "planned",
      items: [
        { id: "cake", product_id: "cake-vanilla", name: "Nut-free vanilla cake", quantity: 1, unit_price: 62, line_total: 62, currency: "PLN", substitution_allowed: false, replaced_product_id: null, replaced_product_name: null },
        { id: "balloons", product_id: "decor-balloons", name: "Biodegradable balloons", quantity: 2, unit_price: 13.5, line_total: 27, currency: "PLN", substitution_allowed: true, replaced_product_id: null, replaced_product_name: null },
        { id: "juice", product_id: "drink-apple", name: "Apple juice 1 L", quantity: 3, unit_price: 6.47, line_total: 19.41, currency: "PLN", substitution_allowed: true, replaced_product_id: null, replaced_product_name: null },
        { id: "pretzels", product_id: "snack-pretzels", name: "Mini pretzels", quantity: 3, unit_price: 6.99, line_total: 20.97, currency: "PLN", substitution_allowed: true, replaced_product_id: null, replaced_product_name: null },
      ],
    },
    approval: waitingForApproval ? { question: "Approve the planned basket for 128.41 PLN?", status: "pending", amount: 128.41, currency: "PLN", expires_at: null } : null,
    action_requests: [],
    funding: { status: paid || ordered ? "used_closed" : "not_ready" },
    payment_attempts: paymentAttempts,
    order: ordered ? { confirmation_code: "DONE-EXAMPLE", status: "confirmed", total: 128.41, currency: "PLN", delivery_at: "2026-07-12T12:00:00+02:00" } : null,
    metrics: { budget_variance: 121.59, recovered_failures: eventType === "mission.completed" ? 2 : 0, payment_attempts: paymentAttempts.length },
  };
}

export function createDetailPanel(container: HTMLElement): DetailPanel {
  return {
    update(detail) {
      render(container, detail);
    },
    showReplay(eventType) {
      render(container, replayDetail(eventType));
    },
    reset() {
      container.replaceChildren();
    },
  };
}
