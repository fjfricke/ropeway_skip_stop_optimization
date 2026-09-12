# Kompakter Reservoir-Arc-Flow: Implementierung und Ergebnisse

**Abgeschlossen:** experimentelle Architektur implementiert, 114 kleine Tests
und 27 historische Prüfungen bestanden. Die Versuchsserie dauerte einschließlich
Runnerreparatur **48 Minuten 7 Sekunden**; mit Auswertung und Abschluss blieb
das Paket **unter 60 Minuten**. Keine weiteren Solverjobs laufen.

**Befund:** Auf R2 ist P2 deutlich kompakter und kommt in beiden Bestätigungen
innerhalb von fünf Minuten durch die Root-LP. Legacy schafft das dort nicht.
**Keine Variante verbessert aber die Bedienung oder den relevanten Gap.**
Das Ziel eines brauchbar besseren Incumbents beziehungsweise einer starken
Schranke ist mit diesen Änderungen noch nicht erreicht. Legacy bleibt Standard.

## Implementierte Architektur

Alle Varianten verwenden unverändert denselben Bewegungskern, dieselben exakten
Zeitpunkte, denselben Waitingvertrag und das Single-Use-Reservoir mit maximal
50 Kabinen. Das Ziel bleibt `unserved`; die Reisezeit ist eine Kontrollkennzahl.
Gurobi übernimmt die gesamte Suche. Es gibt keine eigene LNS oder Zerlegung.

- **P1 / `od_flow`:** gruppenspezifische Einstiege, gemeinsame OD-Bordflüsse.
- **P2 / `od_queue`:** zusätzlich exakte Nachfragezeitketten mit deterministischer,
  ganzzahliger Rückübersetzung in die ursprünglichen Gruppen und Ride-IDs.
- **I / `boarding`:** nur einzelne Einstiegsereignisse müssen explizit integer sein.
- **K / `contracted`:** exakte Substitution deterministischer Passagiergleichungen,
  bei erhaltenen Kapazitätskopplungen auf allen ursprünglichen Bewegungsarcs.
- **R / `maximal`:** Ressourcenzeilen mit identischen oder dominierten Koeffizienten
  entfernen; jede Entfernung besitzt eine erhaltene implizierende Zeile.
- **C / `local_cliques`:** begrenzte zusätzliche Konfliktdreiecke mit vollständigen
  paarweisen Ressourcenbelegen. Im Pilot entstehen 62 zusätzliche Cuts je Fall.

Die Optionen sind unabhängig kombinierbar; die kombinierte Variante wurde auf
Korrektheit geprüft, nicht zusätzlich als freie Suchvariante bewertet.
Nicht unterstützte Optionen für andere Methoden werden vor Modellbau abgewiesen.
Physikalischer Fingerprint, Graph-Fingerprint und Modell-Fingerprint bleiben
getrennt. Historische Checkpoints benötigen keine Migration.

## Korrektheitsbelege

[Finaler Testlauf](../../benchmarks/output/reservoir_compact_correctness_20260911_v3/pytest.log):
**114 bestanden in 32,53 Sekunden**, mit JUnit, Kommando und Quellhashes.
Enthalten sind vollständige kleine Enumeration, Legacy-Algebra gegen den
unveränderten alten Builder, LP-Projektionen, Waiting, Überholen, Rückkehr,
Freigaben, Ganzzahligkeit einschließlich Odd-Cycle, Checkpoints und Abbrüche.

[Historische Freigabe](../../benchmarks/output/reservoir_compact_replays_20260911_v1/gate.json):
alle acht Konfigurationen reproduzieren die ursprünglichen Zuordnungen auf drei
Referenzen. Bei fixierter Bewegung stimmen sie mit dem unabhängig von CP-SAT
bestimmten Passagieroptimum überein:

| Referenzbewegung | Kapazitätsoptimum U | Geprüfte Konfigurationen |
|---|---:|---:|
| R0 | 285 | 8 |
| R2 | 578 | 8 |
| Historischer Plan mit positivem Waiting | 339 | 8 |

Die ursprüngliche Waiting-Zuordnung mit U=476 bleibt unverändert als Zeuge
reproduzierbar; ihr Kapazitätsoptimum ist U=339. Zusammen mit den drei separaten
CP-SAT-Referenzprüfungen sind das 27 Prüfungen. Gleiche Graph- und Domain-IDs je
Fall sind separat in `network_identity_checks.json` bestätigt.

Im ersten Testlauf wurde ein Exportfehler gefunden und korrigiert: Der neue
Legacy-Adapter hatte Bordflüsse an Zwischenstationen als neue Einstiege gelesen.
Er nutzt nun ausdrücklich die vorbereiteten Einstiegsindizes. Fehlgeschlagene
Belege bleiben unter `reservoir_compact_correctness_20260911_v1/` erhalten;
die vollständigen nachfolgenden Testläufe sind bestanden.

## Modellgrößen auf identischen Netzen

Vor Presolve, aus den historischen Modellbauten. Alle angegebenen Modelle
reproduzieren dieselben ganzzahligen Kapazitätswerte ihrer Referenzbewegung.

| Profil | R0 Variablen | R0 Zeilen | R2 Variablen | R2 Zeilen |
|---|---:|---:|---:|---:|
| L | 769.834 | 752.306 | 889.209 | 826.867 |
| P1 | 769.834 | 752.306 | 356.720 | 458.856 |
| P2 | 835.385 | 817.837 | 304.965 | 471.985 |
| I | 769.834 | 752.306 | 356.720 | 458.856 |
| K | 674.688 | 657.160 | 337.127 | 439.263 |
| R | 769.834 | 734.047 | 889.209 | 808.509 |
| C | 769.834 | 752.368 | 889.209 | 826.929 |
| combined | 740.239 | 704.494 | 285.372 | 434.096 |

I und K enthalten P1; R und C verändern ausschließlich Legacy. `combined`
verbindet P2, Integer-Einstiege, Kontraktion, Ressourcenbereinigung und Cuts.

Auf R2: **P1 −59,88 %, P2 −65,70 %, kombiniert −67,91 % Variablen**.
Auf R0 existiert je OD nur eine Gruppe: P1 reduziert nichts, P2 vergrößert das
Modell durch die Bodenwarteschlangen. Ein pauschaler Wechsel wäre falsch.

## Freie Suche und Fortschritt

Alle abgeschlossenen Screeningläufe bleiben bei **R0 U=285 / R2 U=578**.
Es gibt **kein echtes Verbesserungsereignis**, sondern jeweils die Übernahme
der geprüften Referenz. Alle vergleichbaren Untergrenzen bleiben null.
Negative frühe native Bounds sind schwächer als die bekannte Nichtnegativität;
Werte um 10^-11 sind numerisch null, keine zusätzliche bediente Person.

P2 wurde nach dem vorab festgelegten Struktur-Ersatzkriterium für die Bestätigung
ausgewählt: kleinste Größe nach Presolve, bei gleicher UB, vergleichbarer LB und
noch nicht abgeschlossener Root-Verarbeitung im 120-Sekunden-Screening.

| R2-Profil, Screening | Variablen nach Presolve | Zeilen nach Presolve | Barrier fertig nach s | Root-LP vollständig fertig? |
|---|---:|---:|---:|---|
| L | 488.577 | 322.655 | nein | nein |
| P1 | 242.203 | 241.959 | 62.9 | nein |
| P2 | 167.495 | 232.125 | 67.2 | nein |
| I | 244.739 | 244.327 | nein | nein |
| K | 242.199 | 241.958 | 71.0 | nein |
| R | 488.588 | 322.712 | nein | nein |
| C | 488.572 | 322.696 | nein | nein |

K reduziert gegenüber P1 nach Presolve nur vier weitere Variablen. Bei R ist
die vermeintliche Ersparnis nach Presolve ebenfalls verschwunden. I erzeugt
weniger explizite Integer-Variablen, aber kein kleineres verbleibendes LP als P1.
Die OD-Zusammenfassung ist der klarste strukturelle Gewinn.

### Bestätigung: jeweils höchstens 300 Sekunden Gesamtbudget

Root-Zeiten bezeichnen das erste native Boundereignis nach im Log bestätigtem
Root-LP-Abschluss; Gesamtzeit enthält den vorangehenden Aufbau. Das bisherige
Feld `root_lp_complete_seconds` misst den ersten optimalen MIPNODE-Callback und
bleibt hier leer. **Das bedeutet bei P2 nicht, dass die Root-LP ungelöst blieb**;
ihr Abschluss ist über Gurobis Log und die Boundereignisse ausdrücklich belegt.

| Profil / Seed | U | Vergleichbare LB | Root fertig, Solver-s / Gesamt-s | Peak RSS GiB |
|---|---:|---:|---|---:|
| P2_s1 | 578 | 0 | 214.3 / 230.5 | 6.56 |
| L_s1 | 578 | 0 | nicht im Budget abgeschlossen | 6.54 |
| L_s2 | 578 | 0 | nicht im Budget abgeschlossen | 8.63 |
| P2_s2 | 578 | 0 | 231.1 / 247.1 | 6.41 |

In beiden P2-Läufen wurde nur der Root-Knoten bearbeitet, mit weiterhin ungefähr
75.000 fraktionalen Integer-Variablen am Root. Die stärkere Aussage „die Suche
lief jetzt wirksam durch einen Branch-and-Bound-Baum“ wäre falsch.

Das automatische LP-Verfahren verursacht zusätzlich **37,69 beziehungsweise
90,61 Sekunden Concurrent Spin** bei P2. Diese interne Wartezeit ist im
Root-Aufwand enthalten. Die Root-Methode blieb wie geplant unverändert; eine
andere Einstellung wurde nicht getestet und wird hier nicht als Vorteil behauptet.

Der Speichergewinn ist nicht entsprechend der Variablenreduktion bestätigt:
bei Seed 1 liegen beide Modelle um 6,5 GiB, bei Seed 2 P2 bei etwa 6,4 und Legacy
bei 8,6 GiB. Die Faktorisierungen bleiben groß. Mehr RAM war unter dem gesetzten
24-GiB-Limit kein beobachteter Engpass dieser Kampagne.

[UB-/LB-Verläufe](../../benchmarks/output/reservoir_compact_campaign_20260911_v2/progress.svg)
zeigen den fehlenden Qualitätsfortschritt; die deckungsgleichen Kurven sind
beabsichtigt. Referenzen sind ab Zeitpunkt null getrennt von nativen Erfolgen
berücksichtigt. [Crossover-Verläufe](../../benchmarks/output/reservoir_compact_campaign_20260911_v2/root_crossover.svg)
zeigen dagegen den realen Fortschritt in der linearen Algebra. Diese Kurve ist
kein Maß für Verbesserungen der Kabinenfahrpläne. Der Sprung im ersten Legacy-
Verlauf entspricht dem im nativen Log ausdrücklich gemeldeten Crossover-Neustart.
Beide Datensätze liegen auch
als CSV vor.

## Entscheidung und Grenzen

Die festgelegten Empfehlungsschwellen sind in **keinem** der beiden zusätzlichen
Seeds erreicht: null zusätzlich bediente Personen, kein relevanter Gapgewinn,
kein schnelleres Erreichen besserer UB-/LB-Werte. Den ohnehin vorhandenen Seed
mit trivialer LB=0 zu übernehmen zählt nicht als Beschleunigung.

**P2 bleibt eine sinnvolle experimentelle kompakte Darstellung für mehrere
Freigabegruppen derselben OD. Es ist nach diesem Test kein besserer Algorithmus
für Incumbentqualität oder Beweisleistung.** Für Batch-Nachfrage ist P1/P2 kein
allgemeiner Vorteil. K, R, I und C erhalten keine pauschale Performanceempfehlung.
Kein Standardwechsel, keine zusätzlichen Langläufe, kein Doppelringausbau.

Die gute Nachricht ist die korrekte deutliche Verkleinerung. Die offene Hürde
ist jetzt klarer: trotz schnellerem Root bleibt dessen Kapazitätsschranke null,
und die verbleibende ganzzahlige Suche erreicht noch keinen besseren Plan.
Die Thesis-Frage ist dadurch **nicht** beantwortet. Der separate gültige
All-Stop-Bound auf R2 bleibt 125; der erforderliche Skip-Stop-Zeuge mit U<=124
wurde nicht gefunden.

Alle hier gezeigten Arc-Flow-Bounds gelten nur für das eingefrorene eingeschränkte
Zeitnetz. Keine Aussage über ein globales Skip-Stop-Optimum wird daraus abgeleitet.
Die Pilotdauer von zwei beziehungsweise fünf Minuten begrenzt Aussagen über
langfristige Suche; sie rechtfertigt weder eine Durchbruchzusage noch automatisch
längere Läufe.

## Budget, Abbruch und Reproduzierbarkeit

18 angesetzte Versuche: **16 mit regulärem finalem Solverbericht**, R0-Legacy mit
unabhängig wiederhergestelltem Checkpoint nach hartem Zeitlimit, und **R0-P2 als
unvollständiger Performanceversuch** nach Unterbrechung zur Runnerreparatur.
R0-P2 ist in Grafiken und Auswertung gekennzeichnet und keine reguläre Kontrolle.

Beim ersten R0-Lauf reichten zwei Sekunden Abschlussreserve nicht für Export
und Prozessabschluss. Die Reparatur erhöhte die Reserve großer Phasenläufe auf
acht Sekunden und sichert Modellgrößen schon vor der Suche. Ein harter Abbruch
verliert nicht mehr den separat validierbaren Checkpoint; er wird ausdrücklich
als Wiederherstellung gekennzeichnet, nicht als native neue Lösung.

Der erste Kampagnenteil bleibt unverändert erhalten; die Fortsetzung verwendet
**dieselbe ursprüngliche 60-Minuten-Deadline**. Kein begonnener Versuch wurde
wiederholt, Reparaturzeit ist enthalten. Geändert wurden nur Benchmark-Runner;
alle eingefrorenen `src/`-Hashes und alle Modellvarianten beider Teile sind identisch.
Zwölf Gurobi-Threads, 24 GiB Prozessbaumlimit, MIPFocus=0 und automatische Root-
Methode; alle Solverläufe sequenziell. Native Version: Gurobi 13.0.2.

- [Erster Kampagnenteil und Abbruchprotokoll](../../benchmarks/output/reservoir_compact_campaign_20260911_v1/interruption.json)
- [Fortsetzung, Quellen und Manifest](../../benchmarks/output/reservoir_compact_campaign_20260911_v2/manifest.json)
- [Einzelvergleich](../../benchmarks/output/reservoir_compact_campaign_20260911_v2/comparison.json)
- [Zusätzliche Root-/RAM-Auswertung](../../benchmarks/output/reservoir_compact_campaign_20260911_v2/analysis.json)
- [Automatische Entscheidung](../../benchmarks/output/reservoir_compact_campaign_20260911_v2/decision.json)

## Wo die Implementierung liegt

Unter `src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_capacity/`:
`formulation.py`, `passenger_structure.py`, `passenger_model.py`,
`passenger_certificate.py`, `resource_structure.py`; Integration in `model.py`.

CLI: `benchmarks/run_reservoir_capacity_arc_flow.py`.
Historische Prüfung: `benchmarks/verify_reservoir_compact_replays.py`.
Kampagne: `benchmarks/run_reservoir_compact_campaign.py`.
Auswertung: `benchmarks/report_reservoir_compact_campaign.py`.

Die [Modellreferenz](../reference/reservoir_capacity_phase_arc_flow.md) enthält
Projektions-, Integritäts- und Konfliktargumente sowie die Flags. Grundlage sind
[Umsetzungsplan](../plans/reservoir_arc_flow_compact_architecture_20260911.md)
und [Architekturrecherche mit Literatur](../research/ropeway_arc_flow_architecture_20260911.md).
Die Literatur motiviert die Darstellung, ersetzt aber weder diese eigenen
Nachweise noch den fehlenden Performanceerfolg.
