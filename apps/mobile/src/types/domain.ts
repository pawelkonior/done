export type MissionStatus =
  | "created"
  | "transcribing"
  | "understanding"
  | "planning"
  | "searching"
  | "optimizing"
  | "validating"
  | "approval_required"
  | "executing"
  | "recovering"
  | "completed"
  | "failed"
  | "cancelled"
  | "waiting";

export interface MissionSummary {
  id: string;
  title: string;
  subtitle: string;
  status: MissionStatus;
  current_step: number;
  total_steps: number;
  progress: number;
  latest_update: string;
  created_at: string;
  completed_at?: string | null;
  icon?: "cake" | "laptop" | "cart" | "coffee" | "package";
  accent?: "violet" | "blue" | "green" | "amber";
  recovered_failures?: number;
  revision?: number;
}

export interface MissionContract {
  goal: string;
  participants: number;
  hard_constraints: string[];
  soft_preferences: string[];
  budget: number;
  currency: string;
  deadline: string;
  approval_policy: string;
  confidence: number;
  version: number;
  transcript?: string;
}

export interface BasketItem {
  id: string;
  name: string;
  category: string;
  quantity: number;
  unit_price: number;
  total: number;
  nut_free?: boolean;
  replaced_item?: string | null;
}

export interface Basket {
  id: string;
  merchant: string;
  items: BasketItem[];
  subtotal: number;
  delivery_cost: number;
  total: number;
  currency: string;
  status: string;
}

export interface ApprovalRequest {
  id: string;
  type: string;
  question: string;
  status: "pending" | "approved" | "cancelled" | "expired";
  options: Array<{ id: string; label: string }>;
  created_at: string;
}

export interface MissionEvent {
  id: string;
  type: string;
  title: string;
  description: string;
  severity: "info" | "success" | "warning" | "error";
  created_at: string;
  sequence?: number;
}

export interface DeliveryOption {
  id: string;
  name: string;
  eta: string;
  price: number;
  currency: string;
  badge: string;
  selected: boolean;
  reliability?: number;
}

export interface MissionMetrics {
  budget: number;
  final_cost: number;
  saved: number;
  recovered_failures: number;
  payment_attempts: number;
  constraint_satisfaction: number;
  delivery_confidence: number;
}

export interface MissionDetail {
  mission: MissionSummary & {
    raw_voice_transcript?: string;
    current_step_key?: string;
  };
  contract: MissionContract | null;
  basket: Basket | null;
  approval: ApprovalRequest | null;
  events: MissionEvent[];
  metrics: MissionMetrics;
  delivery_options: DeliveryOption[];
}

export interface MissionListResponse {
  items: MissionSummary[];
  total: number;
}

export interface CreateMissionResponse {
  mission_id: string;
  status: MissionStatus;
  transcript?: string;
  confirmation?: string;
  detail?: MissionDetail;
  transcription?: VoiceTranscription;
}

export interface VoiceTranscription {
  text: string;
  language?: string;
  model?: string;
}

export interface MissionListFilters {
  status?: MissionStatus | "active" | string;
  q?: string;
  completed_from?: string;
  completed_to?: string;
  sort?: "newest" | "oldest" | "updated" | "deadline";
  requires_action?: boolean;
}

export interface TextMissionInput {
  transcript: string;
  locale?: string;
  timezone?: string;
}

export interface VoiceMissionInput {
  audioUri: string;
  locale: string;
  timezone: string;
  language: string;
}

export interface MissionCorrectionInput {
  correction: string;
  expected_revision?: number;
}

export interface DeliverySelectionInput {
  option_id: string;
  expected_revision?: number;
}

export interface PaymentMethod {
  token: string;
  brand: string;
  last4: string;
  expiry_month: number;
  expiry_year: number;
  is_demo: boolean;
}

export interface DeliveryAddress {
  label: string;
  line1: string;
  city: string;
  postal_code: string;
  country: string;
}

export interface UserStats {
  missions: number;
  recoveries: number;
  saved: number;
}

export interface UserProfile {
  id: string;
  name: string;
  email: string;
  locale: string;
  currency: string;
  timezone: string;
  autonomy_level: string;
  delivery_address: DeliveryAddress;
  payment_method: PaymentMethod;
  default_constraints: string[];
  contact_preference: string;
  stats: UserStats;
}

export type UserProfileUpdate = Partial<
  Pick<
    UserProfile,
    | "name"
    | "email"
    | "locale"
    | "currency"
    | "timezone"
    | "autonomy_level"
    | "default_constraints"
    | "contact_preference"
  >
> & {
  delivery_address?: Partial<DeliveryAddress>;
  payment_method?: Partial<PaymentMethod>;
};

export interface UserSettings {
  voice_language: string;
  confirmation_voice_enabled: boolean;
  safe_recovery_enabled: boolean;
  approval_policy: string;
  approval_threshold: number;
  notifications_enabled: boolean;
  preferred_merchant_ids: string[];
}

export type UserSettingsUpdate = Partial<UserSettings>;

export interface Merchant {
  id: string;
  name: string;
  reliability_score: number;
  active: boolean;
}

export type UserDataExport = Record<string, unknown>;

export interface RuntimeCapability {
  status: string;
  provider?: string;
  model?: string;
  detail?: string | null;
}

export interface RuntimeCapabilities {
  speech_to_text: RuntimeCapability;
  realtime: RuntimeCapability;
  demo_failures: boolean;
  demo_endpoints: boolean;
}

export interface RealtimeClientSecret {
  value: string;
  expires_at: number;
  model: string;
  voice: string;
}
