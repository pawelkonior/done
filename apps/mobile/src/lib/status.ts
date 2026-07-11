import type { MissionStatus } from "@/types/domain";
import { colors } from "@/theme/tokens";

export const statusLabel: Record<MissionStatus, string> = {
  created: "Created",
  transcribing: "Listening",
  understanding: "Understanding",
  clarification_required: "Needs clarification",
  planning: "Planning",
  searching: "Searching",
  optimizing: "Optimizing",
  validating: "Validating",
  approval_required: "Needs approval",
  executing: "Ordering",
  recovering: "Recovering",
  completed: "Completed",
  failed: "Needs attention",
  cancelled: "Cancelled",
  waiting: "Waiting",
};

export const statusColor: Record<MissionStatus, string> = {
  created: colors.primary,
  transcribing: colors.primary,
  understanding: colors.primary,
  clarification_required: colors.warning,
  planning: colors.primary,
  searching: colors.primary,
  optimizing: colors.primary,
  validating: colors.primary,
  approval_required: colors.warning,
  executing: colors.secondary,
  recovering: colors.warning,
  completed: colors.success,
  failed: colors.error,
  cancelled: colors.textMuted,
  waiting: colors.secondary,
};

export const isTerminal = (status: MissionStatus) =>
  status === "completed" || status === "failed" || status === "cancelled";

export const workflowSteps = [
  { key: "understanding", label: "Understanding your request" },
  { key: "searching", label: "Finding the best products" },
  { key: "validating", label: "Checking availability & prices" },
  { key: "optimizing", label: "Optimizing delivery" },
  { key: "executing", label: "Payment & order" },
  { key: "completed", label: "Confirmation" },
] as const;

export const statusToStep = (status: MissionStatus, fallback = 1) => {
  const map: Partial<Record<MissionStatus, number>> = {
    created: 0,
    transcribing: 0,
    understanding: 1,
    clarification_required: 1,
    planning: 1,
    searching: 2,
    optimizing: 3,
    validating: 3,
    approval_required: 4,
    executing: 5,
    recovering: 5,
    completed: 6,
  };
  return map[status] ?? fallback;
};

