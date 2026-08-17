import type {
  DerivedHeadwayPolicy,
  DerivedSpatialRole,
  EanMovementPlan,
  EanPhysicalEvent,
  EanPhysicalReplay,
  EanVisitPlan,
  Scenario,
  SpeedProfile,
  TrackSegment,
} from "../types";
import {
  MAX_STORED_SAFETY_VIOLATIONS,
  SAFETY_MARKER_WINDOW_SECONDS,
  SAFETY_TOLERANCE_M,
  SAFETY_TOLERANCE_SECONDS,
  type ReplaySafetyViolation,
} from "./types";

export interface ContinuousSpacingCheckResult {
  violations: ReplaySafetyViolation[];
  totalViolationCount: number;
  minimumSlackM: number | null;
  motionIntervalCount: number;
  pairCount: number;
  diagnostics: string[];
}

interface Polynomial {
  quadratic: number;
  linear: number;
  constant: number;
}

interface BaseMotionInterval {
  id: string;
  cabinId: number;
  visitIndex: number;
  startTime: number;
  endTime: number;
  role: DerivedSpatialRole;
}

interface SegmentMotionInterval extends BaseMotionInterval {
  kind: "segment";
  segmentId: string;
  fromNodeId: string;
  toNodeId: string;
  lengthM: number;
  position: Polynomial;
}

interface NodeMotionInterval extends BaseMotionInterval {
  kind: "node";
  nodeId: string;
}

type MotionInterval = SegmentMotionInterval | NodeMotionInterval;

interface MinimumDistance {
  distanceM: number;
  timeSeconds: number;
  nodeId: string | null;
  segmentId: string | null;
}

export function checkContinuousSpacing({
  scenario,
  policy,
  movementPlan,
  replay,
}: {
  scenario: Scenario;
  policy: DerivedHeadwayPolicy;
  movementPlan: EanMovementPlan;
  replay: EanPhysicalReplay;
}): ContinuousSpacingCheckResult {
  const built = buildMotionIntervals(scenario, movementPlan, replay);
  const spacingByRole = new Map<DerivedSpatialRole, number>();
  for (const spacing of policy.spatial_spacings) {
    if (spacingByRole.has(spacing.role)) built.diagnostics.push(`Duplicate ${spacing.role} spatial spacing`);
    spacingByRole.set(spacing.role, spacing.spacing_m);
  }
  for (const role of ["rope", "service"] satisfies DerivedSpatialRole[]) {
    const spacing = spacingByRole.get(role);
    if (!Number.isFinite(spacing) || (spacing ?? 0) <= 0) {
      built.diagnostics.push(`Missing positive ${role} spatial spacing`);
    }
  }

  const violations: ReplaySafetyViolation[] = [];
  let totalViolationCount = 0;
  let pairCount = 0;
  let minimumSlackM: number | null = null;
  const checkedPairIds = new Set<string>();

  const segmentGroups = new Map<string, SegmentMotionInterval[]>();
  const nodeGroups = new Map<string, NodeMotionInterval[]>();
  const incidentSegments = new Map<string, Map<string, SegmentMotionInterval[]>>();
  for (const interval of built.intervals) {
    if (interval.kind === "node") {
      pushGrouped(nodeGroups, interval.nodeId, interval);
      continue;
    }
    const edgeKey = undirectedEdgeKey(interval.fromNodeId, interval.toNodeId);
    pushGrouped(segmentGroups, edgeKey, interval);
    pushNestedGrouped(incidentSegments, interval.fromNodeId, edgeKey, interval);
    pushNestedGrouped(incidentSegments, interval.toNodeId, edgeKey, interval);
  }

  const examine = (
    first: MotionInterval,
    second: MotionInterval,
    sharedNodeId: string | null,
  ) => {
    if (first.cabinId === second.cabinId) return;
    const pairId = first.id < second.id ? `${first.id}|${second.id}` : `${second.id}|${first.id}`;
    if (checkedPairIds.has(pairId)) return;
    checkedPairIds.add(pairId);
    const overlapStart = Math.max(0, first.startTime, second.startTime);
    const overlapEnd = Math.min(
      movementPlan.model_end_seconds,
      first.endTime,
      second.endTime,
    );
    if (overlapEnd <= overlapStart + SAFETY_TOLERANCE_SECONDS) return;
    pairCount += 1;
    const minimum = minimumDistance(first, second, overlapStart, overlapEnd, sharedNodeId);
    if (!minimum) return;
    const firstSpacing = spacingByRole.get(first.role);
    const secondSpacing = spacingByRole.get(second.role);
    if (firstSpacing === undefined || secondSpacing === undefined) return;
    const required = Math.max(firstSpacing, secondSpacing);
    const slack = minimum.distanceM - required;
    minimumSlackM = minimumSlackM === null ? slack : Math.min(minimumSlackM, slack);
    if (slack >= -SAFETY_TOLERANCE_M) return;

    totalViolationCount += 1;
    if (violations.length >= MAX_STORED_SAFETY_VIOLATIONS) return;
    violations.push({
      id: `geometry:${pairId}`,
      kind: "geometric_spacing",
      cabinIds: [first.cabinId, second.cabinId],
      visitIndices: [first.visitIndex, second.visitIndex],
      timeSeconds: minimum.timeSeconds,
      activeFromSeconds: Math.max(0, minimum.timeSeconds - SAFETY_MARKER_WINDOW_SECONDS),
      activeUntilSeconds: Math.min(
        movementPlan.model_end_seconds,
        minimum.timeSeconds + SAFETY_MARKER_WINDOW_SECONDS,
      ),
      resourceId: null,
      ruleId: null,
      nodeId: minimum.nodeId,
      segmentId: minimum.segmentId,
      leaderBehavior: null,
      actualSeparation: minimum.distanceM,
      requiredSeparation: required,
      unit: "m",
      message: `${minimum.distanceM.toFixed(3)} m available, ${required.toFixed(3)} m required`,
    });
  };

  for (const group of segmentGroups.values()) examineCombinations(group, (first, second) => examine(first, second, null));
  for (const group of nodeGroups.values()) examineCombinations(group, (first, second) => examine(first, second, first.nodeId));

  for (const [nodeId, byEdge] of incidentSegments) {
    const nodeIntervals = nodeGroups.get(nodeId) ?? [];
    for (const segmentIntervals of byEdge.values()) {
      for (const nodeInterval of nodeIntervals) {
        for (const segmentInterval of segmentIntervals) examine(nodeInterval, segmentInterval, nodeId);
      }
    }
    const edgeGroups = [...byEdge.values()];
    for (let left = 0; left < edgeGroups.length; left += 1) {
      for (let right = left + 1; right < edgeGroups.length; right += 1) {
        for (const first of edgeGroups[left]) {
          for (const second of edgeGroups[right]) examine(first, second, nodeId);
        }
      }
    }
  }

  return {
    violations,
    totalViolationCount,
    minimumSlackM,
    motionIntervalCount: built.intervals.length,
    pairCount,
    diagnostics: unique(built.diagnostics),
  };
}

export function buildMotionIntervals(
  scenario: Scenario,
  movementPlan: EanMovementPlan,
  replay: EanPhysicalReplay,
): { intervals: MotionInterval[]; diagnostics: string[] } {
  const diagnostics: string[] = [];
  const intervals: MotionInterval[] = [];
  const segmentById = new Map(scenario.track_segments.map((segment) => [segment.id, segment]));
  const visitByKey = new Map<string, EanVisitPlan>();
  for (const trajectory of movementPlan.trajectories) {
    for (const visit of trajectory.visits) visitByKey.set(visitKey(visit.cabin_id, visit.visit_index), visit);
  }
  const eventsByCabin = new Map<number, EanPhysicalEvent[]>();
  for (const event of replay.events) {
    const events = eventsByCabin.get(event.cabin_id) ?? [];
    events.push(event);
    eventsByCabin.set(event.cabin_id, events);
  }

  for (const trajectory of movementPlan.trajectories) {
    const events = eventsByCabin.get(trajectory.cabin_id) ?? [];
    events.sort((left, right) => left.time_seconds - right.time_seconds || eventOrder(left) - eventOrder(right));
    if (events.length === 0) {
      diagnostics.push(`Replay has no events for cabin ${trajectory.cabin_id}`);
      continue;
    }
    if (events[0].time_seconds > SAFETY_TOLERANCE_SECONDS) {
      diagnostics.push(`Replay lacks t=0 interpolation context for cabin ${trajectory.cabin_id}`);
    }
    const lastVisit = trajectory.visits.at(-1);
    if (lastVisit && lastVisit.next_switch_time_seconds < movementPlan.model_end_seconds - SAFETY_TOLERANCE_SECONDS) {
      diagnostics.push(`Movement plan ends before H for cabin ${trajectory.cabin_id}`);
    }
    for (let index = 0; index + 1 < events.length; index += 1) {
      const previous = events[index];
      const next = events[index + 1];
      if (next.time_seconds <= previous.time_seconds + SAFETY_TOLERANCE_SECONDS) continue;
      const startTime = previous.time_seconds;
      const endTime = next.time_seconds;
      if (endTime <= 0 || startTime >= movementPlan.model_end_seconds) continue;
      const visit = visitByKey.get(visitKey(next.cabin_id, next.visit_index));
      const role = roleForEventPath(next, visit);
      if (next.source_segment_ids.length === 0 || next.physical_node_id === previous.physical_node_id) {
        intervals.push({
          id: `node:${trajectory.cabin_id}:${index}:${previous.physical_node_id}`,
          kind: "node",
          cabinId: trajectory.cabin_id,
          visitIndex: next.visit_index,
          startTime,
          endTime,
          role,
          nodeId: previous.physical_node_id,
        });
        continue;
      }
      appendPathIntervals({
        cabinId: trajectory.cabin_id,
        visitIndex: next.visit_index,
        intervalIndex: index,
        startNodeId: previous.physical_node_id,
        endNodeId: next.physical_node_id,
        segmentIds: next.source_segment_ids,
        startTime,
        endTime,
        role,
        segmentById,
        intervals,
        diagnostics,
      });
    }
  }
  return { intervals, diagnostics };
}

function appendPathIntervals({
  cabinId,
  visitIndex,
  intervalIndex,
  startNodeId,
  endNodeId,
  segmentIds,
  startTime,
  endTime,
  role,
  segmentById,
  intervals,
  diagnostics,
}: {
  cabinId: number;
  visitIndex: number;
  intervalIndex: number;
  startNodeId: string;
  endNodeId: string;
  segmentIds: string[];
  startTime: number;
  endTime: number;
  role: DerivedSpatialRole;
  segmentById: Map<string, TrackSegment>;
  intervals: MotionInterval[];
  diagnostics: string[];
}) {
  const path: { segment: TrackSegment; forward: boolean; duration: number }[] = [];
  let currentNodeId = startNodeId;
  for (const segmentId of segmentIds) {
    const segment = segmentById.get(segmentId);
    if (!segment) {
      diagnostics.push(`Replay path references missing segment ${segmentId}`);
      return;
    }
    const forward = segment.from_node_id === currentNodeId;
    if (!forward && segment.to_node_id !== currentNodeId) {
      diagnostics.push(`Replay path ${segmentIds.join(",")} is disconnected at ${currentNodeId}`);
      return;
    }
    const duration = travelSecondsForSegment(segment);
    if (!Number.isFinite(duration) || duration <= 0) {
      diagnostics.push(`Segment ${segment.id} has no usable speed profile`);
      return;
    }
    path.push({ segment, forward, duration });
    currentNodeId = forward ? segment.to_node_id : segment.from_node_id;
  }
  if (currentNodeId !== endNodeId) {
    diagnostics.push(`Replay path ends at ${currentNodeId}, expected ${endNodeId}`);
    return;
  }
  const theoreticalDuration = path.reduce((sum, item) => sum + item.duration, 0);
  const scale = (endTime - startTime) / theoreticalDuration;
  if (!Number.isFinite(scale) || scale <= 0) {
    diagnostics.push(`Replay path for cabin ${cabinId} has an invalid time scale`);
    return;
  }
  let cursor = startTime;
  for (let pathIndex = 0; pathIndex < path.length; pathIndex += 1) {
    const item = path[pathIndex];
    const duration = item.duration * scale;
    const profile = item.segment.speed_profile;
    if (!profile) continue;
    const forwardPolynomial = distancePolynomial(item.segment, profile, item.duration, scale);
    const position = item.forward
      ? forwardPolynomial
      : {
          quadratic: -forwardPolynomial.quadratic,
          linear: -forwardPolynomial.linear,
          constant: item.segment.length_m,
        };
    intervals.push({
      id: `segment:${cabinId}:${intervalIndex}:${pathIndex}:${item.segment.id}`,
      kind: "segment",
      cabinId,
      visitIndex,
      startTime: cursor,
      endTime: cursor + duration,
      role: roleForSegment(item.segment, role),
      segmentId: item.segment.id,
      fromNodeId: item.segment.from_node_id,
      toNodeId: item.segment.to_node_id,
      lengthM: item.segment.length_m,
      position,
    });
    cursor += duration;
  }
}

function minimumDistance(
  first: MotionInterval,
  second: MotionInterval,
  start: number,
  end: number,
  sharedNodeId: string | null,
): MinimumDistance | null {
  if (first.kind === "node" && second.kind === "node") {
    if (first.nodeId !== second.nodeId) return null;
    return { distanceM: 0, timeSeconds: start, nodeId: first.nodeId, segmentId: null };
  }
  if (first.kind === "node" && second.kind === "segment") {
    if (first.nodeId !== sharedNodeId) return null;
    const polynomial = distanceToNodePolynomial(second, first.nodeId);
    const minimum = minimumPolynomial(polynomial, start, end, second.startTime, false);
    return { ...minimum, nodeId: first.nodeId, segmentId: second.segmentId };
  }
  if (first.kind === "segment" && second.kind === "node") {
    return minimumDistance(second, first, start, end, sharedNodeId);
  }
  if (first.kind === "segment" && second.kind === "segment") {
    if (undirectedEdgeKey(first.fromNodeId, first.toNodeId) === undirectedEdgeKey(second.fromNodeId, second.toNodeId)) {
      const firstPosition = canonicalPositionPolynomial(first);
      const secondPosition = canonicalPositionPolynomial(second);
      const difference = subtractAbsolutePolynomials(firstPosition, first.startTime, secondPosition, second.startTime);
      const minimum = minimumAbsolutePolynomial(difference, start, end);
      return { ...minimum, nodeId: null, segmentId: first.segmentId };
    }
    if (!sharedNodeId) return null;
    const firstDistance = distanceToNodePolynomial(first, sharedNodeId);
    const secondDistance = distanceToNodePolynomial(second, sharedNodeId);
    const sum = addAbsolutePolynomials(firstDistance, first.startTime, secondDistance, second.startTime);
    const minimum = minimumPolynomial(sum, start, end, 0, true);
    return { ...minimum, nodeId: sharedNodeId, segmentId: first.segmentId };
  }
  return null;
}

function canonicalPositionPolynomial(interval: SegmentMotionInterval): Polynomial {
  if (interval.fromNodeId <= interval.toNodeId) return interval.position;
  return {
    quadratic: -interval.position.quadratic,
    linear: -interval.position.linear,
    constant: interval.lengthM - interval.position.constant,
  };
}

function distanceToNodePolynomial(interval: SegmentMotionInterval, nodeId: string): Polynomial {
  if (nodeId === interval.fromNodeId) return interval.position;
  if (nodeId === interval.toNodeId) {
    return {
      quadratic: -interval.position.quadratic,
      linear: -interval.position.linear,
      constant: interval.lengthM - interval.position.constant,
    };
  }
  throw new Error(`Node ${nodeId} is not incident to segment ${interval.segmentId}`);
}

function minimumAbsolutePolynomial(polynomial: Polynomial, start: number, end: number): { distanceM: number; timeSeconds: number } {
  const candidates = polynomialCandidateTimes(polynomial, start, end, true);
  let bestTime = start;
  let bestValue = Number.POSITIVE_INFINITY;
  for (const time of candidates) {
    const value = Math.abs(evaluatePolynomial(polynomial, time));
    if (value < bestValue) {
      bestValue = value;
      bestTime = time;
    }
  }
  return { distanceM: bestValue, timeSeconds: bestTime };
}

function minimumPolynomial(
  polynomial: Polynomial,
  start: number,
  end: number,
  localStart: number,
  alreadyAbsolute: boolean,
): { distanceM: number; timeSeconds: number } {
  const absolute = alreadyAbsolute ? polynomial : toAbsolutePolynomial(polynomial, localStart);
  const candidates = polynomialCandidateTimes(absolute, start, end, false);
  let bestTime = start;
  let bestValue = Number.POSITIVE_INFINITY;
  for (const time of candidates) {
    const value = Math.max(0, evaluatePolynomial(absolute, time));
    if (value < bestValue) {
      bestValue = value;
      bestTime = time;
    }
  }
  return { distanceM: bestValue, timeSeconds: bestTime };
}

function polynomialCandidateTimes(polynomial: Polynomial, start: number, end: number, includeRoots: boolean): number[] {
  const candidates = [start, end];
  if (Math.abs(polynomial.quadratic) > 1e-12) {
    addIfInRange(candidates, -polynomial.linear / (2 * polynomial.quadratic), start, end);
    if (includeRoots) {
      const discriminant = polynomial.linear ** 2 - 4 * polynomial.quadratic * polynomial.constant;
      if (discriminant >= 0) {
        const root = Math.sqrt(discriminant);
        addIfInRange(candidates, (-polynomial.linear - root) / (2 * polynomial.quadratic), start, end);
        addIfInRange(candidates, (-polynomial.linear + root) / (2 * polynomial.quadratic), start, end);
      }
    }
  } else if (includeRoots && Math.abs(polynomial.linear) > 1e-12) {
    addIfInRange(candidates, -polynomial.constant / polynomial.linear, start, end);
  }
  return candidates;
}

function distancePolynomial(
  segment: TrackSegment,
  profile: SpeedProfile,
  theoreticalDuration: number,
  scale: number,
): Polynomial {
  if (profile.kind === "constant") {
    return {
      quadratic: 0,
      linear: segment.length_m / (theoreticalDuration * scale),
      constant: 0,
    };
  }
  const startSpeed = profile.start_speed_m_per_s ?? 0;
  const endSpeed = profile.end_speed_m_per_s ?? 0;
  const acceleration = (endSpeed - startSpeed) / theoreticalDuration;
  return {
    quadratic: 0.5 * acceleration / (scale ** 2),
    linear: startSpeed / scale,
    constant: 0,
  };
}

function travelSecondsForSegment(segment: TrackSegment): number {
  const profile = segment.speed_profile;
  if (!profile || segment.length_m <= 0) return Number.NaN;
  if (profile.kind === "constant") {
    const speed = profile.speed_m_per_s ?? 0;
    return speed > 0 ? segment.length_m / speed : Number.NaN;
  }
  const average = ((profile.start_speed_m_per_s ?? 0) + (profile.end_speed_m_per_s ?? 0)) / 2;
  return average > 0 ? segment.length_m / average : Number.NaN;
}

function roleForEventPath(event: EanPhysicalEvent, visit: EanVisitPlan | undefined): DerivedSpatialRole {
  if (event.event_kind === "reach_next_switch") return "rope";
  if (visit?.decision === "skip") return "rope";
  return "service";
}

function roleForSegment(segment: TrackSegment, fallback: DerivedSpatialRole): DerivedSpatialRole {
  if (segment.kind === "rope" || segment.kind === "skip") return "rope";
  if (segment.kind === "station") return "service";
  return fallback;
}

function subtractAbsolutePolynomials(
  first: Polynomial,
  firstStart: number,
  second: Polynomial,
  secondStart: number,
): Polynomial {
  const left = toAbsolutePolynomial(first, firstStart);
  const right = toAbsolutePolynomial(second, secondStart);
  return {
    quadratic: left.quadratic - right.quadratic,
    linear: left.linear - right.linear,
    constant: left.constant - right.constant,
  };
}

function addAbsolutePolynomials(
  first: Polynomial,
  firstStart: number,
  second: Polynomial,
  secondStart: number,
): Polynomial {
  const left = toAbsolutePolynomial(first, firstStart);
  const right = toAbsolutePolynomial(second, secondStart);
  return {
    quadratic: left.quadratic + right.quadratic,
    linear: left.linear + right.linear,
    constant: left.constant + right.constant,
  };
}

function toAbsolutePolynomial(polynomial: Polynomial, start: number): Polynomial {
  return {
    quadratic: polynomial.quadratic,
    linear: polynomial.linear - 2 * polynomial.quadratic * start,
    constant: polynomial.quadratic * start ** 2 - polynomial.linear * start + polynomial.constant,
  };
}

function evaluatePolynomial(polynomial: Polynomial, time: number): number {
  return polynomial.quadratic * time ** 2 + polynomial.linear * time + polynomial.constant;
}

function addIfInRange(values: number[], value: number, start: number, end: number) {
  if (Number.isFinite(value) && value >= start && value <= end) values.push(value);
}

function examineCombinations<T>(values: T[], callback: (first: T, second: T) => void) {
  for (let first = 0; first < values.length; first += 1) {
    for (let second = first + 1; second < values.length; second += 1) callback(values[first], values[second]);
  }
}

function pushGrouped<T>(map: Map<string, T[]>, key: string, value: T) {
  const values = map.get(key) ?? [];
  values.push(value);
  map.set(key, values);
}

function pushNestedGrouped<T>(map: Map<string, Map<string, T[]>>, outer: string, inner: string, value: T) {
  const nested = map.get(outer) ?? new Map<string, T[]>();
  pushGrouped(nested, inner, value);
  map.set(outer, nested);
}

function undirectedEdgeKey(first: string, second: string) {
  return first <= second ? `${first}|${second}` : `${second}|${first}`;
}

function visitKey(cabinId: number, visitIndex: number) {
  return `${cabinId}:${visitIndex}`;
}

function eventOrder(event: EanPhysicalEvent) {
  return ["reach_next_switch", "enter_switch", "enter_platform", "enter_wait", "exit_wait", "exit_platform", "exit_switch"].indexOf(event.event_kind);
}

function unique(values: string[]) {
  return [...new Set(values)];
}
