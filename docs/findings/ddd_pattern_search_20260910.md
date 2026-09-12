# Mustersuche: Implementierung und Ergebnisse

**Pausiert auf Nutzerwunsch.** Fortsetzung als gezielte Oracle-Diagnose: [aktueller Bericht](ddd_pattern_oracle_diagnostic_20260910.md). Der alte automatische Berichtsprozess wurde gestoppt.

Stand: 2026-09-10. Zielgröße: unbediente Personen. Alle aufgeführten Endfahrpläne wurden zusätzlich mit einer unabhängigen ganzzahligen EAN/Gurobi-Passagierzuordnung geprüft.

## Ergebnisstand

Vergleichsurteil: **PENDING**. Abgeschlossene Paare: 1/4.

Das globale Lower Bound der Mustersuche bleibt 0; lokale Muster-Bounds werden nicht übertragen. Ein Vorteil der äußeren Suche ist von einer Verbesserung durch Timing desselben Musters zu unterscheiden.

| Phase / Methode | K | Seed | Start U | Ende U | Nachprüfung U | Muster | Neue gültige Muster | Sekunden |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| campaign / cp_sat | 38 | 0 | 315 | 315 | 315 | — | — | 890.93 |
| campaign / vns | 38 | 0 | 315 | 315 | 315 | 190 | 0 | 890.38 |
| screen / vns | 38 | 0 | 315 | 315 | 315 | 25 | 0 | 110.34 |
| screen / vns | 39 | 0 | 1426 | 1418 | 1418 | 15 | 2 | 110.22 |

## Screeningdiagnose

Gate bestanden: 40 verschiedene Muster; 2 neue gültige Muster. Vorgabe: mindestens 10 bzw. 2.

- K38: bestes Ergebnis im ursprünglichen Muster U=315; 0 zusätzliche Bestverbesserungen durch ein anderes Muster. Oracle-Aufrufe: {'UNKNOWN': 19, 'INFEASIBLE': 10}. Median 4.46 s, p95 5.81 s; Peak-RSS 0.90 GiB. UNKNOWN bereits nach Presolve beendet: 19/19.
- K39: bestes Ergebnis im ursprünglichen Muster U=1418; 0 zusätzliche Bestverbesserungen durch ein anderes Muster. Oracle-Aufrufe: {'FEASIBLE': 3, 'UNKNOWN': 14}. Median 5.04 s, p95 15.05 s; Peak-RSS 1.06 GiB. UNKNOWN bereits nach Presolve beendet: 0/14.

Die Spalte zur Verbesserung im ursprünglichen Muster trennt Timing-Nachoptimierung von der äußeren Suche. UNKNOWN ist kein Unmöglichkeitsnachweis.

## Versuchsaufbau und Bewertung

Fünf-Stationen-B-Fall, exakt K38/K39, feste Balanced-Reference-Starts, H=1200 s, Exit-Warten bis 1200 s bei 1 µs, acht Plätze, Nachfrage 3074. Kein Reservoir. Die 3074 Personen entsprechen 120 % der nachgewiesenen Kapazität eines festen All-Stop-38-Referenzfahrplans, nicht eines globalen All-Stop-Maximums.

Kampagne: je K und Seeds 0/1 jeweils VNS und globales CP-SAT, 900 s inklusive Vorbereitung und 10 s Finalisierungsreserve, 12 Worker, sequenziell; Methodenreihenfolge bei Seed 1 umgekehrt. Identische eingefrorene Ausgangszertifikate (K38: 315, K39: 1426 unbedient). Screeningverbesserungen werden nicht als neue Kampagnenseeds verwendet. Nachbewertung wird separat ausgewiesen.

Vielversprechend: Für mindestens ein K müssen beide VNS-Seeds bessere Endwerte liefern oder beide den finalen CP-SAT-Wert in höchstens halber Zeit erreichen. Zeitvergleich verwendet den tatsächlichen ersten Erreichungszeitpunkt, und ein unveränderter gemeinsamer Seed zählt nicht als Geschwindigkeitsvorteil. PENDING bedeutet ausdrücklich noch keine Aussage zugunsten einer Methode.

## Code und Reproduktion

- Implementierungsplan: `docs/plans/ddd_pattern_search.md`.
- `src/ropeway_skip_stop_optimization/optimization/ddd/pattern_search.py`: Muster, Timing-Oracle, Cache und VNS.
- `src/ropeway_skip_stop_optimization/benchmarking/pattern_search.py`: Laufadapter und unabhängige Prüfung.
- `src/ropeway_skip_stop_optimization/benchmarking/pattern_search_report.py`: UB-Zeitkurven und Paarvergleich.
- `benchmarks/run_pattern_search.py`: eingefrorene Worker, Gate und Kampagne.
- `tests/test_ddd_pattern_search.py`: Oracle-, Suchsteuerungs- und Auswertungstests.
- Ergebnisordner: `/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/pattern_search_20260910_v2`.
- `source.tar.gz`/`source_manifest.json`, `seeds/`, pro Lauf `config.json`, `domain.json`, `events.jsonl`, `solver.log`, `result.json`, `incumbent.json`, `independent_assignment.json`, `completion.json`.
- `analysis.json` enthält alle UB-Zeitkurven, Paarmetriken und Diagnosewerte.

Die ausführende Basis stammt aus dem Quellcodearchiv der abgeschlossenen Kapazitätskampagne plus dem neuen Piloten, da die Live-CP-Builder gleichzeitig in einem anderen Task verändert wurden. Der abgebrochene erste Start `pattern_search_20260910/` ist ungültig; ausgewertet wird ausschließlich `pattern_search_20260910_v2/`.
