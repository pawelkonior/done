import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import { AlertCircle, Inbox } from "lucide-react-native";
import { GlassCard } from "@/components/GlassCard";
import { colors, radii, spacing, type } from "@/theme/tokens";

export function ScreenState({
  loading = false,
  title,
  message,
  onRetry,
}: {
  loading?: boolean;
  title: string;
  message?: string;
  onRetry?: () => void;
}) {
  return (
    <GlassCard style={styles.card}>
      {loading ? <ActivityIndicator color={colors.primaryBright} /> : <Inbox size={27} color={colors.primaryBright} />}
      <Text style={styles.title}>{title}</Text>
      {message ? <Text style={styles.message}>{message}</Text> : null}
      {onRetry ? (
        <Pressable accessibilityRole="button" onPress={onRetry} style={({ pressed }) => [styles.retry, pressed && styles.pressed]}>
          <Text style={styles.retryText}>Try again</Text>
        </Pressable>
      ) : null}
    </GlassCard>
  );
}

export function InlineError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <View style={styles.error}>
      <AlertCircle size={16} color={colors.error} />
      <Text accessibilityRole="alert" style={styles.errorText}>{message}</Text>
      {onRetry ? <Pressable onPress={onRetry}><Text style={styles.inlineRetry}>Retry</Text></Pressable> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { minHeight: 150, padding: spacing.lg, alignItems: "center", justifyContent: "center", gap: spacing.xs },
  title: { ...type.bodyMedium, color: colors.text, textAlign: "center" },
  message: { ...type.small, color: colors.textSecondary, textAlign: "center" },
  retry: { minHeight: 42, paddingHorizontal: spacing.md, marginTop: spacing.xs, borderRadius: radii.md, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  retryText: { ...type.smallMedium, color: colors.primaryBright },
  pressed: { opacity: 0.7 },
  error: { minHeight: 44, flexDirection: "row", alignItems: "center", gap: spacing.xs, padding: spacing.sm, borderRadius: radii.md, borderWidth: 1, borderColor: "rgba(255,93,115,0.24)", backgroundColor: "rgba(255,93,115,0.07)" },
  errorText: { ...type.caption, color: colors.error, flex: 1 },
  inlineRetry: { ...type.caption, color: colors.primaryBright },
});
