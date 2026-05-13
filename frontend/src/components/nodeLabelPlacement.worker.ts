import type { ScenarioLayout } from "../scenarioLayout";
import type { PhysicalNode, TrackSegment } from "../types";
import { buildNodeLabelPlacements } from "./nodeLabelPlacement";
import type { NodeLabelPlacement, ViewBoxState } from "./networkTypes";

type NodeLabelPlacementRequest = {
  jobId: number;
  nodes: PhysicalNode[];
  visibleSegments: TrackSegment[];
  layout: ScenarioLayout;
  viewBox: ViewBoxState;
  labelScale: number;
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
  const { jobId, nodes, visibleSegments, layout, viewBox, labelScale } = event.data;
  const placements = buildNodeLabelPlacements(nodes, visibleSegments, layout, viewBox, labelScale);
  workerSelf.postMessage({
    jobId,
    placements: Array.from(placements.entries()),
  } satisfies NodeLabelPlacementResponse);
};

export {};
