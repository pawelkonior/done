export type NodeId =
  | "intake"
  | "contract"
  | "snapshot"
  | "model"
  | "guardrails"
  | "purchase"
  | "result";

export type NodeSubtitles = Partial<Record<NodeId, string>>;

export interface NodeDetail {
  title: string;
  meta?: string;
  description?: string;
  tone?: "info" | "ok" | "warn" | "error";
  route?: {
    label: string;
    state: "default" | "ok" | "error";
  };
}

export type NodeDetails = Partial<Record<NodeId, NodeDetail[]>>;

export interface ProductStoreRoute {
  productId: string;
  title: string;
  quantity: number;
  storeId: string;
  storeName: string;
  endpoint: string;
  state: "planned" | "processing" | "purchased" | "failed";
  simulated: boolean;
}

export interface LoopEvent {
  type: string;
  title: string;
  severity: string;
  created_at: string;
}

export interface ApiEvent extends LoopEvent {
  id: number;
  actor: string;
  description: string;
}

export interface MissionSummary {
  id: string;
  title: string;
  status: string;
  created_at: string;
}

export interface BasketItem {
  id: string;
  product_id: string;
  name: string;
  quantity: number;
  unit_price: number;
  line_total: number;
  currency: string;
  substitution_allowed: boolean;
  replaced_product_id: string | null;
  replaced_product_name: string | null;
}

export interface Basket {
  merchant: { id: string; name: string; reliability_score: number } | null;
  items: BasketItem[];
  item_count: number;
  total: number;
  currency: string;
  status: string;
}

export interface Approval {
  question: string;
  status: string;
  amount: number | null;
  currency: string | null;
  expires_at: string | null;
}

export interface ActionRequest {
  type: string;
  question: string;
  status: string;
  owner: string;
}

export interface Funding {
  status: string;
  max_amount?: number;
  currency?: string;
}

export interface PaymentAttempt {
  provider: string;
  amount: number;
  currency: string;
  status: string;
  decline_code: string | null;
  product_id?: string | null;
  product_name?: string | null;
  simulated?: boolean;
}

export interface Order {
  confirmation_code: string;
  status: string;
  total: number;
  currency: string;
  delivery_at: string | null;
}

export interface MissionDetail {
  mission: MissionSummary & {
    current_step: number;
    total_steps: number;
    progress: number;
    latest_update: string;
    budget_limit: number;
    currency: string;
  };
  basket: Basket | null;
  approval: Approval | null;
  action_requests: ActionRequest[];
  funding: Funding;
  payment_attempts: PaymentAttempt[];
  order: Order | null;
  metrics: {
    budget_variance: number;
    recovered_failures: number;
    payment_attempts: number;
  };
}

export interface CatalogOffer {
  store_id: string;
  store_name: string;
  product_id: string;
  sku: string;
  product_name: string;
  price: number;
  currency: string;
  is_available: boolean;
  product_url?: string;
}
