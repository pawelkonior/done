import {
  parseRealtimeCommand,
  parseTranscriptFailure,
  parseTranscriptOrderEvent,
  parseSubmitMissionCall,
  parseTranscriptEvent,
  realtimeInputActivity,
  realtimeServerError,
} from "@/realtime/events";

const responseDone = (name: string, args: unknown, callId = "call-1") => ({
  type: "response.done",
  response: {
    output: [{
      type: "function_call",
      name,
      call_id: callId,
      arguments: typeof args === "string" ? args : JSON.stringify(args),
    }],
  },
});

const PLAN_HASH = `sha256:${"a".repeat(64)}`;

describe("Realtime event parsing", () => {
  it("parses transcript deltas and completion", () => {
    expect(parseTranscriptEvent({
      type: "conversation.item.input_audio_transcription.delta",
      event_id: "event-1",
      item_id: "item-1",
      content_index: 0,
      delta: "Kup ",
    })).toEqual({ kind: "delta", itemId: "item-1", contentIndex: 0, eventId: "event-1", delta: "Kup " });
    expect(parseTranscriptEvent({
      type: "conversation.item.input_audio_transcription.completed",
      item_id: "item-1",
      content_index: 0,
      transcript: " Kup napoje. ",
    })).toEqual({ kind: "completed", itemId: "item-1", contentIndex: 0, transcript: "Kup napoje." });
    expect(parseTranscriptEvent({
      type: "conversation.item.input_audio_transcription.segment",
      item_id: "item-2",
      content_index: 1,
      id: "segment-1",
      start: 0.2,
      text: "  oraz wodę ",
    })).toEqual({
      kind: "segment",
      itemId: "item-2",
      contentIndex: 1,
      segment: { id: "segment-1", start: 0.2, text: "oraz wodę" },
    });
  });

  it("tracks microphone activity, turn order and safe transcription failures", () => {
    expect(realtimeInputActivity({ type: "input_audio_buffer.speech_started" })).toBe("hearing");
    expect(realtimeInputActivity({ type: "input_audio_buffer.speech_stopped" })).toBe("transcribing");
    expect(parseTranscriptOrderEvent({
      type: "input_audio_buffer.committed",
      item_id: "item-2",
      previous_item_id: "item-1",
    })).toEqual({ itemId: "item-2", previousItemId: "item-1" });
    expect(parseTranscriptFailure({
      type: "conversation.item.input_audio_transcription.failed",
      event_id: "event-failed",
      item_id: "item-2",
      content_index: 0,
      error: { message: "provider detail" },
    })).toEqual({ itemId: "item-2", contentIndex: 0, eventId: "event-failed" });
  });

  it("accepts only a valid submit_mission function call", () => {
    expect(parseSubmitMissionCall(responseDone(
      "submit_mission",
      { transcript: " Kup napoje do 50 PLN. " },
    ))).toEqual({ callId: "call-1", transcript: "Kup napoje do 50 PLN." });
    expect(parseSubmitMissionCall(responseDone("get_status", { mission_id: "mission-1" }))).toBeNull();
  });

  it("parses intake, contract, correction and status commands as a discriminated union", () => {
    expect(parseRealtimeCommand(responseDone("submit_mission", {
      transcript: "Prezenty dla pięciu osób do 500 PLN.",
    }))).toEqual({
      name: "submit_mission",
      callId: "call-1",
      transcript: "Prezenty dla pięciu osób do 500 PLN.",
    });
    expect(parseRealtimeCommand(responseDone("confirm_contract", {
      mission_id: "mission-1",
      revision: 2,
    }))).toEqual({ name: "confirm_contract", callId: "call-1", missionId: "mission-1", revision: 2 });
    expect(parseRealtimeCommand(responseDone("correct_mission", {
      mission_id: "mission-1",
      revision: 2,
      correction: " Zmień budżet na 450 PLN. ",
    }))).toEqual({
      name: "correct_mission",
      callId: "call-1",
      missionId: "mission-1",
      revision: 2,
      correction: "Zmień budżet na 450 PLN.",
    });
    expect(parseRealtimeCommand(responseDone("get_status", {
      mission_id: "mission-1",
    }))).toEqual({ name: "get_status", callId: "call-1", missionId: "mission-1" });
  });

  it("parses guarded purchase approval and rejection commands", () => {
    expect(parseRealtimeCommand(responseDone("approve_purchase", {
      mission_id: "mission-1",
      approval_id: "approval-9",
      revision: 4,
      amount: 499.99,
      currency: "PLN",
      plan_hash: PLAN_HASH,
      merchant_id: "merchant-b",
    }))).toEqual({
      name: "approve_purchase",
      callId: "call-1",
      missionId: "mission-1",
      approvalId: "approval-9",
      revision: 4,
      amount: 499.99,
      currency: "PLN",
      planHash: PLAN_HASH,
      merchantId: "merchant-b",
    });
    expect(parseRealtimeCommand(responseDone("reject_purchase", {
      mission_id: "mission-1",
      approval_id: "approval-9",
      revision: 4,
      choice: "review",
    }))).toEqual({
      name: "reject_purchase",
      callId: "call-1",
      missionId: "mission-1",
      approvalId: "approval-9",
      revision: 4,
      choice: "review",
    });
  });

  it("parses recovery, cancellation and human-support commands", () => {
    expect(parseRealtimeCommand(responseDone("choose_recovery", {
      mission_id: "mission-1",
      action_request_id: "action-3",
      revision: 5,
      choice: "use_substitute",
    }))).toEqual({
      name: "choose_recovery",
      callId: "call-1",
      missionId: "mission-1",
      actionRequestId: "action-3",
      revision: 5,
      choice: "use_substitute",
    });
    expect(parseRealtimeCommand(responseDone("cancel_mission", {
      mission_id: "mission-1",
      revision: 5,
    }))).toEqual({ name: "cancel_mission", callId: "call-1", missionId: "mission-1", revision: 5 });
    expect(parseRealtimeCommand(responseDone("request_human", {
      mission_id: "mission-1",
      revision: 5,
      reason: " Nie widzę dobrego zamiennika. ",
    }))).toEqual({
      name: "request_human",
      callId: "call-1",
      missionId: "mission-1",
      revision: 5,
      reason: "Nie widzę dobrego zamiennika.",
    });
    expect(parseRealtimeCommand(responseDone("request_human", {
      mission_id: "mission-1",
      revision: 5,
    }))).toEqual({ name: "request_human", callId: "call-1", missionId: "mission-1", revision: 5 });
  });

  it("rejects unknown, malformed, ambiguous and non-response commands", () => {
    expect(parseRealtimeCommand(responseDone("transfer_money", { amount: 10 }))).toBeNull();
    expect(parseRealtimeCommand(responseDone("submit_mission", "{not-json"))).toBeNull();
    expect(parseRealtimeCommand({
      type: "response.done",
      response: { output: [{ type: "function_call", name: "get_status", call_id: "call-1", arguments: [] }] },
    })).toBeNull();
    expect(parseRealtimeCommand({
      type: "response.done",
      response: {
        output: [
          { type: "function_call", name: "get_status", call_id: "call-1", arguments: "{\"mission_id\":\"one\"}" },
          { type: "function_call", name: "get_status", call_id: "call-2", arguments: "{\"mission_id\":\"two\"}" },
        ],
      },
    })).toBeNull();
    expect(parseRealtimeCommand({ type: "response.created", response: { output: [] } })).toBeNull();
    expect(parseRealtimeCommand({ type: "response.done", response: { output: [] } })).toBeNull();
  });

  it("rejects missing, extra and unsafe identifiers or text arguments", () => {
    expect(parseRealtimeCommand(responseDone("get_status", {}))).toBeNull();
    expect(parseRealtimeCommand(responseDone("get_status", {
      mission_id: "mission-1",
      unsafe_extra: true,
    }))).toBeNull();
    expect(parseRealtimeCommand(responseDone("get_status", { mission_id: "../../mission-1" }))).toBeNull();
    expect(parseRealtimeCommand(responseDone("get_status", { mission_id: "x".repeat(201) }))).toBeNull();
    expect(parseRealtimeCommand(responseDone("get_status", { mission_id: "mission-1" }, "bad call id"))).toBeNull();
    expect(parseRealtimeCommand(responseDone("submit_mission", { transcript: "no" }))).toBeNull();
    expect(parseRealtimeCommand(responseDone("correct_mission", {
      mission_id: "mission-1",
      revision: 1,
      correction: "x".repeat(4_001),
    }))).toBeNull();
    expect(parseRealtimeCommand(responseDone("request_human", {
      mission_id: "mission-1",
      revision: 1,
      reason: "x".repeat(1_001),
    }))).toBeNull();
  });

  it("rejects unsafe revisions, amounts, currencies and choices", () => {
    for (const revision of [0, -1, 1.5, "2", Number.MAX_SAFE_INTEGER + 1]) {
      expect(parseRealtimeCommand(responseDone("confirm_contract", {
        mission_id: "mission-1",
        revision,
      }))).toBeNull();
    }
    for (const amount of [0, -1, "499.99"]) {
      expect(parseRealtimeCommand(responseDone("approve_purchase", {
        mission_id: "mission-1",
        approval_id: "approval-9",
        revision: 4,
        amount,
        currency: "PLN",
        plan_hash: PLAN_HASH,
        merchant_id: "merchant-b",
      }))).toBeNull();
    }
    for (const currency of ["pln", "GBP", "PLNX", 123]) {
      expect(parseRealtimeCommand(responseDone("approve_purchase", {
        mission_id: "mission-1",
        approval_id: "approval-9",
        revision: 4,
        amount: 499.99,
        currency,
        plan_hash: PLAN_HASH,
        merchant_id: "merchant-b",
      }))).toBeNull();
    }
    for (const unsafePlanHash of ["sha256:short", `sha256:${"A".repeat(64)}`, "md5:abc", 123]) {
      expect(parseRealtimeCommand(responseDone("approve_purchase", {
        mission_id: "mission-1",
        approval_id: "approval-9",
        revision: 4,
        amount: 499.99,
        currency: "PLN",
        plan_hash: unsafePlanHash,
        merchant_id: "merchant-b",
      }))).toBeNull();
    }
    for (const choice of ["approve", "reject", "", 1]) {
      expect(parseRealtimeCommand(responseDone("reject_purchase", {
        mission_id: "mission-1",
        approval_id: "approval-9",
        revision: 4,
        choice,
      }))).toBeNull();
    }
    expect(parseRealtimeCommand(responseDone("choose_recovery", {
      mission_id: "mission-1",
      action_request_id: "action-3",
      revision: 5,
      choice: "x".repeat(101),
    }))).toBeNull();
  });

  it("does not expose provider error messages", () => {
    expect(realtimeServerError({
      type: "error",
      error: { code: "invalid_event", message: "sensitive provider detail" },
    })).toBe("Live voice reported invalid_event.");
  });
});
