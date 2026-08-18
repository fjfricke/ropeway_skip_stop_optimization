import { SlidersHorizontal } from "lucide-react";
import type { Scenario } from "../types";

interface ParametersPanelProps {
  scenario: Scenario;
}

export function ParametersPanel({ scenario }: ParametersPanelProps) {
  const spacing = scenario.operating.cabin_length_m + scenario.operating.min_clearance_m;
  const spacingLabel = scenario.headway_design ? "station pitch" : "spacing";
  return (
    <section className="panel">
      <header className="panel__header">
        <SlidersHorizontal size={17} />
        <h2>Operating Parameters</h2>
      </header>
      <div className="metric-grid">
        <Metric label="rope speed" value={`${scenario.operating.rope_speed_m_per_s} m/s`} />
        <Metric label="station speed" value={`${scenario.operating.station_speed_m_per_s} m/s`} />
        <Metric label="capacity" value={`${scenario.operating.cabin_capacity} pax`} />
        <Metric label={spacingLabel} value={`${spacing.toFixed(1)} m`} />
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
