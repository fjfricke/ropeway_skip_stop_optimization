import { Activity, AlertTriangle, Clock, TimerReset, Users } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import type { MouseEvent } from "react";
import type { ReplayMetrics, ReplayMetricsStep, Scenario } from "../types";

interface MetricsViewProps {
  scenario: Scenario;
  replayMetrics: ReplayMetrics | null;
  replayMetricsWarning: string | null;
}

interface ChartPoint {
  x: number;
  y: number;
}

const SVG_WIDTH = 1040;
const SVG_HEIGHT = 420;
const PLOT = { left: 58, right: 74, top: 24, bottom: 48 };
const PLOT_WIDTH = SVG_WIDTH - PLOT.left - PLOT.right;
const PLOT_HEIGHT = SVG_HEIGHT - PLOT.top - PLOT.bottom;

export function MetricsView({ scenario, replayMetrics, replayMetricsWarning }: MetricsViewProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [hoveredStep, setHoveredStep] = useState<ReplayMetricsStep | null>(null);
  const chart = useMemo(() => (replayMetrics ? buildChartModel(replayMetrics) : null), [replayMetrics]);

  if (!replayMetrics || !chart) {
    return (
      <section className="metrics-view metrics-view--empty">
        <AlertTriangle size={18} />
        <strong>{replayMetricsWarning ?? "Replay metrics unavailable"}</strong>
      </section>
    );
  }

  const activeStep = hoveredStep ?? replayMetrics.steps[0];
  const totalArrivals = replayMetrics.steps.reduce((sum, step) => sum + step.arrivals_count, 0);
  const finalStep = replayMetrics.steps[replayMetrics.steps.length - 1];

  function handleMouseMove(event: MouseEvent<SVGSVGElement>) {
    const svg = svgRef.current;
    if (!svg || !chart) return;
    const rect = svg.getBoundingClientRect();
    const svgX = ((event.clientX - rect.left) / rect.width) * SVG_WIDTH;
    const clampedX = Math.max(PLOT.left, Math.min(PLOT.left + PLOT_WIDTH, svgX));
    const rawStep = Math.round(((clampedX - PLOT.left) / PLOT_WIDTH) * chart.maxStep);
    setHoveredStep(replayMetrics?.steps[Math.max(0, Math.min(chart.maxStep, rawStep))] ?? null);
  }

  return (
    <section className="metrics-view" aria-label="Replay metrics view">
      <header className="metrics-view__header">
        <div>
          <h2>Replay Metrics</h2>
          <p>Demand, alightings, queues, in-transit passengers, and accumulated passenger-hours</p>
        </div>
        <div className="metrics-summary" aria-label="Replay metrics summary">
          <span>
            <Users size={15} />
            {formatInteger(totalArrivals)} pax
          </span>
          <span>
            <Activity size={15} />
            {formatInteger(chart.maxPassengerCount)} peak count
          </span>
          <span>
            <TimerReset size={15} />
            {formatDecimal(finalStep.cumulative_waiting_passenger_hours, 1)} pax-h
          </span>
        </div>
      </header>

      <div className="metrics-chart-shell">
        <svg
          ref={svgRef}
          className="metrics-chart"
          viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
          role="img"
          aria-label="Replay demand and waiting time chart"
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setHoveredStep(null)}
        >
          <g className="metrics-grid">
            {chart.passengerTicks.map((tick) => {
              const y = passengerY(tick, chart.maxPassengerCount);
              return (
                <g key={`left-${tick}`}>
                  <line x1={PLOT.left} x2={PLOT.left + PLOT_WIDTH} y1={y} y2={y} />
                  <text x={PLOT.left - 10} y={y + 4}>
                    {formatCompact(tick)}
                  </text>
                </g>
              );
            })}
            {chart.timeTicks.map((tick) => {
              const x = timeX(tick, chart.maxStep);
              return (
                <g key={`time-${tick}`}>
                  <line x1={x} x2={x} y1={PLOT.top} y2={PLOT.top + PLOT_HEIGHT} />
                  <text className="metrics-time-label" x={x} y={PLOT.top + PLOT_HEIGHT + 28}>
                    {clockLabel(scenario.service_start_time, tick, replayMetrics.delta_seconds)}
                  </text>
                </g>
              );
            })}
            {chart.waitingHourTicks.map((tick) => {
              const y = cumulativeY(tick, chart.maxCumulativeWaitingHours);
              return (
                <text className="metrics-right-label" key={`right-${tick}`} x={PLOT.left + PLOT_WIDTH + 12} y={y + 4}>
                  {formatCompact(tick)}
                </text>
              );
            })}
          </g>

          <g className="metrics-bars metrics-bars--arrivals">
            {chart.arrivalBars.map((step) => (
              <rect
                key={`arrival-${step.time_step}`}
                x={timeX(step.time_step, chart.maxStep) - chart.barWidth / 2}
                y={passengerY(step.arrivals_count, chart.maxPassengerCount)}
                width={chart.barWidth}
                height={PLOT.top + PLOT_HEIGHT - passengerY(step.arrivals_count, chart.maxPassengerCount)}
              />
            ))}
          </g>
          <g className="metrics-bars metrics-bars--alightings">
            {chart.alightingBars.map((step) => (
              <rect
                key={`alighting-${step.time_step}`}
                x={timeX(step.time_step, chart.maxStep) - chart.barWidth / 2}
                y={passengerY(step.alighting_count, chart.maxPassengerCount)}
                width={chart.barWidth}
                height={PLOT.top + PLOT_HEIGHT - passengerY(step.alighting_count, chart.maxPassengerCount)}
              />
            ))}
          </g>

          <polyline className="metrics-line metrics-line--waiting" points={pointsToString(chart.waitingPoints)} />
          <polyline className="metrics-line metrics-line--onboard" points={pointsToString(chart.onboardPoints)} />
          <polyline className="metrics-line metrics-line--cumulative" points={pointsToString(chart.cumulativePoints)} />

          <line className="metrics-axis" x1={PLOT.left} x2={PLOT.left} y1={PLOT.top} y2={PLOT.top + PLOT_HEIGHT} />
          <line className="metrics-axis" x1={PLOT.left} x2={PLOT.left + PLOT_WIDTH} y1={PLOT.top + PLOT_HEIGHT} y2={PLOT.top + PLOT_HEIGHT} />
          <line className="metrics-axis metrics-axis--right" x1={PLOT.left + PLOT_WIDTH} x2={PLOT.left + PLOT_WIDTH} y1={PLOT.top} y2={PLOT.top + PLOT_HEIGHT} />

          {activeStep ? (
            <g className="metrics-hover">
              <line x1={timeX(activeStep.time_step, chart.maxStep)} x2={timeX(activeStep.time_step, chart.maxStep)} y1={PLOT.top} y2={PLOT.top + PLOT_HEIGHT} />
              <circle cx={timeX(activeStep.time_step, chart.maxStep)} cy={passengerY(activeStep.waiting_count, chart.maxPassengerCount)} r="4" />
              <circle cx={timeX(activeStep.time_step, chart.maxStep)} cy={passengerY(activeStep.onboard_count, chart.maxPassengerCount)} r="4" />
            </g>
          ) : null}
        </svg>
      </div>

      <div className="metrics-lower">
        <section className="panel metrics-tooltip" aria-label="Selected metrics step">
          <header className="panel__header">
            <Clock size={17} />
            <h2>{clockLabel(scenario.service_start_time, activeStep.time_step, replayMetrics.delta_seconds)}</h2>
          </header>
          <div className="metric-grid">
            <Metric label="step" value={activeStep.time_step} />
            <Metric label="arrivals" value={activeStep.arrivals_count} />
            <Metric label="boardings" value={activeStep.boarding_count} />
            <Metric label="alightings" value={activeStep.alighting_count} />
            <Metric label="waiting" value={activeStep.waiting_count} />
            <Metric label="onboard" value={activeStep.onboard_count} />
            <Metric label="waiting pax-h" value={formatDecimal(activeStep.cumulative_waiting_passenger_hours, 2)} />
          </div>
        </section>

        <section className="panel metrics-breakdown" aria-label="Waiting by station">
          <header className="panel__header">
            <Users size={17} />
            <h2>Waiting By Station</h2>
          </header>
          <BreakdownRows rows={activeStep.waiting_by_station.map((row) => ({ id: row.station_id, count: row.count }))} empty="No waiting passengers" />
        </section>

        <section className="panel metrics-breakdown" aria-label="Onboard by OD">
          <header className="panel__header">
            <Activity size={17} />
            <h2>Onboard By OD</h2>
          </header>
          <BreakdownRows rows={activeStep.onboard_by_od.map((row) => ({ id: `${row.origin}->${row.destination}`, count: row.count }))} empty="No onboard passengers" />
        </section>
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{typeof value === "number" ? formatInteger(value) : value}</strong>
    </div>
  );
}

function BreakdownRows({ rows, empty }: { rows: { id: string; count: number }[]; empty: string }) {
  if (rows.length === 0) return <div className="empty-panel">{empty}</div>;
  const maxCount = Math.max(...rows.map((row) => row.count), 1);
  return (
    <div className="metrics-breakdown__rows">
      {rows.map((row) => (
        <div className="metrics-breakdown__row" key={row.id}>
          <span>{row.id}</span>
          <div className="metrics-breakdown__bar">
            <span style={{ width: `${Math.max(4, (row.count / maxCount) * 100)}%` }} />
          </div>
          <strong>{formatInteger(row.count)}</strong>
        </div>
      ))}
    </div>
  );
}

function buildChartModel(metrics: ReplayMetrics) {
  const maxStep = Math.max(metrics.movement_plan_horizon_steps, metrics.steps.length - 1, 1);
  const maxPassengerCount = Math.max(
    1,
    ...metrics.steps.map((step) => Math.max(step.arrivals_count, step.alighting_count, step.waiting_count, step.onboard_count)),
  );
  const maxCumulativeWaitingHours = Math.max(
    1,
    ...metrics.steps.map((step) => step.cumulative_waiting_passenger_hours),
  );
  const waitingPoints = metrics.steps.map((step) => ({
    x: timeX(step.time_step, maxStep),
    y: passengerY(step.waiting_count, maxPassengerCount),
  }));
  const onboardPoints = metrics.steps.map((step) => ({
    x: timeX(step.time_step, maxStep),
    y: passengerY(step.onboard_count, maxPassengerCount),
  }));
  const cumulativePoints = metrics.steps.map((step) => ({
    x: timeX(step.time_step, maxStep),
    y: cumulativeY(step.cumulative_waiting_passenger_hours, maxCumulativeWaitingHours),
  }));
  return {
    maxStep,
    maxPassengerCount,
    maxCumulativeWaitingHours,
    passengerTicks: ticks(maxPassengerCount, 4),
    waitingHourTicks: ticks(maxCumulativeWaitingHours, 4),
    timeTicks: ticks(maxStep, 5),
    barWidth: Math.max(2, PLOT_WIDTH / maxStep),
    arrivalBars: metrics.steps.filter((step) => step.arrivals_count > 0),
    alightingBars: metrics.steps.filter((step) => step.alighting_count > 0),
    waitingPoints,
    onboardPoints,
    cumulativePoints,
  };
}

function timeX(timeStep: number, maxStep: number) {
  return PLOT.left + (timeStep / maxStep) * PLOT_WIDTH;
}

function passengerY(value: number, maxValue: number) {
  return PLOT.top + PLOT_HEIGHT - (value / maxValue) * PLOT_HEIGHT;
}

function cumulativeY(value: number, maxValue: number) {
  return PLOT.top + PLOT_HEIGHT - (value / maxValue) * PLOT_HEIGHT;
}

function pointsToString(points: ChartPoint[]) {
  return points.map((point) => `${round(point.x)},${round(point.y)}`).join(" ");
}

function ticks(maxValue: number, count: number) {
  if (maxValue <= 0) return [0];
  return Array.from({ length: count + 1 }, (_, index) => Math.round((maxValue / count) * index));
}

function clockLabel(startTime: string, timeStep: number, deltaSeconds: number) {
  const [hours = 0, minutes = 0, seconds = 0] = startTime.split(":").map(Number);
  const totalSeconds = hours * 3600 + minutes * 60 + seconds + timeStep * deltaSeconds;
  const normalized = ((totalSeconds % 86400) + 86400) % 86400;
  const wholeSeconds = Math.floor(normalized);
  const hh = Math.floor(wholeSeconds / 3600);
  const mm = Math.floor((wholeSeconds % 3600) / 60);
  const ss = wholeSeconds % 60;
  return `${pad2(hh)}:${pad2(mm)}:${pad2(ss)}`;
}

function pad2(value: number) {
  return String(value).padStart(2, "0");
}

function formatInteger(value: number) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}

function formatCompact(value: number) {
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function formatDecimal(value: number, maximumFractionDigits: number) {
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: value > 0 && value < 1 ? Math.min(2, maximumFractionDigits) : 0,
    maximumFractionDigits,
  }).format(value);
}

function round(value: number) {
  return Math.round(value * 10) / 10;
}
