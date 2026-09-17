# Kompakte Formulierungen des Reservoir-Linienmodells

Stand: 13.09.2026. Begleitdokument zum
[Umsetzungs- und Testplan](../plans/reservoir_line_compaction_tests_20260913.md).

## Ergebnis in einem Satz

Die gemeinsame Rundendarstellung verkleinert das bisherige Modell um 68 % der
Variablen und 72 % der Constraints, halbiert ungefähr den nativen Suchstart und
liefert wesentlich stärkere Flottenschranken. Mit einem geprüften U=38-Seed
erreichen alle Varianten U=0; ohne Seed bleibt die Konstruktion großer Flotten
auch nach der Kompaktion unzuverlässig.

## 1. Gegenstand und Grenzen

Verglichen wird exakt dieselbe eingeschränkte Domäne:

- fünf Stationen, R2-Nachfrage mit D=3.074;
- maximal 50 optionale Single-Use-Reservoirkabinen;
- drei feste wiederkehrende Haltemuster aus dem kleinen Katalog;
- freie zulässige Dispatchzeit und Rundenzahl;
- ganzzahlige direkte Beförderungen;
- primär maximale Bedienung, sekundär minimale Flotte.

Das Modell fixiert Waiting weiterhin auf null. Die Resultate belegen daher die
Leistung des Linienmodells, nicht des vollständigen Reservoirproblems mit Waiting.
Ein U=0-Plan beweist das primäre Optimum innerhalb dieser Domäne unmittelbar,
weil höchstens D Personen bedient werden können. Das sekundäre Flottenoptimum ist
in keinem freien 300-s-Lauf bewiesen.

## 2. Implementierte Varianten

| Kürzel | Darstellung |
|---|---|
| V0 | bisherige Vorlagenkopien für jede Muster-/Rundenzahlalternative |
| V1 | V0-Modell, aber ungenutzte Paar-Domänen bei Intervallkodierung nicht vorbereiten |
| V2 | Ressourcen und Passagiere einmal je gemeinsamem Rundenvorsatz und Muster |
| V3 | V2-Ressourcen; Ride-Mengen zusätzlich über kompatible Muster zusammenfassen |
| V4 | nicht implementiert; nach V2/V3 war der bedingte Auslöser nicht erfüllt |

Zum Zeitpunkt dieser Ablation blieb V0 zunächst der öffentliche Standard. Nach
der gesonderten Entscheidung und Längenskalierung vom 13.09.2026 wurde V2 zum
Linienmodell-Default; alle Varianten bleiben explizit über `--preparation` und
`--formulation` wählbar. Die Vorbereitung prüft vor dem
Modellbau, dass kürzere Vorlagen tatsächlich Präfixe der längsten Vorlage eines
Musters sind. Nicht unterstützte Kombinationen werden abgewiesen.

## 3. Korrektheit

Die kleinen Tests vergleichen V0, V2 und V3 bei freien sowie fixierten Bewegungen,
einschließlich jeder erzeugten Ein-Kabinen-Vorlage des kleinen Testfalls. Sie
prüfen außerdem Rundengrenzen, optionale Flotte, Hint-Semantik, Freigaben,
Intervallberührung und die unabhängige Zertifikatsvalidierung. Gemeinsam mit den
Reservoir-CP-SAT-Regressionen bestehen 44 gezielte Tests. Die vollständige Suite unter `tests/` besteht mit 1.519 Tests und 22 erwarteten Skips.

Der historische R2-Plan mit U=0 und 38 Kabinen wurde in allen drei Suchvarianten
als Bewegung fixiert. Jede Variante reproduzierte und bewies S=3.074:

| Variante | Solverstatus | Gesamtzeit | Peak-RSS |
|---|---|---:|---:|
| V0 | OPTIMAL | 3,55 s | 577 MiB |
| V2 | OPTIMAL | 1,10 s | 248 MiB |
| V3 | OPTIMAL | 0,89 s | 231 MiB |

Die maschinenlesbaren Nachweise stehen in
`benchmarks/output/reservoir_line_compaction_20260913_campaign_v1/correctness.json`.

## 4. Modellgröße und Aufbau

Median aus drei frischen Prozessen pro Variante. Peak-RSS umfasst den jeweiligen
Build-Prozess und ist nicht mit dem Peak eines Suchlaufs gleichzusetzen.

| Variante | q-Variablen | Variablen | Constraints | Intervalle | Proto | Modellbau | Runner gesamt | Peak-RSS |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| V0 | 49.850 | 100.950 | 393.205 | 72.500 | 26,26 MB | 2,33 s | 2,90 s | 326 MiB |
| V1 | 49.850 | 100.950 | 393.205 | 72.500 | 26,26 MB | 2,33 s | 2,77 s | 322 MiB |
| V2 | 14.800 | 31.950 | 111.405 | 17.350 | 7,26 MB | 0,67 s | 0,84 s | 157 MiB |
| V3 | 9.200 | 20.750 | 94.605 | 17.350 | 5,86 MB | 0,55 s | 0,68 s | 144 MiB |

Gegenüber V0 reduziert V2 Variablen um 68,4 %, Constraints um 71,7 %,
Intervalle um 76,1 % und die serialisierte Größe um 72,3 %. V3 reduziert die
Variablen um 79,4 % und die serialisierte Größe um 77,7 %. Die vorher geschätzten
17.350 Intervalle wurden exakt bestätigt.

V1 erzeugt ein bytegleiches CP-SAT-Modell. Es spart im Median nur ungefähr
0,11 s Vorlauf und ist deshalb eine sichere kleine Vorbereitungskorrektur, keine
Suchverbesserung.

## 5. Freie Suche mit gemeinsamem U=38-Hint

Jeder Lauf erhielt denselben unabhängig validierten Startplan mit S=3.036 und
36 Kabinen. Zeitangaben messen ab Runnerstart; Seedübernahme zählt nicht als
Verbesserung. Solverlimit 300 s, 12 Worker, 24 GiB.

| Variante / Seed | Hint übernommen | erste echte Verbesserung | U=0 | Endflotte | lokaler Objective-Bound | Peak-RSS |
|---|---:|---:|---:|---:|---:|---:|
| V0 / 0 | 107,1 s | 127,8 s | 172,2 s | 37 | 156.772 | 8,98 GiB |
| V0 / 1 | 104,7 s | 133,4 s | 151,2 s | 38 | 156.770 | 9,66 GiB |
| V2 / 0 | 54,3 s | 70,0 s | 188,6 s | 38 | 156.742 | 6,14 GiB |
| V2 / 1 | 54,8 s | 77,4 s | 141,9 s | 38 | 156.741 | 7,00 GiB |
| V3 / 0 | 51,0 s | 87,3 s | 199,7 s | 38 | 156.741 | 4,07 GiB |
| V3 / 1 | 52,0 s | 85,7 s | 231,0 s | 37 | 156.743 | 4,12 GiB |

V2/V3 halbieren reproduzierbar die Zeit bis zum Suchstart. V2 findet die erste
echte Verbesserung in beiden Seeds früher als V0. Die Zeit bis U=0 ist dagegen
nicht eindeutig besser: V0-Median 161,7 s, V2 165,2 s, V3 215,4 s. V0 und V3
erreichen jeweils in einem Seed 37 Kabinen; V2 bleibt bei 38.

Für einen U=0-Plan mit K Kabinen lautet das kombinierte Ziel `51*3074-K`.
Die Endbounds von V2/V3 beweisen deshalb innerhalb der Liniendomäne mindestens
32 bis 33 benötigte Kabinen. V0 beweist nur mindestens zwei bis vier. Das ist ein
deutlicher Gewinn auf der sekundären Beweisseite, schließt den Flottengap aber nicht.

## 6. Freie Suche ohne Fahrplanhint

| Variante / Seed | erste Lösung | S nach 180 s | S Ende | K Ende | letzter Fortschritt | Peak-RSS |
|---|---:|---:|---:|---:|---:|---:|
| V0 / 0 | 107,1 s | 888 | 1.048 | 17 | 302,1 s | 9,49 GiB |
| V0 / 1 | 103,8 s | 832 | 1.496 | 20 | 274,1 s | 9,97 GiB |
| V2 / 0 | 55,1 s | 1.456 | 1.456 | 19 | 148,6 s | 6,22 GiB |
| V2 / 1 | 54,9 s | 1.344 | 1.344 | 17 | 147,2 s | 6,30 GiB |
| V3 / 0 | 50,9 s | 808 | 1.613 | 39 | 300,5 s | 4,15 GiB |
| V3 / 1 | 50,6 s | 1.120 | 1.136 | 16 | 296,1 s | 4,13 GiB |

V2 ist der stabilste hintfreie Konstruktor: beide Endwerte liegen relativ nah
beieinander und der Flottenaufbau erfolgt früh. V3 streut stark. In Seed 0 findet
es erst nach 295,9 s eine 39-Kabinen-Struktur und springt bis S=1.613; Seed 1
reproduziert diesen Sprung nicht. Auch die beste hintfreie Lösung bleibt 1.461
Personen unter Vollbedienung. Die interne CP-SAT-Suche ersetzt daher keinen
konstruktiven Linienseed.

Ein scheinbares Plateau war mehrfach nur temporär: V3/0 sprang nach rund 171 s
ohne Verbesserung am Ende stark, V0/1 nach über 100 s. Deshalb werden vollständige
Zeitverläufe berichtet und keine dauerhafte Stagnation aus kurzen Fenstern abgeleitet.

## 7. Entscheidung

Nach den vorab festgelegten Kriterien gibt es **keinen bestätigten allgemeinen
Suchsieger**: Keine neue Variante erreicht in beiden Hint-Seeds U=0 mindestens
20 % schneller als V0, und die hintfreien Endvorteile wechseln mit dem Seed.
Die Variantenwahl wurde deshalb nicht als allgemeiner CP-SAT-Speedup begründet.

Für die nächsten Thesis-Experimente ist dennoch eine klare Rollenverteilung sinnvoll:

1. **V2 als Hauptformulierung und neuer Linienmodell-Default**, wenn Speicher,
   stabiler eigener Aufbau und stärkere Bounds gemeinsam zählen.
2. **V3 als speichersparende Vergleichsvariante**, besonders für längere Strecken
   oder größere K; wegen der Streuung immer mit mehreren Seeds.
3. **V0 als Regression und Incumbent-Kontrolle** beibehalten.
4. Große Läufe mit einem konstruktiven Linienplan starten. Hintfreie Läufe sind
   Diagnosefälle und keine sinnvolle Produktionsstrategie.

V4 wird vorerst nicht umgesetzt. Die Intervallkopien sind bereits um 76 % reduziert;
der nächste wissenschaftlich sinnvollere Schritt ist die geplante K-/Längenskalierung
von V0/V2/V3 und der Vergleich gegen die phasenoptimierte All-Stop-Baseline.

Der Defaultwechsel vom 13.09.2026 betrifft ausschließlich das eingeschränkte
No-Wait-Linienmodell. Das vollständige Reservoir-CP-SAT-Modell und historische
Aufrufe bleiben davon unberührt; V0 ist weiterhin explizit auswählbar. Die
anschließende [Längenskalierung](reservoir_line_length_scaling_results_20260913.md)
bestätigt, dass V2 auch bei 75 bis 235 verfügbaren Slots baubar bleibt.

## 8. Reproduzierbarkeit und Thesis-Verwendung

Zentrale Artefakte:

- `benchmarks/output/reservoir_line_compaction_20260913_campaign_v1/manifest.json`
- `benchmarks/output/reservoir_line_compaction_20260913_campaign_v1/build_metrics.csv`
- `benchmarks/output/reservoir_line_compaction_20260913_campaign_v1/run_summary.csv`
- `benchmarks/output/reservoir_line_compaction_20260913_campaign_v1/progress.jsonl`
- die validierten `best.json`-Zertifikate in den referenzierten Laufordnern.

Für die Thesis sind drei Aussagen belastbar: Die Präfixfaktorisierung reduziert
die Darstellung erheblich; sie verbessert Presolve, Speicher und lokale Bounds;
und ein guter konstruktiver Seed bleibt für hohe Nachfrage entscheidend. Diese
Kodierungsresultate sind getrennt vom späteren Nachweis eines betrieblichen
Skip-Stop-Vorteils gegenüber All-Stop zu berichten.
