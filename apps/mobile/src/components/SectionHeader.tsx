import { ChevronRight } from "lucide-react-native";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { colors, spacing, type } from "@/theme/tokens";

export function SectionHeader({
  title,
  count,
  onPress,
}: {
  title: string;
  count?: number;
  onPress?: () => void;
}) {
  return (
    <Pressable
      disabled={!onPress}
      onPress={onPress}
      style={({ pressed }) => [styles.row, pressed && styles.pressed]}
      accessibilityRole={onPress ? "button" : undefined}
    >
      <Text style={styles.title}>{title}</Text>
      <View style={styles.right}>
        {typeof count === "number" ? <Text style={styles.count}>{count}</Text> : null}
        {onPress ? <ChevronRight size={19} color={colors.textSecondary} /> : null}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    minHeight: 42,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  right: { flexDirection: "row", gap: spacing.sm, alignItems: "center" },
  title: { ...type.eyebrow, color: colors.textSecondary },
  count: { ...type.smallMedium, color: colors.text },
  pressed: { opacity: 0.68 },
});

