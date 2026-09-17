# Plan: Intervallkodierung vorbereiten und größere Linienfälle vermessen

Stand: 13.09.2026. **Die kontrollierte Fünf-Stationen-Längenskalierung ist
abgeschlossen; die quellenkalibrierten Sechs-Stationen-Fälle bleiben offen.**
Die native Intervallkodierung und V2-Präfixkompaktierung sind implementiert.
Ergebnisse der ersten 300/800/1.200-m-Matrix stehen im
[Längenskalierungsbericht](../findings/reservoir_line_length_scaling_results_20260913.md).
Begleitplan für die noch offenen realen Profile:
[Beispiele und Betriebsverträge](thesis_example_calibration_20260913.md).

Die weitergehende Komprimierung gemeinsamer Rundenvorsätze, Passagiere und
Ereignisketten wird im [V0–V4-Testplan](reservoir_line_compaction_tests_20260913.md)
als eigene gestufte Ablation behandelt. Dessen
[Ergebnisbericht](../findings/reservoir_line_compaction_results_20260913.md)
sammelt die späteren Messungen. Die vorgeschlagenen Kampagnenbudgets sind
getrennt; dieser Verweis startet keine zusätzliche Kampagne.

## 1. Ziel und Ausgangspunkt

Prüfen, ob längere Strecken mit mehr verfügbaren Kabinen im bestehenden
No-Wait-Linienmodell sinnvoll lösbar bleiben. Vorbereitung verkleinern, ohne
die zugelassenen Fahrpläne, Freigaben oder Passagierentscheidungen zu ändern.
Die Suchentscheidungen treffen weiterhin ausschließlich CP-SATs native Verfahren.

Relevante Dateien:

- `src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_lines/preparation.py`
- `src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_lines/cp_model.py`
- `src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_lines/passenger_model.py`
- `src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_lines/config.py`
- `src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_lines/certificate.py`
- `benchmarks/run_reservoir_lines.py`, `tests/test_reservoir_lines.py`

Runner und `ReservoirLineConfig` verwenden seit der abgeschlossenen
Kompaktierung standardmäßig `intervals + encoding_specific + shared_rounds`.
Die alten Varianten bleiben explizit auswählbar und dienen der Regression.

## 2. Exakter Vertrag der beiden Darstellungen

Eine Vorlage t legt Haltemuster, Rundenzahl und relative Belegungen fest.
Für Kabinenslot k mit Dispatch d_k hat Ressourcennutzung j das Intervall

\[
I_{ktj}=[d_k+\alpha_{tj},\ d_k+\beta_{tj}).
\]

Die geschützte Dauer ist \(\beta-\alpha\), einschließlich vorhandener
Schutzzeiten. Das optionale Intervall ist genau dann präsent, wenn die
zugehörige Vorlage gewählt wird. Je Ressource gilt natives `NoOverlap`.
Die bereits vorhandenen synthetischen Ein-Tick-Intervalle für Zustandskollisionen
bleiben erhalten. Kein Abschneiden an der Bedienungsdeadline.

`dispatch_domains` beschreibt dieselben Konflikte durch erlaubte Bereiche
des Dispatchunterschieds für jedes Kabinen-/Vorlagenpaar. Es schreibt keine
gemeinsame Ressourcenreihenfolge vor. `intervals` überlässt diese Beziehung
den nativen Intervallbedingungen. Beide müssen dieselben ganzzahligen
Fahrpläne und Passagieroptima darstellen, einschließlich zulässiger Überholung.

Die gemeinsamen Auswahl-/Aktivitätsregeln, sortierten Dispatches, erste Abfahrt
null, ganzzahligen Ride-Mengen, Zielgewichte und Exportregeln bleiben unverändert.
Gleicher Bewegungsvertrag bedeutet nicht automatisch gleiche Relaxation,
gleiche Laufzeit oder brauchbare globale Schranken des allgemeinen Skip-Stop-Problems.

## 3. Konkrete Änderung: ungenutzte Paarvorbereitung auslassen

**Codebefund:** `prepare_line_problem` erzeugt gegenwärtig mit `_pair_domain`
alle geordneten Templatepaare, auch für `intervals`. `cp_model.py` liest diese
Paarbereiche nur im `dispatch_domains`-Zweig. Die Intervallvariante trägt damit
Vorbereitungs-, Speicher- und Manifestkosten für nicht verwendete Daten.

### Umsetzung

1. Unveränderlichen gemeinsamen Kern aus Vorlagen, Ressourcen, Zustandsereignissen
   und Dispatchgrenzen von encodingabhängigen Paarbereichen trennen.
2. Einen expliziten Vorbereitungsmodus einführen, vorgeschlagen
   `pair_preparation=legacy_eager|encoding_specific`; `legacy_eager` erhält den
   bisherigen Pfad für den Vergleich und alte direkte Aufrufer.
3. Bei `encoding_specific + intervals` keine `_pair_domain`-Aufrufe und keine
   materialisierten Templatepaarlisten. Vorlageninterne Konfliktprüfung bleibt.
4. Bei `dispatch_domains` Paarbereiche weiterhin vollständig berechnen. Zugriff
   auf nicht vorbereitete Bereiche muss einen verständlichen Fehler liefern,
   nicht eine leere zulässige Domain vortäuschen.
5. Potentielle Paarzahl, tatsächlich materialisierte Paarzahl und
   Vorbereitungsmodus getrennt protokollieren. „Nicht berechnet“ nicht als
   „null Konflikte“ ausgeben.
6. Physikalischen Fingerprint und kanonische Vorlagen-/Ride-IDs erhalten;
   geänderte Vorbereitungs-/Modellversion in eigenen Fingerprints festhalten.
   Historische Zertifikate nach physikalischer Domäne und IDs prüfen und
   kompatible Hints übersetzen, nicht anhand einer neuen Modellhashgleichheit ablehnen.
7. Optimizer und Runner geben den Modus explizit weiter. Keine zweite Kopie
   des Gesamtsolvers und kein geänderter Passagierbuilder für diese Ablation.

**Erwartung:** geringere Vorbereitungszeit und weniger Python-/Manifestdaten.
Das CP-Modell kann dabei unverändert groß bleiben. Deshalb kein behaupteter
Suchgewinn allein aufgrund dieser Änderung.

## 4. Größenmodell und zu messende Ursachen

Bezeichne Kmax die Slotzahl, P die Musterzahl, T die Vorlagenzahl einschließlich
Rundenzahlalternativen, R_t die Ressourcen-/Zustandsintervalle je Vorlage und
B_t die zeitlich unterstützten Beförderungskandidaten je Slot/Vorlage.

| Teil | Struktur im bestehenden Builder |
|---|---|
| Linienauswahl | Kmax × T Boolesche Variablen |
| Intervallobjekte | Kmax × Summe_t R_t |
| Beförderungsvariablen | ungefähr Kmax × Summe_t B_t; abhängig von Nachfragegruppen und Pruning |
| Explizite Dispatchpaarzeilen | bis zu Kmax(Kmax−1)/2 × T² |
| Paarvorbereitung | T² Paare mit zusätzlichen Vergleichen ihrer Ressourcenbelegungen |

Bei gesättigtem regelmäßigen Betrieb ist näherungsweise K≈C/h und die Rundenzahl
je Kabine H/C. Gesamtumlaufzahl≈H/h kann deshalb bei längerer Strecke ähnlich
bleiben. Das ist weder eine Komplexitätsgarantie noch eine Aussage über den
Vorlauf-/Rückkehrfall. Mehr Kabinen können weniger Rundenzahlvorlagen bedeuten;
ein gleichzeitig verlängerter Horizont kann diese Entlastung wieder aufheben.

Nicht nur Meter und K protokollieren: tatsächliche Besuche, T, Ressourcenintervalle,
Nachfragegruppen und Kandidaten sind die erklärenden Größen. Personenanzahl und
Nachfragegruppenzahl getrennt halten; letztere kann viele zusätzliche Variablen erzeugen.

Historische Größen stehen in den
[Linienmodellbefunden](../findings/reservoir_line_dispatch_pilot_20260912.md).
Die dortigen Rohmodellgrößen sind keine lineare Prognose der Solver-Peak-RSS.

## 5. Korrektheitsgates

Vor Performancevergleichen:

- Kleine endliche Dispatchdomänen vollständig aufzählen: direkte Prüfung der
  geschützten Intervalle, `dispatch_domains`, alte Intervallvorbereitung und
  neue Intervallvorbereitung müssen dieselben Bewegungen zulassen.
- Ganzzahlige Passagieroptima auf denselben kleinen Fällen vergleichen.
- Grenzkontakt `end_1 == start_2` zulässig; Überlappung um einen Tick unzulässig;
  Schutzzeiten, Zustandsgleichheit und Rückkehr genau an der Grenze prüfen.
- Unterschiedliche Reihenfolge an zwei Ressourcen, Bypass-Überholung,
  eine erst später beginnende Reservierung und mehrere Nutzungen je Vorlage.
- Optionale Flotte einschließlich null und eins; abgewählte Vorlagen blockieren
  keine Ressource. Ungenutzte Slots verändern keine Fahrgastbilanzen.
- Freigabe am Plattformausstieg, Zielankunft vor dessen Waiting, Kapazität vor/nach
  Ein-/Ausstieg, keine zusätzlichen Runden oder Umstiege in einer Beförderung.
  Die Variante selbst bleibt No-Wait.
- Historischen Max50-R2-Checkpoint fixiert reproduzieren und unabhängig validieren;
  danach als Hint ohne Fixierung laden. Wert und Herkunft vor dem Vergleich einfrieren.
- Regression aller bestehenden Linien-/Reservoirtests; alte direkte
  Vorbereitungstests mit Paarbereichen behalten einen ausdrücklich passenden Modus.
- Gezielt bestätigen, dass neue Intervallvorbereitung keine Paartabellen baut;
  ein fehlender Datensatz darf nicht als erlaubtes Paar missverstanden werden.

Timeout, Speicherabbruch und fehlender Incumbent bleiben unentschiedene Suchbefunde.
Seedübernahme ist keine native Verbesserung. Native Rohwerte und unabhängig
validierte Fahrpläne getrennt speichern.

## 6. Messinstrumentierung vor größeren Geometrien

Runner ergänzt beziehungsweise prüft folgende einzeln ausgewiesene Messungen:

- Domänenaufbau und kanonische Kandidatenerzeugung;
- Vorlagenaufbau, Paarvorbereitung, CP-Modellbau und Hintaufbau;
- Solverstart, Presolve, erste gültige native Lösung, echte Verbesserungen,
  letzter Fortschrittszeitpunkt und Validierung;
- tatsächliche Gesamtwandzeit einschließlich Aufbau/Abschluss;
- Prozessbaum-Peak-RSS, verfügbare CPU-Messung und Workerzahl;
- Kmax, genutzte Kabinen, P, T, Besuche, Kandidaten, q-Variablen,
  Boolesche Variablen, Intervalle, Constraints und Proto-Größe;
- native Bounds mit Katalog-/Dispatch-/No-Wait-Gültigkeitsbereich.

`--build-only` wird für beide Modi nutzbar gehalten. Quellenhashes, Engineversion,
physikalische Konfiguration und Startzertifikat werden eingefroren. Ein Manifest
der Intervallvariante darf keine unbenutzten Paarlisten serialisieren.

## 7. Vorgeschlagene erste Kampagne: maximal 75 Minuten

Budget ist ein Vorschlag für spätere Ausführung, keine aktuelle Laufautorisierung.
Implementierung und kleine Korrektheitstests liegen davor. Alle Versuche sequenziell,
zwölf Worker; zunächst 24 GiB Prozessbaum-RSS als expliziter, konfigurierbarer
Versuchswert nach Prüfung des verfügbaren Speichers. Limit/Abbruch darf nicht
durch Betriebssystem-Swap verschleiert werden. Ein übergeordneter Prozess
überwacht Gesamtdeadline und Kinder einschließlich Suspend.

### A. Vorbereitungsablation

Historischen unveränderten R2-Fall verwenden: drei Build-only-Wiederholungen
je Modus `intervals + legacy_eager` und `intervals + encoding_specific`.
Quelle, Passagiergruppen, Flotte, Vorlagen und Parameter sonst identisch.
Auswertung auf Bauzeit/Speicher; kein Suchvorteil aus einem nur kleineren
Vorbereitungsmanifest ableiten. Paar- und Intervallencoding nur auf kleinen
kontrollierbaren Fällen direkt gegeneinander testen.

### B. Strukturelle Geometriematrix

Auf einer gemeinsamen Topologie, vorzugsweise Sechserring, unveränderte
Stationsphysik, konstantes Nachfrageprofil und festen kleinen Musterkatalog nutzen.

| Matrix | Längen | Flotte und Zeitvertrag | Zweck |
|---|---|---|---|
| Kontrollierte Größenprobe | 300/800/1.200 m | Identische absolute Zeitachse, Kmax je gesättigter AS-Geometrie abgeleitet | Mehr Slots gegen weniger Runden isolieren; kein fairer stationärer Kapazitätsvergleich behauptet |
| Tatsächliche Betriebsszenarien | dieselben drei | Gemäß Beispielplan geprüfter Vorlauf und Rückkehr, gleiche Nachfrage-/Bedienungsfenster | Praktischen Aufwand der Thesisfälle erfassen |

Jeweils K_AS und vorgeschlagen ceil(1,25 K_AS) ausweisen; die zugehörigen
Buildvarianten dürfen bei zu hohem prognostiziertem Aufwand als ausstehend
markiert werden. Historisches R2 dient nur der Regression, nicht als direkte
Größenvergleichszeile einer anderen Topologie. Keine gleichzeitige Einführung
von 14 Mustern und feinerem Freigabeprofil.

### C. Suchprobe

Für die drei freigegebenen tatsächlichen Betriebsszenarien je zwei Läufe mit
300 s Gesamtbudget einschließlich Aufbau/Validierung: Seeds 0 und 1, gleiche
gültige Startbewegung innerhalb desselben Falls. Physikalisch geänderte Fälle
erhalten neu geprüfte Seeds, keine blind übertragenen alten Zeitstempel.
Presolve und weitere Suchparameter vorab festhalten; nicht nebenbei tunen.

| Abschnitt | Maximaler Anteil |
|---|---:|
| Einfrieren, Vorbereitungsablation, Größenmatrix | 30 min |
| Sechs Suchproben à 300 s Gesamtzeit | 30 min |
| Abschluss und Reserve | 15 min |

Nach Deadline keine neuen Läufe. Nicht freigegebene/abgebrochene Fälle bleiben
ausstehend; deren Zeit wird nicht automatisch für Langläufe umgewidmet.

## 8. Entscheidung und weitere Änderungen nur nach Befund

| Beobachtung | Konsequenz |
|---|---|
| Weniger Paarvorbereitung, gleiche CP-Größe | Struktureller Erfolg; als empfohlenen Vorbereitungsmodus für neue Intervallkampagnen dokumentieren |
| Viele Rundenzahlvorlagen dominieren | Exakte gemeinsame Präfixdarstellung erst als separaten Folgeplan untersuchen; keine Rundenzahlen still streichen |
| Passagiergruppen/Kandidaten dominieren | Sicheres zeitliches Pruning vor Variablenbau und äquivalente Aggregation prüfen; unterschiedliche Freigaben nicht ungeprüft zusammenlegen |
| Größerer Katalog dominiert | Katalog als experimentellen Faktor behandeln; dessen Verkleinerung ist eine Suchraumbeschränkung |
| Modell passt, Suche bleibt ohne Fortschritt | Kein pauschaler Langlauf; Konfliktsuche, Seeds, Presolve und Schranken getrennt auswerten |
| Mehr Kabinen, weniger Vorlagen und ähnlicher Aufwand | Längere Strecken nicht wegen K allein ausschließen |

Empfehlung „handhabbar“ verlangt vollständig gebauten Fall innerhalb der
Limits sowie einen unabhängig gültigen Plan im Suchbudget. Ein unveränderter
Hint erfüllt nur die Rückfallprüfung, keinen Nachweis hilfreicher nativer Suche.
Nach fünf Minuten fehlender Fortschritt belegt nur dieses Budget. Mit nur zwei
Seeds werden Skalierungsbefunde berichtet, keine robuste allgemeine Überlegenheit.

Labelled Arc-Flow bleibt in kleinen Fixed-Start-No-Wait-Fällen: bei neuen Längen
zuerst K und Horizont kontrolliert halten, Netzgrößen aufnehmen und nur passende
Fälle lösen. Gleiche Kabinenzahl bedeutet nicht gleiche Modellgröße. All-Stop
erhält eine getrennte Messung der Phasenauswertung und Integer-Passagierzuordnung.

## 9. Quellen und Nachweisumfang

- [OR-Tools: Job Shop / Intervalle und NoOverlap](https://developers.google.com/optimization/scheduling/job_shop)
  beschreibt den nativen Scheduling-Baustein. Unsere optionalen affinen Intervalle,
  Zustandsressourcen und Fahrgastkopplung sind die projektspezifische Umsetzung.
- Der aktuelle `cp_model.py`-Builder verwendet
  `new_optional_fixed_size_interval_var` und `add_no_overlap`;
  `preparation.py` liefert die relative vollständige Schutzgeometrie.
- [Bisherige Linienplanung](reservoir_line_dispatch_models_20260912.md),
  [Befunde](../findings/reservoir_line_dispatch_pilot_20260912.md),
  [All-Stop-Vertrag](../reference/all_stop_no_wait_capacity_baseline.md).

Die Literatur erklärt die Darstellung, garantiert aber keine günstige Laufzeit
unserer Instanzen. Der neue Plan liefert eine konkrete exakte Vorbereitungskorrektur
und eine Messentscheidung; kein Waiting-, Reservoir-Wiedereinsatz- oder neuer
Suchalgorithmus wird damit als implementiert ausgegeben.
