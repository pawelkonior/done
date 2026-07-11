import { useEffect, useRef } from "react";
import { useRouter } from "expo-router";
import { useMissions, useUserSettings } from "@/api/hooks";
import {
  ensureNotificationPermission,
  getInitialNotificationMission,
  scheduleMissionNotification,
  subscribeToNotificationMissions,
} from "@/notifications/notifications";
import type { MissionStatus, MissionSummary } from "@/types/domain";

const notificationStatuses = new Set<MissionStatus>([
  "approval_required",
  "clarification_required",
  "waiting_for_user",
  "waiting_for_support",
  "recovering",
  "completed",
  "failed",
]);

function notificationCopy(mission: MissionSummary): { title: string; message: string } {
  switch (mission.status) {
    case "approval_required":
      return { title: `${mission.title} needs your decision`, message: mission.latest_update };
    case "clarification_required":
    case "waiting_for_user":
      return { title: `${mission.title} needs an answer`, message: mission.latest_update };
    case "waiting_for_support":
      return { title: `Human support is reviewing ${mission.title}`, message: mission.latest_update };
    case "recovering":
      return { title: `Done is recovering ${mission.title}`, message: mission.latest_update };
    case "completed":
      return { title: `${mission.title} is complete`, message: mission.latest_update };
    case "failed":
      return { title: `${mission.title} needs attention`, message: mission.latest_update };
    default:
      return { title: mission.title, message: mission.latest_update };
  }
}

export function MissionNotificationBridge() {
  const router = useRouter();
  const settings = useUserSettings();
  const missions = useMissions({ sort: "updated" });
  const previousStatuses = useRef(new Map<string, MissionStatus>());
  const initialized = useRef(false);

  useEffect(() => {
    const openMission = (missionId: string) => router.push(`/mission/${missionId}`);
    const unsubscribe = subscribeToNotificationMissions(openMission);
    void getInitialNotificationMission().then((missionId) => {
      if (missionId) openMission(missionId);
    });
    return unsubscribe;
  }, [router]);

  useEffect(() => {
    if (settings.data?.notifications_enabled) {
      void ensureNotificationPermission();
    }
  }, [settings.data?.notifications_enabled]);

  useEffect(() => {
    const items = missions.data?.items;
    if (!items) return;
    if (!initialized.current) {
      for (const mission of items) previousStatuses.current.set(mission.id, mission.status);
      initialized.current = true;
      return;
    }
    for (const mission of items) {
      const previous = previousStatuses.current.get(mission.id);
      previousStatuses.current.set(mission.id, mission.status);
      if (
        settings.data?.notifications_enabled
        && previous
        && previous !== mission.status
        && notificationStatuses.has(mission.status)
      ) {
        const copy = notificationCopy(mission);
        void scheduleMissionNotification({
          missionId: mission.id,
          title: copy.title,
          message: copy.message,
          status: mission.status,
        });
      }
    }
  }, [missions.data?.items, settings.data?.notifications_enabled]);

  return null;
}
