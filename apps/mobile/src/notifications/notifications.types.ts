import type { MissionStatus } from "@/types/domain";

export interface MissionNotification {
  missionId: string;
  title: string;
  message: string;
  status: MissionStatus;
}
