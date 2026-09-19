# OIP-Muster- und Flottenscreening: zusammenfassende Ergebnisse

_Stand: 18. September 2026_

## Versuchsvertrag

Alle hier verglichenen Läufe verwenden T5R/G500, Architektur B, P0-Nachfrage, zwei All-Stop-Umläufe Nachfragefenster, 900 s Abschlusszeit und 300 s geprüfte Weiterfahrt. Die OIP-Läufe verwenden exakt K aktive Kabinen, frei optimierte Anfangspositionen, No-Wait, feste Kabinenmuster und eine gemeinsame Optimierung von Bewegung und ganzzahliger Passagierzuordnung. Das Ziel ist lexikografisch: zuerst minimale Nichtbedienung, danach minimale Journey Time einschließlich Unserved-Strafe.

Die damalige Auswertung stellte daneben Werte aus der regelmäßigen CAL-O-Kalibrierung. Erst die nachträgliche Vertragsprüfung zeigte, dass CAL-O ein 45-Minuten-Nachfragefenster verwendet, während diese OIP-Läufe nur zwei All-Stop-Umläufe modellieren. Die Zahlen bleiben zur Nachvollziehbarkeit erhalten, sind aber keine Vergleichsreferenz für das kurze OIP-Modell.

## Historische CAL-O-Werte (nicht direkt vergleichbar)

| Nachfragefamilie | K=40 | K=50 | K=62 |
|---|---:|---:|---:|
| F0 | 6.323 | 7.923 | 9.785 |
| F2 | 1.882 | 2.356 | 2.918 |
| F3 | 4.630 | 5.795 | 7.153 |

Diese Werte stammen aus CAL-O-Läufen mit dem langen 45-Minuten-Nachfragefenster. Die OIP-Screenings verwenden dagegen zwei All-Stop-Umläufe, 900 s Abschluss und 300 s Weiterfahrt. Sie sind deshalb keine Baselines für die kurzen OIP-Läufe. Die frühere direkte Gegenüberstellung und die daraus abgeleitete Aussage, die getesteten Muster könnten All-Stop nicht schlagen, werden zurückgenommen.

## Beste gefundene feste Muster im Vergleich

Die Spalte `Historisches CAL-O` dient nur der Dokumentation und darf wegen des unterschiedlichen Betriebsvertrags nicht als Differenz zum kurzen OIP-Lauf interpretiert werden. `OIP-AS` ist ein zeitlimitierter Incumbent im kurzen Vertrag.

| Familie | Last | Nachfrage | K | Historisches CAL-O | OIP-AS | Bestes Nicht-AS-Muster | Bedient | rechnerisches Δ (nicht vergleichbar) | Journey Time |
|---|---:|---:|---:|---:|---:|---|---:|---:|---:|
| F2 | 100 % | 2.918 | 40 | 1.882 | 1.250 | F2 direct | 1.600 | -282 | 2.857.812,28 |
| F2 | 100 % | 2.918 | 50 | 2.356 | 1.550 | Direkt | 2.000 | -356 | 2.463.708,32 |
| F2 | 100 % | 2.918 | 62 | 2.918 | 1.910 | — | — | — | — |
| F2 | 110 % | 3.210 | 40 | 1.882 | 1.250 | F2 direct | 1.600 | -282 | 3.335.392,36 |
| F2 | 110 % | 3.210 | 50 | 2.356 | 1.550 | F2 direct | 2.000 | -356 | 2.938.218,32 |
| F2 | 110 % | 3.210 | 62 | 2.918 | 1.910 | — | — | — | — |
| F3 | 100 % | 7.153 | 40 | 4.630 | 3.020 | Rotating express three-stop | 3.000 | -1.630 | 8.244.439,30 |
| F3 | 100 % | 7.153 | 50 | 5.795 | 3.750 | Rotating express three-stop | 3.670 | -2.125 | 7.489.449,01 |
| F3 | 100 % | 7.153 | 62 | 7.153 | 4.580 | — | — | — | — |
| F3 | 110 % | 7.869 | 40 | 4.630 | 3.006 | Rotating express three-stop | 3.000 | -1.630 | 9.408.403,30 |
| F3 | 110 % | 7.869 | 50 | 5.795 | 3.740 | Rotating express three-stop | 3.700 | -2.095 | 8.607.545,79 |
| F3 | 110 % | 7.869 | 62 | 7.153 | 4.586 | — | — | — | — |
| F0 | 100 % | 9.785 | 40 | 6.323 | 5.531 | Four-stop + All-Stop | 5.618 | -705 | 9.543.731,93 |
| F0 | 100 % | 9.785 | 50 | 7.923 | 6.299 | Rotating four-stop | 6.467 | -1.456 | 8.555.607,38 |
| F0 | 100 % | 9.785 | 62 | 9.785 | 7.221 | — | — | — | — |
| F0 | 110 % | 10.764 | 40 | 6.323 | 5.802 | Four-stop + All-Stop | 5.747 | -576 | 11.066.073,66 |
| F0 | 110 % | 10.764 | 50 | 7.923 | 6.541 | Rotating four-stop | 6.607 | -1.316 | 10.100.807,33 |
| F0 | 110 % | 10.764 | 62 | 9.785 | 7.466 | — | — | — | — |

### Fehlender F2-Vergleich

Der ursprüngliche 100%-Screeninglauf `F2/direct/K50` endete ohne Incumbent. Für den fehlenden Vergleich wurde deshalb die unabhängig gültige K50-Direktbewegung aus dem 110%-Lauf auf die 100%-Domäne übertragen, nach Änderung der reinen Szenario-ID erneut physikalisch validiert und die Passagierzuordnung neu optimiert. Die Bewegung besteht aus 25 Kabinen `{S1,S3}` und 25 Kabinen `{S2,S4}`. Die feste Passagier-IP ist optimal und bedient **2.000 von 2.918 Personen**; Journey Time: **2.463.708,32 Personen-s**.

Dieser Wert schlägt den schwachen OIP-All-Stop-Incumbent von 1.550 Personen, bleibt aber 356 Personen unter der bewiesenen regelmäßigen K50-All-Stop-Kapazität von 2.356. Er ist ein fairer Vergleich derselben physischen Bewegung unter anderer Nachfrage, aber kein neuer gemeinsamer Bewegungssuchlauf.

## Verlauf der 300-s-Verfeinerung

- 43 von 43 ausgewählten Screening-Incumbents wurden vollständig nachgerechnet.
- 38 Läufe verbesserten die bestätigte Bedienung; 5 blieben unverändert.
- Alle 43 Nachläufe lieferten einen validierten Incumbent. Ein Zeitlimit oder ein verbleibender Gap ist kein Optimalitätsbeweis über andere Anfangspositionen derselben Musterbelegung.
- Die starken Verbesserungen einzelner Skip-Stop-Muster gegenüber den OIP-All-Stop-Incumbents zeigen vor allem, dass der freie OIP-Suchraum in 300 s schwer zu durchsuchen ist.

## Korrigierter Befund

Die festen Muster und die kurzen OIP-All-Stop-Incumbents dürfen verglichen werden, sofern Nachfrage, Fenster, Nachlauf und Geometrie identisch sind. Die historischen CAL-O-Werte beantworten eine andere Frage. Ob eine Typmischung All-Stop im kurzen OIP-Vertrag schlägt, bleibt daher offen und wird in der gemeinsamen Typkatalogkampagne mit je einem im selben Vertrag validierten All-Stop-Start untersucht.

## Nachvollziehbare Evidenz

- 300-s-Verfeinerung: `results/thesis_oip_pattern_refinement_300s_20260918/campaign.json`
- Ergänzte K40/K50-Baselines und K62-Verweise: `results/thesis_oip_all_stop_baselines_k40_k50_20260918/references.json`
- Fehlender F2-K50-Vergleich: `results/thesis_oip_missing_f2_comparison_20260918/direct_k50_p100_from_p110_movement/result.json`
- Ursprüngliche K62-CAL-O-Referenzen: `results/thesis_calibration_v2_20260917/references.json`
