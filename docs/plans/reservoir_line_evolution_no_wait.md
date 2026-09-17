# Evolutionäre Reservoir-Linienplanung: No-Wait-Pilot

Stand: 14. September 2026. Die Implementierung ist abgeschlossen; die
einstündige Vergleichskampagne ist der noch auszuführende Teil dieses Plans.

## Forschungsfrage

Der Pilot prüft, ob eine äußere populationsbasierte Suche die für die
Kapazität entscheidenden Kombinationen aus Flottengröße, geordneten
Haltemustern und Dispatchzeiten zuverlässiger findet als das monolithische
Linienmodell. Er ist eine Heuristik für gute gültige Fahrpläne. Er liefert
keine globale Schranke für die Fahrplansuche.

R0 und R2 verwenden 3.074 Personen, höchstens 50 verfügbare Kabinen und den
aktuellen Single-Use-Reservoirvertrag. Eine eingesetzte Kabine fährt ohne
Waiting kontinuierlich bis zur ersten vollständigen Umlaufrückkehr am oder
nach der Bedienungsdeadline. Alle Dispatches liegen im bestehenden
Dispatchfenster. Die erste Abfahrt ist als gemeinsame Phase frei.

## Implementierte Darstellung

Ein Individuum ist die variable Sequenz

\[
(p_1,\ldots,p_K;\phi;x_1,\ldots,x_{K-1}).
\]

Die Abfahrten werden mit dem auf das Dispatchraster aufgerundeten physischen
Port-Headway \(h\) rekonstruiert:

\[
d_1=\phi,\qquad d_{i+1}=d_i+h+x_i.
\]

Phase und Zusatzabstände sind nichtnegative Vielfache des Instanzrasters.
Die letzte Abfahrt darf vor dem Ende des Dispatchfensters liegen. Inaktive
Füllgene gibt es nicht; Identität und Cache verwenden ausschließlich die
tatsächliche Sequenz.

Der Decoder wählt für Muster und Dispatch genau ein bestehendes
Lebenszyklustemplate, berechnet sämtliche Besuche, Ressourcenintervalle,
Zustands- und Portereignisse und meldet konkrete Überlappungszeugen. Ein
unabhängiger Durchlauf des bestehenden Reservoirvalidators ist ein
zusätzliches Zulässigkeitsgate. Der Decoder ruft keinen Optimierungssolver
auf.

Für eine gültige Bewegung baut die Bewertung ein spezialisiertes Gurobi-IP
aus kanonischen Ride-Mengen, Nachfragegrenzen und Abschnittskapazitäten. Es
enthält keine Bewegungsvariablen und keine Reisezeitprodukte. Aufbau und
Lösung erhalten zusammen zwei Sekunden. Incumbent und native Schranke werden
getrennt gespeichert. Der Fahrplan-Cache ist pro Suchlauf isoliert.

## Suchverfahren

`pymoo` 0.6.1.6 betreibt den GA mit Population 32 und acht Nachkommen. Die
Profile `local`, `local_block` und `mixed_global` aktivieren gezielte
Ein-Halt-Nachbarn, benachbarte Vertauschungen, Phase und Abstände,
Einfügen/Entfernen, Blockersetzung sowie Flottensprünge und Neustarts. Die
tatsächliche Herkunft jedes ausgewerteten Individuums wird protokolliert.

Die Survival-Auswahl hält bis zu 24 beste gültige Individuen. Acht feste
K-Bereiche bevorzugen jeweils den kollidierenden Vorschlag mit der kleinsten
Verletzung; freie Plätze werden anschließend mit weiteren Kandidaten gefüllt.
Optimistische OD-Abdeckung kollidierender Vorschläge wird nie als Bedienung
ausgegeben.

Zufallssuche und Optuna TPE 4.5.0 verwenden denselben Sampler, Decoder,
Validator und Passagierbaustein. Der bestehende native Linienplaner verwendet
`intervals`, `shared_rounds`, `relevant` und `exact_service`. Alle Verfahren
erhalten denselben erneut geprüften All-Stop-Startplan. Historische gute
Skip-Stop-Pläne bleiben externe Referenzen.

## Korrektheitsgates

Die automatischen Tests decken leere und einzelne Flotten, volle
Dispatchfenster, das Dispatchraster, Ein-Halt-Nachbarn, alle Operatorprofile,
solverfreies Dekodieren, unabhängige Bewegungsprüfung, ganzzahlige
Passagieroptima, Cacheidentität und eine positive Suche ohne guten Hint ab.
Die bestehenden Reservoir- und Linienmodelltests bleiben zusätzlich
maßgeblich. R0/R2 werden vor der Kampagne erneut gebaut; R2 muss weiterhin 14
relevante Muster besitzen.

## Eingefrorene Kampagne

`benchmarks/run_reservoir_line_evolution_campaign.py` überwacht höchstens
3.600 Sekunden, 32 GiB Prozessbaum-RSS und systemweiten Speicherdruck. Zuerst
werden die All-Stop-Referenzen je Fall bis zu 120 Sekunden erneut bewertet.
Danach laufen auf R0 und R2 je 120 Sekunden:

- GA `local`, `local_block` und `mixed_global`;
- Zufallssuche;
- Optuna TPE;
- nativer Linienplaner.

Auf R2 werden das beste GA-Profil, die bessere Blackbox-Kontrolle und der
native Linienplaner mit Seeds 1 und 2 je 240 Sekunden bestätigt. Auswahl und
Erfolgskriterien folgen dem eingefrorenen Benutzerplan. Jeder Lauf speichert
Argumente, Versionen, Quellenhashes, Modellidentität, Events, gültige
Bedienung, Konflikte, untersuchte K und Zeitanteile.

Die Ausführung erfolgt mit:

```bash
uv run --extra evolutionary python benchmarks/run_reservoir_line_evolution_campaign.py \
  --r0-reference <R0-skip-stop-checkpoint> \
  --r2-reference <R2-skip-stop-checkpoint> \
  --r0-all-stop <R0-all-stop-checkpoint> \
  --r2-all-stop <R2-all-stop-checkpoint> \
  --dispatch-window-end 300 \
  --output <neuer-ergebnisordner>
```

Ergebnisse werden nach Abschluss in
`docs/findings/reservoir_line_evolution_no_wait_results.md` zusammengefasst.

## Isolierter Test der Elternwahl (14. September)

Nach Nutzerentscheidung wird zuerst ausschließlich die Elternwahl geändert.
`--exploration-parent-probability 0` verwendet die bisherige Tournament-Regel;
`0.25` wählt pro Elternplatz mit 25 % Wahrscheinlichkeit zwei unzulässige
Populationsmitglieder zum Turnier. Dort entscheidet lexikografisch die
Konfliktzahl, danach die gesamte Überlappungsdauer, danach Zufall. Ohne
unzulässige Mitglieder fällt die Auswahl auf das Standardturnier zurück.
Die Population enthält auch ihre nach K diversifizierten Explorationsplätze.
Alle übrigen Ziele, Survival-Regeln und Operatoren bleiben für diesen Test gleich.

Der isolierte Vorvergleich umfasst zwei sequenzielle R2-Läufe mit Seed 0,
60 Sekunden Gesamtbudget je Lauf, `mixed_global` und identischem gültigen
All-Stop-Phasenplan. Er misst Elternanteile sowie zeitabhängige gültige
K-Frontiers, Mustermengen und Konfliktdaten. Ein einzelner Seed erlaubt keine
Performanceempfehlung. Die umfassende Kampagne wurde für diesen gezielten
Test angehalten; ihre Teilresultate bleiben erhalten.

## Gekoppelte Variation und Seedvergleich

Die nächste Fassung wählt pro Nachkomme genau eine Variationskategorie gemäß
Profil. Die frühere vorgeschaltete 90-%-Blockkreuzung entfällt. Blockvariation
wählt zwischen gekoppelt übernommenem Elternblock und einer auf den Block
begrenzten Mutation. Muster und interne Dispatchabstände werden gemeinsam
übertragen; außerhalb des Blocks bleiben Abfahrten erhalten. Unpassende
Blockanschlüsse erzeugen keinen global neu gezeichneten Ersatzfahrplan.
Lokales Einfügen erhält bestehende Abfahrten und kann ohne zulässigen Platz
unverändert scheitern. Vollständige Neuziehungen bleiben globale Operationen.

Survival erhält 16 beste gültige Individuen, bis zu acht weitere gültige
unterschiedliche K-/Mustermengen sowie bis zu acht explorative K-Vertreter.
Unbesetzte Plätze werden aufgefüllt. Die globale Zielfunktion bleibt unserved.
Das Passagierzeitlimit wird bis zur tatsächlich verwendeten Bewertung gereicht.
Fünfsekündliche Populationsereignisse enthalten geordnete Muster, Dispatchzeiten,
Bedienung, Konflikte und Elternzähler. Verbesserte Konfliktfrontiers werden
nun auch als zeitliche Events persistiert.

`benchmarks/run_reservoir_line_seed_comparison.py` friert die Quellen ein und
führt sechs sequenzielle R2-Läufe aus: mit/ohne importierten All-Stop-Seed,
Seeds 0/1/2, je 300 Sekunden inklusive Aufbau, abwechselnde Reihenfolge.
All-Stop bleibt in beiden Gruppen ein erlaubtes Muster. Population 32,
Nachkommen 8 und Elternexploration 25 % bleiben gleich. Der externe gemeinsame
All-Stop-Plan bleibt als Referenz in beiden Fällen gespeichert. Die Auswertung
vergleicht gültige K-Frontiers und Populationen nach 30/60/120/300 Sekunden.
Maximal 31 Minuten einschließlich Quellenkopie und Abschluss; keine zusätzlichen
Langläufe ohne Befundentscheidung. Ausgabe: campaign.json, summary.json,
report.md sowie vollständige Events und Checkpoints je Versuch.
