import { useEffect, useState } from "react";
import { ScenarioViewer } from "./components/ScenarioViewer";
import type {
  DiscreteScenario,
  EanBuildArtifact,
  EanMovementPlan,
  EanPassengerServiceResult,
  EanPhysicalReplay,
  ExportArtifactKind,
  ExportArtifactSetManifest,
  ExportExampleManifest,
  ExportManifest,
  MovementPlan,
  PassengerReplayResult,
  ReplayMetrics,
  Scenario,
} from "./types";

const MANIFEST_URL = "/generated/examples/manifest.json";
const ARTIFACT_BASE_URL = "/generated/examples/";

interface LoadedArtifacts {
  scenario: Scenario | null;
  discreteScenario: DiscreteScenario | null;
  movementPlan: MovementPlan | null;
  passengerReplay: PassengerReplayResult | null;
  replayMetrics: ReplayMetrics | null;
  eanInput: EanBuildArtifact | null;
  eanResult: EanMovementPlan | null;
  eanReplay: EanPhysicalReplay | null;
  eanPassengerService: EanPassengerServiceResult | null;
  discreteWarning: string | null;
  movementPlanWarning: string | null;
  passengerReplayWarning: string | null;
  replayMetricsWarning: string | null;
  eanInputWarning: string | null;
  eanResultWarning: string | null;
  eanReplayWarning: string | null;
  eanPassengerServiceWarning: string | null;
}

export default function App() {
  const [manifest, setManifest] = useState<ExportManifest | null>(null);
  const [selectedExampleId, setSelectedExampleId] = useState<string>("");
  const [selectedArtifactSetId, setSelectedArtifactSetId] = useState<string>("");
  const [artifacts, setArtifacts] = useState<LoadedArtifacts>(emptyArtifacts);
  const [isLoadingArtifacts, setIsLoadingArtifacts] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadManifest() {
      try {
        const nextManifest = await fetchRequired<ExportManifest>(MANIFEST_URL);
        const example = nextManifest.examples[0];
        if (!example) {
          throw new Error(`No examples listed in ${MANIFEST_URL}`);
        }
        const artifactSet = defaultArtifactSet(example);
        if (!artifactSet) {
          throw new Error(`No artifact sets listed for example ${example.id}`);
        }
        if (!cancelled) {
          setManifest(nextManifest);
          setSelectedExampleId(example.id);
          setSelectedArtifactSetId(artifactSet.id);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Unknown manifest load error");
        }
      }
    }

    loadManifest();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!manifest || !selectedExampleId || !selectedArtifactSetId) {
      return;
    }

    let cancelled = false;
    const activeManifest = manifest;

    async function loadArtifacts() {
      const example = activeManifest.examples.find((candidate) => candidate.id === selectedExampleId);
      const artifactSet = example?.artifact_sets.find((candidate) => candidate.id === selectedArtifactSetId);
      if (!example || !artifactSet) {
        setError(`Unknown artifact selection ${selectedExampleId}/${selectedArtifactSetId}`);
        return;
      }

      setIsLoadingArtifacts(true);
      setError(null);
      try {
        const nextArtifacts = await loadArtifactSet(example, artifactSet);
        if (!cancelled) {
          setArtifacts(nextArtifacts);
        }
      } catch (loadError) {
        if (!cancelled) {
          setArtifacts(emptyArtifacts);
          setError(loadError instanceof Error ? loadError.message : "Unknown artifact load error");
        }
      } finally {
        if (!cancelled) {
          setIsLoadingArtifacts(false);
        }
      }
    }

    loadArtifacts();
    return () => {
      cancelled = true;
    };
  }, [manifest, selectedArtifactSetId, selectedExampleId]);

  function handleExampleChange(exampleId: string) {
    const example = manifest?.examples.find((candidate) => candidate.id === exampleId);
    const artifactSet = example ? defaultArtifactSet(example) : null;
    setSelectedExampleId(exampleId);
    setSelectedArtifactSetId(artifactSet?.id ?? "");
  }

  if (error) {
    return (
      <main className="app-shell">
        <section className="load-state load-state--error">{error}</section>
      </main>
    );
  }

  if (!manifest || !artifacts.scenario) {
    return (
      <main className="app-shell">
        <section className="load-state">Loading scenario</section>
      </main>
    );
  }

  return (
    <ScenarioViewer
      scenario={artifacts.scenario}
      discreteScenario={artifacts.discreteScenario}
      movementPlan={artifacts.movementPlan}
      passengerReplay={artifacts.passengerReplay}
      replayMetrics={artifacts.replayMetrics}
      eanInput={artifacts.eanInput}
      eanResult={artifacts.eanResult}
      eanReplay={artifacts.eanReplay}
      eanPassengerService={artifacts.eanPassengerService}
      discreteWarning={artifacts.discreteWarning}
      movementPlanWarning={artifacts.movementPlanWarning}
      passengerReplayWarning={artifacts.passengerReplayWarning}
      replayMetricsWarning={artifacts.replayMetricsWarning}
      eanInputWarning={artifacts.eanInputWarning}
      eanResultWarning={artifacts.eanResultWarning}
      eanReplayWarning={artifacts.eanReplayWarning}
      eanPassengerServiceWarning={artifacts.eanPassengerServiceWarning}
      artifactSelection={{
        examples: manifest.examples,
        selectedExampleId,
        selectedArtifactSetId,
        isLoading: isLoadingArtifacts,
        onExampleChange: handleExampleChange,
        onArtifactSetChange: setSelectedArtifactSetId,
      }}
    />
  );
}

async function fetchRequired<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to load ${url}: ${response.status}`);
  }
  return (await response.json()) as T;
}

async function loadArtifactSet(example: ExportExampleManifest, artifactSet: ExportArtifactSetManifest): Promise<LoadedArtifacts> {
  const scenarioPath = artifactUrl(artifactSet, "scenario");
  if (!scenarioPath) {
    throw new Error(`Artifact set ${artifactSet.id} does not provide a physical scenario`);
  }
  const discreteArtifactSet = artifactSet.artifacts.discrete_scenario
    ? artifactSet
    : example.artifact_sets.find((candidate) => candidate.artifacts.discrete_scenario);

  const [
    scenario,
    discreteResult,
    movementResult,
    passengerReplayResult,
    replayMetricsResult,
    eanInputResult,
    eanResultResult,
    eanReplayResult,
    eanPassengerServiceResult,
  ] = await Promise.all([
    fetchRequired<Scenario>(scenarioPath),
    discreteArtifactSet
      ? fetchOptional<DiscreteScenario>(discreteArtifactSet, "discrete_scenario", "Discrete overlay")
      : Promise.resolve({ data: null, warning: `Discrete overlay unavailable in artifact set ${artifactSet.id}` }),
    fetchOptional<MovementPlan>(artifactSet, "movement_plan", "Replay"),
    fetchOptional<PassengerReplayResult>(artifactSet, "passenger_replay", "Passenger replay"),
    fetchOptional<ReplayMetrics>(artifactSet, "replay_metrics", "Replay metrics"),
    fetchOptional<EanBuildArtifact>(artifactSet, "ean_input", "EAN input"),
    fetchOptional<EanMovementPlan>(artifactSet, "ean_result", "EAN result"),
    fetchOptional<EanPhysicalReplay>(artifactSet, "ean_replay", "EAN replay"),
    fetchOptional<EanPassengerServiceResult>(artifactSet, "milp_result", "MILP result"),
  ]);

  return {
    scenario,
    discreteScenario: discreteResult.data,
    movementPlan: movementResult.data,
    passengerReplay: passengerReplayResult.data,
    replayMetrics: replayMetricsResult.data,
    eanInput: eanInputResult.data,
    eanResult: eanResultResult.data,
    eanReplay: eanReplayResult.data,
    eanPassengerService: isEanPassengerServiceResult(eanPassengerServiceResult.data) ? eanPassengerServiceResult.data : null,
    discreteWarning: discreteResult.warning,
    movementPlanWarning: movementResult.warning,
    passengerReplayWarning: passengerReplayResult.warning,
    replayMetricsWarning: replayMetricsResult.warning,
    eanInputWarning: eanInputResult.warning,
    eanResultWarning: eanResultResult.warning,
    eanReplayWarning: eanReplayResult.warning,
    eanPassengerServiceWarning: eanPassengerServiceResult.warning,
  };
}

function isEanPassengerServiceResult(value: EanPassengerServiceResult | null): value is EanPassengerServiceResult {
  return value !== null && typeof value === "object" && "passenger_plan" in value && "metadata" in value;
}

async function fetchOptional<T>(
  artifactSet: ExportArtifactSetManifest,
  kind: ExportArtifactKind,
  label: string,
): Promise<{ data: T | null; warning: string | null }> {
  const url = artifactUrl(artifactSet, kind);
  if (!url) {
    return { data: null, warning: `${label} unavailable in artifact set ${artifactSet.id}` };
  }
  try {
    return { data: await fetchRequired<T>(url), warning: null };
  } catch (loadError) {
    const message = loadError instanceof Error ? loadError.message : `Unknown ${label.toLowerCase()} load error`;
    return { data: null, warning: message };
  }
}

function artifactUrl(artifactSet: ExportArtifactSetManifest, kind: ExportArtifactKind): string | null {
  const relativePath = artifactSet.artifacts[kind];
  return relativePath ? `${ARTIFACT_BASE_URL}${relativePath}` : null;
}

function defaultArtifactSet(example: ExportExampleManifest): ExportArtifactSetManifest | null {
  return example.artifact_sets.find((candidate) => candidate.id === example.default_artifact_set) ?? example.artifact_sets[0] ?? null;
}

const emptyArtifacts: LoadedArtifacts = {
  scenario: null,
  discreteScenario: null,
  movementPlan: null,
  passengerReplay: null,
  replayMetrics: null,
  eanInput: null,
  eanResult: null,
  eanReplay: null,
  eanPassengerService: null,
  discreteWarning: null,
  movementPlanWarning: null,
  passengerReplayWarning: null,
  replayMetricsWarning: null,
  eanInputWarning: null,
  eanResultWarning: null,
  eanReplayWarning: null,
  eanPassengerServiceWarning: null,
};
