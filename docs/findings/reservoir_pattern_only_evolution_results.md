# Pattern-only evolution: results

## Status

Nach einer missverständlichen Diskussion wurde der Vertrag ausdrücklich bestätigt: Reihenfolge beim Dispatch durch Evolution; Überholen unterwegs zulässig. Der historische K38-Plan enthält einen konkreten Zeugen: Kabine 0 startet bei Tick 1.267.872 und Kabine 3 bei 19.710.183; beim Besuch 1 kommt Kabine 3 bei 53.710.183 vor Kabine 0 bei 55.449.690 an. Beide Builder (`intervals`, `dispatch_domains`) reproduzieren die fixierte Bewegung mit 2.936 bedienten Personen und Status OPTIMAL. Protokoll: `benchmarks/output/reservoir_line_evolution_20260914/pattern_only_overtaking_regression.json`.

Vier bereits vorselektierte Kontrollfolgen erlauben keine Aussage über den zulässigen Anteil zufälliger Folgen. Die frühere gegenteilige Einschätzung im Chat wird zurückgenommen. Der wiederholte Baselinelauf wurde auf Nutzerwunsch abgebrochen.

Die Implementierung und kleinen Korrektheitsprüfungen sind abgeschlossen. Ein erster R2-Replay derselben gemischten K38-Musterfolge wurde ausgeführt; das vollständige Screening und die Vergleichskampagne stehen noch aus.

## Bereits bestätigte Eigenschaften

- Musterreihenfolge gehört zur Genomidentität; das Genom enthält keine Zeitgene.
- Alle Operatoren erhalten die feste Flotte.
- Beide Untermodelle erzeugen auf dem kleinen vollständig prüfbaren Fall einen unabhängig gültigen No-Wait-Fahrplan und dasselbe Bedienungsoptimum.
- Die feste Musterfolge entfernt fremde Templatealternativen vor dem Modellbau.
- `UNKNOWN` und `INFEASIBLE` bleiben getrennt; Pattern-only verwendet keine konstruierte Konfliktmetrik.

## Vorläufiger R2-Replay

Die letzte Musterfolge des vorherigen 30-Minuten-Laufs bestand aus 10× `stop_A_B_D`, 14× `stop_A_C_E`, 5× `stop_B_C_E` und 9× `stop_B_D_E`. Der frühere Lauf bediente mit seinen evolutionär gefundenen Dispatchzeiten 2.936 Personen.

Die neue Dispatch-Domain-Darstellung löste genau diese Folge ohne Zeit-Hint wie folgt:

| Untermodell | Bestätigt bedient | Status | Gesamte Untermodellauswertung | Variablen | Constraints |
|---|---:|---|---:|---:|---:|
| Timing, danach Passagier-IP | 2.936 | Timing optimal; Passagiere optimal | 0,75 s | 456 | 3.494 |
| Gemeinsame Bedienungsoptimierung | 2.952 | optimal für diese Musterfolge | 3,77 s | 6.404 | 22.514 |

Das ist ein relevanter Architekturtest: Die Evolution muss für diese Folge keine Dispatchzeiten mehr finden, und die gemeinsame Variante gewinnt weitere 16 Personen allein durch die Zeitwahl. Das Ergebnis ist kein globaler Bound über Musterfolgen.

Zum Größenvergleich besitzt der nicht spezialisierte R2/K38-Builder mit allen 14 Mustern je Slot 95.646 Variablen, 339.470 Constraints und 23,2 MB serialisiertes Modell. Die spezialisierte gemeinsame Variante besitzt 6.404 Variablen, 22.514 Constraints und rund 1,5 MB Modell; das Timingmodell besitzt 456 Variablen. Die Reduktion entsteht durch Musterfixierung vor dem Modellbau und lazy berechnete Dispatchdifferenzdomänen.

## Ausstehende R2-Messwerte

Zu berichten sind Kandidaten pro Minute, Statusanteile, Modellbau- und Suchzeit, Zeit zur ersten gültigen Bewegung, Bedienungsverbesserungen, Dispatchzeiten, Modellgrößen und der Vergleich mit der Evolution einschließlich Zeitgenen.
