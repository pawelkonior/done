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
  "intent.needs_clarification": "intake",
  "clarification.updated": "intake",
  "clarification.resolved": "intake",
  "action.requested": "intake",

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
  "portfolio.shadow_audit": "model",
  "catalog.plan_not_found": "model",
  "timing.orange_mode": "model",

  "policy.validated": "guardrails",
  "approval.requested": "guardrails",
  "approval.review_requested": "guardrails",
  "approval.resolved": "guardrails",
  "approval.skipped": "guardrails",
  "approval.superseded": "guardrails",
  "approval.expired": "guardrails",
  "approval.refreshed_after_expiry": "guardrails",
  "approval.rejected_stale_plan": "guardrails",
  "approval.rejected_policy_change": "guardrails",
  "approval.rejected_missing_evidence": "guardrails",
  "policy.plan_blocked": "guardrails",
  "funding.approval_required": "guardrails",

  "execution.started": "purchase",
  "inventory.reserved": "purchase",
  "payment.attempted": "purchase",
  "payment.declined": "purchase",
  "payment.rerouted": "purchase",
  "payment.authorized": "purchase",
  "delivery.selected": "purchase",
  "funding.card_request_ready": "purchase",
  "funding.blocked": "purchase",
  "funding.issuer_required": "purchase",
  "funding.reentry_blocked": "purchase",
  "commerce.providers_required": "purchase",

  "order.confirmed": "result",
  "mission.completed": "result",
  "mission.failed": "result",
  "mission.cancelled": "result",
  "action.cancelled_mission": "result",
};

/** Events that light the feedback edge back into the loop. */
export const FEEDBACK_EVENTS = new Set([
  "price.changed",
  "inventory.unavailable",
  "product.replaced",
  "recovery.started",
  "recovery.blocked_by_policy",
  "recovery.action_required",
  "delivery.switched",
]);

export const WARN_EVENTS = new Set([
  "portfolio.infeasible",
  "portfolio.invalid",
  "payment.declined",
  "mission.failed",
  "approval.expired",
  "approval.rejected_stale_plan",
  "approval.rejected_policy_change",
  "approval.rejected_missing_evidence",
  "policy.plan_blocked",
  "catalog.plan_not_found",
  "funding.blocked",
  "funding.issuer_required",
  "funding.reentry_blocked",
  "commerce.providers_required",
]);

export const WARN_SEVERITIES = new Set(["warning", "error", "critical"]);
