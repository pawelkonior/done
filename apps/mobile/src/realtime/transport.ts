import type { RealtimeTransportFactory } from "@/realtime/transport.types";

// Metro resolves transport.web.ts or transport.native.ts before this file.
// This fallback keeps TypeScript resolution explicit for unsupported targets.
export const createRealtimeTransport: RealtimeTransportFactory = () => ({
  async connect() {
    throw new Error("Live voice is not supported on this platform.");
  },
  send() {
    throw new Error("Live voice is not connected.");
  },
  disconnect() {},
});
