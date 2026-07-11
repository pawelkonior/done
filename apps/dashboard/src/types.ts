export type NodeId =
  | "intake"
  | "contract"
  | "snapshot"
  | "model"
  | "guardrails"
  | "purchase"
  | "result";

export interface LoopEvent {
  type: string;
  title: string;
  severity: string;
  created_at: string;
}

export interface ApiEvent extends LoopEvent {
  id: number;
  actor: string;
  description: string;
}

export interface MissionSummary {
  id: string;
  title: string;
  status: string;
  created_at: string;
}
