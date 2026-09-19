# Abschluss: geometrische OIP-Mischungsreihe

19.09.2026. Kampagne `oip_fixed_mixes_geometric_120_20260918`, Status `complete`. Alle 15 Fälle wurden abgearbeitet; kein weiterer Solverlauf ist vorgesehen.

## Vertrag

T5R/G500, K62, No-Wait, freie Anfangspositionen, feste Typzahlen; geometrische Headways 1053/11667 ms. Nachfragefenster 1464 s, Bedienung bis 2364 s, Betrieb bis 2664 s. Served ist das einzige Ziel, Journey Time wird einschließlich Unserved-Strafe gemessen. Keine Hints. Jeder Versuch höchstens 300 s einschließlich Vorbereitung und Abschluss.

Regelmäßige All-Stop-Referenzen bei der tatsächlichen Versuchsnachfrage: F2 1902/2266, F3 4549/5430, F0 6616/7606 bedient. Die bewiesenen CAL-O-Vollbedienungsgrenzen sind davon zu unterscheiden: 1888, 4525, 6338.

## Vollständige Matrix

Die Schranke bezeichnet die maximale noch mögliche Bedienung im jeweiligen festen Typmodell: Nachfrage minus native untere Unserved-Schranke. Striche bedeuten fehlende geprüfte Lösungen, nicht Bedienung null. Ein UNKNOWN kann trotzdem eine gültige Schranke besitzen.

| Familie | All-Stop / Typ 1 / Typ 2 | Bestätigt bedient | Obere Bedienungsschranke | Abschluss |
|---|---|---:|---:|---|
| F2 | 62/0/0 | 1902 | 1980 | FEASIBLE |
| F2 | 46/8/8 | — | 2140 | UNKNOWN |
| F2 | 30/16/16 | — | 2266 | UNKNOWN |
| F2 | 16/23/23 | — | 2266 | UNKNOWN |
| F2 | 0/31/31 | 2266 | 2266 | OPTIMAL |
| F3 | 62/0/0 | 4542 | 4919 | Zulässig, geprüftes Checkpoint nach Zeitlimit |
| F3 | 46/8/8 | — | 5280 | UNKNOWN |
| F3 | 30/16/16 | — | 5430 | UNKNOWN |
| F3 | 16/23/23 | — | 5430 | UNKNOWN |
| F3 | 0/31/31 | 5430 | 5430 | OPTIMAL |
| F0 | 62/0/0 | 6636 | 6901 | Zulässig, geprüftes Checkpoint nach Zeitlimit |
| F0 | 46/8/8 | — | 7311 | UNKNOWN |
| F0 | 30/16/16 | — | 7606 | UNKNOWN |
| F0 | 16/23/23 | — | 6723 | UNKNOWN |
| F0 | 0/31/31 | — | 6042 | UNKNOWN; Referenz durch Schranke nicht schlagbar |

F2-Typen: BD und CE. F0/F3-Typen: alternierendes STOP/SKIP mit beiden Phasen, über Umlaufgrenzen fortgesetzt.

## Schlussfolgerungen und Beweisumfang

- F2: BD/CE 31/31 bedient alle 2266 Personen. Der All-Stop-Kontrolllauf mit freien Positionen hat eine obere Bedienungsschranke von 1980. Damit übertrifft die bestätigte Lösung sogar diese Schranke um 286 Personen.
- F3: Alternierend 31/31 bedient alle 5430 Personen. Die obere Bedienungsschranke des All-Stop-Kontrolllaufs mit freien Positionen beträgt 4919. Die bestätigte Lösung liegt 511 Personen darüber.
- Damit ist ein Bedienungsvorteil gegenüber All-Stop auch bei freier Positionierung für diese beiden konkreten, identisch definierten Fälle belegt. Ein All-Stop-Optimum muss dafür nicht exakt bekannt sein. Beide vollständig bedienenden Skip-Stop-Lösungen sind für Served optimal; Journey-Time-Optimalität folgt daraus nicht.
- F0: Die beste geprüfte Lösung bedient 6636 Personen mit All-Stop, 20 mehr als die regelmäßige Referenz. Rein alternierend erlaubt die Schranke höchstens 6042, weniger als die Referenz 6616. Die Zwischenmischungen bleiben ungeklärt; ein genereller Ausschluss eines Skip-Stop-Vorteils für F0 wäre nicht gerechtfertigt.
- Insgesamt liegen fünf geprüfte Fahrpläne vor (zwei davon mit optimaler Vollbedienung). Zehn Fälle endeten UNKNOWN; bei einem davon erlaubt die Schranke den Vergleichsabbruch. UNKNOWN ist kein Bewegungsunzulässigkeitsbeweis.

## Unterbrechungen und Vergleichbarkeit

Die ersten F3-Versuche 62/0/0 und 46/8/8 wurden unterbrochen. Auf ausdrücklichen Auftrag wurden genau diese beiden mit unverändertem Fünf-Minuten-Budget als `attempt_2` wiederholt. Die übrigen 13 Fälle wurden nicht wiederholt. Alle ursprünglichen Dateien bleiben erhalten.

Während der Reihe wurde die Ergebnissicherung korrigiert. Vollständige Kandidaten werden exportiert und im Hintergrund unabhängig geprüft; ein atomar gespeicherter geprüfter Checkpoint kann einen harten Zeitabbruch überleben. Modell und Zielfunktion bleiben gleich, zusätzlicher Export-/Prüfaufwand schränkt reine Laufzeitvergleiche zwischen den Codeständen ein. Quellhashwechsel und autorisierte Ersatzversuche stehen im Manifest.

Die früher angezeigten 4550 Personen im unterbrochenen F3-All-Stop-Lauf besitzen kein gesichertes Zertifikat und werden nicht gewertet. Der geprüfte Ersatzversuch liefert 4542; die regelmäßige Referenz mit 4549 bleibt der bessere bekannte All-Stop-Fahrplan. Eine freie Positionierung garantiert bei begrenzter Suche ohne Hint nicht, dass der Solver diese bekannte Lösung wiederfindet.

## Noch offen für die Thesis

Der Rechenteil der vereinbarten No-Wait-Reihe ist abgeschlossen. Die Ergebnisdarstellung, Tabellen/Grafiken und Diskussion müssen noch in die Thesis übernommen werden. Keine längeren Läufe oder Waiting-Reihe sind für diesen Abschluss erforderlich oder automatisch autorisiert. Ergebnisse gelten für diese festen Mischungen, Nachfragen und den endlichen Betriebshorizont. Ein einzelner Seed und kurze Budgets erlauben keine allgemeine Aussage über Solverleistung.

## Herkunft

- Kampagnenmanifest: `results/oip_fixed_mixes_geometric_120_20260918/campaign.json`
- SHA256 zum Abschluss: `3ce24c5e7d7e3f26bf504ed5bf92f0aa3826a8635c265378547e63044d0e12ea`
- Ergebnisdateien: pro Zeile der letzte Versuch unter `trials/<trial_id>/attempt_<n>/result.json`; vollständige Zertifikate bei allen fünf bestätigten Fahrplänen.
- [Sicherungskorrektur](oip_incumbent_persistence_fix_20260919.md)
- [Vertrag und Modellabnahme](oip_geometric_preparation_20260918.md)
