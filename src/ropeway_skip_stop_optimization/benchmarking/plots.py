from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, Mapping, Sequence


PLOT_NAMES = (
    "gap_over_time",
    "objective_and_bound_over_time",
    "nodes_over_time",
    "runtime_by_run",
    "final_gap_by_run",
    "objective_by_run",
    "model_size_by_run",
    "model_nonzeros_by_run",
    "model_setup_runtime_by_run",
    "candidate_size_by_run",
)


@dataclass(frozen=True)
class PlotSeries:
    label: str
    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class BarGroup:
    label: str
    values: Mapping[str, float | None]


@dataclass(frozen=True)
class PlotBuilder:
    results: Sequence[Mapping[str, Any]]

    def write_all(self, output_dir: Path, *, file_format: str = "svg", include: str = "all") -> tuple[Path, ...]:
        if file_format != "svg":
            raise ValueError("Only SVG benchmark plots are supported for now")
        selected = _selected_plot_names(include)
        output_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for name in selected:
            svg = self._build_svg(name)
            output_path = output_dir / f"{name}.svg"
            output_path.write_text(svg, encoding="utf-8")
            written.append(output_path)
        return tuple(written)

    def _build_svg(self, name: str) -> str:
        if name == "gap_over_time":
            return _line_chart(
                title="MIP gap over time",
                x_label="runtime seconds",
                y_label="gap percent",
                series=_time_series(self.results, "mip_gap", scale=100.0),
            )
        if name == "objective_and_bound_over_time":
            return _line_chart(
                title="Objective and bound over time",
                x_label="runtime seconds",
                y_label="objective seconds",
                series=_objective_bound_series(self.results),
            )
        if name == "nodes_over_time":
            return _line_chart(
                title="Explored nodes over time",
                x_label="runtime seconds",
                y_label="nodes",
                series=_time_series(self.results, "node_count"),
            )
        if name == "runtime_by_run":
            return _bar_chart(
                title="Runtime by run",
                y_label="runtime seconds",
                groups=_single_metric_groups(self.results, "runtime_seconds"),
            )
        if name == "final_gap_by_run":
            return _bar_chart(
                title="Final MIP gap by run",
                y_label="gap percent",
                groups=_single_metric_groups(self.results, "mip_gap", scale=100.0),
            )
        if name == "objective_by_run":
            return _bar_chart(
                title="Final objective by run",
                y_label="passenger hours",
                groups=_single_metric_groups(self.results, "objective_passenger_hours"),
            )
        if name == "model_size_by_run":
            return _bar_chart(
                title="Model size by run",
                y_label="count",
                groups=_multi_metric_groups(
                    self.results,
                    (
                        ("variables", "model_variable_count"),
                        ("constraints", "model_constraint_count"),
                    ),
                ),
            )
        if name == "model_nonzeros_by_run":
            return _bar_chart(
                title="Model nonzeros by run",
                y_label="nonzeros",
                groups=_single_metric_groups(self.results, "model_nonzero_count"),
            )
        if name == "model_setup_runtime_by_run":
            return _bar_chart(
                title="Model setup time by run",
                y_label="seconds",
                groups=_single_metric_groups(self.results, "model_setup_runtime_seconds"),
            )
        if name == "candidate_size_by_run":
            return _bar_chart(
                title="Candidate size by run",
                y_label="count",
                groups=_multi_metric_groups(
                    self.results,
                    (
                        ("demand groups", "demand_group_count"),
                        ("ride candidates", "ride_candidate_count"),
                        ("slots", "slot_variable_count"),
                    ),
                ),
            )
        raise ValueError(f"Unknown plot name: {name}")


@dataclass(frozen=True)
class EanBottleneckPlotBuilder:
    diagnostic: Mapping[str, Any]

    def write_all(
        self,
        output_dir: Path,
        *,
        prefix: str,
    ) -> tuple[Path, ...]:
        output_dir.mkdir(parents=True, exist_ok=True)
        case_results = self._case_results()
        plots = {
            "runtime_by_case": _bar_chart(
                title="EAN bottleneck runtime by case",
                y_label="seconds",
                groups=_single_metric_groups(
                    case_results,
                    "runtime_seconds",
                ),
            ),
            "model_size_by_case": _bar_chart(
                title="EAN bottleneck model size by case",
                y_label="count",
                groups=_multi_metric_groups(
                    case_results,
                    (
                        ("variables", "variable_count"),
                        ("constraints", "constraint_count"),
                        ("nonzeros", "model_nonzero_count"),
                    ),
                ),
            ),
            "build_time_by_case": _bar_chart(
                title="EAN model construction by case",
                y_label="seconds",
                groups=_multi_metric_groups(
                    case_results,
                    (
                        ("candidates", "candidate_seconds"),
                        ("movement", "movement_seconds"),
                        ("fix movement", "fixing_seconds"),
                        ("passengers", "passenger_seconds"),
                        ("MIP start", "mip_start_seconds"),
                    ),
                ),
            ),
            "solve_phases_by_case": _bar_chart(
                title="EAN solve phases by case",
                y_label="seconds",
                groups=_multi_metric_groups(
                    case_results,
                    (
                        ("presolve", "presolve_seconds"),
                        ("root relaxation", "root_seconds"),
                        ("first incumbent", "first_incumbent_seconds"),
                    ),
                ),
            ),
            "memory_by_case": _bar_chart(
                title="EAN observed memory by case",
                y_label="GB",
                groups=_single_metric_groups(
                    case_results,
                    "peak_memory_gb",
                ),
            ),
        }
        root_fractionality_groups = self._root_fractionality_groups()
        if root_fractionality_groups:
            plots["root_fractionality_by_case"] = _bar_chart(
                title="EAN root fractional variables by family",
                y_label="fractional variables",
                groups=root_fractionality_groups,
            )
        root_bound_series = self._root_bound_series()
        if root_bound_series:
            plots["root_bound_over_time"] = _line_chart(
                title="EAN root lower bound over time",
                x_label="runtime seconds",
                y_label="objective seconds",
                series=root_bound_series,
            )
        written: list[Path] = []
        for name, svg in plots.items():
            output_path = output_dir / f"{prefix}__{name}.svg"
            output_path.write_text(svg, encoding="utf-8")
            written.append(output_path)
        return tuple(written)

    def _case_results(self) -> tuple[dict[str, Any], ...]:
        results: list[dict[str, Any]] = []
        example_id = str(self.diagnostic.get("example_id", "EAN"))
        for case in self.diagnostic.get("cases") or ():
            metadata = case.get("metadata")
            if not isinstance(metadata, Mapping):
                continue
            build = metadata.get("build_metrics")
            phases = metadata.get("solve_phase_metrics")
            build = build if isinstance(build, Mapping) else {}
            phases = phases if isinstance(phases, Mapping) else {}
            results.append(
                {
                    "label": f"{example_id} / {case.get('case')}",
                    "runtime_seconds": metadata.get("runtime_seconds"),
                    "variable_count": metadata.get("variable_count"),
                    "constraint_count": metadata.get("constraint_count"),
                    "model_nonzero_count": metadata.get(
                        "model_nonzero_count"
                    ),
                    "candidate_seconds": build.get(
                        "passenger_candidate_generation_seconds"
                    ),
                    "movement_seconds": build.get(
                        "movement_model_seconds"
                    ),
                    "fixing_seconds": build.get(
                        "movement_fixing_seconds"
                    ),
                    "passenger_seconds": build.get(
                        "passenger_model_seconds"
                    ),
                    "mip_start_seconds": build.get("mip_start_seconds"),
                    "presolve_seconds": phases.get(
                        "presolve_runtime_seconds"
                    ),
                    "root_seconds": phases.get(
                        "root_relaxation_runtime_seconds"
                    ),
                    "first_incumbent_seconds": phases.get(
                        "first_incumbent_runtime_seconds"
                    ),
                    "peak_memory_gb": phases.get("peak_memory_gb"),
                }
            )
        return tuple(results)

    def _root_fractionality_groups(self) -> tuple[BarGroup, ...]:
        groups: list[BarGroup] = []
        example_id = str(self.diagnostic.get("example_id", "EAN"))
        for case in self.diagnostic.get("cases") or ():
            root = case.get("root_relaxation")
            if not isinstance(root, Mapping):
                continue
            samples = root.get("samples") or ()
            if samples:
                families = samples[-1].get("families") or ()
            else:
                standalone = root.get("standalone_relaxation")
                families = (
                    standalone.get("families") or ()
                    if isinstance(standalone, Mapping)
                    else ()
                )
            values = {
                str(family.get("family")): _as_float(
                    family.get("fractional_variable_count")
                )
                for family in families
                if _as_float(
                    family.get("fractional_variable_count")
                )
                is not None
            }
            if values:
                groups.append(
                    BarGroup(
                        f"{example_id} / {case.get('case')}",
                        values,
                    )
                )
        return tuple(groups)

    def _root_bound_series(self) -> tuple[PlotSeries, ...]:
        series: list[PlotSeries] = []
        example_id = str(self.diagnostic.get("example_id", "EAN"))
        for case in self.diagnostic.get("cases") or ():
            root = case.get("root_relaxation")
            if not isinstance(root, Mapping):
                continue
            points: list[tuple[float, float]] = []
            for sample in root.get("samples") or ():
                runtime = _as_float(sample.get("runtime_seconds"))
                bound = _as_float(sample.get("best_bound"))
                if runtime is not None and bound is not None:
                    points.append((runtime, bound))
            if not points:
                metadata = case.get("metadata")
                if isinstance(metadata, Mapping):
                    for sample in (
                        metadata.get("progress_samples") or ()
                    ):
                        runtime = _as_float(
                            sample.get("runtime_seconds")
                        )
                        bound = _as_float(sample.get("best_bound"))
                        node_count = _as_float(
                            sample.get("node_count")
                        )
                        if (
                            runtime is not None
                            and bound is not None
                            and (
                                node_count is None
                                or node_count <= 0.5
                            )
                        ):
                            points.append((runtime, bound))
            if points:
                series.append(
                    PlotSeries(
                        f"{example_id} / {case.get('case')}",
                        tuple(points),
                    )
                )
        return tuple(series)


def load_benchmark_result_dicts(paths: Sequence[Path]) -> tuple[dict[str, Any], ...]:
    return tuple(json.loads(path.read_text(encoding="utf-8")) for path in paths)


def collect_result_paths(input_paths: Sequence[Path], input_dir: Path | None = None) -> tuple[Path, ...]:
    paths: list[Path] = []
    for path in input_paths:
        if path.is_dir():
            paths.extend(sorted(path.glob("*.json")))
        else:
            paths.append(path)
    if input_dir is not None and not input_paths:
        paths.extend(sorted(input_dir.glob("*.json")))
    return tuple(path for path in paths if path.is_file())


def _selected_plot_names(include: str) -> tuple[str, ...]:
    if include == "all":
        return PLOT_NAMES
    selected = tuple(item.strip() for item in include.split(",") if item.strip())
    unknown = sorted(set(selected) - set(PLOT_NAMES))
    if unknown:
        raise ValueError(f"Unknown plot name(s): {', '.join(unknown)}")
    return selected


def _time_series(results: Sequence[Mapping[str, Any]], metric: str, *, scale: float = 1.0) -> tuple[PlotSeries, ...]:
    series: list[PlotSeries] = []
    for result in results:
        points = []
        for sample in result.get("progress_samples") or ():
            x_value = _as_float(sample.get("runtime_seconds"))
            y_value = _as_float(sample.get(metric))
            if x_value is not None and y_value is not None:
                points.append((x_value, y_value * scale))
        if not points:
            x_value = _as_float(result.get("runtime_seconds"))
            y_value = _as_float(result.get(metric))
            if x_value is not None and y_value is not None:
                points.append((x_value, y_value * scale))
        if points:
            series.append(PlotSeries(_label(result), tuple(points)))
    return tuple(series)


def _objective_bound_series(results: Sequence[Mapping[str, Any]]) -> tuple[PlotSeries, ...]:
    series: list[PlotSeries] = []
    for result in results:
        label = _label(result)
        incumbent_points: list[tuple[float, float]] = []
        bound_points: list[tuple[float, float]] = []
        for sample in result.get("progress_samples") or ():
            runtime = _as_float(sample.get("runtime_seconds"))
            incumbent = _as_float(sample.get("incumbent_objective"))
            bound = _as_float(sample.get("best_bound"))
            if runtime is None:
                continue
            if incumbent is not None:
                incumbent_points.append((runtime, incumbent))
            if bound is not None:
                bound_points.append((runtime, bound))
        if incumbent_points:
            series.append(PlotSeries(f"{label} incumbent", tuple(incumbent_points)))
        if bound_points:
            series.append(PlotSeries(f"{label} bound", tuple(bound_points)))
    return tuple(series)


def _single_metric_groups(
    results: Sequence[Mapping[str, Any]],
    metric: str,
    *,
    scale: float = 1.0,
) -> tuple[BarGroup, ...]:
    return tuple(BarGroup(_label(result), {metric: _scaled(result.get(metric), scale)}) for result in results)


def _multi_metric_groups(
    results: Sequence[Mapping[str, Any]],
    metrics: Sequence[tuple[str, str]],
) -> tuple[BarGroup, ...]:
    groups: list[BarGroup] = []
    for result in results:
        groups.append(BarGroup(_label(result), {label: _as_float(result.get(key)) for label, key in metrics}))
    return tuple(groups)


def _line_chart(
    *,
    title: str,
    x_label: str,
    y_label: str,
    series: Sequence[PlotSeries],
    width: int = 960,
    height: int = 540,
) -> str:
    margin_left = 84
    margin_right = 220
    margin_top = 56
    margin_bottom = 72
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    points = [point for item in series for point in item.points]
    if not points:
        return _empty_svg(title, "No benchmark samples available", width, height)
    x_min, x_max = _bounds(point[0] for point in points)
    y_min, y_max = _bounds(point[1] for point in points)
    colors = _palette()
    elements = _chart_frame(
        title=title,
        x_label=x_label,
        y_label=y_label,
        width=width,
        height=height,
        margin_left=margin_left,
        margin_right=margin_right,
        margin_top=margin_top,
        margin_bottom=margin_bottom,
        x_min=x_min,
        x_max=x_max,
        y_min=y_min,
        y_max=y_max,
    )
    legend_y = margin_top
    for index, item in enumerate(series):
        color = colors[index % len(colors)]
        path_parts = []
        for point_index, (x_value, y_value) in enumerate(item.points):
            x = _scale(x_value, x_min, x_max, margin_left, margin_left + plot_width)
            y = _scale(y_value, y_min, y_max, margin_top + plot_height, margin_top)
            path_parts.append(f"{'M' if point_index == 0 else 'L'} {x:.2f} {y:.2f}")
        elements.append(
            f'<path d="{" ".join(path_parts)}" fill="none" stroke="{color}" stroke-width="2.5" />'
        )
        for x_value, y_value in item.points:
            x = _scale(x_value, x_min, x_max, margin_left, margin_left + plot_width)
            y = _scale(y_value, y_min, y_max, margin_top + plot_height, margin_top)
            elements.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="{color}" />')
        elements.append(f'<rect x="{width - margin_right + 24}" y="{legend_y - 10}" width="12" height="12" fill="{color}" />')
        elements.append(_text(width - margin_right + 44, legend_y, _truncate(item.label, 34), size=12, anchor="start"))
        legend_y += 20
    return _svg(width, height, elements)


def _bar_chart(
    *,
    title: str,
    y_label: str,
    groups: Sequence[BarGroup],
    width: int = 960,
    height: int = 540,
) -> str:
    margin_left = 84
    margin_right = 180
    margin_top = 56
    margin_bottom = 104
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    metric_names = tuple(dict.fromkeys(name for group in groups for name in group.values))
    values = [value for group in groups for value in group.values.values() if value is not None]
    if not values:
        return _empty_svg(title, "No benchmark values available", width, height)
    y_min = 0.0
    y_max = max(values) * 1.08 if max(values) > 0 else 1.0
    colors = _palette()
    elements = _chart_frame(
        title=title,
        x_label="run",
        y_label=y_label,
        width=width,
        height=height,
        margin_left=margin_left,
        margin_right=margin_right,
        margin_top=margin_top,
        margin_bottom=margin_bottom,
        x_min=0,
        x_max=max(1, len(groups)),
        y_min=y_min,
        y_max=y_max,
        draw_x_ticks=False,
    )
    group_width = plot_width / max(1, len(groups))
    bar_gap = 6
    bar_width = max(3.0, (group_width - 18) / max(1, len(metric_names)) - bar_gap)
    for group_index, group in enumerate(groups):
        group_x = margin_left + group_index * group_width + 9
        for metric_index, metric in enumerate(metric_names):
            value = group.values.get(metric)
            if value is None:
                continue
            x = group_x + metric_index * (bar_width + bar_gap)
            y = _scale(value, y_min, y_max, margin_top + plot_height, margin_top)
            h = margin_top + plot_height - y
            color = colors[metric_index % len(colors)]
            elements.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width:.2f}" height="{h:.2f}" fill="{color}" />')
        label_x = margin_left + group_index * group_width + group_width / 2
        elements.append(
            _text(
                label_x,
                height - margin_bottom + 30,
                _truncate(group.label, 24),
                size=11,
                anchor="middle",
                rotate=-18,
            )
        )
    legend_y = margin_top
    for metric_index, metric in enumerate(metric_names):
        color = colors[metric_index % len(colors)]
        elements.append(f'<rect x="{width - margin_right + 24}" y="{legend_y - 10}" width="12" height="12" fill="{color}" />')
        elements.append(_text(width - margin_right + 44, legend_y, metric, size=12, anchor="start"))
        legend_y += 20
    return _svg(width, height, elements)


def _chart_frame(
    *,
    title: str,
    x_label: str,
    y_label: str,
    width: int,
    height: int,
    margin_left: int,
    margin_right: int,
    margin_top: int,
    margin_bottom: int,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    draw_x_ticks: bool = True,
) -> list[str]:
    plot_left = margin_left
    plot_right = width - margin_right
    plot_top = margin_top
    plot_bottom = height - margin_bottom
    elements = [
        '<rect x="0" y="0" width="100%" height="100%" fill="#ffffff" />',
        _text(width / 2, 28, title, size=18, weight="700", anchor="middle"),
        f'<line x1="{plot_left}" y1="{plot_bottom}" x2="{plot_right}" y2="{plot_bottom}" stroke="#222" stroke-width="1.4" />',
        f'<line x1="{plot_left}" y1="{plot_top}" x2="{plot_left}" y2="{plot_bottom}" stroke="#222" stroke-width="1.4" />',
        _text((plot_left + plot_right) / 2, height - 18, x_label, size=12, anchor="middle"),
        _text(18, (plot_top + plot_bottom) / 2, y_label, size=12, anchor="middle", rotate=-90),
    ]
    for tick_index in range(5):
        y_value = y_min + (y_max - y_min) * tick_index / 4
        y = _scale(y_value, y_min, y_max, plot_bottom, plot_top)
        elements.append(f'<line x1="{plot_left - 5}" y1="{y:.2f}" x2="{plot_right}" y2="{y:.2f}" stroke="#d8dee4" stroke-width="1" />')
        elements.append(_text(plot_left - 10, y + 4, _format_number(y_value), size=11, anchor="end"))
    if draw_x_ticks:
        for tick_index in range(5):
            x_value = x_min + (x_max - x_min) * tick_index / 4
            x = _scale(x_value, x_min, x_max, plot_left, plot_right)
            elements.append(f'<line x1="{x:.2f}" y1="{plot_bottom}" x2="{x:.2f}" y2="{plot_bottom + 5}" stroke="#222" />')
            elements.append(_text(x, plot_bottom + 22, _format_number(x_value), size=11, anchor="middle"))
    return elements


def _empty_svg(title: str, message: str, width: int, height: int) -> str:
    return _svg(
        width,
        height,
        [
            '<rect x="0" y="0" width="100%" height="100%" fill="#ffffff" />',
            _text(width / 2, 28, title, size=18, weight="700", anchor="middle"),
            _text(width / 2, height / 2, message, size=14, anchor="middle"),
        ],
    )


def _svg(width: int, height: int, elements: Sequence[str]) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img">\n'
        '<style>text{font-family:Arial,Helvetica,sans-serif;fill:#202428} '
        'path,line,rect,circle{shape-rendering:geometricPrecision}</style>\n'
        + "\n".join(elements)
        + "\n</svg>\n"
    )


def _text(
    x: float,
    y: float,
    value: str,
    *,
    size: int,
    anchor: str,
    weight: str = "400",
    rotate: float | None = None,
) -> str:
    transform = f' transform="rotate({rotate:.1f} {x:.2f} {y:.2f})"' if rotate is not None else ""
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size}" font-weight="{weight}" '
        f'text-anchor="{anchor}"{transform}>{escape(value)}</text>'
    )


def _bounds(values: Sequence[float] | Any) -> tuple[float, float]:
    materialized = list(values)
    minimum = min(materialized)
    maximum = max(materialized)
    if minimum == maximum:
        delta = abs(minimum) * 0.05 or 1.0
        return minimum - delta, maximum + delta
    pad = (maximum - minimum) * 0.04
    return minimum - pad, maximum + pad


def _scale(value: float, source_min: float, source_max: float, target_min: float, target_max: float) -> float:
    if source_min == source_max:
        return (target_min + target_max) / 2
    ratio = (value - source_min) / (source_max - source_min)
    return target_min + ratio * (target_max - target_min)


def _palette() -> tuple[str, ...]:
    return (
        "#2563eb",
        "#dc2626",
        "#16a34a",
        "#9333ea",
        "#f59e0b",
        "#0891b2",
        "#db2777",
        "#4b5563",
    )


def _label(result: Mapping[str, Any]) -> str:
    return str(result.get("label") or result.get("run_id") or "run")


def _truncate(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - 1] + "..."


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _scaled(value: Any, scale: float) -> float | None:
    number = _as_float(value)
    return None if number is None else number * scale


def _format_number(value: float) -> str:
    magnitude = abs(value)
    if magnitude >= 1_000_000 or (0 < magnitude < 0.01):
        return f"{value:.2e}"
    if magnitude >= 100:
        return f"{value:.0f}"
    if magnitude >= 10:
        return f"{value:.1f}"
    return f"{value:.2f}"
