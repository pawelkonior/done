import { Check, Sparkles } from "lucide-react-native";
import { StyleSheet, Text, View } from "react-native";
import { colors, radii, spacing, type } from "@/theme/tokens";
import { workflowSteps } from "@/lib/status";
import type { MissionEvent } from "@/types/domain";

export function MissionTimeline({
  currentStep,
  events,
  compact = false,
}: {
  currentStep: number;
  events?: MissionEvent[];
  compact?: boolean;
}) {
  return (
    <View>
      {workflowSteps.map((step, index) => {
        const position = index + 1;
        const complete = currentStep > position;
        const current = currentStep === position;
        const time = events?.[index]?.created_at;
        return (
          <View key={step.key} style={[styles.step, compact && styles.stepCompact]}>
            <View style={styles.rail}>
              {index > 0 ? (
                <View style={[styles.connectorTop, complete || current ? styles.connectorActive : undefined]} />
              ) : null}
              <View style={[styles.node, complete && styles.nodeComplete, current && styles.nodeCurrent]}>
                {complete ? <Check color={colors.backgroundDeep} size={13} strokeWidth={3} /> : null}
                {current ? <View style={styles.nodeCenter} /> : null}
              </View>
              {index < workflowSteps.length - 1 ? (
                <View style={[styles.connectorBottom, complete ? styles.connectorActive : undefined]} />
              ) : null}
            </View>
            <View style={styles.stepText}>
              <View style={styles.stepTitleRow}>
                <Text style={[styles.stepTitle, current && styles.stepTitleCurrent]}>{step.label}</Text>
                {current ? <Text style={styles.now}>Now</Text> : null}
                {time && !compact ? (
                  <Text style={styles.time}>
                    {new Intl.DateTimeFormat("en", { hour: "numeric", minute: "2-digit" }).format(new Date(time))}
                  </Text>
                ) : null}
              </View>
              {current && !compact ? (
                <Text style={styles.stepSubtitle}>
                  {position === 4 ? "Comparing delivery speed, price and reliability" : "Done is handling this now"}
                </Text>
              ) : null}
            </View>
          </View>
        );
      })}
      <View style={[styles.note, compact && styles.noteCompact]}>
        <Sparkles size={25} color={colors.primaryBright} />
        <Text style={styles.noteText}>
          I found a few great options within your budget. I’ll update you if I need a decision.
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  step: { minHeight: 60, flexDirection: "row" },
  stepCompact: { minHeight: 50 },
  rail: { width: 44, alignItems: "center", position: "relative" },
  node: {
    width: 24,
    height: 24,
    borderRadius: 12,
    borderWidth: 2,
    borderColor: "rgba(155, 92, 255, 0.30)",
    backgroundColor: colors.surface,
    alignItems: "center",
    justifyContent: "center",
    zIndex: 2,
  },
  nodeComplete: { backgroundColor: colors.primary, borderColor: colors.primary },
  nodeCurrent: { borderColor: colors.primary, borderWidth: 3 },
  nodeCenter: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.primary },
  connectorTop: { position: "absolute", top: -36, height: 38, width: 2, backgroundColor: "rgba(155, 92, 255, 0.22)" },
  connectorBottom: { position: "absolute", top: 22, height: 40, width: 2, backgroundColor: "rgba(155, 92, 255, 0.22)" },
  connectorActive: { backgroundColor: colors.primarySoft },
  stepText: { flex: 1, paddingTop: 1 },
  stepTitleRow: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  stepTitle: { ...type.small, color: colors.textSecondary, flexShrink: 1 },
  stepTitleCurrent: { ...type.bodyMedium, color: colors.text },
  stepSubtitle: { ...type.caption, color: colors.textSecondary, marginTop: 2 },
  now: {
    ...type.caption,
    color: colors.primaryBright,
    backgroundColor: "rgba(155,92,255,0.14)",
    borderRadius: radii.round,
    paddingVertical: 3,
    paddingHorizontal: 9,
  },
  time: { ...type.caption, color: colors.textMuted, marginLeft: "auto" },
  note: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    padding: spacing.md,
    backgroundColor: "rgba(155, 92, 255, 0.045)",
    borderWidth: 1,
    borderColor: colors.hairline,
    borderRadius: radii.md,
    marginTop: spacing.sm,
  },
  noteCompact: { paddingVertical: spacing.sm },
  noteText: { ...type.small, color: colors.textSecondary, flex: 1 },
});
