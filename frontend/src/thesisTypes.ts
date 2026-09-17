export type ThesisObjective = "unserved" | "journey_time";

export interface ThesisReference {
  provenFeasibleDemand?: number | null;
  provenInfeasibleDemand?: number | null;
  capacity?: number | null;
  capacityProven?: boolean;
  fleet?: number | null;
  proofScope?: string;
  releaseResolutionSeconds?: number | null;
}

export interface ThesisRunSummary {
  id: string;
  groupId: string;
  status: "planned" | "queued" | "running" | "complete" | "unknown" | "failed";
  method: "evolution" | "labelled_arc_flow" | "all_stop_phase";
  operatingMode?: "all_stop" | "skip_stop" | null;
  validated?: boolean;
  primalSeedKind?: string | null;
  primalSeedObjective?: number | null;
  k?: number | null;
  demand?: number | null;
  releaseResolutionSeconds?: number | null;
  caseFingerprint?: string | null;
  detail?: string | null;
  seed?: number | null;
  elapsedSeconds?: number | null;
  supervisedWallSeconds?: number | null;
  peakRssBytes?: number | null;
  cumulativeSeconds?: number | null;
  served?: number | null;
  unserved?: number | null;
  journeyTime?: number | null;
  globalLowerBound?: number | null;
  boundScope?: string | null;
  parentRunId?: string | null;
  stopReason?: string | null;
  transferKind?: string | null;
  provenance?: "main_study" | "calibration";
  studyMembership?: "current_thesis" | "archive";
  contractId?: string | null;
  snapshot?: string | null;
  replay?: string | null;
  reference?: ThesisReference | null;
}

export interface ThesisGroup {
  id: string;
  topology: "t5r" | "t6r";
  geometry: "g500";
  demandFamily: "f0" | "f2" | "f3" | "f4";
  demandProfile: "p0";
  objective: ThesisObjective;
  method: "evolution" | "labelled_arc_flow";
  reference?: ThesisReference;
  runIds: string[];
}

export interface ThesisIndex {
  schema: "thesis_frontend_index_v1";
  generatedAt?: string;
  campaignStatus: "planned" | "calibrating" | "partial" | "ready" | "running" | "complete";
  contractId?: string;
  groups: ThesisGroup[];
  runs: ThesisRunSummary[];
  launchReadiness?: { status: string; groups: { id: string; blockers: string[]; demandBasis?: string }[] };
  sources?: Array<{ label: string; url: string; use: string }>;
}
