# Räumliche und zeitliche Nachfrage für die Seilbahnexperimente

## Ergebnis und Empfehlung

Die Thesis sollte eine kontrollierte, synthetische Potenzialstudie mit nachvollziehbaren Nachfragefunktionen durchführen. Dafür eignen sich eine diffuse Referenz, komplementäre OD-Märkte, ein gemeinsamer Hub sowie kurze und längere Fahrten. Zeitlich sollten gleichmäßiger Zufluss, ein breiter Peak und begründete Zuflusspulse getrennt untersucht werden. Diese Auswahl ist durch die Forschung zu Seilbahnen, Metrofahrplänen und Limited-Stop-Bussen motiviert. Die konkreten Stationspaare, Gewichte und Peakstärken sind eigene Versuchsparameter und keine empirisch kalibrierten Nachfrageprognosen.

Die vereinbarte Kapazitätsfrage bleibt erhalten: Wie viele Personen eines festgelegten, verschachtelten Nachfrageprofils können bei Freigaben während 45 Minuten bis Minute 60 vollständig ankommen? Das Ergebnis ist eine **vollständig bedienbare Profilnachfrage unter einem endlichen Zeitvertrag**. Eine dauerhaft tragbare Stundenleistung wird damit allein nicht bewiesen.

Vor einer großen Versuchsmatrix sind fünf Korrekturen wichtig:

1. Eine konstante Ankunftsrate darf nicht unbemerkt durch gleichzeitige Minuten-Batches ersetzt werden.
2. Kurze Wege sind eine Reisezeitkontrolle, aber kein sicherer Negativfall für den Kapazitätsgewinn.
3. Komplementäre OD-Märkte brauchen Kontrollen mit Hintergrundnachfrage und gemeinsamen Stationsengpässen.
4. Die All-Stop-Referenz ist exakt innerhalb ihres regelmäßigen, phasenoptimierten No-Wait-Vertrags; sie umfasst nicht sämtliche denkbaren All-Stop-Betriebsweisen.
5. Optimale ganzzahlige Passagierzuweisung misst ein koordiniertes Potenzial. Selbstständiges Einsteigen und unbekannte zukünftige Nachfrage sind zusätzliche Modellannahmen.

Dieser Bericht enthält **Empfehlungen zur Freigabe**, keine pauschal beschlossenen Einstellungen. Nach gesonderter Vorstellung im Chat wurden am 14.09.2026 die räumlichen Funktionen F0–F4, die 80/20-Hintergrundvariante sowie P0/P1/P4 mit ihren angegebenen Hauptparametern bestätigt. Verbindlich ist diese abgegrenzte Freigabe in §§ 12–13 des [Entscheidungsregisters](../thesis/experiment_definition_register_20260913.md). Weitere Empfehlungen dieses Berichts, insbesondere Ankunftsaggregation, Zusatztests und geänderte Auswertungsregeln, bleiben Vorschläge. Der Bericht ersetzt weder historische Instanzen noch Solverergebnisse.

## 1. Forschungsbasis und Übertragbarkeit

In den einschlägigen Arbeiten gibt es drei verschiedene Formen der Nachfragebeschreibung: gemessene Nachfrage einer konkreten Anwendung, systematisch variierte synthetische OD-Strukturen und stochastische Ankunftsprozesse. Für eine neuartige Stationsarchitektur ohne örtliche Fahrgastdaten ist die zweite Form die belastbare Hauptmethode; die dritte ergänzt Robustheit. Technische Realwerte allein machen eine synthetische OD-Matrix noch nicht empirisch.

| Primärquelle | Tatsächlich untersuchte Nachfrage oder Methodik | Bedeutung für die Thesis | Grenze der Übertragung |
|---|---|---|---|
| Haimerl et al., 2022, urbane Seilbahn Regensburg [^1] | Lokale Buszählungen als Mengengrundlage; stationsbezogene Tagesprofile in 15-Minuten-Schritten, anhand des Umfelds ausgestaltet; empirische Zielwahrscheinlichkeiten. Nachfrage wird zur Grenzsuche skaliert, mit einer gewählten maximalen Wartezeit von acht Minuten. | Besonders passende Begründung für stationenspezifische Profile, OD-Matrizen, Mengenskalierung und Wartezeitkennzahlen. | Keine Skip-Stop-Optimierung unserer Architektur. Weder 15-Minuten-Batches noch acht Minuten Wartezeit sind allgemeine Seilbahnstandards. |
| Mei, Gu, Cassidy und Fan, 2021 [^2] | Räumliche Herkunftsdichte und Fahrtlängenverteilung werden getrennt variiert. Im Versuch: abgeschnittene Normalverteilung der Ursprünge und gleichverteilte Fahrtlängen mit variierenden Parametern. | Herkunftskonzentration und Fahrtlänge als getrennte Faktoren behandeln. | Kontinuierliche Näherung mit anderen Linien-, Zugangs- und Umstiegsannahmen; keine übertragbare Gewinngarantie. |
| Larrain und Muñoz, 2016 [^3] | Fast 1.000 synthetische Buskorridorfälle. Nutzen hängt unter anderem mit OD-Konzentration, kritischer Abschnittslast, Haltedauer und Kapazität zusammen. | Nicht allein „express versus lokal“ testen, sondern auch Stations- und Abschnittskonzentration messen. | Zugänglich waren Verlagsabstract und bibliografische Angaben; keine unbekannten Tabellenparameter übernommen. |
| Sun et al., 2014 [^4] | Zeitabhängige Metronachfrage aus AFC-Daten; mögliche Zeitintervalle von 30 Sekunden, einer oder zwei Minuten. Innerhalb der Intervalle wird ausdrücklich gleichmäßige Ankunft angenommen. | Datenintervall, individuelle Ankunft und Fahrzeugzeitdiskretisierung unterscheiden. | Identische Zugtrajektorien und weitere Annahmen vereinfachen deren Modell; diese Vereinfachung gilt nicht für unsere wechselnden Muster. |
| Kieu und Cai, 2018 [^5] | Deterministisch gleichmäßige und Poisson-Ankünfte werden eingeordnet; ein zeitlich variierender kollektiver NHPP wird an Stationsdaten untersucht. | Konstante Rate als Kontrolle, zeitabhängige Intensität und zufällige Realisierungen als Erweiterung. | Eine eingefrorene Zufallsrealisierung ergibt noch keine stochastische Optimierung oder Zuverlässigkeitsgarantie. |
| Blanco et al., veröffentlichte Fassung 2020, Autorenvorabfassung 2019 [^6] | Kumulierte Nachfrage mit kontinuierlichem Zufluss und Sprüngen durch externe Ereignisse beziehungsweise Umsteiger. | Glatter Zufluss und echte Feeder-/Ereignispulse sind unterschiedliche Modellbestandteile. | Die Vorabfassung und die veröffentlichte Formulierung sind nicht versionsgleich; übernommen wird hier nur der Nachfragegedanke. |
| Niu, Zhou und Gao, 2015 [^7] | Zeitabhängige Nachfrage und Skip-Stop-Fahrpläne mit fahrgastbezogener Wartezeitbewertung. | Zeitliche Lage von Nachfrage und Haltemustern gehört in dieselbe Versuchsspezifikation. | Verlagsvorschau; daraus werden keine konkreten empfohlenen Bucketbreiten abgeleitet. |
| Farrando et al., 2024 [^8] | Zwei Skip-Stop-Dienste, nachfrageabhängige Haltezeiten und zwei Nachfrageprofile. Längere Fahrten können trotz zusätzlicher Wartezeit profitieren, kurze können verlieren. | Reisezeit in Warte- und Fahrzeugzeit zerlegen. | Vorgegebene Dienststruktur, feste Flotte und nachfrageabhängige Haltezeiten unterscheiden sich von unserem Modell. |
| Singh et al., 2021 [^9] | Londoner AFC-/AVL-Daten zeigen eine frequenzabhängige Veränderung des Ankunftsverhaltens; Übergang bei den untersuchten Linien bereits bei etwa zwei bis drei Minuten. | Zufällige, fahrplanunabhängige Ankunft ist eine Annahme, kein universelles Fahrgastgesetz. | Kein allgemeiner Grenzwert für Seilbahnen. Relevant ist hier auch die Frequenz eines tatsächlich passenden Dienstes. |
| Suman, Larrain und Muñoz, 2021 [^10] | Untersuchung der Differenz zwischen einer gesamtkostenorientierten, kapazitierten Zuweisung und verhaltensbezogener Passagierzuweisung. | Unsere optimale Zuordnung als koordiniertes Potenzial kenntlich machen. | Primärvorschau/indizierter Autoren-PDF-Auszug; keine numerischen Effekte aus nicht eingesehenen Ergebnistabellen übernommen. |
| Martinod et al., 2023 [^11] | Stochastische Ereignissimulation urbaner Seilbahnen im intermodalen Netz, Warteschlangen und Betriebspolitiken über einen Arbeitstag. | Hub-/Feederfälle und eine spätere feste-Fahrplan-Simulation sind sachlich passende Ergänzungen. | Keine Gleichsetzung mit einem exakten Kapazitätsbeweis. |
| TCQSM, vierte Ausgabe 2026 [^12] | Aktuelle Zusammenstellung von Kapazitäts- und Qualitätsmethoden. Die offizielle Beschreibung legt ausdrücklich keine allgemein erwünschten Qualitäts- oder Kapazitätsniveaus fest. | Gewählte Servicegrenzen müssen begründet werden; sie folgen nicht automatisch aus einem Handbuch. | Verifiziert sind Ausgabe, Inhaltsverzeichnis und offizielle Beschreibung. Die einzelnen Kapazitätskapitel wurden nicht zuverlässig als Volltext erschlossen. |

Die ersten, zweiten, vierten, fünften und sechsten Quellen sind anhand zugänglicher Volltexte geprüft. Die übrigen Zugriffsgrenzen stehen ausdrücklich in der Tabelle und im Quellenverzeichnis. Dies ist eine fokussierte Literaturauswertung, keine als vollständig behauptete systematische Review mit PRISMA-Auswahl.

## 2. Was üblich ist und was eine eigene Festlegung bleibt

Die Quellen rechtfertigen eine OD-Matrix mit zeitlicher Struktur, getrennte kurze/lange Wege, heterogene Ursprünge, Spitzen und besondere Zuflüsse. Sie rechtfertigen auch, dieselbe Profilform bei unterschiedlichen Gesamtmengen zu untersuchen. Ein einzelner besonders günstiger OD-Fall reicht dagegen nicht zur Verallgemeinerung auf urbane Seilbahnen.

Nicht aus den Quellen ableitbar sind insbesondere:

- genau 45 Minuten Freigabe plus 15 Minuten Abschluss;
- genau 60 Sekunden als optimale Nachfrageaggregation;
- ein Peak mit Verhältnis 3:1 zwischen Spitze und Rand;
- genau zwei disjunkte OD-Märkte mit je 50 Prozent;
- ein Flottenmaximum von 1,25 mal All-Stop;
- eine universelle maximal akzeptable Passagierwartezeit.

Solche Werte dürfen sinnvoll gewählt werden. Wissenschaftlich sauber werden sie durch eine offen benannte Funktion, eine mechanistische Begründung, eine begrenzte Sensitivität und eine vor den Hauptläufen festgelegte Auswertung. Die Literatur motiviert die Faktoren; eine Kalibrierung auf ein reales Netz benötigt dessen Daten.

## 3. Ein gemeinsamer Nachfragevertrag

### 3.1 Makroskopisches Profil

Für jeden zulässigen gerichteten OD-Markt wird ein Anteil \(w_{od}\) und eine zeitliche Dichte \(p_{od}(t)\) festgelegt:

\[
w_{od}\ge0,\quad\sum_{od}w_{od}=1,\qquad
\int_0^{T_D}p_{od}(t)\,dt=1,
\]

\[
\lambda_{od}(t;N)=Nw_{od}p_{od}(t),\qquad T_D=45\text{ min}.
\]

Die Dichte beschreibt die gewünschte Verteilung. Die konkrete Optimierungsinstanz enthält weiterhin ganzzahlige Personen beziehungsweise Gruppen mit exakten Freigabezeiten. Sie enthält keine fraktionalen Fahrgäste.

Im Hauptvergleich ist \(p_{od}=p\) für alle aktiven ODs. Dadurch wird zunächst nur die räumliche Struktur verändert. OD-spezifische Zeitverschiebungen bilden eine eigene Sensitivität; sie dürfen nicht versehentlich durch verschiedene Erzeugungsregeln entstehen.

### 3.2 Gerichtete Topologien und Routenwahl

T5R und T6R beschreiben eine Richtung eines bidirektional gedachten Rings. Die Zulässigkeit einer Richtung wird aus einem **vorab festgelegten Referenz-Reisekriterium** abgeleitet. Bei gleichen Stationsabständen und gleicher Kinematik kann dies der kürzere Weg sein. Bei ungleichen Abständen genügt die Zahl der Stationen nicht.

Empfehlung: Aus der vollständigen OD-Matrix beide Referenzrichtungen bewerten, Gleichstände hälftig teilen und danach die gewählte Richtungsinstanz normieren. Die Zuordnung bleibt für All-Stop und Skip-Stop gleich. Endogene Routenwahl aufgrund des optimierten Skip-Stop-Fahrplans gehört nicht in diesen Vergleich.

Ein wichtiger Unterschied entsteht beim Sechserring: Bei ursprünglich gleichgewichteten geordneten ODs hat eine gerichtete Ein- oder Zwei-Abschnittsverbindung Rohgewicht 1, eine diametrale Verbindung Rohgewicht 1/2. Die normierten Fahrtlängenanteile sind dann 40/40/20 Prozent. Eine direkte Gleichverteilung über alle gerichteten Ein-, Zwei- und Drei-Abschnittsverbindungen ergäbe dagegen je ein Drittel. Beides ist konstruierbar, aber es sind verschiedene Nachfragefälle.

Für T5R ergeben sich unter denselben Annahmen je 50 Prozent Ein- und Zwei-Abschnittswege. Die früheren drei- und vierabschnittigen Expressfahrten des rein gerichteten T5-Legacy-Falls sind deshalb keine passende Hauptnachfrage für das neue T5R.

Bei ungleichmäßigen Geometrien muss zusätzlich festgelegt werden, ob dieselben ODs als kontrollierte Nachfrage erhalten bleiben oder nach dem neuen Referenzweg anders auf Richtungen verteilt werden. Letzteres ist ein kombinierter Geometrie-/Routenwahleffekt und muss so ausgewiesen werden.

### 3.3 Verschachtelte Integernachfrage

Die Folge \(D(1),D(2),\ldots\) muss Personen ausschließlich hinzufügen. Eine Person behält OD, Freigabezeit und Identität. Der vorhandene gewichtete Defizitausgleich für feste Nachfragegruppen ist hierfür eine passende Grundlage.

Bei Verteilung innerhalb eines Zeitintervalls muss auch die **individuelle** Freigabe stabil bleiben. Für jede OD-Zeit-Zelle wird eine feste Folge von Positionen im Intervall gespeichert; die nächste dieser Zelle zugewiesene Person erhält die nächste Position. Eine reproduzierbare Zufallsfolge oder deterministische verteilte Folge ist möglich. Das Verfahren, seine Parameter und die tatsächlich erzeugten Listen werden eingefroren.

Nicht geeignet ist, bei jeder neuen Gesamtmenge sämtliche Personen erneut gleichmäßig als \((j-1/2)/n\) über das Intervall zu verteilen. Damit verschieben sich alte Freigaben und die für Kapazitätsbracketing benötigte Verschachtelung geht verloren. Ebenso darf eine unabhängige Neuauslosung der gesamten Nachfrage nicht bei jedem N stattfinden.

## 4. Räumliche Versuchsfamilien

Die folgende Auswahl umfasst einen neutralen Vergleich und unterscheidbare Mechanismen. Die IDs erhalten nach Freigabe einen Versionszusatz; historische F-IDs bleiben reproduzierbar.

| Familie | Konkrete Empfehlung | Zu prüfender Mechanismus | Priorität |
|---|---|---|---|
| F0 diffus | Gleichgewichtete vollständige ODs, dann Referenzrichtungszuordnung und Normierung wie oben. | Viele Märkte teilen Flotte und Halte. Spezialisierung ist weniger offensichtlich. | Beide Forschungsfragen. |
| F1 Hub | Alle zulässigen Ursprünge zu einem festen Hub, gleiches Gewicht je Ursprung; Gegenrichtung als gesonderte Variante. Auf der Linie zuerst Terminalhub, später ein innerer Hub. | Ein gemeinsamer verpflichtender Halt kann den Stationsengpass erhalten. | Kapazitätskontrolle. |
| F2 komplementär | Bei gleichmäßigen T5R/T6R: S1→S3 und S2→S4 je 1/2. Auf T6L bei beidseitiger Nachfrage zusätzlich die Rückrichtungen, alle vier je 1/4. | Verschiedene Linien können unterschiedliche Stationsressourcen nutzen. | Positiver Kapazitäts-Mechanismusfall. |
| F2-background | \(0{,}8F2+0{,}2F0\), nach Normierung der Komponenten. | Bleibt der Vorteil bei weiteren ODs bestehen? | Erste Robustheitsprüfung eines F2-Erfolgs. |
| F3 längere Wege | Symmetrischer T5R: zwei Abschnitte; T6R: drei Abschnitte mit korrekter Richtungsteilung. T6L: vier oder fünf Abschnitte. Gleichgewichte auf den jeweils definierten vollständigen ODs. | Einsparung von Zwischenhalten gegenüber zusätzlichem Warten. | Reisezeit. |
| F4 lokal | Nur benachbarte Stationen, symmetrisch gewichtet und der gewählten Richtung zugeordnet. | Keine überspringbaren Zwischenhalte während einer direkten Ein-Abschnittsreise; dafür schnelle Wiederverwendung von Sitzplätzen. | Reisezeitkontrolle, Kapazitätsdiagnostik. |
| F5 gemischt | Nur dort zusätzlich, wo \(0{,}5F3+0{,}5F4\) tatsächlich von F0 abweicht. | Gleichzeitige lokale und längere Märkte. | Nachrangig. |

**F2 ist bewusst konstruiert.** Es ist zulässig, damit den Nutzen einer Architektur zu demonstrieren. Die Aussage lautet dann „unter dieser komplementären Nachfrage“, nicht „bei typischer Stadtnachfrage“. Die 80/20-Mischung ist eine eigene erste Sensitivität, kein Literaturstandard. Zusätzlich wird F2 einmal relativ zum Reservoirport rotiert, bei unverändertem Gesamtgewicht und unveränderten Weglängen. So wird sichtbar, ob ein Gewinn hauptsächlich von der Platzierung relativ zum Betriebsanfang abhängt.

**F1 sollte nicht auf eine entfernte Zusatzstudie verschoben werden.** Gerade ein gemeinsamer Bahnhof oder Zubringerhub ist ein plausibler Anwendungsfall, in dem freie Stationsressourcen weniger helfen könnten. Auch F1 garantiert keinen Nullgewinn: Andere Halte und Umlaufzeiten können weiterhin verbessert werden.

**F4 ist kein garantierter negativer Kapazitätsfall.** Kurze Reisen geben Sitze früher frei. Eine Kabine kann während eines Umlaufs mehrere Personen nacheinander bedienen. Deshalb kann eine hohe Zahl unterschiedlicher vollständig bedienter Personen trotz geringer Personenkilometer entstehen. Ein niedriger Reisezeitnutzen und ein niedriger Kapazitätsnutzen sind verschiedene Hypothesen.

**F5 ist auf dem gleichmäßigen T5R redundant:** F4 enthält die fünf Ein-Abschnitts-ODs, F3 die fünf Zwei-Abschnitts-ODs. Die 50/50-Mischung gibt jedem der zehn ODs Gewicht 1/10 und ist damit F0. Solche Duplikate werden über die normierten Gewichte erkannt und nicht als zusätzliche Evidenz gezählt.

Optional kann F2 mit einem Paar gleich langer Verbindungen verglichen werden, das eine Station gemeinsam hat. Beispiel T5R: S1→S3 und S3→S0. Dieser Vergleich kontrolliert OD-Anzahl und Weglänge, aber nicht vollständig die Abschnittslasten. Er ist daher ein ergänzender Mechanismustest und kein perfekt isolierter Faktorversuch.

## 5. Zeitprofile: Rate, Einzelankunft und Batch

Eine Minutenrate von 60 Personen ist etwas anderes als 60 gleichzeitig eintreffende Personen zu Beginn jeder Minute. Bei kurzen Kabinenabständen kann dieser Unterschied mehrere unmittelbar verfügbare Kabinen betreffen. Ein Minuten-Batch kann künstliche Warteschlangen erzeugen oder einer passend phasenverschobenen Referenz besonders günstige Einstiege ermöglichen.

Sun et al. unterscheiden ausdrücklich Intervallmengen und gleichmäßige Ankunft innerhalb des Intervalls. Die Seilbahnstudie aus Regensburg gibt zeitabhängige Raten in 15-Minuten-Schritten vor. Daraus folgt keine Begründung, die gesamte Intervallmenge gleichzeitig freizugeben. [^4] [^1]

### 5.1 Empfohlene Funktionen

Für \(x=t/T_D\in[0,1)\) wird \(p(t)=f(x)/T_D\) verwendet.

**P0 – konstanter Zufluss:**

\[
f_0(x)=1.
\]

**P1 – breiter Einzelpeak mit Grundlast:**

\[
g(x)=1-2|x-1/2|,
\qquad f_1(x;a)=\frac{1+a g(x)}{1+a/2}.
\]

Empfohlener Startwert ist \(a=2\). Dann beträgt die Spitzenrate das 1,5-Fache des Gesamtmittels, die Rate am Rand das 0,5-Fache. Das Verhältnis Spitze zu Rand beträgt 3:1. Diese beiden Peakdefinitionen dürfen nicht verwechselt werden. Der Parameter ist synthetisch; \(a=1\) und \(a=4\) können später eine mildere und stärkere Variante bilden.

**P4 – gleichmäßiger Hintergrund mit drei Feederpulsen:**

\[
p_4(t)=\frac{1-\beta}{T_D}
 +\frac{\beta}{3b}\sum_{m=1}^{3}
 \mathbf{1}_{[c_m-b/2,c_m+b/2)}(t).
\]

Vorschlag: \(\beta=0{,}5\), Pulsbreite \(b=2\) Minuten und Zentren \(c=(7{,}5;22{,}5;37{,}5)\) Minuten. Die Hälfte der Nachfrage kommt dann als Hintergrund, die andere Hälfte in drei endlichen Wellen. Die Zentren liegen bewusst im Inneren des Beobachtungsfensters. Die Zahlen dienen einem kontrollierten Feederexperiment; sie sind keine unterstellten realen Busfahrpläne. Sprünge beziehungsweise zusätzliche Zuflüsse sind durch entsprechende Metromodelle motiviert. [^6]

**P-batch – reine Ereignisnachfrage:** Alle Personen einer Welle erhalten tatsächlich denselben Zeitpunkt. Frühere Fälle mit Freigaben bei Minute 0/15/30 bleiben als solcher Stresstest möglich. Sie dürfen nicht als gleichmäßige Nachfrage beschriftet werden und ersetzen P0 nicht.

**OD-versetzte Peaks:** Für die zwei F2-Märkte werden endliche Pulsfenster gegeneinander verschoben, beispielsweise zunächst um fünf Minuten. Alle Fenster müssen im Freigabezeitraum bleiben, die OD-Gesamtmengen bleiben gleich. Die entstehende Änderung des Gesamtpeaks wird mitgemessen; der Test untersucht gerade die zeitliche Überlagerung der Märkte.

Eine Verschiebung um eine halbe numerische Bucketbreite heißt dagegen **Rasterphasensensitivität**. Sie beantwortet, ob das Ergebnis an einer Modellierungsphase hängt. Sie ersetzt keinen verkehrlichen Test von versetzten Nachfragewellen.

### 5.2 Keine vorschnelle neue Standardauflösung

Die physikalische Mikrosekundenauflösung bleibt unverändert. Die Frage betrifft ausschließlich die Darstellung der Nachfrage. Ein feineres Rateprofil muss nicht bedeuten, dass jede Person zu einem Rasterrand gebündelt wird.

Empfohlene Prüfung auf kleinen und mittleren Fällen:

1. Eine feste Liste individueller Ankünfte innerhalb der Ratenintervalle erzeugen und als Referenz speichern.
2. Daraus aggregierte Nachfrage mit früher beziehungsweise später Freigabe ableiten.
3. Zunächst 60, 30 und 10 Sekunden vergleichen; 120 Sekunden nur als explizit gröbere Zusatzvariante.
4. Nachfragemenge, OD und Personidentitäten erhalten; All-Stop-Phase in jedem abgewandelten Fall erneut optimieren.
5. Modellgröße und Aussageänderung gemeinsam bewerten.

Diese drei Auflösungen sind Testpunkte, keine behauptete erforderliche Feinheit. Die Auflösung ist akzeptabel, wenn die zu belegende Aussage gegen eine ausreichend feine Referenz oder die nachfolgende Einhüllung abgesichert ist. Ein gleiches Ergebnis zweier grober Raster allein reicht nicht.

### 5.3 Konservative Einhüllung für den Kapazitätsnachweis

Eine eigene, aus der Modellsemantik folgende Möglichkeit vermeidet ein unbegründetes Runden: Für jede Person in einem Intervall werden eine früheste und eine späteste Freigabe definiert,

\[
r_p^-\le r_p\le r_p^+.
\]

Wenn früher eintreffende Personen am Ursprung warten dürfen und keine zusätzliche individuelle Maximalwartezeit gilt, kann jede Beförderung für die spätere Freigabe auch bei der früheren Freigabe durchgeführt werden. Bei sonst identischer Betriebsdomäne folgt für die maximal bedienbare Menge:

\[
S^*(D^-)\ge S^*(D)\ge S^*(D^+).
\]

Damit wäre bei demselben N besonders belastbar:

\[
S_{SS}^{\text{validiert}}(D^+)=N
\quad\text{und}\quad
UB\bigl(S_{AS}^*(D^-)\bigr)<N.
\]

Dann gilt der Vorteil auch für jede dazwischenliegende tatsächliche Freigabeliste. Für All-Stop ist dabei wieder der festgelegte Baselinevertrag gemeint. Die Instanzen haben unterschiedliche Nachfrage-Fingerprints; die Vergleichsaussage muss den monotonen Zusammenhang ausdrücklich speichern.

Diese Einhüllung ist **eine vorgeschlagene Ergänzung, nicht bereits implementiert**. Sie darf keine frühen Boardingkandidaten abschneiden und muss dieselben Personen und sonstigen Randbedingungen enthalten. Bei endlichen Stationswarteschlangen, Verlassen des Systems oder individueller Wartezeitbegrenzung ist der einfache Beweis erneut zu prüfen. Für Reisezeitkosten gilt die obige Ungleichung nicht unverändert, weil die Freigabezeit selbst in der Kostenfunktion steht.

## 6. 45 Minuten Nachfrage und 15 Minuten Abschluss

Die Hauptdefinition bleibt:

- Fahrgastfreigaben in \([0,45\text{ min})\), bezogen auf einen eindeutig definierten Servicebeginn;
- Zielankunft spätestens bei Minute 60;
- Warm-up vor diesem Fenster und reine Fahrzeugrückkehr danach als getrennte Phasen;
- keine neue Nachfrage in der Abschlussphase.

Das ist als endliche Kohortenaufgabe sauber. Die Kombination beweist aber nicht, dass die mittlere Zuflussrate während der ersten 45 Minuten unbegrenzt tragbar wäre. Ein einfaches eigenes Gegenbeispiel: Eine Anlage kann 100 Personen pro Minute bedienen. Es kommen 45 Minuten lang 120 Personen pro Minute. Die 5.400 Personen sind bei kontinuierlichem Betrieb nach 54 Minuten abgearbeitet. Die Kohorte ist vollständig bedient, obwohl bei dauerhaftem Zufluss von 120 pro Minute die Warteschlange wachsen würde.

Deshalb werden \(\kappa\), \(\kappa/45\) Minuten und eine dauerhaft tragbare Leistung nicht synonym verwendet. Die zweite Größe ist die mittlere angebotene Rate der Kohorte. Auch \(\kappa/60\) Minuten ist zunächst nur ein über das gesamte Experiment gemittelter Wert.

Die bisher vorgeschlagene Bedingung

\[
h_{AS}+\tau_{AS}(o,d)\le15\text{ min}
\]

prüft höchstens, ob eine spät eintreffende Person bei verfügbarer Kapazität noch eine passende All-Stop-Kabine erreichen und ankommen kann. Sie beweist nicht, dass an der Kapazitätsgrenze alle Warteschlangen in 15 Minuten abfließen. Die benötigte Wartezeit kann mehrere Kabinen umfassen.

Empfehlung: 45+15 nicht wegen einzelner schlechter Resultate nachträglich verändern. Vor dem Einfrieren jeder Geometrie zunächst leere-System-Erreichbarkeit prüfen. Danach für jeden Kapazitätszeugen die Wartenden und Bordpassagiere bei Minute 45, den Anteil der Ankünfte während des Flushs, maximale/p95-Passagierwartezeit und den letzten Ankunftszeitpunkt berichten.

Bei deutlicher Abhängigkeit vom Zeitrand folgt ein gesonderter Test: 90 Minuten Nachfrage mit gleicher Rate und gleicher 15-Minuten-Abschlusszeit. Gleiche Gesamtmenge wäre dafür der falsche Vergleich. Alternativ lässt sich ein bereits vorhandener wiederholbarer Fahrplan über mehrere Nachfragefenster ohne neue Fahrplansuche auswerten. Das ergibt eine praktische Zeitfensterdiagnose, aber allein ebenfalls noch keinen asymptotischen Stabilitätsbeweis.

## 7. Kapazitätsprotokoll

### 7.1 Referenz und Nachweis

Die Referenz heißt ausdrücklich **gesättigtes, regelmäßiges All-Stop ohne Waiting mit optimierter gemeinsamer Phase**. Ihre genaue Flotte, Ressourcenbelegung, Vorlauf- und Endbedingungen werden pro Geometrie geprüft. Die einfache Formel Umlaufzeit durch Headway ersetzt diese Prüfung nicht.

Für ein eingefrorenes Profil ist

\[
\kappa_{AS}^{\mathrm{regular,phase}}
=\max\{N: U_{AS}(D(N))=0\}.
\]

Für Skip-Stop wird die größte N mit unabhängig geprüftem Vollbedienungsplan als \(\kappa_{SS}^{LB}\) gemeldet. Falls eine exakte All-Stop-Grenze zu teuer ist, genügt für einen Vorteilsnachweis eine gültige All-Stop-Obergrenze unterhalb eines solchen SS-Zeugen. Ein bloßer bester All-Stop-Fahrplan ist keine Obergrenze.

Die All-Stop-Nachfrageleiter braucht einen geprüften zulässigen unteren und einen nachgewiesen nicht vollständig bedienbaren oberen Punkt. Ganzzahliges Bracketing und anschließende Bisektion dürfen nur auf solchen Aussagen aufbauen. `UNKNOWN` verschiebt keine beweisrelevante Grenze.

Für Skip-Stop sind höhere N Suchaufgaben. Die zuletzt gefundene Vollbedienung ist eine Untergrenze; ein Suchplateau beweist kein Kappa-Maximum. Die Wachstumsleiter kann geometrisch sein, wird nahe einem gefundenen Übergang verfeinert und endet am vorab festgelegten Budget. Ein 1,25-facher Lastpunkt allein bestimmt kein Maximum.

### 7.2 Gleiche Last und gleiche relative Last

Für jede zeitliche oder räumliche Familie wird die eigene All-Stop-Grenze bestimmt, soweit für den Claim erforderlich. Der Quotient \(\kappa_{SS}^{LB}/\kappa_{AS}\) beantwortet die relative Verbesserung innerhalb dieses Falls.

Daneben werden P0, P1 und P4 bei derselben absoluten N verglichen. Eine Normierung aller Profile auf ihre jeweils eigene Kapazität könnte den Effekt stärkerer Spitzen verdecken. Beide Ansichten sind sinnvoll, dürfen aber nicht in derselben Vergleichsspalte vermischt werden.

Zwischen OD-Familien ist die Anzahl unterschiedlicher Personen keine konstante Transportleistung. Deshalb zusätzlich Personenkilometer beziehungsweise Personenabschnitte, mittlere Weglänge und kritische Abschnittslast angeben. Ein höheres Kappa bei lokalen Wegen beweist für sich keine effizientere Architektur.

## 8. Reisezeitprotokoll

Der methodische Hauptvergleich bleibt Fixed-K, gleiche feste Starts, gleiche Nachfrage, No-Wait und vollständige Bedienung. Labelled Arc-Flow kann hier eine exakte Lösung und gegebenenfalls einen gültigen Gap liefern. Die gesättigte All-Stop-Referenz mit anderer Flotte ist eine zusätzliche betriebliche Einordnung.

50 Prozent der am kleinsten K nachgewiesenen All-Stop-Profilkapazität sind ein brauchbarer **vorläufiger** niedriger Lastpunkt. Über den K-Sweep bleiben N und die individuellen Freigaben gleich. Die Wahl wird anhand niedriger Warteschlangen und vollständiger Bedienung überprüft; 50 Prozent sind kein empirisches Off-Peak-Gesetz.

Eine fehlende native Skip-Stop-Lösung darf nicht automatisch zu einer Nachfragereduktion auf 40 Prozent führen. Enthält das SS-Modell die All-Stop-Entscheidung und gelten identische Randbedingungen, ist der gültige AS-Plan zugleich ein SS-Zeuge. Scheitert sein Import oder Replay, muss der Modell- oder Vergleichsvertrag geprüft werden. Ein Such-Timeout ist kein Nachweis, dass die Nachfrage zu hoch ist.

Außerdem gilt bei diesem eingeschlossenen All-Stop-Fall:

\[
J_{SS}^*\le J_{AS}^*.
\]

Ein optimaler SS-Plan kann im Modell also auf All-Stop zurückfallen. Ein negativer gemessener Gewinn kann durch einen schlechteren Incumbent, zusätzliche Einschränkungen oder einen anderen Betriebsvertrag entstehen. Die Forschung zu nachteiligen vorgegebenen Skip-Stop-Diensten widerspricht dieser Mengeninklusion nicht.

Reisezeit wird in Wartezeit am Ursprung und Zeit in der Kabine zerlegt. Exit-Waiting unterwegs gehört zur Kabinenzeit, wenn Fahrgäste noch an Bord sind; Waiting nach dem Zielausstieg nicht. Neben dem Mittel werden p95 und Maximum sowie OD-bezogene Mittel berichtet. Eine Gesamtverbesserung kann einzelne Märkte verschlechtern.

Für die kleinen exakten Reihen bleibt ein umlaufbezogener Beobachtungszeitraum sinnvoll. Er muss je Geometrie ausdrücklich angegeben werden. Zwei Umläufe einer kurzen und einer langen Strecke sind keine identische absolute Betriebsdauer; daraus darf kein isolierter Streckenlängeneffekt auf Stundenkapazität abgeleitet werden.

## 9. Passagierverhalten, Vorwissen und Qualitätsaussagen

Das derzeitige Optimierungsproblem kennt die konkrete Nachfrage und verteilt sie ganzzahlig auf zulässige direkte Beförderungen. Es bewertet damit die technische Möglichkeit einer koordinierten Zuweisung. Verhaltensbezogene Limited-Stop-Forschung warnt davor, eine gesamtsystemorientierte Zuweisung ohne Weiteres als selbstständige Fahrgastentscheidung zu lesen. [^10]

Für die Hauptthesis ist es vertretbar, perfekte Nachfrageinformation und kontrollierte Zuweisung anzunehmen. Das muss im Modellumfang stehen. Beide Betriebsweisen erhalten dieselbe Informations- und Zuweisungsmöglichkeit. Die Zahlen sind keine Nachfrageprognose und keine Zusage, dass ungeführte Fahrgäste diese Kapazität realisieren.

Eine gezielte Robustheitserweiterung kann den fertigen Fahrplan fixieren und unabhängig evaluieren:

- andere eingefrorene Ankunftsrealisierungen aus derselben Intensität;
- deterministisch definierte Reihenfolge am Ursprung;
- Einstieg in eine geeignete Kabine nach einer vorab definierten Regel;
- getrennte Bewertung der optimalen Zuweisung und dieser Verhaltensregel.

Ein einfaches FIFO muss bei unterschiedlichen Haltemustern festlegen, ob es eine gemeinsame Warteschlange oder OD-bezogene Schlangen gibt und ob Personen eine ungeeignete Kabine vorbeifahren lassen. Diese Entscheidung gehört zur Simulation und darf nicht still im Passagieroptimizer angenommen werden.

Derartige Tests werden zuerst auf wenigen fertigen Fahrplänen durchgeführt. Sie erfordern keinen neuen Solvercontroller. Sie prüfen die Übertragbarkeit eines Plans; eine erneute Optimierung auf jeder Testrealisierung würde vor allem erneut das Potenzial bei perfekter Information messen.

## 10. Kleine, gestufte Versuchsmatrix

### Stufe A: Vertrags- und Erzeugungstests

Noch keine große Suche. Zuerst auf einer gleichmäßigen Referenzgeometrie die Nachfragegeneratoren und Baseline prüfen. Alle positiven, neutralen und begrenzenden Fälle bleiben in der Berichterstattung, auch wenn sie keine SS-Verbesserung zeigen.

### Stufe B: Kernnachfrage bei P0

| Forschungsfrage | Familien | Vergleich | Ergebnis |
|---|---|---|---|
| Kapazität | F0, F1, F2, F4 | Regelmäßiges phasenoptimiertes AS gegen Linienmodell mit zulässigem Waiting-Vertrag | AS-Grenze/Intervall, SS-Vollbedienungszeugen, Mindestgewinn, Flotte, Wartezeiten. |
| Reisezeit | F0, F3, F4 | AS und Labelled Arc-Flow bei identischem kleinen K und Starts | U=0, Kosten, gültiger Gap, Warte-/Kabinenzeit. |

Diese sieben Zellen werden zunächst auf **einer** Geometrie bearbeitet. Ein K-Sweep oder eine Nachfrageleiter umfasst mehrere Läufe; sieben Zellen bedeuten nicht sieben Solveraufrufe. T5R dient zugleich als kleiner Kontrollfall, T6R als Hauptmechanismusfall nach bestandenen Gates. T6L folgt mit Pflichtterminals und eigener Richtungsprüfung. Es wird nicht sofort über jede Geometrie, jedes Zeitprofil, jede Flottengrenze und jeden Seed das volle Produkt gebildet.

Die Flottengrenze ist eine noch zu schließende Betriebsfestlegung. Ein behaupteter physischer Maximalwert muss für Dispatch, Waiting und Rückkehr hergeleitet werden; kürzeste Umlaufzeit geteilt durch Headway ist nicht ohne Weiteres ein solcher Bound. Eine logarithmische Cap-Leiter ist anschließend ein vertretbarer Budgetkompromiss, aber keine Vorgabe der Nachfrageliteratur. Die Waiting-Stufe des Linienmodells benötigt ebenfalls ihre eigene Abnahme: Ein bisheriger No-Wait-Lauf darf nicht nachträglich als Ergebnis des vorgesehenen Waiting-Betriebs gelten.

### Stufe C: gezielte Zeit- und Strukturrobustheit

- F2 und F1 zusätzlich mit P1: fünfzig Prozent höhere Spitzenrate als Mittel beim vorgeschlagenen Parameter, sonst gleiche Gesamtmenge.
- F1 mit P4 als Zubringeranwendung; F2 mit P4, falls die zeitliche Überlagerung als Mechanismus relevant ist.
- F2-background und eine räumliche Rotation unabhängig davon berichten, ob der reine F2-Fall positiv ausfällt.
- Eine F2-Variante mit 75/25 statt 50/50 und eine mit versetzten Marktpeaks erst nach der Kernmatrix.
- Raster-/Ankunftsrobustheit auf mindestens einer diffusen und einer komplementären Zelle; nicht nur auf dem bequemsten Fall.

### Stufe D: Geometrie und Qualität

Erst danach Stationsabstände, Betriebsdauer oder Stationskinematik verändern. Ein konkreter Plan kann bei festem Fahrplan preiswert auf weitere Ankünfte und längere Zeitfenster geprüft werden. Solche Auswertungen sind von einer erneuten globalen Fahrplansuche getrennt.

Bei identischer Geometrie und Nachfrage erhalten Solverreplikationen dieselben Nachfrageartefakte. Unterschiedliche Nachfrage-Seeds und unterschiedliche Solver-Seeds werden getrennt geführt. Zunächst drei gepaarte Nachfragerealisierungen sind ein pragmatisches Screening, keine statistisch abgesicherte allgemeine Zuverlässigkeitsaussage. Eine starke Robustheitsaussage benötigt vorab festgelegte zusätzliche Replikationen und eine passende Unsicherheitsauswertung.

## 11. Zwischentests und Abnahmekriterien

| Test | Durchführung | Erwartete Aussage / Abnahme |
|---|---|---|
| D1 Normierung | Alle räumlichen/zeitlichen Profile integrieren beziehungsweise summieren. | Nichtnegative Gewichte, Summe 1; Integerinstanz enthält genau N Personen. |
| D2 Richtung | T5R/T6R mit symmetrischen Distanzen, T6L sowie ungleiche Distanzen. | Keine versehentlich lange Ringrichtung; diametrale Anteile korrekt; Richtungsanteil explizit. |
| D3 Verschachtelung | Viele aufeinanderfolgende N, darunter Zellwechsel. | Alte Personen behalten ID, OD und Freigabe; nur neue Personen kommen hinzu. |
| D4 Duplikate | Normierte OD-/Zeitfelder vergleichen. | F5=F0 auf symmetrischem T5R erkannt; semantisch gleiche Fälle nicht doppelt gezählt. |
| D5 Zeitdarstellung | Feste Einzelankünfte gegen Minuten-Batches und feinere Aggregationen, AS-Phase jeweils frei. | Größe und Richtung des Aggregationseffekts berichtet; konstante Rate nicht falsch beschriftet. |
| D6 Einhüllung | Kleine vollständig lösbare Fälle mit frühen/originalen/späten Freigaben. | Monotonie der Kapazität; Kandidatenbasis vollständig; Verletzung blockiert Nutzung als Nachweis. |
| D7 Zeithorizont | Einzelne späte Personen, danach belastete Warteschlangen. | Erreichbarkeitsprüfung und tatsächliche Räumung unterschieden; Endereignisse tickgenau. |
| D8 Baselineinklusion | AS-Zeuge im passenden SS-Modell reproduzieren. | Gleiche Bewegung/Beförderung gültig; ansonsten Unterschiede aufklären. |
| D9 Kapazitätsgrenze | Verschachtelte Nachfrage, exakte AS-Phase und Integerzuweisung. | Untere Grenze mit U=0; obere Grenze nur mit Beweis; UNKNOWN bleibt offen. |
| D10 Konfundierung | F2 mit Hintergrund und Portrotation. | Gewinne nach OD-Struktur und Start-/Endeffekt eingeordnet. |
| D11 Qualitätsreplay | Validierten Plan mit optimaler Zuordnung und festgelegter Einstiegsregel bewerten. | Technisches Potenzial und verhaltensbezogene Bedienung getrennt. |
| D12 Reproduzierbarkeit | Manifest und exportierte Nachfrage erneut laden. | Gleiche Hashes, Mengen, Zeitpunkte und Referenzwerte. |

Numerische Akzeptanzgrenzen werden vor den Testläufen festgelegt. Für Integerkapazität ist die Entscheidung besonders klar: Ein behaupteter SS-Vorteil muss größer als die verbleibende Unsicherheit des AS-/Nachfragevergleichs sein. Für Reisezeit sollte die tolerierte Aggregationsänderung deutlich unter dem als relevant bezeichneten Effekt liegen. Eine konkrete Prozenttoleranz wird hier nicht als literaturgegeben erfunden.

## 12. Kennzahlen und Ergebnisdateien

Jede Instanz erhält neben den bisherigen Fingerprints folgende Angaben:

| Bereich | Zu speichern |
|---|---|
| Nachfrage | Normierte OD-Gewichte, Richtungsanteile, Zeitfunktion samt Parametern, tatsächliche Freigabeliste, Erzeugerversion, Nachfrage-Seed, Präfixidentitäten. |
| Belastung | Einsteigeranteil je Station, Aussteigeranteil je Station, Abschnittslast, mittlere Fahrtlänge, Anteil der größten OD-Märkte, Spitzenkonzentration. |
| Zeitvertrag | Vorlauf, Servicebeginn, Freigabeende, Fahrgastdeadline, Rückkehrdeadline, Anfangsbelegung. |
| Kapazität | Validierte Vollbedienungszeugen, abgesicherte AS-Grenzen, Teilbedienung separat, verwendete/einsetzbare Flotte. |
| Qualität | Mittel/p95/Maximum von Warten und Reisezeit; Ergebnisse je OD; Wartende/Bordpassagiere bei Minute 45, Ankünfte im Flush, letzte Zielankunft. |
| Rechenaufwand | Aufbau, Passagiergruppen/Rides, Variablen, Constraints, RSS, native Fortschritte, Referenzübernahme, Gültigkeitsbereich der Bounds. |
| Vergleich | Gleiche absolute N oder gleiche relative Last, optimierte oder fixierte Phase, Nachfrage- versus Solverreplikation. |

Für festgelegte Referenzwege ist die erwartete Abschnittslast pro Person

\[
L_e=\sum_{od:e\in P_{od}}w_{od}.
\]

Stationsanteile sind \(B_s=\sum_d w_{sd}\) und \(A_s=\sum_o w_{os}\). Die Kombination aus \(\max_eL_e\), \(\max_sB_s\), \(\max_sA_s\) und mittlerer Fahrtlänge erklärt Unterschiede besser als die Familien-ID allein. Sie ersetzt keine Ressourcenkapazitätsprüfung.

Für das 45-Minuten-Fenster kann eine eigene Peakkennzahl

\[
C_{15}=3\max_{a\in[0,30\text{ min}]}\int_a^{a+15\text{ min}}p(t)\,dt
\]

verwendet werden. Bei konstanter Rate ist sie 1. Sie ist ausdrücklich eine auf dieses Fenster normierte Konzentrationskennzahl, kein ungeprüft übernommener stündlicher Peak-Hour-Factor. Für mehrere OD-spezifische Zeitprofile wird die gewichtete Gesamtdichte verwendet und bei Bedarf je Station zusätzlich ausgewertet.

## 13. Anschluss an vorhandene Dokumente und Code

| Fundstelle | Bedeutung / Konsequenz |
|---|---|
| [Entscheidungsregister](../thesis/experiment_definition_register_20260913.md) | Zentrale Freigaben. Dieser Bericht präzisiert die noch vorläufigen räumlichen und zeitlichen Kategorien. |
| [Nachfragefamilien](../reference/demand_case_families.md) | Vorhandene F-/P-Formeln und verschachtelte Zellverteilung; teilweise ältere Doppelring- und Batchverträge. Nicht allein über gleiche ID als neuer Thesisfall interpretieren. |
| [All-Stop-Referenz](../reference/all_stop_no_wait_capacity_baseline.md) | Regelmäßiger phasenoptimierter No-Wait-Vertrag und ganzzahlige Zuordnung. |
| [Älterer Versuchsplan](../thesis/experimental_design_20260913.md) | Ausgangspunkt der beiden Forschungsfragen und früheren Matrix. |
| [Ringnachfrage-Pilot](../../src/ropeway_skip_stop_optimization/benchmarking/ddd_ring_demand_case.py) | `distributed` sind derzeit vier gemeinsame Freigaben bei 0/200/400/600 s; `express` nutzt drei/vier Abschnitte im rein gerichteten Fünferring. Beides gehört zum Legacy-Pilot und ist kein neuer P0/T5R-Vertrag. |
| [NestedDemand und feste Fahrplankapazität](../../src/ropeway_skip_stop_optimization/optimization/ddd/fixed_timetable_capacity.py) | Stabile Gruppenfreigaben und gewichteter Defizitausgleich vorhanden. Innerhalb von Intervallen verteilte stabile Einzelankünfte sind eine zusätzliche Erzeugeraufgabe. |
| [Längenskalierung](../findings/reservoir_line_length_scaling_results_20260913.md) | Historische kurze Fälle mit alter Lebenszyklusvariante; kein bereits eingefrorenes T6R-Ergebnis. |
| [Verdoppelte Betriebsdauer](../findings/reservoir_line_operation_horizon_results_20260913.md) | Zeigt den Unterschied zwischen konstanter Menge und konstanter Rate; die alten No-Wait-Läufe zeigten bei fünf Minuten Suche keine Verbesserung des Seeds. Kein Ersatz für den neuen 45+15-Nachweis. |

Diese Abgleiche begründen auch, weshalb kein bestehender `distributed`-Lauf ohne Prüfung als Evidenz für gleichmäßigen kontinuierlichen Zufluss verwendet werden sollte. Für dieses Dokument wurden keine neuen Solverläufe ausgeführt und keine historischen Resultate umetikettiert.

## 14. Entscheidungsvorschlag

Als nächstes werden **Nachfragegenerator und Aussagevertrag**, anschließend die konkreten Fallwerte eingefroren. Empfohlene Reihenfolge:

1. Referenzrichtungen, Gleichstände und F0-Normierung für T5R/T6R/T6L entscheiden.
2. Kapazität mit F0/F1/F2/F4 und Reisezeit mit F0/F3/F4 festlegen; F5 nur ohne Duplikat.
3. P0 als Rate, P1 und P4 durch die angegebenen normierten Funktionen festlegen; vorgeschlagene Parameter ausdrücklich als synthetisch kennzeichnen.
4. Den 45+15-Vertrag einschließlich Anfangszustand und Qualitätskennzahlen schließen.
5. Frühe/späte Nachfrageaggregation gegen feste Einzelankünfte prüfen; daraus eine tragbare Darstellung wählen.
6. All-Stop-Grenzen und kleine RQ-J-Kalibrierung bestimmen, danach die Hauptsuche starten.

Die präzise Hauptaussage wäre: **Unter definierten Nachfrageprofilen und identischen physischen Randbedingungen kann ein validierter Skip-Stop-Fahrplan mehr Personen vollständig bedienen als die regelmäßige, phasenoptimierte All-Stop-No-Wait-Referenz.** Hinzu kommt der exakte kleine-K-Vergleich der Reisezeit. Ein allgemeiner Vorteil gegenüber jeder All-Stop-Politik, eine stationäre Stundenkapazität und ungeführtes reales Einsteigeverhalten bleiben getrennte, weitergehende Aussagen.

## Quellen

Zugriffsstand: 14.09.2026. Abschnittsangaben beziehen sich auf die jeweils verlinkte Fassung. Empfohlene Zahlen dieses Berichts sind, sofern nicht ausdrücklich anders bezeichnet, eigene Versuchsparameter.

[^1]: Simon Haimerl, Christoph Tschernitz, Tobias Schiller, Christoph Weig, Ulrich Briem und Stefan Galka. 2022. [Development of a Simulation Framework for Urban Ropeway Systems and Analysis of the Planned Ropeway Network in Regensburg, Germany](https://informs-sim.org/wsc22papers/138.pdf). Winter Simulation Conference, S. 1413–1424. Volltext; besonders §§ 3.2, 4.2.1–4.2.3 und 5.2.

[^2]: Y. Mei, W. Gu, M. J. Cassidy und W. Fan. 2021. [Planning skip-stop transit service under heterogeneous demands](https://doi.org/10.1016/j.trb.2021.06.008). Transportation Research Part B. [Autorenvolltext](https://arxiv.org/pdf/2011.12674), besonders § 4.1 und § 5.1. Originalverteilungen und Modellumfang geprüft; keine Übernahme der dortigen Gewinnwerte.

[^3]: Homero Larrain und Juan Carlos Muñoz. 2016. [When and where are limited-stop bus services justified?](https://doi.org/10.1080/23249935.2016.1177135). Transportmetrica A 12(9), 811–831. [Verlagsabstract](https://www.sciencedirect.com/org/science/article/abs/pii/S2324993522000719); Umfang des Versuchs und berichtete Einflussgrößen.

[^4]: Lijun Sun, Jian Gang Jin, Der-Horng Lee, Kay W. Axhausen und Alexander Erath. 2014. [Demand-driven timetable design for metro services](https://doi.org/10.1016/j.trc.2014.06.003). Transportation Research Part C 46, 284–299. [Autorenvolltext](https://lijunsun.github.io/files/papers/2014-TRC-Timetable.pdf), § 3.1, § 3.2.1, Annahme A2, und § 3.3.3.

[^5]: Le Minh Kieu und Chen Cai. 2018. [Stochastic collective model of public transport passenger arrival process](https://ietresearch.onlinelibrary.wiley.com/doi/10.1049/iet-its.2018.0085). IET Intelligent Transport Systems 12(9), 1027–1035. Volltext, Einleitung, Modell und empirische Auswertung.

[^6]: Víctor Blanco, Eduardo Conde, Yolanda Hinojosa und Justo Puerto. 2020. [An optimization model for line planning and timetabling in automated urban metro subway networks. A case study](https://doi.org/10.1016/j.omega.2019.102165). Omega. [Autorenvorabfassung](https://arxiv.org/html/1903.08617), besonders § 2 und § 4 zu kumulierter Nachfrage. Unterschiede der Formulierungsfassungen nicht aufgelöst, daher hier keine Gleichsetzung ihrer Solvermodelle.

[^7]: Huimin Niu, Xuesong Zhou und Ruhu Gao. 2015. [Train scheduling for minimizing passenger waiting time with time-dependent demand and skip-stop patterns: Nonlinear integer programming models with linear constraints](https://doi.org/10.1016/j.trb.2015.03.004). Transportation Research Part B. [Verlagsvorschau](https://www.sciencedirect.com/science/article/pii/S0191261515000478). Verwendet für die Verbindung zeitabhängiger Nachfrage und Wartezeitbewertung.

[^8]: Rodolphe Farrando, Nadir Farhi, Zoi Christoforou und Alain Urban. 2024. [A mathematical model for a two-service skip-stop policy with demand-dependent dwell times](https://doi.org/10.1016/j.jrtpm.2024.100461). Journal of Rail Transport Planning & Management 31, 100461. [Verlagsvorschau](https://www.sciencedirect.com/science/article/pii/S2210970624000313), Abstract und Modellumfang; kein Volltextnachweis der konkreten Profilparameter.

[^9]: Ramandeep Singh, Daniel J. Graham, Daniel Hörcher und Richard J. Anderson. 2021. [The boundary between random and non-random passenger arrivals: Robust empirical evidence and economic implications](https://doi.org/10.1016/j.trc.2021.103267). Transportation Research Part C 130, 103267. [Verlagsabstract](https://www.sciencedirect.com/science/article/abs/pii/S0968090X21002795); empirischer Frequenz-/Ankunftszusammenhang.

[^10]: Hemant Suman, Homero Larrain und Juan Carlos Muñoz. 2021. [The impact of using a naïve approach in the limited-stop bus service design problem](https://doi.org/10.1016/j.tra.2021.04.018). Transportation Research Part A 149, 45–61. [Primärveröffentlichung](https://www.sciencedirect.com/science/article/abs/pii/S0965856421001166) und indizierter [Autoren-PDF-Auszug](https://www.cedeus.cl/wp-content/uploads/2021/05/2021-The-impact-of-using-a-naive-approach-in-the-limited-stop-bus-service-design-problem.pdf). Direkter PDF-Zugriff eingeschränkt; nur verifizierte Problemstellung verwendet.

[^11]: R. M. Martinod, Olivier Bistorin, L. F. Castañeda und Nidhal Rezg. 2023. [Decision support algorithm for intermodal transport networks: Urban aerial cableway systems](https://doi.org/10.1016/j.cstp.2023.101018). Case Studies on Transport Policy 12, 101018. Verlagsabstract und [Autoreneintrag mit Abstract](https://www.researchgate.net/publication/370788456_Decision_support_algorithm_for_intermodal_transport_networks_urban_aerial_cableway_systems); keine detaillierte Übernahme von Ankunftsverteilungen.

[^12]: National Academies of Sciences, Engineering, and Medicine. 2026. [Transit Capacity and Quality of Service Manual, 4th edition](https://www.nationalacademies.org/publications/29449), TCRP Research Report 262, DOI [10.17226/29449](https://doi.org/10.17226/29449). Ausgabe und Inhaltsverzeichnis verifiziert; [offizielle APTA-Veröffentlichungsbeschreibung](https://www.apta.com/news-research/transit-cooperative-research-program/tcrp-publications/), Eintrag vom 22.06.2026. Hier keine nicht eingesehene Kapazitätsformel zitiert.
