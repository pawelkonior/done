import { useCallback, useEffect, useRef } from "react";
import { AudioModule, RecordingPresets, setAudioModeAsync, useAudioRecorder } from "expo-audio";
import * as Haptics from "expo-haptics";
import { useVoiceStore } from "@/store/voice";

export function useVoiceCapture() {
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const startedAt = useRef(0);
  const store = useVoiceStore();

  const clearTimer = useCallback(() => {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
  }, []);

  useEffect(() => () => {
    clearTimer();
    if (useVoiceStore.getState().isRecording) {
      void recorder.stop().catch(() => undefined);
      useVoiceStore.getState().reset();
    }
  }, [clearTimer, recorder]);

  const start = useCallback(async () => {
    try {
      store.setError(null);
      const permission = await AudioModule.requestRecordingPermissionsAsync();
      if (!permission.granted) throw new Error("Microphone access is needed to hear your mission.");
      await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
      await recorder.prepareToRecordAsync();
      recorder.record();
      startedAt.current = Date.now();
      store.setRecording(true);
      store.setDuration(0);
      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
      timer.current = setInterval(() => {
        store.setDuration(Math.floor((Date.now() - startedAt.current) / 1000));
      }, 250);
      return true;
    } catch (error) {
      store.setError(error instanceof Error ? error.message : "Could not start recording.");
      store.setRecording(false);
      clearTimer();
      return false;
    }
  }, [clearTimer, recorder, store]);

  const stop = useCallback(async () => {
    clearTimer();
    try {
      await recorder.stop();
      const uri = recorder.uri ?? null;
      store.setAudioUri(uri);
      store.setRecording(false);
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      return uri;
    } catch (error) {
      store.setError(error instanceof Error ? error.message : "Could not finish recording.");
      store.setRecording(false);
      return null;
    }
  }, [clearTimer, recorder, store]);

  const cancel = useCallback(async () => {
    clearTimer();
    try {
      if (store.isRecording) await recorder.stop();
    } catch {
      // The recorder may already have stopped after a platform interruption.
    }
    store.reset();
  }, [clearTimer, recorder, store]);

  return { start, stop, cancel };
}
