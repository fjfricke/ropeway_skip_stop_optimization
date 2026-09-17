# Waiting-Reparatur bei unveränderten Dispatchzeiten

## Festgelegter Testvertrag

Für gespeicherte kollidierende NSGA-II-Kandidaten bleiben **K, jede Dispatchzeit und die vollständige Besuchs-/Routenfolge einschließlich Rundenzahl fest**. Ausschließlich Exit-Waiting wird freigegeben. Es gibt ausdrücklich keine Variante mit freien Dispatchzeiten und keine Veränderung der äußeren Evolution.

Der physikalische Vertrag wird unverändert aus dem R2-Referenzcheckpoint übernommen: Single-Use-Reservoir, gemeinsamer Portschutz, Integer-Mikrosekunden, positives Waiting erst ab Sekunde 300, bis zu 1.200 Sekunden pro erlaubtem STOP. Rückkehr und Betriebsende begrenzen Waiting zusätzlich. Die letzte vollständige Umlaufrückkehr bleibt die erste am oder nach der Bedienungsdeadline; eine frühere vollständige Rückkehr muss strikt davor liegen. Keine Kabine und kein Umlauf werden still entfernt oder ergänzt.

## Umsetzung

`reservoir_lines/evolution/waiting_repair.py` verwendet den bestehenden vollständigen `build_reservoir_cp_movement`-Builder. Der Adapter ergänzt nur feste Aktivitäts-, Routen- und Dispatchbedingungen sowie den Linienlebenszyklus. Er kopiert keine Ressourcenphysik. Kollidierende Eingaben werden je Einzelkabine validiert; ihre gegenseitige Verträglichkeit wird ausdrücklich nicht vorausgesetzt. Positive ursprüngliche Passagierzuordnungen werden nicht übernommen.

CP-SAT sucht mit zwölf Workern eine erste gültige Bewegung. Die ursprünglichen No-Wait-Zeiten sind lediglich ein möglicherweise unzulässiger Hint; sie werden nicht als Incumbent ausgegeben. Ankunftszeiten und Rückkehr dürfen ausschließlich durch das hinzugefügte Waiting später werden. Ein `OPTIMAL` des reinen Machbarkeitsmodells ist kein Kapazitätsoptimum.

Danach optimiert der gemeinsame Gurobi-Passagierbaustein die Zuordnung auf genau diesem reparierten Fahrplan. Die zusätzliche Funktion `optimize_waiting_timetable_passengers` berücksichtigt Waiting am Ursprung beim Einstieg, aber nicht beim Ausstieg am Ziel. Der vorhandene No-Wait-Evaluator bleibt streng und lehnt positive Wartezeiten weiterhin ab.

Die erste gültige Bewegung wird sofort in `movement.json` gesichert. Nach der Passagierzuordnung wird `best.json` unabhängig validiert gespeichert. Der erste gefundene Timingplan ist nicht notwendig derjenige mit höchster Bedienung; ein schlechtes Ergebnis beweist daher nicht, dass die fixierte Musterfolge unter Waiting keine bessere Bedienung zulässt.

## Kandidaten und Ressourcen

Aus den bereits vorhandenen Populationsschnitten werden vor dem Start drei unterschiedliche Kandidaten eingefroren. Spätere Evolutionsergebnisse ändern die Auswahl nicht. Die ausgewählten Genome und ihre Herkunft stehen in `candidates/*.json`.

| Probe | K | No-Wait-Potenzial | Konfliktzeugen | Zusammensetzung |
|---|---:|---:|---:|---|
| All-Stop-Kontrolle | 38 | gültig 2.496 | 0 | gemeinsamer Referenzplan |
| Nahe Referenz | 38 | 2.504 | 50 | All-Stop mit anderen festen Dispatchzeiten |
| Maximales Potenzial | 45 | 3.074 | 623 | 38 All-Stop, 1 BCE, 3 BD, 3 CE |
| Komplementäre Muster | 34 | 2.715 | 585 | vor allem 14 BD und 12 CE; weitere Muster |

Die zweite Probe ist ausdrücklich **kein Skip-Stop-Plan**. Sie prüft die reine zeitliche Reparierbarkeit einer referenznahen, kollidierenden All-Stop-Anordnung. Ihre eventuelle Verbesserung darf nicht als Skip-Stop-Vorteil ausgegeben werden.

Kontrolle maximal 60 Sekunden; drei Reparaturen je maximal 120 Sekunden einschließlich Aufbau, Timing, Passagierzuordnung und Abschluss. Bis zu zehn Sekunden innerhalb dieses Budgets sind für die nachfolgende Passagierbewertung reserviert. Gesamtkampagne maximal acht Minuten ab Start; Wartezeit auf das Ende der NSGA-II-Kampagne wird separat gespeichert. Keine ausgefallenen Budgets werden in neue Versuche umgewandelt.

Es läuft ein Solverjob gleichzeitig. CP-SAT verwendet zwölf Worker, der kleine Passagier-IP einen Thread. Der vorhandene Supervisor überwacht die tatsächliche Deadline, höchstens 32 GiB Prozessbaum-RSS und anhaltenden kritischen Speicherdruck. Ein Supervisorabbruch ohne Ergebnis bleibt unvollständig, niemals bewiesen unzulässig.

## Tests

62 Tests bestanden: acht neue Waiting-Reparaturtests plus die 54 vorherigen Evolutions-/NSGA-II-/Linientests.

Die neuen Tests bestätigen:

- Ein zunächst kollidierender kleiner Fahrplan wird nur durch Waiting ausführbar und bedient Personen.
- Keine Dispatchzeit, Kabine oder Route ändert sich; zusätzliche native Gleichheits-/Aktivitätswidersprüche machen das Modell unzulässig.
- Ein Konflikt direkt an festen Abfahrten bleibt unlösbar, auch wenn später Waiting verfügbar wäre.
- Waiting vor seiner erlaubten Freigabephase wird nicht zur Reparatur verwendet.
- Ohne erlaubtes Waiting bleibt der ursprüngliche Konflikt bestehen.
- Nachfragefreigabe während Waiting am Ursprung wird korrekt behandelt, einschließlich eines Ticks nach dem tatsächlichen Einstieg.
- Zielankunft wird vor Ziel-Waiting bewertet; der alte No-Wait-Baustein akzeptiert keine Wartezeiten.
- Aufbau-Timeout bleibt getrennt von einer Unzulässigkeitsfeststellung.

## Reproduktion und Auswertung

Runner: `benchmarks/run_reservoir_line_waiting_probe.py`.

Ausgabe: `benchmarks/output/reservoir_line_evolution_20260914/fixed_dispatch_waiting_probe_v1`.

Die Kampagne friert Quellen, Hashes, Lockfile, Referenz und Kandidaten ein und wartet vor ihren Solverläufen auf den Abschluss des laufenden NSGA-II-Vergleichs. Je Probe entstehen `input.json`, `progress.json`, `events.jsonl`, `cp_sat.log`, gegebenenfalls Zertifikate und `result.json`. `report.md` und `summary.json` werden nach jeder Probe aktualisiert.

Ausgewertet werden Modellgröße, Aufbau-/Suchzeit, erste gültige Bewegung, Anzahl und Summe positiver Waitings sowie abschließende gültige Bedienung. Ursprüngliches kollidierendes Potenzial bleibt eine eigene Spalte. Solver-Konflikte aus CP-SAT sind nicht mit den physikalischen Konfliktzeugen der Eingabe gleichzusetzen.

Ein `INFEASIBLE_FIXED_CANDIDATE` gilt für exakt diese Dispatchzeiten, vollständigen Routenfolgen und Waiting-Regeln. Es schließt keine anderen Dispatchzeiten, Rundenzahlen, Muster oder eine anders festgelegte Waiting-Freigabe aus. `UNKNOWN` beweist weder Nähe zur Zulässigkeit noch Unzulässigkeit. Weitere lange Reparaturen oder die Integration in jede Evo-Bewertung werden aus diesem Test nicht automatisch gestartet.

## Wiederholung mit Waiting im Warmup

Nach dem ersten Test wurde die Waiting-Freigabe explizit auf Sekunde **0 statt 300** geändert. Ausschließlich diese einzelne Eigenschaft wird durch `--earliest-wait-seconds 0` überschrieben; die Standardkonfiguration bleibt unverändert. Weil der zulässige Betriebsvertrag erweitert wird, erhält die Instanz einen anderen physikalischen Fingerprint. Quell- und Zielfingerprint sowie vollständige Waiting-Policy werden dokumentiert.

`--repeat-probe` übernimmt dieselben vier Kandidatendateien bytegleich aus `fixed_dispatch_waiting_probe_v1`; keine erneute Auswahl anhand späterer NSGA-II-Ergebnisse. K, vollständige Routenfolgen, Rundenzahlen, Dispatchzeiten, Port-/Headwayregeln, Nachfrage, Horizonte und maximale Wartezeiten bleiben unverändert. Für diesen gezielten Vergleich gelten wieder 60 Sekunden für die Kontrolle und höchstens 120 Sekunden je kollidierendem Kandidaten, sequenziell mit zwölf CP-SAT-Workern und 32-GiB-Prozessbaumgrenze.

63 Tests bestehen. Der zusätzliche Test bestätigt, dass der Override ausschließlich die Waiting-Freigabe verändert, die ursprüngliche Instanz unverändert lässt und den Fingerprint ändert. Ein zunächst wegen der Freigabephase unzulässiger kleiner Kandidat wird mit Warmup-Waiting reparierbar, bei identischen Dispatchzeiten. Ungültige Freigabezeiten werden abgelehnt.

Ausgabe: `benchmarks/output/reservoir_line_evolution_20260914/fixed_dispatch_waiting_warmup_v1`.

Eine Verbesserung gegenüber der regelmäßigen All-Stop-No-Wait-Referenz ist weiterhin kein Nachweis gegen alle All-Stop-Fahrpläne mit Waiting. Insbesondere ist der Kandidat `near_reference` selbst vollständig All-Stop. Die früheren Unzulässigkeitsbeweise bleiben für die damalige Freigabephase gültig und werden durch die neue Instanz nicht überschrieben.
