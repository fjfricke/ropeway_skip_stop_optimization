"""Read-only evaluation of paired pattern/global searches; never pools local bounds."""

import json
import re
from collections import Counter
from pathlib import Path

from ..optimization.ddd.cp_sat_certificate import atomic_json


def incumbent_curve(result, events):
    best = result["seed_unserved"]
    curve = [(0.0, best)]
    for event in events:
        if event.get("kind") == "incumbent" and event.get("unserved", best) >= 0:
            value = event.get("unserved", best)
            if value < best:
                best = value
                curve.append(
                    (event.get("run_elapsed_seconds", event["elapsed_seconds"]), best)
                )
    if result["unserved_upper_bound"] < best:
        curve.append((result["search_wall_seconds"], result["unserved_upper_bound"]))
    return curve


def paired_verdict(rows):
    pairs = []
    for k in (38, 39):
        for seed in (0, 1):
            v = next(
                (
                    r
                    for r in rows
                    if (r["stage"], r["cabins"], r["seed"], r["method"])
                    == ("campaign", k, seed, "vns")
                ),
                None,
            )
            c = next(
                (
                    r
                    for r in rows
                    if (r["stage"], r["cabins"], r["seed"], r["method"])
                    == ("campaign", k, seed, "cp_sat")
                ),
                None,
            )
            if not v or not c:
                continue
            if (
                v["domain"] != c["domain"]
                or v["initial_unserved"] != c["initial_unserved"]
            ):
                raise ValueError("paired experiment domains or initial service differ")
            target = c["final_unserved"]
            tv = next((t for t, u in v["curve"] if u <= target), None)
            tc = next((t for t, u in c["curve"] if u <= target), None)
            # An unchanged common seed is not evidence of a speed advantage.
            faster = (
                target < c["initial_unserved"]
                and tv is not None
                and tc is not None
                and tc > 0
                and tv <= tc / 2
            )
            pairs.append(
                dict(
                    cabins=k,
                    seed=seed,
                    vns_unserved=v["final_unserved"],
                    cp_sat_unserved=target,
                    strictly_better=v["final_unserved"] < target,
                    twice_as_fast=bool(faster),
                    vns_seconds_to_cp_final=tv,
                    cp_seconds_to_final=tc,
                )
            )
    promising = []
    for k in (38, 39):
        by_k = [p for p in pairs if p["cabins"] == k]
        if len(by_k) == 2 and (
            all(p["strictly_better"] for p in by_k)
            or all(p["twice_as_fast"] for p in by_k)
        ):
            promising.append(k)
    complete = len(pairs) == 4
    return dict(
        complete=complete,
        status=("PROMISING" if promising else "NOT_DEMONSTRATED")
        if complete
        else "PENDING",
        promising_cabins=promising,
        pairs=pairs,
    )


def build_report(output, *, report_md=None):
    output = Path(output)
    rows = []
    for path in sorted(output.glob("*/*/result.json")):
        if path.parent.parent.name not in ("screen", "campaign"):
            continue
        # Do not interpret an outcome before its independent audit is complete.
        if not (path.parent / "completion.json").exists():
            continue
        r = json.loads(path.read_text())
        c = json.loads((path.parent / "config.json").read_text())
        events = [
            json.loads(s)
            for s in (path.parent / "events.jsonl").read_text().splitlines()
        ]
        complete = json.loads((path.parent / "completion.json").read_text())
        native = (path.parent / "solver.log").read_text()
        sections = re.split(r"PATTERN [0-9a-f]{64} budget=[^\n]+\n", native)[1:]
        unknown_sections = [s for s in sections if "status: UNKNOWN" in s]
        native_stats = dict(
            unknown_calls=len(unknown_sections),
            unknown_stopped_after_presolve=sum(
                "Stopped after presolve." in s for s in unknown_sections
            ),
        )
        evaluations = [e for e in events if e.get("kind") == "pattern_evaluated"]
        initial_id = next((e["pattern_id"] for e in events if e.get("initial")), None)
        initial_improvements = [
            e["unserved"]
            for e in events
            if e.get("kind") == "incumbent" and e.get("pattern_id") == initial_id
        ]
        changed_improvements = [
            e
            for e in events
            if e.get("kind") == "incumbent"
            and e.get("pattern_id") not in (None, initial_id)
        ]
        rows.append(
            dict(
                stage=path.parent.parent.name,
                method=c["method"],
                cabins=c["cabins"],
                seed=c["seed"],
                domain=r["domain_manifest"],
                initial_unserved=r["seed_unserved"],
                final_unserved=r["unserved_upper_bound"],
                post_unserved=complete["post_unserved"],
                seconds=r["search_wall_seconds"],
                curve=incumbent_curve(r, events),
                distinct_patterns=r.get("distinct_patterns"),
                changed_valid_patterns=r.get("changed_valid_patterns"),
                initial_pattern_best=min(initial_improvements, default=None),
                changed_pattern_improvements=len(changed_improvements),
                oracle_status_counts=dict(Counter(e["status"] for e in evaluations)),
                oracle_timing=r.get("oracle_timing"),
                native_diagnostics=native_stats,
                model_stats=r["model_stats"],
                peak_rss_bytes=complete["peak_rss_bytes"],
                result_path=str(path),
            )
        )
    verdict = paired_verdict(rows)
    gate = (
        json.loads((output / "gate.json").read_text())
        if (output / "gate.json").exists()
        else None
    )
    completion = (
        json.loads((output / "completion.json").read_text())
        if (output / "completion.json").exists()
        else None
    )
    report = dict(
        schema="pattern_campaign_report_v1",
        gate=gate,
        completion=completion,
        verdict=verdict,
        rows=rows,
    )
    atomic_json(output / "analysis.json", report)
    lines = [
        "# Mustersuche: Implementierung und Ergebnisse",
        "",
        "Stand: 2026-09-10. Zielgröße: unbediente Personen. Alle aufgeführten Endfahrpläne wurden zusätzlich mit einer unabhängigen ganzzahligen EAN/Gurobi-Passagierzuordnung geprüft.",
        "",
        "## Ergebnisstand",
        "",
        f"Vergleichsurteil: **{verdict['status']}**. Abgeschlossene Paare: {len(verdict['pairs'])}/4.",
        "",
        "Das globale Lower Bound der Mustersuche bleibt 0; lokale Muster-Bounds werden nicht übertragen. Ein Vorteil der äußeren Suche ist von einer Verbesserung durch Timing desselben Musters zu unterscheiden.",
        "",
        "| Phase / Methode | K | Seed | Start U | Ende U | Nachprüfung U | Muster | Neue gültige Muster | Sekunden |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['stage']} / {r['method']} | {r['cabins']} | {r['seed']} | {r['initial_unserved']} | {r['final_unserved']} | {r['post_unserved']} | {r['distinct_patterns'] if r['distinct_patterns'] is not None else '—'} | {r['changed_valid_patterns'] if r['changed_valid_patterns'] is not None else '—'} | {r['seconds']:.2f} |"
        )
    lines += ["", "## Screeningdiagnose", ""]
    if gate:
        lines.append(
            f"Gate {'bestanden' if gate['passed'] else 'nicht bestanden'}: {gate['distinct_patterns']} verschiedene Muster; {gate['changed_valid_patterns']} neue gültige Muster. Vorgabe: mindestens 10 bzw. 2."
        )
    lines.append("")
    for r in rows:
        if r["stage"] == "screen":
            lines.append(
                f"- K{r['cabins']}: bestes Ergebnis im ursprünglichen Muster U={r['initial_pattern_best']}; {r['changed_pattern_improvements']} zusätzliche Bestverbesserungen durch ein anderes Muster. Oracle-Aufrufe: {r['oracle_status_counts']}. Median {r['oracle_timing']['median_seconds']:.2f} s, p95 {r['oracle_timing']['p95_seconds']:.2f} s; Peak-RSS {r['peak_rss_bytes'] / 2**30:.2f} GiB. UNKNOWN bereits nach Presolve beendet: {r['native_diagnostics']['unknown_stopped_after_presolve']}/{r['native_diagnostics']['unknown_calls']}."
            )
    lines += [
        "",
        "Die Spalte zur Verbesserung im ursprünglichen Muster trennt Timing-Nachoptimierung von der äußeren Suche. UNKNOWN ist kein Unmöglichkeitsnachweis.",
        "",
        "## Versuchsaufbau und Bewertung",
        "",
        "Fünf-Stationen-B-Fall, exakt K38/K39, feste Balanced-Reference-Starts, H=1200 s, Exit-Warten bis 1200 s bei 1 µs, acht Plätze, Nachfrage 3074. Kein Reservoir. Die 3074 Personen entsprechen 120 % der nachgewiesenen Kapazität eines festen All-Stop-38-Referenzfahrplans, nicht eines globalen All-Stop-Maximums.",
        "",
        "Kampagne: je K und Seeds 0/1 jeweils VNS und globales CP-SAT, 900 s inklusive Vorbereitung und 10 s Finalisierungsreserve, 12 Worker, sequenziell; Methodenreihenfolge bei Seed 1 umgekehrt. Identische eingefrorene Ausgangszertifikate (K38: 315, K39: 1426 unbedient). Screeningverbesserungen werden nicht als neue Kampagnenseeds verwendet. Nachbewertung wird separat ausgewiesen.",
        "",
        "Vielversprechend: Für mindestens ein K müssen beide VNS-Seeds bessere Endwerte liefern oder beide den finalen CP-SAT-Wert in höchstens halber Zeit erreichen. Zeitvergleich verwendet den tatsächlichen ersten Erreichungszeitpunkt, und ein unveränderter gemeinsamer Seed zählt nicht als Geschwindigkeitsvorteil. PENDING bedeutet ausdrücklich noch keine Aussage zugunsten einer Methode.",
        "",
        "## Code und Reproduktion",
        "",
        "- Implementierungsplan: `docs/plans/ddd_pattern_search.md`.",
        "- `src/ropeway_skip_stop_optimization/optimization/ddd/pattern_search.py`: Muster, Timing-Oracle, Cache und VNS.",
        "- `src/ropeway_skip_stop_optimization/benchmarking/pattern_search.py`: Laufadapter und unabhängige Prüfung.",
        "- `src/ropeway_skip_stop_optimization/benchmarking/pattern_search_report.py`: UB-Zeitkurven und Paarvergleich.",
        "- `benchmarks/run_pattern_search.py`: eingefrorene Worker, Gate und Kampagne.",
        "- `tests/test_ddd_pattern_search.py`: Oracle-, Suchsteuerungs- und Auswertungstests.",
        f"- Ergebnisordner: `{output}`.",
        "- `source.tar.gz`/`source_manifest.json`, `seeds/`, pro Lauf `config.json`, `domain.json`, `events.jsonl`, `solver.log`, `result.json`, `incumbent.json`, `independent_assignment.json`, `completion.json`.",
        "- `analysis.json` enthält alle UB-Zeitkurven, Paarmetriken und Diagnosewerte.",
        "",
        "Die ausführende Basis stammt aus dem Quellcodearchiv der abgeschlossenen Kapazitätskampagne plus dem neuen Piloten, da die Live-CP-Builder gleichzeitig in einem anderen Task verändert wurden. Der abgebrochene erste Start `pattern_search_20260910/` ist ungültig; ausgewertet wird ausschließlich `pattern_search_20260910_v2/`.",
    ]
    text = "\n".join(lines) + "\n"
    (output / "comparison.md").write_text(text)
    if report_md:
        Path(report_md).write_text(text)
    return report
