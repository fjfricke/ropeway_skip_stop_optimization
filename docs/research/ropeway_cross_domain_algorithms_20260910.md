# Ropeway: alternative Suchprinzipien aus Fertigung, Robotik, Warteschlangen und formaler Verifikation

Stand: 10. September 2026. Literaturbefunde, Abgleich mit implementierter Physik und konkrete Forschungshypothesen. Keine neue Solverimplementierung oder Benchmarkkampagne Bestandteil dieses Dokuments.

## Entscheidung in Kürze

**Es gibt ernsthafte zusätzliche Ansatzpunkte. Einen bereits publizierten Algorithmus, der unsere vollständige Kombination aus Skip-Stop, Überholen, Exit-Waiting, ganzzahliger Passagierzuordnung und endlichem Betriebshorizont nachweislich schnell löst, habe ich nicht gefunden.** Die erfolgversprechendsten Unterschiede liegen in der Darstellung der Entscheidungen, nicht im Namen eines weiteren Optimierers.

Meine Priorität wäre ein kleiner Machbarkeitstest für **Suche über lokale Konfliktreihenfolgen mit einem separaten Zeitgraphen**. Danach folgt ein unabhängiger Test einer **ereignisbasierten dynamischen Programmierung**, zunächst mit einer günstigen Rollout-Heuristik, anschließend gegebenenfalls mit DIDP. Beide müssen zeigen, dass eine einzelne Suchentscheidung wesentlich billiger bewertet werden kann als in der bisherigen Mustersuche. Für stärkere globale Schranken sind relaxierte Decision Diagrams besonders interessant; sie benötigen allerdings eine eigenständige mathematische Entwicklung.

Das sind unterschiedliche Wetten:

- **Schnell viele bessere Fahrpläne finden:** Konfliktreihenfolge, Zeitgraph, gezielte Nachbarschaften und Rollout.
- **Ein alternatives vollständiges Optimierungsverfahren entwickeln:** ereignisbasierte Zustände, DIDP oder Decision-Diagram-Branch-and-Bound.
- **Waiting symbolisch statt über einzelne Zeitwerte behandeln:** kostenbewertete Zeitautomaten; fachlich passend, aber mit hohem Zustandsrisiko.
- **Verstehen, wann zusätzliche Kabinen helfen oder schaden:** Conveyor- und Max-Plus-Modelle als strukturelle Diagnose.

Die ersten beiden Richtungen sind meine konkreten Kandidaten. Das bedeutet ausdrücklich nicht, dass die Literatur für Ropeway einen Durchbruch garantiert. Die geplanten Prüfungen unten sollen diese Vermutung möglichst billig widerlegen können.

## 1. Welches Problem muss eine übertragbare Methode tatsächlich lösen?

Die Kabinen bewegen sich auf einer gerichteten Umlaufstruktur. STOP und SKIP führen jeweils zum nächsten Zustand, benötigen aber unterschiedliche Fahrzeiten und Ressourcen. Warten ist am dafür vorgesehenen STOP-Exit erlaubt. Eine Kabine darf nicht beliebig auf dem Seil oder im SKIP-Zweig stehen bleiben. Ein Bypass erlaubt reale Änderungen der Reihenfolge; eine überall festgeschriebene Kabinenreihenfolge wäre eine Einschränkung.

Passagiere sind ganzzahlig, haben Ursprung, Ziel und Freigabezeit. Eine Beförderung benötigt STOP an beiden Enden und freie Kapazität auf allen dazwischenliegenden Abschnitten. Die Freigabe wird beim tatsächlichen Plattformverlassen einschließlich Waiting geprüft; die Zielankunft liegt am entsprechenden Ankunftsereignis. Zwischenzeitliches Aussteigen und Umsteigen darf eine neue Methode nicht still ergänzen.

Die Lebenszyklen unterscheiden sich: Fixed-K darf die bereits begonnene letzte Bewegung gemäß bestehendem Vertrag über den Horizont hinaus abschließen. Reservoirbetrieb verlangt die rechtzeitige Rückkehr zum Port. Der aktuelle Reservoirkern erlaubt einen zusammenhängenden Einsatz, keinen beliebigen wiederholten Aus- und Wiedereintritt. Auch die Schutzzeit einer Ressourcennutzung darf am Horizont nicht einfach abgeschnitten werden.

Das Reisezeitziel zählt für bediente Personen Ankunft minus Freigabe und für unbediente Personen die Zeit bis zum Bedienungshorizont. Das Kapazitätsziel minimiert stattdessen die unbediente Menge. Diese Ziele bleiben getrennt. Insbesondere darf ein Verfahren nicht weniger Personen bedienen und dann allein eine schönere mittlere Reisezeit der verbliebenen Personen berichten.

Die unmittelbar ausgewerteten großen Tests betreffen die **bestehende Fünf-Stationen-Instanz**. Sie sind keine abgeschlossene Auswertung der vorgesehenen sechs Stationen. Die physikalische Nähe eines Papers wird deshalb an obigen Regeln beurteilt, nicht nur am Wort „Seilbahn“.

### Aktuelle Evidenz aus dem Projekt

Die [CP-Formulierungskampagne](../../benchmarks/output/cp_formulation_campaign_20260910_121055/comparison.md) umfasst 24 gültige Läufe in knapp 90 Minuten. CP-SAT verbesserte einzelne obere Schranken geringfügig; IBM übernahm im Reservoirvergleich den bekannten Seed, ohne ihn zu verbessern. Keine Variante erfüllte die vorab festgelegte Bestätigungsschwelle in beiden zusätzlichen Seeds. Die vergleichbare Reisezeit-Untergrenze blieb bei 109.032,727040 Passagiersekunden. Das ist Evidenz gegen einen unmittelbar großen Gewinn durch die getesteten Formulierungsvarianten, kein Beweis gegen CP allgemein.

Die neuere [K39-Mustersuche](../findings/ddd_pattern_search_followup_20260910.md) verbesserte bei 3.074 Personen den Start von 1.410 auf 1.402 Unbediente. 170 von 191 Prüfungen blieben UNKNOWN; 1.767,73 Sekunden entfielen auf den Solver und insgesamt nur 10,02 Sekunden auf den Aufbau. Die einzige Verbesserung kam nach 592,6 Sekunden. Der Engpass ist damit in diesem Lauf die innere Suche, nicht Python-Modellbau.

Gleichzeitig zeigt die [Zeit-Hint-Ablation](../findings/ddd_pattern_time_hint_ablation_20260910.md), dass zwei geänderte Muster mit Zeit-Hints nach ungefähr vier Sekunden zulässige Lösungen lieferten, während dieselben Modelle ohne Hints in allen vier Kontrollen nach 300 Sekunden UNKNOWN blieben. Ein schlechter Start kann also sehr wohl entscheidend sein. UNKNOWN bedeutet weder unzulässig noch „schlechtes Muster“.

Im [Oracle-Vergleich](../findings/ddd_pattern_oracle_diagnostic_20260910.md) liefert CP-SAT für ein festes K39-Muster U=1.410 und Gurobi eine stärkere lokale Schranke von 1.386. Das ergibt ein Intervall **für dieses Muster**, keinen globalen Gap. Für K38 wurde U=315 bei festem untersuchtem Muster bewiesen. K38 und K39 haben unterschiedliche feste Startpositionen; ihre Lösungsräume sind nicht ineinander geschachtelt.

## 2. Breite Landkarte der Suchprinzipien

Die folgende Bewertung ist eine Ropeway-Einschätzung, kein aus Papers übernommenes Erfolgsranking. „Exakt möglich“ setzt jeweils ein vollständiges Modell und korrekte Schranken voraus; es bedeutet keine Garantie auf schnelle Gap-Schließung.

| Familie und Herkunft | Was wird gesucht? | Beitrag für Ropeway | Globaler Beweis? | Meine Einordnung |
|---|---|---|---|---|
| Blocking-/No-Wait-Job-Shop [1](https://www.sciencedirect.com/science/article/pii/S0377221701003381) | Reihenfolgen konkurrierender Operationen | Sehr ähnliche physische Kopplung | Mit vollständigem B&B möglich | Hohe strukturelle Nähe |
| Shifting Bottleneck [2](https://pubsonline.informs.org/doi/10.1287/mnsc.34.3.391) | Schrittweise bessere Reihenfolgen an Engpässen | Gezieltere Änderungen als isolierte STOP-Bits | Heuristik allein: nein | Kurzfristig interessant |
| Temporale Constraint-Netze [3](https://doi.org/10.1016/0004-3702(91)90006-6) | Zeitpunkte bei festgelegten diskreten Entscheidungen | Potenziell sehr günstige Zeitberechnung | Nur für das fixierte Teilproblem | Wichtigster technischer Pilot |
| Petri-Netze / Cluster Tools [4](https://journals.sagepub.com/doi/full/10.1177/1687814017693217), [5](https://researchwith.njit.edu/en/publications/optimal-one-wafer-cyclic-scheduling-of-time-constrained-hybrid-mu/) | Konfliktfreie Operationsfolgen und Timing | Blockierung, Wiederbesuche, zulässige Warteorte | Je nach Verfahren/Teilklasse | Gute Grundlage für Ablaufkern |
| Prioritätsgraphen in der Robotik [6](https://arxiv.org/abs/1306.0785) | Wer passiert welchen Konflikt zuerst? | Kleine Suchentscheidungen statt absoluter Zeiten | Regelbasierte Steuerung allein: nein | Mit Besuchsindizes übertragen |
| Rollout [7](https://www.mit.edu/~jnt/Papers/J066-97-rollout.pdf) | Nächste Entscheidung anhand kompletter Fortsetzungen | Weniger kurzsichtiges Greedy | Keine allgemeine Optimalität | Guter erster Suchcontroller |
| MCTS für Scheduling/AGV [8](https://informs-sim.org/wsc22papers/336.pdf), [9](https://arxiv.org/html/2501.17991v1) | Ereignis- oder Operationsentscheidungen mit Simulation | Explorative Suche ohne großes Gesamtmodell | Normalerweise kein zertifizierter LB | Interessant mit billigem Decoder |
| DIDP / dynamische Programmierung [10](https://arxiv.org/abs/2401.13883) | Zustandsübergänge mit Dominanz und Restkostenschranken | Anderer vollständiger Suchkern | Unter Modellbedingungen ja | Stärkster zusätzlicher exakter Kandidat |
| Relaxierte/restringierte Decision Diagrams [11](https://pubsonline.informs.org/doi/10.1287/ijoc.2015.0648), [12](https://liu.diva-portal.org/smash/get/diva2:1485500/FULLTEXT02.pdf), [13](https://pubsonline.informs.org/doi/10.1287/ijoc.2022.0340) | Zusammengefasste bzw. eingeschränkte Zustandsräume | Nichtlineare kombinatorische Schranken | Mit vollständigem B&B ja | Besonders für LB interessant |
| Kostenbewertete Zeitautomaten [14](https://www.brics.dk/RS/01/3/index.html), [15](https://arxiv.org/abs/1602.00481) | Symbolische Mengen von Uhrbelegungen | Waiting ohne Aufzählung jedes Ticks | In geeigneter Klasse ja | Mutiger, längerfristiger Kandidat |
| Aufzugs-Destination-Control [16](https://research.aalto.fi/fi/publications/assignment-formulation-for-the-elevator-dispatching-problem-with-/) | Passagiere zuerst Fahrzeugen zuweisen | Direkte Nachfragekopplung | Eingeschränkte Regeln: kein Originalbeweis | Interessant, mit Gegenbeleg |
| Polling / Renewal Control [17](https://arxiv.org/abs/1011.5942), [18](https://ee.usc.edu/stochastic-nets/docs/asynchronous-renewals.pdf) | Bedienregeln aus Warteschlangen und Zeitkosten | Schnelle nachfrageabhängige Politik | Andere, oft asymptotische Garantien | Heuristik oder Diagnose |
| Conveyor-Queueing [19](https://repub.eur.nl/pub/114014/RePub-114014-OA.pdf) | Durchsatz bei Umlauf, Merges, Blockierung | Flottendichte und Engpässe verstehen | Approximation, kein globaler LB | Sehr nützliche Nebenanalyse |
| Max-Plus-Verkehrsmodelle [20](https://arxiv.org/abs/1604.04593), [21](https://arxiv.org/abs/1801.00931) | Ereignisdynamik und asymptotischer Takt | Kapazitätsphasen und kritische Umläufe | Für jeweiliges vereinfachtes Modell | Kein Ersatz für freien Fahrplan |
| Continuous-Time CBS [22](https://ojs.aaai.org/index.php/AAAI/article/view/17338) | Einzelpläne plus konfliktgetriebene Verzweigung | Selektive Kopplung von Kabinen | Nur mit korrektem Low-Level-Modell | Bereits bekannt, schwieriger Transfer |
| Core-guided SAT / Hitting Set [23](https://www.ijcai.org/proceedings/2023/215), [24](https://www.ijcai.org/proceedings/2021/643) | Welche Wünsche sind gemeinsam unmöglich? | Potenziell stärkere Bedienungsschranken | Ja bei vollständiger Kodierung | Teilweise bereits im CP-Portfolio |
| Bucket Elimination [25](https://www.sciencedirect.com/science/article/pii/S0004370299000594) | Variablen/Zustände entlang kleiner Separatoren | Exakte Zerlegung oder Relaxationen | Ja, abhängig von Breite | Sechs Stationen allein reichen nicht |
| Packet Routing [26](https://www.cs.cmu.edu/afs/cs.cmu.edu/project/phrensy/pub/papers/LeightonMR94/LeightonMR94.html) | Wege zeitlich unter Engpasslast koordinieren | Kongestions-/Weglängen-Untergrenzen | Garantien für andere Pufferregeln | Vorsicht bei Approximationstransfer |
| Gelernte Suchoperatoren / RL [27](https://www.ijcai.org/proceedings/2025/966), [28](https://doi.org/10.1145/3790252) | Gute Regeln oder Nachbarschaften lernen | Kann vorhandene schnelle Suche steuern | Im Allgemeinen nein | Aktuell nachrangig |

## 3. Fertigungsplanung: Konflikte ordnen, Zeiten anschließend berechnen

### Literaturbefund

Bei Blocking- und No-Wait-Job-Shops darf ein Werkstück nicht einfach zwischen beliebigen Maschinen warten. Eine belegte Operation kann ihre Ressource bis zur Weitergabe blockieren. Mascis und Pacciarelli modellieren solche Abhängigkeiten mit alternativen Graphen [1](https://www.sciencedirect.com/science/article/pii/S0377221701003381). Das ist näher an einer Kabine, die am Exit wartet und dadurch Ressourcen belegt, als ein Standardfahrzeug, das jederzeit auf einem unbegrenzten Parkplatz stehen kann.

Shifting Bottleneck behandelt nacheinander kritische Maschinen und verbessert deren Reihenfolge unter Berücksichtigung bereits behandelter Maschinen [2](https://pubsonline.informs.org/doi/10.1287/mnsc.34.3.391). Für Ropeway ist die übertragbare Idee, eine Konfliktgruppe am Merge gemeinsam umzuordnen, statt nur ein einzelnes STOP-Bit zu drehen. Die ursprüngliche Heuristik ist weder ein fertiger Seilbahnalgorithmus noch ein Approximationssatz für unser Ziel.

Ein besonders passendes Gegenstück zu einer rein periodischen Betrachtung ist Sakai und Nishis **nichtzyklische** Cluster-Tool-Planung: Operationsfolge und zeitliche Planung werden getrennt; nach festgelegter Folge lässt sich das Timing ihres Systems linear optimieren [4](https://journals.sagepub.com/doi/full/10.1177/1687814017693217). Die zyklischen Petri-Netz-Ergebnisse von Yang et al. gelten dagegen für eine spezielle Betriebsstrategie [5](https://researchwith.njit.edu/en/publications/optimal-one-wafer-cyclic-scheduling-of-time-constrained-hybrid-mu/). Beides darf nicht als allgemeine Ropeway-Garantie gelesen werden.

### Eigene Ableitung für den vorhandenen Code

Die entscheidende Frage ist: **Können wir nach hinreichend vollständiger Festlegung der kombinatorischen Entscheidungen die gesamte verbleibende Zeitberechnung als Differenzconstraints lösen?**

Für einen aktiven Besuch gilt mit Grunddauer dᵢ und Exit-Waiting wᵢ:

\[
t_{i+1}=t_i+d_i+w_i,\qquad 0\le w_i\le W_i.
\]

Die Ressourcengeometrie in `models.py` verwendet für Eintritt und Räumung affine Ausdrücke der Form tᵢ+e+αwᵢ, wobei α nur 0 oder 1 sein darf. Damit ist der Ausdruck entweder tᵢ+e oder tᵢ₊₁+e−dᵢ. Wenn die Reihenfolge zweier Ressourcennutzungen feststeht, wird ihre Schutzbedingung deshalb zu einer Differenzbedingung:

\[
x_v\ge x_u+c.
\]

Auch Mindest-/Höchstdauer, fixe Starts und Rückkehrgrenzen passen grundsätzlich in diese Form. Das theoretische Werkzeug ist ein Simple Temporal Network [3](https://doi.org/10.1016/0004-3702(91)90006-6). Wichtige Konsequenz: Es braucht nicht für jede Bewertung erneut einen großen gemischt diskreten Zeitoptimierer.

**Dafür genügt ein festes STOP-Muster aber nicht.** Festgelegt oder separat behandelt werden müssen mindestens:

1. STOP/SKIP-Option jedes aktiven Besuchs und das Aktivitätspräfix;
2. die lokal geltenden Reihenfolgen der Ressourcennutzungen;
3. die bei Horizontgrenzen wirksamen Präsenzentscheidungen;
4. eine ganzzahlige Passagierzuordnung, wenn die Bewertung bereits das exakte Reisezeitziel umfassen soll;
5. die verbleibenden diskreten Lebenszyklusentscheidungen.

Mit fixierten Passagiermengen sind Belegungssummen Konstanten; Freigaben und Ankunftsgrenzen liefern zusätzliche Zeitbedingungen. Das Reisezeitziel wird linear in den Ankunftszeiten mit nichtnegativen Gewichten. Unter diesen Voraussetzungen kann eine komponentenweise früheste zulässige Zeitbelegung die fixierte Zuordnung optimal takten. Eine anschließend andere Passagierzuordnung ist eine neue kombinatorische Entscheidung und kann ein erneutes Timing erfordern.

Das ist eine **zu verifizierende Ableitung für unseren Kern**, noch kein implementierter Äquivalenzbeweis. Obergrenzen für Waiting erzeugen rückwärts gerichtete Kanten. Ein bloßes topologisches Sortieren eines vermeintlichen DAG reicht daher nicht; Zyklen und Widersprüche müssen korrekt erkannt werden. Fixierte Ursprungszeit, sämtliche unteren/oberen Schranken und die Horizontfälle gehören in den Graphen. Bei Waiting-Schritten größer als einem Tick kommen Kongruenzbedingungen hinzu, die ein gewöhnliches Zeitnetz nicht abdeckt. Die betrachteten Mikrosekundenfälle verwenden den Ein-Tick-Schritt.

### Daraus würde ein tatsächlich anderer Suchablauf

Ein Kandidat enthält eine vollständige konsistente Kombination aus Routen, lokalen Prioritäten und Passagiermengen. Eine Änderung tauscht beispielsweise zwei benachbarte Nutzungen am kritischen Exit oder verschiebt zusammengehörige STOPs. Danach berechnet der Zeitgraph die Folgewirkungen auf alle betroffenen Kabinen. Ein Widerspruch liefert eine konkrete Konfliktkette; ein gültiger Plan wird unabhängig geprüft.

Die Suche darf bei späteren Kandidaten andere lokale Reihenfolgen wählen. Es entsteht dadurch weder ein periodischer Fahrplan noch eine dauerhaft festgelegte globale Kabinenfolge. Das ist der wichtige Unterschied zwischen „eine Reihenfolge für eine Bewertung fixieren“ und „alle anderen Reihenfolgen aus dem Problem entfernen“.

Prioritätsgraphen aus der Multirobot-Koordination stützen die Trennung zwischen Konfliktentscheidung und Bewegungsausführung [6](https://arxiv.org/abs/1306.0785). Bei uns muss eine Priorität jedoch auf Besuche/Ressourcennutzungen bezogen sein: Kabine A darf bei einem Merge vor B und später hinter B liegen. Eine einzige lebenslange Priorität pro Kabinenpaar würde zulässiges Überholen verlieren.

**Erhoffter Gewinn:** wesentlich mehr vollständig geprüfte Kandidaten pro Sekunde. **Risiko:** Der schwierige Teil wandert in die Wahl von Reihenfolge und Passagierzuordnung; viele Änderungen können weiterhin unzulässig sein. Darum ist zunächst der Decoder zu messen, nicht gleich ein großes Metaheuristikpaket zu bauen.

## 4. Ereignisbasierte Suche: Reisezeit als laufende Systemkosten

### Eine exakte Identität statt eines neuen Ziels

Für eine Person p mit Freigabe rₚ und rechtzeitiger Ankunft aₚ gilt ihre Reisezeit aₚ−rₚ. Für eine bis H nicht angekommene Person setzt das bestehende Ziel effektiv aₚ*=H; ansonsten aₚ*=aₚ. Für die betrachteten Freigaben innerhalb [0,H] folgt:

\[
C=\sum_p(a_p^*-r_p)
 =\int_0^H N_{\text{freigegeben, noch nicht angekommen}}(t)\,dt.
\]

Diese Gleichheit ist eine eigene unmittelbare Umformung des vorhandenen Ziels, keine stationäre Warteschlangenannahme. Die Indikatorfunktion jeder Person ist genau von ihrer Freigabe bis zur Ankunft beziehungsweise H gleich eins. Summieren und Integrieren ergibt die Formel. Gruppen werden mit ihrer Personenzahl gewichtet.

Gezählt werden **Wartende und Personen in Kabinen**. Noch nicht freigegebene Nachfrage zählt nicht. Zwischen zwei aufeinanderfolgenden Freigabe-/Ankunftsereignissen ist N konstant; der Kostenbeitrag beträgt N·Δt. In einem Suchzustand ist N bereits bekannt, sodass kein Produkt zweier noch unbestimmter Entscheidungsvariablen erforderlich ist.

Dadurch wird das Problem nicht automatisch leicht. Zeitdauern bleiben Entscheidungen, und in einem monolithischen Modell mit variablem N könnte dieselbe Umformung erneut Produkte erzeugen. Der Vorteil entsteht erst durch eine passende Zustandssuche. Für das Kapazitätsziel zählt weiterhin die terminal unbediente Menge; diese Formel darf nicht heimlich dessen Zielfunktion ersetzen. Die physikalische Prüfung einer notwendigen Betriebsfortsetzung läuft gegebenenfalls über H hinaus weiter.

### Rollout und Monte-Carlo Tree Search

Eine Rollout-Suche betrachtet mehrere nächste Entscheidungen. Jede wird mit einer einfachen vollständigen Politik bis zum Ende fortgesetzt und mit den tatsächlichen Gesamtkosten bewertet. Die bessere Fortsetzung bestimmt den nächsten Schritt. Das ist der grundlegende Mechanismus bei Bertsekas, Tsitsiklis und Wu [7](https://www.mit.edu/~jnt/Papers/J066-97-rollout.pdf); die Verbesserungseigenschaften hängen an den Voraussetzungen der Basisheuristik. Ein beliebig beschnittener oder unzulässig simulierender Rollout erbt sie nicht.

MCTS verteilt das Rechenbudget wiederholt auf vielversprechende und bislang wenig untersuchte Zweige. Kim und Kim behandeln dynamisches Job-Shop-Scheduling mit AGVs in einem Petri-Netz-basierten Ansatz [8](https://informs-sim.org/wsc22papers/336.pdf). Boveroux et al. untersuchen unter anderem Wiederbesuche von Maschinen und gewichtete Fertigstellungszeiten; ihre MCTS-Verfahren übertreffen ihre eigene CP-Vergleichsformulierung auf Teilen ihres Benchmarks [9](https://arxiv.org/html/2501.17991v1). Das ist ein relevanter Machbarkeitsbefund, kein allgemeiner Sieg über CP-SAT oder ein Ropeway-Laufzeitergebnis.

Für Ropeway würde ein Rollout an einem Entscheidungsereignis beispielsweise STOP/SKIP, Passagieraufnahme und eine zulässige Exit-Freigabe bewerten. Die Fortsetzung müsste alle bereits beförderten Personen bis zum Ziel berücksichtigen und physisch gültig bleiben. Ein erster Controller könnte deterministisch wenige Fortsetzungen vergleichen; MCTS lohnt sich erst, wenn diese Fortsetzungen günstig genug sind.

**Meine Einschätzung:** als Heuristik ernsthaft interessant. Das explorative Verhalten wird explizit steuerbar, und das Ziel bewertet den gesamten Ereignisverlauf. Es gibt jedoch keinen globalen LB allein aus guten Simulationen. Wer einen Gap aus MCTS ausgibt, braucht daneben eine nachweislich gültige Schranke.

### Warum eine naive Ereignissimulation trotzdem falsch sein kann

„Fahre immer zum nächsten vorhandenen Ereignis“ ist nicht automatisch vollständig. Sinnvolles Waiting kann zukünftige Ressourcenreihenfolgen oder Passagierfreigaben ermöglichen, die im aktuellen Ereigniskalender noch nicht liegen. Nur frühestmögliche Aktionen zu erlauben wäre ebenfalls eine zusätzliche Einschränkung.

Ein heuristischer Pilot darf eine ausgewiesene Auswahl von Warteentscheidungen verwenden und weiterhin gültige Fahrpläne erzeugen. Ein exakter Solver muss dagegen beweisen, dass seine Ereignis-/Intervallrepräsentation jede relevante Möglichkeit erfasst. Genau hier unterscheiden sich ein schnell gebauter Simulator und eine wissenschaftlich belastbare vollständige Optimierung.

## 5. DIDP: der interessanteste zusätzliche vollständige Suchkern

Kuroiwa und Beck formulieren Optimierungsprobleme als dynamische Programme mit expliziten Zuständen, Übergängen, Dominanz und dualen Schranken [10](https://arxiv.org/abs/2401.13883). Das Framework ist als DIDP/didppy verfügbar. Die untersuchte Literaturfassung enthält mehrere Suchverfahren und Vergleiche mit MIP und CP in verschiedenen kombinatorischen Problemklassen. Das belegt die praktische Existenz eines ernsthaften Alternativsolvers; Ropeway gehört nicht zu den dort gelösten Anwendungen.

Ein einschlägiges Verfahren ist Complete Anytime Beam Search: zunächst mit beschränkter Breite suchen, anschließend breiter wiederholen. Unter den jeweiligen Modell- und Vollständigkeitsbedingungen kann daraus ein beweisendes Verfahren werden. Der Optimalitätsbeweis folgt nicht aus dem Wort „Beam“, sondern aus vollständiger Erweiterung, korrekter Dominanz und gültigen Schranken. Verworfene Zustände dürfen bei der Bound-Buchführung nicht einfach verschwinden.

### Was unser Zustand enthalten müsste — eigene Übertragung

- Fortschritt und verbleibende Bewegungszeiten aktiver Kabinen;
- lokale Ressourcennutzung einschließlich ausstehender Schutzzeiten;
- freigegebene, noch wartende Mengen je notwendiger Nachfrageklasse;
- Zielverpflichtungen und Belegung jeder Kabine;
- verbleibende Nachfragefreigaben;
- Betriebs-/Reservoirzustand und gegebenenfalls verbleibende Dispatchmöglichkeiten;
- bisherige Kosten und Informationen für eine optimistische Restkostenschranke.

Die mögliche Ersparnis entsteht, wenn viele unterschiedliche Entscheidungshistorien im **gleichen zukunftsrelevanten Zustand** zusammenlaufen. Dann muss dieselbe Restaufgabe nur einmal bearbeitet werden. Austauschbare Kabinen dürfen nur dann kanonisch umbenannt werden, wenn ihre gesamte zukünftige Physik und Passagierbelegung austauschbar sind.

Eine frühere Zeit dominiert eine spätere nicht automatisch. Wenn die frühere Kabine an diesem Ort nicht warten darf, kann sie die spätere Lage unter Umständen nicht reproduzieren. Ebenso können weniger aufgelaufene Kosten mit ungünstigeren Ressourcenresten oder anderen Passagierzielen verbunden sein. Unbegründete Dominanz würde den Solver schnell, aber falsch machen.

Als erste Restkostenschranke könnten wir Ressourcenüberlagerungen optimistisch ignorieren und für jede offene Person eine frühestmögliche Zielankunft einschließlich Nichtbedienungsalternative ableiten. Eine stärkere Variante müsste knappe Restkapazität oder unvermeidliche Engpassarbeit erfassen. Jede Kombination muss Doppelzählungen vermeiden.

**Erfolgsaussicht:** mittel für einen sinnvollen eigenständigen Prototyp, derzeit unklar für den vollständigen Max50-Fall. 50 simultane Kabinen, zahlreiche OD-Gruppen und feine Zeitwerte können auch ein dynamisches Programm überfordern. Wenige Stationen garantieren keine kleine Zustandszahl. Trotzdem ist DIDP eine konkretere zusätzliche Option als ein weiterer generischer MIP-Backendwechsel.

## 6. Decision Diagrams: Zustände gezielt zusammenfassen und Grenzen erhalten

Ein exaktes Decision Diagram repräsentiert zulässige Entscheidungsfolgen. Ein eingeschränktes Diagramm lässt Möglichkeiten weg und liefert damit zulässige Kandidaten. Ein relaxiertes Diagramm fasst Zustände so zusammen, dass zusätzliche Möglichkeiten entstehen; sein Optimum liefert eine gültige optimistische Schranke. Mit Branch-and-Bound kann daraus eine vollständige Optimierung werden [11](https://pubsonline.informs.org/doi/10.1287/ijoc.2015.0648). Bei unserem Minimierungsziel entsprechen diese Rollen UB und LB; einige Papers verwenden umgekehrt ein Gewinnmaximierungsziel.

Horn et al. behandeln die gemeinsame Auswahl und Reihenfolge gewinnbringender Jobs mit mehreren Ressourcen [12](https://liu.diva-portal.org/smash/get/diva2:1485500/FULLTEXT02.pdf). Ihre A*-gesteuerte Konstruktion benötigt keine starre Zuordnung jeder Diagrammschicht zu einer Variablen und vermeidet dadurch bestimmte Zustandsduplikate. Das ist näher an unserer optionalen Bedienung als ein reiner Hamiltonkreis. Coppé et al. ergänzen wiederverwendbare Dominanz-/Expansionsinformationen in DD-Branch-and-Bound [13](https://pubsonline.informs.org/doi/10.1287/ijoc.2022.0340).

**Eigene Ropeway-Idee:** Ein relaxierter Zustand könnte bestimmte Unterschiede zwischen Restbelegungen oder Ressourcenzeiten optimistisch vergessen, aber belastende Mindestarbeit am wichtigsten Merge erhalten. Ein daraus berechneter LB könnte viel aussagekräftiger sein als die Summe unabhängiger kürzester Passagierfahrten.

Die Schwierigkeit ist nicht das Zeichnen eines Diagramms. Für jede Zusammenführung muss bewiesen sein, dass keine Originalfortsetzung verloren geht und die Kosten nicht überschätzt werden. Ein Diagramm, das nur die „besten“ 1.000 Zustände behält, ist eine Heuristik und keine solche Relaxation. Die Methodengruppe war bereits in unseren Plänen; neu konkretisiert wird hier, welche modernen Konstruktions- und Cachingarbeiten man verwenden könnte.

**Priorität:** hoch, wenn die Thesis noch eine echte neue Schrankenmethode tragen soll; geringer für einen kurzfristigen UB-Erfolg. Ich würde damit erst anfangen, wenn eine korrekte kompakte Zustandsbeschreibung aus dem DIDP-/Ereignispilot vorliegt.

## 7. Kostenbewertete Zeitautomaten: Waiting als Bereich statt einzelner Tick

Timed Automata kombinieren diskrete Betriebszustände mit Uhren. Ein Übergang darf stattfinden, wenn Zeitbedingungen erfüllt sind. Symbolische „Zonen“ repräsentieren viele Uhrbelegungen gemeinsam. Kostenbewertete Varianten ergänzen Kostenraten in Zuständen und Kosten auf Übergängen; Mindestkosten-Erreichbarkeit ist für die entsprechenden Klassen algorithmisch behandelbar [14](https://www.brics.dk/RS/01/3/index.html). Bouyer, Colange und Markey entwickeln symbolische Verfahren mit bewerteten Zonen weiter [15](https://arxiv.org/abs/1602.00481).

**Eigene Übertragung:** STOP, SKIP, Exit-Waiting und Reservoir bilden Betriebszustände. Uhren beschreiben verbleibende Fahr-/Schutzzeiten. Die Kostenrate ist die oben hergeleitete Zahl noch nicht angekommener Personen. Eine Zone könnte einen ganzen Bereich zulässiger Waiting-Zeiten behandeln, ohne jeden Mikrosekundenwert separat auszuprobieren.

Das ist konzeptionell eine der deutlichsten Alternativen zum aktuellen Variablenmodell. Sie ist aber kein kostenloser Ausweg: Viele Kabinenuhren und diskrete Belegungen erzeugen ein riesiges Produkt von Zuständen. Außerdem muss die konkrete Engine dieselbe endliche Integer-Tick-Semantik abbilden oder die Äquivalenz einer kontinuierlichen Behandlung beweisen. Das theoretische Resultat für gewichtete Zeitautomaten garantiert nicht, dass beliebige zusätzliche Datenstrukturen und nichtlineare Raten unterstützt werden.

**Einschätzung:** fachlich passend und in den überprüften Projektunterlagen bisher kein implementierter Schwerpunkt. Sinnvoll als kleines unabhängiges Forschungsmodell; für den kurzfristigen vollständigen Max50-Neustart zu riskant.

## 8. Aufzüge: von Passagieren statt von Fahrplanbits ausgehen

Destination-Control-Aufzüge kennen die Ziele schon bei der Zuordnung. Ruokokoski et al. untersuchen, wann eine reine Zuordnung mit vorgegebener Bedienregel die umfassendere Dispatchentscheidung ersetzen kann [16](https://research.aalto.fi/fi/publications/assignment-formulation-for-the-elevator-dispatching-problem-with-/). Besonders relevant ist der Gegenbefund: Gute Eigenschaften für Wartezeit übertragen sich nicht allgemein auf die gesamte Reisezeit. Die Ergebnisse hängen zudem an Verkehrsform und Modellannahmen.

**Eigene Ropeway-Idee:** Zuerst kleine kompatible OD-Bündel zu Kabinen zuordnen. Dadurch werden zwingende STOPs, Kapazitätsverlauf und Zielverpflichtungen sichtbar. Erst danach Ressourcenreihenfolge und Zeiten planen. Mit fixierten ganzzahligen Mengen verschwinden die Mengen-mal-Ankunftszeit-Produkte aus der Zeitoptimierung.

Ein starrer erster Zuordnungsschritt kann jedoch den falschen Fahrplan erzwingen. Deshalb müsste die Suche Passagierbündel wieder tauschen, entfernen oder einer anderen Kabine geben können. Sinnvolle Nachbarschaften wären beispielsweise „zwei OD-Bündel zwischen Kabinen tauschen“ oder „einen Ursprungs-/Ziel-STOP zusammen mit seinen Passagieren verschieben“. Ein isolierter STOP-Wechsel verliert diese Komplementarität.

Die vorhandene Odd-Cycle-Instanz verhindert eine weitere Abkürzung: Auch bei fixiertem Fahrplan ist unsere allgemeine ganzzahlige Zuordnung nicht automatisch ein integrales Flussproblem. Ein LP oder Min-Cost-Flow darf nur für eine ausdrücklich bewiesene Teilklasse als exakter Ersatz dienen.

**Einschätzung:** gute Ergänzung einer Reihenfolge-/Rollout-Suche, keine ausreichende alleinige Neumodellierung. Der Aufzugstransfer ist gerade wegen seiner Gegenbeispiele nützlich.

## 9. Conveyor, Max-Plus und Warteschlangen: das Dichteproblem untersuchen

Van der Gaast et al. modellieren umlaufende Fördertechnik mit Merges, endlichen Puffern und Rezirkulation [19](https://repub.eur.nl/pub/114014/RePub-114014-OA.pdf). In ihren Simulationstabellen kann zusätzlicher Umlaufbestand den Durchsatz senken. Die Arbeit bietet eine genaue Approximation für ihre Systeme, keinen exakten Ropeway-Kapazitätsbeweis. Ihre Zahlen dürfen nicht auf unsere Kabinen übertragen werden.

Max-Plus-Modelle für Metrolinien beschreiben Ereigniszeiten über Maximum- und Additionsoperationen. Die Arbeiten von Farhi et al. und Schanzenbächer et al. zeigen Abhängigkeiten zwischen Fahrzeugzahl, Streckenstruktur und asymptotischem Betrieb [20](https://arxiv.org/abs/1604.04593), [21](https://arxiv.org/abs/1801.00931). Sie behalten stärkere Strukturannahmen als unser frei optimierter endlicher Fahrplan.

**Eigene Nutzung:** Nicht sofort eine neue Optimierung bauen, sondern im gültigen Fahrplan messen, wo Kabinen Zeit verbringen: Fahrt, Plattform, Exit-Waiting, Reservoir; welche Ressource die Weiterfahrt blockiert; ob zusätzliche Kabinen mehr Beförderung oder überwiegend zusätzliche Belegung erzeugen. Eine Dichte-/Engpassanalyse kann erklären, warum K39 bei einer bestimmten Initialisierung schlechter arbeitet als K38.

Das beantwortet jedoch nicht automatisch die Optimumsfrage. Bei **maximal K** und ansonsten wirklich identischem Modell enthält der Lösungsraum für K+1 den für K, sofern die Zusatzkabine vollständig inaktiv bleiben darf. Das Optimum kann dann nicht schlechter werden. Bei **genau K mit neuem Placement** besteht diese Inklusion nicht. Ein schlechterer Incumbent ist zusätzlich nur ein schlechterer gefundener Plan, nicht notwendigerweise ein schlechteres Optimum.

Polling-Systeme betrachten einen Server, der Warteschlangen besucht; Renewal-Optimierung behandelt Entscheidungen mit variabler Wirkungsdauer [17](https://arxiv.org/abs/1011.5942), [18](https://ee.usc.edu/stochastic-nets/docs/asynchronous-renewals.pdf). Daraus lassen sich Heuristiken ableiten, die erwartete Bedienung gegen gebundene Ressourcenzeit abwägen. Die dortigen Garantien betreffen aber andere, häufig langfristige oder erwartete Kriterien. Ein Konvergenzsatz über viele Betriebsperioden ist keine Aussage darüber, wie schnell unser endlicher Optimierungslauf seinen Gap schließt.

Eine konkrete einfache Politik wäre etwa, OD-Druck, freie Sitze und erwartete Exit-Blockierung gemeinsam zu gewichten. Das wäre zunächst eine **heuristische Politik mit exakter physikalischer Prüfung**. Eine davon getrennte ungefähre Warteschlangenrechnung dürfte keine zertifizierten Untergrenzen liefern.

## 10. Weitere Richtungen und warum ich sie derzeit zurückstufe

### Andere Skip-Stop- und Sortierprobleme

Mei et al. entwickeln für räumlich heterogene Nachfrage eine kontinuierliche Approximation eines AB-Skip-Stop-Angebots und eine effiziente Heuristik [29](https://research.polyu.edu.hk/en/publications/planning-skip-stop-transit-service-under-heterogeneous-demands/). Das ist nützlich für die Auswahl anspruchsvoller Nachfrageprofile: ungleich verteilte Ursprünge und hohe Nachfrage gehören zu ihren interessanten Fällen. Es löst jedoch eine eingeschränkte Angebotsgestaltung; der berichtete numerische Abstand ist kein Approximationsfaktor für unsere freien Kabinentrajektorien. AB-Muster könnten Startpläne liefern, sollten aber keine verpflichtende Einschränkung des Hauptmodells werden.

Beim Loop-Sorter-Scheduling von Boysen et al. werden Artikel Aufträgen, Aufträge Ausgabespuren und eine Ausschleusungsreihenfolge zugeordnet [30](https://www.sciencedirect.com/science/article/pii/S0377221724001723). Die geschlossene Umlaufstruktur ist anschaulich nah. Entscheidender ist die Kombination von Zuordnung und Reihenfolge: Die Autoren finden ungenutztes Potenzial einfacher Prioritätsregeln. Unser Fahrzeit-/Exit-Waiting-Modell ist dort nicht abgebildet. Die Arbeit spricht daher für anspruchsvollere Bündel-/Reihenfolgenachbarschaften, nicht für einen direkt übernehmbaren Sorteralgorithmus.

### Continuous-Time Conflict-Based Search

CBS plant zunächst einzelne Agenten und verzweigt erst bei Konflikten. Die kontinuierliche Variante verwendet geeignete zeitliche Low-Level-Suchen; Verbesserungen betreffen unter anderem die Konfliktauswahl und Verzweigung [22](https://ojs.aaai.org/index.php/AAAI/article/view/17338). Bei Ropeway sind aber Kabinenziel, STOPs und Kosten durch eine gemeinsame Passagierzuordnung gekoppelt. Außerdem darf nicht an jedem Ort gewartet werden. Der Low-Level-Solver ist deshalb wesentlich schwieriger als eine Standard-Einzelagentenroute. CBS bleibt denkbar, wurde allerdings bereits diskutiert und würde den wichtigsten Zuordnungsengpass nicht von selbst beseitigen.

### Core-guided SAT und Hitting Sets

Unvereinbare Bedienwünsche können als Konfliktkerne eine Schranke darauf begründen, wie viel Nachfrage aufgegeben werden muss. Moderne Arbeiten kombinieren core-guided und implizite Hitting-Set-Verfahren oder komprimieren wiederkehrende Kerne [23](https://www.ijcai.org/proceedings/2023/215), [24](https://www.ijcai.org/proceedings/2021/643). Manche Hitting-Set-Methoden verwenden selbst ganzzahlige Optimierung; „SAT-basiert“ bedeutet daher nicht automatisch „vollständig ohne MIP“.

Im vorhandenen C-Legacy-CP-SAT-Log ist bereits ein Subsolver `core` aktiv. Ein bloßes Einschalten einer gleichnamigen Suchidee wäre keine neue Methode. Neu wäre eine problembezogene Kodierung, die starke **passagierbezogene** Unvereinbarkeiten billig findet. Ob solche Kerne bei freiem Waiting und Skip-Stop groß genug sind, ist offen.

### Bucket Elimination und kleine Separatoren

Bucket Elimination löst Probleme durch schrittweises Eliminieren von Variablen; die wesentliche Schwierigkeit hängt von der induzierten Breite ab [25](https://www.sciencedirect.com/science/article/pii/S0004370299000594). Eine räumliche Zerlegung nach sechs Stationen wirkt zunächst attraktiv. Die Grenze zwischen Teilproblemen müsste jedoch alle gleichzeitig relevanten Kabinenzeiten, Belegungen und Zielverpflichtungen transportieren. Kleine Stationszahl bedeutet daher nicht automatisch kleine Breite. Als optimistische Relaxation über wenige kritische Ressourcen bleibt die Idee interessant.

### Packet Routing und Approximationsgarantien

Leighton, Maggs und Rao verbinden Routingdauer mit Kongestion und Weglänge unter ihren Paket-Routing-Annahmen [26](https://www.cs.cmu.edu/afs/cs.cmu.edu/project/phrensy/pub/papers/LeightonMR94/LeightonMR94.html). Das motiviert Ressourcenlast- und Mindestfahrtzeit-Untergrenzen. Ihre Puffer-, Weg- und Transportregeln entsprechen aber nicht unserem Exit-Waiting, wiederholten Umlauf und der gemeinsamen Kabinenkapazität. Den dortigen Faktor auf Ropeway zu übertragen wäre unbegründet.

Auch ein vermeintlicher Standard-Greedy-Faktor für „gute STOPs auswählen“ ist problematisch. Beispiel: Eine einzige OD-Nachfrage wird nur bedient, wenn sowohl A als auch B gehalten wird. Dann gilt f({A})=f({B})=0, aber f({A,B})>0. Der marginale Nutzen von B steigt durch A; die für viele Greedy-Garantien benötigte abnehmende Zusatzwirkung fehlt bereits ohne Ressourcenkonflikte. Das ist ein eigenes Gegenbeispiel für die naheliegende STOP-Mengenfunktion, kein Unmöglichkeitssatz für jede denkbare Approximation.

### Lernen von Regeln statt direktes Lernen eines Gesamtfahrplans

NS4S untersucht automatisch erzeugte Regeln zur Steuerung von Scheduling-Nachbarschaften [27](https://www.ijcai.org/proceedings/2025/966). Neuere Aufzugsarbeiten verbinden Imitationslernen und Reinforcement Learning [28](https://doi.org/10.1145/3790252). Solche Ergebnisse machen Lernen zu einer plausiblen späteren Steuerung eines schnellen Decoders. Sie liefern weder die fehlende Physikimplementierung noch einen globalen Optimalitätsbeweis.

Für uns wäre Trainingszeit derzeit schwer zu rechtfertigen, solange eine einzelne Planbewertung noch Sekunden kostet und wir keine zuverlässige schnelle Basispolitik haben. Eine lernende Methode sollte erst gegen einen gut gewählten Rollout und einfache Prioritätsregeln antreten.

## 11. Was daran wirklich neu ist — und was schon in den Unterlagen steht

| Konzept | Bisheriger Projektbezug | Zusätzlicher Inhalt dieser Recherche |
|---|---|---|
| Alternative Graphs / Ressourcenreihenfolgen | In [Exact Alternatives](../ideas/exact_algorithmic_solver_alternatives.md) bereits vorgeschlagen | Konkrete Herleitung eines möglichen Differenzconstraint-Decoders aus den 0/1-Waiting-Koeffizienten |
| A*, Beam, dynamische Programmierung | In [Heuristik-/Non-MIP-Roadmap](../plans/heuristic_and_non_mip_roadmap.md) beschrieben | DIDP als vorhandenes Framework; ereignisbezogene exakte Kostenidentität |
| Decision Diagrams | Ebenfalls in der Roadmap | A*-gesteuerte Konstruktion für optionale Jobauswahl sowie zustandsübergreifendes Caching |
| CBS / SMT-CBS | Bereits diskutiert | Klare Einschränkung durch Passagierkopplung und zulässige Warteorte |
| Lokale Reservierungsreparatur | [Insertion Kernel](../plans/reservation_insertion_kernel.md) geplant und untersucht | Globale Zeitfortpflanzung nach gewählter Reihenfolge ist ein anderer innerer Kern als erneute lokale Einfügung |
| STOP-Mustersuche mit CP-Orakel | Implementiert, zuletzt geringer Fortschritt | Zusätzlich Reihenfolgen und OD-Bündel bewegen; Bewertungskosten vor neuer großer Suche lösen |
| DIDP als Solver, bewertete Zonen, Conveyor-Diagnose, Aufzugszuordnung | In überprüften Unterlagen kein implementierter Schwerpunkt gefunden | Konkrete zusätzliche Forschungslinien, mit Übertragungsgrenzen |

Die Aussage ist bewusst auf die überprüften Dokumente und Implementierungen begrenzt. Eine breite Recherche kann fehlende Ansätze aufzeigen; sie kann nicht beweisen, dass alle weltweiten Ideen oder jeder frühere Chat vollständig erfasst wurden.

## 12. Zwei begrenzte Tests statt des nächsten großen Neubaus

Die Aufwandsangaben sind eigene grobe Planungsschätzungen. Sie sind keine Laufzeitprognosen aus Papers und hängen vom Umfang der Äquivalenzfälle ab. Kein Test wird durch dieses Dokument gestartet.

### Test A — Kann ein Zeitgraph das innere Teilproblem billig lösen?

**Priorität 1; erste Machbarkeitsprüfung grob 1–2 Arbeitstage, vollständige Heuristik anschließend separat entscheiden.**

Zuerst aus bestehenden gültigen Zertifikaten Routen, lokale Ressourcenreihenfolgen, Präsenz und ganzzahlige Passagierzuordnung extrahieren. Einen vom Solver getrennten Zeitgraphen aufbauen. Noch keine freie Passenger-Optimierung und keine Behauptung, das ganze Problem sei damit polynomial.

Die Eingangssammlung soll verfügbare historische Zertifikate und kleine vollständig aufzählbare Fälle umfassen. Nicht künstlich 100 fast identische Kopien als unabhängige Evidenz zählen. Gefordert sind STOP/SKIP, echte Überholung, zwei gekoppelte Merges, Freigabe während Waiting, voller Sitzabschnitt, Horizontgleichheit, Schutz über H hinaus und Reservoir-Rückkehr.

Die früheste zulässige Belegung muss die fixierte Zuordnung erhalten, bekannte Zeugnisse akzeptieren und in kleinen Fällen das Optimum des entsprechenden fixierten Teilproblems reproduzieren. Widersprüche müssen auch erkannt werden. Gemessen werden Übersetzungszeit, Zeitberechnung, Validierung und Größe des Graphen.

Erst nach bestandenem Kern: auf kleinen Konfliktgruppen von 2, 4 und 8 Kabinen benachbarte lokale Reihenfolgen ändern, danach zusammengehörige OD-/STOP-Änderungen ergänzen. Der Rest des Plans darf als feste Randbedingung dienen; solche Ergebnisse sind lokale Heuristikresultate. Diese Nachbarschaft kann später erweitert werden.

**Entscheidungskriterium:** Liefert der Kern auf realen Teilproblemen mindestens eine Größenordnung mehr abgeschlossene Bewertungen je Sekunde als das heutige Orakel, und entstehen dabei auch gültige veränderte Pläne? Diese Schwelle ist ein vorgeschlagenes Pilotkriterium, keine erwartete Messzahl. Schnelle Ablehnungen allein reichen nicht. Falls die Restentscheidung weiterhin regelmäßig globale CP-Aufrufe benötigt, wäre der erhoffte Architekturgewinn nicht gezeigt.

### Test B — Trägt ein kompakter Ereigniszustand?

**Priorität 2; grob 2–4 Arbeitstage für ein begrenztes korrektes Modell.**

Mit wenigen Kabinen und wenigen OD-Gruppen beginnen, aber dieselbe Ressourcengeometrie und zulässigen Warteorte verwenden. Erst ein exaktes Replay mit der Summe N·Δt, dann ein Rollout mit mehreren Fortsetzungen, anschließend ein DIDP-Modell auf einem vollständig beschriebenen endlichen Aktionsraum.

Das Replay muss die vorhandenen Passagiersekunden exakt bis auf die bestehende Tick-Einheit reproduzieren. Auf vollständig enumerierbaren Fällen müssen Optima und zulässige Entscheidungen übereinstimmen. Für einen nur heuristischen Warteaktionssatz wird kein Optimalitätsbeweis ausgegeben.

Gemessen werden eindeutige Zustände, Transpositionsrate, Speicher pro Zustand, erzeugte Nachfolger, Zeit pro Fortsetzung und unabhängige Fahrplanvalidität. Noch vor Max50 stufenweise die Zahl gleichzeitig aktiver Kabinen und OD-Gruppen erhöhen. Explosion bereits bei kleinen echten Konfliktfällen wäre ein klares Stoppsignal für einen kurzfristigen vollständigen DIDP-Neubau.

**Entscheidungskriterium:** Können wir relevante Historien zusammenfassen und deutlich billiger fortsetzen als mit einem neuen Gesamtmodell? Falls ja, Rollout und vollständige Suche auf denselben kleinen Zuständen vergleichen. Falls nein, keine große Lern-/MCTS-Schicht über einen zu teuren Simulator bauen.

### Gemeinsamer fairer Vergleich nach bestandenen Piloten

Bei 10, 30, 120 und 300 Sekunden dieselben validierten Seeds und Domänen verwenden. Mindestens zwei zusätzliche Seeds für stochastische Verfahren einplanen. Aufbau, Suche und Prüfung separat sowie insgesamt messen. Berichten: gültige neue Pläne, UB-Verlauf, Zahl tatsächlich abgeschlossener Bewertungen, Plateauzeit und Speicher. Ein Retiming ohne neues Muster bleibt eine echte UB-Verbesserung, wird aber als solches ausgewiesen.

R-Reisezeit und C-Kapazität bleiben getrennt. Eine lokale Suche hat keinen neuen globalen LB. Für globale Vergleiche dieselbe zulässige analytische Untergrenze verwenden; Schranken aus fixierten Mustern dürfen nicht übertragen werden. Die jeweils aktuell besten zertifizierten Starts verwenden und deshalb die historische C-Formulierungskampagne mit ihrem älteren Seed nicht als unmittelbaren Laufzeitgegner ausgeben.

Erst danach lohnt eine längere Kampagne. Ein besserer Kandidatengenerator, der in fünf Minuten nur denselben Seed zurückliefert, ist trotz eleganter Theorie noch kein Fortschritt.

## 13. Konkrete Empfehlung für die Thesis

Ich würde derzeit **nicht** die nächste breite Solverkampagne oder ein großes Max50-Modell beginnen. Der erste überprüfbare Beitrag wäre die Frage, ob unser exaktes Timing nach festgelegten lokalen Entscheidungen zu einem kleinen Graphproblem wird. Das adressiert den gemessenen Engpass direkt und lässt freie, nichtperiodische Reihenfolgen weiterhin zu. Ein positiver Test eröffnet Rollout, gezielte Konfliktsuche und später eine vollständige Verzweigung über dieselben Entscheidungen.

Als eigenständige Alternative würde ich DIDP mit ereignisbezogenen Kosten prüfen. Hier liegt eine reale Chance auf eine andere Suchdynamik und Zustandswiederverwendung. Die größte Unbekannte ist die Zustandsbreite, nicht die Verfügbarkeit eines Solvers. Wer vor allem den globalen Gap verbessern will, sollte daraus eine valide DD-/DP-Relaxation entwickeln, statt MCTS eine nicht vorhandene Beweisfunktion zuzuschreiben.

Eine kleine Conveyor-/Dichteanalyse würde ich parallel zur Interpretation vorhandener Resultate verwenden, ohne daraus eine dritte große Implementierung zu machen. Sie kann die Frage „Warum hilft die 39. Kabine nicht?“ in physische Blockierung, Initialisierung und Suchversagen aufteilen.

Der wissenschaftlich belastbare Fortschritt kann also auch lauten: eine neue Darstellung mit nachgewiesener Äquivalenz eines Teilkerns, messbar günstigere Suche und eine sauber abgegrenzte Grenze ihrer Skalierung. Eine erneute Behauptung, der nächste Optimierer werde mit genügend Laufzeit sicher alles lösen, wäre durch die vorhandene Evidenz nicht gedeckt.

## Literatur und Evidenzumfang

Primärquellen sind verlinkt. „Volltextauszüge“ bedeutet, dass relevante Abschnitte eines zugänglichen Volltexts geprüft wurden, nicht dass jeder Beweis vollständig nachvollzogen wurde. Bei „Abstract“ stützt sich die Bewertung nur auf den angegebenen öffentlichen Primärtext. Laufzeitaussagen aus anderen Problemklassen werden nicht als Ropeway-Prognosen verwendet. Eigene Übertragungen und mathematische Ableitungen sind im Haupttext gekennzeichnet.

1. **Mascis, A.; Pacciarelli, D. (2002).** *Job-shop scheduling with blocking and no-wait constraints.* European Journal of Operational Research 143(3), 498–517. [Verlag / DOI 10.1016/S0377-2217(01)00338-1](https://www.sciencedirect.com/science/article/pii/S0377221701003381). Zugriff: primärer Abstract. Relevanz: alternative Graphen für physisch eingeschränktes Warten.
2. **Adams, J.; Balas, E.; Zawack, D. (1988).** *The Shifting Bottleneck Procedure for Job Shop Scheduling.* Management Science 34(3), 391–401. [Verlag / DOI 10.1287/mnsc.34.3.391](https://pubsonline.informs.org/doi/10.1287/mnsc.34.3.391). Zugriff: Abstract. Relevanz: engpassorientierte Reihenfolgeheuristik.
3. **Dechter, R.; Meiri, I.; Pearl, J. (1991).** *Temporal constraint networks.* Artificial Intelligence 49, 61–95. [Verlag / DOI 10.1016/0004-3702(91)90006-6](https://doi.org/10.1016/0004-3702(91)90006-6). Zugriff: Abstract und indexierter Autoren-Reprint; direkter PDF-Abruf zeitweise fehlgeschlagen. Relevanz: temporale Differenzconstraints; keine Ropeway-Äquivalenz aus dem Paper übernommen.
4. **Sakai, M.; Nishi, T. (2017).** *Noncyclic scheduling of dual-armed cluster tools for minimization of wafer residency time and makespan.* Advances in Mechanical Engineering. [Volltext / DOI 10.1177/1687814017693217](https://journals.sagepub.com/doi/full/10.1177/1687814017693217). Zugriff: Volltextauszüge. Relevanz: nichtzyklische Operationsfolge, Petri-Netz und anschließende Zeitoptimierung.
5. **Yang, F.; Wu, N.; Qiao, Y.; Zhou, M. (2017).** *Optimal One-Wafer Cyclic Scheduling of Time-Constrained Hybrid Multicluster Tools via Petri Nets.* IEEE Transactions on Systems, Man, and Cybernetics: Systems 47(11), 2920–2932. [Autoreninstitution / DOI 10.1109/TSMC.2016.2531697](https://researchwith.njit.edu/en/publications/optimal-one-wafer-cyclic-scheduling-of-time-constrained-hybrid-mu/). Zugriff: Abstract. Einschränkung: spezielle zyklische Strategie.
6. **Gregoire, J.; Bonnabel, S.; de La Fortelle, A. (2013).** *Robust multirobot coordination using priority encoded homotopic constraints.* [Autoren-Preprint](https://arxiv.org/abs/1306.0785). Zugriff: Abstract. Relevanz: Prioritäten von geometrischer Ausführung trennen.
7. **Bertsekas, D. P.; Tsitsiklis, J. N.; Wu, C. (1997).** *Rollout Algorithms for Combinatorial Optimization.* Journal of Heuristics 3, 245–262. [Autoren-PDF](https://www.mit.edu/~jnt/Papers/J066-97-rollout.pdf), DOI 10.1023/A:1009635226865. Zugriff: Abstract und Einleitung. Relevanz: Fortsetzungsheuristik als Bewertung nächster Entscheidungen.
8. **Kim, D.; Kim, H.-J. (2022).** *Monte Carlo Tree Search-Based Algorithm for Dynamic Job Shop Scheduling with Automated Guided Vehicles.* Winter Simulation Conference. [Proceedings-PDF](https://informs-sim.org/wsc22papers/336.pdf). Zugriff: Volltextauszüge, insbesondere Abstract/Modellbeschreibung. Relevanz: Scheduling mit Transportmitteln und zeitlichen Zuständen.
9. **Boveroux, L.; Ernst, D.; Louveaux, Q. (2025).** *Investigating the Monte-Carlo Tree Search Approach for the Job Shop Scheduling Problem.* [Autoren-Preprint, geprüfte Fassung v1](https://arxiv.org/html/2501.17991v1). Zugriff: Volltextauszüge einschließlich Modellierung und Experimenten. Relevanz: Rezirkulation, gewichtete Fertigstellung, Vergleich mit eigener CP-Formulierung.
10. **Kuroiwa, R.; Beck, J. C. (2024–2026).** *Domain-Independent Dynamic Programming.* [Autoren-Preprint; geprüfte Fassung v5, 12.03.2026](https://arxiv.org/abs/2401.13883), [Framework und Software](https://didp.ai/). Zugriff: Volltextauszüge, Suchverfahren und Modellbedingungen. Relevanz: ausführbarer allgemeiner DP-Solver statt nur abstrakter Algorithmusidee.
11. **Bergman, D.; Ciré, A. A.; van Hoeve, W.-J.; Hooker, J. N. (2016).** *Discrete Optimization with Decision Diagrams.* INFORMS Journal on Computing 28(1), 47–66. [Verlag / DOI 10.1287/ijoc.2015.0648](https://pubsonline.informs.org/doi/10.1287/ijoc.2015.0648), [Autoren-PDF](https://johnhooker.tepper.cmu.edu/discrete_opt_with_DDs.pdf). Zugriff: Abstract/Methodenüberblick. Relevanz: relaxierte und restringierte DDs, Branch-and-Bound.
12. **Horn, M.; Maschler, J.; Raidl, G. R.; Rönnberg, E. (2021).** *A*-based construction of decision diagrams for a prize-collecting scheduling problem.* Computers & Operations Research 126, 105125. [Volltext](https://liu.diva-portal.org/smash/get/diva2:1485500/FULLTEXT02.pdf), DOI 10.1016/j.cor.2020.105125. Zugriff: Volltextauszüge. Relevanz: optionale Auswahl, Reihenfolge, mehrere Ressourcen, kompakte Schranken.
13. **Coppé, V.; Gillard, X.; Schaus, P. (2024).** *Decision Diagram-Based Branch-and-Bound with Caching for Dominance and Suboptimality Detection.* INFORMS Journal on Computing 36(6), 1522–1542. [Verlag / DOI 10.1287/ijoc.2022.0340](https://pubsonline.informs.org/doi/10.1287/ijoc.2022.0340), [Forschungssoftware](https://github.com/INFORMSJoC/2022.0340). Zugriff: Abstract und Softwarebeschreibung. Relevanz: Wiederverwendung von Zustandsinformationen.
14. **Behrmann, G.; Fehnker, A.; Hune, T. S.; Larsen, K. G.; Pettersson, P.; Romijn, J.; Vaandrager, F. W. (2001).** *Minimum-Cost Reachability for Priced Timed Automata.* BRICS RS-01-3. [Bericht und Volltext](https://www.brics.dk/RS/01/3/index.html). Zugriff: Volltextauszüge. Relevanz: Zeitbedingungen und akkumulierte Kosten in symbolischer Suche.
15. **Bouyer, P.; Colange, M.; Markey, N. (2016).** *Symbolic Optimal Reachability in Weighted Timed Automata.* [Autoren-Preprint und PDF](https://arxiv.org/abs/1602.00481). Zugriff: Abstract und Volltextauszüge. Relevanz: bewertete Zonen, symbolische Behandlung von Uhren.
16. **Ruokokoski, M.; Sorsa, J.; Siikonen, M.-L.; Ehtamo, H. (2016).** *Assignment formulation for the Elevator Dispatching Problem with destination control and its performance analysis.* European Journal of Operational Research 252(2), 397–406. [Autoreninstitution](https://research.aalto.fi/fi/publications/assignment-formulation-for-the-elevator-dispatching-problem-with-/), [Autoren-PDF](https://sal.aalto.fi/publications/pdf-files/ejor2016_public.pdf), DOI 10.1016/j.ejor.2016.01.019. Zugriff: Abstract und Volltextauszüge; erneuter PDF-Abruf zeitweise fehlgeschlagen. Relevanz: Zuordnung zuerst, aber Gegenbeleg für allgemeine Reisezeitäquivalenz.
17. **Neely, M. J. (2010, Preprint).** *Dynamic Optimization and Learning for Renewal Systems.* [Autoren-Preprint](https://arxiv.org/abs/1011.5942). Zugriff: Abstract. Relevanz: Entscheidungen mit variabler Dauer; langfristige Kriterien sind keine endlichen Ropeway-Gaps.
18. **Wei, X.; Neely, M. J. (2018).** *Asynchronous Optimization over Weakly Coupled Renewal Systems.* Stochastic Systems 8(3). [Autoren-PDF](https://ee.usc.edu/stochastic-nets/docs/asynchronous-renewals.pdf). Zugriff: Abstract/Einleitung. Relevanz: asynchrone Akteure mit gemeinsamer Kopplung; harte Kollisionsregeln bleiben separat nötig.
19. **van der Gaast, J. P.; de Koster, M. B. M.; Adan, I. J. B. F. (2018).** *Conveyor Merges in Zone Picking Systems: A Tractable and Accurate Approximate Model.* Transportation Science 52(6), 1428–1443. [Publizierter Volltext](https://repub.eur.nl/pub/114014/RePub-114014-OA.pdf), DOI 10.1287/trsc.2017.0782. Zugriff: Volltextauszüge einschließlich Durchsatztabellen. Relevanz: endliche Puffer, Rezirkulation, nichtmonotone Durchsatzwirkung von Umlaufbestand.
20. **Farhi, N.; Nguyen Van Phu, C.; Haj-Salem, H.; Lebacque, J.-P. (2016, Preprint).** *Traffic Modeling and Real-time Control for Metro Lines.* [Autoren-Preprint](https://arxiv.org/abs/1604.04593). Zugriff: Abstract. Relevanz: Max-Plus-Dynamik, Fahrzeugzahl und asymptotischer Verkehr.
21. **Schanzenbächer, F.; Farhi, N.; Christoforou, Z.; Leurent, F.; Gabriel, G. (2018).** *A discrete event traffic model explaining the traffic phases of the train dynamics in a metro line system with a junction.* [Autoren-Preprint](https://arxiv.org/abs/1801.00931). Zugriff: Abstract. Relevanz: Engpass-/Verzweigungsstruktur und Betriebsphasen.
22. **Andreychuk, A.; Yakovlev, K.; Boyarski, E.; Stern, R. (2021).** *Improving Continuous-time Conflict Based Search.* Proceedings of AAAI 35(13), 11220–11227. [Proceedings / DOI 10.1609/aaai.v35i13.17338](https://ojs.aaai.org/index.php/AAAI/article/view/17338). Zugriff: Abstract. Relevanz: zeitkontinuierliche Konfliktsuche; nicht die gemeinsame Passagierzuordnung.
23. **Ihalainen, H.; Berg, J.; Järvisalo, M. (2023).** *Unifying Core-Guided and Implicit Hitting Set Based Optimization.* IJCAI, 1935–1943. [Proceedings / DOI 10.24963/ijcai.2023/215](https://www.ijcai.org/proceedings/2023/215). Zugriff: Abstract. Relevanz: Konfliktkerne und Optimierung.
24. **Berg, J.; Bacchus, F.; Poole, A. (2021).** *Abstract Cores in Implicit Hitting Set MaxSat Solving (Extended Abstract).* IJCAI. [Proceedings](https://www.ijcai.org/proceedings/2021/643). Zugriff: Abstract. Relevanz: wiederkehrende Kerne komprimieren; teilweise ganzzahliger Master.
25. **Dechter, R. (1999).** *Bucket elimination: A unifying framework for reasoning.* Artificial Intelligence 113, 41–85. [Verlag / DOI 10.1016/S0004-3702(99)00059-4](https://www.sciencedirect.com/science/article/pii/S0004370299000594), [Autoren-PDF](https://ics.uci.edu/~csp/r48b.pdf). Zugriff: Abstract/Methodenüberblick. Relevanz: Breite statt reine Variablenzahl als Komplexitätsmaß.
26. **Leighton, F. T.; Maggs, B. M.; Rao, S. B. (1994).** *Packet Routing and Job-Shop Scheduling in O(Congestion + Dilation) Steps.* [Autorenfassung](https://www.cs.cmu.edu/afs/cs.cmu.edu/project/phrensy/pub/papers/LeightonMR94/LeightonMR94.html). Zugriff: Satz-/Modellbeschreibung. Relevanz: Kongestion und Weglänge; abweichende Pufferannahmen.
27. **Zhang, J.; Luo, C.; Su, Z.; Zhang, Q.; Lü, Z.; Ding, J.; Jin, Y. (2025).** *NS4S: Neighborhood Search for Scheduling Problems Via Large Language Models.* IJCAI, 8687–8695. [Proceedings / DOI 10.24963/ijcai.2025/966](https://www.ijcai.org/proceedings/2025/966). Zugriff: Abstract. Relevanz: gelernte/generierte Steuerung bestehender Nachbarschaften.
28. **Wan, J.; Lee, K.; Shin, H. (2026).** *A Hybrid Approach of Imitation Learning and Deep Reinforcement Learning with Direct-Effect Update Interval for Elevator Dispatching.* ACM Transactions on Cyber-Physical Systems 10(3), Artikel 30. [Verlag / DOI 10.1145/3790252](https://doi.org/10.1145/3790252). Zugriff: Abstract/Publikationsdaten. Relevanz: lernende Aufzugssteuerung; keine hier übertragene Optimalitätsgarantie.
29. **Mei, Y.; Gu, W.; Cassidy, M.; Fan, W. (2021).** *Planning skip-stop transit service under heterogeneous demands.* Transportation Research Part B 150, 503–523. [Autoreninstitution](https://research.polyu.edu.hk/en/publications/planning-skip-stop-transit-service-under-heterogeneous-demands/), [Autoren-Preprint](https://arxiv.org/abs/2011.12674), DOI 10.1016/j.trb.2021.06.008. Zugriff: Abstract/Modellübersicht. Relevanz: Nachfrageheterogenität und eingeschränkte AB-Angebotsgestaltung.
30. **Boysen, N.; Stephan, K.; Schwerdfeger, S. (2024).** *Order consolidation in warehouses: The loop sorter scheduling problem.* European Journal of Operational Research 316(2), 459–472. [Verlag / DOI 10.1016/j.ejor.2024.02.042](https://www.sciencedirect.com/science/article/pii/S0377221724001723). Zugriff: primärer Abstract. Relevanz: kombinierte Zuordnung und Reihenfolge auf geschlossenem Förderkreislauf.

## Code- und Ergebniswegweiser

Alle Codepfade beziehen sich auf `src/ropeway_skip_stop_optimization/optimization/ddd/`:

| Gegenstand | Datei / Dokument |
|---|---|
| Route, Ressourcen, affine Waiting-Geometrie | [models.py](../../src/ropeway_skip_stop_optimization/optimization/ddd/models.py) |
| Ganzzahlige Beförderungen, Freigaben, Zielfunktion | [cp_sat_passenger.py](../../src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_passenger.py) |
| Reservoirbesuche, kanonische Kandidaten, Lebenszyklus | [reservoir_cp_sat_problem.py](../../src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_cp_sat_problem.py) |
| Bestehendes CP-Timing und Ressourcennutzung | [cp_sat_movement.py](../../src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_movement.py) |
| Muster, Nachbarschaften, inneres Timing-Orakel | [pattern_search.py](../../src/ropeway_skip_stop_optimization/optimization/ddd/pattern_search.py) |
| Neue Profile und gemeinsame Vorbereitung | [cp_formulation.py](../../src/ropeway_skip_stop_optimization/optimization/ddd/cp_formulation.py) |
| 24-Läufe-Kampagne | [comparison.md](../../benchmarks/output/cp_formulation_campaign_20260910_121055/comparison.md), [evaluation.json](../../benchmarks/output/cp_formulation_campaign_20260910_121055/evaluation.json) |
| Aktuelle K39-Fortsetzung | [Befund mit Artefaktlinks](../findings/ddd_pattern_search_followup_20260910.md) |
| Startwert-Effekt ohne Modelländerung | [Zeit-Hint-Ablation](../findings/ddd_pattern_time_hint_ablation_20260910.md) |

Für jeden neuen Suchkern bleiben die ursprüngliche Domäne und unabhängigen physikalischen sowie ganzzahligen Passagierprüfer maßgeblich. Ein schneller Decoder wird nicht zugleich seine eigene einzige Korrektheitsinstanz.
