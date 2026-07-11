import { useEffect, useRef } from "react";
import { AudioLines, LoaderCircle } from "lucide-react-native";
import {
  Animated,
  Easing,
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
  onRecorded,
}: {
  onTap: () => void;
  onRecorded: (audioUri: string | null) => Promise<void> | void;
}) {
  const { isRecording, isSubmitting, error, setError } = useVoiceStore();
  const { start, stop } = useVoiceCapture();
  const pulse = useRef(new Animated.Value(0)).current;
  const holdTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const longPress = useRef(false);
  const starting = useRef(false);
  const recordingStarted = useRef(false);

  useEffect(() => {
    const useNativeDriver = Platform.OS !== "web";
    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 1, duration: 120, easing: Easing.out(Easing.cubic), useNativeDriver }),
        Animated.timing(pulse, { toValue: 0, duration: 170, easing: Easing.inOut(Easing.quad), useNativeDriver }),
        Animated.delay(90),
        Animated.timing(pulse, { toValue: 0.72, duration: 105, easing: Easing.out(Easing.cubic), useNativeDriver }),
        Animated.timing(pulse, { toValue: 0, duration: 185, easing: Easing.inOut(Easing.quad), useNativeDriver }),
        Animated.delay(isRecording ? 420 : 1050),
      ]),
    );
    animation.start();
    return () => {
      animation.stop();
      pulse.stopAnimation();
      pulse.setValue(0);
    };
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

  const orbScale = pulse.interpolate({ inputRange: [0, 1], outputRange: [1, isRecording ? 1.065 : 1.04] });
  const haloScale = pulse.interpolate({ inputRange: [0, 1], outputRange: [1, isRecording ? 1.2 : 1.14] });
  const haloOpacity = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.34, 0.04] });
  const glowScale = pulse.interpolate({ inputRange: [0, 1], outputRange: [1, isRecording ? 1.14 : 1.09] });
  const glowOpacity = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.28, isRecording ? 0.68 : 0.48] });

  return (
    <View style={styles.wrapper}>
      <View style={styles.stage}>
        <Animated.View pointerEvents="none" style={[styles.halo, { opacity: haloOpacity, transform: [{ scale: haloScale }] }]} />
        <Animated.View pointerEvents="none" style={[styles.glow, { opacity: glowOpacity, transform: [{ scale: glowScale }] }]} />
        <Pressable
          onPress={() => { if (!longPress.current) onTap(); }}
          onPressIn={pressIn}
          onPressOut={() => void pressOut()}
          disabled={isSubmitting}
          style={styles.orbButton}
          accessibilityRole="button"
          accessibilityLabel="Start a voice mission"
          testID="voice-orb"
        >
          <Animated.View style={[styles.orbBeat, { transform: [{ scale: orbScale }] }]}>
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
      </View>
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: { alignItems: "center", paddingVertical: spacing.xl },
  stage: { width: 220, height: 220, alignItems: "center", justifyContent: "center" },
  halo: {
    position: "absolute",
    top: 10,
    left: 10,
    width: 200,
    height: 200,
    borderRadius: 100,
    borderWidth: 1.5,
    borderColor: colors.primaryBright,
  },
  glow: {
    position: "absolute",
    top: 18,
    left: 18,
    width: 184,
    height: 184,
    borderRadius: 92,
    backgroundColor: colors.primary,
    ...shadows.glow,
  },
  orbButton: { width: 176, height: 176, alignItems: "center", justifyContent: "center" },
  orbBeat: { width: 176, height: 176 },
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
  error: { ...type.caption, color: colors.error, marginTop: spacing.sm, textAlign: "center", maxWidth: 300 },
});
