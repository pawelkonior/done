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
import { AudioLines, Check, Keyboard, Mic2, RefreshCw, Sparkles, X } from "lucide-react-native";
import { LinearGradient } from "expo-linear-gradient";
import { getRealtimeClientSecret } from "@/api/client";
import type { CreateMissionResponse } from "@/types/domain";
import {
  parseTranscriptFailure,
  parseTranscriptOrderEvent,
  parseSubmitMissionCall,
  parseTranscriptEvent,
  realtimeActivity,
  realtimeInputActivity,
  realtimeServerError,
} from "@/realtime/events";
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

const statusCopy: Record<LiveStatus, { title: string; subtitle: string }> = {
  connecting: { title: "Connecting…", subtitle: "Creating a secure live voice session" },
  ready: { title: "Mic is live", subtitle: "Start speaking — your words will appear below" },
  listening: { title: "I hear you", subtitle: "Your voice is reaching Realtime now" },
  thinking: { title: "Thinking…", subtitle: "Turning the conversation into a complete mission" },
  speaking: { title: "Speaking", subtitle: "You can interrupt at any time" },
  submitting: { title: "Creating mission…", subtitle: "Deterministic safety rules are validating it" },
  complete: { title: "Mission ready", subtitle: "Open it to review progress and approvals" },
  error: { title: "Live voice unavailable", subtitle: "Local voice and text are still available" },
};

type InputStatus =
  | "connecting"
  | "ready"
  | "hearing"
  | "transcribing"
  | "streaming"
  | "captured"
  | "error";

const inputStatusCopy: Record<InputStatus, { label: string; placeholder: string }> = {
  connecting: { label: "CONNECTING", placeholder: "Connecting the microphone to Realtime…" },
  ready: { label: "MIC LIVE", placeholder: "Start speaking. Your words will appear here." },
  hearing: { label: "VOICE DETECTED", placeholder: "I hear your voice — text will arrive after a short pause…" },
  transcribing: { label: "TRANSCRIBING", placeholder: "Turning this turn into text…" },
  streaming: { label: "LIVE TEXT", placeholder: "Streaming your words…" },
  captured: { label: "CAPTURED", placeholder: "Your last turn was captured." },
  error: { label: "TEXT ERROR", placeholder: "Audio is live, but this turn could not be transcribed." },
};

const errorMessage = (error: unknown) =>
  error instanceof Error ? error.message : "Live voice could not start.";

export function LiveVoiceSheet({
  visible,
  language,
  onClose,
  onUseText,
  onSubmitTranscript,
  onOpenMission,
}: {
  visible: boolean;
  language: string;
  onClose: () => void;
  onUseText: () => void;
  onSubmitTranscript: (transcript: string) => Promise<CreateMissionResponse>;
  onOpenMission: (missionId: string) => void;
}) {
  const [status, setStatus] = useState<LiveStatus>("connecting");
  const [error, setError] = useState<string | null>(null);
  const [transcript, setTranscript] = useState("");
  const [finalTranscript, setFinalTranscript] = useState("");
  const [inputStatus, setInputStatus] = useState<InputStatus>("connecting");
  const [transcriptError, setTranscriptError] = useState<string | null>(null);
  const [missionId, setMissionId] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  const transportRef = useRef<RealtimeTransport | null>(null);
  const onSubmitRef = useRef(onSubmitTranscript);
  const generationRef = useRef(0);
  const submittingRef = useRef(false);
  const missionIdRef = useRef<string | null>(null);
  const handledCallsRef = useRef(new Set<string>());
  const transcriptBufferRef = useRef(new RealtimeTranscriptBuffer());
  const transcriptScrollRef = useRef<ScrollView | null>(null);

  useEffect(() => {
    onSubmitRef.current = onSubmitTranscript;
  }, [onSubmitTranscript]);

  const rebuildTranscript = useCallback(() => {
    setTranscript(transcriptBufferRef.current.previewText());
    setFinalTranscript(transcriptBufferRef.current.finalText());
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
      const result = await onSubmitRef.current(normalized);
      setTranscript((current) => current.trim().length >= 3 ? current : normalized);
      setInputStatus("captured");
      missionIdRef.current = result.mission_id;
      setMissionId(result.mission_id);
      setStatus("complete");
      if (callId) {
        transportRef.current?.send({
          type: "conversation.item.create",
          item: {
            type: "function_call_output",
            call_id: callId,
            output: JSON.stringify({ ok: true, mission_id: result.mission_id }),
          },
        });
      }
      try {
        transportRef.current?.send({
          type: "response.create",
          response: {
            instructions: "Confirm in one short sentence that the mission is ready in Done. "
              + "Do not claim that a purchase or external action has completed.",
          },
        });
      } catch {
        // The mission is already created even if the optional spoken confirmation is interrupted.
      }
    } catch (submitError) {
      if (callId) handledCallsRef.current.delete(callId);
      setStatus("error");
      setError(errorMessage(submitError));
    } finally {
      submittingRef.current = false;
    }
  }, []);

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
      setInputStatus(transcriptEvent.kind === "completed" ? "captured" : "streaming");
      setTranscriptError(null);
      rebuildTranscript();
    }

    const orderEvent = parseTranscriptOrderEvent(event);
    if (orderEvent) transcriptBufferRef.current.register(orderEvent);

    const transcriptFailure = parseTranscriptFailure(event);
    if (transcriptFailure) {
      transcriptBufferRef.current.fail(transcriptFailure);
      setInputStatus("error");
      setTranscriptError("This turn could not be transcribed. The live audio connection is still active.");
      rebuildTranscript();
    }

    const call = parseSubmitMissionCall(event);
    if (call) {
      void submitMission(call.transcript, call.callId);
      return;
    }

    const activity = realtimeActivity(event);
    if (activity && !submittingRef.current && !missionIdRef.current) setStatus(activity);
    const inputActivity = realtimeInputActivity(event);
    if (inputActivity) {
      setInputStatus(inputActivity);
      if (inputActivity === "hearing") setTranscriptError(null);
    }
  }, [rebuildTranscript, submitMission]);

  useEffect(() => {
    if (!visible) return;
    const generation = ++generationRef.current;
    setStatus("connecting");
    setError(null);
    setTranscript("");
    setFinalTranscript("");
    setInputStatus("connecting");
    setTranscriptError(null);
    setMissionId(null);
    missionIdRef.current = null;
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
        const secret = await getRealtimeClientSecret(language);
        if (generation !== generationRef.current) return;
        await transport.connect(secret.value);
        if (generation !== generationRef.current) return;
        transport.send({
          type: "response.create",
          response: {
            instructions: "Greet the user in one short sentence in the configured language and ask what "
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
      transport.disconnect();
      if (transportRef.current === transport) transportRef.current = null;
    };
  }, [handleEvent, language, retryKey, visible]);

  const close = () => {
    transportRef.current?.disconnect();
    onClose();
  };

  const retry = () => {
    transportRef.current?.disconnect();
    setRetryKey((value) => value + 1);
  };

  const copy = statusCopy[status];
  const inputCopy = inputStatusCopy[inputStatus];
  const busy = ["connecting", "thinking", "submitting"].includes(status);
  const inputActive = ["ready", "hearing", "streaming"].includes(inputStatus);

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={close}>
      <View style={styles.backdrop}>
        <Pressable style={StyleSheet.absoluteFill} onPress={close} accessibilityLabel="Close live voice" />
        <View style={styles.sheet} testID="live-voice-sheet">
          <View style={styles.handle} />
          <View style={styles.header}>
            <View style={styles.brandRow}>
              <Sparkles size={16} color={colors.primaryBright} />
              <Text style={styles.eyebrow}>ChatGPT Live 1</Text>
              <View style={styles.modelPill}><Text style={styles.modelText}>Realtime 1.5</Text></View>
            </View>
            <Pressable onPress={close} accessibilityRole="button" accessibilityLabel="Close" style={styles.close}>
              <X size={21} color={colors.textSecondary} />
            </Pressable>
          </View>

          <View style={styles.voiceStage}>
            <View style={[styles.glow, status === "error" && styles.errorGlow]} />
            <LinearGradient
              colors={status === "complete" ? [colors.success, colors.secondary] : status === "error" ? [colors.error, colors.primarySoft] : [colors.primaryBright, colors.secondary]}
              style={styles.liveOrb}
            >
              <View style={styles.liveOrbInner}>
                {busy ? <ActivityIndicator size="large" color={colors.text} /> : status === "complete" ? <Check size={42} color={colors.text} /> : <AudioLines size={43} color={colors.text} />}
              </View>
            </LinearGradient>
            <Text accessibilityLiveRegion="polite" style={styles.statusTitle}>{copy.title}</Text>
            <Text style={styles.statusSubtitle}>{copy.subtitle}</Text>
          </View>

          <ScrollView
            ref={transcriptScrollRef}
            style={styles.transcriptBox}
            contentContainerStyle={styles.transcriptContent}
            onContentSizeChange={() => transcriptScrollRef.current?.scrollToEnd({ animated: true })}
            testID="live-transcript-preview"
          >
            <View style={styles.transcriptHeader}>
              <Text style={styles.transcriptLabel}>{missionId ? "What I heard" : "What I hear"}</Text>
              <View style={[
                styles.inputStatusPill,
                inputActive && styles.inputStatusPillActive,
                inputStatus === "error" && styles.inputStatusPillError,
              ]} testID="live-input-status">
                <View style={[
                  styles.inputStatusDot,
                  inputActive && styles.inputStatusDotActive,
                  inputStatus === "transcribing" && styles.inputStatusDotPending,
                  inputStatus === "error" && styles.inputStatusDotError,
                ]} />
                <Text style={[
                  styles.inputStatusText,
                  inputActive && styles.inputStatusTextActive,
                  inputStatus === "error" && styles.inputStatusTextError,
                ]}>{inputCopy.label}</Text>
              </View>
            </View>
            <Text
              accessibilityLiveRegion="polite"
              style={[styles.transcript, !transcript && styles.transcriptPlaceholder]}
              testID="live-transcript-text"
            >
              {transcript || inputCopy.placeholder}
              {transcript && inputStatus === "streaming" ? <Text style={styles.transcriptCursor}> ▋</Text> : null}
            </Text>
            {transcriptError ? <Text accessibilityRole="alert" style={styles.transcriptError}>{transcriptError}</Text> : null}
          </ScrollView>

          {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}

          <View style={styles.actions}>
            {missionId ? (
              <Pressable
                onPress={() => { close(); onOpenMission(missionId); }}
                accessibilityRole="button"
                style={({ pressed }) => [styles.primaryWrap, pressed && styles.pressed]}
                testID="open-live-mission"
              >
                <LinearGradient colors={[colors.primary, "#7442EA"]} style={styles.primaryButton}>
                  <Text style={styles.primaryText}>Open mission</Text>
                </LinearGradient>
              </Pressable>
            ) : status === "error" ? (
              <Pressable onPress={retry} accessibilityRole="button" style={({ pressed }) => [styles.secondaryButton, pressed && styles.pressed]}>
                <RefreshCw size={17} color={colors.primaryBright} />
                <Text style={styles.secondaryText}>Try live again</Text>
              </Pressable>
            ) : finalTranscript.length >= 3 ? (
              <Pressable
                onPress={() => void submitMission(finalTranscript)}
                disabled={submittingRef.current}
                accessibilityRole="button"
                style={({ pressed }) => [styles.secondaryButton, pressed && styles.pressed]}
                testID="submit-live-transcript"
              >
                <Check size={17} color={colors.primaryBright} />
                <Text style={styles.secondaryText}>Create mission now</Text>
              </Pressable>
            ) : null}
            {!missionId ? (
              <View style={styles.fallbackRow}>
                <Pressable onPress={close} style={({ pressed }) => [styles.fallbackButton, pressed && styles.pressed]}>
                  <Mic2 size={16} color={colors.textSecondary} />
                  <Text style={styles.fallbackText}>Use local voice</Text>
                </Pressable>
                <Pressable onPress={() => { close(); onUseText(); }} style={({ pressed }) => [styles.fallbackButton, pressed && styles.pressed]}>
                  <Keyboard size={16} color={colors.textSecondary} />
                  <Text style={styles.fallbackText}>Type instead</Text>
                </Pressable>
              </View>
            ) : null}
          </View>

          <Text style={styles.privacy}>Audio streams directly to OpenAI with a short-lived token. The standard API key stays on your server.</Text>
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
  modelPill: { borderRadius: radii.round, paddingHorizontal: spacing.xs, paddingVertical: 3, borderWidth: 1, borderColor: colors.border, backgroundColor: "rgba(155,92,255,0.09)" },
  modelText: { fontSize: 10, lineHeight: 14, fontWeight: "600", color: colors.primaryBright },
  close: { width: 42, height: 42, borderRadius: 21, backgroundColor: "rgba(255,255,255,0.04)", alignItems: "center", justifyContent: "center" },
  voiceStage: { alignItems: "center", paddingTop: spacing.xl, paddingBottom: spacing.lg },
  glow: { position: "absolute", top: 30, width: 130, height: 130, borderRadius: 65, backgroundColor: colors.primary, opacity: 0.24, ...shadows.glow },
  errorGlow: { backgroundColor: colors.error, opacity: 0.2 },
  liveOrb: { width: 116, height: 116, borderRadius: 58, padding: 4, alignItems: "center", justifyContent: "center" },
  liveOrbInner: { width: "100%", height: "100%", borderRadius: 54, alignItems: "center", justifyContent: "center", backgroundColor: colors.backgroundDeep, borderWidth: 1, borderColor: "rgba(255,255,255,0.1)" },
  statusTitle: { ...type.h2, color: colors.text, marginTop: spacing.lg, textAlign: "center" },
  statusSubtitle: { ...type.small, color: colors.textSecondary, marginTop: spacing.xs, textAlign: "center" },
  transcriptBox: { maxHeight: 164, borderWidth: 1, borderColor: colors.hairline, borderRadius: radii.md, backgroundColor: "rgba(255,255,255,0.025)" },
  transcriptContent: { minHeight: 112, padding: spacing.md },
  transcriptHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm, marginBottom: spacing.sm },
  transcriptLabel: { ...type.eyebrow, color: colors.textMuted },
  inputStatusPill: { flexDirection: "row", alignItems: "center", gap: 5, borderRadius: radii.round, borderWidth: 1, borderColor: colors.hairline, backgroundColor: "rgba(255,255,255,0.035)", paddingHorizontal: 8, paddingVertical: 4 },
  inputStatusPillActive: { borderColor: "rgba(72,214,106,0.3)", backgroundColor: "rgba(72,214,106,0.08)" },
  inputStatusPillError: { borderColor: "rgba(255,93,115,0.3)", backgroundColor: "rgba(255,93,115,0.07)" },
  inputStatusDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.textMuted },
  inputStatusDotActive: { backgroundColor: colors.success },
  inputStatusDotPending: { backgroundColor: colors.warning },
  inputStatusDotError: { backgroundColor: colors.error },
  inputStatusText: { fontSize: 9, lineHeight: 12, fontWeight: "700", letterSpacing: 0.5, color: colors.textMuted },
  inputStatusTextActive: { color: colors.success },
  inputStatusTextError: { color: colors.error },
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
  fallbackRow: { flexDirection: "row", gap: spacing.sm },
  fallbackButton: { minHeight: 44, flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, borderRadius: radii.md, borderWidth: 1, borderColor: colors.hairline },
  fallbackText: { ...type.caption, color: colors.textSecondary },
  privacy: { ...type.caption, color: colors.textMuted, textAlign: "center", marginTop: spacing.md },
  pressed: { opacity: 0.7 },
});
