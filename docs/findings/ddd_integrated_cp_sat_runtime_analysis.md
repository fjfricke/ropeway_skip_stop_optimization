# Integrierter CP-SAT: Laufzeit, Fortschritt und Implementierungsprüfung

Stand: 9. September 2026. Nachanalyse der drei vorhandenen Läufe; **kein neuer Langlauf und keine Änderung der Solverformulierung**. Ergänzt den [ersten Gate-Bericht](ddd_integrated_cp_sat_gate.md). Die nächste Priorität ist eine belastbare Laufzeitanalyse desselben CP-SAT-Modells, vor einem Wechsel zu Arc-Flow.

## Befund

Zehn Minuten reichen nicht, um die langfristige Konvergenz zu beurteilen. K=39 verbessert die Lösung zuletzt nach 379,77 s und die native untere Schranke zuletzt nach 560,52 s, jeweils seit Beginn des integrierten Optimizers. Am Ende stehen etwa 219 s ohne bessere Lösung, aber nur etwa 38 s ohne bessere Schranke. Das ist ein beobachtetes Plateau der Lösung am Laufende, kein Nachweis dauerhafter Stagnation.

Die Implementierung ist eine getestete erste Version. Korrektheitstests, unabhängige Fahrplanvalidierung und Passagier-IP bestätigen die geprüften Fälle. Sie beweisen weder Fehlerfreiheit noch eine besonders effiziente Formulierung. Ein systematischer Performancevergleich einzelner Implementierungsänderungen fehlt bisher.

## Zeitanteile

Quelle: jeweilige `result.json` und `solver.log` unter `benchmarks/output/ddd_integrated_cp_sat/`.

| Phase | K20 Produkt | K20 Unary | K39 Produkt |
|---|---:|---:|---:|
| Instanz/Startzustand vorbereiten | 0,055 s | 0,057 s | 3,995 s |
| Startlösung importieren/aufbereiten | 0,373 s | 0,305 s | 0,667 s |
| Integrierter Aufbau inkl. Eingangsprüfung/Hints | 0,422 s | 0,538 s | 0,903 s |
| Solveraufruf, inkl. Presolve und Callbacks | 299,387 s | 299,197 s | 597,344 s |
| Davon bis zum protokollierten Suchstart | 2,91 s | 6,34 s | 14,88 s |
| Abschließende Validierung/Checkpoint | 0,069 s | 0,073 s | 0,189 s |
| Gesamter Runner | 300,352 s | 300,221 s | 603,215 s |

Die Suchstartzeit ist eine Teilmenge des Solveraufrufs, kein zusätzlicher Summand. Kleine Differenzen zur Gesamtsumme entstehen durch weitere Runnerarbeiten. Die 603 s beim 600-s-Budget enthalten kooperativen Solverstopp und Abschlussarbeiten.

Der K39-Aufbau beansprucht rund **0,15 %** der Gesamtlaufzeit. Python-Modellbau zu beschleunigen allein wird den Engpass nicht lösen. Eine andere Formulierung kann dagegen die spätere Solversuche beeinflussen, auch wenn ihr Aufbau schon schnell ist.

Nicht separat gemessen: gesamte Zeit für Lösungs-Extraktion in Callbacks, Bound-Callbacks, Logging sowie Peak-RSS pro Phase. Die Callbackklasse zählt Checkpoint-Validierungszeit intern, exportiert diese Kennzahl aber noch nicht separat. Daher ist die Aussage „Callbacks sind vernachlässigbar“ bisher unbewiesen.

## Modellgrößen vor und nach Presolve

| Modell | Variablen vorher → nachher | Constraints vorher → nachher | Peak-RSS |
|---|---:|---:|---:|
| K20 Produkt | 19.570 → 9.250 | 42.175 → 16.325 | 1.351 MB |
| K20 Unary | 29.620 → 18.470 | 57.585 → 30.765 | 1.764 MB |
| K39 Produkt | 43.986 → 17.268 | 92.596 → 31.820 | 2.051 MB |

Constraintzahlen sind Einträge im CP-Modell und mischen lineare Bedingungen, Intervalle, NoOverlap, Produkte usw.; sie sind nicht direkt mit einer MILP-Zeilenzahl gleichzusetzen. Peak-RSS gilt für den gesamten Prozess einschließlich Solverarbeitsspeicher, nicht nur für den Modell-Proto.

K39 enthält initial 1.418 modellierte Besuche, 2.836 Routenliterale, 5.677 Ressourcenintervalle und 5.030 Passagier-Ride-Variablen. Nach Presolve bleiben 8.713 Boolesche Variablen, 1.219 Produktbedingungen und 5.437 Intervalle in 36 NoOverlap-Komponenten. Presolve verkleinert also erheblich; die verbleibende gekoppelte Suchstruktur ist weiterhin anspruchsvoll.

## Fortschritt bei K39

Kosten in Passagiersekunden, LB unten bei null abgeschnitten. Zeit seit Optimizerstart, also **nach** Instanzvorbereitung und Seedimport. Die Tabellenwerte sind Zustände aus den aufgezeichneten Events; Bound-Events werden höchstens alle 0,5 s gespeichert. Finale Werte stammen zusätzlich aus dem Solverresultat. Zwischenwerte sind Solverberichte, nicht alle separat validierte Checkpoints.

| Zeit | Beste CP-Lösung, kleiner ist besser | Native LB, größer ist besser | Gap |
|---|---:|---:|---:|
| 1 min | 1.312.631,34 | 2.161,16 | 99,84 % |
| 2 min | 1.278.095,43 | 380.167,08 | 70,26 % |
| 3 min | 1.275.627,88 | 381.898,78 | 70,06 % |
| 5 min | 1.273.232,35 | 390.930,68 | 69,30 % |
| 7 min | 1.272.673,03 | 394.362,18 | 69,01 % |
| Laufende, etwa 10 min | 1.272.673,03 | 402.843,30 | 68,35 % |

Zwischen Minute 5 und Laufende verbessert sich die Lösung nur noch um **559,33 (0,044 %)**, die LB hingegen um **11.912,62 (3,05 %)**. Der Gap sinkt dabei um etwa **0,95 Prozentpunkte**. Daraus darf keine lineare Zeitprognose bis zur Optimalität abgeleitet werden.

49 CP-Incumbent-Events wurden gespeichert; der erste reproduziert die importierte Startlösung. Bei K20 Produkt wird der bekannte optimale Seed nach 4,45 s intern erreicht. Seine LB liegt nach 60 s bereits bei 419.871,87 und am Ende bei 419.877,36: ein wesentlich ausgeprägteres spätes Schrankenplateau. K20 Unary hält ab etwa 9,3 s denselben Seed, erreicht während der fünf Minuten aber keine positive LB. Das priorisiert Produkt für weitere Experimente, beweist keine generelle Unterlegenheit von Unary.

## Welche internen Verfahren arbeiten?

Das native K39-Log zeigt bereits ein Solverportfolio innerhalb **eines** CP-SAT-Modells:

- Die erste Lösung kommt aus `no_lp` mit Hint. Viele spätere Verbesserungszeilen nennen `graph_dec_lns`, daneben Graph- und Scheduling-Nachbarschaften. LNS repariert jeweils einen begrenzten Ausschnitt einer vorhandenen Lösung.
- Die untere Schranke steigt zunächst vor allem durch `quick_restart`, später durch `max_lp`. Die abschließenden LB-Verbesserungen ab etwa 425 Solversekunden kommen aus `max_lp`.
- Es findet erhebliche LP-Arbeit statt: `default_lp` 1.215.741 Iterationen, `fixed` 759.065, `max_lp` 417.648, `quick_restart` 769.643. Das sind workerbezogene Zähler, keine unabhängigen End-to-End-Zeitanteile.
- Die kompakte `CpSolverResponse` nennt unter anderem `conflicts: 0` und `lp_iterations: 0`. Diese Felder allein bilden hier offensichtlich nicht die gesamte Portfolioarbeit ab; die detaillierten Workerstatistiken zeigen zahlreiche Konflikte und LP-Iterationen. Für Diagnosen deshalb das vollständige Log verwenden.

Aus den Beiträgen einzelner Worker folgt nicht, dass andere Worker nutzlos sind: geteilte Schranken, Klauseln und Lösungen beeinflussen das Portfolio. Änderungen müssen kontrolliert getestet werden. Offizielle Parameter- und Portfolioquellen: [SatParameters](https://github.com/google/or-tools/blob/v9.15/ortools/sat/sat_parameters.proto), [CP-SAT-Suchportfolio](https://github.com/google/or-tools/blob/v9.15/ortools/sat/cp_model_search.cc).

## Konkrete Stellen für Verbesserungen

Die folgenden Punkte sind **prüfbare Hypothesen**, keine bereits gemessenen Beschleunigungen.

1. **Zeitdomänen und Passagierkopplung stärken — höchste fachliche Priorität.** In [cp_sat_movement.py](../../src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_movement.py) beginnen alle späteren Ereigniszeiten mit der breiten Domäne `0..max_completion_tick`. In [cp_sat_passenger.py](../../src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_passenger.py) werden Alighting-Produkte ebenfalls zunächst breit begrenzt. Aus festen Starts und No-Wait-Routendauern lassen sich besuchsspezifische erreichbare Zeiten bzw. sichere Unter-/Obergrenzen ableiten. Davon erhoffe ich mir stärkere frühe Propagation und engere Produktrelaxationen. Endhorizont, inaktive angehängte Besuche und Ressourcen dürfen dabei nicht falsch abgeschnitten werden. Gröbere Zeitraster wären eine Modelländerung und sind kein gleichwertiger Ersatz.
2. **No-Wait-Intervalle kompakter ausdrücken.** `_add_resource_intervals` erzeugt auch ohne Warten explizite Entry-, End- und Size-Variablen samt Gleichungen. Ein spezialisierter No-Wait-Pfad könnte affine Starts und feste Intervallgrößen verwenden; die bisherige Präsenz-/Horizontlogik muss erhalten bleiben. Davon erhoffe ich mir weniger Hilfsvariablen und eventuell weniger Presolve-/Hintaufwand. Da Presolve viele Hilfsvariablen bereits entfernt, ist ein großer Suchgewinn ungewiss. OR-Tools unterstützt solche [optionalen Intervalle mit fester Größe](https://or-tools.github.io/docs/python/cp__model_8py_source.html).
3. **Hints vervollständigen und messen.** K39 startet mit 19.739 von 36.857 nicht fixierten Variablen im Hint; nach Presolve 15.794 von 17.268. Viele fehlende Werte sind ableitbare Ressourcenhilfsgrößen. Vollständige konsistente Hints könnten die interne Übernahme beschleunigen. Der erste Seed wird aber schon nach etwa 20,45 Solversekunden übernommen: daraus allein ist kein Durchbruch nach zehn Minuten zu erwarten.
4. **Callbackkosten sichtbar machen.** [cp_sat_integrated.py](../../src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_integrated.py) extrahiert bei jedem Incumbent sämtliche Routen- und Passagierwerte; nur die nachfolgende Checkpointvalidierung ist zeitlich gedrosselt. Erst Extraktions-/Validierungs-/Logzeiten messen, dann bei relevantem Anteil seltener vollständig extrahieren. Finale Validierung und sichere Checkpoints bleiben erhalten.
5. **Portfolio erst nach Baseline abstimmen.** Ein Vergleich von etwa 4 und 8 Workern bzw. einer gezielten Portfolioänderung ist sinnvoll, wenn Laufzeitkurven und Wiederholungen vorliegen. Mehr Worker sind keine automatisch schnellere Variante; Portfolio und Speicherbedarf ändern sich mit. Kein Abschalten vermeintlich unnützer Worker allein anhand ihrer Incumbentanzahl.

Pauschale Symmetriebedingungen zwischen Kabinen sind vorerst keine Priorität: feste unterschiedliche Starts können die Austauschbarkeit bereits aufheben. Zusätzliche Bedingungen dürfen keine erlaubten Überholungen oder Trajektorien entfernen.

Die unabhängige Passagier-IP löst den finalen **festen** Fahrplan praktisch sofort optimal. Das bestätigt die Zuordnung dieser Lösung, sagt aber nicht, dass die integrierte Passagierkopplung in der globalen Suche billig ist.

## Empfohlene Experimentreihenfolge

1. **Unveränderte Produkt-Baseline K39 einmal 60 Minuten durchgehend**, mit dem ursprünglichen importierten Seed, gleichem Domain-Fingerprint, 8 Workern und Seed 0. Zustände bei 1/2/5/10/20/30/60 Minuten aus demselben Lauf auswerten. Damit untersuchen wir zuerst, was mehr Zeit bewirkt. Mehrere unabhängige 10-Minuten-Neustarts ersetzen diesen Test nicht.
2. **Wiederholbarkeit prüfen:** anschließend zwei weitere Seeds mit jeweils 15 Minuten und identischer Startlösung. Das gibt eine erste Aussage über Streuung; bei starkem Unterschied den Langlauf wiederholen. Selbst gleicher Random-Seed garantiert beim parallelen Portfolio keinen identischen Verlauf.
3. **Eine Formulierungsverbesserung nach der anderen** gegen eingefrorene Baseline/Instanz/Seeds testen, zuerst sichere Zeitdomänen, danach gegebenenfalls kompakte Intervalle. Kleine exakte Vergleichstests müssen weiterhin bestehen. Keine gleichzeitige Änderung von Startlösung, Nachfrage, Modell und Workerzahl.
4. **Längere Läufe nur für gemessen hilfreiche Varianten.** Zielgrößen: UB, LB, Gap, bediente Personen, Zeit bis zu vereinbarten Kosten-/Schrankenzielen, letzter Fortschritt und Peak-RSS. Als Fortschrittsfenster die jeweils letzten 10 Minuten getrennt nach UB und LB berichten; etwa 0,1 % relative Verbesserung als beschreibende Schwelle verwenden, nicht als bewiesene Plateaugrenze oder automatische Stopregel.
5. Ein Arc-Flow-Vergleich mit gemeinsamer Startlösung bleibt später möglich. Er steht nicht vor dieser Diagnose des Hauptansatzes.

**Checkpoint-Hinweis:** `--resume-checkpoint` lädt in unserer Implementierung den validierten Fahrplan und die Passagierzuweisung als neuen Hint. Es stellt keinen vollständigen internen Solverzustand mit Suchbaum, gelernten Klauseln und Portfoliozuständen wieder her. Ein neuer 50-Minuten-Lauf vom besten Checkpoint ist deshalb ein Restart mit besserem Start, keine echte Fortsetzung des alten 10-Minuten-Laufs. Solche Experimente getrennt kennzeichnen.

## Noch fehlende Instrumentierung

- Getrennte Aufbauzeiten für Domainprüfung, Bewegung, Passagiere, Modellvalidierung und Hintaufbau.
- Extraktions-/Checkpoint-/Callbackgesamtzeit, Callbackanzahlen und phasenbezogene RSS-Samples.
- Ein gemeinsamer Zeitursprung für Runner, Optimizer und natives Solverlog.
- Laufendes strukturiertes Eventprotokoll: Der Runner schreibt `events.jsonl` derzeit erst nach Solverende; `solver.log` wird bereits fortlaufend geflusht, Checkpoints periodisch gespeichert. Für Langläufe ist inkrementelles JSONL sinnvoll.
- Reproduzierbar abgeleitete Tabellen für Presolve-Größen und UB/LB-Zeitpunkte. Bestehende `progress.csv` enthalten die benötigten Stichproben; obige Tabellen wurden aus den Original-JSONs/Logs gelesen.

Quellartefakte: `k20/product_300s_seed0_v2/`, `k20/unary_300s_seed0/`, `k39/product_600s_seed0/` jeweils unter `benchmarks/output/ddd_integrated_cp_sat/`. Die originalen Resultate und Logs wurden bei dieser Analyse nicht verändert.
