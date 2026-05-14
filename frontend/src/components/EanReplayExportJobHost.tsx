import { useEffect, useMemo, useRef, useState } from "react";
import type { RefObject } from "react";
import type { ScenarioLayout } from "../scenarioLayout";
import type { EanPassengerServiceResult, EanPhysicalReplay, Scenario } from "../types";
import { groupEventsByCabin } from "./EanReplayView";
import { downloadBlob, loadSvgImage, nextAnimationFrame } from "./export/exportDom";
import type { ReplayExportConfig, ReplayVideoExportFormat } from "./export/exportTypes";
import { exportRenderConfig, normalizeRange, VIDEO_EXPORT_FPS } from "./eanReplayExport/replayExportConfig";
import { createReplayVideoFrameBuilder } from "./eanReplayExport/replayFrameModel";
import { createReplayVideoSpriteCache, drawReplayVideoFrame } from "./eanReplayExport/replayVideoCanvas";
import { ScenarioExportSvg } from "./ScenarioExportSvg";
import { buildScenarioExportRenderPlan } from "./scenarioExportGeometry";

export type EanReplayVideoExportJob = {
  id: number;
  scenario: Scenario;
  layout: ScenarioLayout;
  eanReplay: EanPhysicalReplay;
  eanPassengerService: EanPassengerServiceResult | null;
  config: ReplayExportConfig;
  format: ReplayVideoExportFormat;
};

type ExportJobStatus =
  | { state: "preparing"; message: string; progress: number }
  | { state: "rendering"; message: string; progress: number }
  | { state: "complete"; message: string; progress: number }
  | { state: "cancelled"; message: string; progress: number }
  | { state: "error"; message: string; progress: number };

type RunToken = {
  cancelled: boolean;
};

export function EanReplayExportJobHost({
  job,
  onDismiss,
}: {
  job: EanReplayVideoExportJob | null;
  onDismiss: (jobId: number) => void;
}) {
  const staticExportSvgRef = useRef<SVGSVGElement | null>(null);
  const runTokenRef = useRef<RunToken | null>(null);
  const [status, setStatus] = useState<ExportJobStatus | null>(null);
  const renderConfig = useMemo(() => (job ? exportRenderConfig(job.config) : null), [job]);
  const renderPlan = useMemo(
    () => (job && renderConfig ? buildScenarioExportRenderPlan({ scenario: job.scenario, layout: job.layout, config: renderConfig }) : null),
    [job, renderConfig],
  );

  useEffect(() => {
    if (!job || !renderConfig || !renderPlan) {
      setStatus(null);
      return undefined;
    }

    const token: RunToken = { cancelled: false };
    runTokenRef.current = token;
    setStatus({ state: "preparing", message: `Preparing EAN replay ${job.format.toUpperCase()}`, progress: 0 });

    runVideoExport(job, renderConfig, renderPlan, staticExportSvgRef, token, setStatus)
      .then(() => {
        if (token.cancelled) return;
        setStatus({ state: "complete", message: "Video downloaded", progress: 1 });
        window.setTimeout(() => {
          if (runTokenRef.current === token) onDismiss(job.id);
        }, 2600);
      })
      .catch((error) => {
        if (token.cancelled) return;
        setStatus({
          state: "error",
          message: error instanceof Error ? error.message : "Video export failed",
          progress: 1,
        });
      });

    return () => {
      token.cancelled = true;
    };
  }, [job, onDismiss, renderConfig, renderPlan]);

  if (!job || !renderConfig || !renderPlan) return null;

  const canCancel = status?.state === "preparing" || status?.state === "rendering";
  const cancelJob = () => {
    if (!status) return;
    if (runTokenRef.current) runTokenRef.current.cancelled = true;
    setStatus({ state: "cancelled", message: "Export cancelled", progress: status.progress });
    window.setTimeout(() => onDismiss(job.id), 1200);
  };
  return (
    <>
      <div className="export-download-source" aria-hidden="true">
        <ScenarioExportSvg
          ref={staticExportSvgRef}
          scenario={job.scenario}
          layout={job.layout}
          config={renderConfig}
          renderPlan={renderPlan}
          showCabinFill={job.config.showCabinFill}
        />
      </div>
      {status ? (
        <aside className={`export-job-toast export-job-toast--${status.state}`} aria-live="polite">
          <div className="export-job-toast__header">
            <div>
              <strong>EAN replay {job.format.toUpperCase()} export</strong>
              <span>{status.message}</span>
            </div>
          </div>
          <div className="export-job-toast__progress" aria-hidden="true">
            <span style={{ width: `${Math.round(status.progress * 100)}%` }} />
          </div>
          <div className="export-job-toast__footer">
            <span>{Math.round(status.progress * 100)}%</span>
            {canCancel ? <button type="button" onClick={cancelJob}>Cancel</button> : null}
          </div>
        </aside>
      ) : null}
    </>
  );
}

async function runVideoExport(
  job: EanReplayVideoExportJob,
  renderConfig: ReplayExportConfig,
  renderPlan: NonNullable<ReturnType<typeof buildScenarioExportRenderPlan>>,
  staticExportSvgRef: RefObject<SVGSVGElement | null>,
  token: RunToken,
  setStatus: (status: ExportJobStatus) => void,
) {
  const videoRange = normalizeRange(job.config.videoStartSeconds, job.config.videoEndSeconds);
  const modelDurationSeconds = Math.max(0.1, videoRange.end - videoRange.start);
  const videoDurationSeconds = Math.max(0.1, modelDurationSeconds / Math.max(0.1, job.config.exportSpeed));
  const frameCount = Math.max(2, Math.ceil(videoDurationSeconds * VIDEO_EXPORT_FPS));
  const eventsByCabin = groupEventsByCabin(job.eanReplay.events);
  const passengerPlan = job.eanPassengerService?.passenger_plan ?? null;
  const videoFrameBuilder = createReplayVideoFrameBuilder({
    scenario: job.scenario,
    layout: job.layout,
    eventsByCabin,
    passengerPlan,
  });

  await nextAnimationFrame();
  if (token.cancelled) return;
  const staticSvg = staticExportSvgRef.current;
  if (!staticSvg) throw new Error("Static export SVG unavailable");

  setStatus({ state: "preparing", message: "Preparing video layers", progress: 0 });
  const staticImage = await loadSvgImage(staticSvg);
  if (token.cancelled) return;

  const canvas = document.createElement("canvas");
  canvas.width = Number(staticSvg.getAttribute("width")) || renderPlan.outputWidth;
  canvas.height = Number(staticSvg.getAttribute("height")) || renderPlan.outputHeight;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Canvas export unavailable");
  const spriteCache = createReplayVideoSpriteCache(canvas, renderPlan, job.config.showCabinFill, job.scenario.stations);

  const { BufferTarget, CanvasSource, getFirstEncodableVideoCodec, Mp4OutputFormat, Output, QUALITY_HIGH, WebMOutputFormat } = await import("mediabunny");
  const codecCandidates = job.format === "mp4" ? ["avc"] as const : ["vp8", "vp9"] as const;
  const codec = await getFirstEncodableVideoCodec([...codecCandidates], {
    width: canvas.width,
    height: canvas.height,
    bitrate: QUALITY_HIGH,
  });
  if (!codec) throw new Error(`WebCodecs ${job.format.toUpperCase()} encoding is not supported by this browser`);
  if (token.cancelled) return;

  const target = new BufferTarget();
  const output = new Output({
    format: job.format === "mp4" ? new Mp4OutputFormat({ fastStart: "in-memory" }) : new WebMOutputFormat(),
    target,
  });
  const videoSource = new CanvasSource(canvas, {
    codec,
    bitrate: QUALITY_HIGH,
    keyFrameInterval: 2,
    alpha: "discard",
    latencyMode: "quality",
  });
  output.addVideoTrack(videoSource, {
    frameRate: VIDEO_EXPORT_FPS,
    maximumPacketCount: frameCount,
  });
  await output.start();

  const frameDurationSeconds = 1 / VIDEO_EXPORT_FPS;
  const statusStride = Math.max(1, Math.floor(frameCount / 120));
  try {
    for (let index = 0; index < frameCount; index += 1) {
      if (token.cancelled) return;
      const ratio = frameCount === 1 ? 0 : index / (frameCount - 1);
      const timeSeconds = videoRange.start + ratio * (videoRange.end - videoRange.start);
      const frame = videoFrameBuilder.frameAt(timeSeconds);
      if (index === 0 || index === frameCount - 1 || index % statusStride === 0) {
        setStatus({
          state: "rendering",
          message: `Rendering video frame ${index + 1} / ${frameCount}`,
          progress: index / frameCount,
        });
      }
      drawReplayVideoFrame(context, canvas, staticImage, frame, renderPlan, spriteCache, job.config.toggles.demand, job.scenario, job.layout);
      await videoSource.add(index * frameDurationSeconds, frameDurationSeconds, { keyFrame: index % (VIDEO_EXPORT_FPS * 2) === 0 });
    }
  } finally {
    videoSource.close();
  }

  if (token.cancelled) return;
  await output.finalize();
  if (token.cancelled) return;
  if (!target.buffer) throw new Error(`${job.format.toUpperCase()} export did not produce a file`);
  const mimeType = job.format === "mp4" ? "video/mp4" : "video/webm";
  downloadBlob(new Blob([target.buffer], { type: mimeType }), `${job.scenario.scenario_id}_ean_replay.${job.format}`);
}
