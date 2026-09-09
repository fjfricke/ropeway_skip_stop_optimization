# Vollständiger CP-SAT-Solver mit Passagieren

## 1. Ziel und Ausgangsstand

Status: **erste Version implementiert; erste Gates ausgewertet**. Stand: 9. September 2026.

Die ursprünglichen Anforderungen und Abnahmekriterien bleiben unten nachvollziehbar. Der tatsächliche Stand steht in der [Implementierungsreferenz](../reference/ddd_integrated_cp_sat_passengers.md) und den [Gate-Befunden](../findings/ddd_integrated_cp_sat_gate.md). P0 und P1 sind abgeschlossen; integrierte Passagiere, beide Kostenkodierungen, unabhängige Prüfung, Hints, native Checkpoints und CLI sind vorhanden. K=20 wurde je Kodierung mit fünf Minuten geprüft. Ein einzelner K=39-Produkttest verbesserte in rund zehn Minuten die UB auf 1.272.673,026168; native LB 402.843,295830, Gap 68,35 %. Die unabhängige fixe Passagier-IP-Bewertung bestätigt denselben Wert. 172 Tests sind grün. Der faire Arc-Flow-Vergleich mit gemeinsamem Seed, ein Wiederholungslauf und zusätzliche Demand-Profile bleiben offen; keine längere Kampagne wurde automatisch gestartet.

Modellabgleich am 9. September: Die Mengen-, Kapazitäts- und Journey-Time-Formulierung passt zur bestehenden Fixed-K-No-Wait-Aufgabe. Die Erstfassung war bei Horizonten, Headways, Kandidatendomäne und Vergleichsidentität zu unbestimmt. Die folgenden Präzisierungen sind verbindlicher Teil der Umsetzung; sie sind noch kein Nachweis für einen implementierten CP-Solver.

Ziel ist ein ereignisbasiertes CP-SAT-Modell, das Stop-/Skip-Bewegung und ganzzahlige Passagierzuweisung gemeinsam optimiert. Es soll für dieselbe deklarierte Fixed-K-No-Wait-Domäne wie das vollständige Arc-Flow gültige obere und untere Schranken liefern. Der Leistungsversuch prüft, ob damit bei K=39 schneller bessere Fahrpläne oder ein kleinerer zertifizierter Gap entstehen. Ein Laufzeitvorteil ist eine Hypothese, kein zugesagtes Ergebnis.

Der aktuelle Arbeitsstand wurde vor diesem Plan getrennt gesichert:

| Repository | Commit | Inhalt |
|---|---|---|
| Software, Branch `ddd` | `63bca5e` | Reservoir-Arc-Flow, Runner, Frontend-Metriken und Tests als experimenteller Checkpoint |
| Thesis `idp_report`, Branch `ddd` | `d5487ed` | Manuskriptstand, mathematische Herleitungen und Solver-Übersicht |
| Übergeordneter Workspace `idp`, Branch `main` | `7822c6c` | `PROJECT_STATUS.md`, `SOLVER_OVERVIEW.md`, `RESEARCH_CONCEPTS.md` |

Historischer Prüfstand des Checkpoints (vor der Umsetzung):

- Frontend: `npm run build` erfolgreich.
- CP-Primal-/Passagierzieltests: 19 bestanden.
- Reservoirtests: 7 bestanden, 1 fehlgeschlagen. `reservoir_arc_flow.py:626` ruft die nicht definierte Funktion `_solver_status_name` auf. Das ist ein vorhandener Laufzeitfehler, keine Folge der CP-SAT-Planung.
- Die LaTeX-Ziele für Hauptbericht, DDD-Herleitungen und Solver-Übersicht melden erfolgreiche, aktuelle Builds; es wurde kein erzwungener vollständiger Neubau durchgeführt.
- Kein neuer großer Solverbenchmark wurde für den Checkpoint gestartet.

Die ausführliche Ausgangsbewertung steht im [Solver-Overview](/Users/felix/Programming/idp/ropeway/SOLVER_OVERVIEW.md), die methodische Einordnung in der [Forschungslandkarte](/Users/felix/Programming/idp/ropeway/RESEARCH_CONCEPTS.md).

## 2. Verbindlicher Umfang der ersten Version

Die erste Version behandelt ausschließlich:

1. einen gerichteten Ring mit nach jedem Besuch wieder zusammenlaufenden Stop-/Skip-Optionen, genau einer Stop-Option je Zustand und festen Routendauern;
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
| Five-Station B, Beispiel `five_station_circle_cw_half_skip_no_wait_headway_b_v0`, K=20, Balanced Reference, No-Wait, Journey Time | `2c53481066e498cc29ec206e717911f55d1ac30296cdc5cb8ac05139b35fbd01` | Bekannter Optimalwert ungefähr 525.730,908; vollständigen gespeicherten Wert verwenden |
| Gleiche Betriebsfamilie, K=39 | `2f82126c06273d2299ab258ca5c5d92acc9d83d829360422f8473c26521cc0f0` | Anonymes Arc-Flow: UB 1.376.000,783, LB 441.919,534 nach etwa 1 h; CP/Root-CG: UB 1.326.950,671, vollständiger Export noch zu beschaffen |

Fingerprint und vollständiger Zielfunktionswert sind beim Laden zu prüfen. Ein K=20-Canonical-Rope-Fall ist nicht dieselbe Instanz. Ein passender globaler Bound darf nur nach bewiesener Domänenübereinstimmung kombiniert werden. Zur Diagnose werden native CP-Bounds und gegebenenfalls externe Bounds getrennt gespeichert.

Die `half`-Basisvariante verwendet ursprünglich jeden zweiten Kabinenstart und 64 statt 128 Personen je OD; „halbe Nachfrage“ ist somit zutreffend. Der Fixed-K-Runner ersetzt ihre Startregel durch die gewählte Fixed-K-Startpolitik, behält aber die Nachfrage bei. Der am 9. September frisch vorbereitete K=20-Fall reproduziert den obigen Fingerprint und enthält 1.280 Personen in 20 OD-Gruppen, alle mit Release 0, Kabinenkapazität 8, fünf Zustände, zehn Routen, zehn Ressourcen und 2.560 strukturelle Fahrtkandidaten. Service- und Bewegungsende liegen hier beide bei 1.200 s; die Besuchsgrenzen sind 36 bzw. 37 je Kabine. Zeitlich verteilte Demand-Profile sind damit noch nicht untersucht.

### 2.2 Genaue Problemidentität und Reichweite

Der bestehende `DddFixedKTrajectoryProblem.fingerprint` enthält unter anderem Starts, Horizonte, Nachfrage und Routen-IDs, jedoch **nicht** Kabinenkapazität, vollständige Routendauern/-Offsets, sämtliche Ressourcenparameter oder die konkrete Fahrtkandidatenliste. Beim Abgleich ließ sich Kapazität oder Kandidatenliste ändern, ohne den Fingerprint zu ändern. Dieser Hash bleibt für historische Ergebnisse erhalten, ist aber allein kein ausreichender Äquivalenznachweis.

Der neue Runner speichert deshalb zusätzlich ein solverunabhängiges `domain_manifest` mit `domain_fingerprint`: vollständige Tick-Routen-/Ressourcendaten, Start- und Anfangsbelegungen, Kapazität, Nachfrage einschließlich Releases, Horizonte, Besuchsgrenzen, zulässige Kandidaten-IDs/-Besuchspaare, Betriebsmodus und Kostenannahmen. `model_fingerprint` identifiziert zusätzlich die konkrete CP-Kodierung. Für historische Bounds ohne Manifest müssen diese Daten aus der jeweiligen Instanz nachvollzogen werden; ein bloßer Hash-Treffer erlaubt noch keine Übernahme.

Der globale Beweisbereich ist **Fixed-K mit genau diesen festen Starts und dieser endlichen Passagier-/Bewegungsdomäne**. Er umfasst weder frei optimierte Anfangslagen noch unbegrenzten Betrieb nach dem Horizont. Bei K=39 liefert die periodische Balanced-Reference-Konstruktion feste Anfangslagen und eine Startlösung; sie verpflichtet spätere Stop-/Skip-Entscheidungen nicht zur Periodizität.

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

### 3.2 Geplante und inzwischen angelegte Dateien

Die folgenden Dateien wurden angelegt. Zusätzlich wurde die unabhängige Domänen-/Lösungsprüfung in `cp_sat_certificate.py` ausgelagert. Alle Pfade beziehen sich auf das Software-Repository.

| Pfad | Verantwortung |
|---|---|
| `src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_movement.py` | Gemeinsamer Movement-Builder; liefert `CpModel`-Variablen und semantische Ereigniszuordnung ohne Suchsteuerung |
| `src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_passenger.py` | Struktureller Passagierindex, Mengenvariablen, Aktivierung, Kapazität, Ausstiegsaggregation und Kostenkodierung |
| `src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_certificate.py` | Domänenmanifest, unabhängige Integer-/Physikprüfung und atomare Checkpoints |
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

Boarding entspricht dem vorhandenen Plattform-Austrittsereignis, Alighting dem Plattform-Eintrittsereignis. V1 verwendet wie der Arc-Flow-Passagierbuilder `unique_stop_route_option`: genau eine Stop-Option je Zustand, daher eindeutige Offsets. Mehrere Stop-Optionen sind vorerst abzulehnen. Eine spätere Erweiterung braucht routenabhängige Ereigniszeiten und einen eigenen Domänenvergleich.

### 4.1 Physikalische Route und Reihenfolge

Ein Besuch beginnt am Eingangswechsel der Station. Die Stop-Dauer enthält Fahrt zur Plattform, feste Plattformdurchfahrt, Fahrt zum Ausgangswechsel und Seilfahrt zum nächsten Eingangswechsel. Skip verwendet die Bypassdauer plus dieselbe anschließende Seilfahrt. Alle Zeiten kommen aus dem adaptierten Movement-Core; keine neue freie Fahrzeit oder von der Fahrgastzahl abhängige Haltezeit einführen. No-Wait heißt keine zusätzliche Warteentscheidung; eine Stop-Kabine benötigt weiterhin ihre feste Stationszeit. Routen, die der konfigurierte Stationsmechanismus nicht anbietet, bleiben ausgeschlossen. Im All-Stop-Vergleich ist `resolved_trajectory_problem` mit herausgefilterten Skip-Routen zu verwenden.

Es gibt keine neue globale Reihenfolgebedingung zwischen Kabinen. Auf derselben Route erhalten gleiche feste Offsets unter No-Wait die Reihenfolge. Stop und Skip dürfen sich dagegen über die getrennten Stationszweige relativ überholen; am Zusammenführen gelten die Ressourcenabstände. Insbesondere darf keine aus Kabinen-IDs oder dem Seed übernommene Reihenfolge zulässiges Bypass-Überholen verhindern.

### 4.2 Headways als Schutzintervalle

Das aktuelle physikalische Modell verwendet konstante oder nur vom vorausfahrenden Routentyp abhängige Headways (`ConstantHeadwayRule`, `LeaderBehaviorHeadwayRule` in `models/headway.py`). Der DDD-Adapter legt den jeweiligen Wert in `usage.separation_after_tick(...)` ab. Für jede ausgewählte Ressourcennutzung wird unter No-Wait das halboffene Intervall

`[t[c,v] + follower_enter_offset, t[c,v] + leader_clear_offset + separation_after)`

verwendet. `NoOverlap` verlangt damit genau eine der beiden vorhandenen Abstandsbedingungen: B tritt nach der Freigabe plus Schutzzeit von A ein oder umgekehrt. Die aktuelle Architektur passt zu dieser Abbildung; ein bloßes Ersetzen aller Abstände durch Minimum, Maximum oder einen symmetrischen Mittelwert wäre ein anderes Modell. Beliebige künftig paarabhängige Headway-Matrizen sind durch diese Darstellung nicht automatisch unterstützt.

Die Intervalle sind Schutzzeiten an den vorhandenen Checkpoints, **keine exklusive Reservierung der gesamten Station oder der vollständigen Plattformdurchfahrt**. Beispielsweise hat eine Stop-Route an Station A im K=20-Fall Plattform-Eintritt bei +2,090909 s, Austritt bei +22,090909 s und dort einen Plattform-Eintrittsheadway von 7 s. Die ganze 20-s-Plattformdurchfahrt exklusiv zu sperren würde zulässige Kabinenfolgen entfernen. Sämtliche im Movement-Core vorhandenen Ressourcen werden übernommen; diagnostisches Abschalten einzelner Ressourcen aus dem alten Oracle ist im globalen Modus verboten.

Bei Anfangsbelegungen werden die vorhandenen abgeschnittenen festen Intervalle übernommen: Start `max(0, follower_enter_time)`, Ende `leader_clear_time + separation_after`; leere Intervalle entfallen. `boundary_only`/`boundary_origin`-Sonderfälle aus der Referenzprüfung dürfen nicht still als gewöhnliche Paarbedingungen behandelt werden. Falls solche Fälle auftreten, ist die Äquivalenz zur vorhandenen Ressourcenreduktion separat zu prüfen oder die Variante abzulehnen. Der K=39-Referenzbuilder deaktiviert die Ressourcenreduktion; der K=20-Referenzfall hat keine Boundary-Occurrences.

### 4.3 Zwei Horizonte und vollständige Fortsetzung

Im Folgenden gilt entsprechend `EanConfig`: **T = Serviceende**, **H = Bewegungsende = T + Tail**. Alle Passagierbedingungen und Nichtbedienungskosten verwenden T. Physikalische Aktivierung und Ressourcenbedingungen verwenden H. Dass beide im Referenzfall 1.200 s betragen, darf eine Verwechslung nicht verdecken.

Für v=0,...,N gilt `a[c,v] <=> t[c,v] <= H`, mit festem Start und `a[c,0]=1`, `a[c,N]=0`. Für v<N gilt `sum_o s[c,v,o]=a[c,v]` und `t[c,v+1]=t[c,v]+sum_o duration[o]*s[c,v,o]`. Damit muss eine Kabine jeden vor oder genau bei H begonnenen Besuch vollständig fortsetzen, bis der nächste Besuch nach H liegt; danach bleiben Zeiten in der inaktiven Fortsetzung konstant. Kein freiwilliges Parken, kein künstlicher Depotabschluss, keine Rückkehrpflicht zur Anfangsphase und keine kostenlose Deaktivierung nach dem letzten Fahrgast.

Eine ausgewählte Ressourcennutzung ist genau dann präsent, wenn ihr Eintritt `<= H` liegt. Ihr Schutzende darf H überschreiten und wird nicht abgeschnitten. Nutzungen mit Eintritt `> H` entfallen gemäß dem bestehenden Arc-Flow-/Referenzmodell. Diese Regel wird aus `_add_resource_intervals` übernommen, einschließlich der Äquivalenz des Präsenzliterals; nur `present => selected` wäre unzureichend.

N stammt aus der kanonischen Besuchsdomäne. Zusätzlich ist mit minimalen Routendauern in Ticks zu prüfen, dass selbst die schnellste Fortsetzung bei Index N nach H liegt. Andernfalls Eingabe als unzureichend begrenzt zurückweisen und die kanonische Instanzvorbereitung korrigieren; nicht nur den CP-Besuchsumfang heimlich erweitern. Die Terminalzeitdomäne muss mindestens bis `H + max(duration)` reichen, Ressourcenenden zusätzlich bis zu ihren Offsets und Schutzzeiten.

**Nachweisaufgabe:** Für kleine Instanzen zulässige vollständige Routenbelegungen enumerieren und CP-Feasibility mit der unabhängigen Ressourcenprüfung sowie dem vollständigen Referenzmodell vergleichen. Beide Richtungen prüfen: kein ungültiger Plan akzeptiert und kein gültiger Referenzplan ausgeschlossen. Der sichere Besuchsumfang muss unabhängig von einem Seed alle zulässigen No-Wait-Fortsetzungen abdecken.

## 5. Vollständige Passagierzuweisung

### 5.1 Domäne und Variablen

Für Nachfragegruppe g seien `d[g]` die Anzahl und `r[g]` die Release-Zeit. Für jeden strukturell möglichen direkten Fahrtkandidaten q mit Kabine c, Boarding-Besuch i und Alighting-Besuch j:

\[
0\le y_q\le U_q=\min(d_{g(q)},C),\qquad y_q\in\mathbb Z.
\]

`y[q]` beschreibt die gemeinsam zugewiesene Anzahl, nicht eine LP-Menge. Zusätzlich gibt es ein Literal `used[q]` für `y[q] >= 1`. Die Äquivalenz wird durch `used => y >= 1` und `not used => y = 0` hergestellt. Unbediente Nachfrage kann als `u[g] = d[g] - sum(y[q])` abgeleitet oder als eigene begrenzte Ganzzahlvariable geführt werden.

Die neue Domäne wird aus Besuchspaaren erzeugt und enthält keine Fahrt-pro-Zeittick-Variablen. Nicht verwendet werden `DddArcFlowPassengerDomainBuilder` und seine zeitexpandierten Passenger-Arcs. Frühe Abschneidung ist nur mit sicheren zeitlichen Untergrenzen zulässig. Besonders an Tick-Grenzen darf Float-Pruning keine im kanonischen Modell mögliche Fahrt entfernen.

Verbindlicher Ausgangspunkt ist die **konkrete vollständige strukturelle Liste** `problem.passenger_build.ride_candidates`, die auch Arc-Flow verwendet. „Vollständig“ bedeutet hier alle Kandidaten dieser deklarierten Domäne, nicht beliebige zusätzliche Mehrumlauffahrten. Bei aktiviertem Single-Ring-Pruning gilt `0 < j-i < len(artifact.circulation_state_ids)`; das sind Eingangswechselbesuche, keine Zeitticks. V1 übernimmt diese Einstellung und verändert sie nicht beiläufig. Eine neu erzeugte oder anders geprunte Liste ist vor dem Zertifikatsvergleich auf Gleichheit bzw. nachgewiesen sichere Entfernung unmöglicher Fahrten zu prüfen. Ein Unterschied zum bestehenden Float-Pruning ist ein zu klärender Domänenbefund. Erweiterungen auf Mehrumlauffahrten brauchen eine gesonderte Modellentscheidung, statt sie pauschal mit der bisherigen Code-Dominanzbegründung auszuschließen.

### 5.2 Aktivierung

Wenn `used[q]` gilt, müssen gelten:

1. Boarding- und Alighting-Besuch sind aktiv und bedienen die richtige Station mit einer Stop-Route;
2. `board[q] >= max(0, r[g])`;
3. `board[q] <= T` und `alight[q] <= T`, jeweils nach vorhandener Service-Semantik;
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

Physikalische Vorlaufbelegungen sind keine zusätzlichen Boarding-Angebote. Negative historische Boarding-Ereignisse bleiben wie in `_fixed_movement_ride` ausgeschlossen. Ein Fahrgast darf Zwischenstationen in derselben Kabine sowohl mit Stop als auch mit Skip durchfahren; nur Boarding und Alighting erzwingen einen Stop. Es gibt keine zusätzliche Pflicht zum frühestmöglichen Boarding, keine Passagier-FIFO-Zuweisung und keine Pflicht, jede Nachfrage zu bedienen. Nachfrageanzahl und Kabinenkapazität werden als nichtnegative bzw. positive Ganzzahlen validiert, ohne Rundung aus allgemeinen Floats.

## 6. Zielfunktion nach Ausstiegsereignissen

Für eine bis zum Serviceende T freigegebene Person sind die bisherigen Journey-Time-Kosten bei Bedienung `t_alight - r`, bei Nichtbedienung `T - r`. Die Veränderung durch Bedienung ist daher `t_alight - T`. Das Bewegungsende H gehört nicht in diese Kostenformel.

Sei e ein konkretes Alighting-Ereignis einer Kabine, mit Zeit `tau[e]`. Definiere

\[
A_e=\sum_{q:\operatorname{alight}(q)=e}y_q,
\qquad 0\le A_e\le C,
\]

und die konstante Nichtbedienungskostenbasis

\[
F_0=\sum_g d_g\max(0,T-r_g).
\]

Dann lautet das zu minimierende Ziel:

\[
F=F_0+\sum_e A_e(\tau_e-T).
\]

Gruppen mit Release nach T haben keine bedienbaren Kandidaten und bleiben mit ihrer kanonischen Nichtbedienungsbewertung in der Bilanz. Unterschiedliche Release-Zeiten kürzen sich nur in der Kostendifferenz heraus; in den Boarding-Bedingungen bleiben sie zwingend erhalten.

Diese Kosten sind ein endlicher Journey-Time-/Backlog-Vergleich und kein lexikografisches „erst alle bedienen“. Eine erst bei T aussteigende Person verbessert das Ziel gegenüber Nichtbedienung nicht. `served_count` und `unserved_count` werden deshalb zusätzlich zum Zielwert berichtet; ein anderes Strafgewicht oder Bedienungsziel wäre eine andere Vergleichsaufgabe. Beim verifizierten K=20-Eingang beträgt F0 genau 1.536.000 Personen-Sekunden, in Ticks 1.536.000.000.000.

Die algebraische Kürzung ist bereits in den vorhandenen Arc-Flow-/Thesis-Herleitungen enthalten. Die zusätzliche Implementierungsentscheidung hier ist, alle zu einem Alighting-Ereignis gehörenden Fahrtmengen **vor** der variablen Zeitkopplung zu aggregieren. Das spart Kostenkopplungen, ohne Nachfragegruppen oder Kapazitätsbeziehungen zu verlieren.

### 6.1 Zwei äquivalente Kostenkodierungen

**Referenz: direktes Produkt.** Für jedes Ereignis `P[e] = A[e] * tau[e]` mit `AddMultiplicationEquality` und Ziel `F0 + sum(P[e] - T*A[e])`. Die Produktdomäne muss alle legalen Werte abdecken. Inaktive Ereignisse haben `A[e]=0`; ihr beliebiger zulässiger Dummy-Zeitwert darf keine zusätzlichen Bedingungen erzeugen. Insbesondere `tau[e] <= T` nicht pauschal für ungenutzte Stop-Ereignisse erzwingen: physikalische Stopps im Tail bleiben möglich.

**Vergleich: kapazitätsbeschränkte unäre Darstellung.** Für k=1,...,C ein Literal `b[e,k]`, mit `b[e,k] >= b[e,k+1]` und `A[e] = sum_k b[e,k]`. Hilfsvariable `z[e,k]` erfüllt `z=tau[e]` bei aktivem Literal, sonst `z=0`. Ziel: `F0 + sum_e,k(z[e,k] - T*b[e,k])`. Damit entstehen höchstens C bedingte Zeitkopplungen je Ausstiegsereignis.

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

- `problem_fingerprint`, `domain_manifest`, `domain_fingerprint`, `model_fingerprint`, `proof_scope`, `formulation_version`;
- `time_ticks_per_second`, `objective`, `objective_constant_tick`, `cost_encoding`;
- `solver_status`, `termination_reason`, `proven_optimal`, `model_validation_error`;
- `cp_objective_tick`, `cp_best_bound_tick`, `validated_upper_bound`, `cp_lower_bound`, `combined_lower_bound`, `relative_gap`;
- vollständigen Bewegungsplan, Fahrtmengen, `served_count` und `unserved_count` sowie unbediente Nachfrage je Gruppe;
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
| **P1** | Domänenmanifest und Eingabeprüfungen; gemeinsamen CP-Movement-Builder extrahieren; bisherige Heuristik darüber aufbauen | Bestehende CP-Primaltests bestehen; Horizont-, Headway- und Besuchssemantik aus Abschnitt 4 geprüft | Etwa ein halber bis ein Tag |
| **P2** | Strukturelle Fahrtmengen, Aktivierung, Kapazität und aggregierte Kosten bauen; Fixed-Movement-Modus | G0: exakte Übereinstimmung mit Passenger-IP auf mehreren festen Plänen | Etwa ein Tag |
| **P3** | Integrierten Optimierungslauf, Resultat, Hints, Validator und Checkpoint verbinden | G1: vollständige kleine Instanzen und Grenzfälle; korrekte LB-/UB-Semantik | Etwa ein Tag |
| **P4** | CLI und Build-only; beide Kostenkodierungen begrenzt vergleichen | G2: K=20-Referenz geprüft; Modellgröße und Laufzeit dokumentiert | Etwa ein halber bis ein Tag plus Solverbudget |
| **P5** | Kontrollierter K=39-Vergleich und Entscheidung | G3: native/kompatible Bounds, validierte Lösungen, gleicher Start und Kostenrahmen | Etwa ein halber Tag Auswertung plus Solverbudget |

Gesamteinschätzung: etwa drei bis vier fokussierte Arbeitstage bei problemloser Wiederverwendung. Das ist ein Budgetrahmen für den Versuch, keine Zusage. Nach P2/P3 liegt die erste belastbare Information über Modellgröße und Korrektheit vor. Bei strukturellen Problemen wird der Umfang neu bewertet, statt automatisch bis K=39 weiterzubauen.

P0 ist als separate Wartung in `e252ff2` abgeschlossen und ändert die mathematische CP-Aufgabe nicht. Die gemeinsame Movement-Konstruktion aus P1 liegt in `608b709`. Die zuvor fehlgeschlagene Reservoirregression ist jetzt grün.

### G0: feste Bewegung und exakte Passagierbewertung

Testfälle: eine OD-Gruppe; mehrere Gruppen mit überlappender Sitzplatznutzung; Aussteigen und Einsteigen am selben Besuch; identische OD mit unterschiedlichen Releases; keine Nachfrage; vollständig unbedienbare Nachfrage; Boarding exakt bei Release; Boarding davor; negative historische Boarding-Zeit; Alighting exakt T und einen Tick danach; fehlender Stop an einem Fahrtende; Skip einer Zwischenstation bei besetzter Kabine; ausgeschalteter Kandidat mit sonst unzulässigen Zeitwerten. Zusätzlich T < H mit ungenutzten Stop-Ereignissen im Tail sowie Release genau T und nach T. Nichtbedienung und Alighting bei T müssen dieselben Kosten haben.

Beide Kostenkodierungen gegen die direkte Summe der ursprünglichen served/unserved-Kosten prüfen. Verschiedene Fahrtzuordnungen mit gleichem Optimum sind zulässig. Das vorhandene Nichtintegralitäts-Gegenbeispiel des Passenger-LP wird als Regression aufgenommen: die CP-Lösung muss ganzzahlig bleiben.

### G1: freies integriertes Modell

Kleine Instanzen mit wenigen Kabinen und Stopentscheidungen vollständig enumerieren. Zu jeder gültigen Bewegung den Passenger-IP lösen und das globale Minimum mit CP-SAT sowie vollständigem Arc-Flow vergleichen. Zusätzlich Anfangsbelegungen, unterschiedliche Stop-/Skip-Headways in beiden Reihenfolgen, zulässiges Überholen über den Bypass, gleichzeitig zulässige Plattformdurchfahrten mit Headway-Abstand, exakte Berührung halboffener Intervalle, mehrere Umläufe und die Terminalfortsetzung testen. Die Argumentation der Modelläquivalenz dokumentieren; wenige übereinstimmende Optima allein sind kein allgemeiner Beweis.

Horizonttests: Besuchsbeginn genau H erzwingt seine Route; Ressourceneintritt genau H wird geschützt, bei H+1 Tick entfällt er; Schutzende nach H wird nicht gekappt. Eine zu kleine Besuchsgrenze wird vor dem Solve abgelehnt. Am Betriebsende wird keine zyklische Rückkehr oder All-Stop-Recovery erzwungen.

Fahrtkandidaten, die in einem Seed nicht genutzt wurden, müssen in einer optimalen Alternativlösung nutzbar bleiben. Ein bewusst inkompatibler Fingerprint wird abgelehnt. Auch bei gleichem historischem Fingerprint werden veränderte Kapazität, Routendauer, Headway oder Kandidatenliste durch den Manifestvergleich erkannt. Mehrere Stop-Optionen, variable Routendauern und aktiviertes Waiting werden in v1 explizit abgelehnt. `UNKNOWN`, `FEASIBLE`, `OPTIMAL` und feste-Bewegung-Schranken dürfen nicht verwechselt werden. Modellfehler, Budgets und Checkpointunterbrechungen erhalten gezielte Tests.

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

Die erste Implementierung liegt vor; die vereinbarten kleinen Modellvergleiche wurden durchgeführt. Vorhandene Solver werden durch den neuen Pfad nicht ersetzt. Ein Codepfad wird erst dann als exakter integrierter Solver bezeichnet, wenn die oben beschriebenen Domänen- und Zertifikatsprüfungen erfüllt sind.

## 13. Historischer Nachweisstand des Planreviews vor der Umsetzung

Geprüft wurden Movement-Adapter, vorhandener CP-Oracle, Arc-Flow-Netz und -Passagierdomäne, Headway-Regeln, Fixed-K-Startvorbereitung, Besuchsgenerator, Kandidatenbuilder, Fixed-Movement-Passagiermodell und Kostenfunktionen. Der K=20-Referenzfall wurde ohne Aufbau des zeitexpandierten Netzes frisch vorbereitet; seine oben angegebenen Parameter und der historische Fingerprint stimmen. Die Unvollständigkeit des historischen Fingerprints wurde mit Änderungen an ausschließlich im Speicher gehaltenen Dataclass-Kopien nachgewiesen.

Bestehende Regressionen: **127 bestanden** mit `.venv/bin/python -m pytest -q tests/test_optimization_ddd_cp_sat_primal.py tests/test_optimization_ddd_fixed_k.py tests/test_optimization_ean_passenger_builder.py tests/test_optimization_ean_passenger_objective.py tests/test_optimization_ean_passenger_service.py`. Diese Tests prüfen vorhandene Bausteine; sie ersetzen weder die geplanten G0/G1-Prüfungen des neuen Solvers noch einen K=39-Leistungsversuch. Nur dieser Plan wurde geändert, kein Solvercode und kein historisches Resultat.

Zusätzliche Fundstellen zum Modellabgleich:

- [Horizontdefinition im EAN-Modell](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ean/models.py:145).
- [Konstante und vorgängerabhängige Headways](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/models/headway.py:197).
- [Physikalische Routen und Ressourcen im DDD-Adapter](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/artifact_adapter.py:282).
- [CP-Schutzintervalle und Horizontaktivierung](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_movement.py:278).
- [Arc-Flow-Fortsetzung und Ressourcenaktivierung](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/arc_flow_network.py:220).
- [Kandidaten und Zeitbedingungen im Arc-Flow-Passagiermodell](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/arc_flow_passenger_domain.py:241).
- [Sichere Besuchszahl aus minimalen Umlaufzeiten](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ean/builders/cyclic_visit_builder.py:212).
- [Historischer Problem-Fingerprint](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/fixed_k.py:186).

## Quellen und fachliche Grundlage

- [OR-Tools: CP-SAT Solver](https://developers.google.com/optimization/cp/cp_solver): ganzzahlige Modellierung und Solverstatus.
- [OR-Tools: Integer arithmetic](https://github.com/google/or-tools/blob/stable/ortools/sat/docs/integer_arithmetic.md): Produktbedingungen und exakte Kopplung von Boolean- und Integervariablen.
- [Joaquín Rodriguez (2007): A constraint programming model for real-time train scheduling at junctions](https://doi.org/10.1016/j.trb.2006.02.006): ereignis-/ressourcenbasierte CP-Modellierung in der Zugdisposition; kein direkter Ropeway-Leistungsnachweis.
- [Gange, Harabor, Stuckey (2019): Lazy CBS](https://ojs.aaai.org/index.php/ICAPS/article/view/3471): wiederverwendbares Konfliktlernen als methodischer Hintergrund. V1 implementiert keinen eigenen CBS-Suchbaum.
- Die konkrete Mengen-, Kapazitäts- und Kostenformulierung folgt dem vorhandenen Fixed-Movement-Passenger-Modell und dessen kanonischem Ziel. Die Ausstiegsaggregation ist eine algebraisch äquivalente Implementierungsentscheidung unter diesen Kostenannahmen; ihre Geschwindigkeit ist experimentell zu bewerten.
