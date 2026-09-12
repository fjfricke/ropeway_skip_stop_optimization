# Veröffentlichte Solver und alternative Formulierungen für Skip-Stop-Seilbahnen

## Entscheidung

Die bisherigen negativen Versuche rechtfertigen es, die konkret getestete eigene Nachbarschaftssuche zurückzustellen. Sie rechtfertigen weder die Aussage, dass andere veröffentlichte Verfahren ausgeschöpft seien, noch die Annahme, dass die Forschungsfragen bereits beantwortet seien.

Vier bislang unzureichend untersuchte Richtungen sind relevant: native mengen- und listenbasierte Optimierung mit **Hexaly**, vollständige arithmetische Optimierung mit **Z3/OptiMathSAT**, **temporale numerische Planung** mit vorhandenen Planern wie TemPEST und Patty sowie die weiterentwickelte Beweissuche in **OptalCP**. Diese Richtungen unterscheiden sich erheblich in Übertragbarkeit, Softwarezugang und Beweisleistung. Keine Quelle belegt einen Durchbruch für die vollständige hier betrachtete Seilbahn.

Für einen weiteren vollständigen Solververgleich ist **Hexaly der erste praktische Kandidat**, sofern ein kleiner Zahlenbereichs- und Zertifikatscheck besteht. Für einen grundlegend anderen exakten Modellansatz ist **direktes OMT mit ganzzahligen Ereigniszeiten** am saubersten abgrenzbar. Die wissenschaftlich interessanteste zusätzliche Modellfamilie ist **temporale numerische Planung**; ihr Einsatz verlangt zunächst eine Prüfung von Zeit-, Passagier- und Zielsemantik. **OptalCP hat konkrete Forschung zur Verbesserung unterer Schranken, scheitert aber als direkter Austauschbackend an den dokumentierten Zahlenbereichen unseres Mikrosekundenmodells.**

Diese Einordnung betrifft Modellierung in vorhandenen Engines. Sie beinhaltet keinen neuen selbst entwickelten Suchalgorithmus, keinen weiteren LNS-Controller und keine automatische neue Langkampagne.

## 1. Welche Fragen noch offen sind

Die [Research Questions im Modellierungsdokument](../../../proposal/modeling_notes/main.tex) betreffen eine physikalisch brauchbare Formulierung, geeignete Lösungsverfahren und die Nachfragebedingungen, unter denen Skip-Stop besser als All-Stop oder feste Bedienungsmuster funktioniert. Der [Versuchsplan für künstliche Fälle](../plans/artificial_case_capacity_experiments.md) konkretisiert den Vergleich für sechs Stationen und die maximal vollständig bedienbare Nachfrage. Die [Nachfragefamilien](../reference/demand_case_families.md) unterscheiden unter anderem diffuse, lokale, Express-, komplementäre und gemischte Nachfrage sowie verschiedene zeitliche Profile.

Die kleinen positiven Fünf-Stationen-Ergebnisse sind Teilantworten. Sie ersetzen keine belastbare Untersuchung der geplanten sechs Stationen mit Waiting, höherer Auslastung und flexibler Flotte. Eine einzige stagnierende Reservoirinstanz ist ebenso wenig eine ausreichende Untersuchung der Nachfrageabhängigkeit.

| Forschungsfrage | Erforderliche Aussage | Dafür allein nicht ausreichend |
|---|---|---|
| Nutzen von Skip-Stop | Vergleichbare Betriebsbedingungen und valide Kosten-/Bedienungsvergleiche über Nachfragefamilien | Beste gefundene Pläne aus verschiedenen Start- oder Flottendomänen vergleichen |
| Maximale bedienbare Nachfrage | Nachfrageskalierung mit nachgewiesen zulässiger Untergrenze und belastbarer Obergrenze | Eine nicht bediente Menge nach Timeout als Kapazitätsmaximum bezeichnen |
| Flexible Flotte | Gemeinsames Modell mit optionalem Einsatz, überprüfter Depotgeometrie und gleichen Randbedingungen | Fixed-K38 und Fixed-K39 mit veränderten Startpositionen als verschachtelte Suchräume behandeln |
| Modellqualität | Schrankenverlauf, native Verbesserungen und korrekt reproduzierte Zertifikate | Nur Variablenzahl oder Laufzeit bis zur Seedübernahme |
| Praktische Steuerbarkeit | Physikalisch umsetzbare Fahrpläne mit erlaubtem Waiting und ganzzahligen Fahrgästen | Gute Lösungen einer anonymen, fraktionalen oder zeitlich gelockerten Relaxation |

Ein vollständiger Optimalitätsbeweis ist nicht für jede Vergleichsaussage notwendig. Bei Kostenminimierung belegt beispielsweise `UB_skip < LB_allstop` einen Vorteil gegenüber dem **optimalen All-Stop-Betrieb derselben Vergleichsdomäne**. Ein besserer Skip-Stop-Plan als ein einzelner All-Stop-Referenzplan belegt dagegen nur den Vorteil gegenüber dieser Referenz. Für die maximale Nachfrage bleibt eine eigene Kapazitätsaussage notwendig. Diese Unterscheidung präzisiert die Beweisziele; sie verkleinert den Untersuchungsumfang nicht.

## 2. Ausgangslage und unveränderliche Modellbedingungen

Der jüngste [Vergleich mit global freier Passagierzuordnung und Konfliktnachbarschaften](../findings/reservoir_global_passengers_conflict_test_20260911.md) umfasst 18 Versuche ohne relevante Verbesserung. Die Kosten bleiben bei **368.765,817136 Passagiersekunden**, 1.280 Personen werden bedient, 38 Einsätze genutzt. Mit der externen globalen Schranke **209.409,890300** verbleiben **43,2133 %** Gap. Das beweist weder globale Optimalität noch, dass eine deutlich bessere Lösung existiert. Es zeigt, dass die bisherigen Versuche diese Unsicherheit nicht auflösen.

Die Referenz R hat maximal 50 optionale Kabinen, einen Betriebshorizont von 1.800 Sekunden, Exit-Waiting bis 1.200 Sekunden und Mikrosekundenticks. Ihr physischer Fingerprint lautet `ea2b46d53da6f34147bfd5a9c1a635116e89eb47afd84cfd036b56971376ac65`. Der bisherige Reservoirvertrag erlaubt pro Kabine einen zusammenhängenden Einsatz einschließlich mehrerer Umläufe, aber keinen erneuten Einsatz nach Rückkehr. Ein späterer Wiedereinsatz wäre eine explizite Erweiterung.

Für einen übertragbaren neuen Ansatz müssen insbesondere folgende Eigenschaften erhalten bleiben:

- STOP und SKIP haben unterschiedliche Dauern und Ressourcenbelegungen; Bypass-Überholen bleibt zulässig.
- Waiting ist nur an den vorgesehenen STOP-Exits erlaubt, einschließlich der bisherigen Waiting-Freigabephase. Es gibt kein freies Warten auf beliebigen Streckenabschnitten.
- Ressourcen werden zu ihren tatsächlichen Eintritts- und Räumzeiten geschützt. Einige Schutzintervalle beginnen erst nach Bewegungsbeginn; ein einzelner Freigabezeitpunkt pro Ressource genügt nicht als allgemeiner Ersatz.
- Passagiermengen sind ganzzahlig. Ein- und Ausstieg erfordern STOP, Nachfragefreigaben gelten am tatsächlichen Plattformausstieg einschließlich erlaubtem Waiting, Ankunft am Ziel vor dessen Exit-Waiting.
- Direkte kanonische Beförderungen erhalten ihre Identität. Keine Umstiege, zusätzlichen Fahrgastrunden oder stillen Wechsel zwischen Kabinen.
- Aussteigen und anschließendes Einsteigen werden korrekt getrennt; beide Mengen teilen sich nicht fälschlich eine gemeinsame Kapazitätssumme.
- Reservoirrückkehr, Eintritt genau am Horizont und Schutz über den Horizont hinaus bleiben erhalten. Fixed-K besitzt einen anderen Vertrag für den Abschluss der letzten Bewegung.
- Kostenminimierung und Minimierung unbedienter Personen bleiben verschiedene Ziele. Eine andere Engine darf daraus keine neue lexikografische Zielsetzung machen.

Diese Bedingungen sind im vorhandenen [IBM-Modell](../../src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_ibm_cp_model.py), den CP-Bausteinen und den unabhängigen Prüfern verankert. Ein Scheduling-Paper ohne diese Kopplungen ist ein Übertragungshinweis, kein Leistungsnachweis für die Seilbahn.

## 3. Überblick über die untersuchten Richtungen

Die Bewertung in dieser Tabelle ist eine fachliche Einschätzung zur konkreten Übertragung, keine empirisch bestimmte Erfolgswahrscheinlichkeit.

| Richtung und verfügbare Software | Tatsächlicher Unterschied | Gute Pläne | Globaler Nachweis | Einordnung für dieses Projekt |
|---|---|---|---|---|
| Hexaly: Listen, Mengen, optionale Intervalle | Andere native Modellstruktur und interne hybride Suche | Plausibler neuer Kandidat | Bounds vorhanden; Stärke für unser Ziel offen | Erster vollständiger neuer Engine-Test nach Kompatibilitätscheck |
| Z3 / OptiMathSAT: OMT über lineare Integerarithmetik | Logische Disjunktionen und exakte Arithmetik statt zeitlicher Flusskopien | Offen | Vollständiges beschränktes Modell grundsätzlich exakt lösbar | Sauberer exakter Alternativansatz, kein belegter Leistungsvorteil |
| TemPEST: optimale temporale Planung | Konkrete Aktionen plus Abstraktion noch längerer Pläne | Offen | Veröffentlichter Optimalitätsansatz für unterstützte Metriken | Besonders interessante Formulierungsforschung; Semantikprüfung zuerst |
| Patty: symbolische temporale Muster | Zeitvariablen in kompakten Aktionsmustern, Erweiterung bei Bedarf | Positive Evidenz für verwandte Zugdisposition | Gefundener Plan / kleine Mustertiefe ist kein Kostenbeweis | Interessanter vorhandener Planer für Kapazitätszulässigkeit |
| OptalCP: native Intervalle und FDS | Weiterentwickelte vollständige Beweissuche innerhalb einer Engine | Plausibel | Konkrete veröffentlichte LB-Verbesserungen | Direkter Port derzeit durch Integer-/Intervallgrenzen ausgeschlossen |
| Athanor: Essence-Spezifikationen | Solver erzeugt Nachbarschaften aus strukturierten Typen automatisch | Wissenschaftlich begründete Alternative | Keine globale Gap-Schließung durch lokale Suche allein | Reserve für Incumbents, nicht erste Wahl für beide Ziele |
| Aries: zeitliche/numerische Planung | Bestehender Planer und CP/SAT-Kern mit zeitlicher Kausalstruktur | Offen | Abhängig von Planerfragment und Ziel | Weitere verfügbare Forschungsengine, keine bestätigte Seilbahnübertragung |
| UPPAAL CORA: bepreiste Zeitautomaten | Symbolische Uhrbereiche statt einzelner Zeitwerte | Auf kleinen Modellen plausibel | Kostenoptimale Erreichbarkeit unter Modellvoraussetzungen | Alte Engine, hoher Zustandsaufwand; kein kurzfristiger Hauptkandidat |
| GCG: automatische Dantzig-Wolfe-Zerlegung | Vorhandener Solver übernimmt Pricing und Branching | Modellabhängig | Vollständiges Branch-Price-and-Cut | Bereits erwähnt, aber nicht gleichbedeutend mit bisherigem Root-CG |
| Kapazitiertes MAPD / MCA-RMCA | Gemeinsame Transportzuordnung und kollisionsfreie Roboterwege | Veröffentlichter Code vorhanden | Die betrachtete Heuristik liefert keinen globalen Gap | Erfordert erheblichen Umbau des Bewegungsmodells |
| TSN-Scheduling / TSNKit | Exakte Zeitfenster, Leitungsbelegung, teilweise No-Wait | Verfügbare Vergleichsimplementierungen | Je Verfahren verschieden | Gute Formulierungsquelle; kein fertiger Seilbahnsolver |
| Prozessplanung: State-Task-/Resource-Task-Netze | Material-, Bestands- und Ereignisbilanz statt nur Fahrzeugtrajektorien | Möglich | Bei exaktem MILP-Modell | Große Modellierungsarbeit, teilweise schon Nähe zu EAN/Arc-Flow |
| Warteschlangen / Max-plus / Petri-Netze | Kapazitäts- und Stabilitätsanalyse statt kompletter Tagesfahrpläne | Nicht das primäre Ergebnis | Beweis nur für jeweiliges analytisches Modell | Ergänzung für Erklärungen, kein Ersatz des integrierten Problems |

## 4. Hexaly: eine vorhandene Engine für strukturierte Entscheidungen

### Forschungs- und Softwarebasis

Hexaly bietet neben skalaren Variablen Mengen, Listen und optionale Intervalle. Die dokumentierte Engine kombiniert unter anderem lokale Suche, Propagation, Branch-and-Bound sowie automatische Reformulierungen und Spaltengenerierung. Die frühere Einordnung als ausschließlich heuristischer Backend in [ean_decomposition.md](../plans/ean_decomposition.md) ist deshalb zu eng. Das bedeutet allerdings nicht, dass jede Modellformulierung starke Bounds erhält.[^1][^2]

Ein Entwicklerbeitrag beschreibt Schranken aus erkannten Einmaschinenproblemen, unter anderem für gewichtete Fertigstellungszeiten. Für diese Zielfamilie berichtet er durchschnittliche Gap-Reduktionen von 55 % auf 24 %. Das ist ein herstellernaher Befund für andere Schedulingmodelle, kein unabhängiger Nachweis für variable Passagiermengen. Gerade die festen Gewichte solcher Unterprobleme unterscheiden sich von unserer variablen Besetzung.[^3]

Ein Gegenbefund ist wesentlich: In Abreus Vergleich von 80 Job-Shop-Instanzen lieferte IBM CP im Mittel bessere Lösungen als Hexaly; bei Total Flowtime erreichte keiner der getesteten Solver einen Optimalitätsnachweis. Ein Wechsel zu einer neuen Engine löst schwierige Fertigstellungszeitziele also nicht automatisch.[^4]

### Konkrete Übertragung auf die Seilbahn

**Eigene Modellierungsableitung:** Native Listen könnten die Reihenfolge der tatsächlich benutzten Ressourcenintervalle darstellen. Pro Ressource bleibt ihre Reihenfolge frei; es wird keine gemeinsame Kabinenreihenfolge über alle Ressourcen erzwungen. Eine vorbeifahrende Kabine kann am Bypass eine andere Reihenfolge erhalten als an der Plattform.

Bewegungen bleiben optionale STOP-/SKIP-Besuche mit Zeitvariablen. Waiting verlängert genau die Ressourcenintervalle, die laut Domäne davon abhängen. Reihenfolgebedingungen zwischen benachbarten Listeneinträgen können für gewöhnliche geschützte Intervalle deren Nichtüberlappung darstellen; Sonderfälle mit zusätzlichen paarabhängigen Regeln dürfen dabei nicht verschwinden. Die Liste muss exakt die präsenten Nutzungen enthalten.

Passagiermengen, Demand-Bilanzen und Belegung bleiben gemeinsame Entscheidungen des Solvers. Es wäre keine ausreichend aussagekräftige Umsetzung, lediglich eine externe Replay-Kostenfunktion anzuhängen oder Bewegung unabhängig von den Passagieren zu optimieren. Ebenso wenig genügt es, jede heutige Hilfsvariable mechanisch in einen anderen API-Aufruf zu übersetzen: Der Test soll die native Struktur nutzen, ohne die zulässigen Fahrpläne zu verändern.

Flexible Flotte lässt sich zunächst mit optionalen Einsätzen abbilden. Das reduziert nicht automatisch die Zahl potenzieller Besuche. Ein späteres Modell mit einer variablen Menge von Einsätzen und separatem Kabinenbestand wäre eine zusätzliche Formulierungsentscheidung; Wiedereinsatz ist nicht bereits durch einen Solverwechsel implementiert.

### Erwartung, Aufwand und Beweisgrenze

Der plausible Vorteil liegt in anderen internen Änderungen an Reihenfolgen und Zuordnungen sowie der Auswertung strukturierter Ausdrücke. Die Engine kann solche Änderungen selbst suchen. Ob unsere engen Gleichheiten zwischen Bewegung, Waiting und Besetzung diese Suche ebenfalls blockieren, bleibt offen.

Hexaly dokumentiert macOS-Unterstützung einschließlich ARM64 und akademische Lizenzen. Es handelt sich nicht um eine frei verfügbare quelloffene Solverengine.[^5] Vor einem Port sind die tatsächliche Lizenz, Integer-/Intervallwerte, importierte Startwerte und der vollständige Zertifikatsexport zu prüfen.

Der Status `OPTIMAL` ist laut Dokumentation mit einer relativen Toleranz von 0,01 % verknüpft. Für unsere Auswertung müssen daher numerischer UB, LB und Toleranz berichtet werden; das Statuswort allein ist kein exakter Tick-Optimalitätsbeweis.[^6]

**Urteil:** Der am besten begründbare nächste praktische Test für eine wirklich andere native Suche. Potenzial für bessere Incumbents vorhanden; starke globale Schranken sind eine offene Testfrage und dürfen nicht zugesagt werden.

## 5. OptalCP: relevante Beweissuche, aber kein einfacher Backendwechsel

Heinz, Vilím und Hanzálek untersuchen eine verbesserte Failure-Directed Search in OptalCP. Sie berichten verbesserte untere Schranken auf 78 von 84 offenen Job-Shop- und 226 von 393 RCPSP-Instanzen bei 900 Sekunden. Der Vergleich der Suchgeschwindigkeit verwendet einen Kern und bei IBM explizit FDS; er ist kein Vergleich vollständiger Zwölf-Worker-Portfolios. Ein Autor ist OptalCP-Entwickler. Das macht die Arbeit direkt relevant für Beweissuche, verlangt aber eine vorsichtige Übertragung.[^7]

Ein zusätzlicher Job-Shop-Benchmark berichtet unterschiedliche Stärken von OptalCP, IBM, CP-SAT und Hexaly. Der zugängliche Preprint untersucht überwiegend Makespan und Standard-Jobs, nicht Passagierfluss oder Reservoir. Seine Rangfolge wird deshalb nicht als Vorhersage für die Seilbahn verwendet.[^8]

OptalCP besitzt eine DOcplex-Kompatibilitätsschicht. Die dokumentierten Abweichungen umfassen unter anderem Übergangszeiten in `noOverlap`: OptalCP erzwingt sie auch zwischen indirekten Nachfolgern. Ein ungeprüfter Importwechsel kann deshalb eine andere zulässige Menge erzeugen. Unsere expliziten Schutzintervalle sind hierfür eine bessere Ausgangsbasis als ein stiller Wechsel zu anders interpretierten Übergangsmatrizen.[^9]

Die entscheidende unmittelbare Hürde sind die dokumentierten Grenzen:

| Größe | Dokumentierter Bereich / Referenzwert |
|---|---:|
| OptalCP maximale Integerentscheidung bzw. Integerausdruck | 1.073.741.823 |
| OptalCP maximaler Intervallstart/-endwert | 715.827.882 |
| Unser Betriebshorizont in Mikrosekunden | 1.800.000.000 |
| Unsere maximale Waitingdauer in Mikrosekunden | 1.200.000.000 |
| Unser aktueller Reisezeitwert in Personenticks | 368.765.817.136 |

Die API dokumentiert, dass auch arithmetische Ausdrücke im unterstützten Bereich bleiben müssen.[^10] Damit ist das aktuelle absolute Zeitmodell nicht direkt darstellbar. Die nominelle negative Intervallgrenze würde selbst durch Zentrierung keine Spanne von 1.800.000.000 Ticks ermöglichen. Eine Division durch 1.000 wäre eine Rasteränderung: Bei frei erlaubten Ein-Mikrosekunden-Waitingwerten ist sie nicht verlustfrei.

Eine Darstellung mit mehreren Zeitkomponenten oder getrennten Epochen ist theoretisch denkbar, aber eine erhebliche zusätzliche Formulierung mit Synchronisationsbedingungen. Sie ist kein kostenloser Importwechsel. Für einen kurzen Pilot sollte dieser Umbau nicht still vorausgesetzt werden.

Außerdem liefert die kostenlose Preview laut Dokumentation keine vollständigen Variablenwerte. Für unabhängig überprüfte Fahrpläne ist die Academic- oder Full-Ausgabe nötig.[^11]

**Urteil:** Unter den neuen Funden besonders relevante Literatur für den Wunsch nach stärkeren Schranken. Unter unveränderter Mikrosekundensemantik derzeit kein kurzfristig nutzbarer Austauschbackend. Zuerst müsste eine tatsächlich verfügbare passende Engineversion oder eine nachweislich verlustfreie kompakte Darstellung feststehen.

## 6. OMT: ein exaktes Ereignismodell in Z3 oder OptiMathSAT

### Verfahren und Evidenz

Optimization Modulo Theories verbindet logische Entscheidungen mit arithmetischen Bedingungen und einer Zielfunktion. Z3 bietet einen nativen Optimierungsmodus; OptiMathSAT unterstützt Optimierung über lineare Arithmetik. Der Benutzer beschreibt das Modell, während die Engine Entscheidungen, Konfliktlernen und Optimierung übernimmt.[^12][^13]

Die Flussähnlichkeit allein ist kein positives Performanceargument. Kasslin und Berg vergleichen 2025 kumulatives Scheduling mit Speicher und Transportverzögerungen. Gurobi löst dort alle Versuche innerhalb von 32 Sekunden; die OMT-Solver sind deutlich langsamer und lösen zahlreiche Optimierungsfälle nicht im 30-Minuten-Limit. Bei zusätzlicher Alles-oder-nichts-Logik wird OMT vergleichbarer. Das spricht gegen ein pauschales Versprechen und für einen sehr gezielten Test der disjunktiven Seilbahnstruktur.[^14]

TSN-Arbeiten liefern eine weitere benachbarte Problemklasse: Nachrichten müssen zeitlich kollisionsfrei über gemeinsam benutzte Leitungen gelangen. TSNKit stellt konkrete SMT- und MILP-basierte Schedulingimplementierungen bereit. Die Analogie betrifft präzise Zeiten und Ressourcenkonflikte; Nachrichten nehmen unterwegs keine frei zuzuordnenden Fahrgäste auf.[^15]

### Exakte Übertragung ohne eigene Suchlogik

**Eigene Modellierungsableitung:** Besuche erhalten ganzzahlige Tickzeiten `t`, Waiting `w`, Route und Aktivität. Für zwei präsente Nutzungen derselben exklusiven Ressource gilt direkt

\[
\operatorname{present}(i)\land\operatorname{present}(j)
\Rightarrow(e_i\le b_j\;\lor\;e_j\le b_i).
\]

Eintritt `b` und geschütztes Ende `e` sind die vorhandenen affinen Ausdrücke aus Besuchszeit, Route und Waiting. Die Reihenfolge bleibt eine Solverentscheidung. Anders als im zeitexpandierten Arc-Flow erzeugt der Waitingbereich keine Variable für jeden möglichen Zeitpunkt.

Ganzzahlige Beförderungsmengen `q_r`, Nachfragegleichungen und Segmentkapazitäten lassen sich direkt übernehmen. Das Kapazitätsziel `min sum(u_g)` ist linear. Auch das Reisezeitziel muss nicht als allgemeines nichtlineares Integerproblem formuliert werden: Die bereits aggregierte Aussteigermenge `n_e` liegt zwischen null und acht. Mit vier Bits und `n_e <= 8` gilt exakt

\[
n_e=\sum_{b=0}^{3}2^b z_{e,b},\qquad
n_et_e=\sum_{b=0}^{3}2^b\operatorname{ite}(z_{e,b},t_e,0).
\]

`ite` bezeichnet eine Fallunterscheidung. Es entstehen nur lineare arithmetische Zweige und boolesche Bedingungen. Die ursprüngliche Menge bleibt gleich; insbesondere ist dies keine fraktionale Passagierrelaxation. Die Umformung ist eine elementare eigene Ableitung für die begrenzten Mengen, kein publizierter Seilbahn-Performancebefund.

Z3-Integer können mathematische ganzzahlige Tickwerte darstellen, ohne den OptalCP-Intervallbereich zu übernehmen. Geeignete explizite endliche Grenzen bleiben trotzdem nötig. Warteschritte, Ressourcenpräsenz am Horizont und alle Lebenszyklusbedingungen gehören weiterhin ins Modell.

### Warum es anders sein könnte – und warum es ebenfalls scheitern kann

Der Unterschied liegt in der Behandlung der disjunktiven Arithmetik, nicht darin, dass CP-SAT keine Logik kennen würde. CP-SAT verfügt ebenfalls über SAT-basierte Suche und zusätzliche Propagation. Ein Vorteil von OMT ist daher eine überprüfbare Hypothese, keine Folgerung aus dem Namen.

Eine naive OMT-Formulierung erzeugt quadratisch viele Konfliktpaare und verzichtet möglicherweise auf wirksame spezialisierte `noOverlap`-Propagation. Große Mengen- und Kostensummen bleiben schwierig. Ein kompakter Text oder der Verzicht auf Big-M garantiert keine kleine Suche.

**Urteil:** Ein sauberer vollständiger Alternativtest, besonders zunächst für das lineare Kapazitätsziel. Native Optimierung und ihr Status werden verwendet; kein selbst geschriebener Scheduling-Suchbaum. Nach Timeout zählen ausschließlich tatsächlich verfügbare gültige Modelle und nachgewiesene Schranken. Eine unbekannte Antwort darf keine Unzulässigkeit oder vermeintlich steigende LB erzeugen.

## 7. Temporale numerische Planung: die wichtigste zusätzliche Modellfamilie

### TemPEST und abstrakte zukünftige Aktionen

Panjkovic und Micheli beschreiben einen optimalen temporalen Planungsansatz, der einen konkreten Plananfang und eine optimistische Abstraktion weiterer Aktionen gemeinsam kodiert. Die Erweiterung von 2024 stärkt die kausalen und zeitlichen Bedingungen im abstrakten Teil. Benötigt eine optimale Lösung der Kodierung keine abstrakten Aktionen mehr, kann ein global optimaler Plan folgen, auch gegenüber längeren Plänen. Die Beweise gelten für das dort definierte Planungsfragment und dessen Ziele; die Arbeit ist kein allgemeiner Seilbahnsatz.[^16]

Mit **TemPEST** existiert eine dazugehörige Software, inzwischen mit Unified-Planning-Anbindung und Z3 als Standardbackend. Die veröffentlichte API nennt Makespan und Aktionskosten als Optimierungsziele. Das ist ein vorhandener Planer, kein Auftrag, diese Abstraktionssuche selbst neu zu implementieren.[^17]

**Eigene Übertragungsüberlegung:** Aktionen könnten Dispatch, STOP-Bewegung, SKIP-Bewegung, Boarding, Alighting und Rückkehr darstellen. Zustandsgrößen speichern Kabinenort, verbleibende Nachfrage, Bordmengen und Reservoirbestand. Ein Planer entscheidet sowohl, welche Aktionen vorkommen, als auch wann sie stattfinden. Ein zusätzlicher Umlauf entsteht durch weitere Aktionen; er muss nicht unbedingt schon als vollständige Zeitnetz-Kopie vorliegen.

Das ist für flexible Einsätze interessant. Allerdings wird ein Bestandstoken nicht automatisch zu einer korrekten anonymen Kabine: Während eines Einsatzes müssen Bordmengen und physische Fortsetzung zusammenbleiben. Derselbe physische Ressourcen- und Lifecyclevertrag ist weiterhin nötig.

### Patty und Zugdisposition mit Zwischenereignissen

Cardellini und Giunchiglia erweitern symbolische Aktionsmuster auf zeitliche Planung. Ein Muster legt eine mögliche kausale Reihenfolge nahe, während ein SMT-Modell Aktionen auswählt und zeitlich einordnet; bei Bedarf wird das Muster erweitert. Der Ansatz ist keine Beschränkung auf einen periodischen Fahrplan.[^18]

Die Erweiterung mit Intermediate Conditions and Effects untersucht ausdrücklich Zugdisposition: Ressourcen werden während einer länger dauernden Bewegung zu unterschiedlichen Zeiten freigegeben. Im untersuchten InSTraDi-Satz mit ein bis zwanzig Zügen findet Patty in allen zwanzig Fällen einen Plan innerhalb von fünf Minuten, gegenüber vier Fällen für Tamer und zwei für ANMLSMT. Das sind Ergebnisse zur **Planfindung**, keine nachgewiesenen Passagierkostenoptima. Die Studie umfasst keine frei optimierte Passagierbesetzung der Züge.[^19]

Der öffentliche Patty-Code ist vorhanden. Sein README weist jedoch ausdrücklich darauf hin, dass der Repositorystand nicht immer mit den Veröffentlichungen übereinstimmt. Die exakt zur ICE-Arbeit gehörende Fassung muss vor einem Vergleich identifiziert werden; die alte Installation des allgemeinen Patty-Repositories ist kein Nachweis, diese Fassung bereits zu besitzen.[^20]

### Vier notwendige Übertragungsprüfungen

**1. Zeitgenauigkeit.** Die publizierten Planer arbeiten mit kontinuierlicher Zeit und teilweise einer Epsilon-Trennung interferierender Ereignisse. Das ist weder automatisch unser Ein-Mikrosekundenraster noch unsere Erlaubnis, ein Schutzintervall exakt beim Beginn des nächsten enden zu lassen. Eine kleine positive Zeitlücke kann eine Grenzlösung ausschließen. Umgekehrt können kontinuierliche Bruchteilticks die Domäne erweitern. Beides braucht einen Nachweis oder eine ausdrückliche Einstufung als Relaxation.

**2. Ressourcen innerhalb einer Bewegung.** Das vollständige Sperren einer Route schon bei Bewegungsbeginn wäre bei uns zu restriktiv. Ressourcen müssen genau zu ihren vorhandenen zeitlichen Offsets und Waiting-abhängigen Enden belegt werden. Das ist der konkrete Nutzen von Zwischenbedingungen; es ist nicht bereits durch die Zugdispositionsbeispiele für unsere Geometrie bewiesen.

**3. Ganzzahligkeit.** Reelle numerische Fluents dürfen keine halben Fahrgäste erzeugen. Ein denkbarer deklarativer Weg wären Boarding-/Alightingaktionen mit festen ganzzahligen Mengen eins bis acht und integerer Initialbelegung. Das bleibt Modellierung, kann aber die geerdete Aktionsmenge stark vergrößern. Die Kombination von Gruppen, Kabinen, Besuchen und Mengen muss vor Skalierung gemessen werden.

**4. Ziel und globale Schranke.** TemPESTs `TempestOptimal.supported_kind()` nennt Makespan und Aktionskosten, keine allgemeine finale numerische Zielfunktion. Der untersuchte Code setzt außerdem standardmäßig ein Epsilon von 1/100, wenn keines angegeben wird. Ein direkter Aufruf würde unser Modell also nicht automatisch bewahren.[^21]

Eine Zielbedingung „bis H mindestens S Personen ausgeliefert“ ist für Kapazität naheliegend. Ein gültiger Plan belegt diese Bedienung. Ein fehlender Plan im beschränkten Suchlauf belegt dagegen nicht die Unmöglichkeit. Unbedientenzahlen als Kosten von Ablehnungsaktionen zu kodieren wäre zusätzlich auf Nullkosten, Terminierung, Horizont und die Voraussetzungen der Optimalitätsabstraktion zu prüfen. Variable ankunftsabhängige Reisezeitkosten passen noch weniger unmittelbar zu statischen Aktionskosten.

**Urteil:** Diese Familie hätte früher ernsthaft untersucht werden sollen. Sie verbindet variable Aktionsfolgen, zeitliche Ressourcenkonflikte und numerischen Zustand in bestehenden Planern. Sie ist besonders interessant für Kapazitätszulässigkeit und Einsatzplanung. Eine bestätigte vollständige Übersetzung mit globalem Gap für unser Kostenmodell liegt jedoch noch nicht vor. Der nächste sinnvolle Schritt wäre ein gezielter Semantik- und Softwaretest, kein großer Neubau auf Basis des Wortes „optimal“.

Aries ist eine weitere verfügbare Engine für temporale/numerische Planung und Scheduling. Das Projekt verweist auf einschlägige Arbeiten von 2023 und 2025. Für die spezifische Reisezeit- und Ticksemantik wurde hier keine gleichwertige Unterstützung nachgewiesen; deshalb erhält es keinen höheren Rang allein aufgrund vorhandenen Codes.[^22]

## 8. Weitere Richtungen und ihre tatsächlichen Grenzen

### Athanor: eigene Nachbarschaften vermeiden, aber keinen Beweis erwarten

Die 2025 veröffentlichte Athanor-Arbeit beschreibt einen Solver, der direkt auf strukturierten Essence-Typen arbeitet und Nachbarschaften automatisch ableitet. Mengen von Sequenzen können variable Touren ausdrücken, ohne dass ein Anwender die Suchzüge selbst schreibt. Das ist sachlich eine andere Option als unsere handgebauten Reparaturen; Quellcode und Experimente sind verfügbar.[^23]

Für die Seilbahn wäre ein strukturierter Einsatz mit Besuchsfolge, Waiting und Belegung denkbar. Enge zeitliche Gleichheiten und gekoppelte Ressourcen bleiben aber problematisch. Athanor ist eine lokale Suchengine und liefert damit allein keinen globalen Beweis. **Als zusätzliche Incumbent-Engine vertretbar, für die Kombination aus Incumbent und Gap zunächst hinter Hexaly und OMT.**

### Zeitautomaten: symbolisches Waiting ist real, freie Skalierung nicht

UPPAAL CORA verwendet bepreiste symbolische Uhrbereiche und unterstützt kostenoptimale Erreichbarkeit. Damit kann es viele Zeitbelegungen gemeinsam behandeln. Die dokumentierten Terminierungsvoraussetzungen und Einschränkungen müssen beachtet werden; CORA ist nicht identisch mit statistischer Steuerung durch UPPAAL Stratego.[^24]

Unsere Kosten lassen sich konzeptionell als Integral über die Zahl freigegebener, noch nicht ausgelieferter Personen verstehen. Das passt zu Zustandskostenraten. Boarding und Ressourcenreservierungen vergrößern jedoch den diskreten Zustand, und viele unabhängig laufende Schutzzeiten benötigen viele Uhren. Der aktuelle Downloadbereich bietet für CORA noch die Fassung von 2006 an; moderne UPPAAL-Hauptversionen sind kein Nachweis einer entsprechend modernisierten CORA-Engine.[^25]

**Ein fundierter kleiner Kontrollansatz, aber aktuell kein überzeugender kurzfristiger Weg zu Max50.** Er wurde bereits abstrakt erwogen; neu ist hier die konkrete Bewertung der verfügbaren Engine und ihrer Grenzen.

### Kapazitiertes Multi-Agent Pickup and Delivery

Chen et al. behandeln gemeinsam Transportzuordnung und kollisionsfreie Wege mit mehreren Gütern pro Roboter. Die veröffentlichten MCA-/RMCA-Verfahren verbinden marginale Zuordnungskosten mit einer LNS-Verbesserung; Code ist vorhanden.[^26]

Das ist näher an unseren Passagieren als klassisches MAPF mit einem Ziel pro Agent. Trotzdem fehlen im Standardmodell die erzwungene Seilbahnbewegung, das ausschließlich am STOP-Exit erlaubte Waiting und die exakte Ressourcengeometrie. Ein vorhandener Grid-Pathfinder wäre kein unveränderter Seilbahnsolver. Die notwendigen Eingriffe würden gerade wieder eigene Such- und Bewegungslogik erfordern. **Keine Empfehlung für den nächsten Versuch mit der Vorgabe, vorhandene Engines zu nutzen.**

### TSN, Prozessplanung und automatische Zerlegung

Time-Sensitive Networking liefert Modelle für No-Wait, Warteschlangen und präzise Ressourcenkonflikte. Seine publizierten Algorithmen sind in TSNKit teilweise reproduzierbar. Periodische Nachrichtenfolgen und fest zugewiesene Nutzlast sind aber keine austauschbare Beschreibung unserer frei besetzten Kabinen. **Formulierungsquelle für OMT, kein Komplettbackend.**[^15]

Prozessplanung betrachtet variable Chargen, Zwischenlager und blockierende Maschinen. State-Task-Netze können Nachfrage und freie Sitze als Bestände motivieren. Die Verwandtschaft ist stark; die Übertragung darf jedoch weder Personen verschiedener Kabinen vermischen noch Speicher an unzulässigen Stellen erzeugen. Auch ereignisbasierte Formulierungen sind nicht generell überlegen: Eine Studie zum Multi-Mode-Projektscheduling findet Netzwerkflussmodelle im untersuchten Testbett wettbewerbsfähiger als ereignisbasierte Alternativen.[^27][^28]

GCG ist eine konkrete Alternative zum selbst geschriebenen Branch-and-Price. Es kann MIP-Struktur erkennen und automatische Dantzig-Wolfe-Reformulierung samt vollständigem Branch-Price-and-Cut ausführen.[^29] Das ist stärker als ein alleiniger Root-CG-Lauf, wurde aber bereits im Projektplan erwähnt. Für die Seilbahn ist offen, ob Ressourcen- und Demand-Kopplungen eine brauchbare Zerlegung lassen. Ein Export einer bereits riesigen No-Wait-Matrix löst zudem das Waiting-Netzproblem nicht. **Reserve für ein klar zerlegbares vollständiges Modell, kein weiterer ungezielter MIP-Solverwechsel.**

### Analytische Kapazität und Seilbahn-Warteschlangen

Grippa, Schilcher und Bettstetter leiten Warteschlangen-, Wartezeit- und Kapazitätseigenschaften für kabinenbasierte Systeme mit deterministischen Kabinenankünften und Poisson-Nachfrage her. Der Ansatz erklärt unter anderem den Konflikt zwischen hoher Auslastung früher Stationen und Versorgung später Stationen.[^30]

Solche Modelle können Nachfrageeffekte erklären und die Versuchsplanung unterstützen. Sie beantworten unter ihren Annahmen Stabilitäts- oder Bedienungsfragen, nicht automatisch die maximale endlich-horizontige Nachfrage mit frei gewählten Skip-Stop-Trajektorien. Ein periodischer oder stationärer Nachweis muss als solcher bezeichnet werden. **Ergänzung der wissenschaftlichen Erklärung, kein Ausweg durch eine unbemerkte Änderung der Forschungsfrage.**

## 9. Konkrete Reihenfolge für weitere Arbeit

Es gibt weder eine Grundlage für einen endgültigen Ideenstopp noch für fünf gleichzeitige neue Implementierungen. Die folgenden Prüfungen trennen wissenschaftliche Eignung, technische Nutzbarkeit und Leistung.

### Erstens: den nächsten vollständigen Engine-Test auf Hexaly begrenzen

Das Ziel wäre ein deklaratives integriertes Modell mit nativen Listen/Intervallen, dem bestehenden Reservoirvertrag, voller Waitingdomäne und ganzzahligen Passagieren. Es werden keine eigenen Suchnachbarschaften geschrieben. Vor der Implementierung einer großen Instanz müssen verfügbare Lizenz, Zahlenbereiche und exportierbare Lösungen feststehen.

Die entscheidenden Vorprüfungen sind ein gültiger historischer Plan, ein echter Bypass-Überholfall, gleichzeitig endende/beginnende Schutzintervalle und korrektes Ein-/Aussteigen. Bestehen sie, ist ein begrenzter direkter Vergleich auf R sinnvoll: gleiche Instanz, gleicher geprüfter Seed, anschließend ein ungehineter Kontrolllauf. Die Aussage muss getrennt lauten: bessere native Lösung, stärkere native globale Schranke oder kein Vorteil.

### Zweitens: eine vollständige OMT-Kapazitätsformulierung abgrenzen

Das ist der geradlinigste neue exakte Modelltest ohne Wechsel der Zeitdomäne. Er beginnt mit `min U`, weil damit die Wirkung arithmetischer Disjunktionen ohne das zusätzliche Kostenziel messbar wird. Waiting, Kabinenaktivierung und Passenger-Flow bleiben frei. Es genügt nicht, nur Bewegung oder feste Passagiere zu übertragen.

Der kleine Prototyp muss gegen Enumeration und CP-SAT dieselben zulässigen Ergebnisse liefern. Danach braucht er mindestens einen Fall nahe der Kapazitätsgrenze, auf dem tatsächlich ein offenes Ergebnis entschieden werden soll. Ein schneller K2-Lauf allein wäre kein Grund für einen weiteren großen Ausbau. Reisezeit mit der beschriebenen exakten Produktdarstellung folgt nur, wenn der Kapazitätstest ein verwertbares Signal liefert.

### Drittens: temporale Planung durch einen Übertragungstest bewerten

TemPEST und die richtige Patty-Version erhalten zunächst nur einen kleinen, aber semantisch vollständigen Seilbahnfall: zwei Kabinen, zwei gekoppelte Ressourcen, optionaler Einsatz, Exit-Waiting, Nachfragefreigabe und ganzzahlige Kapazität. Er enthält absichtlich eine gültige Grenzlösung mit unmittelbar anschließenden Ressourcenbelegungen sowie einen Fall, der eine echte Routenalternative benötigt.

Dieser Test muss klären, ob die Engine die ursprüngliche Domäne ausdrücken kann, ohne neue Propagatoren oder eigene Suche zu benötigen. Ein Scheitern an Epsilon, Tickzeiten, Zielmetrik oder nicht verfügbarer Paper-Version wird als **Übertragungshürde** dokumentiert. Es darf nicht als negativer Performancebefund über die veröffentlichte Methode verkauft werden.

### OptalCP bleibt bis zur Zahlenbereichsklärung außerhalb großer Läufe

Die wissenschaftliche Begründung ist stark genug, um den Ansatz zu behalten. Sie ist nicht stark genug, die konkrete Darstellungsgrenze zu ignorieren. Ein verkürzter oder gröberer Test darf als gesonderter Fall laufen, aber nicht als fairer Ersatz für das volle bestehende Modell.

### Erfolg an den Forschungsfragen messen

| Stufe | Benötigtes Zwischenergebnis |
|---|---|
| Darstellbarkeit | Originale Waiting-, Passagier- und Ressourcenregeln in einer vorhandenen Engine |
| Korrektheit | Historische Pläne und kleine Optima stimmen; Grenzfälle bleiben erhalten |
| Suche | Neue native Pläne und/oder nachweislich bessere globale Grenzen auf einem schwierigen Fall |
| Forschung | Entscheidbare Nutzen-/Kapazitätsvergleiche für die sechs Stationen und mehrere Nachfragefamilien |

Die bisherigen Schwellen wie zehn zusätzliche Fahrgäste oder 0,1 % bessere Kosten können ein erstes Leistungssignal anzeigen. Sie sind noch kein Beleg, die Forschungsfragen ausreichend beantworten zu können. Erst die letzte Stufe rechtfertigt eine Festlegung auf eine Hauptstrategie.

## 10. Quellen, Evidenz und offene Nachweise

Recherche- und Dokumentationsstand: 11. September 2026. Veröffentlichungen, offizielle Dokumentation und Autorenrepositories bilden die Grundlage. Herstellerangaben und Preprints sind entsprechend eingeordnet. Nicht ausführbare oder noch nicht zugeordnete Software wird nicht als getestet bezeichnet. Keine der neuen Engines wurde für diesen Bericht installiert oder auf der Seilbahn benchmarked.

Die zentrale Evidenzlücke bleibt bestehen: Es gibt in den hier geprüften Quellen keinen fertigen Solver mit publiziertem Leistungsnachweis für **genau** die gemeinsame Kombination aus Seilbahn-STOP/SKIP, Exit-Waiting, integrierten ganzzahligen Fahrgästen und optionalem Reservoirbetrieb. Die Quellen begründen gezielte Alternativtests, keine Erfolgszusage.

[^1]: Hexaly, [Modeling Principles](https://www.hexaly.com/docs/last/modelingprinciples/index.html), Dokumentation 15.0. Offizielle Beschreibung der internen Verfahren; keine unabhängige Leistungsbewertung.
[^2]: Hexaly, [Mathematical Modeling Features](https://www.hexaly.com/docs/last/mathematicaloperators/mathematicalmodelingfeatures.html) und [HxOperator](https://www.hexaly.com/docs/last/pythonapi/optimizer/hxoperator.html), 15.0. Native Entscheidungen und optionale Intervalle; API-Referenz.
[^3]: Léa Petit-Jean Genat, Hexaly, [Fast bounds in Hexaly based on single-machine scheduling problems](https://www.hexaly.com/wp-content/uploads/2024/12/Fast_bounds_in_Hexaly_based_on_single-machine_scheduling_problems.pdf), 2024 bereitgestellter zweiseitiger Forschungsbeitrag. Volltext einschließlich Tabelle gelesen; Beitrag aus dem Solverhersteller.
[^4]: Levi R. Abreu, [Mixed-integer versus Constraint Programming Solvers: An Extensive Comparison with the Job Shop Scheduling Problem](https://www.hexaly.com/wp-content/uploads/2026/02/2026-Mixed-integer-versus-Constraint-Programming-Solvers-An-Extensive-Comparison-with-the-Job-Shop-Scheduling-Problem.pdf), SBMAC Proceedings 12(1), 2026, DOI 10.5540/03.2026.012.01.0308. Volltext, insbesondere Tabelle 2. Auf der Herstellerseite gehostet, Universitätsautor.
[^5]: Hexaly, [Installation on macOS](https://www.hexaly.com/docs/last/installation/installationonmacosx.html), 15.0. Plattform- und Lizenzangaben.
[^6]: Hexaly, [Retrieving Solution Status and Values](https://www.hexaly.com/docs/last/features/solution.html), 15.0. Statusdefinition und Optimalitätstoleranz.
[^7]: Vilém Heinz, Petr Vilím, Zdeněk Hanzálek, [Reinforcement Learning for Search Tree Size Minimization in Constraint Programming: New Results on Scheduling Benchmarks](https://arxiv.org/html/2508.20056v1), 2025. Volltext, Abschnitte 5–6, besonders 6.3. Entwicklungsteam beteiligt; FDS-Experimente und Schranken, keine Seilbahnversuche.
[^8]: [A Comprehensive Benchmark of Constraint Programming Solvers for the Makespan-Minimisation Job Shop Scheduling Problem](https://www.preprints.org/manuscript/202605.1319), Preprint vom 20. Mai 2026. Zugänglicher Volltext; die zusätzlich gefundene [Journalfassung](https://www.mdpi.com/2227-7390/14/12/2179) war nicht zuverlässig im Volltext abrufbar. Zahlen und Aussagen wurden nicht zwischen Fassungen als identisch vorausgesetzt.
[^9]: ScheduleOpt, [optalcp-cpo README](https://github.com/ScheduleOpt/optalcp-cpo), insbesondere Compatibility / Limitations. Öffentliche Kompatibilitätsschicht; Unterschiede bei Übergangszeiten und unterstützten APIs.
[^10]: ScheduleOpt, [Model: Integer- und Intervallgrenzen](https://optalcp.com/csharp-api/api/OptalCP.Model.html), ergänzt durch [IntVarMax](https://optalcp.com/docs/api/variables/IntVarMax) und [IntervalMax](https://optalcp.com/docs/api/variables/IntervalMax). Offizielle Dokumentation; tatsächliche Limits der gewählten Binärversion vor Verwendung erneut prüfen.
[^11]: ScheduleOpt, [Editions](https://optalcp.com/docs/Quick%20Start/editions) und [Introduction to Scheduling](https://optalcp.com/docs/Tutorial/intro). Preview ohne vollständige Lösungsausgabe; Academic/Full für Zertifikate erforderlich.
[^12]: Nikolaj Bjørner, Leonardo de Moura, Lev Nachmanson, Christoph Wintersteiger, [Programming Z3](https://z3prover.github.io/papers/programmingz3.html), Autoren-Tutorial, insbesondere Arithmetik und Optimierung; [Z3-Repository](https://github.com/Z3Prover/z3) für verfügbare Software.
[^13]: FBK / Universität Trento, [OptiMathSAT](https://optimathsat.disi.unitn.it/index.html). Offizielle Beschreibung der unterstützten Optimierungstheorien. Keine lokale Plattforminstallation geprüft.
[^14]: Antton Kasslin, Jeremias Berg, [An Optimization Modulo Theories-Based Approach to Cumulative Scheduling with Delays](https://ceur-ws.org/Vol-4008/SMT_paper17.pdf), SMT 2025, CEUR 4008, S. 16–28. Volltext, insbesondere Tabellen 5–6 und Ergebnisdiskussion; [Benchmarkdaten](https://doi.org/10.5281/zenodo.15741417).
[^15]: Chuanyu Xue et al., [TSNKit](https://github.com/ChuanyuXue/tsnkit), [implementierte Schedulingverfahren](https://tsnkit.readthedocs.io/en/latest/schedule.html) und [Real-Time Scheduling for 802.1Qbv Time-Sensitive Networking: A Systematic Review and Experimental Study](https://arxiv.org/abs/2305.16772), 2023 / RTAS-2024-Projektbezug. Software-/Modellübersicht; keine Seilbahnübertragung behauptet.
[^16]: Stefan Panjkovic, Andrea Micheli, [Abstract Action Scheduling for Optimal Temporal Planning via OMT](https://ojs.aaai.org/index.php/AAAI/article/download/30002/31758), AAAI 2024, S. 20222–20229. Volltext mit Voraussetzungen, Theoremen und Experimenten.
[^17]: FBK-PSO, [TemPEST](https://github.com/fbk-pso/tempest), [up-tempest 0.1.0](https://pypi.org/project/up-tempest/0.1.0/), Veröffentlichung 14. Juli 2026. README und Engine-Schnittstelle geprüft; kein lokaler Solverlauf.
[^18]: Matteo Cardellini, Enrico Giunchiglia, [Temporal Numeric Planning with Patterns](https://ojs.aaai.org/index.php/AAAI/article/download/34848/37003), AAAI 2025, S. 26481–26489. Publizierter Vorläufer der erweiterten ICE-Arbeit.
[^19]: Matteo Cardellini, Enrico Giunchiglia, [Symbolic Pattern Temporal Numeric Planning with Intermediate Conditions and Effects](https://arxiv.org/html/2602.09798v1), Preprint vom 10. Februar 2026. Volltext, Modell der Zugdisposition und Tabelle 2. Such-Bound bezeichnet Musterausbau, keine Zielfunktionsuntergrenze.
[^20]: [Patty-Autorenrepository](https://github.com/matteocarde/patty), README und Versionshinweis. Gelesener Hauptzweig: `651a813d9c61b9b2926dcc9abdeeb05b4b2acb97`. Eine exakte Zuordnung dieses Stands zum ICE-Paper ist offen.
[^21]: [TemPEST engine.py](https://github.com/fbk-pso/tempest/blob/a888dc25d2fb705be42a4790cf4f3ceea83fcb6c/src/tempest/engine.py), geprüfter Commit `a888dc25d2fb705be42a4790cf4f3ceea83fcb6c`, insbesondere `TempestOptimal.supported_kind()` und Epsilon-Initialisierung. Die allgemeinen Featureflags allein ersetzen keinen Test der Integer- und Gleichzeitigkeitsemantik.
[^22]: [Aries-Autorenrepository](https://github.com/plaans/aries), Softwarekomponenten und Publikationsliste. Die verlinkte ICTAI-2025-Arbeit war über HAL nicht im Volltext zugänglich; daraus werden keine spezifischen Leistungszahlen abgeleitet.
[^23]: Saad Attieh et al., [Athanor: Local Search over Abstract Constraint Specifications](https://eprints.whiterose.ac.uk/id/eprint/221133/7/1-s2.0-S0004370224002133-main.pdf), Artificial Intelligence 340, 104277, 2025; [Solvercode](https://github.com/athanor/athanor). Beschreibung, Ergebnisse und Schlussfolgerungen; vollständige eigene Seilbahnmodellierung bleibt erforderlich.
[^24]: UPPAAL, [CORA-Dokumentation](https://docs.uppaal.org/extensions/cora/); Gerd Behrmann et al., [Optimal Scheduling using Priced Timed Automata](https://homes.cs.aau.dk/~kgl/GLOBAN06/READING/OptimalScheduling.pdf), 2005. Symbolische Kostenbereiche und kostenoptimale Erreichbarkeit.
[^25]: UPPAAL, [Downloads](https://uppaal.org/downloads/), Abschnitt CORA. Die dort angebotene CORA-Version ist von 2006; aktuelle Hauptversionen getrennt betrachten.
[^26]: Zhe Chen, Javier Alonso-Mora, Xiaoshan Bai, Daniel Harabor, Peter Stuckey, [Integrated Task Assignment and Path Planning for Capacitated Multi-Agent Pickup and Delivery](https://arxiv.org/abs/2110.14891), IEEE RA-L 6(3), 2021, S. 5816–5823; [MCA-/RMCA-Code](https://github.com/nobodyczcz/MCA-RMCA). Abstract und Codebeschreibung für Algorithmus und Verfügbarkeit; kein exakter Seilbahngap belegt.
[^27]: [New General Continuous-Time State–Task Network Formulation for Short-Term Scheduling of Multipurpose Batch Plants](https://pubs.acs.org/doi/10.1021/ie020923y), Industrial & Engineering Chemistry Research, 2003. Zugängliche Zusammenfassung zur Modellfamilie, kein daraus abgeleitetes Laufzeitversprechen.
[^28]: [Continuous-Time Formulations for Multi-Mode Project Scheduling](https://arxiv.org/html/2301.04700), 2023. Vergleich ereignis- und flussbasierter Formulierungen; Modellklasse ist nicht identisch mit Seilbahnbetrieb.
[^29]: RWTH Aachen, [GCG-Dokumentation](https://gcg.or.rwth-aachen.de/doc-preview/). Automatische Reformulierung, Strukturerkennung und Branch-Price-and-Cut; keine konkrete Zerlegung der Seilbahnmatrix geprüft.
[^30]: Pasquale Grippa, Udo Schilcher, Christian Bettstetter, [On Access Control in Cabin-Based Transport Systems](https://arxiv.org/abs/1804.08933), 2018. Zugängliche Zusammenfassung für Modellannahmen und Anwendungsbereich; analytische Seilbahnreferenz, kein Skip-Stop-Optimierungsnachweis.
