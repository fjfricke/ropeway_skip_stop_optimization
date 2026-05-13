import { Download, Eye, Film, Images, MousePointer2, Pause, Play, Plus, RotateCcw, RotateCw, SkipBack, SkipForward, Tags, Trash2, Users, WholeWord, X } from "lucide-react";
import { zipSync, strToU8 } from "fflate";
import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { flushSync } from "react-dom";
import type { ScenarioLayout } from "../scenarioLayout";
import type { EanPassengerServicePlan, EanPassengerServiceResult, EanPhysicalReplay, Scenario, TrackSegment } from "../types";
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
import type { ReplayCabinMarker, ReplayCollisionMarker, ReplayStationQueueMarker } from "./networkTypes";
import { stationQueuePlacement, stationQueueSize } from "./ReplayLayers";
import { ScenarioExportSelectorSvg } from "./ScenarioExportSelectorSvg";
import { ScenarioExportSvg } from "./ScenarioExportSvg";
import { buildScenarioExportRenderPlan, type ScenarioExportRenderPlan } from "./scenarioExportGeometry";
import { A4_PORTRAIT_300_DPI } from "./scenarioFigureMetrics";
import type { ArcColorMode, ReplayExportConfig, ReplayVideoExportFormat, ScenarioExportBasis, ViewerToggles } from "./viewerTypes";

interface EanReplayExportModalProps {
  scenario: Scenario;
  layout: ScenarioLayout;
  eanReplay: EanPhysicalReplay;
  eanPassengerService: EanPassengerServiceResult | null;
  toggles: ViewerToggles;
  arcColorMode: ArcColorMode;
  initialTimeSeconds: number;
  isVideoExportRunning?: boolean;
  onStartVideoExport: (config: ReplayExportConfig, format: ReplayVideoExportFormat) => void;
  onClose: () => void;
}

type ExportPane = "preview" | "selector";
type ExportStatus = {
  message: string;
  progress: number;
} | null;

const DEFAULT_PERCENTAGE = 100;
export const VIDEO_EXPORT_FPS = 15;
const VIDEO_RESOLUTION_PRESETS = [720, 1080, 1440, 2160] as const;
const DEFAULT_VIDEO_RESOLUTION_HEIGHT = 1080;
const STATION_QUEUE_ROW_HEIGHT = 14;
const STATION_QUEUE_ROW_TOP = 22;

export function EanReplayExportModal({
  scenario,
  layout,
  eanReplay,
  eanPassengerService,
  toggles,
  arcColorMode,
  initialTimeSeconds,
  isVideoExportRunning = false,
  onStartVideoExport,
  onClose,
}: EanReplayExportModalProps) {
  const nodeOptions = useMemo(() => scenario.physical_nodes.map((node) => ({ id: node.id, label: node.id.replaceAll("_", " ") })), [scenario.physical_nodes]);
  const arcOptions = useMemo(() => scenario.track_segments.map((segment) => ({ id: segment.id, label: physicalArcLabel(segment) })), [scenario.track_segments]);
  const timeBounds = useMemo(() => eanReplayTimeBounds(eanReplay), [eanReplay]);
  const initialTime = clampNumber(initialTimeSeconds, timeBounds.min, timeBounds.max);
  const initialStartTime = timeBounds.min;
  const initialEndTime = timeBounds.max;
  const [activePane, setActivePane] = useState<ExportPane>("selector");
  const [selectorTimeSeconds, setSelectorTimeSeconds] = useState(initialTime);
  const [selectorPlaying, setSelectorPlaying] = useState(false);
  const [selectorDirection, setSelectorDirection] = useState<PlaybackDirection>(1);
  const [videoPreviewTimeSeconds, setVideoPreviewTimeSeconds] = useState(initialStartTime);
  const [videoPreviewPlaying, setVideoPreviewPlaying] = useState(false);
  const [framePreviewIndex, setFramePreviewIndex] = useState(0);
  const [sourceFrameTimeSeconds, setSourceFrameTimeSeconds] = useState(initialTime);
  const [sourceConfig, setSourceConfig] = useState<ReplayExportConfig | null>(null);
  const [status, setStatus] = useState<ExportStatus>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [config, setConfig] = useState<ReplayExportConfig>(() => ({
    displayMode: "physical",
    scope: "custom",
    selectedNodeIds: nodeOptions.map((option) => option.id),
    selectedArcIds: arcOptions.map((option) => option.id),
    toggles: { ...toggles },
    arcColorMode,
    basis: "a4_width",
    percentage: DEFAULT_PERCENTAGE,
    exportMode: "video",
    videoResolutionHeight: DEFAULT_VIDEO_RESOLUTION_HEIGHT,
    videoStartSeconds: initialStartTime,
    videoEndSeconds: initialEndTime,
    exportSpeed: 1,
    selectedFrameTimes: [roundFrameTime(initialTime)],
    showCabinFill: true,
  }));
  const previewStageRef = useRef<HTMLDivElement | null>(null);
  const exportSvgRef = useRef<SVGSVGElement | null>(null);
  const [previewCanvasSize, setPreviewCanvasSize] = useState({ width: 0, height: 0 });
  const deferredConfig = useDeferredValue(config);
  const renderConfig = useMemo(() => exportRenderConfig(deferredConfig), [deferredConfig]);
  const sourceExportConfig = sourceConfig ? exportRenderConfig(sourceConfig) : renderConfig;
  const renderPlan = useMemo(() => buildScenarioExportRenderPlan({ scenario, layout, config: renderConfig }), [scenario, layout, renderConfig]);
  const sourceRenderPlan = useMemo(
    () => (sourceConfig ? buildScenarioExportRenderPlan({ scenario, layout, config: sourceExportConfig }) : renderPlan),
    [layout, renderPlan, scenario, sourceConfig, sourceExportConfig],
  );
  const selectedNodeIds = useMemo(() => new Set(config.selectedNodeIds), [config.selectedNodeIds]);
  const selectedArcIds = useMemo(() => new Set(config.selectedArcIds), [config.selectedArcIds]);
  const eventsByCabin = useMemo(() => groupEventsByCabin(eanReplay.events), [eanReplay.events]);
  const passengerPlan = eanPassengerService?.passenger_plan ?? null;
  const videoRange = normalizeRange(config.videoStartSeconds, config.videoEndSeconds);
  const selectorPlaybackSpeed = config.exportMode === "video" ? config.exportSpeed : 1;
  const framePreviewTimes = config.selectedFrameTimes;
  const activeFramePreviewTime = framePreviewTimes[framePreviewIndex] ?? selectorTimeSeconds;
  const previewTimeSeconds = config.exportMode === "video" ? videoPreviewTimeSeconds : activeFramePreviewTime;
  const previewFrame = useMemo(
    () => replayFrameAtTime({ scenario, layout, eventsByCabin, passengerPlan, timeSeconds: previewTimeSeconds }),
    [eventsByCabin, layout, passengerPlan, previewTimeSeconds, scenario],
  );
  const selectorFrame = useMemo(
    () => replayFrameAtTime({ scenario, layout, eventsByCabin, passengerPlan, timeSeconds: selectorTimeSeconds }),
    [eventsByCabin, layout, passengerPlan, scenario, selectorTimeSeconds],
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
    const element = previewStageRef.current;
    if (!element) return undefined;
    const updateSize = () => {
      const rect = element.getBoundingClientRect();
      setPreviewCanvasSize({ width: rect.width, height: rect.height });
    };
    updateSize();
    const observer = new ResizeObserver(updateSize);
    observer.observe(element);
    return () => observer.disconnect();
  }, [activePane, config.exportMode]);

  useEffect(() => {
    if (!selectorPlaying) return undefined;
    let frameId = 0;
    let previousFrameMs: number | null = null;
    const animate = (frameMs: number) => {
      if (previousFrameMs !== null) {
        const elapsedSeconds = (frameMs - previousFrameMs) / 1000;
        setSelectorTimeSeconds((current) => {
          const next = advanceReplayTime(current, elapsedSeconds * selectorPlaybackSpeed * selectorDirection, timeBounds.min, timeBounds.max);
          if (isReplayBoundary(next, selectorDirection, timeBounds.min, timeBounds.max)) setSelectorPlaying(false);
          return next;
        });
      }
      previousFrameMs = frameMs;
      frameId = window.requestAnimationFrame(animate);
    };
    frameId = window.requestAnimationFrame(animate);
    return () => window.cancelAnimationFrame(frameId);
  }, [selectorDirection, selectorPlaybackSpeed, selectorPlaying, timeBounds.max, timeBounds.min]);

  useEffect(() => {
    setFramePreviewIndex((current) => clampInteger(current, 0, Math.max(0, framePreviewTimes.length - 1)));
  }, [framePreviewTimes.length]);

  useEffect(() => {
    setVideoPreviewTimeSeconds((current) => clampNumber(current, videoRange.start, videoRange.end));
  }, [videoRange.end, videoRange.start]);

  useEffect(() => {
    if (!videoPreviewPlaying) return undefined;
    let frameId = 0;
    let previousFrameMs: number | null = null;
    const animate = (frameMs: number) => {
      if (previousFrameMs !== null) {
        const elapsedSeconds = (frameMs - previousFrameMs) / 1000;
        setVideoPreviewTimeSeconds((current) => {
          const next = clampNumber(current + elapsedSeconds * config.exportSpeed, videoRange.start, videoRange.end);
          if (next >= videoRange.end) setVideoPreviewPlaying(false);
          return next;
        });
      }
      previousFrameMs = frameMs;
      frameId = window.requestAnimationFrame(animate);
    };
    frameId = window.requestAnimationFrame(animate);
    return () => window.cancelAnimationFrame(frameId);
  }, [config.exportSpeed, videoPreviewPlaying, videoRange.end, videoRange.start]);

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

  function setVideoRangePoint(kind: "start" | "end") {
    const nextTime = roundFrameTime(selectorTimeSeconds);
    updateConfig((current) => {
      const next =
        kind === "start"
          ? {
              ...current,
              videoStartSeconds: nextTime,
              videoEndSeconds: nextTime > current.videoEndSeconds ? timeBounds.max : current.videoEndSeconds,
            }
          : {
              ...current,
              videoStartSeconds: nextTime < current.videoStartSeconds ? timeBounds.min : current.videoStartSeconds,
              videoEndSeconds: nextTime,
            };
      setVideoPreviewTimeSeconds(next.videoStartSeconds);
      return next;
    });
  }

  function addCurrentFrame() {
    const nextTime = roundFrameTime(selectorTimeSeconds);
    updateConfig((current) => ({
      ...current,
      selectedFrameTimes: [...new Set([...current.selectedFrameTimes, nextTime])].sort((left, right) => left - right),
    }));
    setFramePreviewIndex(config.selectedFrameTimes.filter((time) => time < nextTime).length);
  }

  function removeFrame(timeSeconds: number) {
    updateConfig((current) => ({
      ...current,
      selectedFrameTimes: current.selectedFrameTimes.filter((time) => time !== timeSeconds),
    }));
  }

  function jumpSelectorTo(timeSeconds: number) {
    setSelectorPlaying(false);
    setSelectorTimeSeconds(clampNumber(timeSeconds, timeBounds.min, timeBounds.max));
    setActivePane("selector");
  }

  async function renderSourceSvgAt(timeSeconds: number) {
    flushSync(() => {
      setSourceConfig(config);
      setSourceFrameTimeSeconds(timeSeconds);
    });
    await nextAnimationFrame();
    if (!exportSvgRef.current) throw new Error("Export SVG unavailable");
    return exportSvgRef.current;
  }

  async function handleDownload(format: ReplayVideoExportFormat = "webm") {
    setDownloadError(null);
    try {
      if (config.exportMode === "frames") {
        await downloadFrameZip();
      } else {
        if (isVideoExportRunning) return;
        onStartVideoExport(config, format);
        onClose();
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

  const canDownload = config.exportMode === "video" || config.selectedFrameTimes.length > 0;
  const canStartVideoDownload = config.exportMode === "video" && canDownload && status === null && !isVideoExportRunning;

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
                <div className="export-section__header">
                  <h3>Video Range</h3>
                  {activePane === "selector" ? (
                    <div className="export-section__actions">
                      <button type="button" onClick={() => setVideoRangePoint("start")}>Set Start</button>
                      <button type="button" onClick={() => setVideoRangePoint("end")}>Set End</button>
                    </div>
                  ) : null}
                </div>
                <div className="replay-export-range-list">
                  <button type="button" onClick={() => jumpSelectorTo(config.videoStartSeconds)}>
                    <span>Start</span>
                    <strong>{formatSeconds(config.videoStartSeconds)}</strong>
                    <em>{clockLabel(scenario.service_start_time, config.videoStartSeconds)}</em>
                  </button>
                  <button type="button" onClick={() => jumpSelectorTo(config.videoEndSeconds)}>
                    <span>End</span>
                    <strong>{formatSeconds(config.videoEndSeconds)}</strong>
                    <em>{clockLabel(scenario.service_start_time, config.videoEndSeconds)}</em>
                  </button>
                </div>
                <div className="replay-export-speed-control">
                  <span>Speed</span>
                  <div className="export-toggle-grid">
                    {SPEED_OPTIONS.map((speed) => (
                      <button
                        key={speed}
                        type="button"
                        className={config.exportSpeed === speed ? "is-active" : ""}
                        onClick={() => updateConfig((current) => ({ ...current, exportSpeed: speed }))}
                      >
                        {speed}x
                      </button>
                    ))}
                  </div>
                </div>
              </section>
            ) : (
              <section className="export-section">
                <div className="export-section__header">
                  <h3>Frames</h3>
                  <div className="export-section__actions">
                    {activePane === "selector" ? (
                      <button type="button" onClick={addCurrentFrame}>
                        <Plus size={14} />
                        Add
                      </button>
                    ) : null}
                    <button type="button" onClick={() => updateConfig((current) => ({ ...current, selectedFrameTimes: [] }))}>
                      None
                    </button>
                  </div>
                </div>
                <div className="replay-export-frame-list">
                  {config.selectedFrameTimes.length === 0 ? (
                    <p>No frames selected</p>
                  ) : config.selectedFrameTimes.map((timeSeconds, index) => (
                    <button type="button" key={timeSeconds} className={index === framePreviewIndex ? "is-active" : ""} onClick={() => setFramePreviewIndex(index)}>
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

            {config.exportMode === "video" ? (
              <section className="export-section">
                <h3>Resolution</h3>
                <div className="export-toggle-grid replay-export-resolution-grid">
                  {VIDEO_RESOLUTION_PRESETS.map((height) => (
                    <button
                      key={height}
                      type="button"
                      className={config.videoResolutionHeight === height ? "is-active" : ""}
                      onClick={() => updateConfig((current) => ({ ...current, videoResolutionHeight: height }))}
                    >
                      {height}p
                    </button>
                  ))}
                </div>
              </section>
            ) : (
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
            )}
          </div>

          <div className="export-modal__preview">
            <div className="export-preview__header">
              <div>
                <h3>{activePane === "preview" ? "Preview" : "Selector"}</h3>
                <p>{renderPlan.outputWidth} x {renderPlan.outputHeight}px</p>
              </div>
              <div className="export-preview__actions">
                <div className="export-pane-tabs" aria-label="Export panel">
                  <button type="button" className={activePane === "selector" ? "is-active" : ""} onClick={() => setActivePane("selector")}>
                    <MousePointer2 size={16} />
                    Selector
                  </button>
                  <button type="button" className={activePane === "preview" ? "is-active" : ""} onClick={() => setActivePane("preview")}>
                    <Eye size={16} />
                    Preview
                  </button>
                </div>
                {config.exportMode === "video" ? (
                  <div className="export-download-actions">
                    <button type="button" onClick={() => handleDownload("webm")} disabled={!canStartVideoDownload}>
                      <Download size={16} />
                      Download WebM
                    </button>
                    <button type="button" onClick={() => handleDownload("mp4")} disabled={!canStartVideoDownload}>
                      <Download size={16} />
                      Download MP4
                    </button>
                  </div>
                ) : (
                  <button type="button" onClick={() => handleDownload()} disabled={!canDownload || status !== null}>
                    <Download size={16} />
                    Download SVG ZIP
                  </button>
                )}
              </div>
            </div>

            {activePane === "preview" ? (
              <div className="export-preview__canvas export-preview__canvas--with-controls">
                {config.exportMode === "video" ? (
                  <VideoPreviewControls
                    timeSeconds={videoPreviewTimeSeconds}
                    startSeconds={videoRange.start}
                    endSeconds={videoRange.end}
                    exportSpeed={config.exportSpeed}
                    isPlaying={videoPreviewPlaying}
                    onPlayToggle={() => {
                      if (videoPreviewTimeSeconds >= videoRange.end) setVideoPreviewTimeSeconds(videoRange.start);
                      setVideoPreviewPlaying((current) => !current);
                    }}
                    onTimeChange={(timeSeconds) => {
                      setVideoPreviewPlaying(false);
                      setVideoPreviewTimeSeconds(timeSeconds);
                    }}
                  />
                ) : (
                  <FramePreviewControls
                    frameTimes={framePreviewTimes}
                    framePreviewIndex={framePreviewIndex}
                    serviceStartTime={scenario.service_start_time}
                    onPrevious={() => setFramePreviewIndex((current) => clampInteger(current - 1, 0, Math.max(0, framePreviewTimes.length - 1)))}
                    onNext={() => setFramePreviewIndex((current) => clampInteger(current + 1, 0, Math.max(0, framePreviewTimes.length - 1)))}
                  />
                )}
                <div className="export-preview__stage" ref={previewStageRef}>
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
                      config={renderConfig}
                      renderPlan={renderPlan}
                      replayCabins={previewFrame.cabins}
                      replayCollisionMarkers={previewFrame.collisions}
                      replayStationQueues={previewFrame.queues}
                      showCabinFill={config.showCabinFill}
                    />
                  </div>
                </div>
              </div>
            ) : (
              <div className="export-preview__canvas export-preview__canvas--selector">
                <div className="replay-export-selector-playback">
                  <ReplayExportPlaybackControls
                    timeSeconds={selectorTimeSeconds}
                    minSeconds={timeBounds.min}
                    maxSeconds={timeBounds.max}
                    serviceStartTime={scenario.service_start_time}
                    isPlaying={selectorPlaying}
                    playbackDirection={selectorDirection}
                    onPrevious={() => {
                      setSelectorPlaying(false);
                      setSelectorTimeSeconds((current) => Math.max(timeBounds.min, current - MANUAL_STEP_SECONDS));
                    }}
                    onPlayToggle={() => {
                      if (selectorPlaying) {
                        setSelectorPlaying(false);
                        return;
                      }
                      setSelectorTimeSeconds((current) => replayStartTimeForDirection(current, selectorDirection, timeBounds.min, timeBounds.max));
                      setSelectorPlaying(true);
                    }}
                    onNext={() => {
                      setSelectorPlaying(false);
                      setSelectorTimeSeconds((current) => Math.min(timeBounds.max, current + MANUAL_STEP_SECONDS));
                    }}
                    onDirectionToggle={() => setSelectorDirection((current) => (current === 1 ? -1 : 1))}
                    onTimeChange={(timeSeconds) => {
                      setSelectorPlaying(false);
                      setSelectorTimeSeconds(timeSeconds);
                    }}
                  />
                </div>
                <ScenarioExportSelectorSvg
                  scenario={scenario}
                  layout={layout}
                  config={config}
                  selectedNodeIds={selectedNodeIds}
                  selectedArcIds={selectedArcIds}
                  replayCabins={selectorFrame.cabins}
                  replayCollisionMarkers={selectorFrame.collisions}
                  replayStationQueues={selectorFrame.queues}
                  showCabinFill={config.showCabinFill}
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
                config={sourceExportConfig}
                renderPlan={sourceRenderPlan}
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

function ReplayExportPlaybackControls({
  timeSeconds,
  minSeconds,
  maxSeconds,
  serviceStartTime,
  isPlaying,
  playbackDirection,
  onPrevious,
  onPlayToggle,
  onNext,
  onDirectionToggle,
  onTimeChange,
}: {
  timeSeconds: number;
  minSeconds: number;
  maxSeconds: number;
  serviceStartTime: string;
  isPlaying: boolean;
  playbackDirection: PlaybackDirection;
  onPrevious: () => void;
  onPlayToggle: () => void;
  onNext: () => void;
  onDirectionToggle: () => void;
  onTimeChange: (timeSeconds: number) => void;
}) {
  return (
    <div className="replay-export-playback">
      <div className="replay-buttons">
        <button type="button" onClick={onPrevious} aria-label="Previous time">
          <SkipBack size={16} />
        </button>
        <button type="button" className="replay-play" onClick={onPlayToggle}>
          {isPlaying ? <Pause size={16} /> : <Play size={16} />}
          {isPlaying ? "Pause" : "Play"}
        </button>
        <button type="button" onClick={onNext} aria-label="Next time">
          <SkipForward size={16} />
        </button>
        <button
          type="button"
          className="replay-direction"
          onClick={onDirectionToggle}
          aria-label={playbackDirection === 1 ? "Playback direction forward" : "Playback direction backward"}
          title={playbackDirection === 1 ? "Forward playback" : "Backward playback"}
        >
          {playbackDirection === 1 ? <RotateCw size={17} /> : <RotateCcw size={17} />}
        </button>
      </div>
      <input
        aria-label="EAN export selector time"
        className="replay-slider"
        type="range"
        min={minSeconds}
        max={maxSeconds}
        step="0.1"
        value={timeSeconds}
        onChange={(event) => onTimeChange(Number(event.target.value))}
      />
      <div className="replay-time">
        <strong>{formatSeconds(timeSeconds)}</strong>
        <span>{clockLabelFixedTenths(serviceStartTime, timeSeconds)}</span>
      </div>
    </div>
  );
}

function VideoPreviewControls({
  timeSeconds,
  startSeconds,
  endSeconds,
  exportSpeed,
  isPlaying,
  onPlayToggle,
  onTimeChange,
}: {
  timeSeconds: number;
  startSeconds: number;
  endSeconds: number;
  exportSpeed: number;
  isPlaying: boolean;
  onPlayToggle: () => void;
  onTimeChange: (timeSeconds: number) => void;
}) {
  const safeSpeed = Math.max(0.1, exportSpeed);
  const playbackDurationSeconds = Math.max(0, (endSeconds - startSeconds) / safeSpeed);
  const playbackTimeSeconds = clampNumber((timeSeconds - startSeconds) / safeSpeed, 0, playbackDurationSeconds);
  return (
    <div className="replay-export-preview-controls">
      <button type="button" className="is-active" onClick={onPlayToggle}>
        {isPlaying ? <Pause size={15} /> : <Play size={15} />}
        {isPlaying ? "Pause" : "Play"}
      </button>
      <input
        aria-label="EAN replay export video preview time"
        type="range"
        min={0}
        max={playbackDurationSeconds}
        step="0.1"
        value={playbackTimeSeconds}
        onChange={(event) => onTimeChange(startSeconds + Number(event.target.value) * safeSpeed)}
      />
      <strong>{formatSeconds(playbackTimeSeconds)}</strong>
      <span>/ {formatSeconds(playbackDurationSeconds)}</span>
    </div>
  );
}

function FramePreviewControls({
  frameTimes,
  framePreviewIndex,
  serviceStartTime,
  onPrevious,
  onNext,
}: {
  frameTimes: number[];
  framePreviewIndex: number;
  serviceStartTime: string;
  onPrevious: () => void;
  onNext: () => void;
}) {
  const activeTime = frameTimes[framePreviewIndex];
  return (
    <div className="replay-export-preview-controls">
      <button type="button" onClick={onPrevious} disabled={framePreviewIndex <= 0}>
        <SkipBack size={15} />
      </button>
      <strong>{frameTimes.length === 0 ? "No frame" : `${framePreviewIndex + 1} / ${frameTimes.length}`}</strong>
      <button type="button" onClick={onNext} disabled={framePreviewIndex >= frameTimes.length - 1}>
        <SkipForward size={15} />
      </button>
      {activeTime !== undefined ? (
        <>
          <span>{formatSeconds(activeTime)}</span>
          <span>{clockLabel(serviceStartTime, activeTime)}</span>
        </>
      ) : null}
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
  passengerPlan: EanPassengerServicePlan | null;
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

export type ReplayVideoFrame = {
  cabins: ReplayCabinMarker[];
  collisions: ReplayCollisionMarker[];
  queues: ReplayStationQueueMarker[];
};

type ReplayVideoPassengerEvent = {
  timeSeconds: number;
  order: number;
  kind: "release" | "board" | "alight";
  groupId: string;
  cabinId?: number;
  destination: string;
  count: number;
};

type ReplayVideoDemandGroup = {
  origin: string;
  destination: string;
  count: number;
};

export function createReplayVideoFrameBuilder({
  scenario,
  layout,
  eventsByCabin,
  passengerPlan,
}: {
  scenario: Scenario;
  layout: ScenarioLayout;
  eventsByCabin: ReturnType<typeof groupEventsByCabin>;
  passengerPlan: EanPassengerServicePlan | null;
}) {
  const passengerTimeline = createPassengerTimeline(scenario, passengerPlan);
  return {
    frameAt(timeSeconds: number): ReplayVideoFrame {
      const passengerState = passengerTimeline.advanceTo(timeSeconds);
      const cabins = eanCabinMarkersAtTime(scenario, layout, eventsByCabin, timeSeconds, passengerState.cabinLoadsById);
      return {
        cabins,
        collisions: eanReplayCollisionMarkers(scenario, cabins),
        queues: passengerState.queueMarkers,
      };
    },
  };
}

function createPassengerTimeline(scenario: Scenario, passengerPlan: EanPassengerServicePlan | null) {
  if (!passengerPlan) {
    return {
      advanceTo() {
        return { cabinLoadsById: new Map<number, { loadCount: number; destinationLoads: { destination: string; count: number }[] }>(), queueMarkers: [] };
      },
    };
  }

  const demandByGroupId = new Map<string, ReplayVideoDemandGroup>();
  for (let index = 0; index < scenario.demands.length; index += 1) {
    const demand = scenario.demands[index];
    demandByGroupId.set(`demand::${index}`, {
      origin: demand.origin,
      destination: demand.destination,
      count: demand.count,
    });
  }

  const events: ReplayVideoPassengerEvent[] = [];
  for (let index = 0; index < scenario.demands.length; index += 1) {
    const demand = scenario.demands[index];
    events.push({
      timeSeconds: releaseSeconds(scenario.service_start_time, demand.arrival_time),
      order: 0,
      kind: "release",
      groupId: `demand::${index}`,
      destination: demand.destination,
      count: demand.count,
    });
  }

  for (const ride of passengerPlan?.served_rides ?? []) {
    const demand = demandByGroupId.get(ride.demand_group_id);
    if (!demand) continue;
    events.push({
      timeSeconds: ride.boarding_time_seconds,
      order: 1,
      kind: "board",
      groupId: ride.demand_group_id,
      cabinId: ride.cabin_id,
      destination: demand.destination,
      count: ride.count,
    });
    events.push({
      timeSeconds: ride.alighting_time_seconds,
      order: 2,
      kind: "alight",
      groupId: ride.demand_group_id,
      cabinId: ride.cabin_id,
      destination: demand.destination,
      count: ride.count,
    });
  }

  events.sort((left, right) => left.timeSeconds - right.timeSeconds || left.order - right.order);

  const waitingByGroupId = new Map<string, number>();
  const loadsByCabinId = new Map<number, Map<string, number>>();
  let eventIndex = 0;

  function applyEvent(event: ReplayVideoPassengerEvent) {
    if (event.kind === "release") {
      waitingByGroupId.set(event.groupId, (waitingByGroupId.get(event.groupId) ?? 0) + event.count);
      return;
    }
    if (event.kind === "board") {
      waitingByGroupId.set(event.groupId, Math.max(0, (waitingByGroupId.get(event.groupId) ?? 0) - event.count));
      if (event.cabinId === undefined) return;
      const load = loadsByCabinId.get(event.cabinId) ?? new Map<string, number>();
      load.set(event.destination, (load.get(event.destination) ?? 0) + event.count);
      loadsByCabinId.set(event.cabinId, load);
      return;
    }
    if (event.cabinId === undefined) return;
    const load = loadsByCabinId.get(event.cabinId);
    if (!load) return;
    const nextCount = Math.max(0, (load.get(event.destination) ?? 0) - event.count);
    if (nextCount > 0) {
      load.set(event.destination, nextCount);
    } else {
      load.delete(event.destination);
    }
    if (load.size === 0) loadsByCabinId.delete(event.cabinId);
  }

  return {
    advanceTo(timeSeconds: number) {
      while (eventIndex < events.length && events[eventIndex].timeSeconds <= timeSeconds) {
        applyEvent(events[eventIndex]);
        eventIndex += 1;
      }
      return snapshotPassengerState(demandByGroupId, waitingByGroupId, loadsByCabinId);
    },
  };
}

function snapshotPassengerState(
  demandByGroupId: Map<string, ReplayVideoDemandGroup>,
  waitingByGroupId: Map<string, number>,
  loadsByCabinId: Map<number, Map<string, number>>,
) {
  const cabinLoadsById = new Map<number, { loadCount: number; destinationLoads: { destination: string; count: number }[] }>();
  for (const [cabinId, destinationMap] of loadsByCabinId.entries()) {
    const destinationLoads = [...destinationMap.entries()]
      .filter(([, count]) => count > 0)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([destination, count]) => ({ destination, count }));
    if (destinationLoads.length === 0) continue;
    cabinLoadsById.set(cabinId, {
      loadCount: destinationLoads.reduce((sum, load) => sum + load.count, 0),
      destinationLoads,
    });
  }

  const queuesByStation = new Map<string, ReplayStationQueueMarker>();
  for (const [groupId, waiting] of waitingByGroupId.entries()) {
    if (waiting <= 0) continue;
    const demand = demandByGroupId.get(groupId);
    if (!demand) continue;
    const queue = queuesByStation.get(demand.origin) ?? {
      stationId: demand.origin,
      totalCount: 0,
      destinationQueues: [],
    };
    queue.totalCount += waiting;
    queue.destinationQueues.push({ destination: demand.destination, count: waiting });
    queuesByStation.set(demand.origin, queue);
  }

  const queueMarkers = [...queuesByStation.values()]
    .map((queue) => ({
      ...queue,
      destinationQueues: queue.destinationQueues.sort((left, right) => left.destination.localeCompare(right.destination)),
    }))
    .sort((left, right) => left.stationId.localeCompare(right.stationId));

  return { cabinLoadsById, queueMarkers };
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
  const image = await loadSvgImage(svg);
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
}

export async function loadSvgImage(svg: SVGSVGElement) {
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
    return image;
  } finally {
    URL.revokeObjectURL(url);
  }
}

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
};

export function createReplayVideoSpriteCache(canvas: HTMLCanvasElement, renderPlan: ScenarioExportRenderPlan, showCabinFill: boolean): ReplayVideoSpriteCache {
  return {
    cabinSprites: new Map(),
    queueSprites: new Map(),
    renderPlan,
    scale: exportScaleToCanvas(canvas, renderPlan),
    showCabinFill,
  };
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
  drawReplayCabinShape(context, cabin, radius, cache.renderPlan, cache.scale, cache.showCabinFill);
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
    drawCabinPieSlices(context, cabin.destinationLoads ?? [], capacity, innerRadius);
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
  queues: ReplayStationQueueMarker[],
  renderPlan: ScenarioExportRenderPlan,
  spriteCache: ReplayVideoSpriteCache,
  scenario: Scenario,
  layout: ScenarioLayout,
) {
  if (queues.length === 0) return;
  const maxQueue = Math.max(1, ...queues.map((queue) => queue.totalCount));
  for (const queue of queues) {
    const localSize = stationQueueSize(queue, maxQueue);
    const placement = stationQueuePlacement(queue.stationId, scenario, layout, renderPlan.viewBox, localSize, renderPlan.metrics.shapeScale);
    if (!placement) continue;
    const point = exportPointToCanvas(placement.x, placement.y, canvas, renderPlan);
    const sprite = replayQueueSprite(spriteCache, queue, maxQueue);
    context.drawImage(sprite.source, point.x - sprite.offsetX, point.y - sprite.offsetY);
  }
}

function replayQueueSprite(cache: ReplayVideoSpriteCache, queue: ReplayStationQueueMarker, maxQueue: number): ReplayVideoSprite {
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
    context.fillStyle = destinationColor(item.destination);
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

function drawCabinPieSlices(context: CanvasRenderingContext2D, destinationLoads: { destination: string; count: number }[], capacity: number, radius: number) {
  let cursor = -Math.PI / 2;
  for (const item of destinationLoads) {
    if (item.count <= 0) continue;
    const sliceRadians = Math.min(Math.PI * 2, (item.count / capacity) * Math.PI * 2);
    const end = cursor + sliceRadians;
    context.beginPath();
    context.moveTo(0, 0);
    context.arc(0, 0, radius, cursor, end);
    context.closePath();
    context.fillStyle = destinationColor(item.destination);
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

function destinationColor(destination: string) {
  const key = destination.toLowerCase();
  if (key === "l") return "#285aa8";
  if (key === "m") return "#1c8c74";
  if (key === "r") return "#d97925";
  const palette = ["#285aa8", "#1c8c74", "#d97925", "#7b5fc9", "#c6476b", "#607d2f"];
  let hash = 0;
  for (const char of key) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return palette[hash % palette.length];
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function frameFilename(scenarioId: string, timeSeconds: number) {
  return `${scenarioId}_ean_replay_${String(Math.round(timeSeconds * 10)).padStart(5, "0")}ds.svg`;
}

function releaseSeconds(serviceStartTime: string, arrivalTime: string) {
  return timeOfDaySeconds(arrivalTime) - timeOfDaySeconds(serviceStartTime);
}

function timeOfDaySeconds(value: string) {
  const [hours = 0, minutes = 0, seconds = 0] = value.split(":").map(Number);
  return hours * 3600 + minutes * 60 + seconds;
}

export function exportRenderConfig(config: ReplayExportConfig): ReplayExportConfig {
  if (config.exportMode !== "video") return config;
  return {
    ...config,
    basis: "a4_height",
    percentage: (config.videoResolutionHeight / A4_PORTRAIT_300_DPI.height) * 100,
  };
}

export function normalizeRange(left: number, right: number) {
  return {
    start: Math.min(left, right),
    end: Math.max(left, right),
  };
}

function roundFrameTime(timeSeconds: number) {
  return Math.round(timeSeconds * 10) / 10;
}

function replayStartTimeForDirection(timeSeconds: number, direction: PlaybackDirection, min: number, max: number) {
  if (direction === 1 && timeSeconds >= max) return min;
  if (direction === -1 && timeSeconds <= min) return max;
  return timeSeconds;
}

function clockLabelFixedTenths(startTime: string, secondsAfterStart: number) {
  const label = clockLabel(startTime, secondsAfterStart);
  return label.includes(".") ? label : `${label}.0`;
}

function clampInteger(value: number, min: number, max: number) {
  return Math.round(clampNumber(value, min, max));
}

function clampNumber(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return min;
  return Math.max(min, Math.min(max, value));
}

export function nextAnimationFrame() {
  return new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
}
