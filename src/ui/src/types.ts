export type ProviderId = "cursor" | "workbuddy" | "volc_agent_plan" | "deepseek" | "trae";

export interface ProviderMeta {
  id: ProviderId | string;
  title: string;
}

export interface MeterRow {
  key: string;
  title: string;
  value: string;
  percent: number | null;
  color: string;
  detail: string;
}

export interface ModelUsage {
  name: string;
  tokens: number;
  tokens_text: string;
  percent: number;
  cents: number;
}

export interface CreditBalance {
  remaining_cents: number;
  total_cents: number;
  used_cents: number;
  remaining_percent: number;
  remaining_text: string;
  total_text: string;
  expires_at: string | null;
}

export interface GrokBotUsage {
  usage_percent: number | null;
  has_included_allowance: boolean;
  uses_pooled_enterprise: boolean;
  has_available_usage: boolean | null;
  period_start: string | null;
  reset_at: string | null;
  trial_expires_at: string | null;
  plan_label: string | null;
  is_unified: boolean | null;
  banked_reset_count: number;
  error: string | null;
  show_meter: boolean;
  seconds_left: number | null;
}

export interface CursorDetails {
  email: string | null;
  plan_name: string;
  membership: string | null;
  price: string | null;
  total_percent_used: number;
  first_party_percent_used: number;
  api_percent_used: number;
  first_party_tokens: number;
  first_party_tokens_text: string;
  api_tokens: number;
  api_tokens_text: string;
  first_party_models: ModelUsage[];
  api_models: ModelUsage[];
  cycle_start: string | null;
  cycle_end: string | null;
  seconds_left: number | null;
  seconds_left_text: string;
  display_message: string | null;
  hit_limit: boolean;
  credits: CreditBalance | null;
  grok_bot: GrokBotUsage | null;
}

export interface Snapshot {
  provider_id: string;
  title: string;
  account: string;
  plan: string;
  subtitle: string;
  display_text: string;
  percent_used: number | null;
  status: string;
  error: string | null;
  ok: boolean;
  rows: MeterRow[];
  extras: string[];
  notes: string;
  fetched_at: string | null;
  reset_fact: string;
  cursor: CursorDetails | null;
}

export interface WindowState {
  x: number | null;
  y: number | null;
  docked: boolean;
  dock_edge: "left" | "right" | "top" | "bottom" | null;
  detail_x: number | null;
  detail_y: number | null;
}

export interface AppState {
  provider_id: string;
  providers: ProviderMeta[];
  snapshot: Snapshot;
  loading: boolean;
  window: WindowState;
  config_path: string;
}

export interface SettingsState {
  volc_agent_plan: {
    configured: boolean;
    access_key_id: string;
    has_access_key_id: boolean;
    secret_access_key: string;
    has_secret_access_key: boolean;
    session_token: string;
    has_session_token: boolean;
    account_type: "personal" | "enterprise" | string;
    seat_ids: string[];
  };
  deepseek: {
    configured: boolean;
    api_key: string;
    has_api_key: boolean;
    reference_balance: number | null;
  };
  config_path: string;
}
