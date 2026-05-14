import type { ScenarioLayout } from "../../scenarioLayout";
import type { Scenario, Station } from "../../types";
import type { ReplayCabinMarker, ReplayCollisionMarker } from "../networkTypes";
import { stationQueueSize } from "../ReplayLayers";
import type { ScenarioExportRenderPlan } from "../scenarioExportGeometry";
import { stationContentPlacement } from "../stationPlacement";
import { stationVisualColor } from "../stationColors";
import type { ReplayVideoFrame } from "./replayFrameModel";

const STATION_QUEUE_ROW_HEIGHT = 14;
const STATION_QUEUE_ROW_TOP = 22;

type ReplayVideoSprite = {
  source: CanvasImageSource;
  offsetX: number;
  offsetY: number;
};

export type ReplayVideoSpriteCache = {
  cabinSprites: Map<string, ReplayVideoSprite>;
  queueSprites: Map<string, ReplayVideoSprite>;
  renderPlan: ScenarioExportRenderPlan;
  scale: number;
  showCabinFill: boolean;
  stations: Station[];
};

export function drawReplayVideoFrame(
  context: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  staticImage: CanvasImageSource,
  frame: ReplayVideoFrame,
  renderPlan: ScenarioExportRenderPlan,
  spriteCache: ReplayVideoSpriteCache,
  showQueues: boolean,
  scenario: Scenario,
  layout: ScenarioLayout,
) {
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = "#fff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(staticImage, 0, 0, canvas.width, canvas.height);
  if (showQueues) {
    drawReplayQueues(context, canvas, frame.queues, renderPlan, spriteCache, scenario, layout);
  }
  const cabins = visibleReplayCabinsForRenderPlan(frame.cabins, renderPlan);
  const cabinIds = new Set(cabins.map((cabin) => cabin.cabinId));
  for (let index = 0; index < cabins.length; index += 1) {
    drawReplayCabin(context, cabins[index], canvas, renderPlan, spriteCache);
  }
  const collisions = frame.collisions.filter((collision) => collision.cabinIds.every((cabinId) => cabinIds.has(cabinId)));
  for (const collision of collisions) {
    drawReplayCollision(context, collision, canvas, renderPlan);
  }
}

export function createReplayVideoSpriteCache(
  canvas: HTMLCanvasElement,
  renderPlan: ScenarioExportRenderPlan,
  showCabinFill: boolean,
  stations: Station[],
): ReplayVideoSpriteCache {
  return {
    cabinSprites: new Map(),
    queueSprites: new Map(),
    renderPlan,
    scale: exportScaleToCanvas(canvas, renderPlan),
    showCabinFill,
    stations,
  };
}

function visibleReplayCabinsForRenderPlan(cabins: ReplayCabinMarker[], renderPlan: ScenarioExportRenderPlan) {
  return cabins.filter((cabin) => {
    if (cabin.physicalNodeId) return renderPlan.physicalNodes.has(cabin.physicalNodeId);
    if (!cabin.segmentId) return false;
    const segmentRender = renderPlan.physicalSegments.find((current) => current.segment.id === cabin.segmentId);
    if (!segmentRender) return false;
    if (segmentRender.mode === "full") return true;
    if (typeof cabin.positionM !== "number" || typeof cabin.segmentLengthM !== "number" || cabin.segmentLengthM <= 0) return true;
    const t = cabin.positionM / cabin.segmentLengthM;
    return segmentRender.mode === "from_start" ? t <= 0.5 : t >= 0.5;
  });
}

function drawReplayCabin(
  context: CanvasRenderingContext2D,
  cabin: ReplayCabinMarker,
  canvas: HTMLCanvasElement,
  renderPlan: ScenarioExportRenderPlan,
  spriteCache: ReplayVideoSpriteCache,
) {
  if (typeof cabin.x !== "number" || typeof cabin.y !== "number") return;
  const point = exportPointToCanvas(cabin.x, cabin.y, canvas, renderPlan);
  const sprite = replayCabinSprite(spriteCache, cabin);
  context.drawImage(sprite.source, point.x - sprite.offsetX, point.y - sprite.offsetY);
}

function replayCabinSprite(cache: ReplayVideoSpriteCache, cabin: ReplayCabinMarker): ReplayVideoSprite {
  const key = [
    cabin.cabinId,
    cabin.capacity ?? 0,
    cabin.loadCount ?? 0,
    cache.showCabinFill ? "fill" : "empty",
    ...(cabin.destinationLoads ?? []).map((item) => `${item.destination}:${item.count}`),
  ].join("|");
  const cached = cache.cabinSprites.get(key);
  if (cached) return cached;

  const radius = 10 * cache.renderPlan.metrics.shapeScale * cache.scale;
  const pad = Math.ceil(Math.max(5, radius * 0.35));
  const size = Math.ceil(radius * 2 + pad * 2);
  const spriteCanvas = document.createElement("canvas");
  spriteCanvas.width = size;
  spriteCanvas.height = size;
  const context = spriteCanvas.getContext("2d");
  if (!context) {
    const fallback = { source: spriteCanvas, offsetX: size / 2, offsetY: size / 2 };
    cache.cabinSprites.set(key, fallback);
    return fallback;
  }
  context.translate(size / 2, size / 2);
  drawReplayCabinShape(context, cabin, radius, cache.renderPlan, cache.scale, cache.showCabinFill, cache.stations);
  const sprite = { source: spriteCanvas, offsetX: size / 2, offsetY: size / 2 };
  cache.cabinSprites.set(key, sprite);
  return sprite;
}

function drawReplayCabinShape(
  context: CanvasRenderingContext2D,
  cabin: ReplayCabinMarker,
  radius: number,
  renderPlan: ScenarioExportRenderPlan,
  scale: number,
  showCabinFill: boolean,
  stations: Station[],
) {
  const innerRadius = Math.max(1, radius - 2.2 * renderPlan.metrics.shapeScale * scale);
  const capacity = cabin.capacity ?? 0;
  const loadCount = cabin.loadCount ?? 0;
  context.save();
  context.fillStyle = "#253345";
  context.strokeStyle = "#fff";
  context.lineWidth = Math.max(1, 2 * renderPlan.metrics.shapeScale * scale);
  context.beginPath();
  context.arc(0, 0, radius, 0, Math.PI * 2);
  context.fill();
  context.stroke();

  context.fillStyle = "#f7faf9";
  context.strokeStyle = "rgba(23,32,43,.24)";
  context.lineWidth = Math.max(0.5, renderPlan.metrics.shapeScale * scale);
  context.beginPath();
  context.arc(0, 0, innerRadius, 0, Math.PI * 2);
  context.fill();
  context.stroke();

  if (showCabinFill && capacity > 0) {
    drawCabinPieSlices(context, cabin.destinationLoads ?? [], capacity, innerRadius, stations);
  }

  const fontSize = Math.max(5, 8 * renderPlan.metrics.shapeScale * scale);
  context.font = `850 ${fontSize}px ${renderPlan.metrics.fontFamily}`;
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.lineWidth = Math.max(1, 2.2 * renderPlan.metrics.shapeScale * scale);
  context.strokeStyle = loadCount > 0 ? "rgba(23,32,43,.62)" : "rgba(255,255,255,.92)";
  context.fillStyle = loadCount > 0 ? "#fff" : "#17202b";
  context.strokeText(`C${cabin.cabinId}`, 0, fontSize * 0.04);
  context.fillText(`C${cabin.cabinId}`, 0, fontSize * 0.04);
  context.restore();
}

function drawReplayQueues(
  context: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  queues: ReplayVideoFrame["queues"],
  renderPlan: ScenarioExportRenderPlan,
  spriteCache: ReplayVideoSpriteCache,
  scenario: Scenario,
  layout: ScenarioLayout,
) {
  if (queues.length === 0) return;
  const maxQueue = Math.max(1, ...queues.map((queue) => queue.totalCount));
  for (const queue of queues) {
    const localSize = stationQueueSize(queue, maxQueue);
    const placement = stationContentPlacement(queue.stationId, scenario, layout, renderPlan.viewBox, localSize, renderPlan.metrics.shapeScale);
    if (!placement) continue;
    const point = exportPointToCanvas(placement.x, placement.y, canvas, renderPlan);
    const sprite = replayQueueSprite(spriteCache, queue, maxQueue);
    context.drawImage(sprite.source, point.x - sprite.offsetX, point.y - sprite.offsetY);
  }
}

function replayQueueSprite(cache: ReplayVideoSpriteCache, queue: ReplayVideoFrame["queues"][number], maxQueue: number): ReplayVideoSprite {
  const key = [
    maxQueue,
    queue.stationId,
    queue.totalCount,
    ...queue.destinationQueues.map((item) => `${item.destination}:${item.count}`),
  ].join("|");
  const cached = cache.queueSprites.get(key);
  if (cached) return cached;

  const localSize = stationQueueSize(queue, maxQueue);
  const localPad = 6;
  const spriteScale = cache.renderPlan.metrics.shapeScale * cache.scale;
  const width = Math.ceil((localSize.width + localPad * 2) * spriteScale);
  const height = Math.ceil((localSize.height + localPad * 2) * spriteScale);
  const spriteCanvas = document.createElement("canvas");
  spriteCanvas.width = Math.max(1, width);
  spriteCanvas.height = Math.max(1, height);
  const context = spriteCanvas.getContext("2d");
  if (!context) {
    const fallback = { source: spriteCanvas, offsetX: localPad * spriteScale, offsetY: localPad * spriteScale };
    cache.queueSprites.set(key, fallback);
    return fallback;
  }

  context.scale(spriteScale, spriteScale);
  context.translate(localPad, localPad);
  context.textBaseline = "alphabetic";
  context.lineJoin = "round";

  context.font = `850 11px ${cache.renderPlan.metrics.fontFamily}`;
  context.strokeStyle = "rgba(255,255,255,.86)";
  context.lineWidth = 3;
  context.fillStyle = "#17202b";
  const label = `${queue.totalCount} waiting`;
  context.strokeText(label, 0, 12);
  context.fillText(label, 0, 12);

  queue.destinationQueues.forEach((item, index) => {
    const y = STATION_QUEUE_ROW_TOP + index * STATION_QUEUE_ROW_HEIGHT;
    const barWidth = 18 + (item.count / maxQueue) * 54;
    context.beginPath();
    roundedRectPath(context, 0, y, barWidth, 9, 2);
    context.fillStyle = stationVisualColor(item.destination, cache.stations).base;
    context.fill();
    context.strokeStyle = "rgba(255,255,255,.92)";
    context.lineWidth = 1;
    context.stroke();

    const text = `${item.destination}:${item.count}`;
    context.font = `820 10px ${cache.renderPlan.metrics.fontFamily}`;
    context.strokeStyle = "rgba(255,255,255,.86)";
    context.lineWidth = 3;
    context.fillStyle = "#17202b";
    context.strokeText(text, barWidth + 5, y + 8);
    context.fillText(text, barWidth + 5, y + 8);
  });

  const sprite = {
    source: spriteCanvas,
    offsetX: localPad * spriteScale,
    offsetY: localPad * spriteScale,
  };
  cache.queueSprites.set(key, sprite);
  return sprite;
}

function roundedRectPath(context: CanvasRenderingContext2D, x: number, y: number, width: number, height: number, radius: number) {
  const safeRadius = Math.min(radius, width / 2, height / 2);
  context.moveTo(x + safeRadius, y);
  context.lineTo(x + width - safeRadius, y);
  context.quadraticCurveTo(x + width, y, x + width, y + safeRadius);
  context.lineTo(x + width, y + height - safeRadius);
  context.quadraticCurveTo(x + width, y + height, x + width - safeRadius, y + height);
  context.lineTo(x + safeRadius, y + height);
  context.quadraticCurveTo(x, y + height, x, y + height - safeRadius);
  context.lineTo(x, y + safeRadius);
  context.quadraticCurveTo(x, y, x + safeRadius, y);
}

function drawCabinPieSlices(
  context: CanvasRenderingContext2D,
  destinationLoads: { destination: string; count: number }[],
  capacity: number,
  radius: number,
  stations: Station[],
) {
  let cursor = -Math.PI / 2;
  for (const item of destinationLoads) {
    if (item.count <= 0) continue;
    const sliceRadians = Math.min(Math.PI * 2, (item.count / capacity) * Math.PI * 2);
    const end = cursor + sliceRadians;
    context.beginPath();
    context.moveTo(0, 0);
    context.arc(0, 0, radius, cursor, end);
    context.closePath();
    context.fillStyle = stationVisualColor(item.destination, stations).base;
    context.fill();
    context.strokeStyle = "rgba(255,255,255,.9)";
    context.lineWidth = Math.max(0.5, radius * 0.07);
    context.stroke();
    cursor = end;
  }
}

function drawReplayCollision(
  context: CanvasRenderingContext2D,
  collision: ReplayCollisionMarker,
  canvas: HTMLCanvasElement,
  renderPlan: ScenarioExportRenderPlan,
) {
  const point = exportPointToCanvas(collision.x, collision.y, canvas, renderPlan);
  const scale = exportScaleToCanvas(canvas, renderPlan);
  const radius = 17 * renderPlan.metrics.shapeScale * scale;
  context.save();
  context.translate(point.x, point.y);
  context.fillStyle = "#d82020";
  context.strokeStyle = "#fff";
  context.lineWidth = Math.max(1.5, 3.2 * renderPlan.metrics.shapeScale * scale);
  context.beginPath();
  context.arc(0, 0, radius, 0, Math.PI * 2);
  context.fill();
  context.stroke();
  context.fillStyle = "#fff";
  context.font = `950 ${28 * renderPlan.metrics.shapeScale * scale}px ${renderPlan.metrics.fontFamily}`;
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText("!", 0, 0);
  context.restore();
}

function exportPointToCanvas(x: number, y: number, canvas: HTMLCanvasElement, renderPlan: ScenarioExportRenderPlan) {
  return {
    x: ((x - renderPlan.viewBox.x) / renderPlan.viewBox.width) * canvas.width,
    y: ((y - renderPlan.viewBox.y) / renderPlan.viewBox.height) * canvas.height,
  };
}

function exportScaleToCanvas(canvas: HTMLCanvasElement, renderPlan: ScenarioExportRenderPlan) {
  return canvas.width / renderPlan.viewBox.width;
}
