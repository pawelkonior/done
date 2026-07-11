import { create } from "zustand";

interface VoiceState {
  isRecording: boolean;
  isSubmitting: boolean;
  recordingDuration: number;
  audioUri: string | null;
  transcript: string;
  error: string | null;
  setRecording: (value: boolean) => void;
  setSubmitting: (value: boolean) => void;
  setDuration: (value: number) => void;
  setAudioUri: (value: string | null) => void;
  setTranscript: (value: string) => void;
  setError: (value: string | null) => void;
  reset: () => void;
}

export const useVoiceStore = create<VoiceState>((set) => ({
  isRecording: false,
  isSubmitting: false,
  recordingDuration: 0,
  audioUri: null,
  transcript: "",
  error: null,
  setRecording: (isRecording) => set({ isRecording }),
  setSubmitting: (isSubmitting) => set({ isSubmitting }),
  setDuration: (recordingDuration) => set({ recordingDuration }),
  setAudioUri: (audioUri) => set({ audioUri }),
  setTranscript: (transcript) => set({ transcript }),
  setError: (error) => set({ error }),
  reset: () =>
    set({
      isRecording: false,
      isSubmitting: false,
      recordingDuration: 0,
      audioUri: null,
      transcript: "",
      error: null,
    }),
}));

