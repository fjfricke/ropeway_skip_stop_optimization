# Vollständiger CP-SAT-Solver mit Passagieren

## 1. Ziel und Ausgangsstand

Status: **konkreter Umsetzungsplan; noch nicht implementiert**. Stand: 9. September 2026.

Ziel ist ein ereignisbasiertes CP-SAT-Modell, das Stop-/Skip-Bewegung und ganzzahlige Passagierzuweisung gemeinsam optimiert. Es soll für dieselbe deklarierte Fixed-K-No-Wait-Domäne wie das vollständige Arc-Flow gültige obere und untere Schranken liefern. Der Leistungsversuch prüft, ob damit bei K=39 schneller bessere Fahrpläne oder ein kleinerer zertifizierter Gap entstehen. Ein Laufzeitvorteil ist eine Hypothese, kein zugesagtes Ergebnis.

Der aktuelle Arbeitsstand wurde vor diesem Plan getrennt gesichert:

| Repository | Commit | Inhalt |
|---|---|---|
| Software, Branch `ddd` | `63bca5e` | Reservoir-Arc-Flow, Runner, Frontend-Metriken und Tests als experimenteller Checkpoint |
| Thesis `idp_report`, Branch `ddd` | `d5487ed` | Manuskriptstand, mathematische Herleitungen und Solver-Übersicht |
| Übergeordneter Workspace `idp`, Branch `main` | `7822c6c` | `PROJECT_STATUS.md`, `SOLVER_OVERVIEW.md`, `RESEARCH_CONCEPTS.md` |

Prüfstand des Checkpoints:

- Frontend: `npm run build` erfolgreich.
- CP-Primal-/Passagierzieltests: 19 bestanden.
- Reservoirtests: 7 bestanden, 1 fehlgeschlagen. `reservoir_arc_flow.py:626` ruft die nicht definierte Funktion `_solver_status_name` auf. Das ist ein vorhandener Laufzeitfehler, keine Folge der CP-SAT-Planung.
- Die LaTeX-Ziele für Hauptbericht, DDD-Herleitungen und Solver-Übersicht melden erfolgreiche, aktuelle Builds; es wurde kein erzwungener vollständiger Neubau durchgeführt.
- Kein neuer großer Solverbenchmark wurde für den Checkpoint gestartet.

Die ausführliche Ausgangsbewertung steht im [Solver-Overview](/Users/felix/Programming/idp/ropeway/SOLVER_OVERVIEW.md), die methodische Einordnung in der [Forschungslandkarte](/Users/felix/Programming/idp/ropeway/RESEARCH_CONCEPTS.md).

## 2. Verbindlicher Umfang der ersten Version

Die erste Version behandelt ausschließlich:

1. einen gerichteten Ring mit nach jedem Besuch wieder zusammenlaufenden Stop-/Skip-Optionen;
2. feste Kabinenzahl, feste physikalische Anfangszustände und die vorhandenen Anfangsbelegungen;
3. No-Wait, einschließlich der bestehenden Service-, Bewegungs- und Horizontabschlussregeln;
4. direkte Passagierfahrten innerhalb der bestehenden zulässigen Besuchsspanne, ohne Transfers;
5. homogene Nachfragegruppen mit Ursprung, Ziel, Release-Zeit und ganzzahliger Anzahl;
6. das bestehende Journey-Time-Ziel einschließlich der bisherigen Kosten unbedienter Nachfrage;
7. die kanonische DDD-Zeitdomäne mit einer Million Ticks pro Sekunde.

Waiting, Reservoir, endogene Startlagen, mehrere Linien, andere Nachfragekosten und lexikografische Bedienungsziele sind spätere Erweiterungen. Unsupported-Eingaben werden explizit zurückgewiesen. Insbesondere darf ein Reservoirproblem nicht automatisch als Fixed-K-Problem behandelt werden.

Es wird keine Periodizität vorgegeben. Ein periodischer Seed ist lediglich ein Hinweis an die Suche. Es werden keine Kandidaten nach einer heuristischen Top-N-Regel abgeschnitten und keine Besuchsgrenzen aus einem einzelnen Seed übernommen.

### 2.1 Referenzinstanzen

| Instanz | Kanonischer Problem-Fingerprint | Referenz |
|---|---|---|
| Five-Station B, halbe Nachfrage, K=20, Balanced Reference, No-Wait, Journey Time | `2c53481066e498cc29ec206e717911f55d1ac30296cdc5cb8ac05139b35fbd01` | Bekannter Optimalwert ungefähr 525.730,908; vollständigen gespeicherten Wert verwenden |
| Gleiche Betriebsfamilie, K=39 | `2f82126c06273d2299ab258ca5c5d92acc9d83d829360422f8473c26521cc0f0` | Anonymes Arc-Flow: UB 1.376.000,783, LB 441.919,534 nach etwa 1 h; CP/Root-CG: UB 1.326.950,671, vollständiger Export noch zu beschaffen |

Fingerprint und vollständiger Zielfunktionswert sind beim Laden zu prüfen. Ein K=20-Canonical-Rope-Fall ist nicht dieselbe Instanz. Ein passender globaler Bound darf nur nach bewiesener Domänenübereinstimmung kombiniert werden. Zur Diagnose werden native CP-Bounds und gegebenenfalls externe Bounds getrennt gespeichert.

## 3. Wiederverwendung und Dateiaufteilung

### 3.1 Bereits vorhandene Bausteine

| Baustein | Vorhandener Code | Verwendung / erforderliche Anpassung |
|---|---|---|
| Ereignisbasiertes CP-Bewegungsmodell | [cp_sat_primal.py](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_primal.py) | Konstruktion der Ereignisse, Auswahlvariablen und Ressourcenintervalle extrahieren; bisherige Heuristik weiterhin unterstützen |
| Globale CP-Kandidaten | [trajectory_coordinated_primal.py](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/trajectory_coordinated_primal.py) | Referenz für Konvertierung und Seed-Nutzung; das heuristische Präferenzziel wird nicht zum exakten Ziel umbenannt |
| Fixed-K-Problem und Starts | [fixed_k.py](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/fixed_k.py), [Benchmark-Vorbereitung](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/benchmarking/ddd_fixed_k_arc_flow.py) | Dieselbe Problemvorbereitung wiederverwenden; kein zeitexpandiertes Netz bauen |
| Strukturelle Passagierfahrten | [passenger_builder.py](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ean/builders/passenger_builder.py) | Nachfragegruppen und zulässige Boarding-/Alighting-Besuchspaare übernehmen, konservative Tick-Prüfung ergänzen |
| Fixe Passagierzuweisung | [fixed_movement_passenger_model.py](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ean/optimizers/fixed_movement_passenger_model.py) | Unabhängiger ganzzahliger Vergleichsoptimierer und Kapazitätsreferenz |
| Einheitliches Ziel | [passenger_objective.py](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ean/passenger_objective.py) | Zeitereignisse und unbediente Kosten semantisch beibehalten |
| Seeds | [fixed_k_primal_seed.py](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/fixed_k_primal_seed.py) | `DddFixedKPrimalSeed`, kanonische Fahrt-IDs und vorhandene Ergebnis-/Checkpoint-Importe nutzen |
| Physikalische Prüfung | [reference.py](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/reference.py), [EAN validation.py](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ean/validation.py) | Extrahierte Pläne unabhängig prüfen |
| Ganzzahlige Zeiten | [time_ticks.py](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/time_ticks.py) | Bereits quantisierte Werte verwenden, keine zusätzliche Rundung |

### 3.2 Geplante neue Dateien

Die folgenden Pfade sind geplante Dateien, keine bereits verfügbaren APIs. Alle beziehen sich auf das Software-Repository.

| Pfad | Verantwortung |
|---|---|
| `src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_movement.py` | Gemeinsamer Movement-Builder; liefert `CpModel`-Variablen und semantische Ereigniszuordnung ohne Suchsteuerung |
| `src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_passenger.py` | Struktureller Passagierindex, Mengenvariablen, Aktivierung, Kapazität, Ausstiegsaggregation und Kostenkodierung |
| `src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_integrated.py` | Konfiguration, eigener Optimierungslauf, Hints, Extraktion, Validierung, Ergebnis und versionierter Checkpoint |
| `src/ropeway_skip_stop_optimization/benchmarking/ddd_fixed_k_cp_sat.py` | Kanonische Instanzvorbereitung, gemeinsames Zeitbudget, Ergebnisdateien und Vergleichsmetadaten |
| `benchmarks/run_ddd_fixed_k_cp_sat.py` | CLI für Build-only, festen Fahrplan und vollständige Optimierung |
| `tests/test_optimization_ddd_cp_sat_passenger.py` | Passagiersemantik und beide Kostenkodierungen |
| `tests/test_optimization_ddd_cp_sat_integrated.py` | Kleine vollständige Optima, Exaktheitsgrenzen und Zertifikate |
| `tests/test_benchmarking_ddd_fixed_k_cp_sat.py` | Budgets, Fingerprints, CLI-Konfiguration und Checkpoints |
| `docs/reference/ddd_integrated_cp_sat_passengers.md` | Nach Implementierung: tatsächliche Formulierung und unterstützte Domäne |

Der bestehende Primal-Oracle verwendet nach der Extraktion denselben Movement-Builder. Seine bisherigen Ergebnisse, Ausschluss-/Support-Funktionen und Tests müssen erhalten bleiben. Der neue Optimierer verwendet eine eigene Suchsteuerung; ein zusätzlicher Spezialfall tief in der alten Kandidatenschleife ist zu vermeiden.

## 4. Bewegungsmodell und notwendige Äquivalenzprüfung

Für Kabine c und Besuch v bleiben Zeit `t[c,v]`, Aktivität `a[c,v]` und Auswahl `s[c,v,o]` für Route o erhalten. Im aktiven Besuch wird genau eine Route gewählt. Unter No-Wait ergibt sich die nächste Zeit aus der aktuellen Zeit plus der Dauer der gewählten Route. Inaktive Terminalfortsetzung entspricht exakt der vorhandenen Fixed-K-Semantik.

Der gemeinsame Builder gibt mindestens folgende Zuordnungen zurück:

- Ereigniszeit, Besuchsaktivität, Zustand und mögliche Routen je Kabine/Besuch;
- ausgewählte Stop-Routen und deren Plattform-Eintritts-/Austrittszeiten;
- geschützte Intervalle je Ressource, inklusive Anfangsbelegung;
- Zeitunter-/obergrenzen und den sicheren maximalen Besuchsumfang;
- Daten für Hints und deterministische Rekonstruktion.

Boarding entspricht dem vorhandenen Plattform-Austrittsereignis, Alighting dem Plattform-Eintrittsereignis. Falls mehrere Stop-Routen unterschiedliche Offsets haben, müssen die Ereigniszeiten unter der jeweils ausgewählten Route festgelegt werden. Ein gemeinsamer konstanter Offset ist nur erlaubt, wenn die Gleichheit zuvor geprüft wurde.

Die vorhandene Ressourcenabbildung mit halboffenen geschützten Intervallen ist für die unterstützte Domäne zu bestätigen. Vorgängerabhängige Schutzzeiten, Zweig-FIFO, gleichzeitige Mehrfachnutzung und Belegungen über Zeit null bleiben erhalten. Es darf nicht pauschal jede Headway-Matrix durch einen symmetrischen Abstand ersetzt werden. Wenn die Intervallabbildung eine zulässige Variante nicht ausdrücken kann, muss v1 diese Variante ablehnen oder eine nachweislich äquivalente Disjunktion ergänzen.

**Nachweisaufgabe:** Für kleine Instanzen zulässige vollständige Routenbelegungen enumerieren und CP-Feasibility mit der unabhängigen Ressourcenprüfung sowie dem vollständigen Referenzmodell vergleichen. Beide Richtungen prüfen: kein ungültiger Plan akzeptiert und kein gültiger Referenzplan ausgeschlossen. Der sichere Besuchsumfang muss unabhängig von einem Seed alle zulässigen No-Wait-Fortsetzungen abdecken.

## 5. Vollständige Passagierzuweisung

### 5.1 Domäne und Variablen

Für Nachfragegruppe g seien `d[g]` die Anzahl und `r[g]` die Release-Zeit. Für jeden strukturell möglichen direkten Fahrtkandidaten q mit Kabine c, Boarding-Besuch i und Alighting-Besuch j:

\[
0\le y_q\le U_q=\min(d_{g(q)},C),\qquad y_q\in\mathbb Z.
\]

`y[q]` beschreibt die gemeinsam zugewiesene Anzahl, nicht eine LP-Menge. Zusätzlich gibt es ein Literal `used[q]` für `y[q] >= 1`. Die Äquivalenz wird durch `used => y >= 1` und `not used => y = 0` hergestellt. Unbediente Nachfrage kann als `u[g] = d[g] - sum(y[q])` abgeleitet oder als eigene begrenzte Ganzzahlvariable geführt werden.

Die neue Domäne wird aus Besuchspaaren erzeugt und enthält keine Fahrt-pro-Zeittick-Variablen. Nicht verwendet werden `DddArcFlowPassengerDomainBuilder` und seine zeitexpandierten Passenger-Arcs. Frühe Abschneidung ist nur mit sicheren zeitlichen Untergrenzen zulässig. Besonders an Tick-Grenzen darf Float-Pruning keine im kanonischen Modell mögliche Fahrt entfernen.

### 5.2 Aktivierung

Wenn `used[q]` gilt, müssen gelten:

1. Boarding- und Alighting-Besuch sind aktiv und bedienen die richtige Station mit einer Stop-Route;
2. `board[q] >= r[g]`;
3. `board[q] <= H` und `alight[q] <= H`, jeweils nach vorhandener Service-Semantik;
4. `alight[q] >= board[q]`;
5. i < j, zulässige direkte Besuchsspanne, dieselbe Kabine, keine Transfers.

Die zeitlichen Bedingungen werden nur für benutzte Kandidaten erzwungen. Eine mögliche, aber unbenutzte Fahrt darf die Bewegung nicht einschränken. Umgekehrt ist ein gültiges Fahrtangebot keine Pflicht, Fahrgäste aufzunehmen.

### 5.3 Nachfrage und Kapazität

\[
\sum_{q:g(q)=g} y_q + u_g=d_g.
\]

Für jeden Kabinenabschnitt zwischen Besuchen v und v+1:

\[
\sum_{q:c(q)=c,\ i(q)\le v<j(q)} y_q\le C.
\]

Die Besuchsspanne ist statisch; deshalb sind diese Kapazitätsbedingungen linear und benötigen keine zeitexpandierten Passenger-Flüsse. An einer Station erfolgt Alighting vor dem anschließenden Boarding gemäß dem bestehenden Modell. Die Kapazität der Weiterfahrt darf frei gewordene Plätze wieder nutzen.

Nachfragegruppen bleiben getrennt, sobald Release-Zeit, OD oder eine andere relevante Bedingung verschieden ist. Aggregiert werden nur wirklich austauschbare Personen. Die erste Version enthält keine initial bereits onboard befindlichen Passagiere.

## 6. Zielfunktion nach Ausstiegsereignissen

Für eine innerhalb des Servicehorizonts freigegebene Person sind die bisherigen Journey-Time-Kosten bei Bedienung `t_alight - r`, bei Nichtbedienung `H - r`. Die Veränderung durch Bedienung ist daher `t_alight - H`.

Sei e ein konkretes Alighting-Ereignis einer Kabine, mit Zeit `T[e]`. Definiere

\[
A_e=\sum_{q:\operatorname{alight}(q)=e}y_q,
\qquad 0\le A_e\le C,
\]

und die konstante Nichtbedienungskostenbasis

\[
F_0=\sum_g d_g\max(0,H-r_g).
\]

Dann lautet das zu minimierende Ziel:

\[
F=F_0+\sum_e A_e(T_e-H).
\]

Gruppen mit Release nach H haben keine bedienbaren Kandidaten und bleiben mit ihrer kanonischen Nichtbedienungsbewertung in der Bilanz. Unterschiedliche Release-Zeiten kürzen sich nur in der Kostendifferenz heraus; in den Boarding-Bedingungen bleiben sie zwingend erhalten.

Die algebraische Kürzung ist bereits in den vorhandenen Arc-Flow-/Thesis-Herleitungen enthalten. Die zusätzliche Implementierungsentscheidung hier ist, alle zu einem Alighting-Ereignis gehörenden Fahrtmengen **vor** der variablen Zeitkopplung zu aggregieren. Das spart Kostenkopplungen, ohne Nachfragegruppen oder Kapazitätsbeziehungen zu verlieren.

### 6.1 Zwei äquivalente Kostenkodierungen

**Referenz: direktes Produkt.** Für jedes Ereignis `P[e] = A[e] * T[e]` mit `AddMultiplicationEquality` und Ziel `F0 + sum(P[e] - H*A[e])`. Die Produktdomäne muss alle legalen Werte abdecken. Inaktive Ereignisse haben `A[e]=0`; ihr beliebiger zulässiger Dummy-Zeitwert darf keine zusätzlichen Bedingungen erzeugen.

**Vergleich: kapazitätsbeschränkte unäre Darstellung.** Für k=1,...,C ein Literal `b[e,k]`, mit `b[e,k] >= b[e,k+1]` und `A[e] = sum_k b[e,k]`. Hilfsvariable `z[e,k]` erfüllt `z=T[e]` bei aktivem Literal, sonst `z=0`. Ziel: `F0 + sum_e,k(z[e,k] - H*b[e,k])`. Damit entstehen höchstens C bedingte Zeitkopplungen je Ausstiegsereignis.

Beide Kodierungen müssen auf kleinen Instanzen exakt dasselbe Optimum liefern. Direkte Produkte dienen als einfache Ausgangsversion. Die unäre Variante wird nur als kontrollierte Alternative getestet; keine große Parametersuche. Kleine Kabinenkapazität motiviert den Vergleich, beweist aber keinen Geschwindigkeitsvorteil.

### 6.2 Größe vor dem ersten großen Lauf

Build-only speichert mindestens: Anzahl Besuche, Routenliterals, Ressourcenintervalle, Nachfragegruppen, Fahrtkandidaten, Mengenvariablen, Used-Literals, Kapazitätsbedingungen, Ausstiegsereignisse und Kostenhilfsvariablen. Erwartete Struktur: ein Mengenwert pro strukturellem Fahrtkandidaten; Kostenkopplungen pro Alighting-Ereignis statt pro Kandidat und Zeitarc.

Vor der Solverübergabe Grenzen sämtlicher Produkte, Zielfunktionskonstanten und Ausdruckssummen gegen den CP-SAT-Integerbereich prüfen und `model.validate()` aufrufen. Große Domänen werden nicht still gerundet oder gekappt. Mikrosekunden sind eine Integerdarstellung, keine Aufforderung, pro Mikrosekunde einen Zustand anzulegen.

## 7. Exakter Optimierungslauf und Zertifikatsvertrag

### 7.1 Eigene Suchsteuerung

Der neue `DddIntegratedCpSatOptimizer` führt einen vollständigen Optimierungslauf aus. Er übernimmt nicht die alte Schleife zum Sammeln und Ausschließen von Kandidaten.

- `stop_after_first_solution = false`;
- keine Präferenzbegrenzung, kein Hamming-Ausschluss, keine festgehaltenen Kabinenrouten im globalen Modus;
- Hints sind Hinweise, keine Fixierungen;
- positives relatives/absolutes Gap-Limit in v1 nicht als Optimalitätsbeweis verwenden; Standard für Beweisläufe ist null;
- Zeitbudget, Workerzahl und Zufallsseed explizit speichern;
- Unterbrechung exportiert besten validierten Incumbent und verfügbare globale Schranke;
- keine automatische Folgekampagne nach einem erfolgreichen Smoke-Test.

Ein diagnostischer Modus mit festem Fahrplan ist für Tests erlaubt. Seine Schranke wird ausdrücklich als `FIXED_MOVEMENT` markiert und darf nicht im globalen Fixed-K-Gap erscheinen. Entsprechend sind spätere Nachbarschafts-/Proximity-Modi eigene Beweisbereiche.

### 7.2 Zeit- und Zielskalierung

Das Modell übernimmt die kanonischen Tickwerte des Fixed-K-Problems. Bereits aufgerundete Sicherheitsabstände werden nicht erneut aus Float-Sekunden rekonstruiert. Alle Zielfunktionswerte werden intern mit derselben Zeiteinheit und derselben Konstanten F0 geführt.

Exaktheit bezieht sich auf diese endliche Domäne, nicht auf beliebige kontinuierliche Zeiten. Vergleichbarkeit mit dem alten Ergebnis verlangt sowohl den passenden Fingerprint als auch die bestätigte Bewegungs-/Passagieräquivalenz. Der Proof-Vertrag dokumentiert diese Voraussetzung.

Solver-Bounds werden mit korrekter Konstante und Skalierung zurückgerechnet. Eine Float-Ausgabe wird nicht durch Runden auf den nächsten Integer künstlich verstärkt. Bei nicht sicher interpretierbaren großen Werten wird kein exakter Gap-Schluss behauptet. Eine konservative Umrechnung und Prüfung der Tickgenauigkeit ist Teil der Tests.

### 7.3 Ergebnisdaten

Geplantes Ergebnis enthält mindestens:

- `problem_fingerprint`, `model_fingerprint`, `proof_scope`, `formulation_version`;
- `time_ticks_per_second`, `objective`, `objective_constant_tick`, `cost_encoding`;
- `solver_status`, `termination_reason`, `proven_optimal`, `model_validation_error`;
- `cp_objective_tick`, `cp_best_bound_tick`, `validated_upper_bound`, `cp_lower_bound`, `combined_lower_bound`, `relative_gap`;
- vollständigen Bewegungsplan, Fahrtmengen und unbediente Nachfrage;
- `prepare_seconds`, `build_seconds`, `solve_seconds`, `validation_seconds`, `total_wall_seconds`;
- Modellgrößen, Konflikte, Branches, Worker, Seed, Peak-RSS und Seed-Provenienz;
- zeitgestempelte UB-/LB-Samples und Checkpointpfad.

Ein validierter externer Seed bleibt als UB verfügbar, auch wenn CP-SAT im Budget keinen eigenen Incumbent findet. Er wird nicht als vom Solver übernommene Lösung ausgegeben. `UNKNOWN` ist weder Infeasibility noch ein fehlender UB, wenn ein externer Plan vorliegt. Ein Widerspruch zwischen einem validierten Seed und CP-`INFEASIBLE` ist ein Modell-/Domänenfehler und beendet den Vergleich.

`OPTIMAL` zählt nur mit gültiger eigener Zielfunktion, vollständiger Domäne, passenden Solver-Abbruchparametern und validiertem Plan als Abschluss. Die im bisherigen Primal-Oracle gespeicherten `passenger_pricing_objective_bound` sind für diesen Zweck unbrauchbar.

## 8. Hints, Validierung und Checkpoints

### 8.1 Startlösung

Vorhandene kompatible Arc-Flow-Ergebnisse bzw. Root-CG-Checkpoints werden über die bestehenden Importer in `DddFixedKPrimalSeed` überführt. Gemappt werden Zeiten, Routen, Aktivitätsliterals, Fahrtmengen, Used-Literals, Ausstiegsmengen und Kostenhilfsvariablen. Seed-Zielwert und Fahrtmengen werden vor der CP-Suche erneut geprüft.

Für K=39 ist der anonyme gespeicherte Plan unmittelbar verfügbar. Der bessere CP/Root-CG-Wert allein ist kein Seed; seine vollständigen Trajektorien und eine gültige Zuordnung müssen erst reproduziert oder rekonstruiert werden. Der erste Leistungsversuch darf ersatzweise den verfügbaren anonymen Plan verwenden, dann aber für alle Vergleichssolver denselben.

### 8.2 Zwei unterschiedliche Prüfungen

**Prüfung des exportierten Incumbents:** Bewegungsplan und genau die exportierten Integer-Fahrtmengen gegen Physik, Nachfrage, Zeitbedingungen und Abschnittskapazitäten prüfen. Den Kostenwert aus diesen Daten unabhängig neu berechnen. Ein Fehler verhindert die Aufnahme als validierte UB.

**Nachoptimierung bei festgehaltener Bewegung:** Der bestehende Passenger-IP darf eine andere Zuordnung mit kleinerem Zielwert finden. Das ist bei einem zeitlimitierten integrierten CP-Incumbent kein Korrektheitsfehler; der nachoptimierte Plan kann die UB weiter senken. Gleichheit der optimalen Werte wird nur verlangt, wenn beide Verfahren dieselbe feste Bewegung nachweislich optimal bewerten. Eine LP-Lösung ist kein Ersatz für die ganzzahlige Zuordnung.

Validator und CP-Modell verwenden dieselben Tick-/Offset-Semantiken, werden aber unabhängig ausgewertet. Negative Zeiten, Grenzfälle und Rundungsabweichungen werden nicht durch großzügige Toleranzen verdeckt.

### 8.3 Persistenz

Der versionierte Checkpoint speichert vollständige kanonische Trajektorien und Passagiermengen samt Fingerprints und Kosten. Schreiben erfolgt atomar erst nach erfolgreicher Prüfung. Im Callback werden günstige Integerdaten gesichert; teure externe Passagieroptimierung läuft nicht bei jedem Solverereignis im Callback.

Ein Neustart mit Checkpoint ist ein Warm-Start. Er setzt den vorherigen CP-SAT-Suchbaum nicht fort. Der Benchmark rechnet Import-, Vorbereitungs-, Validierungs- und Optimierungszeit dem jeweiligen Arbeitsbudget zu und zeigt die Komponenten getrennt.

## 9. Arbeitspakete in verbindlicher Reihenfolge

| Paket | Konkrete Arbeit | Abnahme / Ergebnis | Grober Aufwand |
|---|---|---|---|
| **P0** | Bestehenden Reservoir-Statusfehler in separatem Fix beheben; Statuscode-Zuordnung nach vorhandener Konvention ergänzen | Alle acht Reservoirtests bestehen; sinnvoller Test für Statusausgabe | 1–2 Stunden, sofern kein weiterer Defekt sichtbar wird |
| **P1** | Gemeinsamen CP-Movement-Builder extrahieren; unveränderte bisherige Heuristik darüber aufbauen | Bestehende CP-Primaltests bestehen; keine Routen-/Zeitsemantik verändert | Etwa ein halber Tag |
| **P2** | Strukturelle Fahrtmengen, Aktivierung, Kapazität und aggregierte Kosten bauen; Fixed-Movement-Modus | G0: exakte Übereinstimmung mit Passenger-IP auf mehreren festen Plänen | Etwa ein Tag |
| **P3** | Integrierten Optimierungslauf, Resultat, Hints, Validator und Checkpoint verbinden | G1: vollständige kleine Instanzen und Grenzfälle; korrekte LB-/UB-Semantik | Etwa ein Tag |
| **P4** | CLI und Build-only; beide Kostenkodierungen begrenzt vergleichen | G2: K=20-Referenz geprüft; Modellgröße und Laufzeit dokumentiert | Etwa ein halber bis ein Tag plus Solverbudget |
| **P5** | Kontrollierter K=39-Vergleich und Entscheidung | G3: native/kompatible Bounds, validierte Lösungen, gleicher Start und Kostenrahmen | Etwa ein halber Tag Auswertung plus Solverbudget |

Gesamteinschätzung: etwa drei bis vier fokussierte Arbeitstage bei problemloser Wiederverwendung. Das ist ein Budgetrahmen für den Versuch, keine Zusage. Nach P2/P3 liegt die erste belastbare Information über Modellgröße und Korrektheit vor. Bei strukturellen Problemen wird der Umfang neu bewertet, statt automatisch bis K=39 weiterzubauen.

P0 ist eine separate Wartung des gesicherten Stands und ändert die mathematische CP-Aufgabe nicht. Die neue CP-Implementierung darf bei einem größeren Reservoir-Folgeproblem unabhängig weiterentwickelt werden; der bekannte Fehler bleibt dann ausdrücklich offen und blockiert nur Reservoir-Läufe.

### G0: feste Bewegung und exakte Passagierbewertung

Testfälle: eine OD-Gruppe; mehrere Gruppen mit überlappender Sitzplatznutzung; Aussteigen und Einsteigen am selben Besuch; identische OD mit unterschiedlichen Releases; keine Nachfrage; vollständig unbedienbare Nachfrage; Boarding exakt bei Release; Boarding davor; Alighting exakt H und einen Tick danach; fehlender Stop an einem Fahrtende; ausgeschalteter Kandidat mit sonst unzulässigen Zeitwerten.

Beide Kostenkodierungen gegen die direkte Summe der ursprünglichen served/unserved-Kosten prüfen. Verschiedene Fahrtzuordnungen mit gleichem Optimum sind zulässig. Das vorhandene Nichtintegralitäts-Gegenbeispiel des Passenger-LP wird als Regression aufgenommen: die CP-Lösung muss ganzzahlig bleiben.

### G1: freies integriertes Modell

Kleine Instanzen mit wenigen Kabinen und Stopentscheidungen vollständig enumerieren. Zu jeder gültigen Bewegung den Passenger-IP lösen und das globale Minimum mit CP-SAT vergleichen. Zusätzlich Anfangsbelegungen, unterschiedliche Stop-/Skip-Headways, exakte Berührung halboffener Intervalle, mehrere Umläufe und die Terminalfortsetzung testen.

Fahrtkandidaten, die in einem Seed nicht genutzt wurden, müssen in einer optimalen Alternativlösung nutzbar bleiben. Ein bewusst inkompatibler Fingerprint wird abgelehnt. `UNKNOWN`, `FEASIBLE`, `OPTIMAL` und feste-Bewegung-Schranken dürfen nicht verwechselt werden. Modellfehler, Budgets und Checkpointunterbrechungen erhalten gezielte Tests.

### G2: K=20 und Größenprüfung

Zunächst Build-only auf K=20 und K=39 mit je maximal fünf Minuten Gesamtbudget; Modellgrößen und Speicher protokollieren. Bei mehrminütigem Aufbau bereits für K=20 zuerst die Ursache untersuchen.

Danach K=20 mit höchstens 300 Sekunden Gesamtbudget je Kostenkodierung, identischem validiertem Seed und gleicher Workerzahl testen. Ziel ist die Reproduktion des bekannten Optimums und ein korrekter Gap. Wird das Optimum nicht bewiesen, ist das zunächst ein Leistungsbefund, kein Korrektheitsbeweis gegen das Modell. Falls bereits die kleinen G1-Optima abweichen, wird jedoch kein größerer Benchmark gestartet.

Vor G3 werden nur zwei Kostenkodierungen und keine weiteren Modellfamilien verglichen. Wenn beide bei K=20 kaum verwertbare Schranken erzeugen oder der Modellaufbau das Budget aufbraucht, wird der K=39-Versuch zurückgestellt. Ein langsamerer K=20-Lauf kann trotzdem einen begrenzten K=39-Test rechtfertigen, wenn Aufbau und Schrankenbildung funktionieren; die Entscheidung wird dokumentiert.

### G3: K=39 mit identischer Instanz und gleichem Start

1. Beste verfügbare vollständige Startlösung wählen und für CP-SAT sowie vollständiges Arc-Flow verwenden. Vorhandene historische Werte dienen der Orientierung, nicht als neuer fairer Laufzeitvergleich.
2. Die in G2 gewählte CP-Kodierung zunächst zehn Minuten, dann höchstens 30 Minuten Gesamtbudget testen. Ein 60-Minuten-Lauf folgt nur bei erkennbarer UB-/LB-Bewegung oder einem klar begründeten Diagnosebedarf.
3. Den ausgewählten Arc-Flow-Vergleich mit gleicher Instanz, Startlösung, Hardware und Worker-/Threadzahl rechnen. Leistungsversuche nicht gleichzeitig auf derselben Maschine ausführen.
4. Zeit bis zur ersten verbesserten UB, beste UB, native LB, kompatible kombinierte LB, relativen Gap, Aufbau und Peak-RSS vergleichen. Externe LB-Übernahme darf einen schwachen nativen CP-Bound nicht verdecken.
5. Bei positivem Ergebnis einmal mit weiterem Zufallsseed bestätigen; anschließend einen vorab festgelegten zusätzlichen Nachfragefall prüfen. Keine breite Parametersuche vor der Präsentation.

Für positive UB ist der ausgewiesene relative Gap `(UB - LB) / abs(UB)` mit zusätzlichem absoluten Gap. Bei UB=0 ist nur ein konsistenter absoluter Gap sinnvoll. Unterschiedliche Solverstatus allein sind kein Leistungsmaß.

## 10. Entscheidungsregeln nach dem Versuch

| Beobachtung | Entscheidung |
|---|---|
| CP verbessert UB und LB bei gleichem Budget | Als ernsthaften exakten Konkurrenten weiterverwenden; kleine Nachfragekampagne statt weiterer Methodenentwicklung |
| CP verbessert vor allem UB, native LB bleibt schwach | Als Primalverfahren mit passendem unabhängigem Beweiskanal verwenden; keine Behauptung einer besseren Gap-Schließung durch CP allein |
| CP verbessert vor allem LB | Mit bestem kompatiblen externen Fahrplan kombinieren; weitere Zeit nur bei fortgesetzter Schrankenbewegung |
| Beide Kostenkodierungen stagnieren, Größe ist ähnlich problematisch wie Arc-Flow | Versuch mit Nullbefund dokumentieren; nicht unmittelbar weitere umfassende Modellvarianten bauen |
| Modell- oder Domänenabweichung | Zertifikate nicht veröffentlichen; Ursache auf kleinster Gegeninstanz beheben |

Die Präsentation am 21. September braucht bis zum 18. September auswertbare Resultate. Spätestens nach dem begrenzten G3-Versuch wird entschieden, ob CP-SAT in die Ergebniskampagne aufgenommen wird. Die Erstellung von Tabellen, Nachfragevergleichen und Folien darf nicht von einem noch offenen großen Optimalitätsbeweis abhängen.

## 11. Vorgesehene CLI und Ablage

Geplante CLI-Optionen: `--example`, `--cabin-count`, `--start-policy`, `--objective`, `--time-limit-seconds`, `--num-workers`, `--seed`, `--cost-encoding product|unary`, `--primal-seed-result`, `--primal-seed-checkpoint`, `--checkpoint`, `--output-dir`, `--build-only`, `--fixed-movement-result`.

Die endgültigen Namen sollen sich an den existierenden Fixed-K-Runnern orientieren. Globale und diagnostisch festgehaltene Bewegung werden im Output klar unterschieden. Unsupported-Waiting/Reservoir-Optionen werden zurückgewiesen, statt ignoriert zu werden.

Geplante Ergebnisablage: `benchmarks/output/ddd_integrated_cp_sat/<instance>/<run_id>/` mit `config.json`, `result.json`, `events.jsonl`, `incumbent.json` und Solverlog. Eine knappe Auswertung wird nach G3 unter `docs/findings/ddd_integrated_cp_sat_gate.md` angelegt. Große Ergebnisdateien bleiben unter den vorhandenen Ignore-/Artefaktregeln; die Findings nennen präzise Pfade und Fingerprints.

## 12. Vorgesehene Implementierungscommits

1. `fix(ddd): restore reservoir status reporting` — vorhandener Checkpointfehler und gezielte Regression.
2. `refactor(ddd): extract CP-SAT movement builder` — ausschließlich gemeinsame Konstruktion, alte Primaltests unverändert grün.
3. `feat(ddd): add integer CP-SAT passenger model` — G0, beide exakten Kostenkodierungen.
4. `feat(ddd): add integrated CP-SAT optimizer` — G1, Hints, Validierung und Zertifikate.
5. `feat(benchmarks): add fixed-k CP-SAT runner` — Build-only, Budgets, persistente Ergebnisse.
6. `docs(ddd): report integrated CP-SAT gate` — tatsächliche G2/G3-Befunde einschließlich Nullbefunden.

Die Implementierung beginnt erst nach diesem Plan. Vorhandene Solver werden durch den neuen Pfad nicht ersetzt. Ein Codepfad wird erst dann als exakter integrierter Solver bezeichnet, wenn die oben beschriebenen Domänen- und Zertifikatsprüfungen erfüllt sind.

## Quellen und fachliche Grundlage

- [OR-Tools: CP-SAT Solver](https://developers.google.com/optimization/cp/cp_solver): ganzzahlige Modellierung und Solverstatus.
- [OR-Tools: Integer arithmetic](https://github.com/google/or-tools/blob/stable/ortools/sat/docs/integer_arithmetic.md): Produktbedingungen und exakte Kopplung von Boolean- und Integervariablen.
- [Joaquín Rodriguez (2007): A constraint programming model for real-time train scheduling at junctions](https://doi.org/10.1016/j.trb.2006.02.006): ereignis-/ressourcenbasierte CP-Modellierung in der Zugdisposition; kein direkter Ropeway-Leistungsnachweis.
- [Gange, Harabor, Stuckey (2019): Lazy CBS](https://ojs.aaai.org/index.php/ICAPS/article/view/3471): wiederverwendbares Konfliktlernen als methodischer Hintergrund. V1 implementiert keinen eigenen CBS-Suchbaum.
- Die konkrete Mengen-, Kapazitäts- und Kostenformulierung folgt dem vorhandenen Fixed-Movement-Passenger-Modell und dessen kanonischem Ziel. Die Ausstiegsaggregation ist eine algebraisch äquivalente Implementierungsentscheidung unter diesen Kostenannahmen; ihre Geschwindigkeit ist experimentell zu bewerten.
