import type { ScenarioExportBasis } from "./exportTypes";
import { clampNumber } from "./exportSizing";

export function ExportSizeControls({
  basis,
  percentage,
  onBasisChange,
  onPercentageChange,
}: {
  basis: ScenarioExportBasis;
  percentage: number;
  onBasisChange: (basis: ScenarioExportBasis) => void;
  onPercentageChange: (percentage: number) => void;
}) {
  return (
    <section className="export-section">
      <h3>Size</h3>
      <div className="export-size-grid">
        <label>
          Basis
          <select value={basis} onChange={(event) => onBasisChange(event.target.value as ScenarioExportBasis)}>
            <option value="a4_width">A4 width</option>
            <option value="a4_height">A4 height</option>
            <option value="text_width">Text width (147 mm)</option>
          </select>
        </label>
        <label>
          Percent
          <input
            type="number"
            min="1"
            max="400"
            value={percentage}
            onChange={(event) => onPercentageChange(clampNumber(Number(event.target.value), 1, 400))}
          />
        </label>
      </div>
    </section>
  );
}
