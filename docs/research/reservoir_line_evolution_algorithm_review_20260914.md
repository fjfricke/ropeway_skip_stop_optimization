# Veröffentlichte Suchverfahren für die Reservoir-Linienplanung

## 1. Einordnung und Empfehlung

Die stärkste kurzfristige Option ist eine kontrollierte NSGA-II-Erweiterung der vorhandenen Suche: transportstarke, noch kollidierende Fahrpläne erhalten eine eigene Bewertung und können neben bereits zulässigen Plänen überleben. Diese Änderung prüft einen konkreten Engpass der bisherigen Auswahl. Sie ist kein Beleg, dass eine neuere evolutionäre Engine das Seilbahnproblem automatisch besser löst.

Die Literatur legt zugleich eine wichtigere zweite Unterscheidung nahe: **Auswahlverfahren und Fahrplandecoder sind verschiedene Hebel.** Eine bessere Auswahl kann interessante Musterfamilien erhalten; sie erzeugt noch keine passenden Dispatchzeiten. Für den zweiten Hebel ist die Forschung zum No-Wait Job Shop besonders relevant. Für den Wunsch nach möglichst viel fertiger Software ist BRKGA-MP-IPR der interessanteste zusätzliche Rahmen, während C-TAEA eine gut verfügbare Alternative zur Mehrzielauswahl darstellt. Ein HGS-Routingpaket lässt sich dagegen nicht unverändert als Seilbahnsolver verwenden.

Diese Rangfolge ist eine fachliche Transferbewertung, keine gemessene Rangfolge für R0/R2. Die folgenden Prioritäten gelten für den derzeitigen No-Wait-Pilot:

| Priorität | Ansatz | Was er konkret prüfen würde | Einordnung |
|---|---|---|---|
| 1 | NSGA-II mit Transportpotenzial und Konfliktzielen | Ob die bisherige Auswahl produktive, unzulässige Musterfamilien zu früh verliert | Kleiner, gut isolierbarer Versuch; läuft als separate Implementierungsaufgabe |
| 2a | Strukturierter No-Wait-Decoder mit zulässigen Dispatchintervallen | Ob ein Großteil der erfolglosen Vorschläge durch eine geeignetere Zeitdarstellung vermeidbar ist | Stärkster struktureller Ansatzpunkt; eigener problemspezifischer Adapter nötig |
| 2b | C-TAEA aus pymoo | Ob getrennte Konvergenz- und Diversitätsarchive produktive Grenzregionen besser erschließen | Vorhandene Engine; sinnvoll erst mit begründeten Suchzielen |
| 3 | BRKGA-MP-IPR | Ob Inseln, Mehr-Eltern-Kombination und Path-Relinking neue Muster-/Zeitkombinationen erschließen | Veröffentlichter Rahmen mit offiziellem Code; neue Kodierung erforderlich |
| 4 | MAP-Elites / Quality Diversity | Ob dichte Skip-Stop-Familien als Zwischenstufen erhalten werden | Sehr passend zur gewünschten Entwicklungsanalyse; Zulässigkeit muss zusätzlich behandelt werden |
| 5 | Stochastic Ranking / SRES / ISRES | Ob weniger strenge Trennung nach Zulässigkeit hilft | Guter methodischer Kontrollansatz; numerische Standardoperatoren passen schlecht zur variablen Sequenz |
| Zurückstellen | HGS-Neuentwicklung, RL, neue EDAs, weitere Metaheuristiknamen | Würden zusätzlich Repräsentation, Decoder oder Lernumgebung verändern | Hoher Aufwand und derzeit geringe diagnostische Trennschärfe |

Keines dieser Verfahren liefert aus sich heraus eine globale Kapazitätsuntergrenze oder einen Optimalitätsgap. Der ganzzahlige Passagier-IP beweist höchstens die optimale Zuordnung für einen gegebenen Fahrplan. Diese Aussage bleibt von der Suche nach dem Fahrplan getrennt.

## 2. Ausgangslage und tatsächlich belegte Beobachtungen

Der No-Wait-Pilot entscheidet über eine variable Zahl eingesetzter Kabinen, ihre geordnete Folge fester Stationsmasken sowie gemeinsame Phase und zusätzliche Dispatchabstände. Aus diesen Größen folgen vollständige Trajektorien, Ressourcenintervalle und Portereignisse. Die ganzzahlige Passagierzuordnung wird anschließend bei festem Fahrplan optimiert. Diese Trennung ist wesentlich: Die Bewegungsauswertung ist kein erneuter CP-SAT-Timinglauf.

Die historische Fünf-Stationen-Geometrie und der aktuelle Port-/Lebenszyklusvertrag sind von den späteren Thesis-Geometrien zu unterscheiden. Insbesondere dürfen Kapazität, Umlaufzeiten und Referenzzahlen verschiedener Vertragsstände nicht vermischt werden. Für den hier betrachteten R2-Fall werden 3.074 Personen und 14 relevante Stationsmasken verwendet.

Ein bereits dokumentierter, isolierter Vergleich der Elternwahl zeigt Folgendes:

| R2, je 60 Sekunden, Seed 0 | Standardturnier | Zusätzlicher Explorationszweig mit Wahrscheinlichkeit 25 % |
|---|---:|---:|
| Eindeutige Bewertungen | 5.701 | 7.108 |
| Gültige Bewertungen | 1.025 | 899 |
| Tatsächlicher Anteil unzulässiger Eltern | 6,9 % | 30,5 % |
| Beste gültige Bedienung | 2.496 | 2.496 |

Mit zusätzlicher Exploration entstand nach 16,4 Sekunden ein gemischter K7-Plan mit 560 bedienten Personen. Die globale Lösung blieb beim gemeinsamen All-Stop-Startplan. Das belegt, dass die Auswahl die Entwicklung verändert; es belegt noch keine erfolgreiche Überquerung zur dichten Skip-Stop-Flotte. Quelle sind die lokalen Messartefakte und der [Elternwahlbefund](../findings/reservoir_line_parent_selection_20260914.md), nicht eine allgemeine Aussage über evolutionäre Algorithmen.

Die bisherige Implementierung reserviert Plätze für gute gültige Kandidaten, zusätzliche gültige Muster-/Flottensignaturen und unzulässige Kandidaten in K-Bereichen. Die Kennzeichnung einer unterschiedlichen Signatur kann auch durch eine andere Zahl ansonsten identischer All-Stop-Kabinen entstehen. Solche Vielfalt ist formal vorhanden, ohne die gewünschte Vielfalt der Haltemuster zu garantieren. Die betreffenden Stellen liegen in `evolution/search.py`; die gekoppelte Variation liegt in `evolution/operators.py`.

Die daraus folgende Arbeitshypothese lautet: Es fehlt möglicherweise weniger an der Anzahl erzeugter Vorschläge als an einer wirksamen Verbindung zwischen **Transportpotenzial, zeitlicher Reparierbarkeit und Erhaltung unterschiedlicher dichter Musterfamilien**. Diese Hypothese muss durch Verläufe geprüft werden. Ein gleichbleibender globaler Bestwert allein kann sie weder bestätigen noch widerlegen.

## 3. Was eine fertige Engine tatsächlich übernehmen kann

Ein evolutionäres Verfahren besteht hier aus mindestens vier Komponenten:

1. Darstellung der Entscheidungen einschließlich variabler Länge und gekoppelter Dispatchgrenzen.
2. Erzeugung neuer Kandidaten durch Mutation, Kombination und gegebenenfalls Neustarts.
3. Bewertung von Bedienung, Ressourcenverletzung und gegebenenfalls Vielfalt.
4. Eltern- und Überlebensauswahl sowie Verwaltung der Population oder Archive.

Die Verwendung einer Bibliothek standardisiert nicht automatisch alle vier. NSGA-II kann die Auswahl übernehmen und zugleich weiterhin eigene, getestete Sequenzoperatoren verwenden. BRKGA-MP-IPR standardisiert mehr von der Variation, verlangt dafür eine Abbildung seiner festen Zahlenvektoren auf unsere Entscheidungen. Ein fertiger CVRP-Solver bringt einen umfangreichen Decoder und lokale Suche mit, allerdings für eine andere Domäne.

Die sinnvolle Grenze ist deshalb: **veröffentlichte Engine und nachvollziehbarer Domänenadapter**, soweit das möglich ist. Eine neue eigene Auswahlheuristik benötigt mehr Begründung als die Implementierung des physikalisch korrekten Seilbahndecoders. Umgekehrt darf ein schlechter Decoder nicht durch den Namen einer etablierten Engine wissenschaftlich aufgewertet werden.

## 4. Constraint Handling: Die unmittelbar passenden Verfahren

### 4.1 NSGA-II mit Konflikten als Suchzielen

NSGA-II sortiert Kandidaten nach nichtdominierten Fronten und erhält innerhalb einer zu großen Front über Crowding Distance unterschiedliche Zielkombinationen. pymoo stellt das Verfahren einschließlich Eltern- und Überlebensauswahl bereit. Die ursprüngliche Konzeption und die offizielle Implementierung erlauben problemspezifische Variationsoperatoren.[^1]

Die Umwandlung von Constraint-Verletzung in zusätzliche Ziele ist ebenfalls dokumentiert. Sie kann den Verlust von Vielfalt vermindern, aber erhebliche Rechenzeit für niemals zulässige Kandidaten verbrauchen. Ein fast konfliktfreier Punkt bleibt unzulässig; das Verfahren garantiert keine exakte Grenzlösung.[^2]

**Konkrete Übertragung:** Für einen Kandidaten x werden die noch unbediente potenzielle Nachfrage, Zahl der Konflikte und gesamte Überlappungsdauer minimiert. Das Potenzial stammt aus der Passagierzuordnung auf den konkreten Trajektorien unter temporärer Ignorierung der Konflikte zwischen verschiedenen Kabinen. Zeitliche Freigaben, ganzzahlige Personen und individuelle Kabinenkapazitäten bleiben erhalten.

Ein hypothetischer gültiger Plan mit 2.496 Personen und ein Plan mit potenziell 2.900 Personen bei zwei Konflikten dominieren sich dann nicht. Damit besteht ein selektiver Grund, die zweite Familie weiterzuentwickeln. Ein hoher K-Wert ohne entsprechendes zeitlich realisierbares Transportpotenzial ist dagegen nicht schon deshalb interessant.

**Vier wichtige Grenzen:**

- Bei Abbruch eines maximierenden Passagier-IP ist dessen gefundene Zuordnung eine untere Schranke auf sein erreichbares Potenzial, nicht dessen optimistisches Maximum. Eine native obere Schranke kann als optimistische Potenzialschranke geführt werden. Diese beiden Größen dürfen nicht verwechselt werden.
- Gleiche Konfliktzahlen bedeuten nicht gleiche Entfernung zur Zulässigkeit: Zwei Konflikte können durch eine kleine Zeitverschiebung gemeinsam verschwinden oder widersprüchliche Verschiebungen verlangen.
- Drei Ziele können bei Population 32 viele nichtdominierte Kandidaten erzeugen. Populationsgröße und Mehrzielauswahl sind getrennte Änderungen; zuerst sollte der Vergleich die bisherige Größe erhalten.
- Wenn Ressourcenverletzungen zusätzlich wieder als harte feasibility-first-Bedingung an NSGA-II gemeldet werden, kann der beabsichtigte Wettbewerb gerade unterdrückt werden. Strukturell ungültige Genome und bewusst bewertete Ressourcenkollisionen müssen unterschieden werden.

Die Qualität der Mehrziel-Front ist eine Suchdiagnose. Der praktische Bestwert bleibt die separat gesicherte, unabhängig validierte Bedienung.

### 4.2 FI-2Pop

FI-2Pop hält eine zulässige Population zur Verbesserung des eigentlichen Ziels und eine unzulässige Population zur Verringerung der Verletzungen. Der klassische Ansatz lässt Nachkommen beim Wechsel der Zulässigkeit zwischen den Populationen migrieren; die Veröffentlichung untersucht ausdrücklich diese Dynamik und die Herkunft des genetischen Materials guter Lösungen.[^3]

Die Nähe zum aktuellen Problem ist hoch: Gute All-Stop-Pläne müssen nicht sämtliche unzulässigen Skip-Stop-Vorstufen verdrängen. Allerdings bewertet die klassische unzulässige Population gerade nicht deren eigentliches Ziel. Das kann bei uns erneut fast leere, leicht zulässige Flotten begünstigen. Eine zusätzliche Potenzialbewertung wäre bereits eine Variante, kein unverändertes FI-2Pop.

In den überprüften offiziellen pymoo-Verfahrensseiten wurde kein gleichermaßen direkter FI-2Pop-Komplettadapter nachgewiesen. Deshalb ist dies eine wichtige theoretische Referenz, aber momentan weniger attraktiv als die verfügbare NSGA-II- oder C-TAEA-Implementierung. Die bisherige Eigenkonstruktion mit einigen Explorationsplätzen sollte nicht nachträglich als originalgetreue FI-2Pop-Implementierung bezeichnet werden.

### 4.3 C-TAEA

Li, Chen, Fu und Yao schlagen zwei zusammenarbeitende Archive vor: eines unterstützt Konvergenz, das andere Vielfalt auch in unzulässigen Bereichen. Die Elternwahl berücksichtigt den Entwicklungszustand beider Archive. Das Verfahren wurde für constrained multiobjective optimization entwickelt und anhand von Benchmarkproblemen und einer Anwendungsstudie bewertet.[^4]

pymoo enthält eine C-TAEA-Implementierung auf Grundlage der Autorenimplementierung. Sie benötigt Referenzrichtungen und stellt die zwei Archive bereit.[^5] Das macht sie zum interessantesten fertigen Vergleich, wenn NSGA-II ein reiches Potenzial-/Konfliktfeld findet, aber die Umwandlung zu gültigen Plänen schwach bleibt.

Eine unveränderte Anwendung auf das alleinige Kapazitätsziel ist nicht automatisch sinnvoll. Eine mögliche experimentelle Definition wären potenziell unbediente Personen und Konfliktdauer als Suchziele, wobei exakte Konfliktfreiheit weiterhin die Betriebszulässigkeit festlegt. Diese doppelte Rolle muss ausdrücklich dokumentiert werden. Es ist nicht sinnvoll, nur um einen Algorithmus verwenden zu können, ein beliebiges zweites Betriebsziel einzuführen.

### 4.4 Stochastic Ranking, SRES und ISRES

Stochastic Ranking entscheidet stochastisch, ob ein Vergleich stärker dem Zielwert oder der Verletzung folgt. Die ursprüngliche Arbeit zeigt, dass bereits die Rangbildung großen Einfluss haben kann, und behandelt das schwierige Gewichtungsverhältnis zwischen Ziel und Strafe.[^6] SRES und ISRES sind in pymoo vorhanden; ISRES ergänzt die numerische Evolution durch Informationen aus Unterschieden zwischen Individuen.[^7]

Die Idee passt zur zu harten Trennung von All-Stop und kollidierenden Mustern. Die fertigen Standardstrategien sind jedoch für reellwertige Vektoren gedacht. Eine Stationsmaske ist keine natürliche kontinuierliche Zahl: Der Abstand der Masken-IDs sagt nichts über Ähnlichkeit aus. K verändert zudem Zahl und Bedeutung der Dispatchparameter. Deshalb ist ISRES kein überzeugender erster Wechsel des gesamten Suchverfahrens.

Als isolierter Vergleich ist die veröffentlichte Rankingidee interessant. Das Ersetzen einzelner pymoo-Auswahlbausteine würde aber erneut einen eigenen Hybrid erzeugen. Das muss gegen den Wunsch abgewogen werden, gerade solche neuen Hybride zu vermeiden.

### 4.5 Epsilon-Constraint Handling

Ein anfangs gelockerter Zulässigkeitsvergleich, dessen Epsilon im Verlauf sinkt, kann zunächst Bewegung zwischen unzulässigen Regionen zulassen und später die Grenze stärker erzwingen. pymoo dokumentiert einen solchen Mechanismus.[^8] Der Ansatz ist enger und leichter erklärbar als viele adaptive Eigenregeln.

Für das Seilbahnproblem ist die Bedeutung von Epsilon heikel: Ein Tick Überlappung bleibt ein echter Konflikt. Eine vorübergehende Suchlockerung darf nur Rangfolgen betreffen, niemals den Validator oder exportierte Fahrpläne. Bei diskontinuierlichen Konfliktlandschaften kann ein sinkendes Epsilon außerdem die interessanten Familien abschneiden, bevor sie zulässig werden. Der Laufzeitplan wäre eine zusätzliche zu kalibrierende Entscheidung.

## 5. Verfahren mit stärkerer Diversifizierung und anderer Kodierung

### 5.1 BRKGA-MP-IPR

BRKGA-MP-IPR kombiniert biased random keys, mehrere Eltern und implizites Path-Relinking. Die Veröffentlichung bewertet reale kombinatorische Anwendungen einschließlich Scheduling und Netzdesign. Die wesentliche Softwareidee ist eine Trennung zwischen generischer Suche im Zahlenvektor und dem problemspezifischen Decoder.[^9]

Die offizielle C++-Implementierung stellt außerdem mehrere Populationen und Elitenaustausch bereit; Path-Relinking und Diversifikationsfunktionen sind dokumentiert. Eine offizielle Python-Implementierung existiert ebenfalls. Das belegt verfügbare Bausteine, noch keine geprüfte Integration in die lokale Umgebung. Die Python- und C++-Varianten sollten nicht ungeprüft als funktions- und versionsgleich behandelt werden.[^10]

**Passende Kodierungsoption:** Ein festes Chromosom für Kmax enthält Aktivitäts-/Anzahlentscheidungen, Maskenentscheidungen, Reihenfolgeprioritäten und Dispatchparameter. Der Decoder erzeugt daraus eine kanonische aktive Sequenz. Die Bewertung und Deduplizierung richten sich nach dieser Sequenz, nicht nach unterschiedlichen Werten in inaktiven Feldern.

Der entscheidende Nachteil ist Neutralität: Viele Zahlenvektoren können denselben Fahrplan ergeben. Außerdem kann eine kleine Schlüsseländerung die Reihenfolge zweier Kabinen vertauschen und fast den gesamten Fahrplan verändern. Die bessere generische Suche erkauft sich daher keine automatisch bessere Nachbarschaft.

BRKGA wird besonders attraktiv, wenn der Decoder bereits zulässige oder gezielt fast zulässige Dispatchanordnungen erzeugt. Mit unverändertem zufälligem Abstandssampling bleibt dieselbe Feasibility-Barriere bestehen. Path-Relinking zwischen zwei guten Eltern garantiert keine zulässigen Zwischenpläne.

### 5.2 MAP-Elites / Quality Diversity

MAP-Elites speichert gute Lösungen in Zellen eines vorher festgelegten Merkmalsraums. Statt ausschließlich einen globalen Gewinner zu verfolgen, entsteht eine Landkarte verschiedener leistungsfähiger Verhaltensweisen. Das ursprüngliche Paper demonstriert dieses Konzept in mehreren Domänen, ohne einen allgemeinen Vorteil für constrained scheduling zu beweisen.[^11]

pyribs bietet Archive, Emitter und Scheduler sowie Implementierungen mehrerer Quality-Diversity-Verfahren. Diese Komponenten sind öffentlich dokumentiert. Numerische Standardemitter sind nicht automatisch geeignete Operatoren für variable Stationsmaskensequenzen.[^12]

**Sinnvolle Merkmale für uns:** K-Bereich, mittlere Haltzahl pro Umlauf und Anteil der Kapazität auf komplementären OD-Mustern. Ein Archiv nur nach K kann wieder 50 Varianten von All-Stop erhalten. Ein Archiv nach jeder vollständigen Musterfolge wäre dagegen zu groß und zu dünn besetzt.

Quality Diversity passt besonders gut zu der Frage, welche Fahrplanfamilien über die Zeit entdeckt werden. Es schützt beispielsweise einen noch schwächeren K20-Expressplan davor, allein durch einen K38-All-Stop-Plan verdrängt zu werden. Für unzulässige Zwischenstufen ist eine zusätzliche Constraint-Behandlung nötig; ein ausschließlich gültiges Archiv löst den Zugang zu dichten Familien nicht.

### 5.3 HGS und PyVRP

Hybrid Genetic Search für CVRP verbindet genetische Suche mit stark problemspezifischer lokaler Suche und Diversitätsmanagement. Die publizierte Open-Source-Implementierung untersucht ausdrücklich Lösungsentwicklung über Zeit; SWAP* ist ein Beispiel für die Bedeutung der lokalen Routingstruktur.[^13] Der offizielle Code verwaltet zulässige und unzulässige Lösungen sowie adaptive Strafen; Zielanteil und Anpassungsregeln sind konfigurierbar.[^14]

Das ist ein guter Gegenbeleg zur Vorstellung, erfolgreiche Routingalgorithmen bestünden lediglich aus einer stärkeren generischen GA-Engine. Ihre Stärke steckt wesentlich in Decoder, Reparatur und effizienter Auswertung ihrer Nachbarschaften.

PyVRP ist ein nutzbares Routingpaket, aber kein Blackbox-Optimizer für beliebige konfliktbehaftete Kabinentrajektorien.[^15] Seilbahnkabinen teilen zeitabhängige Merge-Ressourcen, fahren wiederholt durch Stationen und führen direkt zugeordnete Passagiere mit. Eine Abbildung auf gewöhnliche Kundenrouten und Fahrzeitmatrizen würde diesen Vertrag verlieren. Eine HGS-Neuentwicklung wäre deshalb derzeit ein größeres Forschungsprojekt, keine einfache Installation eines besseren Solvers.

### 5.4 Weitere fertige Blackbox-Verfahren

Nevergrad bietet Parametrisierungen für kategoriale und numerische Entscheidungen sowie automatische Algorithmuswahl. Seine Dokumentation betont die Rolle der Parametrisierung.[^16] Das macht NGOpt oder eine diskrete Variante zu möglichen Kontrollen, wenn eine feste Vektorkodierung ohnehin entsteht.

Ein weiterer Paketwechsel beseitigt jedoch weder die stark gekoppelten Zeitgrenzen noch die Vielzahl neutraler inaktiver Gene. TPE ist bereits eine Kontrolle im Projekt. CMA-ES, Differential Evolution und numerische Evolution Strategies sind eher für den Teilraum der Dispatchparameter bei festgehaltener aktiver Musterfolge interessant. Dies wäre eine neue Zerlegung und sollte nicht als unveränderte Lösung der Gesamtaufgabe gelten.

Neuronale evolutionäre Transitplanung kombiniert gelernte Veränderungsvorschläge mit evolutionärer Suche und berichtet Vorteile auf Transitnetz-Benchmarks.[^17] Die Arbeit liefert eine langfristige Perspektive auf lernbare Operatoren. Sie liefert weder ein vortrainiertes Modell für unsere physikalischen Merge-Regeln noch einen Grund, vor Abschluss der jetzigen Diagnostik eine RL-Trainingsumgebung aufzubauen.

## 6. Ähnliche Anwendungsgebiete und Grenzen des Transfers

### 6.1 No-Wait Job Shop: die engste Timing-Analogie

Eine Kabinentrajektorie mit festem Muster und fester Rundenzahl kann als Job mit festen relativen Zeitabständen ihrer Ressourcenoperationen aufgefasst werden. Unterschiedliche Kabinen teilen Ressourcen, während innerhalb der Trajektorie kein Waiting erlaubt ist. Das ist näher am No-Wait Job Shop als an einer gewöhnlichen TSP-Routenplanung.

Schon die klassische No-Wait-Flowshop-Aufgabe ist mit dem asymmetrischen Traveling-Salesman-Problem eng verbunden; die Forschung zeigt erhebliche Schwierigkeit trotz fest verbundener Operationen.[^18] Daraus folgt nicht automatisch ein Komplexitätsbeweis für jede konkrete Seilbahninstanz. Es widerlegt aber die allgemeine Vermutung, No-Wait mache freie Reihenfolge und freie Startzeiten grundsätzlich leicht.

Bürgy und Gröflin behandeln die optimale Einfügung eines Jobs in den No-Wait Job Shop mit festen Zeitabständen und möglichen Rüstzeiten. Für diese Teilaufgabe geben sie ein polynomielles Verfahren an und verwenden es in einer Heuristik. Der Beweis betrifft die definierte Einfügeaufgabe, nicht die globale optimale Planung aller Jobs.[^19] Bereits frühere Arbeiten trennen beim No-Wait Job Shop Sequenz und Timetabling in lokalen Suchverfahren.[^20]

**Eigene Ableitung für den bestehenden Decoder:** Bei festem Lebenszyklustemplate ist eine Ressourcennutzung der neuen Kabine `[d+a,d+b)`. Eine bereits platzierte Nutzung ist `[s,e)`. Beide kollidieren genau dann, wenn

\[
s-b < d < e-a.
\]

Für Integer-Ticks ist der verbotene Bereich folglich `[s-b+1,e-a-1]`. Er wird mit dem erlaubten Dispatchfenster geschnitten. Die Vereinigung solcher Bereiche über sämtliche relevanten Ressourcen und bereits platzierten Kabinen liefert die verbotenen Dispatchzeiten dieser einzelnen neuen Trajektorie. Die verbleibenden Intervalle lassen sich ohne Mikrosekundenaufzählung bestimmen.

Damit könnte ein äußerer Schlüssel zunächst ein Muster und dann einen Platz innerhalb der **zulässigen** Dispatchbereiche wählen. Dies ist eine mögliche Kodierungsänderung; der aktuelle Pilot verändert Vorschläge ausdrücklich nicht stillschweigend. Ein neuer Decoder müsste deshalb einen eigenen Modus und eigene Vergleichsidentität der Suchdarstellung erhalten.

**Notwendige Einschränkungen der Ableitung:**

- Die erste vollständige Rückkehr nach der Deadline kann beim Verschieben des Dispatchs die Rundenzahl ändern. Die Rechnung gilt deshalb nur innerhalb eines Dispatchbereichs mit unverändertem Template; alle entsprechenden Bereiche müssen getrennt betrachtet werden.
- Anfangsreservierungen, Zustandskollisionen, sämtliche Portdurchfahrten und Rückkehr werden zusätzlich berücksichtigt. Schutzintervalle müssen bereits die vollständige Geometrie enthalten.
- Wegen Überholungen und wiederholter Ressourcennutzung genügt die Prüfung gegen die unmittelbar vorher dispatchte Kabine nicht. Es werden alle relevanten platzierten Trajektorien benötigt.
- Eine sukzessive Konstruktion kann früh ungünstige Entscheidungen treffen und später keine Lücke mehr finden. Sie ist keine globale Machbarkeitsentscheidung. Fehlende Einfügbarkeit erlaubt weder eine Unzulässigkeitsbehauptung über die Musterkombination noch stilles Entfernen einer Kabine.
- Ein frühester zulässiger Dispatch maximiert nicht notwendig die Passagierbedienung. Freigaben und komplementäre Nachfrage können spätere Lücken besser machen.

Diese Darstellung wäre daher zuerst ein Decoderexperiment unter derselben äußeren Engine. Sie zielt unmittelbar auf die Häufigkeit brauchbarer dichter Vorschläge, statt lediglich den Umgang mit vielen kollidierenden Vorschlägen zu ändern.

### 6.2 Kreisförderer und Sequential Zone Picking

Debold, Gönsch und Dochow untersuchen einen einseitig gerichteten Kreisförderer mit Zonenabzweigungen. Behälter können Stationen umgehen, nach Bedienung im Ausgangspuffer auf eine Merge-Lücke warten und gegebenenfalls rezirkulieren. Ihre Routingverfahren berücksichtigen Arbeitslast und erforderliche Zonenbesuche; der reale Anwendungsfall stammt von HelloFresh.[^21]

Diese Physikanalogie ist sehr eng. Die Optimierungssemantik ist jedoch anders: Artikel eines Auftrags können teils in verschiedenen Zonen gepickt werden, während unsere OD-Passagiere feste Ursprünge und Ziele besitzen. Die Arbeit untersucht Routingregeln mit Simulation und Pufferbetrieb, keine vollständige exakte No-Wait-Seilbahnplanung.

**Wichtige Quellenkorrektur:** `GA` bezeichnet in dieser Arbeit den **Greedy Algorithm**, nicht Genetic Algorithm. Die berichtete Verbesserung gegenüber GA darf nicht als Beleg gegen evolutionäre Suche interpretiert werden. Für uns ist der übertragbare Gedanke die gemeinsame Betrachtung von Zonenbesuchen und Lastverteilung, nicht eine unveränderte Übernahme des Algorithmus.

Van der Gaast et al. zeigen außerdem, dass Merge-Blocking, endliche Puffer und Rezirkulation schon die analytische Durchsatzbewertung eines solchen Systems schwierig machen. Ihr approximatives Warteschlangenmodell dient der Systemauslegung.[^22] Eine solche Durchsatzschätzung könnte langfristig Musterpotenzial bewerten, ist aber kein physikalischer Fahrplannachweis und keine ohne Weiteres gültige globale Schranke.

### 6.3 Paketförderer als Multi-Agent Path Finding

Kato und Okumura veröffentlichen 2026 DOPP für Conveyor Parcel Routing mit zusammenhängender Auftragsankunft. Das Verfahren kombiniert Auftragsreihenfolge, Agentenprioritäten und priorisierte Pfadplanung.[^23]

Die Modellannahmen verhindern eine direkte Übernahme: Agenten dürfen an normalen Knoten warten, tatsächlicher Eintritt kann beliebig nach dem frühesten Eintritt erfolgen, und Wege verwenden diskrete Kapazitätsknoten. Der Vollständigkeitsanspruch ist unter diesen Bedingungen formuliert. Unser enger Dispatchhorizont, No-Wait auf der Strecke, feste Ressourcengeometrie und wiederholte Umläufe fallen nicht darunter. Es wäre irreführend, daraus einen polynomiellen vollständigen Solver für den aktuellen Pilot abzuleiten.

### 6.4 Bahn, Buslinien und Skip-Stop

Die Literatur zur Transitnetz- und Frequenzplanung kombiniert Routenwahl, Flotte und Passagierbewertung schon lange. Ein Alternating-Objective GA behandelt beispielsweise Nutzer- und Betriebskosten sowie unzulässige Netzvorschläge mit spezifischen Verbesserungsverfahren.[^24] Cao und Ceder integrieren Skip-Stop, Fahrplan und Fahrzeugbedarf für einen kreisförmigen Shuttleverkehr.[^25]

Diese Arbeiten unterstützen die konzeptionelle Trennung von Linienentscheidungen und Bewertung. Sie rechtfertigen aber nicht, Straßenfahrzeuge oder Zuglinien ohne Prüfung mit Kabinen auf gemeinsam geschützten Merge-Ressourcen gleichzusetzen. Auch publizierte Verbesserungsprozente sind Ergebnisse ihrer Fälle, keine Prognosen für R2.

Das klassische Bahn-Skip-Stop-Paper von Sogin et al. ist ein weiterer direkter Anwendungsbezug.[^26] Die methodische Frage für einen Transfer bleibt jeweils: Sind Überholungen, Kapazität, Flottengröße und exakte Konflikttests gleich modelliert, oder wird nur eine vorher fahrbare Grundstruktur variiert? Eine hohe Zahl Stationen im Paper bedeutet nicht automatisch einen schwierigeren Timingfall als unsere dichte Ringbelegung.

### 6.5 Neuere Richtungen ohne unmittelbare Freigabe

Ein jüngerer BRKGA/CP-Beitrag zu gekoppelten Aufgaben mit exakten Zeitabständen ist inhaltlich nah am Timingteil, behandelt aber einen anderen Schedulingvertrag.[^27] Ein 2026 vorgestelltes NS-BRKGA verbindet nichtdominierte Sortierung mit BRKGA-MP-IPR.[^28] Beide sind interessante Literaturhinweise; sie sollten angesichts ihres jungen Veröffentlichungsstands und der noch ungeprüften lokalen Softwareintegration nicht vor den kontrollierten, etablierten Varianten priorisiert werden.

## 7. Was die Verlaufsanalyse messen muss

Ein evolutionärer Lauf kann auf mindestens drei verschiedene Arten stehenbleiben. Die Diagnose entscheidet, welcher nächste Versuch sinnvoll ist.

| Beobachtung | Mögliche Erklärung | Sinnvolle nächste Prüfung |
|---|---|---|
| Kaum dichte Musterkombinationen mit hohem Potenzial | Erzeugung oder Potenzialmetrik erreicht die interessanten Familien nicht | K-/Maskenverteilung und relaxed passenger evaluation prüfen |
| Hohe Potenziale überleben, Konflikte bleiben groß | Auswahl funktioniert; Dispatchdarstellung oder Variation kommt nicht zur Zulässigkeit | Zulässige Dispatchintervalle beziehungsweise gezielte Zeitschritte prüfen |
| Konflikte sinken, Potenzial bricht dabei ein | Feasibility wird durch Aufgabe der interessanten Bedienung erreicht | Gemeinsame Entwicklung beider Größen je Abstammung untersuchen |
| Dichte gültige Skip-Stop-Pläne entstehen, Gesamtbestwert steigt noch nicht | Echte Zwischenentwicklung unter einer starken Referenz | Weitere Zeit kann begründet sein, wenn der Trend über Wiederholungen besteht |
| Viel Vielfalt, keine zunehmende gültige Qualität | Archiv bewahrt Unterschiede ohne brauchbare Entwicklung | Archive nicht mit Fortschritt gleichsetzen; Abbruchkriterium prüfen |
| Anzahl Bewertungen steigt, gleiche wenigen Phänotypen | Genotypische Neutralität oder Cacheeffekte | Eindeutige Fahrpläne statt bloßer Vorschlagszahl vergleichen |

Für jeden gespeicherten Kandidaten sind mindestens Musterfolge, K, Dispatchs, Potenzial samt Schrankenstatus, Konfliktzahl, Überlappungsdauer und unabhängige Zulässigkeit erforderlich. Bei gültigen Kandidaten kommen tatsächliche Bedienung und Passagieroptimalität hinzu. Der zeitliche Bezug muss zwischen Erzeugung, Bewertung und späterer Nachbewertung unterscheiden.

Hilfreiche Kurven sind:

- beste gültige Bedienung über Wandzeit, getrennt nach All-Stop und mindestens einer Skip-Stop-Kabine;
- beste gültige Bedienung je K-Bereich und Haltzahldichte;
- kleinste Konfliktverletzung unter Kandidaten oberhalb fester Potenzialschwellen;
- Zahl tatsächlich überlebender Musterfamilien, nicht nur erzeugter Vorschläge;
- Anteil bewerteter Kandidaten mit offener Passagieroptimierung und dafür verbrauchte Zeit;
- Abstammung ausgewählter dichten Familien: Werden sie repariert, verworfen oder immer neu zufällig gefunden?

Hypervolumen der Suchziele kann ergänzend berichtet werden. Es ersetzt keine dieser fachlichen Größen, denn eine bessere Konflikt-/Potenzialfront kann vollständig unzulässig bleiben. K0 und kleine, fast leere Flotten müssen als Kontrollen erhalten bleiben, dürfen aber nicht den Eindruck erfolgreicher Kapazitätsentwicklung erzeugen.

## 8. Begrenzter Testpfad nach dem NSGA-II-Start

### Schritt A: Auswahlwirkung isolieren

NSGA-II und bisheriger GA erhalten denselben Decoder, dieselben Muster, dieselben Variationsprofile und Referenzinformationen. Zunächst bleibt die Populationsgröße gleich. Es werden Wandzeit und Zahl tatsächlicher Auswertungen dokumentiert, weil die neue Potenzialbewertung teurer sein kann.

Der wichtigste frühe Befund ist, ob produktive dichte Skip-Stop-Familien erhalten bleiben und deren Konflikte sinken. Der gemeinsame All-Stop-Seed bleibt im Hauptvergleich sinnvoll: Er ist eine legitime verfügbare Lösung und schafft einen klaren Referenzwert. Ein unseeded Lauf ist eine gesonderte Diagnostik zur Initialisierungsabhängigkeit.

### Schritt B: Engpassabhängige Fortsetzung

Wenn NSGA-II viel hohes Potenzial mit stabilen Konflikten zeigt, sollte zuerst ein Decoderexperiment folgen. Wenn dagegen geeignete Familien ständig verschwinden, ist C-TAEA oder ein klar definierter Quality-Diversity-Vergleich naheliegender. Wenn die Vektorkodierung durch einen geeigneten Decoder tragfähig wird, ist BRKGA-MP-IPR der nächste vollständige alternative Rahmen.

Diese Reihenfolge vermeidet, dass ein neuer Algorithmus zugleich neue Kodierung, andere Population, mehr Bewertungszeit und neue Startpläne erhält. Ein solcher Vergleich könnte bei Erfolg nicht sagen, welcher Baustein geholfen hat.

### Schritt C: Kleine Pflichtprüfungen für einen Dispatchintervall-Decoder

Eine kleine vollständige Enumeration muss die berechneten zulässigen Dispatchintervalle reproduzieren. Sie umfasst Schutzgrenzen mit erlaubter Berührung, einen Tick Überlappung, mehrere spätere Ressourcennutzungen derselben Kabine, Portdurchfahrt, Rückkehr und einen Lebenszykluswechsel. Ein bewusstes Beispiel muss zeigen, warum nur der unmittelbare Dispatchnachbar nicht genügt.

Zusätzlich wird ein Fall benötigt, in dem die früheste Einfügung späteres Einfügen blockiert, obwohl eine gemeinsame Lösung existiert. Der Decoder muss diesen Fall als eigene Konstruktionsentscheidung behandeln und darf keine globale Unzulässigkeit melden. Erst nach diesen Prüfungen wäre eine dichte R2-Suche sinnvoll.

### Schritt D: Fortsetzungskriterien

Ein längerer Lauf ist begründet, wenn nach dem frühen Einpendeln mindestens eine fachliche Größe weiter vorankommt: größere gültige Skip-Stop-Flotten, bessere Bedienung derselben Familie oder sinkende Konflikte bei erhaltenem hohem Potenzial. Ein einzelner spätester Zufallsfund ist schwächere Evidenz als wiederholter Fortschritt über mehrere Zeitabschnitte und Seeds.

Eine kurzfristige erfolgreiche Methodenentwicklung verlangt nicht sofort das Übertreffen von All-Stop. Für die Thesis-Kapazitätsaussage bleibt letztlich aber eine gültige Bedienungsverbesserung beziehungsweise ein vollständig bedienbarer höherer Nachfragepunkt erforderlich. Suchdiversität allein beantwortet diese Forschungsfrage nicht.

## 9. Quellenstand und lokale Nachvollziehbarkeit

Die Literatur und die verlinkten offiziellen Softwareseiten wurden für diesen Befund am 14. September 2026 geprüft. Verfügbar bedeutet öffentlich dokumentiert beziehungsweise Quellcode vorhanden; ein lokaler Kompatibilitätstest oder eine Installation aller Pakete wurde nicht durchgeführt. Die aktuell dargestellte pymoo-Dokumentation trägt Version 0.6.2; das Projekt verwendet laut Implementierungsstand die fixierte Version 0.6.1.6. Vor Nutzung eines weiteren Verfahrens ist dessen API in der tatsächlich installierten Version zu prüfen.

Die Ausgangscodeprüfung dieses Berichts erfolgte vor der parallel entstehenden NSGA-II-Erweiterung. Git-HEAD war `1a8758e5372c56fbf1c9eccc298de2562478c4fb`; wegen laufender Änderungen ist HEAD allein keine vollständige Quellenidentität. Gelesene Dateihashes:

| Datei unter `src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_lines/evolution/` | SHA-256 |
|---|---|
| `search.py` | `b25abdaf66be8f8ab0930ddc84cf84fae30554f2e0ddfd3c8ac0254fef3c9d7a` |
| `operators.py` | `3b7e1596380fc8f40e579b2faa90899dacbf617e0f8b89e584dc6acff25bd824` |
| `decoder.py` | `a3fbfedcde4e75fcc9eb9e9c386c458e2da4c10bfeccfdb151aeed91fdc2d50e` |

Lokale Ausgangsdokumente sind der [Implementierungsplan](../plans/reservoir_line_evolution_no_wait.md), der [bisherige Pilotbefund](../findings/reservoir_line_evolution_no_wait_results.md) und der [isolierte Elternwahlvergleich](../findings/reservoir_line_parent_selection_20260914.md). Ergebnisse neuer NSGA-II-Läufe gehören in einen eigenen Befund und werden durch diesen Forschungsbericht nicht vorweggenommen.

## Quellen

[^1]: pymoo / Julian Blank. [NSGA-II: Non-dominated Sorting Genetic Algorithm](https://pymoo.org/algorithms/moo/nsga2.html). Offizielle Implementierungsdokumentation, geprüft 2026-09-14; basiert auf Deb et al., 2002. Verwendet für Auswahlprinzip und Softwareverfügbarkeit.
[^2]: pymoo. [Constraint Violation as Objective](https://pymoo.org/constraints/as_obj.html). Offizielle Dokumentation, geprüft 2026-09-14. Verwendet für Constraint-Ziel-Umwandlung und ihre Grenzen.
[^3]: Kimbrough, S. O., Koehler, G. J., Lu, M., Wood, D. H. [On a Feasible–Infeasible Two-Population (FI-2Pop) genetic algorithm for constrained optimization: Distance tracing and no free lunch](https://doi.org/10.1016/j.ejor.2007.06.028). European Journal of Operational Research 190(2), 310–327, 2008. [Gelesene Autorenfassung](https://www.eecis.udel.edu/~wood/papers/JointPaper-FI-2PopGA.pdf).
[^4]: Li, K., Chen, R., Fu, G., Yao, X. [Two-Archive Evolutionary Algorithm for Constrained Multiobjective Optimization](https://doi.org/10.1109/TEVC.2018.2855411). IEEE Transactions on Evolutionary Computation 23(2), 303–315, 2019. [Autorenpreprint](https://arxiv.org/abs/1711.07907).
[^5]: pymoo. [C-TAEA](https://pymoo.org/algorithms/moo/ctaea.html). Offizielle Implementierungsdokumentation, geprüft 2026-09-14.
[^6]: Runarsson, T. P., Yao, X. [Stochastic Ranking for Constrained Evolutionary Optimization](https://doi.org/10.1109/4235.873238). IEEE Transactions on Evolutionary Computation 4(3), 284–294, 2000. [Gelesenes Paper](https://faculty.csu.edu.cn/_tsf/00/65/AriuAjbIFJzy.pdf).
[^7]: pymoo. [SRES](https://pymoo.org/algorithms/soo/sres.html) und [ISRES](https://pymoo.org/algorithms/soo/isres.html). Offizielle Verfahrensdokumentation, geprüft 2026-09-14.
[^8]: pymoo. [Epsilon-Constraint Handling](https://pymoo.org/constraints/eps.html). Offizielle Dokumentation, geprüft 2026-09-14.
[^9]: Andrade, C. E., Toso, R. F., Gonçalves, J. F., Resende, M. G. C. [The Multi-Parent Biased Random-Key Genetic Algorithm with Implicit Path-Relinking and its real-world applications](https://doi.org/10.1016/j.ejor.2019.11.037). European Journal of Operational Research 289(1), 17–30, 2021. [Autorenfassung](https://mauricio.resende.info/doc/brkga-pr.pdf).
[^10]: Andrade, C. E. et al. Offizielle [C++-Implementierung](https://github.com/ceandrade/brkga_mp_ipr_cpp), [C++-API](https://ceandrade.github.io/brkga_mp_ipr_cpp/class_BRKGA_BRKGA_MP_IPR.html) und [Python-Implementierung](https://github.com/ceandrade/brkga_mp_ipr_python). Geprüft 2026-09-14.
[^11]: Mouret, J.-B., Clune, J. [Illuminating search spaces by mapping elites](https://arxiv.org/abs/1504.04909). 2015. Verwendet für das Quality-Diversity-Grundprinzip.
[^12]: pyribs. [Projektseite](https://pyribs.org/), [GridArchive](https://docs.pyribs.org/en/stable/api/ribs.archives.GridArchive.html), [Emitter-API](https://docs.pyribs.org/en/stable/api/ribs.emitters.html). Offizielle Dokumentation, geprüft 2026-09-14.
[^13]: Vidal, T. [Hybrid genetic search for the CVRP: Open-source implementation and SWAP* neighborhood](https://doi.org/10.1016/j.cor.2021.105643). Computers & Operations Research 140, 105643, 2022. [Autorenpreprint](https://arxiv.org/abs/2012.10384).
[^14]: Vidal, T. [HGS-CVRP](https://github.com/vidalt/HGS-CVRP). Offizielle Referenzimplementierung und dokumentierte Parameter, geprüft 2026-09-14.
[^15]: PyVRP. [Offizielle Dokumentation](https://pyvrp.org/). Geprüft 2026-09-14. Verwendet zur Abgrenzung eines Routingpakets von einem generischen Seilbahnoptimizer.
[^16]: Nevergrad. [Parametrizing your optimization](https://facebookresearch.github.io/nevergrad/parametrization.html), [offizielles Repository](https://github.com/facebookresearch/nevergrad). Geprüft 2026-09-14.
[^17]: [A Neural-Evolutionary Algorithm for Autonomous Transit Network Design](https://arxiv.org/abs/2403.07917). Autorenpreprint, 2024. Verwendet als langfristiger Forschungsbezug, nicht als lokaler Performancebeleg.
[^18]: Mucha, M., Sviridenko, M. [No-Wait Flowshop Scheduling Is as Hard as Asymmetric Traveling Salesman Problem](https://doi.org/10.1287/moor.2015.0725). Mathematics of Operations Research 41(1), 247–254, 2016. [Autorenpreprint](https://arxiv.org/abs/1302.2551).
[^19]: Bürgy, R., Gröflin, H. [Optimal Job Insertion in the No-Wait Job Shop](https://doi.org/10.1007/s10878-012-9466-y). Journal of Combinatorial Optimization; 2012 angenommen. [Gelesene Autorenfassung](https://reinhardbuergy.ch/research/pdf/buergy_groeflin12_oji_nwjs_preprint.pdf), insbesondere Modell und Einfügeproblem.
[^20]: [Approximative procedures for no-wait job shop scheduling](https://doi.org/10.1016/S0167-6377(03)00005-1). Operations Research Letters 31(4), 308–318, 2003. Verwendet für Sequenz-/Timingzerlegung; Verlagsabstract gelesen.
[^21]: Debold, S., Gönsch, J., Dochow, R. [Order routing in sequential zone picking systems](https://doi.org/10.1007/s00291-025-00833-y). OR Spectrum, 2025. Volltext, insbesondere Abschnitte 2, 5, 6.2 und 6.4.
[^22]: Van der Gaast, J. P., de Koster, R., Adan, I. J. B. F., Resing, J. A. C. [Conveyor merges in zone picking systems: A tractable and accurate approximate model](https://doi.org/10.1287/trsc.2017.0782). Transportation Science, 2018. [Institutionelles Repository](https://repub.eur.nl/pub/114014).
[^23]: Kato, T., Okumura, K. [Conveyor Parcel Routing with Order-Contiguous Arrivals](https://arxiv.org/abs/2605.13035). Preprint, 2026. [Gelesener Volltext](https://arxiv.org/html/2605.13035v1), insbesondere Abschnitt 3.
[^24]: [Efficient transit network design and frequencies setting multi-objective optimization by alternating objective genetic algorithm](https://doi.org/10.1016/j.trb.2015.06.014). Transportation Research Part B 81(2), 355–376, 2015. Verlagsbeschreibung und Abstract gelesen.
[^25]: Cao, Z., Ceder, A. [Autonomous shuttle bus service timetabling and vehicle scheduling using skip-stop tactic](https://doi.org/10.1016/j.trc.2019.03.018). Transportation Research Part C, 2019. Verlagsbeschreibung und Abstract gelesen.
[^26]: Sogin et al. [Optimizing Skip Stop Service in Passenger Rail Transportation](https://railtec.illinois.edu/wp/wp-content/uploads/2019/01/Sogin%20et%20al%202012b.pdf). 2012, Autoren-/Institutsfassung.
[^27]: [Constraint programming model and biased random-key genetic algorithm for the single-machine coupled task scheduling problem with exact delays to minimize the makespan](https://arxiv.org/abs/2512.23150). Autorenpreprint, 2025. Nur als neuer Forschungsbezug eingeordnet.
[^28]: Mendes, L. H. P., Usberti, F., San Felice, M. C., Andrade, C. E. [NS-BRKGA: Non-dominated Sorting Biased Random-Key Genetic Algorithm](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6225221). Working paper, 2026. Abstract geprüft; keine lokale Code-/Performanceverifikation.
