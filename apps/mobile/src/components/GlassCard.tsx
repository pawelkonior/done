import type { PropsWithChildren } from "react";
import { StyleSheet, View, type ViewProps } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { colors, radii, shadows } from "@/theme/tokens";

interface GlassCardProps extends PropsWithChildren, ViewProps {
  strong?: boolean;
  accent?: string;
}

export function GlassCard({ children, strong, accent, style, ...props }: GlassCardProps) {
  return (
    <LinearGradient
      colors={
        strong
          ? ["rgba(24, 25, 43, 0.98)", "rgba(10, 12, 25, 0.98)"]
          : ["rgba(20, 22, 38, 0.92)", "rgba(9, 11, 23, 0.94)"]
      }
      start={{ x: 0, y: 0 }}
      end={{ x: 1, y: 1 }}
      style={[
        styles.card,
        accent ? { borderColor: accent } : undefined,
        style,
      ]}
      {...props}
    >
      <View pointerEvents="none" style={styles.highlight} />
      {children}
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  card: {
    position: "relative",
    overflow: "hidden",
    borderWidth: 1,
    borderColor: colors.hairline,
    borderRadius: radii.lg,
    ...shadows.card,
  },
  highlight: {
    position: "absolute",
    top: 0,
    left: 28,
    right: 28,
    height: 1,
    backgroundColor: "rgba(255,255,255,0.06)",
  },
});

