import { AlertTriangle, GitCommitHorizontal, TimerReset } from "lucide-react";
import { useMemo } from "react";
import type { DiscreteScenario, EanPassengerServiceResult, Scenario, SpeedProfile, TrackSegment } from "../types";

interface GraphSlackViewProps {
  scenario: Scenario;
  discreteScenario: DiscreteScenario | null;
  eanPassengerService?: EanPassengerServiceResult | null;
}

interface SegmentSlackRow {
  segment: TrackSegment;
  physicalSeconds: number;
  discreteSeconds: number;
  durationSteps: number;
  slackSeconds: number;
}

export function GraphSlackView({ scenario, discreteScenario, eanPassengerService = null }: GraphSlackViewProps) {
  const rows = useMemo(
    () => (discreteScenario ? buildSegmentSlackRows(scenario, discreteScenario) : []),
    [scenario, discreteScenario],
  );
  const maxSlackSeconds = Math.max(...rows.map((row) => row.slackSeconds), 0);
  const totalSlackSeconds = rows.reduce((total, row) => total + row.slackSeconds, 0);
  const roundedSegments = rows.filter((row) => row.slackSeconds > 1e-9).length;

  if (!discreteScenario) {
    return (
      <section className="graph-view graph-view--empty">
        <AlertTriangle size={18} />
        <strong>Discrete graph unavailable</strong>
      </section>
    );
  }

  return (
    <section className="graph-view" aria-label="Discrete graph slack view">
      <header className="graph-view__header">
        <div>
          <h2>Discrete Graph Slack</h2>
          <p>Rounding slack per physical track segment at {discreteScenario.delta_seconds}s steps</p>
        </div>
        <div className="graph-view__summary" aria-label="Slack summary">
          <span>
            <TimerReset size={15} />
            {formatSeconds(totalSlackSeconds)} total slack
          </span>
          <span>
            <GitCommitHorizontal size={15} />
            {roundedSegments} rounded segments
          </span>
          {eanPassengerService ? (
            <span>
              <TimerReset size={15} />
              {objectiveLabel(eanPassengerService.metadata.objective_kind)} · {formatPassengerHours(eanPassengerService.metadata.objective_passenger_hours)}
            </span>
          ) : null}
        </div>
      </header>

      {eanPassengerService ? (
        <section className="graph-objective-panel" aria-label="EAN objective summary">
          <div className="metric">
            <span>solver status</span>
            <strong>{eanPassengerService.metadata.solver_status ?? eanPassengerService.metadata.status}</strong>
          </div>
          <div className="metric">
            <span>gap</span>
            <strong>{formatPercent(eanPassengerService.metadata.mip_gap)}</strong>
          </div>
          <div className="metric">
            <span>best bound</span>
            <strong>{formatPassengerSecondsAsHours(eanPassengerService.metadata.best_bound)}</strong>
          </div>
          <div className="metric">
            <span>runtime</span>
            <strong>{formatOptionalSeconds(eanPassengerService.metadata.runtime_seconds)}</strong>
          </div>
          <div className="metric">
            <span>served</span>
            <strong>{formatInteger(eanPassengerService.metadata.served_passenger_count)}</strong>
          </div>
          <div className="metric">
            <span>unserved</span>
            <strong>{formatInteger(eanPassengerService.metadata.unserved_passenger_count)}</strong>
          </div>
          <div className="metric">
            <span>visible skips</span>
            <strong>{formatInteger(eanPassengerService.metadata.visible_skipped_visit_count)}</strong>
          </div>
        </section>
      ) : null}

      <div className="slack-table" role="table" aria-label="Segment slack table">
        <div className="slack-row slack-row--header" role="row">
          <span>segment</span>
          <span>kind</span>
          <span>steps</span>
          <span>physical</span>
          <span>discrete</span>
          <span>slack</span>
          <span>graph</span>
        </div>
        {rows.map((row) => (
          <div className="slack-row" role="row" key={row.segment.id}>
            <strong>{row.segment.id}</strong>
            <span className={`slack-kind slack-kind--${row.segment.kind}`}>{row.segment.kind}</span>
            <span>{row.durationSteps}</span>
            <span>{formatSeconds(row.physicalSeconds)}</span>
            <span>{formatSeconds(row.discreteSeconds)}</span>
            <span className={row.slackSeconds > 1e-9 ? "slack-value slack-value--positive" : "slack-value"}>
              {formatSeconds(row.slackSeconds)}
            </span>
            <span className="slack-bar" aria-label={`${row.segment.id} slack ${formatSeconds(row.slackSeconds)}`}>
              <span style={{ width: `${barPercent(row.slackSeconds, maxSlackSeconds)}%` }} />
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

function buildSegmentSlackRows(scenario: Scenario, discreteScenario: DiscreteScenario): SegmentSlackRow[] {
  const moveArcCountsBySegmentId = new Map<string, number>();
  for (const arc of discreteScenario.arcs) {
    if (arc.kind !== "move" || !arc.source_segment_id) continue;
    moveArcCountsBySegmentId.set(
      arc.source_segment_id,
      (moveArcCountsBySegmentId.get(arc.source_segment_id) ?? 0) + 1,
    );
  }

  return scenario.track_segments.map((segment) => {
    const durationSteps = moveArcCountsBySegmentId.get(segment.id) ?? 0;
    const physicalSeconds = travelSeconds(segment);
    const discreteSeconds = durationSteps * discreteScenario.delta_seconds;
    const slackSeconds = Math.max(0, discreteSeconds - physicalSeconds);
    return { segment, physicalSeconds, discreteSeconds, durationSteps, slackSeconds };
  });
}

function travelSeconds(segment: TrackSegment) {
  if (!segment.speed_profile) return 0;
  return segment.length_m / averageSpeed(segment.speed_profile);
}

function averageSpeed(profile: SpeedProfile) {
  if (profile.kind === "constant") {
    return profile.speed_m_per_s ?? 0;
  }
  return ((profile.start_speed_m_per_s ?? 0) + (profile.end_speed_m_per_s ?? 0)) / 2;
}

function formatSeconds(value: number) {
  if (value < 0.0005) return "0.000s";
  return `${value.toFixed(3)}s`;
}

function formatOptionalSeconds(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "n/a";
  return formatSeconds(value);
}

function barPercent(value: number, maxValue: number) {
  if (maxValue <= 0 || value <= 0) return 0;
  return Math.max(4, (value / maxValue) * 100);
}

function objectiveLabel(value: string) {
  return value.replaceAll("_", " ");
}

function formatPassengerHours(value: number | null | undefined) {
  if (value === null || value === undefined) return "n/a";
  return `${value.toFixed(1)} pax-h`;
}

function formatPassengerSecondsAsHours(value: number | null | undefined) {
  if (value === null || value === undefined) return "n/a";
  return formatPassengerHours(value / 3600.0);
}

function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "n/a";
  return `${(value * 100).toFixed(value < 0.01 ? 2 : 1)}%`;
}

function formatInteger(value: number) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}
