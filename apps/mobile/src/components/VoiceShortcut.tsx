import { AudioLines, ChevronRight } from "lucide-react-native";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { colors, radii, spacing, type } from "@/theme/tokens";

export function VoiceShortcut({ onPress }: { onPress: () => void }) {
  return (
    <Pressable accessibilityRole="button" onPress={onPress} style={({ pressed }) => [pressed && styles.pressed]}>
      <LinearGradient colors={["rgba(99,56,183,0.22)", "rgba(11,13,28,0.96)"]} style={styles.card}>
        <LinearGradient colors={[colors.primary, "#5D39C7"]} style={styles.icon}>
          <AudioLines size={28} color={colors.text} />
        </LinearGradient>
        <View style={styles.textWrap}>
          <Text style={styles.title}>Add a mission</Text>
          <Text style={styles.subtitle}>Type a new request for Done</Text>
        </View>
        <ChevronRight size={22} color={colors.primaryBright} />
      </LinearGradient>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  pressed: { opacity: 0.72 },
  card: { borderWidth: 1, borderColor: colors.borderStrong, borderRadius: radii.lg, padding: spacing.md, flexDirection: "row", alignItems: "center", gap: spacing.md },
  icon: { width: 54, height: 54, borderRadius: 27, alignItems: "center", justifyContent: "center" },
  textWrap: { flex: 1 },
  title: { ...type.bodyMedium, color: colors.primaryBright },
  subtitle: { ...type.small, color: colors.textSecondary, marginTop: 2 },
});
