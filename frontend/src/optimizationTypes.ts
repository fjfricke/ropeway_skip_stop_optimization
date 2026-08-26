export interface OptimizationCampaignIndex {
  schema_version: number;
  campaigns: OptimizationCampaignSummary[];
}

export interface OptimizationCampaignSummary {
  campaign_id: string;
  label?: string;
  status?: string;
  objective?: string;
  method?: string;
  formulation?: string;
  campaign_kind?: string;
  operating_mode?: string;
  updated_at_utc?: string;
  sequence?: number;
  completed_trial_count?: number;
  trial_count?: number;
  largest_certified_feasible_k?: number | null;
  frontier_k?: number | null;
  frontier_status?: string | null;
  frontier_termination?: string | null;
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
  solver_status?: string | null;
  stage?: string;
  round_index?: number;
  certified_lower_bound?: number | null;
  validated_upper_bound?: number | null;
  relative_gap?: number | null;
  elapsed_seconds?: number;
  root_lp_certified?: boolean;
  dispatched_fleet_count?: number | null;
  method?: string;
  formulation?: string;
  certificate_kind?: string;
  termination?: string;
  attempt_count?: number;
  cp_sat_seconds?: number;
  cp_sat_solver_status_name?: string | null;
  cp_sat_conflict_count?: number;
  cp_sat_branch_count?: number;
  cp_sat_search_complete?: boolean;
  peak_rss_bytes?: number | null;
  trajectory_count?: number;
  worker_exit_code?: number | null;
  detail?: string | null;
  start_policy?: string;
  start_layout_kind?: string;
  all_stop_maximum_cabin_count?: number | null;
  start_layout_candidate_count?: number;
  start_layout_incompatibility_pair_count?: number;
  start_layout_service_station_count?: number | null;
  start_layout_minimum_station_stop_count?: number | null;
  start_layout_maximum_service_gap_seconds?: number | null;
  start_layout_seconds?: number;
  start_layout_objective_proven?: boolean | null;
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
  method?: string;
  formulation?: string;
  campaign_kind?: string;
  operating_mode?: string;
  minimum_k?: number;
  maximum_k?: number;
  largest_certified_feasible_k?: number | null;
  frontier_k?: number | null;
  frontier_status?: string | null;
  frontier_termination?: string | null;
  updated_at_utc?: string;
  sequence: number;
  trial_count?: number;
  completed_trial_count?: number;
  trials: Record<string, OptimizationTrialSnapshot> | OptimizationTrialSnapshot[];
  policies?: Record<string, OptimizationPolicyResult>;
  policy_comparisons?: Array<Record<string, unknown>>;
  events?: OptimizationEvent[];
}

export interface OptimizationFeasibilityAttempt {
  cabin_count: number;
  attempt_index: number;
  status: string;
  termination: string;
  cp_sat_seconds: number;
  total_seconds: number;
  trajectory_count: number;
  cp_sat_solver_status_name?: string | null;
  cp_sat_conflict_count?: number;
  cp_sat_branch_count?: number;
  peak_rss_bytes?: number | null;
  worker_exit_code?: number | null;
  detail?: string | null;
}
