import { Users } from "lucide-react";
import type { ReactNode } from "react";

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
  children?: ReactNode;
}

export function DemandSummaryPanel({
  title = "Demand",
  total,
  rows,
  emptyMessage = "No demand",
  className,
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
          {rows.map((row) => (
            <div className="demand-row" key={row.id}>
              <span className="od">
                {row.origin} {"->"} {row.destination}
              </span>
              <strong>{row.count}</strong>
              <small>{row.detail}</small>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
