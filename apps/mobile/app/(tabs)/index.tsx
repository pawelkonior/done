import { useEffect, useRef, useState } from "react";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Check, ListTodo, WifiOff } from "lucide-react-native";
import { Pressable, StyleSheet, Text, View } from "react-native";
import * as Speech from "expo-speech";
import { AppScreen } from "@/components/AppScreen";
import { MissionCard } from "@/components/MissionCard";
import { MissionComposer } from "@/components/MissionComposer";
import { LiveVoiceSheet } from "@/components/LiveVoiceSheet";
import { InlineError, ScreenState } from "@/components/ScreenState";
import { SectionHeader } from "@/components/SectionHeader";
import { VoiceOrb } from "@/components/VoiceOrb";
import { useCreateTextMission, useCreateVoiceMission, useMissions, useUserProfile, useUserSettings } from "@/api/hooks";
import { demoFallbackEnabled } from "@/config/runtime";
import { fallbackMissions } from "@/data/fallback";
import { useVoiceStore } from "@/store/voice";
import { colors, radii, spacing, type } from "@/theme/tokens";

const errorMessage = (error: unknown) => error instanceof Error ? error.message : "Something went wrong.";

function isToday(value?: string | null) {
  if (!value) return false;
  const date = new Date(value);
  const now = new Date();
  return date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate();
}

function initials(name: string) {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase() ?? "").join("") || "D";
}

export default function NowScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ live?: string }>();
  const missionsQuery = useMissions({ sort: "updated" });
  const profileQuery = useUserProfile();
  const settingsQuery = useUserSettings();
  const createText = useCreateTextMission();
  const createVoice = useCreateVoiceMission();
  const voice = useVoiceStore();
  const [composerOpen, setComposerOpen] = useState(false);
  const [liveVoiceOpen, setLiveVoiceOpen] = useState(false);
  const handledLiveLink = useRef(false);
  const [composerError, setComposerError] = useState<string | null>(null);
  const usingFallback = demoFallbackEnabled && missionsQuery.isError;
  const missions = missionsQuery.data?.items ?? (usingFallback ? fallbackMissions : []);
  const active = missions.filter((item) => !["completed", "cancelled", "failed"].includes(item.status));
  const completed = missions.filter((item) => item.status === "completed" && isToday(item.completed_at));
  const profileName = profileQuery.data?.name.trim() || "there";
  const firstName = profileName.split(/\s+/)[0] ?? profileName;

  useEffect(() => {
    if (params.live === "1" && !handledLiveLink.current) {
      handledLiveLink.current = true;
      setLiveVoiceOpen(true);
    }
    if (params.live !== "1") handledLiveLink.current = false;
  }, [params.live]);

  const openMission = (id: string) => router.push(`/mission/${id}`);

  const speakConfirmation = (message?: string) => {
    if (settingsQuery.data?.confirmation_voice_enabled === false) return;
    void Speech.speak(message || "I understood your mission. I’ll take care of it.", {
      rate: 0.98,
      language: settingsQuery.data?.voice_language || profileQuery.data?.locale || "en-PL",
    });
  };

  const submitText = async (transcript: string) => {
    setComposerError(null);
    try {
      const result = await createText.mutateAsync({
        transcript,
        locale: profileQuery.data?.locale,
        timezone: profileQuery.data?.timezone,
      });
      setComposerOpen(false);
      speakConfirmation(result.confirmation);
      openMission(result.mission_id);
    } catch (error) {
      setComposerError(errorMessage(error));
    }
  };

  const submitVoice = async (audioUri: string | null) => {
    if (!audioUri) {
      voice.setError("The recording could not be saved. Tap below to type your mission instead.");
      return;
    }
    voice.setSubmitting(true);
    voice.setError(null);
    try {
      const result = await createVoice.mutateAsync({
        audioUri,
        locale: profileQuery.data?.locale || "en-PL",
        timezone: profileQuery.data?.timezone || "Europe/Warsaw",
        language: settingsQuery.data?.voice_language || profileQuery.data?.locale || "en-PL",
      });
      voice.setTranscript(result.transcript ?? "");
      speakConfirmation(result.confirmation);
      openMission(result.mission_id);
    } catch (error) {
      voice.setError(errorMessage(error));
    } finally {
      voice.setSubmitting(false);
    }
  };

  const submitLive = async (transcript: string) => {
    setComposerError(null);
    return createText.mutateAsync({
      transcript,
      locale: profileQuery.data?.locale,
      timezone: profileQuery.data?.timezone,
    });
  };

  return (
    <AppScreen testID="now-screen">
      <View style={styles.greetingRow}>
        <View style={styles.greetingText}>
          <Text style={styles.greeting}>Good morning,</Text>
          <Text numberOfLines={1} style={styles.name}>{firstName}</Text>
          <Text style={styles.prompt}>What should I take care of?</Text>
        </View>
        <Pressable accessibilityRole="button" accessibilityLabel="Open profile" onPress={() => router.push("/profile")} style={({ pressed }) => [styles.avatarRing, pressed && styles.pressed]} testID="open-profile">
          <View style={styles.avatar}><Text style={styles.avatarText}>{initials(profileName)}</Text></View>
          <View style={styles.onlineDot} />
        </Pressable>
      </View>

      {usingFallback ? (
        <View style={styles.offlinePill}><WifiOff size={13} color={colors.warning} /><Text style={styles.offlineText}>Explicit demo fallback data</Text></View>
      ) : null}
      {missionsQuery.isError && !usingFallback ? (
        <View style={styles.notice}><InlineError message={errorMessage(missionsQuery.error)} onRetry={() => void missionsQuery.refetch()} /></View>
      ) : null}

      <VoiceOrb
        onTap={() => setLiveVoiceOpen(true)}
        onType={() => { setComposerError(null); setComposerOpen(true); }}
        onRecorded={submitVoice}
      />

      {missionsQuery.isLoading ? <ScreenState loading title="Loading your missions…" /> : (
        <>
          <View style={styles.section}>
            <SectionHeader title="Active missions" count={active.length} onPress={() => router.push("/missions")} />
            {active.length ? (
              <View style={styles.cardList}>
                {active.slice(0, 2).map((mission) => <MissionCard key={mission.id} mission={mission} compact onPress={() => openMission(mission.id)} />)}
              </View>
            ) : (
              <View style={styles.emptyComplete}><View style={styles.emptyCheck}><ListTodo color={colors.primaryBright} size={18} /></View><Text style={styles.emptyText}>No active missions. Add one above when you’re ready.</Text></View>
            )}
          </View>

          <View style={styles.section}>
            <SectionHeader title="Completed today" onPress={() => router.push("/completed")} />
            {completed[0] ? (
              <MissionCard mission={completed[0]} compact completed onPress={() => openMission(completed[0]!.id)} />
            ) : (
              <View style={styles.emptyComplete}><View style={styles.emptyCheck}><Check color={colors.success} size={18} /></View><Text style={styles.emptyText}>Completed missions will show up here.</Text></View>
            )}
          </View>
        </>
      )}

      <MissionComposer visible={composerOpen} loading={createText.isPending} error={composerError} onClose={() => setComposerOpen(false)} onSubmit={submitText} />
      <LiveVoiceSheet
        visible={liveVoiceOpen}
        language={settingsQuery.data?.voice_language || profileQuery.data?.locale || "pl-PL"}
        onClose={() => setLiveVoiceOpen(false)}
        onUseText={() => { setComposerError(null); setComposerOpen(true); }}
        onSubmitTranscript={submitLive}
        onOpenMission={openMission}
      />
    </AppScreen>
  );
}

const styles = StyleSheet.create({
  greetingRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: spacing.md },
  greetingText: { flex: 1 },
  greeting: { ...type.h2, fontWeight: "400", color: colors.textSecondary },
  name: { ...type.display, color: colors.text, marginTop: 2 },
  prompt: { ...type.body, color: colors.textSecondary, marginTop: spacing.sm },
  avatarRing: { width: 60, height: 60, borderRadius: 30, borderWidth: 2, borderColor: colors.primarySoft, padding: 3 },
  avatar: { flex: 1, borderRadius: 26, backgroundColor: "#272B43", alignItems: "center", justifyContent: "center" },
  avatarText: { ...type.h3, color: colors.text },
  onlineDot: { position: "absolute", width: 11, height: 11, borderRadius: 6, backgroundColor: colors.success, right: 0, bottom: 3, borderWidth: 2, borderColor: colors.background },
  pressed: { opacity: 0.68 },
  offlinePill: { alignSelf: "center", flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 6, paddingHorizontal: spacing.sm, marginTop: spacing.md, backgroundColor: "rgba(255,184,77,0.08)", borderRadius: radii.round },
  offlineText: { ...type.caption, color: colors.warning },
  notice: { marginTop: spacing.md },
  section: { marginTop: spacing.lg },
  cardList: { gap: spacing.sm },
  emptyComplete: { minHeight: 80, flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.md, borderWidth: 1, borderColor: colors.hairline, borderRadius: radii.lg },
  emptyCheck: { width: 42, height: 42, borderRadius: 21, backgroundColor: "rgba(72,214,106,0.1)", alignItems: "center", justifyContent: "center" },
  emptyText: { ...type.small, color: colors.textSecondary, flex: 1 },
});
