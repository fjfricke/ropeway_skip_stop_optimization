import { Eye, MousePointer2 } from "lucide-react";

export type ExportPane = "preview" | "selector";

export function ExportPaneTabs({ activePane, onPaneChange }: { activePane: ExportPane; onPaneChange: (pane: ExportPane) => void }) {
  return (
    <div className="export-pane-tabs" aria-label="Export panel">
      <button type="button" className={activePane === "selector" ? "is-active" : ""} onClick={() => onPaneChange("selector")}>
        <MousePointer2 size={16} />
        Selector
      </button>
      <button type="button" className={activePane === "preview" ? "is-active" : ""} onClick={() => onPaneChange("preview")}>
        <Eye size={16} />
        Preview
      </button>
    </div>
  );
}
