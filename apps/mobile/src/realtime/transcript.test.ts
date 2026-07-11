import type { RealtimeTranscriptEvent } from "@/realtime/events";
import { RealtimeTranscriptBuffer } from "@/realtime/transcript";

const delta = (eventId: string, itemId: string, text: string): RealtimeTranscriptEvent => ({
  kind: "delta",
  eventId,
  itemId,
  contentIndex: 0,
  delta: text,
});

describe("RealtimeTranscriptBuffer", () => {
  it("streams drafts, replaces them with finals, and ignores duplicates and late deltas", () => {
    const buffer = new RealtimeTranscriptBuffer();
    buffer.register({ itemId: "item-1", previousItemId: null });
    buffer.apply(delta("event-1", "item-1", "Kup "));
    buffer.apply(delta("event-2", "item-1", "napoje"));
    buffer.apply(delta("event-2", "item-1", "napoje"));

    expect(buffer.previewText()).toBe("Kup napoje");
    expect(buffer.finalText()).toBe("");

    buffer.apply({
      kind: "completed",
      eventId: "event-3",
      itemId: "item-1",
      contentIndex: 0,
      transcript: "Kup napoje i wodę.",
    });
    buffer.apply(delta("event-4", "item-1", " spóźnione"));

    expect(buffer.previewText()).toBe("Kup napoje i wodę.");
    expect(buffer.finalText()).toBe("Kup napoje i wodę.");
  });

  it("keeps committed turns ordered and excludes failed drafts from actionable text", () => {
    const buffer = new RealtimeTranscriptBuffer();
    buffer.register({ itemId: "item-1", previousItemId: null });
    buffer.register({ itemId: "item-2", previousItemId: "item-1" });
    buffer.apply(delta("event-2", "item-2", "Druga wypowiedź"));
    buffer.apply(delta("event-1", "item-1", "Pierwsza wypowiedź"));
    buffer.apply({
      kind: "completed",
      itemId: "item-1",
      contentIndex: 0,
      transcript: "Pierwsza wypowiedź.",
    });
    buffer.fail({ itemId: "item-2", contentIndex: 0, eventId: "failed-2" });

    expect(buffer.previewText()).toBe("Pierwsza wypowiedź. Druga wypowiedź");
    expect(buffer.finalText()).toBe("Pierwsza wypowiedź.");
  });

  it("uses ordered segment text as a preview fallback", () => {
    const buffer = new RealtimeTranscriptBuffer();
    buffer.apply({
      kind: "segment",
      itemId: "item-1",
      contentIndex: 0,
      segment: { id: "segment-2", text: "świecie", start: 0.8 },
    });
    buffer.apply({
      kind: "segment",
      itemId: "item-1",
      contentIndex: 0,
      segment: { id: "segment-1", text: "Cześć", start: 0 },
    });

    expect(buffer.previewText()).toBe("Cześć świecie");
    expect(buffer.finalText()).toBe("");
  });
});
