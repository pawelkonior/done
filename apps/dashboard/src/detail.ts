import type { MissionDetail, PaymentAttempt } from "./types";

export type CheckoutTone = "info" | "warn" | "ok" | "error";

export interface PurchaseStage {
  name: string;
  state: "done" | "active" | "idle";
}

export interface PaymentDisplay {
  provider: string;
  status: string;
  detail: string;
  tone: "info" | "ok" | "warn";
}

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

export function productName(productId: string | null | undefined): string {
  if (productId && ENGLISH_PRODUCT_NAMES[productId]) return ENGLISH_PRODUCT_NAMES[productId];
  const identifier = productId?.replace(/^product-/, "").toUpperCase() || "UNSPECIFIED";
  return `Catalog item ${identifier}`;
}

function label(value: string | null | undefined): string {
  if (!value) return "Not ready";
  return value
    .split(/[_-]/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function formatMoney(value: number | null | undefined, currency?: string | null): string {
  if (value == null || !Number.isFinite(value)) return "-";
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
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}

export function purchaseState(detail: MissionDetail): { title: string; body: string; tone: CheckoutTone } {
  const pendingAction = detail.action_requests.find((item) => item.status === "pending");
  const lastPayment = detail.payment_attempts.at(-1);

  if (detail.order) {
    return {
      title: "Purchased",
      body: `Order ${detail.order.confirmation_code} is ${label(detail.order.status).toLowerCase()}. Delivery: ${dateTime(detail.order.delivery_at)}.`,
      tone: "ok",
    };
  }
  if (pendingAction) return { title: "Input needed", body: pendingAction.question, tone: "warn" };
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
  if (lastPayment?.status === "attempted") {
    return {
      title: "Payment in progress",
      body: `${lastPayment.provider} is processing the charge. The cart will be recalculated when the provider responds.`,
      tone: "info",
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
      title: "Cart planned",
      body: "The cart is being checked against policy before any inventory or payment action.",
      tone: "info",
    };
  }
  return { title: "Planning in progress", body: "The workflow is collecting the information needed to build a safe cart.", tone: "info" };
}

export function purchaseStages(detail: MissionDetail): PurchaseStage[] {
  const hasPayment = detail.payment_attempts.length > 0;
  const approved = detail.approval?.status === "approved" || detail.approval?.status === "skipped" || hasPayment || detail.order != null;
  const reserved = hasPayment || detail.funding.status !== "not_ready" || detail.order != null;
  const charged = detail.payment_attempts.some((payment) => payment.status === "authorized") || detail.order != null;
  const stages = [
    ["Approve", approved],
    ["Reserve", reserved],
    ["Charge", charged],
    ["Confirm", detail.order != null],
  ] as const;
  const activeIndex = stages.findIndex(([, complete]) => !complete);
  return stages.map(([name, complete], index) => ({
    name,
    state: complete ? "done" : index === activeIndex ? "active" : "idle",
  }));
}

export function paymentDisplay(payment: PaymentAttempt): PaymentDisplay {
  return {
    provider: payment.provider,
    status: label(payment.status),
    detail: [
      formatMoney(payment.amount, payment.currency),
      payment.product_id ? `Line item: ${productName(payment.product_id)}` : null,
      payment.decline_code,
    ].filter(Boolean).join(" · "),
    tone: payment.status === "authorized" ? "ok" : payment.status === "declined" ? "warn" : "info",
  };
}

export function paymentIncident(detail: MissionDetail): { title: string; body: string; tone: "warn" | "error" } | null {
  const declined = detail.payment_attempts.find((payment) => payment.status === "declined");
  if (!declined) return null;
  const recoveredBy = declined.simulated
    ? undefined
    : detail.payment_attempts.find((payment) => payment.status === "authorized");
  const failedAttempt = `${declined.provider} declined ${formatMoney(declined.amount, declined.currency)}${declined.decline_code ? ` (${declined.decline_code})` : ""}`;
  const failedLine = declined.product_id ? ` for ${productName(declined.product_id)}` : "";
  if (declined.simulated) {
    return {
      title: declined.product_id ? "Line-item payment failed" : "Batch payment failed",
      body: `${failedAttempt}${failedLine}. The workflow is replanning the affected items and preparing a new payment route.`,
      tone: "error",
    };
  }
  if (recoveredBy) {
    return {
      title: "Payment failure recovered",
      body: `${failedAttempt}. The failed attempt created no order; ${recoveredBy.provider} authorised the retry.`,
      tone: "warn",
    };
  }
  return {
    title: "Payment failed",
    body: `${failedAttempt}. No order has been confirmed from this attempt; the workflow is waiting to reroute or request action.`,
    tone: "error",
  };
}

/** A client-only demonstration of one split-payment line failing. */
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

export function replayDetail(eventType: string): MissionDetail {
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
      item_count: 9,
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
    approval: waitingForApproval ? { question: "Approve the planned cart for 128.41 PLN?", status: "pending", amount: 128.41, currency: "PLN", expires_at: null } : null,
    action_requests: [],
    funding: { status: paid || ordered ? "used_closed" : "not_ready" },
    payment_attempts: paymentAttempts,
    order: ordered ? { confirmation_code: "DONE-EXAMPLE", status: "confirmed", total: 128.41, currency: "PLN", delivery_at: "2026-07-12T12:00:00+02:00" } : null,
    metrics: { budget_variance: 121.59, recovered_failures: eventType === "mission.completed" ? 2 : 0, payment_attempts: paymentAttempts.length },
  };
}
