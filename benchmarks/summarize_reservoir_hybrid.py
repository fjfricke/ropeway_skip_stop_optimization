"""Summarize completed bound/repair comparison, with optional standalone plots."""

import argparse
import csv
import json
from pathlib import Path


def read_events(path):
    return (
        [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        if path.exists()
        else []
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--refinement", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--plots", action="store_true")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    campaign = json.loads((args.comparison / "campaign.json").read_text())
    refined = json.loads(args.refinement.read_text())
    if campaign["common_bound"]["fingerprint"] != refined["problem_fingerprint"]:
        raise ValueError("comparison and refinement have different physical domains")
    shared = campaign["common_bound"]["value"]
    summaries = []
    curves = {}
    for case in campaign["cases"]:
        name = case["name"]
        result = case["result"]
        events = read_events(args.comparison / name / "events.jsonl")
        initial = next(e for e in events if e.get("kind") == "initial")
        upper = initial["validated_upper_bound"]
        samples = [(0.0, upper, shared)]
        lower = shared
        improvements = []
        for event in events:
            elapsed = event.get("elapsed_seconds")
            if elapsed is None:
                continue
            candidate = upper
            if event.get("kind") == "incumbent":
                candidate = event["objective_raw"] / 1e6
            elif event.get("kind") == "improvement":
                candidate = event["validated_upper_bound"]
            if candidate < upper - 1e-6:
                improvements.append((elapsed, candidate))
            upper = min(upper, candidate)
            if event.get("kind") == "bound" and "bound_raw" in event:
                lower = max(lower, event["bound_raw"] / 1e6)
            lower = max(lower, event.get("certified_lower_bound", lower))
            samples.append((elapsed, upper, lower))
        end = case["actual_seconds"]
        samples.append(
            (end, result["validated_upper_bound"], result["certified_lower_bound"])
        )
        samples.sort()
        curves[name] = samples
        last_quarter = [s for s in samples if s[0] <= 0.75 * end][-1]
        ub_gain_last = last_quarter[1] - result["validated_upper_bound"]
        lb_gain_last = result["certified_lower_bound"] - last_quarter[2]
        entry = {
            "case": name,
            "completed": case["return_code"] == 0 and not result.get("incomplete"),
            "stop": case.get("termination_reason"),
            "actual_seconds": end,
            "upper_bound": result["validated_upper_bound"],
            "lower_bound": result["certified_lower_bound"],
            "gap_percent": 100
            * (result["validated_upper_bound"] - result["certified_lower_bound"])
            / result["validated_upper_bound"],
            "peak_rss_gib": case["peak_sampled_rss_bytes"] / 1024**3,
            "native_improvements": len(improvements),
            "first_improvement_seconds": improvements[0][0] if improvements else None,
            "last_improvement_seconds": improvements[-1][0] if improvements else None,
            "last_quarter_ub_gain": ub_gain_last,
            "last_quarter_lb_gain": lb_gain_last,
            "plateau_last_quarter": ub_gain_last < 0.001 * last_quarter[1]
            and lb_gain_last < 0.001 * last_quarter[1],
        }
        if not entry["completed"]:
            entry["plateau_last_quarter"] = None
        summaries.append(entry)
    with (args.output_dir / "comparison.csv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    with (args.output_dir / "progress.csv").open("w") as f:
        writer = csv.writer(f)
        writer.writerow(["case", "elapsed_seconds", "incumbent", "lower_bound"])
        for name, points in curves.items():
            writer.writerows((name, *point) for point in points)
    (args.output_dir / "summary.json").write_text(
        json.dumps(
            {
                "cases": summaries,
                "performance_recommendation": campaign.get(
                    "performance_recommendation", False
                ),
            },
            indent=2,
        )
    )
    lines = [
        "# Reservoir hybrid comparison",
        "",
        "CP progress incumbents are native solver values; final plans are independently validated. Hybrid improvements are validated at each event. Initial seed adoption is excluded.",
        "",
        "| Case | Complete | UB | LB | Gap | Wall seconds | Peak GiB | Improvements |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in summaries:
        lines.append(
            f"| {r['case']} | {r['completed']} | {r['upper_bound']:.6f} | {r['lower_bound']:.6f} | {r['gap_percent']:.3f}% | {r['actual_seconds']:.2f} | {r['peak_rss_gib']:.3f} | {r['native_improvements']} |"
        )
    lines += [
        "",
        "Curve times use solver/coordinator clocks; total wall time includes process startup. Aborted runs are not equal-duration performance comparisons.",
        "",
        f"Confirmed performance recommendation: **{campaign.get('performance_recommendation', False)}**.",
    ]
    (args.output_dir / "report.md").write_text("\n".join(lines) + "\n")
    if args.plots:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), constrained_layout=True)
        start_lb = refined["analytical_lower_bound"]
        ub = refined["validated_upper_bound"]
        points = [(0, start_lb)]
        incumbent_lb = start_lb
        for r in refined["rounds"]:
            incumbent_lb = max(incumbent_lb, r["ledger_lower_bound"])
            points.append((r["cumulative_seconds"], incumbent_lb))
        axes[0].step(
            *zip(*points),
            where="post",
            label="Certified lower bound",
            color="#117A65",
            linewidth=2,
        )
        axes[0].axhline(ub, color="#374151", linestyle="--", label="Validated seed")
        axes[0].set(
            title="Time-moment refinement",
            xlabel="Elapsed seconds",
            ylabel="Passenger-seconds",
            ylim=(0, ub * 1.05),
        )
        axes[0].legend()
        for name, points in curves.items():
            axes[1].step(
                [p[0] for p in points],
                [p[1] for p in points],
                where="post",
                label=name,
                alpha=0.85,
            )
        axes[1].axhline(
            shared, color="#117A65", linestyle="--", label="Shared lower bound"
        )
        axes[1].set(
            title="Search from the same reference",
            xlabel="Elapsed seconds",
            ylabel="Passenger-seconds",
            ylim=(shared * 0.95, ub * 1.05),
        )
        axes[1].legend(fontsize=8)
        for axis in axes:
            axis.grid(alpha=0.2)
            axis.ticklabel_format(style="plain", axis="y")
        fig.savefig(args.output_dir / "progress.png", dpi=180)
        fig.savefig(args.output_dir / "progress.pdf")


if __name__ == "__main__":
    main()
