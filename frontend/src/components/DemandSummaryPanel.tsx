import { Users } from "lucide-react";
import type { ReactNode } from "react";
import type { CSSProperties } from "react";
import type { Station } from "../types";
import { stationVisualColor } from "./stationColors";

export interface DemandSummaryRow {
  id: string;
  origin: string;
  destination: string;
  count: number;
  detail: string;
}

interface DemandSummaryPanelProps {
  title?: string;
  total: number;
  rows: DemandSummaryRow[];
  emptyMessage?: string;
  className?: string;
  stations?: Station[];
  children?: ReactNode;
}

export function DemandSummaryPanel({
  title = "Demand",
  total,
  rows,
  emptyMessage = "No demand",
  className,
  stations,
  children,
}: DemandSummaryPanelProps) {
  return (
    <section className={`panel demand-panel${className ? ` ${className}` : ""}`}>
      <header className="panel__header">
        <Users size={17} />
        <h2>{title}</h2>
        <span className="panel__count">{total} pax</span>
      </header>
      {children}
      {rows.length === 0 ? (
        <div className="empty-panel empty-panel--compact">{emptyMessage}</div>
      ) : (
        <div className="demand-list">
          {rows.map((row) => {
            const color = stationVisualColor(row.destination, stations);
            return (
              <div
                className="demand-row"
                key={row.id}
                style={{ "--demand-destination-color": color.base, "--demand-destination-fill": color.haloFill } as CSSProperties}
              >
                <span className="od">
                  {row.origin} {"->"} {row.destination}
                </span>
                <strong>{row.count}</strong>
                <small>{row.detail}</small>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
