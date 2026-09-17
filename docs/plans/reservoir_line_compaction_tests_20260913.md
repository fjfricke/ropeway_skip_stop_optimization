# Plan: Linienmodell kompakter formulieren und einzeln vergleichen

Stand: 13.09.2026. **V0--V3 und die erste Build-/Suchkampagne sind umgesetzt.**
Dieses Dokument hält das vorab festgelegte Protokoll und die noch bedingten
Schritte V4 sowie K-/Längenskalierung fest. Messergebnisse stehen im verknüpften
[Ergebnisbericht](../findings/reservoir_line_compaction_results_20260913.md)
und können daraus nachvollziehbar in die Thesis übernommen werden.

## 1. Fragestellung und unveränderlicher Vertrag

Können wir gleiche zulässige Linienfahrpläne und ganzzahlige Passagierzuordnungen
mit weniger Modellkopien darstellen und dadurch schneller bessere Lösungen finden?

Ziel bleibt die bestehende ganzzahlige Maximierung
`(Kmax + 1) * served - used_fleet`: zuerst mehr bediente Personen, dann weniger
Kabinen. Bedienungs- und Flottenfortschritt werden getrennt ausgewertet.
Unverändert bleiben Musterkatalog, freie Musterauswahl je Kabine, Rundenzahlwahl,
Dispatchregeln, Single-Use-Reservoir, No-Wait, Mikrosekundenticks, Ressourcen-
und Zustandskollisionen sowie die kanonischen direkten Beförderungen.

Keine eigene Suche, keine neuen Objective-Cutoff-Schleifen, kein Waiting-Ausbau.
Historische Daten und die alten expliziten Profile bleiben erhalten. Der Plan
forderte ursprünglich keinen automatischen Standardwechsel; nach abgeschlossener
Auswertung und einer gesonderten Nutzerentscheidung wurde V2 am 13.09.2026 zum
Default des Linienmodells. Kleinere Modelle sind nicht automatisch schneller
oder beweisstärker.

## 2. Varianten und genaue Vergleichspaare

| Variante | Neue Darstellung | Vergleich für ihre Einzelwirkung |
|---|---|---|
| V0 | Bestehendes Intervallmodell einschließlich bisheriger Vorbereitung | Referenz |
| V1 | Intervallmodell ohne ungenutzte Templatepaar-Vorbereitung | V1 gegen V0 |
| V2 | V1 plus gemeinsame Rundenvorsätze und über Rundenzahlen geteilte Passagierentscheidungen | V2 gegen V1; praktisch auch gegen V0 |
| V3 | V2 plus gemeinsame Passagierentscheidungen über Haltemuster | V3 gegen V2 |
| V4 | V3 plus gemeinsame Ereigniskette statt vollständiger Ressourcenstruktur je Muster | V4 gegen V3; erst nach dessen Auswertung |

Diese Varianten bilden eine gestufte Ablation, kein vollständiges faktorielles
Experiment. Bei Wirkungen von V3/V4 immer den gemeinsamen Unterbau nennen.
Kumulierte Nachfrage statt einzelner Freigabegruppen bleibt außerhalb.

### V1: gezielte Vorbereitungskorrektur

`preparation.py` berechnet bislang auch bei `intervals` sämtliche Templatepaar-
Dispatchbereiche, obwohl `cp_model.py` sie dort nicht liest. Die im
[Intervallplan](reservoir_line_interval_scaling_20260913.md) beschriebene
encodingabhängige Vorbereitung implementieren. Nach Normalisierung muss das
eigentliche CP-Modell von V0/V1 identisch sein; neue Fingerprints/Statistiken
der Vorbereitung dürfen abweichen. Keine Constraintänderung in dieser Ablation.

### V2: gemeinsamen Rundenanfang nur einmal darstellen

Heute duplizieren Vorlagen für eine, zwei, drei usw. Runden dieselben früheren
Besuche und Beförderungen. Stattdessen pro Kabine/Muster eine Folge aktiver
Runden vorsehen; spätere Aktivität impliziert alle früheren Runden. Musterwahl
und Dispatch bestimmen weiterhin die Zeiten. Bei Muster p, nullbasiertem
Rundenindex r und Ereignisoffset tau gilt `t = dispatch + r*C_p + tau`.

Besuche und Passagiermengen gemeinsam speichern, unabhängig von der späteren
Rückkehr nach einer weiteren Runde. Es müssen exakt die alten erlaubten
Rundenzahl-/Dispatchkombinationen erhalten bleiben, einschließlich eventueller
Lücken durch Zeitgrenzen oder vorlageninterne Konflikte.

Der letzte Rückkehrknoten ist aktiv, auch wenn kein Folgebesuch mehr stattfindet.
Offene Beförderungen dürfen nicht beim Rückkehrentscheid verschwinden. Keine
doppelte Zustandsbelegung durch getrennte Kopien desselben Rundenübergangs.

### V3: Passagiere an tatsächliche Besuche koppeln

Mengen `q[k,g,i,j]` beziehen sich auf Kabine, Nachfragegruppe, Einstiegs- und
Ausstiegsbesuch. Das gewählte Muster bestimmt STOP-Präsenz und Ereigniszeiten;
die Menge wird nicht mehr für jede Musteralternative separat angelegt.

Positive Mengen erfordern aktive Besuche, STOP an beiden Enden, rechtzeitige
Freigabe/Ankunft und Abschnittskapazität. Jede direkte Beförderung bleibt auf
die bisherige kanonische Unterstützung beschränkt. Gemeinsame Variablen dürfen
keine Beförderung aus Teilen inkompatibler Muster zusammensetzen.

### V4: gemeinsame Ereignisse über Muster

Pro Kabine eine Besuchskette, deren STOP/SKIP-Wahlen durch ein einziges
wiederkehrendes Muster festgelegt bleiben. Native Ressourcenintervalle an
diese Ereignisse koppeln. Keine unabhängigen freien Zeiten je Besuch und keine
neue Freiheit, das Muster während des Einsatzes zu ändern. Weniger Intervalle
können mehr Hilfsvariablen und schwächere Propagation bedeuten; deshalb eigener Test.

## 3. Integration und Artefakte

Gemeinsame unveränderliche Vorbereitung, spezialisierte Formulierungsbuilder,
gemeinsamer Optimizer und Zertifikatsadapter statt kopierter Gesamtsolver.
Betroffene Stellen unter `src/ropeway_skip_stop_optimization/optimization/ddd/`:
`reservoir_lines/preparation.py`, `cp_model.py`, `passenger_model.py`, `config.py`,
`optimizer.py`, `certificate.py`; Runner `benchmarks/run_reservoir_lines.py`.

Variantenwahl explizit über eine neue Formulierungskonfiguration weiterreichen;
bestehendes `--variant intervals|dispatch_domains` bleibt die Ressourcenwahl.
Nicht unterstützte Kombinationen vor Modellbau ablehnen. Physikalische IDs und
historische Zertifikate erhalten; Modell-/Vorbereitungsfingerprint versionieren.

Für jede Kampagne einen neuen Ordner mit Manifest, Quellenhashes einschließlich
ungecommiteter Änderungen, Engineversion, Plattform, Parametern, Prüfnachweisen
und unveränderlichen Startcheckpointkopien anlegen. Keine Zugangsdaten speichern.

## 4. Gate G1: vollständig aufzählbare Fälle

Zwei bis vier Kabinen, ein bis drei Muster und ein bis drei Runden verwenden.
Für diese kleinen synthetischen Fälle bewusst endliche Dispatchdomänen wählen;
alle zulässigen Dispatch-/Muster-/Rundenzahlkombinationen unabhängig aufzählen.
Die Produktionsauflösung und großen Domänen werden dadurch nicht eingeschränkt.

Verglichen werden die **projizierten zulässigen Bewegungen und Beförderungen**,
nicht Hilfsvariablenbelegungen oder nur zufällig gleiche Optima. Auf sehr kleinen
Nachfragen alle Integer-Zuordnungen aufzählen; auf weiteren Fällen die Integer-
Passagieroptima bei jeder festen Bewegung exakt bestimmen.

| Pflichtfall | Erwarteter Nachweis |
|---|---|
| Eine statt drei aktive Runden | Inaktive Folgerunden erzeugen weder Belegung noch Service |
| Ziel erst in Runde zwei | Rückkehr nach Runde eins schließt diese Beförderung aus |
| Gleicher Ride in mehreren Mustern | Keine doppelte Bedienung oder Mustervermischung |
| Ursprung/Ziel vom Muster ausgelassen | Positive Menge ausgeschlossen |
| Volle Kabine, Aus-/Einstieg am selben Besuch | Freigewordene Kapazität korrekt wieder nutzbar |
| Überholen und zwei gekoppelte Ressourcen | Keine globale physische Reihenfolge eingeführt |
| Später beginnende Belegung einer früheren Bewegung | Vollständige Intervalle bleiben berücksichtigt |
| Berührung und Überlappung um einen Tick | Halb offene Schutzintervalle exakt erhalten |
| Rückkehr exakt am Ende/einen Tick zu spät | Endknoten und Deadline korrekt |
| Eintritt am Horizont, Schutz darüber hinaus | Kein Abschneiden der Schutzzeit |
| Freigabe exakt am Einstieg/einen Tick später | Gleichheit zulässig; spätere Freigabe ausgeschlossen |
| Ungenutzte Flotte und abgewählte Muster | Keine Phantomressourcen oder Phantompassagiere |
| Kanonischer Zielbesuch | Keine zusätzliche Passagierrunde und kein Umstieg |

G1 besteht nur bei übereinstimmenden Projektionen/Optima und bestandenem
unabhängigen Validator. Ein Gegenbeispiel wird gespeichert und vor Performance behoben.

## 5. Gate G2: historische Pläne und Hints

Mindestens einen teilweise bedienenden und den vollständig bedienenden R2-
Linienplan verwenden. Exakte Pfade/Fingerprints/Werte beim Einfrieren auflösen
und erneut unabhängig prüfen; Gesprächswerte nicht als Prüfresultate übernehmen.

1. Bewegung und Beförderungsmengen fixieren: alle Varianten akzeptieren den Plan.
2. Nur Bewegung fixieren: identisches ganzzahliges Passagieroptimum reproduzieren.
3. Nur Hints setzen: keine zusätzliche Fixierung oder Objective-Cutoff erzeugen.
   Auf einem kleinen Fall nachweisen, dass ein anderer gültiger Plan erreichbar bleibt.
4. Exportierte Pläne wieder mit ursprünglicher Domäne und unveränderten Prüfern
   validieren. Nicht darstellbare positive Mengen verursachen einen Fehler.

Checkpointübernahme wird getrennt von nativer Suche protokolliert. Ein U=0-Plan
prüft Vollbedienung und sekundäre Flottenoptimierung, aber keinen weiteren
Bedienungsfortschritt. Er ist deshalb nicht der einzige Performance-Seed.

## 6. Gate G3: Modellgröße ohne Suche

Zuerst unverändertes historisches R2 mit identischem Katalog, Nachfragegruppen,
Zeitvertrag und Kmax. Drei Build-only-Wiederholungen pro verfügbarer Variante,
Reihenfolge rotieren; neue Prozesse verwenden. Jeweils Median und Spannweite.

Erfassen: Domänen-/Kandidatenaufbau, Vorlagen, Paare, Modellbau, Hintaufbau,
Variablen nach Familie, Constraints, Intervallobjekte, Protobuf-Größe und
Prozessbaum-Peak-RSS. Python-Vorbereitung und native Modellgröße unterscheiden.

V2 prüft insbesondere die strukturelle Prognose ungefähr 72.500 → 17.350
Ressourcen-/Zustandsintervalle auf der historischen Referenzvorbereitung.
Die zweite Zahl ist eine Abschätzung aus längsten Vorlagen, **kein Messergebnis**;
zusätzliche Präsenzkopplungen und Endknotenbehandlung separat zählen.

## 7. Gate G4: Suchvergleich und Zeitverläufe

Zwei Startbedingungen je Fall:

- **Hint:** identischer geprüfter Plan mit U>0, sodass Verbesserung möglich ist.
- **Ohne Hint:** keine Fahrplanstartinformation oder externe Zielfunktionsgrenze.

V0, V2 und V3 zunächst je Bedingung mit Seeds 0 und 1 vergleichen. V1 erhält
keine vollständige separate Suchkampagne, wenn G1 die Identität des nativen
Modells bestätigt; seine Aufbauzeit geht trotzdem in den Gesamtvergleich ein.
Ist V3 noch nicht freigegeben, bleiben dessen Versuche ausstehend.

Pro Lauf 300 s **Gesamtbudget einschließlich Aufbau und Validierung**. Zusätzlich
Suchzeit ab Solveraufruf berichten. Zwölf Worker, identisches explizites
Speicherlimit (vorgeschlagen 24 GiB nach Hostprüfung), Presolve und sonstige
Parameter je Vergleich identisch. Keine parallelen Solverjobs. Reihenfolge der
Varianten über Seeds/Startbedingungen rotieren; Manifest vor dem Lauf einfrieren.

### Erster Budgetvorschlag

| Abschnitt | Budget |
|---|---:|
| Einfrieren und Build-only-Messungen | höchstens 25 min |
| V0/V2/V3 × zwei Startbedingungen × zwei Seeds × 300 s | höchstens 60 min |
| Validierung verbleibender Artefakte und Auswertung | höchstens 20 min |
| Gesamte erste Kampagne | höchstens 105 min |

Implementierung/Korrektheitstests liegen außerhalb. Keine Übertragung ausgefallener
Läufe in zusätzliche Suche. Übergeordnete Wandzeit-/RSS-Kontrolle einschließlich
Suspend und Kindprozessen; bei Abbruch letzten gesicherten Stand ausweisen.

Die frühere 75-min-Kampagne im Intervallplan wird **nicht automatisch zusätzlich**
gestartet. Sie bleibt eine separate spätere Skalierungsstufe. Dieser Plan erweitert
deren Formulierungsvergleich und hat dafür eigene vorgeschlagene Budgets.

### Protokoll pro Lauf

- Erstlösung, Hintübernahme, erste echte Verbesserung gegenüber Hint und
  weitere Verbesserungen mit Zeit, S, U, genutzter Flotte und Zertifikatspfad.
- Werte nach 30/60/180/300 s Gesamtzeit; „kein Incumbent“ explizit, nicht U=D
  oder ein Referenzwert als native Lösung eintragen.
- Solver-Rohwert, native Schranke und korrekt umgerechnete Bedienungsschranke.
  `F=(Kmax+1)S-Kused`: eine obere Schranke B auf F liefert konservativ
  `S_UB <= min(D, floor((B+Kmax)/(Kmax+1)))`, mit nach außen sicherer
  Zahlenbehandlung. Gegen kleine gelöste Fälle prüfen; `U_LB=D-S_UB`.
- Letzter Bedienungsfortschritt, letzter Flottenfortschritt und letzte
  Schrankenverbesserung getrennt. Zeit ohne Fortschritt ist nur ein beobachtetes
  Plateau im jeweiligen Budget, kein Nachweis dauerhaften Stillstands.
- Native Zwischenlösungen unveränderlich sichern und vor Aufnahme in validierte
  Kurven prüfen; erste Suchzeit und spätere Validierungszeit getrennt speichern.

## 8. Bestätigung und Skalierung nach dem Screening

Beste korrekte Variante zunächst gegen V0 mit 15 min Gesamtbudget, drei
zusätzlichen gemeinsamen Seeds 2/3/4 und derselben Hintbedingung bestätigen.
Das sind höchstens 90 min Laufbudget zuzüglich vorher festgelegter Reserve;
separat festzulegende Kampagne, kein automatischer Langlauf. Falls kein Seed
eine Verbesserung zeigt, nicht allein wegen kleinerer Modelle verlängern.

Skalierung separat durchführen:

1. **K-Skalierung:** gleiche Geometrie, Zeitachse, Nachfrage, Muster; nur Kmax
   verändern. Dadurch ändert sich auch der erlaubte Flottenraum; Varianten
   immer nur innerhalb derselben Zeile direkt vergleichen.
2. **Längenskalierung:** gleiche Stationszahl/Stationsphysik, 300/800/1.200 m;
   Flotte aus der jeweiligen All-Stop-Sättigung ableiten. Kontrollierte Zeitachse
   und tatsächlich benötigten Vorlauf getrennt betrachten, wie im Intervallplan.
3. Erst danach größerer Musterkatalog oder feinere Freigaben, jeweils einzeln.

Je Stufe zuerst Build-only; problematische Fälle als Aufbau-/Speicherbefund
dokumentieren. Keine stille Reduktion der Flotte, Runden, Muster oder Zeitticks.
V4 wird nur bei fortbestehendem Ressourcen-Duplikationsengpass implementiert
und durch G1–G4 geführt, nicht zugleich mit neuer Physik getestet.

## 9. Entscheidungskriterien

| Befund | Entscheidung |
|---|---|
| Unterschiedliche zulässige Lösung/Optimum ohne beabsichtigte Domänenänderung | Korrektheitsfehler, Variante ausgeschlossen |
| Weniger Speicher/Aufbauzeit, gleiche Suche | Struktureller Gewinn; kein behaupteter Suchspeedup |
| Kleinere Darstellung, schlechtere Suche | Experimentelle Alternative behalten; Standard nicht wechseln |
| Schnellere gültige Incumbents oder bessere Endbedienung reproduziert | Empfehlung für Lösungssuche |
| Engere vergleichbare Schranke ohne schlechteren Incumbent | Separate Empfehlung für Beweisleistung innerhalb der Liniendomäne |

Als vorab festgelegter praktischer Effekt gelten bei Bestätigung in mindestens
zwei von drei zusätzlichen Seeds: mindestens zehn zusätzliche bediente Personen
am Laufende oder mindestens 20 % kürzere Zeit bis zur jeweiligen V0-Endbedienung,
ohne schlechtere Endbedienung. Alle drei Läufe und Gegenbefunde berichten.
Bei U=0 Flottenreduktion separat bewerten; kein allgemeiner Signifikanznachweis
aus drei Seeds. Nicht erreichte Zielwerte sind zensierte Zeiten, keine fiktiven
Laufzeiten von genau 300/900 s. Kriterien betreffen dieselbe physikalische Instanz.

## 10. Ergebnissicherung für die Thesis

Der [Ergebnisbericht](../findings/reservoir_line_compaction_results_20260913.md)
ist die zentrale lesbare Ergebnisablage. Rohdaten bleiben in versionierten
Kampagnenordnern. Nach jeder abgeschlossenen Stufe Bericht und Artefaktlinks
aktualisieren; fehlgeschlagene Varianten ebenfalls aufnehmen.

Pflichtartefakte: `manifest.json`, `correctness.json`, `build_metrics.csv`,
`run_summary.csv`, `progress.jsonl`, Logs und unabhängig validierte Checkpoints.
Die Namen sind vorgeschlagene Ausgabeschnittstellen, noch keine vorhandenen Dateien.
Spätere Tabellen und Abbildungen werden aus diesen Daten reproduzierbar erzeugt.

Gültige Aussagen unterscheiden: Implementierungsaufwand, Modellgrößenreduktion,
Suchfortschritt, Optimalität im eingeschränkten Linienmodell und betrieblicher
Vorteil gegenüber der gesondert geprüften phasenoptimierten All-Stop-Referenz.
Ein Vergleich zweier Kodierungen beweist für sich keinen neuen Skip-Stop-Vorteil.
