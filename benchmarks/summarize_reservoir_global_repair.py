"""Summarize the passenger/global-neighborhood ablation without promoting local bounds."""

import argparse
import csv
import json
from pathlib import Path


def summarize(root, output):
    campaign = json.loads((root / "campaign.json").read_text())
    rows = []
    curves = []
    start = campaign["seed_value"]
    bound = campaign["global_lower_bound"]
    for case in campaign["cases"]:
        result = case["result"]
        if (
            result.get("problem_fingerprint", campaign["problem_fingerprint"])
            != campaign["problem_fingerprint"]
        ):
            raise ValueError("mixed physical domains")
        events = result.get("events", [])
        if not events and (root / case["name"] / "events.jsonl").exists():
            events = [
                json.loads(line)
                for line in (root / case["name"] / "events.jsonl")
                .read_text()
                .splitlines()
                if line.strip()
            ]
        best = start
        improvements = []
        for e in events:
            candidate = e.get("validated_upper_bound")
            if e.get("kind") == "incumbent":
                candidate = e["objective_raw"] / 1e6
            if candidate is not None and candidate < best - 1e-6:
                best = candidate
                improvements.append((e["elapsed_seconds"], best))
        curves.append((case["name"], 0, start))
        curves.extend((case["name"], t, v) for t, v in improvements)
        curves.append(
            (case["name"], case["actual_seconds"], result["validated_upper_bound"])
        )
        size = result.get("model_stats", result)
        rows.append(
            dict(
                case=case["name"],
                engine=case["engine"],
                seed=case["seed"],
                selection=case["selection"],
                completed=case["return_code"] == 0
                and not result.get("incomplete")
                and not case["sleep_or_clock_discrepancy"],
                status=result.get("status", result.get("solver_status")),
                upper_bound=result["validated_upper_bound"],
                gain=start - result["validated_upper_bound"],
                global_lower_bound=bound,
                gap_percent=100
                * (result["validated_upper_bound"] - bound)
                / result["validated_upper_bound"],
                variables=size.get("variables"),
                constraints=size.get("constraints"),
                actual_seconds=case["civil_wall_seconds"],
                peak_gib=case["peak_sampled_rss_bytes"] / 1024**3,
                improvements=len(improvements),
                last_improvement_seconds=improvements[-1][0] if improvements else None,
            )
        )
    output.mkdir(exist_ok=False)
    with (output / "comparison.csv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (output / "progress.csv").open("w") as f:
        writer = csv.writer(f)
        writer.writerow(["case", "elapsed_seconds", "upper_bound"])
        writer.writerows(curves)
    lines = [
        "# Freie Passagiere und Konfliktnachbarschaften: Vergleich",
        "",
        f"Gemeinsamer Startwert: {start:.6f}. Globale externe LB: {bound:.6f}.",
        "Lokale Bounds sind keine globalen Bounds. Seedübernahme zählt nicht als Verbesserung.",
        "",
        "| Lauf | Status | Kosten | Gewinn | Variablen | Zeit s | Peak GiB |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['case']} | {r['status']} | {r['upper_bound']:.6f} | {r['gain']:.6f} | {r['variables']} | {r['actual_seconds']:.2f} | {r['peak_gib']:.2f} |"
        )
    lines.extend(
        [
            "",
            f"Bestätigter Performancevorteil: **{campaign.get('performance_recommendation', False)}**.",
            f"Gesamte Wandzeit: {campaign['elapsed_seconds']:.2f} Sekunden; Budget 1800 Sekunden.",
            "Schwelle: mindestens 0.1% bessere Kosten als beide Kontrollen, in beiden zusätzlichen Seeds.",
            "CP-Zwischenwerte sind native Solverwerte; Endpläne sind unabhängig validiert. Lokale Verbesserungen werden vor Akzeptanz unabhängig geprüft.",
        ]
    )
    (output / "report.md").write_text("\n".join(lines) + "\n")
    (output / "summary.json").write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--campaign", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    a = p.parse_args()
    summarize(a.campaign, a.output_dir)
