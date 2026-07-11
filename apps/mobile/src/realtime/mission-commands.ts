import {
  cancelMission,
  correctMission,
  getMission,
  requestHumanSupport,
  resolveActionRequest,
  resolveApproval,
} from "@/api/client";
import type { RealtimeCommand } from "@/realtime/events";
import type { MissionDetail } from "@/types/domain";

type MissionRealtimeCommand = Exclude<RealtimeCommand, { name: "submit_mission" }>;

export interface MissionCommandContext {
  missionId: string;
  voiceTranscript?: string;
}

export interface MissionCommandResult {
  detail: MissionDetail;
  output: Record<string, unknown>;
}

export interface MissionCommandApi {
  getMission: (missionId: string) => Promise<MissionDetail>;
  correctMission: (
    missionId: string,
    input: { correction: string; expected_revision: number },
  ) => Promise<MissionDetail>;
  resolveApproval: (
    approvalId: string,
    choice: "approve" | "review" | "cancel",
    evidence: {
      expected_revision: number;
      amount?: number;
      currency?: string;
      plan_hash?: string;
      merchant_id?: string;
      voice_transcript?: string;
    },
  ) => Promise<MissionDetail>;
  resolveActionRequest: (
    actionRequestId: string,
    input: {
      choice: string;
      expected_revision: number;
      voice_transcript?: string;
    },
  ) => Promise<MissionDetail>;
  cancelMission: (missionId: string, expectedRevision: number) => Promise<MissionDetail>;
  requestHumanSupport: (
    missionId: string,
    input: { reason?: string; expected_revision: number },
  ) => Promise<MissionDetail>;
}

export class MissionCommandRejected extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "MissionCommandRejected";
  }
}

const defaultApi: MissionCommandApi = {
  getMission,
  correctMission,
  async resolveApproval(approvalId, choice, evidence) {
    return (await resolveApproval(approvalId, choice, evidence)).detail;
  },
  resolveActionRequest,
  cancelMission,
  requestHumanSupport,
};

function reject(code: string, message: string): never {
  throw new MissionCommandRejected(code, message);
}

function normalizedVoiceEvidence(value: string | undefined) {
  const normalized = value?.trim();
  return normalized && normalized.length >= 3 ? normalized.slice(0, 4_000) : undefined;
}

function revisionOf(detail: MissionDetail) {
  const revision = detail.mission.revision;
  if (!revision || !Number.isSafeInteger(revision) || revision < 1) {
    return reject("CURRENT_REVISION_UNAVAILABLE", "The current mission revision is unavailable.");
  }
  return revision;
}

function requireRevision(detail: MissionDetail, spokenRevision: number) {
  const currentRevision = revisionOf(detail);
  if (spokenRevision !== currentRevision) {
    return reject(
      "STALE_MISSION_REVISION",
      "The mission changed. Review its current state before trying that command again.",
    );
  }
  return currentRevision;
}

function sameMoney(left: number, right: number) {
  return Math.round(left * 100) === Math.round(right * 100);
}

function statusOutput(detail: MissionDetail) {
  const pendingAction = detail.action_requests?.find((action) => action.status === "pending");
  const pendingApproval = detail.approval?.status === "pending" ? detail.approval : null;
  return {
    mission_id: detail.mission.id,
    status: detail.mission.status,
    revision: detail.mission.revision,
    title: detail.mission.title,
    requires_action: Boolean(pendingAction || pendingApproval),
    pending_action: pendingAction
      ? {
          id: pendingAction.id,
          question: pendingAction.question,
          owner: pendingAction.owner,
          options: pendingAction.options,
        }
      : null,
    pending_approval: pendingApproval && detail.basket
      ? {
          id: pendingApproval.id,
          amount: detail.basket.total,
          currency: detail.basket.currency,
          plan_hash: pendingApproval.plan_hash,
          merchant_id: pendingApproval.merchant_id,
        }
      : null,
  };
}

function success(action: string, detail: MissionDetail, extra?: Record<string, unknown>): MissionCommandResult {
  return {
    detail,
    output: {
      ok: true,
      action,
      ...statusOutput(detail),
      ...extra,
    },
  };
}

/**
 * Executes a model-requested mission command only after binding it to fresh,
 * authoritative mission state. Realtime tool arguments are never trusted by
 * themselves, especially for approvals and human-in-the-loop recovery.
 */
export async function executeMissionRealtimeCommand(
  command: MissionRealtimeCommand,
  context: MissionCommandContext,
  api: MissionCommandApi = defaultApi,
): Promise<MissionCommandResult> {
  if (command.missionId !== context.missionId) {
    return reject("MISSION_ID_MISMATCH", "That command belongs to a different mission.");
  }

  const current = await api.getMission(context.missionId);
  if (current.mission.id !== context.missionId) {
    return reject("MISSION_STATE_MISMATCH", "The server returned a different mission.");
  }

  if (command.name === "get_status") {
    return success("status_read", current);
  }

  const revision = requireRevision(current, command.revision);
  const voiceEvidence = normalizedVoiceEvidence(context.voiceTranscript);

  if (command.name === "confirm_contract") {
    if (!current.contract) {
      return reject("CONTRACT_UNAVAILABLE", "There is no complete contract to confirm yet.");
    }
    return success("contract_checked", current, {
      contract_matches_revision: true,
      contract: {
        goal: current.contract.goal,
        participants: current.contract.participants,
        hard_constraints: current.contract.hard_constraints,
        budget: current.contract.budget,
        currency: current.contract.currency,
        deadline: current.contract.deadline,
      },
    });
  }

  if (!voiceEvidence) {
    return reject(
      "VOICE_EVIDENCE_REQUIRED",
      "A fresh transcribed voice turn is required for this mission change.",
    );
  }

  if (command.name === "correct_mission") {
    const detail = await api.correctMission(context.missionId, {
      // The model argument selects the command. Mission facts come only from
      // the user's current microphone transcript.
      correction: voiceEvidence,
      expected_revision: revision,
    });
    return success("mission_corrected", detail);
  }

  if (command.name === "approve_purchase") {
    const approval = current.approval;
    const basket = current.basket;
    if (!approval || approval.status !== "pending" || approval.id !== command.approvalId) {
      return reject("APPROVAL_ID_MISMATCH", "That approval is no longer the pending purchase approval.");
    }
    if (!basket) return reject("BASKET_UNAVAILABLE", "There is no current basket to approve.");
    if (
      !approval.plan_hash
      || !approval.merchant_id
      || approval.amount === undefined
      || !approval.currency
    ) {
      return reject(
        "APPROVAL_BINDING_UNAVAILABLE",
        "The current approval binding is unavailable. Refresh the purchase plan before approving.",
      );
    }
    if (command.planHash !== approval.plan_hash) {
      return reject("APPROVAL_PLAN_MISMATCH", "The spoken approval refers to an outdated purchase plan.");
    }
    if (
      command.merchantId !== approval.merchant_id
      || (basket.merchant_id !== undefined && command.merchantId !== basket.merchant_id)
    ) {
      return reject("APPROVAL_MERCHANT_MISMATCH", "The spoken merchant does not match the current plan.");
    }
    if (
      !sameMoney(approval.amount, basket.total)
      || approval.currency !== basket.currency
      || !sameMoney(command.amount, approval.amount)
      || command.currency !== approval.currency
    ) {
      return reject(
        "APPROVAL_AMOUNT_MISMATCH",
        "The spoken amount or currency does not match the current basket.",
      );
    }
    const detail = await api.resolveApproval(approval.id, "approve", {
      expected_revision: revision,
      amount: basket.total,
      currency: basket.currency,
      plan_hash: approval.plan_hash,
      merchant_id: approval.merchant_id,
      voice_transcript: voiceEvidence,
    });
    return success("purchase_approval_recorded", detail, {
      approved_amount: basket.total,
      approved_currency: basket.currency,
      approved_plan_hash: approval.plan_hash,
      approved_merchant_id: approval.merchant_id,
    });
  }

  if (command.name === "reject_purchase") {
    const approval = current.approval;
    if (!approval || approval.status !== "pending" || approval.id !== command.approvalId) {
      return reject("APPROVAL_ID_MISMATCH", "That approval is no longer pending.");
    }
    const detail = await api.resolveApproval(approval.id, command.choice, {
      expected_revision: revision,
      voice_transcript: voiceEvidence,
    });
    return success(command.choice === "cancel" ? "purchase_cancelled" : "purchase_review_requested", detail);
  }

  if (command.name === "choose_recovery") {
    const action = current.action_requests?.find((candidate) => candidate.status === "pending");
    if (!action || action.id !== command.actionRequestId) {
      return reject("ACTION_REQUEST_MISMATCH", "That action request is no longer pending.");
    }
    if (action.owner !== "user") {
      return reject("ACTION_OWNED_BY_SUPPORT", "That action is assigned to human support.");
    }
    if (!action.options.some((option) => option.id === command.choice)) {
      return reject("ACTION_CHOICE_NOT_ALLOWED", "That choice is not available for the current action.");
    }
    const detail = await api.resolveActionRequest(action.id, {
      choice: command.choice,
      expected_revision: revision,
      voice_transcript: voiceEvidence,
    });
    return success("action_request_resolved", detail, { selected_choice: command.choice });
  }

  if (command.name === "cancel_mission") {
    const detail = await api.cancelMission(context.missionId, revision);
    return success("mission_cancelled", detail);
  }

  if (command.name === "request_human") {
    const detail = await api.requestHumanSupport(context.missionId, {
      reason: voiceEvidence.slice(0, 500),
      expected_revision: revision,
    });
    return success("human_support_requested", detail);
  }

  return reject("UNSUPPORTED_COMMAND", "That mission command is not supported.");
}
