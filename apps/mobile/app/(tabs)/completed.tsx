import { useState } from "react";
import { useRouter } from "expo-router";
import { CalendarDays, Check, Leaf, PartyPopper } from "lucide-react-native";
import { StyleSheet, Text, View } from "react-native";
import { AppScreen } from "@/components/AppScreen";
import { GlassCard } from "@/components/GlassCard";
import { MissionCard } from "@/components/MissionCard";
import { CircleAction, PageHeader } from "@/components/PageHeader";
import { ChoiceRow, PreferenceModal } from "@/components/PreferenceModal";
import { ScreenState } from "@/components/ScreenState";
import { useMissionDetails, useMissions } from "@/api/hooks";
import type { MissionDetail } from "@/types/domain";
import { colors, radii, spacing, type } from "@/theme/tokens";

type CompletedRange = "today" | "yesterday" | "week";

const rangeOptions: Array<{ value: CompletedRange; label: string; description: string }> = [
  { value: "today", label: "Today", description: "Missions completed since midnight" },
  { value: "yesterday", label: "Yesterday", description: "The previous calendar day" },
  { value: "week", label: "Last 7 days", description: "Today and the previous six days" },
];

function localDate(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function rangeDates(range: CompletedRange) {
  const end = new Date();
  const start = new Date(end);
  if (range === "yesterday") {
    start.setDate(start.getDate() - 1);
    end.setDate(end.getDate() - 1);
  } else if (range === "week") {
    start.setDate(start.getDate() - 6);
  }
  return { from: localDate(start), to: localDate(end) };
}

const errorMessage = (error: unknown) => error instanceof Error ? error.message : "Couldn’t load completed missions.";

export default function CompletedScreen() {
  const router = useRouter();
  const [range, setRange] = useState<CompletedRange>("today");
  const [pickerOpen, setPickerOpen] = useState(false);
  const dates = rangeDates(range);
  const query = useMissions({ status: "completed", completed_from: dates.from, completed_to: dates.to, sort: "newest" });
  const completed = query.data?.items ?? [];
  const detailQueries = useMissionDetails(completed.map((mission) => mission.id));
  const details = detailQueries.map((detail) => detail.data).filter((detail): detail is MissionDetail => Boolean(detail));
  const detailsLoading = detailQueries.some((detail) => detail.isLoading);
  const saved = details.reduce((sum, detail) => sum + (detail.metrics.saved ?? 0), 0);
  const recovered = completed.reduce((sum, mission) => sum + (mission.recovered_failures ?? 0), 0);
  const currency = details[0]?.basket?.currency ?? details[0]?.contract?.currency ?? "PLN";
  const selectedRange = rangeOptions.find((option) => option.value === range)!;
  const pageTitle = range === "today" ? "Completed Today" : range === "yesterday" ? "Completed Yesterday" : "Completed · 7 Days";

  return (
    <AppScreen testID="completed-screen">
      <PageHeader
        title={pageTitle}
        action={<CircleAction label="Select date" onPress={() => setPickerOpen(true)}><CalendarDays color={colors.primaryBright} size={23} /></CircleAction>}
      />

      {query.isLoading ? <ScreenState loading title="Loading completed missions…" /> : null}
      {query.isError ? <ScreenState title="Couldn’t load completed missions" message={errorMessage(query.error)} onRetry={() => void query.refetch()} /> : null}

      {!query.isLoading && !query.isError ? (
        <>
          <GlassCard accent={colors.borderStrong} style={styles.summary}>
            <View style={styles.checkCircle}><Check size={33} color={colors.primaryBright} strokeWidth={2.3} /></View>
            <View style={styles.summaryText}>
              <Text style={styles.summaryTitle}>{completed.length} {completed.length === 1 ? "mission" : "missions"} completed</Text>
              <Text style={styles.summarySubtitle}>{completed.length ? "Everything in this period is safely recorded." : "Nothing completed in this period yet."}</Text>
            </View>
            <PartyPopper size={34} color={colors.primaryBright} />
          </GlassCard>

          <Text style={styles.today}>{selectedRange.label}</Text>
          {completed.length ? (
            <View style={styles.list}>
              {completed.map((mission) => <MissionCard key={mission.id} mission={mission} completed onPress={() => router.push(`/mission/${mission.id}`)} />)}
            </View>
          ) : (
            <ScreenState title="No completed missions" message="Choose another period or complete an active mission." />
          )}

          {completed.length ? (
            <GlassCard style={styles.savings}>
              <View style={styles.leaf}><Leaf size={28} color={colors.primaryBright} /></View>
              <View style={styles.savingsText}>
                <Text style={styles.savingsTitle}>Verified results</Text>
                <Text style={styles.savingsSubtitle}>Done recovered {recovered} unexpected {recovered === 1 ? "issue" : "issues"} in this period.</Text>
              </View>
              <View style={styles.savedPill}>
                <Text style={styles.savedValue}>{detailsLoading ? "…" : `${formatAmount(saved)} ${currency}`}</Text>
                <Text style={styles.savedLabel}>Saved</Text>
              </View>
            </GlassCard>
          ) : null}
        </>
      ) : null}

      <PreferenceModal visible={pickerOpen} title="Completed period" description="Choose which completed missions to show." onClose={() => setPickerOpen(false)} testID="completed-range-modal">
        <View accessibilityRole="radiogroup" style={styles.choiceList}>
          {rangeOptions.map((option) => (
            <ChoiceRow
              key={option.value}
              label={option.label}
              description={option.description}
              selected={range === option.value}
              onPress={() => { setRange(option.value); setPickerOpen(false); }}
              testID={`completed-range-${option.value}`}
            />
          ))}
        </View>
      </PreferenceModal>
    </AppScreen>
  );
}

function formatAmount(value: number) {
  return new Intl.NumberFormat("en", { maximumFractionDigits: 0 }).format(value);
}

const styles = StyleSheet.create({
  summary: { padding: spacing.lg, flexDirection: "row", alignItems: "center", gap: spacing.md },
  checkCircle: { width: 60, height: 60, borderRadius: 30, borderWidth: 2, borderColor: colors.primary, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(155,92,255,0.08)" },
  summaryText: { flex: 1 },
  summaryTitle: { ...type.h3, color: colors.text },
  summarySubtitle: { ...type.small, color: colors.textSecondary, marginTop: 3 },
  today: { ...type.h3, color: colors.text, marginTop: spacing.xxl, marginBottom: spacing.sm },
  list: { gap: spacing.sm },
  savings: { marginTop: spacing.md, padding: spacing.md, flexDirection: "row", alignItems: "center", gap: spacing.md },
  leaf: { width: 54, height: 54, borderRadius: 27, backgroundColor: "rgba(155,92,255,0.10)", alignItems: "center", justifyContent: "center" },
  savingsText: { flex: 1 },
  savingsTitle: { ...type.bodyMedium, color: colors.text },
  savingsSubtitle: { ...type.caption, color: colors.textSecondary, marginTop: 3 },
  savedPill: { backgroundColor: "rgba(255,255,255,0.035)", borderRadius: radii.md, padding: spacing.sm, alignItems: "center", minWidth: 72 },
  savedValue: { ...type.h3, color: colors.success, fontSize: 15 },
  savedLabel: { ...type.caption, color: colors.textSecondary },
  choiceList: { gap: spacing.xs },
});
