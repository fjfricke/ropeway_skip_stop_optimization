import type { ThesisGroup, ThesisIndex, ThesisRunSummary } from "./thesisTypes";

const families = ["f0", "f2", "f3", "f4"] as const;

export const plannedThesisGroups: ThesisGroup[] = [
  ...families.map((demandFamily) => ({
    id: `journey_t5r_${demandFamily}_g500_p0`,
    topology: "t5r" as const,
    geometry: "g500" as const,
    demandFamily,
    demandProfile: "p0" as const,
    objective: "journey_time" as const,
    method: "labelled_arc_flow" as const,
    runIds: [],
  })),
];

export const plannedThesisIndex: ThesisIndex = {
  schema: "thesis_frontend_index_v1",
  campaignStatus: "planned",
  contractId: "t5r_g500_b_entry_exit_2cycles_900completion_300tail_v2",
  groups: plannedThesisGroups,
  runs: [],
  sources: [{
    label: "Câble C1 press kit",
    url: "https://www.iledefrance-mobilites.fr/le-reseau/projets/cablec1/mediatheque/kit-presse-c1",
    use: "Published 500–1,800 m interstation range motivates the synthetic G500 scale.",
  }],
};

export function runMap(index: ThesisIndex): Map<string, ThesisRunSummary> {
  return new Map(index.runs.map((run) => [run.id, run]));
}

export function groupRuns(index: ThesisIndex, group: ThesisGroup): ThesisRunSummary[] {
  const byId = runMap(index);
  return group.runIds.map((id) => byId.get(id)).filter((run): run is ThesisRunSummary => Boolean(run));
}

export function referenceLabel(group: ThesisGroup): string {
  const reference = group.reference;
  if (!reference) return "Reference pending";
  if (reference.capacityProven && reference.capacity != null) return `κAS = ${reference.capacity.toLocaleString()}`;
  const lower = reference.provenFeasibleDemand;
  const upper = reference.provenInfeasibleDemand;
  if (lower != null && upper != null) return `${lower.toLocaleString()} ≤ κAS < ${upper.toLocaleString()}`;
  if (lower != null) return `κAS ≥ ${lower.toLocaleString()}`;
  return "Reference unresolved";
}

export function bestRun(runs: ThesisRunSummary[], objective: ThesisGroup["objective"]): ThesisRunSummary | undefined {
  const valid = runs.filter((run) => run.validated !== false && run.method !== "all_stop_phase" && run.operatingMode !== "all_stop" && run.status === "complete" && (
    objective === "unserved" ? run.served != null : run.journeyTime != null
  ));
  // A larger demand must not silently win a fixed-demand comparison.
  if (new Set(valid.map((run) => run.demand).filter((demand) => demand != null)).size > 1) return undefined;
  if (new Set(valid.map(run => run.releaseResolutionSeconds)).size > 1) return undefined;
  return valid.sort((a, b) => {
    const objectiveOrder = objective === "unserved"
      ? (b.served ?? -1) - (a.served ?? -1)
      : (a.journeyTime ?? Number.POSITIVE_INFINITY) - (b.journeyTime ?? Number.POSITIVE_INFINITY);
    if (objectiveOrder !== 0) return objectiveOrder;
    const fleetOrder = (a.k ?? Number.POSITIVE_INFINITY) - (b.k ?? Number.POSITIVE_INFINITY);
    if (fleetOrder !== 0) return fleetOrder;
    return (a.elapsedSeconds ?? Number.POSITIVE_INFINITY) - (b.elapsedSeconds ?? Number.POSITIVE_INFINITY);
  })[0];
}

export function matchingAllStop(run: ThesisRunSummary, runs: ThesisRunSummary[]) {
  return runs.find(other => other.id !== run.id && other.groupId === run.groupId
    && other.method === run.method && other.operatingMode === "all_stop"
    && other.k === run.k && other.demand === run.demand
    && other.releaseResolutionSeconds === run.releaseResolutionSeconds
    && other.caseFingerprint === run.caseFingerprint
    && other.validated === true);
}
