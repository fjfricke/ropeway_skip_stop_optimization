# Abnahme: geometrische OIP-Mischungsreihe

18.09.2026. Implementierung, Tests und Build-only-Vorbereitung; **keine großen Referenz- oder Experimentläufe gestartet.**

## Vertrag und Nachweise

- 15 geplante Mischungen in F2/F3/F0-Reihenfolge, K62, No-Wait, freie Positionen; zusätzlich drei geplante regelmäßige Referenzbewertungen.
- Nachfrage 2266 / 5430 / 7606. CAL-O-Nmax 1888 / 4525 / 6338; alle drei Vollbedienungszertifikate unabhängig unter dem neuen Vertrag geprüft.
- Minimale zyklische Lücke 11806 ms; maximale alte und neue All-Stop-Schutzdauer 11667 ms. Bewegung, Nachfrage, Raster und ganzer Phasenraum bleiben gleich. N/N+1-Nachweise werden mit Quellhashes referenziert.
- Gemeinsame Ein-/Ausfahrten 1053 ms, Plattform 11667 ms. Keine mechanische 6-s-Ressource oder STOP-abhängige Dauerentscheidung. Historische Varianten bleiben verfügbar.
- Absolute 300-s-Deadline; zehn Sekunden Abschlussreserve innerhalb des Budgets. Gemischte Läufe haben den konservativen Referenz-Bound-Abbruch, All-Stop-Kontrollen nicht. Keine Hints, keine Journey-Nachoptimierung.

## Gemessene Modellgrößen

Jeweils K62, Mischung 30/16/16 bei der tatsächlichen Versuchsnachfrage. Vor Presolve; getrennte Aufbauvarianten, keine großen Solves. Ressourcenintervalle sind eine Teilmenge aller Intervalle (Passagierinventar erzeugt weitere).

| Familie | Variante | Variablen | Constraints | Ressourcenintervalle |
|---|---|---:|---:|---:|
| F2 | historische Regeln + Typwahl | 39436 | 93591 | 15686 |
| F2 | geometrische Regeln + Typwahl | 39684 | 94087 | 15686 |
| F2 | feste Typen, vollständige Headways | 19052 | 47897 | 5364 |
| F2 | feste Typen, geteilte Headway-Intervalle | 19052 | 46317 | 3784 |
| F3 | historische Regeln + Typwahl | 57171 | 134129 | 16058 |
| F3 | geometrische Regeln + Typwahl | 57357 | 134501 | 16058 |
| F3 | feste Typen, vollständige Headways | 28735 | 70167 | 5460 |
| F3 | feste Typen, geteilte Headway-Intervalle | 28735 | 68571 | 3864 |
| F0 | historische Regeln + Typwahl | 88424 | 204937 | 16058 |
| F0 | geometrische Regeln + Typwahl | 88610 | 205309 | 16058 |
| F0 | feste Typen, vollständige Headways | 47316 | 112463 | 5460 |
| F0 | feste Typen, geteilte Headway-Intervalle | 47316 | 110867 | 3864 |

Die Headway-Umstellung allein erhöht hier leicht die Aufbauzahlen: Plattformausfahrten bleiben neu auch bei No-Wait als vollständige Prüfstellen erhalten, während mechanische Ressourcen entfallen. Das wird nicht als Größenersparnis ausgegeben. Die große Einsparung stammt aus dem festen Typaufbau.

Intervallteilung entfernt zusätzlich 1580 Kopien bei F2 und 1596 bei F3/F0. Die 20 ursprünglichen Ressourcenfamilien bleiben als getrennte NoOverlap-Mengen erhalten, da sich ihre Randaktivierungen unterscheiden. Geteilte Intervalle erzeugen keine neuen Konfliktpaare. Der unabhängige Prüfer verwendet sämtliche physischen Prüfstellen.

## Prüfungen

- 155 Python-Tests im gezielten Headway-/OIP-/Thesis-Vertragstestlauf bestanden.
- 25 Frontendtests bestanden; TypeScript/Vite-Produktionsbuild erfolgreich. Die bestehende Warnung zur Chunkgröße bleibt, ohne Einfluss auf diesen Vertrag.
- 64 vollständig enumerierte Kombinationen einer kleinen Zweikabinen-Positionsdomäne stimmen in Typwahl-, festem und reduziertem Modell hinsichtlich Machbarkeit überein. Ihre Served-Optima stimmen ebenfalls überein.
- Kleiner BD/CE-Fahrplan mit zwei Sekunden Abstand: unter geometrischen Regeln unabhängig gültig, unter der alten Sonderbeschränkung abgelehnt. Tatsächliche Seil-/Plattformabstände bleiben geschützt.
- Anfangs-/Seilstarts, Alternierung und Millisekundengrenzen, vollständige Zertifikate, die alten gespeicherten F2/F3-Starts, fehlende Bounds, Budgetabbrüche, Bound-Abbruch ohne neuen Incumbent und fehlerhafte Kalibrierungsmetadaten geprüft.
- Referenz und Mischung teilen ausdrücklich denselben Vergleichsfingerprint. Die bisher mögliche doppelte Quantisierung beim CLI-Aufbau wurde entfernt.
- Frontend im Browser geprüft: 0/15, drei geplante Referenzen, richtige Typzahlen/Nachfragen, fehlende Ergebnisse als Strich. Keine künstlichen Nullwerte.
- Thesis gebaut; geänderte Methodik- und Parametertabellenseiten visuell geprüft.

## Kleine Suche und Grenzen

- Vollständig: OPTIMAL, 12/12 bedient, 0.044 s Suche; vor Presolve 636 Variablen/1614 Constraints/262 Intervalle, danach 195/560/211.
- Reduziert: OPTIMAL, 12/12 bedient, 0.041 s Suche; vor Presolve 636 Variablen/1563 Constraints/211 Intervalle, danach 195/509/160.

Der kleine Test zeigt keine offensichtliche Verschlechterung; ein einzelner kurzer Lauf ist kein Geschwindigkeitsnachweis für K62. Die endliche Enumeration deckt die ausgewählte kleine Positionsdomäne ab, nicht alle K62-Positionen. Die allgemeine Reduktion beruht zusätzlich auf identischer Zeittranslation, Dauer und Präsenz; ungleiche Randmengen bleiben erhalten.

Die CAL-O-Übernahme gilt nur für regelmäßiges All-Stop ohne Waiting. Sie ist kein Kapazitätsbeweis für freie Anfangspositionen. Große Presolve-/Suchstatistiken bleiben unbekannt, bis die ausdrücklich noch nicht gestartete Reihe läuft.

## Artefakte

- [Plan und CLI](../plans/oip_fixed_mixtures_120_20260918.md)
- `results/oip_fixed_mixes_geometric_120_20260918/campaign.json`: vorbereitete Matrix und Herkunft.
- `calibration_adoption/*.json`: geprüfte Zertifikate, Äquivalenzbegründung, Quellhashes.
- `frozen_domains/*.json`: Nachfragegruppen und Fingerprints bei Versuchsnachfrage.
- `results/oip_geometric_build_ablation_20260918.json`: vollständige Größenablation.
- `results/oip_geometric_small_solve_20260918.json`: kleine Such- und Presolve-Messung.
