import type { ExportArtifactSetBackend } from "../types";
import type { ArtifactSelectionControl, ViewerCounts } from "./viewerTypes";

const BACKEND_LABELS: Record<ExportArtifactSetBackend, string> = {
  physical: "Physical",
  discrete: "Discrete",
  ean: "EAN",
};

interface ViewerHeaderProps {
  scenarioId: string;
  counts: ViewerCounts;
  hasDiscrete: boolean;
  artifactSelection: ArtifactSelectionControl;
}

export function ViewerHeader({ scenarioId, counts, hasDiscrete, artifactSelection }: ViewerHeaderProps) {
  const selectedFamily = artifactSelection.families.find(
    (family) => family.id === artifactSelection.selectedFamilyId,
  );
  const variants = selectedFamily?.variants ?? [];
  const selectedVariant = variants.find((variant) => variant.id === artifactSelection.selectedVariantId);
  const availableBackends = new Set(selectedVariant?.artifact_sets.map((artifactSet) => artifactSet.backend) ?? []);
  const nonPhysicalBackends = (["discrete", "ean"] as const).filter((backend) => availableBackends.has(backend));
  const backendOptions: ExportArtifactSetBackend[] = nonPhysicalBackends.length > 0
    ? nonPhysicalBackends
    : (["physical"] as const).filter((backend) => availableBackends.has(backend));
  const artifactSets = selectedVariant?.artifact_sets.filter(
    (artifactSet) => artifactSet.backend === artifactSelection.selectedBackend,
  ) ?? [];

  return (
    <header className="topbar">
      <div>
        <p className="eyebrow">Ropeway Scenario Viewer</p>
        <h1>{scenarioId}</h1>
      </div>
      <div className="topbar__right">
        <div className="topbar__meta" aria-label="Scenario counts">
          <span>{counts.stations} stations</span>
          <span>{counts.nodes} nodes</span>
          <span>{counts.segments} segments</span>
          <span>{counts.routes} routes</span>
          {hasDiscrete ? <span>{counts.discreteNodes} discrete nodes</span> : null}
          {hasDiscrete ? <span>{counts.constraints} constraints</span> : null}
        </div>
        <div className="artifact-controls" aria-label="Loaded artifact selection">
          <label>
            <span>Topology</span>
            <select
              aria-label="Topology"
              value={artifactSelection.selectedFamilyId}
              onChange={(event) => artifactSelection.onFamilyChange(event.target.value)}
            >
              {artifactSelection.families.map((family) => (
                <option key={family.id} value={family.id}>
                  {family.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Geometry</span>
            <select
              aria-label="Geometry variant"
              value={artifactSelection.selectedVariantId}
              onChange={(event) => artifactSelection.onVariantChange(event.target.value)}
            >
              {variants.map((variant) => (
                <option key={variant.id} value={variant.id}>
                  {variant.label}
                </option>
              ))}
            </select>
          </label>
          {backendOptions.length > 1 ? (
            <div className="artifact-controls__segments" aria-label="Backend">
              {backendOptions.map((backend) => (
                <button
                  key={backend}
                  className={backend === artifactSelection.selectedBackend ? "is-active" : ""}
                  type="button"
                  onClick={() => artifactSelection.onBackendChange(backend)}
                >
                  {BACKEND_LABELS[backend]}
                </button>
              ))}
            </div>
          ) : null}
          {artifactSets.length > 1 ? (
            <label>
              <span>Artifact</span>
              <select
                aria-label="Artifact Set"
                value={artifactSelection.selectedArtifactSetId}
                onChange={(event) => artifactSelection.onArtifactSetChange(event.target.value)}
              >
                {artifactSets.map((artifactSet) => (
                  <option key={artifactSet.id} value={artifactSet.id}>
                    {artifactSet.label}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {artifactSelection.isLoading ? <span className="artifact-controls__status">Loading</span> : null}
        </div>
      </div>
    </header>
  );
}
