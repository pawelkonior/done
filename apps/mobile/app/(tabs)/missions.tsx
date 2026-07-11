import { useState } from "react";
import { useRouter } from "expo-router";
import { Search, SlidersHorizontal } from "lucide-react-native";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { AppScreen } from "@/components/AppScreen";
import { CircleAction, PageHeader } from "@/components/PageHeader";
import { GlassCard } from "@/components/GlassCard";
import { IconTile } from "@/components/IconTile";
import { MissionCard } from "@/components/MissionCard";
import { MissionComposer } from "@/components/MissionComposer";
import { MissionTimeline } from "@/components/MissionTimeline";
import { ChoiceRow, PreferenceModal } from "@/components/PreferenceModal";
import { ProgressBar } from "@/components/ProgressBar";
import { ScreenState } from "@/components/ScreenState";
import { StatusPill } from "@/components/StatusPill";
import { VoiceShortcut } from "@/components/VoiceShortcut";
import { useCreateTextMission, useMissions, useUserProfile } from "@/api/hooks";
import type { MissionListFilters } from "@/types/domain";
import { colors, radii, spacing, type } from "@/theme/tokens";

type ActionFilter = "all" | "required" | "working";
type MissionSort = NonNullable<MissionListFilters["sort"]>;

const actionOptions: Array<{ value: ActionFilter; label: string }> = [
  { value: "all", label: "All" },
  { value: "required", label: "Needs action" },
  { value: "working", label: "In progress" },
];

const sortOptions: Array<{ value: MissionSort; label: string }> = [
  { value: "updated", label: "Recently updated" },
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "deadline", label: "Deadline" },
];

const errorMessage = (error: unknown) => error instanceof Error ? error.message : "Couldn’t load missions.";

export default function MissionsScreen() {
  const router = useRouter();
  const profile = useUserProfile();
  const create = useCreateTextMission();
  const [composerOpen, setComposerOpen] = useState(false);
  const [composerError, setComposerError] = useState<string | null>(null);
  const [filterOpen, setFilterOpen] = useState(false);
  const [actionFilter, setActionFilter] = useState<ActionFilter>("all");
  const [sort, setSort] = useState<MissionSort>("updated");
  const [search, setSearch] = useState("");
  const [draftAction, setDraftAction] = useState<ActionFilter>("all");
  const [draftSort, setDraftSort] = useState<MissionSort>("updated");
  const [draftSearch, setDraftSearch] = useState("");

  const filters: MissionListFilters = {
    status: "active",
    q: search || undefined,
    sort,
    requires_action: actionFilter === "all" ? undefined : actionFilter === "required",
  };
  const query = useMissions(filters);
  const missions = query.data?.items ?? [];
  const primary = missions[0];

  const openFilters = () => {
    setDraftAction(actionFilter);
    setDraftSort(sort);
    setDraftSearch(search);
    setFilterOpen(true);
  };

  const applyFilters = () => {
    setActionFilter(draftAction);
    setSort(draftSort);
    setSearch(draftSearch.trim());
    setFilterOpen(false);
  };

  const submit = async (text: string) => {
    setComposerError(null);
    try {
      const result = await create.mutateAsync({
        transcript: text,
        locale: profile.data?.locale,
        timezone: profile.data?.timezone,
      });
      setComposerOpen(false);
      router.push(`/mission/${result.mission_id}`);
    } catch (error) {
      setComposerError(errorMessage(error));
    }
  };

  return (
    <AppScreen testID="missions-screen">
      <PageHeader
        title="Active Missions"
        action={<CircleAction label="Filter missions" onPress={openFilters}><SlidersHorizontal color={colors.primaryBright} size={23} /></CircleAction>}
      />

      {query.isLoading ? <ScreenState loading title="Loading active missions…" /> : null}
      {query.isError ? <ScreenState title="Couldn’t load missions" message={errorMessage(query.error)} onRetry={() => void query.refetch()} /> : null}
      {!query.isLoading && !query.isError && !missions.length ? (
        <ScreenState title="No matching missions" message="Change the filters or add a new mission." />
      ) : null}

      {primary ? (
        <Pressable
          accessibilityRole="button"
          onPress={() => router.push(`/mission/${primary.id}`)}
          style={({ pressed }) => [pressed && styles.pressed]}
          testID="primary-mission-card"
        >
          <GlassCard strong accent={colors.borderStrong} style={styles.expanded}>
            <View style={styles.heroRow}>
              <IconTile icon={primary.icon} accent={primary.accent} size={64} />
              <View style={styles.heroContent}>
                <View style={styles.titleRow}>
                  <Text style={styles.title}>{primary.title}</Text>
                  <StatusPill status={primary.status} />
                </View>
                <View style={styles.progressRow}>
                  <ProgressBar progress={primary.progress} />
                </View>
              </View>
            </View>
            <View style={styles.timelinePanel}><MissionTimeline currentStep={Math.max(1, primary.current_step)} compact /></View>
          </GlassCard>
        </Pressable>
      ) : null}

      <View style={styles.list}>
        {missions.slice(1).map((mission) => <MissionCard key={mission.id} mission={mission} onPress={() => router.push(`/mission/${mission.id}`)} />)}
      </View>
      <View style={styles.shortcut}><VoiceShortcut onPress={() => { setComposerError(null); setComposerOpen(true); }} /></View>

      <MissionComposer visible={composerOpen} loading={create.isPending} error={composerError} onClose={() => setComposerOpen(false)} onSubmit={submit} />

      <PreferenceModal
        visible={filterOpen}
        title="Filter missions"
        onClose={() => setFilterOpen(false)}
        onSave={applyFilters}
        saveLabel="Apply filters"
        testID="mission-filter-modal"
      >
        <View style={styles.searchBox}>
          <Search size={18} color={colors.textMuted} />
          <TextInput value={draftSearch} onChangeText={setDraftSearch} placeholder="Search missions" placeholderTextColor={colors.textMuted} style={styles.searchInput} testID="mission-search-input" />
        </View>
        <Text style={styles.filterLabel}>Attention</Text>
        <View accessibilityRole="radiogroup" style={styles.choiceList}>
        {actionOptions.map((option) => <ChoiceRow key={option.value} label={option.label} selected={draftAction === option.value} onPress={() => setDraftAction(option.value)} />)}
        </View>
        <Text style={styles.filterLabel}>Sort</Text>
        <View accessibilityRole="radiogroup" style={styles.choiceList}>
          {sortOptions.map((option) => <ChoiceRow key={option.value} label={option.label} selected={draftSort === option.value} onPress={() => setDraftSort(option.value)} />)}
        </View>
      </PreferenceModal>
    </AppScreen>
  );
}

const styles = StyleSheet.create({
  expanded: { padding: spacing.md },
  heroRow: { flexDirection: "row", gap: spacing.md },
  heroContent: { flex: 1, minWidth: 0 },
  titleRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: spacing.xs },
  title: { ...type.h3, color: colors.text, flexShrink: 1 },
  progressRow: { flexDirection: "row", alignItems: "center", marginTop: spacing.sm },
  timelinePanel: { marginTop: spacing.lg, padding: spacing.md, borderRadius: 16, backgroundColor: "rgba(22,25,43,0.64)", borderWidth: 1, borderColor: colors.hairline },
  list: { gap: spacing.sm, marginTop: spacing.sm },
  shortcut: { marginTop: spacing.md },
  pressed: { opacity: 0.76, transform: [{ scale: 0.994 }] },
  searchBox: { minHeight: 52, flexDirection: "row", alignItems: "center", gap: spacing.xs, borderWidth: 1, borderColor: colors.borderStrong, borderRadius: radii.md, backgroundColor: colors.backgroundDeep, paddingHorizontal: spacing.md },
  searchInput: { ...type.body, color: colors.text, flex: 1 },
  filterLabel: { ...type.eyebrow, color: colors.textSecondary, marginTop: spacing.md },
  choiceList: { gap: spacing.xs },
});
