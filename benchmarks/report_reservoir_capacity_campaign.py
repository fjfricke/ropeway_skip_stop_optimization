"""Read-only campaign analysis; optional matplotlib from an artifact runtime."""

import argparse
import csv
import json
from pathlib import Path


def analyze(root):
    comparison = json.loads((root / "comparison.json").read_text())
    rows = []
    history = []
    for run in comparison["rows"]:
        path = root / run["name"]
        r = (
            json.loads((path / "result.json").read_text())
            if (path / "result.json").exists()
            else {}
        )
        ref = (
            json.loads((path / "reference.json").read_text())
            if (path / "reference.json").exists()
            else {}
        )
        seed = ref.get("metrics", {}).get("unserved")
        best = seed
        first = None
        improvements = []
        bounds = []
        origin = "search" if run["method"] == "phase_arc_flow" else "worker"
        eventfile = path / "events.jsonl"
        events = []
        if eventfile.exists():
            for line in eventfile.read_text().splitlines():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # supervisor may interrupt last write
        for e in events:
            kind = e.get("event", e.get("kind"))
            seconds = e.get("seconds", e.get("elapsed_seconds"))
            if kind in ("native_solution", "incumbent"):
                u = e.get("unserved", e.get("objective_raw"))
                if first is None:
                    first = seconds
                if best is None or u < best:
                    improvements.append((seconds, u))
                    best = u
                history.append(
                    dict(
                        run=run["name"],
                        clock_origin=origin,
                        seconds=seconds,
                        kind="native_ub",
                        value=u,
                    )
                )
            elif kind in ("restricted_bound", "bound"):
                value = e.get("lower", e.get("bound_raw"))
                bounds.append((seconds, value))
                history.append(
                    dict(
                        run=run["name"],
                        clock_origin=origin,
                        seconds=seconds,
                        kind="restricted_lb" if origin == "search" else "global_lb_raw",
                        value=value,
                    )
                )
        failure = (
            json.loads((path / "failure.json").read_text())
            if (path / "failure.json").exists()
            else None
        )
        rows.append(
            dict(
                run=run["name"],
                case=run["case"],
                method=run["method"],
                seed=run["seed"],
                reference_unserved=seed,
                validated_unserved=run["upper"],
                global_lower=run["global_lower"],
                first_native_seconds=first,
                last_improvement_seconds=improvements[-1][0] if improvements else None,
                clock_origin=origin,
                improvements=len(improvements),
                improvement_history=improvements,
                last_bound_event=bounds[-1] if bounds else None,
                wall_seconds=run["wall_seconds"],
                model_seconds=r.get("model_seconds", r.get("model_build_seconds")),
                network_seconds=r.get("network_seconds"),
                variables=r.get("variables", r.get("model_stats")),
                rows=r.get("rows"),
                root_lp_complete_seconds=r.get("root_lp_complete_seconds"),
                peak_rss=run["peak_rss"],
                failure=failure,
            )
        )
    (root / "progress_analysis.json").write_text(json.dumps(rows, indent=2) + "\n")
    with (root / "progress.csv").open("w") as f:
        writer = csv.DictWriter(
            f, fieldnames=["run", "clock_origin", "seconds", "kind", "value"]
        )
        writer.writeheader()
        writer.writerows(history)
    return rows, history


def plots(root, rows, history):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    for case in ("R0", "R2"):
        trials = [
            r
            for r in rows
            if r["case"] == case
            and r["method"] in ("phase_arc_flow", "cp_sat", "cp_sat_all_stop")
        ]
        if not trials:
            continue
        fig, axes = plt.subplots(
            len(trials), 1, figsize=(9, 2.5 * len(trials)), squeeze=False
        )
        for ax, r in zip(axes[:, 0], trials):
            events = [
                e for e in history if e["run"] == r["run"] and e["kind"] == "native_ub"
            ]
            xs = [0]
            ys = [r["reference_unserved"]]
            for e in events:
                xs.append(e["seconds"])
                ys.append(min(ys[-1], e["value"]))
            if r["clock_origin"] == "worker":
                end = r["wall_seconds"]
            else:
                end = max(
                    xs[-1],
                    (r["wall_seconds"] or 0)
                    - (r["model_seconds"] or 0)
                    - (r["network_seconds"] or 0),
                )
            xs.append(end)
            ys.append(ys[-1])
            ax.step(xs, ys, where="post", label="Best valid U (including reference)")
            ax.set(
                title=f"{case}: {r['method']}, seed {r['seed']}",
                ylabel="Unserved",
                xlabel=f"Seconds from {r['clock_origin']} start"
                + (" (end approximate)" if r["clock_origin"] == "search" else ""),
            )
            ax.grid(alpha=0.25)
            ax.legend(loc="best")
        fig.tight_layout()
        fig.savefig(root / f"{case}_progress.png", dpi=160)
        fig.savefig(root / f"{case}_progress.svg")
        plt.close(fig)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("output_dir", type=Path)
    p.add_argument("--plots", action="store_true")
    a = p.parse_args()
    rows, history = analyze(a.output_dir)
    if a.plots:
        plots(a.output_dir, rows, history)


if __name__ == "__main__":
    main()
