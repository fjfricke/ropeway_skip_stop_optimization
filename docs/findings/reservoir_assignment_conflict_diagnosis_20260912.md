# Reservoir Assignment: Freie Zuordnung und Konfliktdiagnose

Stand: 12.09.2026. Implementierung und erste R2-Kampagne abgeschlossen.

## Ergebnis

Die kontrollierte Freigabe der Passagierzuordnung liefert innerhalb von je
120 Sekunden keinen neuen gültigen Plan. Alle fünf Versuche enden mit
`UNKNOWN`. Deshalb existiert kein Unzulässigkeitsnachweis, kein Annahmekern und
kein gültiger Master-Cut. Der bedingte Transferlauf wurde korrekt ausgelassen.

Damit ist der geplante Gate-Fall erreicht: Diesen Assignment-/Cut-Ausbau nicht
zu einer iterativen Benders-Schleife erweitern. Die Versuche belegen keine
Unzulässigkeit von S=2.506 und keine globale Kapazitätsgrenze.

## Implementierung

Der vorhandene CP-SAT-Timingpfad besitzt drei getrennte Passagiermodi:

- `exact`: alle Ride-Mengen einschließlich null bleiben fixiert;
- `commitments`: bisher positive Mengen sind Untergrenzen, andere Rides frei;
- `reassign`: Ride-Mengen sind frei, Bedienung ist mindestens der Zielwert.

Normale Timingsolves und Annahmekerne verwenden denselben Modellbuilder. Der
neue Konfliktpfad benennt Aktivität, Routen, Waiting, Ride-Bindungen und
Bedienungsziel als Annahmen. Er exportiert einen Cut nur nach `INFEASIBLE`,
begrenzten Löschtests und einem frischen `INFEASIBLE`-Replay.

Der Gurobi-Master kann einen solchen geprüften No-Good aufnehmen. Integer-
Gleichheiten und Mindestmengen werden exakt reifiziert; der Cut verlangt, dass
mindestens eine Kernentscheidung geändert wird. Fingerprint- und
Gültigkeitsprüfungen verhindern die Verwendung auf einer anderen Domäne.

Der Kampagnenrunner speichert Eingabe-/Quellenhashes und Engineversionen,
überwacht reale Wandzeit und Prozessbaum-RSS und startet Solver sequenziell.

## Eingefrorene Identität

- Physik/Nachfrage: R2, D=3.074, Max50, Single-Use-Reservoir mit Rückkehr.
- Referenz: S=2.496, U=578, 38 Kabinen, 398 positive Rides, kein Waiting.
- Schwieriger Auftrag: S=2.506, 40 Kabinen, 400 positive Rides, 79 positive
  Waiting-Werte und insgesamt 3.762.177.063 Waiting-Ticks.
- Referenzdatei-Hash: `e02290147a6aec2c1a9853b8935d2d3b291455c8ad11ab29e057acd353ac0379`.
- Auftragsdatei-Hash: `305ff703f9befd567b5809935f298d1c664b79161e8ffbad871ad0689564680e`.
- OR-Tools 9.15.6755, Gurobi 13.0.2, zwölf CP-SAT-Worker.

Der frühere, in 0,81 Sekunden als unzulässig gemeldete S=2.506-Auftrag hat
den anderen Hash
`dc2fdc8eb57f60ed602ce8850794d420487b50338b6f0c893de87a8a32bcd154`.
Er darf nicht als Unzulässigkeitsbeweis für den Nachtauftrag verwendet werden.

## Ergebnisse

| Fall | Routen | Passagiere | Status | Branches | Peak RSS |
|---|---|---|---:|---:|---:|
| T0 Referenz S=2.496 | frei | exact | `UNKNOWN` | 219.926 | 1.215 MiB |
| T1 Auftrag S=2.506 | fixiert | exact | `UNKNOWN` | 54.262 | 981 MiB |
| T2 Auftrag S=2.506 | frei | commitments | `UNKNOWN` | 57.667 | 1.172 MiB |
| T3 Auftrag S=2.506 | fixiert | reassign | `UNKNOWN` | 150.956 | 1.482 MiB |
| T4 Auftrag S=2.506 | frei | reassign | `UNKNOWN` | 145.287 | 2.950 MiB |

Jeder Lauf verwendete rund 118,5 Sekunden Solverzeit und etwa 1,6 Sekunden
Modellbau. Kein Lauf fand eine erste Lösung. Die Speichergrenze von 24 GiB war
nicht aktiv.

T0 ist die entscheidende Kontrolle: Derselbe bekannte Referenzauftrag löst
mit fixierten Referenzrouten ohne Hints in 2,84 Sekunden, bleibt aber bei
freien Nebenrouten in 120 Sekunden ungeklärt. Routenfreiheit kann das
Machbarkeitsmodell daher stark erschweren, obwohl eine Lösung enthalten ist.
Ein `UNKNOWN` bei T2 oder T4 trennt schlechte Zuordnung und Suchschwierigkeit
nicht zuverlässig.

Das Freigeben der Passagiermengen reduziert zwar Fixierungszeilen, erzeugt aber
keinen schnellen Reparaturpfad. T4 benötigt mit rund 2,95 GiB außerdem deutlich
mehr Speicher als die stärker fixierten Varianten.

## Entscheidung

Der Ansatz erfüllt keines seiner Fortsetzungskriterien:

- keine gültige Lösung mit S>=2.506;
- kein bestätigter kleiner Konflikt;
- kein neuer Masterauftrag aus einem gültigen Cut.

Weitere Langläufe desselben Auftrags oder eine Schleife aus Master und
vollständigem CP-SAT-Timing werden nicht empfohlen. Der neue Code bleibt als
Diagnoseinstrument erhalten: Er kann bei künftig schnell bewiesen unzulässigen
Aufträgen einen echten Kern liefern und unterscheidet freie Zuordnung von
exakten Commitments.

Für die Thesis ist der Befund verwendbar: Eine schwache Dekomposition kann
fahrgastseitig attraktive Einzelkabinenaufträge erzeugen, aber die gemeinsame
Ressourcenrealisierbarkeit weder schnell bestätigen noch widerlegen. Das
erklärt auch, weshalb ein einfacher Benders-Ausbau ohne starke, schnell
erhältliche Konflikte nicht trägt.

Artefakte:

- `benchmarks/output/reservoir_assignment_conflict_diagnosis_20260912_v1/campaign.json`
- Unterordner `T0_...` bis `T4_...` mit vollständigen Resultaten und Logs.
- Eingefrorene Assignments und Domäne unter `frozen/`.
