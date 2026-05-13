export function ExportItemActions({
  selectedNodeCount,
  selectedArcCount,
  nodeLabel,
  arcLabel,
  onSelectAll,
  onClear,
}: {
  selectedNodeCount: number;
  selectedArcCount: number;
  nodeLabel: string;
  arcLabel: string;
  onSelectAll: () => void;
  onClear: () => void;
}) {
  return (
    <section className="export-section export-section--selection-actions">
      <div className="export-section__header">
        <h3>Items</h3>
        <div className="export-section__actions">
          <button type="button" onClick={onSelectAll}>
            All
          </button>
          <button type="button" onClick={onClear}>
            None
          </button>
        </div>
      </div>
      <p className="export-section__meta">
        {selectedNodeCount} {nodeLabel} · {selectedArcCount} {arcLabel}
      </p>
    </section>
  );
}
