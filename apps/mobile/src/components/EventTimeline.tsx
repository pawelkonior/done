import { AlertTriangle, Check, CircleDot, RefreshCw, Sparkles } from "lucide-react-native";
import { StyleSheet, Text, View } from "react-native";
import { GlassCard } from "@/components/GlassCard";
import { colors, radii, spacing, type } from "@/theme/tokens";
import type { MissionEvent } from "@/types/domain";

const severityColor = {
  info: colors.secondary,
  success: colors.success,
  warning: colors.warning,
  error: colors.error,
};

function iconFor(event: MissionEvent) {
  if (event.type.includes("recover") || event.type.includes("replac") || event.type.includes("rerout")) return RefreshCw;
  if (event.severity === "success") return Check;
  if (event.severity === "warning" || event.severity === "error") return AlertTriangle;
  if (event.type.includes("approval")) return Sparkles;
  return CircleDot;
}

function isRecovery(event: MissionEvent) {
  return event.type.includes("recover") || event.type.includes("replac") || event.type.includes("rerout") || event.type.includes("retry");
}

export function EventTimeline({ events }: { events: MissionEvent[] }) {
  const ordered = [...events].sort((a, b) => (a.sequence ?? 0) - (b.sequence ?? 0));
  return (
    <GlassCard style={styles.card}>
      <Text style={styles.title}>Mission & order timeline</Text>
      <Text style={styles.subtitle}>Every decision, retry and recovery is recorded.</Text>
      <View style={styles.events}>
        {ordered.map((event, index) => {
          const Icon = iconFor(event);
          const color = severityColor[event.severity] ?? colors.secondary;
          return (
            <View key={event.id} style={styles.event}>
              <View style={styles.rail}>
                <View style={[styles.icon, { backgroundColor: `${color}18`, borderColor: `${color}50` }]}><Icon size={14} color={color} /></View>
                {index < ordered.length - 1 ? <View style={styles.line} /> : null}
              </View>
              <View style={styles.content}>
                <View style={styles.heading}>
                  <Text style={styles.eventTitle}>{event.title}</Text>
                  {isRecovery(event) ? <Text style={styles.recoveryBadge}>Recovery</Text> : null}
                  <Text style={styles.time}>{formatTime(event.created_at)}</Text>
                </View>
                <Text style={styles.description}>{event.description}</Text>
              </View>
            </View>
          );
        })}
      </View>
    </GlassCard>
  );
}

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("en", { hour: "numeric", minute: "2-digit", second: "2-digit" }).format(date);
}

const styles = StyleSheet.create({
  card: { padding: spacing.lg },
  title: { ...type.h3, color: colors.text },
  subtitle: { ...type.small, color: colors.textSecondary, marginTop: 2 },
  events: { marginTop: spacing.lg },
  event: { flexDirection: "row", minHeight: 76 },
  rail: { width: 36, alignItems: "center" },
  icon: { width: 28, height: 28, borderRadius: 14, borderWidth: 1, alignItems: "center", justifyContent: "center", zIndex: 2 },
  line: { position: "absolute", width: 1, top: 27, bottom: -2, backgroundColor: colors.hairline },
  content: { flex: 1, paddingLeft: spacing.xs, paddingBottom: spacing.lg },
  heading: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.xs },
  eventTitle: { ...type.smallMedium, color: colors.text, flex: 1 },
  time: { ...type.caption, color: colors.textMuted },
  description: { ...type.caption, color: colors.textSecondary, marginTop: 3 },
  recoveryBadge: { ...type.caption, color: colors.warning, backgroundColor: "rgba(255,184,77,0.10)", borderRadius: radii.round, paddingHorizontal: 6, paddingVertical: 2 },
});

