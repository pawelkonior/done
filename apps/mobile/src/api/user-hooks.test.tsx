import type { PropsWithChildren } from "react";
import { act, renderHook, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  getUserProfile,
  getUserSettings,
  updateUserProfile,
  updateUserSettings,
} from "@/api/client";
import {
  useUpdateUserProfile,
  useUpdateUserSettings,
  useUserProfile,
  useUserSettings,
  userProfileQueryKey,
  userSettingsQueryKey,
} from "@/api/hooks";
import type { UserProfile, UserSettings } from "@/types/domain";

jest.mock("@/api/client", () => ({
  createTextMission: jest.fn(),
  createVoiceMission: jest.fn(),
  getMission: jest.fn(),
  listMissions: jest.fn(),
  resetDemo: jest.fn(),
  resolveApproval: jest.fn(),
  getUserDataExport: jest.fn(),
  getUserProfile: jest.fn(),
  getUserSettings: jest.fn(),
  listMerchants: jest.fn(),
  updateUserProfile: jest.fn(),
  updateUserSettings: jest.fn(),
}));

const settings: UserSettings = {
  voice_language: "en-PL",
  confirmation_voice_enabled: true,
  safe_recovery_enabled: true,
  approval_policy: "always",
  approval_threshold: 100,
  notifications_enabled: true,
  preferred_merchant_ids: ["merchant-a"],
};

const profile: UserProfile = {
  id: "demo-user",
  name: "Paweł K.",
  email: "demo@done.app",
  locale: "pl-PL",
  currency: "PLN",
  timezone: "Europe/Warsaw",
  autonomy_level: "balanced",
  delivery_address: { label: "Home", line1: "Prosta 20", city: "Warsaw", postal_code: "00-001", country: "PL" },
  payment_method: { token: "tok_demo", brand: "Visa", last4: "4242", expiry_month: 12, expiry_year: 2030, is_demo: true },
  default_constraints: ["No nuts"],
  contact_preference: "only_when_needed",
  stats: { missions: 4, recoveries: 2, saved: 50 },
};

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const wrapper = ({ children }: PropsWithChildren) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  return { client, wrapper };
}

describe("user API hooks", () => {
  beforeEach(() => jest.clearAllMocks());

  it("loads profile and settings into separate query caches", async () => {
    jest.mocked(getUserProfile).mockResolvedValue(profile);
    jest.mocked(getUserSettings).mockResolvedValue(settings);
    const { client, wrapper } = setup();
    const profileHook = await renderHook(() => useUserProfile(), { wrapper });
    await waitFor(() => expect(profileHook.result.current.isSuccess).toBe(true));
    const settingsHook = await renderHook(() => useUserSettings(), { wrapper });

    await waitFor(() => expect(settingsHook.result.current.isSuccess).toBe(true));

    expect(client.getQueryData(userProfileQueryKey)).toEqual(profile);
    expect(client.getQueryData(userSettingsQueryKey)).toEqual(settings);
    await profileHook.unmount();
    await settingsHook.unmount();
    client.clear();
  });

  it("persists settings and profile mutations and updates cached values", async () => {
    const { client, wrapper } = setup();
    client.setQueryData(userSettingsQueryKey, settings);
    client.setQueryData(userProfileQueryKey, profile);
    jest.mocked(updateUserSettings).mockResolvedValue({ ...settings, notifications_enabled: false });
    jest.mocked(updateUserProfile).mockResolvedValue({
      ...profile,
      delivery_address: { ...profile.delivery_address, city: "Kraków" },
    });
    const settingsMutation = await renderHook(() => useUpdateUserSettings(), { wrapper });
    const profileMutation = await renderHook(() => useUpdateUserProfile(), { wrapper });

    await act(async () => {
      await settingsMutation.result.current.mutateAsync({ notifications_enabled: false });
      await profileMutation.result.current.mutateAsync({ delivery_address: { city: "Kraków" } });
    });

    expect(updateUserSettings).toHaveBeenCalledWith({ notifications_enabled: false });
    expect(updateUserProfile).toHaveBeenCalledWith({ delivery_address: { city: "Kraków" } });
    expect(client.getQueryData<UserSettings>(userSettingsQueryKey)?.notifications_enabled).toBe(false);
    expect(client.getQueryData<UserProfile>(userProfileQueryKey)?.delivery_address.city).toBe("Kraków");
    await settingsMutation.unmount();
    await profileMutation.unmount();
    client.clear();
  });
});
