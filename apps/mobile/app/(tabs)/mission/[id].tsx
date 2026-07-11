import { useState } from "react";
import { useLocalSearchParams, useRouter } from "expo-router";
import { AudioLines, Check, Send, Sparkles, WifiOff } from "lucide-react-native";
import { Alert, Pressable, StyleSheet, Text, View } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { AppScreen } from "@/components/AppScreen";
import { ApprovalCard } from "@/components/ApprovalCard";
import { BasketCard } from "@/components/BasketCard";
import { ContractCard } from "@/components/ContractCard";
import { DecisionCard } from "@/components/DecisionCard";
import { DeliveryOptions } from "@/components/DeliveryOptions";
import { DetailHeader } from "@/components/PageHeader";
import { EventTimeline } from "@/components/EventTimeline";
import { GlassCard } from "@/components/GlassCard";
import { IconTile } from "@/components/IconTile";
import { MetricsGrid } from "@/components/MetricsGrid";
import { MissionComposer } from "@/components/MissionComposer";
import { MissionTrackingCard } from "@/components/MissionTrackingCard";
import { MissionTimeline } from "@/components/MissionTimeline";
import { ProgressBar } from "@/components/ProgressBar";
import { RecoveryBanner } from "@/components/RecoveryBanner";
import { ScreenState } from "@/components/ScreenState";
import { StatusPill } from "@/components/StatusPill";
import { useCancelMission, useCorrectMission, useMission, useResolveApproval, useSelectDeliveryOption } from "@/api/hooks";
import { demoFallbackEnabled } from "@/config/runtime";
import { getFallbackDetail } from "@/data/fallback";
import { statusToStep } from "@/lib/status";
import { colors, radii, spacing, type } from "@/theme/tokens";

const messageFor = (error: unknown, fallback = "Try again.") => error instanceof Error ? error.message : fallback;

export default function MissionDetailScreen() {
  const params = useLocalSearchParams<{ id: string | string[] }>();
  const id = Array.isArray(params.id) ? params.id[0] : params.id;
  const missionId = id ?? "";
  const router = useRouter();
  const query = useMission(id);
  const approvalMutation = useResolveApproval(id);
  const correctionMutation = useCorrectMission(missionId);
  const deliveryMutation = useSelectDeliveryOption(missionId);
  const cancelMutation = useCancelMission(missionId);
  const [composerOpen, setComposerOpen] = useState(false);
  const [correctionError, setCorrectionError] = useState<string | null>(null);
  const [deliveryError, setDeliveryError] = useState<string | null>(null);
  const [loadingOptionId, setLoadingOptionId] = useState<string | null>(null);

  const fallbackDetail = demoFallbackEnabled && query.isError ? getFallbackDetail(missionId || "birthday-demo") : null;
  const detail = query.data ?? fallbackDetail;
  const preview = Boolean(fallbackDetail && !query.data);

  if (!detail) {
    return (
      <AppScreen testID="mission-detail-screen">
        <DetailHeader title="Mission Details" onBack={() => router.back()} onMore={() => void query.refetch()} />
        <ScreenState
          loading={query.isLoading}
          title={query.isLoading ? "Loading mission…" : "Mission unavailable"}
          message={query.error ? messageFor(query.error) : "This mission could not be found."}
          onRetry={query.isLoading ? undefined : () => void query.refetch()}
        />
      </AppScreen>
    );
  }

  const { mission, contract, basket, approval, portfolio_decision: portfolioDecision, order, events, metrics, delivery_options: deliveryOptions } = detail;
  const currentStep = mission.current_step || statusToStep(mission.status, 1);
  const recovered = Math.max(metrics.recovered_failures ?? 0, events.some((event) => event.type.includes("recover") || event.type.includes("replac") || event.type.includes("rerout")) ? 1 : 0);
  const isCompleted = mission.status === "completed";
  const isTerminal = ["completed", "cancelled", "failed"].includes(mission.status);
  const approvalPending = mission.status === "approval_required" && approval?.status === "pending";

  const subtitle = isCompleted
    ? "Everything was completed safely"
    : mission.status === "recovering"
      ? "Repairing the plan automatically"
      : approvalPending
        ? "Your optimized basket is ready"
        : mission.subtitle;

  const resolve = async (choice: "approve" | "review" | "cancel") => {
    if (!approval || preview) return;
    try {
      await approvalMutation.mutateAsync({ approvalId: approval.id, choice });
      if (choice === "review") Alert.alert("Basket ready for review", "The mission remains paused. Review the basket and delivery choice below, then approve when ready.");
    } catch (error) {
      Alert.alert("Couldn’t update approval", messageFor(error));
    }
  };

  const confirmApprovalCancel = () => {
    Alert.alert("Cancel this mission?", "The proposed basket will not be purchased.", [
      { text: "Keep mission", style: "cancel" },
      { text: "Cancel mission", style: "destructive", onPress: () => void resolve("cancel") },
    ]);
  };

  const cancelMission = async () => {
    if (preview || isTerminal) return;
    try {
      await cancelMutation.mutateAsync();
    } catch (error) {
      Alert.alert("Couldn’t cancel mission", messageFor(error));
    }
  };

  const confirmCancel = () => {
    Alert.alert("Cancel this mission?", "Current work will stop and pending approvals will be closed.", [
      { text: "Keep mission", style: "cancel" },
      { text: "Cancel mission", style: "destructive", onPress: () => void cancelMission() },
    ]);
  };

  const showMenu = () => {
    Alert.alert("Mission options", undefined, [
      { text: "Refresh", onPress: () => void query.refetch() },
      ...(!isTerminal && !preview ? [{ text: "Cancel mission", style: "destructive" as const, onPress: confirmCancel }] : []),
      { text: "Close", style: "cancel" },
    ]);
  };

  const submitCorrection = async (correction: string) => {
    setCorrectionError(null);
    try {
      await correctionMutation.mutateAsync({ correction, expected_revision: mission.revision });
      setComposerOpen(false);
    } catch (error) {
      setCorrectionError(messageFor(error, "Couldn’t update this mission."));
    }
  };

  const selectDelivery = async (optionId: string) => {
    if (preview || isTerminal || deliveryOptions.find((option) => option.id === optionId)?.selected) return;
    setDeliveryError(null);
    setLoadingOptionId(optionId);
    try {
      await deliveryMutation.mutateAsync({ option_id: optionId, expected_revision: mission.revision });
    } catch (error) {
      setDeliveryError(messageFor(error, "Couldn’t change the delivery option."));
    } finally {
      setLoadingOptionId(null);
    }
  };

  return (
    <AppScreen testID="mission-detail-screen">
      <DetailHeader title="Mission Details" onBack={() => router.back()} onMore={showMenu} />

      {preview ? (
        <View style={styles.previewBanner}>
          <WifiOff size={16} color={colors.warning} />
          <Text style={styles.previewText}>Demo fallback is enabled. This preview is read-only until the API reconnects.</Text>
        </View>
      ) : null}

      <View style={styles.hero}>
        <IconTile icon={mission.icon ?? "cake"} accent={mission.accent ?? "violet"} size={82} />
        <View style={styles.heroText}>
          <Text style={styles.heroTitle}>{mission.title}</Text>
          <Text style={styles.heroSubtitle}>{subtitle}</Text>
          <View style={styles.statusRow}>
            <StatusPill status={mission.status} />
            <Text style={styles.steps}>{mission.current_step} of {mission.total_steps} steps</Text>
          </View>
          <ProgressBar progress={mission.progress} />
        </View>
      </View>

      {isCompleted ? (
        <LinearGradient colors={["rgba(72,214,106,0.19)", "rgba(11,35,20,0.12)"]} style={styles.completedHero}>
          <View style={styles.completedCheck}><Check size={28} color={colors.backgroundDeep} strokeWidth={3} /></View>
          <View style={styles.completedText}>
            <Text style={styles.completedTitle}>Mission completed</Text>
            <Text style={styles.completedSubtitle}>Say it once. Consider it done.</Text>
          </View>
          <Sparkles size={25} color={colors.success} />
        </LinearGradient>
      ) : null}

      <View style={styles.sectionGap}><RecoveryBanner recovered={recovered} active={mission.status === "recovering"} /></View>

      {portfolioDecision ? (
        <View style={styles.sectionGap}>
          <DecisionCard decision={portfolioDecision} basket={basket} deadline={contract?.deadline} />
        </View>
      ) : null}

      {approvalPending && basket ? (
        <View style={styles.sectionGap}>
          <ApprovalCard
            amount={basket.total}
            currency={basket.currency}
            loading={approvalMutation.isPending}
            onApprove={() => void resolve("approve")}
            onReview={() => void resolve("review")}
            onCancel={confirmApprovalCancel}
          />
        </View>
      ) : null}

      {isCompleted ? <View style={styles.sectionGap}><MetricsGrid metrics={metrics} /></View> : null}

      <GlassCard style={[styles.progressCard, styles.sectionGap]}>
        <Text style={styles.sectionTitle}>Progress</Text>
        <View style={styles.timeline}><MissionTimeline currentStep={isCompleted ? 7 : Math.max(1, Math.min(6, currentStep))} events={events} /></View>
      </GlassCard>

      {contract ? <View style={styles.sectionGap}><ContractCard contract={contract} /></View> : null}
      {deliveryOptions.length ? (
        <View style={styles.sectionGap}>
          <DeliveryOptions
            options={deliveryOptions}
            onSelect={(optionId) => void selectDelivery(optionId)}
            loadingOptionId={loadingOptionId}
            disabled={preview || isTerminal}
            error={deliveryError}
          />
        </View>
      ) : null}
      {basket ? <View style={styles.sectionGap}><BasketCard basket={basket} /></View> : null}
      <View style={styles.sectionGap}><MissionTrackingCard missionStatus={mission.status} order={order} events={events} recovered={recovered} /></View>
      {events.length ? <View style={styles.sectionGap}><EventTimeline events={events} /></View> : null}

      {!isTerminal ? (
        <Pressable
          accessibilityRole="button"
          disabled={preview}
          onPress={() => { setCorrectionError(null); setComposerOpen(true); }}
          style={({ pressed }) => [styles.composer, preview && styles.disabled, pressed && styles.pressed]}
        >
          <LinearGradient colors={[colors.primary, "#6036CE"]} style={styles.composerVoice}><AudioLines size={21} color={colors.text} /></LinearGradient>
          <Text style={styles.composerText}>Correct or add to this mission…</Text>
          <View style={styles.send}><Send size={18} color={colors.text} /></View>
        </Pressable>
      ) : null}

      <MissionComposer
        visible={composerOpen}
        mode="correction"
        loading={correctionMutation.isPending}
        error={correctionError}
        onClose={() => setComposerOpen(false)}
        onSubmit={submitCorrection}
      />
    </AppScreen>
  );
}

const styles = StyleSheet.create({
  previewBanner: { minHeight: 48, flexDirection: "row", alignItems: "center", gap: spacing.xs, borderRadius: radii.md, padding: spacing.sm, marginBottom: spacing.md, borderWidth: 1, borderColor: "rgba(255,184,77,0.25)", backgroundColor: "rgba(255,184,77,0.07)" },
  previewText: { ...type.caption, color: colors.warning, flex: 1 },
  hero: { flexDirection: "row", gap: spacing.md, alignItems: "center", marginBottom: spacing.sm },
  heroText: { flex: 1, minWidth: 0 },
  heroTitle: { ...type.h1, fontSize: 26, lineHeight: 31, color: colors.text },
  heroSubtitle: { ...type.small, color: colors.textSecondary, marginTop: 3 },
  statusRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm, marginTop: spacing.sm, marginBottom: spacing.sm },
  steps: { ...type.small, color: colors.primaryBright },
  completedHero: { borderRadius: radii.lg, borderWidth: 1, borderColor: "rgba(72,214,106,0.30)", padding: spacing.md, flexDirection: "row", alignItems: "center", gap: spacing.md, marginTop: spacing.lg },
  completedCheck: { width: 50, height: 50, borderRadius: 25, backgroundColor: colors.success, alignItems: "center", justifyContent: "center" },
  completedText: { flex: 1 },
  completedTitle: { ...type.h3, color: colors.text },
  completedSubtitle: { ...type.caption, color: colors.textSecondary },
  sectionGap: { marginTop: spacing.md },
  progressCard: { padding: spacing.lg },
  sectionTitle: { ...type.h3, color: colors.text },
  timeline: { marginTop: spacing.lg },
  composer: { minHeight: 64, flexDirection: "row", alignItems: "center", gap: spacing.sm, borderWidth: 1, borderColor: colors.borderStrong, borderRadius: radii.lg, padding: spacing.xs, marginTop: spacing.md, backgroundColor: "rgba(14,17,32,0.94)" },
  composerVoice: { width: 48, height: 48, borderRadius: 24, alignItems: "center", justifyContent: "center" },
  composerText: { ...type.small, color: colors.textSecondary, flex: 1 },
  send: { width: 38, height: 38, borderRadius: 19, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center" },
  pressed: { opacity: 0.72 },
  disabled: { opacity: 0.48 },
});
