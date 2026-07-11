import { useEffect, useMemo, useState } from "react";
import {
  Bell,
  Bot,
  ChevronRight,
  Cpu,
  Download,
  Languages,
  LockKeyhole,
  Mic2,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Store,
  WalletCards,
} from "lucide-react-native";
import { ActivityIndicator, Alert, Pressable, Share, StyleSheet, Switch, Text, TextInput, View } from "react-native";
import { AppScreen } from "@/components/AppScreen";
import { GlassCard } from "@/components/GlassCard";
import { PageHeader } from "@/components/PageHeader";
import { ChoiceRow, PreferenceModal } from "@/components/PreferenceModal";
import { useMerchants, useResetDemo, useRuntimeCapabilities, useUpdateUserSettings, useUserDataExport, useUserSettings } from "@/api/hooks";
import { API_URL } from "@/api/client";
import type { UserSettingsUpdate } from "@/types/domain";
import { ensureNotificationPermission } from "@/notifications/notifications";
import { colors, radii, spacing, type } from "@/theme/tokens";

type SettingsDialog = "language" | "approval" | "threshold" | "merchants" | "privacy" | null;

const languageOptions = [
  { value: "en-PL", label: "English (Poland)", description: "English voice with Polish regional defaults" },
  { value: "pl-PL", label: "Polski", description: "Polish voice and responses" },
  { value: "en-US", label: "English (United States)", description: "US English voice and formatting" },
];

const approvalOptions = [
  { value: "always", label: "Always ask", description: "Require approval before every simulated purchase" },
  { value: "above_threshold", label: "Above threshold", description: "Ask only when the total reaches your limit" },
  { value: "autonomous_low_risk", label: "Autonomous for low risk", description: "Act without approval only for low-risk purchases" },
];

const languageLabel = (value: string) => languageOptions.find((option) => option.value === value)?.label ?? value;
const approvalLabel = (value: string) => approvalOptions.find((option) => option.value === value)?.label ?? value.replaceAll("_", " ");
const errorMessage = (error: unknown) => error instanceof Error ? error.message : "Couldn’t save this setting.";

export default function SettingsScreen() {
  const settingsQuery = useUserSettings();
  const merchantsQuery = useMerchants();
  const update = useUpdateUserSettings();
  const reset = useResetDemo();
  const runtime = useRuntimeCapabilities();
  const [dialog, setDialog] = useState<SettingsDialog>(null);
  const exportQuery = useUserDataExport(dialog === "privacy");
  const [languageDraft, setLanguageDraft] = useState("");
  const [approvalDraft, setApprovalDraft] = useState("");
  const [thresholdDraft, setThresholdDraft] = useState("");
  const [merchantDraft, setMerchantDraft] = useState<string[]>([]);

  const settings = settingsQuery.data;

  useEffect(() => {
    if (!settings) return;
    setLanguageDraft(settings.voice_language);
    setApprovalDraft(settings.approval_policy);
    setThresholdDraft(String(settings.approval_threshold));
    setMerchantDraft(settings.preferred_merchant_ids);
  }, [settings]);

  const openDialog = (next: Exclude<SettingsDialog, null>) => {
    if (!settings) return;
    update.reset();
    setLanguageDraft(settings.voice_language);
    setApprovalDraft(settings.approval_policy);
    setThresholdDraft(String(settings.approval_threshold));
    setMerchantDraft(settings.preferred_merchant_ids);
    setDialog(next);
  };

  const save = async (payload: UserSettingsUpdate) => {
    try {
      await update.mutateAsync(payload);
      setDialog(null);
    } catch {
      // The modal keeps the mutation error visible and lets the user retry.
    }
  };

  const toggle = (payload: UserSettingsUpdate) => {
    update.reset();
    void update.mutateAsync(payload).catch(() => undefined);
  };

  const toggleNotifications = async () => {
    if (!settings) return;
    const enabled = !settings.notifications_enabled;
    if (enabled && !(await ensureNotificationPermission())) {
      Alert.alert(
        "Notifications are disabled",
        "Allow notifications in system settings to receive mission updates.",
      );
      return;
    }
    toggle({ notifications_enabled: enabled });
  };

  const doReset = () => {
    Alert.alert("Reset demo?", "This removes all live missions and restores the deterministic catalog.", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Reset",
        style: "destructive",
        onPress: async () => {
          try {
            await reset.mutateAsync();
            Alert.alert("Demo reset", "Ready for a fresh mission.");
          } catch (error) {
            Alert.alert("Reset failed", errorMessage(error));
          }
        },
      },
    ]);
  };

  const exportText = useMemo(
    () => exportQuery.data ? JSON.stringify(exportQuery.data, null, 2) : "",
    [exportQuery.data],
  );

  const shareExport = async () => {
    if (!exportText) return;
    try {
      await Share.share({ title: "Done data export", message: exportText });
    } catch (error) {
      Alert.alert("Couldn’t share export", errorMessage(error));
    }
  };

  const threshold = Number(thresholdDraft.replace(",", "."));
  const mutationError = update.error ? errorMessage(update.error) : null;

  return (
    <AppScreen testID="settings-screen">
      <PageHeader title="Settings" subtitle="Choose how Done speaks, decides and keeps you informed." />

      {!settings ? (
        <QueryState
          loading={settingsQuery.isLoading}
          error={settingsQuery.error ? errorMessage(settingsQuery.error) : null}
          onRetry={() => void settingsQuery.refetch()}
        />
      ) : (
        <>
          {mutationError && !dialog ? <InlineError message={mutationError} /> : null}

          <SettingsSection title="Voice & language">
            <SettingsRow
              icon={Languages}
              label="Language"
              value={languageLabel(settings.voice_language)}
              onPress={() => openDialog("language")}
              testID="settings-language"
            />
            <SettingsRow
              icon={Bot}
              label="Confirmation voice"
              value=""
              toggleValue={settings.confirmation_voice_enabled}
              disabled={update.isPending}
              onPress={() => toggle({ confirmation_voice_enabled: !settings.confirmation_voice_enabled })}
              testID="settings-confirmation-voice"
            />
          </SettingsSection>

          <SettingsSection title="Autonomy">
            <SettingsRow
              icon={ShieldCheck}
              label="Safe self-healing"
              value=""
              toggleValue={settings.safe_recovery_enabled}
              disabled={update.isPending}
              onPress={() => toggle({ safe_recovery_enabled: !settings.safe_recovery_enabled })}
              testID="settings-safe-recovery"
            />
            <SettingsRow
              icon={WalletCards}
              label="Purchase approval"
              value={approvalLabel(settings.approval_policy)}
              onPress={() => openDialog("approval")}
              testID="settings-approval-policy"
            />
            <SettingsRow
              icon={WalletCards}
              label="Approval threshold"
              value={`${settings.approval_threshold.toFixed(0)} PLN`}
              onPress={() => openDialog("threshold")}
              testID="settings-approval-threshold"
            />
            <SettingsRow
              icon={Store}
              label="Preferred merchants"
              value={`${settings.preferred_merchant_ids.length} enabled`}
              onPress={() => openDialog("merchants")}
              testID="settings-merchants"
            />
          </SettingsSection>

          <SettingsSection title="Updates & privacy">
            <SettingsRow
              icon={Bell}
              label="Mission notifications"
              value=""
              toggleValue={settings.notifications_enabled}
              disabled={update.isPending}
              onPress={() => void toggleNotifications()}
              testID="settings-notifications"
            />
            <SettingsRow
              icon={LockKeyhole}
              label="Privacy & data"
              value="View export"
              onPress={() => openDialog("privacy")}
              testID="settings-privacy"
            />
          </SettingsSection>

          <SettingsSection title="AI services">
            {runtime.data ? (
              <>
                <RuntimeRow icon={Cpu} label="Ollama" capability={runtime.data.ai} />
                <RuntimeRow icon={Mic2} label="OpenAI STT" capability={runtime.data.speech_to_text} />
                <RuntimeRow icon={Sparkles} label="OpenAI Realtime" capability={runtime.data.realtime} />
              </>
            ) : (
              <View style={styles.runtimeLoading}>
                {runtime.isLoading ? <ActivityIndicator color={colors.primaryBright} /> : <Text style={styles.runtimeError}>{runtime.error ? errorMessage(runtime.error) : "Runtime status unavailable"}</Text>}
              </View>
            )}
            <Pressable onPress={() => void runtime.refetch()} disabled={runtime.isFetching} accessibilityRole="button" style={({ pressed }) => [styles.runtimeRefresh, runtime.isFetching && styles.disabled, pressed && styles.pressed]} testID="refresh-runtime">
              {runtime.isFetching ? <ActivityIndicator size="small" color={colors.primaryBright} /> : <RefreshCw size={16} color={colors.primaryBright} />}
              <Text style={styles.runtimeRefreshText}>{runtime.isFetching ? "Checking…" : "Refresh runtime status"}</Text>
            </Pressable>
          </SettingsSection>

          {runtime.data?.demo_endpoints ? (
            <GlassCard accent={colors.borderStrong} style={styles.demoCard}>
              <View style={styles.demoIcon}><RotateCcw color={colors.primaryBright} size={24} /></View>
              <View style={styles.demoText}>
                <Text style={styles.demoTitle}>Demo controls</Text>
                <Text style={styles.demoSubtitle}>Reset all missions, approvals, failures and payment attempts.</Text>
                <Text numberOfLines={1} style={styles.endpoint}>{API_URL}</Text>
              </View>
              <Pressable
                onPress={doReset}
                disabled={reset.isPending}
                accessibilityRole="button"
                accessibilityState={{ disabled: reset.isPending }}
                style={[styles.resetButton, reset.isPending && styles.disabled]}
                testID="reset-demo-button"
              >
                <Text style={styles.resetText}>{reset.isPending ? "Resetting…" : "Reset"}</Text>
              </Pressable>
            </GlassCard>
          ) : null}
        </>
      )}

      <PreferenceModal
        visible={dialog === "language"}
        title="Voice language"
        description="Used for voice recognition, spoken confirmations and regional formatting."
        onClose={() => setDialog(null)}
        onSave={() => void save({ voice_language: languageDraft })}
        saving={update.isPending}
        error={dialog === "language" && mutationError ? mutationError : null}
        testID="language-modal"
      >
        <View accessibilityRole="radiogroup" style={styles.choiceList}>
          {languageOptions.map((option) => (
            <ChoiceRow
              key={option.value}
              label={option.label}
              description={option.description}
              selected={languageDraft === option.value}
              onPress={() => setLanguageDraft(option.value)}
            />
          ))}
        </View>
      </PreferenceModal>

      <PreferenceModal
        visible={dialog === "approval"}
        title="Purchase approval"
        description="Control when Done pauses before a simulated purchase."
        onClose={() => setDialog(null)}
        onSave={() => void save({ approval_policy: approvalDraft })}
        saving={update.isPending}
        error={dialog === "approval" && mutationError ? mutationError : null}
        testID="approval-policy-modal"
      >
        <View accessibilityRole="radiogroup" style={styles.choiceList}>
          {approvalOptions.map((option) => (
            <ChoiceRow
              key={option.value}
              label={option.label}
              description={option.description}
              selected={approvalDraft === option.value}
              onPress={() => setApprovalDraft(option.value)}
            />
          ))}
        </View>
      </PreferenceModal>

      <PreferenceModal
        visible={dialog === "threshold"}
        title="Approval threshold"
        description="Done will request approval when the basket reaches this amount."
        onClose={() => setDialog(null)}
        onSave={() => void save({ approval_threshold: threshold })}
        saving={update.isPending}
        saveDisabled={!Number.isFinite(threshold) || threshold < 0}
        error={dialog === "threshold" && mutationError ? mutationError : null}
        testID="approval-threshold-modal"
      >
        <Text style={styles.inputLabel}>Amount in PLN</Text>
        <TextInput
          value={thresholdDraft}
          onChangeText={setThresholdDraft}
          keyboardType="decimal-pad"
          placeholder="0"
          placeholderTextColor={colors.textMuted}
          style={styles.input}
          testID="approval-threshold-input"
        />
      </PreferenceModal>

      <PreferenceModal
        visible={dialog === "merchants"}
        title="Preferred merchants"
        description="Done will prefer these stores when price, safety and delivery are comparable."
        onClose={() => setDialog(null)}
        onSave={() => void save({ preferred_merchant_ids: merchantDraft })}
        saving={update.isPending}
        error={dialog === "merchants" && mutationError ? mutationError : null}
        testID="merchant-modal"
      >
        {merchantsQuery.isLoading ? <ActivityIndicator color={colors.primaryBright} /> : null}
        {merchantsQuery.error ? <InlineError message={errorMessage(merchantsQuery.error)} /> : null}
        {merchantsQuery.data?.filter((merchant) => merchant.active).map((merchant) => {
          const selected = merchantDraft.includes(merchant.id);
          return (
            <ChoiceRow
              key={merchant.id}
              label={merchant.name}
              description={`${Math.round(merchant.reliability_score * 100)}% reliability`}
              selected={selected}
              multiple
              onPress={() => setMerchantDraft((current) => selected ? current.filter((id) => id !== merchant.id) : [...current, merchant.id])}
              testID={`merchant-${merchant.id}`}
            />
          );
        })}
      </PreferenceModal>

      <PreferenceModal
        visible={dialog === "privacy"}
        title="Privacy & data"
        description="This is the complete data export associated with your Done profile."
        onClose={() => setDialog(null)}
        testID="privacy-modal"
      >
        {exportQuery.isLoading ? <ActivityIndicator color={colors.primaryBright} /> : null}
        {exportQuery.error ? (
          <>
            <InlineError message={errorMessage(exportQuery.error)} />
            <Pressable onPress={() => void exportQuery.refetch()} style={styles.secondaryButton}>
              <Text style={styles.secondaryButtonText}>Try again</Text>
            </Pressable>
          </>
        ) : null}
        {exportText ? (
          <>
            <View style={styles.exportBox}>
              <Text selectable style={styles.exportText}>{exportText}</Text>
            </View>
            <Pressable onPress={() => void shareExport()} style={styles.shareButton} accessibilityRole="button" testID="share-export-button">
              <Download size={18} color={colors.text} />
              <Text style={styles.shareText}>Share data export</Text>
            </Pressable>
          </>
        ) : null}
      </PreferenceModal>
    </AppScreen>
  );
}

function SettingsSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <GlassCard style={styles.rows}>{children}</GlassCard>
    </View>
  );
}

function SettingsRow({
  icon: Icon,
  label,
  value,
  onPress,
  toggleValue,
  disabled = false,
  testID,
}: {
  icon: typeof Languages;
  label: string;
  value: string;
  onPress: () => void;
  toggleValue?: boolean;
  disabled?: boolean;
  testID?: string;
}) {
  const isSwitch = typeof toggleValue === "boolean";
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      accessibilityRole={isSwitch ? "switch" : "button"}
      accessibilityState={isSwitch ? { checked: toggleValue, disabled } : { disabled }}
      style={({ pressed }) => [styles.row, disabled && styles.disabled, pressed && styles.pressed]}
      testID={testID}
    >
      <View style={styles.rowIcon}><Icon size={20} color={colors.primaryBright} /></View>
      <Text style={styles.rowLabel}>{label}</Text>
      {isSwitch ? (
        <View pointerEvents="none">
          <Switch
            value={toggleValue}
            disabled={disabled}
            trackColor={{ false: colors.surfaceElevated, true: colors.primarySoft }}
            thumbColor={colors.text}
          />
        </View>
      ) : (
        <>
          <Text numberOfLines={1} style={styles.rowValue}>{value}</Text>
          <ChevronRight size={18} color={colors.textMuted} />
        </>
      )}
    </Pressable>
  );
}

function RuntimeRow({ icon: Icon, label, capability }: { icon: typeof Cpu; label: string; capability: { status: string; model?: string; detail?: string | null } }) {
  const available = capability.status === "available";
  const degraded = capability.status === "degraded";
  const statusColor = available ? colors.success : degraded ? colors.warning : colors.error;
  return (
    <View style={styles.runtimeRow}>
      <View style={styles.rowIcon}><Icon size={20} color={colors.primaryBright} /></View>
      <View style={styles.runtimeText}>
        <Text style={styles.rowLabel}>{label}</Text>
        <Text numberOfLines={2} style={styles.runtimeDetail}>{capability.model || capability.detail || "No model configured"}</Text>
      </View>
      <View style={[styles.statusDot, { backgroundColor: statusColor }]} />
      <Text style={[styles.runtimeStatus, { color: statusColor }]}>{capability.status}</Text>
    </View>
  );
}

function QueryState({ loading, error, onRetry }: { loading: boolean; error: string | null; onRetry: () => void }) {
  return (
    <GlassCard style={styles.queryState}>
      {loading ? <ActivityIndicator color={colors.primaryBright} /> : null}
      <Text style={styles.queryStateText}>{loading ? "Loading settings…" : error ?? "Settings aren’t available."}</Text>
      {!loading ? <Pressable onPress={onRetry} style={styles.secondaryButton}><Text style={styles.secondaryButtonText}>Try again</Text></Pressable> : null}
    </GlassCard>
  );
}

function InlineError({ message }: { message: string }) {
  return <View style={styles.errorBanner}><Text accessibilityRole="alert" style={styles.errorText}>{message}</Text></View>;
}

const styles = StyleSheet.create({
  section: { marginBottom: spacing.lg },
  sectionTitle: { ...type.eyebrow, color: colors.textSecondary, marginBottom: spacing.xs, paddingLeft: spacing.xs },
  rows: { overflow: "hidden" },
  row: { minHeight: 62, paddingHorizontal: spacing.md, flexDirection: "row", alignItems: "center", gap: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.hairline },
  rowIcon: { width: 36, height: 36, borderRadius: 12, backgroundColor: "rgba(155,92,255,0.08)", alignItems: "center", justifyContent: "center" },
  rowLabel: { ...type.smallMedium, color: colors.text, flex: 1 },
  rowValue: { ...type.caption, color: colors.textSecondary, maxWidth: 145, textTransform: "capitalize" },
  runtimeRow: { minHeight: 66, paddingHorizontal: spacing.md, flexDirection: "row", alignItems: "center", gap: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.hairline },
  runtimeText: { flex: 1, minWidth: 0 },
  runtimeDetail: { ...type.caption, color: colors.textMuted, marginTop: 2 },
  runtimeStatus: { ...type.caption, textTransform: "capitalize" },
  statusDot: { width: 7, height: 7, borderRadius: 4 },
  runtimeLoading: { minHeight: 70, alignItems: "center", justifyContent: "center", padding: spacing.md },
  runtimeError: { ...type.caption, color: colors.error, textAlign: "center" },
  runtimeRefresh: { minHeight: 46, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.xs },
  runtimeRefreshText: { ...type.smallMedium, color: colors.primaryBright },
  pressed: { opacity: 0.68 },
  disabled: { opacity: 0.48 },
  demoCard: { padding: spacing.md, flexDirection: "row", alignItems: "center", gap: spacing.sm },
  demoIcon: { width: 48, height: 48, borderRadius: 24, backgroundColor: "rgba(155,92,255,0.10)", alignItems: "center", justifyContent: "center" },
  demoText: { flex: 1, minWidth: 0 },
  demoTitle: { ...type.bodyMedium, color: colors.text },
  demoSubtitle: { ...type.caption, color: colors.textSecondary, marginTop: 2 },
  endpoint: { ...type.caption, color: colors.textMuted, marginTop: 4 },
  resetButton: { minHeight: 40, paddingHorizontal: spacing.md, borderRadius: radii.md, backgroundColor: "rgba(155,92,255,0.12)", alignItems: "center", justifyContent: "center" },
  resetText: { ...type.smallMedium, color: colors.primaryBright },
  choiceList: { gap: spacing.xs },
  inputLabel: { ...type.caption, color: colors.textSecondary, marginBottom: spacing.xs },
  input: { minHeight: 52, borderWidth: 1, borderColor: colors.borderStrong, borderRadius: radii.md, backgroundColor: "rgba(5,7,16,0.72)", paddingHorizontal: spacing.md, color: colors.text, ...type.body },
  errorBanner: { borderWidth: 1, borderColor: "rgba(255,93,115,0.25)", backgroundColor: "rgba(255,93,115,0.07)", borderRadius: radii.md, padding: spacing.sm, marginBottom: spacing.md },
  errorText: { ...type.caption, color: colors.error },
  queryState: { minHeight: 150, padding: spacing.lg, alignItems: "center", justifyContent: "center", gap: spacing.sm },
  queryStateText: { ...type.small, color: colors.textSecondary, textAlign: "center" },
  secondaryButton: { minHeight: 42, paddingHorizontal: spacing.md, borderRadius: radii.md, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  secondaryButtonText: { ...type.smallMedium, color: colors.primaryBright },
  exportBox: { maxHeight: 330, borderRadius: radii.md, borderWidth: 1, borderColor: colors.hairline, backgroundColor: colors.backgroundDeep, padding: spacing.sm },
  exportText: { fontSize: 11, lineHeight: 16, color: colors.textSecondary, fontFamily: "monospace" },
  shareButton: { minHeight: 50, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.xs, borderRadius: radii.md, backgroundColor: colors.primary, marginTop: spacing.sm },
  shareText: { ...type.smallMedium, color: colors.text },
});
