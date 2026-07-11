import { Platform } from "react-native";
import * as Notifications from "expo-notifications";
import type { MissionNotification } from "@/notifications/notifications.types";

export type { MissionNotification } from "@/notifications/notifications.types";

const CHANNEL_ID = "mission-updates";

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

async function configureAndroidChannel(): Promise<void> {
  if (Platform.OS !== "android") return;
  await Notifications.setNotificationChannelAsync(CHANNEL_ID, {
    name: "Mission updates",
    description: "Approvals, recovery events and completed Done missions",
    importance: Notifications.AndroidImportance.HIGH,
    vibrationPattern: [0, 220, 120, 220],
    lightColor: "#9B5CFF",
  });
}

export async function ensureNotificationPermission(): Promise<boolean> {
  await configureAndroidChannel();
  const current = await Notifications.getPermissionsAsync();
  if (current.granted) return true;
  if (!current.canAskAgain) return false;
  const requested = await Notifications.requestPermissionsAsync();
  return requested.granted;
}

export async function scheduleMissionNotification(notification: MissionNotification): Promise<void> {
  const current = await Notifications.getPermissionsAsync();
  if (!current.granted) return;
  await configureAndroidChannel();
  await Notifications.scheduleNotificationAsync({
    content: {
      title: notification.title,
      body: notification.message,
      sound: "default",
      data: {
        mission_id: notification.missionId,
        status: notification.status,
      },
    },
    trigger: Platform.OS === "android" ? { channelId: CHANNEL_ID } : null,
  });
}

function missionIdFromResponse(response: Notifications.NotificationResponse | null): string | null {
  const missionId = response?.notification.request.content.data?.mission_id;
  return typeof missionId === "string" && missionId ? missionId : null;
}

export function subscribeToNotificationMissions(listener: (missionId: string) => void): () => void {
  const subscription = Notifications.addNotificationResponseReceivedListener((response) => {
    const missionId = missionIdFromResponse(response);
    if (missionId) listener(missionId);
  });
  return () => subscription.remove();
}

export async function getInitialNotificationMission(): Promise<string | null> {
  const response = await Notifications.getLastNotificationResponseAsync();
  const missionId = missionIdFromResponse(response);
  if (response) await Notifications.clearLastNotificationResponseAsync();
  return missionId;
}
