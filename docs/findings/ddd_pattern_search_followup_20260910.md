# Vollständige K39-Mustersuche mit kurzen Timing-Prüfungen

Abgeschlossen am 10.09.2026 nach 1791,7 Sekunden einschließlich unabhängiger Endprüfung.

## Ergebnis

Start: 1410 unbedient. Ende: **1402 unbedient, 1672 bedient**. Die einzige Verbesserung erfolgte nach 592,6 Sekunden Gesamtlaufzeit; danach knapp 20 Minuten ohne weitere Verbesserung. Die unabhängige EAN/Gurobi-Zuordnung bestätigt 1402 und ist für den festen Endfahrplan optimal (kein globaler Beweis).

191 Prüfungen über 190 unterschiedliche Muster: 5 FEASIBLE, 170 UNKNOWN, 16 INFEASIBLE. Drei veränderte Muster mit gültigen Fahrplänen; vier Musterzertifikate einschließlich Startmuster gespeichert. Median je Prüfung 10,04 Sekunden. Aufbau über alle Prüfungen insgesamt 10,02 Sekunden, Solverzeit 1767,73 Sekunden: Der Engpass liegt in der Lösung der inneren Modelle, nicht im Modellaufbau.

Bewertung: acht zusätzliche Passagiere gegenüber dem Start, aber kein Durchbruch. Rund 89 % der Prüfungen bleiben ungeklärt. Einfach längeres Laufen ist auf dieser Evidenz keine überzeugende nächste Maßnahme; vor einer weiteren Kampagne sind die ungelösten inneren Entscheidungen und gezieltere Nachbarschaften zu untersuchen.

## Protokoll

30 Minuten Gesamtbudget, K39 mit festen Balanced-Reference-Startpositionen, Nachfrage 3074, Exit-Waiting bis 1200 Sekunden in Mikrosekundenauflösung. Zwölf CP-SAT-Worker, Zufallsseed 0. Ausgangspunkt ist das validierte Zertifikat von `variant1_time_hint_seed0` aus dem Zeit-Hint-Test mit 1410 Unbedienten (1664 bedient).

Jedes neue Stop/Skip-Muster erhält zehn Sekunden Timing-/Passagieroptimierung. Nur eine Verbesserung der globalen Bestlösung löst bis zu 30 Sekunden zusätzliche Optimierung aus. UNKNOWN wird als ungeklärt protokolliert; längere UNKNOWN-Wiederholungen sind in diesem Lauf ausgeschaltet. Bereits gefundene Zertifikate desselben Musters liefern dessen Zeit-Hints bei der Nachoptimierung; ansonsten wird der aktuelle Suchfahrplan als Zeitvorschlag verwendet. Keine Zeiten werden dadurch fixiert.

Die bestehende VNS durchsucht ihre drei Nachbarschaften und kann aus einem Pool gültiger Muster neu ansetzen. Jedes ausgewertete Muster mit gültigem Incumbent erhält ein eigenes vollständiges Zertifikat. Bestlösungen werden zusätzlich sofort als gemeinsamer Checkpoint gesichert. Die Endlösung wird unabhängig mit EAN/Gurobi geprüft.

Die gemeinsame Formulierung stammt aus dem eingefrorenen Zeit-Hint-Experiment. Nur die VNS-/Benchmark-Erweiterungen werden darübergelegt; Hashes und Quellarchiv sind abgelegt. Die 15 bestehenden gezielten Mustersuchtests bestehen im Arbeitsstand, Ruff ebenfalls. Zusätzlich bestehen alle 13 relevanten Tests gegen die eingefrorene Laufzeitkopie; zwei Tests des dort nicht enthaltenen alten Berichtsmoduls sind von dieser zweiten Prüfung ausgeschlossen. Frühere Standardkonfigurationen bleiben erhalten.

## Bewertung nach Abschluss

Entscheidend sind Verbesserung gegenüber dem Startwert 1410, Zahl gültiger veränderter Muster, UNKNOWN-Anteil, Zeit pro Prüfung und Incumbent-Verlauf. K38 mit 315 Unbedienten ist zusätzlich die bessere Vergleichslösung, jedoch mit anderen festen Startpositionen und anderer Kabinenzahl. Ein Erfolg der Mustersuche wäre zunächst eine Verbesserung innerhalb K39. Lokale Mustergrenzen ergeben keinen globalen Optimalitätsbeweis.

## Artefakte

- [Supervisorlog](../../benchmarks/output/pattern_search_followup_20260910.log)
- [Protokoll](../../benchmarks/output/pattern_search_followup_20260910/protocol.json)
- [Laufereignisse](../../benchmarks/output/pattern_search_followup_20260910/run/events.jsonl)
- [Bestfahrplan](../../benchmarks/output/pattern_search_followup_20260910/run/incumbent.json)
- [Endergebnis, nach Abschluss](../../benchmarks/output/pattern_search_followup_20260910/run/result.json)
- Einzelne Muster und Zertifikate: `benchmarks/output/pattern_search_followup_20260910/run/patterns/`
- Runner: `benchmarks/run_pattern_search_followup.py`
