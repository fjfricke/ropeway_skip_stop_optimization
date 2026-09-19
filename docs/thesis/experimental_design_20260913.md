# Versuchsplan: Wann lohnt sich Skip-Stop?

Stand: 13.09.2026. Entscheidungsvorlage; dieser Plan startet keine Rechenläufe.
Grundlage sind Codelektüre, vorhandene Messdaten und die bisherigen Szenariopläne.
Die Budgets unten sind Vorschläge für die nächste Kampagne, keine neue Laufautorisierung.

## Bestätigte Integrationsentscheidungen — 14.09.2026

Maßgeblich sind die [Antworten auf die 21 Integrationsfragen](experiment_definition_register_20260913.md#verbindliche-antworten-zur-integration--14092026).
Sie ersetzen widersprechende Vorschläge weiter unten.

- **Zwölf Hauptgruppen auf G500/P0:** acht Kapazitätsgruppen T5R/T6R ×
  F0/F2/F3/F4 und vier Journey-Gruppen T5R × F0/F2/F3/F4. Je Gruppe mehrere
  feste K, gegebenenfalls mehrere Nachfragelevel, und Wiederholungen.
- **Evolution:** kleiner deterministischer Katalog, Muster- und Dispatchgene,
  Intervall-Decoder, genau K aktive Kabinen, durchgehender Single-Use-Betrieb
  bis zur ersten vollständigen Rückkehr am/nach Bedienungsdeadline. No-Wait;
  keine Reparaturstufe. Drei Seed-Reihen.
- **Journey:** Labelled Arc-Flow mit festen Starts und No-Wait, U=0;
  Nachfragebasis kappa_AS(K_ref), K_ref vor Hauptläufen kalibrieren.
- **Startinformation:** kein vorgegebener guter Plan am Reihenbeginn.
  Eigene Lösungen dürfen innerhalb derselben Seed-Reihe an spätere K-Stufen
  weitergegeben werden, soweit korrekt übersetzbar. Exaktes K und feste Starts
  erneut prüfen; kumulierte Suchzeit und übernommene Werte getrennt berichten.
- **Referenz:** automatische All-Stop-Kalibrierung, ausdrücklich auch offene
  Kapazitätsintervalle zulassen. Referenzpläne nicht automatisch als Suchseeds
  einsetzen.
- **Frontend:** englisch, rein lesend, lokal und mit teilbaren statischen
  Ergebnisdaten; eingefrorene Thesisfälle, explorative Fälle und historisches
  Archiv getrennt. Kein Laufstart/-stopp im Frontend. Bestverbesserungen,
  aggregierte Suchhistorie, synchronisierte Replays und wissenschaftliche
  Exporte vorsehen.
- **Nicht im Paket:** T6L, neue ungleiche Längen, Waiting und automatische
  zusätzliche Geometrie-/T6R-Journey-Kampagnen. Bestehende Längenprofile als
  Kontrollen erhalten.

Anschließend bestätigt sind **höchstens zwei Stunden Wandzeit für die Kalibrierung**.
Der [Integrations- und Testplan](../plans/thesis_experiment_frontend_integration_20260914.md)
beschreibt Code, Frontend, Zwischentests und Budgetaufteilung. Noch zu beziffern
sind die Gesamtbudgets für Hauptkampagnen.
Konkrete K-Leitern, K_ref, Katalogregel und endgültige Nachfrageauflösung werden
im Umsetzungsplan beziehungsweise anhand der begrenzten Kalibrierung festgelegt.
Ältere Zwei-Stunden-Budgets werden nicht still als neue Laufautorisierung übernommen.

## Frühere Methodenentscheidung und Compute-Prüfung — 14.09.2026

Dieser Abschnitt hat Vorrang vor den älteren Stufen/Budgets weiter unten.
Physik und Nachfrage richten sich nach dem [Entscheidungsregister](experiment_definition_register_20260913.md),
insbesondere den dort bestätigten kontinuierlichen Nachfragefunktionen und der
Richtungsfilterung. Alte Batchdefinitionen, Startphase 0 und Doppelringvorschläge
weiter unten sind historische Planungsstände, keine neuen Freigaben.

**Nachfolgende Geometriefreigabe:** G500 (gleichmäßig 500 m freie Seilstrecke)
ist die gemeinsame Hauptgeometrie für Journey und Kapazität. Der Wert ist an
der unteren veröffentlichten Stationsdistanz von [Câble C1: 500–1.800 m](https://www.iledefrance-mobilites.fr/le-reseau/projets/cablec1/mediatheque/kit-presse-c1)
orientiert. Das ist keine universelle Untergrenze und kein exakter C1-Nachbau;
bei uns kommen Stationswege separat hinzu. Bisherige G300/G800-Messwerte bleiben
Kontrollen, keine gemessene G500-Performance. Der neue Profiladapter und die
All-Stop-Referenzen müssen vor Kampagnenbeginn implementiert/geprüft werden.

### Festgelegt: zwei Skip-Stop-Hauptmethoden plus All-Stop-Referenz

| Studie | Skip-Stop-Verfahren | Primärziel | Vergleich |
|---|---|---|---|
| Niedrige Nachfrage / kleinere K | vollständiger Labelled Arc-Flow, feste Starts, Fixed-K, No-Wait, freie STOP/SKIP je Besuch | Journey Time mit U=0 | All-Stop bei identischem K und Startzustand; gesättigtes phasenoptimiertes AS zusätzlich |
| Nachfrage an/über AS-Kapazität, K an/über K_AS | Evolution mit kleinem vorab begründetem Katalog wiederholter Stationsmasken | `unserved`; vollständige Bedienung als Kapazitätszeuge | phasenoptimiertes regelmäßiges No-Wait-AS unter der gemeinsamen Geometrie/Nachfrage/Zeitachse |

### Nachfolgende Festlegung: feste K-Reihen und Referenznachfrage

Beide Hauptmethoden werden über mehrere **feste K je Einzelversuch** untersucht.
Auch die evolutionäre Hauptreihe verwendet keine freie K-/Kmax-Entscheidung
innerhalb eines Laufs. Die Nachfrage bleibt innerhalb einer K-Reihe konstant.

- **Journey:** `N_J = kappa_AS(K_ref)` für dasselbe Nachfrageprofil und den
  festgelegten All-Stop-Referenzvertrag. K_ref ist ein vor der Hauptreihe
  festzulegender Referenzwert. Seine numerische Wahl bleibt bis zur Größenprüfung
  offen; der diskutierte Wert `floor(K_AS/2)` ist noch keine automatisch
  eingefrorene Vorgabe. Dies ersetzt die ältere Regel
  `N_J = 0.5 * kappa_AS(K_min)`. Primäre Journey-Vergleiche verlangen U=0 auf
  beiden Seiten; eine Referenz mit optimierter Phase ersetzt nicht den
  Vollbedienungscheck bei den tatsächlich gemeinsamen festen Starts.
- **Kapazität:** erste Nachfragebasis `N_C = kappa_AS(K_AS)` bei voller
  regelmäßiger All-Stop-Flotte. Weitere Laststufen liegen darüber. Je Laststufe
  werden mehrere feste K verglichen, ohne gleichzeitig die Nachfrage zu ändern.
- Konkrete K-Punkte, Laststufen, Initialisierungsregel und eventuelle Übergabe
  von Lösungen zwischen K bleiben offen. Fortgesetzte Suche und unabhängige
  K-Versuche müssen getrennt berichtet werden; ein K-Plan ist nicht automatisch
  ein zulässiger Startplan für K+1.

`kappa_AS` bezeichnet vollständig bedienbare Profilnachfrage, keine pauschale
Personen-pro-Stunde-Kennzahl. Offene Kapazitätsintervalle werden als solche
behandelt. Die Zahl der Einzelversuche folgt aus Szenarien × Laststufen ×
K-Punkten × Wiederholungen; neun Kerngruppen sind keine neun Läufe.

Die evolutionäre Methode ist eine Heuristik ohne garantierten
Approximationsfaktor. Native Linienplanung, große freie CP-SAT-Modelle und
andere Solverfamilien bleiben Diagnose-/Vergleichswerkzeuge und historische
Befunde; sie sind nicht zusätzliche verpflichtende Hauptreihen.
Ein kleiner Katalog gehört jetzt zur Hauptmethode und ist nicht bloß eine
Seedhilfe für eine zwingend folgende große `relevant`-Suche.

Implementierungsdetail vor Kampagnenfreigabe: Der aktuelle
`run_reservoir_line_evolution.py` bereitet den Katalog noch fest als `relevant`
vor. Der kleine Hauptkatalog muss dort beziehungsweise über die gemeinsame
Fallkonfiguration ausdrücklich auswählbar werden. Die heutige Planentscheidung
behauptet nicht, dass diese Runneranbindung bereits fertig ist.

Der Katalog muss für jedes Nachfrageprofil durch dieselbe vorab festgelegte
Regel entstehen. Keine nach beobachtetem Ergebnis ausgewählten Masken. Bei F2
ist All-Stop plus OD-Endpunktmasken ein plausibler Start; bei F0/F4 kann schon
dieser Katalog größer sein. Exakte Regel, Pflichtterminals, Duplikatentfernung
und gegebenenfalls Obergrenze sind noch gemeinsam festzulegen. Bekannte
BD/CE-Erfolge sind keine Evidenz für eine freie Entdeckung aus allen Masken.

### Größen und Zeiten: gemessen versus abgeleitet

Neue Thesis-Physik: 6 m/s Seil, 0,3 m/s Plattform, zehn Plätze; STOP 63,0667 s,
SKIP 10,1517 s. Quellen und idealisierte Stationsannahmen bleiben im
Entscheidungsregister §§6–8 dokumentiert. Historisches R2 mit 5 m/s, acht Plätzen
und K_AS=38 ist nur Regression, keine Ersatzgeometrie der Thesis.

| Neue Geometrie | AS-Umlauf | Gesättigte regelmäßige AS-Flotte | Gesamter Kapazitätszeitraum bei C_AS Warmup + 45/15 min + C_AS Recovery |
|---|---:|---:|---:|
| T5R/G300 | 9,42 min | 48 | 78,84 min |
| T5R/G800 | 16,37 min | 84 | 92,73 min |
| T6R/G300 | 11,31 min | 58 | 82,61 min |
| T6R/G800 | 19,64 min | 101 | 99,28 min |

Die letzte Spalte ist aus der aktuellen Zeitkonfiguration abgeleitet, keine
Solverlaufzeit. 45/15 min meint Nachfragefreigabe plus Fahrgastabschluss;
Warmup und Rückkehr kommen hinzu. Journey T5R/G300 mit zwei Umläufen Nachfrage
plus derzeit 15 min Completion umfasst etwa 33,84 min Modellhorizont.

Messungen aus der [Thesis-Kalibrierung](../findings/thesis_calibration_results_20260914.md):

- T5R/G300, F3/P0, 31 Personen, Arc-Flow K1/K5/K20: Optima nach 2,5/3,5/35,5 s;
  K20-Wiederholungen 26,8/28,1 s. Bei K20 rund 188.405 binäre/ganzzahlige
  Variablen zusammen und 268.767 Constraints. Das stützt die kleine Journey-Reihe.
- T5R/G800/F2, 15-s-Nachfrage, natives Linienmodell Kmax84: `shared_rounds`
  1,59 Mio. Variablen/4,88 Mio. Constraints; `shared_rides` 218.988/2,82 Mio.
  Beide lieferten im kurzen Vergleich schwache Bedienung. Bei Kmax280 wuchs
  `shared_rides` auf 9,38 Mio. Constraints. Das ist **kein Größenmaß der Evolution**.
- Historisches R2, fixe K38, alle 14 Muster, native integrierte CP-SAT-Suche
  ohne Hint: nach 1.800,76 s keine Lösung, UNKNOWN. Der angeforderte K40-Lauf
  wurde vom Nutzer gestrichen. Artefakt:
  `benchmarks/output/reservoir_line_evolution_20260914/native_fixed_k_relevant_30min_v1/k38/run/result.json`.
- Ältere [Längentests](../findings/reservoir_line_length_scaling_results_20260913.md)
  und [Betriebszeitverdopplung](../findings/reservoir_line_operation_horizon_results_20260913.md)
  verwenden andere Physik und einen früheren Rückkehrvertrag. Ihre qualitativen
  Skalierungshinweise dürfen nicht als Laufzeitprognose für die neue Evolution
  ausgegeben werden.

Längere Strecken sind nicht automatisch größere Zeitmodelle: Bei fester
Betriebszeit braucht man für die Seilsättigung mehr Kabinen, jede fährt aber
weniger Runden. Näherungsweise ist die Zahl der AS-Stationsbesuche
`K_AS * H/C_AS * n ≈ n*H/h_AS`. Trotzdem wird die evolutionäre Musterfolge
länger; Konfliktprüfungen und Waiting-Untermodelle können deutlich schwerer
werden. Kürzere Strecken verkürzen die Gene, erhöhen aber die Rundenzahl.

Mehr Betriebszeit ist ein anderer Faktor: mehr Besuche, mehr mögliche
Beförderungen und bei feiner Freigabeauflösung mehr Nachfragegruppen. Mit
Waiting kann deshalb bereits die Bewertung eines einzelnen Genoms teuer sein.
32 GiB sind eine Schutzgrenze, kein Hinweis auf sinnvoll nutzbare Suchgröße.

### Vorschlag zur Begrenzung — noch nicht neu freigegeben

1. **Journey:** G500 gemäß neuer Freigabe und zwei Referenzumläufe Nachfrage. Den
   restlichen Horizont nicht pauschal auf eine Stunde erhöhen. Zunächst K bis
   etwa20; die vorhandene geometrische K-Leiter wird erst bei lösbaren höheren
   Stufen weitergeführt. U=0 und dieselben Starts bleiben Pflicht.
2. **Kapazität:** Die bisher bestätigten 45 min Nachfrage + 15 min Completion
   vorerst beibehalten. Eine kürzere Hauptstudie würde Anfahr- und Endeffekte
   stärker gewichten. Zuerst Matrix, Katalog und K-Sweep begrenzen, bevor die
   verkehrliche Zeitachse verändert wird.
3. **Längen:** G500 ist nun ausdrücklich für beide Fragen bestätigt. G300/G800
   bleiben mögliche Sensitivitäten; G1200 und große Längensweeps zurückstellen.
   G500 mit beiden Hauptmethoden vorab vermessen; keine G300-Laufzeit übertragen.
4. **Flotte:** Zunächst wenige feste K knapp an/über K_AS vergleichen, statt
   direkt Richtung Portdurchsatzgrenze zu wachsen. Konkrete K-Punkte und
   variable-K-Nutzung sind offen; kein historisches pauschales Max50 übernehmen.
5. **Wenn der Horizont gekürzt wird:** Geänderte Instanz separat einfrieren,
   AS-Kapazität neu bestimmen, Nachfrageprofil zeitlich transparent abbilden
   und mindestens einen längeren Kontrollfall einplanen. Konstante Nachfrage
   und konstante Nachfragerate sind unterschiedliche Versuche.

### Vor den exakten Reihen gemeinsam festzulegen

Die bisherige Struktur bleibt als Ausgangspunkt erhalten: sechs
Kapazitätskurven T5R/T6R × F2/F0/F4 und drei Journey-Kurven T5R × F3/F0/F4;
T6L/F2/F4 sind zwei spätere Terminalkurven. Das sind neun Kerngruppen plus
zwei Erweiterungen, keine elf Einzelruns. Nachfragehöhen, K-Punkte und
Wiederholungen vervielfachen die tatsächlichen Versuche.

Entscheidungsreihenfolge:

1. G500 ist als gemeinsame Hauptgeometrie bestätigt; neue Größenprüfung und
   AS-Kalibrierung fehlen. T6L-Rolle und zusätzliche Längenstudien begrenzen.
2. 45/15 min sowie Warmup/Recovery bestätigen; Rückkehr vor Bedienungsende
   versus durchgehender Linienbetrieb bewusst wählen. Gleicher Vertrag für
   die verglichenen Verfahren; historische Zeugen nicht vermischen.
3. Kleinen Katalog je F-Profil deterministisch definieren. Weiter zulässiges
   Exit-Waiting, dessen Obergrenze und Freigabephase explizit festlegen.
4. Evolution-Engine, Darstellung und Evaluator einfrieren: No-Wait direkt;
   Waiting-Reparatur, falls vorgesehen, mit festem Budget und dokumentierten
   freien/fixierten Dispatchentscheidungen. Ein erfolgloser Repair ist kein
   Beweis gegen die Musterfolge.
5. AS-Kapazitätsintervalle und Nachfrageauflösung fertig kalibrieren. Der alte
   30-/15-s-Test bewies noch keine Ein-Prozent-Äquivalenz. Offene AS-Kappa nicht
   als exakten Nenner von Lastfaktoren ausgeben.
6. Wenige K-Punkte um K_AS, Nachfrageleiter ab AS-Kapazität, Seeds,
   Initialisierung, Beobachtungszeitpunkte und Abbruchkriterien festlegen.

Für das Evolution-Rechengate werden pro kleiner/mittlerer/schwerer Instanz
Bewertungen je Minute, gültiger Anteil, Zeit pro Decoder/Passagier-IP/Repair
(Median/P95), Zeit bis erster gültiger Lösung und echter Verbesserung gemessen.
Ein häufiger Zwei-Sekunden-Abbruch des Passagier-IP ist eine unvollständige
Bewertung, kein exaktes Fitnesssignal. Vorhandene native CP-Modellgrößen allein
reichen nicht, um dieses Gate zu bestehen oder die Evolution auszuschließen.
Hiermit werden weder neue Kalibrierungsläufe noch eine vollständige Kampagne gestartet.

### Evidenz und Berichtspflichten

Die gute native Verbesserung 3.036→3.074 mit kleinem Katalog und starkem Hint
belegt die Existenz und Verbesserbarkeit solcher Fahrpläne, **nicht** den Erfolg
der jetzt gewählten Evolution. Ihre Leistungsfähigkeit bleibt separat zu testen.
Arc-Flow-Gaps gelten für den exakten Fixed-Start-No-Wait-Fall. Die Evolution
liefert gültige Zeugen; Passagier-IP-Bounds gelten nur für den jeweiligen
Fahrplan. Unterschiede zur regelmäßigen AS-Referenz und Nachweise gegen einen
globalen AS-Bound werden getrennt bezeichnet. Fehlender SS-Erfolg ist kein
Beweis gegen einen Skip-Stop-Vorteil.

## 1. Empfehlung und Forschungsfragen

Die Thesis verwendet drei Hauptmethoden: phasenoptimiertes All-Stop-No-Wait als
betriebliche Referenz, vollständiges Labelled Arc-Flow bei festen kleinen K und
festen Starts, sowie beschränkte Linienplanung mit optionaler Flotte für große
Kapazitätsfälle. Weitere Solverfamilien sind für diesen Versuchsplan nicht nötig.

Die Experimente sollen vier Fragen beantworten:

1. **Reisequalität:** Verkürzt Skip-Stop bei niedriger Nachfrage die Zeit von
   Nachfragefreigabe bis Ziel, wenn beide Betriebsweisen alle Personen bedienen?
2. **Kapazität:** Bedient Skip-Stop bei hoher Nachfrage mehr Personen und kann es
   ein größeres, vorgeschriebenes Nachfrageprofil vollständig bedienen?
3. **Mechanismus und Grenzen:** Welche räumlichen Nachfrage- und
   Infrastrukturmerkmale ermöglichen den Gewinn, welche begrenzen ihn?
4. **Berechenbarkeit:** Welche Qualität und welche nachweisbaren Schranken liefern
   die beiden Formulierungen innerhalb eines festen Zeit- und Speicherbudgets?

Empfohlener Kern: **F2 komplementär, F0 diffus und F4 lokal**. F1 gemeinsamer Hub
und F5 gemischt ergänzen die Grenzen. Express F3 erhält besonderes Gewicht bei
der kleinen Reisezeitstudie. Zuerst den bestehenden Fünf-Stationen-Ring nutzen;
die sechs Stationen bilden eine getrennte Übertragungsstufe.

## 2. Was heute tatsächlich verfügbar ist

| Baustein | Geprüfter Stand | Konsequenz für den Plan |
|---|---|---|
| Labelled Arc-Flow | Vollständige Fixed-K-No-Wait-Domäne; freie STOP/SKIP- und Integer-Passagierwahl; bestehendes Journey-Time-Ziel | Hauptmethode für kleine Reisezeitfälle und dortige globale Solver-Gaps |
| Arc-Flow-Ziele | `EanPassengerObjective` enthält aktuell `journey_time` und `waiting_time`, kein separates `unserved` | Kapazitätsoptimierung im Arc-Flow nicht als fertigen CLI-Modus voraussetzen |
| Linienmodell | `exact_service` maximiert `(Kmax+1)*served - used_fleet`; also primär Bedienung, sekundär Kabinenzahl | Direkt für hohe Last und Flotteneffizienz nutzbar; Reisezeit ist bisher nur Kontrollwert |
| Linienbewegung | Ein wiederkehrendes Stationsmuster pro Einsatz, Rundenzahl und Dispatch frei; erste Abfahrt 0; deklarierter Dispatchbereich; Single-Use; Waiting=0 | Keine freie Musteränderung während des Einsatzes, kein Wiedereinsatz, keine getestete Waiting-Reparatur |
| Linienkatalog | `small`: All-Stop plus Endpunktmengen der nachgefragten OD-Paare; `relevant`: weitere Masken mit mindestens einem solchen Paar | Katalog ist nachfrageabhängig; nicht überall drei beziehungsweise 14 Muster |
| Feste Passagierbewertung | Bestehende ganzzahlige Zuordnung und unabhängige Zertifikatsprüfung | Für jeden finalen Fahrplan wiederverwenden; LP-Zuordnung ersetzt keine Integer-Prüfung |
| Verschachtelte Nachfrage | `NestedDemand` erzeugt stabile gewichtete Integer-Präfixe | Baustein vorhanden; allgemeiner F0–F6/P0–P4-Adapter noch zu integrieren |
| Fünf-Stationen-Profilrunner | `diffuse`, `local`, `express`; Batch bei 0 oder vier Buckets 0/200/400/600; Horizont 1.200 s | Historische sechs Profilpaare unmittelbar nachvollziehbar; kein allgemeiner Sechs-Stationen-Runner |
| All-Stop-Phasenmaximum | Vertrag dokumentiert; bisherige Referenz verwendet feste Phase | Direkte gemeinsame Phasenvariable mit Integer-Passagieren ist noch zu implementieren; kleine Sweeps dienen nur als Kontrolle |
| Sechs Stationen | Geometriebausteine für Linie sowie einzelne CW-/CCW-Ringe, Architekturen A/B/C vorhanden | Gemeinsame Doppelring-Nachfrage, Flotte und Baseline nicht als fertige Integration behandeln |

**Begriff:** Die Linienplanung ist eine mathematische Suchraumbeschränkung und
damit eine heuristische Approximation des allgemeinen Problems. Es gibt bislang
keinen bewiesenen Approximationsfaktor. Auch im beschränkten Modell ist ein
Zeitlimitresultat nicht automatisch optimal.

## 3. Welche Konzepte wir vergleichen

Die Definitionen lehnen sich an die vorhandenen
[Nachfragefamilien](../reference/demand_case_families.md) an. Erwartungen sind
prüfbare Hypothesen, keine vorweggenommenen Ergebnisse.

| Konzept | Mechanismus / Erwartung | Wann wenig oder kein Nutzen plausibel ist | Geeigneter Test | Priorität |
|---|---|---|---|---|
| **F2: komplementäre Märkte** B↔D und C↔E | Verschiedene Kabinengruppen nutzen verschiedene Plattformen; kürzere Umläufe, mehr nützliche Fahrten | Gemeinsames Seil, Merge oder Terminal sättigt; einseitige Nachfrage macht eine Gruppe schwach | Hohe Last: Bedienungszahl, vollständige Profilkapazität, genutzte Flotte | Kern |
| **F0: diffuse Nachfrage** | Viele ODs benötigen viele Stationen; prüft Übertragbarkeit jenseits zugeschnittener Cluster | Spezialisierung fragmentiert Frequenzen und erhöht Warten | Niedrige Last: Journey Time; hohe Last: Bedienung | Kern, neutral |
| **F4: lokale Nachfrage** | Kaum Zwischenhalte auf der individuellen Fahrt einzusparen | Ausgelassene Halte kosten Angebot; All-Stop kann bereits gut sein | Niedrige Last: Journey Time und Warteanteil; hohe Last: Bedienung | Kern, Negativhypothese |
| **F3: Express / lange Wege** | Viele Zwischenhalte vermeidbar; deutliche Fahrzeitersparnis möglich | Längere Wartezeit auf die passende Kabine verbraucht den Gewinn | Niedrige Last mit U=0: Reisezeit zerlegen; Überlast als Zusatz | Kern der kleinen Studie |
| **F1: gemeinsamer Hub** | Zwischenhalte vermeidbar, aber viele Fahrten benötigen denselben Hub | Hubressource bleibt Flaschenhals; hoher Kapazitätsgewinn unwahrscheinlich | Hohe Last, Hubauslastung und Bedienung; optional niedrige Last | Ergänzung |
| **F5: Lokal/Express gemischt** | Gemeinsame Auswahl von All-Stop- und Expresslinien könnte beide Märkte bedienen | Expressgewinn entsteht durch schlechte Lokalbedienung | 50/50-Mischung, danach optional 25/75; Bedienungsquote je Markt und Reisezeit | Ergänzung |
| **F6: spätere Einstiegsstation benachteiligt** | Kabinen könnten gezielt Restkapazität zu späteren Stationen bringen | Freie optimale All-Stop-Zuordnung kann Plätze bereits zurückhalten | Gruppenbedienung und Warteanteile; keine Greedy-Baseline | Optional |
| **Ungleiche Clusterstärke** | R2 von 50/50 auf 75/25 verändern: passt die freie Flottenwahl ihre Verteilung an? | Starre alternierende Anfangslösung dominiert die kurze Suche | Freie Linienwahl und Flottenverteilung bei hoher Last | Kleine wichtige Ergänzung |
| **Cluster mit zeitlich versetzten Ankünften** | Zeitliche Entzerrung kann Konflikte reduzieren; zeigt Abhängigkeit von synchronen Freigaben | Vorteil verschwindet, sobald beide Cluster gleichzeitig Druck erzeugen | Gleiche Personen/OD-Anteile, Freigaben gezielt verschieben | Robustheit |

F4 ist kein theoretischer Nullgewinnsatz: Schnellere leere Umläufe und andere
Flottenverteilungen können auch bei kurzen ODs Vorteile ergeben. F0 ist ebenfalls
kein garantierter Nullfall; im vorhandenen Batch-Fall gab es bereits einen
Reisezeitgewinn. Ein nicht verbesserter Incumbent beweist keinen fehlenden Nutzen.

### Konkrete Definitionen auf dem vorhandenen gerichteten Fünfer-Ring

- F0: alle 20 gerichteten OD-Paare gleich gewichtet.
- F4: jeweils nächste Station in Fahrtrichtung, fünf OD-Paare.
- F3: drei oder vier Seilabschnitte in Fahrtrichtung, zehn OD-Paare.
- F2: B→D, D→B, C→E, E→C gleich gewichtet; historisches R2 unverändert archivieren.
- F1: C als Hub, alle C↔i gleich gewichtet.
- F5: Mischung der bereits normalisierten F4- und F3-Matrizen mit Gewichten 1/2.
- F6 optional: A→D mit Gewicht 7 und B→E mit Gewicht 3; gemeinsame
  Abschnittskapazität bei unterschiedlichen Einstiegsstationen, ohne fiktive
  Gegenrichtung im Einrichtungsring.

Auf dem gerichteten Ring bedeutet ein Rückweg häufig mehr Seilabschnitte als der
Hinweg. Die Definitionen werden nicht über ungerichtete Stationsabstände ersetzt.

## 4. Zeitprofile und Infrastruktur

### Zeitprofile

| Profil | Konstruktion | Zu beantwortende Frage |
|---|---|---|
| P0 gleichmäßige Buckets | neun gleich gewichtete Freigaben | Räumlichen Mechanismus isolieren |
| P1 Einzelpeak | Gewichte `[1,2,3,4,5,4,3,2,1]` | Übersteht der Vorteil einen temporären Kapazitätsengpass? |
| P4 drei Batches | `[3,0,0,3,0,0,3,0,0]` | Wie schnell werden konzentrierte Ankünfte abgebaut? |
| P0 versetzt | bei F2 nur C/E-Buckets um eine halbe Bucketbreite verschieben | Ist der R2-Erfolg stark von der Synchronisation abhängig? |
| P2 Richtungswechsel | spätere Doppelring-Stufe | Kann eine feste Richtungsflotte wechselnde Nachfrage bedienen? |
| P3/P5 Doppelpeak/Unsicherheit | zurückgestellt | Erst nach belastbarer deterministischer Kernstudie |

Historisches R2 bleibt bei Freigaben 300,400,…,1.100 s. Für die versetzte
Variante beispielsweise C/E bei 350,450,…,1.150 s; die unveränderten
Bedienungs-/Rückkehrgrenzen müssen das zulassen. Eine Verschiebung verändert
die verbleibende Bedienungszeit und wird deshalb auch als Randeffekt erfasst.
Ein zusätzlicher vorgezogener Kontrollversatz ist optional, kein Pflichtlauf.

Die alten K20-Batch-/Distributed-Fälle behalten ihre ursprüngliche Zeitachse.
Die geplante Sechs-Stationen-Stufe nutzt 300 s Warm-up, 3.600 s Service und 300 s
Rückkehrreserve; P0/P1/P4 liegen auf neun Fünfminuten-Buckets während der ersten
45 Serviceminuten. Bucketnachfrage ist keine kontinuierliche Poisson-Nachfrage.

Für Zeitprofilvergleiche bleibt die absolute Personenzahl aus der P0-Kalibrierung
gleich. Gleichzeitig wird All-Stop für jedes geänderte Profil erneut über die
Phase optimiert. So wird ein Peakeffekt nicht durch erneutes Herunterskalieren
der Personenzahl verborgen.

### Strecken- und Betriebskonzepte

| Stufe | Strecke / Betrieb | Erwartete Erkenntnis | Stand / Voraussetzung |
|---|---|---|---|
| T5 | bestehender gerichteter Fünfer-Ring, Architektur B | Reproduktion, Nachfragevariation, Laufzeitkurven | Hauptmethoden auf dieser Familie vorhanden |
| T6R | einzelner Sechser-Ring B | Übertragung auf zusätzliche Station und längere Fahrt | Geometrie vorhanden; Adapter, neue Baseline, Kontrollreplays nötig |
| T6D | zwei gerichtete Sechser-Ringe als gemeinsames System | Richtungswahl, gemeinsame Flottenverteilung, komplementäre Bedienung | Neue gemeinsame Flotten-/Passagierintegration erforderlich |
| T6L | Linie mit obligatorischen Endstationen | Begrenzen gemeinsame Terminals den Skip-Stop-Kapazitätsgewinn? | Geometrie vorhanden; Linienkatalog muss Pflichtterminals immer halten |
| Geometriesensitivität | z. B. kürzere/längere Seilabschnitte relativ zur Stationsdauer | Je größer vermeidbare Haltezeit gegenüber Fahrzeit, desto eher Nutzen | Nur ein vorab definiertes Parameterpaar, beide Betriebsweisen neu berechnen |
| Technik A/C statt B | veränderte Weichen-/Headwayarchitektur | Grenze durch gemeinsame Ressourcen statt nur Nachfrage | Sekundäre Studie; keine Solveroptimierung, sondern andere Anlagentechnik |

Für T6D darf Nachfrage nur einmal angelegt werden; beide Richtungen greifen auf
dieselbe OD-Bilanz zu. Diametral gegenüberliegende Ziele dürfen nicht doppelt
bedient werden. Kabinen bleiben je Einsatz auf ihrer Richtung; Wiedereinsatz
gehört nicht zum bestehenden Modell. Eine gemeinsame Flottenobergrenze wird aus
den Port- und Ressourcenbedingungen der später implementierten T6D-Domäne
abgeleitet; der historische Wert Max50 wird nicht übertragen.

**All-Stop im Doppelring:** Zwei Richtungskreise besitzen grundsätzlich zwei
Phasen. Bei gemeinsam entscheidbaren Passagierwegen müssen diese gemeinsam
bewertet werden. Vollständiges Auffüllen beider Kreise kann wesentlich mehr als
in den historischen Max50-Fällen erfordern. Vor solchen Läufen muss explizit
festgelegt werden, ob die abgeleitete gemeinsame Flottenobergrenze dies zulässt;
andernfalls ist eine begrenzte All-Stop-
Flottenaufteilung eine zusätzliche Entscheidung. Weder K=38 noch ein einzelner
Phasenparameter werden ungeprüft auf sechs Stationen übertragen.

## 5. Ziele, Referenzen und faire Vergleiche

### L: Reisezeit bei niedriger Last

Primär gilt U=0 für beide Methoden. Optimiert wird

\[
J=\sum_p(t_p^{Ziel}-r_p),\qquad \bar J=J/N.
\]

Berichtet werden zusätzlich `Release → Plattformabfahrt` und
`Plattformabfahrt → Ziel`, jeweils mit Mittelwert und personenmengengewichtetem
P95. Der erste Anteil enthält im aktuellen Vertrag Boarding-/Plattformzeit und
ist nicht ausschließlich reines Warten in einer Schlange.

Die bestehende Journey-Time-Funktion bestraft Unbediente endlich mit H−r und
erzwingt U=0 nicht. Deshalb sind eine geprüfte Vollbedienungsbedingung oder eine
entsprechende Runnererweiterung erforderlich. Bis dahin darf ein Lauf nur dann
als reiner Reisezeitvergleich ausgewertet werden, wenn beide tatsächlich U=0
erreichen; ein Lauf mit U>0 wird separat als gemischter Kostenvergleich geführt.

Für dieselbe K20-Instanz laufen All-Stop und Arc-Flow mit identischen Starts.
Zusätzlich wird die **gesättigte phasenoptimierte All-Stop-Referenz** berichtet,
wie vom Nutzer festgelegt. Der Vergleich gegen All-Stop K20 isoliert die Wirkung
der Halteentscheidungen; der Vergleich gegen die gesättigte Baseline beantwortet
die betriebliche Frage. Ein Gewinn gegen K20-All-Stop beweist keinen Gewinn gegen
die maximal gefüllte Anlage.

Die All-Stop-Phase muss für dieses Ziel J minimieren, unter U=0. Eine bloß auf
maximale Bedienung optimierte Phase kann bei niedriger Last beliebig sein und
die Reisezeitreferenz unnötig schwächen. Die Baseline bleibt gesättigt/No-Wait;
nur ihr zum Test passendes Bewertungskriterium wird präzisiert.

Das Linienmodell optimiert J noch nicht. Eine feste nachgelagerte
Passagieroptimierung verbessert nur die Zuordnung auf dem gewählten Fahrplan,
nicht dessen Dispatchzeiten. Direkte Linien-Reisezeitläufe sind daher eine
gesonderte spätere Erweiterung und keine Voraussetzung des ersten Kernpakets.

### H: Bedienungsleistung bei hoher Last

Primär minimieren wir U=N−S. Reisezeit wird als Kontrollkennzahl berichtet.
Die bestehende Linienzielfunktion priorisiert jede zusätzliche bediente Person
vor jeder möglichen Flottenreduktion und passt zu dieser Frage.

Für feste Nachfrage N werden ausgewiesen:

- S und U für Skip-Stop und phasenoptimiertes gesättigtes All-Stop;
- zusätzliche Personen ΔS und Differenz der Bedienungsquoten in Prozentpunkten;
- Quote je OD-Gruppe und Freigabebucket; schwächste Gruppe;
- verwendete Kabinen, Kabinen-Betriebszeit, Haltemuster und Umlaufzahlen;
- verfügbare globale bzw. katalogbezogene Bounds mit ihrem Gültigkeitsbereich.

Ein niedriger Mittelwert der Reisezeit unter den Bedienten ist bei U>0 kein
alleiniger Qualitätsbeweis: Der Solver könnte vor allem leicht erreichbare
Personen auswählen. Auch eine hohe mittlere Sitzbelegung ist kein Primärziel;
schnelle Wiederverwendung freier Plätze kann bei niedrigerer Belegung mehr
Personen transportieren.

### C: Größere vollständig bedienbare Profilnachfrage

Für ein verschachteltes Integer-Nachfrageprofil D(N) ist die Referenz

\[
\kappa_{AS}=\max\{N:\min_\theta U_{AS}(D(N),\theta)=0\}.
\]

Das ist die Kapazität der definierten gesättigten phasenfreien No-Wait-Baseline,
nicht das Maximum über eine variable All-Stop-Flottenfrontier aus älteren Plänen.

Für SS genügt zunächst ein gültiger Plan bei N>κ_AS mit U=0. Für eine untere
Schranke κ_SS^LB nehmen wir die größte vollständig validierte Nachfrage.
Damit ist κ_SS^LB/κ_AS ein nachgewiesener Mindestfaktor der Profilkapazität.
Eine größere teilweise bediente Menge bei festem N ist ein anderer Befund.

Geometrische Nachfrageerhöhung und ganzzahlige Intervallsuche sind für die exakte
AS-Baseline möglich, sobald alle Phasen zuverlässig ausgewertet werden. Ein
SS-Timeout beweist keine Kapazitätsobergrenze und darf kein Intervallende nach
unten setzen. Kleine globale Solver-Bounds oder sichere analytische Schranken
sind dafür nötig. Geänderte Nachfrage erfordert neue gültige Kandidaten und
Fingerprint; alte Ride-Mengen werden geprüft statt blind übertragen.

### E: Flotteneffizienz

Für ein vorgegebenes N mit U=0 die nötige Kabinenzahl untersuchen. Der bestehende
Linienlauf minimiert sie bereits sekundär. Tests mit Max37 und Max36 würden
für R2 zusätzliche Zeugen liefern. Ein Fehlschlag nach Zeitlimit beweist nicht,
dass 38 notwendig sind. Für kleinere Flotten dieselben Dispatch-/Rückkehrregeln
und denselben Katalog behalten; das größere Modell enthält den kleineren Plan.

## 6. Provable Gaps: Was wir realistisch nachweisen können

| Nachweis | Bedingung | Aussage |
|---|---|---|
| Exaktes kleines Optimum | UB_J=LB_J im vollständigen Fixed-K-Arc-Flow | Reisezeitoptimum bei genau diesen Starts und No-Wait |
| Begrenzter Reisezeitvorteil | L≤J_SS*≤U und exakter Referenzwert A>0 | Optimaler Vorteil gegenüber A liegt in `[1−U/A, 1−L/A]`, nur für die jeweilige SS-Domäne |
| Großer Bedienungsbeweis | gültiger Plan mit U=0 | Primäres Bedienungsoptimum für dieses N auch im allgemeinen SS-Modell |
| Globaler U-Gap | LB_U≤U*≤UB_U in derselben allgemeinen Domäne | Höchstens `UB_U−LB_U` weitere Personen können zusätzlich bedient werden |
| Katalog-Gap | Bounds des beschränkten Linienmodells | Nur Optimalität innerhalb der festen Muster-/Dispatchdomäne |
| Vorteil ohne SS-Optimum | U_SS^valid < LB(U_AS*) | SS schlägt jeden AS-Plan im Gültigkeitsbereich des AS-Bounds |
| Annähernde Gleichwertigkeit | bei gleicher Domäne A−LB_J≤ε und gültiger AS-Plan in SS enthalten | Maximal möglicher Reisezeitgewinn ist ≤ε |
| Nur keine Verbesserung gefunden | UB bleibt bei AS und LB ist schwach | Suchbefund; kein Nachweis, dass Skip-Stop nutzlos ist |

Bei U nahe null sind **Personenlücke** und Lücke als Anteil an N aussagekräftiger
als eine relative Prozentlücke mit U im Nenner. Beim Linienmodell zuerst die
skalierte Flotten-/Bedienungszielfunktion korrekt in Personenbounds umrechnen;
die Rohziellücke ist keine reine Bedienungslücke.

Die vorhandene R2-Schranke S_AS≤2.949 und der SS-Zeuge S=3.074 sind der bereits
erreichte stärkere Vergleich. Sie gelten nicht für neue Freigaben, neue ODs oder
andere Geometrie. Die AS-Schranke ist kein SS-Lower-Bound. Weitere globale
AS-Relaxationen sind optionale Zertifikatsbausteine, keine vierte Hauptmethode.

Ein direkter algorithmischer Gap zwischen Linienplanung und Labelled Arc-Flow
ist erst bei **gleichen Starts, Lebenszyklen, Flotte und Ziel** zulässig.
Heutiges Reservoir-Linienmodell und Fixed-Start-Arc-Flow erfüllen das nicht.
Eine kleine spätere Brückenstudie könnte in der vollständigen Arc-Flow-Domäne
dieselben wiederkehrenden Muster erzwingen und so den Preis der Beschränkung
messen. Das benötigt eine gezielte Integration, keinen neuen Solver.

## 7. Konkrete Versuchsmatrix in priorisierter Reihenfolge

### Stufe 0 — Vergleich herstellen

Vor zusätzlichen großen Läufen:

1. Phasenoptimierte All-Stop-Baseline für S und für J bei U=0 ergänzen.
2. Für den Zeitvertrag beweisen, welches Phasenintervall sämtliche vorgesehenen
   Lagen repräsentiert. `C/K` kann in Integer-Ticks nicht ganzzahlig sein;
   Startoffsets deshalb exakt und konsistent ableiten, keine Rundungsdrift.
   Ein endlicher Anlauf/Rückkehrvertrag macht Verschieben und Neubenennen nicht
   automatisch äquivalent. Boundaryfälle explizit prüfen.
3. Kritische Phasen aus Freigaben, Zielhorizont, Dispatch und Rückkehr ableiten.
   Für Kapazität ist der Wert zwischen Unterstützungswechseln konstant; für
   Reisezeit muss zusätzlich die affine Kostenänderung über die Phase erfasst
   werden. Endpunkte benachbarter Tickbereiche berücksichtigen.
4. Auf kleinen Bereichen vollständige Tickenumeration gegen das Phasenverfahren
   prüfen; bekannte fixe Phase und ihre Passagierwerte reproduzieren.
5. Gemeinsamen OD-/Bucketgenerator auf Basis von `NestedDemand` mit stabilen IDs
   integrieren. Positive/negative Muster nicht pro Solver unterschiedlich erzeugen.
6. Repräsentative All-Stop- und SS-Zertifikate sowie Grenzen der unabhängigen
   Modellprüfung festhalten; bislang idealisierten Reservoirport als Annahme
   kennzeichnen, nicht als bereits nachgewiesene reale Einfahrgeometrie.

**Bestehender Altplan-Konflikt:** `demand_case_families.md` normalisiert noch auf
eine globale All-Stop-K-Frontier. Hier gilt die vom Nutzer neu festgelegte
gesättigte phasenoptimierte Baseline. Die alten Definitionen bleiben als
historische Planung lesbar; neue Kampagnen verwenden diesen Vertrag.

### Stufe 1 — Kleine Reisezeitstudie: sechs Zellen

T5, K20, Balanced-Starts, No-Wait, F0/F3/F4 × Batch/Distributed.
Für jede Familie zunächst einen gemeinsamen niedrigen N-Wert für beide
Zeitprofile bestimmen: etwa 50 % der kleineren exakt bestätigten
All-Stop-K20-Profilkapazität. So bleibt die Personenzahl beim Zeitprofilvergleich
gleich. N und die Berechnung vor den SS-Läufen einfrieren.

Jede Zelle bekommt:

- AS bei denselben K20-Starts, exakte Zuordnung;
- AS gesättigt mit zielgerecht optimierter Phase, zusätzliche Betriebsreferenz;
- Arc-Flow bei denselben K20-Starts, Journey Time mit Vollbedienung;
- Verlauf bei 30/60/120/300 s, finale Gap- und Personenwerte.

Erwartung: F3 spart Fahrtzeit; F4 kann gleichwertig bleiben; F0 testet, ob diffuse
Nachfrage dennoch profitiert. Historische 1.280-Personen-Läufe als getrennte
Referenztabelle übernehmen, nicht als neue Low-Demand-Kalibrierung ausgeben.

### Stufe 2 — Hohe Last: zwölf Zellen

T5, Single-Use-Reservoir, No-Wait, je Geometrie neu bestimmte Flottengrenzen und
gemeinsame unveränderte Physik und Zeitgrenzen. Default: `intervals`,
`exact_service`, kleiner regelbasiert erzeugter Katalog. Die alte Max50-R2-Domäne
bleibt als eigener historischer Fall erhalten.

| Fallgruppe | Nachfrage | Zellen |
|---|---|---:|
| F0, F2, F4 jeweils P0 | N=`ceil(ρ κ_AS(F,P0))`, ρ=0,8 / 1,0 / 1,2 | 9 |
| F1 Hub, F5 Mischung, F2 mit 75/25-Clustern jeweils P0 | ρ=1,2 mit jeweils eigener Baselinekalibrierung | 3 |

Bei ρ=0,8/1,0 interessieren auch Kabinenzahl und Gruppenversorgung. Bei ρ=1,2
stehen Mehrbedienung und mögliche Vollbedienung im Vordergrund. Für die
75/25-Ergänzung zusätzlich ein Vergleich bei gleichem absoluten N wie im
symmetrischen R2 als optionale Sensitivität, da getrennte Kalibrierung sonst
Nachfragehöhe und Ungleichheit zugleich verändert.

Eine erfolgreiche Vollbedienung bei 1,2 beweist noch keine maximale SS-Kapazität.
Ein optionaler Folgepunkt 1,4 oder 1,6 prüft, ob noch Reserve vorhanden ist.

### Stufe 3 — Zeitliche Robustheit: sechs Zellen

F2 und F4 jeweils bei der **festen absoluten** Personenzahl aus P0 mit ρ=1,2:

- P1 Peak;
- P4 Batches;
- P0 mit versetzter Cluster-/Stationsfreigabe.

Bei F4 eine vorab feste Hälfte der Ursprungsstationen um einen halben Bucket
verschieben; keine nach Ergebnis ausgewählte Verschiebung. Je Zelle eigene
AS-Phasenoptimierung. Die drei Referenzprofile werden samt Integer-Mengen
gespeichert. F2 prüft Robustheit des positiven Falls, F4 eine negative Hypothese.

### Stufe 4 — Nur gezielte Vertiefung

Höchstens vier zunächst ausgewählte zusätzliche Versuche:

1. R2 mit `relevant` statt `small`, gleicher Vollbedienungshint und Zeitbudget;
   untersucht Katalogempfindlichkeit/Flottenzahl, nicht mehr als N bediente Personen.
2. Ein neutraler oder gemischter Fall mit erweitertem Katalog.
3. Ein Nachfragepunkt oberhalb 1,2, falls dort U=0 erreicht wurde.
4. Ein Max37-/Max36-Test oder ein begründet noch fortschreitender offener Fall.

Das `small`-Profil hat bei diffuser Fünfer-Nachfrage bereits elf Muster,
`relevant` 26; der große R2-Katalog hat dagegen 14. Ein Build-Gate ist daher
auch für vermeintlich kleine Kataloge nötig. Rundenzahl und Beförderungskandidaten
bestimmen den Aufwand zusätzlich. Aus vierfacher Variablenzahl lässt sich kein
verlässlich vierfacher RAM-Bedarf ableiten.

### Stufe 5 — Sechs Stationen, eigene Kampagne

Zuerst T6R/F2 und T6R/F4 als kleine Adapterkontrollen. Danach vorzugsweise
T6D mit F2/F0/F4. Die Linie T6L liefert anschließend mit F2 und F1 den Vergleich
gegen Pflichtterminals. Beginnen mit P0 und zwei Lastpunkten, etwa 0,5 und 1,2;
keine vollständige Kombination aller Topologien, Familien, Profile und K-Werte.

Diese Übertragung erfordert zuvor einen gemeinsamen Doppelringadapter, zwei
Phasen in der AS-Referenz und den bewussten Umgang mit dem Flottenbudget.
Der jetzige Stationsmaskenbuilder versucht SKIP an nicht gewählten Stationen;
auf einer Linie müssen Pflichtterminals daher vorab in jedem Muster liegen.
Kleine Tests für Richtungswahl, Doppelzählung, Ressourcen und Rückkehr gehören
vor jede große T6-Kampagne. Der Katalog allein macht die vorhandenen Backends
nicht automatisch topologieunabhängig.

## 8. Laufbudgets, Startlösungen und Plateauauswertung

Vorschlag für die erste T5-Kampagne, nach Implementierung und Korrektheitstests:

| Abschnitt | Anzahl / Budget | Maximale nominelle Zeit |
|---|---|---:|
| Baselinekalibrierung und Phasenläufe | gemeinsamer Abschnitt mit Abbruchgrenze | 45 min |
| Kleine Replays und Build-Gates | gemeinsamer Abschnitt | 15 min |
| Stufen 1–3 | 24 SS-Läufe × 300 s Gesamtbudget | 120 min |
| Zusätzliche Seeds auf drei vorab benannten Zellen | 6 × 300 s | 30 min |
| Optionale Stufe 4 | höchstens 4 × 600 s | 40 min |
| Auswertung und Abschlussreserve | gemeinsam | 15 min |
| **Summe** | **harte Obergrenze vorgeschlagen: 270 min** | **265 min + 5 min Puffer** |

Aufbau, Hintaufbau, Lösungsextraktion und Validierung zählen zum Einzelbudget.
Nicht fertig kalibrierte Zellen bleiben ausstehend und werden nicht mit
geschätzter AS-Kapazität gestartet. Falls die exakte Phasenreferenz mehr Zeit
braucht, zuerst Matrix verkleinern; Referenznachweis nicht durch stilles
Herabsetzen der Genauigkeit ersetzen. Die historische R2-Reproduktion mit
N=3.074 kann weiterhin als klar bezeichnete unnormierte Kontrolle dienen.

Läufe sequenziell, zwölf Worker/Threads als Wunsch; tatsächliche CPU-Auslastung
und Prozessbaum-RSS messen. Für neue große Linienläufe gilt auf dem vorhandenen
36-GiB-Rechner ein externes Maximum von 32 GiB für den gesamten Prozessbaum,
ergänzt um Speicherdruck- und Swapüberwachung; Abbruch als Speicherbefund berichten. Presolve
im R2-Hauptprofil wie im erfolgreichen Pilot aus, Einstellung vor der Kampagne
einfrieren. Keine parallelen Solverjobs oder nachträgliche Parameterauswahl
ohne Kennzeichnung einer neuen Variante.

Die drei Wiederholungszellen: F2/P0/1,2, F4/P0/1,2 und F2/P4 bei festem N.
Seeds 0/1/2 erhalten jeweils **denselben vorab geprüften Hint**. Ein Ergebnis
von Seed 0 wird nicht zum Startwert von Seed 1, wenn wir Zufallsrobustheit
behaupten wollen. Die historischen R2-Läufe mit 60/300/180 s waren eine
fortgesetzte Verbesserungskette; 89,69 s bis U=0 ist die Zeit des letzten Laufs
mit bereits gutem U=38-Hint, nicht die Gesamtzeit vom ungesäten Start.

Der bekannte BD/CE-Hint darf für die R2-Incumbentstudie genutzt werden. In allen
anderen Zellen dieselbe vorab dokumentierte Startprozedur verwenden, ihren
Aufwand mitzählen und nicht manuell pro Ergebnis nachhelfen. Nicht darstellbare
AS-Referenzen (etwa erste Abfahrt 29,09 s statt 0) werden als externe Referenz
geführt. Ein obligatorischer Baselinewert ist nicht automatisch ein zulässiger
Hint des engeren SS-Modells.

**Wann verlängern?** Ein Lauf bekommt nach dem Screening ein längeres Budget,
wenn in der letzten Minute ein gültiger Incumbent oder ein relevanter Bound
verbessert wurde und Aufbau/RAM beherrscht sind, oder wenn ein kleiner noch
offener Gap eine konkrete Beweisfrage entscheidet. Stagnation über 300 s ist
ein Befund dieses Budgets, keine Garantie dauerhaften Stillstands. Mehr Zeit
allein erhält keinen Vorrang vor fehlenden Vergleichsreferenzen.

## 9. Messwerte und Abbildungen

Pro Experiment eine eingefrorene Identität mit Topologie, Physik, Nachfrage,
Phasen-/Startpolicy, Horizonten, Ziel, Katalog, Seed und Quellcodeversion.
Historische Ergebnisordner bleiben erhalten. Kein katalogbezogener Bound wird
als globaler allgemeiner SS-Bound beschriftet.

Pflichtmetriken:

- AS-Phase, ihre Vollständigkeits-/Optimalitätsaussage und Referenzwerte;
- U/S, Flotte und gegebenenfalls J samt Gültigkeitsbereich;
- Zeitpunkt der Hintübernahme, erste native Lösung, jede echte Verbesserung;
- UB/LB bei 30/60/120/300 s, letzter Fortschritt; keine erfundene Interpolation;
- Aufbau, Suche, Validierung, Gesamtlaufzeit und Peak-Prozessbaum-RSS;
- Musterzahl, Templatezahl, Ride-Variablen, Intervalle, Constraints;
- globale Personenlücke oder J-Gap, zusätzlich Katalog-Gap wo verfügbar;
- Nachfragebedienung je OD/Bucket, Release-bis-Abfahrt und Fahrtzeit;
- belegte Plätze je Abschnitt und geschützte Ressourcenauslastung als Erklärung.

Geeignete Thesis-Abbildungen:

1. Reisezeit gegen niedrige Last: gestapelt vor Abfahrt / während Fahrt.
2. Bedienungsquote gegen Lastfaktor mit AS und Linienplanung; gleiche absolute N.
3. Vollständig bedienbare Profilnachfrage als bewiesene Intervalle, offene
   Obergrenze sichtbar statt als geschätztes Optimum.
4. S und LB/UB über tatsächliche Gesamtlaufzeit; übernommenen Hint markieren.
5. Gewählte Muster/Flottenanteile für F2, F5 und asymmetrisches F2.
6. Modellgröße und Zeitaufwand bei K bzw. Katalogvariation.

Kein Mittelwert über unterschiedliche Nachfragefamilien als universeller
Skip-Stop-Gewinn. Bei drei Solver-Seeds Median und Spannweite berichten;
das ist keine Stichprobe zufälliger realer Verkehrsnachfrage.

## 10. Welche vorhandenen Ergebnisse verwendet werden können

| Befund | Bestehende Evidenz | Verwendung / Grenze |
|---|---|---|
| K20 diffus/Batch | 635.519,998 → 525.730,908; beide 1.280 bedient, SS-Gap 0 | Exakter Reisezeitgewinn 17,28 % bei gemeinsamen festen K20-Starts |
| K20 lokal/Batch und verteilt | gleiche AS-/SS-Kosten, beide vollständig bedient, Gap 0 | Belastbare Nullfälle genau dieser Start-/Nachfragedomänen |
| K20 Express/Batch | 960 → 1.280 bedient, Kosten −19,52 % | Gemischter Bedienungs-/Kostenbefund, kein reiner Reisezeitgewinn |
| K20 Express/verteilt | 940 → 1.272 bedient, Kosten −30,62 %, Gap 0,061 % | Sehr enge Kostenbounds bei unvollständiger Bedienung |
| K20 diffus/verteilt | AS und SS 1.270 bedient, Kosten gleich; SS-Gap 34,556 % | Keine Verbesserung gefunden, Gleichwertigkeit nicht bewiesen |
| R2-Linienmodell | 3.074 bedient mit 19 BD + 19 CE; U=0 | Primäroptimum bei diesem N, Flottenminimum offen |
| R2-AS-Relaxation | S_AS≤2.949 in ursprünglicher Max50-Domäne | Stärkerer AS-Vergleich; kein Wert für neue Nachfrageprofile |
| K39-No-Wait | schwache Primalwerte trotz langer Läufe | Skalierungsbefund; nicht zur Hauptkampagne immer weiter verlängern |

Für die Thesis zuerst diese gesicherten positiven und negativen Fälle darstellen,
dann die phasenoptimierten Baselines und die neue Lastmatrix ergänzen. Das
verringert die Abhängigkeit von noch ausstehenden großen Optimalitätsbeweisen.

## 11. Umsetzungspunkte und Quellen im Projekt

| Aufgabe / Evidenz | Einstieg |
|---|---|
| Forschungslogik | [Thesis-Kern](algorithmic_capacity_evaluation.md) |
| Verbindliche gesättigte Referenz | [All-Stop-No-Wait](../reference/all_stop_no_wait_capacity_baseline.md) |
| Räumliche/zeitliche Definitionen, Linie/Doppelring | [Nachfragefamilien](../reference/demand_case_families.md) |
| Ältere vollständige Kapazitätsfrontierplanung | [Artificial capacity experiments](../plans/artificial_case_capacity_experiments.md) |
| Historische K20-Profile und Endwerte | [Folgekampagne](../findings/solver_followup_campaign.md), [CSV](../findings/solver_followup_results.csv) |
| Linienmodell, 3/14-Kataloggrößen, R2-Verlauf | [Linienbefund](../findings/reservoir_line_dispatch_pilot_20260912.md) |
| Globale AS-Schranke | [Kapazitätspilot](../findings/reservoir_capacity_phase_pilot_20260911.md) |
| Modellphysik und idealer Port | [Headway-Audit](../findings/headway_physics_audit_20260911.md) |
| Bestehende K20-Nachfrageintegration | [ddd_ring_demand_case.py](../../src/ropeway_skip_stop_optimization/benchmarking/ddd_ring_demand_case.py) |
| Verschachtelte Nachfrage und feste Bewertung | [fixed_timetable_capacity.py](../../src/ropeway_skip_stop_optimization/optimization/ddd/fixed_timetable_capacity.py) |
| Neue Profil-/Checkpointvorbereitung | [bestehende R2-Vorbereitung](../../benchmarks/run_reservoir_capacity_campaign.py) |
| Linienkatalog | [catalog.py](../../src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_lines/catalog.py) |
| Bestehende Linienzielfunktion | [cp_model.py](../../src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_lines/cp_model.py) |
| Linienrunner | [run_reservoir_lines.py](../../benchmarks/run_reservoir_lines.py) |
| Kleine Arc-Flow-Läufe | [run_ring_demand_case.py](../../benchmarks/run_ring_demand_case.py) |
| Gemeinsame Arc-Flow-Konfiguration | [ddd_fixed_k_arc_flow.py](../../src/ropeway_skip_stop_optimization/benchmarking/ddd_fixed_k_arc_flow.py) |
| Physische Sechs-Stationen-Beispiele | [artificial_headway_cases.py](../../src/ropeway_skip_stop_optimization/examples/artificial_headway_cases.py) |

**Nächste Entscheidung:** zuerst Stufe 0 fertigstellen und die T5-Kernmatrix
einfrieren. Den größten direkten Erkenntnisgewinn erwarten wir von sauberer
AS-Phasenoptimierung, der F2/F0/F4-Lastkurve und den kontrollierten kleinen
Reisezeitfällen. T6-Doppelring und Pflichtterminalvergleich folgen nach den
expliziten Integrationsprüfungen; sie sind keine Voraussetzung, um den bereits
validierten R2-Kapazitätsvorteil zu berichten.
