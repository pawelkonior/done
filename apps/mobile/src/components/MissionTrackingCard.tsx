import { PackageCheck, RefreshCw, Truck } from "lucide-react-native";
import { StyleSheet, Text, View } from "react-native";
import { GlassCard } from "@/components/GlassCard";
import { StatusPill } from "@/components/StatusPill";
import { colors, radii, spacing, type } from "@/theme/tokens";
import type { MissionEvent, MissionOrder, MissionStatus } from "@/types/domain";

function humanize(value: string) {
  return value.replaceAll("_", " ").replace(/(^|\s)\S/g, (letter) => letter.toUpperCase());
}

function isRecovery(event: MissionEvent) {
  return event.type.includes("recover") || event.type.includes("replac") || event.type.includes("rerout") || event.type.includes("retry");
}

function formatDelivery(value: string) {
  const date = new Date(value);
  if (!value || Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en", { weekday: "short", hour: "numeric", minute: "2-digit" }).format(date);
}

export function MissionTrackingCard({
  missionStatus,
  order,
  events,
  recovered,
}: {
  missionStatus: MissionStatus;
  order?: MissionOrder | null;
  events: MissionEvent[];
  recovered: number;
}) {
  const recoveryEvents = events.filter(isRecovery);
  return (
    <GlassCard style={styles.card} testID="mission-tracking-card">
      <View style={styles.header}>
        <View style={styles.icon}><Truck size={22} color={colors.primaryBright} /></View>
        <View style={styles.heading}>
          <Text style={styles.title}>Mission tracking</Text>
          <Text style={styles.subtitle}>Current status and the important moments</Text>
        </View>
      </View>

      <View style={styles.statuses}>
        <View style={styles.statusRow}>
          <View style={styles.statusLabel}><RefreshCw size={16} color={colors.primaryBright} /><Text style={styles.label}>Mission</Text></View>
          <StatusPill status={missionStatus} />
        </View>
        {order ? (
          <View style={styles.statusRow}>
            <View style={styles.statusLabel}><PackageCheck size={16} color={colors.success} /><Text style={styles.label}>Order</Text></View>
            <View style={styles.orderStatus}><View style={styles.orderDot} /><Text style={styles.orderStatusText}>{humanize(order.status)}</Text></View>
          </View>
        ) : null}
      </View>

      {order ? (
        <View style={styles.orderDetails}>
          <View style={styles.orderFact}><Text style={styles.factLabel}>Confirmation</Text><Text style={styles.factValue}>{order.confirmation_code || order.id}</Text></View>
          <View style={styles.orderFact}><Text style={styles.factLabel}>Expected delivery</Text><Text style={styles.factValue}>{formatDelivery(order.delivery_at)}</Text></View>
        </View>
      ) : null}

      {recoveryEvents.length || recovered ? (
        <View style={styles.recovery}>
          <View style={styles.recoveryIcon}><RefreshCw size={16} color={colors.warning} /></View>
          <View style={styles.recoveryText}>
            <Text style={styles.recoveryTitle}>{recovered || recoveryEvents.length} recovery event{(recovered || recoveryEvents.length) === 1 ? "" : "s"} handled</Text>
            <Text style={styles.recoverySubtitle}>Done kept the mission constraints while repairing the issue.</Text>
          </View>
        </View>
      ) : null}
    </GlassCard>
  );
}

const styles = StyleSheet.create({
  card: { padding: spacing.lg },
  header: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  icon: { width: 44, height: 44, borderRadius: radii.md, backgroundColor: "rgba(155,92,255,0.10)", alignItems: "center", justifyContent: "center" },
  heading: { flex: 1 },
  title: { ...type.h3, color: colors.text },
  subtitle: { ...type.caption, color: colors.textSecondary, marginTop: 2 },
  statuses: { marginTop: spacing.lg, gap: spacing.xs, borderTopWidth: 1, borderTopColor: colors.hairline, paddingTop: spacing.sm },
  statusRow: { minHeight: 42, flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  statusLabel: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  label: { ...type.small, color: colors.textSecondary },
  orderStatus: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: spacing.sm, paddingVertical: 6, borderRadius: radii.round, backgroundColor: "rgba(72,214,106,0.10)" },
  orderDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.success },
  orderStatusText: { ...type.caption, color: colors.success, textTransform: "capitalize" },
  orderDetails: { flexDirection: "row", gap: spacing.xs, marginTop: spacing.xs },
  orderFact: { flex: 1, padding: spacing.sm, borderRadius: radii.md, backgroundColor: "rgba(255,255,255,0.025)" },
  factLabel: { ...type.caption, color: colors.textMuted },
  factValue: { ...type.smallMedium, color: colors.text, marginTop: 2 },
  recovery: { flexDirection: "row", alignItems: "center", gap: spacing.sm, padding: spacing.sm, marginTop: spacing.md, borderRadius: radii.md, borderWidth: 1, borderColor: "rgba(255,184,77,0.25)", backgroundColor: "rgba(255,184,77,0.07)" },
  recoveryIcon: { width: 32, height: 32, borderRadius: 16, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(255,184,77,0.12)" },
  recoveryText: { flex: 1 },
  recoveryTitle: { ...type.smallMedium, color: colors.text },
  recoverySubtitle: { ...type.caption, color: colors.textSecondary, marginTop: 2 },
});
