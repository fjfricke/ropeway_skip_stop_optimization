# Arc-Flow-Architektur für Reservoirbetrieb mit Waiting und Passagieren

## Empfehlung und Geltungsbereich

Die nächste experimentelle Architektur sollte aus einem unveränderten exakten Phasen-Bewegungsnetz, einem eigenständigen Nachfrage-Wartenetz, gemeinsamen Bordflüssen kompatibler OD-Klassen und einer expliziten Konfliktstruktur bestehen. Gurobi optimiert weiterhin ein integriertes MILP. Weder ein neuer Solver noch eine eigene Fahrplansuche oder ein eigener Zerlegungscontroller ist dafür erforderlich.

Priorität haben zwei verschiedene Ziele: weniger redundante Passagierdarstellung und stärkere Beschreibung tatsächlich kombinatorischer Konflikte. Eine Verringerung der Variablenzahl allein garantiert weder bessere Fahrpläne noch einen kleineren Gap. Die vorgeschlagenen Änderungen sind noch nicht implementiert. Die laufende Vergleichskampagne wird dadurch nicht verändert.

Der unmittelbare Vertrag ist der aktuelle Fünf-Stationen-Pilot: Single-Use-Reservoir mit höchstens 50 Kabinen, exakte ausgewählte Ereigniszeiten, Exit-Waiting, direkte ganzzahlige Beförderungen und Ziel `unserved`. Der eingeschränkte Ereignisgraph bleibt eine Fahrplansuche; seine Schranken werden durch eine bessere Formulierung nicht zu globalen Schranken des vollständigen Zeitbereichs. Aussagen über Fixed-K, Reisezeit und den Sechs-Stationen-Doppelring werden separat eingeordnet.

## 1. Lokaler Befund und bisherige Erfahrungen

Die abgeschlossene erste Reservoir-Kampagne liegt unter `benchmarks/output/reservoir_capacity_campaign_20260911_v1/`. Maßgeblich sind dort die abgeschlossenen Ergebnisdateien; das ältere Findings-Dokument enthält noch einen Zwischenstand. Auf R2 lieferten beide Arc-Flow-Screenings und beide CP-SAT-Skip-Stop-Läufe den übernommenen Startwert U=578, ohne Verbesserung. Der globale All-Stop-Bound ist U>=125. Er darf nicht als Skip-Stop-Schranke verwendet werden.

| Größe im R2-Phasenmodell | Wert |
|---|---:|
| Bewegungsvariablen | 122.088 |
| Ganzzahlige Passagierflussvariablen | 720.346 |
| Kumulative kontinuierliche Hilfsvariablen | 46.775 |
| Variablen insgesamt | 889.209 |
| Nebenbedingungen | 826.867 |
| Passagier-Flusserhaltung | 443.613 |
| Kapazitätszeilen | 82.357 |
| Ressourcenzeilen | 76.188 |
| Nichtnullkoeffizienten | 4.493.613 |

Quelle: [R2-Ergebnis](../../benchmarks/output/reservoir_capacity_campaign_20260911_v1/R2_phase_arc_flow_s0/result.json). Nach Presolve blieben etwa 489.000 Variablen und 323.000 Zeilen. Die kurzen Läufe endeten während der Root-Verarbeitung. Barrier erreichte ungefähr U=0; das ist kein gültiger ganzzahliger Fahrplan. Die Ursache des schwachen Bounds ist bislang nicht durch eine systematische Analyse der fraktionalen Lösung isoliert.

Der [aktuelle Builder](../../src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_capacity/model.py) erzeugt ab der Schleife `for g in p.demand_groups` ein eigenes Bordnetz je Nachfragegruppe. R2 hat vier OD-Verbindungen mit jeweils neun Freigabezeiten. Vorwärts-/Rückwärts-Erreichbarkeitspruning ist bereits implementiert. Auch aggregierte Kapazitätskopplung auf den Ausstiegsarcs existiert bereits über `loads`; sie darf nicht nochmals als neue Idee verkauft werden.

Die frühere [Labelled-A–D-Kampagne](../plans/arc_flow_passenger_profiles_20260910.md) ist ein wichtiger Gegenbefund: `destination_flows` verringerte K39 von 355.304 auf 214.399 Variablen. Die bestätigten Kostenverbesserungen von etwa 0,0344 % und 0,0850 % verfehlten die vorgegebenen Schwellen. Alle K39-Läufe meldeten nur einen Suchknoten. Aggregation wurde also bereits getestet und war kein Durchbruch. Neu wäre ihre auf den anonymen Phasengraphen und identische OD-Freigabeklassen zugeschnittene Anwendung, ergänzt um andere Konfliktkopplungen.

## 2. Was die Forschung über gute Arc-Flow-Modelle sagt

### Zustandsinhalt bestimmt die Stärke

De Lima et al. stellen den Zusammenhang zwischen dynamischen Programmen, Arc-Flow-Netzen und Dantzig-Wolfe-Formulierungen dar. Starke Modelle entstehen insbesondere, wenn ein Pfad bereits ein zulässiges kombinatorisches Teilobjekt repräsentiert. Zustandsraumrelaxation kann Netze verkleinern, verändert aber deren Stärke. Der Name Arc-Flow allein sagt daher wenig über die Relaxationsqualität aus.[^1]

**Übertragung:** Unser einzelner Kabinenpfad beschreibt Bewegung. Konfliktfreiheit zwischen Kabinen und die gekoppelten Passagieranforderungen entstehen größtenteils erst durch Nebenbedingungen. Die LP darf diese Entscheidungen fraktional kombinieren. Die gute Erfahrung mit kleinen Labelled-Instanzen beweist deshalb keine vergleichbare Stärke der anonymen Reservoirformulierung.

### Partielle statt pauschale Flussaggregation

Kazemi et al. untersuchen Aggregation über Teilnetze und stellen mehrere Formulierungen mit unterschiedlicher Größe und LP-Stärke gegenüber. Ihre verschärfte Variante nutzt zusätzliche künstliche Knoten und Flusserhaltungsgleichungen, um unerlaubtes Wechseln zwischen Flussklassen zu verhindern. Die Arbeit belegt einen kontrollierbaren Zielkonflikt; sie behauptet nicht, dass die kleinste Darstellung immer am schnellsten ist.[^2]

**Übertragung:** Herkunft und Freigabe nur dort mitführen, wo sie noch Entscheidungen einschränken. Gemeinsame Bordflüsse erst nach einem zulässigen Einstieg zusammenführen. Unterschiedliche Ziele, Fristen, zulässige Teilnetze oder Richtungen dürfen nicht ohne Nachweis dieselbe Klasse bilden.

### Graphkompression ist kein beliebiges Zusammenlegen von Zeiten

Brandão und Pedroso zeigen eine kompakte Arc-Flow-Darstellung gültiger Packmuster. Ihre Kompression erhält die benötigten Muster und erzeugt keine ungültigen; für die untersuchten Packprobleme bleibt die starke Gilmore-Gomory-Relaxation erhalten.[^3]

**Übertragung:** Gesucht werden bei Ropeway äquivalente Fortsetzungen beziehungsweise deterministische Teilketten mit rekonstruierbaren Schnittstellen. Zwei Ereignisse an derselben Station, aber zu unterschiedlichen Zeiten, sind wegen Freigaben, Kollisionen und Rückkehrfrist im Allgemeinen nicht äquivalent. Die hohen Kompressionsraten der Packprobleme sind keine Vorhersage für unser Zeitnetz.

### Zeit-Raum-Aggregation im Fahrzeugeinsatz

Kliewer, Mellouli und Suhl reduzieren ein Zeit-Raum-Netz für Busumlaufplanung durch Aggregation von Verbindungsarcs. Ihr Modell behandelt vorgegebene Fahrten und deren Verkettung.[^4]

**Übertragung:** Nützlich sind gemeinsame Warteketten anstelle sämtlicher paarweiser Verbindungen. Unsere Exit-Holding-Ketten tun bereits einen Teil davon. Bei uns sind jedoch die Fahrten selbst Entscheidungen, und Waiting blockiert Ressourcen. Die Busformulierung kann diese Bedingungen nicht ersetzen.

### Kapazität und Konsolidierung als strukturierte Teilobjekte

Hewitt und Lehuédé beschreiben konsolidierungsbasierte und hybride SSND-Formulierungen mit stärkeren Relaxationen gegenüber ihrer klassischen Zeitnetzdarstellung. Der hybride Ansatz soll die Explosion vollständig enumerierter Konsolidierungen begrenzen. Zugänglich war hier insbesondere die Autoren-Zusammenfassung; daraus wird kein ungeprüftes Detail ihrer Algebra übernommen.[^5]

Gouveia, Leitner und Ruthmair behandeln geschichtete Netze mit zusätzlichen Ressourceninformationen und den Zielkonflikt zwischen Modellstärke und Größe.[^6]

**Übertragung:** Ein Bordzustand kann zusätzliche Information tragen. Aber das volle Produkt aus Zeit, Station, Belegung und Zielverpflichtungen könnte größer werden als unser heutiges Modell. Ein lokaler Zustandsblock ist zunächst eine zu prüfende Verschärfung, keine automatische Kompression.

## 3. Empfohlene Nachfrage- und Passagierarchitektur

Die folgenden Konstruktionen sind Ropeway-Ableitungen. Die Literatur liefert die Modellierungsprinzipien, keinen fertigen Korrektheitsbeweis für unseren Vertrag.

### Stufe P1: Gruppenspezifischer Einstieg, gemeinsamer Bordfluss

Für jede Nachfragegruppe g bleiben ganzzahlige Einstiegsvariablen b[g,a] auf den nach Freigabe zulässigen Origin-Exit-Arcs. Nachfrage wird weiterhin gruppengenau bilanziert. Auf nachfolgenden Arcs ersetzt f[c,a] die einzelnen Flüsse; c ist eine nachweislich kompatible OD-Klasse. Am ersten Ziel endet der Fluss über den rechtzeitigen STOP-Ankunftsarc. Alle Klassen teilen die vorhandenen Kabinenkapazitäten.

Eine lokale Supportzählung auf dem eingefrorenen R2-Netz ergibt:

| Komponente | Anzahl |
|---|---:|
| Gruppenspezifische Einstiegsvariablen | 78.081 |
| Gemeinsame Nicht-Einstiegsflüsse je OD | 109.776 |
| Passagiervariablen zusammen | 187.857 |
| Gesamt einschließlich unveränderter Bewegung und Waiting-Hilfsvariablen | 356.720 |

Das entspricht rechnerisch rund 60 % weniger Gesamtvariablen. Gezählt wurden die bisherigen nach Reachability verbleibenden Supports, mit unverändertem Gruppenindex am Einstieg und Vereinigungsbildung über OD und Arc danach. Das ist keine Modellbau- oder Laufzeitmessung und enthält noch keine eventuell notwendigen zusätzlichen Schnittstellenvariablen.

**Nachweisbedarf:** Aus jedem alten Fluss entsteht durch Summieren ein neuer. Für die umgekehrte Richtung müssen gemeinsame Flüsse in ursprüngliche Klassen zerlegbar sein. Bei ganzzahliger Bewegung verhindert die erhaltene Ein-Kabinen-Belegung jedes exakten Phasenknotens einen Kabinenwechsel. Das rechtfertigt noch keine willkürliche Zusammenfassung unterschiedlicher Restwege. LP-Projektionsgleichheit wird separat untersucht, nicht aus ganzzahliger Äquivalenz gefolgert.

### Stufe P2: Nachfrage-Wartenetz vor dem Einstieg

Für `unserved` können Freigabegruppen derselben OD unter bestimmten Bedingungen sogar vor dem Einstieg gemeinsam dargestellt werden. Entscheidend ist eine **Nachfragewarteschlange an Land**, nicht ein zusätzlicher Warteort für Kabinen oder Passagiere während der Beförderung.

Für eine OD-Klasse c sei A_c(t) die kumulierte Zahl freigegebener Personen. Für jeden möglichen Einstiegszeitpunkt gilt:

```
Summe der Einstiege dieser OD bis einschließlich t <= A_c(t).
```

Eine sparsame Darstellung nutzt statt vieler langer Präfixsummen eine Zeitkette. Zwischen aufeinanderfolgenden Nachfrage-/Einstiegsereignissen gilt:

```
Restbestand_neu = Restbestand_alt + neue_Nachfrage - Einstiege
Restbestand_neu >= 0
```

Freigabe am selben Tick wird vor dem Einstieg verbucht. Bestand am Ende ist unbediente Nachfrage. Ab Einstieg darf kein Fluss mehr in diese Bodenwarteschlange zurückkehren; es gibt weiterhin keine Umstiege und kein Verwerfen eingestiegener Personen. Die Bordnetze enden nur an zulässigen Zielen.

**Warum die Freigabesemantik damit darstellbar ist:** Ordnet man ganzzahlige Einstiege zeitlich, garantiert die Präfixbedingung bei jedem Einstieg ausreichend noch nicht verbrauchte, bereits freigegebene Personen. Durch Zuordnung aus diesem Bestand erhält man Gruppenmengen mit unveränderten Freigaben. Umgekehrt erfüllt jede gültige gruppenspezifische Zuordnung die Präfixbedingungen. Diese Argumentation betrifft die Nachfragezuordnung; die Kabinen- und Beförderungsbedingungen müssen zusätzlich durch das Bordnetz erhalten bleiben.

**Geltungsbedingungen:** gleiche OD, gleiche weiteren Bedienungsbedingungen, gleicher letzter Ankunftshorizont, identische Personenplätze und keine gruppenspezifischen Mindestbedienungen, Prioritäten oder maximalen individuellen Reisezeiten. Für R2 ist das ein passender Prüfbereich. Reisezeitoptimierung ist gesondert zu entwickeln: Welche Freigabegruppen bedient werden, beeinflusst dort die Kosten. Ein bloßer Gesamtbestand reicht dafür nicht.

**Zertifikate:** Das kompakte Modell projiziert Gruppenidentitäten heraus. Ein Lift ordnet anschließend Personen Gruppen und kanonischen Rides zu. Das ist Rekonstruktion einer zulässigen Lösung, keine Reparatur eines unzulässigen Fahrplans. Historische Seed-Belegungen müssen weiterhin nachweislich darstellbar bleiben; zur Reproduktion genau dieses Seeds wird seine ursprüngliche Gruppenzerlegung mitgeführt. Die Reisezeit bleibt überprüfbare Kennzahl, kann bei einer anderen zulässigen Gruppenzuordnung aber abweichen.

Für P2 liegt noch keine belastbare Gesamtgrößenzählung vor. Die 356.720 aus P1 dürfen nicht als Größe von P2 ausgegeben werden.

### Ganzzahligkeit verschieben

Erst nach erfolgreicher P1-Validierung sollte geprüft werden, ob allein die Einstiege ganzzahlig bleiben können. Bei binärer Bewegung verläuft jedes Fahrzeug auf einem separaten ausgewählten Pfad. Ganzzahlige Einstiege und vorgeschriebene Zielausstiege könnten auf diesen Pfaden die Ganzzahligkeit der restlichen Bordflüsse erzwingen.

Das ist ein bedingter Strukturbeweis, kein allgemeiner Integritätssatz für Multicommodity-LPs. Verschwindet die eindeutige Pfadzuordnung durch eine spätere Kompression, kann das Argument ungültig werden. Der bestehende Odd-Cycle-Test und weitere Fälle mit mehreren Gruppen müssen deshalb erhalten bleiben. Reine Verlagerung der Ganzzahligkeit entfernt keine LP-Spalten; sie ist nicht die erste Maßnahme gegen teuren Crossover.

## 4. Bewegungsnetz und Ressourcenarchitektur

### Zwei Sichten auf dieselben exakten Phasen

Die physikalische Sicht sollte alle vorhandenen Ankunfts-, Service-, Ready-, Holding- und Exit-Ereignisse behalten. Eine algebraische Sicht darf deterministische Teilketten zusammenziehen, wenn ihre Variablen durch Erhaltung identisch sind und alle Ressourcen-, Nachfrage-, Ausstiegs- und Waiting-Schnittstellen erhalten oder exakt substituiert werden.

Beispielsweise braucht eine Passagierklasse ohne Ein-/Ausstieg an einem Zwischenpunkt nicht zwangsläufig eine zusätzliche Variable auf jeder rein deterministischen Servicekante. Für eine andere Klasse kann derselbe Punkt ein unverzichtbares Ausstiegsereignis sein. Deshalb ist eine klassenspezifische Kompression der Passagiersicht häufig sicherer als Löschen physikalischer Ereignisse im Bewegungsnetz.

Vor und nach der Kompression werden Original-zu-Modell-Abbildungen gespeichert. Der Ausbau darf keine neuen Warteorte, kein zeitliches Runden und keine zusätzliche Verbindung zweier Kabinen erzeugen. Gurobi entfernt bereits viele Gleichheiten im Presolve; der zusätzliche Nutzen muss an der Größe **nach** Presolve und an der Faktorisierung gemessen werden.

### Ressourcencliquen: Verkleinern und Verstärken getrennt behandeln

Der aktuelle Sweep erzeugt Ressourcenzeilen je geschütztem Intervallabschnitt. Identische Zeilen und komponentenweise dominierte Zeilen mit derselben rechten Seite können entfernt werden. Wegen möglicher mehrfacher Ressourcennutzungen eines Arcs muss der Nachweis Koeffizienten berücksichtigen; reine Mengeninklusion genügt nicht immer. Das ist algebraische Bereinigung mit gleicher LP-Projektion.

Ein anderer Ansatz ist der **ressourcenübergreifende Konfliktgraph**. Ein Knoten steht für eine binäre Arc-Auswahl; eine Kante belegt, dass zwei Auswahlen physikalisch unvereinbar sind. Die Bahn-Literatur untersucht stärkere Formulierungen aus Kompatibilitäts- und Konfliktstrukturen.[^7]

Eigene Illustration: Drei Alternativen a,b,c können paarweise kollidieren, aber auf unterschiedlichen Ressourcen. Die drei vorhandenen Zeilen

```
x_a + x_b <= 1
x_b + x_c <= 1
x_a + x_c <= 1
```

lassen x_a=x_b=x_c=0,5 zu. Eine bewiesene Konfliktclique liefert `x_a+x_b+x_c<=1`. Sie verkleinert die LP-Menge, ohne einen ganzzahligen Fahrplan auszuschließen. Ob solche nicht bereits implizierten Strukturen unser Root-LP tatsächlich bestimmen, ist auf dessen Support zu diagnostizieren.

Ein vollständiger Konfliktgraph mit allen Paaren oder allen maximalen Cliquen kann wiederum zu groß sein. Zunächst sind kleine, deterministisch vorbereitete lokale Konfliktblöcke sinnvoll; Gurobi bleibt der Suchalgorithmus. Physisch zulässiges Bypass-Überholen darf niemals pauschal als Konflikt kodiert werden. Auch dürfen keine zwei gemeinsam zulässigen Phasen derselben Kabine fälschlich unvereinbar werden.

### Netzwerkschnitte und Kapazitätsrundung

Atamtürk und Günlük behandeln insbesondere Projektion von Flüssen, Cutsets und Mixed-Integer-Rounding für kapazitierten Netzwerkentwurf.[^8] Achterberg und Raack zeigen, wie erkennbare Multicommodity-Strukturen zur automatischen Erzeugung von Schnitten genutzt werden können.[^9]

Eigene Übertragung: Für OD-Mengen, die einen bestimmten räumlichen beziehungsweise zeitlichen Schnitt passieren müssen, werden Bedienung, verfügbare Kabinenpassagen und Ressourcenfenster gemeinsam betrachtet. Die bloße Summierung bestehender Kapazitätszeilen verbessert den LP-Bound nicht. Interessant sind erst zusätzliche diskrete oder ressourcenübergreifende Konsequenzen.

Bei optionaler Bedienung ist besondere Vorsicht notwendig: Aus `Q*z + U >= D` darf nicht einfach `z >= ceil(D/Q)` werden. Der U-Term muss korrekt im Schnitt enthalten bleiben. Ebenso ist der All-Stop-Bound kein gültiger Skip-Stop-Cut. Nicht jeder fachlich sinnvolle Schnitt ist neu gegenüber den bereits eingebauten Solvercuts; das muss anhand der gemessenen LP-Wirkung überprüft werden.

## 5. Weitergehende Architektur: lokale Belegungszustände

Eine mögliche spätere Verschärfung lässt einen Teilpfad zusätzlich die Zielverteilung seiner Belegung darstellen. Bei Q=8 und m Zielklassen gibt es höchstens `binomial(8+m,m)` nichtnegative Belegungsvektoren mit Summe höchstens acht: bei m=2 sind es 45, bei m=4 bereits 495. Übergänge und Zeitschnittstellen erhöhen die Größe weiter.

Ein Skalar „aktuell fünf Personen an Bord“ reicht nicht: Er sagt nicht, an welchem Ziel STOP verpflichtend ist. Ein voller Zielvektor im gesamten Zeitnetz könnte dagegen Millionen Zustände erzeugen. Das wäre kein belegter Fortschritt gegenüber den heutigen 889.209 Variablen.

Zudem ist `Summe n_d <= 8, n_d>=0` für Einheitsplätze bereits die konvexe Hülle der isolierten ganzzahligen Beladungen. Nur diese Menge als Zustandsnetz zu enumerieren liefert keine stärkere lokale Relaxation. Ein sinnvoller Block müsste zusätzliche gekoppelte Anforderungen enthalten, etwa mehrere Stop-/Skip-Entscheidungen, Zielverpflichtungen oder Ressourcenkonflikte über mehrere Ereignisse. Erst ein gemessener fraktionaler Gegenfall rechtfertigt diesen Ausbau.

Die Konsolidierungs- und Layered-Graph-Literatur motiviert diesen Versuch, beweist aber keinen Gewinn für Seilbahnen. Daher: nachrangig gegenüber kompakter Nachfrage und konkreten Konfliktverschärfungen; keine vollständige neue Beladungs-Zeit-Expansion als erster Schritt.

## 6. Warum nicht einfach weniger Zeitpunkte oder vollständiges DDD?

Knotenaggregation in einem Zeitnetz ist häufig eine Relaxation, keine äquivalente Kompression. Das Entfernen von Zeitpunkten ist dagegen meist eine Einschränkung der Fahrplansuche. Beide Maßnahmen sind von rein algebraischer Verkleinerung zu unterscheiden.

Van Dyk und Koenemann zeigen für DDD mit Speichergrenzen, dass das vollständige Weglassen bestimmter Speicherbedingungen sehr schwache Relaxationen verursachen kann; sie entwickeln begrenzte Speicherrelaxationen und Projektionsargumente.[^10] Für die Seilbahn entspricht Exit-Waiting einer physisch blockierenden Einzelbelegung. Eine zeitliche Zusammenfassung muss diese Belegung und das maximale zusammenhängende Waiting respektieren.

Der vorhandene Phasenpilot hat bereits eine begründete Holding-Darstellung mit kumulierten Waiting-Grenzen. Sie sollte bei der nächsten Verkleinerung erhalten bleiben. Ein vollständiger adaptiver DDD-Controller wäre ein eigener Ausbau und ist für die hier vorgeschlagene Architektur nicht erforderlich.

## 7. Vergleich der Architekturentscheidungen

| Ansatz | Erwartete Größe | Erwartete LP-Stärke | Hauptrisiko | Priorität |
|---|---|---|---|---|
| P1: gemeinsame OD-Bordflüsse, getrennte Einstiege | deutlich kleiner; konkret gezählt | separat beweisen/messen | falsche Restweg-Aggregation | zuerst |
| P2: OD-Nachfrage-Wartenetz | weiterer Rückgang möglich | genaue Projektion prüfen | verlorene Gruppenbedingungen/Zielkosten | danach für `unserved` |
| Deterministische Teilketten substituieren | kleiner | bei exakter Substitution gleich | verlorene Ein-/Ausstiegsschnittstelle | mit P1 vorbereiten |
| Ganzzahligkeit nur am Einstieg | gleiche LP-Spaltenzahl | reine Relaxation unverändert | fraktionale Beförderung bei uneindeutigen Pfaden | nach P1 |
| Dominierte Ressourcenzeilen entfernen | kleiner | gleich | Koeffizienten statt Mengen übersehen | risikoarmer Einzeltest |
| Konfliktcliquen über Ressourcen | mehr ausgewählte Zeilen | kann stärker werden | große Konfliktstruktur | erster Bound-Test |
| Netzwerkschnitte mit Rundung | mehr ausgewählte Zeilen | kann stärker werden | optionales U falsch behandelt | nach Root-Diagnose |
| Lokale Belegungs-/Konfliktzustände | größer oder ersetzt Teilblöcke | nur bei zusätzlicher Kopplung stärker | Zustandsprodukt | bedingter späterer Test |
| Beliebige Zeitaggregation | kleiner | schwächer oder eingeschränkt | falscher globaler Bound | kein Ersatz |

Dies ist eine Einschätzung für die vorliegende Implementierung, kein aus Literaturdaten abgeleitetes Erfolgsranking.

## 8. Konkrete Abfolge und Zwischennachweise

1. **Architekturbaseline sichern.** Dasselbe R2-Netz und derselbe Seed bleiben Vergleichsgrundlage. Zählen nach Gruppen, OD, Arc-Typ und Zeilenfamilie; zusätzlich Presolve-Größen und Faktorisierungs-Nichtnullen erfassen. Die neue Darstellung muss sich gegenüber dem bereits vorhandenen Gurobi-Presolve lohnen.
2. **P1 als separaten Builder vorbereiten.** Kompatibilitätsklassen explizit definieren, Projektion/Lift und historische Replays implementieren. Kleine vollständig enumerierte Fälle vergleichen; keine großen Suchläufe vor Korrektheit.
3. **P2 als gesondertes Kapazitätsprofil prüfen.** Zwei unterschiedliche Freigaben, gleicher Tick, unbediente Restmengen und verschiedene Ziele als Gegenfälle. Bedingungen bei zukünftigen Gruppenfristen oder Sechs-Stationen-Richtungswahl ausdrücklich ablehnen, solange kein Beweis vorliegt.
4. **Gleiche LPs und native Suche messen.** Rootzeit, UB, LB, Zeit bis Verbesserung und tatsächliche Gesamtzeit getrennt auswerten. Gleiche Null-LP-Werte sind kein Beweis gleicher Polyeder; Tests brauchen auch Fälle mit nichttrivialem LP-Bound und unterschiedliche lineare Bewertungsrichtungen.
5. **Fraktionale Lösung erklären.** Kleine Ausschnitte identifizieren, die Bedienung ohne gemeinsam realisierbare Kabinenbewegungen ermöglichen. Erst dann kleine Konfliktcliquen oder andere gültige Verschärfungen auswählen. Bessere LP-Werte allein genügen nicht, wenn ihr Aufbau mehr Zeit kostet als die Suche gewinnt.
6. **Ganzzahligkeit verlagern und Kettenbereinigung einzeln testen.** Nicht gleichzeitig mit sämtlichen Verschärfungen, damit ihre Wirkung sichtbar bleibt.
7. **Lokale Zustandsblöcke nur bei konkretem Bedarf.** Belegen, welcher bislang zugelassene fraktionale Zusammenhang ausgeschlossen wird, und die projizierte Modellgröße vor Implementierung zählen.

Pflichttests umfassen Waiting-Freigabe, Ausstieg vor Ziel-Waiting, gleichzeitiges Aus-/Einsteigen, volle Kabinen, Rückkehr, letzte Ereignisse am Horizont, echte Überholung, keine zusätzlichen Runden/Umstiege sowie die ganzzahlige Odd-Cycle-Instanz. Die unabhängigen Validatoren arbeiten unverändert gegen die ursprüngliche Domäne.

Ein erster Erfolg wäre: wesentlich kleinerer tatsächlich gebauter und presolvter Block, gleicher gültiger Lösungsraum und früherer Eintritt in die ganzzahlige Suche. Eine Empfehlung für die Thesis verlangt darüber hinaus bessere validierte Bedienung oder bessere vergleichbare Schranken in wiederholten Versuchen. Eine kleinere Datei ist kein Suchfortschritt.

## 9. Code-Zuordnung und Betriebsformen

| Bereich | Bestehender Anknüpfungspunkt | Vorgeschlagene Verantwortung |
|---|---|---|
| Exakte physikalische Ereignisse | `reservoir_capacity/network.py` | Originalnetz und Ressourcengeometrie erhalten |
| Passagieraufbereitung | Gruppen-Schleife in `reservoir_capacity/model.py` | solverfreie OD-/Supportklassen, Nachfragezeitketten, Projektionsabbildungen |
| MIP-Aufbau | `build_model` in derselben Datei | getrennte Legacy-/Aggregationsbausteine, gemeinsamer Bewegungskern |
| Ressourcen | Intervallsweep im selben Builder | normalisierte Zeilensignaturen und belegte Konfliktgruppen |
| Historische Aggregation | `arc_flow_passenger_formulation.py` | Beweis-/Adaptermuster wiederverwenden; nicht blind Cabin-Visit-Blöcke übertragen |
| Export | `reference_values`, `extract`, Reservoir-Zertifikate | Gruppen- und Ride-Lift mit physikalischer und ganzzahliger Validierung |
| Vergleich | bestehende Capacity-Runner | unveränderte Instanzen/Seeds, neue Modellprofile und Fingerprints |

Fixed-K kann vom gleichen Prinzip profitieren, benötigt aber seine eigenen Lebenszyklusgrenzen. Beim Doppelring muss die Nachfragewarteschlange vor der Richtungswahl gemeinsam sein, damit dieselben Personen nicht zweimal bedient werden. Danach bleiben richtungsspezifische Bordflüsse erforderlich. Journey-Time braucht zusätzlich eine exakte Abrechnung der bedienten Freigabegruppen. Diese drei Erweiterungen sind nicht automatisch durch den R2-Kapazitätsnachweis abgedeckt.

## Quellen und Evidenzzugang

Die Literaturbefunde oben sind von den ausdrücklich als Übertragung bezeichneten Ropeway-Konstruktionen getrennt. Quellenabruf und Codeabgleich: 11.09.2026. Die Publikationen behandeln andere Problemklassen; ihre Rechenzeitgewinne werden nicht auf Ropeway hochgerechnet.

[^1]: De Lima, V. L.; Alves, C.; Clautiaux, F.; Iori, M.; Valério de Carvalho, J. M. (2022). *Arc flow formulations based on dynamic programming: Theoretical foundations and applications*. EJOR 296(1), 3–21. [DOI](https://doi.org/10.1016/j.ejor.2021.04.024), [Autorenpreprint, Volltext](https://arxiv.org/pdf/2010.00558). Insbesondere Abschnitte 3–6 zu Stärke, Zustandsrelaxation und Lösungsverfahren.

[^2]: Kazemi, A.; Le Bodic, P.; Ernst, A. T.; Krishnamoorthy, M. (2021). *New partial aggregations for multicommodity network flow problems: An application to the fixed-charge network design problem*. COR 136, 105505. [DOI](https://doi.org/10.1016/j.cor.2021.105505), [Preprint unter früherem Titel, Volltext](https://arxiv.org/pdf/2101.03707). Abschnitte 2–4; PA, PAi und PAe, Theoreme zur LP-Hierarchie. Die allgemeinen Ergebnisse werden nicht mit unserem Spezialfall identischer OD-Freigabeklassen gleichgesetzt.

[^3]: Brandão, F.; Pedroso, J. P. (2016). *Bin packing and related problems: General arc-flow formulation with graph compression*. COR 69, 56–67. [Verlagsseite](https://www.sciencedirect.com/science/article/pii/S0305054815002762), [Autorenpreprint, Volltext](https://arxiv.org/pdf/1310.6887). Insbesondere Abschnitt 3, Eigenschaften 3 und 4 zur Erhaltung gültiger Muster.

[^4]: Kliewer, N.; Mellouli, T.; Suhl, L. (2006). *A time–space network based exact optimization model for multi-depot bus scheduling*. EJOR 175(3), 1616–1627. [DOI](https://doi.org/10.1016/j.ejor.2005.02.030). Verlagsabstract und indexierter Einführungstext; kein vollständiger Beweis aus dem Volltext übernommen.

[^5]: Hewitt, M.; Lehuédé, F. (2022, Working Paper). *New Formulations for the Scheduled Service Network Design Problem*. [Autorenabstract/SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4232772), [DOI](https://doi.org/10.2139/ssrn.4232772). Ergänzend: Hewitt (2023), *Consolidation-Based Modeling for the Scheduled Service Network Design Problem*, [Autoreninstitution](https://scholars.luc.edu/en/publications/consolidation-based-modeling-forthescheduled-service-network-desi), DOI 10.1007/978-3-031-38145-4_1. Zugang zur Zusammenfassung/Metadaten; keine überprüften numerischen Detailvergleiche verwendet.

[^6]: Gouveia, L.; Leitner, M.; Ruthmair, M. (2019). *Layered graph approaches for combinatorial optimization problems*. COR 102, 22–38. [DOI](https://doi.org/10.1016/j.cor.2018.09.007), [Volltext im Universitätsrepository](https://research.vu.nl/ws/portalfiles/portal/123183179/Layered_graph_approaches_for_combinatorial_optimization_problems.pdf).

[^7]: Cacchiani, V.; Caprara, A.; Toth, P. (2010). *Non-cyclic train timetabling and comparability graphs*. OR Letters 38(3), 179–184. [DOI](https://doi.org/10.1016/j.orl.2010.01.007), [Volltext](https://cedric.cnam.fr/~bentzc/INITREC/Files/CB34.pdf). Kompatibilitätsbasierte Formulierungen auf stark belasteten Instanzen. Die oben angeführte Dreierclique ist eine eigene elementare Illustration, keine behauptete gemessene Ropeway-Struktur.

[^8]: Atamtürk, A.; Günlük, O. *Multi-Commodity Multi-Facility Network Design*. [Autorenpreprint, 2017](https://arxiv.org/abs/1707.03810), [Volltext auf Autorenwebseite](https://atamturk.ieor.berkeley.edu/pubs/mcmfnd.pdf). Insbesondere Abschnitt 3 zu Projektion, Netzverkleinerung und MIR. Keine ungeprüfte Übernahme von Formeln mit verpflichtender Gesamtbedienung.

[^9]: Achterberg, T.; Raack, C. (2009/2010). *The MCF-Separator – Detecting and Exploiting Multi-Commodity Flow Structures in MIPs*. ZIB-Report 09-38; Mathematical Programming Computation. [Autorenveröffentlichung](https://optimization-online.org/2009/11/2475/), [Volltext](https://optimization-online.org/wp-content/uploads/2009/11/2475.pdf). Netzwerkstruktur und Schnitte; kein Nachweis, welche identischen Verfahren die aktuelle Gurobi-Version intern verwendet.

[^10]: Van Dyk, M.; Koenemann, J. (2023, Preprint). *Dynamic discretization discovery under hard node storage constraints*. [Volltext](https://arxiv.org/pdf/2303.01419). Speicherrelaxation und Projektion, insbesondere Abschnitt 3.2 und Anhänge A/B. Packet-Routing-Resultate ersetzen keinen Seilbahn-Waitingnachweis.
