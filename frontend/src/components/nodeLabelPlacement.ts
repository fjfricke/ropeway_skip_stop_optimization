import type { ScenarioLayout } from "../scenarioLayout";
import type { PhysicalNode, TrackSegment } from "../types";
import { clamp, pointOnSegment } from "./networkGeometry";
import type { NodeLabelPlacement, ViewBoxState } from "./networkTypes";

export function buildNodeLabelPlacements(
  nodes: PhysicalNode[],
  visibleSegments: TrackSegment[],
  layout: ScenarioLayout,
  viewBox: ViewBoxState,
  labelScale: number,
): Map<string, NodeLabelPlacement> {
  const nodePoints = nodes
    .map((node) => {
      const point = layout.nodes[node.id];
      return point ? { node, point, radius: nodeRadius(node) } : null;
    })
    .filter((item): item is { node: PhysicalNode; point: { x: number; y: number }; radius: number } => item !== null)
    .sort((left, right) => left.point.y - right.point.y || left.point.x - right.point.x);
  const segmentSamples = visibleSegments.flatMap((segment) => sampleSegment(segment, layout));
  const labelItems = nodePoints.map((item) => {
    const labelSize = estimateLabelSize(item.node.id.replaceAll("_", " "));
    return {
      ...item,
      labelSize,
      candidates: nodeLabelCandidates(item.radius, labelSize),
    };
  });
  const orderedItems = [...labelItems].sort((left, right) => {
    const leftValid = staticValidCandidateCount(left, nodePoints, segmentSamples, viewBox, labelScale);
    const rightValid = staticValidCandidateCount(right, nodePoints, segmentSamples, viewBox, labelScale);
    return leftValid - rightValid || left.point.y - right.point.y || left.point.x - right.point.x;
  });
  const placements = new Map<string, NodeLabelPlacement>();
  const placedLabelRects = new Map<string, Rect>();

  for (const item of orderedItems) {
    const best = chooseNodeLabelCandidate({
      item,
      nodePoints,
      segmentSamples,
      placedLabelRects: Array.from(placedLabelRects.values()),
      viewBox,
      labelScale,
    });
    placements.set(item.node.id, { dx: best.dx, dy: best.dy });
    placedLabelRects.set(item.node.id, nodeLabelRect(item.point, best, item.labelSize, labelScale));
  }

  for (let pass = 0; pass < 3; pass += 1) {
    let changed = false;
    for (const item of orderedItems) {
      const currentRect = placedLabelRects.get(item.node.id);
      if (!currentRect || labelCollisionCount(currentRect, item.node.id, placedLabelRects, labelScale) === 0) continue;
      const otherLabelRects = Array.from(placedLabelRects.entries())
        .filter(([nodeId]) => nodeId !== item.node.id)
        .map(([, rect]) => rect);
      const best = chooseNodeLabelCandidate({
        item,
        nodePoints,
        segmentSamples,
        placedLabelRects: otherLabelRects,
        viewBox,
        labelScale,
      });
      const current = placements.get(item.node.id);
      if (current && current.dx === best.dx && current.dy === best.dy) continue;
      placements.set(item.node.id, { dx: best.dx, dy: best.dy });
      placedLabelRects.set(item.node.id, nodeLabelRect(item.point, best, item.labelSize, labelScale));
      changed = true;
    }
    if (!changed) break;
  }

  return placements;
}

type NodeLabelItem = {
  node: PhysicalNode;
  point: { x: number; y: number };
  radius: number;
  labelSize: { width: number; height: number };
  candidates: NodeLabelCandidate[];
};

type NodeLabelCandidate = {
  dx: number;
  dy: number;
  bias: number;
  gap: number;
  position: string;
};

type Rect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

function estimateLabelSize(label: string) {
  return {
    width: Math.max(42, label.length * 8.4),
    height: 18,
  };
}

function nodeLabelCandidates(radius: number, labelSize: { width: number; height: number }): NodeLabelCandidate[] {
  return [5, 3, 1, 0, -3, -6, -9, -12].flatMap((gap) => {
    const horizontal = radius + gap + labelSize.width / 2;
    const vertical = radius + gap + labelSize.height / 2;
    const diagonalX = radius + gap + labelSize.width / 2;
    const diagonalY = radius + gap + labelSize.height / 2;
    const gapPenalty = (5 - gap) * 20;
    return [
      { position: "t", dx: 0, dy: -vertical, bias: gapPenalty, gap },
      { position: "lt", dx: -diagonalX, dy: -diagonalY, bias: gapPenalty + 1, gap },
      { position: "rt", dx: diagonalX, dy: -diagonalY, bias: gapPenalty + 1, gap },
      { position: "l", dx: -horizontal, dy: 0, bias: gapPenalty + 2, gap },
      { position: "r", dx: horizontal, dy: 0, bias: gapPenalty + 2, gap },
      { position: "b", dx: 0, dy: vertical, bias: gapPenalty + 3, gap },
      { position: "lb", dx: -diagonalX, dy: diagonalY, bias: gapPenalty + 4, gap },
      { position: "rb", dx: diagonalX, dy: diagonalY, bias: gapPenalty + 4, gap },
    ];
  });
}

function staticValidCandidateCount(
  item: NodeLabelItem,
  nodePoints: { node: PhysicalNode; point: { x: number; y: number }; radius: number }[],
  segmentSamples: { x: number; y: number }[],
  viewBox: ViewBoxState,
  labelScale: number,
) {
  return item.candidates.filter((candidate) => {
    const rect = nodeLabelRect(item.point, candidate, item.labelSize, labelScale);
    const score = nodeLabelScore(rect, item.node.id, nodePoints, segmentSamples, [], viewBox, labelScale);
    return score.ownershipViolations + score.nodeCollisions + score.segmentCollisions + score.boundsCollisions === 0;
  }).length;
}

function labelCollisionCount(rect: Rect, ownNodeId: string, placedLabelRects: Map<string, Rect>, labelScale: number) {
  let collisions = 0;
  for (const [nodeId, otherRect] of placedLabelRects.entries()) {
    if (nodeId === ownNodeId) continue;
    if (rectsOverlap(expandRect(rect, 5 * labelScale), expandRect(otherRect, 5 * labelScale))) collisions += 1;
  }
  return collisions;
}

function chooseNodeLabelCandidate({
  item,
  nodePoints,
  segmentSamples,
  placedLabelRects,
  viewBox,
  labelScale,
}: {
  item: NodeLabelItem;
  nodePoints: { node: PhysicalNode; point: { x: number; y: number }; radius: number }[];
  segmentSamples: { x: number; y: number }[];
  placedLabelRects: Rect[];
  viewBox: ViewBoxState;
  labelScale: number;
}) {
  let best = item.candidates[0];
  let bestScore: NodeLabelScore | null = null;

  for (const candidate of item.candidates) {
    const rect = nodeLabelRect(item.point, candidate, item.labelSize, labelScale);
    const score = nodeLabelScore(rect, item.node.id, nodePoints, segmentSamples, placedLabelRects, viewBox, labelScale);
    if (!bestScore || compareNodeLabelScores(score, candidate, bestScore, best) < 0) {
      best = candidate;
      bestScore = score;
    }
  }

  return best;
}

type NodeLabelScore = {
  ownershipViolations: number;
  ownershipPenalty: number;
  labelCollisions: number;
  nodeCollisions: number;
  segmentCollisions: number;
  boundsCollisions: number;
  softCost: number;
  minNodeCornerClearance: number;
};

function compareNodeLabelScores(
  leftScore: NodeLabelScore,
  leftCandidate: NodeLabelCandidate,
  rightScore: NodeLabelScore,
  rightCandidate: NodeLabelCandidate,
) {
  if (leftScore.ownershipViolations !== rightScore.ownershipViolations) return leftScore.ownershipViolations - rightScore.ownershipViolations;
  if (leftScore.ownershipPenalty !== rightScore.ownershipPenalty) return leftScore.ownershipPenalty - rightScore.ownershipPenalty;
  if (leftScore.labelCollisions !== rightScore.labelCollisions) return leftScore.labelCollisions - rightScore.labelCollisions;
  if (leftScore.nodeCollisions !== rightScore.nodeCollisions) return leftScore.nodeCollisions - rightScore.nodeCollisions;
  if (leftScore.boundsCollisions !== rightScore.boundsCollisions) return leftScore.boundsCollisions - rightScore.boundsCollisions;
  if (leftScore.segmentCollisions !== rightScore.segmentCollisions) return leftScore.segmentCollisions - rightScore.segmentCollisions;
  if (leftScore.minNodeCornerClearance !== rightScore.minNodeCornerClearance) {
    return rightScore.minNodeCornerClearance - leftScore.minNodeCornerClearance;
  }
  if (leftScore.softCost !== rightScore.softCost) return leftScore.softCost - rightScore.softCost;
  return leftCandidate.bias - rightCandidate.bias;
}

function nodeLabelRect(
  point: { x: number; y: number },
  candidate: { dx: number; dy: number },
  labelSize: { width: number; height: number },
  labelScale: number,
): Rect {
  return {
    x: point.x + candidate.dx * labelScale - (labelSize.width * labelScale) / 2,
    y: point.y + candidate.dy * labelScale - (labelSize.height * labelScale) / 2,
    width: labelSize.width * labelScale,
    height: labelSize.height * labelScale,
  };
}

function nodeLabelScore(
  rect: Rect,
  ownNodeId: string,
  nodePoints: { node: PhysicalNode; point: { x: number; y: number }; radius: number }[],
  segmentSamples: { x: number; y: number }[],
  placedLabelRects: Rect[],
  viewBox: ViewBoxState,
  labelScale: number,
): NodeLabelScore {
  let ownershipViolations = 0;
  let ownershipPenalty = 0;
  let labelCollisions = 0;
  let nodeCollisions = 0;
  let segmentCollisions = 0;
  let boundsCollisions = 0;
  let softCost = 0;
  let minNodeCornerClearance = Number.POSITIVE_INFINITY;
  const ownNode = nodePoints.find((item) => item.node.id === ownNodeId);
  const ownClearance = ownNode ? rectClearanceToCircle(rect, ownNode.point, ownNode.radius * labelScale) : Number.POSITIVE_INFINITY;
  const paddedRect = expandRect(rect, 4 * labelScale);
  for (const item of nodePoints) {
    const scaledRadius = item.radius * labelScale;
    if (item.node.id !== ownNodeId) {
      const otherClearance = rectClearanceToCircle(rect, item.point, scaledRadius);
      const violation = ownClearance - otherClearance;
      if (violation >= 0) {
        ownershipViolations += 1;
        ownershipPenalty += violation;
      }
      minNodeCornerClearance = Math.min(minNodeCornerClearance, rectCornerClearanceToCircle(rect, item.point, scaledRadius));
    }
    if (item.node.id !== ownNodeId && rectOverlapsCircle(paddedRect, item.point, scaledRadius + 4 * labelScale)) nodeCollisions += 1;
  }
  for (const point of segmentSamples) {
    if (pointInsideRect(point, paddedRect)) {
      segmentCollisions += 1;
      softCost += 120;
    }
  }
  for (const label of placedLabelRects) {
    if (rectsOverlap(expandRect(rect, 5 * labelScale), expandRect(label, 5 * labelScale))) labelCollisions += 1;
  }
  if (rect.x < viewBox.x) {
    boundsCollisions += 1;
    softCost += (viewBox.x - rect.x) * 20;
  }
  if (rect.y < viewBox.y) {
    boundsCollisions += 1;
    softCost += (viewBox.y - rect.y) * 20;
  }
  if (rect.x + rect.width > viewBox.x + viewBox.width) {
    boundsCollisions += 1;
    softCost += (rect.x + rect.width - viewBox.x - viewBox.width) * 20;
  }
  if (rect.y + rect.height > viewBox.y + viewBox.height) {
    boundsCollisions += 1;
    softCost += (rect.y + rect.height - viewBox.y - viewBox.height) * 20;
  }
  return {
    ownershipViolations,
    ownershipPenalty,
    labelCollisions,
    nodeCollisions,
    segmentCollisions,
    boundsCollisions,
    softCost,
    minNodeCornerClearance: Number.isFinite(minNodeCornerClearance) ? minNodeCornerClearance : 0,
  };
}

function sampleSegment(segment: TrackSegment, layout: ScenarioLayout) {
  const points: { x: number; y: number }[] = [];
  for (let index = 1; index < 7; index += 1) {
    const point = pointOnSegment(segment, layout, index / 7);
    if (point) points.push(point);
  }
  return points;
}

function nodeRadius(node: PhysicalNode) {
  return node.kind === "platform" ? 12 : 9;
}

function expandRect(rect: Rect, amount: number): Rect {
  return {
    x: rect.x - amount,
    y: rect.y - amount,
    width: rect.width + amount * 2,
    height: rect.height + amount * 2,
  };
}

function rectsOverlap(left: Rect, right: Rect) {
  return left.x < right.x + right.width && left.x + left.width > right.x && left.y < right.y + right.height && left.y + left.height > right.y;
}

function rectOverlapsCircle(rect: Rect, circle: { x: number; y: number }, radius: number) {
  return rectClearanceToCircle(rect, circle, radius) <= 0;
}

function rectClearanceToCircle(rect: Rect, circle: { x: number; y: number }, radius: number) {
  const closestX = clamp(circle.x, rect.x, rect.x + rect.width);
  const closestY = clamp(circle.y, rect.y, rect.y + rect.height);
  return Math.hypot(circle.x - closestX, circle.y - closestY) - radius;
}

function rectCornerClearanceToCircle(rect: Rect, circle: { x: number; y: number }, radius: number) {
  const corners = [
    { x: rect.x, y: rect.y },
    { x: rect.x + rect.width, y: rect.y },
    { x: rect.x, y: rect.y + rect.height },
    { x: rect.x + rect.width, y: rect.y + rect.height },
  ];
  return Math.min(...corners.map((corner) => Math.hypot(corner.x - circle.x, corner.y - circle.y) - radius));
}

function pointInsideRect(point: { x: number; y: number }, rect: Rect) {
  return point.x >= rect.x && point.x <= rect.x + rect.width && point.y >= rect.y && point.y <= rect.y + rect.height;
}
