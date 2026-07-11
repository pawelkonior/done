import { act, render, waitFor } from "@testing-library/react-native";
import { getRealtimeClientSecret } from "@/api/client";
import { LiveVoiceSheet } from "@/components/LiveVoiceSheet";
import { executeMissionRealtimeCommand } from "@/realtime/mission-commands";
import type { MissionDetail } from "@/types/domain";

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
}));
jest.mock("@/realtime/mission-commands", () => {
  return {
    executeMissionRealtimeCommand: jest.fn(),
    MissionCommandRejected: class extends Error {},
  };
});
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
        onUseText={jest.fn()}
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
        onUseText={jest.fn()}
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
    await screen.unmount();
  });

  it("preserves intake mode and does not execute mission commands", async () => {
    const onMissionCreated = jest.fn();
    const onSubmitTranscript = jest.fn(async () => ({
      mission_id: "mission-new",
      status: "clarification_required" as const,
    }));
    const screen = await render(
      <LiveVoiceSheet
        visible
        language="pl-PL"
        onClose={jest.fn()}
        onUseText={jest.fn()}
        onSubmitTranscript={onSubmitTranscript}
        onMissionCreated={onMissionCreated}
      />,
    );

    await waitFor(() => expect(getRealtimeClientSecret).toHaveBeenCalledWith("pl-PL", undefined));
    await act(async () => {
      mockCallbacks.onEvent(responseDone("submit_mission", {
        transcript: "Prezenty dla pięciu dziesięciolatków do 500 PLN.",
      }, "call-submit"));
      await Promise.resolve();
    });

    await waitFor(() => expect(onSubmitTranscript).toHaveBeenCalledWith(
      "Prezenty dla pięciu dziesięciolatków do 500 PLN.",
    ));
    expect(executeMissionRealtimeCommand).not.toHaveBeenCalled();
    expect(onMissionCreated).toHaveBeenCalledWith("mission-new");
    expect(mockSend).toHaveBeenCalledWith({
      type: "conversation.item.create",
      item: {
        type: "function_call_output",
        call_id: "call-submit",
        output: JSON.stringify({
          ok: true,
          mission_id: "mission-new",
          status: "clarification_required",
        }),
      },
    });
    await screen.unmount();
  });
});
