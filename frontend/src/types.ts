export type StationKind = "service" | "terminal" | "storage";
export type PhysicalNodeKind = "entry_switch" | "exit_switch" | "platform" | "hold" | "depot" | "connector";
export type TrackSegmentKind = "rope" | "station" | "connector" | "skip";
export type SpeedProfileKind = "constant" | "linear";
export type StationRouteKind = "service" | "skip";
export type DiscreteArcKind = "move" | "wait";
export type DiscreteConstraintKind =
  | "node_occupancy"
  | "headway"
  | "switch_occupancy"
  | "shared_resource"
  | "route_continuity";
export type DiscreteConstraintScope = "same_node" | "same_segment" | "cross_segment" | "switch" | "route";
export type DiscreteConstraintStrength = "hard" | "relaxable";

export interface Station {
  id: string;
  kind: StationKind;
  name: string | null;
  route_ids: string[];
}

export interface PhysicalNode {
  id: string;
  kind: PhysicalNodeKind;
  station_id: string | null;
  allows_waiting: boolean;
}

export interface SpeedProfile {
  kind: SpeedProfileKind;
  speed_m_per_s: number | null;
  start_speed_m_per_s: number | null;
  end_speed_m_per_s: number | null;
}

export interface TrackSegment {
  id: string;
  kind: TrackSegmentKind;
  from_node_id: string;
  to_node_id: string;
  length_m: number;
  speed_profile: SpeedProfile | null;
  resource_id: string | null;
}

export interface StationRoute {
  id: string;
  station_id: string;
  kind: StationRouteKind;
  segment_ids: string[];
  allows_boarding: boolean;
  allows_alighting: boolean;
}

export interface Cabin {
  id: number;
}

export interface CabinInitialState {
  cabin_id: number;
  node_id: string;
  available_from: string;
}

export interface Demand {
  arrival_time: string;
  origin: string;
  destination: string;
  count: number;
}

export interface OperatingParameters {
  rope_speed_m_per_s: number;
  station_speed_m_per_s: number;
  cabin_capacity: number;
  cabin_length_m: number;
  min_clearance_m: number;
}

export type HeadwayEvidenceKind = "literature" | "manufacturer" | "experimental" | "engineering_input";

export interface HeadwayParameterProvenance {
  parameter_name: string;
  source_id: string;
  evidence_kind: HeadwayEvidenceKind;
  note: string;
}

export interface HeadwayPhysicalParameters {
  service_clearance_m: number;
  rope_clearance_m: number;
  merge_clearance_m: number;
  suspension_length_m: number;
  rope_sway_angle_rad: number;
  emergency_merge_sway_angle_rad: number;
  control_delay_seconds: number;
  emergency_deceleration_m_per_s2: number;
  provenance: HeadwayParameterProvenance[];
}

export type StationMechanismDesign =
  | { manufacturer_vehicle_interval_seconds: number }
  | { mechanical_service_cycle_seconds: number; service_resource_id: string }
  | {
      mechanical_service_cycle_seconds: number;
      detection_seconds: number;
      diversion_seconds: number;
      safety_path_segment_ids: string[];
      service_resource_id: string;
    }
  | { guaranteed_vehicle_interval_seconds: number; service_resource_id: string };

export interface HeadwayDesign {
  physical: HeadwayPhysicalParameters;
  station_mechanisms: { exit_switch_id: string; design: StationMechanismDesign }[];
  provenance: HeadwayParameterProvenance[];
}

export interface Scenario {
  scenario_id: string;
  service_start_time: string;
  service_end_time: string;
  stations: Station[];
  physical_nodes: PhysicalNode[];
  track_segments: TrackSegment[];
  station_routes: StationRoute[];
  cabins: Cabin[];
  cabin_initial_states: CabinInitialState[];
  demands: Demand[];
  operating: OperatingParameters;
  headway_design?: HeadwayDesign | null;
}

export interface DiscreteNode {
  id: string;
  source_physical_node_id: string | null;
  source_segment_id: string | null;
  station_id: string | null;
  resource_id: string | null;
  position_m: number | null;
  allows_waiting: boolean;
  allows_boarding: boolean;
  allows_alighting: boolean;
}

export interface DiscreteArc {
  id: string;
  kind: DiscreteArcKind;
  from_node_id: string;
  to_node_id: string;
  source_segment_id: string | null;
  source_route_id: string | null;
}

export interface DiscreteRoute {
  id: string;
  source_route_id: string;
  arc_ids: string[];
}

export interface DiscreteConstraint {
  id: string;
  kind: DiscreteConstraintKind;
  scope: DiscreteConstraintScope;
  strength: DiscreteConstraintStrength;
  node_ids: string[];
  arc_ids: string[];
  resource_id: string | null;
  source_segment_ids: string[];
  source_route_ids: string[];
}

export interface DiscreteDemand {
  time_step: number;
  origin: string;
  destination: string;
  count: number;
}

export interface DiscreteCabinInitialState {
  cabin_id: number;
  node_id: string;
  available_from_step: number;
}

export interface DiscreteScenario {
  id: string;
  source_scenario_id: string;
  delta_seconds: number;
  horizon_steps: number;
  nodes: DiscreteNode[];
  arcs: DiscreteArc[];
  routes: DiscreteRoute[];
  constraints: DiscreteConstraint[];
  stations: Station[];
  station_routes: StationRoute[];
  cabins: Cabin[];
  cabin_initial_states: DiscreteCabinInitialState[];
  demands: DiscreteDemand[];
  cabin_capacity: number;
  required_cabin_spacing_m: number;
}

export interface DiscretePath {
  id: string;
  arc_ids: string[];
  node_ids: string[];
  source_segment_ids: string[];
  source_route_ids: string[];
}

export interface CabinPosition {
  time_step: number;
  node_id: string;
  incoming_arc_id: string | null;
}

export interface CabinTrajectory {
  cabin_id: number;
  positions: CabinPosition[];
}

export interface MovementPlan {
  discrete_scenario_id: string;
  horizon_steps: number;
  trajectories: CabinTrajectory[];
  paths: DiscretePath[];
}

export type BoardingPolicyKind = "greedy_fifo_next_compatible_cabin";
export type ExportArtifactKind =
  | "scenario"
  | "discrete_scenario"
  | "movement_plan"
  | "passenger_replay"
  | "replay_metrics"
  | "milp_result"
  | "ean_input"
  | "ean_result"
  | "ean_replay";

export interface ExportArtifactMetadata {
  id: string;
  kind: ExportArtifactKind;
  label: string | null;
  path: string;
}

export interface ExportArtifactSetManifest {
  id: string;
  label: string;
  backend: ExportArtifactSetBackend;
  artifacts: Partial<Record<ExportArtifactKind, string>>;
  artifact_metadata: ExportArtifactMetadata[];
}

export type ExportArtifactSetBackend = "physical" | "discrete" | "ean";

export interface ExportExampleManifest {
  id: string;
  label: string;
  description: string;
  tags: string[];
  default_artifact_set: string;
  artifact_sets: ExportArtifactSetManifest[];
}

export interface ExportScenarioVariantManifest {
  id: string;
  label: string;
  example_id: string;
  example_label: string;
  description: string;
  tags: string[];
  default_artifact_set: string;
  artifact_sets: ExportArtifactSetManifest[];
}

export interface ExportScenarioFamilyManifest {
  id: string;
  label: string;
  variants: ExportScenarioVariantManifest[];
}

export interface ExportManifest {
  schema_version: number;
  generated_at: string | null;
  families: ExportScenarioFamilyManifest[];
  examples?: ExportExampleManifest[];
}

export interface PassengerQueueState {
  time_step: number;
  station_id: string;
  destination: string;
  waiting_count: number;
}

export interface OnboardPassengerGroup {
  batch_id: string;
  demand_index: number;
  origin: string;
  destination: string;
  arrival_step: number;
  boarded_step: number;
  count: number;
}

export interface CabinLoadState {
  time_step: number;
  cabin_id: number;
  node_id: string;
  onboard_groups: OnboardPassengerGroup[];
}

export interface BoardingEvent {
  time_step: number;
  cabin_id: number;
  station_id: string;
  destination: string;
  batch_id: string;
  count: number;
  waiting_steps: number;
}

export interface AlightingEvent {
  time_step: number;
  cabin_id: number;
  station_id: string;
  batch_id: string;
  count: number;
  onboard_steps: number;
}

export interface ReplayStepState {
  time_step: number;
  queue_states: PassengerQueueState[];
  cabin_loads: CabinLoadState[];
  boarding_events: BoardingEvent[];
  alighting_events: AlightingEvent[];
}

export interface ReplaySummary {
  arrived_passengers: number;
  boarded_passengers: number;
  served_passengers: number;
  unserved_passengers: number;
  onboard_passengers: number;
  total_waiting_steps: number;
  max_waiting_steps: number;
}

export interface PassengerReplayResult {
  discrete_scenario_id: string;
  movement_plan_horizon_steps: number;
  boarding_policy: BoardingPolicyKind;
  steps: ReplayStepState[];
  boarding_events: BoardingEvent[];
  alighting_events: AlightingEvent[];
  final_queue_states: PassengerQueueState[];
  final_cabin_loads: CabinLoadState[];
  summary: ReplaySummary;
}

export interface PassengerStationMetric {
  station_id: string;
  count: number;
}

export interface PassengerOdMetric {
  origin: string;
  destination: string;
  count: number;
}

export interface ReplayMetricsStep {
  time_step: number;
  arrivals_count: number;
  boarding_count: number;
  alighting_count: number;
  waiting_count: number;
  onboard_count: number;
  cumulative_waiting_passenger_hours: number;
  waiting_by_station: PassengerStationMetric[];
  onboard_by_od: PassengerOdMetric[];
}

export interface ReplayMetrics {
  discrete_scenario_id: string;
  movement_plan_horizon_steps: number;
  delta_seconds: number;
  steps: ReplayMetricsStep[];
}

export type EanStationWaitingMode = "no_waiting" | "end_of_platform_wait" | "station_fifo_buffer";
export type EanCabinStartKind = "fixed" | "earliest";
export type EanVisitDecision = "stop" | "skip";
export type EanHeadwayCheckpointKind = "platform_entry" | "exit_switch";
export type EanHeadwayCandidateActivationReference = "serve" | "skip" | "active";
export type EanHorizonFormulation =
  | "horizon_legacy"
  | "horizon_conservative_free_suffix"
  | "horizon_exact_time_activation";
export type EanStopSkipTimingFormulation =
  | "stop_skip_timing_big_m"
  | "stop_skip_timing_affine";
export type EanTimeBoundFormulation =
  | "time_bounds_legacy_plus_10"
  | "time_bounds_derived_visit_bounds";
export type EanSlotActivationFormulation =
  | "slot_activation_per_slot"
  | "slot_activation_first_slot";
export type EanBoardTimeFormulation =
  | "board_time_explicit"
  | "board_time_projected_journey_time";
export interface EanFormulationConfig {
  horizon: EanHorizonFormulation;
  time_bounds: EanTimeBoundFormulation;
  stop_skip_timing: EanStopSkipTimingFormulation;
  slot_activation: EanSlotActivationFormulation;
  board_time: EanBoardTimeFormulation;
}
export interface EanOptimizationConfig {
  enable_candidate_horizon_pruning: boolean;
  enable_single_ring_dominated_ride_pruning: boolean;
  enable_slot_time_relaxation_strengthening: boolean;
  enable_tight_big_m_bounds: boolean;
  formulation?: EanFormulationConfig;
}
export type EanHeadwayCandidateTimeReference =
  | "switch_time"
  | "platform_entry_time"
  | "platform_exit_time"
  | "exit_switch_time"
  | "next_switch_time";
export type EanPhysicalEventKind =
  | "enter_switch"
  | "enter_platform"
  | "enter_wait"
  | "exit_wait"
  | "exit_platform"
  | "exit_switch"
  | "reach_next_switch";

export interface EanStationConfig {
  station_id: string;
  waiting_mode: EanStationWaitingMode;
  fifo_capacity: number | null;
  max_wait_seconds: number | null;
}

export interface EanConfig {
  horizon_seconds: number;
  tail_seconds: number;
  cabin_capacity: number;
  station_configs: EanStationConfig[];
}

export interface EanSkipStopTiming {
  switch_id: string;
  station_id: string;
  entry_to_platform_entry_seconds: number;
  min_platform_entry_to_platform_exit_seconds: number;
  platform_exit_to_exit_switch_seconds: number;
  skip_entry_to_exit_switch_seconds: number;
  rope_to_next_switch_seconds: number;
  skip_allowed: boolean;
}

export interface EanCabinStart {
  cabin_id: number;
  first_switch_id: string;
  kind: EanCabinStartKind;
  time_seconds: number;
}

export interface EanSwitchVisitDefinition {
  cabin_id: number;
  visit_index: number;
  switch_id: string;
}

export interface EanSwitchTransition {
  from_switch_id: string;
  to_switch_id: string;
  min_seconds: number;
  max_seconds: number | null;
}

export interface EanHeadwayCheckpoint {
  id: string;
  kind: EanHeadwayCheckpointKind;
  switch_id: string;
  station_id: string;
  headway_seconds: number;
  applies_to_serve: boolean;
  applies_to_skip: boolean;
  waiting_modes: EanStationWaitingMode[];
  headway_rule_id?: string | null;
}

export interface EanHeadwayCandidate {
  id: string;
  checkpoint_id: string;
  cabin_id: number;
  visit_index: number;
  activation_reference: EanHeadwayCandidateActivationReference;
  time_reference: EanHeadwayCandidateTimeReference;
}

export interface EanHeadwayPair {
  id: string;
  checkpoint_id: string;
  first_candidate_id: string;
  second_candidate_id: string;
  headway_seconds: number;
}

export type HeadwayRouteBehavior = "bypass" | "service";
export type HeadwayRuleKind = "constant" | "leader_behavior";

export interface ConstantHeadwayRule {
  id: string;
  seconds: number;
  kind: "constant";
}

export interface LeaderBehaviorHeadwayRule {
  id: string;
  bypass_leader_seconds: number;
  service_leader_seconds: number;
  kind: "leader_behavior";
}

export type HeadwayRule = ConstantHeadwayRule | LeaderBehaviorHeadwayRule;
export type DerivedHeadwayResourceKind = "platform_entry" | "platform_exit" | "exit_switch" | "service_mechanism";
export type DerivedSpatialRole = "rope" | "service";

export interface DerivedHeadwayResource {
  id: string;
  state_id: string;
  exit_switch_id: string;
  station_id: string;
  kind: DerivedHeadwayResourceKind;
  rule_id: string;
  applies_to_service: boolean;
  applies_to_bypass: boolean;
  physical_resource_id: string | null;
}

export interface DerivedSpatialSpacing {
  role: DerivedSpatialRole;
  spacing_m: number;
}

export interface DerivedQuantity {
  id: string;
  value: number;
  unit: string;
  formula: string;
  evidence_kind: HeadwayEvidenceKind;
}

export interface DerivedHeadwayPolicy {
  rules: HeadwayRule[];
  resource_requirements: DerivedHeadwayResource[];
  spatial_spacings: DerivedSpatialSpacing[];
  derived_quantities: DerivedQuantity[];
  provenance: HeadwayParameterProvenance[];
  legacy: boolean;
}

export interface HeadwayResourceDominanceCertificate {
  dominated_resource_id: string;
  dominating_resource_id: string;
  behavior_pairs: [HeadwayRouteBehavior, HeadwayRouteBehavior][];
  minimum_implied_headway_seconds: number;
  required_headway_seconds: number;
  proof_kind: "fixed_offset" | "wait_occupancy_fixed_suffix";
  retain_at_initial_boundary: boolean;
}

export interface EffectiveHeadwayPolicy {
  rules: HeadwayRule[];
  resource_requirements: DerivedHeadwayResource[];
  dominance_certificates: HeadwayResourceDominanceCertificate[];
  component_resource_ids_by_effective_id: Record<string, string[]>;
  reduction_version: string;
}

export type EanFleetMode = "fixed_starts" | "optimized_initial_placement";
export type EanInitialPlacementStateKind =
  | "entry_switch"
  | "service_route"
  | "skip_route"
  | "platform_wait"
  | "exit_switch"
  | "rope";

export interface EanInitialPlacementState {
  cabin_id: number;
  kind: EanInitialPlacementStateKind;
  switch_id: string;
  visit_index: number;
  progress: number;
  previous_event_time_seconds: number;
  next_event_time_seconds: number;
  previous_service: boolean | null;
}

export interface EanFleetPlan {
  mode: "optimized_initial_placement";
  available_fleet_count: number;
  active_cabin_ids: number[];
  inactive_cabin_ids: number[];
  initial_states: EanInitialPlacementState[];
}

export interface EanBuildArtifact {
  scenario_id: string;
  config: EanConfig;
  switch_cycle: string[];
  timings: EanSkipStopTiming[];
  cabin_starts: EanCabinStart[];
  switch_visits: EanSwitchVisitDefinition[];
  switch_transitions: EanSwitchTransition[];
  headway_checkpoints: EanHeadwayCheckpoint[];
  headway_candidates: EanHeadwayCandidate[];
  headway_pairs: EanHeadwayPair[];
  headway_pair_scope?: "complete" | "sparse";
  fleet_mode?: EanFleetMode;
  headway_policy?: DerivedHeadwayPolicy | null;
  effective_headway_policy?: EffectiveHeadwayPolicy | null;
  safety_schema_version?: "frontend_replay_safety_v1";
}

export interface EanVisitPlan {
  cabin_id: number;
  visit_index: number;
  switch_id: string;
  station_id: string;
  decision: EanVisitDecision;
  switch_time_seconds: number;
  platform_entry_time_seconds: number | null;
  platform_exit_time_seconds: number | null;
  exit_switch_time_seconds: number;
  next_switch_time_seconds: number;
  wait_seconds: number;
}

export interface EanCabinTrajectory {
  cabin_id: number;
  visits: EanVisitPlan[];
}

export interface EanMovementPlan {
  scenario_id: string;
  horizon_seconds: number;
  model_end_seconds: number;
  horizon_formulation: EanHorizonFormulation;
  fleet_mode?: EanFleetMode;
  fleet_plan?: EanFleetPlan | null;
  trajectories: EanCabinTrajectory[];
}

export interface EanPhysicalEvent {
  cabin_id: number;
  visit_index: number;
  event_kind: EanPhysicalEventKind;
  time_seconds: number;
  switch_id: string;
  station_id: string;
  physical_node_id: string;
  source_segment_ids: string[];
}

export interface EanPhysicalReplay {
  scenario_id: string;
  horizon_seconds: number;
  model_end_seconds: number;
  events: EanPhysicalEvent[];
}

export type EanPassengerServiceObjectiveKind = "waiting_time" | "journey_time";

export interface EanServedRideGroup {
  demand_group_id: string;
  cabin_id: number;
  board_visit_index: number;
  alight_visit_index: number;
  count: number;
  boarding_time_seconds: number;
  alighting_time_seconds: number;
}

export interface EanPassengerServicePlan {
  scenario_id: string;
  horizon_seconds: number;
  served_rides: EanServedRideGroup[];
  unserved_counts_by_demand_group_id: Record<string, number>;
}

export interface EanPassengerServiceMetadata {
  status: string;
  solver_status?: string;
  objective_kind: EanPassengerServiceObjectiveKind;
  objective_value_seconds: number | null;
  objective_passenger_hours: number | null;
  best_bound?: number | null;
  mip_gap?: number | null;
  runtime_seconds?: number | null;
  node_count?: number | null;
  solution_count?: number;
  mip_gap_target?: number | null;
  time_limit_seconds?: number | null;
  checkpoint_read_path?: string | null;
  checkpoint_solution_file_prefix?: string | null;
  checkpoint_final_solution_path?: string | null;
  demand_group_count: number;
  ride_candidate_count: number;
  slot_variable_count: number;
  served_passenger_count: number;
  unserved_passenger_count: number;
  variable_count: number;
  constraint_count: number;
  model_nonzero_count?: number;
  model_setup_runtime_seconds?: number;
  optimization_config?: EanOptimizationConfig;
  skipped_visit_count: number;
  visible_skipped_visit_count: number;
  progress_samples?: EanSolverProgressSample[];
}

export interface EanSolverProgressSample {
  runtime_seconds: number;
  node_count?: number | null;
  incumbent_objective?: number | null;
  best_bound?: number | null;
  mip_gap?: number | null;
  solution_count?: number | null;
  work?: number | null;
  event?: string;
}

export interface EanPassengerServiceResult {
  movement_plan: EanMovementPlan | null;
  passenger_plan: EanPassengerServicePlan | null;
  fleet_plan?: EanFleetPlan | null;
  metadata: EanPassengerServiceMetadata;
}

export type Selection =
  | { type: "node"; id: string }
  | { type: "segment"; id: string }
  | { type: "route"; id: string }
  | { type: "discrete_node"; id: string }
  | { type: "discrete_arc"; id: string }
  | { type: "discrete_constraint"; id: string };
