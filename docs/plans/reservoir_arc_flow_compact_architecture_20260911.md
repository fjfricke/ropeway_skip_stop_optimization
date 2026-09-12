# Kompakter Reservoir-Arc-Flow: Umsetzung und Testplan

## 1. Ziel und Umfang

Status: Implementiert und abgeschlossen. 114 kleine Tests und alle 27 historischen Prüfungen bestanden; Versuchsserie in 48 Minuten 7 Sekunden, einschließlich Auswertung unter 60 Minuten beendet. Struktureller Gewinn, keine bestätigte Verbesserung von Bedienung/Gap. Ein R0-P2-Screening blieb nach Runnerreparatur unvollständig. [Abschlussbericht](../findings/reservoir_compact_architecture_20260911.md). Grundlage ist die [Architekturrecherche](../research/ropeway_arc_flow_architecture_20260911.md) mit Literatur, Codebefunden und Einschränkungen. Die Änderungen sollen redundant dargestellte Passagierflüsse reduzieren und separat die Konfliktbeschreibung stärken. Die Optimierung bleibt ein integriertes Gurobi-MILP ohne eigene Suche, LNS oder Zerlegungssteuerung.

Der erste Umfang ist das bestehende anonyme Single-Use-Reservoir mit optionaler Flotte bis Max50, STOP/SKIP, Exit-Waiting und Ziel `unserved`. Das physikalische Problem, seine Integer-Ticks, die ausgewählten exakten Zeitpunkte und die kanonischen Beförderungen bleiben unverändert. Die letzte Rückkehr und leere Kabinen beim Betriebsende bleiben ausdrücklich modelliert.

Nicht Teil dieses Pakets: neue Zeitanker, kleineres Waiting, feste Kabinenreihenfolge, wiederholter Reservoireinsatz, Fixed-K-Adapter, Reisezeitoptimierung, Doppelring-Erweiterung, vollständiges DDD, neue Root-Methode oder Solverparameter-Tuning. Lokale Belegungszustandsnetze und MIR-Schnitte bleiben dokumentierte Folgeoptionen; zunächst wird ihre Notwendigkeit anhand fraktionaler Lösungen geprüft.

Erfolgskriterien sind getrennt:

1. **Korrektheit:** gleiche gültige Bewegungen und Kapazitätsmöglichkeiten auf demselben Netz, mit rekonstruierbaren ganzzahligen Zertifikaten.
2. **Darstellung:** nachweisbare Verringerung von Variablen, Zeilen und Nichtnullen, einschließlich Größen nach Presolve.
3. **Performance:** schneller abgeschlossene Root-Verarbeitung, bessere validierte Bedienung oder stärkerer vergleichbarer Bound. Eine kleinere Darstellung allein ist keine Performanceempfehlung.

Für P1 liegt eine Supportzählung von 889.209 auf rechnerisch 356.720 Gesamtvariablen vor. Sie ist ein Kontrollwert, keine garantierte Endgröße oder Beschleunigung.

## 2. Entwicklung während laufender Versuche

Die aktuelle Kampagne `benchmarks/output/reservoir_capacity_followup_20260911_30min/` verwendet eingefrorene Quellen unter `sources/`, einen eingefrorenen R2-Checkpoint und einen gesetzten `PYTHONPATH`. Ihr Supervisor wurde vor den Änderungen gestartet. Die Dateien dieser Kampagne bleiben unangetastet.

Während sie läuft, sind vorgesehen:

- Editieren der Arbeitskopie und neuer Dokumente.
- Kleine reine Python-Tests für Klassenbildung, Abbildungen, Nachfrageketten und Konfliktnachweise.
- Syntax-, Import- und Lintprüfungen mit begrenzter Last.

Erst nach Abschluss **beider** laufender 30-Minuten-Versuche und ihrer Kindprozesse:

- Tests mit Gurobi, CP-SAT oder anderen Solveraufrufen, auch bei kleinen Instanzen.
- Historische Replays, größere Modellbauten und LP-Diagnosen.
- Neue Performancekampagne.

Kein automatischer Solverstart aus einem allgemein benannten „Unit-Test“. Neue reine Tests importieren keine Testmodule, deren Fixtures Solver starten. Bestehende Solverprozesse werden weder unterbrochen noch umparametriert. Bei erheblicher Entwicklerlast wird deren Zeitfenster im Vergleichsmanifest vermerkt; ansonsten bleibt die Entwicklungsarbeit leichtgewichtig.

Vor jeder neuen Kampagne kontrolliert der Runner Prozessidentität und Prozessbaum, nicht nur einen möglicherweise wiederverwendeten PID. Fehlt nach einem Abbruch der alte Abschlussstatus, wird nicht automatisch konkurrierend gestartet. Queue-Wartezeit zählt nicht als neues Suchbudget.

## 3. Gemeinsame Architektur und Schnittstellen

### Solverfreie Vorbereitung

Neue unveränderliche Typen unter `optimization/ddd/reservoir_capacity/`:

| Modul | Inhalt |
|---|---|
| `formulation.py` | `ReservoirPhaseFormulationConfig`, Optionsprüfung, Serialisierung und Modell-Fingerprint |
| `passenger_structure.py` | `PreparedPassengerStructure`, kompatible OD-Klassen, Supports, Einstiegs-/Ausstiegsindizes, Nachfrageereignisse und Original-IDs |
| `passenger_model.py` | gemeinsames Builder-Protokoll und Legacy-, OD-Flow-, OD-Queue-Builder |
| `passenger_certificate.py` | Projektion von Referenzen und Rekonstruktion von Gruppen-/Ride-Mengen |
| `resource_structure.py` | normalisierte Ressourcenzeilen, Dominanznachweise, belegte lokale Konfliktcliquen |

Es werden keine Gesamtsolver kopiert. `model.py` behält den gemeinsamen Bewegungskern, Zielfunktion, Solve-Aufruf und Ergebnisverwaltung. Zunächst wird der existierende Passagiercode ohne mathematische Änderung in den Legacy-Baustein verlegt.

Das gebaute Passagierobjekt stellt ausdrücklich bereit:

- Solvervariablen und ihre Familien;
- Nachfrage-, Boarding-, Alighting- und Kapazitätsausdrücke;
- `reference_values(plan, movement_paths)`;
- `extract_assignment(value, movement_paths)`;
- Abbildung der ursprünglichen auf kompakte Variablen und Schnittstellen;
- Rechenzeit, Modellgrößen und erklärbare Vorverarbeitungsentscheidungen.

`PhaseModel.reference_values` und `extract` greifen über diese Schnittstelle zu. Sie dürfen nicht länger implizit annehmen, jeder Fluss sei mit `(group_id, arc_id)` indiziert. Die Zerlegung ausgewählter Bewegungen in Kabinenpfade bleibt gemeinsam und eindeutig.

### Öffentliche Optionen

Der vorhandene Runner erhält ausschließlich für `--method phase_arc_flow`:

```
--passenger-encoding legacy|od_flow|od_queue       # default legacy
--passenger-integrality all|boarding              # default all
--passenger-network legacy|contracted             # default legacy
--resource-encoding legacy|maximal                # default legacy
--conflict-cuts none|local_cliques                 # default none
```

Die Konfiguration ist optional; bisherige Aufrufe verwenden vollständig Legacy. Neue, nicht standardmäßige Optionen für `cp_sat` oder `all_stop_bound` werden vor dem Modellbau abgelehnt. Alle Kombinationen innerhalb des Kapazitäts-Phasenmodells benötigen eine geprüfte Kompatibilität; insbesondere wird `od_queue` bei nicht nachgewiesen austauschbaren Nachfragegruppen verständlich abgelehnt, nicht still vereinfacht.

`boarding` bedeutet ganzzahlige Mengen **je Einstiegsereignis**, nicht nur eine ganzzahlige Gesamtsumme je Nachfragegruppe. Bestand und Bordfluss dürfen nur dann kontinuierlich werden, wenn der Pfad-/Erhaltungsnachweis gilt.

Physikalischer Fingerprint, Graph-Fingerprint und Modell-Fingerprint werden getrennt ausgewiesen. Letzterer enthält Encoding, Struktur, Kompressionsabbildungen und tatsächlich erzeugte Cuts. Bestehende Checkpoints werden weiter gelesen; sie benötigen keine Migration. Kapazitätsziel und lokale Bound-Geltung ändern sich nicht.

## 4. Umsetzungsschritte und Abnahmekriterien

### Schritt 0 – Legacy isolieren und Baseline sichern

- Vorhandene Variablen und Zeilen nach Familie vollständig zählen, einschließlich kontinuierlicher Hilfsvariablen.
- Native Parameter, Versionsnummern, Referenzwert, Seedübernahme und echte Verbesserungen getrennt speichern.
- Legacy-Passagiercode in den gemeinsamen Baustein übertragen.
- Modellstruktur über normalisierte Variablen-/Zeilensignaturen prüfen; Reihenfolgeänderungen nicht mit mathematischen Änderungen verwechseln.
- Reine und solvergestützte Tests separat kennzeichnen.

**Abnahme:** Legacy baut dieselbe Algebra, reproduziert bisherige Zertifikate und behält Defaults. Keine Aussage über bitidentische Suchverläufe bei geänderter interner Variablenreihenfolge.

### Schritt 1 – P1: gemeinsame Bordflüsse

Kompatible Klassen werden zunächst konservativ durch OD, Richtung, tatsächliche Zielregel und gleiche Restwegbedingungen bestimmt. Unterschiedliche Freigaben sind nur am Einstieg zulässig. Bereits vorhandenes Vorwärts-/Rückwärtspruning wird wiederverwendet; Supports dürfen nicht lediglich durch ungeprüfte Vereinigungsbildung erweitert werden.

Je Gruppe bleiben ganzzahlige Einstiegsvariablen mit ursprünglichen Freigaben und Nachfrageobergrenzen. Danach gemeinsame Bordflüsse je Klasse und physischem Arc; Ausstieg am ersten zulässigen Ziel vor dessen Waiting. Kapazität zählt einen gemeinsamen Fluss genau einmal. Originale gruppenspezifische Schranken und ihre mögliche Wirkung auf die LP werden bei der Projektion erfasst.

Pro Klasse wird dokumentiert:

- welche Originalflüsse sie ersetzt;
- warum die Fortsetzungen kompatibel sind;
- welche Mengen beim Einstieg entstehen und am Ziel verschwinden;
- ob zusätzliche Schnittstellen notwendig sind.

**Abnahme:** Ganzzahlige Projektions-/Lift-Äquivalenz auf kleinen vollständig aufzählbaren Fällen; historische Referenzen darstellbar. Die LP darf nur nach dokumentierter Analyse schwächer sein. Nicht allein aus gleichen Optima eine gleiche LP-Projektion behaupten.

### Schritt 2 – P2: Nachfragezeitketten

Je kompatibler OD-Klasse entsteht eine Bodenwarteschlange. Ihre Ereignisse sind die exakten Freigaben und möglichen Einstiegszeiten. An jeder Zeit gilt:

```
Bestand_nach = Bestand_vor + Freigabe_am_Tick - Einstieg_am_Tick
Bestand_nach >= 0
```

Freigabe gilt einschließlich desselben Ticks. Die Kette wird als sparse Erhaltung formuliert, nicht als wiederholte lange Präfixsumme. Restbestand am Ende zählt als unbedient. Eingestiegene Personen dürfen weder zurück auf den Bodenfluss noch ohne Zielausstieg verschwinden. Anfangsbestand und Freigaben vor dem ersten nutzbaren Einstieg werden korrekt übernommen.

Der Klassenvertrag fordert gleiche weitere Bedienungsbedingungen und gleiche Kapazitätsgewichte. Andere Gruppenfristen, Prioritäten, individuelle Fahrzeitgrenzen oder unterschiedliche direkte Supports verhindern die Zusammenfassung. Klassen und Grund einer Ablehnung werden gespeichert.

**Lift:** Einstiege werden chronologisch aus bereits freigegebenen, unverbrauchten Personen derselben Klasse belegt. Diese Zuordnung erfolgt deterministisch und benötigt keinen zweiten Optimierer. An Bord wird die Gruppenherkunft als Rekonstruktionsinformation auf dem festgelegten Kabinenpfad mitgeführt. Eine nicht erfüllbare Zuordnung ist ein Modell-/Exportfehler, keine Gelegenheit zur nachträglichen Reparatur.

**Referenzen:** Für den exakten Replay eines importierten Seeds bleibt seine ursprüngliche Gruppenzuordnung als Zeuge erhalten. Derselbe aggregierte Punkt kann mehrere Gruppenzerlegungen besitzen. Für neue native Pläne wird eine zulässige Zerlegung erstellt und ihre Reisezeit separat berechnet. Gleicher U-Wert garantiert hier keine identische Reisezeit-Kontrollkennzahl.

**Abnahme:** Nachweis der Äquivalenz von Nachfragepräfixen und ganzzahliger Gruppenzuordnung unter dem Klassenvertrag; U=0, Teilbedienung und Nullbedienung korrekt. Kein universeller „alle Gruppen sind austauschbar“-Fallback.

### Schritt 3 – Ganzzahligkeit nur beim Einstieg

Diese Änderung wird zuerst auf dem geprüften P1-Builder umgesetzt. Bei binärer Bewegung und erhaltener Ein-Kabinen-Belegung jedes Phasenknotens entsteht je ausgewähltem Fahrzeug ein separater Pfad. Ganzzahlige Einstiege und erster verpflichtender Zielausstieg müssen die weiteren Flüsse auf diesem Pfad eindeutig ganzzahlig bestimmen.

- Jede Einstiegsvariable bleibt integer.
- Andere Passagierflüsse dürfen nur unter diesem Nachweis kontinuierlich werden.
- Bewegungen bleiben binär.
- Extraktion prüft Integrität; keine Rundungsreparatur außerhalb der vorhandenen Zertifikatstoleranz.

**Abnahme:** Keine fraktionalen Personen in kleinen vollständigen Suchen, im Odd-Cycle-Fall und bei fixierten Bewegungen. Bei vollständiger LP-Relaxation muss die gleiche Algebra wie P1 mit `all` entstehen. Gurobi-Presolve darf implizite Ganzzahligkeit wiedererkennen; das ist kein Fehler und kein garantierter Größengewinn.

### Schritt 4 – Deterministische Passagierketten komprimieren

Zunächst ausschließlich die Passagiersicht kontrahieren. Das physikalische Bewegungsnetz und seine State-Occupancy-Bedingungen bleiben erhalten.

Ketten ohne Boarding, Alighting oder sonstigen Bilanzwechsel können durch exakte Substitution verkürzt werden. Sämtliche ursprünglichen Kapazitätskopplungen zu unterschiedlichen Bewegungsarcs bleiben erhalten oder erhalten einen separaten Redundanznachweis. Ein gemeinsamer Passagierfluss darf dadurch nicht an ungewählten Zwischenbewegungen vorbeigeführt werden.

**Abnahme:** Gleiche LP-Projektion auf erhaltene Schnittstellen, gleiche Integer-Zertifikate und vollständige Referenzabbildung. Reduktion vor und nach Presolve messen. Nicht gleichzeitig physikalische Zeitpunkte entfernen.

### Schritt 5 – Ressourcenzeilen bereinigen und Konfliktcliquen ergänzen

**5a: `maximal`.** Ressourcenzeilen werden als sortierte `(arc_id, coefficient)`-Signaturen normalisiert. Entfernt werden nur identische oder bei derselben rechten Seite komponentenweise dominierte Zeilen mit nichtnegativen Variablen. Koeffizientenzähler bleiben erhalten, auch wenn ein Arc eine Ressource mehrfach betrifft. Jeder entfernten Zeile wird eine erhaltene implizierende Zeile zugeordnet.

**5b: `local_cliques`.** Zusätzliche ressourcenübergreifende Cliquen werden zunächst statisch aus exakt belegten paarweisen Konflikten erzeugt. Kein eigener Suchcontroller und keine pauschale O(|Arcs|²)-Matrix. Kandidaten entstehen aus lokalen Intervallüberlappungen und vorhandenen Konfliktindizes. Jede neue Clique erhält einen Nachweis für alle enthaltenen Paare; dieselbe oder dominierte bereits vorhandene Zeile wird nicht nochmals erzeugt.

Die optionale Cut-Erzeugung hat ein deterministisches Arbeitslimit und eine konfigurierte Größenobergrenze. Bei Erreichen bleiben alle ursprünglichen Ressourcenbedingungen erhalten; nur zusätzliche gültige Cuts entfallen. Das verändert nicht die Ganzzahligkeitskorrektheit. Cutliste und Grenze gehen in den Modell-Fingerprint ein.

**Abnahme:** Ganzzahlige Enumeration unverändert; LP-Bound nicht schwächer. Ein künstlicher Drei-Konflikte-auf-drei-Ressourcen-Fall zeigt, dass die neue Zeile den Punkt (0,5;0,5;0,5) ausschließt. Ein Gegenfall mit gemeinsam zulässigen Phasen und echter Überholung verhindert falsche Konflikte. Die Anwendung auf R2 ist nur eine Performancehypothese.

### Schritt 6 – Runner, Dokumentation und Abschluss

- Optionen und Fehlerbehandlung integrieren; alte Defaults behalten.
- Vorbereitungs-, Modellbau-, Hint-, Such-, Validierungs- und Gesamtlaufzeit separat berichten.
- LP-Relaxationswerte, native MIP-Bounds und unabhängig validierte U-Werte getrennt speichern.
- Rohwerte vor abgeschlossenem Root nicht als sinnvollen globalen Skip-Stop-Gap ausweisen.
- Quellen-/Versionsmanifest, Referenzhash und Modell-Fingerprint je Run ablegen.
- Markieren, wenn eine native Lösung lediglich die Referenz reproduziert; Seedübernahme zählt nicht als Verbesserung.
- Bericht nennt auch wirkungslose und schlechtere Varianten. Kein automatischer Standardwechsel.

## 5. Testplan

### A. Reine Tests während der laufenden Kampagne

Neue Dateien getrennt von Solver-Fixtures, beispielsweise `tests/test_reservoir_capacity_structure.py` und `tests/test_reservoir_capacity_projection.py`.

| Prüfung | Erwartung |
|---|---|
| Klassenbildung für gleiche OD, neun Releases | gemeinsame Restwegklasse, Releases bleiben korrekt abgebildet |
| Andere Ziele, Richtung, Frist oder zulässiger Restweg | Trennung beziehungsweise klare Ablehnung |
| Nachfragezeitkette, kleine Releases und sämtliche kleinen Boardingfolgen | Präfixzulässigkeit genau dann, wenn eine Gruppenbelegung existiert |
| Release exakt beim Einstieg / ein Tick später | erste zulässig, zweite unzulässig |
| Zwei Einstiege am selben Tick | gemeinsame Nachfrage wird nicht doppelt verbraucht |
| Keine Einstiege / U=0 / teilweise Bedienung | korrekter Endbestand |
| Deterministischer Lift mit Gruppenrestmengen | gültige Zuordnung ohne Überschreitung und ohne verlorene Personen |
| Kompression mit und ohne Bilanzwechsel | nur erlaubte Ketten werden substituiert |
| Zeilenidentität und Dominanz | Koeffizienten, nicht nur Arc-Mengen, entscheiden |
| Drei belegte Konflikte auf verschiedenen Ressourcen | Dreierclique korrekt |
| Nichtkonflikt und halb offene Übergabe | keine falsche Clique |
| Konfiguration/Fingerprint | stabile Serialisierung; nur Modell-, nicht Domain-Identität geändert |

Keine großen R2-Netzaufbauten und keine nativen Engineaufrufe in dieser Testgruppe.

### B. Kleine solvergestützte Korrektheitsfälle nach Ende der alten Kampagne

Die bestehenden Dateien `test_reservoir_capacity_phases.py`, `test_reservoir_capacity_bound.py`, `test_reservoir_capacity_runner.py` und `test_reservoir_capacity_additional.py` bleiben Regressionen. Neue Fälle liegen getrennt in `test_reservoir_capacity_formulations.py` und `test_reservoir_capacity_lp_projection.py`.

1. **Vollständige kleine Enumeration:** STOP/SKIP, optionale Flotte, No-Wait und Waiting, mehrere Gruppen und Integerzuordnungen. Enumeration ist unabhängig vom neuen Klassen-/Lift-Code. Alle Varianten müssen gleiche Kapazitätsoptima erreichen und ausschließlich gültige Zertifikate erzeugen.
2. **Warten und Lebenszyklus:** keine positive Wartezeit vor Freigabe, maximale Gesamtwartezeit über mehrere Holdingkanten, Freigabe während Waiting, Ankunft vor Ziel-Waiting, Rückkehr inklusive letztem Zustandsknoten, Schutzzeit über Horizont, Ankunft exakt am Horizont und ein Tick danach.
3. **Passagierintegrität:** volle Kabine, Aus-/Einstieg im selben Besuch, mehrere Releases derselben OD, unterschiedliche Ziele, keine zusätzliche Runde und keine künstlichen Umstiege. Bestehende Odd-Cycle-Instanz ausdrücklich weiterführen.
4. **Bewegungsintegrität:** echte Bypass-Überholung, gekoppelte Ressourcen, zeitlich später beginnende Reservierungen und ungenutzte Kabinen. Alle neuen Builder müssen dieselben physischen Bewegungen unterstützen.
5. **LP-Vergleich:** reine Ganzzahligkeitsverlagerung, exakte Kettensubstitution und Redundanzentfernung erhalten die entsprechende LP-Projektion. Konfliktcuts dürfen den Minimierungs-LB nicht verringern. Für P1/P2 separat dokumentieren, ob und warum die Projektion gleich oder schwächer ist.
6. **Nichttriviale LP-Fälle:** Nicht nur Instanzen mit U=0. Zusätzliche deterministische Zielfunktionen auf gemeinsamen Schnittstellen sowie Projektions-/Lift-Machbarkeit prüfen. Gleichheit einiger LP-Optimalwerte ist Evidenz, ersetzt aber keinen mathematischen Projektionsnachweis.
7. **Seed und Timeout:** ungültige positive Beförderung muss fehlschlagen; gültiger Seed wird nur als Hint behandelt. Unvollständiger Seed ist kein U=0-Zeuge. Timeout oder Speicherabbruch ohne native Lösung behalten die getrennte Referenz, ohne falsche Infeasibility-/Optimality-Aussage.

Kleine Tests mit einem Thread und knappen expliziten Limits, nacheinander. Kein paralleles pytest mit Solverjobs.

### C. Historische Replays und Modellbau

Auf genau demselben eingefrorenen Netzwerk:

- R0-Referenz aus `reservoir_capacity_campaign_20260911_v1/prepare/R0_ss.json`, U=285.
- R2-Referenz aus `reservoir_capacity_campaign_20260911_v1/prepare/R2_ss.json`, U=578.
- Frühere physikalisch gültige Skip-Stop-Reservoirpläne mit positivem Waiting, nicht nur die All-Stop-Referenzen. Auswahl aus bestehenden Checkpoints; Domäne vor Verwendung abgleichen.

Je Variante drei getrennte Prüfungen:

1. Referenzbewegung und ursprüngliche Passagierzuordnung als exakter Projektionszeuge; alle erzeugten Modellzeilen erfüllt.
2. Fixierte Referenzbewegung, Passagiere frei: Kapazitätsoptimum stimmt mit dem unabhängigen ganzzahligen Passagierpfad überein. Ein historischer Journey-Wert ist kein Kapazitätsoptimum.
3. Kleiner freier Fall ohne Hint findet selbst eine gültige Lösung.

Bei P2 ist eine andere zulässige Gruppenzerlegung im freien Kapazitätsoptimum erlaubt. Für den Replay der alten Zuordnung werden jedoch deren ursprüngliche Ride-Mengen und Journey-Kennzahl unverändert bestätigt. Originalreferenz und neues natives Zertifikat bleiben separate Artefakte.

Große Tests starten nur nach A und B. Fehlende historische Replays sind ein offener Gate-Punkt; sie werden nicht durch kleine Tests ersetzt.

## 6. Vorgeschlagene erste Performancekampagne

Die Kampagne wurde nach bestandenen Korrektheitsprüfungen abgeschlossen; ursprünglicher Lauf unter `reservoir_compact_campaign_20260911_v1`, Fortsetzung unter derselben Deadline unter `reservoir_compact_campaign_20260911_v2`. Implementierung und Korrektheit liegen außerhalb ihres Budgets. Sie untersucht zunächst Architektur, nicht gleichzeitig neue Solverparameter.

### Eingefrorene Varianten

| Kennung | Passagiere | Integer | Passagiernetz | Ressourcen | Zusätzliche Cuts | Direkter Vergleich |
|---|---|---|---|---|---|---|
| L | legacy | all | legacy | legacy | none | Referenz |
| P1 | od_flow | all | legacy | legacy | none | L |
| P2 | od_queue | all | legacy | legacy | none | P1 und L |
| I | od_flow | boarding | legacy | legacy | none | P1 |
| K | od_flow | all | contracted | legacy | none | P1 |
| R | legacy | all | legacy | maximal | none | L |
| C | legacy | all | legacy | legacy | local_cliques | L |

So werden Änderungen mit einer passenden Basis verglichen. Insbesondere I und K dürfen nicht als isolierte Änderungen gegenüber L interpretiert werden. Kombinationen von P2, K, R und C erhalten Korrektheitstests, aber keine automatische zusätzliche Suchkampagne.

### Budgetvorschlag: höchstens 60 Minuten tatsächliche Wandzeit

| Abschnitt | Budget |
|---|---:|
| R0 und R2: sieben Varianten, jeweils 120 s einschließlich Aufbau/Abschluss | 28 min |
| R2: beste neue Variante gegen L, Seeds 1 und 2, jeweils 300 s | 20 min |
| Einfrieren, gemeinsame Vorbereitung, Auswertung und Reserve | 12 min |
| Gesamt | 60 min |

Alle Läufe sequenziell mit zwölf Threads und 24 GiB Prozessbaumlimit; Gurobis internes SoftMemLimit verwendet die dazu passende dezimale GB-Zahl. Root-Methode bleibt automatisch, MIPFocus=0. Der Supervisor überwacht Gesamtdeadline, Kindprozesse und Suspend. Ausgefallene Budgets erzeugen keine Zusatzläufe.

120 Sekunden sind ein Screening auf Aufbau/Rootverhalten und frühe Lösungen, kein Langzeit-Leistungsurteil. Die bereits laufende 30-Minuten-Legacy-Messung liefert Zusatzkontext, ist aber kein gleichbudgetierter Ersatz für neue Kontrollen.

### Auswahl und Messung

Erfassen: Vorbereitung, Modellbau, Hintabbildung, Barrierabschluss, Crossoverabschluss, erste optimale Root-MIPNODE-Meldung soweit verfügbar, erste gültige native Lösung, jede echte Verbesserung, letzter Fortschritt, Suchknoten, RSS/CPU sowie Variablen/Zeilen/Nichtnullen vor und nach Presolve. Nicht verfügbare native Größen bleiben als unbekannt markiert.

Primäre Auswahl: validiertes U, dann vergleichbarer lokaler Netz-LB, dann Zeit bis zu diesen Werten. Sind alle Endwerte gleich und kein verwertbarer Bound vorhanden, darf für den technischen Bestätigungstest die Variante mit früherem Rootabschluss gewählt werden; ohne Rootabschluss nach kleinerer Presolve-Struktur, ersatzweise nach kleinerem ursprünglichem Modell. Dieser Ersatzmaßstab wird ausdrücklich markiert und begründet keine Lösungsqualitäts-Empfehlung.

Eine Empfehlung verlangt in beiden zusätzlichen Seeds mindestens eines:

- mindestens zehn zusätzlich bediente Personen;
- mindestens einen Prozentpunkt kleineren vergleichbaren Gap ohne schlechtere UB;
- mindestens 20 % weniger Gesamtzeit bis zum Erreichen der Legacy-End-UB und Legacy-End-LB, ohne schlechtere Endwerte.

Ist lediglich Root-Verarbeitung oder Größe besser, lautet das Ergebnis „strukturell verbessert“, nicht „Kapazitätsproblem gelöst“. Ist der Root-Bound null, wird das nicht als geschlossener Gap dargestellt. Das separate Thesis-Kriterium bleibt `validiertes U_SS < globales LB_AS`; aktuell wäre auf R2 U_SS<=124 erforderlich.

## 7. Liefergegenstände und Abschluss

- Experimentelle, einzeln konfigurierbare Builder mit Legacy-Standard.
- Solverfreie Vorbereitung und dokumentierte Klassen-/Projektionsverträge.
- Beweise beziehungsweise klar abgegrenzte Beweispflichten für P1, P2, Ganzzahligkeit, Kompression und Cuts.
- Getrennte reine Tests, kleine Solvertests und historische Replays.
- Neue Ergebnisordner mit eingefrorenen Eingaben/Quellen, Modellgrößen und Fortschrittsverläufen.
- Abschlussbericht mit Einzelwirkungen, bestätigten Vorteilen und Grenzen.

Längere Folgeläufe, neue Nachfrageinstanzen und der Ausbau auf sechs Stationen werden aus den Ergebnissen abgeleitet, nicht automatisch gestartet. Ein Planungs- oder Implementierungsabschluss ist keine Zusage, dass die verbleibende Forschungslücke damit geschlossen wird.
