interface BoundPoint {
  x: number;
  lower: number;
  upper: number | null;
}

export function BoundProgressChart({ points, xLabel = "K" }: { points: BoundPoint[]; xLabel?: string }) {
  if (points.length === 0) return <div className="optimization-empty">No certified bounds yet.</div>;
  const values = points.flatMap((point) => [point.lower, ...(point.upper === null ? [] : [point.upper])]);
  const minX = Math.min(...points.map((point) => point.x));
  const maxX = Math.max(...points.map((point) => point.x));
  const minY = Math.min(...values);
  const maxY = Math.max(...values);
  const sx = (x: number) => 42 + ((x - minX) / Math.max(1, maxX - minX)) * 516;
  const sy = (y: number) => 178 - ((y - minY) / Math.max(1e-9, maxY - minY)) * 144;
  const lower = points.map((point) => `${sx(point.x)},${sy(point.lower)}`).join(" ");
  const upper = points.filter((point) => point.upper !== null).map((point) => `${sx(point.x)},${sy(point.upper!)}`).join(" ");
  return (
    <figure className="bound-chart" aria-label={`Certified lower and validated upper bounds by ${xLabel}`}>
      <svg viewBox="0 0 600 220" role="img">
        <line x1="42" y1="178" x2="570" y2="178" className="chart-axis" />
        <line x1="42" y1="24" x2="42" y2="178" className="chart-axis" />
        <polyline points={lower} className="chart-line chart-line--lower" />
        {upper && <polyline points={upper} className="chart-line chart-line--upper" />}
        {points.map((point) => <circle key={`l${point.x}`} cx={sx(point.x)} cy={sy(point.lower)} r="4" className="chart-dot chart-dot--lower" />)}
        {points.filter((point) => point.upper !== null).map((point) => <circle key={`u${point.x}`} cx={sx(point.x)} cy={sy(point.upper!)} r="4" className="chart-dot chart-dot--upper" />)}
        <text x="570" y="205" textAnchor="end">{xLabel}</text>
        <text x="48" y="18">objective</text>
      </svg>
      <figcaption><span className="legend legend--lower">Certified LB</span><span className="legend legend--upper">Validated UB</span></figcaption>
    </figure>
  );
}
