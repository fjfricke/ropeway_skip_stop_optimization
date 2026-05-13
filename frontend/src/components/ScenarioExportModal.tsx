import { Download, Tags, Users, WholeWord, X } from "lucide-react";
import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import type { ScenarioLayout } from "../scenarioLayout";
import type { Scenario } from "../types";
import { downloadSvgElement } from "./export/exportDom";
import { ExportItemActions } from "./export/ExportItemActions";
import { ExportPaneTabs, type ExportPane } from "./export/ExportPaneTabs";
import { exportArcOptions, exportNodeOptions, toggleId } from "./export/exportSelection";
import { computeArtboardSize, DEFAULT_EXPORT_PERCENTAGE } from "./export/exportSizing";
import { ExportSizeControls } from "./export/ExportSizeControls";
import type { ScenarioExportConfig } from "./export/exportTypes";
import { useElementSize } from "./hooks/useElementSize";
import { ScenarioExportSelectorSvg } from "./ScenarioExportSelectorSvg";
import { ScenarioExportSvg } from "./ScenarioExportSvg";
import { buildScenarioExportRenderPlan } from "./scenarioExportGeometry";
import type { ArcColorMode, ScenarioDisplayMode, ViewerToggles } from "./viewerTypes";

interface ScenarioExportModalProps {
  scenario: Scenario;
  layout: ScenarioLayout;
  displayMode: ScenarioDisplayMode;
  toggles: ViewerToggles;
  arcColorMode: ArcColorMode;
  onClose: () => void;
}

export function ScenarioExportModal({ scenario, layout, displayMode, toggles, arcColorMode, onClose }: ScenarioExportModalProps) {
  const nodeOptions = useMemo(() => exportNodeOptions(scenario, displayMode), [scenario, displayMode]);
  const arcOptions = useMemo(() => exportArcOptions(scenario, displayMode), [scenario, displayMode]);
  const [config, setConfig] = useState<ScenarioExportConfig>(() => ({
    displayMode,
    selectedNodeIds: nodeOptions.map((option) => option.id),
    selectedArcIds: arcOptions.map((option) => option.id),
    toggles: { ...toggles },
    arcColorMode,
    basis: "a4_width",
    percentage: DEFAULT_EXPORT_PERCENTAGE,
  }));
  const [activePane, setActivePane] = useState<ExportPane>("selector");
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const exportSvgRef = useRef<SVGSVGElement | null>(null);
  const [previewCanvasRef, previewCanvasSize] = useElementSize<HTMLDivElement>([activePane]);
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

  const artboardSize = useMemo(() => {
    return computeArtboardSize(previewCanvasSize, renderPlan.outputWidth, renderPlan.outputHeight);
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
            <ExportItemActions
              selectedNodeCount={selectedNodeIds.size}
              selectedArcCount={selectedArcIds.size}
              nodeLabel={displayMode === "line" ? "stations" : "nodes"}
              arcLabel={displayMode === "line" ? "links" : "arcs"}
              onSelectAll={selectAllCustomItems}
              onClear={clearCustomItems}
            />

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

            <ExportSizeControls
              basis={config.basis}
              percentage={config.percentage}
              onBasisChange={(basis) => updateConfig((current) => ({ ...current, basis }))}
              onPercentageChange={(percentage) => updateConfig((current) => ({ ...current, percentage }))}
            />
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
                <ExportPaneTabs activePane={activePane} onPaneChange={setActivePane} />
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

function svgFilename(scenarioId: string, config: ScenarioExportConfig) {
  const mode = config.displayMode === "line" ? "line" : "physical";
  return `${scenarioId}_${mode}_scenario_export.svg`;
}
