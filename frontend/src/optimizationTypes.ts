export interface OptimizationCampaignIndex {
  schema_version: number;
  campaigns: OptimizationCampaignSummary[];
}

export interface OptimizationCampaignSummary {
  campaign_id: string;
  label?: string;
  status?: string;
  objective?: string;
  updated_at_utc?: string;
  sequence?: number;
  completed_trial_count?: number;
  trial_count?: number;
}

export interface OptimizationEvent {
  sequence: number;
  kind: string;
  timestamp_utc: string;
  stage?: string | null;
  round_index?: number | null;
  global_certified_lower_bound?: number | null;
  global_validated_upper_bound?: number | null;
  global_relative_gap?: number | null;
  local_solver_incumbent?: number | null;
  local_solver_bound?: number | null;
  local_solver_gap?: number | null;
  elapsed_seconds?: number | null;
  payload?: Record<string, unknown>;
}

export interface OptimizationTrialSnapshot {
  trial_id: string;
  policy_id: string;
  available_fleet_count: number;
  status: string;
  stage?: string;
  round_index?: number;
  certified_lower_bound?: number;
  validated_upper_bound?: number;
  relative_gap?: number;
  elapsed_seconds?: number;
  root_lp_certified?: boolean;
  dispatched_fleet_count?: number | null;
  updated_at_utc?: string;
  events: OptimizationEvent[];
}

export interface OptimizationBoundPoint {
  available_fleet_count: number;
  raw_lower_bound: number;
  raw_upper_bound: number | null;
  tightened_lower_bound: number;
  tightened_upper_bound: number | null;
  lower_bound_source_k: number;
  upper_bound_source_k: number | null;
}

export interface OptimizationPolicyResult {
  policy: { id: string; label: string; example_id: string; tags?: string[] };
  bounds: OptimizationBoundPoint[];
  trials: OptimizationTrialSnapshot[];
  service_targets?: Array<Record<string, unknown>>;
  cabin_costs?: Array<Record<string, unknown>>;
}

export interface OptimizationCampaignSnapshot {
  schema_version: number;
  campaign_id: string;
  label?: string;
  status: string;
  objective?: string;
  updated_at_utc?: string;
  sequence: number;
  trial_count?: number;
  completed_trial_count?: number;
  trials: Record<string, OptimizationTrialSnapshot> | OptimizationTrialSnapshot[];
  policies?: Record<string, OptimizationPolicyResult>;
  policy_comparisons?: Array<Record<string, unknown>>;
  events?: OptimizationEvent[];
}
