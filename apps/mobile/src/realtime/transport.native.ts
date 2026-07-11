import Constants, { ExecutionEnvironment } from "expo-constants";
import type {
  RealtimeTransport,
  RealtimeTransportCallbacks,
  RealtimeTransportFactory,
} from "@/realtime/transport.types";

type NativeWebRTC = typeof import("react-native-webrtc");
type NativePeer = InstanceType<NativeWebRTC["RTCPeerConnection"]>;
type NativeStream = InstanceType<NativeWebRTC["MediaStream"]>;
type NativeChannel = ReturnType<NativePeer["createDataChannel"]>;

interface NativeEventSource {
  addEventListener: (
    type: string,
    listener: (event: { data?: unknown }) => void,
    options?: { once?: boolean },
  ) => void;
}

const eventSource = (value: unknown) => value as NativeEventSource;

const OPENAI_REALTIME_CALLS_URL = "https://api.openai.com/v1/realtime/calls";
const CONNECTION_TIMEOUT_MS = 20_000;

function connectionError(error: unknown): Error {
  const name = error && typeof error === "object" && "name" in error
    ? String((error as { name?: unknown }).name)
    : "";
  const message = error instanceof Error ? error.message : "";
  if (
    name === "NotAllowedError"
    || name === "SecurityError"
    || /permission|not authorized/i.test(message)
  ) {
    return new Error("Microphone access is blocked. Allow microphone access in system settings and try again.");
  }
  if (name === "NotFoundError" || /no.*(microphone|audio device)/i.test(message)) {
    return new Error("No microphone is available on this device.");
  }
  if (name === "AbortError") return new Error("Live voice negotiation timed out. Check your connection and try again.");
  if (error instanceof Error && !["TypeError", "NetworkError"].includes(name)) return error;
  return new Error("Live voice could not reach the voice service. Check your internet connection and try again.");
}

function waitForDataChannel(channel: NativeChannel): Promise<void> {
  if (channel.readyState === "open") return Promise.resolve();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("Live voice connection timed out.")), CONNECTION_TIMEOUT_MS);
    eventSource(channel).addEventListener("open", () => {
      clearTimeout(timer);
      resolve();
    }, { once: true });
    eventSource(channel).addEventListener("error", () => {
      clearTimeout(timer);
      reject(new Error("The live voice data channel could not be opened."));
    }, { once: true });
  });
}

function requestMicrophone(webrtc: NativeWebRTC): Promise<NativeStream> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      settled = true;
      reject(new Error("Microphone permission timed out. Allow microphone access in system settings and try again."));
    }, CONNECTION_TIMEOUT_MS);
    webrtc.mediaDevices.getUserMedia({ audio: true, video: false }).then((stream) => {
      clearTimeout(timer);
      if (settled) {
        for (const track of stream.getTracks()) track.stop();
        return;
      }
      settled = true;
      resolve(stream);
    }, (error: unknown) => {
      clearTimeout(timer);
      if (settled) return;
      settled = true;
      reject(error);
    });
  });
}

class NativeRealtimeTransport implements RealtimeTransport {
  private peer: NativePeer | null = null;
  private channel: NativeChannel | null = null;
  private localStream: NativeStream | null = null;
  private negotiationAbort: AbortController | null = null;
  private generation = 0;

  constructor(private readonly callbacks: RealtimeTransportCallbacks) {}

  async connect(ephemeralSecret: string): Promise<void> {
    if (Constants.executionEnvironment === ExecutionEnvironment.StoreClient) {
      throw new Error("Live voice requires the Done development or production build, not Expo Go.");
    }
    this.disconnect();
    const generation = this.generation;
    this.callbacks.onStateChange("connecting");
    try {
      const webrtc = await import("react-native-webrtc");
      const peer = new webrtc.RTCPeerConnection();
      this.peer = peer;
      eventSource(peer).addEventListener("connectionstatechange", () => {
        if (peer.connectionState === "connected") this.callbacks.onStateChange("connected");
        if (["failed", "closed"].includes(peer.connectionState)) {
          this.callbacks.onStateChange(peer.connectionState === "failed" ? "failed" : "disconnected");
        }
      });

      // Native WebRTC routes remote audio tracks through the platform audio session.
      eventSource(peer).addEventListener("track", () => undefined);
      const stream = await requestMicrophone(webrtc);
      if (generation !== this.generation) {
        for (const track of stream.getTracks()) track.stop();
        throw new Error("Live voice connection was closed.");
      }
      this.localStream = stream;
      for (const track of stream.getAudioTracks()) peer.addTrack(track, stream);

      const channel = peer.createDataChannel("oai-events");
      this.channel = channel;
      eventSource(channel).addEventListener("message", (message) => {
        if (typeof message.data !== "string") return;
        try {
          this.callbacks.onEvent(JSON.parse(message.data));
        } catch {
          this.callbacks.onError(new Error("Live voice returned an unreadable event."));
        }
      });

      const offer = await peer.createOffer({ offerToReceiveAudio: true });
      await peer.setLocalDescription(offer);
      const negotiationAbort = new AbortController();
      this.negotiationAbort = negotiationAbort;
      const negotiationTimeout = setTimeout(
        () => negotiationAbort.abort(),
        CONNECTION_TIMEOUT_MS,
      );
      let sdpResponse: Response;
      try {
        sdpResponse = await fetch(OPENAI_REALTIME_CALLS_URL, {
          method: "POST",
          body: offer.sdp,
          signal: negotiationAbort.signal,
          headers: {
            Authorization: `Bearer ${ephemeralSecret}`,
            "Content-Type": "application/sdp",
          },
        });
      } finally {
        clearTimeout(negotiationTimeout);
        if (this.negotiationAbort === negotiationAbort) this.negotiationAbort = null;
      }
      if (!sdpResponse.ok) {
        throw new Error(`Live voice negotiation failed (${sdpResponse.status}).`);
      }
      await peer.setRemoteDescription(
        new webrtc.RTCSessionDescription({ type: "answer", sdp: await sdpResponse.text() }),
      );
      await waitForDataChannel(channel);
      this.callbacks.onStateChange("connected");
    } catch (error) {
      this.disconnect();
      this.callbacks.onStateChange("failed");
      const safeError = connectionError(error);
      this.callbacks.onError(safeError);
      throw safeError;
    }
  }

  send(event: Record<string, unknown>): void {
    if (this.channel?.readyState !== "open") throw new Error("Live voice is not connected.");
    this.channel.send(JSON.stringify(event));
  }

  disconnect(): void {
    this.generation += 1;
    this.negotiationAbort?.abort();
    this.negotiationAbort = null;
    this.channel?.close();
    this.channel = null;
    for (const track of this.localStream?.getTracks() ?? []) track.stop();
    this.localStream = null;
    this.peer?.close();
    this.peer = null;
  }
}

export const createRealtimeTransport: RealtimeTransportFactory = (callbacks) =>
  new NativeRealtimeTransport(callbacks);
