import { AudioLines, Check, UserRound } from "lucide-react-native";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import { GlassCard } from "@/components/GlassCard";
import { colors, radii, spacing, type } from "@/theme/tokens";
import type { ActionRequest } from "@/types/domain";

interface ActionRequestCardProps {
  action: ActionRequest;
  loading: boolean;
  onChoose: (choiceId: string) => void;
  onRequestHuman?: () => void;
}

const HUMAN_CHOICE_ID = "request_human";

function readableLabel(value: string) {
  const normalized = value.trim().replace(/[_-]+/g, " ").toLowerCase();
  if (!normalized) return "Action required";
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

export function ActionRequestCard({
  action,
  loading,
  onChoose,
  onRequestHuman,
}: ActionRequestCardProps) {
  const pending = action.status === "pending";
  const disabled = !pending || loading;
  const humanChoice = action.options.find((option) => option.id === HUMAN_CHOICE_ID);
  const choices = action.options.filter((option) => option.id !== HUMAN_CHOICE_ID);
  const showHumanSupport = Boolean(humanChoice || onRequestHuman);
  const statusLabel = pending ? "Voice decision needed" : `Request ${readableLabel(action.status).toLowerCase()}`;
  const reasonLabel = readableLabel(action.reason_code);

  const requestHumanSupport = () => {
    if (onRequestHuman) {
      onRequestHuman();
      return;
    }
    if (humanChoice) onChoose(humanChoice.id);
  };

  return (
    <GlassCard
      strong={pending}
      accent={pending ? "rgba(255,184,77,0.46)" : undefined}
      style={styles.card}
      testID="action-request-card"
      accessibilityLabel={`${statusLabel}. ${action.question}. Reason: ${reasonLabel}`}
    >
      <View style={styles.header}>
        <View style={[styles.icon, !pending && styles.iconInactive]}>
          {pending ? (
            <AudioLines color={colors.warning} size={24} />
          ) : (
            <Check color={colors.textMuted} size={22} />
          )}
        </View>
        <View style={styles.heading}>
          <View style={styles.statusRow}>
            <Text
              style={[styles.eyebrow, !pending && styles.eyebrowInactive]}
              testID="action-request-status"
            >
              {statusLabel}
            </Text>
            {loading ? <ActivityIndicator color={colors.warning} size="small" /> : null}
          </View>
          <Text style={styles.question} testID="action-request-question">
            {action.question}
          </Text>
        </View>
      </View>

      <View style={styles.reason} testID="action-request-reason">
        <Text style={styles.reasonKey}>Reason</Text>
        <Text style={styles.reasonValue}>{reasonLabel}</Text>
      </View>

      {choices.length > 0 ? (
        <View style={styles.choices} accessibilityLabel="Available choices">
          {choices.map((choice) => (
            <Pressable
              key={choice.id}
              accessibilityRole="button"
              accessibilityLabel={`Choose ${choice.label}`}
              accessibilityState={{ disabled, busy: loading }}
              disabled={disabled}
              onPress={() => onChoose(choice.id)}
              style={({ pressed }) => [
                styles.choice,
                disabled && styles.disabled,
                pressed && styles.pressed,
              ]}
              testID={`action-choice-${choice.id}`}
            >
              <Text style={styles.choiceText}>{choice.label}</Text>
            </Pressable>
          ))}
        </View>
      ) : null}

      {showHumanSupport ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Talk to human support"
          accessibilityState={{ disabled, busy: loading }}
          disabled={disabled}
          onPress={requestHumanSupport}
          style={({ pressed }) => [
            styles.humanSupport,
            disabled && styles.disabled,
            pressed && styles.pressed,
          ]}
          testID="request-human-button"
        >
          <UserRound color={colors.primaryBright} size={18} />
          <Text style={styles.humanSupportText}>Talk to human support</Text>
        </Pressable>
      ) : null}
    </GlassCard>
  );
}

const styles = StyleSheet.create({
  card: { padding: spacing.lg },
  header: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm },
  icon: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(255,184,77,0.10)",
  },
  iconInactive: { backgroundColor: "rgba(112,117,139,0.10)" },
  heading: { flex: 1, minWidth: 0, gap: spacing.xxs },
  statusRow: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  eyebrow: { ...type.eyebrow, color: colors.warning, flex: 1 },
  eyebrowInactive: { color: colors.textMuted },
  question: { ...type.h2, color: colors.text },
  reason: {
    marginTop: spacing.md,
    padding: spacing.sm,
    borderRadius: radii.sm,
    borderWidth: 1,
    borderColor: colors.hairline,
    backgroundColor: "rgba(255,255,255,0.018)",
    gap: spacing.xxs,
  },
  reasonKey: { ...type.caption, color: colors.textMuted, textTransform: "uppercase" },
  reasonValue: { ...type.smallMedium, color: colors.textSecondary },
  choices: { gap: spacing.xs, marginTop: spacing.md },
  choice: {
    minHeight: 52,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: spacing.md,
    borderRadius: radii.md,
    backgroundColor: colors.primary,
  },
  choiceText: { ...type.bodyMedium, color: colors.text, textAlign: "center" },
  humanSupport: {
    minHeight: 48,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.xs,
    marginTop: spacing.xs,
    paddingHorizontal: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.md,
  },
  humanSupportText: { ...type.smallMedium, color: colors.primaryBright },
  disabled: { opacity: 0.48 },
  pressed: { opacity: 0.72 },
});
