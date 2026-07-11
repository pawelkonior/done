import { useState } from "react";
import { useLocalSearchParams, useRouter } from "expo-router";
import { AudioLines, Check, Send, Sparkles } from "lucide-react-native";
import { Alert, Pressable, StyleSheet, Text, View } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { AppScreen } from "@/components/AppScreen";
import { ApprovalCard } from "@/components/ApprovalCard";
import { ActionRequestCard } from "@/components/ActionRequestCard";
import { BasketCard } from "@/components/BasketCard";
import { ContractCard } from "@/components/ContractCard";
import { DecisionCard } from "@/components/DecisionCard";
import { DeliveryOptions } from "@/components/DeliveryOptions";
import { DetailHeader } from "@/components/PageHeader";
import { EventTimeline } from "@/components/EventTimeline";
import { GlassCard } from "@/components/GlassCard";
import { IconTile } from "@/components/IconTile";
import { MetricsGrid } from "@/components/MetricsGrid";
import { MissionTrackingCard } from "@/components/MissionTrackingCard";
import { LiveVoiceSheet } from "@/components/LiveVoiceSheet";
import { MissionTimeline } from "@/components/MissionTimeline";
import { ProgressBar } from "@/components/ProgressBar";
import { RecoveryBanner } from "@/components/RecoveryBanner";
import { ScreenState } from "@/components/ScreenState";
import { StatusPill } from "@/components/StatusPill";
import { useCancelMission, useMission, useReplanMission, useRequestHumanSupport, useResolveActionRequest, useSelectDeliveryOption, useUserSettings } from "@/api/hooks";
import { statusToStep } from "@/lib/status";
import { colors, radii, spacing, type } from "@/theme/tokens";

const messageFor = (error: unknown, fallback = "Try again.") => error instanceof Error ? error.message : fallback;

export default function MissionDetailScreen() {
  const params = useLocalSearchParams<{ id: string | string[] }>();
  const id = Array.isArray(params.id) ? params.id[0] : params.id;
  const missionId = id ?? "";
  const router = useRouter();
  const query = useMission(id);
  const deliveryMutation = useSelectDeliveryOption(missionId);
  const cancelMutation = useCancelMission(missionId);
  const replanMutation = useReplanMission(missionId);
  const actionMutation = useResolveActionRequest(missionId);
  const supportMutation = useRequestHumanSupport(missionId);
  const settingsQuery = useUserSettings();
  const [liveVoiceOpen, setLiveVoiceOpen] = useState(false);
  const [deliveryError, setDeliveryError] = useState<string | null>(null);
  const [loadingOptionId, setLoadingOptionId] = useState<string | null>(null);

  const detail = query.data;

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
  const pendingAction = detail.action_requests?.find(
    (action) => action.status === "pending" && action.owner === "user",
  );

  const subtitle = isCompleted
    ? mission.subtitle
    : mission.status === "recovering"
      ? "Repairing the plan automatically"
      : approvalPending
        ? "Your optimized basket is ready"
        : mission.subtitle;

  const cancelMission = async () => {
    if (isTerminal) return;
    try {
      await cancelMutation.mutateAsync(mission.revision);
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

  const replan = async () => {
    try {
      await replanMutation.mutateAsync(mission.revision);
    } catch (error) {
      Alert.alert("Couldn’t replan mission", messageFor(error));
    }
  };

  const showMenu = () => {
    Alert.alert("Mission options", undefined, [
      { text: "Refresh", onPress: () => void query.refetch() },
      ...(!isTerminal ? [{ text: "Replan mission", onPress: () => void replan() }] : []),
      ...(!isTerminal ? [{ text: "Cancel mission", style: "destructive" as const, onPress: confirmCancel }] : []),
      { text: "Close", style: "cancel" },
    ]);
  };

  const selectDelivery = async (optionId: string) => {
    if (isTerminal || deliveryOptions.find((option) => option.id === optionId)?.selected) return;
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

  const resolveAction = async (choice: string) => {
    if (!pendingAction) return;
    if (choice === "answer_by_voice") {
      setLiveVoiceOpen(true);
      return;
    }
    try {
      await actionMutation.mutateAsync({
        actionRequestId: pendingAction.id,
        choice,
        expectedRevision: mission.revision,
      });
    } catch (error) {
      Alert.alert("Couldn’t continue this mission", messageFor(error));
    }
  };

  const requestSupport = async () => {
    try {
      await supportMutation.mutateAsync({
        reason: pendingAction?.reason_code,
        expectedRevision: mission.revision,
      });
    } catch (error) {
      Alert.alert("Couldn’t request human support", messageFor(error));
    }
  };

  return (
    <AppScreen testID="mission-detail-screen">
      <DetailHeader title="Mission Details" onBack={() => router.back()} onMore={showMenu} />

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
            <Text style={styles.completedSubtitle}>{mission.latest_update}</Text>
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

      {pendingAction ? (
        <View style={styles.sectionGap}>
          <ActionRequestCard
            action={pendingAction}
            loading={actionMutation.isPending || supportMutation.isPending}
            onChoose={(choice) => void resolveAction(choice)}
            onRequestHuman={() => void requestSupport()}
          />
        </View>
      ) : null}

      {approvalPending && basket ? (
        <View style={styles.sectionGap}>
          <ApprovalCard
            amount={basket.total}
            currency={basket.currency}
            loading={false}
            onApprove={() => setLiveVoiceOpen(true)}
            onReview={() => setLiveVoiceOpen(true)}
            onCancel={() => setLiveVoiceOpen(true)}
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
            disabled={isTerminal}
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
          onPress={() => setLiveVoiceOpen(true)}
          style={({ pressed }) => [styles.composer, pressed && styles.pressed]}
        >
          <LinearGradient colors={[colors.primary, "#6036CE"]} style={styles.composerVoice}><AudioLines size={21} color={colors.text} /></LinearGradient>
          <Text style={styles.composerText}>Speak to correct or continue this mission…</Text>
          <View style={styles.send}><Send size={18} color={colors.text} /></View>
        </Pressable>
      ) : null}

      <LiveVoiceSheet
        visible={liveVoiceOpen}
        language={settingsQuery.data?.voice_language || "pl-PL"}
        missionId={missionId}
        onClose={() => setLiveVoiceOpen(false)}
        onMissionUpdated={() => void query.refetch()}
        onMissionRefreshRequested={() => void query.refetch()}
      />
    </AppScreen>
  );
}

const styles = StyleSheet.create({
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
