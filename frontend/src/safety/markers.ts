import type { ScenarioLayout } from "../scenarioLayout";
import type { ReplayCabinMarker, ReplayCollisionMarker } from "../components/networkTypes";
import { safetyViolationsAtTime, type ReplaySafetyReport } from "./types";
import type { ReplaySafetyViolationKind } from "./types";

export function replaySafetyMarkersAtTime(
  report: ReplaySafetyReport,
  markers: ReplayCabinMarker[],
  layout: ScenarioLayout,
  timeSeconds: number,
  visibleKinds?: ReadonlySet<ReplaySafetyViolationKind>,
): ReplayCollisionMarker[] {
  const markerByCabin = new Map(markers.map((marker) => [marker.cabinId, marker]));
  return safetyViolationsAtTime(report, timeSeconds)
    .filter((violation) => !visibleKinds || visibleKinds.has(violation.kind))
    .flatMap((violation) => {
    const cabinMarkers = violation.cabinIds
      .map((cabinId) => markerByCabin.get(cabinId))
      .filter((marker): marker is ReplayCabinMarker => Boolean(marker?.x !== undefined && marker?.y !== undefined));
    const nodePoint = violation.nodeId ? layout.nodes[violation.nodeId] : undefined;
    const x = nodePoint?.x ?? average(cabinMarkers.map((marker) => marker.x as number));
    const y = nodePoint?.y ?? average(cabinMarkers.map((marker) => marker.y as number));
    if (!Number.isFinite(x) || !Number.isFinite(y)) return [];
    return [{
      id: violation.id,
      x,
      y,
      cabinIds: [...violation.cabinIds],
      distanceM: violation.unit === "m" ? violation.actualSeparation : 0,
      violationKind: violation.kind,
      actualSeparation: violation.actualSeparation,
      requiredSeparation: violation.requiredSeparation,
      unit: violation.unit,
      message: violation.message,
    }];
    });
}

function average(values: number[]) {
  return values.length > 0
    ? values.reduce((sum, value) => sum + value, 0) / values.length
    : Number.NaN;
}
