import type { MissionNotification } from "@/notifications/notifications.types";

export type { MissionNotification } from "@/notifications/notifications.types";

export async function ensureNotificationPermission(): Promise<boolean> {
  return false;
}

export async function scheduleMissionNotification(_: MissionNotification): Promise<void> {}

export function subscribeToNotificationMissions(_: (missionId: string) => void): () => void {
  return () => undefined;
}

export async function getInitialNotificationMission(): Promise<string | null> {
  return null;
}
