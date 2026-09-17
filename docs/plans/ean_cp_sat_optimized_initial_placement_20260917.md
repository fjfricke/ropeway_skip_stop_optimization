# Ereignis-CP-SAT mit optimierter Anfangsaufstellung: Umsetzung und Experimente

> Verbindlicher Stand für diese Implementierung: Der physische Nachlauf von einer
> All-Stop-Umlaufzeit bleibt zunächst erhalten, ohne Rückkehrforderung. Eine
> Verkürzung wird erst in einem separaten Vergleich untersucht. Der frühere
> [Kurzfenster-Entwurf](oip_short_horizon_pattern_starts_20260917.md) ist damit
> keine Konfiguration dieses ersten OIP-Vergleichs.

Stand: 17.09.2026. **Der gemeinsame 1-ms-OIP-Vergleich ist implementiert und durch kleine Solver-Smokes abgenommen. Große Versuchsläufe wurden nicht gestartet.**

Die Implementierung liegt unter `optimization/oip/` und ergänzt den vorhandenen
EAN-Solver, ohne dessen kontinuierliche Standards zu ändern. CP-SAT unterstützt
`od_inventory` und `groups`; Gurobi unterstützt `ride_counts` und `slots`. Die
neuen Vergleichspfade verwenden dasselbe lexikografische Ziel, dieselbe
quantisierte Domäne und denselben unabhängigen Zertifikatsprüfer. Der aktuelle
Abnahmestand und die gemessenen Modellgrößen stehen in
[`../findings/oip_common_1ms_implementation_20260917.md`](../findings/oip_common_1ms_implementation_20260917.md).

## 1. Entscheidung und Untersuchungsfrage

Wir ergänzen den ereignisbasierten CP-SAT-Solver um **optimierte Anfangspositionen** (OIP, optimized initial placement). Das Modell wählt pro eingesetzter Kabine ihren Zustand zu t=0 und die dazu passenden ersten Ereigniszeiten. Es gibt keinen Dispatch aus dem Reservoir. Anfangspositionen werden weder vom Nutzer festgelegt noch als unveränderlicher All-Stop-Zustand vorgegeben.

Frage: Findet die gemeinsame Optimierung von Anfangsaufstellung, Flottengröße, STOP/SKIP und Passagieren im bereits laufenden Betrieb brauchbare Hochlastfahrpläne, wenn Anfahrt und Reservoirrückkehr entfallen?

Das ist eine **neue Betriebsdomäne**, keine nachgewiesen äquivalente Verdichtung des Reservoirmodells. Optimierte Anfangspositionen ersetzen Dispatchentscheidungen; sie beseitigen nicht die gesamte Anfangskombinatorik. Erwartete Ersparnis: Warmup-Besuchsketten, Reservoirport-Kopplung und Rückkehrentscheidungen. Spätere Ressourcenreihenfolgen, STOP/SKIP und Passagierzuordnung bleiben gekoppelt. Ein Suchvorteil ist erst experimentell zu belegen.

## 2. Was im Code vorhanden ist und was fehlt

| Baustein | Vorhanden | Geplante Verwendung |
|---|---|---|
| Gurobi-EAN mit OIP | Stations-/Seilauswahl, Anfangszeiten, optionale Kabinen, Anfangsheadways und Symmetrie | Physikalischer Vertrag und unabhängiger Vergleich auf kleinen Fällen |
| CP-SAT mit festen Starts | Ereignisketten, STOP/SKIP, Waiting, optionale Ressourcenintervalle und NoOverlap | Gemeinsamer Bewegungskern; feste Starts bleiben als Kontrollmodus |
| Reservoir-CP-SAT | Optionale Kabinen, Dispatch, Rückkehr, kompakte Ressourcen- und Passagierencodings | Wiederverwendung solverunabhängiger Vorbereitung, Passagiere, Berichterstattung |
| OD-Inventar | Implementiert im Reservoir-CP-SAT | Für OIP und feste Starts anschließen und gesondert validieren |
| Gurobi-EAN-Passagiere | Binäre Slots je Nachfragegruppe und Ride, teilweise Zeitvariablen pro Slot | Zunächst Korrektheitsreferenz; keine große neue Gurobi-Kampagne |

Der Fixed-Start-CP-SAT weist `od_inventory` derzeit ausdrücklich zurück. Der neue Modus muss diese Lücke schließen; eine neue Bezeichnung allein genügt nicht. EAN bezeichnet die Ereignisdarstellung, CP-SAT bzw. Gurobi den Solver, OIP bzw. Reservoir den Betriebsvertrag.

## 3. Betriebsvertrag des ersten OIP-Piloten

- T5R/G500, deterministische P0-Nachfrage mit den bestehenden OD-Anteilen und 15-s-Freigabebatches.
- Erste Hauptprüfung F2; F3 nur nach dem unten definierten Gate.
- Verfügbare Flotte zunächst **Kmax=62, aktive Flotte frei von 0 bis 62**. Jede verwendete Kabine ist bereits zu t=0 im Netz. Keine spätere Aktivierung und kein Ausscheiden während des betrachteten Betriebs.
- Keine Musterbindung: STOP/SKIP darf bei jedem Besuch neu entschieden werden. Keine globale Kabinenreihenfolge; Überholen bleibt nach der physischen Geometrie möglich.
- Zunächst **No-Wait**. Waiting bis 120 s je zulässigem STOP ist eine spätere, getrennte Erweiterung.
- Keine anfänglichen Fahrgäste und kein versteckter Nachfragebestand. Originale Freigaben werden um den bisherigen Warmup-Offset auf den Beginn des Betriebsfensters verschoben; Anzahl, Abstände und relative Bedienungsfristen bleiben erhalten.
- 45 Minuten Nachfragefreigaben und anschließend die bestehende Bedienungsreserve `max(15 min, Referenzheadway + längste relevante All-Stop-Direktfahrt)`. Bedienungsdeadline sei T.
- Erstes Vergleichspaar: physische Zertifizierung bis H=T+L_AS, mit L_AS als bestehender All-Stop-Umlaufzeit. Alle Kabinen fahren bis H weiter, ohne Depot- oder Rückkehrforderung. Der längere Nachlauf bleibt zunächst erhalten, damit die Wirkung der Anfangsaufstellung nicht gleichzeitig mit einem kürzeren Ende vermischt wird.
- Angefangene Bewegungen und ihre Schutzintervalle werden auch über H hinaus vollständig geprüft. Das ist ein endlicher Betriebsnachweis, kein Beweis unbegrenzter zyklischer Fortsetzbarkeit.
- Ziel **lexikografisch zuerst Unserved, danach bestehendes Journey Time mit Unserved-Strafe**. Keine Flottenstrafe. U=0 beendet die Suche nicht; nur native Optimalität oder das Budget beendet den Lauf.
- Vorgeschlagenes CP-Zeitraster: **1 ms**, explizit im neuen Vertrag. Das Raster darf keine physisch zu kurzen Fahrten oder Headways erzeugen. Ergebnisse werden gegen die ungerundete Physik validiert; keine stille Timingreparatur im Export. Eine sichere Rasterabbildung ist ein Pflichtgate, sonst wird für den ersten Pilot die vorhandene Mikrosekundenauflösung verwendet.

Die alten Werte 2.918, 3.210 und 7.153 bleiben Herkunftsangaben der ausgewählten Nachfragefälle. Insbesondere ist N=3.210 unter OIP nicht automatisch „110 % der All-Stop-Kapazität“.

## 4. Modell und Implementierungsfolge

### A. Gemeinsame Domäne und Anfangsaufstellung

1. Einen eigenen OIP-Domänentyp aus physischer Topologie, Nachfrage, Kmax, T, H und Raster erzeugen. Fixed-Start-, OIP- und Reservoir-Verträge erhalten getrennte Fingerprints.
2. Die zulässigen Anfangskategorien des EAN wiederverwenden: Zustand innerhalb einer Station bzw. auf deren zuführendem Seil. Der erste relevante Besuch und sein Zeitbereich bestimmen die Anfangsposition.
3. Je aktiver Kabine genau eine Anfangskategorie wählen. Bei Seilstart muss das erste Eintreffen zur verbleibenden Seilfahrzeit passen. Bei Stationsstart kann der Beginn einer laufenden Stationsbewegung vor t=0 liegen; Ende und Restbelegung müssen dazu konsistent sein.
4. Bereits laufende Ressourcenbelegungen, Schutzzeiten aus Ereignissen vor t=0 und gegebenenfalls vorherige STOP-/SKIP-Eigenschaften berücksichtigen. Eine Kabine darf weder auf einer belegten Ressource erscheinen noch erst beliebig spät erstmals eintreffen.
5. Aktive Kabinenlabels und gleichartige Anfangszustände kanonisch ordnen. Dies dient nur der Labelsymmetrie und darf spätere Überholungen nicht verhindern.

Die reine Wahl einer beliebigen ersten Ereigniszeit wäre unvollständig. Zu jeder Lösung muss ein physischer Anfangszustand rekonstruierbar und unabhängig validierbar sein.

### B. Gemeinsamer CP-Bewegungskern

Die vorhandenen Ressourcenintervalle, NoOverlap-Bedingungen und sicheren Ressourcenreduktionen wiederverwenden. Anfangsauswahl und Aktivitätskette ersetzen die festen Starts bzw. Reservoirgrenzen. Der Besuchsvorrat wird aus schnellster Route und H sicher nach oben begrenzt; keine heuristische Begrenzung der Rundenzahl.

Die gemeinsame OIP-Domäne, der CP-SAT-Bewegungskern, Runner und Zertifikatsadapter
liegen unter `optimization/oip/`. Solverkonfiguration, Zielbehandlung,
Fortschrittscallbacks und Ergebnisexport nutzen die vorhandenen EAN- und
Frontend-Schnittstellen; es wurde kein zweiter vollständiger Evolutions- oder
Experimentcontroller angelegt.

### C. Kompakte integrierte Passagiere

`cp_sat_passenger_inventory.py` über eine gemeinsame Bewegungsschnittstelle anschließen:

- ganzzahlige Mengen je OD/Kabine/Ein- und Ausstiegsbesuch;
- gemeinsame Freigabebestände mit Cumulative;
- Kapazität je tatsächlich befahrenem Abschnitt;
- aktive STOPs an beiden Fahrtenden und direkte Fahrt ohne zusätzliche Runde;
- Ausstiegsereignisse für Kosten bündeln;
- Rekonstruktion der ursprünglichen Nachfragegruppen und unabhängige Prüfung.

Bei stationären Anfangsbewegungen dürfen negative Ereigniszeiten keine Aufnahme vor der Nachfragefreigabe oder fingierte anfängliche Fahrgäste erlauben. Hints und Validator müssen Besuchs-IDs nach Wahl des Anfangszustands korrekt abbilden.

Die Aggregation bleibt exakt nur innerhalb von Klassen mit gleichen Beförderungsregeln, gemeinsamen Fristen und Zielgewichten. Individuelle Zusatzregeln erfordern getrennte Klassen oder das Gruppenencoding.

### D. Referenzen und Initialisierung

Im neuen Solver einen All-Stop-Modus anbieten: alle aktiven Besuche STOP, **Anfangsaufstellung und aktive Flotte weiterhin frei**. Dieser Modus besitzt denselben Vertrag wie die freie STOP/SKIP-Variante.

Ein unabhängig geprüftes regelmäßiges All-Stop-Snapshot darf als Hint und Rückfall dienen. Es ist kein bewiesenes OIP-All-Stop-Optimum. Die nachfolgende Skip-Stop-Suche erhält den besten gültigen All-Stop-Plan als freien Hint; alle Entscheidungen dürfen geändert werden. Seine Herkunft und Vorbereitungszeit werden ausgewiesen.

Ein Reservoirplan darf nur nach expliziter physischer Snapshot-Projektion und vollständiger Prüfung als OIP-Zeuge verwendet werden. Sein alter Zielwert und seine alten Schranken werden nicht übernommen.

### E. Runner und Frontend

Ein dünner OIP-Runner nutzt bestehenden Supervisor und Solverkern. Optionen: Fall, Kmax bzw. separates Exact-K, All-Stop/Skip-Stop, Waiting, Raster, T/H, Budget, Seed, Worker, Speichergrenze, Build-only und Checkpoint.

Bestehende einfache Optimierungsseite erweitern: Bedienung und Journey Time über Zeit, native Schranken und Gap, aktive Flotte, STOP/SKIP-Anteil, Anfangsaufstellung, Aufbau-/Suchzeit und Validierungsstatus. Gestrichelte Referenzen stammen ausschließlich aus demselben N/Kmax/T/H/Raster. Referenzincumbent und Referenzoptimum werden unterschieden. Bei lexikografischer Suche Bounds/Gaps samt Zielstufe eindeutig beschriften; keine erfundene Journey-Schranke aus einer Unserved-Schranke.

## 5. Pflichtgates vor großen Läufen

1. **Kleine Enumeration:** OIP-Zustände, Ereigniszeiten und STOP/SKIP auf kleinen Rasterfällen vollständig enumerieren; identische zulässige Lösungen und ganzzahlige Optima mit CP-SAT. Gurobi-EAN auf dasselbe Raster/den gleichen Vertrag beschränken, wenn Optima direkt verglichen werden.
2. **Anfangsgrenze:** Seilanfang/-ende, laufender STOP/SKIP, zwei Kabinen auf derselben Ressource, Schutzzeit aus t<0 und benachbarte Ticks. Keine Überschneidung, Teleportation oder unbeschränkte Startverzögerung.
3. **K und Symmetrie:** K=0,1; zusätzliche ungenutzte Kabine verändert Zielwert nicht; Kabinenumbenennung erhält Lösungen; Überholen nach dem Start bleibt zulässig.
4. **Bewegung bis H:** kein vorzeitiges Ausscheiden, keine fehlenden Endintervalle, ausreichender Besuchsvorrat, H−1/H/H+1 korrekt. Keine Depotpflicht in OIP.
5. **Passagiere:** Gruppen- und OD-Inventarencoding bei gleicher Bewegung und bei freien Zeiten vergleichen; Freigaben, Ganzzahligkeit, voller Abschnitt, Aus-/Einstieg gleichzeitig, q=0, ursprüngliche Ride-IDs und beide Zielstufen prüfen.
6. **Zielvertrag:** `J = sum(q_j * a_j) + T * U - sum(n_g * r_g)` unabhängig aus der rekonstruierten Belegung bestätigen. Einheitliche Zeitverschiebung erhält Journey Time.
7. **Raster und Referenz:** Zertifikate bestehen die physische Originalprüfung; All-Stop und Skip-Stop besitzen identische Domänen. Das freie Modell enthält den All-Stop-Zeugen.
8. **Fehlerfälle:** UNKNOWN, Timeout und Speicherabbruch sind keine Unzulässigkeitsbeweise; gültige Starts bleiben erhalten und werden nicht als native Verbesserung gezählt.

Erst danach Buildgrößen und Suchverhalten messen. Weniger Variablen allein sind kein Erfolgskriterium.

## 6. Welche Verfahren für welche Thesis-Experimente?

### Studie 1: Journey Time bei vollständiger Bedienung

**Hauptverfahren bleibt Labelled Arc-Flow mit Gurobi**, feste ausgeglichene Anfangspositionen, No-Wait, exakt K und vollständige Bedienung. Die ausgewählte abgeschlossene Hauptreihe bleibt erhalten:

- T5R/G500/P0, F0/F2/F3/F4.
- Relative Last: K=10/20/30, 25 % und 75 % der jeweiligen All-Stop-Referenzkapazität.
- Konstante Last: K=20/30, jeweils dieselbe profilabhängige halbe All-Stop-Kapazität bei Kref=31.
- All-Stop und Skip-Stop unter gleichen Randbedingungen, 30 min bzw. 1 % MIP-Gap.

Keine pauschale Wiederholung wegen eines neuen Passagierencodings. OIP-Ergebnisse dürfen die Fixed-Start-Ergebnisse nicht ersetzen. Für die neue Implementierung genügt zusätzlich ein kleiner Fixed-Start-CP-SAT/Arc-Flow-Gleichheitsfall; das ist ein Korrektheitsvergleich, keine dritte breite Studie.

### Studie 2a: Bereits abgeschlossene Reservoir-Kapazitätsstudie

**Behalten:** regulärer All-Stop-Phasenreferenzsolver; unabhängige Musterevolution mit kleinem OD-Katalog und No-Wait-Decoder; ganzzahliger Passagier-IP; CP-SAT zur Nachoptimierung gültiger Zeugen.

F2 auf T5 und T6 liefert gültige Vollbedienungszeugen oberhalb der regulären All-Stop-Referenzkapazität. F3 wird als erfolgloses, zeitbegrenztes Screening dieser Heuristik berichtet. Kein Beweis gegen Skip-Stop und kein Ersatz für einen All-Stop-Vergleich bei identischem N. Initialisierungserfolg und spätere Evolutionsverbesserungen werden getrennt bewertet.

Diese Ergebnisse bleiben eine eigenständige Reservoir-Domäne. Keine automatische neue Evo-, Greedy- oder Reservoir-CP-SAT-Kampagne.

### Studie 2b: Neuer, begrenzter OIP-Kapazitätspilot

**Kandidat für den ergänzenden Hochlastvergleich: vollständiges OIP-CP-SAT mit OD-Inventar.** Keine äußere Evolution und keine feste Musterliste. Ein erfolgreicher Pilot rechtfertigt eine Ergänzung der Studie; vorher wird er nicht zum neuen Hauptverfahren erklärt.

| Reihenfolge | Fall | Verfahren | Maximale Wandzeit | Zweck |
|---|---|---|---:|---|
| 0 | kleine Gatefälle | CP-SAT, Enumeration, bestehendes EAN | separat vor Kampagne | Korrektheit |
| 1 | T5/F2, N=3.210, Kmax=62 | OIP-CP-SAT, All-Stop | 30 min | gleichberechtigte neue Referenz |
| 2 | exakt derselbe Fall | OIP-CP-SAT, freie STOP/SKIP | 30 min | gemeinsame Suche aus gültigem Referenzhint |
| 3, bedingt | T5/F3, N=7.153, Kmax=62 | OIP-CP-SAT, All-Stop | 30 min | breiteres Nachfrageprofil |
| 4, bedingt | exakt derselbe F3-Fall | OIP-CP-SAT, freie STOP/SKIP | 30 min | Transfer des Suchansatzes |

Seed 0, zwölf CP-SAT-Worker, ein Solverjob gleichzeitig, höchstens 32 GiB Prozessbaum-RSS und bestehende Speicherdrucküberwachung. Je Lauf zählen Aufbau, Suche, Rekonstruktion und Validierung zum Budget. Supervisor unabhängig von der geöffneten Sitzung; keine automatischen Zusatzläufe bei Ausfällen.

**Budget:** Erstes F2-Paar einschließlich Einfrieren/Auswertung höchstens 75 min. F3 nur, wenn F2 einen unabhängig gültigen Plan und mindestens eine relevante native Verbesserung gegenüber dem übernommenen Start liefert: zusätzliche Bedienung oder mindestens 1 % Journey-Verbesserung bei gleicher Bedienung. Reines Presolve, bloßes Seedtragen oder Mikrosekundenänderungen reichen nicht. Einschließlich F3 und zusätzlicher Auswertung höchstens 140 min. Das sind vorgeschlagene zukünftige Budgets, keine bereits gestartete Kampagne.

Bei gemeinsamem Zeitbudget wird die Referenzsuche als Aufwand des Verfahrens mitgezählt. Kein Geschwindigkeitsvergleich mit alten Reservoirläufen: Anfangs-/Endvertrag und gegebenenfalls Raster unterscheiden sich.

**Auswertung:** K aktiv, Bedienung, J, Zeit bis zur ersten gültigen Lösung, echte Verbesserungen, belegte SKIPs, Modell-/Presolvegröße, Speicher und native Bounds. Werden beide Varianten bei N=3.210 vollständig bedient, ist das zunächst ein Journey-Vergleich; 3.210 ist dann kein nachgewiesener OIP-Kapazitätsvorteil.

Eine Behauptung „mehr Vollbedienungskapazität als OIP-All-Stop“ benötigt denselben Nachfragestand N mit gültiger vollständiger Skip-Stop-Bedienung und bewiesen fehlender All-Stop-Vollbedienbarkeit. Ohne diesen Nachweis nur gefundene Bedienung bzw. offene Referenzintervalle berichten. Eine erneute umfassende Nmax-Suche gehört nicht zum ersten Pilot.

F0 ist der nächste mögliche Kontrollfall nach einem positiven F2/F3-Befund. F4 bleibt aus neuen Hochlastläufen ausgeschlossen wie gewünscht. **F1 ist zwar im allgemeinen Nachfragekatalog beschrieben, aber nicht Teil des aktuellen Thesis-Fallbuilders** (`ThesisDemandFamily`: F0/F2/F3/F4); keine kurzfristige zusätzliche F1-Reihe. Die frühere Chatempfehlung, F1 einfach als nächsten vorhandenen Fall zu starten, war zu weitgehend.

## 7. Nachlauf: separate, nachgelagerte Entscheidung

Im ersten Paar bleibt der bisherige physische Nachlauf L_AS als weiterlaufender Betrieb erhalten. Es gibt keine Reservoirrückkehr. So wird nicht gleichzeitig durch eine verkürzte Zukunftsprüfung zusätzliche Freiheit geschaffen.

Erst bei positivem Pilot einen kurzen OIP-Nachlauf definieren: als vorab aus der Geometrie abgeleitete Dauer einer vollständigen längsten No-Wait-Stations-/Seilbewegung zuzüglich relevanter Schutzzeit. Der Wert ist ein endlicher Prüfvertrag, kein allgemeiner Fortsetzbarkeitsbeweis. Angefangene Bewegungen werden vollständig abgewickelt; keine Kabine wird vor H entfernt.

All-Stop und Skip-Stop müssen dann beide mit demselben kürzeren H neu bewertet bzw. optimiert werden. Neue kurze Pläne zusätzlich versuchen bis zum langen H fortzusetzen, ohne den bewerteten Präfix zu verändern. Ein Timeout dieses Fortsetzungsversuchs bleibt UNKNOWN. Ohne bestätigte Fortsetzung Ergebnisse ausdrücklich nur unter dem kurzen Vertrag ausweisen. Für die endgültige Thesis bleibt zunächst der längere geprüfte Vertrag maßgeblich.

**Die 15-minütige Bedienungsreserve wird dabei nicht gekürzt.** Eine Änderung davon wäre eine andere Nachfrage-/Deadline-Studie und würde eine neue Referenzkalibrierung verlangen. Waiting=120 s ebenfalls erst separat prüfen; No-Wait-Nachlaufgrenzen nicht ungeprüft übernehmen.

## 8. Was wir vorerst nicht einsetzen oder neu entwickeln

| Verfahren / Erweiterung | Entscheidung für die nächsten Experimente |
|---|---|
| Gurobi-EAN, großes OIP-Vollmodell | Nur kleine Korrektheitsreferenz, keine neue große Hochlastkampagne |
| Kompaktere Gurobi-EAN-Passagiere | Nachgelagert: erst Integer-Ride-Mengen und gebündelte Ereigniskosten; danach ggf. OD-Bestand. Kein direkter Cumulative-Port und keine zugesicherte MILP-Größenersparnis |
| Breite Evo mit teurem CP-SAT-Timing je Musterfolge | Nicht neu starten; bisher viele unzulässige/ungeklärte Folgen, schwaches Suchsignal |
| Evo mit Liniengruppen | Nicht verwenden; aktuelle unabhängige Darstellung bleibt für vorhandene Reservoirbefunde maßgeblich |
| Greedy mit/ohne Waiting | Vorhandene Befunde behalten; keine neue Hauptreihe |
| Großes Reservoir-CP-SAT ohne guten Start; Flottenfortsetzung K=1… | Nicht erneut als Hauptsuche starten; CP-SAT bleibt für vorhandene gültige Reservoirpläne Nachoptimierer |
| Neue DP-, DDD-, Corridor-, Benders-, Column-Generation-, Service-Class-Verfahren | Archiv/Methodendiskussion; keine weitere Implementierungsrunde für diese Experimente |
| MAP-Elites, RL, neues Surrogat, neue Solverbackend-Migration | Nicht Teil dieses Plans |
| Neuaufbau sämtlicher Journey-Läufe | Nicht erforderlich ohne nachgewiesenen Korrektheitsfehler oder ausdrücklich neue Forschungsfrage |

Die Entscheidung betrifft die Versuchspriorität. Bestehenden Code und Rohdaten erhalten; experimentelle Ansätze nicht als generell ungeeignet deklarieren.

## 9. Quellen im Projekt und erwartete Liefergegenstände

- [OIP-Flottenmodell](../../src/ropeway_skip_stop_optimization/optimization/ean/optimizers/fleet_model.py), [OIP-Symmetrievertrag](ean_oip_symmetry_and_exact_k.md).
- [CP-SAT-Bewegung](../../src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_movement.py), [integriertes Fixed-Start-CP-SAT](../../src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_integrated.py), [OD-Inventar](../../src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_passenger_inventory.py).
- [Thesis-Fallbuilder](../../src/ropeway_skip_stop_optimization/benchmarking/thesis_cases.py), [Methodenaudit und Journey-Reihen](thesis_methods_and_final_experiments_20260917.md).
- [Abgeschlossener Kapazitätsplan](thesis_capacity_final_campaign_20260917.md), [Kapazitätsbefund](../results/thesis_capacity_final_campaign_20260917.md).

Bei Umsetzung: versionierter OIP-Vertrag, gemeinsame Modelladapter, bestandene Gleichheits-/Grenztests, unabhängige Zertifikate, begrenzter Runner und bestehende Liveansicht. Ein separater Befund dokumentiert sowohl Erfolge als auch einen gegebenenfalls negativen Pilot. Historische Ergebnisse und deren Betriebsverträge bleiben unverändert.
