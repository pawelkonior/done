import { ChevronRight, Clock3, Sparkles } from "lucide-react-native";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { GlassCard } from "@/components/GlassCard";
import { IconTile, accentColors } from "@/components/IconTile";
import { ProgressBar } from "@/components/ProgressBar";
import { StatusPill } from "@/components/StatusPill";
import { colors, radii, spacing, type } from "@/theme/tokens";
import type { MissionSummary } from "@/types/domain";

export function MissionCard({
  mission,
  onPress,
  completed = false,
  compact = false,
}: {
  mission: MissionSummary;
  onPress?: () => void;
  completed?: boolean;
  compact?: boolean;
}) {
  const accent = accentColors[mission.accent ?? "violet"];
  const time = mission.completed_at
    ? new Intl.DateTimeFormat("en", { hour: "numeric", minute: "2-digit" }).format(
        new Date(mission.completed_at),
      )
    : null;

  return (
    <Pressable accessibilityRole={onPress ? "button" : undefined} onPress={onPress} disabled={!onPress} style={({ pressed }) => [pressed && styles.pressed]}>
      <GlassCard style={[styles.card, compact && styles.cardCompact]}>
        <IconTile icon={mission.icon} accent={mission.accent} size={compact ? 54 : 60} />
        <View style={styles.content}>
          <View style={styles.titleRow}>
            <Text numberOfLines={1} style={styles.title}>{mission.title}</Text>
            {!completed ? <StatusPill status={mission.status} /> : null}
          </View>
          <Text numberOfLines={1} style={styles.subtitle}>{mission.subtitle}</Text>
          {completed ? (
            <>
              <View style={styles.completeMeta}>
                <StatusPill status="completed" />
                {time ? <Text style={styles.time}>•  {time}</Text> : null}
              </View>
              <View style={styles.insight}>
                <Sparkles size={16} color={colors.primaryBright} />
                <Text style={styles.insightText}>{mission.latest_update}</Text>
              </View>
            </>
          ) : (
            <>
              <View style={styles.progressRow}>
                <ProgressBar progress={mission.progress} color={accent} />
                <Text style={[styles.progressLabel, { color: accent }]}> 
                  {mission.current_step} of {mission.total_steps}
                </Text>
              </View>
              {!compact ? (
                <View style={styles.latestRow}>
                  <Clock3 size={15} color={colors.textMuted} />
                  <Text numberOfLines={1} style={styles.latest}>{mission.latest_update}</Text>
                </View>
              ) : null}
            </>
          )}
        </View>
        <ChevronRight size={22} color={colors.textMuted} />
      </GlassCard>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  pressed: { opacity: 0.75, transform: [{ scale: 0.992 }] },
  card: {
    padding: spacing.md,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
  },
  cardCompact: { paddingVertical: spacing.md },
  content: { flex: 1, minWidth: 0 },
  titleRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  title: { ...type.h3, color: colors.text, flexShrink: 1 },
  subtitle: { ...type.small, color: colors.textSecondary, marginTop: 3 },
  progressRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: spacing.sm },
  progressLabel: { ...type.caption, minWidth: 43, textAlign: "right" },
  latestRow: { flexDirection: "row", gap: spacing.xs, alignItems: "center", marginTop: spacing.sm },
  latest: { ...type.caption, color: colors.textSecondary, flex: 1 },
  completeMeta: { flexDirection: "row", alignItems: "center", marginTop: spacing.xs },
  time: { ...type.small, color: colors.textSecondary },
  insight: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    borderTopWidth: 1,
    borderTopColor: colors.hairline,
    marginTop: spacing.sm,
    paddingTop: spacing.sm,
  },
  insightText: { ...type.caption, color: colors.textSecondary, flex: 1 },
});
