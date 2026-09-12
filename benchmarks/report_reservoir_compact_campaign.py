"""Decision rules for the compact campaign; unavailable evidence stays unknown."""

import argparse
import csv
import json
import re
from pathlib import Path


def gap(row):
    if row.get("upper") is None or row.get("lower") is None:
        return None
    return 100 * max(0, row["upper"] - max(0, row["lower"])) / max(1, abs(row["upper"]))


def reach(row, target_upper, target_lower):
    for event in row.get("progress", []):
        if (
            event["upper"] is not None
            and event["upper"] <= target_upper
            and event["lower"] >= target_lower - 1e-6
        ):
            return event["seconds"]
    return None


def assess(records, profile):
    by_name = {r["run"]: r for r in records}
    comparisons = []
    for seed in (1, 2):
        new = by_name.get(f"R2_{profile}_s{seed}")
        old = by_name.get(f"R2_L_s{seed}")
        if (
            not new
            or not old
            or new["upper"] is None
            or old["upper"] is None
            or new.get("failure")
            or old.get("failure")
        ):
            comparisons.append(
                dict(seed=seed, confirmed=False, reason="missing or invalid comparison")
            )
            continue
        served = old["upper"] - new["upper"]
        gn, go = gap(new), gap(old)
        gain = go - gn if gn is not None and go is not None else None
        quality = served >= 10 or served >= 0 and gain is not None and gain >= 1
        old_time = new_time = None
        speed = False
        if old["lower"] is not None and new["lower"] is not None:
            target = max(0, old["lower"])
            old_time = reach(old, old["upper"], target)
            new_time = reach(new, old["upper"], target)
            speed = (
                served >= 0
                and max(0, new["lower"]) >= target - 1e-6
                and old_time is not None
                and old_time > 0
                and new_time is not None
                and new_time <= 0.8 * old_time
            )
        quality = quality or speed
        comparisons.append(
            dict(
                seed=seed,
                additional_served=served,
                gap_percentage_point_gain=gain,
                confirmed=quality,
                time_criterion=speed,
                legacy_reach_seconds=old_time,
                new_reach_seconds=new_time,
            )
        )
    return dict(
        profile=profile,
        recommendation=all(c["confirmed"] for c in comparisons),
        comparisons=comparisons,
        bound_scope="restricted_phase_network",
        standard_changed=False,
    )


def write_progress(directory, records, plot=False):
    with (directory / "progress.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["run", "seconds", "upper", "lower"])
        writer.writeheader()
        for row in records:
            for event in row.get("progress", []):
                writer.writerow(dict(run=row["run"], **event))
    if not plot:
        return
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(3, 2, figsize=(12, 10), constrained_layout=True)
    selections = [
        ("R0 Screening", lambda name: name.startswith("R0_")),
        ("R2 Screening", lambda name: name.startswith("R2_") and name.endswith("_s0")),
        (
            "R2 Bestätigung",
            lambda name: name.startswith("R2_") and not name.endswith("_s0"),
        ),
    ]
    colors = dict(zip(("L", "P1", "P2", "I", "K", "R", "C"), plt.cm.tab10.colors))
    for pair, (title, selected) in zip(axes, selections):
        for axis, key, label in zip(
            pair, ("upper", "lower"), ("Unbediente Personen (UB)", "Lokale Untergrenze")
        ):
            for row in records:
                if not selected(row["run"]):
                    continue
                points = [p for p in row.get("progress", []) if p.get(key) is not None]
                if not points:
                    continue
                _, profile, seed = row["run"].split("_")
                axis.step(
                    [p["seconds"] for p in points],
                    [p[key] for p in points],
                    where="post",
                    label=f"{profile} {seed}"
                    + (" (abgebrochen)" if row.get("failure") else ""),
                    color=colors[profile],
                    linestyle="--" if seed == "s2" else "-",
                    linewidth=1.5,
                )
            axis.set(
                title=f"{title}: {label}",
                xlabel="Gesamtzeit inkl. Aufbau [s]",
                ylabel="Personen",
            )
            axis.grid(alpha=0.2)
            if axis.lines:
                maximum = max(float(v) for line in axis.lines for v in line.get_ydata())
                axis.set_ylim(0, max(1, maximum * 1.1))
                axis.ticklabel_format(axis="y", style="plain", useOffset=False)
                axis.legend(fontsize=7, ncol=3)
    fig.suptitle(
        "Kompakter Reservoir-Arc-Flow — Bounds nur für das eingeschränkte Zeitnetz"
    )
    fig.savefig(directory / "progress.svg")
    fig.savefig(directory / "progress.png", dpi=160)
    plt.close(fig)


def write_root_crossover(directory, records):
    import matplotlib.pyplot as plt

    data = []
    fig, axis = plt.subplots(figsize=(9, 4.5), constrained_layout=True)
    for row in records:
        if (
            not row["run"].startswith("R2_")
            or row["run"].endswith("_s0")
            or not row.get("directory")
        ):
            continue
        log = (Path(row["directory"]) / "process.log").read_text()
        points = [
            (float(t), int(n))
            for n, t in re.findall(
                r"^\s*(\d+) PPushes remaining.*?\s([\d.]+)s\s*$", log, re.MULTILINE
            )
        ]
        if not points:
            continue
        _, profile, seed = row["run"].split("_")
        axis.plot(
            [t for t, n in points],
            [n for t, n in points],
            label=f"{profile} {seed}",
            color="tab:green" if profile == "P2" else "tab:blue",
            linestyle="--" if seed == "s2" else "-",
        )
        for (previous_t, previous_n), (t, n) in zip(points, points[1:]):
            if n > previous_n:
                axis.annotate(
                    "Crossover-Neustart",
                    xy=(t, n),
                    xytext=(t - 65, n - 35000),
                    fontsize=8,
                    arrowprops={"arrowstyle": "->", "color": "tab:blue"},
                )
        data.extend(
            dict(run=row["run"], solver_seconds=t, remaining_ppushes=n)
            for t, n in points
        )
    axis.set(
        title="R2: Crossover-Fortschritt – keine Fahrplanverbesserung",
        xlabel="Gurobi-Solverzeit [s]",
        ylabel="Verbleibende Crossover-Schritte (PPush)",
    )
    axis.set_ylim(bottom=-5000)
    axis.grid(alpha=0.2)
    axis.ticklabel_format(axis="y", style="plain", useOffset=False)
    if axis.lines:
        axis.legend()
    fig.savefig(directory / "root_crossover.svg")
    fig.savefig(directory / "root_crossover.png", dpi=160)
    plt.close(fig)
    with (directory / "root_crossover.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=["run", "solver_seconds", "remaining_ppushes"]
        )
        writer.writeheader()
        writer.writerows(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--plot", action="store_true")
    a = parser.parse_args()
    selection = (
        json.loads((a.directory / "selection.json").read_text())
        if (a.directory / "selection.json").exists()
        else {}
    )
    records = json.loads((a.directory / "comparison.json").read_text())
    write_progress(a.directory, records, plot=a.plot)
    if a.plot:
        write_root_crossover(a.directory, records)
    result = assess(records, selection.get("profile", "unknown"))
    (a.directory / "decision.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = [
        "# Compact architecture decision",
        "",
        f"Recommended by confirmed quality thresholds: **{result['recommendation']}**.",
        "",
        "No standard switch. Size reductions and root progress are structural evidence; they are not counted as native capacity improvements.",
        "",
    ]
    for c in result["comparisons"]:
        lines.append(f"- Seed {c['seed']}: {c}")
    lines += [
        "",
        "The decision does not imply superiority to global All-Stop capacity.",
    ]
    (a.directory / "decision.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
