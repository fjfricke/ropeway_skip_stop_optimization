# Lastbewusste Zuordnung mit exaktem Timing: Pilotbefund

Stand: 12.09.2026

## Ergebnis

Der zweistufige Pilot ist implementiert und korrekt an den bestehenden
Reservoirvertrag angebunden. Er hat den Erfolgsgate auf R2 nicht bestanden:
Kein getesteter Auftrag für 2.506 statt 2.496 bediente Personen wurde in einen
gültigen gemeinsamen Fahrplan überführt.

Das ist kein Unzulässigkeitsbeweis für `U=568`. Zwei Aufträge wurden bewiesen
unzulässig; die übrigen Timingversuche endeten mit `UNKNOWN`.

## Implementierung

- `reservoir_assignment/assignment.py`: eigenes schwächeres Auftragsschema,
  strikte Validierung, Serialisierung und kanonische Kabinenumbenennung.
- `reservoir_assignment/master.py`: ein natives Gurobi-MIP für Einsatzlängen,
  STOP/SKIP, ganzzahlige Ride-Mengen, individuelle exakte Zeiten und
  ressourcenbezogene Arbeitslasten. Konflikte zwischen Kabinen fehlen bewusst.
- `reservoir_assignment/timing.py`: ein CP-SAT-Machbarkeitssolve mit fixierten
  Mengen und Einsätzen. Routen können für die Diagnose entweder fixiert oder
  freigelassen werden.
- `reservoir_assignment/pipeline.py`: genau ein Master- und anschließend
  höchstens ein Timingsolve; kein stiller Rückfall auf die Referenz.
- `benchmarks/run_reservoir_assignment_timing.py`: reproduzierbarer Runner für
  `master`, `timing` und `pipeline`.
- Der Reservoir-Bewegungsbuilder besitzt jetzt die schaltbare
  Dispatch-Reihenfolgensymmetrie. Der Legacy-Standard bleibt aktiv; fixierte,
  verschiedenartige Aufträge verwenden sie nicht.

Alle exportierten Pläne werden weiter durch
`validate_reservoir_cp_plan` gegen die ursprüngliche Domäne geprüft.

## Korrektheitskontrollen

- Neuer Testsatz: fünf kleine Fälle für Master, Timing, Pipeline,
  Serialisierung, globale Kollision und Kabinenumbenennung.
- Zusammen mit den bestehenden Reservoirtests: 28 Tests bestanden.
- Separater R2-Referenzreplay: `OPTIMAL` und unabhängig gültig nach 5,21 s,
  weiterhin 2.496 bediente Personen, 578 unbedient und 38 Kabinen.

Damit sind Auftragstransfer, Fixierungen, CP-Extraktion und Validierung nicht
die Ursache des negativen Kapazitätsergebnisses.

## R2-Messungen

Referenz: `R2_ss.json`, D=3.074, S=2.496, U=578. Ziel: S=2.506, U=568.

| Versuch | Master / Timing | Ergebnis |
|---|---|---|
| Master ohne Start, `balanced` | 60 s | kein Incumbent |
| Master ohne Start, `total_work` | 60 s | kein Incumbent |
| Referenz plus zwei kopierte All-Stop-Einsätze | Start übernommen; Timing 0,81 s | `INFEASIBLE` |
| Referenzrouten plus zwei kurze Skip-Stop-Einsätze | Start übernommen; Timing 1,76 s | `INFEASIBLE` |
| Komprimierte Routen, fixiert, mit Hints | 5 s + 100 s | `UNKNOWN` |
| Komprimierte Routen, fixiert, ohne Hints | 5 s + 100 s | `UNKNOWN` |
| Komprimierte 38-Kabinen-Kontrolle | Timing 60 s | `UNKNOWN` |
| Mengen/Einsatzlängen fixiert, Routen frei, ohne Hints | Timing 120 s | `UNKNOWN` |
| Mengen/Einsatzlängen fixiert, Routen frei, mit Hints | Timing 120 s | `UNKNOWN` |

Der Gurobi-Master besitzt 46.316 Variablen, 82.917 lineare Zeilen, 254.593
Nichtnullkoeffizienten und 62.749 Indikatoren. Ohne Start endet er nach der
Root-Relaxation mit einem Knoten und ohne Lösung. Der erweiterte Referenzstart
für S=2.506 wird dagegen in 0,09 s akzeptiert und verwendet 40 Kabinen.

Beim fixierten komprimierten Auftrag reduziert CP-SAT das vollständige Modell
auf 910 Integer-Zeitvariablen und 1.923 Intervalle in 13 `NoOverlap`-Gruppen.
Es führt in 100 s 27.576 Branches und rund 42,7 Mio. Integerpropagationen aus,
findet aber keine Lösung. Ohne Zeithints sind es 127.573 Branches. Mit freien
Routen verbleiben 4.077 Variablen und 3.831 Intervalle; beide 120-s-Läufe
bleiben ebenfalls ohne Lösung.

Artefakte liegen unter:

- `benchmarks/output/reservoir_assignment_timing_20260912_r2_reference_replay_v1/`
- `benchmarks/output/reservoir_assignment_timing_20260912_r2_s0_v4/`
- `benchmarks/output/reservoir_assignment_timing_20260912_r2_s0_v5/`
- `benchmarks/output/reservoir_assignment_timing_20260912_r2_compressed38_v1/`
- `benchmarks/output/reservoir_assignment_timing_20260912_r2_free_routes_s0_v1/`
- `benchmarks/output/reservoir_assignment_timing_20260912_r2_free_routes_hints_s0_v1/`

## Einordnung und Entscheidung

Die Trennung reduziert die algebraische Größe erfolgreich, aber die
ressourcenfreie Lastapproximation erzeugt keinen nachweislich gut taktbaren
Auftrag. Das starre Routenprofil ist zu empfindlich; das Freilassen der Routen
gibt CP-SAT wiederum einen schwierigen disjunktiven Suchraum zurück. Der
Gurobi-Master schließt diese Informationslücke innerhalb des kurzen Budgets
nicht selbst.

Nach dem vorab festgelegten Gate wird dieser Ansatz daher nicht automatisch zu
einer Benders-, Cut- oder eigenen LNS-Schleife ausgebaut. Solch eine Schleife
wäre ein neues Forschungs- und Implementierungspaket. Der Pilot bleibt als
reproduzierbares negatives Ergebnis und als möglicher Startpunkt für einen
späteren solverinternen Schedulingansatz erhalten.

## Nachtbestätigung über 5 h 40 min

Am 12.09.2026 liefen drei weitere Versuche sequenziell mit zwölf Workern und
je 6.800 Sekunden. Fixiert waren die Beförderungsmengen und Einsatzlängen des
S=2.506-Auftrags; nicht durch Fahrgäste erzwungene STOP/SKIP-Entscheidungen
blieben frei.

| Variante | Status | Branches | Konflikte | Integerpropagationen |
|---|---:|---:|---:|---:|
| ohne Hints, Seed 1 | `UNKNOWN` | 5.285.348 | 578.896 | 839.978.885 |
| ohne Hints, Seed 2 | `UNKNOWN` | 857.580 | 745.235 | 2.388.527.500 |
| mit Hints, Seed 1 | `UNKNOWN` | 712.981 | 602.270 | 165.978.428 |

Kein Lauf exportierte einen Plan; entsprechend existiert kein neuer unabhängig
validierter Wert. Die unterschiedlichen Statistiken zeigen, dass Seeds und
Hints tatsächlich andere Suchverläufe erzeugten. Dass alle drei nach fast zwei
Stunden ohne erste Lösung endeten, ist deshalb stärkere negative Evidenz als
ein einzelner deterministischer Suchlauf. Es bleibt trotzdem ausdrücklich kein
Beweis, dass dieser Auftrag oder S=2.506 global unzulässig ist.

Das Kampagnenartefakt liegt unter
`benchmarks/output/reservoir_assignment_timing_overnight_20260912_v1/`.
Auf Basis dieses Gates wird eine bloße Verlängerung desselben fixierten
Auftrags nicht empfohlen. Der fehlende Kopplungsmechanismus zwischen
Auftragsmaster und Ressourcenordnung ist der gemessene Engpass.

## Referenz-Ablation: Timing oder Auftrag?

Eine zusätzliche kontrollierte Ablation trennt den reinen Timing-Solver vom
vom Master erzeugten S=2.506-Auftrag. Ausgangspunkt ist jeweils der bereits
unabhängig geprüfte R2-Plan mit S=2.496, U=578 und 38 Kabinen. Ride-Mengen,
Einsatzlängen und fahrgastrelevante Routen sind fixiert; Zeithints werden nicht
verwendet.

| Variante | Freie Entscheidungen | Status | Solve-Zeit | Branches |
|---|---|---:|---:|---:|
| Ressourcenreihenfolge fixiert | Dispatch und Waiting | `OPTIMAL` | 4,30 s | 16 |
| Referenz-Waiting fixiert | Dispatch und Ressourcenreihenfolge | `OPTIMAL` | 0,64 s | 26 |
| Timing vollständig frei | Dispatch, Waiting und Ressourcenreihenfolge | `OPTIMAL` | 2,84 s | 262 |

Alle drei Lösungen wurden gegen die ursprüngliche Domäne validiert und
bedienen exakt 2.496 Personen. Der Referenzplan verwendet kein positives
Waiting. Die Variante mit fixierter Ressourcenreihenfolge ergänzt 3.150
Präzedenzbedingungen, behält aber die ursprünglichen `NoOverlap`-Bedingungen.

Als Gegenprobe wurde der Masterauftrag für S=2.506 mit 40 Kabinen verwendet.
Er enthält 79 positive Waiting-Werte mit insgesamt 3.762.177.063 Ticks. Schon
die ursprünglich festgelegten Routen sind im Presolve unzulässig. Auch bei
freien nicht fahrgastrelevanten Routen und ausschließlich fixiertem
Master-Waiting beweist CP-SAT die Unzulässigkeit in 0,36 s.

Die Kontrolle zeigt, dass das Timing des bekannten All-Stop-Auftrags bei
fixierten Routen auch ohne Zeithints schnell lösbar ist. Sie isoliert jedoch
nicht die Ursache der schwierigen Nachtläufe: Dort unterscheiden sich zusätzlich
Kabinenzahl, Routenstruktur und Passagierzuordnung. Die über 520.000 Booleschen
Variablen sind eine Suchstatistik, keine Zählung ursprünglicher Routenentscheidungen.
Die bisherigen Daten beweisen weder eine einzelne Engpassursache noch die
Unzulässigkeit des Auftrags bei vollständig freien Routen und Waiting.

Eine pauschale Empfehlung für einen neuen Pattern-/Column-Master wäre verfrüht:
Trajectory-Column-Generation und Musterwahl mit Timing existieren bereits im
Projekt. Zunächst werden die fixierten Passagiermengen kontrolliert freigegeben
und reproduzierbare Konflikte auf ihre Verwendbarkeit als Cuts geprüft.
Der [nächste Diagnoseplan](../plans/reservoir_assignment_conflict_diagnosis_20260912.md)
legt dafür eine begrenzte Kampagne und konkrete Fortsetzungskriterien fest.

Artefakte:

- `benchmarks/output/reservoir_assignment_timing_reference_ablation_20260912_v1/fixed_resource_order/`
- `benchmarks/output/reservoir_assignment_timing_reference_ablation_20260912_v1/fixed_waits/`
- `benchmarks/output/reservoir_assignment_timing_reference_ablation_20260912_v1/free_timing/`
- `benchmarks/output/reservoir_assignment_timing_reference_ablation_20260912_v1/problem_2506_fixed_waits/`
