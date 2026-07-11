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

type RealtimeCommandBase<Name extends string> = {
  name: Name;
  callId: string;
};

export type RealtimeCommand =
  | (RealtimeCommandBase<"submit_mission"> & {
      transcript: string;
    })
  | (RealtimeCommandBase<"confirm_contract"> & {
      missionId: string;
      revision: number;
    })
  | (RealtimeCommandBase<"correct_mission"> & {
      missionId: string;
      revision: number;
      correction: string;
    })
  | (RealtimeCommandBase<"approve_purchase"> & {
      missionId: string;
      approvalId: string;
      revision: number;
      amount: number;
      currency: "PLN" | "EUR" | "USD";
      planHash: string;
      merchantId: string;
    })
  | (RealtimeCommandBase<"reject_purchase"> & {
      missionId: string;
      approvalId: string;
      revision: number;
      choice: "cancel" | "review";
    })
  | (RealtimeCommandBase<"choose_recovery"> & {
      missionId: string;
      actionRequestId: string;
      revision: number;
      choice: string;
    })
  | (RealtimeCommandBase<"cancel_mission"> & {
      missionId: string;
      revision: number;
    })
  | (RealtimeCommandBase<"request_human"> & {
      missionId: string;
      revision: number;
      reason?: string;
    })
  | (RealtimeCommandBase<"get_status"> & {
      missionId: string;
    })
  | (RealtimeCommandBase<"get_purchase_plan"> & {
      missionId: string;
      revision: number;
    })
  | (RealtimeCommandBase<"select_delivery"> & {
      missionId: string;
      revision: number;
      optionId: string;
    });

const MAX_ID_LENGTH = 200;
const MAX_TEXT_LENGTH = 4_000;
const MAX_REASON_LENGTH = 1_000;
const MAX_CHOICE_LENGTH = 100;
const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]*$/;
const SHA256_PLAN_HASH = /^sha256:[0-9a-f]{64}$/;
const SUPPORTED_CURRENCIES = new Set(["PLN", "EUR", "USD"] as const);

function jsonRecord(value: unknown): JsonRecord | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as JsonRecord
    : null;
}

function hasExactKeys(
  value: JsonRecord,
  required: readonly string[],
  optional: readonly string[] = [],
): boolean {
  const allowed = new Set([...required, ...optional]);
  const keys = Object.keys(value);
  return required.every((key) => Object.prototype.hasOwnProperty.call(value, key))
    && keys.every((key) => allowed.has(key));
}

function boundedText(value: unknown, minimum: number, maximum: number): string | null {
  if (typeof value !== "string") return null;
  const normalized = value.trim();
  return normalized.length >= minimum && normalized.length <= maximum ? normalized : null;
}

function safeId(value: unknown): string | null {
  const normalized = boundedText(value, 1, MAX_ID_LENGTH);
  return normalized && SAFE_ID.test(normalized) ? normalized : null;
}

function planHash(value: unknown): string | null {
  return typeof value === "string" && SHA256_PLAN_HASH.test(value) ? value : null;
}

function positiveRevision(value: unknown): number | null {
  return typeof value === "number"
    && Number.isSafeInteger(value)
    && value >= 1
    ? value
    : null;
}

function positiveAmount(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

function supportedCurrency(value: unknown): "PLN" | "EUR" | "USD" | null {
  if (typeof value !== "string") return null;
  const normalized = value.trim();
  return SUPPORTED_CURRENCIES.has(normalized as "PLN" | "EUR" | "USD")
    ? normalized as "PLN" | "EUR" | "USD"
    : null;
}

function parseCommandArguments(
  name: string,
  callId: string,
  args: JsonRecord,
): RealtimeCommand | null {
  if (name === "submit_mission") {
    if (!hasExactKeys(args, ["transcript"])) return null;
    const transcript = boundedText(args.transcript, 3, MAX_TEXT_LENGTH);
    return transcript ? { name, callId, transcript } : null;
  }

  if (name === "confirm_contract") {
    if (!hasExactKeys(args, ["mission_id", "revision"])) return null;
    const missionId = safeId(args.mission_id);
    const revision = positiveRevision(args.revision);
    return missionId && revision !== null ? { name, callId, missionId, revision } : null;
  }

  if (name === "correct_mission") {
    if (!hasExactKeys(args, ["mission_id", "revision", "correction"])) return null;
    const missionId = safeId(args.mission_id);
    const revision = positiveRevision(args.revision);
    const correction = boundedText(args.correction, 3, MAX_TEXT_LENGTH);
    return missionId && revision !== null && correction
      ? { name, callId, missionId, revision, correction }
      : null;
  }

  if (name === "approve_purchase") {
    if (!hasExactKeys(args, [
      "mission_id",
      "approval_id",
      "revision",
      "amount",
      "currency",
      "plan_hash",
      "merchant_id",
    ])) {
      return null;
    }
    const missionId = safeId(args.mission_id);
    const approvalId = safeId(args.approval_id);
    const revision = positiveRevision(args.revision);
    const amount = positiveAmount(args.amount);
    const currency = supportedCurrency(args.currency);
    const trustedPlanHash = planHash(args.plan_hash);
    const merchantId = safeId(args.merchant_id);
    return missionId && approvalId && revision !== null && amount !== null && currency
      && trustedPlanHash && merchantId
      ? {
          name,
          callId,
          missionId,
          approvalId,
          revision,
          amount,
          currency,
          planHash: trustedPlanHash,
          merchantId,
        }
      : null;
  }

  if (name === "reject_purchase") {
    if (!hasExactKeys(args, ["mission_id", "approval_id", "revision", "choice"])) return null;
    const missionId = safeId(args.mission_id);
    const approvalId = safeId(args.approval_id);
    const revision = positiveRevision(args.revision);
    const choice = args.choice === "cancel" || args.choice === "review" ? args.choice : null;
    return missionId && approvalId && revision !== null && choice
      ? { name, callId, missionId, approvalId, revision, choice }
      : null;
  }

  if (name === "choose_recovery") {
    if (!hasExactKeys(args, ["mission_id", "action_request_id", "revision", "choice"])) return null;
    const missionId = safeId(args.mission_id);
    const actionRequestId = safeId(args.action_request_id);
    const revision = positiveRevision(args.revision);
    const choice = boundedText(args.choice, 1, MAX_CHOICE_LENGTH);
    return missionId && actionRequestId && revision !== null && choice
      ? { name, callId, missionId, actionRequestId, revision, choice }
      : null;
  }

  if (name === "cancel_mission") {
    if (!hasExactKeys(args, ["mission_id", "revision"])) return null;
    const missionId = safeId(args.mission_id);
    const revision = positiveRevision(args.revision);
    return missionId && revision !== null ? { name, callId, missionId, revision } : null;
  }

  if (name === "request_human") {
    if (!hasExactKeys(args, ["mission_id", "revision"], ["reason"])) return null;
    const missionId = safeId(args.mission_id);
    const revision = positiveRevision(args.revision);
    const reason = args.reason === undefined
      ? undefined
      : boundedText(args.reason, 3, MAX_REASON_LENGTH);
    if (!missionId || revision === null || reason === null) return null;
    return reason === undefined
      ? { name, callId, missionId, revision }
      : { name, callId, missionId, revision, reason };
  }

  if (name === "get_status") {
    if (!hasExactKeys(args, ["mission_id"])) return null;
    const missionId = safeId(args.mission_id);
    return missionId ? { name, callId, missionId } : null;
  }

  if (name === "get_purchase_plan") {
    if (!hasExactKeys(args, ["mission_id", "revision"])) return null;
    const missionId = safeId(args.mission_id);
    const revision = positiveRevision(args.revision);
    return missionId && revision !== null ? { name, callId, missionId, revision } : null;
  }

  if (name === "select_delivery") {
    if (!hasExactKeys(args, ["mission_id", "revision", "option_id"])) return null;
    const missionId = safeId(args.mission_id);
    const revision = positiveRevision(args.revision);
    const optionId = safeId(args.option_id);
    return missionId && revision !== null && optionId
      ? { name, callId, missionId, revision, optionId }
      : null;
  }

  return null;
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

export function parseRealtimeCommand(value: unknown): RealtimeCommand | null {
  const event = record(value);
  if (event.type !== "response.done") return null;
  const response = record(event.response);
  if (!Array.isArray(response.output)) return null;
  const functionCalls = response.output
    .map(jsonRecord)
    .filter((item): item is JsonRecord => item?.type === "function_call");
  // A response with more than one command is ambiguous and must not trigger any action.
  if (functionCalls.length !== 1) return null;

  const item = functionCalls[0];
  if (!item) return null;
  const name = typeof item.name === "string" ? item.name : "";
  const callId = safeId(item.call_id);
  if (!callId || typeof item.arguments !== "string") return null;
  try {
    const args = jsonRecord(JSON.parse(item.arguments));
    return args ? parseCommandArguments(name, callId, args) : null;
  } catch {
    return null;
  }
}

export function parseSubmitMissionCall(value: unknown): SubmitMissionCall | null {
  const command = parseRealtimeCommand(value);
  return command?.name === "submit_mission"
    ? { callId: command.callId, transcript: command.transcript }
    : null;
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
