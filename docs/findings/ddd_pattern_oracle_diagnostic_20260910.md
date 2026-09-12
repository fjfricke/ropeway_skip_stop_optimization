# Diagnose: festes Muster, freies Timing

Sechs eingefrorene Muster, zwei Solver, jeweils ein zusammenhängender Lauf bis 300 s einschließlich Modellbau. Zeiten und Warten bleiben auf demselben 1-µs-Gitter; Ziel ist die Zahl unbedienter Personen. Alle Bounds gelten ausschließlich für das jeweilige Muster.

| K | Muster | Solver | Status | U | lokales LB | Bau s | Erste native Lösung s | Gesamt s |
|---|---|---|---|---:|---:|---:|---:|---:|
| 38 | original | cp_sat | OPTIMAL | 315 | 315 | 4.76 | 21.63 | 24.03 |
| 38 | original | gurobi | OPTIMAL | 315 | 315 | 16.49 | 17.14 | 234.28 |
| 38 | variant1 | cp_sat | INFEASIBLE | — | — | 1.53 | — | 12.36 |
| 38 | variant1 | gurobi | TIME_LIMIT | — | 314 | 14.61 | — | 300.23 |
| 38 | variant2 | cp_sat | INFEASIBLE | — | — | 1.58 | — | 2.32 |
| 38 | variant2 | gurobi | TIME_LIMIT | — | 314 | 14.18 | — | 300.32 |
| 39 | original | cp_sat | FEASIBLE | 1410 | 1369 | 2.88 | 8.34 | 300.20 |
| 39 | original | gurobi | TIME_LIMIT | 1418 | 1386 | 8.48 | 8.79 | 300.78 |
| 39 | variant1 | cp_sat | UNKNOWN | — | 1377 | 1.26 | — | 300.22 |
| 39 | variant1 | gurobi | TIME_LIMIT | — | 1401 | 7.01 | — | 300.49 |
| 39 | variant2 | cp_sat | UNKNOWN | — | 1369 | 0.78 | — | 300.33 |
| 39 | variant2 | gurobi | TIME_LIMIT | — | 1416 | 4.85 | — | 300.18 |

## Abschlussbewertung

Alle zwölf Läufe sind abgeschlossen, ohne Ausführungsfehler. Alle vier zurückgegebenen
Endfahrpläne (zwei Originalmuster × zwei Backends) wurden unabhängig mit EAN/Gurobi
nachoptimiert und bestätigt. Für alle sechs Paare stimmen Domain-Manifest und Muster-ID
überein.

| Muster | CP-SAT | Gurobi | Befund |
|---|---|---|---|
| K38 Original | U=LB=315 nach 24,03 s | U=LB=315 nach 234,28 s | CP schneller beim Beweis |
| K38 Variante 1 | INFEASIBLE nach 12,36 s | nach 300 s keine Lösung/kein Unzulässigkeitsbeweis | früheres UNKNOWN durch mehr Zeit aufgelöst |
| K38 Variante 2 | INFEASIBLE nach 2,32 s | nach 300 s keine Lösung/kein Unzulässigkeitsbeweis | CP deutlich besser beim Unzulässigkeitsnachweis |
| K39 Original | U=1410, LB=1369 | U=1418, LB=1386 | CP besseres U, MIP stärkeres lokales LB |
| K39 Variante 1 | UNKNOWN nach 300 s | nach 300 s keine Lösung | früheres gültiges Muster nicht wiedergefunden |
| K39 Variante 2 | UNKNOWN nach 300 s | nach 300 s keine Lösung | früheres gültiges Muster nicht wiedergefunden |

Beim K39-Original erreichte CP-SAT U=1410 bereits nach 14,98 s und verbesserte dieses U
bis zum Laufende nicht weiter. Gurobi erreichte U=1418 nach 215,39 s. Die bisherige
Startlösung hatte U=1426. Für genau dieses Muster lassen sich die geprüfte CP-Lösung
und der Gurobi-Bound kombinieren: **1386 ≤ Optimum ≤ 1410**, Abstand 24 Personen.
Dies beruht auf zwei separaten 300-s-Läufen; kein globaler Bound über Stop/Skip-Muster.

### Einschränkung des Vergleichs mit dem früheren Screening

Die Solver-Paare dieses Experiments sind untereinander vergleichbar. Der Vergleich
„5 s früher gegen 300 s jetzt“ verändert allerdings zusätzlich die Hint-Strategie:

- Das alte VNS-Oracle übertrug auch bei geändertem Muster unverbindliche **Zeit-Hints**
  des aktuellen Fahrplans.
- Der neue Diagnosevergleich verwendete für geänderte Muster **gar keine Hints**.
  Vollständige Hints und Objective-Cutoff wurden nur bei passendem Muster verwendet.
- Die beiden K39-Varianten waren im alten Screening mit Zeit-Hints jeweils FEASIBLE
  bei U=1426. Die jetzigen UNKNOWN-Ergebnisse beweisen daher keine Unzulässigkeit und
  zeigen auch nicht, dass längere Laufzeit grundsätzlich nichts bringt.
- Unterschiedliche Hint-Strategie und die nicht deterministische parallele Suche sind
  mögliche Erklärungen. Der ursächliche Anteil ist mit diesen Läufen nicht isoliert.

Das war eine relevante Einschränkung unseres Versuchsaufbaus. Falls weitere Oracle-Tests
folgen, sollten sie zunächst dieselben K39-Muster mit/ohne exakt denselben Zeit-Hints
vergleichen und **jedes gültige Muster samt Timing und Passagierzuordnung speichern**.
Im alten Screening wurden die nicht besten Musterzertifikate nicht dauerhaft exportiert.

### Konsequenz

CP-SAT bleibt nach diesem Vergleich das bevorzugte Timing-/Feasibility-Oracle. Die hier
getestete paarweise MIP-Formulierung rechtfertigt keinen vollständigen Backendwechsel:
Sie erzeugt etwa 339.000–561.000 Variablen, während CP-SAT etwa 48.000–50.000 benötigt.
Das ist eine Aussage über diese Formulierungen und Stichprobe, kein allgemeines Urteil
über Gurobi oder MIP.

Fünf Sekunden sind kein belastbares universelles Oracle-Budget. Unbegrenzte Läufe sind
umgekehrt auch nicht durch diese Ergebnisse gerechtfertigt. Die alte VNS-Kampagne bleibt
pausiert. Vor einer weiteren großen Mustersuche sind die Hint-Abhängigkeit und die
Erzeugung physikalisch sinnvoller Muster zu klären. Ein ML-Ausbau ist damit noch nicht
begründet.

## Messpunkte im selben Lauf

| K / Muster / Solver | 5 s U / LB | 30 s U / LB | 60 s U / LB | 300 s U / LB |
|---|---:|---:|---:|---:|
| 38 / original / cp_sat | 315 / — | 315 / 315 | 315 / 315 | 315 / 315 |
| 38 / original / gurobi | 315 / — | 315 / — | 315 / — | 315 / 315 |
| 38 / variant1 / cp_sat | — / — | — / — | — / — | — / — |
| 38 / variant1 / gurobi | — / — | — / — | — / — | — / 314 |
| 38 / variant2 / cp_sat | — / — | — / — | — / — | — / — |
| 38 / variant2 / gurobi | — / — | — / — | — / — | — / 0 |
| 39 / original / cp_sat | 1426 / — | 1410 / 1361 | 1410 / 1363 | 1410 / 1369 |
| 39 / original / gurobi | 1426 / — | 1426 / — | 1426 / 1359 | 1418 / 1386 |
| 39 / variant1 / cp_sat | — / — | — / 1367 | — / 1367 | — / 1377 |
| 39 / variant1 / gurobi | — / — | — / — | — / — | — / 1401 |
| 39 / variant2 / cp_sat | — / 1367 | — / 1367 | — / 1367 | — / 1369 |
| 39 / variant2 / gurobi | — / — | — / — | — / — | — / 1408 |

Eine Startlösung zählt ab ihrer Prüfung als bekanntes U. „Erste native Lösung“ misst separat, wann der Solver selbst ein validiertes Ergebnis liefert. Bei geänderten Mustern wird ein nicht passender Ausgangsfahrplan weder als Lösung noch als Zielfunktionsschranke übernommen. Beide Solver bekommen bei passenden Mustern auch die deterministisch abgeleiteten Hilfsvariablen als Startwerte.

CP-SAT verwendet die bisherige physikalische Formulierung mit fixierten Routen. Gurobi baut nur die gewählten Routen, ganzzahlige Ereigniszeiten/Wartezeiten und optionale paarweise Ressourcenreihenfolgen auf. Unmögliche Besuche werden anhand frühester Ankunftszeiten entfernt; es wird keine Ressourcenreihenfolge aus dem Seed fixiert. Der Vergleich betrifft somit zwei Formulierungen desselben Teilproblems, nicht ausschließlich den Solverwechsel.

Vorgegebene Muster: Originale aus den gemeinsamen Kampagnenseeds; K38 eine UNKNOWN- und eine INFEASIBLE-Änderung aus dem Screening; K39 die zwei damals FEASIBLE-Änderungen. Auswahl vor dem Vergleich eingefroren, kein nachträgliches Aussuchen guter Resultate.

Ergebnisse: `/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/pattern_oracle_diagnostic_20260910`. Pro Lauf: Domain, Konfiguration, Ereignisse, native Logs, Checkpoint, Ergebnis und unabhängige EAN/Gurobi-Passagierprüfung. `summary.json` enthält die Messpunkte und Rohresultate. `patterns.json` enthält die exakten Muster.

Code: `optimization/ddd/pattern_oracle_probe.py`, `optimization/ddd/pattern_mip.py`, `benchmarks/run_pattern_oracle_diagnostic.py`. Der vorherige VNS-Lauf ist pausiert; dessen Ergebnisse sind unter `pattern_search_20260910_v2` erhalten.
