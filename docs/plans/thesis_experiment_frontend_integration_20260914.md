# Thesisfälle, Fixed-K-Reihen und lesendes Ergebnisfrontend

**Aktualisierung 15.09.2026:** Die späteren Korrekturen, Reihensteuerung,
Frontenddetails und verbleibenden Messgates stehen im
[Abschlussbefund](../findings/thesis_completion_20260915.md). Die nachfolgende
frühere Bestandsaufnahme bleibt als Verlauf erhalten.

Stand: 14.09.2026. Umsetzungsplan nach den bestätigten 21 Integrationsantworten.
Zwei Stunden tatsächliche Wandzeit sind für die Kalibrierung freigegeben.
Implementierung und kleine Korrektheitstests liegen davor. Hauptkampagnen
beginnen nicht automatisch; ihre Budgets folgen aus der Kalibrierung.

Maßgeblich: [Entscheidungsregister](../thesis/experiment_definition_register_20260913.md),
[Versuchsdesign](../thesis/experimental_design_20260913.md),
[bisheriger Solverbefund](../findings/solver_reassessment_20260914.md).

**Korrigierter Umsetzungsstand 15.09.2026:** Fallbuilder, Einzel-/K-Runner,
Frontendübersicht und die budgetierte Kalibrierung sind vorhanden. Die
erneute Prüfung hat jedoch offene Integrationspunkte festgestellt: Live-Verläufe,
integrierte Replays, Abbildungsexporte und automatische Nachfrage-/Abbruchreihen
sind noch nicht vollständig umgesetzt. Neun der zwölf Gruppen sind noch nicht
kalibriert. Die bisherigen Arc-Flow-Messungen verwendeten entgegen dem Plan einen
automatischen All-Stop-Start; ihre Optima bleiben gültig, ihre Laufzeiten sind
als Messungen mit Startplan zu kennzeichnen. Künftige Thesis-Läufe deaktivieren
diesen Start ausdrücklich. Maßgeblich ist die
[Nachprüfung und Freigabeliste](../findings/thesis_implementation_review_20260915.md).
Der ursprüngliche Kalibrierungsbefund steht in
[G500-Kalibrierung](../findings/thesis_g500_calibration_20260914.md). Die
vollständige Hauptkampagne wurde nicht automatisch gestartet.

## 1. Ergebnis und Grenzen

Eine gemeinsame versionierte Fallbeschreibung versorgt Referenzberechnung,
beide Optimierer, unabhängige Validatoren und das Frontend. Das Frontend liest
lokale Ergebnisse; es startet oder beendet keine Prozesse. Ein exportiertes
Datenpaket soll mit dem Repository auf einem anderen Rechner ohne Solverlizenz
betrachtet werden können. Hosting ist nicht Teil dieses Pakets.

| Reihe | Topologien | Nachfrage | Geometrie/Zeitprofil | Optimierung |
|---|---|---|---|---|
| Kapazität | T5R, T6R | F0, F2, F3, F4 | G500/P0 | Evolution, genau K aktive Kabinen, No-Wait, `unserved` |
| Journey | T5R | F0, F2, F3, F4 | G500/P0 | Labelled Arc-Flow, feste Starts, genau K, No-Wait, Journey bei U=0 |

Das sind zwölf Gruppen, keine zwölf Läufe. K, Nachfragelevel und Wiederholungen
erzeugen weitere Einzelversuche. T6L, T6R-Journey, Waiting und neue ungleiche
Geometrien bleiben außerhalb. Vorhandene Längenprofile und alte Solver erhalten
ihre bisherigen Identitäten und bleiben im Archiv beziehungsweise als Kontrollen.

## 2. Gemeinsamer Fallvertrag

### Geometrie und Betrieb

- G500: 500 m freie Seilstrecke je Abschnitt, Stationswege separat.
- Seil 6 m/s, Plattform 0,3 m/s, Kapazität 10; symmetrisch 1 m/s².
- Brems-/Beschleunigungsweg je 17,955 m, Plattform 15 m, schnelle Verbindungen
  je 5 m; STOP-/Bypassweg je 60,91 m. Bestehende Integer-Tick-Konvertierung nutzen.
- Architektur B, Ressourcenregeln und gemeinsamer Reservoirport mit
  Rope-Headway unverändert. Kein Runden der Bewegungen auf Nachfragezeitgruppen.
- Kapazität: Warmup ein AS-Umlauf, 45 min Freigaben, 15 min Completion mit
  bestehender Erreichbarkeitsprüfung; gemeinsame konfliktfreie Recovery prüfen.
- Single-Use-Linien fahren durchgehend bis zur ersten vollständigen Rückkehr
  am oder nach der Bedienungsdeadline. Auch leere Kabinen dürfen nicht vorher
  ausscheiden. Erste Dispatchphase frei im gemeinsamen Dispatchfenster.
- Journey: gemeinsame laufende Fixed-K-Starts, Freigaben über zwei AS-Umläufe,
  explizite gemeinsame Completion. K-spezifische Starts dokumentieren.

G500 ist durch die untere Größenordnung der [Câble-C1-Abstände von
500–1.800 m](https://www.iledefrance-mobilites.fr/le-reseau/projets/cablec1/mediatheque/kit-presse-c1)
motiviert. Reale Stationsabstände sind nicht identisch mit unseren freien
Seilstrecken. Die bisherigen Quellen und Annahmen für Stationstechnik aus dem
Entscheidungsregister im Fallmanifest mitführen, nicht durch diesen Beleg ersetzen.

### Fall- und Laufidentität

`ExperimentCaseSpec` erweitern beziehungsweise durch kleine unveränderliche
Teilkonfigurationen ergänzen: Geometrie, Betriebsvertrag, Nachfragefunktion,
Referenzdefinition und Version. Solverkonfiguration, K, Seed und Elternlauf
gehören in eine separate Laufbeschreibung. Physikalische und Modellidentitäten
nicht vermischen. Alte Fingerprints/Checkpoints bleiben lesbar.

Freigabeauflösungen 30/15/5 s aus derselben verschachtelten Personenfolge
ableiten. Richtungsfilterung vor Normalisierung; F0/F2/F3/F4 und P0/P1/P4 nicht
neu erfinden. P1/P4 erscheinen nur als Kontrollen. Zeitfenster und relevante
OD-Mengen müssen in Referenz und Optimierung identisch sein.

## 3. Implementierungsschritte mit Zwischentests

### Schritt A — G500 und zwölf Gruppen

Betroffen:
`examples/thesis_cases.py`, `benchmarking/thesis_cases.py`,
`tests/test_thesis_experiment_cases.py` unter dem bestehenden Pythonpaket.

G500 als neues Profil hinzufügen. Neue versionierte Gruppendefinition mit zwölf
Gruppen ergänzen; alte neun Gruppen für historische Kalibrierungen verfügbar
halten. Der neue Runner wählt ausdrücklich die neue Version. Quellen,
Abschnittslängen, Stationslängen und tatsächliche Umlaufzeiten exportieren.

**Gate:** Alle zwölf Fälle solverfrei bauen; eindeutige IDs, passende Summen und
Richtungsfilter, exakte Kinematik, reproduzierbare Nachfrage. Bestehende Profile
und historische Manifeste unverändert laden. T5 und T6 auch visuell prüfen.

### Schritt B — belastbare All-Stop-Referenzen

Bestehende `benchmarking/thesis_all_stop_capacity.py` und
`optimization/ddd/all_stop_phase.py` anbinden; keinen zweiten Referenzsolver
kopieren. Regelmäßige No-Wait-Flotte einschließlich Anfang, Port und Rückkehr
prüfen. Nicht durch K teilbare Umlaufzeiten benötigen die bestehende exakte
Tickbehandlung; eine verkürzte Phasensuche verlangt nachgewiesene Symmetrie.

Referenzdatensatz enthält `K_AS`, Phasenvertrag, Nachfrageprofil, bestätigtes
N mit U=0, kleinste bewiesen nicht vollständig bedienbare Nachfrage und offene
Zwischenpunkte. Maximum nur bei vollständiger Bedienung N und bewiesener
Unmöglichkeit N+1. Ein einzelner schlechter Plan oder Timeout setzt keine obere
Kapazitätsgrenze. Ein Flottenmaximum verlangt Ausschluss aller relevanten
größeren regelmäßigen Flotten oder einen gültigen physikalischen Bound.

**Gate:** Kleine vollständige Phasen-/Nachfrageenumeration, benachbarte Ticks,
integer Passagiere, unabhängige Validierung, ehrliche Timeoutintervalle.
Referenzpläne werden nicht automatisch zu evolutionären Startindividuen.

### Schritt C — Evolution auf neue Fälle und deterministischen Katalog anbinden

Bestehende Module unter `optimization/ddd/reservoir_lines/evolution` nutzen:
`model.py`, `search.py`, `operators.py`, `interval_decoder.py`, `evaluator.py`
und `passengers.py`; Runner `benchmarks/run_reservoir_line_evolution.py`.

Der Runner erzwingt aktuell `relevant`. Dies durch eine explizite
Katalogkonfiguration ersetzen, bei unverändertem Legacy-Default. Neues Profil
`od_endpoints_v1`: All-Stop sowie je positiv nachgefragtem gerichtetem OD-Paar
die Stationsmaske seiner beiden Endpunkte. Gleiche Masken deduplizieren und
stabil sortieren. Technisch verpflichtende Halte nur übernehmen, wenn der
Domänenvertrag sie tatsächlich fordert; Portpassage ist nicht automatisch STOP.
Keine zusätzlichen vereinigten Masken, kein heimliches Top-N-Abschneiden.
Kataloggröße und OD-Abdeckung je F-Profil vorab dokumentieren.

Eingefrorene Pilotkonfiguration: vorhandene pymoo-GA mit gruppierter Auswahl,
Population 32, acht Nachkommen, `mixed_global`, `patterns_dispatch`,
Intervall-Decoder und `no_wait_first`. Keine neue Suchengine und keine
Waiting-Untermodelle. Exakt K, keine absichtliche All-Stop-Initialisierung,
keine historischen guten Seeds. All-Stop darf wie jedes Katalogmuster durch
Suche entstehen. Konfiguration samt vorhandenen Operatorwahrscheinlichkeiten
vollständig speichern; Legacy-Aufrufe nicht ändern.

Decoder berechnet No-Wait-Bewegungen und prüft sämtliche Konflikte; Gurobi-IP
bewertet nur die Passagiere bei festen Bewegungen. Fehlende Kabinen sind ein
Konstruktionsmaß, keine physische Konfliktzahl. Unvollständige oder kollidierende
Pläne erzeugen keinen bestätigten Bedienungswert.

**Gate:** Katalog reproduzierbar und vollständig gemäß Regel; K-Erhaltung aller
Operatoren, kein versteckter guter Startplan, kein Timing-Solveraufruf,
Port-/Rückkehrvertrag, Passagier-IP gegen kleine Enumeration. Kleine freie Suche
findet selbst einen vollständigen gültigen Plan mit positiver Bedienung.

### Schritt D — Fixed-K-Reihen und Weitergabe

`benchmarks/run_thesis_experiment.py` über Methodenadapter erweitern;
`benchmarking/thesis_adaptive_fleet.py` nur soweit mit exakt K vereinbar
wiederverwenden. Kein Kmax-Lauf als Fixed-K-Ergebnis deklarieren.

- Journey: N bleibt bei 50 % von `kappa_AS(K_ref)` pro Profil; beide Verfahren müssen beim
  jeweiligen K vollständig bedienen. Phasenoptimiertes AS zusätzlich zum
  eigentlichen Vergleich mit gemeinsamen festen Starts anzeigen.
- Kapazität: erste Nachfrage bei `kappa_AS(K_AS)`, höhere Stufen vorläufig
  geometrisch mit 1,1; je N eine getrennte K-Reihe. Offene AS-Kapazität nur als
  bestätigte untere Referenz verwenden und kennzeichnen, nicht als bekanntes κ.
- Start jeder Seed-Reihe ohne bekannten guten Plan. Vorlösungen derselben Reihe
  dürfen weitergegeben werden, aber nicht zwischen unabhängigen Seeds.
- Für Evolution bei K-Erhöhung bisherige Muster/Dispatchs als Elterninformation
  übertragen und fehlende Kabinen über vorhandene Operatoren ergänzen. Der alte
  Plan gilt erst nach vollständiger Konstruktion und Prüfung bei neuem K als
  Incumbent. Falls keine zulässige Ergänzung entsteht, trotzdem frisch suchen.
- Arc-Flow nur kompatible kanonische Entscheidungen übernehmen. Geänderte feste
  Starts verhindern oft ein vollständiges Replay; dann ausdrücklich Teil-Hint
  oder kein Hint. Keine Änderung der vorgegebenen Startpolicy zur Seedrettung.

Zeit je K und kumulierte Zeit, Elternlauf, übernommene Bedienung und neue
Verbesserungen getrennt berichten. Seeds 0/1/2 sind drei komplette evolutionäre
Reihen. Journey zunächst ein Lauf pro Punkt plus ausgewählte Wiederholungen.

**Gate:** Übergang K→K+1 mit erfolgreicher und scheiternder Übertragung; keine
inaktive Ersatzkabine. Unzulässiger/inkompatibler Seed liefert eine klare Meldung
und wird nicht still als gültige Lösung gewertet. Unterbrochene Reihen sind
anhand gesicherter Artefakte fortsetzbar, ohne Zeiten zurückzudatieren.

### Schritt E — Artefakte und lesendes Frontend

Bestehende Komponenten in `frontend/src/App.tsx`, Scenario-, Optimization- und
EvolutionLive-Seiten sowie Manifest-/Replayexport wiederverwenden. Neue
Thesis-Übersicht als Einstieg; existierende URLs und Archiv bleiben erreichbar.

Ansichten:

1. Fallübersicht: zwölf Gruppen, Topologie/Länge getrennt, Nachfragefunktion,
   technische Parameter, tatsächliche Betriebsfenster und Quellen.
2. Reihenübersicht: K × N, Status, AS-Referenzintervall, bestes gültiges Ergebnis,
   Laufzeit und kumulierte Zeit; fehlende Ergebnisse als fehlend.
3. Laufdetail: Bedienung beziehungsweise Journey über Zeit, native Bounds mit
   Gültigkeitsbereich, Generationen/Population, gültiger Anteil, Konstruktion
   und Konflikte getrennt. Keine erfundene evolutionäre globale Gap-Kurve.
4. Replay: jede Bestverbesserung auswählbar; Muster, Dispatch, Belegung und
   synchronisierter All-Stop-Vergleich aus den passenden Zertifikaten.
5. Archiv: frühere Methoden und andere Verträge sichtbar als historische Fälle.

Gemeinsames versioniertes Resultatmanifest mit relativen Pfaden, kleinen
Summaries und getrennten Verlauf-/Replaydateien. Atomare Snapshotupdates und
Polling; keine Steuerungs-API. Noch unvollständiges JSON, HTML statt JSON,
fehlender Pfad und veraltete Snapshots müssen unterscheidbar angezeigt werden.
Letzten gültigen Snapshot bei vorübergehendem Lesefehler behalten.

Alle validierten Bestverbesserungen speichern; Populationsdaten aggregieren,
fehlerhafte Kandidaten stichprobenartig. Export: SVG/PDF, CSV, JSON-Konfiguration,
Zertifikate und vorhandene Replay-/Videofunktionen. Ein Paketmanifest listet
ausgewählte Dateien und Quellen; keine Lizenzdateien, absoluten privaten Pfade
oder vollständigen unkontrollierten Arbeitsverzeichnisse exportieren.

**Gate:** Frontendbuild und passende Komponententests; echte UI-Prüfung für
laufenden, fertigen, unterbrochenen und ungelösten Versuch. Export in ein neues
Verzeichnis kopieren, lokal servieren und ohne Python-Solverbackend öffnen.
G500, Quellen, Chartdaten und Replay müssen weiterhin stimmen.

## 4. Kalibrierung: höchstens 120 Minuten Wandzeit

Die Kalibrierung misst ausgewählte Fälle, nicht die vollständige Hauptmatrix.
Vorher alle zwölf Fälle bauen und kleine Gates bestehen. Ein eingefrorenes
Kampagnenmanifest verhindert nachträgliche Auswahl erfolgreicher Fälle.

| Abschnitt | Versuche | Maximum |
|---|---|---:|
| AS-Referenz und Auflösung | T5R-F2 Journey, T5R-F2 Kapazität, T6R-F2 Kapazität; jeweils 30/15 s, 4 min pro Versuch einschließlich Einklammern | 24 min |
| Evolution-Größenprüfung | T5R/T6R-F2, je K_AS, K_AS+1, ceil(1,1 K_AS), je 5 min; Seed 0, Weitergabe innerhalb der Reihe | 30 min |
| Arc-Flow-Größenprüfung | T5R-F2, K_ref, ceil(1,5 K_ref), ceil(2,25 K_ref), jeweils höchstens K_AS, je 3 min; All-Stop im selben Modell zusätzlich | 18 min |
| Evolution-Verlauf | vorab T6R-F2 bei K_AS+1, Seeds 1/2, je 10 min, beide ohne bekannten Startplan | 20 min |
| Arc-Flow-Verlauf | größtes erfolgreich aufgebautes K aus obiger Leiter, zwei Wiederholungen je 10 min | 20 min |
| Einfrieren, zusätzliche Referenzprüfung und Abschluss | harte gemeinsame Reserve | 8 min |
| **Gesamt** | | **120 min** |

K_ref-Kandidat ist für diesen Vortest `min(10, floor(K_AS/2))`, mindestens 1.
Das ist ein Kalibrierungsvorschlag, keine Behauptung einer realen halben Flotte.
Vor Solverstart Größen aller drei K prüfen. Scheitert der Aufbau bereits am
Ressourcenlimit, den gescheiterten Versuch protokollieren und K_ref nicht
nachträglich innerhalb derselben Nachfragekurve ändern.

AS-Auflösungsvergleich nur als geklärt werten, wenn abgesicherte Intervalle
höchstens 1 % Abweichung zulassen und die Kernaussage unverändert bleibt. Breite
Intervalle sind ungeklärt. 5-s-Prüfung nur innerhalb der ausgewiesenen Reserve;
sonst ausdrücklich ausstehend. F0/F3/F4-Referenzen müssen vor den Hauptreihen
noch separat kalibriert werden. Fehlende Referenzen erzeugen keine erfundenen
Nachfragemengen. Abhängige Läufe ohne positive gültige Referenz bleiben ausstehend.

K_AS aus geprüfter regelmäßiger AS-Belegung bestimmen, nicht aus alten 38/50-
Grenzen übertragen. Keine erzwungene Stufe über der sicheren Dispatchgrenze.
Duplizierte K entfallen; frei werdende Zeit startet keine zusätzlichen Langläufe.

Alle Prozesse sequenziell. Bis zwölf Threads wo unterstützt, tatsächliche
Decoder-/Passagierthreadzahl dokumentieren. 32 GiB Prozessbaum-RSS sind Maximum
auf dem 36-GiB-Mac, keine zugesicherte freie Menge. Bestehender Supervisor prüft
Speicherdruck, Swapentwicklung, Kindprozesse und reale Deadline einschließlich
Suspend; kritischer Druck über 30 s oder RSS-Überschreitung führt zum kontrollierten
Abbruch. Speicher-/Zeitabbruch ist kein Unzulässigkeitsbeweis.

## 5. Messung und Hauptkampagnenentscheidung

Pro Lauf: Quellen-/Codehash, Versionen, Fall, Musterkatalog, Seed, Startinformation,
Aufbau-/Decoder-/Prüf-/Passagier-/Suchzeit, Modellgrößen, Peak-RSS, gültiger Anteil,
erste gültige Lösung, Bestverbesserungen und Zeitpunkt des letzten Fortschritts.
Charts erhalten Beobachtungen bei 30/60/120/300/600 s, soweit der Lauf so lange
dauert. Keine Zwischenwerte erfinden. Root-Verlauf und echte globale Bounds
nur bei den jeweiligen exakten Modellen ausweisen.

Der Befund kommt nach `docs/findings/thesis_g500_calibration_20260914.md` und
enthält eine Bereitschaftstabelle für alle zwölf Gruppen. F2-Messungen begründen
keine automatisch bestätigte Skalierung aller anderen Nachfrageprofile.

Vor Hauptkampagnen festlegen:

- K_ref und realistisch lösbare Journey-K-Leiter pro vergleichbarer Gruppe;
- wenige Kapazitäts-K-Stufen nahe K_AS, Nachfrageleiter und Stopregeln;
- Laufbudgets anhand Erstlösung, weiterem Fortschritt und Plateau, nicht nur
  Endwert; ein No-Wait-Heuristikfehlschlag beweist keine physikalische Grenze;
- tatsächliche AS-Kapazitätsintervalle und offene Referenzarbeit;
- erwartete Gesamtrechenzeit als Summe aller Referenz-, K-, N- und Seedläufe;
- zusätzliche Beweisaussagen nur bei identischen Verträgen. Ein besserer Plan
  als eine gefundene AS-Lösung schlägt nicht automatisch jedes AS-Optimum.

Keine automatische Waiting-Erweiterung, neue Engine oder vollständige
Hauptkampagne aus diesem Plan. Bei ausbleibender gültiger Evolution-Lösung
Konstruktion, Katalog, kontinuierlichen Lebenszyklus und Bewertungskosten
getrennt als Engpass berichten. Das Ergebnis darf auch sein, dass einzelne
Versuchsgruppen mit den verfügbaren Methoden noch nicht einsatzbereit sind.


## Amendment 2026-09-16: exclude F4 from remaining campaigns

At the user’s request, F4 is excluded from all remaining reference preparation, Evo and Greedy runs (with and without Waiting), and future optimisation queues. Active T6R/F4 preparation was stopped. Completed F4 results remain archived as local-demand controls. Active families are F0, F2 and F3. Completed non-F4 references are reused; no saved run is repeated and no excluded budget is reassigned. This experiment-scope decision does not establish global All-Stop optimality for F4.
