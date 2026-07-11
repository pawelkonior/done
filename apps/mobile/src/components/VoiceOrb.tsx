import { useEffect, useRef } from "react";
import { AudioLines, LoaderCircle, Sparkles } from "lucide-react-native";
import {
  Animated,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { colors, radii, shadows, spacing, type } from "@/theme/tokens";
import { useVoiceStore } from "@/store/voice";
import { useVoiceCapture } from "@/hooks/useVoiceCapture";

export function VoiceOrb({
  onTap,
  onType,
  onRecorded,
}: {
  onTap: () => void;
  onType?: () => void;
  onRecorded: (audioUri: string | null) => Promise<void> | void;
}) {
  const { isRecording, isSubmitting, recordingDuration, error, setError } = useVoiceStore();
  const { start, stop } = useVoiceCapture();
  const pulse = useRef(new Animated.Value(0)).current;
  const holdTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const longPress = useRef(false);
  const starting = useRef(false);
  const recordingStarted = useRef(false);

  useEffect(() => {
    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 1, duration: isRecording ? 520 : 1800, useNativeDriver: Platform.OS !== "web" }),
        Animated.timing(pulse, { toValue: 0, duration: isRecording ? 520 : 1800, useNativeDriver: Platform.OS !== "web" }),
      ]),
    );
    animation.start();
    return () => animation.stop();
  }, [isRecording, pulse]);

  const pressIn = () => {
    longPress.current = false;
    recordingStarted.current = false;
    setError(null);
    holdTimer.current = setTimeout(async () => {
      longPress.current = true;
      starting.current = true;
      recordingStarted.current = await start();
      starting.current = false;
    }, 360);
  };

  const pressOut = async () => {
    if (holdTimer.current) clearTimeout(holdTimer.current);
    holdTimer.current = null;
    if (!longPress.current) return;
    while (starting.current) {
      await new Promise((resolve) => setTimeout(resolve, 30));
    }
    if (!recordingStarted.current) return;
    const uri = await stop();
    if (!uri) return;
    await onRecorded(uri);
  };

  const orbScale = pulse.interpolate({ inputRange: [0, 1], outputRange: [1, isRecording ? 1.08 : 1.035] });
  const glowOpacity = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.32, isRecording ? 0.82 : 0.56] });

  return (
    <View style={styles.wrapper}>
      <Pressable
        onPress={() => { if (!longPress.current) onTap(); }}
        onPressIn={pressIn}
        onPressOut={() => void pressOut()}
        disabled={isSubmitting}
        accessibilityRole="button"
        accessibilityLabel="Tap for GPT Realtime 2 with live captions, or hold to record for GPT-4o Transcribe"
        testID="voice-orb"
      >
        <Animated.View style={[styles.glow, { opacity: glowOpacity, transform: [{ scale: orbScale }] }]} />
        <Animated.View style={{ transform: [{ scale: orbScale }] }}>
          <LinearGradient
            colors={isRecording ? [colors.error, colors.primary] : [colors.primaryBright, colors.secondary]}
            start={{ x: 0, y: 0 }}
            end={{ x: 1, y: 1 }}
            style={styles.ringOuter}
          >
            <View style={styles.ringGap}>
              <LinearGradient colors={["#17182B", "#0C0E1D"]} style={styles.orbInner}>
                {isSubmitting ? (
                  <LoaderCircle color={colors.text} size={43} strokeWidth={1.8} />
                ) : (
                  <AudioLines color={colors.text} size={47} strokeWidth={2.2} />
                )}
              </LinearGradient>
            </View>
          </LinearGradient>
        </Animated.View>
      </Pressable>
      <Text style={styles.title}>
        {isSubmitting ? "Understanding…" : isRecording ? "Recording for OpenAI STT…" : "Tap for live transcript"}
      </Text>
      {isRecording ? (
        <>
          <Text style={styles.subtitle}>{recordingDuration}s · release when done</Text>
          <Text style={styles.sttHint}>Release to transcribe with GPT-4o Transcribe</Text>
        </>
      ) : (
        <>
          <View style={styles.liveLabel}><Sparkles size={13} color={colors.primaryBright} /><Text style={styles.liveText}>GPT Realtime 2 · realtime voice + captions</Text></View>
          <Text style={styles.sttHint}>Hold for GPT-4o Transcribe · text after release</Text>
          {onType ? (
            <Pressable onPress={() => { setError(null); onType(); }} testID="open-mission-composer" accessibilityRole="button">
              <Text style={styles.subtitle}>or type a new mission</Text>
            </Pressable>
          ) : null}
        </>
      )}
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: { alignItems: "center", paddingVertical: spacing.lg },
  glow: {
    position: "absolute",
    top: 8,
    width: 188,
    height: 188,
    borderRadius: 94,
    backgroundColor: colors.primary,
    ...shadows.glow,
  },
  ringOuter: {
    width: 176,
    height: 176,
    borderRadius: 88,
    padding: 4,
    alignItems: "center",
    justifyContent: "center",
  },
  ringGap: {
    width: "100%",
    height: "100%",
    padding: 7,
    borderRadius: radii.round,
    backgroundColor: "rgba(7,9,20,0.96)",
  },
  orbInner: {
    flex: 1,
    borderRadius: radii.round,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.08)",
  },
  title: { ...type.h2, color: colors.text, marginTop: spacing.xl },
  subtitle: { ...type.body, color: colors.textSecondary, marginTop: spacing.xs },
  liveLabel: { flexDirection: "row", alignItems: "center", gap: 5, marginTop: spacing.xs },
  liveText: { ...type.caption, color: colors.primaryBright },
  sttHint: { ...type.caption, color: colors.textMuted, marginTop: 4, textAlign: "center" },
  error: { ...type.caption, color: colors.error, marginTop: spacing.sm, textAlign: "center", maxWidth: 300 },
});
