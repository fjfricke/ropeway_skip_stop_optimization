# Ropeway: Audit der bisherigen Solverläufe und Entscheidungsvorlage

Stand: **9. September 2026**. Bestandsaufnahme des lokalen Ergebnisarchivs und der aktuellen Implementierungen; keine neue Optimierungskampagne. Software-HEAD `d12807a`, Branch `ddd`, mit den bereits vorhandenen uncommitteten CP-/Waiting-/Horizon-/Reservierungsänderungen. Historische Läufe stammen aus unterschiedlichen Codeversionen. Der aktuelle Code erklärt die heutige Implementierung, ersetzt aber keine Rekonstruktion jedes damaligen Checkouts.

**Empfehlung: auf CP-SAT mit Produktkodierung und Exit-Waiting als Hauptentwicklung festlegen; gelabeltes Arc-Flow als exakte No-Wait-Referenz behalten.** Das anonyme Arc-Flow erhält höchstens einen kontrollierten No-Wait-Versuch mit besserem Seed. Gemeinsame Fahrplanprüfung und Integer-Passagiernachoptimierung verbinden diese vorhandenen Bausteine. Kein weiterer Solverzweig und kein Ausbau der Reservierungsheuristik vor der Präsentation.

Dafür spricht die vorhandene Evidenz: Arc-Flow löst K20 schnell optimal; CP-SAT Waiting verbessert bei K39 seine Lösung bis kurz vor dem Zeitlimit. Mehrere andere Verfahren stagnieren, erschöpfen ihre aktuelle Verfeinerung oder bezahlen vor allem Modell-/Root-Aufwand. **Noch kein Verfahren hat für den dichten K39-Fall einen kleinen globalen Gap oder einen Vorteil gegenüber All-Stop K38 gezeigt.**

## 1. Umfang und Aussagegrenzen

Der automatisierte Scan erfasst **1.058 JSON-Dateien** unter `benchmarks/output`: 507 enthalten erkannte Ergebnisse/Diagnosen, 538 sind weitere Manifeste, Konfigurationen oder Auswertungen. 13 Dateien über 30 MB wurden nach Pfad/Größe inventarisiert, aber nicht vollständig geladen; darunter große Bewegungsartefakte und Checkpoints. Keine JSON-Lesefehler. Zusätzlich wurden alle **50 JSONL-Dateien mit 11.152 Zeilen** gelesen; keine Parsefehler. Das Archiv hat rund 25 GB, einschließlich 2.128 SOL-Dateien, die überwiegend Zwischenstände und keine unabhängigen Läufe darstellen.

Aus den JSONs entstehen **607 Ergebnis-/Diagnoseeinträge**: 412 Ergebnisdokumente, 135 verschachtelte Diagnosefälle und 60 Artefaktsnapshots. **Das sind ausdrücklich keine 607 unabhängigen Experimente.** Zusammenfassungen, Originalresultate und Exporte können denselben Lauf mehrfach beschreiben. 382 dieser Einträge enthalten Verlaufssamples, insgesamt 10.386 Punkte. Weitere 8.613 Kampagnenereignisse liegen separat vor; sie können sich mit eingebetteten Verläufen überschneiden.

Die folgenden Tabellen verdichten alle gefundenen Methodenfamilien und die entscheidenden Vergleiche. Das vollständige maschinenlesbare Register bewahrt jeden erkannten Eintrag samt Quelle, Abschnitt, originalem Metrikfeld, Zeitbasis und Status. Kein historischer Fahrplan wurde in diesem Audit pauschal neu zertifiziert. Smoke-/Build-/Feasibility-Tests, fehlgeschlagene Vorläufe und Duplikate sind im Register enthalten, aber keine gleichwertigen Qualitätsbenchmarks.

- [Alle Ergebnis-/Diagnoseeinträge](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/docs/findings/solver_history_runs.csv)
- [Eingebettete UB-/LB-Verläufe](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/docs/findings/solver_history_progress.csv)
- [Kampagnenverläufe: globale Zertifikate getrennt von lokalen Solvermeldungen](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/docs/findings/solver_history_campaign_progress.csv)
- [JSON-Dateiinventar](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/docs/findings/solver_history_files.csv), [JSONL-Dateiinventar](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/docs/findings/solver_history_jsonl_files.csv)
- [Extraktionsskript](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/audit_solver_history.py), [lokaler Audit-Arbeitsordner](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/solver_history_audit)

Im CSV heißt `ub` zunächst nur „aus dem angegebenen Ergebnisfeld extrahierter Wert“. Bei OIP ist dies die sekundäre Zielkomponente, bei einer Relaxationsdiagnose keine zulässige UB des Originalproblems. `curve_units` und `objective_semantics` warnen vor solchen Vermischungen. Die Tabellen hier übernehmen nur passend eingeordnete Werte.

## 2. Welche Resultate sind vergleichbar?

Für die heutigen Fixed-K-Journey-Time-Fälle gilt: Summe der Zeiten von Nachfragefreigabe bis Ziel für bediente Personen, plus `T − Freigabe` je unbedienter Person. Im K39-B-Fall sind alle 1.280 Personen bei t=0 freigegeben, T=H=1.200 s, Kapazität 8. Niemanden zu bedienen kostet deshalb **1.536.000**. Weniger unbediente Personen ist eine wichtige Kennzahl, aber kein lexikografisch vorrangiges Ziel dieses Modells.

| Vergleichsgruppe | Was zusammengehört | Was getrennt bleiben muss |
|---|---|---|
| Frühes EAN, `three_station_v0` | Formulierungen derselben 3-Stationen-Instanz mit 3.480 Personen | Keine Rangliste mit Five-Station-B/1.280 Personen |
| Five-Station-B, Fixed-K, No-Wait | Gleiches K, Anfangssnapshot, Kapazität, Nachfrage, Kandidaten, Horizonte und Ziel | `canonical` und `balanced_reference` sind unterschiedliche Starts |
| K39 Exit-Waiting | W=1.200 s, 1-us-Raster, gleicher Snapshot und endlicher Vertrag | No-Wait-LB gilt nicht automatisch für die größere Waiting-Domäne |
| K38 All-Stop vs. K39 Skip-Stop | Betriebliche Referenzen bei gleicher Nachfrage/Zeitspanne | Andere Flotte und anderes Startlayout; kein kontrollierter Solververgleich |
| Warmup B=0 vs. B=300 | Kontrollierter Versuch mit gleicher Anlauf-Seedfamilie | Releases/Horizont verschoben; andere Domäne, kein bloßer Neustart |
| EAN OIP / freie Flotte | Primär unbediente Personen, sekundär bediente Passagierzeit, tertiär aktive Kabinen | Sekundäre Sekunden und primäre Personen-/Boundmeldungen nicht mischen |
| Neues Reservoir-Arc-Flow | Maximalflotte, Dispatch, Anlauf/Recovery, lexikografisches Ziel | 2.560 Personen und andere Betriebskonstruktion; nicht direkt K39-Fixed-K |
| Feste Bewegung / Merge-Gate / Pricing | Isolierte Bausteine mit eindeutigem Teilproblemziel | `OPTIMAL` bedeutet hier nicht global optimaler Passagierfahrplan |

**Startlösung und Anfangsbedingungen unterscheiden:** Ein besserer Hint lässt die zulässige Menge unverändert. Andere feste Anfangspositionen ändern das Problem. Bei K38 startet `balanced_reference` aus All-Stop; bei K39 aus einer All-Stop- und 38 All-Skip-Referenztrajektorien. Deren Zukunft ist im Solver frei, der Anfangssnapshot ist fest. Genau 39 aktive Kabinen sind deshalb keine einfache Erweiterung des K38-Problems um eine optional unbenutzte Kabine.

Die endliche Horizontdefinition ist für diese Bewertung akzeptiert. Ergebnisse werden als endliche Fahrpläne interpretiert; eine periodische oder sichere unendliche Fortsetzung wird nicht unterstellt und hier nicht als neues Pflichtgate eingeführt.

## 3. Gesamtvergleich der bisherigen Methoden

UB kleiner, LB größer ist besser. Sekundenwerte gerundet. Zeiten sind tatsächliche gespeicherte Zeiten, soweit vorhanden; ungefähr bezeichnet Rundung oder mehrere vergleichbare Läufe. Unterschiedliche Tabellenzeilen sind nur innerhalb ihrer benannten Domäne vergleichbar.

| Ansatz / Versuch | Ergebnis und Modellgröße | Verhalten / Konsequenz |
|---|---|---|
| Diskreter Zeit-MILP-Prototyp, 23 Kabinen / 2.400 Schritte | 40,1 Mio. Binärvariablen, 43,7 Mio. Zeilen, 240,2 Mio. Nichtnullen; Indexaufbau 702,4 → 16,6 s | Python-Aufbau massiv verbessert, Expansion bleibt. Kein vollständiger UB/LB-Endverlauf für diesen Großtest vorhanden. Historische Referenz. |
| Base EAN, drei Stationen, 300 s | Ohne Verbesserungen UB 2.705.558 / LB 2.502.419; 151.974 Variablen / 484.989 Zeilen | Löst, aber großes Ereignis-/Headway-/Passagiermodell. |
| EAN Pruning + Strengthening, gleicher 300-s-Fall | UB 2.704.537 / LB 2.532.474; 82.398 / 232.560 | Gap unter 10 % nach etwa 34 statt 105 s. Nützliche belegte Implementierungsverbesserung. |
| EAN affine Zeiten + First-Slot + projizierte Boardingzeit | 300 s: 2.704.483 / 2.582.536; 74.734 / 166.756. 900 s: 2.704.423 / 2.620.817 | Bessere LB, nur kleine UB-Änderung. Verbesserte 900-s-Variante etwa 3,09 % Gap, alte Baseline 6,50 %. |
| EAN Shared/Eager, Five-Station Waiting | Zulässige Variante 663.895 / 463.426 nach 600 s; 90.714 / 407.273 | Nicht mit der absichtlich gelockerten Variante 568.699 verwechseln: diese verletzt 18 Headwaypaare. |
| EAN OIP / optimierte Anfangsplatzierung | 300-s-Startvergleiche unten; großer Double-All-Stop-Test 3,76 Mio. Variablen / 8,81 Mio. Zeilen, etwa 1 h | Andere Zielhierarchie; zunehmende Freiheit und Symmetrie vergrößern das Modell erheblich. Keine Evidenz für „freie Starts machen es einfach“. |
| Pairwise vs. Lattice vs. Slots am isolierten Merge | 10+10: gleicher Wert 1.291,5 in 0,82 / 2,05 / 4,70 s; 20+20 nach 60 s gleiche UB 4.833, beste LB bei Pairwise 2.525 | Zusätzliche Extended Formulations waren im Gate nicht überlegen. Keine neue Integration priorisieren. |
| Fixed-Movement Passenger-IP / LP | 3 Stationen IP etwa 0,005 s, 737 Variablen; 5 Stationen etwa 0,020 s, 3.550 Variablen; Adapter/Aufbau zusätzlich | Sehr guter gemeinsamer Nachoptimierer. LP ist im Allgemeinen nicht ganzzahlig; bekanntes Odd-Cycle-Gegenbeispiel. Integer-IP behalten. |
| DDD Phase 0 / kleine Enumerationsfälle | Kleine Bounds 1 bzw. 4 werden in etwa 0,007–0,016 s geschlossen | Belegt Korrektheit/Funktion einzelner Refinement-Schritte, keine Skalierungsprognose für K39. |
| Adaptiver Passenger-DDD / Support-Lifting, altes K19 | Früher 50/50 gewählte Supports physisch unzulässig; stärkere Zeit-LB etwa 409.360; Nearest-Support-UB 622.436 statt Bootstrap 1.422.004 | Bewegungsprojektion ist der Engpass; guter fraktionaler Support ist nicht automatisch gemeinsam fahrbar. |
| DDD Timed-Flow/Core-/Resource-Window-/Selective-Path-Varianten | In den 20-Runden-ABs LB etwa 409.360 unverändert, Bootstrap-UB unverändert; rund 49–80 s. Selektive Pfade fügen u. a. 7.685 Prefixvariablen hinzu | Kleinere Cores oder größere Modelle erzeugten hier keinen entscheidenden Fortschritt. Kein pauschaler Langlauf. |
| Frozen-Trajectory-Pricing | Mehrere Focus-/zeitgekoppelte Varianten nach 2–30 s `unknown`; ein isolierter Passenger-Flow-Test optimal in 0,507 s | Teilproblemprüfung, kein globaler Fahrplanvergleich. Die schnelle Teilvariante beweist nicht, dass vollständiges Pricing billig ist. |
| Adaptives DDD Waiting, kanonisches K20 | W-Raster 0,5/1/2/5 Headways: LB rund 402.878–403.691, UB bleibt 535.935; Ende nach 40–99 s trotz 900-s-Budget | `refinement_stalled`: mehr Budget allein erzeugt keine weiteren Verfeinerungen. |
| Vollständiges gelabeltes Arc-Flow, K17–22 | No-Wait-K-Sweep löst alle sechs Skip-Fälle optimal in 23–265 s | Stärkste Evidenz für kleine/mittlere exakte Referenzen. Startpolitik beachten. |
| Vollständiges gelabeltes Arc-Flow, balanced K20 | Optimum **525.731** in etwa 16–25 s; im Bakeoff 180.555 Bewegungs-/Passagiervariablen, 288.436 Zeilen | EAN nach 30 min noch 605.613. Klarer lokaler Gewinner. |
| Vollständiges gelabeltes Arc-Flow, balanced K39 | 30 min: 1.441.586 / 407.377; etwa 59 min: 1.408.270 / 429.449; 355.304 Variablen, 556.679 Zeilen | Lange Root-Verarbeitung und schlechte Incumbents. Im 30-min-Lauf überhaupt keine UB-Verbesserung. |
| Vollständiges gelabeltes Arc-Flow mit explizitem Waiting | K20: 829 s Netzbau + 12 s Seed, etwa 842 s gesamt, kein Solve; UB nur Seed 535.935, LB 0 | Kein Suchplateau: Zustands-/Zeitnetzexpansion verbraucht das Budget vor dem Solve. |
| Exakt anonymes Arc-Flow | K20 gleiches Optimum in 135 statt 24 s; K39 etwa 59 min 1.376.001 / 441.920, 397.553 Zeilen | K20 langsamer; K39 beste gespeicherte vollständige No-Wait-LB. Bisher Einzelvergleich, kein allgemeiner Geschwindigkeitsbeweis. |
| Trajectory Root-CG, Pair-only | K20 kann LB 525.731 zertifizieren, UB bleibt 635.520. K39 mit globaler CP-Primalhilfe: 1.326.951 / 315.691 in etwa 529 s | Root-LP kann fertig sein, obwohl die Integerlösung schlecht bleibt. Exaktes Pricing allein schließt diesen Integer-Gap nicht. |
| CG Merge-/Resource-Windows / Batch Pricing | K20 120 s: Pair-LB 518.241, Merge 510.348, alle Fenster 488.713, Batch 473.590; gleiche UB 635.520. Manche K39-Gates LB 0 | Zusätzliche Stärke kostet zu viel oder koordiniert Kandidaten nicht ausreichend. Kein nachgewiesener Gewinn. |
| CG Diving / Cohort / Merge-Corridor | K20 Diving etwa 316 s: 635.520 / 523.757; Cohort K39 UB 1.403.874; globaler CP-Schritt oben besser | Beschränkte Nachbarschaften bringen keinen stabilen Durchbruch. Kein fertig getesteter vollständiger Branch-Price-and-Cut-Solver. |
| Partial-Passenger-Benders | K20 120 s, Core 20 %: LB 48.644; Core 40 %: 85.163; vollständige Referenz 525.731 | Nur 9,25 bzw. 16,20 % des bekannten Wertes, nach erstem Master praktisch flach. Core-Point-Cuts kosten zusätzlich. |
| Älteres Trajectory-Reservoir-CG, K19 / halbe Nachfrage | 2 h: UB **655.272 unverändert**, LB 508.300; 64 Runden; 7.223 s Gesamtzeit | Letzte LB-Verbesserung bereits nach etwa 3.520 s summierter Rundenzeit. Weitere Stunde brachte weder bessere UB noch nennenswert höhere LB. |
| Neues anonymes Reservoir-Arc-Flow | Maximal 57 Kabinen, 2.560 Personen, 159.014 Knoten / 312.645 Arcs, 2,71 Mio. Passagiervariablen / 3,31 Mio. Zeilen | Smoke endet nach 278 s: primär null Unbediente bewiesen, sekundärer 38-Kabinen-Seed 1.290.660 unverändert. Kein gespeicherter erfolgreicher langer Sekundärversuch. |
| Integrierter CP-SAT, K20 Produkt / Unary | Beide halten Seed-Optimum 525.731 nach 300 s; Produkt-LB 419.877, Unary-LB 0 | Produkt klar bessere nächste Baseline. K20 als Proof-Aufgabe wesentlich schlechter als Arc-Flow. |
| Integrierter CP-SAT, K39 No-Wait | Ursprünglich 600 s: 1.272.673 / 402.843. Neuer gemeinsamer-Seed-Lauf: 1.262.100 / 396.587 | Bessere UBs als gespeicherte vollständige MIPs, schwächere LB als anonymer Stundenlauf; ungleiche Budgets/Seeds beachten. |
| Integrierter CP-SAT, K39 Exit-Waiting | 600 s: **1.022.076 / 76.435**, 1.104/1.280 bedient | 19,02 % besser als frischer No-Wait-Kontrolllauf, aber 92,52 % Gap. UB bis direkt vor Ende verbessert. |
| CP-SAT Warmup B=300 | 600 s, nach fixer Passenger-IP 1.127.589 statt B0 1.131.767; B300-LB 0 | Weniger als 0,4 % Gewinn nach Nachoptimierung, größeres Modell; schlechter als früherer Waiting-Bestwert. Freie Starts damit nicht widerlegt. |
| Reservierungs-/Einfügeheuristik | Bester separat nachoptimierter Seed **1.007.532**, 1.112 bedient; finaler 100-Request-Lauf 41,5 s, 9 Bewegungen, bestes Assignment 1.008.673 | Kleiner UB-Gewinn von 1,423 %; keine LB. Alle erfolgreichen großen Reparaturversuche ändern tatsächlich nur eine Kabine. Als Seed behalten, Ausbau pausieren. |

Quellen zu historischen Bausteingates: [EAN-Benchmarks](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/docs/findings/ean_passenger_optimization_benchmarks.md), [EAN-Skalierung](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/docs/findings/ean_model_scaling.md), [Fixed-Movement-Integrality](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/docs/findings/ean_fixed_movement_passenger_integrality.md), [Merge-Gate](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/docs/findings/ean_merge_sequence_gate.md), [DDD-Passenger-Support](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/docs/findings/ddd_five_station_passenger_support.md), [Partial-Benders](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/docs/findings/ddd_partial_passenger_benders_root_gate.md), [Merge-CG](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/docs/findings/ddd_merge_aware_root_gate.md), [Cohort/Corridor](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/docs/findings/ddd_fractional_cabin_neighborhood_gate.md). Die Einzelpfade aller extrahierten Resultate stehen im CSV und im Familienindex unten.

## 4. Die stärksten tatsächlich vergleichbaren No-Wait-Ergebnisse

### K20 und K39, Five-Station-B, balanced_reference

| K | Methode | Tatsächliche Zeit | End-UB | End-LB | Gap |
|---|---|---:|---:|---:|---:|
| 20 | EAN, Bakeoff v3 | 1.801,5 s | 605.612,91 | 446.542,89 | 26,27 % |
| 20 | Gelabeltes Arc-Flow, gleicher Bakeoff | 24,6 s | **525.730,91** | **525.730,91** | **0 %** |
| 20 | Exakt anonymes Arc-Flow | 134,9 s | **525.730,91** | **525.730,91** | **0 %** |
| 20 | CP-SAT Produkt, mit optimalem Seed | 300,4 s | 525.730,91 | 419.877,36 | 20,13 % |
| 39 | EAN, Bakeoff v3 | 1.802,2 s | 1.536.000,00 | 311.588,73 | 79,71 % |
| 39 | Gelabeltes Arc-Flow, gleicher Bakeoff | 1.742,0 s | 1.441.586,41 | 407.377,36 | 71,74 % |
| 39 | Gelabeltes Arc-Flow, separater Awake-Stundenlauf | 3.541,3 s | 1.408.269,90 | 429.449,18 | 69,51 % |
| 39 | Exakt anonymes Arc-Flow, separater Stundenlauf | 3.540,6 s | 1.376.000,78 | **441.919,53** | 67,88 % |
| 39 | Root-CG + koordinierter globaler CP-Schritt | etwa 529 s | 1.326.950,67 | 315.690,63 | 76,21 % |
| 39 | Integrierter CP-SAT Produkt, erster 10-min-Lauf | 603,2 s | 1.272.673,03 | 402.843,30 | 68,35 % |
| 39 | CP-SAT Produkt, neuer Seed-Vergleich | 600,3 s | **1.262.099,94** | 396.586,50 | 68,58 % |

Das ist eine Ergebnisübersicht derselben benannten Fixed-K-Familie, **kein vollständig kontrolliertes Turnier**: Codeversion, Startlösung, Budget und teilweise Aufbereitung unterscheiden sich. Der v3-Bakeoff ist der direkteste EAN/Arc-Flow-Vergleich; selbst dort hat EAN K39 keinen gleichwertigen guten Passagierseed. Insbesondere erhielt CP K20 den bekannten Optimalfahrplan bereits als Hint und hat ihn nicht selbst entdeckt.

Die beiden Stundenläufe enthalten nur `result.json`, keine vollständigen internen Zeitreihen. Der Unterschied zum 30-Minuten-Ergebnis zeigt bessere Ergebnisse eines separaten längeren Experiments, **keinen rekonstruierbaren 30→60-Minuten-Verlauf desselben Laufs**. Die tatsächlichen Gesamtzeiten sind etwa 59 Minuten; das nominelle Stundenbudget nicht als Messwert einsetzen.

[Originaler Bakeoff](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/fixed_k_model_bakeoff/five_station_b_no_wait_model_bakeoff_k20_k39_30m_v3), [gelabelter Awake-Lauf](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_labeled_gate_1h_k39_awake), [anonymer Stundenlauf](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_exact_anonymous_gate_1h_k39), [CP-Gate](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/docs/findings/ddd_integrated_cp_sat_gate.md).

### K-Sweep: Starts erklären scheinbar widersprüchliche Optima

Kanonische Starts, Skip-Stop No-Wait: K17 **596.873** (168 s), K18 **568.786** (87 s), K19 **543.560** (177 s), K20 **535.935** (23 s), K21 **521.593** (63 s), K22 **511.138** (265 s), jeweils als optimal berichtet. Die All-Stop-Kontrollen K17/18/19 ergeben 710.240 / 682.921 / 655.715; bei K20–22 sind diese **kanonischen** All-Stop-Startfälle bewegungsunzulässig.

Mit `balanced_reference` ist dagegen All-Stop K20 zulässig und erreicht **635.519,998**, Skip-Stop bei denselben Starts **525.730,908**: **17,28 % weniger Kosten bei gleicher Flotte, Nachfrage und Anfangsanordnung**. Das ist bereits ein belastbares positives Thesis-Ergebnis. Die kanonische K20-Zahl 535.935 widerspricht dem balanced-Optimum nicht; sie gehört zu einem anderen Problem.

Bei K38 ist All-Stop mit balanced-Starts **399.287,271408**, vollständig bedient, in etwa 1,32 s bewiesen. Der gespeicherte freie Skip-Stop-K38-MIP-Lauf bleibt nach 600 s hingegen bei 1.536.000 und LB 0. Ein gültiger guter Plan existiert; die freie Suche nutzt ihn in diesem Versuch nicht erfolgreich. Die spätere Fixierung des All-Stop-Plans in beiden K38-CP-Varianten reproduziert 399.287,271408. Das spricht gegen eine versehentliche grundsätzliche Unvereinbarkeit dieses Plans mit CP-SAT.

### Betrieblicher Nutzen: der Abstand zu All-Stop bleibt groß

| Gespeicherter Fahrplan | Kosten | Bedient / gesamt | Abstand zu All-Stop K38 |
|---|---:|---:|---:|
| All-Stop K38 | **399.287,27** | **1.280 / 1.280** | Referenz |
| CP-SAT No-Wait K39, Kontrolllauf | 1.262.099,94 | 416 / 1.280 | +216,09 % |
| CP-SAT Waiting K39 | 1.022.076,36 | 1.104 / 1.280 | +155,98 % |
| Bester Reservierungs-/Assignment-Seed K39 | 1.007.532,08 | 1.112 / 1.280 | +152,33 % |

Beim CP-Waiting-Plan entfallen 211.200 Kosten auf 176 Unbediente und 810.876 auf die 1.104 bedienten Personen. Auch die Bedienung ist also spät: durchschnittlich 734,49 s von Freigabe bis Ziel gegenüber 311,94 s bei All-Stop K38. Es fehlt nicht nur die letzte kleine Zuordnungsverbesserung. Umgekehrt beweist die schwache globale LB nicht, dass bessere K39-Pläne unmöglich sind. Diese Tabelle vergleicht Betriebsvarianten mit verschiedenen Anfangsanordnungen, nicht gleich gestartete Solver.

## 5. Was passiert während der Laufzeit?

### Direktes EAN/Arc-Flow-Bakeoff v3

Zeiten aus dem Kampagnenprotokoll, seit jeweiligem Trialbeginn. Zwischen-UBs sind lokale Solvermeldungen, erst das Endergebnis wird als unabhängig validierte globale UB exportiert. Fehlende Schranken werden nicht rückwirkend ergänzt. Bei K20 Arc-Flow endet der Lauf bereits nach 24,6 s.

| Methode | 1 min UB / LB | 5 min UB / LB | 10 min UB / LB | 20 min UB / LB | Ende etwa 30 min UB / LB |
|---|---|---|---|---|---|
| EAN K20 | 635.520 / 0 | 625.833 / 446.491 | 625.833 / 446.491 | 609.622 / 446.491 | 605.613 / 446.543 |
| EAN K39 | noch keine gemeldete UB / 0 | keine / 0 | keine / 0 | 1.536.000 / 309.712 | 1.536.000 / 311.589 |
| Arc-Flow K39 | 1.441.586 / 0 | 1.441.586 / 0 | 1.441.586 / 0 | 1.441.586 / 407.377 | 1.441.586 / 407.377 |

EAN K20 verbessert nach Minute 5 noch die Lösung um etwa 3,2 %, seine LB praktisch nicht. Arc-Flow K39 hält im ganzen protokollierten Lauf dieselbe UB; nach der Root-Phase bleibt auch die gemeldete LB gleich. Eine frühe LB von null bedeutet hier nicht automatisch eine schwache fertig gelöste LP: sie kann schlicht noch nicht fertig verarbeitet sein. Beim anonymen K20-Gate benötigt die Root-Verarbeitung etwa 121 der 135 s; danach schließt der verbleibende Suchteil sehr schnell den Gap.

### CP-SAT: Produkt und Waiting

Zeiten seit Optimizerstart, nach Instanz-/Seedvorbereitung; Endwerte separat validiert. Das sind andere Zeitursprünge als oben. Negative native Zwischenbounds werden hier mit dem gültigen Null-Floor ersetzt.

| Zeitpunkt | Erster K39 No-Wait-Lauf UB / LB | Frischer No-Wait-Kontrolllauf UB / LB | Waiting aus gleichem Kontroll-Seed UB / LB |
|---|---|---|---|
| 1 min | 1.312.631 / 2.161 | 1.270.826 / 0 | 1.196.699 / 0 |
| 2 min | 1.278.095 / 380.167 | 1.269.311 / 370.817 | 1.160.191 / 50.503 |
| 5 min | 1.273.232 / 390.931 | 1.264.366 / 388.093 | 1.087.296 / 50.505 |
| 7 min | 1.272.673 / 394.362 | 1.263.718 / 392.757 | 1.034.566 / 57.855 |
| Ende etwa 10 min | 1.272.673 / 402.843 | 1.262.100 / 396.587 | **1.022.076 / 76.435** |

- Erster No-Wait-Lauf: zwischen Minute 5 und Ende UB nur **0,044 %** besser, LB **3,05 %** höher. Letzte UB-Verbesserung bei 379,77 s, letzte gespeicherte LB-Verbesserung bei 560,52 s. Verschiedene Plateaugeschichten für UB und LB.
- Frischer No-Wait-Lauf: letzte fünf Minuten UB **0,18 %** besser.
- Waiting: letzte fünf Minuten UB **6,00 %** besser; letzte Incumbentmeldung **594,63 s**, letzte gespeicherte LB-Verbesserung **532,12 s**. **Kein beobachtetes spätes UB-Plateau.** Ein längerer unveränderter Lauf ist hier durch Daten begründet, Gap-Schließung aber nicht absehbar.
- K20 Produkt: LB nach 60 s etwa 419.871,87, am Ende 419.877,36; UB optimaler Hint unverändert. K20 Unary nach 300 s LB null. Mehr Zeit für diese kleinen CP-Proof-Fälle hat nachrangigen Nutzen.

Im nativen CP-Log stammen viele Fahrplanverbesserungen aus LNS-Nachbarschaften, späte LB-Beiträge unter anderem aus `max_lp`. CP-SAT nutzt schon intern mehrere Suchverfahren und LPs. Ein externer neuer Heuristik-Stack muss diese Arbeit erst übertreffen; Workerbeiträge allein beweisen allerdings nicht die Entbehrlichkeit anderer Worker.

### Verfahren mit frühem Stopp oder echtem Langzeit-Stillstand

| Fall | Beobachteter Stopp / Verlauf | Folgerung für längere Budgets |
|---|---|---|
| DDD Waiting Cascade K20 | `refinement_stalled` nach 40–99 s; Seed-UB unverändert | Unverändert länger starten reicht nicht. |
| Root-CG mit `root_lp_certified=true` | Exaktes Root-Pricing fertig, Integer-Gap bleibt | Mehr desselben Root-Pricings kann keine höhere Root-LP liefern. |
| Partial-Benders K20 | LB nach erstem Master praktisch flach; weitere Cuts/duale Zusatzarbeit | Kein Langlauf ohne nachgewiesen stärkere Kopplung. |
| Reservoir-CG K19, 2 h | UB in allen 64 Runden gleich; letzte LB-Verbesserung etwa bei summierter Runde 3.520 s | Hier liegt tatsächliche negative Langlauf-Evidenz vor. |
| Explizites Waiting-Arc-Flow K20 | Fast ganzes Budget im Netzbau, Solve 0 s | Aufbau/Enumeration ist das Problem; keine Prognose aus Solverparametern. |
| Reservierungsheuristik | Größeres Budget findet mehr einzelne Bewegungen, schlägt besten gespeicherten Seed nicht | Lokale Geschwindigkeit verbessert, gekoppelte Reparatur bislang kein Durchbruch. |

Summierte Rundenzeiten schließen nicht zugeordnete Vorbereitung, Abschluss und gegebenenfalls separate Primalphasen aus. Beispiel Diving: etwa 172 s in erfassten Runden gegenüber 316 s Gesamtzeit. Diese Zahlen dürfen nicht als identische Wall-Clock-Achse dargestellt werden. Ein CP-Checkpoint-Neustart lädt einen Hint, nicht Suchbaum, Klauseln und internen Portfoliozustand; mehrere Neustarts sind keine echte Fortsetzung.

## 6. Modellgröße, Aufbau und eigentliche Suche

| Fall | Variablen | Zeilen / CP-Constraints | Zeitaufteilung / Speicher |
|---|---:|---:|---|
| EAN K39 Bakeoff | 163.759 | 1.093.843 MILP-Zeilen | Umfangreiche Aufbau-/Presolvephase; lange ohne Passagierincumbent |
| Gelabeltes Arc-Flow K39 | 42.471 Bewegung + 312.833 Passagier = 355.304 | 556.679 | Netz-/Passagierexpansion und Root-Verarbeitung relevant |
| Anonymes Arc-Flow K39 | Andere anonyme Netzstruktur | 397.553 | Weniger Zeilen; K20 dennoch langsamer, also Größe allein erklärt Laufzeit nicht |
| CP K20 Produkt | 19.570 → 9.250 | 42.175 → 16.325 | Aufbau 0,42 s, Solver 299,39 s; Peak-RSS 1.351 MB |
| CP K20 Unary | 29.620 → 18.470 | 57.585 → 30.765 | Aufbau 0,54 s, Solver 299,20 s; Peak-RSS 1.764 MB |
| CP K39 No-Wait | 43.986 → 17.268 | 92.596 → 31.820 | Im Kontrolllauf Aufbau 1,09 s, Solver 593,97 s; Peak-RSS 1.985 MB |
| CP K39 Waiting | 51.076 → 27.978 | 106.782 → 56.056 | Aufbau 1,10 s, Solver 594,31 s; Suchstart nach etwa 22,9 Solver-s; Peak-RSS 3.487 MB |
| CP K39 Waiting + Warmup300 | 63.767 → 34.947 | 133.879 → 69.917 | Aufbau 1,37 s, Solver 593,41 s; Peak-RSS 4.702 MB |
| Neues Reservoir-Arc-Flow | Allein 2.710.064 Passagiervariablen | 3.306.361 | Netz 35,6 s, Modell 137,4 s; rund 81 s sekundärer Solve im alten Smoke |
| Reservierungsheuristik | Kein globales CP-/MIP-Bewegungsmodell | Kalenderbelegungen und Suchlabels | Finaler Lauf: Vorbereitung 6,08 s, Reparatur 22,37 s, Kandidatenprüfung 9,55 s, danach kurze Assignment-IPs |

CP-Pfeile bedeuten vor → nach Presolve. CP-Constraints umfassen lineare Bedingungen, Produkte, Intervalle und NoOverlap; ihre Anzahl ist kein direktes Äquivalent zu MILP-Zeilen. Peak-RSS ist Prozessspeicher, kein reiner Modellbedarf. Suchstart/Presolve liegt innerhalb der Solvezeit; Callbackarbeit ebenfalls. Diese Teilzeiten nicht doppelt addieren.

**Für CP ist schnellerer Python-Aufbau allein kein Durchbruchskandidat:** er kostet bei K39 etwa eine Sekunde von zehn Minuten. Sichere engere Ereignis-/Produktdomänen könnten dagegen die spätere Suche stärken. Beim expliziten Waiting-Arc-Flow ist der Aufbau selbst der Engpass. Das sind unterschiedliche Optimierungsaufträge.

## 7. Freie Starts, Reservoir und Szenarienabdeckung

### EAN OIP: korrekt nach Zielhierarchie lesen

300-s-Läufe der korrigierten v2-MIP-Start-Kampagne. Innerhalb jeder Zeile gleiche Instanz; drei Startstrategien. Zielpaar: **unbediente Personen / sekundäre Zeit der bedienten Personen**; zuerst die linke Zahl minimieren.

| Instanz | Kein MIP-Start | Greedy All-Stop | Optimierter All-Stop-Start |
|---|---:|---:|---:|
| Drei Stationen, 3.480 Personen | 2.776 / 436.457 | 2.776 / 424.351 | 2.776 / 432.032 |
| Fünf Stationen, All-Stop, 2.560 Personen | 1.536 / 651.373 | 1.536 / 604.123 | 1.536 / 586.129 |
| Fünf Stationen, Skip, 2.560 Personen | 2.406 / 76.476 | 1.933 / 443.339 | **1.568 / 511.275** |

Die 76.476 sind in der letzten Zeile **der schlechtere** Plan, weil nur 154 Menschen bedient werden. Ein früherer OIP-Lauf mit null aktiven Kabinen, null bedienten Personen und null sekundären Sekunden ist ebenfalls kein Nullkosten-Erfolg. Das frühere generische Feld `objective_value_seconds` reicht für diesen Vergleich nicht. Die Verlaufsmeldungen können 2.560 → 2.406 unbediente Personen zeigen; sie dürfen nicht als Passagiersekunden neben der sekundären Endzahl erscheinen.

Der neue Reservoir-Smoke beweist dank gültigem 38-Kabinen-All-Stop-Seed bereits null unbediente Personen in seiner eigenen größeren Domäne, verbessert aber das Sekundärziel nicht. Er ist ein brauchbarer Integrationsnachweis, bislang keine Evidenz für schnellere globale Optimierung. Der Statusfehler dieses alten Runners ist inzwischen korrigiert; die alte Datei lässt die genaue sekundäre Abbruchursache nicht vollständig rekonstruieren.

### Was wir an Szenarien tatsächlich untersucht haben

| Gruppe | Vorhandene Evidenz | Noch fehlende Aussage |
|---|---|---|
| Drei Stationen, ursprüngliches EAN | Mehrere Formulierungen, 300-/900-s-Läufe, OIP und Passagier-IP | Kein Beweis allgemeiner Skalierung auf dichte Fünf-Stationen-Fälle |
| Fünf Stationen, ursprüngliche Architektur | Full/Half-Demand, No-Wait/Waiting, OIP, DDD-Pricing-/Supportgates | Flottenzahl und Startkonstruktion wechseln teilweise zusammen mit Betriebsvariante |
| Five-Station-B, halbe Nachfrage | K-Sweeps, All-Stop-Grenzreferenzen, K20/K39-MIP-/CP-Vergleiche, Waiting, Warmup, Heuristik | Dichteste empirische Grundlage, aber aktuelle Headline-Fälle sind t=0-Batchnachfrage |
| Five-Station-B, volle Nachfrage | Feasibility-/CG-/Fleet-Screenings und Reservoirvarianten | Kein entsprechendes abgeschlossenes integriertes CP-Mehrseedturnier gefunden |
| Kleine künstliche Instanzen | Exhaustive/Refinement-/Merge-/Timing-/Kapazitätsprüfungen | Korrektheitsgates, keine realistische Laufzeitprognose |
| Geplante Demand-Familien F0–F6 / Zeitprofile P0–P5 | Dokumentierte Forschungs-/Versuchsplanung | Keine abgeschlossene gemeinsame Ergebnismatrix über diese Familien gefunden |
| Weitere Topologien, etwa geplante Linien-/Doppelringfälle | Planungsansätze | Keine passende abgeschlossene breite Solverkampagne in diesem Archiv gefunden |

Nicht gleichsetzen: „alle Nachfrage bei t=0“ und stationäre zeitlich verteilte Nachfrage. Die aktuelle schwierige Anfangsphase trifft unmittelbar auf den gesamten Batch. Zeitprofile sind daher ein substanzieller fehlender Thesis-Faktor, nicht bloß spätere Ergebnisdekoration. Quelle: [Demand-Case-Familien](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/docs/reference/demand_case_families.md).

## 8. Funktionsweise und konkrete Fundstellen im Code

| Baustein | Wie er das Seilbahnproblem behandelt | Code / wichtiger Prüfpunkt |
|---|---|---|
| EAN | Ereignisbesuche mit Stop/Skip, kontinuierliche Zeiten/Warten, paarweise Ressourcenreihenfolgen und passagierweise bzw. unäre Kapazitätskopplung | [EAN-Solver](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ean/optimizers/solver.py), [Passenger Model](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ean/optimizers/passenger_model.py), [Headway Separator](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ean/headway_separator.py) |
| Vollständiges gelabeltes Arc-Flow | Erreichbares endliches Zustands-/Zeitnetz je Kabine, Bewegungspfade, Ressourcencliquen und ganzzahlige Passagierflüsse in einem Modell | [Netz](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/arc_flow_network.py), [integrierte Passagiere](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/arc_flow_passenger_model.py), [Runner](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/benchmarking/ddd_fixed_k_arc_flow.py) |
| Exakt anonymes Arc-Flow | Physisch gleiche State-Time-Zustände zusammenführen; feste Quellen und K erhalten; Flusslösung wieder zu Kabinentrajektorien zerlegen und prüfen | [Anonymes Netz](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/exact_anonymous_arc_flow_network.py), [Solver](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/exact_anonymous_arc_flow.py). Keine vorgeschriebene Periodizität. |
| Adaptives DDD | Optimistische zeitlich aggregierte Masterlösung; konkrete Bewegung rekonstruieren; Konflikte/Zeitzellen/Netz verfeinern | [Arc-Flow-Relaxation](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/arc_flow_relaxation.py), [CP-Runden](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_round.py). Nicht mit dem vollständigen Arc-Flow unter demselben DDD-Verzeichnis verwechseln. |
| Root-CG und CP-Primal | Ganze Kabinentrajektorien als Spalten; Restricted Master und exaktes Pricing; separate gemeinsame Primalreparatur | [Root-CG](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/trajectory_root_column_generation.py), [CP-Primal](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_primal.py). Zertifiziertes Root-LP ist nicht der Integerbeweis. |
| Partial-Passenger-Benders | Teil der Nachfrage im Master, Rest als kapazitätsgekoppeltes Recourse-LP und duale Cuts | [Partial Master](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/passenger_partial_master.py), [Outer Loop](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/passenger_benders_outer_loop.py). Gemeinsame Kapazität verhindert unbesehen unabhängige OD-Multicuts. |
| Reservoir | Optionaler Dispatch/Flotte, Anlauf und Recovery; entweder Trajektorienspalten oder anonymes vollständiges Netz | [Trajectory Reservoir](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/trajectory_reservoir.py), [Reservoir Arc-Flow](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_arc_flow.py) |
| Integrierter CP-SAT | Ganzzahlige Ereigniszeiten auf kanonischen Mikrosekundenticks, Stopliterale, Exit-Waits und optionale Ressourcenintervalle mit NoOverlap; ganzzahlige Ride-Counts und Segmentkapazitäten; Alighting-Count × Zeit als Produkt | [Bewegung](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_movement.py), [Passagiere](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_passenger.py), [integrierter Optimizer](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_integrated.py). IntVar-Domäne enumeriert nicht jeden Mikrosekundenwert vorab. |
| Reservierungsheuristik | Kalender fixierter Kabinen, zulässige Zeitfenster, begrenzte Suffixreparatur und Beam-Suche; größere freigegebene Kabinenmenge garantiert keinen gemeinsam gefundenen Plan | [Kalender](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/reservation_calendar.py), [Reparatur](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/reservation_repair.py), [Finalisten-IP](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/reservation_refinement.py) |
| Gemeinsame Prüfung / Bewertung | Physische Ereignisse und Randbelegung, Integer-Passagierzuweisung, vollständiges Domänenmanifest; feste Bewegung kann per bestehendem EAN-IP verbessert werden | [neues Fixed-K-Zertifikat](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/fixed_k_certificate.py), [Primal-Evaluator](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/primal_evaluation.py), [Horizontvertrag](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/docs/reference/finite_horizon_contract.md) |

Die großen Modellunterschiede sind strukturell: explizite Zeit-/Pfadenumeration versus Ereignisvariablen; fraktionale Entkopplung versus gemeinsame ganzzahlige Suche; globale Passagierkopplung versus lokale Reparatur. „DDD“, „CP“ und „Reservoir“ bezeichnen jeweils mehrere verschiedenartige Implementierungen und sind keine hinreichenden Modell-IDs.

## 9. Fehler, behobene Probleme und nicht bewiesene Ursachen

### A. Aktuell reproduzierte Schwachstelle: Legacy-Fingerprint und LB-Import

[Fixed-K-Fingerprint](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ddd/fixed_k.py:183) enthält unter anderem Starts, Randbelegung, Nachfrage und Routen-IDs, aber **nicht die Kabinenkapazität** und keine vollständige numerische Ressourcen-/Routenidentität. Im kleinen gültigen Testproblem bleibt der alte Fingerprint bei Kapazität **2 → 3 identisch**. Das neuere gemeinsame Manifest unterscheidet die beiden Fälle korrekt.

Der [Root-CG-LB-Importer](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/benchmarking/ddd_fixed_k_arc_flow.py:1099) prüft nur diesen Fingerprint und einen endlichen Zahlenwert. Eine Testdatei mit passendem Fingerprint, `certified_lower_bound=123`, **`certificate_valid=false`** und `status=internal_certificate_error` wird trotzdem akzeptiert.

**Bedeutung:** Ein echter Mangel der Kompatibilitäts-/Zertifikatsschnittstelle. Er kann bei veränderter Instanz oder ungültigem Quellergebnis einen unberechtigten LB-Import erlauben. Die Reproduktion beweist **nicht**, dass die hier zitierten historischen LB-Werte falsch sind oder bereits mit veränderter Kapazität vermischt wurden. Vor automatischem Solverzusammenbau muss diese Schnittstelle korrigiert werden: vollständiges versioniertes Manifest, Proof-Scope und Zertifikatsstatus, expliziter Umgang mit Legacy-Dateien. Ein gleicher kurzer Legacy-Fingerprint allein reicht nicht.

Reproduktionen: [Kapazitätsfall](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/solver_history_audit/fingerprint_capacity_repro.json), [ungültiger Zertifikatsimport](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/solver_history_audit/invalid_certificate_import_repro.json), [Testfixture](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/solver_history_audit/invalid_certificate_fixture.json). Ein [ausführbares Reproduktionsskript](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/solver_history_audit/reproduce_certificate_checks.py) bereitet dafür nur eine kleine Instanz vor und startet keinen Solver. In diesem Audit wurde der Produktionscode nicht geändert.

### B. Aktuelle Auswertungslücke: OIP-Zielphase nicht eindeutig protokolliert

Die [EAN-Zielsetzung](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/src/ropeway_skip_stop_optimization/optimization/ean/optimizers/passenger_model.py:264) implementiert ausdrücklich verschiedene Ziele für feste und variable Flotte. Das generische Sekundenfeld bzw. die generischen Progress-Samples transportieren die lexikografische Phase nicht zuverlässig. Null Sekunden bei null Bedienung oder 76.476 Sekunden bei 154 Bedienungen können dadurch wie hervorragende Ergebnisse aussehen.

Korrektur für künftige Runs: Zielvektor, Phasen-ID, Einheiten, aktive Flotte und phasenspezifische Bounds speichern. Alte Progresskurven ohne identifizierbare Phase nicht zu einem Sekunden-Gap zusammenrechnen. Das ist ein Reportingproblem; die gezeigte lexikografische Modellierung ist dadurch nicht als falsch erwiesen.

### C. Bekannte historische Probleme: aktuellen Stand berücksichtigen

- **H+1-us-Horizontabweichung:** EAN nahm wegen Prüftoleranz Ereignisse nach H auf, DDD nicht. G0 hat die Mitgliedschaft vereinheitlicht. Die ursprüngliche Warmup-Ablehnung bleibt in der alten JSON dokumentiert; die spätere unveränderte Bewegung besteht den aktuellen endlichen Vertrag. Quellen: [Warmup-Historie](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/docs/findings/ddd_cp_sat_warmup_gate.md), [G0-Nachprüfung](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/docs/findings/ddd_horizon_contract_gate.md). Die CSV ersetzt alte Statuswerte nicht stillschweigend.
- **Reservoir-Abbruchstatus:** in `e252ff2` korrigiert. Aus der alten Smoke-Datei keine genaue sekundäre Endursache bzw. volle Ausschöpfung von 600 s ableiten; tatsächlich sind 278 s gespeichert.
- **CP-Build-Vorläufe:** Ressourcenbestand und Python/pybind-Domainzugriff wurden in der Umsetzung korrigiert. Fehlgeschlagene Build-Smokes sind keine gemessene Suchleistung des aktuellen vollständigen Modells.
- **Absichtlich relaxed EAN:** 568.699 Sekunden mit 18 Headwayverletzungen sind kein zulässiger Vergleichswert. Die Verletzungen sind im Original explizit dokumentiert, keine hier neu entdeckte versteckte physische Abweichung.
- **Reservierungsperformance:** häufige Rekonstruktion des MovementCore über die Horizont-Property wurde bereits durch Cache/Index vermieden. Gleiche 1.000 Fensterabfragen etwa 6,17-mal schneller; kein Beleg für einen gleich großen globalen Solvergewinn.

### D. Kein nachgewiesener Fehler, aber wichtige Grenze

Kein belegter versehentlicher Fixierungsfehler des zukünftigen CP-Seedfahrplans. Die bekannten K38-All-Stop-Pläne sind im CP-Modell enthalten; gespeicherte K39-Waiting-Pläne bestehen aktuelle endliche Bewegungsprüfung und unabhängige Integer-Passagierbewertung. Das ist aussagekräftige positive Evidenz, kein vollständiger Fehlerfreiheitsbeweis.

Die schlechte K39-Qualität kann daher derzeit nicht seriös einem bestimmten Physikbug zugeschrieben werden. Andere Starts, viele dicht aufeinanderfolgende Kabinen, ein bedienungsarmer Hint und schwierige gekoppelte Entscheidungen sind belegte Eigenschaften; ihr jeweiliger kausaler Anteil ist noch nicht isoliert.

Weitere Messlücken: Callback-Extraktion/-Validierung ist in `solve_seconds` enthalten, aber nicht vollständig separat exportiert; parallele CP-Worker können trotz gleichem Seed variieren; manche alten Läufe hatten Schlaf-/Lastprobleme; externe Startlösungen und Post-IP-Zeiten werden uneinheitlich bilanziert. Die Produktionsimplementierung ist deshalb nicht als „optimal implementiert“ zu bezeichnen. Die Befunde rechtfertigen gezielte Messung und sichere Formulierungsverbesserung, keine pauschale Neuentwicklung.

## 10. Konkrete Entscheidung und Reihenfolge

### 1. Gemeinsame Ergebnisbasis absichern und vorhandenen Stand einfrieren

Zuerst die oben reproduzierte Legacy-LB-Schnittstelle beheben und die Solver-/Ergebnisidentität versionieren. Regressionen: geänderte Kapazität, Routenzeit, Headway, Nachfrage, Waiting, Startsnapshot und `certificate_valid=false` müssen einen unzulässigen Bound-Import verhindern. Die neuen Manifestbausteine sind bereits vorhanden; kein zweites Zertifikatssystem bauen.

Dann wenige Headline-Fahrpläne unter demselben aktuellen Vertrag prüfen und einen überprüfbaren Stand sichern: K20 All-Stop/Skip-Stop, K38 All-Stop, K39 No-Wait-Bestplan und Waiting-Bestplan. Codecommit und Sicherung der ausgewählten Resultate sind getrennte Aufgaben: `benchmarks/output` ist gitignored. Dieses Audit erstellt selbst keinen Gitcommit und verändert keine alten Ergebnisse.

### 2. CP-SAT Waiting länger messen — der am besten begründete nächste Suchlauf

Ein **durchgehender 30-Minuten-Lauf**, Produkt, K39, identischer ursprünglicher Waiting-Domäne, 8 Worker, dokumentierter Seed. Als Hint den bereits geprüften Reservierungs-/Assignment-Bestplan **1.007.532,083464** übernehmen. Erwartung: bessere Fahrpläne und weitere Bedienung; **keine belastbare Erwartung eines kleinen Gaps**.

Diese Variante ist ausdrücklich „besserer Hint + längerer Lauf“ zur Ergebnisverbesserung. Um allein den Zeiteffekt gegenüber den alten zehn Minuten zu messen, einen separaten Kontrolllauf mit dem damaligen ursprünglichen Hint verwenden. Die Verbesserungen aus beiden Faktoren nicht vermischen. Zwei zusätzliche 10-Minuten-Seeds geben anschließend eine erste Streuungsabschätzung; sie ersetzen den durchgehenden Verlauf nicht.

Inkrementell UB, LB, bediente Personen, vollständige Zeitanteile und RSS aufzeichnen; gemeinsame Milestones 1/2/5/10/20/30 min. Bei weiterem deutlichem UB-Fortschritt kann genau diese Variante 60 Minuten erhalten. Falls letzte zehn Minuten bei UB und LB praktisch unverändert bleiben, nicht blind einen Nachtlauf anschließen. Die Schwelle ist eine Arbeitsentscheidung, kein mathematischer Plateaubeweis.

### 3. Ein kleiner aussagekräftiger Betriebsvergleich vor weiteren dichten Spezialfällen

**K38 freies Skip-Stop mit dem guten All-Stop-Seed** testen, zunächst im vorhandenen CP-SAT mit Waiting und begrenztem Budget. Gleiche K38-Starts, gleiche Nachfrage, gleiche Horizonte; Zukunft frei. So sehen wir, ob der Solver aus einer bereits vollständig bedienenden Lösung zusätzliche Skip-Stop-Vorteile gewinnt. Ein schlechter neuer Incumbent darf den gültigen All-Stop-Seed nicht verdrängen. Keine zusätzliche Kabine muss dafür physikalisch untergebracht werden.

Danach auf derselben vorhandenen Fünf-Stationen-Topologie eine kleine Thesis-Matrix: diffuse, Express-/komplementäre und lokale OD-Nachfrage, jeweils Batch versus zeitlich verteilt; Gesamtbedarf kontrollieren. Mit K20 als lösbarer Referenz anfangen und K38/K39 nur für ausgewählte aussagekräftige Kontraste ergänzen. Diese Matrix liefert eher eine Antwort auf „wann lohnt Skip-Stop?“ als weitere Solverarchitekturen nur auf demselben t=0-Fall.

### 4. Bestehende Solver nur über geprüfte Fahrpläne und domänengültige Schranken verbinden

Für **No-Wait K39** einmal das anonyme vollständige Arc-Flow mit dem passenden CP-No-Wait-Seed **1.262.099,935264** testen, etwa 30 Minuten. Erwartung: von Beginn an bessere zulässige UB und eventuell wirksameres Pruning bei weiterhin stärkerem LB-Kanal. Ein besserer Seed garantiert keine schnellere Root-LP oder neue globale Lösung.

Das ist nachrangig gegenüber Waiting und der Betriebsvergleichsmatrix. **Den Waiting-Seed nicht in ein No-Wait-Modell zwingen und die No-Wait-LB nicht zur Waiting-LB erklären.** Keine Waiting-Arc-Flow-Expansion auf Mikrosekundenraster beginnen. Falls UB und LB wirklich dieselbe vollständige Domäne und denselben Proof-Scope betreffen, können bestehende Werte kombiniert werden; davor steht die Kompatibilitätskorrektur aus Schritt 1.

Die gemeinsame Architektur bleibt klein: bestehender Problem-/Manifestbaustein → ausgewählter bestehender Optimizer → gemeinsame Bewegungs-/Passagierprüfung → optional bestehende feste Integer-IP → exportierter Hint und sauber bezeichnete Bounds. Kein neuer Metasolver nötig.

### 5. Nur eine belegbar sinnvolle CP-Formulierungsverbesserung

Erst nach eingefrorener Laufzeitbaseline sichere besuchsspezifische Zeitgrenzen und daraus engere Produktdomänen testen. Sie müssen aus Startzeit, erreichbaren Routen, Waiting und Horizont korrekt folgen; inaktive angehängte Besuche gesondert beachten. Ziel: stärkere Propagation/Relaxation, gleiche zulässige Fahrpläne. Kleine exakte Vergleichsfälle und gleiche Seeds/Budgets sichern den A/B-Test.

Breitere Warteobergrenze experimentell verkleinern wäre dagegen eine **Modellvariante**, keine bewiesene verlustfreie Implementierungsverbesserung. Dass der bisherige Plan maximal 33,24 s wartet, beweist kein global ausreichendes W=34 s. Worker-/Portfolioabstimmung erst danach, jeweils eine Änderung.

### Was jetzt pausiert

EAN als Referenz behalten, aber keine weitere große EAN-Formulierungsrunde. Kein unverändertes Partial-Benders-, Merge-Window-, Root-Diving- oder Reservoir-Ausbauprojekt. Kein Greedy/Regret/ALNS-Neubau auf dem bisherigen Einfügekern. Vorhandene Seeds, Kalender und Validatoren bleiben wertvoll.

**Worauf wir uns festlegen können:** eine saubere wissenschaftliche Frage, den vorhandenen CP-SAT-Waiting-Hauptpfad und eine exakte Arc-Flow-Referenz. **Worauf die Daten keine Zusage erlauben:** K39 bis zum 18. September global optimal lösen oder All-Stop K38 sicher schlagen. Der vorhandene K20-Vorteil, die Skalierungsgrenze und der klar gemessene Waiting-Effekt ergeben bereits verwertbare Ergebnisse; die nächste Arbeit sollte deren Generalisierbarkeit und Ursachen untersuchen.

## 11. Quellenrangfolge und Reproduktion

Bei Widersprüchen zuerst aktueller Vertrag und konkrete Nachprüfung, dann unveränderte Originalresultate und native Logs, dann historische Findings und Pläne. Ein späteres Finding kann eine alte Validierungsentscheidung korrigieren, ohne den ursprünglichen Run umzuschreiben. Frühere Empfehlungen in `SOLVER_OVERVIEW.md` dokumentieren verschiedene Projektphasen und sind nicht alle zugleich gültig.

Die Auditdateien lassen sich aus dem Software-Repository neu erzeugen:

```sh
.venv/bin/python benchmarks/audit_solver_history.py
```

Der Scan startet keine Solver und schreibt ausschließlich in seinen angegebenen Audit-Ausgabeordner. Die neben diesem Bericht abgelegten CSVs sind der geprüfte Snapshot dieses Audits; eine erneute Extraktion aktualisiert diese Kopien nicht automatisch. Originalmetriknamen und Quellpfade bleiben erhalten. Für dieses Audit wurden der Extraktor formatiert/geprüft, zentrale Werte mit den Rohdateien abgeglichen und die beiden Zertifikatsmängel im kleinen Testfall reproduziert. Es wurde keine neue vollständige Produktions-Testkampagne behauptet oder benötigt, da kein Produktionssolver geändert wurde.

## 12. Vollständiger Familienindex des Ergebnisregisters

Die Zahl ist die Anzahl erkannter Ergebnis-/Diagnoseeinträge einschließlich Duplikaten und Snapshots, nicht die Zahl unabhängiger Solverläufe. Familiennamen entsprechen den lokalen Output-Unterordnern. Die CSVs enthalten die konkreten Dateien, Status und vorhandenen Verläufe; Build-/Smoke-Familien bleiben bewusst sichtbar.

| Ergebnisfamilie | Einträge |
|---|---:|
| [affine_timing_20260714](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/affine_timing_20260714/) | 4 |
| [artifacts](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/artifacts/) | 10 |
| [bottleneck_diagnostics](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/bottleneck_diagnostics/) | 9 |
| [circle_half_skip_wait_20260716](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/circle_half_skip_wait_20260716/) | 2 |
| [combined_formulations_20260715](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/combined_formulations_20260715/) | 10 |
| [ddd_audit_post_refactor](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_audit_post_refactor/) | 2 |
| [ddd_branch_price_gate_k20](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_branch_price_gate_k20/) | 1 |
| [ddd_branch_price_gate_k20_prepare](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_branch_price_gate_k20_prepare/) | 1 |
| [ddd_branch_price_gate_k39_10m](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_branch_price_gate_k39_10m/) | 1 |
| [ddd_branch_price_gate_k39_arcflow_10m](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_branch_price_gate_k39_arcflow_10m/) | 1 |
| [ddd_branch_price_gate_k39_smoke](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_branch_price_gate_k39_smoke/) | 1 |
| [ddd_branch_price_smoke](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_branch_price_smoke/) | 1 |
| [ddd_delayed_waiting_budget_smoke](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_delayed_waiting_budget_smoke/) | 1 |
| [ddd_delayed_waiting_passenger_pilot_k20](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_delayed_waiting_passenger_pilot_k20/) | 1 |
| [ddd_delayed_waiting_passenger_pilot_k20_v2](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_delayed_waiting_passenger_pilot_k20_v2/) | 1 |
| [ddd_delayed_waiting_pilot_k20](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_delayed_waiting_pilot_k20/) | 1 |
| [ddd_delayed_waiting_shared_budget_k20](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_delayed_waiting_shared_budget_k20/) | 5 |
| [ddd_delayed_waiting_smoke](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_delayed_waiting_smoke/) | 1 |
| [ddd_exact_anonymous_gate](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_exact_anonymous_gate/) | 2 |
| [ddd_exact_anonymous_gate_1h_k39](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_exact_anonymous_gate_1h_k39/) | 1 |
| [ddd_exact_anonymous_gate_5m](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_exact_anonymous_gate_5m/) | 1 |
| [ddd_fixed_k_arc_flow_campaigns](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_fixed_k_arc_flow_campaigns/) | 18 |
| [ddd_fixed_k_arc_flow_pilot](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_fixed_k_arc_flow_pilot/) | 3 |
| [ddd_fixed_k_arc_flow_smoke](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_fixed_k_arc_flow_smoke/) | 5 |
| [ddd_fixed_k_campaigns](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_fixed_k_campaigns/) | 36 |
| [ddd_fixed_k_diagnostics](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_fixed_k_diagnostics/) | 1 |
| [ddd_fixed_k_feasibility](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_fixed_k_feasibility/) | 33 |
| [ddd_fixed_k_feasibility_isolation_smoke](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_fixed_k_feasibility_isolation_smoke/) | 2 |
| [ddd_fixed_k_feasibility_smoke](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_fixed_k_feasibility_smoke/) | 2 |
| [ddd_fixed_start_k_sweep](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_fixed_start_k_sweep/) | 4 |
| [ddd_fixed_start_k_sweep_probe](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_fixed_start_k_sweep_probe/) | 4 |
| [ddd_fixed_start_refinement](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_fixed_start_refinement/) | 2 |
| [ddd_fixed_start_refinement_batch_probe](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_fixed_start_refinement_batch_probe/) | 1 |
| [ddd_fixed_start_refinement_cp_probe](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_fixed_start_refinement_cp_probe/) | 1 |
| [ddd_fixed_start_refinement_incremental_warm](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_fixed_start_refinement_incremental_warm/) | 1 |
| [ddd_fixed_start_refinement_integer_storage](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_fixed_start_refinement_integer_storage/) | 1 |
| [ddd_fixed_start_refinement_ticks](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_fixed_start_refinement_ticks/) | 1 |
| [ddd_fleet_sweeps](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_fleet_sweeps/) | 38 |
| [ddd_frozen_trajectory_pricing](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_frozen_trajectory_pricing/) | 9 |
| [ddd_integrated_cp_sat](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_integrated_cp_sat/) | 6 |
| [ddd_integrated_cp_sat_waiting](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_integrated_cp_sat_waiting/) | 8 |
| [ddd_integrated_cp_sat_warmup](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_integrated_cp_sat_warmup/) | 8 |
| [ddd_labeled_gate_1h_k39](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_labeled_gate_1h_k39/) | 1 |
| [ddd_labeled_gate_1h_k39_awake](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_labeled_gate_1h_k39_awake/) | 1 |
| [ddd_merge_aware_bpc](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_merge_aware_bpc/) | 14 |
| [ddd_movement_feasibility_cp_sat_k19](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_movement_feasibility_cp_sat_k19/) | 1 |
| [ddd_movement_refinement_diagnostic_k19](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_movement_refinement_diagnostic_k19/) | 1 |
| [ddd_movement_refinement_diagnostic_k19_after_fix](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_movement_refinement_diagnostic_k19_after_fix/) | 1 |
| [ddd_pair_root_k39_coordinated_interval5_10m](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_pair_root_k39_coordinated_interval5_10m/) | 1 |
| [ddd_partial_passenger_benders](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_partial_passenger_benders/) | 3 |
| [ddd_passenger_master](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_passenger_master/) | 23 |
| [ddd_phase0_combined_refinement](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_phase0_combined_refinement/) | 1 |
| [ddd_phase0_conflict_loop](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_phase0_conflict_loop/) | 1 |
| [ddd_phase0_network_time_refinement](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_phase0_network_time_refinement/) | 1 |
| [ddd_phase0_reference](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_phase0_reference/) | 2 |
| [ddd_phase0_time_refinement](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_phase0_time_refinement/) | 1 |
| [ddd_progress_compact_smoke](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_progress_compact_smoke/) | 1 |
| [ddd_progress_fixed_width_smoke](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_progress_fixed_width_smoke/) | 1 |
| [ddd_progress_fixed_width_smoke_2](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_progress_fixed_width_smoke_2/) | 1 |
| [ddd_reservation_insertion](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_reservation_insertion/) | 12 |
| [ddd_reservoir_arc_flow_gates](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_reservoir_arc_flow_gates/) | 2 |
| [ddd_resource_clique_gate_k20_3m](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_resource_clique_gate_k20_3m/) | 1 |
| [ddd_resource_clique_gate_k39_10m](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_resource_clique_gate_k39_10m/) | 1 |
| [ddd_resource_clique_gate_k39_arc_pricing_3m](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_resource_clique_gate_k39_arc_pricing_3m/) | 1 |
| [ddd_resource_clique_gate_k39_barrier_3m](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_resource_clique_gate_k39_barrier_3m/) | 1 |
| [ddd_resource_clique_gate_k39_coordinated_200prefs_3m](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_resource_clique_gate_k39_coordinated_200prefs_3m/) | 1 |
| [ddd_resource_clique_gate_k39_coordinated_hint_200prefs_3m](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_resource_clique_gate_k39_coordinated_hint_200prefs_3m/) | 1 |
| [ddd_resource_clique_gate_k39_coordinated_interval3_5m](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_resource_clique_gate_k39_coordinated_interval3_5m/) | 1 |
| [ddd_resource_clique_gate_k39_multicolumn_5m](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_resource_clique_gate_k39_multicolumn_5m/) | 1 |
| [ddd_resource_clique_gate_k39_smoke](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_resource_clique_gate_k39_smoke/) | 1 |
| [ddd_resource_clique_gate_k39_zero_dual_3m](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_resource_clique_gate_k39_zero_dual_3m/) | 1 |
| [ddd_resource_window_ab20_energy](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_resource_window_ab20_energy/) | 1 |
| [ddd_resource_window_ab20_energy_fixed](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_resource_window_ab20_energy_fixed/) | 1 |
| [ddd_resource_window_ab20_entry](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_resource_window_ab20_entry/) | 1 |
| [ddd_resource_window_ab20_off](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_resource_window_ab20_off/) | 1 |
| [ddd_resource_window_smoke](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_resource_window_smoke/) | 1 |
| [ddd_resource_window_smoke_energy_fixed](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_resource_window_smoke_energy_fixed/) | 1 |
| [ddd_timed_flow_cover_smoke](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_timed_flow_cover_smoke/) | 1 |
| [ddd_timed_flow_cover_smoke2](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_timed_flow_cover_smoke2/) | 1 |
| [ddd_timed_flow_cover_smoke5](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_timed_flow_cover_smoke5/) | 1 |
| [ddd_trajectory_ab_20260814](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_trajectory_ab_20260814/) | 9 |
| [ddd_trajectory_phase2_20260814](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_trajectory_phase2_20260814/) | 3 |
| [ddd_trajectory_phase3_20260814](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_trajectory_phase3_20260814/) | 5 |
| [ddd_trajectory_root_cg](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_trajectory_root_cg/) | 58 |
| [ddd_trajectory_slot_probe](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_trajectory_slot_probe/) | 1 |
| [ddd_waiting_canonical_k20_exact_control](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_waiting_canonical_k20_exact_control/) | 1 |
| [ddd_waiting_cascade_k20_15m](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_waiting_cascade_k20_15m/) | 1 |
| [ddd_waiting_cascade_k20_15m_exact_seed](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_waiting_cascade_k20_15m_exact_seed/) | 4 |
| [ddd_waiting_cascade_k20_15m_seeded](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_waiting_cascade_k20_15m_seeded/) | 5 |
| [ddd_waiting_exact_seed_smoke](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_waiting_exact_seed_smoke/) | 1 |
| [ddd_waiting_k20_gate](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_waiting_k20_gate/) | 5 |
| [ddd_waiting_labeled_k20_15m_cascade](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_waiting_labeled_k20_15m_cascade/) | 1 |
| [ddd_waiting_labeled_seed_smoke](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_waiting_labeled_seed_smoke/) | 1 |
| [ddd_waiting_no_wait_k20_true_15m](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_waiting_no_wait_k20_true_15m/) | 1 |
| [ddd_waiting_seed_smoke](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_waiting_seed_smoke/) | 2 |
| [ddd_waiting_smoke](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ddd_waiting_smoke/) | 1 |
| [ean_build_baselines](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ean_build_baselines/) | 1 |
| [ean_merge_sequence](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/ean_merge_sequence/) | 10 |
| [fixed_k_model_bakeoff](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/fixed_k_model_bakeoff/) | 15 |
| [fixed_movement_passenger_20260715](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/fixed_movement_passenger_20260715/) | 12 |
| [horizon_time_bounds_20260714](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/horizon_time_bounds_20260714/) | 12 |
| [initial_placement_comparison_300s](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/initial_placement_comparison_300s/) | 11 |
| [mip_start_comparison_20260715](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/mip_start_comparison_20260715/) | 4 |
| [mip_start_smoke](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/mip_start_smoke/) | 2 |
| [oip_mip_start_comparison_20260720](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/oip_mip_start_comparison_20260720/) | 18 |
| [oip_mip_start_comparison_20260720_v2](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/oip_mip_start_comparison_20260720_v2/) | 27 |
| [oip_mip_start_debug](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/oip_mip_start_debug/) | 2 |
| [oip_mip_start_debug_conditional](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/oip_mip_start_debug_conditional/) | 2 |
| [oip_mip_start_debug_fixed](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/oip_mip_start_debug_fixed/) | 2 |
| [phase2_unary_slots](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/phase2_unary_slots/) | 20 |
| [projected_board_time](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/projected_board_time/) | 4 |
| [results](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/results/) | 9 |
| [root_diagnostic_smoke](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/root_diagnostic_smoke/) | 9 |
| [root_diagnostics_20260715](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/root_diagnostics_20260715/) | 6 |
| [shared_eager_comparison](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/shared_eager_comparison/) | 2 |
| [smoke](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/smoke/) | 3 |
| [smoke_fixed_k_model_bakeoff](/Users/felix/Programming/idp/ropeway/ropeway_skip_stop_optimization/benchmarks/output/smoke_fixed_k_model_bakeoff/) | 8 |

### Erkannte Szenario-IDs

- `event_cell_bound_probe_v0`
- `five_station_circle_cw_full_skip_no_wait_headway_b_v0`
- `five_station_circle_cw_full_skip_no_wait_v0`
- `five_station_circle_cw_half_skip_no_wait_headway_b_v0`
- `five_station_circle_cw_half_skip_no_wait_v0`
- `five_station_circle_cw_half_skip_wait_v0`
- `five_station_optimized_initial_placement_all_stop_skip_wait_v0`
- `five_station_optimized_initial_placement_double_all_stop_skip_wait_v0`
- `five_station_optimized_initial_placement_no_skip_no_wait_v0`
- `five_station_optimized_initial_placement_skip_no_wait_v0`
- `five_station_v0`
- `three_station_exhaustive_trajectory_bound_v0`
- `three_station_half_no_skip_no_wait_v0`
- `three_station_optimized_initial_placement_v0`
- `three_station_time_refinement_v0`
- `three_station_two_cabin_network_refinement_v0`
- `three_station_two_cabin_stop_skip_merge_v0`
- `three_station_v0`
