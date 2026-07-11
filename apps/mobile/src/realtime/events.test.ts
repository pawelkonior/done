import {
  parseTranscriptFailure,
  parseTranscriptOrderEvent,
  parseSubmitMissionCall,
  parseTranscriptEvent,
  realtimeInputActivity,
  realtimeServerError,
} from "@/realtime/events";

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
    expect(parseSubmitMissionCall({
      type: "response.done",
      response: {
        output: [{
          type: "function_call",
          name: "submit_mission",
          call_id: "call-1",
          arguments: JSON.stringify({ transcript: "Kup napoje do 50 PLN." }),
        }],
      },
    })).toEqual({ callId: "call-1", transcript: "Kup napoje do 50 PLN." });
    expect(parseSubmitMissionCall({
      type: "response.done",
      response: { output: [{ type: "function_call", name: "unknown", arguments: "{}" }] },
    })).toBeNull();
  });

  it("does not expose provider error messages", () => {
    expect(realtimeServerError({
      type: "error",
      error: { code: "invalid_event", message: "sensitive provider detail" },
    })).toBe("Live voice reported invalid_event.");
  });
});
