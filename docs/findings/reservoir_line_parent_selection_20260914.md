# Isolierter Vergleich der GA-Elternwahl

14. September 2026. R2, D=3.074, Kmax=50, No-Wait, gemeinsamer All-Stop-Phasenplan, mixed_global, Seed 0, jeweils 60 Sekunden Gesamtbudget. Ein Seed ist ein diagnostischer Vorvergleich, keine bestätigte Performanceempfehlung.

| Messgröße | Standardturnier | 25 % Exploration |
|---|---:|---:|
| Eindeutige Bewertungen | 5701 | 7108 |
| Gültige Bewertungen | 1025 | 899 |
| Anteil unzulässiger Eltern | 6.9 % | 30.5 % |
| Beste Bedienung | 2496 | 2496 |

## Entwicklung der selbst gefundenen Muster

Die Standardauswahl erreicht bei K=4 nach 2,9 Sekunden 352 Personen mit vier C–E-Mustern und bei K=5 nach 4,1 Sekunden 416 Personen. Bei K=6 erreicht sie nach 27,6 Sekunden 392 Personen mit fünf All-Stop-Kabinen und einer A–B–C–E-Kabine.

Mit gezielter Elternwahl entsteht nach 2,9 Sekunden ein gemischter K=6-Plan mit 448 Personen. Nach 16,4 Sekunden entsteht ein K=7-Plan mit 560 Personen: zweimal A–C–E, zweimal B–C–E sowie je einmal B–D, B–D–E und C–E. Die kleineren K=2–5-Frontiers sind teilweise schlechter als im Kontrolllauf. Bei K=35–38 bleiben beide Varianten bei All-Stop.

Der größere Anteil unzulässiger Eltern wirkt wie beabsichtigt. Der Lauf erschließt eine etwas größere gültige gemischte Flotte, belegt aber keinen Durchbruch bei dichter Belegung. Beide globalen Incumbents bleiben beim Startplan mit 2.496 bedienten Personen. Eine größere Anzahl Bewertungen allein ist kein Qualitätsbeleg.

## Artefakte

- Standard: `benchmarks/output/reservoir_line_evolution_20260914/parent_ablation_p0_s0/`
- Exploration: `benchmarks/output/reservoir_line_evolution_20260914/parent_ablation_p0.25_s0/`
- Die events.jsonl-Dateien speichern gültige K-Frontiers mit Musterreihenfolge und exakten Dispatchzeiten sowie Fünf-Sekunden-Fenster über Bewertungen und Konflikte.
- parent_selection_counts dokumentiert die tatsächlich gewählten Eltern. Die 25-%-Quote bezeichnet den zusätzlichen Explorationszweig; unzulässige Eltern können auch im Standardzweig gewinnen.

## Grenzen und nächster Schritt

Die 25-%-Regel bleibt experimentell schaltbar; 0 stellt die bisherige Turnierlogik wieder her. Vor einer Empfehlung sind weitere Seeds erforderlich. Konfliktdauer und optimistische Passagierbedienung werden in diesem Vergleich nicht als neue gemeinsame Zielfunktion eingeführt. Die vorherige breite Kampagne ist unterbrochen und nicht abgeschlossen.
