import { useEffect, useRef, useState } from "react";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Check, ListTodo } from "lucide-react-native";
import { Image, Pressable, StyleSheet, Text, View } from "react-native";
import * as Speech from "expo-speech";
import { AppScreen } from "@/components/AppScreen";
import { MissionCard } from "@/components/MissionCard";
import { LiveVoiceSheet } from "@/components/LiveVoiceSheet";
import { InlineError, ScreenState } from "@/components/ScreenState";
import { SectionHeader } from "@/components/SectionHeader";
import { VoiceOrb } from "@/components/VoiceOrb";
import { useCreateVoiceMission, useCreateVoiceTranscriptMission, useMissions, useUserProfile, useUserSettings } from "@/api/hooks";
import { useVoiceStore } from "@/store/voice";
import { colors, radii, spacing, type } from "@/theme/tokens";

const errorMessage = (error: unknown) => error instanceof Error ? error.message : "Something went wrong.";

function isToday(value?: string | null) {
  if (!value) return false;
  const date = new Date(value);
  const now = new Date();
  return date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate();
}

export default function NowScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ live?: string }>();
  const missionsQuery = useMissions({ sort: "updated" });
  const profileQuery = useUserProfile();
  const settingsQuery = useUserSettings();
  const createVoiceTranscript = useCreateVoiceTranscriptMission();
  const createVoice = useCreateVoiceMission();
  const voice = useVoiceStore();
  const [liveVoiceOpen, setLiveVoiceOpen] = useState(false);
  const handledLiveLink = useRef(false);
  const missions = missionsQuery.data?.items ?? [];
  const active = missions.filter((item) => !["completed", "cancelled", "failed"].includes(item.status));
  const completed = missions.filter((item) => item.status === "completed" && isToday(item.completed_at));

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

  const submitVoice = async (audioUri: string | null) => {
    if (!audioUri) {
      voice.setError("The recording could not be saved. Please try again.");
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
    return createVoiceTranscript.mutateAsync({
      transcript,
      locale: profileQuery.data?.locale,
      timezone: profileQuery.data?.timezone,
    });
  };

  return (
    <AppScreen testID="now-screen">
      <View style={styles.topBar}>
        <View style={styles.brand}>
          <Image source={require("../../assets/icon.png")} style={styles.brandMark} />
          <Text style={styles.brandName}>Done</Text>
        </View>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Open profile"
          onPress={() => router.push("/profile")}
          style={({ pressed }) => [styles.avatarRing, pressed && styles.pressed]}
          testID="open-profile"
        >
          <Image source={require("../../assets/profile-pawel.jpeg")} resizeMode="cover" style={styles.avatar} />
        </Pressable>
      </View>

      {missionsQuery.isError ? (
        <View style={styles.notice}><InlineError message={errorMessage(missionsQuery.error)} onRetry={() => void missionsQuery.refetch()} /></View>
      ) : null}

      <VoiceOrb
        onTap={() => setLiveVoiceOpen(true)}
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
              <View style={styles.emptyComplete}><View style={styles.emptyCheck}><ListTodo color={colors.primaryBright} size={18} /></View><Text style={styles.emptyText}>No active missions.</Text></View>
            )}
          </View>

          <View style={styles.section}>
            <SectionHeader title="Completed today" onPress={() => router.push("/completed")} />
            {completed[0] ? (
              <MissionCard mission={completed[0]} compact completed onPress={() => openMission(completed[0]!.id)} />
            ) : (
              <View style={styles.emptyComplete}><View style={styles.emptyCheck}><Check color={colors.success} size={18} /></View><Text style={styles.emptyText}>Nothing completed today.</Text></View>
            )}
          </View>
        </>
      )}

      <LiveVoiceSheet
        visible={liveVoiceOpen}
        language={settingsQuery.data?.voice_language || profileQuery.data?.locale || "pl-PL"}
        onClose={() => setLiveVoiceOpen(false)}
        onSubmitTranscript={submitLive}
        onMissionCreated={(missionId) => {
          setLiveVoiceOpen(false);
          openMission(missionId);
        }}
      />
    </AppScreen>
  );
}

const styles = StyleSheet.create({
  topBar: { minHeight: 52, flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.md },
  brand: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  brandMark: { width: 40, height: 40, borderRadius: 12 },
  brandName: { ...type.h3, color: colors.text, letterSpacing: -0.3 },
  avatarRing: { width: 44, height: 44, borderRadius: 22, borderWidth: 1, borderColor: colors.borderStrong, padding: 3 },
  avatar: { flex: 1, width: "100%", borderRadius: 18, backgroundColor: colors.surfaceElevated },
  pressed: { opacity: 0.68 },
  notice: { marginTop: spacing.md },
  section: { marginTop: spacing.lg },
  cardList: { gap: spacing.sm },
  emptyComplete: { minHeight: 80, flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.md, borderWidth: 1, borderColor: colors.hairline, borderRadius: radii.lg },
  emptyCheck: { width: 42, height: 42, borderRadius: 21, backgroundColor: "rgba(72,214,106,0.1)", alignItems: "center", justifyContent: "center" },
  emptyText: { ...type.small, color: colors.textSecondary, flex: 1 },
});
