# Evolutionäre Musterwahl mit gemeinsamer No-Wait-Dispatchoptimierung

## Fragestellung

### Präzisierung nach Nutzerklärung

Die Evolution legt die **Dispatchreihenfolge** der Muster fest. CP-SAT optimiert die Dispatchzeiten unter dieser Reihenfolge. Nach dem Dispatch dürfen sich Kabinen überholen; es gibt keine gemeinsame Reihenfolge auf den Stationsressourcen. Die kurz begonnene Änderung zu frei vertauschbaren Dispatches wurde zurückgenommen und nicht als Suchlauf gestartet. Die erneute Baseline wurde auf Nutzerwunsch beendet; fortgesetzt wird ausschließlich Pattern-only. Frühere Unzulässigkeitsmeldungen betreffen die jeweilige feste Dispatchmusterfolge unter No-Wait, nicht allein ihre Musterhäufigkeiten.

Der bisherige evolutionäre Ansatz verändert Haltemuster und Dispatchzeiten zugleich. Auf R2/K38 fand er zwar gültige gemischte Fahrpläne, verbrauchte aber einen großen Teil der Suche damit, bereits durch unpassende Dispatchgene verursachte Konflikte zu reduzieren. Dieser Pilot entfernt die Zeiten aus dem Genom. Ein Individuum ist nur noch die geordnete Folge von 38 Haltemustern; CP-SAT wählt für jede Folge gemeinsam die Dispatchzeiten und die zur Dispatchzeit passende Rundenzahl.

Der Pilot ändert die physikalische Domäne nicht. Er nutzt R2 mit 3.074 Personen, K=38, das Dispatchfenster 0–300 s, den aktuellen gemeinsamen Reservoirport, Single-Use-Betrieb und den Katalog `relevant`. Waiting und variable Flotte bleiben ausgeschlossen.

## Modell und Varianten

`PatternSequenceGenome` enthält ausschließlich `pattern_ids`. Position i bezeichnet die i-te dispatchte Kabine. Die Evolution verwendet Population 32, acht Nachkommen sowie 50 % lokale, 30 % Block- und 20 % globale Änderungen. Die Anfangspopulation enthält nachfragebezogene Mischungen und Zufallsfolgen, aber keine gezielt eingesetzte All-Stop- oder bekannte Skip-Stop-Lösung.

Der spezialisierte Linienbuilder erzeugt je Kabinenslot nur Templates des vorgegebenen Musters. Dispatchzeit und Rundenzahl bleiben Solverentscheidungen. Native optionale Ressourcenintervalle erhalten die vollständigen Port-, Stations-, Zustands- und Rückkehrbedingungen. Dadurch werden keine Dispatchzeitpunkte aufgezählt und keine physische Reihenfolge außerhalb der Dispatchreihenfolge festgelegt.

Zwei Auswertungen bleiben getrennt:

- `timing_then_passengers`: CP-SAT sucht die erste gültige Bewegung; danach optimiert das bestehende Gurobi-IP die Passagiere für genau dieses Timing.
- `joint_service`: CP-SAT optimiert Dispatch, Rundenzahlen und ganzzahlige Passagiermengen gemeinsam.

Ein Ergebnis des ersten Verfahrens ist nur für das gefundene Timing optimal bewertet. Es ist kein Bedienungsoptimum über alle Dispatchzeiten derselben Musterfolge.

## Suche und Status

Gültige Folgen werden nach bestätigter Bedienung selektiert. Für Folgen ohne Lösung unterscheidet der Lauf `PATTERN_UNKNOWN` und bewiesenes `PATTERN_INFEASIBLE`. Diese Gruppen erhalten eigene vielfältige Explorationsplätze über Hamming-Abstand; es wird keine Konfliktzahl erfunden. Identische Musterfolgen werden innerhalb eines Laufs gecacht.

Jede Bewertung protokolliert Vorbereitung, Modellbau, Suche, Passagierzuordnung und Validierung sowie Modellgröße, nativen Status, gefundene Dispatchzeiten und Musterzusammensetzung. Das Live-Dashboard zeigt die Timingstatus statt der Konfliktkurve als Suchsignal.

## Korrektheits- und Vergleichsplan

Vor R2 müssen kleine Fälle beide Untermodelle gegen bestehende Modelle reproduzieren. Pflichtprüfungen umfassen Genomidentität, feste Länge, Template-Spezialisierung, No-Waiting, Ressourcen und Rückkehr, Passagierganzzahligkeit, Timeoutstatus sowie einen freien Fall ohne Hint.

Für das Screening werden eine aktuelle gültige K38-Folge, zwei konfliktarme unterschiedliche Folgen und K38 All-Stop jeweils mit beiden Untermodellen und 30 s geprüft. Danach laufen der bisherige Ansatz mit Zeitgenen und der neue Ansatz je 25 Minuten aus denselben 32 Musterfolgen. Kein Lauf erhält eine bekannte gute Lösung. Das Gesamtbudget einschließlich Einfrieren und Auswertung beträgt 60 Minuten.

Der Pilot ist positiv, wenn Pattern-only mindestens zehn weitere Personen bedient oder die Endqualität des Vergleichslaufs in höchstens halber Zeit erreicht und am Ende nicht schlechter ist. Ein einzelner Seed bleibt ein vorläufiger Befund.

## Umsetzungsstand

- [x] Pattern-only-Genom und Operatoren
- [x] slot-spezialisierter Linien- und Passagierbuilder
- [x] getrennte Timing- und Joint-Untermodelle
- [x] Statusgruppen, Hamming-Diversität und Cache
- [x] Runnerargumente und Evaluate-only-Pfad
- [x] Ereignisprotokoll und Dashboardstatus
- [x] kleine Integrations- und Regressionsprüfungen
- [ ] R2-Screening und formaler 60-Minuten-Vergleich
- [ ] Ergebnisbericht mit Fortschrittskurven

## Festgelegter Thesis-Lauf T5R/F3/K62

Der Lauf beginnt frisch. Weder All-Stop noch ein zuvor gefundener Skip-Stop-
Fahrplan werden initialisiert. Die deterministische Anfangspopulation darf nur
aus Nachfrage und Musterkatalog abgeleitete Linienmischungen enthalten.

Vier Musterfolgen werden gleichzeitig in getrennten Prozessen bewertet. Jede
Bewertung erhält höchstens 30 Sekunden: CP-SAT verwendet drei Worker für
Dispatchzeiten, Rundenzahlen und No-Wait-Machbarkeit; nur nach einem gültigen
Timing optimiert das feste Gurobi-Passagier-IP mit einem Thread. Die globale
Prozessbaumgrenze bleibt 32 GiB.

Sobald der Lauf selbst den ersten gültigen Fahrplan findet, wechselt die
Variation überwiegend auf kleine Reihenfolge-, Einzelmuster- und
Linienanteilsänderungen. Ein Kind darf die Dispatchzeiten seines gültigen
Elternplans als unverbindlichen CP-SAT-Hint erhalten. Der Hint fixiert keine
Zeit und stammt ausschließlich aus demselben Lauf.

Primär wird die Bedienung maximiert; bei gleicher Bedienung minimiert die
Passagierzuordnung die Journey Time. Die beste Bewegung wird am Ende mit einem
reservierten 20-Sekunden-Gurobi-Lauf nachbewertet. Der eigentliche Suchlauf
erhält 30 Minuten Gesamtwandzeit einschließlich dieser Nachbewertung.

## Variable aktive Flotte (16.09.2026)

Der anschließende F3-Pilot verwendet 1 bis 62 aktive Kabinen. K ist die Länge
 der geordneten Musterfolge; es gibt keine inaktiven Slots und kein `no_run`.
CP-SAT optimiert alle Dispatchzeiten für genau diese aktive Folge. Der
unveränderte No-Wait-Lebenszyklus bleibt maßgeblich.

25 % der Variationen ändern die Flotte: davon 80 % um eine Kabine und 20 %
zu einer gleichverteilt gezogenen Größe im erlaubten Bereich. Entfernen erhält
die relative Reihenfolge der übrigen Kabinen; Einfügen wählt Muster und Position.
Die übrigen Variationen bearbeiten Muster und Reihenfolge. Acht nachfragebezogene
Startfolgen verteilen sich über die Flottenspanne; weitere Kandidaten werden
zufällig gezogen. Kein importierter Fahrplan und kein gezielter All-Stop-Seed.

Bis zu acht gültige Populationsplätze schützen über die vorhandenen K-Werte
verteilte Vertreter. Weitere gültige Plätze werden nach Bedienung und dann
Journey Time gefüllt; die bisherigen Status-Explorationsplätze bleiben bestehen.
Bei gültiger Elternwahl wird zur Hälfte eine Flottengröße gleichverteilt gewählt
und deren bester Populationsvertreter verwendet, sonst das Bedienungsturnier.
Das bestehende Ergebnisarchiv protokolliert unabhängig davon den besten Plan je K.
Nach Größenänderungen wird kein Dispatch-Hint des anders dimensionierten Elternteils
übergeben. Größere/kleinere Untermodelle werden vor dem Aufbau passend spezialisiert.

Lauf: 30 Minuten inklusive 20 Sekunden abschließender Passagierbewertung,
vier parallele Kandidaten mit je drei CP-SAT-Workern, ein Gurobi-Thread je
Passagier-IP, 30 Sekunden Kandidatenlimit, 32 GiB Prozessbaumlimit. 21 relevante
Muster, F3 mit 7.153 Personen, Dispatchfenster bis 732 Sekunden, Seed 0.
Der vorherige K62-Lauf wurde auf Nutzerwunsch bei 3.864 bedienten Personen gestoppt.
Neue Tests prüfen variable Längen, unterschiedliche Elternlängen, Bereichsgrenzen,
beide Variationsphasen sowie eine frei gefundene und unabhängig validierte Lösung.
