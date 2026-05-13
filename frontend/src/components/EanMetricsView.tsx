import { Activity, AlertTriangle, Clock, TimerReset, Users } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import type { MouseEvent } from "react";
import type { EanPassengerServiceResult, Scenario } from "../types";

interface EanMetricsViewProps {
  scenario: Scenario;
  eanPassengerService: EanPassengerServiceResult | null;
  eanPassengerServiceWarning: string | null;
}

interface EanMetricStep {
  time_seconds: number;
  arrivals_count: number;
  boarding_count: number;
  alighting_count: number;
  waiting_count: number;
  onboard_count: number;
  cumulative_objective_passenger_hours: number;
  waiting_by_station: { station_id: string; count: number }[];
  onboard_by_od: { origin: string; destination: string; count: number }[];
}

interface ChartPoint {
  x: number;
  y: number;
}

interface DemandInfo {
  id: string;
  index: number;
  origin: string;
  destination: string;
  releaseSeconds: number;
  count: number;
}

interface TimelineEvent {
  timeSeconds: number;
  arrivals: DemandInfo[];
  boardings: { demand: DemandInfo; count: number }[];
  alightings: { demand: DemandInfo; count: number }[];
}

const SVG_WIDTH = 1040;
const SVG_HEIGHT = 420;
const PLOT = { left: 58, right: 74, top: 24, bottom: 48 };
const PLOT_WIDTH = SVG_WIDTH - PLOT.left - PLOT.right;
const PLOT_HEIGHT = SVG_HEIGHT - PLOT.top - PLOT.bottom;

export function EanMetricsView({ scenario, eanPassengerService, eanPassengerServiceWarning }: EanMetricsViewProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [hoveredStep, setHoveredStep] = useState<EanMetricStep | null>(null);
  const metrics = useMemo(
    () => (eanPassengerService?.passenger_plan ? buildEanMetricSteps(scenario, eanPassengerService) : null),
    [eanPassengerService, scenario],
  );
  const chart = useMemo(() => (metrics ? buildChartModel(metrics.steps) : null), [metrics]);

  if (!eanPassengerService?.passenger_plan || !metrics || !chart) {
    return (
      <section className="metrics-view metrics-view--empty">
        <AlertTriangle size={18} />
        <strong>{eanPassengerServiceWarning ?? "EAN passenger metrics unavailable"}</strong>
      </section>
    );
  }

  const activeStep = hoveredStep ?? metrics.steps[0];
  const finalStep = metrics.steps[metrics.steps.length - 1];

  function handleMouseMove(event: MouseEvent<SVGSVGElement>) {
    const svg = svgRef.current;
    if (!svg || !chart) return;
    const rect = svg.getBoundingClientRect();
    const svgX = ((event.clientX - rect.left) / rect.width) * SVG_WIDTH;
    const clampedX = Math.max(PLOT.left, Math.min(PLOT.left + PLOT_WIDTH, svgX));
    const rawSeconds = ((clampedX - PLOT.left) / PLOT_WIDTH) * chart.maxSeconds;
    setHoveredStep(nearestStep(metrics?.steps ?? [], rawSeconds));
  }

  return (
    <section className="metrics-view" aria-label="EAN passenger metrics view">
      <header className="metrics-view__header">
        <div>
          <h2>EAN Metrics</h2>
          <p>Continuous passenger queues, onboard loads, events, and accumulated objective over time</p>
        </div>
        <div className="metrics-summary" aria-label="EAN metrics summary">
          <span>
            <Users size={15} />
            {formatInteger(metrics.totalPassengers)} pax
          </span>
          <span>
            <Activity size={15} />
            {formatInteger(chart.maxPassengerCount)} peak count
          </span>
          <span>
            <TimerReset size={15} />
            {objectiveLabel(eanPassengerService.metadata.objective_kind)} · {formatDecimal(finalStep.cumulative_objective_passenger_hours, 1)} pax-h
          </span>
        </div>
      </header>

      <div className="metrics-chart-shell">
        <svg
          ref={svgRef}
          className="metrics-chart"
          viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
          role="img"
          aria-label="EAN passenger objective and queue chart"
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
              const x = secondsX(tick, chart.maxSeconds);
              return (
                <g key={`time-${tick}`}>
                  <line x1={x} x2={x} y1={PLOT.top} y2={PLOT.top + PLOT_HEIGHT} />
                  <text className="metrics-time-label" x={x} y={PLOT.top + PLOT_HEIGHT + 28}>
                    {clockLabel(scenario.service_start_time, tick)}
                  </text>
                </g>
              );
            })}
            {chart.objectiveTicks.map((tick) => {
              const y = cumulativeY(tick, chart.maxObjectivePassengerHours);
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
                key={`arrival-${step.time_seconds}`}
                x={secondsX(step.time_seconds, chart.maxSeconds) - chart.barWidth / 2}
                y={passengerY(step.arrivals_count, chart.maxPassengerCount)}
                width={chart.barWidth}
                height={PLOT.top + PLOT_HEIGHT - passengerY(step.arrivals_count, chart.maxPassengerCount)}
              />
            ))}
          </g>
          <g className="metrics-bars metrics-bars--boardings">
            {chart.boardingBars.map((step) => (
              <rect
                key={`boarding-${step.time_seconds}`}
                x={secondsX(step.time_seconds, chart.maxSeconds) - chart.barWidth / 2}
                y={passengerY(step.boarding_count, chart.maxPassengerCount)}
                width={chart.barWidth}
                height={PLOT.top + PLOT_HEIGHT - passengerY(step.boarding_count, chart.maxPassengerCount)}
              />
            ))}
          </g>
          <g className="metrics-bars metrics-bars--alightings">
            {chart.alightingBars.map((step) => (
              <rect
                key={`alighting-${step.time_seconds}`}
                x={secondsX(step.time_seconds, chart.maxSeconds) - chart.barWidth / 2}
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
              <line x1={secondsX(activeStep.time_seconds, chart.maxSeconds)} x2={secondsX(activeStep.time_seconds, chart.maxSeconds)} y1={PLOT.top} y2={PLOT.top + PLOT_HEIGHT} />
              <circle cx={secondsX(activeStep.time_seconds, chart.maxSeconds)} cy={passengerY(activeStep.waiting_count, chart.maxPassengerCount)} r="4" />
              <circle cx={secondsX(activeStep.time_seconds, chart.maxSeconds)} cy={passengerY(activeStep.onboard_count, chart.maxPassengerCount)} r="4" />
            </g>
          ) : null}
        </svg>
      </div>

      <div className="metrics-lower">
        <section className="panel metrics-tooltip" aria-label="Selected EAN metrics time">
          <header className="panel__header">
            <Clock size={17} />
            <h2>{clockLabel(scenario.service_start_time, activeStep.time_seconds)}</h2>
          </header>
          <div className="metric-grid">
            <Metric label="time" value={formatSeconds(activeStep.time_seconds)} />
            <Metric label="arrivals" value={activeStep.arrivals_count} />
            <Metric label="boardings" value={activeStep.boarding_count} />
            <Metric label="alightings" value={activeStep.alighting_count} />
            <Metric label="waiting" value={activeStep.waiting_count} />
            <Metric label="onboard" value={activeStep.onboard_count} />
            <Metric label="objective pax-h" value={formatDecimal(activeStep.cumulative_objective_passenger_hours, 2)} />
          </div>
        </section>

        <section className="panel metrics-breakdown" aria-label="EAN waiting by station">
          <header className="panel__header">
            <Users size={17} />
            <h2>Waiting By Station</h2>
          </header>
          <BreakdownRows rows={activeStep.waiting_by_station.map((row) => ({ id: row.station_id, count: row.count }))} empty="No waiting passengers" />
        </section>

        <section className="panel metrics-breakdown" aria-label="EAN onboard by OD">
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

function buildEanMetricSteps(scenario: Scenario, result: EanPassengerServiceResult) {
  const plan = result.passenger_plan;
  if (!plan) return null;
  const demandById = new Map<string, DemandInfo>();
  scenario.demands.forEach((demand, index) => {
    const id = `demand::${index}`;
    demandById.set(id, {
      id,
      index,
      origin: demand.origin,
      destination: demand.destination,
      releaseSeconds: releaseSeconds(scenario.service_start_time, demand.arrival_time),
      count: demand.count,
    });
  });

  const eventsByTime = new Map<number, TimelineEvent>();
  const eventAt = (timeSeconds: number) => {
    const key = roundTime(timeSeconds);
    let event = eventsByTime.get(key);
    if (!event) {
      event = { timeSeconds: key, arrivals: [], boardings: [], alightings: [] };
      eventsByTime.set(key, event);
    }
    return event;
  };

  for (const demand of demandById.values()) {
    eventAt(demand.releaseSeconds).arrivals.push(demand);
  }

  for (const ride of plan.served_rides) {
    const demand = demandById.get(ride.demand_group_id);
    if (!demand || ride.count <= 0) continue;
    eventAt(ride.boarding_time_seconds).boardings.push({ demand, count: ride.count });
    eventAt(ride.alighting_time_seconds).alightings.push({ demand, count: ride.count });
  }

  eventAt(plan.horizon_seconds);

  const waitingByDemandId = new Map<string, number>();
  const onboardByOd = new Map<string, { origin: string; destination: string; count: number }>();
  const steps: EanMetricStep[] = [];
  let previousTime = 0;
  let cumulativeObjectiveSeconds = 0;
  let waitingCount = 0;
  let onboardCount = 0;
  const sortedEvents = Array.from(eventsByTime.values()).sort((left, right) => left.timeSeconds - right.timeSeconds);

  for (const event of sortedEvents) {
    const deltaSeconds = Math.max(0, event.timeSeconds - previousTime);
    const objectiveCount = result.metadata.objective_kind === "journey_time" ? waitingCount + onboardCount : waitingCount;
    cumulativeObjectiveSeconds += objectiveCount * deltaSeconds;
    previousTime = event.timeSeconds;

    let arrivalsCount = 0;
    let boardingCount = 0;
    let alightingCount = 0;

    for (const arrival of event.arrivals) {
      arrivalsCount += arrival.count;
      waitingCount += arrival.count;
      waitingByDemandId.set(arrival.id, (waitingByDemandId.get(arrival.id) ?? 0) + arrival.count);
    }

    for (const boarding of event.boardings) {
      boardingCount += boarding.count;
      waitingCount -= boarding.count;
      onboardCount += boarding.count;
      waitingByDemandId.set(boarding.demand.id, (waitingByDemandId.get(boarding.demand.id) ?? 0) - boarding.count);
      const odKey = `${boarding.demand.origin}->${boarding.demand.destination}`;
      const current = onboardByOd.get(odKey) ?? { origin: boarding.demand.origin, destination: boarding.demand.destination, count: 0 };
      current.count += boarding.count;
      onboardByOd.set(odKey, current);
    }

    for (const alighting of event.alightings) {
      alightingCount += alighting.count;
      onboardCount -= alighting.count;
      const odKey = `${alighting.demand.origin}->${alighting.demand.destination}`;
      const current = onboardByOd.get(odKey);
      if (current) {
        current.count -= alighting.count;
        if (current.count <= 0) onboardByOd.delete(odKey);
      }
    }

    steps.push({
      time_seconds: event.timeSeconds,
      arrivals_count: arrivalsCount,
      boarding_count: boardingCount,
      alighting_count: alightingCount,
      waiting_count: Math.max(0, waitingCount),
      onboard_count: Math.max(0, onboardCount),
      cumulative_objective_passenger_hours: cumulativeObjectiveSeconds / 3600,
      waiting_by_station: waitingBreakdown(waitingByDemandId, demandById),
      onboard_by_od: onboardBreakdown(onboardByOd),
    });
  }

  return {
    steps,
    totalPassengers: scenario.demands.reduce((sum, demand) => sum + demand.count, 0),
  };
}

function onboardBreakdown(onboardByOd: Map<string, { origin: string; destination: string; count: number }>) {
  return Array.from(onboardByOd.values(), (row) => ({ ...row }))
    .filter((row) => row.count > 0)
    .sort(compareOdRows);
}

function waitingBreakdown(waitingByDemandId: Map<string, number>, demandById: Map<string, DemandInfo>) {
  const byStation = new Map<string, number>();
  for (const [demandId, count] of waitingByDemandId) {
    if (count <= 0) continue;
    const demand = demandById.get(demandId);
    if (!demand) continue;
    byStation.set(demand.origin, (byStation.get(demand.origin) ?? 0) + count);
  }
  return Array.from(byStation, ([station_id, count]) => ({ station_id, count })).sort((left, right) => left.station_id.localeCompare(right.station_id));
}

function buildChartModel(steps: EanMetricStep[]) {
  const maxSeconds = Math.max(1, ...steps.map((step) => step.time_seconds));
  const maxPassengerCount = Math.max(
    1,
    ...steps.map((step) => Math.max(step.arrivals_count, step.boarding_count, step.alighting_count, step.waiting_count, step.onboard_count)),
  );
  const maxObjectivePassengerHours = Math.max(1, ...steps.map((step) => step.cumulative_objective_passenger_hours));
  return {
    maxSeconds,
    maxPassengerCount,
    maxObjectivePassengerHours,
    passengerTicks: ticks(maxPassengerCount, 4),
    objectiveTicks: ticks(maxObjectivePassengerHours, 4),
    timeTicks: ticks(maxSeconds, 5),
    barWidth: Math.max(2, Math.min(18, PLOT_WIDTH / Math.max(steps.length, 1))),
    arrivalBars: steps.filter((step) => step.arrivals_count > 0),
    boardingBars: steps.filter((step) => step.boarding_count > 0),
    alightingBars: steps.filter((step) => step.alighting_count > 0),
    waitingPoints: steps.map((step) => ({ x: secondsX(step.time_seconds, maxSeconds), y: passengerY(step.waiting_count, maxPassengerCount) })),
    onboardPoints: steps.map((step) => ({ x: secondsX(step.time_seconds, maxSeconds), y: passengerY(step.onboard_count, maxPassengerCount) })),
    cumulativePoints: steps.map((step) => ({ x: secondsX(step.time_seconds, maxSeconds), y: cumulativeY(step.cumulative_objective_passenger_hours, maxObjectivePassengerHours) })),
  };
}

function nearestStep(steps: EanMetricStep[], timeSeconds: number) {
  if (steps.length === 0) return null;
  return steps.reduce((best, step) => (Math.abs(step.time_seconds - timeSeconds) < Math.abs(best.time_seconds - timeSeconds) ? step : best), steps[0]);
}

function secondsX(timeSeconds: number, maxSeconds: number) {
  return PLOT.left + (timeSeconds / maxSeconds) * PLOT_WIDTH;
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

function releaseSeconds(serviceStartTime: string, arrivalTime: string) {
  return timeOfDaySeconds(arrivalTime) - timeOfDaySeconds(serviceStartTime);
}

function timeOfDaySeconds(value: string) {
  const [hours = 0, minutes = 0, seconds = 0] = value.split(":").map(Number);
  return hours * 3600 + minutes * 60 + seconds;
}

function clockLabel(startTime: string, secondsOffset: number) {
  const totalSeconds = timeOfDaySeconds(startTime) + secondsOffset;
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

function formatSeconds(value: number) {
  return `${value.toFixed(value % 1 === 0 ? 0 : 1)}s`;
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

function objectiveLabel(value: string) {
  return value.replaceAll("_", " ");
}

function compareOdRows(left: { origin: string; destination: string }, right: { origin: string; destination: string }) {
  return left.origin.localeCompare(right.origin) || left.destination.localeCompare(right.destination);
}

function round(value: number) {
  return Math.round(value * 10) / 10;
}

function roundTime(value: number) {
  return Math.round(value * 1_000_000) / 1_000_000;
}
