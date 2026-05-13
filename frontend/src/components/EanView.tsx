import { AlertTriangle, Binary, Cable, Clock3, GitBranch, ListTree, Route, Timer, Waypoints } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type {
  EanBuildArtifact,
  EanHeadwayCheckpoint,
  EanMovementPlan,
  EanPassengerServiceResult,
  EanPhysicalEvent,
  EanPhysicalReplay,
  EanSkipStopTiming,
  EanVisitDecision,
  Scenario,
} from "../types";

interface EanViewProps {
  scenario: Scenario;
  eanInput: EanBuildArtifact | null;
  eanResult: EanMovementPlan | null;
  eanReplay: EanPhysicalReplay | null;
  eanPassengerService: EanPassengerServiceResult | null;
  eanInputWarning: string | null;
  eanResultWarning: string | null;
  eanReplayWarning: string | null;
  eanPassengerServiceWarning: string | null;
}

const MAX_EVENT_ROWS = 240;

export function EanView({
  scenario,
  eanInput,
  eanResult,
  eanReplay,
  eanPassengerService,
  eanInputWarning,
  eanResultWarning,
  eanReplayWarning,
  eanPassengerServiceWarning,
}: EanViewProps) {
  const [selectedEventKey, setSelectedEventKey] = useState<string | null>(null);
  const summary = useMemo(() => (eanInput ? buildEanSummary(eanInput, eanResult, eanReplay) : null), [eanInput, eanResult, eanReplay]);
  const visibleEvents = eanReplay?.events.slice(0, MAX_EVENT_ROWS) ?? [];
  const selectedEvent = useMemo(
    () => visibleEvents.find((event) => eventKey(event) === selectedEventKey) ?? visibleEvents[0] ?? null,
    [selectedEventKey, visibleEvents],
  );

  useEffect(() => {
    setSelectedEventKey(eanReplay?.events[0] ? eventKey(eanReplay.events[0]) : null);
  }, [eanReplay]);

  if (!eanInput) {
    return (
      <section className="ean-empty">
        <AlertTriangle size={18} />
        <strong>{eanInputWarning ?? "EAN artifacts unavailable in this artifact set"}</strong>
      </section>
    );
  }

  return (
    <section className="ean-view" aria-label="EAN artifact view">
      <header className="ean-view__header">
        <div>
          <h2>EAN Artifact</h2>
          <p>Switch visits, skip/stop timings, headway checkpoints, and projected physical replay events</p>
        </div>
        <div className="metrics-summary" aria-label="EAN artifact summary">
          <span>
            <Timer size={15} />
            {formatSeconds(eanInput.config.horizon_seconds)}
          </span>
          <span>
            <GitBranch size={15} />
            {eanInput.switch_cycle.length} switches
          </span>
          <span>
            <Cable size={15} />
            {summary?.cabinCount ?? 0} cabins
          </span>
          <span>
            <Waypoints size={15} />
            {eanReplay?.events.length ?? 0} events
          </span>
        </div>
      </header>

      <div className="ean-grid">
        <div className="ean-main">
          <section className="panel">
            <header className="panel__header">
              <Binary size={17} />
              <h2>Build Summary</h2>
            </header>
            <div className="metric-grid metric-grid--ean">
              <Metric label="horizon" value={formatSeconds(eanInput.config.horizon_seconds)} />
              <Metric label="tail" value={formatSeconds(eanInput.config.tail_seconds)} />
              <Metric label="model end" value={formatSeconds(eanInput.config.horizon_seconds + eanInput.config.tail_seconds)} />
              <Metric label="capacity" value={`${eanInput.config.cabin_capacity} pax`} />
              <Metric label="starts" value={eanInput.cabin_starts.length} />
              <Metric label="visits" value={eanInput.switch_visits.length} />
              <Metric label="checkpoints" value={eanInput.headway_checkpoints.length} />
              <Metric label="headway pairs" value={eanInput.headway_pairs.length} />
            </div>
            <div className="ean-note">
              v0 uses the horizon as physical model boundary: tail is {formatSeconds(eanInput.config.tail_seconds)}.
            </div>
          </section>

          <section className="panel">
            <header className="panel__header">
              <Route size={17} />
              <h2>Switch Cycle</h2>
              <span className="panel__count">{eanInput.switch_cycle.length}</span>
            </header>
            <div className="ean-cycle" aria-label="EAN switch cycle">
              {eanInput.switch_cycle.map((switchId, index) => (
                <div className="ean-cycle__item" key={switchId}>
                  <span>{index + 1}</span>
                  <strong>{switchId}</strong>
                </div>
              ))}
            </div>
          </section>

          <section className="panel">
            <header className="panel__header">
              <Clock3 size={17} />
              <h2>Skip/Stop Timings</h2>
              <span className="panel__count">{eanInput.timings.length}</span>
            </header>
            <div className="ean-table-wrap">
              <table className="ean-table">
                <thead>
                  <tr>
                    <th>Switch</th>
                    <th>Station</th>
                    <th>Skip</th>
                    <th>Entry</th>
                    <th>Platform</th>
                    <th>Exit</th>
                    <th>Skip path</th>
                    <th>Rope</th>
                  </tr>
                </thead>
                <tbody>
                  {eanInput.timings.map((timing) => (
                    <TimingRow key={timing.switch_id} timing={timing} />
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel">
            <header className="panel__header">
              <ListTree size={17} />
              <h2>Headway Checkpoints</h2>
              <span className="panel__count">{eanInput.headway_checkpoints.length}</span>
            </header>
            <div className="ean-table-wrap">
              <table className="ean-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Kind</th>
                    <th>Switch</th>
                    <th>Headway</th>
                    <th>Serve</th>
                    <th>Skip</th>
                    <th>Modes</th>
                  </tr>
                </thead>
                <tbody>
                  {eanInput.headway_checkpoints.map((checkpoint) => (
                    <CheckpointRow key={checkpoint.id} checkpoint={checkpoint} />
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>

        <aside className="side-panel ean-side">
          <section className="panel">
            <header className="panel__header">
              <Waypoints size={17} />
              <h2>Replay Events</h2>
              <span className="panel__count">{eanReplay?.events.length ?? 0}</span>
            </header>
            {eanReplay ? (
              <>
                <div className="kv-list ean-event-summary">
                  <div className="kv-row">
                    <span>range</span>
                    <strong>{formatSeconds(summary?.minEventSeconds ?? 0)} - {formatSeconds(summary?.maxEventSeconds ?? 0)}</strong>
                  </div>
                  <div className="kv-row">
                    <span>after horizon</span>
                    <strong>{summary?.eventsAfterHorizon ?? 0}</strong>
                  </div>
                </div>
                <EventList events={visibleEvents} selectedEvent={selectedEvent} onSelect={setSelectedEventKey} />
                {eanReplay.events.length > visibleEvents.length ? (
                  <div className="ean-note">Showing first {visibleEvents.length} of {eanReplay.events.length} events.</div>
                ) : null}
              </>
            ) : (
              <div className="empty-panel">{eanReplayWarning ?? "EAN replay unavailable"}</div>
            )}
          </section>

          <section className="panel">
            <header className="panel__header">
              <Cable size={17} />
              <h2>Selected Event</h2>
            </header>
            {selectedEvent ? (
              <div className="kv-list">
                <h3>{selectedEvent.event_kind}</h3>
                <EventDetails event={selectedEvent} />
              </div>
            ) : (
              <div className="empty-panel">No event selected</div>
            )}
          </section>

          <section className="panel">
            <header className="panel__header">
              <GitBranch size={17} />
              <h2>Plan Status</h2>
            </header>
            {eanResult ? (
              <div className="metric-grid">
                <Metric label="trajectories" value={eanResult.trajectories.length} />
                <Metric label="decisions" value={formatDecisionCounts(summary?.decisionCounts ?? [])} />
                <Metric label="plan end" value={formatSeconds(eanResult.model_end_seconds)} />
                <Metric label="scenario" value={scenario.scenario_id} />
              </div>
            ) : (
              <div className="empty-panel">{eanResultWarning ?? "EAN result unavailable"}</div>
            )}
          </section>

          <section className="panel">
            <header className="panel__header">
              <Timer size={17} />
              <h2>Objective Result</h2>
            </header>
            {eanPassengerService ? (
              <div className="metric-grid">
                <Metric label="objective" value={objectiveLabel(eanPassengerService.metadata.objective_kind)} />
                <Metric label="value" value={formatPassengerHours(eanPassengerService.metadata.objective_passenger_hours)} />
                <Metric label="status" value={eanPassengerService.metadata.solver_status ?? eanPassengerService.metadata.status} />
                <Metric label="gap" value={formatPercent(eanPassengerService.metadata.mip_gap)} />
                <Metric label="best bound" value={formatPassengerSecondsAsHours(eanPassengerService.metadata.best_bound)} />
                <Metric label="runtime" value={formatOptionalSeconds(eanPassengerService.metadata.runtime_seconds)} />
                <Metric label="nodes" value={formatOptionalInteger(eanPassengerService.metadata.node_count)} />
                <Metric label="solutions" value={formatOptionalInteger(eanPassengerService.metadata.solution_count)} />
                <Metric label="gap target" value={formatPercent(eanPassengerService.metadata.mip_gap_target)} />
                <Metric label="time limit" value={formatOptionalSeconds(eanPassengerService.metadata.time_limit_seconds)} />
                <Metric label="served" value={eanPassengerService.metadata.served_passenger_count} />
                <Metric label="unserved" value={eanPassengerService.metadata.unserved_passenger_count} />
                <Metric label="visible skips" value={eanPassengerService.metadata.visible_skipped_visit_count} />
              </div>
            ) : (
              <div className="empty-panel">{eanPassengerServiceWarning ?? "MILP result unavailable"}</div>
            )}
          </section>
        </aside>
      </div>
    </section>
  );
}

function TimingRow({ timing }: { timing: EanSkipStopTiming }) {
  return (
    <tr>
      <td>{timing.switch_id}</td>
      <td>{timing.station_id}</td>
      <td>{timing.skip_allowed ? "yes" : "no"}</td>
      <td>{formatSeconds(timing.entry_to_platform_entry_seconds)}</td>
      <td>{formatSeconds(timing.min_platform_entry_to_platform_exit_seconds)}</td>
      <td>{formatSeconds(timing.platform_exit_to_exit_switch_seconds)}</td>
      <td>{formatSeconds(timing.skip_entry_to_exit_switch_seconds)}</td>
      <td>{formatSeconds(timing.rope_to_next_switch_seconds)}</td>
    </tr>
  );
}

function CheckpointRow({ checkpoint }: { checkpoint: EanHeadwayCheckpoint }) {
  return (
    <tr>
      <td>{checkpoint.id}</td>
      <td>{checkpoint.kind}</td>
      <td>{checkpoint.switch_id}</td>
      <td>{formatSeconds(checkpoint.headway_seconds)}</td>
      <td>{checkpoint.applies_to_serve ? "yes" : "no"}</td>
      <td>{checkpoint.applies_to_skip ? "yes" : "no"}</td>
      <td>{checkpoint.waiting_modes.join(", ")}</td>
    </tr>
  );
}

function EventList({
  events,
  selectedEvent,
  onSelect,
}: {
  events: EanPhysicalEvent[];
  selectedEvent: EanPhysicalEvent | null;
  onSelect: (key: string) => void;
}) {
  if (events.length === 0) return <div className="empty-panel">No EAN events</div>;
  const selectedKey = selectedEvent ? eventKey(selectedEvent) : null;
  return (
    <div className="ean-event-list" aria-label="EAN replay events">
      {events.map((event) => {
        const key = eventKey(event);
        return (
          <button
            className={key === selectedKey ? "ean-event is-active" : "ean-event"}
            key={key}
            onClick={() => onSelect(key)}
          >
            <span>{formatSeconds(event.time_seconds)}</span>
            <strong>C{event.cabin_id}</strong>
            <em>{event.event_kind}</em>
            <small>{event.physical_node_id}</small>
          </button>
        );
      })}
    </div>
  );
}

function EventDetails({ event }: { event: EanPhysicalEvent }) {
  return (
    <>
      <div className="kv-row">
        <span>time</span>
        <strong>{formatSeconds(event.time_seconds)}</strong>
      </div>
      <div className="kv-row">
        <span>cabin</span>
        <strong>C{event.cabin_id}</strong>
      </div>
      <div className="kv-row">
        <span>visit</span>
        <strong>{event.visit_index}</strong>
      </div>
      <div className="kv-row">
        <span>station</span>
        <strong>{event.station_id}</strong>
      </div>
      <div className="kv-row">
        <span>switch</span>
        <strong>{event.switch_id}</strong>
      </div>
      <div className="kv-row">
        <span>node</span>
        <strong>{event.physical_node_id}</strong>
      </div>
      <div className="kv-row">
        <span>segments</span>
        <strong>{event.source_segment_ids.length > 0 ? event.source_segment_ids.join(", ") : "none"}</strong>
      </div>
    </>
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

function buildEanSummary(input: EanBuildArtifact, result: EanMovementPlan | null, replay: EanPhysicalReplay | null) {
  const cabinCount = new Set(input.cabin_starts.map((start) => start.cabin_id)).size;
  const decisionCounts = result
    ? countBy(result.trajectories.flatMap((trajectory) => trajectory.visits.map((visit) => visit.decision)))
    : [];
  const eventTimes = replay?.events.map((event) => event.time_seconds) ?? [];
  return {
    cabinCount,
    decisionCounts,
    minEventSeconds: eventTimes.length > 0 ? Math.min(...eventTimes) : 0,
    maxEventSeconds: eventTimes.length > 0 ? Math.max(...eventTimes) : 0,
    eventsAfterHorizon: replay?.events.filter((event) => event.time_seconds > replay.horizon_seconds).length ?? 0,
  };
}

function countBy(values: EanVisitDecision[]) {
  const counts = new Map<EanVisitDecision, number>();
  for (const value of values) {
    counts.set(value, (counts.get(value) ?? 0) + 1);
  }
  return [...counts.entries()].map(([decision, count]) => ({ decision, count }));
}

function formatDecisionCounts(counts: { decision: EanVisitDecision; count: number }[]) {
  if (counts.length === 0) return "n/a";
  return counts.map((entry) => `${entry.decision}: ${entry.count}`).join(", ");
}

function eventKey(event: EanPhysicalEvent) {
  return `${event.cabin_id}:${event.visit_index}:${event.event_kind}:${event.time_seconds}`;
}

function formatSeconds(seconds: number) {
  if (!Number.isFinite(seconds)) return "n/a";
  if (Math.abs(seconds) >= 100) return `${seconds.toFixed(0)}s`;
  return `${seconds.toFixed(1)}s`;
}

function formatInteger(value: number) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}

function formatOptionalInteger(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "n/a";
  return formatInteger(value);
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

function formatOptionalSeconds(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "n/a";
  return formatSeconds(value);
}
