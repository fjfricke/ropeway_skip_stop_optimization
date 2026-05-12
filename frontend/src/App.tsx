import { useEffect, useState } from "react";
import { ScenarioViewer } from "./components/ScenarioViewer";
import type {
  DiscreteScenario,
  ExportArtifactKind,
  ExportArtifactSetManifest,
  ExportManifest,
  MovementPlan,
  PassengerReplayResult,
  ReplayMetrics,
  Scenario,
} from "./types";

const MANIFEST_URL = "/generated/examples/manifest.json";
const ARTIFACT_BASE_URL = "/generated/examples/";

export default function App() {
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [discreteScenario, setDiscreteScenario] = useState<DiscreteScenario | null>(null);
  const [movementPlan, setMovementPlan] = useState<MovementPlan | null>(null);
  const [passengerReplay, setPassengerReplay] = useState<PassengerReplayResult | null>(null);
  const [replayMetrics, setReplayMetrics] = useState<ReplayMetrics | null>(null);
  const [discreteWarning, setDiscreteWarning] = useState<string | null>(null);
  const [movementPlanWarning, setMovementPlanWarning] = useState<string | null>(null);
  const [passengerReplayWarning, setPassengerReplayWarning] = useState<string | null>(null);
  const [replayMetricsWarning, setReplayMetricsWarning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadScenario() {
      try {
        const manifest = await fetchRequired<ExportManifest>(MANIFEST_URL);
        const example = manifest.examples[0];
        if (!example) {
          throw new Error(`No examples listed in ${MANIFEST_URL}`);
        }
        const artifactSet =
          example.artifact_sets.find((candidate) => candidate.id === example.default_artifact_set) ??
          example.artifact_sets[0];
        if (!artifactSet) {
          throw new Error(`No artifact sets listed for example ${example.id}`);
        }

        const scenarioPath = artifactUrl(artifactSet, "scenario");
        if (!scenarioPath) {
          throw new Error(`Artifact set ${artifactSet.id} does not provide a physical scenario`);
        }
        const data = await fetchRequired<Scenario>(scenarioPath);
        const discreteResult = await fetchOptional<DiscreteScenario>(artifactSet, "discrete_scenario", "Discrete overlay");
        const movementResult = await fetchOptional<MovementPlan>(artifactSet, "movement_plan", "Replay");
        const passengerReplayResult = await fetchOptional<PassengerReplayResult>(
          artifactSet,
          "passenger_replay",
          "Passenger replay",
        );
        const replayMetricsResult = await fetchOptional<ReplayMetrics>(artifactSet, "replay_metrics", "Replay metrics");

        if (!cancelled) {
          setScenario(data);
          setDiscreteScenario(discreteResult.data);
          setMovementPlan(movementResult.data);
          setPassengerReplay(passengerReplayResult.data);
          setReplayMetrics(replayMetricsResult.data);
          setDiscreteWarning(discreteResult.warning);
          setMovementPlanWarning(movementResult.warning);
          setPassengerReplayWarning(passengerReplayResult.warning);
          setReplayMetricsWarning(replayMetricsResult.warning);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Unknown scenario load error");
        }
      }
    }

    loadScenario();
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <main className="app-shell">
        <section className="load-state load-state--error">{error}</section>
      </main>
    );
  }

  if (!scenario) {
    return (
      <main className="app-shell">
        <section className="load-state">Loading scenario</section>
      </main>
    );
  }

  return (
    <ScenarioViewer
      scenario={scenario}
      discreteScenario={discreteScenario}
      movementPlan={movementPlan}
      passengerReplay={passengerReplay}
      replayMetrics={replayMetrics}
      discreteWarning={discreteWarning}
      movementPlanWarning={movementPlanWarning}
      passengerReplayWarning={passengerReplayWarning}
      replayMetricsWarning={replayMetricsWarning}
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
