import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  cancelMission,
  correctMission,
  createTextMission,
  createVoiceMission,
  getMission,
  getRuntimeCapabilities,
  getUserDataExport,
  getUserProfile,
  getUserSettings,
  listMissions,
  listMerchants,
  resetDemo,
  resolveApproval,
  selectDeliveryOption,
  updateUserProfile,
  updateUserSettings,
} from "@/api/client";
import type {
  DeliverySelectionInput,
  MissionCorrectionInput,
  MissionListFilters,
  MissionStatus,
  UserProfile,
  UserProfileUpdate,
  UserSettings,
  UserSettingsUpdate,
} from "@/types/domain";
import { isTerminal } from "@/lib/status";

export function useMissions(input?: MissionListFilters | MissionStatus | "active") {
  const filters: MissionListFilters = typeof input === "string" ? { status: input } : input ?? {};
  return useQuery({
    queryKey: ["missions", filters],
    queryFn: () => listMissions(filters),
    refetchInterval: (query) => {
      if (query.state.error || filters.status === "completed") return false;
      const items = query.state.data?.items;
      if (!items) return 2_000;
      return items.some((mission) => !isTerminal(mission.status)) ? 2_000 : false;
    },
    retry: 2,
  });
}

export function useMissionDetails(ids: string[]) {
  return useQueries({
    queries: ids.map((id) => ({
      queryKey: ["mission", id],
      queryFn: () => getMission(id),
      staleTime: 5_000,
      retry: 1,
    })),
  });
}

export function useMission(id?: string) {
  return useQuery({
    queryKey: ["mission", id],
    queryFn: () => getMission(id as string),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      if (query.state.error) return false;
      const status = query.state.data?.mission.status;
      if (!status || isTerminal(status)) return false;
      return 1_000;
    },
    retry: 2,
  });
}

export function useCreateTextMission() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: createTextMission,
    onSuccess: () => client.invalidateQueries({ queryKey: ["missions"] }),
  });
}

export function useCreateVoiceMission() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: createVoiceMission,
    onSuccess: () => client.invalidateQueries({ queryKey: ["missions"] }),
  });
}

export function useResolveApproval(missionId?: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ approvalId, choice }: { approvalId: string; choice: "approve" | "review" | "cancel" }) =>
      resolveApproval(approvalId, choice),
    onSuccess: (result) => {
      if (missionId) client.setQueryData(["mission", missionId], result.detail);
      client.invalidateQueries({ queryKey: ["mission", missionId] });
      client.invalidateQueries({ queryKey: ["missions"] });
    },
  });
}

function refreshMissionQueries(client: ReturnType<typeof useQueryClient>, missionId: string, detail?: unknown) {
  if (detail) client.setQueryData(["mission", missionId], detail);
  client.invalidateQueries({ queryKey: ["mission", missionId] });
  client.invalidateQueries({ queryKey: ["missions"] });
}

export function useCorrectMission(missionId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: MissionCorrectionInput) => correctMission(missionId, input),
    onSuccess: (detail) => refreshMissionQueries(client, missionId, detail),
  });
}

export function useSelectDeliveryOption(missionId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: DeliverySelectionInput) => selectDeliveryOption(missionId, input),
    onSuccess: (detail) => refreshMissionQueries(client, missionId, detail),
  });
}

export function useCancelMission(missionId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => cancelMission(missionId),
    onSuccess: (detail) => refreshMissionQueries(client, missionId, detail),
  });
}

export function useResetDemo() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: resetDemo,
    onSuccess: () => client.invalidateQueries(),
  });
}

export const userProfileQueryKey = ["user", "me", "profile"] as const;
export const userSettingsQueryKey = ["user", "me", "settings"] as const;
export const merchantsQueryKey = ["merchants"] as const;
export const userExportQueryKey = ["user", "me", "export"] as const;
export const runtimeCapabilitiesQueryKey = ["runtime", "capabilities"] as const;

export function useUserProfile() {
  return useQuery({
    queryKey: userProfileQueryKey,
    queryFn: getUserProfile,
    retry: 1,
  });
}

export function useUpdateUserProfile() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (update: UserProfileUpdate) => updateUserProfile(update),
    onMutate: async (update) => {
      await client.cancelQueries({ queryKey: userProfileQueryKey });
      const previous = client.getQueryData<UserProfile>(userProfileQueryKey);
      if (previous) {
        client.setQueryData<UserProfile>(userProfileQueryKey, {
          ...previous,
          ...update,
          delivery_address: update.delivery_address
            ? { ...previous.delivery_address, ...update.delivery_address }
            : previous.delivery_address,
          payment_method: update.payment_method
            ? { ...previous.payment_method, ...update.payment_method }
            : previous.payment_method,
        });
      }
      return { previous };
    },
    onError: (_error, _update, context) => {
      if (context?.previous) client.setQueryData(userProfileQueryKey, context.previous);
    },
    onSuccess: (profile) => client.setQueryData(userProfileQueryKey, profile),
    onSettled: () => client.invalidateQueries({ queryKey: userProfileQueryKey }),
  });
}

export function useUserSettings() {
  return useQuery({
    queryKey: userSettingsQueryKey,
    queryFn: getUserSettings,
    retry: 1,
  });
}

export function useUpdateUserSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (update: UserSettingsUpdate) => updateUserSettings(update),
    onMutate: async (update) => {
      await client.cancelQueries({ queryKey: userSettingsQueryKey });
      const previous = client.getQueryData<UserSettings>(userSettingsQueryKey);
      if (previous) client.setQueryData<UserSettings>(userSettingsQueryKey, { ...previous, ...update });
      return { previous };
    },
    onError: (_error, _update, context) => {
      if (context?.previous) client.setQueryData(userSettingsQueryKey, context.previous);
    },
    onSuccess: (settings) => client.setQueryData(userSettingsQueryKey, settings),
    onSettled: () => client.invalidateQueries({ queryKey: userSettingsQueryKey }),
  });
}

export function useMerchants() {
  return useQuery({
    queryKey: merchantsQueryKey,
    queryFn: listMerchants,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });
}

export function useUserDataExport(enabled = false) {
  return useQuery({
    queryKey: userExportQueryKey,
    queryFn: getUserDataExport,
    enabled,
    retry: 1,
  });
}

export function useRuntimeCapabilities() {
  return useQuery({
    queryKey: runtimeCapabilitiesQueryKey,
    queryFn: getRuntimeCapabilities,
    staleTime: 30_000,
    retry: 1,
  });
}
