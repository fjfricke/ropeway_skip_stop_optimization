# Binäre CP-SAT-Kosten: korrekt, im begrenzten Vergleich deutlich schwächere Schranken

Abgeschlossen am 11.09.2026. **Keine Empfehlung für die binäre Variante.** Beide
Seeds verfehlen das vorab festgelegte Erfolgskriterium. Kein Lauf auf dem vollen
Reservoir und kein weiterer Langlauf dieser Variante wurde gestartet. `product`
bleibt Standard.

[Plan](../plans/reservoir_binary_cost_comparison_20260911.md),
[Messwerte](../../benchmarks/output/reservoir_binary_cost_comparison_20260911_v1/report.md),
[CSV](../../benchmarks/output/reservoir_binary_cost_comparison_20260911_v1/comparison.csv),
[Experimentmanifest und Entscheidung](../../benchmarks/output/reservoir_binary_cost_comparison_20260911_v1/campaign.json).

## Gleiche Aufgabe und zulässige Lösungen

Max50-Single-Use-Reservoir, 1.280 Personen, Waiting bis 1.200 Sekunden in
Mikrosekunden; die Referenz setzt 38 Kabinen ein. Für diese Diagnose sind
Haltemuster und sämtliche aktiven Besuche fest. Dispatch, Waiting, Reihenfolgen
auf den Ressourcen und ganzzahlige Passagierzuordnung bleiben gemeinsam frei.
Die LBs gelten ausschließlich in diesem eingeschränkten Timing-Problem.

Beide Encodings verwenden denselben geprüften Startplan mit Kosten
**368.765,817136 Passagiersekunden**, `legacy`-Formulierungsprofil und zwölf Worker.
Es werden dieselben Bewegungs-/Mengen-Hints gesetzt. Die binären Hilfswerte
werden im Legacy-Vergleich nicht zusätzlich vollständig vorgegeben.

Die Produkt-Baseline hat denselben Modell-Fingerprint wie die vorherige Diagnose
(`cb4e023045562e32250e90f7bfe7d3cf3326300a57b1c53ec70a5e44ec915e40`, Seed 0).
Der unveränderte physikalische Fingerprint ist
`ea2b46d53da6f34147bfd5a9c1a635116e89eb47afd84cfd036b56971376ac65`.

## Ergebnis

Alle vier Läufe liefern dieselbe validierte UB: **368.765,817136**. Alle vier
haben Status FEASIBLE, keine Verbesserung gegenüber dem Seed und keinen
Optimalitätsbeweis. Die Seedübernahme zählt nicht als Verbesserung.

| Encoding | Seed | Native LB im Teilproblem | Nativer Gap | Variablen nach Presolve | Peak-RSS |
|---|---:|---:|---:|---:|---:|
| product | 0 | 314.126,681746 | 14,82 % | 8.978 | 2,11 GiB |
| binary | 0 | 0 | 100 % | 14.718 | 3,43 GiB |
| binary | 1 | 0 | 100 % | 14.715 | 2,44 GiB |
| product | 1 | 314.785,637884 | 14,64 % | 8.974 | 2,36 GiB |

„Native LB null“ bezeichnet den nichtnegativ geklemmten nativen CP-SAT-Bound.
Die bereits separat zertifizierte gemeinsame globale LB **209.409,890300** gilt
weiter. Berücksichtigt man sie für beide Encodings, verbleiben bei Binär
**43,21 % vergleichbarer Gap**, gegenüber 14,82 / 14,64 % bei Produkt im
Timing-Teilproblem. Das ändert die negative Entscheidung nicht. Diese stärkeren
Timing-LBs dürfen nicht als globale Reservoir-LBs übernommen werden. Der globale
Gap bleibt unverändert bei 43,21 %.

[Gemeinsame Bound-Provenienz](../../benchmarks/output/reservoir_binary_cost_comparison_20260911_v1/common_bound_provenance.json),
[vergleichbare Schranken](../../benchmarks/output/reservoir_binary_cost_comparison_20260911_v1/comparable_bounds.json).

### Fortschritt über die Laufzeit

- Produkt übernimmt den Seed nach 7,8 / 10,1 Sekunden. Materielle LB-Zuwächse enden
  bei 26,1 / 29,4 Sekunden; in Seed 1 reichen kleinere Änderungen bis 37,1 Sekunden.
  Danach keine weiteren erfassten LB-Verbesserungen bis zum Ende.
- Binär übernimmt den Seed nach 10,0 / 13,3 Sekunden. In beiden Läufen keine
  positive native LB und keine bessere UB bis zum Ende.
- Ausgangsgröße: 87.020 Variablen bei Produkt, 105.220 bei Binär. Die binäre
  Darstellung hat rund 64 % mehr Variablen nach Presolve, obwohl die 820 dann
  verbleibenden direkten Produktbedingungen vollständig entfallen.
- Aufbau etwa 1,4–2,2 s plus 0,4–0,6 s für Hint-/Diagnoseaufbau. Der Unterschied
  entsteht nicht hauptsächlich durch minutenlangen Modellaufbau.

Die native Bound-Erfassung ist zeitlich gedrosselt; „letzter Fortschritt“ meint
den aufgezeichneten Verlauf. Ein materieller Zuwachs entspricht kumulativ 0,1 %
der Referenzkosten seit der letzten so markierten LB. Ereigniszeiten beginnen
beim Solver-Wrapper einschließlich Modellbau. Die zwei Nullkurven liegen auf der
unteren Achse.

![Native Schranken im gleichen Timing-Teilproblem](../../benchmarks/output/reservoir_binary_cost_comparison_20260911_v1/bound_progress.png)

Vier sequenzielle Suchversuche mit je 180 s Prozessbudget einschließlich Aufbau
und Abschluss, Reihenfolge Produkt 0, Binär 0, Binär 1, Produkt 1. Jeder Prozess
endete regulär nach etwa 176 s. Einschließlich Vorbereitung und der zwei
historischen Replay-Prüfungen dauerte die Kampagne **712,36 s (11 min 52 s)**.
Die gesamte Auswertung bleibt innerhalb des 30-Minuten-Budgets; `completion.json`
erfasst ihren Abschluss. Kein Speicherabbruch, Suspend oder Validierungsfehler.
Engine: OR-Tools **9.15.6755**, macOS arm64. Es gab keine konkurrierenden Solverjobs.

## Interpretation und Entscheidung

Die getestete binäre Darstellung ist mathematisch exakt, liefert aber hier
schwächere native Schranken und keine besseren Incumbents. Damit bestätigt sich
die Hypothese nicht, dass genau diese Ersetzung der direkten Integerprodukte den
in der Diagnose gefundenen Engpass verbessert.

Der Produktlauf protokolliert native `PositiveProduct`-Schnitte in mehreren
CP-SAT-Teilsolvern. Die ursprüngliche Multiplikationsbedingung ist somit kein
bloß undurchsichtiger Kostenblock: Die Engine verwendet ihre Struktur für
zusätzliche Schnitte. Die binäre Darstellung erzeugt dafür mehr Boolesche und
reifizierte Bedingungen. Das ist ein plausibler Erklärungsansatz, kein isolierter
Nachweis, welcher interne Mechanismus wie viel Performance verursacht.

Die Kopplung von Zeiten und Passagierentscheidungen bleibt ein Engpass. Daraus
folgt keine allgemeine Unterlegenheit binärer Linearisierung in anderen Solvern
oder mit anderen Formulierungen. Vollständige zusätzliche Hints oder zusätzliche
Cuts wurden nicht mitgetestet. Diese Abgrenzung ist kein automatischer Auftrag
für weitere Varianten.

**Entscheidung:** Die begrenzte Hypothese beenden. Produkt beibehalten, keinen
Reservoir-Ausbau und keinen Langlauf der binären Variante. Das Experiment hat
keinen besseren Fahrplan und keinen neuen globalen Nachweis erzeugt.

## Umsetzung und Korrektheit

Im gemeinsamen [Passagierbaustein](../../src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_passenger.py)
steht zusätzlich `DddCpSatCostEncoding.BINARY` zur Verfügung. Beide bestehenden
CP-SAT-CLIs akzeptieren `--cost-encoding binary`; ihre Defaults bleiben unverändert.
Die binäre Menge behält `0 <= n <= Q`, sodass auch Kapazitäten außerhalb `2^m-1`
exakt bleiben. Kosten werden durch reifizierte Zeitgleichungen aus den Bits
gebildet. Der vollständige Hintpfad unterstützt die neuen Variablen. Modellgrößen
zählen sie korrekt; beim Unserved-Ziel entstehen keine Kostenhilfen.

**102 Tests bestanden**: exhaustive kleine Mengen-/Zeitprojektion, Zeitwerte über
2^31, Fixed-K-/Reservoir-Optima, Waiting, Überholen, Horizontgrenzen, ganzzahlige
Odd-Cycle-Zuordnung, Startwerte und Profilkompatibilität. Die beiden vollständig
fixierten historischen Replays reproduzieren exakt denselben Referenzwert.
Alle exportierten Fahrpläne werden durch die vorhandenen unabhängigen
physikalischen und Passagierprüfer sowie die Diagnoseprüfung validiert.

[Zusätzliche Tests](../../tests/test_cp_sat_binary_cost.py),
[JUnit](../../benchmarks/output/reservoir_binary_cost_comparison_20260911_v1/tests.xml),
[Runner](../../benchmarks/run_reservoir_binary_cost_comparison.py),
[gefrorene Quellcode-Hashes](../../benchmarks/output/reservoir_binary_cost_comparison_20260911_v1/source_hashes.json),
[maschinenlesbare native Verläufe](../../benchmarks/output/reservoir_binary_cost_comparison_20260911_v1/progress.csv).
