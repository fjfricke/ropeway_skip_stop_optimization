import { Download, Film, Images, Pause, Play, Plus, RotateCcw, RotateCw, SkipBack, SkipForward, Tags, Trash2, Users, WholeWord, X } from "lucide-react";
import { zipSync, strToU8 } from "fflate";
import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { flushSync } from "react-dom";
import type { ScenarioLayout } from "../scenarioLayout";
import type { EanPassengerServiceResult, EanPhysicalReplay, Scenario } from "../types";
import {
  advanceReplayTime,
  clockLabel,
  eanReplayTimeBounds,
  formatSeconds,
  groupEventsByCabin,
  isReplayBoundary,
  MANUAL_STEP_SECONDS,
  SPEED_OPTIONS,
  type PlaybackDirection,
} from "./EanReplayView";
import { ExportItemActions } from "./export/ExportItemActions";
import { ExportPaneTabs, type ExportPane } from "./export/ExportPaneTabs";
import { downloadBlob, serializeSvgElement, nextAnimationFrame } from "./export/exportDom";
import { exportArcOptions, exportNodeOptions, toggleId } from "./export/exportSelection";
import { computeArtboardSize, DEFAULT_EXPORT_PERCENTAGE, clampNumber } from "./export/exportSizing";
import { ExportSizeControls } from "./export/ExportSizeControls";
import type { ReplayExportConfig, ReplayVideoExportFormat } from "./export/exportTypes";
import {
  DEFAULT_VIDEO_RESOLUTION_HEIGHT,
  exportRenderConfig,
  normalizeRange,
  replayStartTimeForDirection,
  roundFrameTime,
  VIDEO_RESOLUTION_PRESETS,
} from "./eanReplayExport/replayExportConfig";
import { replayFrameAtTime } from "./eanReplayExport/replayFrameModel";
import { useElementSize } from "./hooks/useElementSize";
import { ScenarioExportSelectorSvg } from "./ScenarioExportSelectorSvg";
import { ScenarioExportSvg } from "./ScenarioExportSvg";
import { buildScenarioExportRenderPlan } from "./scenarioExportGeometry";
import type { ArcColorMode, ViewerToggles } from "./viewerTypes";

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

type ExportStatus = {
  message: string;
  progress: number;
} | null;

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
  const nodeOptions = useMemo(() => exportNodeOptions(scenario, "physical"), [scenario]);
  const arcOptions = useMemo(() => exportArcOptions(scenario, "physical"), [scenario]);
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
    selectedNodeIds: nodeOptions.map((option) => option.id),
    selectedArcIds: arcOptions.map((option) => option.id),
    toggles: { ...toggles },
    arcColorMode,
    basis: "a4_width",
    percentage: DEFAULT_EXPORT_PERCENTAGE,
    exportMode: "video",
    videoResolutionHeight: DEFAULT_VIDEO_RESOLUTION_HEIGHT,
    videoStartSeconds: initialStartTime,
    videoEndSeconds: initialEndTime,
    exportSpeed: 1,
    selectedFrameTimes: [roundFrameTime(initialTime)],
    showCabinFill: true,
  }));
  const exportSvgRef = useRef<SVGSVGElement | null>(null);
  const [previewStageRef, previewCanvasSize] = useElementSize<HTMLDivElement>([activePane, config.exportMode]);
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
    return computeArtboardSize(previewCanvasSize, renderPlan.outputWidth, renderPlan.outputHeight);
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

            <ExportItemActions
              selectedNodeCount={selectedNodeIds.size}
              selectedArcCount={selectedArcIds.size}
              nodeLabel="nodes"
              arcLabel="arcs"
              onSelectAll={selectAllCustomItems}
              onClear={clearCustomItems}
            />

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
              <ExportSizeControls
                basis={config.basis}
                percentage={config.percentage}
                onBasisChange={(basis) => updateConfig((current) => ({ ...current, basis }))}
                onPercentageChange={(percentage) => updateConfig((current) => ({ ...current, percentage }))}
              />
            )}
          </div>

          <div className="export-modal__preview">
            <div className="export-preview__header">
              <div>
                <h3>{activePane === "preview" ? "Preview" : "Selector"}</h3>
                <p>{renderPlan.outputWidth} x {renderPlan.outputHeight}px</p>
              </div>
              <div className="export-preview__actions">
                <ExportPaneTabs activePane={activePane} onPaneChange={setActivePane} />
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

function frameFilename(scenarioId: string, timeSeconds: number) {
  return `${scenarioId}_ean_replay_${String(Math.round(timeSeconds * 10)).padStart(5, "0")}ds.svg`;
}

function clockLabelFixedTenths(startTime: string, secondsAfterStart: number) {
  const label = clockLabel(startTime, secondsAfterStart);
  return label.includes(".") ? label : `${label}.0`;
}

function clampInteger(value: number, min: number, max: number) {
  return Math.round(clampNumber(value, min, max));
}
