# Plan: Beispiele, Nachfrageprofile und Betriebsverträge für die Thesis

Stand: 14.09.2026. **Implementiert und kalibriert.** Die begrenzte Kampagne
schloss 19/19 Läufe in 49,5 Minuten ab. Ergebnisse und Fortsetzungsentscheidung:
[`../findings/thesis_calibration_results_20260914.md`](../findings/thesis_calibration_results_20260914.md).
Die Streckenlängen wurden am 14.09.2026 bestätigt; die aktuelle Freigabe und
Quellennachweise stehen im
[Entscheidungsregister, § 6](../thesis/experiment_definition_register_20260913.md).
Für die inzwischen ebenfalls bestätigten Nachfragefunktionen gelten dort
§§ 12–13; ältere Funktions- und Bucketvorschläge dieses Implementierungsplans
sind nicht als neuer Nachfragevertrag zu übernehmen.
Die Umsetzung verwendet neue, versionierte Instanzen und verändert keine
historische Instanz. Sie startet die vollständige Thesis-Kampagne nicht.
Dieser Plan konkretisiert den [Versuchsplan](../thesis/experimental_design_20260913.md).
Die zugehörige Größenprüfung steht im
[Intervall- und Skalierungsplan](reservoir_line_interval_scaling_20260913.md).

**Neuere Methodenentscheidung nach der Kalibrierung:** Für die Kapazitätsreihen
wurde evolutionäre Linienplanung mit kleinem begründetem Musterkatalog gewählt;
Labelled Arc-Flow bleibt die Journey-Methode. Die unten beschriebene native
V2/V3-Pipeline ist der historische Implementierungs-/Kalibrierungsstand und
nicht mehr automatisch die Hauptmethode der finalen Kapazitätskampagne.
Aktuelle Festlegungen und offene Compute-/Zeitfragen stehen im
[Versuchsplan](../thesis/experimental_design_20260913.md).

**Neue Geometrieentscheidung:** G500 mit 500 m freien Seilabschnitten wird
gemeinsame Hauptgeometrie. Quellenbezug: untere veröffentlichte
C1-Stationsdistanz, siehe Entscheidungsregister §6. Der vorhandene
`THESIS_GEOMETRIES`-Katalog enthält G500 noch nicht; Profil, Frontendauswahl,
Instanzidentität und Referenzkalibrierung sind vor dem Freeze zu ergänzen.
Historische G300/G800-Ergebnisse bleiben unverändert.

## Implementierungsstand

- `ExperimentCaseSpec`, T5R/T6R sowie G300/G800/G1200/GUNEQ-v2:
  `benchmarking/thesis_cases.py` und `examples/thesis_cases.py`.
- Phasenoptimierte regelmäßige All-Stop-Referenz einschließlich vollständiger
  Phasendomäne: `optimization/ddd/all_stop_phase.py`.
- Einklammern und ganzzahlige Bisektion für Reservoir- und Fixed-K-All-Stop:
  `benchmarking/thesis_all_stop_capacity.py`.
- Zweistufige Linienplanung mit 70 % Konstruktion und 30 % vollständigem
  Fixed-Route-CP-SAT-Timing: `optimization/ddd/reservoir_lines/pipeline.py`.
- Gemeinsamer Einzelrunner: `benchmarks/run_thesis_experiment.py`.
- Harte zweistündige Kalibrierung: `benchmarks/run_thesis_calibration.py`.
- Der Supervisor begrenzt den gesamten Prozessbaum auf höchstens 32 GiB,
  protokolliert Swap und beendet nach 30 s kritischem Speicherdruck.
- Das Frontend bezeichnet die unabhängigen Wahlen als Topologie und Geometrie
  und zeigt die tatsächlich geladenen Längen, Geschwindigkeiten, Stationszeiten,
  Mechanismus-Headway, Umlaufzeit, Betriebsfenster und Nachfrage.

## 1. Ziel und Abgrenzung

Mit wenigen nachvollziehbaren Fällen untersuchen, wann Skip-Stop Reisezeit,
Bedienungsleistung oder Flotteneffizienz verbessert. Die drei Hauptmethoden
bleiben: phasenoptimiertes gesättigtes All-Stop-No-Wait als Referenz, vollständiges
Labelled Arc-Flow für geeignete kleine Fixed-Start-No-Wait-Fälle und eingeschränkte
Linienplanung mit CP-SAT für größere optionale Flotten.

Keine neue Solverfamilie, kein eigener Suchcontroller und kein pauschales
Versprechen globaler Skip-Stop-Optimalität. Alte Beispiele, Standardwerte,
Checkpoints und Ergebnisse bleiben unverändert. Neue Fälle erhalten neue IDs.

## 2. Gemeinsame Konfiguration statt kopierter Beispielklassen

Ein unveränderliches `ExperimentCaseSpec` soll die vorhandenen Domänenbuilder
komponieren. Die Namen in diesem Abschnitt sind vorgeschlagene Schnittstellen.

| Baustein | Inhalt |
|---|---|
| `GeometryProfile` | Stabile gerichtete Abschnitts-IDs mit Längen, Stationsphasen, Seil-/Plattformgeschwindigkeit, Kabinenkapazität und -geometrie |
| `TechnologyProfile` | Getrennte Seil-, Plattform-, Merge- und Mechanismusregeln; Architektur A/B/C bleibt ausdrücklich benannt |
| `DemandProfile` | OD-Gewichte, feste Freigabezeitpunkte und Zellgewichte, stabile Integer-Präfixfolge |
| `OperatingContract` | Initialisierung, Dispatchbereich, Nachfragefenster, Bedienungsdeadline, Rückkehr, Waiting und Flottenobergrenze |
| `ParameterEvidence` | Parametername, Einheit, Quelle/Abschnitt/Abrufdatum, Originalwert, Ableitung, Implementierungswert, Evidenzklasse |

Topologie, Geometrie, Nachfrage und Solverkonfiguration bleiben getrennt.
Metadaten ersetzen keine bestehenden physikalischen Validatoren.

Betroffene Integrationsstellen:

- `src/ropeway_skip_stop_optimization/examples/circular_skip_stop.py`:
  bisheriger gemeinsamer Abschnittswert; neue Zuordnung pro gerichteter Kante
  mit explizitem Rückfall auf den Legacy-Skalar.
- `examples/artificial_headway_cases.py` und `examples/registry.py` unter
  demselben Paket: neue Profile registrieren, Legacy-IDs unverändert lassen.
- Bestehende Nachfragepräfix-Erzeugung und die jeweiligen Fixed-K-/Reservoir-
  Problemadapter wiederverwenden; keine unabhängige zweite Physik implementieren.
- Neue Konfiguration beim Export/Import und im Frontend transportieren; genaue
  Serialisierungsschnittstellen vor dem ersten Codepatch lokalisieren.

Änderungen an Geometrie, Nachfrage oder Zeitvertrag erzeugen einen neuen
Problem-Fingerprint. Reine Darstellungspräferenzen ändern ihn nicht. Modell-
Encoding und Katalog erhalten zusätzlich den vorhandenen Modell-Fingerprint.

## 3. Geometrie und Parameter mit Quellen einfrieren

### Bestätigte Längenprofile vom 14.09.2026

| Profil | Freie Seilstrecken | Rolle |
|---|---|---|
| Historisch | bisherige 150 m, 5 m/s, 0,5 m/s, Kapazität 8 | Unveränderte Regression |
| Dicht | je 300 m | Kompakter Kontrollfall |
| Urbaner Hauptfall | je 800 m | Bestätigte Hauptgeometrie der Kapazitätsstudie |
| Weit | je 1.200 m | Nachrangige Längensensitivität, falls das Budget reicht |
| GUNEQ-v2 | im Sechser-Ring 500/1.100/900/600/700/1.000 m, in Stationsreihenfolge | Gezielter Robustheitstest bei gleicher Gesamtlänge wie sechs 800-m-Abschnitte |

Die neuen numerischen Längen sind eigene Versuchsentscheidungen. Hersteller-
Linienlängen geteilt durch Stationszahl minus eins liefern nur mittlere
Abschnittslängen; sie sind keine exakten freien Seilsegmente des Codes.
Streckenlängen sind außerdem weder automatisch Kartenluftlinien noch Stützenabstände.

Quellen für die Längenauswahl, geprüft am 14.09.2026:

- [LEITNER, Manizales Línea 3](https://www.leitner.com/en/company/references/detail/gd10-cable-aereo-de-manizales-linea-3/):
  2.328 m und vier Stationen; eigene Rechnung: im Mittel 776 m je Interstation.
- [POMA, Medellín Línea P](https://www.poma.net/en/work/p-line-metrocable/):
  technische Länge 2.656 m und vier Stationen; eigene Rechnung: etwa 885 m.
- [Doppelmayr, La Paz Línea Blanca](https://lapaz.doppelmayr.com/en/):
  2.847 m und vier Stationen; eigene Rechnung: 949 m.
- [Île-de-France Mobilités, Câble C1](https://www.iledefrance-mobilites.fr/le-reseau/projets/cablec1/mediatheque/kit-presse-c1):
  ausdrücklich 500–1.800 m zwischen den fünf Stationen. Dies belegt reale
  Ungleichmäßigkeit, nicht unsere synthetische Folge.

Die Quellwerte motivieren die Größenordnung; 800 m ist unsere synthetische
Wahl. GUNEQ-v2 ersetzt den früheren Planvorschlag mit abwechselnden 400/1.200 m
für neue Thesisfälle, ohne historische Artefakte umzuschreiben. Für reine
Geometrievergleiche zunächst richtungsstabile ODs wählen; eine Änderung der
kürzeren Richtung getrennt kennzeichnen. GUNEQ-v2 ist ausschließlich für T6R
festgelegt und wird nicht automatisch auf die anderen Topologien übertragen.

Am 14.09.2026 für alle neuen Thesisfälle bestätigt: 6 m/s Seilgeschwindigkeit,
0,3 m/s Plattformgeschwindigkeit und zehn Personen je Kabine. Quelle:
[Haimerl et al. (2022), Regensburg, § 4.1, S. 1418](https://informs-sim.org/wsc22papers/138.pdf),
geprüft am 14.09.2026. Die publizierte, mit Herstellern abgestimmte
Planung verwendet zehn Plätze, 0,3 m/s in Stationen und einen einstellbaren
Seilbereich von 0–6 m/s; wir wählen dessen Obergrenze. Dies sind
Planungsannahmen, keine Betriebsmessungen. Die anlagenspezifischen 60 m
Seilabstand aus derselben Quelle sind nicht Bestandteil dieser Zahlenfreigabe;
unsere Headways benötigen ihre eigene Begründung. Keine zusätzliche
Geschwindigkeitssensitivität ist beschlossen. Historische Fälle bleiben erhalten.
Eine gemeinsame Seilsektion erhält eine gemeinsame Geschwindigkeit. Gegenrichtungen
verwenden dieselben physischen Abschnittslängen mit korrekt umgekehrter Kantenabbildung.

### Bestätigte Stationsgeometrie und Umsetzungsgate

Am 14.09.2026 ausdrücklich freigegeben: symmetrische normale Beschleunigung
1 m/s², 15 m Plattform, je 5 m schnelle STOP-An-/Ausfahrt, je 17,955 m
Brems-/Beschleunigungsweg. STOP und Bypass sind **je 60,91 m** lang.
Freie Seilabschnitte bleiben zusätzlich bestehen. Unquantisierte No-Wait-Zeiten:
STOP 63,066666… s, SKIP 10,151666… s, Differenz 52,915 s.

Quelle und eigene Ableitung: [Leitfaden 2023, §7.3, S.138](https://www.gart.org/wp-content/uploads/2023/08/Guide-accessibilite-transport-par-cable_Juin-2023.pdf#page=139)
und [Rechercheprotokoll](../research/station_geometry_history_20260914.md).
Die dort indikativen 36 m für Beschleunigung/Verzögerung einer Zwischenstation
motivieren 1 m/s² als äquivalenten Wert. Zwei 5-m-Plattformbereiche bei 0,2 m/s
motivieren insgesamt 50 s langsame Passage, bei unseren 0,3 m/s also 15 m.
5-m-Connector und gleiche Pfadlängen sind eigene geometrische Entscheidungen.
Es handelt sich um eine abstrakte Referenz, nicht um einen zertifizierten
Stationsentwurf. T6L-Terminal-Wendewege bleiben separat offen.

1. Gemeinsamen Stationsbuilder parametrisieren, ohne Legacy-Defaults zu ändern.
   Die bisher hart codierten 3-/5-m-Connector durch ein explizites Profil für
   neue Fälle ergänzen; dieselbe Geometrie in EAN/Arc-Flow, Reservoir und Viewer.
2. Nominales Beschleunigungsprofil und Zeitinterpolation prüfen; Dauern aus
   denselben Phasen berechnen, nicht zusätzlich pauschale Stationsverluste
   aufschlagen. Vorhandenen Integer-Tickvertrag beibehalten.
3. Phasensummen, Beschleunigung, gleiche STOP-/SKIP-Pfadlänge und neue
   Ressourcenzeiten unabhängig nachrechnen. Durchgehender Bypass erhält die
   5-m-STOP-Connector nicht zusätzlich. All-Stop-Umlauf, Sättigungsflotte,
   Starts und Referenzfahrpläne für neue Instanzen neu erzeugen.
4. Aussteigerankunft bleibt vor Exit-Waiting; Nachfragefreigabe bezieht sich
   auf den tatsächlichen Plattformausstieg der einsteigenden Kabine. STOP-only
   Waiting bis zum separat bestätigten Maximum 1.200 s, kein Mehrkabinenpuffer.
5. Nominalen 1-m/s²-Wert vom Notstopp-/Merge-Modell getrennt halten. Neue
   Problem-Fingerprints und Export-Metadaten; Legacy-Fahrpläne unverändert
   reproduzieren. Tests für No-Wait, Waiting und Horizont-/Portgrenzen.
6. Nach Klarstellung vom 14.09.2026 die ideale selektive Ausschleusung von
   Architektur B erhalten; keine zusätzliche Auskuppelressource einführen.
   Am Reservoir stattdessen den bestätigten gemeinsamen Rope-Headway für
   Dispatch, Umlaufpassage und letzte Ankunft vor Entnahme ergänzen.
   Beschleunigung und Lagerbewegungen bleiben idealisiert. Dieser Portschutz
   ist inzwischen implementiert und geprüft; siehe
   [Abnahmebericht](../findings/reservoir_port_rope_headway_20260914.md).
   Historische Legacy-Fälle behalten ihren alten Vertrag. Quelle und Gegenbeispiel:
   [Headway-Physikaudit, § 3](../findings/headway_physics_audit_20260911.md).
   Umsetzung, Vertragsversionierung, Testmatrix und Thesisänderungen gemäß
   [Reservoir-Portplan](reservoir_port_rope_headway_20260914.md).

**Zwischentests:** unveränderte Legacy-Zeiten und Ressourcen, Längenänderung nur
auf der gewählten Kante, richtige Gegenrichtungsabbildung, STOP/SKIP-Phasen,
Grenzfälle der Headways und unabhängige Zertifikatsprüfung. Bei identischen
neuen/alten Parameterwerten muss dieselbe physikalische Domäne entstehen.

## 4. Zeitprofile: Rate und Batch tatsächlich unterscheiden

| Profil | Neue Konstruktion | Kontrollfrage |
|---|---|---|
| P0 verteilt | Konstante OD-bezogene Rate, zunächst feste Freigabestützstellen im Abstand von 60 s | Gleichmäßigerer Betrieb ohne gemeinsame Fünfminutenpulse |
| P1 Peak | Normierte Gewichte 1/2/3/4/5/4/3/2/1 über neun Fünfminutenintervalle, innerhalb der Intervalle verteilt | Peak bei unveränderter Gesamtmenge |
| P4 Batch | Drei gleich große Pulse bei Minute 0/15/30 | Bewusste gebündelte Zubringerankünfte |
| P0 fein | 30-s-Stützstellen, zunächst nur kleiner Kontrollfall | Einfluss der Nachfrageauflösung und zusätzliche Modellgröße |

60/30 s sind experimentelle Freigabeauflösungen, kein Bewegungszeitraster und
keine Poisson-Simulation. Beispielsweise P0 im halboffenen Nachfragefenster
`[0, 45 min)`; die Stützstellen werden vor jeder Nachfragehöhensuche eingefroren.
Pro N keine Freigabezeitpunkte verschieben. Die vorhandene verschachtelte
Integer-Zuordnung verteilt zusätzliche Personen auf dieselben stabilen Zellen.

Historische neun Bucketfreigaben erhalten ihre alte ID und werden explizit als
gleich große periodische Batches beschrieben. Keine rückwirkende Umbenennung
historischer Ergebnisdateien. Vergleich von 60 und 30 s ist eine Sensitivität
mit unterschiedlichen Nachfrageinstanzen, keine exakte Modelläquivalenz.

Zeitlich versetzte F2-Cluster erst nach P0: Phasenverschiebung innerhalb eines
festen Rahmens so konstruieren, dass Endrandeffekte gesondert sichtbar sind.
Nicht eine geringere Restbedienungszeit als reinen Synchronisationseffekt ausgeben.

**Zwischentests:** exakte Gesamtmenge, Zellweise-Nesting für N und N+1,
Reproduzierbarkeit, normalisierte Gewichte, keine Freigaben außerhalb des Fensters,
unveränderte historische Präfixe. Nachfragegruppenzahl in den Größenbericht aufnehmen.

## 5. Raumprofile und gezielte Robustheit

Kern: F2 komplementär, F0 diffus und F4 lokal. Ergänzend:

- `0,8 * normiertes F2 + 0,2 * normiertes F0`: weniger idealisierte Cluster.
- F2 mit 75/25 statt 50/50 Marktanteilen: freie Flottenverteilung testen.
- F3 lange Wege für die kleine Journey-Time-Studie mit vollständiger Bedienung.

Die Mischung wird auf OD-Gewichten vor Integer-Erzeugung gebildet; überlappende
OD-Zellen werden addiert, nicht doppelt angelegt. F0-Anteile auf F2-ODs sind dabei
zulässig und müssen in der Beschreibung der Mischung sichtbar bleiben.

Bei Geometriesensitivitäten die OD-Paare zunächst festhalten. Anzahl der
Zwischenhalte und tatsächlich zurückgelegte Distanz separat ausweisen. F4 ist
eine Negativhypothese, kein Satz über zwangsläufig fehlenden Skip-Stop-Nutzen.
F1/F5/F6, Tagesprofile und stochastische Robustheit folgen nur bei klarer Zusatzfrage.

## 6. Betriebszeit, Anfangszustand und Flotte

### Zeitachsen eindeutig trennen

Nachfragefreigaben über 45 min, Zielankunft zunächst spätestens nach 60 min;
Vorlauf und Rückkehr bilden separate Phasen ohne neue Personen. Diese Werte
sind vorgeschlagen, nicht aus den historischen Fällen übertragene Konstanten.

Die bisherigen pauschalen 300 s Vorlauf/Rückkehr werden für neue Geometrien
nicht ungeprüft übernommen. Zunächst vollständig geprüfte All-Stop-Pläne
aufbauen und den Initialisierungs- und Rückkehrvertrag erfüllen. Die Reserve
muss mit erlaubten Waiting-Grenzen und letzter aktiver Bewegung kompatibel sein.

**Hauptfrage ist regulärer Betrieb.** Zwei technisch unterschiedliche Optionen:

1. Geprüfte leere Vorlauftrajektorien aus dem bestehenden Single-Use-Reservoir
   explizit mitführen; erste Dispatchzeit bleibt in der Gesamtzeitachse null,
   Nachfragebeginn liegt später. Beide Methoden erhalten denselben Vertrag.
2. Falls der Vorlauf die Modelle zu stark vergrößert: ein eigener Adapter für
   bereits laufenden Betrieb mit geprüften Anfangsreservierungen. Das ist eine
   neue Domäne mit eigenen Replays, keine bloße Umbenennung der Reservoirzeiten.

Option 1 zuerst prüfen. Option 2 nur nach dokumentierter Größenentscheidung.
Eine lange Vorlaufphase allein beweist noch keine stationäre Auslastung:
Kabinen-/Stationspräsenz beim Nachfragebeginn und mögliche Randeffekte berichten.
Kaltstart als separaten Fall bezeichnen; Zeit-/Nachfragehorizonte nicht je Solver
anpassen, um einer Methode einen Vorteil zu verschaffen.

### Flotten- und All-Stop-Vertrag

- Je Geometrie/Technik die gesättigte All-Stop-Flotte und deren zulässige
  regelmäßige Bewegung neu bestimmen und validieren. `floor(C/h)` nur verwenden,
  wenn seine Voraussetzungen für diese Topologie/Ressourcen nachgewiesen sind.
- K38 und Max50 bleiben historische Größen und werden nicht als Cap neuer
  einringiger Fälle übernommen. Fünf geometrisch verteilte Caps reichen von
  K_AS bis zur aus Dispatchfenster und Reservoir-Portheadway abgeleiteten
  Port-Durchsatzobergrenze; doppelte Werte entfallen. Diese Grenze ist eine
  notwendige Obergrenze und keine Machbarkeitsgarantie für jede kleinere
  Flotte. Die Kalibrierung prüft zunächst
  die ersten drei Größen, bevor sehr große Caps Solverzeit erhalten.
- Der Cap muss All-Stop-Sättigung zulassen, sonst separat „flottenbegrenzt“ melden.
  Skip-Stop darf weniger als K_AS einsetzen; ungenutzte Slots kosten dennoch Modellgröße.
- Die geometrischen Caps dienen ausschließlich als spätere Messpunkte. Gute
  Incumbents werden zuvor über die im Entscheidungsregister definierte adaptive
  Flottenleiter aufgebaut. Für T5R/G800 beginnt sie aus dem vorhandenen
  Elf-Kabinen-Zeugen bei Kmax 16. Jede Stufe übernimmt den validierten
  No-Wait-Konstruktionsplan der vorigen Stufe; der Waiting-Plan wird getrennt
  ausgewertet. Zwei Caps ohne Bedienungs- oder Flottenzuwachs beenden die
  Leiter. Ein frischer unabhängiger Start je Cap erfüllt diesen Test nicht.
- Gesättigtes All-Stop-No-Wait über die Phase und ganzzahlige Fahrgastzuordnung
  exakt auswerten. Bei Reisezeit gilt U=0 und das passende Reisezeitziel.
  Kritische Phasen und zulässiges Phasenintervall unter dem gewählten Randvertrag
  nachweisen; nicht nur eine günstig erscheinende Phase auswerten.
- Alte globale Bounds nur bei identischer Domäne übertragen. Größere Teilbedienung
  und größere vollständig bedienbare verschachtelte Profilnachfrage getrennt berichten.

Im Doppelring sind gemeinsame Nachfrage, Richtungsflotte und zwei Phasen
zusammen zu behandeln. Kein getrenntes Optimieren und anschließendes Addieren
doppelt angelegter Nachfrage.

## 7. Betriebskonzepte und Reihenfolge der Topologien

Primär feste Linienmuster pro Einsatz, optionale Flotte, No-Wait und ein
deklarierter Dispatchbereich. Keine neue Mustervorgabe pro Kabinenindex;
eine Startlösung bleibt ein Hint. Erste Abfahrt null und frühe Dispatchbegrenzung
sind Einschränkungen des Linienmodells, keine physikalischen Naturgesetze.

Reihenfolge: historischer Fünferring → neuer einzelner Sechserring → erst danach
Doppelring bzw. Linie mit Pflichtterminals. Doppelring und Linie müssen ihre
eigenen Ressourcen-/Flottenadapter und kleinen Tests bestehen.

Waiting 30/60 s ist eine spätere Ablation auf ausgewählten Fällen. Das bestehende
Linienintervallmodell unterstützt ausschließlich No-Wait. Lokales Waiting
verschiebt nachfolgende Ressourcen und Fahrgastzeiten; hierfür ist ein gesonderter
Builder-/Semantikplan erforderlich. Keine einfach verlängerten festen Intervalle.
Wiedereinsatz, Musterwechsel im Einsatz und Richtungswechsel bleiben außerhalb.

## 8. Frontend: Längen und Konsequenzen tatsächlich sichtbar machen

Im bestehenden Scenario-Viewer Geometrieprofil und Topologie getrennt auswählen.
Jeden Abschnitt mit seiner realen Modelllänge und Fahrzeit beschriften. Zwei
klar benannte Darstellungen: schematisch und längenbezogen. Nicht behaupten,
dass beliebige Ringlängen automatisch eine maßstabsgerechte ebene Karte ergeben.

Betroffene vorhandene Einstiegspunkte: `frontend/src/pages/ScenarioPage.tsx`,
`frontend/src/components/ScenarioView.tsx`, `frontend/src/scenarioLayout.ts`
und die zugehörigen Typen/Datenadapter. Konkrete Komponenten nach Prüfung
weiterverwenden statt einen zweiten Viewer aufzubauen.

Profilwechsel zeigt neu berechnete Zeiten, Quellenstatus und Flottenreferenz.
Alte Fahrpläne nur mit passendem Fingerprint abspielen; ein Wechsel lädt ein
passendes Ergebnis oder zeigt ausschließlich die neue Geometrie. Kein optisches
Streckenstrecken bei unverändertem Physikmodell. Freie Bearbeitung einzelner
Längen zunächst optional nach den geprüften Presets; dann als eigene Instanz speichern.

**Zwischentests:** alle Abschnittslängen sichtbar, richtige Richtung, Summen,
Profilwechsel ohne veralteten Replay, Legacy-Ansicht weiterhin nutzbar;
visuelle Prüfung langer und ungleichmäßiger Strecken.

## 9. Umsetzungsetappen und Abnahmekriterien

| Schritt | Lieferung | Abnahme vor Fortsetzung |
|---|---|---|
| E1 | Quellenregister und versionierte Specs | Werte/Einheiten/Bezugspunkte geprüft; Unbelegtes gekennzeichnet |
| E2 | Kantenlängen und Stationsprofile | Legacy-Replays identisch; gerichtete Geometrie- und Phasentests bestanden |
| E3 | Nachfrageadapter | Integer-/Nesting-/Zeitfenstertests; Gruppenanzahl dokumentiert |
| E4 | Zeitvertrag und All-Stop-Phase | Kleine Enumeration, Deadline-Ticks, Vorlauf/Rückkehr und gesättigter Referenzplan geprüft |
| E5 | Build-only-Matrix | Größenbefund gemäß Intervallplan; keine stillen Modellkürzungen |
| E6 | Viewerintegration | Profile und Längen sichtbar; Ergebniszuordnung korrekt |
| E7 | Begrenzte Suche | Gleiche Fälle/Budgets, gültige native Lösungen und vergleichbare Referenzen |
| E8 | Befund | Mechanismus, Grenzen, Quellen und Gültigkeitsbereiche dokumentiert |

Zuerst E1–E5. Neue physikalische Kalibrierung und neue Kodierung nicht im selben
Performancevergleich verändern. Bei Größenproblemen zunächst den größten
Verursacher feststellen, nicht Nachfrageauflösung, Musterkatalog und Flotte
gleichzeitig reduzieren. Größere Kampagnen benötigen einen separat festgelegten
Laufplan; dieser Dokumentationsauftrag startet sie nicht.

## 10. Quellen und Anschlussdokumente

- [Haimerl et al. (2022), §4.1–4.2](https://informs-sim.org/wsc22papers/138.pdf):
  herstellerabgestimmte Regensburg-Planung, 6/0,3 m/s, zehn Personen, 60 m
  Auslegungsabstand; Nachfrageprofile sind keine Messdaten einer betriebenen Anlage.
- [STRMTG: Monocable gondola lifts](https://www.strmtg.developpement-durable.gouv.fr/en/gondola-lift-continuous-movement-unidirectional-a132.html):
  technische/regulatorische Einordnung von Seil- und Stationsgeschwindigkeit.
- [Doppelmayr: La Paz](https://lapaz.doppelmayr.com/en/) und
  [LEITNER: Manizales Línea 3](https://www.leitner.com/en/company/references/detail/gd10-cable-aereo-de-manizales-linea-3/):
  Anlagenlängen und Stationszahlen zur Größenordnung, keine Skip-Stop-Zertifizierung.
- [LEITNER Quick Switch](https://www.leitner.com/fileadmin/userdaten/00-home/Ordner-Facelift/PDF_s_Logo_neu/Station_sheets/The_LEITNER_Station_quick_switch.pdf):
  konkrete Komponentenspezifikation, kein pauschaler B/C-Headway.
- [Literaturinventar mit Parametervergleich](../../../idp_report/version_2/docs/background_related_work.md),
  [Physikaudit](../findings/headway_physics_audit_20260911.md),
  [verbindliche All-Stop-Referenz](../reference/all_stop_no_wait_capacity_baseline.md).

Abruf der übrigen Webquellen für die Parameterdiskussion: 13.09.2026;
Längenquellen in § 3 erneut geprüft am 14.09.2026.
Ältere Nachfrage-/Kapazitätspläne enthalten teilweise die All-Stop-Flottenfrontier
als Hauptreferenz; bei Umsetzung auf diesen verbindlichen Phasenvergleich
abgleichen und veraltete Planvorgaben ausdrücklich ersetzen.
