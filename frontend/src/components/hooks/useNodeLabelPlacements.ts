import { useEffect, useRef, useState } from "react";
import type { ScenarioLayout } from "../../scenarioLayout";
import type { PhysicalNode, TrackSegment } from "../../types";
import type { NodeLabelPlacement, ViewBoxState } from "../networkTypes";
import type { NodeLabelPlacementMetrics } from "../scenarioFigureMetrics";

type NodeLabelPlacementWorkerResponse = {
  jobId: number;
  placements: [string, NodeLabelPlacement][];
};

const EMPTY_NODE_LABEL_PLACEMENTS = new Map<string, NodeLabelPlacement>();

export function useNodeLabelPlacements({
  inputKey,
  nodes,
  visibleSegments,
  layout,
  viewBox,
  metrics,
}: {
  inputKey: string | null;
  nodes: PhysicalNode[];
  visibleSegments: TrackSegment[];
  layout: ScenarioLayout;
  viewBox: ViewBoxState;
  metrics: NodeLabelPlacementMetrics;
}) {
  const labelPlacementWorkerRef = useRef<Worker | null>(null);
  const labelPlacementJobIdRef = useRef(0);
  const lastNodeLabelInputKeyRef = useRef<string | null>(null);
  const [nodeLabelState, setNodeLabelState] = useState<{
    inputKey: string | null;
    placements: Map<string, NodeLabelPlacement>;
  }>({
    inputKey: null,
    placements: EMPTY_NODE_LABEL_PLACEMENTS,
  });

  useEffect(() => {
    labelPlacementWorkerRef.current?.terminate();
    labelPlacementWorkerRef.current = null;
    labelPlacementJobIdRef.current += 1;

    if (inputKey === null) {
      lastNodeLabelInputKeyRef.current = null;
      setNodeLabelState({ inputKey: null, placements: EMPTY_NODE_LABEL_PLACEMENTS });
      return undefined;
    }

    const inputChanged = lastNodeLabelInputKeyRef.current !== inputKey;
    lastNodeLabelInputKeyRef.current = inputKey;
    if (inputChanged) {
      setNodeLabelState({ inputKey: null, placements: EMPTY_NODE_LABEL_PLACEMENTS });
    }

    const jobId = labelPlacementJobIdRef.current;
    const frame = window.requestAnimationFrame(() => {
      const worker = new Worker(new URL("../nodeLabelPlacement.worker.ts", import.meta.url), { type: "module" });
      labelPlacementWorkerRef.current = worker;
      worker.onmessage = (event: MessageEvent<NodeLabelPlacementWorkerResponse>) => {
        if (event.data.jobId !== labelPlacementJobIdRef.current) return;
        setNodeLabelState({
          inputKey,
          placements: new Map(event.data.placements),
        });
        worker.terminate();
        if (labelPlacementWorkerRef.current === worker) {
          labelPlacementWorkerRef.current = null;
        }
      };
      worker.postMessage({
        jobId,
        nodes,
        visibleSegments,
        layout,
        viewBox,
        metrics,
      });
    });

    return () => {
      window.cancelAnimationFrame(frame);
      labelPlacementWorkerRef.current?.terminate();
      labelPlacementWorkerRef.current = null;
    };
  }, [inputKey, nodes, visibleSegments, layout, viewBox, metrics]);

  return nodeLabelState.inputKey === inputKey ? nodeLabelState.placements : EMPTY_NODE_LABEL_PLACEMENTS;
}
