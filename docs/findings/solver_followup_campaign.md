# Bestehende Solver: Folgekampagne vom 9. September 2026

Umsetzung des [beschlossenen Plans](../plans/solver_followup_campaign.md). Abgeschlossen: 17 Hauptläufe, sechs geprüfte Profilpaare und unabhängige Integer-Passagierprüfungen. Historische Rohdaten bleiben unverändert.


## Ergebnis in Kürze

- **K39 Waiting bedient nach 30 Minuten alle 1280 Personen** bei 874705,109680. Gegenüber dem bisherigen besten Seed 13,18 % günstiger; nach Minute 10 kommen noch 4,95 % hinzu. Globaler Gap weiterhin 84,94 %.
- **K38 bleibt nach zehn Minuten beim guten All-Stop-Wert 399287,271408.** Kein besserer freier Skip-Stop-Waiting-Plan gefunden, keine Optimalität des freien Modells bewiesen.
- **Der Nachfragepilot liefert bereits verwertbare Anwendungsbefunde:** 17,28 % Skip-Stop-Gewinn für diffus/Batch, 19,52 % für Express/Batch, 30,62 % für Express/verteilt; beide lokalen Profile sind nachweislich gleich gut.
- **K39 No-Wait kann unter den fixierten Bedingungen K38-All-Stop nicht schlagen:** frische globale LB 433230,965761 > geprüfte All-Stop-UB 399287,271408. Ein kleiner K39-Gap ist für diesen Vergleich nicht erforderlich.
- **Festlegen auf bestehende Bausteine:** CP-Waiting für gute schwierige Fahrpläne, Arc-Flow für exakte No-Wait-Profilvergleiche, gemeinsame Integer-Passagierprüfung. Kein neuer Solverzweig als Voraussetzung für einen präsentierbaren Stand.

## Abgesicherte Grundlage

- Neuer vollständiger `fixed_k_problem_v2`-Fingerprint einschließlich Ressourcen-/Routenwerten, Kapazität, Nachfrage, Kandidaten und Horizontvertrag. `legacy_fingerprint` dient nur der expliziten Wiedererkennung historischer primaler CP-Pläne bei zusätzlichem vollständigem Manifestabgleich und erneuter Prüfung.
- Root-CG-LB-Import verlangt vollständiges Manifest, passenden Hash, `certificate_valid=true`, gültigen Status und `FIXED_K_GLOBAL`-Scope. Alte unvollständige Zertifikate werden abgewiesen. Root-CG schreibt die neue Identität mit.
- Der Primal-Seed-Evaluator erhält die kanonische Nachfrage/Kandidaten des konkreten Problems. Das verhindert eine unbemerkte Rückkehr zur Standardnachfrage bei Profilvarianten.
- CP schreibt Ereignisse während des Laufs als JSONL, ergänzt Runnerzeit und Prozess-Peak-RSS. Extraktion, Callbackvalidierung und Eventzustellung werden separat ausgewiesen; sie sind innerhalb der Solvezeit zu interpretieren.
- 140 Tests bestanden im breiteren gezielten Lauf; nach der zusätzlichen Korrektur der Nachfrageübergabe bestanden 68 betroffene Tests. Keine Änderung der Stop-/Skip-/Waiting-Formulierung für die neue Laufzeitbaseline.

## Erneute unabhängige Prüfung historischer Fahrpläne

Alle festen Integer-Passagier-IPs melden OPTIMAL; das ist jeweils ein Beweis bei **fixierter Bewegung**. Frühere globale Schranken werden nicht importiert.

| Bewegung | Aktuell bestätigte Kosten | Bedient / unbedient |
|---|---:|---:|
| K20 All-Stop | 635.519,998080 | 1280 / 0 |
| K20 Skip-Stop | 525.730,908160 | 1280 / 0 |
| K38 All-Stop | 399.287,271408 | 1280 / 0 |
| K39 No-Wait | 1.262.099,935264 | 416 / 864 |
| K39 Waiting, bester Reservierungsseed | 1.007.532,083464 | 1112 / 168 |

Auch die explizite Übertragung nur der K38-All-Stop-Bewegung in die freie Skip-Stop-Waiting-Domäne reproduziert 399.287,271408. Alle geprüften Pläne erfüllen den vereinbarten endlichen Vertrag. Fortsetzung wird nicht behauptet.

Messdaten und kopierte Originalquellen: `benchmarks/output/solver_followup_20260909/frozen/`, jeweils `source.json`, `validation.json`, `problem_manifest.json` und neu zertifizierter `cp_seed.json`. `headline_validation.json` enthält die gemeinsame Übersicht; `software_snapshot.json` Quellcodehashes, Paketversionen, Betriebssystem und damaligen Gitstatus. Reproduktion: `benchmarks/prepare_solver_followup.py`.

## Ausgeführte Experimente

1. K39 Waiting 1800 s, Produkt, acht Worker, Seed 0, eingefrorener Waiting-Bestseed.
2. Zwei 600-s-Wiederholungen mit Seeds 1 und 2 und derselben Startlösung.
3. K38 Skip-Stop Waiting 600 s aus dem All-Stop-Seed.
4. Kleine K20-Nachfragematrix mit gelabeltem No-Wait-Arc-Flow.
5. Anonymes No-Wait-K39-Arc-Flow mit 1800-s-Maximalbudget und passendem CP-No-Wait-Seed.

Alle fünf Teile sind abgeschlossen. Roh-CP-Werte, unabhängige Assignment-Nachoptimierung und globale Bounds sind getrennt ausgewiesen.

## Abgeschlossener 30-Minuten-Lauf K39 Waiting

Commit der Solverbaseline: `192b9b7`. Unveränderte Produktformulierung, acht Worker, Seed 0, eingefrorener Hint 1007532,083464. Gesamtzeit 1800,517 s. Finale geprüfte Kosten **874705,109680**, **1280 bedient / 0 unbedient**, globale native LB **131762,776090**, Gap **84,94 %**. Die unabhängige feste Passagier-IP bestätigt genau denselben Wert und meldet OPTIMAL für diese Bewegung; kein globaler Optimalitätsbeweis.

Kostenverbesserung gegenüber Seed 13,18 %, gegenüber dem Zustand nach zehn Minuten 4,95 %. Die Physik-/Nachfrage-/Kandidatendomäne ist gegenüber dem früheren K39-Waiting-Fall unverändert. Der stärkere Hint und die längere Zeit sind getrennt von einem Formulierungsgewinn zu interpretieren.

Zeitanteile: Vorbereitung 3,950 s, integrierter Aufbau 1,066 s, Solveraufruf 1795,000 s, abschließende Prüfung/Checkpoint 0,241 s. Callback-Extraktion 4,998 s und Callback-Validierung 10,427 s liegen **innerhalb** des Solveraufrufs; Eventzustellung insgesamt 0,050 s. Modell 51076 Variablen / 106782 Constraints vor Presolve, 27978 Variablen nach Presolve, Suchstart nach 22,10 Solver-s. Peak-RSS 4090,8 MB.

Die zusätzliche unabhängige Nachoptimierung/Prüfung benötigt nach erneuter Instanzvorbereitung etwa 0,98 s; sie gehört nicht zum 1800-s-Hauptbudget.

| Runnerzeit | Beste gemeldete UB | Globale Solver-LB |
|---|---:|---:|
| 60 s | 1005329.684 | 0.000 |
| 120 s | 997888.938 | 50501.851 |
| 300 s | 993368.027 | 50503.613 |
| 600 s | 920283.208 | 74872.837 |
| 900 s | 907548.975 | 94697.996 |
| 1200 s | 905617.105 | 113344.002 |
| 1500 s | 883803.910 | 131580.501 |
| Ende | 874705,110 | 131762,776 |

Zwischenwerte sind Solverberichte; finale Bewegung und Zuweisung wurden unabhängig geprüft. Ergebnisse unter `benchmarks/output/solver_followup_20260909/k39_waiting_1800s_seed0/`.

## Profilintegration geprüft

94 Tests bestehen nach Ergänzung der kleinen Nachfragefallklasse, kanonischer Nachfrageübergabe auch in der Arc-Flow-Abschlussprüfung und Erhalt individueller Nachfrage beim Waiting-Übergang. Dieser Testlauf erfolgte erst nach Ende des langen CP-Laufs. Für die Standardnachfrage bleibt die erzeugte CP-Domäne gleich; die abgeschlossenen Wiederholungen weisen denselben vollständigen Domänenhash und dasselbe Modell wie der erste Lauf aus.

## Wiederholungen: Zufallsstreuung bei identischem Modell

Alle drei K39-Läufe haben denselben vollständigen Problemhash, denselben CP-Domänenhash und denselben Modellhash `73459382e6008a7d844de911ba5689fb71ddf18bab67e8343bc0bb885b8a6bbc`; jeweils dieselbe eingefrorene Startlösung 1007532,083464. Die zweite Codeversion `cdf6399` erhält benutzerdefinierte Nachfrage bei der Vorbereitung, erzeugt für diese unveränderte Standardinstanz aber exakt dasselbe Modell. Acht Worker pro Lauf; drei Seeds sind keine statistisch repräsentative Verteilung.

| Lauf | Budget | Finale UB | Native LB | Bedient / unbedient | Peak-RSS |
|---|---:|---:|---:|---:|---:|
| Seed 0 | 1800 s | 874705,109680 | 131762,776090 | 1280 / 0 | 4090,8 MB |
| Seed 1 | 600 s | 975741,831456 | 81928,146276 | 1184 / 96 | 3117,6 MB |
| Seed 2 | 600 s | 977515,935616 | 71720,290136 | 1216 / 64 | 3381,4 MB |

Alle finalen UBs stimmen mit der unabhängigen festen Integer-Passagier-IP überein. Der direkte Zeiteffekt stammt aus Seed 0: seine nach 600 s gemeldete UB 920283,207978 ist bereits besser als beide anderen Endwerte; weitere 1200 s verbessern diesen Wert um 4,95 %. Die Wiederholungen unterstützen bisher keinen Vorteil mehrerer kurzer Neustarts. Eine allgemeine Rangfolge langer Läufe gegenüber Portfolios ist mit drei Seeds nicht bewiesen. Gleichfalls ist eine höhere Bedienungszahl nicht automatisch ein besserer Journey-Time-Wert: Seed 2 bedient mehr Personen als Seed 1, hat aber höhere Gesamtkosten.

Der beste finale K39-Plan enthält 106 positive Exit-Wartevorgänge (>1 Mikrosekunde), maximal 47,511545 s, Median 3,357143 s; die Summe beträgt 606,296556 Kabinensekunden. Die deklarierte W-Grenze von 1200 s ist in diesem Plan nicht aktiv. Diese Beobachtung beweist nicht, dass eine deutlich kleinere W-Grenze alle optimalen Lösungen erhält.

## K38-Kontrolle: freies Skip-Stop Waiting aus All-Stop

600,749 s Gesamtzeit, acht Worker, Seed 0, freies Skip-Stop Waiting mit W=1200 s und geprüfter All-Stop-Startlösung. Finale UB **399287,271408**, unverändert zum Hint, **1280 / 0**, native LB **90630,229149**, Gap **77,30 %**. Unabhängige feste Passagier-IP bestätigt denselben Wert. Während der Suche wurde keine streng bessere UB gemeldet; die LB stieg weiter. Ein Optimalitätsbeweis für All-Stop liegt somit nicht vor.

Die neue K39-Waiting-Lösung ist mit 874705,109680 noch **119,07 % teurer** als dieser konkrete K38-All-Stop-Plan. Dass K39 nun alle Personen bedient, ist ein Fortschritt der Lösungsqualität, bisher aber kein Nachweis eines betrieblichen Vorteils der zusätzlichen Kabine. K38 und K39 haben jeweils ihre eigene Balanced-Startanordnung; der Vergleich isoliert deshalb weder allein die Kabinenzahl noch allein die Anfangspositionen.

## K20-Nachfragepilot: zwölf kontrollierte Läufe

Bestehender CW-Fünf-Stationen-B-Ring, K20 balanced, No-Wait, Kapazität 8, 1280 Personen, geschlossener 1200-s-Horizont. Lokal = ein Vorwärtsabschnitt, Express = drei/vier, diffus = alle vier Distanzen. Batch: Release 0; verteilt: gleiche Anteile bei 0/200/400/600 s. Für jedes All-Stop/Skip-Stop-Paar sind die normalisierten Vergleichsmanifeste identisch. Nur Modus und dadurch erlaubte Routen unterscheiden sich. Alle finalen Integer-Passagier-IPs bestätigen die integrierten Kosten (numerische Rundung <1e-4).

| Profil | All-Stop-UB | Skip-Stop-UB | Kostenreduktion | Bedient AS / SS | SS-LB | SS-Gap | Zeit AS / SS |
|---|---:|---:|---:|---:|---:|---:|---:|
| diffuse, batch | 635519.998 | 525730.908 | 17.28 % | 1280 / 1280 | 525730.908 | 0.000 % | 1.13 / 11.66 s |
| diffuse, distributed | 332987.271 | 332987.271 | 0.00 % | 1270 / 1270 | 217919.536 | 34.556 % | 2.14 / 110.11 s |
| local, batch | 340770.908 | 340770.908 | 0.00 % | 1280 / 1280 | 340770.908 | 0.000 % | 0.71 / 6.38 s |
| local, distributed | 117149.089 | 117149.089 | 0.00 % | 1280 / 1280 | 117149.089 | 0.000 % | 0.87 / 84.61 s |
| express, batch | 977672.725 | 786850.908 | 19.52 % | 960 / 1280 | 786850.908 | 0.000 % | 0.87 / 9.38 s |
| express, distributed | 609774.544 | 423057.454 | 30.62 % | 940 / 1272 | 422798.614 | 0.061 % | 1.34 / 109.29 s |

Alle sechs All-Stop-Arme sind für den jeweiligen festgelegten Fall optimal. Vier Skip-Stop-Arme sind ebenfalls optimal; diffus/verteilt und Express/verteilt enden mit Zeitlimit. Ein 0-%-Befund bei diffus/verteilt bedeutet **keine gefundene Verbesserung**, mit 34,56 % Gap ausdrücklich keinen Gleichwertigkeitsbeweis. Bei beiden lokalen Profilen ist die Gleichwertigkeit hingegen nachgewiesen. Express/verteilt hat ein zertifiziertes Kostenintervall von 422798,614 bis 423057,454; die gefundene Verbesserung von 30,62 % ist damit fast optimal für diese Instanz.

Die Bedienungszahlen gehören zum Journey-Time-Optimum bzw. gefundenen Journey-Time-Plan. Das Ziel minimiert nicht lexikographisch zuerst die Zahl unbedienter Personen. 960 bediente Personen in der optimalen Express-All-Stop-Lösung beweisen deshalb für sich genommen noch keine maximal mögliche Bedienungszahl von 960.

Die Zeitangabe umfasst externe Vorbereitung, Seed, Netz-/Modellaufbau, Suche und die integrierte unabhängige Nachprüfung. Prozessstart/Import und die zusätzliche separat ausgewiesene Zählungs-IP liegen außerhalb dieser Tabellenzeit. Das 120-s-Budget ist ein Maximum; ein vorab reserviertes Validierungsbudget wird nach Ende der Solversuche nicht automatisch an die Suche zurückgegeben. Daher enden die beiden begrenzten Läufe nach etwa 109–110 s statt exakt 120 s.

### Modellgrößen und Zeitverbrauch der Skip-Stop-Arme

| Profil | Bewegung / Passagiervariablen | Constraints | Netzaufbau | Modellaufbau | Suche | Peak-RSS |
|---|---:|---:|---:|---:|---:|---:|
| diffuse, batch | 21630 / 158925 | 288436 | 1.44 s | 4.64 s | 4.55 s | 1118 MB |
| diffuse, distributed | 21630 / 623420 | 1009776 | 1.36 s | 17.29 s | 88.90 s | 3418 MB |
| local, batch | 21630 / 16125 | 60716 | 1.36 s | 0.95 s | 3.40 s | 380 MB |
| local, distributed | 21630 / 61430 | 132226 | 1.37 s | 2.01 s | 80.40 s | 2578 MB |
| express, batch | 21630 / 110720 | 214176 | 1.36 s | 3.33 s | 3.81 s | 941 MB |
| express, distributed | 21630 / 436740 | 718876 | 1.37 s | 11.85 s | 94.48 s | 4303 MB |

Die Bewegungsdomäne bleibt über alle sechs Skip-Stop-Profile gleich groß (21630 Variablen). Die Passagierformulierung wächst dagegen mit OD-/Release-Kombinationen und erreichbaren Ereignissen: diffus/verteilt hat 623420 Passagiervariablen und über eine Million Constraints. Bei diffus/Batch entfallen 6,09 s auf Netz und Modell gegenüber 4,55 s Suche; dort kann Aufbauoptimierung die Gesamtzeit sichtbar senken. Beim schweren verteilten Fall dominieren 88,90 s Suche, der Aufbau kostet zusätzlich 18,66 s. Diese Ursachen sind anders als beim CP-Waiting-Modell mit etwa einer Sekunde Aufbau und fast dem ganzen Budget in der Suche.

Die absoluten Kosten von Batch und verteilt sind keine reine Solverleistungsmessung: Nachfragezeitpunkte, verfügbare Bedienungszeit und unserved-Term T-release unterscheiden sich. Aussagekräftig sind vor allem die All-Stop/Skip-Stop-Vergleiche **innerhalb** eines Profils. Dieser Pilot ersetzt nicht die früher geplante Sechs-Stationen-/60-Minuten-Demand-Studie.

### Konkreter späterer Arc-Flow-Tuningtest

Der frische anonyme Lauf wählt im nativen Log einen deterministischen Concurrent-LP-Solver. Nach dem Barrier-/Crossover-Ergebnis erscheint `Waiting for other threads to finish`. Das ist ein beobachteter Zeitanteil der LP-Verarbeitung, kein Python-Callback-Engpass. Ein späterer kontrollierter Vergleich `Method=2` (Barrier allein) gegen die bisherige automatische Auswahl könnte diese Wartephase vermeiden; ob die Gesamtzeit und spätere Bounds dadurch besser werden, ist **ungetestet**. Die Parameterbedeutung ist in der [offiziellen Gurobi-Referenz](https://docs.gurobi.com/projects/optimizer/en/current/reference/parameters.html#parameter:Method) beschrieben. In dieser Baseline blieb die Einstellung unverändert. Der generische JSONL-Phasenname `branch_and_bound` umfasst auch das anfängliche Root-LP; das native Log ist für diese feinere Zuordnung maßgeblich.

## Warum die gefundene K39-Vollbedienung noch so teuer ist

Reine Auswertung der gespeicherten, geprüften Integer-Zuweisungen; kein weiterer Solve. `benchmarks/analyze_followup_assignments.py` rekonstruiert die Zeiten aus Kandidaten, ausgewählten Routen, Switch-Zeiten und Waits. Die Summe der individuellen Journey Times reproduziert beide zertifizierten UBs auf <1e-4. Rohdiagnose: `benchmarks/output/solver_followup_20260909/assignment_diagnostics.json`.

| Mittelwert pro Person | K38 All-Stop | K39 Waiting, 30-min-Lösung |
|---|---:|---:|
| Release bis modellierte Plattformabfahrt | 196,49 s | 597,68 s |
| Plattformabfahrt bis Ausstieg | 115,45 s | 85,69 s |
| Gesamte Journey Time | 311,94 s | 683,36 s |

Die modellierte Abfahrt ist nominaler Plattformausgang plus Exit-Waiting. Der erste Anteil enthält damit auch Boarding-/Plattformzeit und ist keine separat beobachtete reine Warteschlangenzeit. Alle Personen sind in beiden Plänen bedient und bei t=0 freigegeben. Der Mehrpreis der **gefundenen** K39-Lösung entsteht hauptsächlich vor der Abfahrt; die spätere Fahrt selbst ist im Mittel sogar kürzer. Das passt zu einem Skip-Stop-Plan, der Fahrtzeit spart, aber viele OD-Gruppen erst spät erreicht. Es beweist weder eine unvermeidbare K39-Eigenschaft noch einen Implementierungsfehler; dafür wäre eine deutlich stärkere Schranke bzw. ein besserer Fahrplan erforderlich.


## Frischer anonymer K39-No-Wait-Versuch

1800-s-Maximalbudget, acht Threads, Seed 0, gültiger CP-No-Wait-Hint 1262099,935264, **kein importierter Root-CG-Bound**. Gesamtzeit einschließlich externer Vorbereitung 1774,695 s; mit Prozessstart 1775,7 s. Die reservierte Abschlussprüfung erklärt das Ende unter 1800 s.

Finale **UB 1262099,935264**, **LB 433230,965761253**, **Gap 65,67 %**, 416 bedient / 864 unbedient. Die unabhängige Abschluss-IP bestätigt dieselben Kosten; eine zusätzliche feste IP/CP-Zertifikatsprüfung bestätigt Bewegung und Zuweisung erneut in 0,63 s nach separater Vorbereitung. Die UB verbessert sich im gesamten Hauptlauf nicht. Der finale Gurobi-Zähler meldet einen bearbeiteten Knoten; praktisch das gesamte Suchbudget entfällt auf Root-LP und Root-Verarbeitung. Native Root-LP-Zeit 707,10 s, erste globale LB oberhalb der All-Stop-Referenz nach 730,814 Runner-s. Weitere native Root-Bounds steigen über 415045,698 und 419481,794 bis zum finalen 433230,966. Die strukturierte Zwischenkurve erfasst diese späten Root-Steigerungen nur verzögert (siehe Messlücke unten).

| Zeit-/Größenanteil | Messwert |
|---|---:|
| Externe Instanzvorbereitung/Runnerdifferenz | ca. 4,04 s |
| Seedbewertung | 0,98 s |
| Exaktes Netzwerk | 6,27 s |
| Modellaufbau | 5,71 s |
| Solveraufruf | 1757,01 s |
| Integrierte unabhängige Nachprüfung | 0,33 s |
| Bewegungsvariablen / gelabelte Bewegungsarcs | 31958 / 42471 |
| Passagiervariablen | 336582 |
| Constraints | 397553 |
| Peak-RSS | 4530,8 MB |

**Beantwortete Betriebsfrage:** Für diese K39-No-Wait-Instanz gilt `Optimum >= 433230,965761 > 399287,271408 = Kosten des konkreten K38-All-Stop-Plans`. Selbst das unbekannte K39-Optimum ist mindestens 8,50 % teurer als die Referenz. Die Aussage ist auf die dokumentierten Fixed-K-/Balanced-Startbedingungen, Nachfrage, No-Wait-Domäne und den endlichen Horizont beschränkt. Sie gilt nicht für Waiting, andere Starts oder variable Flottenzahlen. Der globale K39-Gap bleibt groß, aber dieser konkrete Vergleich ist trotzdem entschieden.

Die neue Movement-Kompression auf 75,25 % der gelabelten Arc-Zahl beseitigt weder den großen Passagierblock noch den LP-Engpass. Ein guter Hint verhindert eine schlechte Anfangs-UB, führt in diesem Lauf aber nicht zu weiterer primaler Verbesserung.

## Empfehlung nach dieser Kampagne

1. **Die Anwendungsstudie jetzt auf die vorhandenen Solver festlegen.** Der kontrollierte Pilot liefert bereits beweisbare positive und negative Befunde: 17,28 % Gewinn bei diffuser Batch-Nachfrage, 19,52 % bei Express-Batch, Gleichwertigkeit bei lokalen Profilen und ein fast optimaler Express-/Verteilt-Vorteil von 30,62 %. Diese Fälle sind eine belastbare Grundlage für Tabellen und Argumentation in Thesis/Präsentation.
2. **CP-SAT Produkt/Waiting für gute K39-Fahrpläne beibehalten.** Der lange Lauf verbessert auch nach zehn Minuten weiter und erreicht Vollbedienung. Ein späterer längerer Lauf sollte vom neuen geprüften Wert 874705,109680 starten. Erfolgskriterien getrennt: frühere Bedienung/niedrigere UB, stärkere LB, und tatsächlicher Vergleich mit 399287,271408. Einfach mehr Laufzeit ist bisher kein glaubwürdiges Versprechen eines bald kleinen Gaps.
3. **Arc-Flow als exakte No-Wait-Referenz behalten.** Es löst vier Skip-Stop-Profile vollständig und ein weiteres nahezu optimal. Der K39-No-Wait-LB-Vergleich zeigt zusätzlich, dass eine konkrete Betriebsfrage beantwortet werden kann, ohne das ganze K39-Optimum zu kennen. Daraus folgt keine übertragbare Waiting-LB.
4. **Falls wir genau einen weiteren Rechentest priorisieren:** bestehendes integriertes CP-SAT auf dem offenen K20-Profil diffus/verteilt, mit exakt derselben No-Wait-Domäne und dem geprüften All-Stop-Hint. Die große zeitexpandierte Passagierformulierung des Arc-Flow ist dort ein konkreter Anlass; ein Erfolg des kompakteren CP-Modells ist noch ungetestet. Weder Warten noch Anfangspositionen dabei ändern.
5. **Kleine Implementierungs-/Parametertests statt neuer Solverfamilie:** Root-LP-Methode beim anonymen Arc-Flow isoliert vergleichen; bei kleinen exakten Fällen Aufbaukosten reduzieren, falls viele Replikationen nötig werden. Das sind plausible Optimierungsstellen, kein bewiesener Durchbruch. Reservierungsheuristik, neue Nicht-MIP-Familie und Reservoir-Neuformulierung bleiben vorerst geparkt.

Ein solches Festlegen bedeutet zwei begründete Rollen im selben System mit gemeinsamer Physik, Identität und Integer-Passagierprüfung. Es bedeutet nicht, alle historischen Prototypen weiterzuentwickeln. Die behobenen Zertifikats-/Nachfrageübergabefehler waren reale Implementierungsprobleme; die verbliebenen großen Gaps und langen Root-LP-Phasen sind dadurch nicht als Codefehler bewiesen.

### Verbleibende Messlücke im anonymen Callback

`optimization/ddd/exact_anonymous_arc_flow.py` liest Bounds nur bei `GRB.Callback.MIP`; der gelabelte Runner verarbeitet zusätzlich `MIPNODE`. Im frischen anonymen Lauf zeigt der native Root-Log deshalb bereits 415045,698, während der JSONL-Strom noch 407312,596 hält. Die JSONL-LB bleibt eine konservative gültige Information, bildet aber den Zeitpunkt weiterer Root-Fortschritte nicht vollständig ab. Das ist eine konkrete Lücke der Instrumentierung, kein Beleg für einen falschen finalen Bound. Die finale Auswertung liest `ObjBound` nach dem Solve; Root-Phasen und Zwischenfortschritte müssen hier zusätzlich aus `terminal.log` bewertet werden. Ein späteres Angleichen der Callback-Abdeckung ist sinnvoll; die jetzt gemessene Baseline wurde während des Laufs nicht verändert.

## Zusätzliche K38-Laufzeitdaten

Das K38-Waiting-Modell hat 49303 Variablen / 103054 Constraints, 1369 freie Wait-Variablen und 4852 Ride-Kandidaten. Vorbereitung 0,174 s, Seed 0,201 s, Aufbau 1,100 s, Solve 598,628 s, Abschlussprüfung 0,415 s, Peak-RSS 3471,0 MB. Die Callback-Extraktion/Validierung braucht innerhalb der Solvezeit nur 0,438 s. Der K38-UB-Stillstand entsteht somit ebenfalls nicht durch teure Python-Callbacks.

## Artefakte, Code und Reproduktion

- Aktuelle Rohdaten: `benchmarks/output/solver_followup_20260909/`. Pro Hauptlauf `result.json`, `config.json`, `events.jsonl`; native Logs und Prozessmetadaten direkt im Laufordner oder unter `job_logs/`. CP-/No-Wait-Nachprüfungen unter `post_ip/`, Profilnachprüfungen in `metrics.json`.
- Maschinenlesbare Gesamtauswertung: `summary.json`, `results.csv`, `progress.csv`, `portfolios.json`, `campaign_checks.json`, `assignment_diagnostics.json` im Kampagnenordner. `campaign_checks.json` bestätigt alle 17 Hauptläufe und sechs Paaridentitäten. Zwischen-LBs im JSONL sind beim anonymen Root-Knoten konservativ; finale Bounds aus `result.json`.
- Versionierte Tabellenkopien: [Endwerte](solver_followup_results.csv), [Verlauf](solver_followup_progress.csv). Erstellung: `benchmarks/summarize_solver_followup.py`; Assignmentzerlegung: `benchmarks/analyze_followup_assignments.py`.
- OO-Profilbaustein: `src/ropeway_skip_stop_optimization/benchmarking/ddd_ring_demand_case.py`; Runner: `benchmarks/run_ring_demand_case.py`. Reihenfolge und frische Prozesse: `benchmarks/run_solver_followup_sequence.py`. Historische Prüfung/Seedtransfer: `benchmarks/prepare_solver_followup.py`. Anonymer Versuch: `benchmarks/run_solver_followup_anonymous.py`.
- Die vorbereiteten Phasen verhindern das Überschreiben vorhandener Runordner. Für Replikationen einen frischen Ausgabeort bzw. eigene Kampagnenkopie verwenden.
- Baselinecommit `192b9b7`, Profil-/Runnercommit `cdf6399`. Der finale Ergebniscommit enthält Bericht, Tabellen, Diagnosewerkzeug und komprimierte Messdaten. Baselinearchiv: `benchmarks/snapshots/solver_followup_20260909_baseline.tar.gz`; vollständiges Ergebnisarchiv: `benchmarks/snapshots/solver_followup_20260909_results.tar.gz` mit SHA-256-Dateimanifest.
- 94 gezielte Tests bestanden nach der letzten produktiven Modell-/Profiländerung; danach keine weitere Änderung der Solverformulierung. Neue Auswertungsskripte wurden an allen gespeicherten Ergebnissen ausgeführt, Kostenrekonstruktion und Bound-/Paaridentitäten geprüft; Ruff und Whitespaceprüfung bestanden.
