import type { ApiEvent, MissionDetail, MissionSummary } from "./types";

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://127.0.0.1:8001";

export interface EventsPage {
  events: ApiEvent[];
  cursor: number;
  mission_status: string;
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    signal: AbortSignal.timeout(2500),
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`GET ${path} -> ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function fetchMissions(): Promise<MissionSummary[]> {
  const page = await get<{ missions: MissionSummary[] }>("/v1/missions?sort=updated");
  return page.missions;
}

export async function fetchEvents(missionId: string, afterId: number): Promise<EventsPage> {
  return get<EventsPage>(`/v1/missions/${missionId}/events?after_id=${afterId}`);
}

export async function fetchMissionDetail(missionId: string): Promise<MissionDetail> {
  return get<MissionDetail>(`/v1/missions/${missionId}`);
}
