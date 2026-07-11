import { StyleSheet, Text, View } from "react-native";
import { colors, radii, spacing, type } from "@/theme/tokens";
import type { MissionStatus } from "@/types/domain";
import { statusColor, statusLabel } from "@/lib/status";

export function StatusPill({ status, label }: { status: MissionStatus; label?: string }) {
  const color = statusColor[status];
  return (
    <View style={[styles.pill, { backgroundColor: `${color}18` }]}>
      <View style={[styles.dot, { backgroundColor: color }]} />
      <Text style={[styles.label, { color }]}>{label ?? statusLabel[status]}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-start",
    gap: 6,
    borderRadius: radii.round,
    paddingHorizontal: spacing.sm,
    paddingVertical: 6,
  },
  dot: { width: 6, height: 6, borderRadius: 3 },
  label: { ...type.caption, fontWeight: "600", color: colors.text },
});

