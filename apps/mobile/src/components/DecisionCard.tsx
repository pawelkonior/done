import { AlarmClock, CheckCircle2, CircleHelp, Clock3, ShieldCheck, ShoppingBag } from "lucide-react-native";
import { StyleSheet, Text, View } from "react-native";
import { GlassCard } from "@/components/GlassCard";
import { colors, radii, spacing, type } from "@/theme/tokens";
import type { Basket, PortfolioAction, PortfolioDecision } from "@/types/domain";

function isWaitAction(action: PortfolioAction) {
  return action.action === "wait";
}

function riskLabel(score: number) {
  if (score < 0.2) return "Low risk";
  if (score < 0.5) return "Moderate risk";
  return "Higher risk";
}

function formatMoney(value: number, currency: string) {
  return `${value.toFixed(2)} ${currency}`;
}

export function DecisionCard({
  decision,
  basket,
  deadline,
}: {
  decision: PortfolioDecision;
  basket?: Basket | null;
  deadline?: string;
}) {
  const actions = decision.actions;
  const allWait = actions.length > 0 && actions.every(isWaitAction);
  const waiting = decision.status === "waiting" || allWait;
  const infeasible = decision.status === "infeasible_plan";
  const highestRisk = actions.reduce((highest, action) => Math.max(highest, action.risk_score), 0);
  const totalWithDelivery = basket?.total ?? decision.total;
  const decisionTotal = decision.total || basket?.subtotal || 0;
  const explanations = [...decision.explanations, ...actions.map((action) => action.explanation)]
    .filter(Boolean)
    .slice(0, 3);

  return (
    <GlassCard
      strong
      accent={infeasible ? "rgba(255,93,115,0.46)" : waiting ? "rgba(75,123,255,0.46)" : "rgba(72,214,106,0.46)"}
      style={styles.card}
      testID="decision-card"
    >
      <View style={styles.header}>
        <View style={[styles.icon, waiting ? styles.waitIcon : styles.buyIcon]}>
          {infeasible ? <CircleHelp size={25} color={colors.error} /> : waiting ? <Clock3 size={25} color={colors.secondary} /> : <ShoppingBag size={25} color={colors.success} />}
        </View>
        <View style={styles.heading}>
          <Text style={[styles.eyebrow, { color: infeasible ? colors.error : waiting ? colors.secondary : colors.success }]}>
            Portfolio decision
          </Text>
          <Text style={styles.title}>
            {infeasible ? "No safe plan yet" : waiting ? "Wait for a better price" : "Buy now"}
          </Text>
          <Text style={styles.subtitle}>
            {infeasible ? "The current options do not satisfy every hard constraint." : waiting ? "The plan expects a better purchase window before the deadline." : "The selected basket is ready and fits the mission rules."}
          </Text>
        </View>
      </View>

      {actions.length ? (
        <View style={styles.products}>
          <View style={styles.sectionHeading}>
            <Text style={styles.sectionTitle}>Selected products</Text>
            <Text style={styles.count}>{actions.length}</Text>
          </View>
          {actions.map((action) => (
            <View key={`${action.need_id}-${action.product_id}`} style={styles.product}>
              <View style={styles.productIcon}><CheckCircle2 size={15} color={isWaitAction(action) ? colors.secondary : colors.success} /></View>
              <View style={styles.productText}>
                <Text style={styles.productName}>{action.quantity}× {action.product_name}</Text>
                <Text style={styles.productMeta}>{isWaitAction(action) ? "Wait" : "Buy now"}{action.timing_mode ? ` · ${action.timing_mode}` : ""}</Text>
              </View>
              <Text style={styles.productPrice}>{formatMoney(action.objective_cost, decision.currency)}</Text>
            </View>
          ))}
        </View>
      ) : null}

      <View style={styles.facts}>
        <View style={styles.fact}>
          <ShoppingBag size={16} color={colors.primaryBright} />
          <Text style={styles.factLabel}>Plan</Text>
          <Text style={styles.factValue}>{formatMoney(decisionTotal, decision.currency)}</Text>
        </View>
        <View style={styles.fact}>
          <CheckCircle2 size={16} color={colors.success} />
          <Text style={styles.factLabel}>Total with delivery</Text>
          <Text style={styles.factValue}>{formatMoney(totalWithDelivery, basket?.currency ?? decision.currency)}</Text>
        </View>
        <View style={styles.fact}>
          <ShieldCheck size={16} color={highestRisk >= 0.5 ? colors.warning : colors.success} />
          <Text style={styles.factLabel}>Risk</Text>
          <Text style={styles.factValue}>{riskLabel(highestRisk)} · {Math.round(highestRisk * 100)}%</Text>
        </View>
      </View>

      {deadline ? (
        <View style={styles.deadline}>
          <AlarmClock size={17} color={colors.warning} />
          <Text style={styles.deadlineLabel}>Delivery deadline</Text>
          <Text style={styles.deadlineValue}>{deadline}</Text>
        </View>
      ) : null}

      {explanations.length ? (
        <View style={styles.explanations}>
          <Text style={styles.sectionTitle}>Why this plan</Text>
          {explanations.map((explanation, index) => (
            <View key={`${explanation}-${index}`} style={styles.explanation}>
              <View style={styles.bullet} />
              <Text style={styles.explanationText}>{explanation}</Text>
            </View>
          ))}
        </View>
      ) : null}
    </GlassCard>
  );
}

const styles = StyleSheet.create({
  card: { padding: spacing.lg },
  header: { flexDirection: "row", gap: spacing.md, alignItems: "flex-start" },
  icon: { width: 50, height: 50, borderRadius: 25, alignItems: "center", justifyContent: "center" },
  buyIcon: { backgroundColor: "rgba(72,214,106,0.12)" },
  waitIcon: { backgroundColor: "rgba(75,123,255,0.12)" },
  heading: { flex: 1 },
  eyebrow: { ...type.eyebrow },
  title: { ...type.h2, color: colors.text, marginTop: 2 },
  subtitle: { ...type.small, color: colors.textSecondary, marginTop: 3 },
  products: { marginTop: spacing.lg, borderTopWidth: 1, borderTopColor: colors.hairline, paddingTop: spacing.md },
  sectionHeading: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  sectionTitle: { ...type.smallMedium, color: colors.text },
  count: { ...type.caption, color: colors.primaryBright, backgroundColor: "rgba(155,92,255,0.12)", paddingHorizontal: 7, paddingVertical: 2, borderRadius: radii.round },
  product: { flexDirection: "row", alignItems: "center", gap: spacing.xs, paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.hairline },
  productIcon: { width: 24, height: 24, alignItems: "center", justifyContent: "center" },
  productText: { flex: 1 },
  productName: { ...type.smallMedium, color: colors.text },
  productMeta: { ...type.caption, color: colors.textMuted, marginTop: 1, textTransform: "capitalize" },
  productPrice: { ...type.caption, color: colors.textSecondary },
  facts: { flexDirection: "row", gap: spacing.xs, marginTop: spacing.md },
  fact: { flex: 1, minWidth: 0, padding: spacing.sm, borderRadius: radii.md, backgroundColor: "rgba(255,255,255,0.025)" },
  factLabel: { ...type.caption, color: colors.textMuted, marginTop: 5 },
  factValue: { ...type.smallMedium, color: colors.text, marginTop: 1 },
  deadline: { flexDirection: "row", alignItems: "center", gap: spacing.xs, paddingTop: spacing.md, marginTop: spacing.md, borderTopWidth: 1, borderTopColor: colors.hairline },
  deadlineLabel: { ...type.small, color: colors.textSecondary },
  deadlineValue: { ...type.smallMedium, color: colors.text, flex: 1, textAlign: "right" },
  explanations: { marginTop: spacing.lg, gap: spacing.xs },
  explanation: { flexDirection: "row", gap: spacing.sm, alignItems: "flex-start" },
  bullet: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.primaryBright, marginTop: 7 },
  explanationText: { ...type.small, color: colors.textSecondary, flex: 1 },
});
