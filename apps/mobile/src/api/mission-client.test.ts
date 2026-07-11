import {
  cancelMission,
  correctMission,
  createVoiceTranscriptMission,
  createVoiceMission,
  listMissions,
  replanMission,
  selectDeliveryOption,
} from "@/api/client";
import { File as ExpoFile } from "expo-file-system";

jest.mock("expo-file-system", () => ({
  File: jest.fn((uri: string) => {
    const file = new Blob(["audio"], { type: "audio/mp4" });
    Object.defineProperty(file, "uri", { value: uri });
    return file;
  }),
}));

const detail = {
  mission: {
    id: "mission-1",
    title: "Birthday party",
    subtitle: "Ready",
    status: "approval_required",
    current_step: 5,
    total_steps: 6,
    progress: 0.83,
    latest_update: "Ready",
    created_at: "2026-07-11T10:00:00Z",
    completed_at: null,
    revision: 3,
  },
  contract: null,
  basket: null,
  approval: null,
  events: [],
  metrics: {},
  delivery_options: [],
};

function response(body: unknown) {
  return { ok: true, status: 200, json: async () => body } as Response;
}

describe("mission API client", () => {
  const fetchMock = jest.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    jest.mocked(ExpoFile).mockClear();
    globalThis.fetch = fetchMock as typeof fetch;
  });

  it("uses the same mission for correction and sends the expected revision", async () => {
    fetchMock.mockResolvedValue(response(detail));
    const result = await correctMission("mission-1", { correction: "Increase budget", expected_revision: 2 });

    expect(result.mission.id).toBe("mission-1");
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/v1/missions/mission-1/corrections"),
      expect.objectContaining({ method: "POST", body: JSON.stringify({ correction: "Increase budget", expected_revision: 2 }) }),
    );
  });

  it("selects delivery, replans, and cancels with revision guards", async () => {
    fetchMock.mockResolvedValue(response(detail));
    await selectDeliveryOption("mission-1", { option_id: "standard", expected_revision: 2 });
    await replanMission("mission-1", 2);
    await cancelMission("mission-1", 2);

    expect(fetchMock.mock.calls[0]?.[1]).toEqual(expect.objectContaining({ method: "PUT", body: JSON.stringify({ option_id: "standard", expected_revision: 2 }) }));
    expect(fetchMock.mock.calls[1]?.[0]).toEqual(expect.stringContaining("/v1/missions/mission-1/replan"));
    expect(fetchMock.mock.calls[1]?.[1]).toEqual(expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ expected_revision: 2 }),
    }));
    expect(fetchMock.mock.calls[2]?.[0]).toEqual(expect.stringContaining("/v1/missions/mission-1/cancel"));
    expect(fetchMock.mock.calls[2]?.[1]).toEqual(expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ expected_revision: 2 }),
    }));
  });

  it("serializes search, action, date and sort filters", async () => {
    fetchMock.mockResolvedValue(response({ items: [], total: 0 }));
    await listMissions({ status: "completed", q: "coffee", completed_from: "2026-07-01", completed_to: "2026-07-11", sort: "oldest", requires_action: false });

    const url = String(fetchMock.mock.calls[0]?.[0]);
    expect(url).toContain("status=completed");
    expect(url).toContain("q=coffee");
    expect(url).toContain("completed_from=2026-07-01");
    expect(url).toContain("completed_to=2026-07-11");
    expect(url).toContain("sort=oldest");
    expect(url).toContain("requires_action=false");
  });

  it("adds the optional private-deployment bearer token without changing demo mode", async () => {
    const previousToken = process.env.EXPO_PUBLIC_API_ACCESS_TOKEN;
    process.env.EXPO_PUBLIC_API_ACCESS_TOKEN = "test-access-token";
    fetchMock.mockResolvedValue(response({ items: [], total: 0 }));
    try {
      await listMissions();
      const headers = new Headers(fetchMock.mock.calls[0]?.[1]?.headers);
      expect(headers.get("Authorization")).toBe("Bearer test-access-token");
    } finally {
      if (previousToken === undefined) delete process.env.EXPO_PUBLIC_API_ACCESS_TOKEN;
      else process.env.EXPO_PUBLIC_API_ACCESS_TOKEN = previousToken;
    }
  });

  it("turns a failed network fetch into an actionable backend error", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(listMissions()).rejects.toMatchObject({
      status: 0,
      message: expect.stringContaining("Check that the backend is running"),
    });
  });

  it("uploads a voice recording as FormData without forcing a JSON content type", async () => {
    fetchMock.mockResolvedValue(response({ ...detail, transcription: { text: "Buy coffee", language: "en", model: "gpt-4o-transcribe" } }));
    const result = await createVoiceMission({ audioUri: "file:///tmp/mission.m4a", locale: "en-PL", timezone: "Europe/Warsaw", language: "en-PL" });

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(init.body).toBeInstanceOf(FormData);
    expect(new Headers(init.headers).get("Content-Type")).toBeNull();
    expect(ExpoFile).toHaveBeenCalledWith("file:///tmp/mission.m4a");
    expect(result.transcript).toBe("Buy coffee");
  });

  it("persists a Realtime microphone transcript through the voice contract", async () => {
    fetchMock.mockResolvedValue(response(detail));

    await createVoiceTranscriptMission({
      transcript: "Prezenty dla pięciu dziesięciolatków do 500 PLN.",
      locale: "pl-PL",
      timezone: "Europe/Warsaw",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/v1/missions/voice"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          transcript: "Prezenty dla pięciu dziesięciolatków do 500 PLN.",
          locale: "pl-PL",
          timezone: "Europe/Warsaw",
        }),
      }),
    );
  });
});
