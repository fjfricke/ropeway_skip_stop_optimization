import { Download, Eye, MousePointer2, Tags, Users, WholeWord, X } from "lucide-react";
import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import type { ScenarioLayout } from "../scenarioLayout";
import type { Scenario, TrackSegment } from "../types";
import { lineArcId, lineViewStations, stationLabel } from "./LineViewLayer";
import { ScenarioExportSelectorSvg } from "./ScenarioExportSelectorSvg";
import { ScenarioExportSvg } from "./ScenarioExportSvg";
import { buildScenarioExportRenderPlan } from "./scenarioExportGeometry";
import type { ArcColorMode, ScenarioDisplayMode, ScenarioExportBasis, ScenarioExportConfig, ViewerToggles } from "./viewerTypes";

interface ScenarioExportModalProps {
  scenario: Scenario;
  layout: ScenarioLayout;
  displayMode: ScenarioDisplayMode;
  toggles: ViewerToggles;
  arcColorMode: ArcColorMode;
  onClose: () => void;
}

const DEFAULT_PERCENTAGE = 100;
type ExportPane = "preview" | "selector";

export function ScenarioExportModal({ scenario, layout, displayMode, toggles, arcColorMode, onClose }: ScenarioExportModalProps) {
  const nodeOptions = useMemo(() => exportNodeOptions(scenario, displayMode), [scenario, displayMode]);
  const arcOptions = useMemo(() => exportArcOptions(scenario, displayMode), [scenario, displayMode]);
  const [config, setConfig] = useState<ScenarioExportConfig>(() => ({
    displayMode,
    scope: "custom",
    selectedNodeIds: nodeOptions.map((option) => option.id),
    selectedArcIds: arcOptions.map((option) => option.id),
    toggles: { ...toggles },
    arcColorMode,
    basis: "a4_width",
    percentage: DEFAULT_PERCENTAGE,
  }));
  const [activePane, setActivePane] = useState<ExportPane>("preview");
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const exportSvgRef = useRef<SVGSVGElement | null>(null);
  const previewCanvasRef = useRef<HTMLDivElement | null>(null);
  const [previewCanvasSize, setPreviewCanvasSize] = useState({ width: 0, height: 0 });
  const deferredConfig = useDeferredValue(config);
  const renderPlan = useMemo(() => buildScenarioExportRenderPlan({ scenario, layout, config: deferredConfig }), [scenario, layout, deferredConfig]);
  const selectedNodeIds = useMemo(() => new Set(config.selectedNodeIds), [config.selectedNodeIds]);
  const selectedArcIds = useMemo(() => new Set(config.selectedArcIds), [config.selectedArcIds]);

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

  function downloadSvg(svg: SVGSVGElement, filename: string) {
    try {
      downloadSvgElement(svg, filename);
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : "SVG export failed");
    }
  }

  function updateConfig(updater: (current: ScenarioExportConfig) => ScenarioExportConfig) {
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
    updateConfig((current) => ({
      ...current,
      selectedNodeIds: toggleId(current.selectedNodeIds, id),
    }));
  }

  function toggleArc(id: string) {
    updateConfig((current) => ({
      ...current,
      selectedArcIds: toggleId(current.selectedArcIds, id),
    }));
  }

  function selectAllCustomItems() {
    updateConfig((current) => ({
      ...current,
      selectedNodeIds: nodeOptions.map((option) => option.id),
      selectedArcIds: arcOptions.map((option) => option.id),
    }));
  }

  function clearCustomItems() {
    updateConfig((current) => ({
      ...current,
      selectedNodeIds: [],
      selectedArcIds: [],
    }));
  }

  function handleDownload() {
    setDownloadError(null);
    if (!exportSvgRef.current) return;
    downloadSvg(exportSvgRef.current, svgFilename(scenario.scenario_id, config));
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="export-modal" role="dialog" aria-modal="true" aria-labelledby="scenario-export-title" onMouseDown={(event) => event.stopPropagation()}>
        <header className="export-modal__header">
          <div>
            <p className="eyebrow">Scenario export</p>
            <h2 id="scenario-export-title">{displayMode === "line" ? "Line View SVG" : "Physical View SVG"}</h2>
          </div>
          <button type="button" className="export-modal__icon-button" onClick={onClose} aria-label="Close export modal">
            <X size={17} />
          </button>
        </header>

        <div className="export-modal__body">
          <div className="export-modal__settings">
            <section className="export-section export-section--selection-actions">
              <div className="export-section__header">
                <h3>Items</h3>
                <div className="export-section__actions">
                  <button type="button" onClick={selectAllCustomItems}>
                    All
                  </button>
                  <button type="button" onClick={clearCustomItems}>
                    None
                  </button>
                </div>
              </div>
              <p className="export-section__meta">
                {selectedNodeIds.size} {displayMode === "line" ? "stations" : "nodes"} · {selectedArcIds.size} {displayMode === "line" ? "links" : "arcs"}
              </p>
            </section>

            <section className="export-section">
              <h3>Layers</h3>
              <div className="export-toggle-grid">
                {displayMode === "line" ? (
                  <>
                    <button type="button" className={config.toggles.nodeLabels ? "is-active" : ""} onClick={() => toggleExportLayer("nodeLabels")}>
                      <WholeWord size={16} />
                      Node Labels
                    </button>
                    <button type="button" className={config.toggles.demand ? "is-active" : ""} onClick={() => toggleExportLayer("demand")}>
                      <Users size={16} />
                      Demand
                    </button>
                  </>
                ) : (
                  <>
                    <button type="button" className={config.toggles.serviceRoutes ? "is-active" : ""} onClick={() => toggleExportLayer("serviceRoutes")}>
                      Service
                    </button>
                    <button type="button" className={config.toggles.skipRoutes ? "is-active" : ""} onClick={() => toggleExportLayer("skipRoutes")}>
                      Skip
                    </button>
                    <button type="button" className={config.toggles.nodeLabels ? "is-active" : ""} onClick={() => toggleExportLayer("nodeLabels")}>
                      <WholeWord size={16} />
                      Node Labels
                    </button>
                    <button type="button" className={config.toggles.arcLabels ? "is-active" : ""} onClick={() => toggleExportLayer("arcLabels")}>
                      <Tags size={16} />
                      Arc Labels
                    </button>
                    <button
                      type="button"
                      className={`is-active export-toggle-grid__arc-color export-toggle-grid__arc-color--${config.arcColorMode}`}
                      onClick={() => updateConfig((current) => ({ ...current, arcColorMode: current.arcColorMode === "type" ? "speed" : "type" }))}
                    >
                      Arc Color: {config.arcColorMode === "type" ? "Type" : "Speed"}
                    </button>
                  </>
                )}
              </div>
            </section>

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
                  <input
                    type="number"
                    min="1"
                    max="400"
                    value={config.percentage}
                    onChange={(event) =>
                      updateConfig((current) => ({
                        ...current,
                        percentage: clampNumber(Number(event.target.value), 1, 400),
                      }))
                    }
                  />
                </label>
              </div>
            </section>
          </div>

          <div className="export-modal__preview">
            <div className="export-preview__header">
              <div>
                <h3>{activePane === "preview" ? "Preview" : "Selector"}</h3>
                <p>
                  {renderPlan.outputWidth} x {renderPlan.outputHeight}px
                </p>
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
                <button type="button" onClick={handleDownload}>
                  <Download size={16} />
                  Download SVG
                </button>
              </div>
            </div>
            {activePane === "preview" ? (
              <div className="export-preview__canvas" ref={previewCanvasRef}>
                <div
                  className="export-preview__artboard"
                  style={
                    {
                      aspectRatio: `${renderPlan.outputWidth} / ${renderPlan.outputHeight}`,
                      ...(artboardSize
                        ? {
                            width: `${artboardSize.width}px`,
                            height: `${artboardSize.height}px`,
                          }
                        : null),
                    } as CSSProperties
                  }
                >
                  <ScenarioExportSvg ref={exportSvgRef} scenario={scenario} layout={layout} config={deferredConfig} renderPlan={renderPlan} />
                </div>
              </div>
            ) : (
              <>
                <div className="export-preview__canvas export-preview__canvas--selector">
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
                <div className="export-download-source" aria-hidden="true">
                  <ScenarioExportSvg ref={exportSvgRef} scenario={scenario} layout={layout} config={deferredConfig} renderPlan={renderPlan} />
                </div>
              </>
            )}
            {downloadError ? <p className="export-preview__error">{downloadError}</p> : null}
          </div>
        </div>
      </section>
    </div>
  );
}

function exportNodeOptions(scenario: Scenario, displayMode: ScenarioDisplayMode) {
  if (displayMode === "line") {
    return lineViewStations(scenario).map((station) => ({
      id: station.id,
      label: stationLabel(station),
    }));
  }
  return scenario.physical_nodes.map((node) => ({
    id: node.id,
    label: node.id.replaceAll("_", " "),
  }));
}

function exportArcOptions(scenario: Scenario, displayMode: ScenarioDisplayMode) {
  if (displayMode === "line") {
    const stations = lineViewStations(scenario);
    return stations.slice(0, -1).map((station, index) => {
      const next = stations[index + 1];
      return {
        id: lineArcId(station.id, next.id),
        label: `${stationLabel(station)} -> ${stationLabel(next)}`,
      };
    });
  }
  return scenario.track_segments.map((segment) => ({
    id: segment.id,
    label: physicalArcLabel(segment),
  }));
}

function physicalArcLabel(segment: TrackSegment) {
  return `${segment.id.replaceAll("_", " ")} (${segment.from_node_id} -> ${segment.to_node_id})`;
}

function toggleId(ids: string[], id: string) {
  return ids.includes(id) ? ids.filter((current) => current !== id) : [...ids, id];
}

function svgFilename(scenarioId: string, config: ScenarioExportConfig) {
  const mode = config.displayMode === "line" ? "line" : "physical";
  return `${scenarioId}_${mode}_scenario_export.svg`;
}

function downloadSvgElement(svg: SVGSVGElement, filename: string) {
  const width = Number(svg.getAttribute("width"));
  const height = Number(svg.getAttribute("height"));
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    throw new Error("Invalid export size");
  }

  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));
  const source = new XMLSerializer().serializeToString(clone);
  const blob = new Blob([source], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function clampNumber(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return min;
  return Math.min(Math.max(value, min), max);
}
