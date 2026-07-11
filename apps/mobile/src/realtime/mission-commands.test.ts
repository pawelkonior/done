import {
  executeMissionRealtimeCommand,
  type MissionCommandApi,
} from "@/realtime/mission-commands";
import type { MissionDetail } from "@/types/domain";

const PLAN_HASH = `sha256:${"a".repeat(64)}`;

function missionDetail(overrides: Partial<MissionDetail> = {}): MissionDetail {
  const base: MissionDetail = {
    mission: {
      id: "mission-1",
      title: "Birthday supplies",
      subtitle: "Waiting for approval",
      status: "approval_required",
      current_step: 5,
      total_steps: 7,
      progress: 5 / 7,
      latest_update: "Approval required",
      created_at: "2026-07-11T10:00:00Z",
      revision: 4,
    },
    contract: {
      goal: "Birthday supplies for five children",
      participants: 5,
      hard_constraints: ["Maximum 500 PLN"],
      soft_preferences: [],
      budget: 500,
      currency: "PLN",
      deadline: "Sat, 16:00",
      approval_policy: "Always approve before purchase",
      confidence: 0.98,
      version: 1,
    },
    basket: {
      id: "basket-1",
      merchant: "Party Store",
      merchant_id: "merchant-b",
      items: [],
      subtotal: 470,
      delivery_cost: 29.99,
      total: 499.99,
      currency: "PLN",
      status: "proposed",
    },
    approval: {
      id: "approval-9",
      type: "purchase_approval",
      question: "Approve 499.99 PLN?",
      status: "pending",
      options: [],
      created_at: "2026-07-11T10:01:00Z",
      plan_hash: PLAN_HASH,
      merchant_id: "merchant-b",
      amount: 499.99,
      currency: "PLN",
    },
    events: [],
    metrics: {
      budget: 500,
      final_cost: 499.99,
      saved: 0.01,
      recovered_failures: 0,
      payment_attempts: 0,
      constraint_satisfaction: 1,
      delivery_confidence: 0.95,
    },
    delivery_options: [],
    action_requests: [],
  };
  return { ...base, ...overrides };
}

function commandApi(current: MissionDetail = missionDetail()) {
  const api: MissionCommandApi = {
    getMission: jest.fn(async () => current),
    correctMission: jest.fn(async () => current),
    resolveApproval: jest.fn(async () => current),
    resolveActionRequest: jest.fn(async () => current),
    cancelMission: jest.fn(async () => current),
    requestHumanSupport: jest.fn(async () => current),
  };
  return api as jest.Mocked<MissionCommandApi>;
}

describe("mission Realtime command execution", () => {
  it("binds spoken approval to the exact current plan before calling the API", async () => {
    const api = commandApi();
    const result = await executeMissionRealtimeCommand({
      name: "approve_purchase",
      callId: "call-1",
      missionId: "mission-1",
      approvalId: "approval-9",
      revision: 4,
      amount: 499.99,
      currency: "PLN",
      planHash: PLAN_HASH,
      merchantId: "merchant-b",
    }, {
      missionId: "mission-1",
      voiceTranscript: "Tak, zatwierdzam zakup za 499,99 zł.",
    }, api);

    expect(api.resolveApproval).toHaveBeenCalledWith("approval-9", "approve", {
      expected_revision: 4,
      amount: 499.99,
      currency: "PLN",
      plan_hash: PLAN_HASH,
      merchant_id: "merchant-b",
      voice_transcript: "Tak, zatwierdzam zakup za 499,99 zł.",
    });
    expect(result.output).toMatchObject({
      ok: true,
      action: "purchase_approval_recorded",
      approved_plan_hash: PLAN_HASH,
      approved_merchant_id: "merchant-b",
    });
  });

  it.each([
    ["wrong mission", { missionId: "mission-2" }, "MISSION_ID_MISMATCH"],
    ["stale revision", { revision: 3 }, "STALE_MISSION_REVISION"],
    ["wrong approval", { approvalId: "approval-old" }, "APPROVAL_ID_MISMATCH"],
    ["wrong amount", { amount: 490 }, "APPROVAL_AMOUNT_MISMATCH"],
    ["wrong plan", { planHash: `sha256:${"b".repeat(64)}` }, "APPROVAL_PLAN_MISMATCH"],
    ["wrong merchant", { merchantId: "merchant-c" }, "APPROVAL_MERCHANT_MISMATCH"],
  ])("rejects %s without resolving approval", async (_label, change, expectedCode) => {
    const api = commandApi();
    const command = {
      name: "approve_purchase" as const,
      callId: "call-1",
      missionId: "mission-1",
      approvalId: "approval-9",
      revision: 4,
      amount: 499.99,
      currency: "PLN" as const,
      planHash: PLAN_HASH,
      merchantId: "merchant-b",
      ...change,
    };

    await expect(executeMissionRealtimeCommand(command, {
      missionId: "mission-1",
      voiceTranscript: "Zatwierdzam ten zakup.",
    }, api)).rejects.toMatchObject({ code: expectedCode });
    expect(api.resolveApproval).not.toHaveBeenCalled();
  });

  it("fails closed when an approval has no trusted plan binding or voice evidence", async () => {
    const missingBinding = missionDetail({
      approval: { ...missionDetail().approval!, plan_hash: undefined },
    });
    const api = commandApi(missingBinding);
    const command = {
      name: "approve_purchase" as const,
      callId: "call-1",
      missionId: "mission-1",
      approvalId: "approval-9",
      revision: 4,
      amount: 499.99,
      currency: "PLN" as const,
      planHash: PLAN_HASH,
      merchantId: "merchant-b",
    };

    await expect(executeMissionRealtimeCommand(command, {
      missionId: "mission-1",
      voiceTranscript: "Zatwierdzam ten zakup.",
    }, api))
      .rejects.toMatchObject({ code: "APPROVAL_BINDING_UNAVAILABLE" });

    const boundApi = commandApi();
    await expect(executeMissionRealtimeCommand(command, { missionId: "mission-1" }, boundApi))
      .rejects.toMatchObject({ code: "VOICE_EVIDENCE_REQUIRED" });
    expect(boundApi.resolveApproval).not.toHaveBeenCalled();
  });

  it("validates pending user-owned recovery choices and forwards spoken clarification", async () => {
    const current = missionDetail({
      mission: { ...missionDetail().mission, status: "waiting_for_user", revision: 6 },
      approval: null,
      action_requests: [{
        id: "action-3",
        type: "clarification",
        reason_code: "MISSING_SCOPE",
        question: "What kind of products should I buy?",
        status: "pending",
        owner: "user",
        options: [{ id: "answer_by_voice", label: "Answer by voice" }],
        created_at: "2026-07-11T10:02:00Z",
      }],
    });
    const api = commandApi(current);

    await executeMissionRealtimeCommand({
      name: "choose_recovery",
      callId: "call-2",
      missionId: "mission-1",
      actionRequestId: "action-3",
      revision: 6,
      choice: "answer_by_voice",
    }, {
      missionId: "mission-1",
      voiceTranscript: "Chodzi o prezenty dla dzieci.",
    }, api);

    expect(api.resolveActionRequest).toHaveBeenCalledWith("action-3", {
      choice: "answer_by_voice",
      expected_revision: 6,
      voice_transcript: "Chodzi o prezenty dla dzieci.",
    });
  });

  it("sends the current revision with correction, cancellation and support writes", async () => {
    const api = commandApi();
    await executeMissionRealtimeCommand({
      name: "correct_mission",
      callId: "call-correct",
      missionId: "mission-1",
      revision: 4,
      correction: "Zmień budżet na 450 PLN.",
    }, {
      missionId: "mission-1",
      voiceTranscript: "Zmień budżet na 450 PLN.",
    }, api);
    await executeMissionRealtimeCommand({
      name: "cancel_mission",
      callId: "call-cancel",
      missionId: "mission-1",
      revision: 4,
    }, {
      missionId: "mission-1",
      voiceTranscript: "Anuluj tę misję.",
    }, api);
    await executeMissionRealtimeCommand({
      name: "request_human",
      callId: "call-human",
      missionId: "mission-1",
      revision: 4,
      reason: "Potrzebuję pomocy z zamiennikiem.",
    }, {
      missionId: "mission-1",
      voiceTranscript: "Potrzebuję pomocy człowieka z zamiennikiem.",
    }, api);

    expect(api.correctMission).toHaveBeenCalledWith("mission-1", {
      correction: "Zmień budżet na 450 PLN.",
      expected_revision: 4,
    });
    expect(api.cancelMission).toHaveBeenCalledWith("mission-1", 4);
    expect(api.requestHumanSupport).toHaveBeenCalledWith("mission-1", {
      reason: "Potrzebuję pomocy człowieka z zamiennikiem.",
      expected_revision: 4,
    });
  });

  it("rejects every state-changing Realtime command without a fresh voice turn", async () => {
    const api = commandApi();

    await expect(executeMissionRealtimeCommand({
      name: "cancel_mission",
      callId: "call-cancel",
      missionId: "mission-1",
      revision: 4,
    }, { missionId: "mission-1" }, api)).rejects.toMatchObject({
      code: "VOICE_EVIDENCE_REQUIRED",
    });

    expect(api.cancelMission).not.toHaveBeenCalled();
  });

  it("rejects a destructive model tool call when the spoken intent does not match", async () => {
    const api = commandApi();

    await expect(executeMissionRealtimeCommand({
      name: "cancel_mission",
      callId: "call-hallucinated-cancel",
      missionId: "mission-1",
      revision: 4,
    }, {
      missionId: "mission-1",
      voiceTranscript: "Jaki jest aktualny status misji?",
    }, api)).rejects.toMatchObject({ code: "VOICE_INTENT_MISMATCH" });

    expect(api.cancelMission).not.toHaveBeenCalled();
  });
});
