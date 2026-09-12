# Integriertes CP-SAT mit Reservoir und variabler eingesetzter Flotte

Stand: 2026-09-09. Implementiert auf Basis von `6071c67`. [Umsetzungsplan](../plans/ddd_cp_sat_reservoir.md).

## Was implementiert ist

Eine zusätzliche Betriebsvariante des integrierten CP-SAT: Alle Kabinen starten im Reservoir. Von maximal K verfügbaren Kabinen entscheidet der Solver, welche tatsächlich ausfahren, wann sie ausfahren, welche Stop-/Skip-Routen sie fahren, wie lange sie gegebenenfalls am Exit warten und wann sie leer zurückkehren. Eine Kabine kann mehrere Umläufe fahren, aber nur einmal eingesetzt werden. Nach Rückkehr bleibt sie abgestellt. Wiedereinsatz derselben Kabine ist eine spätere Erweiterung.

`available_fleet_count` begrenzt die Zahl unterschiedlicher eingesetzter Kabinen. Ergebnisse berichten zusätzlich `used_fleet` und `peak_active_fleet`. Diese beiden Zahlen können unterschiedlich sein. Die Flottengröße wird nicht als zweites Ziel minimiert; 38 eingesetzte Kabinen sind deshalb kein Beweis, dass 38 notwendig oder global optimal sind. Auch ein Lauf mit maximal 100 wäre weiterhin ein beschränktes Flottenproblem.

Das bestehende Fixed-K-Verhalten einschließlich Waiting, Warmup und der alte Reservoir-Arc-Flow bleiben separat verfügbar. Die gemeinsame Integer-Passagierformulierung hat jetzt einen generischen Eingang; der bisherige Fixed-K-Wrapper bleibt erhalten.

## Anschluss, Headways und Betriebsvertrag

- Im vorhandenen Fünf-Stationen-Beispiel liegt der ideale Anschluss bei `A_entry_cw`. Die alte Implementierung steht in `optimization/ddd/anonymous_reservoir_network.py` und `reservoir_arc_flow_problem.py` unter `src/ropeway_skip_stop_optimization/`.
- Ein-/Ausschleusen hat dort keine eigene Fahrzeit und keine separat kalibrierte Depotweiche. Das neue Modell übernimmt diese Idealisierung. Es behauptet keine physische Lager-, Rangier- oder Weichenkapazität.
- Die Grenze liegt vor der Stationsroute. Bei Rückkehr an die Grenze können Passagiere nicht automatisch an Station A aussteigen. Sie müssen zuvor an einer tatsächlich gefahrenen STOP-Plattform ausgeladen werden. Jede Kabine kehrt leer zurück.
- Die vorhandenen Ressourcenintervalle gelten einschließlich ihrer Headways und der Koeffizienten, mit denen Exit-Waiting Eintritt und Freigabe beeinflusst. Ihre Schutzzeit bleibt auch nach Rückkehr bestehen. Abgestellte, noch nicht eingesetzte Kabinen erzeugen keine Intervalle.
- Wie im alten Reservoir-Netz darf ein State-Time-Punkt nur einmal belegt sein. CP bildet das mit optionalen Ein-Tick-Intervallen ab, einschließlich Ausfahrt und Rückkehr. Dieser eine Tick ist eine Eindeutigkeitsbedingung, kein neu erfundener physischer Depot-Headway.
- Standard: 300 s Anlauf, 1.200 s Service, 300 s Räumzeit. Ausfahrt ist auf Mikrosekundenticks während Anlauf und Service erlaubt; Rückkehr auch während Service, spätestens bei 1.800 s. Sämtliche gefahrenen Routen müssen bis dahin vollständig abgeschlossen sein.
- Das alte Reservoir erlaubte Ausfahrten nur im Anlauf und Rückkehr erst nach Service. Auch seine Waiting-Phasenfilter sind anders: Dort muss der tatsächliche Exit bei positivem Wait im Service liegen. Die neue Variante übernimmt die bisherige CP-Exit-Waiting-Regel: nominaler Plattformexit frühestens ab `earliest_wait_time_seconds`, begrenzte Wartezeit und vollständige Rückkehr bis Betriebsende. Bei den CLI-Standards liegt die früheste Wartezeit bei 300 s. Waiting kann sich in die Räumphase erstrecken.
- Unterstützt wird zunächst ein deterministischer gerichteter Umlauf mit einmaligen Stations-IDs und einer eindeutigen STOP-Route pro Station. Die geplante Sechs-Stationen-Linie bzw. ein Doppelring ist damit noch nicht integriert.
- Direkte Fahrten verwenden wie der bestehende CP-Ansatz das erste nachfolgende Auftreten der Zielstation; keine Transfers oder absichtlichen zusätzlichen Passagierumlauf-Schleifen.

Diese Bedingungen, sämtliche Geometrie-/Ressourcenparameter, Nachfrage, Zeitraster, Flottenlimit und Betriebsmodus stehen im vollständigen Domain-Manifest. Alte Fixed-K- oder Reservoir-Zertifikate werden nicht als neue Zertifikate akzeptiert. Lower Bounds gelten ausschließlich für ihre ausgewiesene Domäne und Zielfunktion.

## Codekarte

Alle Quellpfade relativ zu `src/ropeway_skip_stop_optimization/`:

| Datei | Aufgabe |
|---|---|
| `optimization/ddd/reservoir_cp_sat_problem.py` | Unveränderliche Problemdefinition, Geometrieübernahme, Besuchsobergrenze aus Minimalfahrzeiten, Passagierkandidaten, Domänenidentität |
| `optimization/ddd/reservoir_cp_sat_movement.py` | Optionale Kabinen, variable Ausfahrt, aktive Besuchsfolge, Rückkehr ausschließlich am Anschluss; vorhandene CP-Ressourcenintervalle |
| `optimization/ddd/cp_sat_passenger.py` | Geteilte Integer-Zuordnung, Releases, Stop-Endpunkte, Sitzkapazität, Journey-Time- bzw. Unserved-Ziel |
| `optimization/ddd/reservoir_cp_sat.py` | Integrierter Optimierer, Seed/Bewegungsfixierung, Bounds, Callbacks, Timeouts und Ergebnis |
| `optimization/ddd/reservoir_cp_sat_certificate.py` | Solverunabhängige Prüfung von Bewegungen, Headways, Passagieren, Kosten und Flotte; strikte Checkpoints |
| `optimization/ddd/__init__.py` | Öffentliche Klassen über bestehende Lazy-Fassade |
| `benchmarking/ddd_reservoir_cp_sat.py` | Wiederverwendung des bestehenden Szenario-Preparers; analytischer All-Stop-Startplan, feste Passagieroptimierung, Budget und Ausgaben |

Einstieg: `benchmarks/run_ddd_reservoir_cp_sat.py`. Tests: `tests/test_optimization_ddd_reservoir_cp_sat.py` und `tests/test_benchmarking_ddd_reservoir_cp_sat.py`.

Das Modell enumeriert Besuche und Passagierzuordnungen, nicht jeden möglichen Zeitstempel. Die Besuchsobergrenze folgt aus der frühesten Ausfahrt, den jeweils kürzesten Routen und dem Betriebsende. Eine Prefix-/Ausfahrtsreihenfolge für identische Kabinen reduziert Label-Symmetrien. Ein Seed muss deshalb kanonische IDs 0 bis used−1 in Ausfahrtsreihenfolge verwenden; native Checkpoints und der analytische Seed erfüllen das.

## Ausführen

Vom Repository-Root aus, mit einem neuen Ausgabeordner:

```bash
.venv/bin/python benchmarks/run_ddd_reservoir_cp_sat.py \
  --example five_station_circle_cw_half_skip_no_wait_headway_b_v0 \
  --max-cabins 39 --mode skip_stop \
  --objective journey_time --maximum-wait-seconds 1200 \
  --time-limit 600 --seed-time-limit 10 --num-workers 8 \
  --log-search-progress \
  --output-dir benchmarks/output/ddd_reservoir_cp_sat/next_waiting_39
```

`--maximum-wait-seconds 0` deaktiviert Waiting. `--mode all_stop` erzwingt Stop-Routen bei denselben Reservoirregeln. `--objective unserved` minimiert unbediente Personen und spart Journey-Time-Produktvariablen; dann sind UB/LB in Personen, sonst in Personensekunden. Das sind zwei verschiedene Ziele, keine automatische lexikografische Optimierung. Journey Time bewertet unbediente Personen mit der verbleibenden Servicezeit.

`--resume-checkpoint .../incumbent.json` übernimmt einen unabhängig validierten Plan mit identischer Domäne. Er übernimmt keine alten Lower Bounds. Ein bestehender Ausgabeordner wird nicht überschrieben. Der Runner zählt Vorbereitung, Seed und Hauptlauf in das Gesamtbudget; abschließende Validierung/Schreiben und Solver-Abbruchlatenz können geringfügig darüber hinausgehen.

Pro Run: `config.json`, `domain.json`, `seed_result.json`, `seed.json`, `result.json`, `incumbent.json`, `events.jsonl`, `solver.log`. Seed-Ergebnisse haben Scope `FIXED_MOVEMENT`: optimaler Passagierfluss für diese fixierten Bewegungen, kein global optimaler All-Stop-Fahrplan. Das Hauptresultat weist `RESERVOIR_SINGLE_USE_GLOBAL` als Domäne aus; das bedeutet nicht automatisch bewiesene Optimalität.

## Erste echte Tests: maximal 39, fünf Stationen

Drei sequenzielle Läufe, je 60 s Gesamtbudget, maximal 10 s Seed, 8 Worker, Seed 0, Mikrosekundenraster. Keine parallelen Solver- oder Testläufe. Jeweils 1.280/1.280 Personen bedient, 38 Kabinen eingesetzt und maximal 38 gleichzeitig aktiv. Jeder finale Plan wurde unabhängig geprüft. Alle Läufe endeten FEASIBLE; LB 0, Gap 100 %.

| Variante | Journey Time UB [Personens.] | Variablen | Constraints | Seed [s] | Hauptmodellaufbau [s] | Solve [s] |
|---|---:|---:|---:|---:|---:|---:|
| All-Stop, No-Wait | 371.869,855 | 30.011 | 71.560 | 2,178 | 0,594 | 57,325 |
| Skip-Stop erlaubt, No-Wait | 371.824,381 | 57.545 | 127.681 | 2,777 | 1,053 | 56,400 |
| Skip-Stop erlaubt, Waiting ≤ 1.200 s | 371.907,060 | 67.880 | 148.356 | 3,122 | 1,257 | 55,810 |

Der gemeinsame analytische All-Stop-Seed erreicht 371.911,194 Personensekunden; dessen feste Passagierzuordnung wurde in allen drei Fällen optimal gelöst. Der globale Solver verbessert ihn geringfügig. Die finalen Pläne aller drei Läufe haben **keine Skip-Routen**. Im Waiting-Plan beträgt das gesamte zusätzliche Exit-Waiting rund 0,258 s. Daher ist der kleine Zahlenvorteil des Skip-Stop-erlaubt-Laufs hier kein Nachweis eines Skip-Stop-Vorteils; sein reiner Stop-Plan ist ebenfalls ein Kandidat für die passende All-Stop-Domäne.

Die ersten nativen Incumbents kommen nach 12,5 / 22,8 / 39,0 s im Hauptoptimierer; letzte Verbesserungen nach 55,5 / 54,6 / 56,9 s. Es gibt 5 / 7 / 6 Incumbent-Ereignisse. Der validierte Seed ist bereits davor verfügbar. Die Rohschranken bleiben negativ und werden durch die mathematisch gültige Nichtnegativität der Kosten auf LB 0 angehoben. Das Problem liegt in diesen Tests überwiegend bei Presolve/Suche und schwachen Schranken, nicht bei der Python-Modellerstellung. Nach 60 s lässt sich weder ein langfristiges Plateau noch gute Skalierung belegen. Prozess-Peak-RSS ca. 1,63 / 3,77 / 3,96 GiB, jeweils einschließlich Seed.

Vergleiche mit dem früheren Fixed-K-39-Wert sind kein isolierter Algorithmusvergleich: andere Starts, optionale Flotte, frühere Rückkehr und vollständig abgeschlossene Fahrten verändern die zulässige Menge. Ebenso ist der vorhandene All-Stop-38-Fixed-Start-Wert keine globale Reservoir-All-Stop-Referenz.

## Erhalt des bisherigen Modells und Prüfungen

**121 Tests bestanden in 23,71 s; Ruff und `git diff --check` bestanden.** Gezielte Regressionen umfassen Fixed-K integriert/Passagiere/Primal/Waiting, Fixed-K-Benchmark, Warmup, alten Reservoir-Arc-Flow und Bound-Zertifikate. Neue Tests prüfen kleine Optima gegen unabhängige vollständige Enumeration (beide Kostencodierungen), variable Ausfahrt, frühe/leere Rückkehr, Nichtverwendung verfügbarer Kabinen, aktive Ressourcen einschließlich Wait-Verlängerung und Schutz nach Rückkehr, Kapazität/Releases, Checkpoint-Manipulationen, Timeout, Runner/Resume und All-Stop-Planübernahme in Skip-Stop.

Zusätzlich wurde das reale Fixed-K-39-Waiting-Modell einmal mit der Passagierimplementierung aus Commit `6071c67` und einmal mit der refaktorisierten Implementierung aufgebaut. Beide erzeugen **exakt denselben Modell-Fingerprint**:

`73459382e6008a7d844de911ba5689fb71ddf18bab67e8343bc0bb885b8a6bbc`

Dabei jeweils 51.076 Variablen und 106.782 Constraints. Beleg: `benchmarks/output/ddd_reservoir_cp_sat/fixed_k_regression.json`.

## Ergebnisse finden und nächster sinnvoller Schritt

Rohdaten unter `benchmarks/output/ddd_reservoir_cp_sat/`, kompakte Vergleichsdaten `summary.json`; die drei Ordner heißen `single_use_all_stop_39_smoke`, `single_use_no_wait_39_smoke`, `single_use_waiting_39_smoke`. Das Archiv `benchmarks/snapshots/ddd_reservoir_cp_sat_20260909_results.tar.gz` enthält diese Runs einschließlich Checkpoints, Live-Verlauf, Modellidentität und Regression-Nachweis; SHA-256 daneben.

Die Erweiterung stellt den gewünschten variablen Flottenbetrieb bereit und erhält einen vollständigen zulässigen All-Stop-Startplan, obwohl 39 Kabinen verfügbar sind. Sie ist bislang kein neuer Optimierungsdurchbruch. Als nächstes bietet sich ein kontrollierter längerer Vergleich derselben Reservoir-Domäne mit guten übernommenen Plänen an, einschließlich Kapazitätsziel `unserved` und Journey-Time-Ziel. Erst daraus lässt sich beurteilen, ob zusätzliche Kabinen/Skip-Muster genutzt werden. Ein höheres Flottenlimit oder Wiedereinsatz sollte anschließend separat getestet werden, damit Modellwachstum und zusätzlicher Nutzen messbar bleiben.
