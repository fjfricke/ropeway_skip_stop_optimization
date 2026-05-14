import { useEffect, useState } from "react";
import { ScenarioViewer } from "./components/ScenarioViewer";
import type {
  DiscreteScenario,
  EanBuildArtifact,
  EanMovementPlan,
  EanPassengerServiceResult,
  EanPhysicalReplay,
  ExportArtifactKind,
  ExportArtifactSetBackend,
  ExportArtifactSetManifest,
  ExportExampleManifest,
  ExportManifest,
  ExportScenarioFamilyManifest,
  ExportScenarioVariantManifest,
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

interface ArtifactSelectionState {
  familyId: string;
  variantId: string;
  backend: ExportArtifactSetBackend;
  artifactSetId: string;
}

interface ChunkedJsonDescriptor {
  __chunked_json__: true;
  encoding: string;
  size_bytes: number;
  chunks: Array<{
    path: string;
    size_bytes: number;
    sha256?: string;
  }>;
}

export default function App() {
  const [manifest, setManifest] = useState<ExportManifest | null>(null);
  const [selection, setSelection] = useState<ArtifactSelectionState | null>(null);
  const [artifacts, setArtifacts] = useState<LoadedArtifacts>(emptyArtifacts);
  const [isLoadingArtifacts, setIsLoadingArtifacts] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadManifest() {
      try {
        const nextManifest = normalizeManifest(await fetchRequired<ExportManifest>(MANIFEST_URL));
        const nextSelection = defaultSelection(nextManifest);
        if (!nextSelection) {
          throw new Error(`No export variants listed in ${MANIFEST_URL}`);
        }
        if (!cancelled) {
          setManifest(nextManifest);
          setSelection(nextSelection);
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
    if (!manifest || !selection) {
      return;
    }

    let cancelled = false;
    const activeManifest = manifest;
    const activeSelection = selection;

    async function loadArtifacts() {
      const resolved = resolveSelection(activeManifest, activeSelection);
      if (!resolved) {
        setError(
          `Unknown artifact selection ${activeSelection.familyId}/${activeSelection.variantId}/${activeSelection.artifactSetId}`,
        );
        return;
      }

      setIsLoadingArtifacts(true);
      setError(null);
      try {
        const nextArtifacts = await loadArtifactSet(resolved.variant, resolved.artifactSet);
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
  }, [manifest, selection]);

  function handleFamilyChange(familyId: string) {
    const family = manifest?.families.find((candidate) => candidate.id === familyId);
    const nextSelection = family ? defaultSelectionForFamily(family) : null;
    setSelection(nextSelection);
  }

  function handleVariantChange(variantId: string) {
    if (!manifest || !selection) {
      return;
    }
    const family = manifest.families.find((candidate) => candidate.id === selection.familyId);
    const variant = family?.variants.find((candidate) => candidate.id === variantId);
    const nextSelection = family && variant ? defaultSelectionForVariant(family.id, variant) : null;
    setSelection(nextSelection);
  }

  function handleBackendChange(backend: ExportArtifactSetBackend) {
    if (!manifest || !selection) {
      return;
    }
    const resolved = resolveSelection(manifest, selection);
    const artifactSet = resolved ? defaultArtifactSet(resolved.variant, backend) : null;
    if (!artifactSet) {
      return;
    }
    setSelection({
      ...selection,
      backend,
      artifactSetId: artifactSet.id,
    });
  }

  function handleArtifactSetChange(artifactSetId: string) {
    setSelection((current) => current ? { ...current, artifactSetId } : current);
  }

  if (error) {
    return (
      <main className="app-shell">
        <section className="load-state load-state--error">{error}</section>
      </main>
    );
  }

  if (!manifest || !selection || !artifacts.scenario) {
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
        families: manifest.families,
        selectedFamilyId: selection.familyId,
        selectedVariantId: selection.variantId,
        selectedBackend: selection.backend,
        selectedArtifactSetId: selection.artifactSetId,
        isLoading: isLoadingArtifacts,
        onFamilyChange: handleFamilyChange,
        onVariantChange: handleVariantChange,
        onBackendChange: handleBackendChange,
        onArtifactSetChange: handleArtifactSetChange,
      }}
    />
  );
}

async function fetchRequired<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to load ${url}: ${response.status}`);
  }
  const json = await response.json();
  return isChunkedJsonDescriptor(json) ? fetchChunkedJson<T>(json, response.url || url) : json as T;
}

async function fetchChunkedJson<T>(descriptor: ChunkedJsonDescriptor, descriptorUrl: string): Promise<T> {
  const chunks = await Promise.all(
    descriptor.chunks.map(async (chunk) => {
      const chunkUrl = new URL(chunk.path, descriptorUrl).toString();
      const response = await fetch(chunkUrl);
      if (!response.ok) {
        throw new Error(`Failed to load ${chunkUrl}: ${response.status}`);
      }
      const buffer = await response.arrayBuffer();
      if (buffer.byteLength !== chunk.size_bytes) {
        throw new Error(
          `Chunk size mismatch for ${chunkUrl}: expected ${chunk.size_bytes}, got ${buffer.byteLength}`,
        );
      }
      return new Uint8Array(buffer);
    }),
  );

  const totalBytes = chunks.reduce((sum, chunk) => sum + chunk.byteLength, 0);
  if (totalBytes !== descriptor.size_bytes) {
    throw new Error(`Chunked JSON size mismatch for ${descriptorUrl}: expected ${descriptor.size_bytes}, got ${totalBytes}`);
  }

  const combined = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    combined.set(chunk, offset);
    offset += chunk.byteLength;
  }

  return JSON.parse(new TextDecoder(descriptor.encoding || "utf-8").decode(combined)) as T;
}

function isChunkedJsonDescriptor(value: unknown): value is ChunkedJsonDescriptor {
  if (!value || typeof value !== "object") {
    return false;
  }
  const candidate = value as Partial<ChunkedJsonDescriptor>;
  return candidate.__chunked_json__ === true
    && typeof candidate.encoding === "string"
    && typeof candidate.size_bytes === "number"
    && Array.isArray(candidate.chunks)
    && candidate.chunks.every((chunk) => (
      Boolean(chunk)
      && typeof chunk.path === "string"
      && typeof chunk.size_bytes === "number"
    ));
}

async function loadArtifactSet(
  variant: ExportScenarioVariantManifest,
  artifactSet: ExportArtifactSetManifest,
): Promise<LoadedArtifacts> {
  const scenarioPath = artifactUrl(artifactSet, "scenario");
  if (!scenarioPath) {
    throw new Error(`Artifact set ${artifactSet.id} does not provide a physical scenario`);
  }
  const discreteArtifactSet = artifactSet.artifacts.discrete_scenario
    ? artifactSet
    : variant.artifact_sets.find((candidate) => candidate.artifacts.discrete_scenario);

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
      : Promise.resolve({ data: null, warning: `Discrete overlay unavailable in variant ${variant.id}` }),
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

function resolveSelection(manifest: ExportManifest, selection: ArtifactSelectionState) {
  const family = manifest.families.find((candidate) => candidate.id === selection.familyId);
  const variant = family?.variants.find((candidate) => candidate.id === selection.variantId);
  const artifactSet = variant?.artifact_sets.find((candidate) => candidate.id === selection.artifactSetId);
  if (!family || !variant || !artifactSet) {
    return null;
  }
  return { family, variant, artifactSet };
}

function defaultSelection(manifest: ExportManifest): ArtifactSelectionState | null {
  const family = manifest.families[0];
  return family ? defaultSelectionForFamily(family) : null;
}

function defaultSelectionForFamily(family: ExportScenarioFamilyManifest): ArtifactSelectionState | null {
  const variant = family.variants[0];
  return variant ? defaultSelectionForVariant(family.id, variant) : null;
}

function defaultSelectionForVariant(
  familyId: string,
  variant: ExportScenarioVariantManifest,
): ArtifactSelectionState | null {
  const artifactSet = defaultArtifactSet(variant);
  return artifactSet
    ? {
      familyId,
      variantId: variant.id,
      backend: artifactSet.backend,
      artifactSetId: artifactSet.id,
    }
    : null;
}

function defaultArtifactSet(
  variant: ExportScenarioVariantManifest,
  backend?: ExportArtifactSetBackend,
): ExportArtifactSetManifest | null {
  const artifactSets = backend
    ? variant.artifact_sets.filter((candidate) => candidate.backend === backend)
    : variant.artifact_sets;
  if (!backend) {
    const defaultSet = artifactSets.find((candidate) => candidate.id === variant.default_artifact_set);
    if (defaultSet?.backend !== "physical") {
      return defaultSet ?? artifactSets.find((candidate) => candidate.backend !== "physical") ?? artifactSets[0] ?? null;
    }
    return artifactSets.find((candidate) => candidate.backend !== "physical") ?? defaultSet ?? artifactSets[0] ?? null;
  }
  return artifactSets.find((candidate) => candidate.id === variant.default_artifact_set) ?? artifactSets[0] ?? null;
}

function normalizeManifest(manifest: ExportManifest): ExportManifest {
  if (manifest.families) {
    return {
      ...manifest,
      families: manifest.families.map((family) => ({
        ...family,
        variants: family.variants.map((variant) => ({
          ...variant,
          artifact_sets: variant.artifact_sets.map(withBackend),
        })),
      })),
    };
  }
  return {
    schema_version: 2,
    generated_at: manifest.generated_at,
    families: legacyExamplesToFamilies(manifest.examples ?? []),
  };
}

function legacyExamplesToFamilies(examples: ExportExampleManifest[]): ExportScenarioFamilyManifest[] {
  const families = new Map<string, ExportScenarioFamilyManifest>();
  for (const example of examples) {
    const group = legacyGroupForExample(example);
    const family = families.get(group.familyId) ?? {
      id: group.familyId,
      label: group.familyLabel,
      variants: [],
    };
    family.variants = [
      ...family.variants.filter((variant) => variant.id !== group.variantId),
      {
        id: group.variantId,
        label: group.variantLabel,
        example_id: example.id,
        example_label: example.label,
        description: example.description,
        tags: example.tags,
        default_artifact_set: example.default_artifact_set,
        artifact_sets: example.artifact_sets.map(withBackend),
      },
    ].sort((left, right) => left.id.localeCompare(right.id));
    families.set(family.id, family);
  }
  return Array.from(families.values()).sort((left, right) => left.id.localeCompare(right.id));
}

function legacyGroupForExample(example: ExportExampleManifest) {
  if (example.id === "three_station_v0") {
    return {
      familyId: "three_station_ring",
      familyLabel: "Three station ring",
      variantId: "half_cabins_skip_wait",
      variantLabel: "Half cabins skip+wait",
    };
  }
  if (example.id === "three_station_no_skip_no_wait_v0") {
    return {
      familyId: "three_station_ring",
      familyLabel: "Three station ring",
      variantId: "full_cabins_no_skip_no_wait",
      variantLabel: "Full cabins no_skip+no_wait",
    };
  }
  if (example.id === "three_station_full_no_skip_no_wait_v0") {
    return {
      familyId: "three_station_ring",
      familyLabel: "Three station ring",
      variantId: "full_cabins_no_skip_no_wait",
      variantLabel: "Full cabins no_skip+no_wait",
    };
  }
  if (example.id === "three_station_half_no_skip_no_wait_v0") {
    return {
      familyId: "three_station_ring",
      familyLabel: "Three station ring",
      variantId: "half_cabins_no_skip_no_wait",
      variantLabel: "Half cabins no_skip+no_wait",
    };
  }
  if (example.id === "five_station_v0") {
    return {
      familyId: "five_station_ring",
      familyLabel: "Five station ring",
      variantId: "half_cabins_skip_wait",
      variantLabel: "Half cabins skip+wait",
    };
  }
  if (example.id === "five_station_no_wait_v0") {
    return {
      familyId: "five_station_ring",
      familyLabel: "Five station ring",
      variantId: "full_cabins_skip_no_wait",
      variantLabel: "Full cabins skip+no_wait",
    };
  }
  if (example.id === "five_station_half_no_skip_no_wait_v0") {
    return {
      familyId: "five_station_ring",
      familyLabel: "Five station ring",
      variantId: "half_cabins_no_skip_no_wait",
      variantLabel: "Half cabins no_skip+no_wait",
    };
  }
  return { familyId: example.id, familyLabel: example.label, variantId: example.id, variantLabel: example.label };
}

function withBackend(artifactSet: ExportArtifactSetManifest): ExportArtifactSetManifest {
  return {
    ...artifactSet,
    backend: artifactSet.backend ?? inferBackend(artifactSet),
  };
}

function inferBackend(artifactSet: ExportArtifactSetManifest): ExportArtifactSetBackend {
  const artifacts = artifactSet.artifacts;
  if (artifacts.ean_input || artifacts.ean_result || artifacts.ean_replay) {
    return "ean";
  }
  if (
    artifacts.discrete_scenario
    || artifacts.movement_plan
    || artifacts.passenger_replay
    || artifacts.replay_metrics
    || artifacts.milp_result
  ) {
    return "discrete";
  }
  return "physical";
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
