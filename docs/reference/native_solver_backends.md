# Experimentelle native Solver

Die neuen Backends liegen unter
`src/ropeway_skip_stop_optimization/optimization/ddd/native_solvers/`:

| Baustein | Aufgabe |
|---|---|
| `model.py` | Unveränderliche Vorbereitung; gemeinsame Physik/Passagiere; Z3-Arithmetik und Hexaly-Listen/Intervalle |
| `optimizer.py` | Ein nativer Solveraufruf, Startwerte, Extraktion, unabhängige Prüfung und Ergebnisprotokoll |
| `benchmarking/native_solvers.py` | Bestehende Instanzbuilder, CP-SAT-Kontrolle, Prozessbaumüberwachung |
| `benchmarks/run_ddd_native_solver.py` | Öffentlicher separater Runner |
| `benchmarks/verify_native_solver_replays.py` | Historische Replays und feste Passagierprobleme |
| `benchmarks/probe_temporal_solvers.py` | Quellcodegebundene Semantikprüfungen in getrennten Umgebungen |
| `benchmarks/run_native_solver_campaign.py` | Eingefrorene Eingaben/Quellen, sequenzielle 60-Minuten-Kampagne |
| `benchmarks/report_native_solver_campaign.py` | Gespeicherte Ergebnisse unabhängig nachprüfen; kein neuer Solverlauf |

## Installation und Aufrufe

Optionale Projektabhängigkeiten: `native-solvers` (Z3 4.16.0.0 und psutil),
`hexaly` (15.0.20260909). Der Hexaly-Python-Wheel enthält keine Lizenzfreigabe.
Die bestehenden Standard-Runner und Solver bleiben unverändert.

**Freigabestatus:** [Prüfungen und Ergebnisse dieses Piloten](../findings/native_solver_pilot_20260911.md).
Der Hexaly-Code ist bis zur vorhandenen Lizenz und den Semantiktests
experimentell ungeprüft. Die großen Z3-Passagieroptima wurden bislang nicht
reproduziert. Ein vorhandener Runner ist keine Performanceempfehlung.

```sh
uv sync --extra native-solvers --extra hexaly
.venv/bin/python benchmarks/run_ddd_native_solver.py \
  --backend z3 --operation fixed_k --objective unserved \
  --example five_station_circle_cw_half_skip_no_wait_headway_b_v0 \
  --cabins 39 --demand 3074 --maximum-wait-seconds 1200 \
  --resume-checkpoint benchmarks/output/pattern_search_followup_20260910/run/incumbent.json \
  --time-limit 150 --output-dir benchmarks/output/new_z3_fixed_k_run

.venv/bin/python benchmarks/run_ddd_native_solver.py \
  --backend hexaly --operation reservoir --objective journey_time \
  --example five_station_circle_cw_half_skip_no_wait_headway_b_v0 \
  --max-cabins 50 --maximum-wait-seconds 1200 \
  --warmup-seconds 300 --service-seconds 1200 --recovery-seconds 300 \
  --resume-checkpoint benchmarks/output/reservoir_global_repair_campaign_20260911_v1/common_seed.json \
  --num-workers 12 --time-limit 150 --output-dir benchmarks/output/new_hexaly_reservoir_run
```

Neue Ausgabeordner sind verpflichtend. `--build-only` baut ohne Suche;
`--waiting-step-seconds` und `--dispatch-step-seconds` bleiben standardmäßig
eine Mikrosekunde. Reservoirargumente werden bei Fixed-K ausdrücklich
abgelehnt. Die Horizonte von Fixed-K stammen aus der ausgewählten Instanz;
`--warmup-seconds` verwendet den bestehenden Adapter.

## Formulierung und Äquivalenz

Zeit und Waiting bleiben Integer. Die Besuchsfolge ist die bestehende
kanonische Folge möglicher Besuche, nicht eine feste Reihenfolge der Kabinen.
Fixed-K wird genau bis zum ersten Ereignis hinter dem Betriebshorizont
fortgesetzt. Reservoir-Aktivität bildet einen Präfix; Beenden ist nur am Port
zulässig. Der letzte Rückkehrknoten bleibt kollisionswirksam.

Jede Ressourcennutzung verwendet unverändert
`Beginn = Ereignis + Eintrittsoffset + Eintritts-Waitingkoeffizient × Waiting`
und das entsprechende Räumungsende einschließlich Schutzzeit. Nutzungen mit
Eintritt genau am Horizont bleiben vorhanden; ihre Enden werden nicht
abgeschnitten. Z3 formuliert bedingte paarweise Disjunktionen. Hexaly ordnet
genau die präsenten Nutzungen in einer nativen Liste je Ressource. Für positive
geschützte Intervalle ist die Nichtüberlappung benachbarter Listeneinträge
äquivalent zur Nichtüberlappung sämtlicher Intervalle. Verschiedene Ressourcen
dürfen verschiedene Reihenfolgen besitzen. Es entsteht kein FIFO-Zwang über
Bypass und Plattform hinweg.

Integer-Ride-Mengen erzwingen Ursprung-/Ziel-STOP und die ursprünglichen
Freigabe-/Horizontbedingungen. Kapazität zählt den Abschnitt nach dem Einstieg;
Aussteiger des aktuellen Besuchs belegen diesen Abschnitt nicht mehr. Die
kanonische erste Zielbegegnung bleibt erhalten.

Für `journey_time` wird dieselbe exakte Kostenfunktion verwendet. Z3 zerlegt
die Aussteigermenge `n ≤ Q` in Binärstellen und ersetzt `n × Ankunft` durch
gewichtete If-Ausdrücke. Alle Multiplikationen haben damit mindestens einen
konstanten Faktor. Bei festem Fahrplan ist die Ankunft bereits konstant, sodass
diese diagnostischen Modelle direkt linear bleiben. `unserved` erzeugt keine
Zeitprodukte. Sichere Zeitgrenzen und die analytische Schranke werden aus der
vorhandenen solverfreien Vorbereitung übernommen.

Die Z3-Darstellung kann durch paarweise Ressourcenregeln quadratisch wachsen.
Es wird keine pauschale Größenreduktion gegenüber CP-SAT behauptet. Hexalys
Listen vermeiden diese explizite paarweise Darstellung; ihre tatsächliche
Suchleistung und Schranken müssen separat gemessen werden.

## Zertifikate, Ergebnisse und Grenzen

Originale Domänen-Fingerprints und Checkpointformate bleiben bestehen. Ein
zusätzlicher Modell-Fingerprint enthält Engine, Version, Encoding, Ziel und
gegebenenfalls diagnostisch fixierte Entscheidungen. Intern null belegte
Rides werden beim Export entsprechend dem bestehenden Zertifikatsvertrag
weggelassen. Ungültige positive Mengen werden nicht repariert.

`reference_objective`, `native_objective`, `validated_upper_bound` und
`lower_bound` sind getrennte Felder. Reisezeitwerte im neuen Ergebnisformat
stehen in **Personenticks**, Kapazitätswerte in **Personen**. Native Ergebnisse
werden gegen die Originaldomäne geprüft. Hints fixieren nichts; `fixed_plan`
ist ein gesonderter Diagnosepfad und liefert nur Schranken für dessen
eingeschränkte Domäne.

`UNKNOWN`, Timeout, Speicherabbruch und eine fehlende native Lösung beweisen
keine Unzulässigkeit. Hexalys Statuswort `OPTIMAL` genügt nicht für exakte
Tick-Optimalität: dafür müssen gültige numerische UB und LB übereinstimmen.
Z3 kann bei Timeout keine nutzbare Schranke oder keinen weiterverwendbaren
Modelldatensatz liefern; die zuletzt unabhängig bestätigte Referenz bleibt
separat erhalten. Bound-Zeitverläufe werden nur bei öffentlich verfügbaren
Engineereignissen ausgegeben.

Der CLI-Runner überwacht den vollständigen Prozessbaum. Standard-Speicherlimit
sind 8 GiB; `--memory-gib` ist einstellbar. Zeitlimits der Python-Solver-API
sind kooperativ; die Prozessüberwachung setzt die harte Laufgrenze durch.
Gemessen werden beobachteter Prozessbaum-RSS, CPU-Zeit, Threadzahl sowie
bürgerliche und wache Wandzeit. Samplingwerte sind keine exakten internen
Engine-Speicherzähler.

## Temporale Prüfungen reproduzieren

Die Planer werden außerhalb der Projektumgebung installiert. Der Probe-Runner
prüft den exakten Commit und unveränderte versionierte Dateien. Er schreibt
Paketversionen, Quellcode-Hashes und ein Gegenbeispiel; ein bestandener Import
oder eine Parserprobe wird nicht als vollständiger Seilbahnadapter ausgegeben.

Geprüfte Quellstände:

- TemPEST: `a888dc25d2fb705be42a4790cf4f3ceea83fcb6c`.
- Patty `main`: `651a813d9c61b9b2926dcc9abdeeb05b4b2acb97`, nur numerische Parserkontrolle.
- Patty `instradi`: `6246e9a8a878f4299adbb111773267504ab8b05a`, relevante temporale ICE-Prüfung.

Beispiel für den bereits installierten, getrennten ICE-Pfad:

```sh
/tmp/ropeway_native_instradi_env_20260911/bin/python \
  benchmarks/probe_temporal_solvers.py --engine patty_instradi \
  --source /tmp/ropeway_native_patty_instradi_20260911 \
  --output benchmarks/output/new_patty_ice_probe.json
```

In dieser Umgebung: Python 3.11.13, PySMT 0.9.6, Z3 4.12.2.0,
ANTLR-Runtime 4.11.1, SymPy 1.13.2, NumPy 1.24.4, PyEDA 0.28.0,
Setuptools 70.3.0. Weitere exakte Paketversionen stehen im Probe-JSON.
Der alte Code liefert PyEDA-Binärdateien für CPython 3.8 mit; diese sind nicht
mit CPython 3.11 kompatibel. Für die Prüfung wurde PyEDA 0.28.0 unverändert
mit `CFLAGS='-Wno-incompatible-function-pointer-types'` kompiliert und seine
drei `.so`-Dateien in `libs/pyeda/pyeda/boolalg/` verlinkt. Die `.py`-Dateien
des Planers blieben unverändert. Die Links und Binärhashes sind dokumentiert.
Die Projektumgebung wurde durch diese alten Planerabhängigkeiten nicht ersetzt.

Die temporalen Backend-Optionen des öffentlichen Runners verweigern weiterhin
den Modellbau, solange kein exakter Adapter freigegeben ist. Ein Fehlschlag
der direkten Übersetzung beweist nicht, dass jede mögliche alternative
Kompilierung ausgeschlossen wäre.

## Historische Freigabe und Kampagnenabschluss

`verify_native_solver_replays.py` reproduziert zuerst feste Bewegungen und
Beförderungen. Für die anschließende freie Passagieroptimierung berechnet es
den Kontrolloptimalwert mit dem bestehenden CP-SAT-Passagiermodell. Ein
historischer Incumbent allein wird nicht als nachgewiesenes Optimum behandelt.
`--oracle-only` prüft ausschließlich diese Kontrollwerte und erzeugt ausdrücklich
keine Enginefreigabe.

```sh
.venv/bin/python benchmarks/verify_native_solver_replays.py \
  --backend hexaly --output-dir benchmarks/output/new_hexaly_replays
.venv/bin/python benchmarks/report_native_solver_campaign.py \
  benchmarks/output/native_solver_campaign_20260911_v1
```

Die Auswertung verändert keine Solverresultate oder historischen Checkpoints.
Sie schreibt `campaign_reviewed.json`, `report_reviewed.md` und `progress.csv`.
Beim Pilot wurde so der Abschluss eines bereits fertig geschriebenen Laufs
nach einem Supervisorfehler wiederhergestellt. Fehlende Prozessmetriken werden
nicht rekonstruiert oder erfunden. Die eingefrorene Kampagnenquelle bleibt als
Beleg des tatsächlich ausgeführten Codes erhalten.

## Literatur-/API-Basis

- [Hexaly-Modellierungsfunktionen](https://www.hexaly.com/docs/last/modelingfeatures/mathematicalmodelingfeatures.html)
- [Hexaly-Startlösungen](https://www.hexaly.com/docs/last/features/initialsolution.html)
- [Z3 Optimize](https://z3prover.github.io/api/html/classz3py_1_1_optimize.html)
- [TemPEST, geprüfter Commit](https://github.com/fbk-pso/tempest/tree/a888dc25d2fb705be42a4790cf4f3ceea83fcb6c)
- [Patty, numerischer Hauptzweig](https://github.com/matteocarde/patty/tree/651a813d9c61b9b2926dcc9abdeeb05b4b2acb97)
- [Patty/InSTraDi, geprüfter temporaler Zweig](https://github.com/matteocarde/patty/tree/6246e9a8a878f4299adbb111773267504ab8b05a)
