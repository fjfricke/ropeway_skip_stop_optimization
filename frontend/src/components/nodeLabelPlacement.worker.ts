import type { ScenarioLayout } from "../scenarioLayout";
import type { PhysicalNode, TrackSegment } from "../types";
import { buildNodeLabelPlacements } from "./nodeLabelPlacement";
import type { NodeLabelPlacement, ViewBoxState } from "./networkTypes";
import type { NodeLabelPlacementMetrics } from "./scenarioFigureMetrics";

type NodeLabelPlacementRequest = {
  jobId: number;
  nodes: PhysicalNode[];
  visibleSegments: TrackSegment[];
  layout: ScenarioLayout;
  viewBox: ViewBoxState;
  metrics: NodeLabelPlacementMetrics;
};

type NodeLabelPlacementResponse = {
  jobId: number;
  placements: [string, NodeLabelPlacement][];
};

const workerSelf = self as unknown as {
  onmessage: ((event: MessageEvent<NodeLabelPlacementRequest>) => void) | null;
  postMessage: (message: NodeLabelPlacementResponse) => void;
};

workerSelf.onmessage = (event: MessageEvent<NodeLabelPlacementRequest>) => {
  const { jobId, nodes, visibleSegments, layout, viewBox, metrics } = event.data;
  const placements = buildNodeLabelPlacements({ nodes, visibleSegments, layout, viewBox, metrics });
  workerSelf.postMessage({
    jobId,
    placements: Array.from(placements.entries()),
  } satisfies NodeLabelPlacementResponse);
};

export {};
