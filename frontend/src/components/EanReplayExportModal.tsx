import { Download, Eye, Film, Images, MousePointer2, Pause, Play, Plus, Tags, Trash2, Users, WholeWord, X } from "lucide-react";
import { zipSync, strToU8 } from "fflate";
import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { flushSync } from "react-dom";
import type { ScenarioLayout } from "../scenarioLayout";
import type { EanPassengerServiceResult, EanPhysicalReplay, Scenario, TrackSegment } from "../types";
import {
  advanceReplayTime,
  buildEanPassengerState,
  clockLabel,
  eanCabinMarkersAtTime,
  eanReplayCollisionMarkers,
  eanReplayTimeBounds,
  EVENT_TOLERANCE_SECONDS,
  formatSeconds,
  groupEventsByCabin,
  isReplayBoundary,
  MANUAL_STEP_SECONDS,
  SPEED_OPTIONS,
  type PlaybackDirection,
} from "./EanReplayView";
import { ScenarioExportSelectorSvg } from "./ScenarioExportSelectorSvg";
import { ScenarioExportSvg } from "./ScenarioExportSvg";
import { buildScenarioExportRenderPlan } from "./scenarioExportGeometry";
import type { ArcColorMode, ReplayExportConfig, ScenarioExportBasis, ViewerToggles } from "./viewerTypes";

interface EanReplayExportModalProps {
  scenario: Scenario;
  layout: ScenarioLayout;
  eanReplay: EanPhysicalReplay;
  eanPassengerService: EanPassengerServiceResult | null;
  toggles: ViewerToggles;
  arcColorMode: ArcColorMode;
  initialTimeSeconds: number;
  onClose: () => void;
}

type ExportPane = "preview" | "selector";
type ExportStatus = {
  message: string;
  progress: number;
} | null;

const DEFAULT_PERCENTAGE = 100;
const DEFAULT_VIDEO_SECONDS = 10;
const DEFAULT_FPS = 30;

export function EanReplayExportModal({
  scenario,
  layout,
  eanReplay,
  eanPassengerService,
  toggles,
  arcColorMode,
  initialTimeSeconds,
  onClose,
}: EanReplayExportModalProps) {
  const nodeOptions = useMemo(() => scenario.physical_nodes.map((node) => ({ id: node.id, label: node.id.replaceAll("_", " ") })), [scenario.physical_nodes]);
  const arcOptions = useMemo(() => scenario.track_segments.map((segment) => ({ id: segment.id, label: physicalArcLabel(segment) })), [scenario.track_segments]);
  const timeBounds = useMemo(() => eanReplayTimeBounds(eanReplay), [eanReplay]);
  const initialTime = clampNumber(initialTimeSeconds, timeBounds.min, timeBounds.max);
  const [activePane, setActivePane] = useState<ExportPane>("preview");
  const [selectorTimeSeconds, setSelectorTimeSeconds] = useState(initialTime);
  const [selectorPlaying, setSelectorPlaying] = useState(false);
  const [selectorSpeed, setSelectorSpeed] = useState(1);
  const [selectorDirection, setSelectorDirection] = useState<PlaybackDirection>(1);
  const [sourceFrameTimeSeconds, setSourceFrameTimeSeconds] = useState(initialTime);
  const [status, setStatus] = useState<ExportStatus>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [config, setConfig] = useState<ReplayExportConfig>(() => {
    const end = Math.min(timeBounds.max, initialTime + DEFAULT_VIDEO_SECONDS);
    const start = end <= initialTime ? Math.max(timeBounds.min, end - DEFAULT_VIDEO_SECONDS) : initialTime;
    return {
      displayMode: "physical",
      scope: "custom",
      selectedNodeIds: nodeOptions.map((option) => option.id),
      selectedArcIds: arcOptions.map((option) => option.id),
      toggles: { ...toggles },
      arcColorMode,
      basis: "a4_width",
      percentage: DEFAULT_PERCENTAGE,
      exportMode: "video",
      videoStartSeconds: start,
      videoEndSeconds: end,
      fps: DEFAULT_FPS,
      exportSpeed: 1,
      selectedFrameTimes: [roundFrameTime(initialTime)],
      showCabinFill: true,
    };
  });
  const previewCanvasRef = useRef<HTMLDivElement | null>(null);
  const exportSvgRef = useRef<SVGSVGElement | null>(null);
  const [previewCanvasSize, setPreviewCanvasSize] = useState({ width: 0, height: 0 });
  const deferredConfig = useDeferredValue(config);
  const renderPlan = useMemo(() => buildScenarioExportRenderPlan({ scenario, layout, config: deferredConfig }), [scenario, layout, deferredConfig]);
  const selectedNodeIds = useMemo(() => new Set(config.selectedNodeIds), [config.selectedNodeIds]);
  const selectedArcIds = useMemo(() => new Set(config.selectedArcIds), [config.selectedArcIds]);
  const eventsByCabin = useMemo(() => groupEventsByCabin(eanReplay.events), [eanReplay.events]);
  const passengerPlan = eanPassengerService?.passenger_plan ?? null;
  const previewTimeSeconds = config.exportMode === "frames" ? selectorTimeSeconds : config.videoStartSeconds;
  const previewFrame = useMemo(
    () => replayFrameAtTime({ scenario, layout, eventsByCabin, passengerPlan, timeSeconds: previewTimeSeconds }),
    [eventsByCabin, layout, passengerPlan, previewTimeSeconds, scenario],
  );
  const sourceFrame = useMemo(
    () => replayFrameAtTime({ scenario, layout, eventsByCabin, passengerPlan, timeSeconds: sourceFrameTimeSeconds }),
    [eventsByCabin, layout, passengerPlan, scenario, sourceFrameTimeSeconds],
  );

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  useEffect(() => {
    const element = previewCanvasRef.current;
    if (!element) return undefined;
    const updateSize = () => {
      const rect = element.getBoundingClientRect();
      setPreviewCanvasSize({ width: rect.width, height: rect.height });
    };
    updateSize();
    const observer = new ResizeObserver(updateSize);
    observer.observe(element);
    return () => observer.disconnect();
  }, [activePane]);

  useEffect(() => {
    if (!selectorPlaying) return undefined;
    let frameId = 0;
    let previousFrameMs: number | null = null;
    const animate = (frameMs: number) => {
      if (previousFrameMs !== null) {
        const elapsedSeconds = (frameMs - previousFrameMs) / 1000;
        setSelectorTimeSeconds((current) => {
          const next = advanceReplayTime(current, elapsedSeconds * selectorSpeed * selectorDirection, timeBounds.min, timeBounds.max);
          if (isReplayBoundary(next, selectorDirection, timeBounds.min, timeBounds.max)) setSelectorPlaying(false);
          return next;
        });
      }
      previousFrameMs = frameMs;
      frameId = window.requestAnimationFrame(animate);
    };
    frameId = window.requestAnimationFrame(animate);
    return () => window.cancelAnimationFrame(frameId);
  }, [selectorDirection, selectorPlaying, selectorSpeed, timeBounds.max, timeBounds.min]);

  const artboardSize = useMemo(() => {
    const exportAspect = renderPlan.outputWidth / renderPlan.outputHeight;
    const canvasAspect = previewCanvasSize.width > 0 && previewCanvasSize.height > 0 ? previewCanvasSize.width / previewCanvasSize.height : exportAspect;
    if (previewCanvasSize.width <= 0 || previewCanvasSize.height <= 0) return null;
    if (exportAspect >= canvasAspect) {
      return {
        width: previewCanvasSize.width,
        height: previewCanvasSize.width / exportAspect,
      };
    }
    return {
      width: previewCanvasSize.height * exportAspect,
      height: previewCanvasSize.height,
    };
  }, [previewCanvasSize, renderPlan.outputHeight, renderPlan.outputWidth]);

  function updateConfig(updater: (current: ReplayExportConfig) => ReplayExportConfig) {
    setConfig(updater);
    setDownloadError(null);
  }

  function toggleExportLayer(key: keyof ViewerToggles) {
    updateConfig((current) => ({
      ...current,
      toggles: {
        ...current.toggles,
        [key]: !current.toggles[key],
      },
    }));
  }

  function toggleNode(id: string) {
    updateConfig((current) => ({ ...current, selectedNodeIds: toggleId(current.selectedNodeIds, id) }));
  }

  function toggleArc(id: string) {
    updateConfig((current) => ({ ...current, selectedArcIds: toggleId(current.selectedArcIds, id) }));
  }

  function selectAllCustomItems() {
    updateConfig((current) => ({
      ...current,
      selectedNodeIds: nodeOptions.map((option) => option.id),
      selectedArcIds: arcOptions.map((option) => option.id),
    }));
  }

  function clearCustomItems() {
    updateConfig((current) => ({ ...current, selectedNodeIds: [], selectedArcIds: [] }));
  }

  function addCurrentFrame() {
    const nextTime = roundFrameTime(selectorTimeSeconds);
    updateConfig((current) => ({
      ...current,
      selectedFrameTimes: [...new Set([...current.selectedFrameTimes, nextTime])].sort((left, right) => left - right),
    }));
  }

  function removeFrame(timeSeconds: number) {
    updateConfig((current) => ({
      ...current,
      selectedFrameTimes: current.selectedFrameTimes.filter((time) => time !== timeSeconds),
    }));
  }

  async function renderSourceSvgAt(timeSeconds: number) {
    flushSync(() => setSourceFrameTimeSeconds(timeSeconds));
    await nextAnimationFrame();
    if (!exportSvgRef.current) throw new Error("Export SVG unavailable");
    return exportSvgRef.current;
  }

  async function handleDownload() {
    setDownloadError(null);
    try {
      if (config.exportMode === "frames") {
        await downloadFrameZip();
      } else {
        await downloadVideo();
      }
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : "Replay export failed");
      setStatus(null);
    }
  }

  async function downloadFrameZip() {
    const frameTimes = config.selectedFrameTimes.length > 0 ? config.selectedFrameTimes : [roundFrameTime(selectorTimeSeconds)];
    const files: Record<string, Uint8Array> = {};
    for (let index = 0; index < frameTimes.length; index += 1) {
      const timeSeconds = frameTimes[index];
      setStatus({ message: `Rendering frame ${index + 1} / ${frameTimes.length}`, progress: index / frameTimes.length });
      const svg = await renderSourceSvgAt(timeSeconds);
      const source = serializeSvgElement(svg);
      files[frameFilename(scenario.scenario_id, timeSeconds)] = strToU8(source);
    }
    const zipBytes = zipSync(files, { level: 6 });
    const zipCopy = new Uint8Array(zipBytes);
    downloadBlob(new Blob([zipCopy.buffer], { type: "application/zip" }), `${scenario.scenario_id}_ean_replay_frames.zip`);
    setStatus(null);
  }

  async function downloadVideo() {
    const start = Math.min(config.videoStartSeconds, config.videoEndSeconds);
    const end = Math.max(config.videoStartSeconds, config.videoEndSeconds);
    const modelDurationSeconds = Math.max(0.1, end - start);
    const videoDurationSeconds = Math.max(0.1, modelDurationSeconds / Math.max(0.1, config.exportSpeed));
    const frameCount = Math.max(2, Math.ceil(videoDurationSeconds * config.fps));
    const canvas = document.createElement("canvas");
    canvas.width = renderPlan.outputWidth;
    canvas.height = renderPlan.outputHeight;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("Canvas export unavailable");
    const stream = canvas.captureStream(config.fps);
    const mimeType = mediaRecorderMimeType();
    const chunks: BlobPart[] = [];
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    };
    const stopped = new Promise<void>((resolve, reject) => {
      recorder.onstop = () => resolve();
      recorder.onerror = () => reject(new Error("WebM recording failed"));
    });
    recorder.start();
    for (let index = 0; index < frameCount; index += 1) {
      const ratio = frameCount === 1 ? 0 : index / (frameCount - 1);
      const timeSeconds = start + ratio * (end - start);
      setStatus({ message: `Rendering video frame ${index + 1} / ${frameCount}`, progress: index / frameCount });
      const svg = await renderSourceSvgAt(timeSeconds);
      await drawSvgToCanvas(svg, canvas, context);
      await delay(1000 / config.fps);
    }
    recorder.stop();
    await stopped;
    stream.getTracks().forEach((track) => track.stop());
    downloadBlob(new Blob(chunks, { type: recorder.mimeType || "video/webm" }), `${scenario.scenario_id}_ean_replay.webm`);
    setStatus(null);
  }

  const canDownload = config.exportMode === "video" || config.selectedFrameTimes.length > 0;

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="export-modal replay-export-modal" role="dialog" aria-modal="true" aria-labelledby="ean-replay-export-title" onMouseDown={(event) => event.stopPropagation()}>
        <header className="export-modal__header">
          <div>
            <p className="eyebrow">EAN replay export</p>
            <h2 id="ean-replay-export-title">Physical Replay Export</h2>
          </div>
          <button type="button" className="export-modal__icon-button" onClick={onClose} aria-label="Close export modal">
            <X size={17} />
          </button>
        </header>

        <div className="export-modal__body">
          <div className="export-modal__settings">
            <section className="export-section">
              <h3>Mode</h3>
              <div className="export-toggle-grid">
                <button type="button" className={config.exportMode === "video" ? "is-active" : ""} onClick={() => updateConfig((current) => ({ ...current, exportMode: "video" }))}>
                  <Film size={16} />
                  Export Video
                </button>
                <button type="button" className={config.exportMode === "frames" ? "is-active" : ""} onClick={() => updateConfig((current) => ({ ...current, exportMode: "frames" }))}>
                  <Images size={16} />
                  Export Frames
                </button>
              </div>
            </section>

            <section className="export-section export-section--selection-actions">
              <div className="export-section__header">
                <h3>Items</h3>
                <div className="export-section__actions">
                  <button type="button" onClick={selectAllCustomItems}>All</button>
                  <button type="button" onClick={clearCustomItems}>None</button>
                </div>
              </div>
              <p className="export-section__meta">
                {selectedNodeIds.size} nodes · {selectedArcIds.size} arcs
              </p>
            </section>

            <section className="export-section">
              <h3>Layers</h3>
              <div className="export-toggle-grid">
                <button type="button" className={config.toggles.serviceRoutes ? "is-active" : ""} onClick={() => toggleExportLayer("serviceRoutes")}>Service</button>
                <button type="button" className={config.toggles.skipRoutes ? "is-active" : ""} onClick={() => toggleExportLayer("skipRoutes")}>Skip</button>
                <button type="button" className={config.toggles.nodeLabels ? "is-active" : ""} onClick={() => toggleExportLayer("nodeLabels")}>
                  <WholeWord size={16} />
                  Node Labels
                </button>
                <button type="button" className={config.toggles.arcLabels ? "is-active" : ""} onClick={() => toggleExportLayer("arcLabels")}>
                  <Tags size={16} />
                  Arc Labels
                </button>
                <button type="button" className={config.toggles.demand ? "is-active" : ""} onClick={() => toggleExportLayer("demand")}>
                  <Users size={16} />
                  Demand
                </button>
                <button type="button" className={config.showCabinFill ? "is-active" : ""} onClick={() => updateConfig((current) => ({ ...current, showCabinFill: !current.showCabinFill }))}>
                  Cabin Fill: {config.showCabinFill ? "On" : "Off"}
                </button>
                <button
                  type="button"
                  className={`is-active export-toggle-grid__arc-color export-toggle-grid__arc-color--${config.arcColorMode}`}
                  onClick={() => updateConfig((current) => ({ ...current, arcColorMode: current.arcColorMode === "type" ? "speed" : "type" }))}
                >
                  Arc Color: {config.arcColorMode === "type" ? "Type" : "Speed"}
                </button>
              </div>
            </section>

            {config.exportMode === "video" ? (
              <section className="export-section">
                <h3>Video Range</h3>
                <div className="export-size-grid">
                  <label>
                    Start
                    <input type="number" step="0.1" value={roundFrameTime(config.videoStartSeconds)} onChange={(event) => updateConfig((current) => ({ ...current, videoStartSeconds: clampNumber(Number(event.target.value), timeBounds.min, timeBounds.max) }))} />
                  </label>
                  <label>
                    End
                    <input type="number" step="0.1" value={roundFrameTime(config.videoEndSeconds)} onChange={(event) => updateConfig((current) => ({ ...current, videoEndSeconds: clampNumber(Number(event.target.value), timeBounds.min, timeBounds.max) }))} />
                  </label>
                  <label>
                    FPS
                    <input type="number" min="1" max="60" value={config.fps} onChange={(event) => updateConfig((current) => ({ ...current, fps: Math.round(clampNumber(Number(event.target.value), 1, 60)) }))} />
                  </label>
                  <label>
                    Speed
                    <select value={config.exportSpeed} onChange={(event) => updateConfig((current) => ({ ...current, exportSpeed: Number(event.target.value) }))}>
                      {SPEED_OPTIONS.map((speed) => <option key={speed} value={speed}>{speed}x</option>)}
                    </select>
                  </label>
                </div>
              </section>
            ) : (
              <section className="export-section">
                <div className="export-section__header">
                  <h3>Frames</h3>
                  <div className="export-section__actions">
                    <button type="button" onClick={addCurrentFrame}>
                      <Plus size={14} />
                      Add
                    </button>
                    <button type="button" onClick={() => updateConfig((current) => ({ ...current, selectedFrameTimes: [] }))}>
                      None
                    </button>
                  </div>
                </div>
                <div className="replay-export-frame-list">
                  {config.selectedFrameTimes.length === 0 ? (
                    <p>No frames selected</p>
                  ) : config.selectedFrameTimes.map((timeSeconds) => (
                    <button type="button" key={timeSeconds} onClick={() => setSelectorTimeSeconds(timeSeconds)}>
                      <span>{formatSeconds(timeSeconds)}</span>
                      <em>{clockLabel(scenario.service_start_time, timeSeconds)}</em>
                      <Trash2 size={14} onClick={(event) => {
                        event.stopPropagation();
                        removeFrame(timeSeconds);
                      }} />
                    </button>
                  ))}
                </div>
              </section>
            )}

            <section className="export-section">
              <h3>Size</h3>
              <div className="export-size-grid">
                <label>
                  Basis
                  <select value={config.basis} onChange={(event) => updateConfig((current) => ({ ...current, basis: event.target.value as ScenarioExportBasis }))}>
                    <option value="a4_width">A4 width</option>
                    <option value="a4_height">A4 height</option>
                  </select>
                </label>
                <label>
                  Percent
                  <input type="number" min="1" max="400" value={config.percentage} onChange={(event) => updateConfig((current) => ({ ...current, percentage: clampNumber(Number(event.target.value), 1, 400) }))} />
                </label>
              </div>
            </section>
          </div>

          <div className="export-modal__preview">
            <div className="export-preview__header">
              <div>
                <h3>{activePane === "preview" ? "Preview" : "Selector"}</h3>
                <p>{renderPlan.outputWidth} x {renderPlan.outputHeight}px · {formatSeconds(previewTimeSeconds)}</p>
              </div>
              <div className="export-preview__actions">
                <div className="export-pane-tabs" aria-label="Export panel">
                  <button type="button" className={activePane === "preview" ? "is-active" : ""} onClick={() => setActivePane("preview")}>
                    <Eye size={16} />
                    Preview
                  </button>
                  <button type="button" className={activePane === "selector" ? "is-active" : ""} onClick={() => setActivePane("selector")}>
                    <MousePointer2 size={16} />
                    Selector
                  </button>
                </div>
                <button type="button" onClick={handleDownload} disabled={!canDownload || status !== null}>
                  <Download size={16} />
                  {config.exportMode === "video" ? "Download WebM" : "Download SVG ZIP"}
                </button>
              </div>
            </div>

            {activePane === "preview" ? (
              <div className="export-preview__canvas" ref={previewCanvasRef}>
                <div
                  className="export-preview__artboard"
                  style={{
                    aspectRatio: `${renderPlan.outputWidth} / ${renderPlan.outputHeight}`,
                    ...(artboardSize ? { width: `${artboardSize.width}px`, height: `${artboardSize.height}px` } : null),
                  } as CSSProperties}
                >
                  <ScenarioExportSvg
                    scenario={scenario}
                    layout={layout}
                    config={deferredConfig}
                    renderPlan={renderPlan}
                    replayCabins={previewFrame.cabins}
                    replayCollisionMarkers={previewFrame.collisions}
                    replayStationQueues={previewFrame.queues}
                    showCabinFill={config.showCabinFill}
                  />
                </div>
              </div>
            ) : (
              <div className="export-preview__canvas export-preview__canvas--selector">
                <div className="replay-export-selector-controls">
                  <button type="button" onClick={() => setSelectorTimeSeconds((current) => Math.max(timeBounds.min, current - MANUAL_STEP_SECONDS))}>Back</button>
                  <button type="button" className="is-active" onClick={() => setSelectorPlaying((current) => !current)}>
                    {selectorPlaying ? <Pause size={15} /> : <Play size={15} />}
                    {selectorPlaying ? "Pause" : "Play"}
                  </button>
                  <button type="button" onClick={() => setSelectorTimeSeconds((current) => Math.min(timeBounds.max, current + MANUAL_STEP_SECONDS))}>Next</button>
                  <button type="button" onClick={() => setSelectorDirection((current) => (current === 1 ? -1 : 1))}>{selectorDirection === 1 ? "Forward" : "Backward"}</button>
                  <select value={selectorSpeed} onChange={(event) => setSelectorSpeed(Number(event.target.value))}>
                    {SPEED_OPTIONS.map((speed) => <option key={speed} value={speed}>{speed}x</option>)}
                  </select>
                  <strong>{formatSeconds(selectorTimeSeconds)}</strong>
                </div>
                <ScenarioExportSelectorSvg
                  scenario={scenario}
                  layout={layout}
                  config={config}
                  selectedNodeIds={selectedNodeIds}
                  selectedArcIds={selectedArcIds}
                  onNodeToggle={toggleNode}
                  onArcToggle={toggleArc}
                />
              </div>
            )}

            <div className="export-download-source" aria-hidden="true">
              <ScenarioExportSvg
                ref={exportSvgRef}
                scenario={scenario}
                layout={layout}
                config={deferredConfig}
                renderPlan={renderPlan}
                replayCabins={sourceFrame.cabins}
                replayCollisionMarkers={sourceFrame.collisions}
                replayStationQueues={sourceFrame.queues}
                showCabinFill={config.showCabinFill}
              />
            </div>

            {status ? (
              <p className="export-preview__stale">{status.message} · {Math.round(status.progress * 100)}%</p>
            ) : null}
            {downloadError ? <p className="export-preview__error">{downloadError}</p> : null}
          </div>
        </div>
      </section>
    </div>
  );
}

function replayFrameAtTime({
  scenario,
  layout,
  eventsByCabin,
  passengerPlan,
  timeSeconds,
}: {
  scenario: Scenario;
  layout: ScenarioLayout;
  eventsByCabin: ReturnType<typeof groupEventsByCabin>;
  passengerPlan: EanPassengerServiceResult["passenger_plan"] | null;
  timeSeconds: number;
}) {
  const passengerState = buildEanPassengerState(scenario, passengerPlan, timeSeconds, EVENT_TOLERANCE_SECONDS);
  const cabins = eanCabinMarkersAtTime(scenario, layout, eventsByCabin, timeSeconds, passengerState.cabinLoadsById);
  return {
    cabins,
    collisions: eanReplayCollisionMarkers(scenario, cabins),
    queues: passengerState.queueMarkers,
  };
}

function physicalArcLabel(segment: TrackSegment) {
  return `${segment.id.replaceAll("_", " ")} (${segment.from_node_id} -> ${segment.to_node_id})`;
}

function toggleId(ids: string[], id: string) {
  return ids.includes(id) ? ids.filter((current) => current !== id) : [...ids, id];
}

function serializeSvgElement(svg: SVGSVGElement) {
  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", svg.getAttribute("width") ?? "1");
  clone.setAttribute("height", svg.getAttribute("height") ?? "1");
  return new XMLSerializer().serializeToString(clone);
}

async function drawSvgToCanvas(svg: SVGSVGElement, canvas: HTMLCanvasElement, context: CanvasRenderingContext2D) {
  const source = serializeSvgElement(svg);
  const blob = new Blob([source], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  try {
    const image = new Image();
    image.decoding = "sync";
    const loaded = new Promise<void>((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () => reject(new Error("Could not rasterize SVG frame"));
    });
    image.src = url;
    await loaded;
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
  } finally {
    URL.revokeObjectURL(url);
  }
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function mediaRecorderMimeType() {
  const candidates = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"];
  return candidates.find((candidate) => MediaRecorder.isTypeSupported(candidate)) ?? "";
}

function frameFilename(scenarioId: string, timeSeconds: number) {
  return `${scenarioId}_ean_replay_${String(Math.round(timeSeconds * 10)).padStart(5, "0")}ds.svg`;
}

function roundFrameTime(timeSeconds: number) {
  return Math.round(timeSeconds * 10) / 10;
}

function clampNumber(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return min;
  return Math.max(min, Math.min(max, value));
}

function nextAnimationFrame() {
  return new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
}

function delay(ms: number) {
  return new Promise<void>((resolve) => window.setTimeout(resolve, ms));
}
