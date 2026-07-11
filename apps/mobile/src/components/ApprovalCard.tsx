import { AudioLines, ListChecks, ShieldCheck, X } from "lucide-react-native";
import { LinearGradient } from "expo-linear-gradient";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { GlassCard } from "@/components/GlassCard";
import { colors, radii, spacing, type } from "@/theme/tokens";

export function ApprovalCard({
  amount,
  currency,
  loading,
  onApprove,
  onReview,
  onCancel,
}: {
  amount: number;
  currency: string;
  loading: boolean;
  onApprove: () => void;
  onReview?: () => void;
  onCancel: () => void;
}) {
  return (
    <GlassCard strong accent="rgba(255,184,77,0.46)" style={styles.card} testID="approval-card">
      <View style={styles.icon}><ShieldCheck color={colors.warning} size={27} /></View>
      <View style={styles.heading}>
        <Text style={styles.eyebrow}>One decision needed</Text>
        <Text style={styles.title}>Approve this exact plan</Text>
        <Text style={styles.body}>Approval is bound to the basket, total and merchant shown below. Confirm all three aloud; checkout continues only through connected commerce providers.</Text>
      </View>
      <View style={styles.amountRow}>
        <Text style={styles.amountLabel}>Total including delivery</Text>
        <Text style={styles.amount}>{amount.toFixed(2)} {currency}</Text>
      </View>
      <Pressable accessibilityRole="button" onPress={onApprove} disabled={loading} style={({ pressed }) => [styles.approveWrap, pressed && styles.pressed]} testID="approve-button">
        <LinearGradient colors={[colors.primary, "#7442EA"]} style={styles.approve}>
          <AudioLines color={colors.text} size={20} />
          <Text style={styles.approveText}>{loading ? "Opening voice…" : "Approve by voice"}</Text>
        </LinearGradient>
      </Pressable>
      {onReview ? (
        <Pressable accessibilityRole="button" onPress={onReview} disabled={loading} style={({ pressed }) => [styles.review, pressed && styles.pressed]} testID="review-button">
          <ListChecks color={colors.primaryBright} size={17} />
          <Text style={styles.reviewText}>Discuss basket by voice</Text>
        </Pressable>
      ) : null}
      <Pressable accessibilityRole="button" onPress={onCancel} disabled={loading} style={({ pressed }) => [styles.cancel, pressed && styles.pressed]}>
        <X color={colors.textMuted} size={17} />
        <Text style={styles.cancelText}>Cancel by voice</Text>
      </Pressable>
    </GlassCard>
  );
}

const styles = StyleSheet.create({
  card: { padding: spacing.lg },
  icon: { width: 48, height: 48, borderRadius: 24, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(255,184,77,0.10)", marginBottom: spacing.md },
  heading: { gap: 4 },
  eyebrow: { ...type.eyebrow, color: colors.warning },
  title: { ...type.h2, color: colors.text },
  body: { ...type.small, color: colors.textSecondary },
  amountRow: { marginTop: spacing.lg, paddingVertical: spacing.md, borderTopWidth: 1, borderBottomWidth: 1, borderColor: colors.hairline, flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  amountLabel: { ...type.small, color: colors.textSecondary },
  amount: { ...type.h3, color: colors.text },
  approveWrap: { overflow: "hidden", borderRadius: radii.md, marginTop: spacing.lg },
  approve: { minHeight: 52, flexDirection: "row", gap: spacing.xs, alignItems: "center", justifyContent: "center" },
  approveText: { ...type.bodyMedium, color: colors.text },
  cancel: { minHeight: 44, flexDirection: "row", gap: spacing.xs, alignItems: "center", justifyContent: "center", marginTop: spacing.xs },
  cancelText: { ...type.smallMedium, color: colors.textMuted },
  review: { minHeight: 44, flexDirection: "row", gap: spacing.xs, alignItems: "center", justifyContent: "center", marginTop: spacing.xs, borderWidth: 1, borderColor: colors.border, borderRadius: radii.md },
  reviewText: { ...type.smallMedium, color: colors.primaryBright },
  pressed: { opacity: 0.72 },
});
