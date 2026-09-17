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
  peak_active_fleet_count?: number | null;
  served?: number | null;
  unserved?: number | null;
  mean_served_journey_seconds?: number | null;
  passenger_carrying_skip_count?: number | null;
  stop_count?: number | null;
  skip_count?: number | null;
  seed_objective_seconds?: number | null;
  native_strict_improvement?: boolean;
  budget_seconds?: number;
  build_seconds?: number | null;
  solve_seconds?: number | null;
  model_variable_count?: number | null;
  primary_lower_bound?: number | null;
  primary_upper_bound?: number | null;
  served_lower_bound?: number | null;
  served_upper_bound?: number | null;
  secondary_lower_bound?: number | null;
  secondary_upper_bound?: number | null;
  movement_variable_count?: number;
  passenger_variable_count?: number;
  linear_constraint_count?: number;
  resource_row_count?: number;
  network_node_count?: number;
  network_arc_count?: number;
  peak_rss_gb?: number;
  seed_provenance?: string | null;
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
  allocation_id?: string;
  allocation_label?: string;
  pattern_composition?: Record<string, number>;
  pattern_identity?: string;
  movement_status?: string | null;
  passenger_status?: string | null;
  journey_time_seconds?: number | null;
  passenger_build_seconds?: number | null;
  passenger_solve_seconds?: number | null;
  run_campaign_id?: string | null;
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
  demand_total?: number;
  demand_family?: string;
  passenger_horizon_seconds?: number;
  operation_seconds?: number;
  allocation_order?: string[];
  k_values?: number[];
  trials: Record<string, OptimizationTrialSnapshot> | OptimizationTrialSnapshot[];
  refinement_count?: number;
  completed_refinement_count?: number;
  refinements?: OptimizationRefinementSnapshot[];
  policies?: Record<string, OptimizationPolicyResult>;
  policy_comparisons?: Array<Record<string, unknown>>;
  events?: OptimizationEvent[];
}

export interface OptimizationRefinementSnapshot extends OptimizationTrialSnapshot {
  refinement_id: string;
  source_trial_id: string;
  source_served?: number | null;
  source_unserved?: number | null;
  source_journey_time_seconds?: number | null;
  rank_within_k?: number;
  objective_value?: number | null;
  best_bound?: number | null;
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
