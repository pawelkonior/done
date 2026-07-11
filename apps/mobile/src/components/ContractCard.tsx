import { CalendarClock, ShieldCheck, UsersRound, WalletCards } from "lucide-react-native";
import { StyleSheet, Text, View } from "react-native";
import { GlassCard } from "@/components/GlassCard";
import { colors, radii, spacing, type } from "@/theme/tokens";
import type { MissionContract } from "@/types/domain";

export function ContractCard({ contract }: { contract: MissionContract }) {
  const facts = [
    { icon: UsersRound, label: "People", value: String(contract.participants || 10) },
    { icon: WalletCards, label: "Budget", value: `${contract.budget} ${contract.currency}` },
    { icon: CalendarClock, label: "Deadline", value: contract.deadline },
  ];
  return (
    <GlassCard style={styles.card}>
      <View style={styles.header}>
        <Text style={styles.title}>Mission contract</Text>
        <View style={styles.version}><Text style={styles.versionText}>v{contract.version}</Text></View>
      </View>
      <Text style={styles.goal}>{contract.goal}</Text>
      <View style={styles.facts}>
        {facts.map(({ icon: Icon, label, value }) => (
          <View key={label} style={styles.fact}>
            <Icon color={colors.primaryBright} size={17} />
            <Text style={styles.factLabel}>{label}</Text>
            <Text numberOfLines={1} style={styles.factValue}>{value}</Text>
          </View>
        ))}
      </View>
      <View style={styles.constraints}>
        <View style={styles.constraintTitleRow}>
          <ShieldCheck color={colors.success} size={18} />
          <Text style={styles.constraintTitle}>Locked constraints</Text>
        </View>
        <View style={styles.chips}>
          {contract.hard_constraints.map((constraint) => (
            <View key={constraint} style={styles.chip}><Text style={styles.chipText}>{constraint}</Text></View>
          ))}
        </View>
      </View>
      <View style={styles.confidenceTrack}><View style={[styles.confidenceFill, { width: `${Math.round(contract.confidence * 100)}%` }]} /></View>
      <Text style={styles.confidence}>{Math.round(contract.confidence * 100)}% interpretation confidence</Text>
    </GlassCard>
  );
}

const styles = StyleSheet.create({
  card: { padding: spacing.lg },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  title: { ...type.h3, color: colors.text },
  version: { paddingVertical: 4, paddingHorizontal: 9, borderRadius: radii.round, backgroundColor: "rgba(155,92,255,0.12)" },
  versionText: { ...type.caption, color: colors.primaryBright },
  goal: { ...type.body, color: colors.textSecondary, marginTop: spacing.xs },
  facts: { flexDirection: "row", gap: spacing.xs, marginTop: spacing.lg },
  fact: { flex: 1, minWidth: 0, padding: spacing.sm, borderRadius: radii.md, backgroundColor: "rgba(255,255,255,0.025)" },
  factLabel: { ...type.caption, color: colors.textMuted, marginTop: 5 },
  factValue: { ...type.smallMedium, color: colors.text, marginTop: 1 },
  constraints: { marginTop: spacing.lg },
  constraintTitleRow: { flexDirection: "row", gap: spacing.xs, alignItems: "center" },
  constraintTitle: { ...type.smallMedium, color: colors.text },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, marginTop: spacing.sm },
  chip: { paddingVertical: 6, paddingHorizontal: 10, borderRadius: radii.round, borderWidth: 1, borderColor: "rgba(72,214,106,0.20)", backgroundColor: "rgba(72,214,106,0.06)" },
  chipText: { ...type.caption, color: colors.success },
  confidenceTrack: { height: 3, borderRadius: 2, backgroundColor: "rgba(255,255,255,0.05)", marginTop: spacing.lg, overflow: "hidden" },
  confidenceFill: { height: "100%", backgroundColor: colors.primary },
  confidence: { ...type.caption, color: colors.textMuted, marginTop: 5 },
});

