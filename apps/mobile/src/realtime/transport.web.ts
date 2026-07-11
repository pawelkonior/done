import type {
  RealtimeTransport,
  RealtimeTransportCallbacks,
  RealtimeTransportFactory,
} from "@/realtime/transport.types";

const OPENAI_REALTIME_CALLS_URL = "https://api.openai.com/v1/realtime/calls";
const CONNECTION_TIMEOUT_MS = 20_000;

function waitForDataChannel(channel: RTCDataChannel): Promise<void> {
  if (channel.readyState === "open") return Promise.resolve();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("Live voice connection timed out.")), CONNECTION_TIMEOUT_MS);
    channel.addEventListener("open", () => {
      clearTimeout(timer);
      resolve();
    }, { once: true });
    channel.addEventListener("error", () => {
      clearTimeout(timer);
      reject(new Error("The live voice data channel could not be opened."));
    }, { once: true });
  });
}

class WebRealtimeTransport implements RealtimeTransport {
  private peer: RTCPeerConnection | null = null;
  private channel: RTCDataChannel | null = null;
  private localStream: MediaStream | null = null;
  private remoteAudio: HTMLAudioElement | null = null;

  constructor(private readonly callbacks: RealtimeTransportCallbacks) {}

  async connect(ephemeralSecret: string): Promise<void> {
    if (!navigator.mediaDevices?.getUserMedia || typeof RTCPeerConnection === "undefined") {
      throw new Error("This browser does not support microphone WebRTC sessions.");
    }
    this.disconnect();
    this.callbacks.onStateChange("connecting");
    try {
      const peer = new RTCPeerConnection();
      this.peer = peer;
      peer.addEventListener("connectionstatechange", () => {
        if (peer.connectionState === "connected") this.callbacks.onStateChange("connected");
        if (["failed", "closed"].includes(peer.connectionState)) {
          this.callbacks.onStateChange(peer.connectionState === "failed" ? "failed" : "disconnected");
        }
      });

      const audio = document.createElement("audio");
      audio.autoplay = true;
      audio.setAttribute("playsinline", "true");
      this.remoteAudio = audio;
      peer.addEventListener("track", (event) => {
        const [stream] = event.streams;
        if (stream) audio.srcObject = stream;
      });

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        video: false,
      });
      this.localStream = stream;
      for (const track of stream.getAudioTracks()) peer.addTrack(track, stream);

      const channel = peer.createDataChannel("oai-events");
      this.channel = channel;
      channel.addEventListener("message", (message) => {
        if (typeof message.data !== "string") return;
        try {
          this.callbacks.onEvent(JSON.parse(message.data));
        } catch {
          this.callbacks.onError(new Error("Live voice returned an unreadable event."));
        }
      });

      const offer = await peer.createOffer();
      await peer.setLocalDescription(offer);
      const sdpResponse = await fetch(OPENAI_REALTIME_CALLS_URL, {
        method: "POST",
        body: offer.sdp,
        headers: {
          Authorization: `Bearer ${ephemeralSecret}`,
          "Content-Type": "application/sdp",
        },
      });
      if (!sdpResponse.ok) {
        throw new Error(`Live voice negotiation failed (${sdpResponse.status}).`);
      }
      await peer.setRemoteDescription({ type: "answer", sdp: await sdpResponse.text() });
      await waitForDataChannel(channel);
      this.callbacks.onStateChange("connected");
    } catch (error) {
      this.disconnect();
      this.callbacks.onStateChange("failed");
      const safeError = error instanceof Error ? error : new Error("Live voice could not start.");
      this.callbacks.onError(safeError);
      throw safeError;
    }
  }

  send(event: Record<string, unknown>): void {
    if (this.channel?.readyState !== "open") throw new Error("Live voice is not connected.");
    this.channel.send(JSON.stringify(event));
  }

  disconnect(): void {
    this.channel?.close();
    this.channel = null;
    for (const track of this.localStream?.getTracks() ?? []) track.stop();
    this.localStream = null;
    this.peer?.close();
    this.peer = null;
    if (this.remoteAudio) {
      this.remoteAudio.srcObject = null;
      this.remoteAudio.remove();
      this.remoteAudio = null;
    }
  }
}

export const createRealtimeTransport: RealtimeTransportFactory = (callbacks) =>
  new WebRealtimeTransport(callbacks);
