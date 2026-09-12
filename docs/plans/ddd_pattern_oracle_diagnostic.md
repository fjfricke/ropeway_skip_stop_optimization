# Diagnose des festen Stop/Skip-Musters: CP-SAT gegen Gurobi

Stand: 2026-09-10. Vom Nutzer freigegeben; implementiert und vollständig abgeschlossen (12/12 Läufe ohne Ausführungsfehler).

## Anlass

Die VNS-Kampagne wurde auf Nutzerwunsch pausiert. Bei K38 endeten im Screening alle
UNKNOWN-Aufrufe bereits in der Vorverarbeitung. Daraus darf nicht geschlossen werden,
dass das feste Muster grundsätzlich schwer oder schlecht ist. Insbesondere sind
Passagierzuordnung bei vollständig festen Zeiten und gemeinsame Timing-/Passagieroptimierung
bei nur festem Stop/Skip zwei verschiedene Teilprobleme.

## Eingefrorener Vergleich

- Unverändert: Fünf-Stationen-B, feste Balanced-Reference-Starts, exakt K38/K39,
  H=1200 s, Exit-Warten bis 1200 s, Mikrosekundenraster, acht Plätze, Nachfrage 3074.
- Ziel ausschließlich unbediente Personen; Journey Time bleibt im Primalzertifikat.
- Je K das ursprüngliche Muster und zwei bereits im Screening ausgewertete Änderungen.
  K38: erste neue UNKNOWN- und erste neue INFEASIBLE-Variante. K39: die beiden neuen
  FEASIBLE-Varianten. Exakte IDs und alle Route-Entscheidungen in `patterns.json`.
- Jedes Muster auf CP-SAT und Gurobi. Ein zusammenhängender Lauf bis 300 s einschließlich
  Modellbau, zwölf Worker/Threads, Solver-Seed 0. Messpunkte 5/30/60/300 s aus demselben
  Lauf. Kein Neustart an den Messpunkten; früheres bewiesenes Ende zulässig.
- Reihenfolge: zuerst Originale (K38 CP/MIP, K39 CP/MIP), danach Variante 1 und Variante 2.
  Insgesamt zwölf Läufe; maximal ungefähr eine Stunde zuzüglich Nachprüfungen/Overruns.
- Beide Verfahren verwenden dieselben ursprünglichen Kampagnenseeds, nicht Ergebnisse
  des neuen Vergleichs. Nur passende Muster erhalten das Zertifikat als Startlösung
  und dessen lokale Objective-Schranke. Geänderte Muster erhalten keinen falschen Seed.
- Vollständige Startwerte einschließlich abgeleiteter Hilfsvariablen für passende Muster.
  Separate Messung: extern bekanntes Zertifikat versus erste vom Solver gelieferte Lösung.
- Native Logs, Bounds, validierte Incumbents, Modellgrößen, Bau-/Lösezeiten und unabhängige
  EAN/Gurobi-Passagiernachprüfung. Bounds niemals über Muster hinweg übertragen.

## Implementierung

`optimization/ddd/pattern_oracle_probe.py` enthält `PatternProbeConfig`, `ProbeProgress`
und `FixedPatternCpSatProbe`. Das CP-Modell bleibt die bisherige Formulierung; nur die
Route jedes Besuchs wird bedingt auf dessen Aktivierung fixiert. Vollständige passende
Hints werden mit `cp_hint_completion.py` abgeleitet; die Ableitung zählt zum Budget.

`optimization/ddd/pattern_mip.py` enthält `PatternMipModel`, `build_pattern_mip` und
`FixedPatternMipProbe`. Das MIP baut pro Besuch nur die ausgewählte Route. Ereigniszeiten
und Wait-Schritte sind ganzzahlig. Aktivierung bleibt äquivalent zu Eintritt vor/auf dem
operativen Horizont. Ressourceneintritt vor/auf dem Horizont aktiviert Belegungen; deren
Ende darf darüber hinausreichen. Boundary-Belegungen und exakte Headway-Ticks werden
übernommen. Paarweise Richtungsindikatoren stellen Nichtüberlappung sicher, ohne die
Reihenfolge aus dem Seed festzuschreiben. Früheste mögliche Zeiten erlauben sichere
Entfernung unmöglicher Besuche/Rides und disjunkter Ressourcenpaare. Passagiermengen sind
ganzzahlig, Stop-Bedingungen, Release-/Service-Zeiten und Sitzplatzbelegung gelten gemeinsam.

Dieser Vergleich untersucht **zwei Formulierungen derselben zulässigen Domäne**. Ein
schlechtes Resultat dieses MIP ist kein Urteil über sämtliche möglichen MIP-Formulierungen.
Die dichte Paarformulierung kann deutlich mehr Variablen als CP-NoOverlap erzeugen.

`benchmarks/run_pattern_oracle_diagnostic.py` isoliert den Quellcode und startet einzelne
Worker sequenziell. Fehler eines Workers werden protokolliert; die übrigen Diagnosen
laufen weiter. Nach jedem Lauf werden Tabelle und Messpunkte aktualisiert.

## Verifikation

Acht neue Tests in `tests/test_ddd_pattern_oracle_probe.py` bestehen:

- Alle No-Wait-Tiny-Muster: gleiche bewiesene Optima in beiden Backends.
- Passender vollständiger Start; schlechteres Muster übernimmt keinen falschen Cutoff.
- Exit-Warten, Release und Kapazität für eine und zwei Kabinen.
- Unvereinbare feste Starts: beide Backends beweisen Unzulässigkeit.
- Bereits belegte Boundary-Ressource wird berücksichtigt.
- Release-Unterschied von exakt einer Mikrosekunde.
- Operativer Nachlauf erweitert nicht das Passagier-Servicefenster.

Die ersten sechs Tests wurden zusätzlich gegen die tatsächlich eingefrorene Runtime
bestanden. Die zwei ergänzten Grenzfalltests verändern die ausgeführte Formulierung nicht.

## Erster Befund

Das Originalmuster K38 wurde von CP-SAT nach **24,03 s** als optimal bewiesen:
U=315, lokales LB=315. Modell/Hints-Aufbau 4,76 s; erste native Lösung nach 21,63 s.
Alle 48.033 Variablen waren gehintet. Dies zeigt konkret, dass fünf Sekunden für diesen
Aufruf unzureichend waren. Timing allein kann dieses Muster nicht weiter verbessern.

Das Gurobi-Modell desselben Musters hat 560.653 Variablen, davon 554.889 binär, wegen
273.588 potenzieller Ressourcenpaare. Bauzeit 16,49 s; erste native Lösung nach 17,14 s.
Auch Gurobi beweist U=LB=315, nach insgesamt 234,28 s. CP-SAT ist bei diesem Muster deutlich schneller beim Optimalitätsnachweis. Alle weiteren Muster sind ausgewertet; Abschlussbewertung im Ergebnisbericht.

## Dateien und laufender Stand

- Bericht: `docs/findings/ddd_pattern_oracle_diagnostic_20260910.md`.
- Ergebnisse: `benchmarks/output/pattern_oracle_diagnostic_20260910/`.
- Supervisorlog: `benchmarks/output/pattern_oracle_diagnostic_20260910.log`.
- Prozessnachweis: `benchmarks/output/pattern_oracle_diagnostic_20260910_process.json`.
- `runtime/`, `source.tar.gz`, `source_manifest.json`: eingefrorene Basis aus dem
  vorherigen Vergleich plus neue Probes und Hint-Vervollständigung.
- Alte VNS-Daten: `benchmarks/output/pattern_search_20260910_v2/`; `completion.json`
  dokumentiert die Pause. Unterbrochene Läufe haben Logs und Checkpoints, aber keinen
  fingierten vollständigen Ergebnisdatensatz.

Nach Abschluss zuerst die Muster einzeln vergleichen: Zeit bis zulässig, Zeit bis
Verbesserung, lokaler Gap, Modell-/Presolve-Anteil. Erst daraus ein geeignetes Oracle-
Budget und gegebenenfalls den Backend-Einsatz für eine erneute Mustersuche ableiten.

Abgeschlossen: CP-SAT bestätigt beide K38-Änderungen als unzulässig; beim K39-Original erreicht CP U=1410 und Gurobi LB=1386. Die K39-Änderungen blieben ohne passende Zeit-Hints bei beiden Backends ungelöst. Details und Einschränkung des Hint-Vergleichs im Ergebnisbericht. Keine automatische weitere Suchkampagne gestartet.
