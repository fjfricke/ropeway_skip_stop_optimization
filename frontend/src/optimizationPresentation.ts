import type { OptimizationCampaignSnapshot, OptimizationTrialSnapshot } from "./optimizationTypes";

export function optimizationSemanticStatus(trial: OptimizationTrialSnapshot) {
  return trial.status === "complete" && trial.solver_status
    ? trial.solver_status
    : trial.status;
}

export function optimizationStatusClass(value: string) {
  if (value.includes("optimal") || value.includes("certified")) return "complete";
  if (value.includes("infeasible")) return "infeasible";
  if (value.includes("feasible")) return "complete";
  if (value.includes("error") || value === "failed") return "failed";
  if (value.includes("unknown") || value.includes("limit")) return "unknown";
  return value;
}

export function isMovementFeasibilityCampaign(campaign: OptimizationCampaignSnapshot) {
  return campaign.method === "fixed_k_cp_sat_feasibility" || campaign.campaign_kind === "movement_feasibility";
}

export function formatOptimizationDuration(value: number | null | undefined) {
  if (value == null) return "—";
  return value < 60 ? `${value.toFixed(1)}s` : `${Math.floor(value / 60)}m ${(value % 60).toFixed(0)}s`;
}

export function formatOptimizationMemory(value: number | null | undefined) {
  return value == null ? "—" : `${(value / (1024 ** 2)).toFixed(0)} MiB`;
}

export function formatOptimizationNumber(
  value: number | null | undefined,
  digits: number,
) {
  return value == null ? "—" : value.toFixed(digits);
}
