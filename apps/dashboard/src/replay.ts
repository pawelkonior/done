import type { LoopEvent } from "./types";

export interface ReplayStep extends Omit<LoopEvent, "created_at"> {
  /** Milliseconds to wait before the next step. */
  delay: number;
}

/** A complete sample journey for presenting the dashboard without a live API. */
export const REPLAY_SCRIPT: readonly ReplayStep[] = [
  { type: "mission.created", title: "Mission created from a voice command", severity: "info", delay: 1600 },
  { type: "voice.transcribed", title: "Maya's birthday, Saturday, 12 children, up to 250 PLN, nut-free", severity: "info", delay: 2000 },
  { type: "intent.parsed", title: "Budget, deadline and constraints parsed deterministically", severity: "info", delay: 1700 },
  { type: "contract.created", title: "Contract v1 · 250 PLN · nut-free · Saturday 12:00", severity: "info", delay: 1900 },
  { type: "market.snapshot_captured", title: "Market snapshot: 14 offers from 3 merchants", severity: "info", delay: 1900 },
  { type: "basket.optimized", title: "CP-SAT selected a cart for 128.41 PLN", severity: "info", delay: 2300 },
  { type: "policy.validated", title: "Budget, allergy and deadline policies satisfied", severity: "info", delay: 1600 },
  { type: "approval.requested", title: "Cart is waiting for user approval", severity: "info", delay: 2600 },
  { type: "price.changed", title: "Pretzel price rose by 20% — feedback returns to the model", severity: "warning", delay: 2100 },
  { type: "portfolio.replanned", title: "Replan replaces pretzels with crackers within the same budget", severity: "info", delay: 2200 },
  { type: "approval.superseded", title: "Previous approval invalidated after the replan", severity: "warning", delay: 1900 },
  { type: "approval.resolved", title: "User approved 128.41 PLN", severity: "info", delay: 2000 },
  { type: "execution.started", title: "Purchase started at Party Market", severity: "info", delay: 1500 },
  { type: "inventory.unavailable", title: "Mini pretzels unavailable — recovery started", severity: "warning", delay: 1900 },
  { type: "product.replaced", title: "A safe nut-free replacement was selected", severity: "info", delay: 1700 },
  { type: "inventory.reserved", title: "Inventory reserved with the merchant", severity: "info", delay: 1400 },
  { type: "payment.attempted", title: "Tokenised card payment sent to PSP_A", severity: "info", delay: 1400 },
  { type: "payment.declined", title: "PSP_A returned a soft decline", severity: "warning", delay: 1700 },
  { type: "payment.rerouted", title: "Payment rerouted to PSP_B", severity: "info", delay: 1400 },
  { type: "payment.authorized", title: "PSP_B authorised 128.41 PLN", severity: "info", delay: 1700 },
  { type: "order.confirmed", title: "Order confirmed · delivery on Friday", severity: "info", delay: 2000 },
  { type: "mission.completed", title: "Mission completed · 121.59 PLN under budget · 2 recoveries", severity: "info", delay: 6500 },
];

export const REPLAY_MISSION_TITLE = "Maya's birthday - sample mission";
