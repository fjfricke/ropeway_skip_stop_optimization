import type { ArtifactSelectionControl, ViewerCounts } from "./viewerTypes";

interface ViewerHeaderProps {
  scenarioId: string;
  counts: ViewerCounts;
  hasDiscrete: boolean;
  artifactSelection: ArtifactSelectionControl;
}

export function ViewerHeader({ scenarioId, counts, hasDiscrete, artifactSelection }: ViewerHeaderProps) {
  const selectedExample = artifactSelection.examples.find((example) => example.id === artifactSelection.selectedExampleId);
  const artifactSets = selectedExample?.artifact_sets ?? [];

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
            <span>Example</span>
            <select
              aria-label="Example"
              value={artifactSelection.selectedExampleId}
              onChange={(event) => artifactSelection.onExampleChange(event.target.value)}
            >
              {artifactSelection.examples.map((example) => (
                <option key={example.id} value={example.id}>
                  {example.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Artifact Set</span>
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
          {artifactSelection.isLoading ? <span className="artifact-controls__status">Loading</span> : null}
        </div>
      </div>
    </header>
  );
}
