type JsonRecord = Record<string, unknown>;

function record(value: unknown): JsonRecord {
  return value && typeof value === "object" ? value as JsonRecord : {};
}

interface RealtimeTranscriptBase {
  itemId: string;
  contentIndex: number;
  eventId?: string;
}

export type RealtimeTranscriptEvent =
  | (RealtimeTranscriptBase & { kind: "delta"; delta: string })
  | (RealtimeTranscriptBase & { kind: "completed"; transcript: string })
  | (RealtimeTranscriptBase & {
      kind: "segment";
      segment: { id: string; text: string; start: number };
    });

export interface RealtimeTranscriptOrderEvent {
  itemId: string;
  previousItemId: string | null;
}

export interface RealtimeTranscriptFailure extends RealtimeTranscriptBase {}

export interface SubmitMissionCall {
  callId: string;
  transcript: string;
}

export function parseTranscriptEvent(value: unknown): RealtimeTranscriptEvent | null {
  const event = record(value);
  const type = typeof event.type === "string" ? event.type : "";
  const itemId = typeof event.item_id === "string" ? event.item_id : "";
  if (!itemId) return null;
  const contentIndex = typeof event.content_index === "number" ? event.content_index : 0;
  const eventId = typeof event.event_id === "string" ? event.event_id : undefined;
  if (type === "conversation.item.input_audio_transcription.delta" && typeof event.delta === "string") {
    return { kind: "delta", itemId, contentIndex, eventId, delta: event.delta };
  }
  if (type === "conversation.item.input_audio_transcription.completed" && typeof event.transcript === "string") {
    return {
      kind: "completed",
      itemId,
      contentIndex,
      eventId,
      transcript: event.transcript.trim(),
    };
  }
  if (type === "conversation.item.input_audio_transcription.segment" && typeof event.text === "string") {
    const text = event.text.trim();
    if (!text) return null;
    return {
      kind: "segment",
      itemId,
      contentIndex,
      eventId,
      segment: {
        id: typeof event.id === "string" ? event.id : `${contentIndex}:${event.start ?? 0}`,
        text,
        start: typeof event.start === "number" ? event.start : 0,
      },
    };
  }
  return null;
}

export function parseTranscriptOrderEvent(value: unknown): RealtimeTranscriptOrderEvent | null {
  const event = record(value);
  const type = typeof event.type === "string" ? event.type : "";
  if (type === "input_audio_buffer.committed" && typeof event.item_id === "string") {
    return {
      itemId: event.item_id,
      previousItemId: typeof event.previous_item_id === "string" ? event.previous_item_id : null,
    };
  }
  if (!["conversation.item.added", "conversation.item.created"].includes(type)) return null;
  const item = record(event.item);
  if (item.role !== "user" || typeof item.id !== "string") return null;
  return {
    itemId: item.id,
    previousItemId: typeof event.previous_item_id === "string" ? event.previous_item_id : null,
  };
}

export function parseTranscriptFailure(value: unknown): RealtimeTranscriptFailure | null {
  const event = record(value);
  if (event.type !== "conversation.item.input_audio_transcription.failed") return null;
  if (typeof event.item_id !== "string") return null;
  return {
    itemId: event.item_id,
    contentIndex: typeof event.content_index === "number" ? event.content_index : 0,
    eventId: typeof event.event_id === "string" ? event.event_id : undefined,
  };
}

export function parseSubmitMissionCall(value: unknown): SubmitMissionCall | null {
  const event = record(value);
  if (event.type !== "response.done") return null;
  const response = record(event.response);
  if (!Array.isArray(response.output)) return null;
  for (const rawItem of response.output) {
    const item = record(rawItem);
    if (item.type !== "function_call" || item.name !== "submit_mission") continue;
    if (typeof item.call_id !== "string" || typeof item.arguments !== "string") continue;
    try {
      const args = record(JSON.parse(item.arguments));
      const transcript = typeof args.transcript === "string" ? args.transcript.trim() : "";
      if (transcript.length >= 3 && transcript.length <= 4_000) {
        return { callId: item.call_id, transcript };
      }
    } catch {
      return null;
    }
  }
  return null;
}

export function realtimeActivity(value: unknown): "listening" | "thinking" | "speaking" | null {
  const type = record(value).type;
  if (type === "input_audio_buffer.speech_started") return "listening";
  if (type === "input_audio_buffer.speech_stopped" || type === "response.created") return "thinking";
  if (type === "response.output_audio.delta") return "speaking";
  return null;
}

export function realtimeInputActivity(value: unknown): "hearing" | "transcribing" | null {
  const type = record(value).type;
  if (type === "input_audio_buffer.speech_started") return "hearing";
  if (type === "input_audio_buffer.speech_stopped") return "transcribing";
  return null;
}

export function realtimeServerError(value: unknown): string | null {
  const event = record(value);
  if (event.type !== "error") return null;
  const error = record(event.error);
  const code = typeof error.code === "string" ? error.code : "realtime_error";
  return `Live voice reported ${code}.`;
}
