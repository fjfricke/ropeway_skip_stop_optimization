# NSGA-II für evolutionäre Reservoir-Linienplanung

## Fragestellung

Der Vergleich untersucht, ob eine etablierte Pareto-Auswahl transportstarke, zunächst kollidierende Musterfamilien besser erhält und zu ausführbaren Fahrplänen entwickelt als die bisherige GA-Auswahl. Maßgeblich ist die Entwicklung über die Zeit: Populationen, Kabinenzahlen, Muster, Dispatchabstände, Konflikte und gültige Bedienung. Ein früher All-Stop-Sieg ist kein Abbruchkriterium. Eine hohe optimistische Bedienung eines kollidierenden Plans ist kein Erfolg der Fahrplansuche.

## Umsetzung

Zusätzliche Engine `nsga2` im bestehenden Modul `reservoir_lines/evolution`, bestehender Standard weiterhin `ga`. `pymoo==0.6.1.6` stellt NSGA-II einschließlich Elternauswahl, nichtdominierter Sortierung und Crowding-Auswahl. Die selbst festgelegten Populationsquoten und die 25-%-Explorations-Elternauswahl sind ausschließlich im bisherigen GA aktiv.

Kodierung, Initialsampler, No-Wait-Decoder, Duplikaterkennung und gekoppelte Sequenzoperatoren bleiben gemeinsam. `mixed_global` verwendet 50 % lokale, 30 % Block- und 20 % globale Änderungen. Keine automatische Verstärkung globaler Änderungen bei Stagnation. Kein Timing-Reparatursolver und keine neue physikalische Einschränkung.

### Suchziele

NSGA-II minimiert drei getrennte Größen:

1. Nicht zugeordnete Personen in der jeweiligen ganzzahligen Passagierbewertung.
2. Anzahl der festgestellten Ressourcen-/Zustandskonflikte zwischen Kabinen.
3. Summe ihrer paarweisen Überlappungsdauern, für die Suchbewertung in Sekunden.

Bei einer gültigen Bewegung ist Ziel 1 die unabhängig bestätigte Nichtbedienung, Ziele 2/3 sind null. Bei Kollisionen wird derselbe kleine ganzzahlige Passagier-IP auf den festen Trajektorien gelöst, wobei nur die gegenseitige Bewegungsverträglichkeit der Kabinen entfällt. Gemeinsame Nachfrage, ganzzahlige Ride-Mengen, Freigaben, Bedienungshorizont und Abschnittskapazitäten bleiben erhalten.

Die Einzelkabinen samt Zuordnung werden unabhängig validiert; die Nachfrage wird zusätzlich über alle Kabinen geprüft. Ungültige Einzeltrajektorien, beispielsweise falsche Rückkehr oder Selbstkonflikte, bleiben harte Ausschlussgründe. Konflikte zwischen Kabinen werden **nicht zusätzlich als harte pymoo-Constraints** gesetzt: Sonst würde dessen Feasibility-first-Auswahl den beabsichtigten Kompromiss wieder aufheben.

Bei Timeout ist der Suchwert die tatsächlich gefundene ganzzahlige Zuordnung, nicht der native obere Bound. Er kann das optimale Potenzial unterschätzen. Native Passagierschranke und Optimalitätsstatus werden separat gespeichert. Daraus entsteht keine globale Schranke für die äußere Suche.

### Datentrennung und Abbruch

`MovementEvaluation.plan` enthält weiterhin nur gültige Bewegungen. Ein kollidierender Zeitplan steht getrennt in `relaxed_timetable`. `PassengerPotential` enthält keine exportierbare Fahrplanlösung und wird nie als `PassengerEvaluation` ausgegeben. Nur `passengers` kann den gültigen Incumbent aktualisieren.

Jede gültige Verbesserung schreibt sofort einen unabhängig geprüften Checkpoint. Auswertungen prüfen die Suchdeadline auch innerhalb einer pymoo-Generation. Das verbleibende Budget begrenzt den nächsten Passagier-Solveraufruf; der Prozesssupervisor begrenzt die gesamte Wandzeit inklusive Aufbau und Validierung.

## Testnachweise

54 Tests bestanden am 14.09.2026: neun neue NSGA-II-Tests plus bestehende Evolutions- und Linienmodelltests.

Neue Prüfungen:

- Kollidierende Bewegung erhält Potenzial, aber keine gültige Bedienung und keinen Incumbent.
- Derselbe Fall bleibt für den strengen Bewegungs-/Passagierprüfer unzulässig.
- Gemeinsame Nachfrage wird auch über kollidierende Kabinen nicht doppelt verbraucht.
- Auf gültiger Bewegung gleiche Passagierwerte zwischen strengem und relaxiertem Pfad.
- Falsche Einzelkabinen-Rückkehr und positives Waiting werden nicht relaxiert.
- Konflikte sind Suchziele; nicht darstellbare Einzeltrajektorien bleiben harte Constraints.
- Native Pareto-Auswahl erhält sowohl gültigen All-Stop als auch einen hypothetisch stärker transportierenden kollidierenden Kandidaten.
- Kleiner freier NSGA-II-Lauf ohne Seed findet selbst positive gültige Bedienung und speichert Populationen.
- Abgelaufene Deadline verhindert weitere Bewertungen einschließlich Cachezugriffen.
- Bei Timeout wird ein nativer Potenzial-Bound nicht als erreichte Zuordnung verwendet.

Zusätzlicher historischer Replay: R2-All-Stop K38 ergibt unverändert **2.496 bediente Personen**. Eine um eine Sekunde veränderte zweite Abfahrt ergibt 60 Konfliktzeugen und weiterhin 2.496 potenziell zugeordnete Personen, aber keinen gültigen Fahrplan. Die einzelne vollständige Bewertung dauerte im Funktionstest rund 0,07–0,08 Sekunden; dies ist keine verallgemeinerte Durchsatzmessung.

## Vergleichsläufe

R2, 3.074 Personen, historische Fünf-Stationen-Geometrie, aktueller gemeinsamer Reservoirport, No-Wait, maximal 50 Kabinen, 300 Sekunden Dispatchfenster, `relevant` mit 14 Mustern. Das historische Maximum gilt nur für diesen eingefrorenen Fall.

| Einstellung | Wert |
|---|---|
| Population / Nachkommen | 32 / 8 |
| Operatorprofil | mixed_global |
| Seeds | 0, 1, 2 |
| Initialisierung | je mit und ohne gemeinsamen All-Stop-Plan |
| Einzelbudget | 300 Sekunden einschließlich Aufbau und Abschluss |
| Passagierbudget | bis zwei Sekunden je Bewertung einschließlich Aufbau; Supervisor begrenzt Gesamtlauf |
| Speicher | höchstens 32 GiB Prozessbaum-RSS; bestehende Speicherdruckprüfung |
| Gleichzeitige Solverjobs | einer |
| Tatsächliche Parallelität | Decoder seriell, Passagier-IP ein Thread; Workerwunsch zwölf ist keine behauptete Zwölf-Kern-Suche |
| Neues Gesamtbudget | 31 Minuten; Wartezeit auf vorhandene Kampagne separat ausgewiesen |

Sechs NSGA-II-Läufe schließen an den bereits gestarteten, eingefrorenen GA-Vergleich an. Die Reihenfolge mit/ohne Seed alterniert zwischen Seeds. Bestehende GA-Läufe werden nicht verändert oder unterbrochen. Beide Kampagnen haben eigene eingefrorene Quellen; Hashes, Lockfile und tatsächliche Paketversionen werden gespeichert.

Dies ist ein Vergleich **der vollständigen Verfahren**, einschließlich zusätzlich erforderlicher Potenzialbewertungen. Weil der bisherige GA kollidierende Vorschläge ohne Passagier-IP bewertet, ist es keine reine Selektionsablation. Einen beobachteten Unterschied darf man daher nicht allein NSGA-II zuschreiben.

## Auswertung

Schnitte nach 30/60/120/180/300 Sekunden; zusätzlich fortlaufende Ereignisse:

- gültiger globaler Incumbent und Zeitpunkt letzter echter Verbesserung;
- gültige Bedienung je K sowie Muster und Dispatchzeiten;
- separat Potenzial und Konflikte kollidierender Vorschläge;
- tatsächlich überlebende Populationen einschließlich der drei Suchziele;
- gültiger Anteil und Anzahl der Auswertungen;
- Zeiten für Decoder, Aufbau, Passagiersuche und Validierung;
- offene Passagierbewertungen und abgelehnte Einzeltrajektorien.

Wichtig: Die letzte Verbesserung je K kann nach dem Plateau des globalen Incumbents liegen. Potenzialfronten und Konfliktfronten sind verschiedene Diagnosen; bessere Werte in einer davon beweisen keine Annäherung an Zulässigkeit. Das langfristige Interesse ist, ob transportstarke Familien Konflikte abbauen und schließlich gültig werden.

## Dateien und Reproduktion

- Einzelrunner: `benchmarks/run_reservoir_line_evolution.py --engine nsga2`.
- Vergleich: `benchmarks/run_reservoir_line_nsga2_comparison.py`.
- Aktueller Ausgabeordner: `benchmarks/output/reservoir_line_evolution_20260914/nsga2_seed_comparison_v1`.
- Je Lauf `events.jsonl`, `best.json`, `prepared.json`, `result.json` und Supervisionsdaten.
- Kampagnenweit `campaign.json`, fortlaufend aktualisierte `summary.json` und `report.md`.
- Forschungsbericht: `docs/research/reservoir_line_evolution_algorithm_review_20260914.md`.

## Literatur und Grenzen

[NSGA-II in pymoo](https://pymoo.org/algorithms/moo/nsga2.html) beschreibt nichtdominierte Sortierung, Crowding und Turnierauswahl. [Constraint Violation as Objective](https://pymoo.org/constraints/as_obj.html) dokumentiert die Behandlung von Verletzungen als zusätzliches Ziel und deren mögliche Nachteile. Das veröffentlichte Verfahren garantiert keinen praktischen Vorteil in dieser Seilbahninstanz und keine globale Gap-Schließung.

Der Pilot verändert weder den fachlichen Erfolgstest noch die geltenden Sicherheitsbedingungen: Ein veröffentlichter Fahrplan muss vollständig konfliktfrei sein. Nur der Suchprozess darf unzulässige Zwischenkandidaten erhalten.
