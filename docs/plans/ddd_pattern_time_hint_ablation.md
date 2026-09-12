# Kontrollierter Zeit-Hint-Test für feste K39-Muster

Stand: 10.09.2026. Implementiert, neun gezielte Tests bestanden, Kampagne gestartet.

## Fragestellung

Zwei geänderte K39-Muster lieferten beim alten 5-s-Screening zulässige Fahrpläne, beim späteren 300-s-Diagnoselauf dagegen UNKNOWN. Das waren keine kontrollierten Laufzeitvergleiche: Das Screening übergab Zeit-Hints aus dem aktuellen Fahrplan, die spätere Diagnose für geänderte Muster keine Hints. Wir prüfen diesen Unterschied ausdrücklich, bevor wir die Mustersuche bewerten.

## Versuchsaufbau

- Exakt dieselben zwei historischen Muster, feste Startpositionen, K=39, Nachfrage 3074, Exit-Waiting bis 1200 s mit Mikrosekundenauflösung.
- Je Muster zwei Solver-Seeds (0 und 1), jeweils mit und ohne Zeit-Hints: acht sequenzielle Läufe, je 300 s einschließlich Modellaufbau, zwölf CP-SAT-Worker. Rund 40 Minuten plus Vorbereitung und unabhängige Prüfung.
- Hint-Quelle: gespeicherter K39-Screening-Fahrplan mit 1418 unbedienten Personen. Dieser blieb während der beiden damaligen erfolgreichen Musteränderungen der aktuelle Zustand; deren schlechtere Lösungen wurden nicht übernommen.
- Nur Ereigniszeitvariablen erhalten optionale Startwerte. Keine Fixierung, kein übernommener Incumbent, keine Objective-Schranke, keine zusätzlichen Passagier- oder Routen-Hints.
- Methodenreihenfolge für Seed 1 umgekehrt. Für beide Methoden neue Läufe; alte Diagnosewerte ersetzen keine Kontrollmessung.
- Codebasis aus dem archivierten Diagnoselauf; nur Probe-Erweiterung, neuer Runner und zugehörige Tests werden darübergelegt. Laufzeitimporte kommen aus dieser eingefrorenen Kopie.

## Messungen und Korrektheit

Modellgröße, Aufbauzeit, erste native zulässige Lösung, sämtliche Incumbent- und Bound-Ereignisse, Endstatus und lokale Grenzen. Die Modell-Fingerprints nach Entfernen der Hint-Felder müssen pro Paar identisch sein; zusätzlich werden Muster-IDs und vollständige Domain-Manifeste verglichen. Jeder zurückgegebene Fahrplan wird gegen die Domäne und das feste Muster validiert, vollständig gespeichert und die Endzuordnung unabhängig mit EAN/Gurobi nachgerechnet.

Der Regressionstest prüft unter anderem, dass ein Hint eines besseren anderen Musters ein schlechteres Zielmuster nicht unzulässig abschneidet. Zertifikat-Callbacks werden ebenfalls geprüft. Alle neun Probe-Tests bestehen.

## Entscheidung nach Abschluss

1. Wiederholbar schnellere zulässige Lösungen mit Zeit-Hints: deren Übernahme in der Mustersuche beibehalten und neu gewonnene vollständige Musterzertifikate für passende Warmstarts nutzen. Danach erst die Suchleistung bewerten.
2. Gemischter Effekt: gezielte Startwert-/Seed-Strategie prüfen; zwei Seeds begründen noch keine allgemeine Aussage.
3. Auch mit Hints häufig UNKNOWN: feste Muster allein garantieren keinen schnellen Timing-Oracle. Keine breite VNS-Kampagne auf dieser unbelegten Annahme starten; verbleibende Konfliktentscheidungen und kleinere Nachbarschaften untersuchen.

Es handelt sich ausschließlich um lokale Musteroptimierung. Ein geschlossener Muster-Gap wäre kein globaler Optimalitätsbeweis für Skip-Stop.

## Dateien

- Runner: `benchmarks/run_pattern_hint_ablation.py`
- CP-SAT-Probe: `src/ropeway_skip_stop_optimization/optimization/ddd/pattern_oracle_probe.py`
- Tests: `tests/test_ddd_pattern_oracle_probe.py`
- Automatisch aktualisierte Tabelle: [Ergebnisse](../findings/ddd_pattern_time_hint_ablation_20260910.md)
- Eingaben, eingefrorener Code, Hashes und Einzelresultate: `benchmarks/output/pattern_time_hint_ablation_20260910/`
- Je Lauf: `config.json`, `domain.json`, `solver.log`, `events.jsonl`, `result.json`, `incumbent.json`, `certificates/`, gegebenenfalls `independent_assignment.json`, `completion.json`.
- Ausgangsdiagnose: [bisheriger CP/MIP-Vergleich](../findings/ddd_pattern_oracle_diagnostic_20260910.md)
