import { SlidersHorizontal } from "lucide-react";
import type { Scenario } from "../types";

interface ParametersPanelProps {
  scenario: Scenario;
}

export function ParametersPanel({ scenario }: ParametersPanelProps) {
  const physical = scenario.headway_design?.physical;
  const spacing = scenario.operating.cabin_length_m + (physical?.service_clearance_m ?? scenario.operating.min_clearance_m);
  const geometric = !!scenario.headway_design?.station_mechanisms.length
    && scenario.headway_design.station_mechanisms.every(({ design }) => Object.keys(design).length === 0);
  const ropeHeadway = physical ? (
    scenario.operating.cabin_length_m
    + 2 * (physical.cabin_height_m + physical.attachment_to_cabin_roof_m) * Math.sin(physical.rope_sway_angle_rad)
    + physical.rope_clearance_m
  ) / scenario.operating.rope_speed_m_per_s : null;
  const spacingLabel = scenario.headway_design ? "station pitch" : "spacing";
  const segments = new Map(scenario.track_segments.map((segment) => [segment.id, segment]));
  const ropeSegments = scenario.track_segments.filter((segment) => segment.kind === "rope");
  const ropeLengths = ropeSegments.map((segment) => segment.length_m);
  const serviceRoutes = scenario.station_routes.filter((route) => route.kind === "service");
  const skipRoutes = scenario.station_routes.filter((route) => route.kind === "skip");
  const serviceDuration = serviceRoutes.length > 0 ? routeDuration(serviceRoutes[0].segment_ids, segments) : null;
  const skipDuration = skipRoutes.length > 0 ? routeDuration(skipRoutes[0].segment_ids, segments) : null;
  const allStopCycle = serviceRoutes.reduce(
    (sum, route) => sum + routeDuration(route.segment_ids, segments),
    ropeSegments.reduce((sum, segment) => sum + segmentDuration(segment), 0),
  );
  const mechanismCycles = scenario.headway_design?.station_mechanisms.flatMap(({ design }) => (
    "mechanical_service_cycle_seconds" in design ? [design.mechanical_service_cycle_seconds]
      : "manufacturer_vehicle_interval_seconds" in design ? [design.manufacturer_vehicle_interval_seconds]
        : "guaranteed_vehicle_interval_seconds" in design ? [design.guaranteed_vehicle_interval_seconds]
          : []
  )) ?? [];
  const totalDemand = scenario.demands.reduce((sum, demand) => sum + demand.count, 0);
  const releases = [...new Set(scenario.demands.map((demand) => demand.arrival_time))];
  const experiment = scenario.experiment_metadata;
  const loadedDemand = typeof experiment?.demand_total === "number"
    ? `${experiment.demand_total} pax · ${String(experiment.demand_family).toUpperCase()}/${String(experiment.demand_profile).toUpperCase()}`
    : `${totalDemand} pax · ${releases.length} releases`;
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
        <Metric label="free rope sections" value={formatLengths(ropeLengths)} />
        <Metric label="station path" value={serviceRoutes.length > 0 ? `${routeLength(serviceRoutes[0].segment_ids, segments).toFixed(2)} m` : "n/a"} />
        <Metric label="bypass path" value={skipRoutes.length > 0 ? `${routeLength(skipRoutes[0].segment_ids, segments).toFixed(2)} m` : "n/a"} />
        <Metric label="STOP time" value={serviceDuration === null ? "n/a" : `${serviceDuration.toFixed(3)} s`} />
        <Metric label="SKIP time" value={skipDuration === null ? "n/a" : `${skipDuration.toFixed(3)} s`} />
        {mechanismCycles.length > 0 ? <Metric label="station mechanism" value={`${Math.max(...mechanismCycles).toFixed(3)} s`} /> : null}
        {geometric && ropeHeadway !== null ? <Metric label="geometric entry / exit headway" value={`${ropeHeadway.toFixed(3)} s`} /> : null}
        {geometric ? <Metric label="platform headway" value={`${(spacing / scenario.operating.station_speed_m_per_s).toFixed(3)} s`} /> : null}
        <Metric label="All-Stop cycle" value={`${allStopCycle.toFixed(3)} s`} />
        <Metric label="operating window" value={`${scenario.service_start_time}–${scenario.service_end_time}`} />
        <Metric label="loaded demand" value={loadedDemand} />
        {experiment?.topology ? <Metric label="topology / geometry" value={`${String(experiment.topology).toUpperCase()} / ${String(experiment.geometry).toUpperCase()}`} /> : null}
        {typeof experiment?.all_stop_reference_cabins === "number" ? <Metric label="All-Stop fleet" value={`${experiment.all_stop_reference_cabins} cabins`} /> : null}
        {typeof experiment?.port_dispatch_upper_bound_cabins === "number" ? <Metric label="port dispatch upper bound" value={`${experiment.port_dispatch_upper_bound_cabins} cabins`} /> : null}
      </div>
    </section>
  );
}

function segmentDuration(segment: Scenario["track_segments"][number]): number {
  const profile = segment.speed_profile;
  if (!profile) return 0;
  if (profile.kind === "constant" && profile.speed_m_per_s !== null) {
    return segment.length_m / profile.speed_m_per_s;
  }
  if (
    profile.kind === "linear"
    && profile.start_speed_m_per_s !== null
    && profile.end_speed_m_per_s !== null
  ) {
    return 2 * segment.length_m / (profile.start_speed_m_per_s + profile.end_speed_m_per_s);
  }
  return 0;
}

function routeLength(
  segmentIds: string[],
  segments: Map<string, Scenario["track_segments"][number]>,
): number {
  return segmentIds.reduce((sum, id) => sum + (segments.get(id)?.length_m ?? 0), 0);
}

function routeDuration(
  segmentIds: string[],
  segments: Map<string, Scenario["track_segments"][number]>,
): number {
  return segmentIds.reduce((sum, id) => {
    const segment = segments.get(id);
    return sum + (segment ? segmentDuration(segment) : 0);
  }, 0);
}

function formatLengths(values: number[]): string {
  if (values.length === 0) return "n/a";
  const unique = [...new Set(values)];
  return unique.length === 1
    ? `${unique[0].toFixed(0)} m × ${values.length}`
    : values.map((value) => value.toFixed(0)).join(" / ") + " m";
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
