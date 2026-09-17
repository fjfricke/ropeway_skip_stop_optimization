# Stationsgeometrie: bisherige Überlegungen und Quellenstand

Stand 14.09.2026. Rechercheauftrag nach Freigabe des übrigen Versuchsplans;
keine Freigabe neuer Stationsmaße, keine Codeänderung und kein Solverlauf.

## Historisch dokumentierte Varianten

| Gegenstand | Bisherige Festlegung / Idee | Evidenz |
|---|---|---|
| Kompakte Station | 5 m Anfahrt, 3 m Bremsconnector, 10 m Plattform, 3 m Beschleunigungsconnector, 5 m Ausfahrt; 20 m direkter Bypass | Implementierte Zeit-/Graphabstraktion, kein nachgewiesener baulicher Entwurf |
| Gleich lange Pfade | 26 m Bypass, gleich dem vollständigen damaligen STOP-Pfad | Älterer Vorschlag in `artificial_case_capacity_experiments.md`, Step 0; sollte Geschwindigkeits- von Weglängeneffekten trennen; nicht aktueller Code-Default |
| Normale Stationskinematik | 3 m bei 6→0,3 m/s implizieren im konstanten Beschleunigungsmodell 5,985 m/s² | Eigene Plausibilitätsrechnung; alte Dokumente erklären den Connector ausdrücklich als Abstraktion |
| 0,5–1 m/s² | Entspräche bei 6→0,3 m/s etwa 35,91–17,955 m je Übergang | In `background_related_work.md` ausdrücklich illustrative, nicht belegte Betriebswerte |
| Neuester Chatvorschlag | 0,5 m/s², 35,91 m je Übergang, ca. 82 m Bypass | Nicht freigegeben; keine historische oder recherchierte Referenzgeometrie |

Die aktuelle `_station_direction_segments`-Funktion legt auch die schnellen
5-m-Connector auf den STOP-Zweig. Sie sind dort **keine gemeinsamen** Kanten
beider Routen. Ein gleich langer Bypass müsste unter der zuletzt vorgeschlagenen
Kinematik deshalb 5+35,91+10+35,91+5 = **91,82 m** lang sein. 81,82 m zählt nur
die inneren drei Phasen. Die letzte Chatbegründung mit gemeinsamen schnellen
Connectoren passte nicht zur aktuellen Graphdefinition.

Gleiche Weglängen sind eine Versuchsentscheidung, kein geometrisches Gesetz.
Ein gerader Bypass kann kürzer als eine gekrümmte Serviceführung sein. Eine
lange Serviceweglänge bestimmt ohne räumliche Führung weder Stationsgrundriss
noch Bypasslänge. Der historische 26-m-Vorschlag bleibt deshalb eine saubere
Kontrollidee, aber liefert keine realistische neue Bremsstrecke.

## Lokale Fundstellen

- [Herleitung vom 17.08., Abschnitt Cabin capacity and logical station geometry](../reference/topology_parameter_derivation/main.tex): explizite Abstraktionslabels; Kabinenhöhe 2,22 m, 3-m-Modellkabine und 0,5-m-Plattformabstand.
- [Alter Kapazitätsplan, Step 0](../plans/artificial_case_capacity_experiments.md): 26-m-Bypass als vorgeschlagene gleich lange Kontrolle; 20 m als gesondert zu erklärende Alternative.
- [Nachfrage-/Topologiereferenz, Common baseline parameters](../reference/demand_case_families.md): tatsächlich verwendete 10/20/5/3-m-Parameter.
- [Physikaudit vom 11.09.](../findings/headway_physics_audit_20260911.md): nominale Kinematik getrennt vom Notstopp-/Merge-Modell; Änderung erfordert neue Referenzen.
- [Thesis-Literaturübersicht, Parameters that remain assumptions](../../../idp_report/version_2/docs/background_related_work.md): 0,5–1 m/s² ausdrücklich nur hypothetische Beispiele.
- [Implementierung der Stationszweige](../../src/ropeway_skip_stop_optimization/examples/circular_skip_stop.py): `_station_direction_segments`.

## Erneut geprüfte externe Quellen

1. [Težak, Sever & Lep (2016), Increasing the Capacities of Cable Cars for Use in Public Transport](https://digitalcommons.usf.edu/jpt/vol19/iss1/1/), DOI 10.5038/2375-0901.19.1.1. Verlags-/Repositoriumsseite bestätigt die Idee mehrerer Plattformen und unabhängig bedienbarer Zwischenstationen. Kein daraus abgeleiteter Nachweis unserer konkreten Stationsmaße.
2. [Težak & Lep (2019), Constructional solutions for increasing the capacities of cable cars](https://elartu.tntu.edu.ua/bitstream/lib/28728/2/ICCPT_2019_Te_ak_S-Constructional_solutions_for_43-48.pdf), S. 45 und 47, §§3/4.3: explizit 3-m-Beispielfahrzeug, 0,5-m-Abstand und 3,5-m-Pitch; selektive Zwischenstationsbedienung in Fig. 4. Bestätigt Konzept und Pitchrechnung, nicht 10/20/26-m-Geometrie.
3. [Gu et al. (2013), An Optimization Design Method for the Acceleration and Deceleration Curves of Detachable Ropeway](https://www.scientific.net/AMR.774-776.199), DOI 10.4028/www.scientific.net/AMR.774-776.199. Zugänglicher Abstract behandelt S-Profile gegenüber konstanter Beschleunigung und Kabinenschwingung; liefert keinen dort verifizierbaren numerischen Standardwert für unsere nominale Beschleunigung.
4. [LEITNER Stationsbroschüre, The Long LEITNER Station](https://www.leitner.com/fileadmin/userdaten/00-home/Ordner-Facelift/PDF_s_Logo_neu/Compact_station/The_LEITNER_Station_.pdf): Stationsverlängerung 2,5–5 m, Plattformverlängerung bis 10 m und bis 50 % mehr Zeit im Stationsumlauf. **Verlängerung** um 10 m ist kein Beleg für eine insgesamt 10 m lange Plattform; Terminalumlauf ist nicht unser gerader Zwischenstationszweig.
5. [Geometric Method for Solving the Rope Path Curve for Cabin Deceleration in Cable Car Station (2025)](https://www.mdpi.com/2073-8994/17/11/1945): auffindbares 0,5-m/s²-Beispiel gehört zu einem anderen Fixed-Grip-/Seilkurvenkonzept und diskutiert Fehler einer früheren Konstruktion. Kein direkter Normalbetriebswert für unseren ausgekuppelten Reibrad-Servicepfad.

## Konsequenz

Die alte Arbeit begründet die Stationsarchitektur und getrennten Ressourcen
wesentlich stärker als konkrete bauliche Abmessungen. Die Geometrie bleibt
offen: 20 m ist die historische Abstraktion; gleich lange Pfade sind eine
gezielte Kontrollidee. Keines davon rechtfertigt, 0,5 m/s² und einen daraus
abgeleiteten langen Bypass als bereits belegten Hauptfall festzuschreiben.
Als nächster Kalibrierungsschritt sind ein nachvollziehbares normales
Geschwindigkeits-/Zeitprofil und dazu passende räumliche Bezugspunkte nötig.

## Nachrecherche: belastbarere Größenordnung für Stationsbeschleunigung

Nach erneuter Nachfrage nach tatsächlicher schneller Stationsverzögerung am
14.09.2026 gefunden: **Pour une accessibilité universelle du transport par câble
aérien en milieu urbain**, Juni 2023, Anhang §7.3, gedruckte Seite **138**
(PDF-Seite 139). Herausgabe/Erarbeitung im Umfeld DMA/GART, STRMTG/Cerema und
Branche. Die Tabelle wurde als PDF visuell geprüft.

- [Offizielle Veröffentlichung und institutionelle Einordnung](https://www.strmtg.developpement-durable.gouv.fr/le-guide-pour-une-accessibilite-universelle-du-a833.html)
- [Volltext beim GART](https://www.gart.org/wp-content/uploads/2023/08/Guide-accessibilite-transport-par-cable_Juin-2023.pdf#page=139)
- [Durchsuchbarer Volltext beim Ministerium](https://portail.documentation.developpement-durable.gouv.fr/pub/MPDOUV00263009-pour-une-accessibilite-universelle-transport-par-c.html)

Die Tabelle nennt als **indikative** beschleunigungs-/verzögerungsbedingte
Stationslängen:

| System | Seil / Plattform | Endstation | Zwischenstation |
|---|---|---:|---:|
| Monocâble | 6 / 0,2 m/s | 18 m | 36 m |
| 2S | 7 / 0,2 m/s | 24 m | 48 m |
| 3S | 8 / 0,2 m/s | 30 m | 60 m |

Bei Interpretation der 36 m als Summe zweier symmetrischer Übergangswege
ergeben sich 18 m je Übergang und eine äquivalente konstante Verzögerung
(6²−0,2²)/(2·18) = **0,9989 m/s²**. Dies ist **unsere kinematische Ableitung**,
kein im Leitfaden berichteter gemessener Beschleunigungsverlauf. Endstations-
Grundriss und zwei aufeinanderfolgende Übergänge in der Zwischenstation dürfen
nicht gleichgesetzt werden. Plattformwege sind in der oberen Tabelle separat
ausgewiesen; 36 m nicht als gesamte betriebliche Stationsweglänge verwenden.

Für unsere 6→0,3 m/s ergeben 1 m/s²: **5,7 s und 17,955 m je Übergang**.
0,5 m/s² würde Zeit und Weg verdoppeln. Die neue Primärquelle stützt damit
1 m/s² als äquivalenten nominellen Modellansatz wesentlich besser als die
frühere Übertragung von 0,5 m/s² aus einem anderen Boardingkonzept.
Ein realer S-Verlauf kann abweichende Spitzenwerte und Zeiten haben.

**Aktualisierte Empfehlung, noch nicht freigegeben:** 1 m/s² symmetrisch als
literaturgestützte äquivalente Stationskinematik; keine Übernahme als normative
Höchstgrenze oder gemessener Herstellerstandard. Normale Stationskinematik
bleibt vom Notstopp-Parameter des Merge-Modells getrennt. Keine automatische
Änderung von Code, Stationsmaßen oder bereits freigegebenen Parametern.

### Anschließende Freigabe und offene Gesamtlänge

Der Nutzer hat 1 m/s² anschließend ausdrücklich bestätigt. Bei 6↔0,3 m/s
sind je 17,955 m und 5,7 s daraus abgeleitet. Weitere Stationsmaße bleiben offen.

Neue Vergleichsrechnung unter Beibehaltung der bisher 5 m langen schnellen
STOP-Connector:

- 10 m Plattform: vollständiger STOP-Pfad 55,91 m, No-Wait-Dauer 46,4 s.
- 15 m Plattform: vollständiger STOP-Pfad 60,91 m, No-Wait-Dauer ca. 63,0667 s.

Die obere Tabelle des Leitfadens auf S.138 nennt für Monocâble bei 0,2 m/s
5 m je Ein-/Ausstiegsbereich und Verdopplung bei getrennten Bereichen.
Eine eigene Übertragung derselben insgesamt 50 s langsamen Passage auf 0,3 m/s
ergibt 15 m. Dies begründet einen 15-m-Kandidaten, ist kein in der Quelle direkt
genanntes 0,3-m/s-Maß und kein Nachweis eines Mindestbedienungszeitbedarfs.

Empfehlung zur Diskussion: 15 m Plattform und 60,91 m STOP-Pfad; Bypass
derselben Gesamtlänge als kontrollierte abstrakte Hauptgeometrie, ohne
zusätzlichen Wegverkürzungsvorteil. Dies ist kein maßstäblicher baulicher
Nachweis paralleler Wege. Ein direkter kürzerer Bypass erfordert eine separat
begründete räumliche Führung. Freie Interstationsseile (G300/G800/G1200)
bleiben unabhängig; die Station wird zusätzlich gezählt. Ein gleicher
Bypass hätte 10,1517 s Fahrzeit und ca. 52,915 s No-Wait-Zeitvorteil gegenüber
STOP. Die Gesamtlängenempfehlung ist noch nicht freigegeben. T6L-Terminals
benötigen einen eigenen Umlenk-/Wendeweg und werden nicht als identischer
gerader Zwischenstationspfad ausgegeben.

**Nachfolgender Entscheid vom 14.09.2026:** Der Nutzer hat diesen Vorschlag
mit „ja passt übernimm das“ bestätigt: 15 m Plattform, je 5 m schnelle
STOP-Connector, je 17,955 m Brems-/Beschleunigungsweg bei 1 m/s² und gleiche
STOP-/Bypasslänge von 60,91 m. Die vorherigen offenen Formulierungen in diesem
Rechercheverlauf dokumentieren den damaligen Stand; maßgeblich sind jetzt
§§6–7 des Entscheidungsregisters. Terminalwendewege bleiben offen. Keine
Implementierung oder Änderung historischer Instanzen durch diese Freigabe.
