# Reservoir capacity phase pilot — 11 September 2026

Status: campaign in progress. The final decision and remaining runs must be
read from the campaign artifacts, not inferred from this interim document.

Implementation and proof contract:
[phase model and global capacity bound](../reference/reservoir_capacity_phase_arc_flow.md).

## Frozen experiment

Results: `benchmarks/output/reservoir_capacity_campaign_20260911_v1/`.
The directory contains the frozen sources and hashes, engine versions,
independently checked references, full logs and per-process supervision.
All search jobs are sequential. The campaign's hard budget is 3600 seconds;
the initial 67-test correctness suite (24.36 seconds) is outside that budget.

R0 preserves the historical Max50/3074 single-use reservoir snapshot, with
waiting up to 1200 seconds. R2 keeps that physics and replaces demand with
the planned complementary markets and nine release buckets.

## Preparation: objective choice matters

Integer passenger assignment was solved to optimality for each fixed schedule:

| Fixed movement | Historical journey assignment U | Capacity-optimal assignment U |
|---|---:|---:|
| R0 historical Skip-Stop | 476 | 339 |
| R0 checked All-Stop reference | — | 285 |
| R2 historical Skip-Stop movements | — | 658 |
| R2 checked All-Stop reference | — | 578 |

On the unchanged historical R0 movement alone, changing passenger assignment
serves 137 extra people. This is not a new movement-search improvement.
The All-Stop reference has different movement times; its additional advantage
must not be attributed solely to passenger assignment. Both SS engines receive
the better common All-Stop reference: U=285 on R0 and U=578 on R2.

## Global All-Stop relaxation

The 60-second R2 relaxation has raw objective 124.51428571428323. Exact dyadic
dual evaluation with residual compensation certifies integer **U_AS >= 125**.
Thus at most **2949 of the specified 3074 R2 people** can be delivered by
All-Stop in this full single-use Max50 domain. A valid SS plan with U<=124
would prove greater service for this demand instance.

This does not imply that the largest fully serviceable nested All-Stop prefix
is 2949: partial service of D and complete service of a smaller prescribed
prefix are different quantities.

R0's coarse relaxation remains at zero. Both 15-second variants exhaust their
90-second budgets while constructing resource-window rows, before LP search.
Those incomplete models supply no new bound.

## Initial phase-search observations

| Case | Variables | Rows | Network s | Model s | Search outcome |
|---|---:|---:|---:|---:|---|
| R0 | 769834 | 752306 | 1.29 | 9.73 | Gurobi memory limit during root ordering; U=285 |
| R2 | 889209 | 826867 | 1.28 | 11.37 | Time limit during root crossover; U=578 |

R0 reaches Gurobi's configured SoftMemLimit=8 (GB) after about 51.7 seconds
of search; sampled RSS is about 4.56 GiB. This is the engine's allocation
accounting limit, not evidence that physical RAM was exhausted. The external
process-tree RSS guard is 8 GiB for all jobs.

On R2, barrier reaches an LP objective approximately zero at 122.3 seconds,
but crossover remains unfinished and restarts near 250 seconds. No improved
integer plan is produced. Negative raw native MIP bounds in the logs precede
completed root processing; the trivial mathematical unserved bound is zero.
None of these restricted-network values is a global SS bound.

## Progress measurement

Native seed uptake is recorded separately from improvement. CP-SAT event
times start at its optimizer entry; phase-MIP event times start at search,
after network/model construction. The exported CSV labels these clock
origins explicitly; construction and supervised total time are separate.
An unavailable root-completion callback is not manufactured from a timeout.

## Decision

Pending completion of CP-SAT SS and the two R2 repeat runs. No six-station
adapter or extra long run has been started.

## Separater längerer R2-Vergleich (autorisiert)

Am 11.09.2026 separat gestartet bzw. hinter der ersten Kampagne eingereiht:
`benchmarks/output/reservoir_capacity_followup_20260911_30min/`.

- Reihenfolge: Phase-Arc-Flow, danach CP-SAT Legacy; jeweils maximal 1.800 Sekunden einschließlich Aufbau und Abschluss, zusammen maximal 3.600 Sekunden nach Vorbereitung.
- Zwölf Threads/Worker auf dem Mac mit zwölf physischen/logischen Kernen und 36 GiB RAM. Die Engine entscheidet über die tatsächliche Parallelität einzelner Phasen.
- 24 GiB Prozessbaum-RSS-Limit. Gurobis internes SoftMemLimit wird ebenfalls angehoben, auf 25,769803776 dezimale GB (= 24 GiB). Die alte Kampagne verwendete intern 8 dezimale GB; ihre eingefrorenen Quellen bleiben unverändert.
- Unveränderter R2-Startcheckpoint aus `prepare/R2_ss.json`, Seed 0, dieselbe Zeitnetzkonstruktion und Formulierung. Keine gleichzeitigen Solverjobs.
- Vor dem Start werden die kleinen Phasen-/Runner- und zusätzlichen Ganzzahligkeitsprüfungen ausgeführt. Bei Fehlern startet kein großer Lauf.
- Schwerpunkt: Abschluss von Root-LP/Crossover, erste echte Verbesserung, weiterer UB-/LB-Verlauf und Speicherverbrauch. Der Arc-Flow-Bound gilt weiterhin nur für das eingeschränkte Netz.

Der Follow-up-Runner speichert Status, Quellenhashes, Versionen, Befehle, Prozessmessungen, native Ereignisse und validierte Checkpoints. Die Laufzeitwarteschlange zählt nicht zum Vergleichsbudget. Aus der Verlängerung folgt noch keine Performanceempfehlung.
