# Kapazität des festen All-Stop-38-Fahrplans und 120-%-Tests

Stand: 10.09.2026. Kalibrierung abgeschlossen; anschließend K38 und K39 sequenziell gestartet, je 900 s CP-SAT-Budget und 12 Worker. Kein Reservoir in diesen Experimenten.

## Exaktes Referenzergebnis

Für den bekannten festen All-Stop-38-Fahrplan beträgt die größte vollständig bedienbare Nachfrage **κ = 2.561 Personen**. Bei 2.561 werden alle bedient, bei 2.562 bleibt nachweislich mindestens eine Person unbedient. Beide Grenzfälle wurden zusätzlich mit dem bestehenden ganzzahligen EAN-Passagiermodell in Gurobi unabhängig bestätigt.

Die Zahl gilt für den konkreten Fahrplan, das gerichtete Fünf-Stationen-Beispiel `five_station_circle_cw_half_skip_no_wait_headway_b_v0`, acht Plätze je Kabine, Release 0 und den geschlossenen 1.200-s-Horizont. Sie ist kein globales All-Stop-Maximum über andere Starts, freie Waiting-Fahrpläne oder Reservoirbetrieb.

Die Nachfrage stammt aus einem deterministischen, verschachtelten Integer-Prefix. Die 20 ursprünglichen OD-Gruppen haben gleiche Gewichte. Es werden jeweils Personen hinzugefügt; keine zuvor vorhandenen Personen werden auf andere OD-Gruppen oder Zeitpunkte verschoben. Bei durch 20 teilbaren Gesamtmengen sind die Gruppen exakt gleich groß. Bei anderen Mengen bestimmt die stabile lexikografische Reihenfolge der Gruppen-IDs die verbleibenden Einzelpersonen. Deshalb lautet die exakte Prefix-Kapazität 2.561; die größte vollständig gleichmäßig verteilte Nachfrage in 20er-Schritten wäre 2.560.

| Referenznachfrage | Optimal unbedient | Befund |
|---|---:|---|
| 1.280 | 0 | Bisheriger Fall, deutlich unter Kapazität |
| 2.561 | 0 | Unteres Grenzzertifikat |
| 2.562 | 1 | Oberes Grenzzertifikat |
| 3.074 | 315 | Überlastfall: maximal 2.759 Personen bedient |

Dass bei 3.074 insgesamt 2.759 bedient werden können, widerspricht κ = 2.561 nicht: Bei dieser teilweisen Bedienung muss die bediente Teilmenge nicht die vorgeschriebenen OD-Anteile des vollständig bedienten Nachfrageprefixes haben.

Der Testwert ist `ceil(1.2 * 2561) = 3074`, also etwa 120,03 % der Referenzkapazität. Die All-Stop-Referenz hat dort genau 315 unbediente Personen. Diese Schranke gilt bei fixierten Bewegungen und darf nicht als globale Skip-Stop-Untergrenze importiert werden.

## Kalibrierung und Nachweise

Eine geometrische Suche mit anschließender ganzzahliger Intervallsuche benötigte 15 CP-SAT-Passagierproben. Jede Probe hat 3.004 Variablen und 823 Constraints; die beobachteten Gesamtzeiten pro Probe lagen unter einer Sekunde. Alle Proben meldeten OPTIMAL. Der Suchalgorithmus behandelt UNKNOWN ausdrücklich als unentschieden und setzt daraus keine obere Kapazitätsgrenze.

Die bestehende Gurobi-Integer-Zuordnung bestätigte 2.561 / 2.562 / 3.074 mit optimal 0 / 1 / 315 unbedienten Personen. Die Bewegungsprüfung und die ursprüngliche EAN-Fahrtenkonstruktion werden dort erneut verwendet. Beide Modellfamilien teilen die deklarierte physische Geometrie und Passagierweg-Domäne; es ist keine unabhängige Validierung einer realen Seilbahnanlage.

Artefakte unter `benchmarks/output/fixed_start_capacity_20260910/`:

- `calibration/summary.json`: exakte Kapazität und Testnachfrage.
- `calibration/n2561/` und `calibration/n2562/`: benachbarte Zertifikate einschließlich Nachfrage-Domäne und geprüfter Zuordnung.
- `calibration/independent_gurobi.json`: unabhängige Solverbestätigung der drei zentralen Nachfragemengen.
- `calibration/original_domain.json`: Identität des ursprünglichen Referenzfalls.

## Gestartete Versuche

| Reihenfolge | Flotte | Starts und Seed | Nachfrage | Ziel |
|---|---:|---|---:|---|
| 1 | Genau 38 | Identische feste Startzeiten/-zustände wie die All-Stop-Referenz; All-Stop-Bewegung als Hint | 3.074 | Unbediente Personen minimieren |
| 2 | Genau 39 | Frühere deterministische Balanced-Startanordnung; bester K39-Waiting-Fahrplan der Folgekampagne als Hint | 3.074 | Unbediente Personen minimieren |

Für beide Fälle bleiben Stop/Skip und Exit-Waiting bis W = 1.200 s frei, auf Mikrosekundenticks. Flotte, Anfangspositionen und Anfangszeiten sind fest; keine Ausfahrts-, Rückkehr- oder Aktivierungsentscheidungen eines Reservoirs. Es gilt der bisherige endliche Fixed-Start-Vertrag einschließlich seiner Fortsetzungsgrenzen.

Die Passagierzuordnung jedes Hints wird vor dem Hauptlauf bei 3.074 Personen auf maximale Bedienung nachoptimiert. K38 startet dadurch bereits mit 2.759 bedienten Personen / 315 unbedienten Personen, nicht nur mit der alten 1.280-Personen-Zuordnung. Beim K39-Seed wird derselbe Schritt separat durchgeführt.

Der Hauptlauf verwendet die unveränderte gemeinsame Bewegungsformulierung und ganzzahlige Passagierzuordnung, aber **keine Journey-Time-Produkte**. K38 hat 48.033 Variablen, 101.785 Constraints, 4.852 Ride-Kandidaten und null Kostenproduktvariablen. Der Modellaufbau dauerte beim Start rund 0,97 s.

Fortschritt und Schranken werden in **Personen** protokolliert. Native Primal-Checkpoints enthalten weiterhin die unabhängig korrekt nachgerechneten Journey-Time-Kosten, damit die Fahrpläne später wieder als Primal-Startlösungen nutzbar sind. Daraus wird keine Journey-Time-Optimalität abgeleitet. Die Kapazitätsergebnisse haben ein eigenes Schema und übernehmen keine früheren Solver-Bounds.

### Erfolg und Interpretation

- Null unbediente Personen beweist die vollständige Bedienbarkeit des 120-%-Falls und zugleich das Optimum null für das Unserved-Ziel. Es beweist keine minimale Journey Time oder minimale Kabinenzahl.
- Eine positive gültige Unserved-Untergrenze beweist fehlende vollständige Bedienbarkeit in der jeweiligen Fixed-Start-Domäne.
- Ein Timeout mit positiver Unserved-UB und LB null bleibt offen.
- Eine Verbesserung gegenüber dem festen All-Stop-Fahrplan kann durch Skip-Stop, zusätzliches Waiting oder beides entstehen. Ohne weitere Kontrolle ist sie kein isolierter Skip-Stop-Effekt.
- K39 hat andere Anfangspositionen. Der Vergleich mit K38 isoliert nicht allein den Effekt einer zusätzlichen Kabine.

## Code und Reproduktion

- `src/ropeway_skip_stop_optimization/optimization/ddd/fixed_timetable_capacity.py`: verschachtelte Nachfrage, ganzzahlige feste Zuordnung und beweisgestützte Kapazitätssuche.
- `src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_capacity.py`: separater Fixed-Start-CP-SAT-Optimierer für unbediente Personen, mit bestehenden Bewegungs-/Passagierbausteinen und Zertifikatsprüfung.
- `benchmarks/run_fixed_start_capacity_campaign.py`: Kalibrierung und anschließende sequenzielle K38-/K39-Proben.
- `tests/test_ddd_capacity_experiment.py`: acht Tests für verschachtelte Nachfrage, exakte Nachbarzertifikate, Release-Grenze, Timeout, Zielfunktionseinheiten, globale Bedienung und nicht fixierende Hints.

```bash
.venv/bin/python benchmarks/run_fixed_start_capacity_campaign.py \
  --stage calibrate --output-dir benchmarks/output/NEUER_ORDNER
.venv/bin/python benchmarks/run_fixed_start_capacity_campaign.py \
  --stage search --output-dir benchmarks/output/NEUER_ORDNER \
  --time-limit 900 --workers 12
```

Die Kalibrierung verlangt einen neuen Unterordner; existierende Fallordner werden nicht überschrieben. Der gestartete Supervisor schreibt `launch.json`, `process.json`, `process_exit.json`, `terminal.log` und nach beiden erfolgreichen Aufrufen `completion.json`. Pro Suchfall gibt es Konfiguration, vollständige Domäne, Seed-Zuordnung, Seed-Zertifikat, native Solverlogs, JSONL-Fortschritt, Incumbent und finales Ergebnis.

Source-Hashes und ein Quellcodearchiv liegen im Kampagnenordner. Der Start erfolgte um 10:25:40 Uhr Europe/Berlin. Die reine Suchzeit beträgt höchstens zweimal 15 Minuten; Vorbereitung, Seed-Zuordnung und Abschluss kommen hinzu. Falls eine Probe früher optimal endet, beginnt die nächste entsprechend früher.

Vor dem Start bestanden 55 gezielte Tests einschließlich bestehender integrierter CP-/Passagier-/Reservoir-Regressionen. Nach der letzten Ergänzung bestanden alle acht neuen Kapazitätstests. Ruff und Whitespaceprüfung bestanden. Bestehende Solverklassen und ihre Standardziele wurden nicht geändert; diese Untersuchung ist eine zusätzliche, getrennte Verwendung ihrer gemeinsamen Modellbausteine.
