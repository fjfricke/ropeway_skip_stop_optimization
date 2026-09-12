# CP-SAT-Plateau: Code, native Suche und Entscheidung gegenüber Arc-Flow/DDD

Stand: 11.09.2026. Analyse vorhandener Quellen und Ergebnisse, ein Modellbau
ohne Solve. Keine neue Performancekampagne, keine Änderung am Optimizer oder
an der installierten Engine. OR-Tools 9.15.6755.

## Ergebnis

Die freie Max50-Formulierung fixiert weder 38 Kabinen noch All-Stop. Der
aktuelle Startplan enthält bereits 18 SKIP- und 1.007 STOP-Besuche. Die Suche
arbeitet, findet aber kaum bessere vollständige Pläne. Die Behauptung, sie
probiere keine anderen Flotten, lässt sich aus Incumbent-Callbacks nicht ableiten.

Zwei Engpässe sind zu unterscheiden: Das Erzeugen einer besseren gemeinsamen
Bewegung und Passagierzuordnung gelingt selten; die globale Relaxation bewertet
die vielen offenen Alternativen zu optimistisch. Ein besserer Suchstart oder
eine andere Verzweigung adressiert zunächst nur den ersten Engpass.

Neue konkrete Befunde dieser Analyse:

- In den beiden jüngsten Hochlastläufen: **102 native Scheduling-LNS-Aufrufe,
  keine Verbesserung und kein abgeschlossenes Teilproblem**.
- Die native Scheduling-Nachbarschaft lässt abwesende Intervalle ausdrücklich
  frei. Zusätzliche Kabinen sind dort nicht generell gesperrt. Kleine ausgewählte
  Intervallmengen ergeben dadurch nicht zwingend kleine Optimierungsprobleme.
- Eine STOP-Bewegung hat drei physische Ressourcenintervalle. Nicht freigegebene
  präsente Intervalle können ihre gemeinsame STOP-Entscheidung weiter festhalten.
- In zwei Zeitfenster-Generatoren des veröffentlichten v9.15-Quellcodes fällt
  eine fehlende Übersetzung von Listenpositionen zu Constraint-IDs auf. Dies ist
  separat zu reproduzieren; der Anteil am Ropeway-Plateau ist **nicht gemessen**.
- Die manuelle Dispatch-Symmetrie kann bei früher Einfügung einer neuen Kabine
  eine Umbenennung vieler bestehender Trajektorien verlangen. Sie verhindert
  jedoch keine spätere Einfügung; der letzte Seed-Dispatch liegt bei 291,909091 s.

Die Daten und heruntergeladenen Enginequellen sind unter
[`cp_sat_plateau_audit_20260911_v1`](../../benchmarks/output/cp_sat_plateau_audit_20260911_v1/audit.json)
mit SHA-256 abgelegt. Historische Ergebnisse bleiben unverändert.

## Modellvertrag und Zielfunktion

[`reservoir_cp_sat_movement.py`](../../src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_cp_sat_movement.py)
baut 50 optionale Kabinenketten. `active[k,0]` ist frei; Aktivität bildet je
Kabine ein Präfix, Rückkehr ist nur am Port möglich. Die Flottenlabels bilden
ebenfalls ein Präfix; Dispatchzeiten sind nach Label sortiert. Aufeinanderfolgende
Zeiten werden exakt aus Route und Waiting berechnet. Es gibt keine freie Lücke.
Das ist das bestehende Single-Use-Reservoir, kein mehrfacher Einsatz derselben Kabine.

[`reservoir_cp_sat.py`](../../src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_cp_sat.py)
setzt Bewegungen als Hints. Gleichheitsfixierungen werden nur bei explizitem
`fixed_plan` beziehungsweise Diagnoseprofil hinzugefügt. Der Cutoff ist die
geprüfte Seed-UB und schließt keine bessere Lösung aus. Ein exakter Solver muss
keinen schlechteren vollständigen Zwischenfahrplan akzeptieren, um eine bessere
Lösung zu beweisen oder zu finden. Das Entfernen des Cutoffs ist deshalb keine
begründete Lösung für eine vermeintliche lokale Kostenbarriere.

[`cp_sat_passenger.py`](../../src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_passenger.py)
koppelt jede positive ganzzahlige Ride-Menge an STOP am Einstieg und Ausstieg,
Freigabe, Horizont und Abschnittskapazität. Beim Reisezeitziel gilt äquivalent:

\[
C=\sum_{\text{bediente Personen}}(a-r)
  +\sum_{\text{unbediente Personen}}(H-r).
\]

Eine zusätzlich ausgelieferte Person spart bei sonst unverändertem Plan
`H-a`. Eine zusätzliche leere Kabine allein hat keinen Zielbeitrag. Es gibt
keine Flottenstrafe, aber auch keine Belohnung für bloße Aktivierung. Mehr
Nachfrage und mehr erlaubte Kabinen garantieren keinen Nutzen weiterer
gleichzeitig fahrender Kabinen: physische Ressourcen und andere Personen können
betroffen sein. Bei Max50 ist die freie optimale Kostenfunktion in der erlaubten
Maximalflotte monoton nichtsteigend, da unbenutzte Kabinen erlaubt sind. Das
beweist keinen strikt positiven Nutzen der 39. eingesetzten Kabine.

Der letzte Nachfrageversuch änderte nur D=1.280 auf D=3.074; **das Ziel blieb
Reisezeit**. Seine 2.598 bedienten Personen sind kein Nachweis maximaler
Bedienung, auch nicht bei festgehaltenem Fahrplan. Ein Kapazitätsvergleich muss
das vorhandene Ziel `unserved` verwenden und eine passende feste
Passagier-Kapazitätsreferenz bestimmen. Die frühere Fixed-Start-Kapazitätsmessung
hat einen anderen Betriebsvertrag.

## Was die native Suche tatsächlich macht

CP-SAT kombiniert SAT/Constraint-Propagation mit gelernten Konflikten,
LP-Relaxationen und einem Portfolio aus vollständiger Suche, Schrankenverfahren
und Heuristiken. Dies beschreibt die Veröffentlichung von
[Perron, Didier und Gay (CP 2023)](https://doi.org/10.4230/LIPIcs.CP.2023.3).
Exakte Beweisfähigkeit bedeutet keinen stetigen oder zeitlich garantierten
praktischen Fortschritt.

Der Hochlastlauf Seed 1 aktiviert acht Vollproblem-Worker:
`core`, `default_lp`, `fixed`, `max_lp`, `no_lp`, `quick_restart`,
`quick_restart_no_lp`, `reduced_costs`. Daneben laufen allgemeine und
Scheduling-LNS-Verfahren. Der Worker `quick_restart_no_lp` verbessert den
Incumbent auch außerhalb der LNS-Aufrufe. Die Suchstatistik enthält beispielsweise
265.518 Branches dieses Workers; dies sind keine 265.518 geprüften Gesamtfahrpläne.

| Native Scheduling-LNS | Aufrufe Seed 0 / 1 | Verbesserungen | Abgeschlossen |
|---|---:|---:|---:|
| intervals | 15 / 14 | 0 / 0 | 0 % / 0 % |
| precedences | 11 / 10 | 0 / 0 | 0 % / 0 % |
| resource windows | 15 / 11 | 0 / 0 | 0 % / 0 % |
| time window | 11 / 15 | 0 / 0 | 0 % / 0 % |

Quelle: die beiden ursprünglichen `process.log` im
[`Nachfrageversuch`](../../benchmarks/output/reservoir_demand_probe_20260911_v2/).
`Improv/Calls` ist grundsätzlich Verbesserung gegen die gewählte Basislösung,
nicht notwendigerweise gegen die globale beste UB. Hier sind beide null.
`Closed` bezeichnet OPTIMAL oder INFEASIBLE im jeweiligen eingeschränkten
Teilproblem, keinen globalen Beweis.

Die vier Generatoren enden bei Schwierigkeiten von ungefähr 0,004 bis 0,014.
Im Enginecode sinkt diese Größe bei nicht abgeschlossenen Nachbarschaften. Ihr
deterministisches Zeitbudget bleibt hier 0,1; das ist **keine Zehntelsekunde
Wandzeit**. In Seed 1 kosten einzelne Scheduling-Aufrufe im Mittel 4,66 bis
7,23 Sekunden. Diese Zeiten dürfen wegen paralleler Worker nicht als additive
Gesamtlaufzeit ausgegeben werden.

Im veröffentlichten
[`cp_model_lns.cc`, v9.15](https://github.com/google/or-tools/blob/v9.15/ortools/sat/cp_model_lns.cc)
startet `GenerateSchedulingNeighborhoodFromRelaxedIntervals` vom vollständigen
Modell, fixiert ausgewählte Präsenzen und ergänzt Ressourcenpräzedenzen.
Abwesende Intervalle werden freigegeben. Die zugehörigen
[`Schnittstellen`](https://github.com/google/or-tools/blob/v9.15/ortools/sat/cp_model_lns.h)
beschreiben diese Einschränkung auf Basis der Incumbent-Intervalle.

Daraus folgt für unser Modell: Die Passagiermengen und Produkte werden nicht
pauschal mit der Bewegung außerhalb des Zeitfensters fixiert. Zusätzlich können
ungenutzte Kabinen frei bleiben. Ihre weitere Einengung durch Propagation hängt
vom erzeugten Teilproblem ab und wurde nicht instrumentiert. Die geringe
Intervall-Schwierigkeit darf daher nicht als Prozentzahl aller freien
Solvervariablen interpretiert werden.

Umgekehrt reicht es nicht unbedingt, eines der drei STOP-Ressourcenintervalle
freizugeben: Ein anderes präsentes Intervall kann weiterhin STOP erzwingen.
Presolve kann Hilfsvariablen zusammenfassen, beseitigt aber nicht diesen logischen
Zusammenhang. Welche konkreten STOPs jeder native Aufruf tatsächlich freigab,
steht nicht im bisherigen Log. Das ist ein struktureller Erklärungsansatz,
keine gemessene Häufigkeit gesperrter Routenwechsel.

## Auffälligkeit in den nativen Zeitfenster-Generatoren

Im gespeicherten v9.15-Quelltext:

1. `PartitionIndicesAroundRandomTimeWindow` liefert `index_in_input_vector`.
2. `SchedulingTimeWindowNeighborhoodGenerator` und
   `SchedulingResourceWindowsNeighborhoodGenerator` übernehmen diese Werte
   direkt in `intervals_to_relax`.
3. `GenerateSchedulingNeighborhoodFromRelaxedIntervals` vergleicht diese Menge
   mit den **Constraint-IDs** der Intervalle.

Beispiel: Aktive Intervall-IDs `[10,30,70]`, gewählte Listenposition `[1]`.
Erwartete Freigabe ist Intervall 30; die untersuchte Übergabe verwendet 1.
Dieser Unterschied ist als kleiner Indexraum-Zeuge in `audit.json` dokumentiert.
Im unpresolvten Ropeway-Modell beginnen die Intervall-IDs tatsächlich mit
`[4,16,23,30,37,...]`; Listenpositionen und IDs sind also unterschiedliche Größen.
Die native LNS arbeitet auf der presolvten Darstellung; deren konkrete
Fehlfreigaben wurden hier nicht ausgelesen.

**Status:** nachvollziehbare Auffälligkeit im veröffentlichten Quellcode,
noch kein kompiliertes natives Minimalrepro und keine gemessene
Performanceursache. Sie betrifft zunächst die Auswahl einer Einschränkung,
nicht die physikalische Validität der unabhängig geprüften Pläne. Die beiden
anderen Scheduling-Generatoren und die Vollproblem-Suche erklären sich dadurch
nicht. Keine Engine wurde gepatcht und kein Issue an Dritte gesendet.

## Dispatch-Symmetrie: sinnvoll, aber möglicherweise ungünstig für Einfügungen

Bei identischen Kabinen ist nach Dispatch sortierte Benennung global verlustfrei.
Eine zusätzliche Kabine mit höchstem bisher unbenutztem Label kann jedoch bei
unveränderten bestehenden Labels erst nach dem letzten Dispatch fahren. Eine
Einfügung früher in die Abfolge erfordert gegebenenfalls Umbenennung eines
ganzen Suffixes einschließlich seiner Passagiervariablen. Allgemeine LNS arbeitet
an Variablen, nicht automatisch an dieser semantischen Umbenennung.

Im konkreten Seed sind die 38 Dispatches zwischen 28,000001 und 291,909091 s,
die Nachfragefreigabe ist 300 s. Die Symmetrie verhindert daher ausdrücklich
**nicht**, eine 39. Kabine ab etwa 292 s zu starten. Sie ist keine vollständige
Erklärung des Plateaus. Eine isolierte Ablation der Dispatch-Zeitordnung wurde
in den durchsuchten Ergebnisdokumenten nicht gefunden. Das Aktivitätspräfix
könnte dabei bestehen bleiben; Exporte müssten anschließend kanonisch umbenannt
werden. Der Nachteil wäre eine größere Labelsymmetrie in der globalen Suche.

## Warum der globale Bound schwach bleibt

Die früheren
[`Diagnosen`](reservoir_diagnostics_20260911.md) sind dafür stärkere Evidenz als
eine reine Vermutung über Modellgröße:

| Freie Entscheidungen, R mit D=1.280 | Ergebnis |
|---|---|
| Passagiere bei festem Fahrplan | Optimum in ca. 3–4 s |
| Zeiten bei festen Halten und Passagieren | Optimum in ca. 9–13 s |
| Zeiten und Passagiere bei festen Halten | ca. 15 % Gap im Teilproblem |
| Zusätzlich STOP/SKIP frei, Einsatzketten noch fest | native LB auf 0 geklemmt |
| Volles Max50 | ebenfalls keine positive native LB |

Es ist also weder nur die optionale Flotte noch allein der Waitingbereich.
Bei offenen Routen, Mengen und Zeiten ist die Kopplung zwischen physischer
Fahrbarkeit und nutzbarer zeitlicher Beförderung in der Relaxation schwach.
Das erzeugt zu optimistische Restprobleme und erschwert das Verwerfen von
Suchzweigen. Beim aktuellen Reisezeitausdruck werden mögliche Bedienungen als
Abzug von der Nichtbedienungskonstante geschrieben. Der rohe globale Bound
im Hochlastlauf bleibt ungefähr bei −915.772,55 Passagiersekunden und wird
deshalb korrekt durch die bekannte Nichtnegativität auf 0 angehoben. Dies ist
keine negative physikalische Kostenlösung und kein Vorzeichenfehler im Zertifikat.

Die Multiplikation ist nicht isoliert als Ursache nachgewiesen:
[`binäre Produkte`](reservoir_binary_cost_comparison_20260911.md) waren schwächer,
und auch das lineare Kapazitätsziel hat in schwierigen früheren Fällen große
Gaps. Native `PositiveProduct`-Cuts sind in den Logs vorhanden.

Die gemeinsame gültige R-LB 209.409,890300 gilt für D=1.280 und lässt dort etwa
43,21 % Gap. Sie darf nicht unverändert auf den neuen D=3.074-Fall übertragen
werden. Höhere LBs aus festgehaltenen Teilproblemen sind keine globalen Bounds.

## Arc-Flow und DDD im Vergleich

Bei zeitexpandiertem Arc-Flow ist die Zeit eines gewählten Arcs bekannt.
Passagierkosten werden dadurch linear; Flusserhaltung und Kapazität bilden
zusammen eine umfangreichere Darstellung der gemeinsamen Alternativen.
Die K20-Batch-Instanz hat bereits eine LP-Untergrenze am Integeroptimum. Das
erklärt den schnellen Beweis für **diesen Fall**, nicht generell alle kleinen K.

Die
[`A–D-Kampagne`](../../benchmarks/output/arc_flow_passenger_campaign_20260910_v2/comparison.md)
zeigt den Unterschied deutlich:

- K20 Batch: Legacy bewiesen optimal nach 23,32 s; `alight_links` nach 14,46 s.
- K20 verteilte Nachfrage: auch Arc-Flow verbessert den Seed im Budget nicht.
- K39 No-Wait: Root-LP etwa 316–813 s, kleine UB-Verbesserungen, bester gemessener
  Gap der Kampagne 66,95 %. Alle dortigen K39-Läufe melden einen Suchknoten.
- Explizites Waiting hatte in einem älteren K20-Versuch schon rund 829 s
  Netzaufbau benötigt; der Solve startete nicht mehr.

Quelle der historischen Einordnung:
[`Solveraudit`](solver_history_audit.md). Die Fälle haben nicht alle dieselbe
Domäne; insbesondere sind K39-No-Wait-Bounds keine Reservoir-Waiting-Bounds.

Der
[`Arc-Flow-Netzbuilder`](../../src/ropeway_skip_stop_optimization/optimization/ddd/arc_flow_network.py)
iteriert pro erreichbarem Zeitknoten, Route und erlaubtem Waitingwert. Seine
aktuelle explizite Darstellung ist kein skalierbarer Ersatz für den freien
1.200-s-Mikrosekunden-Waitingbereich im Reservoir.

DDD ist kein zusätzlicher Solver wie Gurobi oder CP-SAT. Die vorhandenen
[`Verfeinerungswege`](../../src/ropeway_skip_stop_optimization/optimization/ddd/network_refinement.py)
bauen reduzierte Zeitnetze, lösen Masterprobleme und prüfen/rekonstruieren
exakte Bewegung, teilweise wiederum mit CP-SAT. Frühere Supports waren häufig
gemeinsam nicht fahrbar; weitere Mastervarianten und CG beseitigten das nicht.
Im aktuellen Reservoir verbessert die Zeitmomentrelaxation zwar die globale LB,
aber reine Zeitverfeinerung schließt Fahrzeug-/Passagiermischung und Integergap
nicht automatisch. Ein vollständiger konvergenter Abschluss ist dort noch
nicht implementiert. Siehe
[`Hybridbefund`](reservoir_hybrid_pilot_20260910.md) und
[`Merge-CG-Gate`](ddd_merge_aware_root_gate.md).

## Konkrete Reihenfolge für weitere Arbeit — noch nicht ausgeführt

1. **Enginebefund klären.** Ein natives Minimalrepro der Indexübersetzung und
   Prüfung einer unveränderten veröffentlichten Engine mit nachgewiesenem Fix,
   falls verfügbar. Bis dahin zwei betroffene Generatoren isoliert deaktivieren
   wäre ein möglicher Vergleich, kein vorausgesetzter Gewinn. Keine pauschale
   Schuldzuweisung an OR-Tools und kein eigener Suchalgorithmus.
2. **Native LNS-Budgets isoliert prüfen.** Zunächst nur
   `lns_initial_deterministic_limit=1.0` gegen 0.1. Die beobachteten 102 nicht
   abgeschlossenen Scheduling-Aufrufe begründen die Hypothese. Mehr Zeit pro
   Aufruf könnte Reparaturen ermöglichen, aber auch die Zahl verschiedener
   Versuche reduzieren. Physik, Flotte, Ziel und Seed bleiben identisch.
3. **Explizite Flottenverzweigung in einem Engineworker.** Eine redundante
   Integergröße `K_used = sum(active[k,0])`, dazu ein nativer
   `PARTIAL_FIXED_SEARCH`-Worker mit größeren Werten zuerst. Andere Worker
   behalten automatische Suche. K wird nicht festgelegt; Backtracking,
   Propagation und Optimierung bleiben in CP-SAT. Ein früher Versuch mit 50 kann
   selbst schwer sein; das ist eine überprüfbare Suchpräferenz, kein Beweis,
   dass 50 sinnvoll sind. Die Parameter-API unterstützt
   [`subsolver_params` und eigene Strategien](https://github.com/google/or-tools/blob/v9.15/ortools/sat/sat_parameters.proto).
4. **Dispatch-Symmetrie erst separat ablatieren.** Nur wenn die vorigen Befunde
   keinen materiellen Fortschritt liefern. Nicht zugleich Hintprofil, Kosten
   und Ressourcen ändern. Vollständige Hints, `compact_fixed`, `merged_exit`,
   aggregierte Passagierkopplungen und Reisezeitschranken sind bereits getestet;
   sie werden nicht als neue Ideen verkauft.
5. **Beweisleistung separat beurteilen.** `lb_tree_search` ist im jüngsten
   Zwölfworker-Portfolio nicht aktiv. Ein gezielter nativer Bound-Worker ist
   eine kleine weitere Hypothese, keine stärkere Formulierung. Eine eingetragene
   analytische Konstante macht die LB-Anzeige besser, aber liefert keine neue
   Information gegenüber derselben für alle Solver angerechneten Schranke.

Für die konkrete Frage nach zusätzlicher Bedienung muss ein solcher Vergleich
auf dem vorhandenen Hochlast-Reservoir zusätzlich sauber das Ziel `unserved`
verwenden. Eine feste Passagier-Kapazitätsoptimierung des gemeinsamen Startplans
trennt reine bessere Zuweisung von besserer Bewegung. Die freien Modelle bleiben
Max50. Erfolg heißt bessere geprüfte Bedienung/Kosten beziehungsweise stärkerer
vergleichbarer Bound, nicht bloß mehr aktivierte oder leere Kabinen. Verschiedene
K in Incumbents sind ein zusätzliches Suchdiagnostikum; das Fehlen davon beweist
nicht, dass intern nie andere K versucht wurden.

**Entscheidung:** Kein weiterer unveränderter Langlauf und kein pauschaler
Wechsel zu bestehendem DDD/Arc-Flow. Die genannten nativen Suchmechanismen
verdienen einen begrenzten, einzeln auswertbaren Test, bevor ein weiterer
Modellkern gebaut wird. Das Potenzial für bessere Incumbents ist plausibel,
das für einen kleinen globalen Reservoir-Gap weiterhin unbewiesen. Sollten
auch diese Tests scheitern, ist daraus keine Rechtfertigung für eine neue eigene
LNS-Schleife oder beliebig weitere Solverportierungen abzuleiten.
