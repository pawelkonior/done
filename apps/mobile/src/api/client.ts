import { Platform } from "react-native";
import { File } from "expo-file-system";
import type {
  ActionRequest,
  ApprovalRequest,
  Basket,
  CreateMissionResponse,
  DeliverySelectionInput,
  DeliveryAddress,
  DeliveryOption,
  Merchant,
  MissionDetail,
  MissionCorrectionInput,
  MissionEvent,
  MissionListResponse,
  MissionListFilters,
  MissionMetrics,
  MissionSummary,
  MissionStatus,
  MissionOrder,
  PortfolioAction,
  PortfolioDecision,
  PaymentMethod,
  RealtimeClientSecret,
  RuntimeCapabilities,
  UserDataExport,
  UserProfile,
  UserProfileUpdate,
  UserSettings,
  UserSettingsUpdate,
  TextMissionInput,
  VoiceMissionInput,
} from "@/types/domain";

const defaultHost = Platform.OS === "android" ? "10.0.2.2" : "localhost";
export const API_URL =
  process.env.EXPO_PUBLIC_API_URL?.replace(/\/$/, "") ?? `http://${defaultHost}:8001`;

function apiAccessToken() {
  return process.env.EXPO_PUBLIC_API_ACCESS_TOKEN?.trim();
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const accessToken = apiAccessToken();
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...init?.headers,
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
  });

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: string; message?: string };
      message = body.detail ?? body.message ?? message;
    } catch {
      // Keep the status-based fallback when the server did not return JSON.
    }
    throw new ApiError(message, response.status);
  }

  return (await response.json()) as T;
}

type JsonRecord = Record<string, unknown>;

function asRecord(value: unknown): JsonRecord {
  return value && typeof value === "object" ? (value as JsonRecord) : {};
}

function asString(value: unknown, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

function asNumber(value: unknown, fallback = 0) {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asBoolean(value: unknown, fallback = false) {
  return typeof value === "boolean" ? value : fallback;
}

function asArray(value: unknown) {
  return Array.isArray(value) ? value : [];
}

function inferIcon(title: string): MissionSummary["icon"] {
  const value = title.toLowerCase();
  if (value.includes("laptop")) return "laptop";
  if (value.includes("coffee")) return "coffee";
  if (value.includes("grocery") || value.includes("groceries")) return "cart";
  if (value.includes("refund") || value.includes("package")) return "package";
  return "cake";
}

function inferAccent(title: string, status: MissionStatus): MissionSummary["accent"] {
  if (status === "completed") return "green";
  const icon = inferIcon(title);
  if (icon === "laptop") return "blue";
  if (icon === "coffee") return "amber";
  if (icon === "cart") return "green";
  return "violet";
}

function normalizeStatus(value: unknown): MissionStatus {
  const status = asString(value, "created") as MissionStatus;
  return status;
}

function normalizeSummary(value: unknown): MissionSummary {
  const raw = asRecord(value);
  const status = normalizeStatus(raw.status);
  const title = asString(raw.title, "New mission");
  const totalSteps = asNumber(raw.total_steps, 6);
  const currentStep = asNumber(raw.current_step, 1);
  return {
    id: asString(raw.id),
    title,
    subtitle: asString(raw.subtitle, "Done is taking care of it"),
    status,
    current_step: currentStep,
    total_steps: totalSteps,
    progress: asNumber(raw.progress, totalSteps ? currentStep / totalSteps : 0),
    latest_update: asString(raw.latest_update, "Mission created."),
    created_at: asString(raw.created_at, new Date().toISOString()),
    completed_at: typeof raw.completed_at === "string" ? raw.completed_at : null,
    icon: inferIcon(title),
    accent: inferAccent(title, status),
    recovered_failures: asNumber(raw.recovered_failures, 0),
    revision: asNumber(raw.revision, 1),
  };
}

function humanizeGoal(value: unknown) {
  const goal = asString(value, "Complete the mission").replaceAll("_", " ");
  return goal.charAt(0).toUpperCase() + goal.slice(1);
}

function formatDeadline(value: unknown) {
  const raw = asString(value);
  const date = new Date(raw);
  if (!raw || Number.isNaN(date.getTime())) return raw || "Tomorrow, 16:00";
  return new Intl.DateTimeFormat("en", {
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function normalizeConstraint(value: unknown) {
  if (typeof value === "string") return value;
  const raw = asRecord(value);
  const kind = asString(raw.type);
  if (kind === "budget") return `Maximum ${asNumber(raw.value)} ${asString(raw.currency, "PLN")}`;
  if (kind === "delivery_deadline") return `Delivery by ${formatDeadline(raw.value)}`;
  if (kind === "allergen") return `No ${asString(raw.value, "listed allergens")}`;
  return kind.replaceAll("_", " ");
}

function normalizePreference(value: unknown) {
  if (typeof value === "string") return value;
  const raw = asRecord(value);
  return asString(raw.type, "reliable delivery").replaceAll("_", " ");
}

function normalizeBasket(value: unknown): Basket | null {
  if (!value) return null;
  const raw = asRecord(value);
  const merchantValue = raw.merchant;
  const merchantRecord = asRecord(merchantValue);
  const merchant = typeof merchantValue === "string"
    ? merchantValue
    : asString(merchantRecord.name, "Selected merchant");
  const currency = asString(raw.currency, "PLN");
  return {
    id: asString(raw.id),
    merchant,
    merchant_id: asString(raw.merchant_id, asString(merchantRecord.id)) || undefined,
    currency,
    subtotal: asNumber(raw.subtotal),
    delivery_cost: asNumber(raw.delivery_cost),
    total: asNumber(raw.total),
    status: asString(raw.status, "proposed"),
    items: asArray(raw.items).map((value, index) => {
      const item = asRecord(value);
      return {
        id: asString(item.id, `item-${index}`),
        name: asString(item.name, "Product"),
        category: asString(item.category, "other"),
        quantity: asNumber(item.quantity, 1),
        unit_price: asNumber(item.unit_price),
        total: asNumber(item.total, asNumber(item.line_total)),
        nut_free: asBoolean(item.nut_free),
        replaced_item: asString(item.replaced_item, asString(item.replaced_product_name)) || null,
      };
    }),
  };
}

function normalizeApproval(value: unknown, bindingValue?: unknown): ApprovalRequest | null {
  if (!value) return null;
  const raw = asRecord(value);
  const binding = asRecord(bindingValue);
  return {
    id: asString(raw.id),
    type: asString(raw.type, asString(raw.approval_type, "purchase_approval")),
    question: asString(raw.question, "Approve this purchase?"),
    status: asString(raw.status, "pending") as ApprovalRequest["status"],
    options: asArray(raw.options).map((value) => {
      const option = asRecord(value);
      return { id: asString(option.id), label: asString(option.label) };
    }),
    created_at: asString(raw.created_at, new Date().toISOString()),
    plan_hash: asString(raw.plan_hash, asString(binding.plan_hash)) || undefined,
    merchant_id: asString(raw.merchant_id, asString(binding.merchant_id)) || undefined,
    amount: typeof raw.amount === "number"
      ? asNumber(raw.amount)
      : typeof binding.amount === "number" ? asNumber(binding.amount) : undefined,
    currency: asString(raw.currency, asString(binding.currency)) || undefined,
  };
}

function normalizeActionRequest(value: unknown): ActionRequest | null {
  const raw = asRecord(value);
  const id = asString(raw.id);
  if (!id) return null;
  return {
    id,
    type: asString(raw.type, "user_decision"),
    reason_code: asString(raw.reason_code, "ACTION_REQUIRED"),
    question: asString(raw.question, "Done needs one more detail."),
    status: asString(raw.status, "pending") as ActionRequest["status"],
    owner: asString(raw.owner, "user"),
    options: asArray(raw.options).map((option) => {
      const item = asRecord(option);
      return { id: asString(item.id), label: asString(item.label) };
    }).filter((option) => option.id && option.label),
    context: asRecord(raw.context),
    created_at: asString(raw.created_at, new Date().toISOString()),
    expires_at: typeof raw.expires_at === "string" ? raw.expires_at : null,
  };
}

function normalizeEvent(value: unknown, index: number): MissionEvent {
  const raw = asRecord(value);
  const severity = asString(raw.severity, "info");
  return {
    id: asString(raw.id, `event-${index}`),
    type: asString(raw.type, asString(raw.event_type, "mission.event")),
    title: asString(raw.title, "Mission updated"),
    description: asString(raw.description),
    severity: severity === "action" ? "warning" : (severity as MissionEvent["severity"]),
    created_at: asString(raw.created_at, new Date().toISOString()),
    sequence: asNumber(raw.sequence, typeof raw.id === "number" ? raw.id : index + 1),
  };
}

function normalizeTextList(value: unknown): string[] {
  return asArray(value)
    .map((item) => {
      if (typeof item === "string") return item;
      const raw = asRecord(item);
      return asString(raw.message, asString(raw.reason, asString(raw.text)));
    })
    .filter(Boolean);
}

function normalizeLptb(value: unknown): PortfolioAction["lptb"] {
  if (!value) return null;
  const raw = asRecord(value);
  return {
    lptb: asString(raw.lptb),
    p95_delivery_days: asNumber(raw.p95_delivery_days),
    safety_buffer_days: asNumber(raw.safety_buffer_days),
    reason: asString(raw.reason),
  };
}

function normalizePortfolioAction(value: unknown, index: number): PortfolioAction {
  const raw = asRecord(value);
  const explanation = raw.explanation;
  const explanationRecord = asRecord(explanation);
  return {
    need_id: asString(raw.need_id, `need-${index}`),
    quantity: asNumber(raw.quantity, 1),
    product_id: asString(raw.product_id),
    product_name: asString(raw.product_name, "Selected product"),
    merchant_id: asString(raw.merchant_id),
    action: asString(raw.action, "buy_now"),
    timing_mode: asString(raw.timing_mode),
    price_signal: asString(raw.price_signal, asString(asRecord(raw.price_signal).kind)),
    risk_score: Math.min(1, Math.max(0, asNumber(raw.risk_score))),
    lptb: normalizeLptb(raw.lptb),
    objective_cost: asNumber(raw.objective_cost),
    explanation: typeof explanation === "string"
      ? explanation
      : asString(explanationRecord.message, asString(explanationRecord.reason, "Selected by the optimization plan.")),
  };
}

function normalizePortfolioDecision(value: unknown): PortfolioDecision | null {
  if (!value) return null;
  const raw = asRecord(value);
  return {
    id: asString(raw.id),
    trigger: asString(raw.trigger),
    status: asString(raw.status, "feasible"),
    snapshot_id: asString(raw.snapshot_id),
    selected_merchant_id: typeof raw.selected_merchant_id === "string" ? raw.selected_merchant_id : null,
    total: asNumber(raw.total),
    currency: asString(raw.currency, "PLN"),
    constraint_report: normalizeTextList(raw.constraint_report),
    explanations: normalizeTextList(raw.explanations),
    solver_metadata: asRecord(raw.solver_metadata),
    created_at: asString(raw.created_at),
    actions: asArray(raw.actions).map(normalizePortfolioAction),
  };
}

function normalizeMetrics(value: unknown): MissionMetrics {
  const raw = asRecord(value);
  const budget = asNumber(raw.budget, asNumber(raw.budget_limit));
  const finalCost = asNumber(raw.final_cost, asNumber(raw.final_basket_cost));
  return {
    budget,
    final_cost: finalCost,
    saved: asNumber(raw.saved, asNumber(raw.budget_variance, Math.max(0, budget - finalCost))),
    recovered_failures: asNumber(raw.recovered_failures),
    payment_attempts: asNumber(raw.payment_attempts),
    constraint_satisfaction: asNumber(raw.constraint_satisfaction, asNumber(raw.constraint_satisfaction_rate, 1)),
    delivery_confidence: asNumber(raw.delivery_confidence),
  };
}

function normalizeDelivery(value: unknown, index: number): DeliveryOption {
  const raw = asRecord(value);
  const selected = asBoolean(raw.selected);
  const name = asString(raw.name, asString(raw.label, "Delivery"));
  return {
    id: asString(raw.id, `delivery-${index}`),
    name,
    eta: asString(raw.eta, formatDeadline(raw.delivery_at)),
    price: asNumber(raw.price, asNumber(raw.cost)),
    currency: asString(raw.currency, "PLN"),
    badge: asString(raw.badge, selected ? "Recommended" : index === 1 ? "Most reliable" : "Best value"),
    selected,
    available: asBoolean(raw.available, true),
    reliability: asNumber(raw.reliability, asNumber(raw.confidence)),
  };
}

function normalizeOrder(value: unknown): MissionOrder | null {
  if (!value) return null;
  const raw = asRecord(value);
  return {
    id: asString(raw.id),
    confirmation_code: asString(raw.confirmation_code),
    status: asString(raw.status, "placed"),
    total: asNumber(raw.total),
    currency: asString(raw.currency, "PLN"),
    delivery_at: asString(raw.delivery_at),
    created_at: asString(raw.created_at),
  };
}

function normalizeDeliveryAddress(value: unknown): DeliveryAddress {
  const raw = asRecord(value);
  return {
    label: asString(raw.label, "Home"),
    line1: asString(raw.line1),
    city: asString(raw.city),
    postal_code: asString(raw.postal_code),
    country: asString(raw.country, "PL"),
  };
}

function normalizePaymentMethod(value: unknown): PaymentMethod {
  const raw = asRecord(value);
  return {
    token: asString(raw.token),
    brand: asString(raw.brand, "Card"),
    last4: asString(raw.last4),
    expiry_month: asNumber(raw.expiry_month),
    expiry_year: asNumber(raw.expiry_year),
    is_demo: asBoolean(raw.is_demo),
  };
}

function unwrap(value: unknown, key: string) {
  const raw = asRecord(value);
  return raw[key] && typeof raw[key] === "object" ? asRecord(raw[key]) : raw;
}

function normalizeUserProfile(value: unknown): UserProfile {
  const raw = unwrap(value, "user");
  const stats = asRecord(raw.stats);
  return {
    id: asString(raw.id),
    name: asString(raw.name),
    email: asString(raw.email),
    locale: asString(raw.locale, "pl-PL"),
    currency: asString(raw.currency, "PLN"),
    timezone: asString(raw.timezone, "Europe/Warsaw"),
    autonomy_level: asString(raw.autonomy_level, "balanced"),
    delivery_address: normalizeDeliveryAddress(raw.delivery_address),
    payment_method: normalizePaymentMethod(raw.payment_method),
    default_constraints: asArray(raw.default_constraints).map((item) => asString(item)).filter(Boolean),
    contact_preference: asString(raw.contact_preference, "only_when_needed"),
    stats: {
      missions: asNumber(stats.missions),
      recoveries: asNumber(stats.recoveries),
      saved: asNumber(stats.saved),
    },
  };
}

function normalizeUserSettings(value: unknown): UserSettings {
  const raw = unwrap(value, "settings");
  return {
    voice_language: asString(raw.voice_language, "en-PL"),
    confirmation_voice_enabled: asBoolean(raw.confirmation_voice_enabled, true),
    safe_recovery_enabled: asBoolean(raw.safe_recovery_enabled, true),
    approval_policy: asString(raw.approval_policy, "always"),
    approval_threshold: asNumber(raw.approval_threshold, 0),
    notifications_enabled: asBoolean(raw.notifications_enabled, true),
    preferred_merchant_ids: asArray(raw.preferred_merchant_ids).map((item) => asString(item)).filter(Boolean),
  };
}

function normalizeMerchant(value: unknown): Merchant {
  const raw = asRecord(value);
  return {
    id: asString(raw.id),
    name: asString(raw.name, "Merchant"),
    reliability_score: asNumber(raw.reliability_score),
    active: asBoolean(raw.active, true),
  };
}

function normalizeDetail(value: unknown): MissionDetail {
  const raw = asRecord(value);
  const mission = normalizeSummary(raw.mission);
  const contractRaw = raw.contract ? asRecord(raw.contract) : null;
  const participants = contractRaw ? contractRaw.participants : [];
  const participantCount = typeof participants === "number"
    ? participants
    : asNumber(asRecord(asArray(participants)[0]).count, 10);
  const budgetValue = contractRaw ? contractRaw.budget : null;
  const budgetRecord = asRecord(budgetValue);
  const budget = contractRaw
    ? asNumber(contractRaw.budget_limit, asNumber(contractRaw.budget, asNumber(budgetRecord.limit, 300)))
    : 0;
  return {
    mission: {
      ...mission,
      raw_voice_transcript: asString(asRecord(raw.mission).raw_voice_transcript),
      current_step_key: asString(asRecord(raw.mission).current_step_key),
    },
    contract: contractRaw
      ? {
          goal: humanizeGoal(contractRaw.goal),
          participants: participantCount,
          hard_constraints: asArray(contractRaw.hard_constraints).map(normalizeConstraint),
          soft_preferences: asArray(contractRaw.soft_preferences).map(normalizePreference),
          budget,
          currency: asString(contractRaw.currency, asString(budgetRecord.currency, "PLN")),
          deadline: formatDeadline(contractRaw.deadline),
          approval_policy: asString(contractRaw.approval_policy, "Approval required before purchase"),
          confidence: asNumber(contractRaw.confidence, 0.96),
          version: asNumber(contractRaw.version, 1),
          transcript: asString(asRecord(raw.mission).raw_voice_transcript),
        }
      : null,
    basket: normalizeBasket(raw.basket),
    approval: normalizeApproval(raw.approval, raw.approval_binding),
    portfolio_decision: normalizePortfolioDecision(raw.portfolio_decision),
    order: normalizeOrder(raw.order),
    events: asArray(raw.events).map(normalizeEvent),
    metrics: normalizeMetrics(raw.metrics),
    delivery_options: asArray(raw.delivery_options).map(normalizeDelivery),
    action_requests: asArray(raw.action_requests)
      .map(normalizeActionRequest)
      .filter((item): item is ActionRequest => item !== null),
  };
}

export async function listMissions(input?: MissionListFilters | MissionStatus | "active") {
  const filters: MissionListFilters = typeof input === "string" ? { status: input } : input ?? {};
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.q?.trim()) params.set("q", filters.q.trim());
  if (filters.completed_from) params.set("completed_from", filters.completed_from);
  if (filters.completed_to) params.set("completed_to", filters.completed_to);
  if (filters.sort) params.set("sort", filters.sort);
  if (typeof filters.requires_action === "boolean") params.set("requires_action", String(filters.requires_action));
  const query = params.toString();
  const raw = await apiFetch<JsonRecord>(`/v1/missions${query ? `?${query}` : ""}`);
  const items = asArray(raw.items ?? raw.missions).map(normalizeSummary);
  return { items, total: asNumber(raw.total, items.length) } satisfies MissionListResponse;
}

export async function getMission(id: string) {
  const raw = await apiFetch<JsonRecord>(`/v1/missions/${id}`);
  return normalizeDetail(raw);
}

export async function createTextMission(input: string | TextMissionInput) {
  const payload = typeof input === "string"
    ? { transcript: input, locale: "en-PL", timezone: "Europe/Warsaw" }
    : { transcript: input.transcript, locale: input.locale ?? "en-PL", timezone: input.timezone ?? "Europe/Warsaw" };
  const raw = await apiFetch<JsonRecord>("/v1/missions/text", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  const detail = normalizeDetail(raw);
  return {
    mission_id: detail.mission.id,
    status: detail.mission.status,
    transcript: detail.mission.raw_voice_transcript,
    confirmation: asString(raw.confirmation, "I understood your mission. I’ll take care of it."),
    detail,
  } satisfies CreateMissionResponse;
}

function audioMetadata(uri: string) {
  const clean = uri.split("?")[0] ?? uri;
  const extension = clean.match(/\.([a-zA-Z0-9]+)$/)?.[1]?.toLowerCase() ?? "m4a";
  const mime = extension === "wav" ? "audio/wav"
    : extension === "mp3" ? "audio/mpeg"
      : extension === "webm" ? "audio/webm"
        : extension === "caf" ? "audio/x-caf"
          : "audio/mp4";
  return { name: `mission.${extension}`, mime };
}

export async function createVoiceMission(input: VoiceMissionInput) {
  if (!input.audioUri) throw new ApiError("No voice recording is available to upload.", 0);
  const form = new FormData();
  const { name, mime } = audioMetadata(input.audioUri);
  if (Platform.OS === "web") {
    const audioResponse = await fetch(input.audioUri);
    const blob = await audioResponse.blob();
    form.append("file", blob, name);
  } else {
    const audioFile = new File(input.audioUri);
    form.append("file", audioFile, name);
  }
  form.append("locale", input.locale);
  form.append("timezone", input.timezone);
  form.append("language", input.language);
  const raw = await apiFetch<JsonRecord>("/v1/missions/voice", {
    method: "POST",
    body: form,
  });
  const detail = normalizeDetail(raw.detail ?? raw);
  const transcriptionRaw = asRecord(raw.transcription);
  const transcription = {
    text: asString(transcriptionRaw.text, detail.mission.raw_voice_transcript),
    language: asString(transcriptionRaw.language) || undefined,
    model: asString(transcriptionRaw.model) || undefined,
  };
  return {
    mission_id: detail.mission.id,
    status: detail.mission.status,
    transcript: transcription.text,
    confirmation: asString(raw.confirmation, "I understood your mission. I’ll take care of it."),
    detail,
    transcription,
  } satisfies CreateMissionResponse;
}

export async function correctMission(missionId: string, input: MissionCorrectionInput) {
  const raw = await apiFetch<JsonRecord>(`/v1/missions/${missionId}/corrections`, {
    method: "POST",
    body: JSON.stringify(input),
    headers: revisionHeaders(input.expected_revision),
  });
  return normalizeDetail(raw);
}

export async function selectDeliveryOption(missionId: string, input: DeliverySelectionInput) {
  const raw = await apiFetch<JsonRecord>(`/v1/missions/${missionId}/delivery-option`, {
    method: "PUT",
    body: JSON.stringify(input),
    headers: revisionHeaders(input.expected_revision),
  });
  return normalizeDetail(raw);
}

function revisionHeaders(expectedRevision?: number): HeadersInit | undefined {
  return typeof expectedRevision === "number"
    ? { "If-Match": `W/"${expectedRevision}"` }
    : undefined;
}

export async function cancelMission(missionId: string, expectedRevision: number) {
  const raw = await apiFetch<JsonRecord>(`/v1/missions/${missionId}/cancel`, {
    method: "POST",
    body: JSON.stringify({ expected_revision: expectedRevision }),
    headers: revisionHeaders(expectedRevision),
  });
  return normalizeDetail(raw);
}

export async function resolveApproval(
  approvalId: string,
  choice: "approve" | "review" | "cancel",
  evidence: {
    expected_revision: number;
    amount?: number;
    currency?: string;
    plan_hash?: string;
    merchant_id?: string;
    voice_transcript?: string;
  },
) {
  const raw = await apiFetch<JsonRecord>(
    `/v1/approvals/${approvalId}/resolve`,
    { method: "POST", body: JSON.stringify({ choice, ...evidence }) },
  );
  const detail = normalizeDetail(raw);
  return { status: detail.mission.status, mission_id: detail.mission.id, detail };
}

export async function resolveActionRequest(
  actionRequestId: string,
  input: { choice: string; voice_transcript?: string; expected_revision: number },
) {
  const raw = await apiFetch<JsonRecord>(`/v1/action-requests/${actionRequestId}/resolve`, {
    method: "POST",
    body: JSON.stringify(input),
  });
  return normalizeDetail(raw);
}

export async function requestHumanSupport(
  missionId: string,
  input: { reason?: string; expected_revision: number },
) {
  const raw = await apiFetch<JsonRecord>(`/v1/missions/${missionId}/support`, {
    method: "POST",
    body: JSON.stringify(input),
  });
  return normalizeDetail(raw);
}

export async function injectFailure(missionId: string, failureType: string) {
  return apiFetch<{ status: string }>("/v1/demo/failures", {
    method: "POST",
    body: JSON.stringify({ mission_id: missionId, failure_type: failureType }),
  });
}

export async function resetDemo() {
  return apiFetch<{ status: string }>("/v1/demo/reset", { method: "POST", body: "{}" });
}

export async function getUserProfile() {
  const raw = await apiFetch<JsonRecord>("/v1/users/me");
  return normalizeUserProfile(raw);
}

export async function updateUserProfile(update: UserProfileUpdate) {
  const raw = await apiFetch<JsonRecord>("/v1/users/me", {
    method: "PATCH",
    body: JSON.stringify(update),
  });
  return normalizeUserProfile(raw);
}

export async function getUserSettings() {
  const raw = await apiFetch<JsonRecord>("/v1/users/me/settings");
  return normalizeUserSettings(raw);
}

export async function updateUserSettings(update: UserSettingsUpdate) {
  const raw = await apiFetch<JsonRecord>("/v1/users/me/settings", {
    method: "PATCH",
    body: JSON.stringify(update),
  });
  return normalizeUserSettings(raw);
}

export async function listMerchants() {
  const raw = await apiFetch<JsonRecord | unknown[]>("/v1/merchants");
  const record = asRecord(raw);
  return asArray(Array.isArray(raw) ? raw : record.items ?? record.merchants)
    .map(normalizeMerchant)
    .filter((merchant) => merchant.id);
}

export async function getUserDataExport(): Promise<UserDataExport> {
  const raw = await apiFetch<JsonRecord>("/v1/users/me/export");
  return asRecord(raw.export ?? raw);
}

export async function getRuntimeCapabilities(): Promise<RuntimeCapabilities> {
  return apiFetch<RuntimeCapabilities>("/v1/runtime/capabilities");
}

export async function getRealtimeClientSecret(
  language: string,
  missionId?: string,
): Promise<RealtimeClientSecret> {
  return apiFetch<RealtimeClientSecret>("/v1/realtime/client-secret", {
    method: "POST",
    body: JSON.stringify({ language, mission_id: missionId }),
  });
}
