# Höhere Nachfrage im Max50-Reservoir

Auftrag am 11.09.2026: Nachfrage erhöhen und beobachten, ob CP-SAT zusätzliche
Kabinen einsetzt. Status: abgeschlossen. **Beide freien CP-SAT-Läufe bleiben
bei 38 eingesetzten und passagierführenden Kabinen, 2.598 bedienten Personen
und 476 Unbedienten.** Die erhöhte Nachfrage löst in diesen Versuchen keine
gespeicherte Verbesserung mit größerer Flotte aus.

## Abgrenzung zum früheren Nachfrage-Test

Der frühere [3.074-Personen-Test](fixed_start_capacity_20260910.md) verwendete
Fixed-K38/K39 mit festen Startpositionen und dem Ziel Nichtbedienung. Dort war
die Referenzkapazität eines konkreten All-Stop-38-Fahrplans mit 2.561 Personen
bestimmt worden. Das war kein Reservoirversuch.

Hier werden dieselben 3.074 Personen als Vergleichsmenge verwendet, etwa das
2,402-Fache der bisherigen 1.280. Diese Menge ist **keine** nachgewiesene
120-%-Reservoirkapazität.

## Unveränderter Betriebsvertrag

Ausgangspunkt ist der geprüfte Max50-Single-Use-Reservoirplan mit 38 Einsätzen
und 368.765,817136 Passagiersekunden. Die neue Domäne ändert ausschließlich die
Personenzahlen der vorhandenen 20 OD-Gruppen. Der bestehende deterministische
Nachfrageprefix erhält IDs, Releases und bisherige Personen. Die ursprüngliche
Gruppenreihenfolge und die kanonischen Ride-IDs bleiben erhalten.

- Fünf Stationen, acht Plätze pro Kabine, bis zu 50 optionale Kabinen.
- 300/1.200/300 Sekunden Anlauf/Bedienung/Räumung; Nachfragefreigabe bei 300 s.
- Exit-Waiting bis 1.200 s, unveränderte Mikrosekundenticks und Portregeln.
- **Reisezeitziel bleibt unverändert**, einschließlich der bisherigen
  Nichtbedienungskosten. Es wird nicht gleichzeitig auf Kapazitätsoptimierung
  umgestellt. Bediente Personen sind eine zusätzlich gemessene Kennzahl.
- CP-SAT Legacy, Produktkosten, freie Ausfahrt/Rückkehr, STOP/SKIP und Waiting.
- Keine Flottenfixierung und kein Wiedereinsatz; bisherige Solver bleiben gleich.

Die neue Nachfrage bekommt einen neuen Fingerprint. Alte Schranken werden
nicht übernommen. Der alte Fahrplan wird ausdrücklich in der neuen Domäne
validiert, statt seinen alten Checkpoint als kompatibel auszugeben.

## Startplan und Suchvergleich

1. Vorhandene Bewegungen fixieren und die ganzzahlige Passagierzuordnung für
   3.074 Personen nachoptimieren; dieser Schritt zählt nicht als Flottensuche.
2. Zwei unabhängige freie Läufe mit demselben nachoptimierten Seed, Seeds 0/1,
   jeweils 300 Sekunden Prozessbudget und zwölf Workern. 15 Sekunden davon
   werden für Abschluss/Export reserviert.
3. Sequenzieller Supervisor, 8 GiB Prozessbaum-RSS, 900 Sekunden gemeinsame
   Deadline, Suspend-Erkennung und `caffeinate -i`.

Bei jedem gespeicherten Plan werden unabhängig geprüft: Kosten, bediente und
unbediente Personen, Zahl eingesetzter Kabinen, gleichzeitige Spitzenflotte,
Kabinen mit mindestens einem beförderten Passagier und Beförderungen je Kabine.
Eine zusätzliche leere Fahrt gilt nicht als nachgewiesener Kapazitätsgewinn.
Die Kurve zeigt gespeicherte zulässige Lösungen; sie behauptet nicht, sämtliche
internen Flottenentscheidungen des Solvers sichtbar zu machen.

Eine unveränderte Flottenzahl ist kein Beweis, dass mehr Kabinen nicht helfen
können. Die Schranke der festen Passagierzuordnung ist keine globale Schranke
der freien Reservoirsuche.

## Vorbereitungsergebnis und Fortsetzung

Der gespeicherte Ausgangsplan mit seinen alten Mengen bedient zunächst weiterhin
1.280 Personen; die zusätzlichen 1.794 Personen bleiben darin unbedient.
Die Passagiernachoptimierung bei exakt denselben Bewegungen erreicht
**2.598 bediente / 476 unbediente Personen**, 38 eingesetzte und passagierführende
Kabinen, Kosten **1.760.456,178715 Passagiersekunden**.

Nach 45 Sekunden ist der feste Zuordnungswert nicht exakt optimal bewiesen:
LB 1.760.456,178664, Restdifferenz 0,000051 Passagiersekunden. Dies ist ein
gültiger Startplan und kein globaler Bound. Eine zunächst zu strenge Bedingung
im Messrunner stoppte v1 nach der Vorbereitung, weil sie einen exakten
Teilproblembeweis verlangte. Für die beauftragte Flottenprobe ist dieser Beweis
nicht erforderlich; die Bedingung wurde auf einen validierten Startplan korrigiert.

v2 übernimmt genau das vorhandene Vorbereitungszertifikat, ohne die Vorbereitung
zu wiederholen. Beide Suchseeds erhalten dieselbe Zuordnung. Die originale
900-Sekunden-Deadline von v1 bleibt bestehen; v2 erhält kein neues Gesamtbudget.
Die ursprünglichen v1-Daten und Quellkopien bleiben unverändert erhalten.

Die neue Domäne hat Fingerprint
`69ec6a28d939f81c27d120e817df5290f32bc323328f299e82e6aee733be0e43`.

## Ergebnisse

| Plan | Nachfrage | Bedient | Unbedient | Eingesetzt / Spitzenflotte / passagierführend | Kosten in Passagiersekunden |
|---|---:|---:|---:|---:|---:|
| Historischer Ausgangsplan | 1.280 | 1.280 | 0 | 38 / 38 / 38 | 368.765,817136 |
| Neue Zuordnung, Bewegungen fixiert | 3.074 | 2.598 | 476 | 38 / 38 / 38 | 1.760.456,178715 |
| Freie Suche, Seed 0 | 3.074 | 2.598 | 476 | 38 / 38 / 38 | 1.760.456,178626 |
| Freie Suche, Seed 1 | 3.074 | 2.598 | 476 | 38 / 38 / 38 | 1.760.254,724189 |

Beide freien Läufe enden regulär als `FEASIBLE`, native globale LB jeweils 0.
Es wird kein alter globaler Reservoir-Bound auf die neue Nachfrage übertragen.
Die Kosten der 1.280- und 3.074-Personen-Zeilen dürfen nicht als prozentualer
Algorithmusvergleich interpretiert werden: Nachfrage und Nichtbedienung ändern
sich. Der faire Vergleich der freien Suche ist jeweils gegen die neue Zuordnung.

Seed 0 verbessert diese Kosten um lediglich 0,000089 Passagiersekunden. Seed 1
verbessert um 201,454526 Passagiersekunden beziehungsweise **0,01144 %**.
Die größeren Schritte in Seed 1 treten etwa bei 104, 137, 157 und 180 Sekunden
in der geprüften Checkpointkurve auf. Danach folgen nur noch Änderungen im
Mikrosekundenbereich. Bedienung und Flottenzahl bleiben während aller
gespeicherten Lösungen unverändert. Keine zusätzliche leere Kabine wurde
als Erfolg gezählt.

Die endgültigen Pläne enthalten gegenüber dem Seed veränderte Ride-Mengen und
Routenentscheidungen. Die Suche war somit nicht versehentlich auf dessen
Bewegungen oder Passagiermengen fixiert. Welche anderen Flottenzahlen intern
untersucht und verworfen wurden, ist aus diesen Logs nicht feststellbar.

## Größe, Laufzeit und Prüfung

Beide Modelle besitzen unverändert **87.020 Variablen, 190.189 Bedingungen,
10.100 Ride-Kandidaten und 2.600 Kostenhilfsvariablen**. Die Nachfrageerhöhung
vergrößert hier die Mengenbereiche, nicht die Anzahl der Variablen.
Modellbau: 1,33 / 1,36 Sekunden. Hintaufbau: 0,34 / 0,35 Sekunden.
Native Suche: 286,13 / 283,90 Sekunden. Tatsächliche Prozesszeiten:
288,91 / 286,72 Sekunden, jeweils unter dem 300-Sekunden-Slot.
Peak-Prozessbaum-RSS: etwa 5,75 / 5,77 GiB. Kein Timeout durch den Wächter,
kein Speicherabbruch und kein fehlender Endexport.

Die freie Kampagne einschließlich unmittelbarem Abschluss benötigt 576,06
Sekunden. Die getrennt erhaltene Vorbereitung benötigt 46,15 Sekunden.
Vorbereitung, Übergang zwischen v1/v2 und Endauswertung werden zusammen gegen
die ursprüngliche 900-Sekunden-Deadline geprüft (`completion_audit.json`).
Beide Endzertifikate wurden erneut unabhängig geladen, physisch und bezüglich
ganzzahliger Passagiere validiert und mit den gespeicherten Ergebnissen verglichen.

## Schlussfolgerung und nächste Hypothese

Der frühere schwache Nachfragedruck ist nicht die alleinige Erklärung für das
beobachtete Festhalten an 38 Kabinen: Auch mit 476 Unbedienten findet die freie
Reisezeitsuche in beiden Seeds keine Lösung mit größerer Flotte.
Das beweist weder die Optimalität von 38 Kabinen noch die Wirkungslosigkeit
zusätzlicher Kabinen.

Eine gezielte Folgehypothese wäre ein separates Flottenunterproblem mit 39
eingesetzten Kabinen, zunächst ohne den Kosten-Cutoff des 38er-Seeds. Ein dort
gefundener guter Plan könnte als gültiger Startplan in das freie Max50-Modell
übernommen werden. Die 38er-Referenz dürfte in dem 39er-Unterproblem nicht als
gültiger Fallback ausgegeben werden. Passagierführende und leere Einsätze sind
weiter getrennt zu erfassen; zusätzliche leere Fahrten beweisen keinen Nutzen.
Diese Folgehypothese ist kein Bestandteil der abgeschlossenen Nachfrageprobe.

## Fundstellen

- [Vorbereitung und ursprüngliche Quellkopien](../../benchmarks/output/reservoir_demand_probe_20260911_v1)
- [Freie Suche und Quellen](../../benchmarks/output/reservoir_demand_probe_20260911_v2)
- [Erneute Prüfung und Vergleichsdaten](../../benchmarks/output/reservoir_demand_probe_20260911_v2/analysis.json)
- [Geprüfter Verlauf als CSV](../../benchmarks/output/reservoir_demand_probe_20260911_v2/progress.csv)
- [Separater Messrunner](../../benchmarks/run_reservoir_demand_probe.py)
- [Früherer Fixed-Start-Kapazitätstest](fixed_start_capacity_20260910.md)
