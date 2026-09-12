# K39: isolierter Vergleich von Zeit-Hints

Zwei historische Muster × mit/ohne Zeit-Hints × Solver-Seeds 0/1. Jeweils 300 s einschließlich Aufbau, zwölf Worker, sequenziell. Bei Seed 1 ist die Methodenreihenfolge umgekehrt. Startwerte sind keine fixierten Zeiten; keine Ausgangslösung oder Objective-Schranke wird übernommen.

| Muster | Seed | Zeit-Hint | Status | Unbedient | lokales LB | Erste native Lösung s | Gesamt s |
|---|---:|---|---|---:|---:|---:|---:|
| variant1 | 0 | time_hint | FEASIBLE | 1410 | 1377 | 4.11 | 300.35 |
| variant1 | 0 | none | UNKNOWN | — | 1377 | — | 300.12 |
| variant2 | 0 | time_hint | FEASIBLE | 1418 | 1377 | 3.86 | 300.35 |
| variant2 | 0 | none | UNKNOWN | — | 1377 | — | 300.12 |
| variant1 | 1 | none | UNKNOWN | — | 1377 | — | 300.14 |
| variant1 | 1 | time_hint | FEASIBLE | 1410 | 1384 | 4.50 | 300.42 |
| variant2 | 1 | none | UNKNOWN | — | 1377 | — | 300.12 |
| variant2 | 1 | time_hint | FEASIBLE | 1418 | 1377 | 4.06 | 300.33 |

Abgeschlossene, auf identische Modellstruktur geprüfte Paare: 4/4. Alle Bounds sind nur musterbezogen.

Die Zeit-Hints stammen unverändert aus dem gespeicherten K39-Screening-Endfahrplan (U=1418). Beim damaligen Screening blieb dieser aktuelle Fahrplan vor beiden erfolgreichen Musteränderungen erhalten: Die geänderten Muster mit U=1426 wurden nicht als aktueller Zustand akzeptiert. Damit sind dies die früher verwendeten Zeitwerte.

Für jedes Paar wird der Modell-Fingerprint nach Entfernen der Hint-Felder verglichen. Vollständige Domain-Manifeste und Muster-IDs müssen ebenfalls übereinstimmen. Jede Bestlösung je Musterlauf wird als vollständiges Zertifikat gespeichert; sämtliche vom Solver zurückgegebenen zulässigen Lösungen zusätzlich unter `certificates/`. Die Endzuordnung wird unabhängig mit EAN/Gurobi geprüft.

Zwei Seeds liefern eine begrenzte Wiederholung, keinen statistisch abgesicherten allgemeinen Effekt. Die parallele CP-SAT-Suche ist nicht deterministisch. Die abgeschlossenen früheren 300-s-Läufe ohne Hints werden nicht anstelle neuer Kontrollläufe verwendet.

Ergebnisordner: `/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/pattern_time_hint_ablation_20260910`. `experiment.json`, `patterns.json`, `time_hint.json`, `source.tar.gz`, `source_manifest.json`; je Lauf Konfiguration, Domain, Events, Solverlog, Ergebnis, Checkpoint und vollständige Zertifikate.
