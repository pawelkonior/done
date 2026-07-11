import { StyleSheet, View } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { colors, radii } from "@/theme/tokens";

export function ProgressBar({ progress, color = colors.primary }: { progress: number; color?: string }) {
  const value = Math.min(1, Math.max(0.02, progress || 0));
  return (
    <View style={styles.track} accessibilityRole="progressbar" accessibilityValue={{ min: 0, max: 100, now: Math.round(progress * 100) }}>
      <LinearGradient
        colors={[color, color === colors.primary ? colors.primaryBright : color]}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 0 }}
        style={[styles.fill, { width: `${value * 100}%` }]}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  track: {
    height: 5,
    flex: 1,
    borderRadius: radii.round,
    overflow: "hidden",
    backgroundColor: "rgba(111, 92, 181, 0.25)",
  },
  fill: { height: "100%", borderRadius: radii.round },
});

