"""Summarize validated objective comparisons without launching optimization."""

import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    args = parser.parse_args()
    root = args.campaign
    campaign = json.loads((root / "campaign.json").read_text())
    rows = []
    fig, axes = plt.subplots(1, 3, figsize=(15, 4), constrained_layout=True)
    for entry in campaign["runs"]:
        folder = root / entry["name"]
        result_file = folder / "result.json"
        if not result_file.exists():
            continue
        result = json.loads(result_file.read_text())
        plan = json.loads((folder / "best.json").read_text())
        metrics = result["metrics"]
        trips = plan["plan"]["trips"]
        events = [
            json.loads(line)
            for line in (folder / "events.jsonl").read_text().splitlines()
        ]
        points = [e for e in events if e["kind"] == "accepted_insertion"]
        objective = result["config"]["objective"]
        seed = result["config"]["seed"]
        label = f"{objective}, seed {seed}"
        color = "tab:blue" if objective == "unserved" else "tab:orange"
        style = "-" if seed == 0 else "--"
        x = [p["elapsed_seconds"] for p in points]
        for ax, ys in zip(
            axes,
            (
                [p["served"] for p in points],
                [p["journey_time_tick"] / 1e6 for p in points],
                [p["fleet_size"] for p in points],
            ),
        ):
            ax.step(x, ys, where="post", label=label, color=color, linestyle=style)
        rows.append(
            {
                "objective": objective,
                "seed": seed,
                "served": metrics["served"],
                "fleet": metrics["used_fleet"],
                "time_cost_person_seconds": metrics["journey_time_tick"] / 1e6,
                "waiting_seconds": sum(sum(t["wait_ticks"]) for t in trips) / 1e6,
                "skip_visits": sum(
                    "_skip_" in oid for t in trips for oid in t["route_option_ids"]
                ),
                "visits": sum(len(t["route_option_ids"]) for t in trips),
                "wall_seconds": result["runner_total_wall_seconds"],
                "last_improvement_seconds": points[-1]["elapsed_seconds"]
                if points
                else None,
                "termination": result["termination"],
                "optimal_insertions": sum(
                    s["status"] == "OPTIMAL" for s in result["steps"]
                ),
                "insertions": len(result["steps"]),
            }
        )
    axes[0].axhline(
        2496, color="gray", linestyle=":", label="Recorded All-Stop reference"
    )
    for ax, title in zip(
        axes,
        ("Validated service", "Time cost including unserved penalty", "Accepted fleet"),
    ):
        ax.set_title(title)
        ax.set_xlabel("Elapsed seconds")
        ax.grid(alpha=0.2)
    axes[0].legend(fontsize=7)
    axes[1].set_ylabel("Person-seconds")
    fig.savefig(root / "progress.png", dpi=160)
    plt.close(fig)
    if rows:
        with (root / "comparison.csv").open("w") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    lines = [
        "# Greedy objective comparison, corrected free STOP/SKIP domain",
        "",
        f"Campaign status: {campaign['status']}.",
        "",
        "R2, 3074 people; CP-SAT; 120 seconds per run, seeds 0/1. Existing movements remain frozen.",
        "The first Greedy campaign inherited ALL_STOP and is excluded as a free STOP/SKIP baseline.",
        "",
        "| Objective | Seed | Served | K | Time cost (person-s) | Waiting (s) | SKIP visits | Wall (s) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['objective']} | {r['seed']} | {r['served']} | {r['fleet']} | {r['time_cost_person_seconds']:.1f} | {r['waiting_seconds']:.1f} | {r['skip_visits']}/{r['visits']} | {r['wall_seconds']:.1f} |"
        )
    lines += [
        "",
        "![Progress](progress.png)",
        "",
        "Time cost uses arrival minus release for served people and horizon minus release for unserved people. It is not mean journey time among served passengers. Capacity-run passenger assignments are optimized for service; their recorded time cost is not asserted to be the best assignment cost on those fixed trajectories. No post-evaluation is backdated into the search curve.",
        "",
        "Only independently validated accepted insertions are plotted. Model-local insertion bounds are not global fleet bounds. The stored termination field can contain FEASIBLE when budget expires after accepting a feasible insertion; inspect wall time and step statuses before interpreting it as a stop reason. Two short seeds do not establish general performance superiority.",
    ]
    (root / "report.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
