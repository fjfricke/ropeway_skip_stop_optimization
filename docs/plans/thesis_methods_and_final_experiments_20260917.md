# Welche Verfahren wir für die Thesis jetzt verwenden sollten

Stand: 17.09.2026. Entscheidungsvorschlag nach Code-, Plan- und Ergebnisprüfung; noch keine Freigabe einer neuen Kampagne.

**Nachfolgende Festlegung:** Für die Ausführung gilt nun der
[abschließende Kapazitätsplan](thesis_capacity_final_campaign_20260917.md).
F2 wird vollständig neu gerechnet; die unten vorgeschlagene Wiederverwendung
alter Suchläufe ist damit überholt. Vorzeitige Rückkehr ist in allen Verfahren,
einschließlich freier CP-SAT-Nachoptimierung, ausgeschlossen. Die folgenden
historischen Befunde bleiben als Audit erhalten.

## 1. Empfehlung

**Studie 1 bleibt bei Labelled Arc-Flow mit Gurobi. Die vorhandenen Journey-Ergebnisse bleiben erhalten. Studie 2 sollte mit wenigen nachfragebasierten Linien und dem vorhandenen No-Wait-Decoder ausführbare Skip-Stop-Pläne erzeugen. Den vollständigen CP-SAT verwenden wir anschließend gezielt zur Verbesserung guter Pläne.**

Die knappe verbleibende Zeit würde ich nicht mehr in einen neuen Solver, eine weitere breite Mustersuche mit teurem Timing-Unterproblem oder große CP-SAT-Suchen ohne Startplan investieren.

Dabei ist die Ausgangslage besser als „alles erfolglos“:

- Die abgeschlossene Journey-Kampagne enthält 64 ausgewählte Läufe; 62 haben unabhängig validierte vollständige Bedienung.
- Für T5/F2 existiert bereits ein gültiger **No-Wait-Plan für 3.210 Personen bei K=62**. Die reguläre All-Stop-Referenz kann höchstens ein Profil mit 2.918 Personen vollständig bedienen.
- Ein vollständiger CP-SAT-Lauf hat einen bekannten Skip-Stop-Plan bei N=2.918 erheblich in Journey Time verbessert. Die späteren schwachen Suchen mit All-Stop-Start oder ohne Start widerlegen diesen Erfolg nicht.
- Für F3 und F0 gibt es bisher keinen entsprechend überzeugenden Kapazitätserfolg. Hier sind kurze, begrenzte Versuche und ein ehrlicher negativer Befund sinnvoller als eine weitere offene Methodenentwicklung.

**Evo kann als vorhandener Suchmechanismus bleiben. Die Thesis sollte seinen Nutzen aber an Verbesserungen nach der Initialisierung messen.** Ein guter erster Kandidat beweist eine gute Konstruktion, nicht die Leistungsfähigkeit der Evolution.

## 2. Was die beiden Studien tatsächlich untersuchen

### Studie 1: Journey Time bei vollständiger Bedienung

Frage: Wie stark verkürzt Skip-Stop die Zeit von Nachfragefreigabe bis Ankunft, wenn dieselbe Nachfrage mit derselben Flotte vollständig bedient werden muss?

| Einstellung | Tatsächlich verwendete Hauptreihe |
|---|---|
| Modell | Labelled Arc-Flow, integrierte ganzzahlige Passagierzuordnung, Gurobi |
| Netz/Nachfrage | T5R/G500, P0, F0/F2/F3/F4, Freigabebatches alle 15 s |
| Betrieb | Feste, ausgeglichene Anfangspositionen; No-Wait; feste Kabinenzahl |
| Vergleich | All-Stop und freie STOP/SKIP-Entscheidungen unter gleichen Anfangsbedingungen |
| Ziel | Journey Time; vollständige Bedienung als Nebenbedingung |
| Laufbudget | 1.800 s je Lauf, 1 % MIP-Gap, Seed 0, zwölf Threads |

Es gibt **zwei Teilreihen innerhalb dieser Journey-Studie**:

1. **Relative Belastung:** K=10,20,30; Nachfrage `floor(alpha * kappa_AS(K))` mit alpha=0,25 beziehungsweise 0,75. Das sind 48 Läufe einschließlich beider Betriebsweisen.
2. **Konstante Nachfrage:** K=20,30; Nachfrage `floor(kappa_AS(31)/2)`, bei beiden K identisch. F0=1.553, F2=469, F3=1.105, F4=2.327. Das sind 16 Läufe.

Diese Teilreihen sind nicht mit der späteren Reservoir-Kapazitätsstudie gleichzusetzen. Insbesondere beziehen sich ihre Referenzkapazitäten auf feste Anfangspositionen.

### Studie 2: Bedienbare Nachfrage nahe der All-Stop-Grenze

Frage: Kann Skip-Stop bei begrenzter verfügbarer Flotte ein stärkeres Nachfrageprofil vollständig bedienen als der **reguläre All-Stop-Referenzbetrieb**?

Empfohlener Hauptvertrag: Single-Use-Reservoir, gemeinsamer Port, No-Wait, unveränderte Freigaben und Betriebsfenster. Kabinen fahren bis zur vorgeschriebenen Rückkehr weiter. Zunächst K=K_AS. Waiting und größere/kleinere Flotten sind ausdrücklich getrennte Erweiterungen.

Ziel: zunächst `unserved` minimieren, bei gleichem Wert Journey Time. Bei U=0 ist die Bedienungsfrage für diesen Nachfragepunkt beantwortet; die beste Journey Time ist dadurch noch nicht bewiesen.

| Referenz | K_AS | Größtes nachgewiesen voll bedienbares N | Erstes nachgewiesen nicht voll bedienbares N |
|---|---:|---:|---:|
| T5/F2 | 62 | 2.918 | 2.919 |
| T5/F3 | 62 | 7.153 | 7.154 |
| T5/F0 | 62 | 9.781 | 9.796 |
| T6/F2 | 75 | 2.942 | 2.943 |
| T6/F3 | 75 | 5.517 | 5.518 |
| T6/F0 | 75 | 9.750 | 9.875 |

F2 und F3 sind innerhalb des Referenzvertrags exakt bestimmt. Bei F0 bleiben Intervalle offen: T5 `9781 <= kappa_AS <= 9795`, T6 `9750 <= kappa_AS <= 9874`. F0 daher nicht als bekannte exakte Nmax ausweisen.

**Was Nmax hier bedeutet:** Die Referenz optimiert die gemeinsame Phase eines regelmäßig disponierten All-Stop-Plans und seine ganzzahlige Passagierzuordnung. Sie beweist kein Optimum über beliebige unregelmäßige All-Stop-Dispatchzeiten und Waiting.

Beispiel F2: `ceil(1.1 * 2918) = 3210` bedeutet 10 % mehr **Profilnachfrage**. Es bedeutet nicht, dass All-Stop bei N=3.210 genau 2.918 Personen bedient. Bei größerer Nachfrage kann sich seine tatsächlich bediente Menge ändern. Für einen Vergleich „served bei gleichem N“ müssen beide Fahrpläne auf genau diesem N bewertet werden; eine bloß mitgeführte Linie bei 2.918 ersetzt das nicht.

Quellen: [ausgewählte Journey-Queue](../../results/thesis_journey_revised_campaign_20260915/queue.json), [Referenzablage](../../results/thesis_phase_cell_capacity_references_20260916), [bisheriger Studienplan](../../archive/docs/plans/thesis_study_execution_20260915.md).

## 3. Labelled Arc-Flow und aktuelles CP-SAT: der konkrete Unterschied

**„Labelled“ bedeutet, dass eine Kabine ihre Identität behält. Das allein bestimmt noch nicht die Modellierung.** Auch der Reservoir-CP-SAT unterscheidet Kabinen.

| Aspekt | Labelled Arc-Flow der Journey-Reihe | Aktueller vollständiger Reservoir-CP-SAT |
|---|---|---|
| Bewegung | Binäre Auswahl eines Pfades je Kabine in einem vorbereiteten Netz erreichbarer Besuchszeiten | Integer-Ereigniszeiten, aktive Besuche und STOP/SKIP-Entscheidungen |
| Zeitentscheidung | Wahl eines Arcs wählt dessen vorbereitete Zeitlage mit | Zeitvariablen werden unmittelbar durch den Solver bestimmt |
| Start | Feste Anfangsposition und Anfangszeit je Kabine | Dispatch aus gemeinsamem Reservoir innerhalb eines Fensters |
| Flotte | Feste K im verwendeten Versuch | Grundsätzlich bis Kmax; letzte Versuche zusätzlich exakt K=62 |
| Waiting | In der Journey-Reihe ausgeschlossen | Optional erlaubt; im aktuellen Versuch auf null gesetzt |
| Konflikte | Ressourcen-Konfliktcliquen zwischen zeitlich bestimmten Arcs | Bedingte Ressourcennutzung und Scheduling-Constraints |
| Passagiere | Gemeinsame ganzzahlige Passagierfluss-/Ride-Variablen im Gurobi-Modell | Gemeinsame ganzzahlige Passagiervariablen, zuletzt OD-Inventar im CP-SAT |
| Journey-Kosten | Vorberechnete Zeitkosten an ausgewählten Beförderungen | Variable Ankunftszeiten müssen mit Passagiermengen gekoppelt werden |
| Entscheidungsraum | Exakt für die vorbereitete Fixed-Start-No-Wait-Domäne | Freiere Reservoir-Domäne mit Dispatch, Rückkehr und ggf. Waiting |

Im Arc-Flow-Netz werden nicht sämtliche Mikrosekunden blind als Knoten erzeugt. Die Vorbereitung erzeugt aus möglichen Bewegungen erreichbare Zeitlagen. Bei festen Starts und No-Wait kann das gut funktionieren. Freie Dispatchzeiten und Waiting würden wesentlich mehr Timingmöglichkeiten beziehungsweise eine andere Darstellung verlangen.

Der No-Wait-Reservoir-CP-SAT bleibt dagegen ein Ereignismodell mit freien Dispatchzeiten. Selbst wenn für eine festgelegte Haltefolge alle späteren Zeiten aus dem Dispatch folgen, muss der Solver Haltefolgen und ihre gegenseitige Verträglichkeit noch finden. **Waiting=0 schaltet nicht auf Labelled Arc-Flow um.**

Auch das gleichzeitige Auftreten von `arc_flow` und `ddd` in Dateinamen ist kein Beleg, dass die Thesis-Reihe eine äußere DDD-Verfeinerung ausführt. Der gewählte Runner verwendet den integrierten Arc-Flow-Solve.

Code: [Arc-Flow](../../src/ropeway_skip_stop_optimization/optimization/ddd/arc_flow.py), [Netzvorbereitung](../../src/ropeway_skip_stop_optimization/optimization/ddd/arc_flow_preparation.py), [Thesis-Fallbuilder](../../src/ropeway_skip_stop_optimization/benchmarking/thesis_cases.py), [Reservoir-CP-SAT](../../src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_cp_sat.py).

## 4. Ist die neue Passagieroptimierung auch im Arc-Flow-Modell?

**Passagieroptimierung: ja. Die neue OD-Inventar-Formulierung: nein.**

Alle 64 ausgewählten Journey-Ergebnisse melden `passenger_profile=legacy`. Ihr Gurobi-Modell optimiert dennoch Bewegung und ganzzahlige Passagierzuordnung gemeinsam. „Legacy“ ist hier ein Formulierungsname, kein Hinweis auf eine fehlende oder nachträgliche Passagieroptimierung.

Die neue CP-SAT-Darstellung bündelt Freigabebatches gleicher OD. Kumulative Verfügbarkeitsbedingungen verhindern, dass mehr Personen einsteigen als bereits angekommen sind. Die Zuordnung wird anschließend auf die ursprünglichen Nachfragegruppen zurückgeführt und unabhängig geprüft. Sie nutzt den gemeinsamen Bedienungshorizont und die vorhandene Zielstruktur.

Der gemessene Größengewinn ist erheblich: auf T5/F2, N=3.210, Kmax=69 und W=1.200 s von **638.127 auf 97.361 Variablen** und von **2.337.064 auf 166.328 Constraints**. Das ist ein gemessener Vergleich dieser Reservoir-Formulierungen, keine Größenprognose für Arc-Flow und kein Nachweis schneller globaler Optimierung.

Arc-Flow besitzt eigene optionale Passagierverdichtungen, etwa `destination_flows`. Diese sind nicht dieselbe Implementierung. Eine Übertragung der OD-Inventar-Idee müsste gegen die Arc-Flow-Domäne und Zielfunktion geprüft werden. **Das würde ich vor morgen nicht entwickeln und deshalb auch nicht alle bestehenden Läufe wiederholen.**

Quellen: [OD-Inventar](../../src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_passenger_inventory.py), [Buildbefund](../findings/cp_sat_od_inventory_passengers_20260916.md), [Arc-Flow-Passagierformulierungen](../../src/ropeway_skip_stop_optimization/optimization/ddd/arc_flow_passenger_formulation.py).

## 5. Welche Verfahren vorhanden sind und wofür wir sie noch brauchen

Die Tabelle fasst Familien zusammen. Unterschiedliche Encodings, Selektionsprofile und Solverparameter sind keine jeweils neuen Hauptalgorithmen.

| Familie | Aufgabe / bisheriger Nutzen | Empfehlung bis zur Abgabe |
|---|---|---|
| **Labelled Arc-Flow / Gurobi** | Exakte integrierte Fixed-Start-No-Wait-Aufgabe; belastbare Journey-Ergebnisse | **Hauptverfahren Studie 1 behalten** |
| **Regulärer All-Stop-Phasenzellen-Referenzsolver** | Spezialisierte Referenzkapazität durch gemeinsame Phase und Integer-Passagiere | **Referenz für Studie 2 behalten**; offene F0-Intervalle kennzeichnen |
| **No-Wait-Liniendecoder + fester Passagier-IP** | Wiederholte Stationsmasken und Dispatchvorschläge physikalisch prüfen; gültige Pläne schnell bewerten | **Konstruktiver Kern Studie 2** |
| **Evo mit Muster- und Dispatchgenen** | Sucht Kombinationen, Reihenfolge und Dispatchparameter; GA/NSGA-II sowie lokale, Block- und globale Varianten | Nur mit kleinem begründetem Katalog und nachvollziehbarer Initialisierung; Nutzen gegenüber erstem Kandidaten messen |
| **Evo mit Liniengruppen / Stopmasken** | Gekoppelte statt unabhängige Musteränderungen, besser strukturierte Kandidaten | Vorhandenen Pfad für kurze F3-Prüfung verwenden; bisher kein allgemeiner Durchbruch |
| **Patterns-only-Evo + CP-SAT-Timing, ggf. gemeinsame Bedienung** | Äußere Suche legt Folge fest, Untermodell optimiert Dispatch; Waiting-Varianten vorhanden | **Keine neue breite Kampagne**: viele unzulässige/ungeklärte Folgen und teure Auswertungen |
| **Nativer kompakter Linien-CP-SAT** | Gemeinsame Musterwahl, Dispatch, Templates und Passagiere innerhalb eines Katalogs; auch feste Folgen/Anzahlen | Optionaler enger Kontrollversuch; historische Erfolge hatten kleinen Katalog/guten Start oder festgelegte Folge |
| **Vollständiger Reservoir-CP-SAT mit OD-Inventar** | Freie STOP/SKIP-Besuche, K, Dispatch, Waiting, Rückkehr und Passagiere | **Gezielte Nachoptimierung guter Skip-Stop-Zeugen**; keine weitere große Suche ohne Hint priorisieren |
| **Flottenfortsetzung K=1,2,…** | Wiederholte vollständige CP-SAT-Solves mit vorheriger Lösung als Hint | Archivierter Pilot; für die verbleibende Zeit kein Hauptverfahren |
| **Greedy, mit/ohne Waiting** | Schrittweise Einfügung; gültiger heuristischer Vergleich | Gespeicherte Vergleichsläufe behalten, keine breite Wiederholung; zuletzt schwächer als vorhandene F2-Zeugen |
| **EAN / Gurobi und zeitdiskrete MILPs** | Alternative vollständige bzw. diskretisierte Modellierungen, Validator-/Referenzbausteine | Historische Methodenentwicklung; jetzt kein Neuaufbau |
| **Anonymer/exakter Reservoir-Arc-Flow und Kapazitätsrelaxationen** | Weniger Kabinenlabels, andere Flussmodelle; teils nützliche Bounds | Bounds nur im jeweiligen Gültigkeitsbereich nutzen; kein bewährter Ersatz für die aktuelle Hauptsuche |
| **Corridor-Arc-Flow / adaptive DDD** | Grobe Zeitbereiche, konservative ausführbare Modelle und optimistische Relaxationen | Negativen Pilot dokumentieren; konservative Konflikthüllen verhinderten gute ausführbare Pläne |
| **Trajectory-/Column-Generation-, Benders- und Service-Class-Verfahren** | Auswahl aggregierter Bewegungen/Bedienung, danach Koordination oder Verfeinerung | Archiv/Methodendiskussion; Timingverträglichkeit und/oder Mastergröße blieben Engpässe |
| **DP/DIDP, symbolische/Pattern-DP** | Strukturierte Zustands-/Mustersuche | Für große dichte Fälle nicht mehr priorisieren |
| **IBM CP, Z3, Hexaly-Backends** | Weitere Solverpiloten, unterschiedlich weit geprüft | Kein belegter allgemeiner Sieger; unvollständig geprüfte Backends nicht als verlorenen fairen Vergleich ausweisen |

Random/TPE sind bestehende Blackbox-Kontrollen der Evolution. MAP-Elites, RL, neue Lagrange- oder eigene LNS-Verfahren würde ich jetzt nicht als zusätzliche Thesis-Hauptmethode beginnen.

Historischer Überblick und Belege: [Solver-Neubewertung](../findings/solver_reassessment_20260914.md), [Corridor-Befund](../findings/ddd_corridor_waiting_arc_flow_20260914.md), [Service-Class-Befund](../findings/reservoir_service_class_pilot_20260914.md), [native Solverpiloten](../findings/native_solver_pilot_20260911.md).

## 6. Was die entscheidenden gespeicherten Versuche zeigen

### Journey: kein Anlass für einen pauschalen Neustart

Die ausgewählten 64 Ergebnisdateien wurden anhand der aktuellen Queue geprüft, nicht durch Zählen aller archivierten Versuche:

- Relative Last: 24 All-Stop-Läufe mit geschlossenem Gap; 22 von 24 Skip-Stop-Läufen mit gültiger Vollbedienung. Davon 15 mit höchstens 1 % Gap, sieben mit größerem Gap. F0/K30 und F3/K30 bei 75 % Last haben keinen Incumbent.
- Konstante Nachfrage: alle 16 Läufe gültig und vollständig bedient. Vier der acht Skip-Stop-Ergebnisse haben einen Gap unter 1 %; vier bleiben darüber.
- F2 erreicht gegenüber All-Stop ungefähr 15–40 % Journey-Verbesserung, je Teilreihe/Last/K. F3 zeigt ebenfalls deutliche Verbesserungen. F4 ist in diesen Resultaten gleich gut. F0 ist schwieriger; einzelne zeitlimitierte Skip-Stop-Incumbents sind sogar schlechter als der bekannte All-Stop-Plan.

Letzteres beweist keinen Nachteil des Skip-Stop-Entscheidungsraums: Unter gleichen Bedingungen ist All-Stop darin enthalten. Es zeigt eine schwache gefundene Lösung im begrenzten Suchbudget. Das sollte im Text ausdrücklich so stehen.

### Kapazität und Reservoir: Erfolg hängt stark vom Start und vom Fall ab

| Gespeicherter Versuch | Beobachtung | Aussage |
|---|---|---|
| T5/F2, K62, N=3.210, kleiner OD-Katalog, No-Wait | 3.210 bedient; U=0; nur **eine** Auswertung, etwa 1,57 s Suchzeit | Gültiger Kapazitätszeuge bereits aus Initialisierung; kein Evolutionsfortschritt |
| T5/F3, K62, N=7.153, OD-Katalog | 3.710 bedient nach ca. 285 s | Kleiner Katalog allein löst das Problem nicht |
| T5/F3, K62, `relevant`, unabhängige Muster | 6.778 Auswertungen, keine gültige Lösung | Viele Versuche sind kein Ersatz für brauchbare Kandidatenstruktur |
| T5/F3, K62, `relevant`, Liniengruppen | 5.083 bedient, 51 gültige Auswertungen | Konstruktion verbessert; weiterhin deutlich unter der Referenz |
| F3, Patterns-only, parallele Timing-Auswertung | Gespeichert 3.864 bedient bei K62; variable-K-Variante 4.235 bei K38 | Kein Nachweis, dass das teure Untermodell den Suchengpass beseitigt |
| T5/F2, Journey-Evo, 30 min, N=2.918 | Alle bedient; J≈1,946 Mio. Personen-s | Vollbedienung allein bedeutet noch keine gute Journey Time |
| T5/F2, Greedy Journey ohne/mit Waiting | 2.130 / 2.255 bedient bei N=2.918 | Diese konkreten Greedy-Läufe sind schwächer |
| T5/F2, CP-SAT mit Skip-Stop-Start, N=2.918 | Alle bedient; J von 2,143 Mio. auf **0,733 Mio. Personen-s** in ca. 304 s | Starker positiver Befund für gemeinsame Nachoptimierung eines guten Skip-Stop-Starts |
| T5/F2, CP-SAT mit All-Stop-Start, W120, 30 min | Alle bedient; J≈1,753 Mio., nur geringe Verbesserung | Dieser Start führte zu wenig strukturellem Fortschritt |
| T5/F2, freies K, 1 ms, ohne Referenz, W120 | Beim Abbruch 633 bedient mit zehn Kabinen | Kleinere Tickdomäne allein reicht nicht für gute dichte Fahrpläne |

Der aktuelle No-Wait-Lauf mit exakt K62 und ohne Referenz hatte beim Audit nach ungefähr zehn Minuten noch keinen nativen Incumbent (`best:inf`). Das ist ein Zwischenstand, kein endgültiges Scheitern und kein Unzulässigkeitsbeweis. Er wurde für dieses Review nicht verändert.

**Der F2-Zeuge ist konkret:** 31 Kabinen halten an S1/S3, 31 an S2/S4, in alternierender Dispatchreihenfolge; die Masken wiederholen sich über die Umläufe. Alle Waitingwerte sind null. Der Initialsampler erzeugt solche alternierenden OD-Mischungen bereits. Der gespeicherte Fall unterscheidet sich vom All-Stop-Referenzcheckpoint in der Domänenbeschreibung nur durch die Nachfragegruppen.

Die beiden F2-Linienpläne für N=2.918 und N=3.210 sowie der CP-SAT-Verbesserungsplan wurden während dieses Reviews erneut durch `load_reference` und `validate_reservoir_cp_plan` geprüft. Der CP-SAT-Verbesserungsplan entstand mit Wmax=1.200 s, nutzt tatsächlich maximal 22,697 s Waiting und besteht auch eine erneute Prüfung mit Wmax=120 s. Er ist damit **kein No-Wait-Ergebnis**. Das Vergleichsexperiment mit identischem Start und identischem Budget fehlt weiterhin.

Rohdaten: [Stage-2-Evo](../../results/thesis_evo_stage2_lexicographic_20260916), [Liniengruppen](../../results/thesis_line_groups_pilot_20260916), [Patterns-only K62](../../results/thesis_pattern_only_parallel_k62_f3_s0_20260916), [Patterns-only variables K](../../results/thesis_pattern_only_variable_k_f3_s0_20260916), [Journey-Evo](../../results/thesis_evo_journey_t5r_f2_20260916/result.json), [Greedy](../../results/thesis_greedy_journey_t5r_f2_20260916), [CP-SAT mit Skip-Stop-Start](../../results/thesis_od_inventory_example_t5r_f2_n2918_k62_20260916/result.json).

Die älteren R2-Ergebnisse mit 3.074 Personen gehören zu einer anderen Geometrie und teils anderen Rückkehrregeln. Sie bleiben methodische Evidenz, werden aber nicht als T5R/G500-Ergebnis übernommen.

## 7. Was wir am oberen Ende jetzt konkret tun sollten

### Kleine Musterbibliothek: ja. Alles vorab fixieren: nein.

Es sind drei verschiedene Einschränkungen:

1. **Katalog fix:** Beispielsweise All-Stop sowie zwei OD-Masken. Suche entscheidet Mischung, Anzahl, Reihenfolge und Zeiten.
2. **Musterfolge fix:** Jede Kabine erhält ihre konkrete Maske; nur Dispatch und Passagiere werden optimiert.
3. **Fahrplan fix:** Auch Zeiten stehen fest; nur Passagiere werden zugewiesen.

Für F2 würde ich zunächst den bereits erfolgreichen kleinen Katalog und die ausführbare alternierende Konstruktion nutzen. Die Evolution darf anschließend Kombinationen und Timing verbessern. Wenn eine vollständig fixierte Folge nur zeitlich optimiert werden soll, brauchen wir dafür keine äußere Evolution.

Für F3 würde ich die vorhandenen Liniengruppen nur noch in einem kurzen Gate prüfen. Eine erneute unbeschränkte `relevant`-Suche ist durch die bisherigen Ergebnisse nicht gut begründet. F0 würde ich mit den bestehenden negativen Befunden und dem offenen Referenzintervall berichten; eine breite neue Kampagne ist keine Priorität.

### Guter Start plus freies CP-SAT ist eine sinnvolle zweite Stufe

Den besten gültigen Skip-Stop-Fahrplan mitsamt Passagieren als Hint übergeben. Keine `fixed_plan`- oder `fixed_route_plan`-Restriktion setzen, wenn wir eine freie Nachoptimierung behaupten. K als Obergrenze modellieren; weniger Kabinen dürfen verwendet werden. Der Hint ist ein Ausgangspunkt, keine Festlegung der Haltefolgen.

Der starke F2-Befund rechtfertigt einen begrenzten solchen Versuch. Er rechtfertigt keine Aussage, dass CP-SAT aus beliebigen Mustern oder ohne Start zuverlässig gute Pläne findet.

Die Haupt-Kapazitätsreihe bleibt No-Wait. Eine Nachoptimierung mit W120 wird separat als Betriebserweiterung gezeigt. Damit kann eine Verbesserung nicht versehentlich allein dem Suchalgorithmus zugeschrieben werden, obwohl zusätzliche Wartefreiheit erlaubt wurde.

### Nicht erneut alles gleichzeitig öffnen

Bis morgen würde ich nicht gleichzeitig den Katalog erweitern, K frei machen, Waiting ergänzen, die Nachfrage ändern und die Tickauflösung wechseln. Für die neuen Vergleiche jeweils dieselbe eingefrorene Domäne verwenden. Vorhandene Mikrosekunden-Zertifikate nicht nur durch Abrunden in 1-ms-Hints verwandeln; Übertragung muss validiert werden. Für die bestehende schnelle Linienreihe kann ihre bisherige Auflösung unverändert bleiben.

## 8. Müssen die bisherigen Thesis-Läufe wiederholt werden?

**Nein, nicht pauschal.** Die Änderungen am Reservoir-Passagiermodell verbessern nicht automatisch die bereits gerechnete andere Fixed-Start-Aufgabe. Kein im Audit gefundener Befund erklärt die 64 Journey-Ergebnisse für ungültig.

Sinnvolle begrenzte Ergänzung, falls nach den Kapazitätsversuchen noch Zeit bleibt: die zwei Journey-Fälle ohne Incumbent erneut mit dem jeweils validierten All-Stop-Plan als MIP-Start lösen. Das sind zwei neue, separat bezeichnete Warmstart-Läufe. Die ursprüngliche Kampagne „ohne importierten Start“ bleibt erhalten; Ergebnisse und Laufzeit werden nicht rückwirkend ersetzt.

Auch bei den schwachen F0-Incumbents darf man einen bekannten besseren All-Stop-Fahrplan als verfügbaren Rückfallwert nennen. Das ist aber nicht dasselbe wie ein vom ursprünglichen Skip-Stop-Solve gefundener Incumbent.

Vor Abgabe ist vor allem die **Dokumentation zu synchronisieren**:

- Kapitel 6 nennt noch volle `kappa_AS(31)`, K=10/20/30/31 und 32 konstante Läufe. Tatsächlich ausgewertet sind halbe `kappa_AS(31)`, K=20/30 und 16 Läufe; Kapitel 7 beschreibt dies bereits richtig.
- F1 ist im aktuellen `ThesisDemandFamily` nicht implementiert. Die implementierten Familien sind F0/F2/F3/F4. Keine F1-Ergebnisse oder zugesagte F1-Reihe suggerieren.
- F4 bleibt als abgeschlossene Journey-Kontrolle erhalten; bei der neuen Kapazitätssuche darf es ausdrücklich ausgeschlossen sein. Gleich gute beobachtete Ergebnisse nicht ohne Beweis zu allgemeiner All-Stop-Optimalität erklären.
- All-Stop-Kapazitäten überall mit dem Gültigkeitsbereich „regulär, No-Wait, gemeinsame Phase“ beschriften; F0 als Intervall.
- Das vorhandene Kapazitäts-Screening hatte 300-s-Budgets. Spätere 30-min-Diagnosen sind keine uniforme Fortsetzung derselben Kampagne.
- Kein Incumbent/UNKNOWN, bewiesene Unzulässigkeit, Ressourcenabbruch und vollständige Bedienung sauber unterscheiden. Ein Passagieroptimum bei festen Zeiten ist kein Fahrplanoptimum.

Thesisstellen: [Kapitel 4](../../../idp_report/version_2/chapters/04_methodology.tex), [Kapitel 6](../../../idp_report/version_2/chapters/06_evaluation.tex), [Kapitel 7](../../../idp_report/version_2/chapters/07_results.tex). Dieses Dokument ändert die Kapitel noch nicht.

## 9. Begrenztes Restprogramm bis morgen

Vorschlag für eine sequenzielle Kampagne mit **höchstens 6 h 40 min einschließlich Auswertung**. Das ist ein Budgetvorschlag, keine Behauptung über eine bekannte Abgabeuhrzeit. Wenn weniger Zeit bleibt, die optionalen Blöcke von unten streichen. Laufzeitlimits enthalten Aufbau und Prüfung; keine konkurrierenden Solverjobs, bestehende 32-GiB-Grenze beibehalten.

| Priorität | Arbeit | Maximales Budget | Entscheidung danach |
|---|---|---:|---|
| 1 | Ergebnisse/Quellen einfrieren, passende Baselines auf derselben Nachfrage bewerten, Zertifikate und Exporte prüfen | 30 min | Ohne passenden Vertrag keine neue Vergleichszahl |
| 2 | F2: T5 und T6 bei `ceil(1.1*kappa_AS)` = 3.210 / 3.237, K=62 / 75; kleiner Katalog, bestehender No-Wait-Linienpfad, Seeds 0/1/2 | höchstens 6 × 30 min | Initialkandidat und spätere Verbesserung getrennt; vorhandenen identischen Seed-0-Lauf wiederverwenden statt doppelt rechnen |
| 3 | F3: je ein kurzes T5-/T6-Gate mit bestehenden Liniengruppen bei 1,1×Referenz; All-Stop-Rückfall separat neu bewerten | 2 × 10 min | Kein belastbarer Vorteil: negative Ergebnisse sichern und Reihe beenden |
| 4 | Besten F2-Skip-Stop-Start frei mit OD-Inventar-CP-SAT nachoptimieren: einmal W=0, einmal W=120; identische Nachfrage, Kmax und Startbewegung | 2 × 30 min | Nutzen der Nachoptimierung und der zusätzlichen Waitingfreiheit getrennt berichten |
| 5, optional | Eine einzige Sensitivität: entweder zwei kleinere/größere K-Vergleiche am besten Fall **oder** die zwei Journey-Läufe ohne Incumbent mit Warmstart ergänzen | 2 × 30 min | Keine zusätzliche K-/Demand-/Solver-Matrix öffnen |
| 6 | Zertifikate, Tabellen, Methodenscope und Ergebnisbericht abschließen | 50 min | Spätestens danach keine neuen Läufe |

Wenn F2 schon bei der Initialisierung U=0 erreicht, ist die Kapazitätsfrage dieses Punkts beantwortet. Die restliche Zeit nicht automatisch durch immer höhere Nachfrage oder zusätzliche Seeds verbrauchen. Für Journey-Nachoptimierung einen getrennten Auftrag mit bekanntem Start dokumentieren.

Bei kleinerer Flotte empfehle ich als begrenzte Sensitivität zum Beispiel K=56 statt 62 auf T5; eine größere Flotte wäre Kmax=69. Das sind getrennte Verfügbarkeitsfälle. Der Erfolg bei K=69 würde keinen Vorteil bei unverändertem K=62 belegen. Diese Sensitivität kommt erst nach einem gesicherten Hauptvergleich.

Ein zulässiger, unabhängig geprüfter Zeuge oberhalb der regulären All-Stop-Profilgrenze reicht bereits für einen interessanten Thesisbefund. Ein globales Skip-Stop-Optimum oder 1-%-Gap ist dafür nicht erforderlich. Einen heuristischen Lauf ohne globale Schranke lassen wir daher nicht auf einen erfundenen Gap warten.

## 10. Umfang dieses Audits

Geprüft wurden die relevanten Codepfade, Studienpläne, Kapitel 4/6/7, die 64 durch die aktuelle Journey-Queue ausgewählten Ergebnisse, sechs All-Stop-Referenzresultate, ausgewählte Evo-/Greedy-/CP-SAT-Rohresultate und die historischen Methodenbefunde. Drei relevante F2-Checkpoints wurden erneut solverfrei unabhängig validiert; der CP-SAT-Zeuge zusätzlich unter W120.

Keine neue Performancekampagne, kein Solververgleich und kein vollständiger erneuter Regressionstest aller historischen Implementierungen wurden durchgeführt. Historische Familienbewertungen sind als solche gekennzeichnet. Die Empfehlung beruht auf den tatsächlich verfügbaren Zeugen und dem Zeitbudget, nicht auf einer zugesagten Erfolgswahrscheinlichkeit für weitere Suchen.
