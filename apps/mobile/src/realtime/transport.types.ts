export type RealtimeConnectionState =
  | "idle"
  | "connecting"
  | "connected"
  | "disconnected"
  | "failed";

export interface RealtimeTransportCallbacks {
  onStateChange: (state: RealtimeConnectionState) => void;
  onEvent: (event: unknown) => void;
  onError: (error: Error) => void;
}

export interface RealtimeTransport {
  connect: (ephemeralSecret: string) => Promise<void>;
  send: (event: Record<string, unknown>) => void;
  disconnect: () => void;
}

export type RealtimeTransportFactory = (
  callbacks: RealtimeTransportCallbacks,
) => RealtimeTransport;
