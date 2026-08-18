import type { DiscreteArc, DiscreteConstraint, DiscreteNode } from "../types";

export interface ReplayCabinMarker {
  cabinId: number;
  nodeId: string;
  x?: number;
  y?: number;
  physicalNodeId?: string | null;
  segmentId?: string | null;
  positionM?: number | null;
  fromNodeId?: string | null;
  toNodeId?: string | null;
  segmentLengthM?: number | null;
  resourceId?: string | null;
  incomingArcId?: string | null;
  loadCount?: number;
  capacity?: number;
  destinationLoads?: { destination: string; count: number }[];
}

export interface ReplayCollisionMarker {
  id: string;
  x: number;
  y: number;
  cabinIds: number[];
  distanceM: number;
  violationKind?: "resource_headway" | "initial_boundary" | "geometric_spacing" | "policy_geometric_preview";
  actualSeparation?: number;
  requiredSeparation?: number;
  unit?: "s" | "m";
  message?: string;
}

export interface ReplayStationQueueMarker {
  stationId: string;
  totalCount: number;
  destinationQueues: { destination: string; count: number }[];
}

export type SegmentRouteInfo = {
  routeId: string;
  routeKind: "service" | "skip";
};

export type ViewBoxState = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type DiscreteOverlayData = {
  nodes: DiscreteNode[];
  selectedNodeIds: Set<string>;
  arcs: DiscreteArc[];
  constraints: DiscreteConstraint[];
  haloSegmentIds: Set<string>;
};

export type NodeLabelPlacement = {
  dx: number;
  dy: number;
};

export type SpeedDomain = {
  min: number;
  max: number;
};
