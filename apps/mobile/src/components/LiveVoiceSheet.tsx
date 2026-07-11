import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { AudioLines, Check, RefreshCw, Sparkles, X } from "lucide-react-native";
import { LinearGradient } from "expo-linear-gradient";
import { getRealtimeClientSecret } from "@/api/client";
import type { CreateMissionResponse, MissionDetail } from "@/types/domain";
import {
  parseRealtimeCommand,
  parseTranscriptFailure,
  parseTranscriptOrderEvent,
  parseTranscriptEvent,
  realtimeActivity,
  realtimeInputActivity,
  realtimeServerError,
  type RealtimeCommand,
} from "@/realtime/events";
import {
  executeMissionRealtimeCommand,
  MissionCommandRejected,
} from "@/realtime/mission-commands";
import { RealtimeTranscriptBuffer } from "@/realtime/transcript";
import { createRealtimeTransport } from "@/realtime/transport";
import type { RealtimeTransport } from "@/realtime/transport.types";
import { colors, radii, shadows, spacing, type } from "@/theme/tokens";

type LiveStatus =
  | "connecting"
  | "ready"
  | "listening"
  | "thinking"
  | "speaking"
  | "submitting"
  | "complete"
  | "error";

const statusCopy: Record<LiveStatus, string> = {
  connecting: "Connecting…",
  ready: "Ready",
  listening: "Listening…",
  thinking: "Thinking…",
  speaking: "Speaking",
  submitting: "Creating mission…",
  complete: "Mission ready",
  error: "Connection unavailable",
};

type InputStatus =
  | "connecting"
  | "ready"
  | "hearing"
  | "transcribing"
  | "streaming"
  | "captured"
  | "error";

const inputStatusCopy: Record<InputStatus, string> = {
  connecting: "Connecting…",
  ready: "Start speaking",
  hearing: "Listening…",
  transcribing: "One moment…",
  streaming: "Listening…",
  captured: "Ready for more",
  error: "I couldn’t capture that. Try again.",
};

const errorMessage = (error: unknown) =>
  error instanceof Error ? error.message : "Live voice could not start.";

export function LiveVoiceSheet({
  visible,
  language,
  onClose,
  onSubmitTranscript,
  onMissionCreated,
  missionId: activeMissionId,
  onMissionUpdated,
  onMissionRefreshRequested,
}: {
  visible: boolean;
  language: string;
  onClose: () => void;
  onSubmitTranscript?: (transcript: string) => Promise<CreateMissionResponse>;
  onMissionCreated?: (missionId: string) => void;
  missionId?: string;
  onMissionUpdated?: (detail: MissionDetail) => void;
  onMissionRefreshRequested?: () => void;
}) {
  const [status, setStatus] = useState<LiveStatus>("connecting");
  const [error, setError] = useState<string | null>(null);
  const [transcript, setTranscript] = useState("");
  const [finalTranscript, setFinalTranscript] = useState("");
  const [inputStatus, setInputStatus] = useState<InputStatus>("connecting");
  const [transcriptError, setTranscriptError] = useState<string | null>(null);
  const [createdMissionId, setCreatedMissionId] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  const transportRef = useRef<RealtimeTransport | null>(null);
  const onSubmitRef = useRef(onSubmitTranscript);
  const onMissionCreatedRef = useRef(onMissionCreated);
  const onMissionUpdatedRef = useRef(onMissionUpdated);
  const onMissionRefreshRequestedRef = useRef(onMissionRefreshRequested);
  const generationRef = useRef(0);
  const submittingRef = useRef(false);
  const createdMissionIdRef = useRef<string | null>(null);
  const handledCallsRef = useRef(new Set<string>());
  const latestTurnTranscriptRef = useRef("");
  const currentVoiceItemIdRef = useRef<string | null>(null);
  const voiceEvidenceWaitersRef = useRef(new Set<(transcript?: string) => void>());
  const transcriptBufferRef = useRef(new RealtimeTranscriptBuffer());
  const transcriptScrollRef = useRef<ScrollView | null>(null);

  useEffect(() => {
    onSubmitRef.current = onSubmitTranscript;
  }, [onSubmitTranscript]);

  useEffect(() => {
    onMissionCreatedRef.current = onMissionCreated;
  }, [onMissionCreated]);

  useEffect(() => {
    onMissionUpdatedRef.current = onMissionUpdated;
  }, [onMissionUpdated]);

  useEffect(() => {
    onMissionRefreshRequestedRef.current = onMissionRefreshRequested;
  }, [onMissionRefreshRequested]);

  const rebuildTranscript = useCallback(() => {
    setTranscript(transcriptBufferRef.current.previewText());
    setFinalTranscript(transcriptBufferRef.current.finalText());
  }, []);

  const waitForCurrentVoiceEvidence = useCallback(() => {
    const current = latestTurnTranscriptRef.current.trim();
    if (current.length >= 3) return Promise.resolve(current);
    if (!currentVoiceItemIdRef.current) return Promise.resolve(undefined);
    return new Promise<string | undefined>((resolve) => {
      let settled = false;
      const complete = (transcript?: string) => {
        if (settled) return;
        settled = true;
        clearTimeout(timeout);
        voiceEvidenceWaitersRef.current.delete(complete);
        resolve(transcript?.trim() || undefined);
      };
      const timeout = setTimeout(() => complete(undefined), 3_000);
      voiceEvidenceWaitersRef.current.add(complete);
    });
  }, []);

  const replyToTool = useCallback((
    callId: string,
    output: Record<string, unknown>,
    success: boolean,
  ) => {
    try {
      transportRef.current?.send({
        type: "conversation.item.create",
        item: {
          type: "function_call_output",
          call_id: callId,
          output: JSON.stringify(output),
        },
      });
      transportRef.current?.send({
        type: "response.create",
        response: {
          instructions: success
            ? "Use the function output to confirm the outcome in one short sentence. "
              + "State the current status accurately and never claim a purchase completed unless the output says so."
            : "Explain in one short sentence that the command could not be safely completed or verified. "
              + "Use only the safe error message from the function output, do not retry automatically, and ask "
              + "the user to review the current mission state.",
        },
      });
    } catch {
      // The authoritative API result is already known; spoken follow-up is best effort.
    }
  }, []);

  const submitMission = useCallback(async (missionTranscript: string, callId?: string) => {
    const normalized = missionTranscript.trim();
    if (normalized.length < 3 || submittingRef.current) return;
    if (callId && handledCallsRef.current.has(callId)) return;
    if (callId) handledCallsRef.current.add(callId);
    submittingRef.current = true;
    setStatus("submitting");
    setError(null);
    try {
      const submit = onSubmitRef.current;
      if (!submit || activeMissionId) {
        throw new MissionCommandRejected(
          "INTAKE_COMMAND_UNAVAILABLE",
          "A new mission cannot be created from this existing-mission session.",
        );
      }
      const result = await submit(normalized);
      setTranscript((current) => current.trim().length >= 3 ? current : normalized);
      setInputStatus("captured");
      createdMissionIdRef.current = result.mission_id;
      setCreatedMissionId(result.mission_id);
      setStatus("complete");
      if (callId) {
        replyToTool(callId, { ok: true, mission_id: result.mission_id, status: result.status }, true);
      }
      onMissionCreatedRef.current?.(result.mission_id);
    } catch (submitError) {
      const safeMessage = submitError instanceof MissionCommandRejected
        ? submitError.message
        : "The mission creation result could not be verified. Check the mission list before trying again.";
      setStatus(activeMissionId ? "ready" : "error");
      setError(safeMessage);
      if (callId) {
        replyToTool(callId, {
          ok: false,
          error: {
            code: submitError instanceof MissionCommandRejected ? submitError.code : "MISSION_CREATE_FAILED",
            message: safeMessage,
          },
        }, false);
      }
    } finally {
      submittingRef.current = false;
    }
  }, [activeMissionId, replyToTool]);

  const runMissionCommand = useCallback(async (
    command: Exclude<RealtimeCommand, { name: "submit_mission" }>,
  ) => {
    if (handledCallsRef.current.has(command.callId)) return;
    handledCallsRef.current.add(command.callId);
    if (!activeMissionId) {
      replyToTool(command.callId, {
        ok: false,
        error: {
          code: "MISSION_CONTEXT_REQUIRED",
          message: "That command requires an existing mission session.",
        },
      }, false);
      return;
    }
    if (submittingRef.current) {
      replyToTool(command.callId, {
        ok: false,
        error: {
          code: "COMMAND_IN_PROGRESS",
          message: "Another mission command is still being processed.",
        },
      }, false);
      return;
    }

    submittingRef.current = true;
    setStatus("submitting");
    setError(null);
    try {
      const needsCurrentVoiceEvidence = !["get_status", "confirm_contract"].includes(command.name);
      const voiceTranscript = needsCurrentVoiceEvidence
        ? await waitForCurrentVoiceEvidence()
        : latestTurnTranscriptRef.current;
      const result = await executeMissionRealtimeCommand(command, {
        missionId: activeMissionId,
        voiceTranscript,
      });
      setStatus("complete");
      setInputStatus("captured");
      try {
        onMissionUpdatedRef.current?.(result.detail);
      } catch {
        // The next query refresh will reconcile the UI even if a consumer callback fails.
      }
      replyToTool(command.callId, result.output, true);
    } catch (commandError) {
      const safeMessage = commandError instanceof MissionCommandRejected
        ? commandError.message
        : "The command result could not be verified. Review the refreshed mission before trying again.";
      setStatus("ready");
      setError(safeMessage);
      try {
        onMissionRefreshRequestedRef.current?.();
      } catch {
        // Polling remains available if the immediate refresh callback fails.
      }
      replyToTool(command.callId, {
        ok: false,
        error: {
          code: commandError instanceof MissionCommandRejected ? commandError.code : "MISSION_COMMAND_FAILED",
          message: safeMessage,
        },
      }, false);
    } finally {
      submittingRef.current = false;
    }
  }, [activeMissionId, replyToTool, waitForCurrentVoiceEvidence]);

  const handleEvent = useCallback((event: unknown) => {
    const serverError = realtimeServerError(event);
    if (serverError) {
      setError(serverError);
      setStatus("error");
      return;
    }

    const transcriptEvent = parseTranscriptEvent(event);
    if (transcriptEvent) {
      transcriptBufferRef.current.apply(transcriptEvent);
      if (
        transcriptEvent.kind === "completed"
        && currentVoiceItemIdRef.current === transcriptEvent.itemId
      ) {
        latestTurnTranscriptRef.current = transcriptEvent.transcript;
        for (const complete of voiceEvidenceWaitersRef.current) {
          complete(transcriptEvent.transcript);
        }
      }
      setInputStatus(transcriptEvent.kind === "completed" ? "captured" : "streaming");
      setTranscriptError(null);
      rebuildTranscript();
    }

    const orderEvent = parseTranscriptOrderEvent(event);
    if (orderEvent) {
      transcriptBufferRef.current.register(orderEvent);
      const eventType = event && typeof event === "object" && "type" in event
        ? (event as { type?: unknown }).type
        : undefined;
      if (eventType === "input_audio_buffer.committed") {
        currentVoiceItemIdRef.current = orderEvent.itemId;
      }
    }

    const transcriptFailure = parseTranscriptFailure(event);
    if (transcriptFailure) {
      transcriptBufferRef.current.fail(transcriptFailure);
      setInputStatus("error");
      setTranscriptError("I couldn’t capture that. Please try again.");
      rebuildTranscript();
    }

    const command = parseRealtimeCommand(event);
    if (command?.name === "submit_mission") {
      void (async () => {
        // Input transcription can complete after response.done. Wait for the
        // committed microphone turn instead of trusting the model argument or
        // rejecting a valid utterance because of event ordering.
        const currentTurn = await waitForCurrentVoiceEvidence();
        if (handledCallsRef.current.has(command.callId)) return;
        const capturedTranscript = transcriptBufferRef.current.finalText().trim();
        if (!currentTurn || capturedTranscript.length < 3) {
          handledCallsRef.current.add(command.callId);
          const message = "I couldn’t verify a spoken transcript. Please say the mission again.";
          setStatus("ready");
          setInputStatus("error");
          setTranscriptError(message);
          replyToTool(command.callId, {
            ok: false,
            error: { code: "VOICE_TRANSCRIPT_UNAVAILABLE", message },
          }, false);
          return;
        }
        // The mission API receives only verbatim speech transcription. The
        // model-generated tool argument is a control signal, never source data.
        await submitMission(capturedTranscript, command.callId);
      })();
      return;
    }
    if (command) {
      void runMissionCommand(command);
      return;
    }

    const activity = realtimeActivity(event);
    if (activity && !submittingRef.current && !createdMissionIdRef.current) setStatus(activity);
    const inputActivity = realtimeInputActivity(event);
    if (inputActivity) {
      setInputStatus(inputActivity);
      if (inputActivity === "hearing") {
        for (const complete of voiceEvidenceWaitersRef.current) complete(undefined);
        latestTurnTranscriptRef.current = "";
        currentVoiceItemIdRef.current = null;
        setTranscriptError(null);
      }
    }
  }, [rebuildTranscript, replyToTool, runMissionCommand, submitMission, waitForCurrentVoiceEvidence]);

  useEffect(() => {
    if (!visible) return;
    const generation = ++generationRef.current;
    setStatus("connecting");
    setError(null);
    setTranscript("");
    setFinalTranscript("");
    setInputStatus("connecting");
    setTranscriptError(null);
    setCreatedMissionId(null);
    createdMissionIdRef.current = null;
    latestTurnTranscriptRef.current = "";
    currentVoiceItemIdRef.current = null;
    for (const complete of voiceEvidenceWaitersRef.current) complete(undefined);
    submittingRef.current = false;
    handledCallsRef.current.clear();
    transcriptBufferRef.current.clear();

    const transport = createRealtimeTransport({
      onStateChange: (next) => {
        if (generation !== generationRef.current) return;
        if (next === "connected") {
          setStatus("ready");
          setInputStatus("ready");
        }
        if (next === "failed") {
          setStatus("error");
          setInputStatus("error");
        }
      },
      onEvent: (event) => {
        if (generation === generationRef.current) handleEvent(event);
      },
      onError: (transportError) => {
        if (generation !== generationRef.current) return;
        setError(errorMessage(transportError));
        setStatus("error");
        setInputStatus("error");
      },
    });
    transportRef.current = transport;

    const start = async () => {
      try {
        const secret = await getRealtimeClientSecret(language, activeMissionId);
        if (generation !== generationRef.current) return;
        await transport.connect(secret.value);
        if (generation !== generationRef.current) return;
        transport.send({
          type: "response.create",
          response: {
            instructions: activeMissionId
              ? "Greet the user in one short sentence in the configured language. Say you are ready to discuss "
                + "the current mission and ask what they want to check, correct, approve, or escalate."
              : "Greet the user in one short sentence in the configured language and ask what "
                + "Done should take care of.",
          },
        });
      } catch (startError) {
        if (generation !== generationRef.current) return;
        setError(errorMessage(startError));
        setStatus("error");
        setInputStatus("error");
      }
    };
    void start();

    return () => {
      generationRef.current += 1;
      for (const complete of voiceEvidenceWaitersRef.current) complete(undefined);
      transport.disconnect();
      if (transportRef.current === transport) transportRef.current = null;
    };
  }, [activeMissionId, handleEvent, language, retryKey, visible]);

  const close = () => {
    transportRef.current?.disconnect();
    onClose();
  };

  const retry = () => {
    transportRef.current?.disconnect();
    setRetryKey((value) => value + 1);
  };

  const statusTitle = activeMissionId && status === "submitting"
    ? "Updating mission…"
    : activeMissionId && status === "complete"
      ? "Mission updated"
      : statusCopy[status];
  const inputCopy = inputStatusCopy[inputStatus];
  const busy = ["connecting", "thinking", "submitting"].includes(status);

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={close}>
      <View style={styles.backdrop}>
        <Pressable style={StyleSheet.absoluteFill} onPress={close} accessibilityLabel="Close live voice" />
        <View style={styles.sheet} testID="live-voice-sheet">
          <View style={styles.handle} />
          <View style={styles.header}>
            <View style={styles.brandRow}>
              <Sparkles size={16} color={colors.primaryBright} />
              <Text style={styles.eyebrow}>Live</Text>
            </View>
            <Pressable onPress={close} accessibilityRole="button" accessibilityLabel="Close" style={styles.close}>
              <X size={21} color={colors.textSecondary} />
            </Pressable>
          </View>

          <View style={styles.voiceStage}>
            <View style={styles.orbStage}>
              <View style={[styles.glow, status === "error" && styles.errorGlow]} />
              <LinearGradient
                colors={status === "complete" ? [colors.success, colors.secondary] : status === "error" ? [colors.error, colors.primarySoft] : [colors.primaryBright, colors.secondary]}
                style={styles.liveOrb}
              >
                <View style={styles.liveOrbInner}>
                  {busy ? <ActivityIndicator size="large" color={colors.text} /> : status === "complete" ? <Check size={42} color={colors.text} /> : <AudioLines size={43} color={colors.text} />}
                </View>
              </LinearGradient>
            </View>
            <Text accessibilityLiveRegion="polite" style={styles.statusTitle}>{statusTitle}</Text>
          </View>

          <ScrollView
            ref={transcriptScrollRef}
            style={styles.transcriptBox}
            contentContainerStyle={styles.transcriptContent}
            onContentSizeChange={() => transcriptScrollRef.current?.scrollToEnd({ animated: true })}
            testID="live-transcript-preview"
          >
            <Text
              accessibilityLiveRegion="polite"
              style={[styles.transcript, !transcript && styles.transcriptPlaceholder]}
              testID="live-transcript-text"
            >
              {transcript || inputCopy}
              {transcript && inputStatus === "streaming" ? <Text style={styles.transcriptCursor}> ▋</Text> : null}
            </Text>
            {transcriptError ? <Text accessibilityRole="alert" style={styles.transcriptError}>{transcriptError}</Text> : null}
          </ScrollView>

          {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}

          <View style={styles.actions}>
            {status === "error" ? (
              <Pressable onPress={retry} accessibilityRole="button" style={({ pressed }) => [styles.secondaryButton, pressed && styles.pressed]}>
                <RefreshCw size={17} color={colors.primaryBright} />
                <Text style={styles.secondaryText}>Try live again</Text>
              </Pressable>
            ) : !activeMissionId && !createdMissionId && finalTranscript.length >= 3 ? (
              <Pressable
                onPress={() => void submitMission(finalTranscript)}
                disabled={status === "submitting"}
                accessibilityRole="button"
                style={({ pressed }) => [styles.primaryWrap, pressed && styles.pressed]}
                testID="submit-live-transcript"
              >
                <LinearGradient colors={[colors.primary, "#7442EA"]} style={styles.primaryButton}>
                  <Text style={styles.primaryText}>Create mission</Text>
                </LinearGradient>
              </Pressable>
            ) : null}
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, justifyContent: "flex-end", backgroundColor: colors.overlay },
  sheet: {
    width: "100%",
    maxWidth: 520,
    maxHeight: "94%",
    alignSelf: "center",
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    paddingBottom: Platform.OS === "ios" ? 34 : spacing.lg,
    borderTopLeftRadius: radii.xl,
    borderTopRightRadius: radii.xl,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  handle: { width: 42, height: 4, borderRadius: 2, backgroundColor: colors.textMuted, opacity: 0.55, alignSelf: "center", marginBottom: spacing.md },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  brandRow: { flexDirection: "row", alignItems: "center", gap: spacing.xs, flex: 1 },
  eyebrow: { ...type.eyebrow, color: colors.text },
  close: { width: 42, height: 42, borderRadius: 21, backgroundColor: "rgba(255,255,255,0.04)", alignItems: "center", justifyContent: "center" },
  voiceStage: { alignItems: "center", paddingTop: spacing.xl, paddingBottom: spacing.lg },
  orbStage: { width: 136, height: 136, alignItems: "center", justifyContent: "center" },
  glow: { position: "absolute", top: 3, left: 3, width: 130, height: 130, borderRadius: 65, backgroundColor: colors.primary, opacity: 0.24, ...shadows.glow },
  errorGlow: { backgroundColor: colors.error, opacity: 0.2 },
  liveOrb: { width: 116, height: 116, borderRadius: 58, padding: 4, alignItems: "center", justifyContent: "center" },
  liveOrbInner: { width: "100%", height: "100%", borderRadius: 54, alignItems: "center", justifyContent: "center", backgroundColor: colors.backgroundDeep, borderWidth: 1, borderColor: "rgba(255,255,255,0.1)" },
  statusTitle: { ...type.h2, color: colors.text, marginTop: spacing.sm, textAlign: "center" },
  transcriptBox: { maxHeight: 164, borderWidth: 1, borderColor: colors.hairline, borderRadius: radii.md, backgroundColor: "rgba(255,255,255,0.025)" },
  transcriptContent: { minHeight: 112, padding: spacing.md },
  transcript: { ...type.body, color: colors.text },
  transcriptCursor: { color: colors.success },
  transcriptPlaceholder: { color: colors.textMuted },
  transcriptError: { ...type.caption, color: colors.error, marginTop: spacing.xs },
  error: { ...type.caption, color: colors.error, marginTop: spacing.sm, textAlign: "center" },
  actions: { marginTop: spacing.md, gap: spacing.sm },
  primaryWrap: { overflow: "hidden", borderRadius: radii.md },
  primaryButton: { minHeight: 52, alignItems: "center", justifyContent: "center" },
  primaryText: { ...type.bodyMedium, color: colors.text },
  secondaryButton: { minHeight: 50, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.xs, borderRadius: radii.md, borderWidth: 1, borderColor: colors.borderStrong, backgroundColor: "rgba(155,92,255,0.08)" },
  secondaryText: { ...type.smallMedium, color: colors.primaryBright },
  pressed: { opacity: 0.7 },
});
