import { act, fireEvent, render, waitFor } from "@testing-library/react-native";
import { getRealtimeClientSecret, resolveActionRequest } from "@/api/client";
import { LiveVoiceSheet } from "@/components/LiveVoiceSheet";
import { executeCatalogRealtimeCommand } from "@/realtime/catalog-commands";
import type { CatalogCommandOutput } from "@/realtime/catalog-commands";
import { executeMissionRealtimeCommand } from "@/realtime/mission-commands";
import type { CatalogOffer, MissionDetail } from "@/types/domain";

const mockConnect = jest.fn(async () => undefined);
const mockSend = jest.fn();
const mockDisconnect = jest.fn();
let mockCallbacks: {
  onStateChange: (state: string) => void;
  onEvent: (event: unknown) => void;
  onError: (error: Error) => void;
};

jest.mock("@/api/client", () => ({
  getRealtimeClientSecret: jest.fn(),
  resolveActionRequest: jest.fn(),
}));
jest.mock("@/realtime/mission-commands", () => {
  return {
    executeMissionRealtimeCommand: jest.fn(),
    MissionCommandRejected: class extends Error {},
  };
});
jest.mock("@/realtime/catalog-commands", () => ({
  executeCatalogRealtimeCommand: jest.fn(),
  CatalogCommandRejected: class extends Error {
    code = "CATALOG_SEARCH_FAILED";
  },
}));
jest.mock("@/realtime/transport", () => ({
  createRealtimeTransport: (callbacks: typeof mockCallbacks) => {
    mockCallbacks = callbacks;
    return { connect: mockConnect, send: mockSend, disconnect: mockDisconnect };
  },
}));
jest.mock("lucide-react-native", () => ({
  AudioLines: () => null,
  Check: () => null,
  Keyboard: () => null,
  Mic2: () => null,
  RefreshCw: () => null,
  Sparkles: () => null,
  X: () => null,
}));
jest.mock("expo-linear-gradient", () => {
  const React = require("react");
  const { View } = require("react-native");
  return {
    LinearGradient: ({ children, ...props }: { children?: React.ReactNode }) =>
      React.createElement(View, props, children),
  };
});

const PLAN_HASH = `sha256:${"a".repeat(64)}`;

const updatedDetail = {
  mission: {
    id: "mission-1",
    title: "Birthday supplies",
    subtitle: "Approved",
    status: "executing",
    current_step: 6,
    total_steps: 7,
    progress: 6 / 7,
    latest_update: "Approval recorded",
    created_at: "2026-07-11T10:00:00Z",
    revision: 5,
  },
  contract: null,
  basket: null,
  approval: null,
  portfolio_decision: null,
  order: null,
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
} as MissionDetail;

const responseDone = (name: string, args: unknown, callId: string) => ({
  type: "response.done",
  response: {
    output: [{
      type: "function_call",
      name,
      call_id: callId,
      arguments: JSON.stringify(args),
    }],
  },
});

describe("LiveVoiceSheet mission commands", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.mocked(getRealtimeClientSecret).mockResolvedValue({
      value: "ephemeral-secret",
      expires_at: 1_800_000_000,
      model: "gpt-realtime",
      voice: "marin",
    });
  });

  it("mints a mission-bound session, executes the guarded command and returns function output", async () => {
    const onMissionUpdated = jest.fn();
    jest.mocked(executeMissionRealtimeCommand).mockResolvedValue({
      detail: updatedDetail,
      output: { ok: true, action: "purchase_approval_recorded", status: "executing" },
    });
    const screen = await render(
      <LiveVoiceSheet
        visible
        language="pl-PL"
        missionId="mission-1"
        onClose={jest.fn()}
        onMissionUpdated={onMissionUpdated}
      />,
    );

    await waitFor(() => expect(getRealtimeClientSecret).toHaveBeenCalledWith("pl-PL", "mission-1"));
    await act(async () => {
      mockCallbacks.onEvent({ type: "input_audio_buffer.speech_started" });
      mockCallbacks.onEvent({
        type: "input_audio_buffer.committed",
        item_id: "item-1",
        previous_item_id: null,
      });
      mockCallbacks.onEvent({
        type: "conversation.item.input_audio_transcription.completed",
        item_id: "item-1",
        content_index: 0,
        transcript: "Tak, zatwierdzam zakup za 499,99 zł.",
      });
      mockCallbacks.onEvent(responseDone("approve_purchase", {
        mission_id: "mission-1",
        approval_id: "approval-9",
        revision: 4,
        amount: 499.99,
        currency: "PLN",
        plan_hash: PLAN_HASH,
        merchant_id: "merchant-b",
      }, "call-approve"));
      await Promise.resolve();
    });

    await waitFor(() => expect(executeMissionRealtimeCommand).toHaveBeenCalledWith({
      name: "approve_purchase",
      callId: "call-approve",
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
    }));
    expect(onMissionUpdated).toHaveBeenCalledWith(updatedDetail);
    expect(mockSend).toHaveBeenCalledWith({
      type: "conversation.item.create",
      item: {
        type: "function_call_output",
        call_id: "call-approve",
        output: JSON.stringify({ ok: true, action: "purchase_approval_recorded", status: "executing" }),
      },
    });
    await act(async () => {
      mockCallbacks.onEvent({ type: "response.done", response: { output: [] } });
      await new Promise((resolve) => setTimeout(resolve, 300));
    });
    await waitFor(() => expect(getRealtimeClientSecret).toHaveBeenCalledTimes(2));
    await screen.unmount();
  });

  it("never reuses a previous voice turn as purchase-approval evidence", async () => {
    jest.mocked(executeMissionRealtimeCommand).mockResolvedValue({
      detail: updatedDetail,
      output: { ok: true, action: "purchase_approval_recorded" },
    });
    const screen = await render(
      <LiveVoiceSheet
        visible
        language="pl-PL"
        missionId="mission-1"
        onClose={jest.fn()}
      />,
    );
    await waitFor(() => expect(getRealtimeClientSecret).toHaveBeenCalled());

    await act(async () => {
      mockCallbacks.onEvent({ type: "input_audio_buffer.speech_started" });
      mockCallbacks.onEvent({
        type: "input_audio_buffer.committed",
        item_id: "item-old",
        previous_item_id: null,
      });
      mockCallbacks.onEvent({
        type: "conversation.item.input_audio_transcription.completed",
        item_id: "item-old",
        content_index: 0,
        transcript: "Jaki jest status?",
      });
      mockCallbacks.onEvent({ type: "input_audio_buffer.speech_started" });
      mockCallbacks.onEvent({
        type: "input_audio_buffer.committed",
        item_id: "item-current",
        previous_item_id: "item-old",
      });
      mockCallbacks.onEvent(responseDone("approve_purchase", {
        mission_id: "mission-1",
        approval_id: "approval-9",
        revision: 4,
        amount: 499.99,
        currency: "PLN",
        plan_hash: PLAN_HASH,
        merchant_id: "merchant-b",
      }, "call-current-turn"));
      await Promise.resolve();
    });
    expect(executeMissionRealtimeCommand).not.toHaveBeenCalled();

    await act(async () => {
      mockCallbacks.onEvent({
        type: "conversation.item.input_audio_transcription.completed",
        item_id: "item-current",
        content_index: 0,
        transcript: "Tak, zatwierdzam dokładnie ten zakup.",
      });
      await Promise.resolve();
    });
    await waitFor(() => expect(executeMissionRealtimeCommand).toHaveBeenCalledWith(
      expect.objectContaining({ name: "approve_purchase", callId: "call-current-turn" }),
      {
        missionId: "mission-1",
        voiceTranscript: "Tak, zatwierdzam dokładnie ten zakup.",
      },
    ));

    await act(async () => {
      mockCallbacks.onEvent(responseDone("approve_purchase", {
        mission_id: "mission-1",
        approval_id: "approval-9",
        revision: 4,
        amount: 499.99,
        currency: "PLN",
        plan_hash: PLAN_HASH,
        merchant_id: "merchant-b",
      }, "call-replayed-turn"));
      await Promise.resolve();
    });
    await waitFor(() => expect(mockSend).toHaveBeenCalledWith(expect.objectContaining({
      type: "conversation.item.create",
      item: expect.objectContaining({
        call_id: "call-replayed-turn",
        output: expect.stringContaining("VOICE_EVIDENCE_REQUIRED"),
      }),
    })));
    expect(executeMissionRealtimeCommand).toHaveBeenCalledTimes(1);
    await screen.unmount();
  });

  it("submits a focused clarification directly from the verified microphone transcript", async () => {
    const onClose = jest.fn();
    const onMissionUpdated = jest.fn();
    const onSubmitFocusedAction = jest.fn(async () => updatedDetail);
    const screen = await render(
      <LiveVoiceSheet
        visible
        language="en-PL"
        missionId="mission-1"
        focusedAction={{
          id: "action-3",
          revision: 6,
          choice: "answer_by_voice",
          question: "What should this purchase include?",
          missingDetails: ["What to buy: gifts or party supplies", "Delivery date and time"],
        }}
        onSubmitFocusedAction={onSubmitFocusedAction}
        onClose={onClose}
        onMissionUpdated={onMissionUpdated}
      />,
    );
    await waitFor(() => expect(getRealtimeClientSecret).toHaveBeenCalledWith("en-PL", "mission-1"));
    expect(screen.getByText("• What to buy: gifts or party supplies")).toBeTruthy();

    await act(async () => {
      mockCallbacks.onEvent({
        type: "input_audio_buffer.committed",
        item_id: "item-answer",
        previous_item_id: null,
      });
      mockCallbacks.onEvent({
        type: "conversation.item.input_audio_transcription.completed",
        item_id: "item-answer",
        content_index: 0,
        transcript: "Buy birthday party supplies and deliver them next Friday at 5 PM.",
      });
      await Promise.resolve();
    });

    await waitFor(() => expect(onSubmitFocusedAction).toHaveBeenCalledWith(
      "Buy birthday party supplies and deliver them next Friday at 5 PM.",
    ));
    expect(onMissionUpdated).toHaveBeenCalledWith(updatedDetail);
    expect(executeMissionRealtimeCommand).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    await act(async () => {
      mockCallbacks.onEvent({ type: "response.done", response: { output: [] } });
      await new Promise((resolve) => setTimeout(resolve, 300));
    });
    expect(onClose).toHaveBeenCalledTimes(1);
    await screen.unmount();
  });

  it("keeps Live open and reconnects when another clarification is still required", async () => {
    const onClose = jest.fn();
    const continuedDetail: MissionDetail = {
      ...updatedDetail,
      mission: {
        ...updatedDetail.mission,
        status: "clarification_required",
        revision: 7,
      },
      action_requests: [{
        id: "action-4",
        type: "clarification",
        reason_code: "MISSION_CONTRACT_INCOMPLETE",
        question: "What delivery date and time do you need?",
        status: "pending",
        owner: "user",
        options: [{ id: "answer_by_voice", label: "Answer by voice" }],
        context: { missing_information: ["deadline"] },
        created_at: "2026-07-11T10:03:00Z",
      }],
    };
    const onSubmitFocusedAction = jest.fn(async () => continuedDetail);
    const onMissionUpdated = jest.fn();
    const screen = await render(
      <LiveVoiceSheet
        visible
        language="en-PL"
        missionId="mission-1"
        focusedAction={{
          id: "action-3",
          revision: 6,
          choice: "answer_by_voice",
          question: "What should this purchase include?",
          missingDetails: ["What to buy: gifts or party supplies", "Delivery date and time"],
        }}
        onSubmitFocusedAction={onSubmitFocusedAction}
        onClose={onClose}
        onMissionUpdated={onMissionUpdated}
      />,
    );
    await waitFor(() => expect(getRealtimeClientSecret).toHaveBeenCalledTimes(1));

    await act(async () => {
      mockCallbacks.onEvent({
        type: "input_audio_buffer.committed",
        item_id: "item-partial-answer",
        previous_item_id: null,
      });
      mockCallbacks.onEvent({
        type: "conversation.item.input_audio_transcription.completed",
        item_id: "item-partial-answer",
        content_index: 0,
        transcript: "Buy birthday party supplies.",
      });
      await Promise.resolve();
    });

    await waitFor(() => expect(onMissionUpdated).toHaveBeenCalledWith(continuedDetail));
    await waitFor(() => expect(getRealtimeClientSecret).toHaveBeenCalledTimes(2));
    expect(onClose).not.toHaveBeenCalled();
    await act(async () => {
      mockCallbacks.onEvent({ type: "response.done", response: { output: [] } });
      await new Promise((resolve) => setTimeout(resolve, 300));
    });
    expect(onClose).not.toHaveBeenCalled();
    await screen.unmount();
  });

  it("does not let catalog search bypass a focused clarification", async () => {
    const screen = await render(
      <LiveVoiceSheet
        visible
        language="pl-PL"
        missionId="mission-1"
        focusedAction={{
          id: "action-3",
          revision: 6,
          choice: "answer_by_voice",
          question: "What should this purchase include?",
          missingDetails: ["Shopping scope"],
        }}
        onSubmitFocusedAction={jest.fn(async () => updatedDetail)}
        onClose={jest.fn()}
      />,
    );
    await waitFor(() => expect(getRealtimeClientSecret).toHaveBeenCalled());

    await act(async () => {
      mockCallbacks.onEvent(responseDone("search_products", {
        q: "Minecraft",
      }, "call-search-during-clarification"));
      await Promise.resolve();
    });

    expect(executeCatalogRealtimeCommand).not.toHaveBeenCalled();
    expect(mockSend).toHaveBeenCalledWith(expect.objectContaining({
      type: "conversation.item.create",
      item: expect.objectContaining({
        call_id: "call-search-during-clarification",
        output: expect.stringContaining("CATALOG_SEARCH_UNAVAILABLE"),
      }),
    }));
    await screen.unmount();
  });

  it("keeps intake in Live until the mission has enough information to start", async () => {
    const onMissionCreated = jest.fn();
    const intakeDetail: MissionDetail = {
      ...updatedDetail,
      mission: {
        ...updatedDetail.mission,
        id: "mission-new",
        status: "clarification_required",
        revision: 2,
      },
      action_requests: [{
        id: "action-intake",
        type: "clarification",
        reason_code: "MISSION_CONTRACT_INCOMPLETE",
        question: "What delivery date and time do you need?",
        status: "pending",
        owner: "user",
        options: [{ id: "answer_by_voice", label: "Answer by voice" }],
        context: { missing_information: ["deadline"] },
        created_at: "2026-07-11T10:03:00Z",
      }],
    };
    const onSubmitTranscript = jest.fn(async () => ({
      mission_id: "mission-new",
      status: "clarification_required" as const,
      detail: intakeDetail,
    }));
    const readyDetail: MissionDetail = {
      ...updatedDetail,
      mission: {
        ...updatedDetail.mission,
        id: "mission-new",
        status: "approval_required",
        revision: 3,
      },
      action_requests: [],
    };
    jest.mocked(resolveActionRequest).mockResolvedValue(readyDetail);
    const screen = await render(
      <LiveVoiceSheet
        visible
        language="pl-PL"
        onClose={jest.fn()}
        onSubmitTranscript={onSubmitTranscript}
        onMissionCreated={onMissionCreated}
      />,
    );

    await waitFor(() => expect(getRealtimeClientSecret).toHaveBeenCalledWith("pl-PL", undefined));
    await act(async () => {
      mockCallbacks.onEvent({
        type: "input_audio_buffer.committed",
        item_id: "item-intake",
        previous_item_id: null,
      });
      mockCallbacks.onEvent(responseDone("submit_mission", {
        transcript: "Zmyślony tekst modelu, którego nie wolno wysłać.",
      }, "call-submit"));
      await Promise.resolve();
    });
    expect(onSubmitTranscript).not.toHaveBeenCalled();

    await act(async () => {
      mockCallbacks.onEvent({
        type: "conversation.item.input_audio_transcription.completed",
        item_id: "item-intake",
        content_index: 0,
        transcript: "Chcę kupić prezenty dla pięciu dziesięciolatków do 500 PLN.",
      });
      await Promise.resolve();
    });

    await waitFor(() => expect(onSubmitTranscript).toHaveBeenCalledWith(
      "Chcę kupić prezenty dla pięciu dziesięciolatków do 500 PLN.",
    ));
    expect(executeMissionRealtimeCommand).not.toHaveBeenCalled();
    expect(onMissionCreated).not.toHaveBeenCalled();
    expect(mockSend).toHaveBeenCalledWith({
      type: "conversation.item.create",
      item: {
        type: "function_call_output",
        call_id: "call-submit",
        output: JSON.stringify({
          ok: true,
          mission_id: "mission-new",
          status: "clarification_required",
          needs_clarification: true,
          next_question: "What delivery date and time do you need?",
          missing_details: ["Delivery date and time"],
        }),
      },
    });
    await waitFor(() => expect(getRealtimeClientSecret).toHaveBeenCalledWith("pl-PL", "mission-new"));
    expect(screen.getByText("What delivery date and time do you need?")).toBeTruthy();
    expect(onMissionCreated).not.toHaveBeenCalled();

    await act(async () => {
      mockCallbacks.onEvent({
        type: "input_audio_buffer.committed",
        item_id: "item-follow-up",
        previous_item_id: null,
      });
      mockCallbacks.onEvent({
        type: "conversation.item.input_audio_transcription.completed",
        item_id: "item-follow-up",
        content_index: 0,
        transcript: "Deliver tomorrow by 5 PM.",
      });
      await Promise.resolve();
    });
    await waitFor(() => expect(resolveActionRequest).toHaveBeenCalledWith("action-intake", {
      choice: "answer_by_voice",
      voice_transcript: "Deliver tomorrow by 5 PM.",
      expected_revision: 2,
    }));
    expect(onMissionCreated).not.toHaveBeenCalled();
    await act(async () => {
      mockCallbacks.onEvent({ type: "response.done", response: { output: [] } });
      await new Promise((resolve) => setTimeout(resolve, 300));
    });
    expect(onMissionCreated).toHaveBeenCalledWith("mission-new");
    await screen.unmount();
  });

  it("keeps the manual Create mission submission in Live when details are missing", async () => {
    const onMissionCreated = jest.fn();
    const draftDetail: MissionDetail = {
      ...updatedDetail,
      mission: {
        ...updatedDetail.mission,
        id: "mission-manual",
        status: "clarification_required",
        revision: 2,
      },
      action_requests: [{
        id: "action-manual",
        type: "clarification",
        reason_code: "MISSION_CONTRACT_INCOMPLETE",
        question: "What delivery date and time do you need?",
        status: "pending",
        owner: "user",
        options: [{ id: "answer_by_voice", label: "Answer by voice" }],
        context: { missing_information: ["deadline"] },
        created_at: "2026-07-11T10:03:00Z",
      }],
    };
    const onSubmitTranscript = jest.fn(async () => ({
      mission_id: "mission-manual",
      status: "clarification_required" as const,
      detail: draftDetail,
    }));
    const screen = await render(
      <LiveVoiceSheet
        visible
        language="en-PL"
        onClose={jest.fn()}
        onSubmitTranscript={onSubmitTranscript}
        onMissionCreated={onMissionCreated}
      />,
    );
    await waitFor(() => expect(getRealtimeClientSecret).toHaveBeenCalledWith("en-PL", undefined));
    await act(async () => {
      mockCallbacks.onEvent({
        type: "input_audio_buffer.committed",
        item_id: "item-manual",
        previous_item_id: null,
      });
      mockCallbacks.onEvent({
        type: "conversation.item.input_audio_transcription.completed",
        item_id: "item-manual",
        content_index: 0,
        transcript: "Buy birthday party supplies for ten guests.",
      });
      await Promise.resolve();
    });

    await fireEvent.press(screen.getByTestId("submit-live-transcript"));

    await waitFor(() => expect(onSubmitTranscript).toHaveBeenCalledWith(
      "Buy birthday party supplies for ten guests.",
    ));
    await waitFor(() => expect(getRealtimeClientSecret).toHaveBeenCalledWith("en-PL", "mission-manual"));
    expect(screen.getByText("What delivery date and time do you need?")).toBeTruthy();
    expect(onMissionCreated).not.toHaveBeenCalled();
    await screen.unmount();
  });

  it("searches every matching product in intake mode and returns the catalog output to the agent", async () => {
    const offers: CatalogOffer[] = Array.from({ length: 29 }, (_, index) => ({
      store_id: "store-smyk",
      store_name: "Smyk",
      city: "Warsaw",
      product_id: `product-${index}`,
      sku: `SKU-${index}`,
      product_name: `Minecraft product ${index}`,
      brand: "Minecraft",
      category: "gifts",
      unit_label: "1 item",
      product_url: `https://example.test/products/${index}`,
      price_cents: 1_000 + index,
      currency: "PLN",
      price_display: `${10 + index / 100} PLN`,
      quantity: 5,
      effective_status: "available",
      is_available: true,
      updated_at: "2026-07-11T13:00:00Z",
    }));
    const catalogOutput: CatalogCommandOutput = {
      ok: true as const,
      action: "catalog_searched" as const,
      source: "researched_catalog" as const,
      executable: false as const,
      query: "Minecraft",
      total: 29,
      returned: 29,
      complete: true,
      offers,
    };
    jest.mocked(executeCatalogRealtimeCommand).mockResolvedValue({
      result: {
        offers,
        total: 29,
        limit: 150,
        offset: 0,
      },
      output: catalogOutput,
    });
    const screen = await render(
      <LiveVoiceSheet
        visible
        language="pl-PL"
        onClose={jest.fn()}
        onSubmitTranscript={jest.fn()}
      />,
    );
    await waitFor(() => expect(getRealtimeClientSecret).toHaveBeenCalledWith("pl-PL", undefined));

    const searchCall = responseDone("search_products", {
      q: "Minecraft",
      category: "gifts",
      available: true,
      sort: "price_asc",
    }, "call-search-products");
    await act(async () => {
      mockCallbacks.onEvent(searchCall);
      mockCallbacks.onEvent(searchCall);
      await Promise.resolve();
    });

    await waitFor(() => expect(executeCatalogRealtimeCommand).toHaveBeenCalledWith({
      name: "search_products",
      callId: "call-search-products",
      query: "Minecraft",
      category: "gifts",
      available: true,
      sort: "price_asc",
    }));
    expect(executeCatalogRealtimeCommand).toHaveBeenCalledTimes(1);
    expect(executeMissionRealtimeCommand).not.toHaveBeenCalled();
    expect(mockSend).toHaveBeenCalledWith({
      type: "conversation.item.create",
      item: {
        type: "function_call_output",
        call_id: "call-search-products",
        output: JSON.stringify(catalogOutput),
      },
    });
    expect(mockSend).toHaveBeenCalledWith(expect.objectContaining({
      type: "response.create",
      response: expect.objectContaining({
        instructions: expect.stringContaining("every matching offer"),
      }),
    }));
    await screen.unmount();
  });

  it("refuses mission creation when a tool call has no verified microphone transcript", async () => {
    const onSubmitTranscript = jest.fn();
    const screen = await render(
      <LiveVoiceSheet
        visible
        language="pl-PL"
        onClose={jest.fn()}
        onSubmitTranscript={onSubmitTranscript}
      />,
    );
    await waitFor(() => expect(getRealtimeClientSecret).toHaveBeenCalled());

    await act(async () => {
      mockCallbacks.onEvent(responseDone("submit_mission", {
        transcript: "Treść istnieje wyłącznie w argumencie wygenerowanym przez model.",
      }, "call-without-voice"));
      await Promise.resolve();
    });

    expect(onSubmitTranscript).not.toHaveBeenCalled();
    expect(mockSend).toHaveBeenCalledWith(expect.objectContaining({
      type: "conversation.item.create",
      item: expect.objectContaining({
        call_id: "call-without-voice",
        output: expect.stringContaining("VOICE_TRANSCRIPT_UNAVAILABLE"),
      }),
    }));
    await screen.unmount();
  });
});
