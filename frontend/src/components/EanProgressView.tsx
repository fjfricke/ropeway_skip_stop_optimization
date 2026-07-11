import { Activity, AlertTriangle, Clock, GitBranch, Gauge, Target } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import type { MouseEvent } from "react";
import type { EanPassengerServiceResult, EanSolverProgressSample } from "../types";

interface EanProgressViewProps {
  eanPassengerService: EanPassengerServiceResult | null;
  eanPassengerServiceWarning: string | null;
}

interface ChartPoint {
  x: number;
  y: number;
}

interface ProgressChartModel {
  samples: EanSolverProgressSample[];
  maxRuntimeSeconds: number;
  objectiveMin: number;
  objectiveMax: number;
  maxGap: number;
  runtimeTicks: number[];
  objectiveTicks: number[];
  gapTicks: number[];
  incumbentPoints: ChartPoint[];
  boundPoints: ChartPoint[];
  gapPoints: ChartPoint[];
  incumbentEvents: EanSolverProgressSample[];
}

const SVG_WIDTH = 1040;
const SVG_HEIGHT = 420;
const PLOT = { left: 72, right: 82, top: 38, bottom: 48 };
const PLOT_WIDTH = SVG_WIDTH - PLOT.left - PLOT.right;
const PLOT_HEIGHT = SVG_HEIGHT - PLOT.top - PLOT.bottom;

export function EanProgressView({ eanPassengerService, eanPassengerServiceWarning }: EanProgressViewProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [hoveredSample, setHoveredSample] = useState<EanSolverProgressSample | null>(null);
  const samples = eanPassengerService?.metadata.progress_samples ?? [];
  const chart = useMemo(() => buildProgressChartModel(samples), [samples]);

  if (!eanPassengerService || !chart) {
    return (
      <section className="metrics-view metrics-view--empty">
        <AlertTriangle size={18} />
        <strong>{eanPassengerServiceWarning ?? "EAN solver progress unavailable"}</strong>
      </section>
    );
  }

  const finalSample = lastFinalSample(chart.samples) ?? chart.samples[chart.samples.length - 1];
  const activeSample = hoveredSample ?? finalSample;

  function handleMouseMove(event: MouseEvent<SVGSVGElement>) {
    const svg = svgRef.current;
    if (!svg || !chart) return;
    const rect = svg.getBoundingClientRect();
    const svgX = ((event.clientX - rect.left) / rect.width) * SVG_WIDTH;
    const clampedX = Math.max(PLOT.left, Math.min(PLOT.left + PLOT_WIDTH, svgX));
    const runtimeSeconds = ((clampedX - PLOT.left) / PLOT_WIDTH) * chart.maxRuntimeSeconds;
    setHoveredSample(nearestProgressSample(chart.samples, runtimeSeconds));
  }

  return (
    <section className="metrics-view" aria-label="EAN solver progress view">
      <header className="metrics-view__header">
        <div>
          <h2>EAN Progress</h2>
          <p>Solver incumbent, bound, gap, and branch-and-bound search over optimization runtime</p>
        </div>
        <div className="metrics-summary" aria-label="EAN progress summary">
          <span>
            <Target size={15} />
            {formatObjective(eanPassengerService.metadata.objective_passenger_hours)} pax-h
          </span>
          <span>
            <Activity size={15} />
            {formatObjective(objectivePassengerHours(eanPassengerService.metadata.best_bound ?? finalSample.best_bound))} bound
          </span>
          <span>
            <Gauge size={15} />
            {formatGap(eanPassengerService.metadata.mip_gap)}
          </span>
          <span>
            <Clock size={15} />
            {formatRuntime(eanPassengerService.metadata.runtime_seconds ?? finalSample.runtime_seconds)}
          </span>
          <span>
            <GitBranch size={15} />
            {formatInteger(eanPassengerService.metadata.node_count ?? finalSample.node_count)} B&amp;B nodes
          </span>
          <span>
            <Activity size={15} />
            {formatInteger(eanPassengerService.metadata.solution_count ?? finalSample.solution_count)} sol
          </span>
        </div>
      </header>

      <div className="metrics-chart-shell">
        <svg
          ref={svgRef}
          className="metrics-chart"
          viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
          role="img"
          aria-label="EAN solver incumbent, bound, and MIP gap over runtime"
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setHoveredSample(null)}
        >
          <g className="metrics-grid">
            <text className="progress-axis-title progress-axis-title--left" x={PLOT.left} y={16}>
              Objective / bound (pax-h)
            </text>
            <text className="progress-axis-title progress-axis-title--right" x={PLOT.left + PLOT_WIDTH} y={16}>
              MIP gap
            </text>
            {chart.objectiveTicks.map((tick) => {
              const y = objectiveY(tick, chart);
              return (
                <g key={`objective-${tick}`}>
                  <line x1={PLOT.left} x2={PLOT.left + PLOT_WIDTH} y1={y} y2={y} />
                  <text x={PLOT.left - 10} y={y + 4}>
                    {formatCompact(tick)}
                  </text>
                </g>
              );
            })}
            {chart.runtimeTicks.map((tick) => {
              const x = runtimeX(tick, chart.maxRuntimeSeconds);
              return (
                <g key={`runtime-${tick}`}>
                  <line x1={x} x2={x} y1={PLOT.top} y2={PLOT.top + PLOT_HEIGHT} />
                  <text className="metrics-time-label" x={x} y={PLOT.top + PLOT_HEIGHT + 28}>
                    {formatRuntime(tick)}
                  </text>
                </g>
              );
            })}
            {chart.gapTicks.map((tick) => {
              const y = gapY(tick, chart.maxGap);
              return (
                <text className="metrics-right-label" key={`gap-${tick}`} x={PLOT.left + PLOT_WIDTH + 12} y={y + 4}>
                  {formatGap(tick)}
                </text>
              );
            })}
          </g>

          <polyline className="metrics-line progress-line--incumbent" points={pointsToString(chart.incumbentPoints)} />
          <polyline className="metrics-line progress-line--bound" points={pointsToString(chart.boundPoints)} />
          <polyline className="metrics-line progress-line--gap" points={pointsToString(chart.gapPoints)} />

          <g className="progress-events">
            {chart.incumbentEvents.map((sample, index) => (
              <circle
                key={`incumbent-${sample.runtime_seconds}-${index}`}
                cx={runtimeX(sample.runtime_seconds, chart.maxRuntimeSeconds)}
                cy={objectiveY(objectivePassengerHours(sample.incumbent_objective) ?? chart.objectiveMax, chart)}
                r="4"
              />
            ))}
          </g>

          <line className="metrics-axis" x1={PLOT.left} x2={PLOT.left} y1={PLOT.top} y2={PLOT.top + PLOT_HEIGHT} />
          <line className="metrics-axis" x1={PLOT.left} x2={PLOT.left + PLOT_WIDTH} y1={PLOT.top + PLOT_HEIGHT} y2={PLOT.top + PLOT_HEIGHT} />
          <line className="metrics-axis metrics-axis--right" x1={PLOT.left + PLOT_WIDTH} x2={PLOT.left + PLOT_WIDTH} y1={PLOT.top} y2={PLOT.top + PLOT_HEIGHT} />

          {activeSample ? (
            <g className="metrics-hover">
              <line x1={runtimeX(activeSample.runtime_seconds, chart.maxRuntimeSeconds)} x2={runtimeX(activeSample.runtime_seconds, chart.maxRuntimeSeconds)} y1={PLOT.top} y2={PLOT.top + PLOT_HEIGHT} />
              {objectivePassengerHours(activeSample.incumbent_objective) !== null ? (
                <circle
                  cx={runtimeX(activeSample.runtime_seconds, chart.maxRuntimeSeconds)}
                  cy={objectiveY(objectivePassengerHours(activeSample.incumbent_objective) ?? 0, chart)}
                  r="4"
                />
              ) : null}
              {objectivePassengerHours(activeSample.best_bound) !== null ? (
                <circle
                  cx={runtimeX(activeSample.runtime_seconds, chart.maxRuntimeSeconds)}
                  cy={objectiveY(objectivePassengerHours(activeSample.best_bound) ?? 0, chart)}
                  r="4"
                />
              ) : null}
            </g>
          ) : null}
        </svg>
      </div>

      <div className="metrics-lower">
        <section className="panel metrics-tooltip" aria-label="Selected EAN solver progress sample">
          <header className="panel__header">
            <Activity size={17} />
            <h2>{formatRuntime(activeSample.runtime_seconds)}</h2>
          </header>
          <div className="metric-grid">
            <Metric label="event" value={activeSample.event ?? "interval"} />
            <Metric label="incumbent" value={`${formatObjective(objectivePassengerHours(activeSample.incumbent_objective))} pax-h`} />
            <Metric label="best bound" value={`${formatObjective(objectivePassengerHours(activeSample.best_bound))} pax-h`} />
            <Metric label="gap" value={formatGap(activeSample.mip_gap)} />
            <Metric label="nodes" value={formatInteger(activeSample.node_count)} />
            <Metric label="solutions" value={formatInteger(activeSample.solution_count)} />
            <Metric label="work" value={formatDecimal(activeSample.work, 1)} />
          </div>
        </section>

        <section className="panel metrics-breakdown" aria-label="EAN solver progress legend">
          <header className="panel__header">
            <Target size={17} />
            <h2>Series</h2>
          </header>
          <div className="progress-legend">
            <span><i className="progress-legend__swatch progress-legend__swatch--incumbent" /> Incumbent objective</span>
            <span><i className="progress-legend__swatch progress-legend__swatch--bound" /> Best bound</span>
            <span><i className="progress-legend__swatch progress-legend__swatch--gap" /> MIP gap</span>
          </div>
        </section>
      </div>
    </section>
  );
}

function buildProgressChartModel(samples: EanSolverProgressSample[]): ProgressChartModel | null {
  const cleanSamples = samples
    .filter((sample) => Number.isFinite(sample.runtime_seconds))
    .slice()
    .sort((left, right) => left.runtime_seconds - right.runtime_seconds);
  if (cleanSamples.length === 0) return null;

  const objectiveValues = cleanSamples
    .flatMap((sample) => [objectivePassengerHours(sample.incumbent_objective), objectivePassengerHours(sample.best_bound)])
    .filter((value): value is number => value !== null);
  const gapValues = cleanSamples
    .map((sample) => sample.mip_gap)
    .filter((value): value is number => value !== null && Number.isFinite(value));
  const maxRuntimeSeconds = Math.max(1, ...cleanSamples.map((sample) => sample.runtime_seconds));
  const objectiveMinRaw = objectiveValues.length ? Math.min(...objectiveValues) : 0;
  const objectiveMaxRaw = objectiveValues.length ? Math.max(...objectiveValues) : 1;
  const objectivePadding = Math.max(0.1, (objectiveMaxRaw - objectiveMinRaw) * 0.08);
  const objectiveMin = Math.max(0, objectiveMinRaw - objectivePadding);
  const objectiveMax = objectiveMaxRaw + objectivePadding;
  const maxGap = Math.max(0.01, ...gapValues);

  const chartBase = {
    maxRuntimeSeconds,
    objectiveMin,
    objectiveMax,
    maxGap,
  };

  return {
    samples: cleanSamples,
    ...chartBase,
    runtimeTicks: ticks(0, maxRuntimeSeconds, 5),
    objectiveTicks: ticks(objectiveMin, objectiveMax, 5),
    gapTicks: ticks(0, maxGap, 5),
    incumbentPoints: cleanSamples
      .map((sample) => pointForObjective(sample.runtime_seconds, sample.incumbent_objective, chartBase))
      .filter((point): point is ChartPoint => point !== null),
    boundPoints: cleanSamples
      .map((sample) => pointForObjective(sample.runtime_seconds, sample.best_bound, chartBase))
      .filter((point): point is ChartPoint => point !== null),
    gapPoints: cleanSamples
      .map((sample) => pointForGap(sample.runtime_seconds, sample.mip_gap, chartBase))
      .filter((point): point is ChartPoint => point !== null),
    incumbentEvents: cleanSamples.filter((sample) => sample.event === "incumbent" && objectivePassengerHours(sample.incumbent_objective) !== null),
  };
}

function pointForObjective(
  runtimeSeconds: number,
  objectiveSeconds: number | null | undefined,
  chart: Pick<ProgressChartModel, "maxRuntimeSeconds" | "objectiveMin" | "objectiveMax">,
): ChartPoint | null {
  const value = objectivePassengerHours(objectiveSeconds);
  if (value === null) return null;
  return {
    x: runtimeX(runtimeSeconds, chart.maxRuntimeSeconds),
    y: objectiveY(value, chart),
  };
}

function pointForGap(
  runtimeSeconds: number,
  gap: number | null | undefined,
  chart: Pick<ProgressChartModel, "maxRuntimeSeconds" | "maxGap">,
): ChartPoint | null {
  if (gap === null || gap === undefined || !Number.isFinite(gap)) return null;
  return {
    x: runtimeX(runtimeSeconds, chart.maxRuntimeSeconds),
    y: gapY(gap, chart.maxGap),
  };
}

function nearestProgressSample(samples: EanSolverProgressSample[], runtimeSeconds: number) {
  return samples.reduce((best, sample) => (
    Math.abs(sample.runtime_seconds - runtimeSeconds) < Math.abs(best.runtime_seconds - runtimeSeconds) ? sample : best
  ), samples[0]);
}

function lastFinalSample(samples: EanSolverProgressSample[]) {
  for (let index = samples.length - 1; index >= 0; index -= 1) {
    if (samples[index].event === "final") return samples[index];
  }
  return null;
}

function runtimeX(runtimeSeconds: number, maxRuntimeSeconds: number) {
  return PLOT.left + (runtimeSeconds / maxRuntimeSeconds) * PLOT_WIDTH;
}

function objectiveY(value: number, chart: Pick<ProgressChartModel, "objectiveMin" | "objectiveMax">) {
  const range = Math.max(1e-9, chart.objectiveMax - chart.objectiveMin);
  return PLOT.top + PLOT_HEIGHT - ((value - chart.objectiveMin) / range) * PLOT_HEIGHT;
}

function gapY(value: number, maxGap: number) {
  return PLOT.top + PLOT_HEIGHT - (Math.max(0, value) / maxGap) * PLOT_HEIGHT;
}

function objectivePassengerHours(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return null;
  return value / 3600;
}

function pointsToString(points: ChartPoint[]) {
  return points.map((point) => `${round(point.x)},${round(point.y)}`).join(" ");
}

function ticks(min: number, max: number, count: number) {
  if (count <= 1 || max <= min) return [min, max];
  const step = (max - min) / (count - 1);
  return Array.from({ length: count }, (_, index) => min + step * index);
}

function round(value: number) {
  return Math.round(value * 10) / 10;
}

function formatObjective(value: number | null | undefined) {
  return formatDecimal(value, 2);
}

function formatGap(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "n/a";
  return `${formatDecimal(value * 100, value < 0.01 ? 2 : 1)}%`;
}

function formatRuntime(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "n/a";
  if (seconds < 60) return `${formatDecimal(seconds, seconds < 10 ? 1 : 0)}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  return `${minutes}m ${String(remainder).padStart(2, "0")}s`;
}

function formatInteger(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "n/a";
  return Math.round(value).toLocaleString("en-US");
}

function formatDecimal(value: number | null | undefined, digits: number) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "n/a";
  return value.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatCompact(value: number) {
  return new Intl.NumberFormat("en-US", {
    notation: Math.abs(value) >= 10000 ? "compact" : "standard",
    maximumFractionDigits: Math.abs(value) >= 100 ? 0 : 1,
  }).format(value);
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
