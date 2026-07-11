import { CreditCard, PiggyBank, ShieldCheck, Sparkles } from "lucide-react-native";
import { StyleSheet, Text, View } from "react-native";
import { GlassCard } from "@/components/GlassCard";
import { colors, radii, spacing, type } from "@/theme/tokens";
import type { MissionMetrics } from "@/types/domain";

export function MetricsGrid({ metrics }: { metrics: MissionMetrics }) {
  const items = [
    { Icon: PiggyBank, label: "Under budget", value: `${metrics.saved.toFixed(0)} PLN`, color: colors.success },
    { Icon: Sparkles, label: "Recovered", value: String(metrics.recovered_failures), color: colors.primaryBright },
    { Icon: CreditCard, label: "Payment tries", value: String(metrics.payment_attempts), color: colors.secondary },
    { Icon: ShieldCheck, label: "Constraints", value: `${Math.round(metrics.constraint_satisfaction * 100)}%`, color: colors.success },
  ];
  return (
    <GlassCard style={styles.card}>
      <Text style={styles.title}>Mission outcome</Text>
      <View style={styles.grid}>
        {items.map(({ Icon, label, value, color }) => (
          <View key={label} style={styles.metric}>
            <View style={[styles.icon, { backgroundColor: `${color}12` }]}><Icon size={19} color={color} /></View>
            <Text style={styles.value}>{value}</Text>
            <Text style={styles.label}>{label}</Text>
          </View>
        ))}
      </View>
    </GlassCard>
  );
}

const styles = StyleSheet.create({
  card: { padding: spacing.lg },
  title: { ...type.h3, color: colors.text, marginBottom: spacing.md },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
  metric: { width: "48%", flexGrow: 1, minHeight: 112, padding: spacing.md, borderRadius: radii.md, backgroundColor: "rgba(255,255,255,0.025)", borderWidth: 1, borderColor: colors.hairline },
  icon: { width: 34, height: 34, borderRadius: 17, alignItems: "center", justifyContent: "center" },
  value: { ...type.h2, color: colors.text, marginTop: spacing.sm },
  label: { ...type.caption, color: colors.textSecondary },
});

