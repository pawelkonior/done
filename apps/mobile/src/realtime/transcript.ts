import type {
  RealtimeTranscriptEvent,
  RealtimeTranscriptFailure,
  RealtimeTranscriptOrderEvent,
} from "@/realtime/events";

interface TranscriptSegment {
  id: string;
  text: string;
  start: number;
}

interface TranscriptPart {
  draft: string;
  final: string | null;
  failed: boolean;
  segments: Map<string, TranscriptSegment>;
}

const partKey = (itemId: string, contentIndex: number) => `${itemId}:${contentIndex}`;

/** Keeps partial Realtime transcripts ordered and safe to submit. */
export class RealtimeTranscriptBuffer {
  private readonly itemOrder: string[] = [];
  private readonly parts = new Map<string, TranscriptPart>();
  private readonly seenEvents = new Set<string>();

  clear() {
    this.itemOrder.length = 0;
    this.parts.clear();
    this.seenEvents.clear();
  }

  register({ itemId, previousItemId }: RealtimeTranscriptOrderEvent) {
    if (this.itemOrder.includes(itemId)) return;
    const previousIndex = previousItemId ? this.itemOrder.indexOf(previousItemId) : -1;
    if (previousIndex >= 0) this.itemOrder.splice(previousIndex + 1, 0, itemId);
    else this.itemOrder.push(itemId);
  }

  apply(event: RealtimeTranscriptEvent) {
    if (event.eventId && this.seenEvents.has(event.eventId)) return;
    if (event.eventId) this.seenEvents.add(event.eventId);
    this.register({ itemId: event.itemId, previousItemId: null });
    const part = this.getPart(event.itemId, event.contentIndex);
    if (event.kind === "delta") {
      if (!part.final && !part.failed) part.draft += event.delta;
      return;
    }
    if (event.kind === "completed") {
      part.final = event.transcript.trim();
      part.failed = false;
      return;
    }
    part.segments.set(event.segment.id, event.segment);
  }

  fail(event: RealtimeTranscriptFailure) {
    if (event.eventId && this.seenEvents.has(event.eventId)) return;
    if (event.eventId) this.seenEvents.add(event.eventId);
    this.register({ itemId: event.itemId, previousItemId: null });
    this.getPart(event.itemId, event.contentIndex).failed = true;
  }

  previewText() {
    return this.collect(false);
  }

  finalText() {
    return this.collect(true);
  }

  private getPart(itemId: string, contentIndex: number) {
    const key = partKey(itemId, contentIndex);
    const existing = this.parts.get(key);
    if (existing) return existing;
    const created: TranscriptPart = {
      draft: "",
      final: null,
      failed: false,
      segments: new Map(),
    };
    this.parts.set(key, created);
    return created;
  }

  private collect(finalOnly: boolean) {
    const values: string[] = [];
    for (const itemId of this.itemOrder) {
      const itemParts = [...this.parts.entries()]
        .filter(([key]) => key.startsWith(`${itemId}:`))
        .sort(([left], [right]) => Number(left.split(":").at(-1)) - Number(right.split(":").at(-1)));
      for (const [, part] of itemParts) {
        if (finalOnly) {
          if (!part.failed && part.final?.trim()) values.push(part.final.trim());
          continue;
        }
        const segments = [...part.segments.values()]
          .sort((left, right) => left.start - right.start)
          .map((segment) => segment.text.trim())
          .filter(Boolean)
          .join(" ");
        const value = part.final?.trim() || part.draft.trim() || segments;
        if (value) values.push(value);
      }
    }
    return values.join(" ").trim();
  }
}
