import type { NodeId } from "./types";

export interface NodeSpec {
  id: NodeId;
  num: number;
  name: string;
  sub: string;
}

export const NODES: readonly NodeSpec[] = [
  { id: "intake", num: 1, name: "Intake", sub: "głos / tekst" },
  { id: "contract", num: 2, name: "Kontrakt", sub: "budżet · deadline · towary" },
  { id: "snapshot", num: 3, name: "Snapshot", sub: "oferty sklepów" },
  { id: "model", num: 4, name: "Model", sub: "CP-SAT · buy / wait" },
  { id: "guardrails", num: 5, name: "Guardrails", sub: "polityki · approval" },
  { id: "purchase", num: 6, name: "Zakup", sub: "karta (token) · PSP" },
  { id: "result", num: 7, name: "Wynik", sub: "order / recovery" },
];

/** Every mission event type emitted by apps/api/app/workflow.py. */
export const EVENT_NODE: Record<string, NodeId> = {
  "mission.created": "intake",
  "voice.transcribed": "intake",
  "intent.parsed": "intake",

  "contract.created": "contract",
  "contract.revised": "contract",
  "mission.corrected": "contract",

  "market.snapshot_captured": "snapshot",
  "catalog.searched": "snapshot",

  "basket.optimized": "model",
  "plan.created": "model",
  "portfolio.replanned": "model",
  "portfolio.waiting": "model",
  "portfolio.infeasible": "model",
  "portfolio.invalid": "model",
  "timing.orange_mode": "model",

  "policy.validated": "guardrails",
  "approval.requested": "guardrails",
  "approval.review_requested": "guardrails",
  "approval.resolved": "guardrails",
  "approval.skipped": "guardrails",
  "approval.superseded": "guardrails",
  "approval.expired": "guardrails",

  "execution.started": "purchase",
  "inventory.reserved": "purchase",
  "payment.attempted": "purchase",
  "payment.declined": "purchase",
  "payment.rerouted": "purchase",
  "payment.authorized": "purchase",
  "delivery.selected": "purchase",

  "order.confirmed": "result",
  "mission.completed": "result",
  "mission.failed": "result",
  "mission.cancelled": "result",
};

/** Events that light the feedback edge back into the loop. */
export const FEEDBACK_EVENTS = new Set([
  "price.changed",
  "inventory.unavailable",
  "product.replaced",
  "recovery.started",
  "recovery.blocked_by_policy",
  "delivery.switched",
]);

export const WARN_EVENTS = new Set([
  "portfolio.infeasible",
  "portfolio.invalid",
  "payment.declined",
  "mission.failed",
  "approval.expired",
]);

export const WARN_SEVERITIES = new Set(["warning", "error", "critical"]);
