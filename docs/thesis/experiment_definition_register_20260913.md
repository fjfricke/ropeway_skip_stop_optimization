# Entscheidungsregister für die Thesis-Experimente

**Umsetzungsnachtrag 15.09.2026:** Die ausführbare Fixed-K-/N-Steuerung und
das lesende Detailfrontend sind umgesetzt. Aktuelle Messgates und offene
Referenzintervalle stehen im [Abschlussbefund](../findings/thesis_completion_20260915.md);
die [Ausführungsregeln](../plans/thesis_study_execution_20260915.md) unterscheiden
exakte Referenzreihen und ausdrücklich gekennzeichnete untere Referenzwerte.
Die vollständigen Thesisreihen wurden noch nicht gestartet.

Stand: 14.09.2026. Dieses Dokument führt die bisher verteilten Festlegungen zu
Geometrie, Technik, Betrieb, Nachfrage, Vergleichsmethoden und Auswertung an
einer Stelle zusammen. Es ist noch keine eingefrorene Versuchsspezifikation.
Wir gehen die Kategorien in der unten angegebenen Reihenfolge durch und setzen
ihren Status danach auf `FROZEN`.

Es werden in diesem Dokument keine Instanzen geändert und keine Solverläufe
gestartet.

### Verbindliche Antworten zur Integration — 14.09.2026

Die folgenden Antworten auf die 21 Integrationsfragen haben Vorrang vor
abweichenden älteren Planungsständen. Sie autorisieren noch keine Kampagne.

**Anschließend bestätigt:** höchstens zwei Stunden tatsächliche Wandzeit für
die Kalibrierung nach Implementierung und Korrektheitstests. Die Hauptbudgets
werden daraus abgeleitet. Konkrete Schritte und Gates stehen im
[Integrationsplan](../plans/thesis_experiment_frontend_integration_20260914.md).

| Fragen | Festlegung |
|---|---|
| 1–2 | Frontend ausschließlich zum Beobachten, keine Start-/Stopp-/Queue-Steuerung. Lokal nutzbar; veröffentlichte Repository- und Thesis-Ergebnisdaten sollen später auch von anderen betrachtet werden können, ohne Solver oder private absolute Dateipfade. Kein Hostingauftrag. |
| 3 | Eingefrorene Thesisfälle und explorative Fälle getrennt darstellen. Änderungen ergeben neue Fallversionen; gespeicherte Läufe behalten ihre ursprüngliche Spezifikation. |
| 4–5 | Historische Ergebnisse in ein getrenntes Archiv; Oberfläche und Exportbeschriftungen Englisch. |
| 6 | Zwölf Kerngruppen: Kapazität T5R/T6R × F0/F2/F3/F4; Journey T5R × F0/F2/F3/F4. T6R-Journey nur nach späterem Gate, nicht Teil dieser Hauptmatrix. |
| 7–9 | T6L nicht in dieses Paket aufnehmen. G500/P0 als gemeinsame Hauptkonfiguration, zunächst gleiche freie Abschnittslängen. Bestehende G300/G800/G1200 als auswählbare Kontrollen erhalten; keine automatische zusätzliche Kampagne oder neue ungleichmäßige Geometrie. |
| 10 | Reservoirkabinen müssen durchgehend weiterfahren: erste vollständige Umlaufrückkehr am oder nach der Bedienungsdeadline. Keine vorzeitige Rückkehr, auch nicht bei leerer Kabine. Single-Use bleibt bestehen. |
| 11 | Kleiner Musterkatalog deterministisch aus der Nachfrage, vor Suche eingefroren. Konkrete Erzeugungsregel im Umsetzungsplan präzisieren; keine ergebnisabhängige Maskenauswahl. |
| 12–13 | Evolution mit Musterfolge und Dispatchgenen sowie Intervall-Decoder. Ausschließlich No-Wait, keine Waiting-Reparatur oder nachgelagerte Waiting-Optimierung. Waiting bleibt einem möglichen späteren Paket vorbehalten. |
| 14–15 | All-Stop-Referenzen automatisch vor den Reihen kalibrieren; bestätigte Bedienung, bewiesene Grenzen und offene Intervalle getrennt ausweisen. K_ref, K-Stufen und Laufbudgets durch Vortests bestimmen. Kalibrierung anschließend mit höchstens zwei Stunden bestätigt; Hauptbudgets noch offen. |
| 16–17 | Lösungen dürfen innerhalb einer K-Reihe weitergegeben werden. Kein vorgegebener All-Stop- oder bekannter guter Skip-Stop-Startplan am Reihenbeginn. Ein K-Plan ist bei geändertem K nicht automatisch zulässig; Übertragung und erneute Validierung dokumentieren. |
| 18 | Evolution mit drei Seeds; Arc-Flow mit einem Hauptlauf je Punkt und ausgewählten Laufzeitwiederholungen. Jede Seed-Reihe beginnt ohne externen guten Startplan; Fortschritt aus einer anderen Seed-Reihe nicht als unabhängige Wiederholung verwenden. |
| 19–20 | Alle unabhängig validierten Bestverbesserungen samt Muster, Dispatch, Belegung und synchronisiertem AS-Vergleich anzeigen. Populationshistorie aggregieren, unzulässige Kandidaten getrennt und stichprobenartig speichern. |
| 21 | SVG/PDF-Abbildungen, CSV-Tabellen, vollständige JSON-Konfigurationen und Zertifikate exportieren; vorhandene Replay-/Videoausgabe wiederverwenden. Gültigkeitsbereich jeder Schranke sichtbar machen. |

Die Weitergabe zwischen K-Stufen ist eine Fortsetzung der Suche. Daher sowohl
Laufzeit je Stufe als auch kumulierte Rechenzeit der Reihe ausweisen. Ein
übertragener Wert zählt nicht als neue Verbesserung. Bei exakt K aktiven
Kabinen darf eine fehlende Kabine nicht still inaktiv bleiben. Bei Arc-Flow
sind zusätzlich die gegebenenfalls veränderten festen Startpositionen zu prüfen;
nicht kompatible Vorlösungen sind höchstens ausdrücklich markierte Teil-Hints.

Die Referenzberechnung darf All-Stop-Pläne erzeugen, ohne diese automatisch in
die evolutionäre Startpopulation einzuspeisen. Historische Ergebnisse mit
früher Rückkehr oder Waiting sind keine identischen Hauptvergleichsfälle.

### Frühere Methodenentscheidung vom 14.09.2026 — nach dem K38-Langlauf

Vom Nutzer festgelegt sind zwei Skip-Stop-Hauptmethoden:

1. **Labelled Arc-Flow** mit festem K, festen Starts und No-Wait für niedrige
   Nachfrage/kleinere K; primär Journey Time bei expliziter Vollbedienung.
2. **Evolutionäre Reservoir-Linienplanung mit kleinem, sinnvoll begründetem
   Musterkatalog** für Nachfrage an/oberhalb der All-Stop-Kapazität und Flotten
   an/oberhalb der All-Stop-Sättigung; primär Nichtbedienung `unserved`.

Phasenoptimiertes regelmäßiges All-Stop bleibt die betriebliche Referenz.
Der native freie CP-SAT-Linienplaner ist damit nicht mehr die Hauptmethode
der Kapazitätsreihe; `relevant` ist nicht mehr zwingend ihr Hauptkatalog.
Die genaue Evolutionsvariante, Waiting-Integration, Katalogregel, K-Leiter und
Startpopulation bleiben vor dem Freeze ausdrücklich festzulegen. Diese
Methodenwahl ist keine Behauptung bereits bewiesener evolutionärer Überlegenheit.

**Nachfolgende Festlegung:** Beide Hauptmethoden erhalten Reihen mit **festem K
je Lauf**, auch die Evolution. Journey verwendet eine über K konstante Nachfrage
`N_J = kappa_AS(K_ref)`; der konkrete Referenzwert K_ref wird vor der Hauptreihe
festgelegt. Die diskutierte halbe Sättigungsflotte ist noch kein numerischer
Freeze. Die bisherige Halbierung der Nachfrage bei K_min wird dadurch ersetzt.
Für die Evolution ist `kappa_AS(K_AS)` die erste Nachfragebasis; höhere
Nachfragestufen werden jeweils in eigenen Fixed-K-Reihen geprüft. K und N
werden nicht gleichzeitig innerhalb einer Vergleichskurve verändert.
K-Punkte, Initialisierung und Weitergabe von Lösungen sind noch offen.

**Neueste Geometriefreigabe:** Gleichmäßige **500 m freie Seilstrecke (G500)**
werden gemeinsame Hauptgeometrie für Journey- und Kapazitätsstudie. G300/G800
sind damit keine unterschiedlichen Hauptgeometrien mehr. Grundlage ist die
untere Größenordnung der für [Câble C1 veröffentlichten Stationsabstände von
500–1.800 m](https://www.iledefrance-mobilites.fr/le-reseau/projets/cablec1/mediatheque/kit-presse-c1).
Das ist keine universelle technische Mindestdistanz: Unser G500 bezeichnet
freie Seilstrecke; die separat modellierten Stationswege kommen hinzu. Die
Quelle begründet die Größenordnung, keine exakte Nachbildung eines C1-Abschnitts.
Die G500-Code-/Frontendintegration und neue Referenzkalibrierung sind ausstehend.

Streckenlängen, Betriebszeiten und die tatsächliche Versuchsanzahl werden jetzt
anhand der Messungen erneut gemeinsam geprüft. Die bisher freigegebenen Werte
bleiben bis zu einer ausdrücklichen Änderung bestehen. Vorschläge und offene
Entscheidungen stehen im [aktualisierten Versuchsplan](experimental_design_20260913.md).
Ältere Aussagen über V2/V3 als Hauptsuchverfahren, einen zwingenden großen
Katalog oder vorgeschriebene gute Skip-Stop-Hints sind durch diese Entscheidung
überholt. Implementierungen und historische Ergebnisse bleiben erhalten.

### Frühere Freigabe vom 14.09.2026 — weiter gültig, soweit oben nicht ersetzt

Der Nutzer hat die zuletzt im Chat vorgestellten Vorschläge insgesamt
akzeptiert, **mit Ausnahme der Stationsgeometrie**. Die Freigabe ist ein
Planungsentscheid, keine Meldung über abgeschlossene Implementierung.

- Die geprüfte Headwaylogik und Architektur B bleiben; verbleibende bisherige
  Engineering-Eingaben sind als Annahmen auszuweisen und nicht durch bloße
  Quellenlabels zu Hersteller-/Normwerten aufzuwerten.
- Kapazität: anfänglich unbenutzte Reservoirflotte, Warm-up von einer
  All-Stop-Umlaufzeit, anschließend 45 min Nachfrage und 15 min Completion
  gemäß Erreichbarkeitsprüfung. Gemeinsame Recovery aus einem konfliktfreien
  Referenz-Rückkehrplan. Journey: identische laufende Fixed-K-Starts,
  Nachfrage über zwei Referenzumläufe und gemeinsame Completion-Marge.
- Deterministische, ausgewogene verschachtelte Personenfolge. 30-s-Freigabegruppen
  sind der Kalibrierungskandidat, 15 s und nötigenfalls 5 s die Gegenprüfung.
  Höchstens 1 % Änderung von AS-Kapazität beziehungsweise mittlerer Reisezeit
  und keine Umkehr der Kernaussage; sonst feinere Darstellung. Bewegungszeiten
  bleiben unverändert exakt. Die endgültige Nachfrageauflösung ist abgeleitet.
- Direkten All-Stop-Phasenoptimizer mit ganzzahligen Passagieren fertigstellen;
  Kapazität durch Einklammern/Bisektion, Journey unter U=0. Timeout ist kein
  Kapazitäts- oder Unzulässigkeitsbeweis.
- Linien: `small` als Seed, `relevant` als Hauptdomäne; native Timingstufe bei
  festen Mustern, mit Dispatchoptimierung und bis 1.200 s Exit-Waiting je
  legalem STOP-Besuch. Dispatchreihenfolge ist keine globale physische
  Reihenfolge. Zuerst U, danach unnötiges Waiting reduzieren. Kein zusätzlicher
  grober Mustermaster vor der Hauptstudie.
- Flottencaps ab K_AS geometrisch öffnen; obere Einsatzgrenze aus Dispatchfenster
  und Portheadway ableiten. Gleichzeitig umlaufende und insgesamt eingesetzte
  Kabinen unterscheiden. Nach ungelöster Nachfrage mindestens eine größere
  Cap als Kontrollversuch, soweit die vorab festgelegten Ressourcenbudgets reichen.
- Kapazitätsleiter Faktor 1,10, danach höchstens drei Zwischenstufen;
  Journey-Nachfrage 50 % der AS-Kapazität bei K_min, konstantes N, K-Faktor etwa
  1,5, Ende nach zwei ungelösten Stufen. Vollständige Bedienung bleibt Pflicht
  für Reisezeitvergleiche.
- Elf zentrale Kurven: sechs Kapazitätskurven T5R/T6R × F2/F0/F4 auf G800/P0;
  drei Journey-K-Kurven T5R × F3/F0/F4 auf G300/P0; zwei Terminal-Kapazitätskurven
  T6L × F2/F4 auf G800/P0. Zusätzliche einzelne Vergleiche: T6R F2/F4 mit P1/P4,
  F2 mit 75/25, T6R-F2 GUNEQ-v2, T6R-F2 Architektur A, Stationszeit-Sensitivität
  und höchstens zwei `small`/`relevant`-Ablationen. F1, G1200 und zusätzliche
  T6-Journey-Reihen sind nachrangig. Elf Kurven bedeuten nicht elf Solverläufe.
- Budgetkalibrierung klein/mittel/schwer bis 900 s, schweres Linienmodell bis
  1.800 s; zwölf Worker/Threads soweit unterstützt, sequenziell, höchstens
  32 GiB Prozessbaum-RSS auf dem 36-GiB-Rechner. Zwei Seeds für Kernaussagen, dritter
  bei deutlicher Streuung. V2 bleibt bei unentschiedenem V2/V3-Gate Standard.
- Frontend: getrennte Topologie-/Längenwahl, Abschnitts- und Stationsparameter,
  Headways/Umlaufzeit und zum Fingerprint passende Replays. Vor Kampagnenbeginn
  versionierte Spezifikationen, Quellen, Referenzen und Validierung einfrieren.

**Nicht freigegeben:** die zuletzt vorgeschlagenen Stationsmaße, insbesondere
0,5 m/s² nominale Beschleunigung, 35,91-m-Connector und ca. 82-m-Bypass, sowie
die Übernahme der übrigen Stationsabmessungen als neuer finaler Parametersatz.
6 m/s, 0,3 m/s und zehn Personen bleiben aus der früheren Freigabe bestehen.
Die historische Grundlage und die Quellenlücken stehen im
[Stationsgeometrie-Rückblick](../research/station_geometry_history_20260914.md).

**Nachfolgende ausdrückliche Freigabe vom 14.09.2026:** Für neue Thesisfälle
werden nominale Stationsbeschleunigung und -verzögerung symmetrisch auf
**1 m/s²** festgelegt. Im äquivalenten konstanten Beschleunigungsmodell ergeben
sich bei 6↔0,3 m/s je **5,7 s** und **17,955 m**. Grundlage ist die eigene
kinematische Ableitung aus den indikativen Stationslängen des französischen
Leitfadens 2023, §7.3, S.138; siehe Nachrecherche im verlinkten Rückblick.
Dies ist kein gemessener Herstellerverlauf und keine normative Höchstgrenze.
Der Notstopp-Parameter des Merge-Modells bleibt getrennt. Plattform-, Bypass-
und gesamte Stationsweglänge waren zu diesem Zeitpunkt noch offen.

**Anschließende Freigabe der Zwischenstationsgeometrie:** 15 m Plattform,
je 5 m schnelle STOP-An-/Ausfahrt, je 17,955 m Brems-/Beschleunigungsweg,
insgesamt **60,91 m STOP-Pfad und 60,91 m Bypass**. Die freien Seilabschnitte
kommen zusätzlich hinzu. Diese Freigabe betrifft eine kontrollierte abstrakte
Referenzgeometrie, keine baulich zertifizierte Station. T6L-Terminalwendewege
bleiben gesondert festzulegen. Noch keine Änderung der Code-Defaults.

## 1. Status und Entscheidungsregel

| Status | Bedeutung |
|---|---|
| `FROZEN` | Für die Hauptkampagne verbindlich; Änderung erzeugt eine neue Fallversion. |
| `PROVISIONAL` | Bisherige Empfehlung, aber noch gemeinsam zu bestätigen. |
| `OPEN` | Mehrere sinnvolle Varianten sind noch nicht entschieden. |
| `DERIVED` | Wird deterministisch aus bereits eingefrorenen Werten berechnet. |
| `REGRESSION` | Historischer Wert bleibt ausschließlich zur Reproduktion bestehen. |

Jeder finale Fall muss genau eine Version aus jeder erforderlichen Kategorie
referenzieren. Zu neuen Empfehlungen und Festlegungen werden die Quellen direkt
im Plan mitgeführt: Originalwert, Fundstelle, eigene Ableitung und Grenzen der
Übertragbarkeit. Synthetische Werte werden als eigene Versuchsentscheidungen
gekennzeichnet; eine Quelle zur Größenordnung wird nicht als Beleg des exakten
Testwerts ausgegeben. Dies gilt auch für weitere Planergänzungen.

Physik, Zeitvertrag oder Nachfrage dürfen nicht innerhalb eines
Solververgleichs wechseln. Eine Änderung daran erzeugt einen neuen
Problem-Fingerprint; Solverprofil, Musterkatalog und Zeitbudget gehören in den
Modell- beziehungsweise Lauf-Fingerprint.

## 2. Empfohlene Reihenfolge

Die Kategorien sollten nicht in beliebiger Reihenfolge entschieden werden:

1. Forschungsfragen und Vergleichsgrößen
2. Topologien und Rolle jeder Topologie
3. Stationsarchitektur und Ressourcenmechanismen
4. Geometrie
5. Geschwindigkeiten, Kabine und Stationskinematik
6. Headways und Sicherheitsparameter
7. Betriebszeit und Anfangs-/Endzustand
8. Flotten- und Reservoirvertrag
9. zulässige Betriebsweisen und Haltemuster
10. räumliche Nachfragefamilien
11. zeitliche Nachfrageprofile
12. Nachfragehöhe und Skalierung
13. All-Stop-Referenz und Skip-Stop-Methoden
14. Versuchsmatrix, Budgets und Wiederholungen
15. Kennzahlen, Nachweise und Ergebnisformat

Die Abhängigkeit ist wesentlich: Aus Geometrie und Stationszeiten folgen
Umlaufzeiten; daraus folgen gesättigte All-Stop-Flotte, Rückkehrreserve und
Modellgröße; erst danach kann die Nachfrage sinnvoll relativ zur
All-Stop-Kapazität skaliert werden.

## 3. Forschungsfragen und Vergleichsgrößen — `FROZEN`

Die Thesis untersucht zwei getrennte Kernfragen.

### RQ-C — vollständig bedienbare Profilnachfrage

Kann Skip-Stop unter demselben physischen und zeitlichen Betriebsvertrag ein
größeres verschachteltes Nachfrageprofil vollständig bedienen als All-Stop?

Für die jeweilige räumliche und zeitliche Profilfamilie gilt:

\[
\kappa_{AS}=\max\{N:U_{AS}(D(N))=0\},
\qquad
\kappa_{SS}^{LB}=\max\{N:\text{ein validierter SS-Plan hat }U=0\}.
\]

Der zentrale Kapazitätsnachweis ist

\[
\kappa_{SS}^{LB}>\kappa_{AS}.
\]

Das All-Stop-Kappa muss für den eingefrorenen Baselinevertrag exakt bestimmt
oder durch eine für diese Aussage ausreichende gültige Grenze abgesichert sein.
Für Skip-Stop genügt zum Nachweis eines Vorteils ein unabhängig validierter
Vollbedienungsplan oberhalb von \(\kappa_{AS}\); ein globales
Skip-Stop-Optimum ist nicht erforderlich. Berichtet werden der absolute
Kapazitätsgewinn und der nachgewiesene Mindestfaktor
\(\kappa_{SS}^{LB}/\kappa_{AS}\).

Teilbedienung bei einem fest gewählten hohen N bleibt ein nützlicher
Screening-, Mechanismus- und Solverwert. Sie ist nicht die Definition von
Kappa und bildet keinen eigenen Thesis-Hauptclaim.

### RQ-J — Reisezeit bei niedriger Nachfrage

Verkürzt Skip-Stop bei einer Nachfrage, die von beiden Betriebsweisen
vollständig bedient wird, die Fahrgastreisezeit?

Der Hauptvergleich verwendet die vollständige Labelled-Arc-Flow-Domäne mit
kleinem Fixed-K, identischen festen Startpositionen, identischer Nachfrage und
No-Wait. Für beide Betriebsweisen muss U=0 gelten. Optimiert und berichtet wird

\[
J=\sum_p(t_p^{Ziel}-r_p),
\qquad \bar J=J/N.
\]

Zusätzlich wird die Zeit in Freigabe bis Plattformabfahrt und
Plattformabfahrt bis Ziel zerlegt. Damit bleibt sichtbar, ob eingesparte
Zwischenhalte durch längeres Warten auf eine passende Kabine kompensiert
werden. Neben dem methodisch sauberen Vergleich bei gleichem K und gleichen
Starts wird die gesättigte phasenoptimierte All-Stop-Referenz als gesonderte
betriebliche Einordnung berichtet; beide Referenzen dürfen nicht vermischt
werden.

Die Reihe wird als aufsteigender K-Sweep ausgeführt. Die absolute Nachfrage
bleibt über alle K-Werte gleich und wird so niedrig gewählt, dass sie bereits
am kleinsten ausgewerteten K von beiden Betriebsweisen vollständig bedient
werden kann. Innerhalb jedes K erhalten All-Stop und Skip-Stop dieselben
Startpositionen. Startpositionen verschiedener K dürfen neu gleichmäßig
erzeugt werden, werden aber vor den Läufen eingefroren.

Die niedrige Nachfrage wird nicht willkürlich als ein globaler Personenwert
festgelegt. Für jede räumliche Familie wird zunächst am kleinsten K die
vollständig bedienbare All-Stop-Nachfrage bestimmt. Hauptwert ist 50 % dieser
Kapazität. Kann eine der beiden Betriebsweisen damit nicht nachweislich alle
Personen bedienen, wird vor der Hauptreihe einmalig auf 40 % abgesenkt. Danach
bleibt die absolute Personenzahl über den gesamten K-Sweep unverändert.

Der Sweep verwendet eine annähernd geometrische Folge mit Faktor 1,5. Der
kleinste vollständig bedienbare K-Wert, bekannte Referenzwerte wie K20 und der
gesättigte All-Stop-Wert werden bei Bedarf zusätzlich aufgenommen. Um einen
sichtbaren Knick nicht zu überspringen, darf genau dort ein Zwischenwert
eingefügt werden. Der Sweep endet spätestens am vorab festgelegten physischen
beziehungsweise rechnerischen K-Cap. Ein verkehrliches Plateau darf nur aus validierten
Optimalwerten oder hinreichend engen Bounds abgeleitet werden, etwa wenn zwei
aufeinanderfolgende gelöste K-Schritte weniger als 1 % Änderung der mittleren
Reisezeit bringen. Erreicht Arc-Flow bei einem K das Zeitlimit mit
breitem Gap, ist der Punkt rechtszensiert: Das ist eine Grenze der
Berechenbarkeit und kein Reisezeitplateau. Nach zwei aufeinanderfolgenden
ungelösten K-Stufen wird der exakte Sweep beendet; bereits erreichte Werte und
Bounds bleiben Teil des Ergebnisses.

### Unterstützende Auswertungen

- Flottenzahl, Musterverteilung und Ressourcenauslastung erklären die beiden
  Hauptergebnisse, bilden aber keine dritte Forschungsfrage.
- Solver-Incumbent, Bound, Gap und Verlauf dokumentieren die Berechenbarkeit
  und den Gültigkeitsbereich der Aussagen.
- Reisezeit und Kappa werden in getrennten Experimentreihen optimiert. Ein
  Reisezeitwert bei U>0 zählt nicht als Ergebnis der RQ-J-Reihe.

## 4. Topologien — `FROZEN`

Für die neuen Thesis-Experimente werden drei Topologien verwendet. Die
Bezeichnungen vermeiden bewusst `T6D` für „directional“, weil diese ID in der
bisherigen Planung bereits den gemeinsamen Double Ring bezeichnet.

| ID | Topologie | Rolle |
|---|---|---|
| T5R | gerichteter Fünf-Stationen-Ring als eine Richtung eines bidirektionalen Systems | kleine exakte Journey-Time-Reihe und bekannte Modellbasis |
| T6R | gerichteter Sechs-Stationen-Ring als eine Richtung eines bidirektionalen Systems | Übertragung und größerer Kapazitätshauptfall |
| T6L | bidirektionale Sechs-Stationen-Linie mit Pflichtterminals | Vergleich, wie gemeinsame Endstationen den Skip-Stop-Nutzen begrenzen |

Der bisherige T5-CW-Fall mit allen gerichteten OD-Paaren bleibt unverändert als
`T5-legacy` für Regressionen und vorhandene Resultate erhalten. Er ist ein
unidirektionaler Ring: auch OD-Paare über mehr als eine halbe Runde fahren dort
clockwise. T5R verwendet dagegen neue Demand-IDs und enthält nur Nachfrage,
die der betrachteten kürzeren Richtung zugeordnet ist.

T6R wird entsprechend als einzelne Richtungsseite ausgewertet. Unter
symmetrischer Geometrie und Nachfrage kann die Gegenrichtung gespiegelt werden.
Eine gemeinsame Flottenaufteilung kann bei Bedarf nachträglich aus den beiden
gerichteten K-Kurven bestimmt werden. OD-Paare mit gleicher Distanz in beiden
Richtungen benötigen in der Nachfragekategorie eine feste Ausschluss- oder
Aufteilungsregel.

Der bisher als T6D bezeichnete gemeinsame Doppelring mit endogener
Richtungswahl, gemeinsamer Nachfrage und gemeinsamer Flotte gehört nicht zum
Thesis-Kernumfang. Er wäre nur für endogene Routenwahl, richtungsübergreifend
gemeinsame Ressourcen oder dynamische Flottenverschiebung erforderlich.

T6L gehört zur Thesis, erhält aber eine kleinere gezielte Matrix als T5R/T6R.
Die Pflichtterminals müssen in jedem zulässigen Linienmuster enthalten sein.

## 5. Stationsarchitektur und Ressourcenmechanismen — `FROZEN`

Die vorhandenen künstlichen Sechs-Stationen-Fälle unterscheiden Architektur
A, B und C. Sie verändern reale Ressourcen- und Headwaymechanismen und sind
nicht bloß Solverparameter.

### Verbindliche Auswahl

- Architektur B bildet den Hauptfall auf T5R, T6R und T6L.
- Architektur A wird als eine gezielte Infrastruktursensitivität auf einer
  später ausgewählten Kernzelle verwendet.
- Architektur C gehört nicht zur Hauptmatrix.

### Modellstand

- T5-legacy, T5R und die bisherige Hauptplanung verwenden Architektur B.
- Rope-, Merge-, Plattform- und Mechanismusheadways sind im neuen
  Sechs-Stationen-Modell getrennt.
- Der Headway-Audit bestätigt den implementierten Vertrag, ersetzt aber keine
  reale Herstellerkalibrierung jeder Stationskomponente.

Die genaue STOP/SKIP-Ressourcengeometrie bleibt Bestandteil der Architektur
und wird nicht zwischen einzelnen Experimentzellen verändert. Architektur A
wird erst nach Abschluss derselben Zelle auf B gerechnet.

## 6. Streckenlängen und Zwischenstationswege — `FROZEN`; Terminalwege — `OPEN`

Neueste Freigabe am 14.09.2026: gleichmäßige **500-m-Abschnitte als gemeinsame
Hauptgeometrie beider Forschungsfragen**, motiviert durch die untere
veröffentlichte Stationsdistanz von Câble C1. Die frühere 800-m-Hauptgeometrie
wird dadurch ersetzt. Die Freigabe betrifft freie Seilabschnitte; die separat
festgelegte Stationsgeometrie bleibt erhalten. Code-Defaults wurden durch
diese Planänderung nicht geändert. Konkrete zusätzliche Längenstudien sind
vor der Hauptkampagne nochmals zu begrenzen.

### Bestätigte Längenprofile und Rollen

| ID | Freie Seilabschnitte | Rolle |
|---|---|---|
| G150 | fünfmal 150 m im historischen Fall | unveränderte Regression |
| G300 | gleichmäßig 300 m | bestehender kompakter Kontrollfall; keine Hauptgeometrie |
| G500 | gleichmäßig 500 m | gemeinsame Hauptgeometrie für Journey und Kapazität; Integration ausstehend |
| G800 | gleichmäßig 800 m | bestehende längere Vergleichsgeometrie; keine Hauptgeometrie |
| G1200 | gleichmäßig 1.200 m | nachrangige Längensensitivität, falls das Budget reicht |
| GUNEQ-v2 | im T6R: 500/1.100/900/600/700/1.000 m | Robustheitstest bei derselben freien Gesamtlänge von 4.800 m wie G800 im T6R |

GUNEQ-v2 ist in Stationsreihenfolge S0→S1, S1→S2, …, S5→S0 definiert. Die
frühere vorgeschlagene Folge 400/1.200/400/1.200/800/800 m wird damit für die
neue Thesisplanung ersetzt. Historische Instanzen und Ergebnisse behalten ihre
ursprünglichen Längen und Identitäten. Die neue Variante benötigt bei Umsetzung
eine eigene Geometrieversion und einen neuen Problem-Fingerprint.

Bei T5R gibt es fünf Ringabschnitte, bei T6R sechs und bei T6L fünf physische
Nachbarabschnitte mit Gegenrichtung. GUNEQ-v2 wird nicht still auf T5R oder T6L
gekürzt; entsprechende zusätzliche ungleichmäßige Profile sind nicht beschlossen.

### Quellen und eigene Ableitung

Die folgenden Primärangaben wurden am 14.09.2026 geprüft:

| Anlage / Quelle | Veröffentlichte Angaben | Eigene Ableitung und Aussagegrenze |
|---|---|---|
| [LEITNER: GD10 Cable Aéreo de Manizales – Línea 3](https://www.leitner.com/en/company/references/detail/gd10-cable-aereo-de-manizales-linea-3/), Projekttext und technische Daten | 2.328 m; vier Stationen | 2.328/(4−1)=776 m mittlere Länge je Interstation, kein gemessener Einzelabschnitt |
| [POMA: Line P – Medellin's Metro](https://www.poma.net/en/work/p-line-metrocable/), Projekttext und Technical Specifications | vier Stationen; technische Länge 2.656 m, im Fließtext gerundet 2.700 m | 2.656/(4−1)≈885 m; für die Rechnung den technischen Wert verwendet |
| [Doppelmayr: Colors of La Paz, Línea Blanca](https://lapaz.doppelmayr.com/en/), Linienübersicht | 2.847 m; vier Stationen | 2.847/(4−1)=949 m; Mittelwert, keine Einzelabstandsmessung |
| [Île-de-France Mobilités: Câble C1, Kit presse](https://www.iledefrance-mobilites.fr/le-reseau/projets/cablec1/mediatheque/kit-presse-c1), Les chiffres clés du projet; Seite aktualisiert 01.06.2026 | fünf Stationen mit Abständen zwischen 500 und 1.800 m | direkter Beleg ungleicher realer Stationsabstände; nicht die Quelle der konkreten GUNEQ-v2-Folge |

Die Beispiele begründen eine plausible Größenordnung, keinen universellen
Durchschnitt urbaner Seilbahnen. Der nun gewählte synthetische Hauptwert
500 m orientiert sich an der unteren veröffentlichten C1-Stationsdistanz.
Das ist keine allgemeine Mindestdistanz. 300 m, 800 m, 1.200 m und die konkrete
GUNEQ-v2-Anordnung bleiben eigene Vergleichsparameter.
Anlagenlängen können andere räumliche Bezugspunkte verwenden: Unser
`rope_segment_length_m` beschreibt freie Seilabschnitte, interne Stationswege
werden separat modelliert. Herstellerinterstationen, Kartenluftlinien und
Stützenabstände dürfen nicht ungeprüft mit diesem Parameter gleichgesetzt werden.

### Kontrollierter Vergleich

Gleichmäßige Abstände dienen der Erklärung von Nachfrage- und Haltemustereffekten.
Der ungleichmäßige Fall prüft, ob ein Vorteil von regelmäßiger zeitlicher
Synchronisation abhängt. Mittlere Abschnittslänge und Ungleichmäßigkeit werden
als getrennte Faktoren verändert. Bei identischen Stationszeiten und gleicher
Seilgeschwindigkeit erhält die gleiche freie Gesamtlänge die All-Stop-Umlaufzeit;
die zeitliche Lage einzelner Stationsereignisse verändert sich trotzdem.

Für den möglichst isolierten Geometrievergleich zuerst ODs verwenden, deren
kürzere Richtung in beiden Geometrien gleich bleibt. Fälle mit veränderter
Richtungszuordnung werden separat gekennzeichnet. All-Stop und Skip-Stop erhalten
innerhalb jeder Zelle identische Nachfrage und Richtungszuordnung.

### Bestätigte Zwischenstationswege vom 14.09.2026

| Phase | Weg | Unquantisierte Dauer ohne Waiting | Status / Begründung |
|---|---:|---:|---|
| Schnelle STOP-Anfahrt | 5 m | 5/6 s | `FROZEN`, bisherige geometrische Annahme |
| Bremsen 6→0,3 m/s | 17,955 m | 5,7 s | `DERIVED` aus 1 m/s² |
| Plattform | 15 m | 50 s | `FROZEN`, Übertragung gleicher langsamer Passagezeit |
| Beschleunigen 0,3→6 m/s | 17,955 m | 5,7 s | `DERIVED` aus 1 m/s² |
| Schnelle STOP-Ausfahrt | 5 m | 5/6 s | `FROZEN`, bisherige geometrische Annahme |
| Vollständiger STOP-Pfad | 60,91 m | 63,066666… s | `DERIVED` als Phasensumme |
| Direkter Bypass | 60,91 m | 10,151666… s | `FROZEN`, gleiche Pfadlänge als Kontrollentscheidung |

Quelle: [Leitfaden zur Zugänglichkeit des urbanen Seilbahnverkehrs, Juni 2023,
§7.3, S.138](https://www.gart.org/wp-content/uploads/2023/08/Guide-accessibilite-transport-par-cable_Juin-2023.pdf#page=139).
Die Quelle nennt indikative 36 m beschleunigungs-/verzögerungsbedingte Länge
einer Monocâble-Zwischenstation bei 6/0,2 m/s. Die eigene symmetrische
18-m-Rechnung motiviert den äquivalenten Modellwert von 1 m/s²; mit unseren
6/0,3 m/s folgen 17,955 m je Übergang. Die separat genannten 5 m je Ein-/
Ausstiegsbereich bei 0,2 m/s ergeben zusammen 50 s; dieselbe Zeit ergibt bei
0,3 m/s unsere 15 m Plattform. Dies sind eigene Übertragungen, keine direkt
publizierte 60,91-m-Station. Die vollständige Quellenprüfung steht im
[Rückblick](../research/station_geometry_history_20260914.md).

Gleiche STOP-/SKIP-Weglänge vermeidet einen zusätzlichen Wegverkürzungseffekt.
Der No-Wait-Zeitunterschied beträgt unquantisiert 52,915 s. Die Weglänge ist
keine Gebäudelänge; ein maßstäblicher Nachweis paralleler Wege wird nicht
behauptet. Die schnellen Connector bleiben im bestehenden Graphvertrag
STOP-only, sie werden nicht zusätzlich dem Bypass zugeschlagen.
Freie Seilstrecken bleiben unverändert: T6R/G800 hat z.B. 4.800 m freie Strecke
plus 6×60,91 m Stationsweg, zusammen 5.165,46 m je Umlaufpfad. T6L-Terminals
benötigen eigene Wendewege und übernehmen nicht einfach diese gerade Station.
Historische 10/20/3-m-Werte bleiben für Legacy-Reproduktionen erhalten.

## 7. Geschwindigkeiten, Kapazität und nominale Stationskinematik — `FROZEN`

| Parameter | Historisch | vorgeschlagener Hauptwert | Status |
|---|---:|---:|---|
| Seilgeschwindigkeit | 5,0 m/s | 6,0 m/s | `FROZEN` |
| Plattformgeschwindigkeit | 0,5 m/s | 0,3 m/s | `FROZEN` |
| Kabinenkapazität | 8 | 10 | `FROZEN` |
| Nominale Stationsbeschleunigung / -verzögerung | implizit aus 3-m-Connector | symmetrisch 1 m/s² | `FROZEN`, äquivalentes konstantes Profil |
| Kabinenlänge | 3,0 m | 3,0 m | `PROVISIONAL` |
| Kabinenhöhe | nicht überall relevant | 2,22 m | `PROVISIONAL` |
| Mindestabstand in Station | historischer Vertrag | 0,5 m zusätzlich zur Kabinenlänge | `OPEN` |

Am 14.09.2026 ausdrücklich für alle neuen Thesisfälle bestätigt: 6 m/s auf
dem Seil, 0,3 m/s an der Plattform und zehn Personen je Kabine. Historische
Instanzen und Ergebnisse behalten ihre Parameter; dies ist eine Festlegung
für die geplanten neuen Fälle, noch keine Änderung der Code-Defaults.

Quelle: [Haimerl et al. (2022), Regensburg, § 4.1, S. 1418](https://informs-sim.org/wsc22papers/138.pdf),
geprüft am 14.09.2026. Die mit Herstellern abgestimmten Planungsannahmen nennen
zehn Plätze, eine einstellbare Seilgeschwindigkeit von 0–6 m/s und 0,3 m/s
in der Station. Wir wählen das obere Ende des angegebenen Seilbereichs.
Evidenzklasse: publizierte Planungs-/Simulationsannahme; keine Messung einer
betriebenen Anlage. Die dort ebenfalls genannten 60 m Seilabstand sind eine
eigene anlagenspezifische Bedingung und werden durch diese Freigabe nicht
automatisch übernommen; unser Seilheadway bleibt separat zu begründen (§ 8).

### Verbleibende Prüfung und Umsetzung

- Bestätigte Zwischenstationswege aus §6 in neue versionierte Fälle übernehmen;
  eigene Terminal-Wendewege gesondert festlegen.
- Kabinenabmessungen und zusätzliche Abstände mit Quellen belegen.
- Nominales konstantes Beschleunigungsprofil und vorhandene Zeitinterpolation
  auf Übereinstimmung prüfen; Ressourcen-/Headwayzeiten neu ableiten.
- 1 m/s² ist kein normativer Grenzwert oder gemessener Herstellerverlauf.
  Notstopp- und Merge-Eingaben bleiben getrennt.

Es wird keine zusätzliche Geschwindigkeitssensitivität aus der früheren
Empfehlung automatisch übernommen.

## 8. Headways und Sicherheitsparameter — `FROZEN`

Mindestens vier Größen müssen getrennt festgelegt werden:

1. Headway auf dem freien Seil;
2. Headway im langsamen Bedienungskanal;
3. Einfahr-/Ausfahr- und Merge-Schutz;
4. zusätzliche Mechanismus-/Safety-Path-Belegung der Architektur.

Der Plattformheadway darf nicht still als Seilheadway verwendet werden. Aus
3,0 m Kabinenlänge, 0,5 m Abstand und 0,3 m/s Plattformgeschwindigkeit ergäbe
sich beispielsweise etwa 11,7 s im Bedienungskanal. Rope- und Merge-Headway
benötigen eigene Technologieparameter beziehungsweise Nachweise.

### Verbindliche Regel

- Rope-, Servicekanal-, Merge- und Mechanismusheadway werden getrennt aus der
  jeweiligen Architektur und den physischen Parametern abgeleitet.
- Es gibt keinen zusätzlichen freien Headway-Faktor in der Hauptmatrix.
- Architektur A bildet die einzige geplante Headway-/Mechanismussensitivität.
- Physische Mindestzeiten werden konservativ auf das Integer-Tickraster
  übertragen; die konkrete Ableitung wird mit den bestätigten Geschwindigkeiten
  und den noch offenen Stationsgeometriewerten eingefroren.

### Bestätigte Einfahrtsannahme und geplanter Reservoir-Portschutz

Codeprüfung am 14.09.2026, konsistent mit dem
[Physikaudit vom 11.09.2026](../findings/headway_physics_audit_20260911.md):
Der vorherige Exit-Merge schützt den Abstand auf der anschließenden konstant
befahrenen Seilkante. Eine eigene geometrisch kalibrierte gemeinsame
Einfahr-/Auskuppelzone ist dagegen nicht separat abgebildet. Der Reservoirport
ist ausdrücklich idealisiert: ein Tick Zustandsbelegung sichert Eindeutigkeit,
aber keinen physischen Depotheadway. Auch die sortierten Dispatchzeiten im
Linienmodell verwenden den Dispatchschritt, keine zusätzliche mechanische
Portregel. Bestehende Plattform- und Exit-Ressourcen gelten weiterhin.

Nach Klarstellung am 14.09.2026 bleibt die ideale selektive Ausschleusung von
Architektur B bestehen: keine zusätzliche Einfahr-/Auskuppelressource. Die
frühere Formulierung als erneut offene Auskuppelentscheidung ist überholt.

Für den Reservoiranschluss wurde dagegen der gemeinsame Rope-Headway
bestätigt: neue und bereits umlaufende Kabinen müssen am Einspeisepunkt
denselben Seilabstand einhalten. Der geplante gemeinsame Grenzquerschnitt
umfasst Dispatch, Umlaufpassage und letzte Ankunft vor Entnahme. Beschleunigung
und Lagerbewegungen innerhalb des Reservoirs bleiben idealisiert. Kein
zusätzlicher Plattform- oder B-Fehlerheadway wird auf diesen Punkt übertragen.

**Status: umgesetzt und geprüft (14.09.2026).**
[Abnahmebericht](../findings/reservoir_port_rope_headway_20260914.md). Neue Thesisfälle erhalten
einen entsprechend versionierten physischen Vertrag; historische Ergebnisse
bleiben Legacy, bis ihr Fahrplan separat erneut geprüft wurde.
Der [Umsetzungs- und Testplan](../plans/reservoir_port_rope_headway_20260914.md)
enthält Codepfade, Präsenz der letzten Rückkehr und Checkpointmigration.
Der [Thesisplan](../../../idp_report/version_2/docs/reservoir_port_headway_plan_20260914.md)
legt die späteren Kapiteländerungen und Ergebnisprüfungen fest.

### Abnahme

STOP/STOP, STOP/SKIP, SKIP/STOP und SKIP/SKIP müssen am Ein- und Ausfahrbereich
gegen Grenzfälle unabhängig geprüft sein. Schutz über den Betriebshorizont
hinaus bleibt erhalten.

## 9. Betriebszeit und Randbedingungen — `OPEN`

Es sind vier Zeitphasen getrennt festzulegen. Dabei sind Nachfragefenster,
Fahrgastabschluss und Fahrzeugrückkehr verschiedene Dinge:

| Phase | Bedeutung | bisherige Kandidaten |
|---|---|---|
| Warm-up | leere Anfahrt beziehungsweise Herstellung des definierten Anfangszustands | historisch 300 s; künftig umlaufabhängig |
| Nachfragefenster | Zeitraum, in dem neue Fahrgäste freigegeben werden | verbindlich: 45 min |
| Completion-Flush | zusätzliche Zeit nur für die bereits freigegebene Kohorte bis zur Zielankunft | verbindlich: 15 min, vorbehaltlich Erreichbarkeitsgate |
| Recovery | anschließende Zeit zur expliziten Reservoirrückkehr der Fahrzeuge | aus längstem nötigen Rückkehrweg abgeleitet |

### Vorliegender Befund

Die Verdopplung des Bedienungszeitraums von 20 auf 40 Minuten reduziert starke
Horizont-Randeffekte. Bei unveränderter Gesamtnachfrage bedient All-Stop auf
300 und 800 m bereits alle 3.074 Personen. Bei verdoppelter Nachfrage und damit
konstanter Rate bleibt der Kapazitätsfall diskriminierend. Gleichzeitig steigt
die Modellgröße etwa auf das Drei- bis Fünffache.

### Empfehlung und verbleibende Entscheidung

Für RQ-C werden Fahrgäste während 45 min freigegeben. Danach entstehen keine
neuen Fahrgäste; die gemeinsame Fahrgastdeadline liegt bei Minute 60. Damit
bilden die letzten 15 min eine reine Completion-Phase. Vor Freigabe des Falls
muss für jede aktive OD-Gruppe gelten

\[
h_{AS}+\tau_{AS}(o_g,d_g)\le 15\ \mathrm{min}.
\]

Andernfalls wird die 45-min-Kohorte beibehalten und nur die gemeinsame
Completion-Deadline verlängert. Die anschließende Fahrzeugrückkehr beeinflusst
die Bedienungszählung nicht, muss aber den Single-Use-Reservoirvertrag erfüllen.

Für RQ-J wird die Beobachtung an der All-Stop-Umlaufzeit ausgerichtet. Empfohlen
sind Freigaben über zwei vollständige Referenzumläufe und dieselbe gemeinsame
Completion-Marge. Ein dritter Umlauf wird nur als Sensitivität gerechnet, wenn
das exakte Arc-Flow-Build-/Solve-Gate dies zulässt. Ein pauschaler
60-min-Horizont würde bei kurzen Geometrien unnötig viele Runden und Variablen
erzeugen und bei langen Geometrien möglicherweise zu wenige vergleichbare
Umläufe beobachten.

Noch festzulegen sind die genaue Formel für Warm-up und Recovery sowie der
Anfangszustand. Empfehlung: RQ-C beginnt mit leerem Reservoir und zählt die
60 min erst ab dem definierten Betriebsbeginn; RQ-J verwendet einen
eingefrorenen, bereits laufenden Anfangszustand ohne künstliche Startwarteschlange.

Mehr Betriebszeit darf in einem Vergleich nicht mit mehr Solverzeit verwechselt
werden. Bei Zeitprofilvergleichen bleiben Bedienungsdeadline und Recovery gleich.

## 10. Flotte und Reservoir — `OPEN`

### Bisheriger Vertrag

- Single-Use-Reservoir: jede Kabine kann höchstens einmal dispatchen und kehrt
  am Ende zurück.
- Kabinen können während desselben Einsatzes weder wieder ins Reservoir fahren
  und später erneut ausfahren noch Richtung oder Linienmuster wechseln.
- Die Linienplanung verwendet optionale Kabinen bis Kmax.
- Die All-Stop-Sättigungsflotte wird je Geometrie aus einem geprüften
  regelmäßigen All-Stop-Umlauf abgeleitet.

### Zu entscheiden

- Single-Use und fehlenden Wiedereinsatz verbindlich bestätigen.
- Kmax nicht über frei gewählte Multiplikatoren festlegen. Zuerst den
  gesättigten All-Stop-Wert K_AS und den sicheren physischen Slotbound K_phys
  bestimmen. Für die große Kapazitätsreihe fünf logarithmisch gleichabständige
  Caps einschließlich beider Endpunkte verwenden:

  \[
  K_j=\left\lceil K_{AS}
  \left(\frac{K_{phys}}{K_{AS}}\right)^{j/4}\right\rceil,
  \qquad j=0,\ldots,4.
  \]

  Durch Rundung doppelte Werte werden entfernt. Auf kleinen vollständig
  lösbaren Fällen wird zusätzlich jedes ganzzahlige K ausgewertet. Die Zahl
  von fünf großen Stufen ist ein vorab festgelegter Rechenbudgetkompromiss und
  keine verkehrliche Schwelle.
- Je Cap die größte validierte vollständig bediente Nachfrage und die
  tatsächlich genutzte Flotte ausweisen. Die nächste Cap-Stufe wird mit der
  besten Lösung der vorigen warm gestartet. Zwei weitere Caps ohne höheren
  Kapazitätszeugen und ohne größere genutzte Flotte bilden ein praktisches
  Suchplateau, aber keinen globalen Beweis. Ein Timeout oder das bloße Fehlen
  einer Lösung ist kein Plateau und kein Unzulässigkeitsnachweis.
- Einen harten physischen Slotbound separat aus den kürzesten zulässigen
  Umläufen und Ressourcenheadways ableiten.
- Flotteneffizienz als sekundäre Kennzahl statt als eigene vollständige
  Experimentmatrix verwenden.

K38 und Max50 sind historische Fallgrößen und werden nicht auf neue Geometrien
übertragen. Max50 war eine gewählte technische Versuchsgrenze des alten
Reservoirfalls; sie wurde weder aus der Anlagenphysik noch aus einem
Kapazitätsoptimum abgeleitet. K_AS, Headway und Umlaufzeit werden für jeden
physischen Fall neu berechnet und validiert.

Die Kalibrierung vom 14.09.2026 bestätigt dieses Vorgehen. Für T5R/G800 gilt
`K_AS=84`; die reine Port-Durchsatzobergrenze ist 933. Die getesteten ersten drei
geometrischen Caps waren 84, 154 und 280. Vollständige Ergebnisse stehen in
[`../findings/thesis_calibration_results_20260914.md`](../findings/thesis_calibration_results_20260914.md).

### Adaptive Flottenleiter für die Incumbent-Suche

Die geometrischen Caps sind Messpunkte der späteren Versuchsreihe. Sie sind
keine geeignete Reihenfolge zum Konstruieren einer guten Startlösung. Dafür wird
eine separate adaptive Leiter verwendet. Seien (K_i) die aktuelle Cap,
(u_i) die tatsächlich genutzte Flotte der besten unabhängig validierten
No-Wait-Lösung, (h=0{,}20) die gewünschte freie Reserve und

\[
b=\max\left(2,\operatorname{round}(K_{AS}/20)\right),\qquad
R_b(x)=b\left\lceil x/b\right\rceil.
\]

Die nächste geprüfte Cap ist

\[
K_{i+1}=\min\left\{K_{hard},R_b\left(\min\left{
1{,}25K_i,\max\left(K_i+b,\frac{u_i}{1-h}\right)
\right}\right)\right\}.
\]

Jede neue Stufe wird mit der vollständigen validierten No-Wait-Lösung der
vorigen Stufe gehintet; zusätzliche Kabinen werden als ungenutzt gehintet.
Der nachgelagerte Waiting-Plan bleibt ein Ergebnis derselben Stufe, ist aber
kein gültiger Startpunkt des erneut No-Wait arbeitenden Linienmasters.

Die Cap wird unmittelbar erhöht, wenn (u_i\ge0{,}8K_i). Entsteht eine späte
Verbesserung im letzten Viertel des Suchbudgets, wird dieselbe Cap zunächst mit
einem weiteren Seed oder längerem Budget wiederholt. Bei kleinerer Auslastung
und praktischem Plateau folgt genau ein explorativer Schritt um mindestens
(b). Zwei aufeinanderfolgende Caps ohne mehr bediente Personen und ohne
größere tatsächlich genutzte Flotte beenden die Leiter als praktisches
Suchplateau. Vollständige Bedienung beendet die Leiter für die aktuelle
Nachfrage. Timeout und fehlender nativer Incumbent sind kein
Unzulässigkeitsnachweis; der validierte Warmstart bleibt als Rückfalllösung
erhalten und wird nicht als native Verbesserung gezählt.

Für T5R/G800 ist (b=4). Der bisherige validierte No-Wait-Plan mit elf
Kabinen ergibt damit als erste Retargeting-Cap (K_0=16), gefolgt von
adaptiv bestimmten Stufen wie 20, 24/28 und nicht vom direkten Sprung auf 154.

## 11. Betriebsweisen und Haltemuster — `OPEN`

Am 14.09.2026 bestätigt: Das bestehende Exit-Waiting-Konzept bleibt erhalten.
Aussteiger erreichen das Ziel vor dem Ziel-Waiting; Einsteiger werden zum
tatsächlichen Plattformausstieg bedient. Waiting schützt den bestehenden
einzelnen Warteort, keinen zusätzlichen Mehrkabinenpuffer. Numerische
Wait-Grenzen und Freigaben sowie die unten beschriebene Integration bleiben
gesondert festzulegen.

| Entscheidung | Kandidaten |
|---|---|
| All-Stop | jeder Halt, No-Wait, gesättigte regelmäßige Bewegung, freie gemeinsame Phase |
| allgemeines Skip-Stop klein | freie STOP/SKIP-Entscheidungen im Labelled Arc-Flow |
| Linienplanung | ein wiederkehrendes Haltemuster je Kabineneinsatz |
| Musterkatalog | `relevant` als vollständiger nachfragerelevanter Hauptkatalog; `small`/automatisch begrenzt als Seed oder Ablation |
| Waiting | im Linienfall als gebundene Fahrplanreparatur vorgesehen; Labelled Arc-Flow bleibt No-Wait |

`relevant` bedeutet: jede Stationsmaske, die Ursprung und Ziel mindestens einer
positiven Demand Group enthält. Auf fünf Stationen gibt es höchstens 26
transportfähige Masken; im komplementären R2-Fall 14. `small` enthält All-Stop
und die minimalen Endpunktmuster der nachgefragten OD-Paare. Formal gilt

\[
\mathcal P_{small}=\{V\}\cup
\{M\cup\{o_g,d_g\}:q_g>0\},
\]

wobei V die All-Stop-Maske und M die Menge verpflichtender Stationen ist. Für
einen Ring ist M leer; für T6L enthält M beide Terminals. Identische Masken
werden zusammengeführt. F2 erzeugt damit typischerweise All-Stop plus je ein
minimales Muster pro komplementärem OD-Cluster.

### Zu entscheiden

1. `relevant` ist die empfohlene Hauptdomäne. Die Darstellung V2/V3 wird durch
   ein Build-/Suchgate gewählt und verändert den Musterraum nicht.
2. `small` beziehungsweise ein automatisch begrenzter Katalog nur zur Erzeugung
   guter Startpläne und als dokumentierte Ablation verwenden.
3. Der end-to-end Linienansatz muss Waiting enthalten. Die derzeit
   implementierte V2/V3-Mustersuche selbst fixiert Waiting noch auf null. Sie
   liefert nur physisch zulässige No-Wait-Pläne. Eine nachgeschaltete native
   Timing-/Repair-Optimierung hält Muster und Kabinenreihenfolge fest, optimiert
   Dispatchzeiten und gibt gebundene Exit-Waits frei. Zusätzlich dürfen
   diskrete Musterkandidaten eines späteren gröberen Masters in diese Stufe
   eingehen, selbst wenn sie ohne Waiting noch zeitlich unzulässig sind.
4. Die Repair-Stufe minimiert lexikografisch zuerst U und danach Gesamt- und
   Maximalwait. Dadurch kann sie eine ohne Waiting unzulässige diskrete
   Kombination reparieren und einen bereits zulässigen No-Wait-Plan durch
   bessere Freigabeausrichtung oder konfliktlösende Verzögerung verbessern.
   Bringt Waiting keinen Bedienungsgewinn, wird der No-Wait-Plan bevorzugt.
   Nur ein anschließend vollständig validierter Plan zählt als
   Kapazitätszeuge.
5. Maximalen Wait, Freigabestationen und Auswahl der reparierbaren Besuche
   festlegen. Ein frei integriertes Waiting über alle Musteralternativen ist
   nicht bereits implementiert.
6. Pflichtterminals der Linie in jeder zulässigen Maske erzwingen.

## 12. Räumliche Nachfragefunktionen — `FROZEN`, Fallauswahl teilweise `OPEN`

Die folgenden Funktionen wurden am 14.09.2026 nach Vorstellung im Chat
bestätigt. Die Freigabe betrifft diese Funktionen und Parameter, nicht sämtliche
weiteren Empfehlungen der
[Nachfrage-Literaturauswertung](../research/thesis_spatiotemporal_demand_design_20260914.md).
Es handelt sich um kontrollierte synthetische Nachfrage, nicht um eine empirisch
kalibrierte Nachfrageprognose.

### Gemeinsame Definition

Für Gesamtmenge N, OD-Anteil w und normierte Zeitdichte p gilt

\[
\lambda_{ij}(t;N)=Nw_{ij}p_{ij}(t),
\qquad \sum_{i\ne j}w_{ij}=1,
\qquad \int_0^{T_D}p_{ij}(t)\,dt=1.
\]

Im ersten Vergleich verwenden sämtliche aktiven ODs dieselbe Zeitfunktion
p(t). Die tatsächlichen Instanzen enthalten ganzzahlige Personen mit festen
Freigabezeiten; die Intensitätsfunktion ersetzt keine Integerzuweisung.

### Bestätigte Rohgewichte

Die folgenden Fahrtlängendefinitionen gelten zunächst für gleichmäßige
Stationsabstände. Die Buchstaben A, B, C, D, E bezeichnen S0 bis S4 in der
festgelegten Stationsreihenfolge.

| ID | Rohgewicht vor Richtungszuordnung und Normierung | Rolle |
|---|---|---|
| F0 | 1 für alle geordneten ODs i≠j | diffuse Referenz |
| F1 | 1 für j=H und i≠H, sonst 0 | gemeinsamer Zielhub |
| F2 | 1 für B→D, D→B, C→E und E→C, sonst 0 | komplementäre Märkte |
| F3, T5R | 1 bei kürzestem Weg über genau zwei Abschnitte, sonst 0 | längere zulässige Ringwege |
| F3, T6R | 1 bei kürzestem Weg über genau drei Abschnitte, sonst 0 | längere zulässige Ringwege |
| F3, T6L | 1 für Wege über vier oder fünf Abschnitte, sonst 0 | längere Linienwege |
| F4 | 1 für benachbarte Stationen, sonst 0 | lokale Wege |

Die konkrete Hubstation H wird je Fall noch festgelegt. F5/F6 bleiben optionale,
nicht durch diese Funktionsfreigabe beschlossene Erweiterungen.

### Richtungsanteile und Normierung

\[
w_{ij}=\frac{a_{ij}\tilde w_{ij}}
{\sum_{u\ne v}a_{uv}\tilde w_{uv}}.
\]

Für die untersuchte Ringrichtung gilt a=1, wenn sie kürzer ist, a=0, wenn die
Gegenrichtung kürzer ist, und a=1/2 bei Gleichstand. Die Richtungsteilung erfolgt
vor der Normierung. Bei einer vollständig betrachteten bidirektionalen Linie
entfällt diese Filterung. Ein leerer Richtungsanteil erzeugt keinen gültigen
Nachfragefall.

Folglich erhält F2 in der betrachteten Richtung der gleichmäßigen Ringe
w(B,D)=w(C,E)=1/2. Auf der vollständig betrachteten Linie erhalten die vier
Verbindungen je 1/4. F0 im gleichmäßigen T6R hat 40/40/20 % Ein-/Zwei-/Drei-
Abschnittsfahrten; im T5R sind es 50/50 % Ein-/Zwei-Abschnittsfahrten.

Die Zuordnung für ungleichmäßige Stationsabstände bleibt offen. Sie darf nicht
ungeprüft durch dieselbe Hopzahlregel erfolgen. All-Stop und Skip-Stop müssen
innerhalb eines Vergleichs dieselbe eingefrorene OD-/Richtungszuordnung erhalten.

### Bestätigte Hintergrundvariante

Nach Normierung beider Komponenten:

\[
w^{F2+}_{ij}=0{,}8w^{F2}_{ij}+0{,}2w^{F0}_{ij}.
\]

Die 80/20-Aufteilung ist ein gewählter synthetischer Robustheitsparameter, keine
Literaturkonstante. Die vollständige Kombination mit Geometrien, Flotten und
weiteren Sensitivitäten wird separat festgelegt.

## 13. Zeitliche Nachfragefunktionen — `FROZEN`, Ankunftsdarstellung `OPEN`

Bestätigt am 14.09.2026: zunächst P0 und P1, danach P4 gezielt beim Hub und bei
den komplementären Märkten. Für RQ-C gilt T_D=45 min mit anschließenden 15 min
für den Fahrgastabschluss. In den folgenden Formeln werden Zeiten in Minuten
angegeben; außerhalb von [0,T_D) ist die Rate null.

### P0 — konstante Rate

\[
p_0(t)=\frac1{T_D}.
\]

Eine konstante Rate bedeutet innerhalb des Fensters verteilte Ankünfte. Sie
bedeutet nicht, dass sämtliche Personen einer Minute gleichzeitig freigegeben
werden.

### P1 — Dreieckspeak mit Grundlast

\[
g(t)=1-2\left|\frac{t}{T_D}-\frac12\right|,
\qquad
p_1(t;a)=\frac{1+a g(t)}{T_D(1+a/2)}.
\]

Der bestätigte Hauptparameter ist a=2. Damit beträgt die Rate am Beginn und
im Grenzwert am Ende das 0,5-Fache des Durchschnitts und in der Mitte das
1,5-Fache. Spitze zu Rand ist somit 3:1. Die gesamte Nachfrage bleibt gegenüber
P0 unverändert. a=0 ergibt P0; a=1 beziehungsweise a=4 sind mögliche spätere
Sensitivitäten, deren Läufe noch nicht beschlossen sind.

### P4 — Hintergrund mit drei Feederwellen

\[
p_4(t)=\frac{1-\beta}{T_D}
+\frac{\beta}{3b}\sum_{m=1}^{3}
\mathbf1_{[c_m-b/2,\;c_m+b/2)}(t).
\]

Für das 45-min-Nachfragefenster sind bestätigt:

\[
\beta=0{,}5,\qquad b=2\text{ min},\qquad
(c_1,c_2,c_3)=(7{,}5;22{,}5;37{,}5)\text{ min}.
\]

Die Hälfte der Nachfrage entsteht gleichmäßig, die andere Hälfte in den drei
jeweils zweiminütigen Wellen. Außerhalb der Wellen beträgt die Rate das
0,5-Fache des Gesamtmittels, innerhalb das 4,25-Fache. Beispiel N=900:
10 Personen/min Hintergrund und zusätzlich 150 Personen pro Welle, somit
85 Personen/min während einer Welle.

Diese Werte sind synthetische Testparameter. Eine Übertragung der P4-Zentren
und -Breite auf andere Nachfragefenster ist noch gesondert festzulegen. P0/P1
sind bereits über T_D parametrisiert; der RQ-J-Zeitvertrag bleibt separat.

### Integerisierung und noch offene Ankunftsdarstellung

Der gewünschte Anteil einer OD-Zeit-Zelle ist

\[
q_{ij,b}=w_{ij}\int_{t_b}^{t_{b+1}}p_{ij}(t)\,dt.
\]

Die Erzeugung führt zu ganzzahligen Personen mit festen Freigabezeitpunkten.
Beim Erhöhen von N werden ausschließlich Personen hinzugefügt; bestehende
Personen behalten ID, OD und Freigabezeit. Die Verschachtelung gilt also auch
für Zeitpunkte innerhalb eines Intervalls, nicht nur für Zellmengen.

Noch nicht entschieden sind:

- Breite der Raten-/Aggregationsintervalle und tatsächliche Verteilung der
  individuellen Freigaben darin;
- deterministische oder eingefrorene zufällige Ankunftsfolgen und ihre genaue
  Erzeugungsregel;
- absolute Lage des Servicebeginns relativ zum Warm-up;
- Umfang zusätzlicher Peak-/Puls- und Synchronisationssensitivitäten.

Es gibt damit noch keine bestätigte automatische Wahl zwischen 60 und 120 s.
Die Funktionen allein rechtfertigen keine Aggregation auf gemeinsame
Minutenanfänge. Historische neun Fünfminuten-Buckets und reine Pulse bei
0/15/30 min bleiben als ältere Nachfrageverträge identifizierbar und werden
nicht still in das neue P0 oder P4 umbenannt. Bei einem direkten P0/P1/P4-
Vergleich bleibt die absolute Gesamtmenge gleich.

## 14. Nachfragehöhe, Integerisierung und Lastpunkte — `OPEN`

Nachfrage wird als deterministisch verschachtelte Integerfolge erzeugt. Der
Fall mit N Personen ist ein Präfix des Falls mit N+1 Personen. Dadurch können
Kapazitätsgrenzen ohne Umverteilung bestehender Nachfrage gesucht werden.

### Kapazitätsreihe

Für jede Topologie-, Geometrie-, F- und P-Kombination wird zuerst
\(\kappa_{AS}\) der phasenoptimierten, gesättigten All-Stop-Referenz exakt
bestimmt. Die verschachtelte Nachfrage macht vollständige Bedienbarkeit
monoton. Deshalb wird die Grenze zunächst exponentiell eingeklammert und dann
mit ganzzahliger Bisektion bestimmt.

Die Skip-Stop-Suche beginnt bei \(N=\kappa_{AS}\) und erhöht die Nachfrage in
einer geometrischen Leiter mit Faktor 1,10:

\[
N_j=\left\lceil 1{,}10^j\,\kappa_{AS}\right\rceil.
\]

Jede Stufe wird mit dem letzten validierten Plan warm gestartet. Nach dem
ersten ungelösten Punkt kann zwischen letzter bestätigter und erster ungelöster
Stufe gezielt nachverdichtet werden. „Ungelöst“ bedeutet bei Zeitlimit nur
`unknown`. Als \(\kappa_{SS}^{LB}\) zählt ausschließlich das größte N mit
unabhängig validiertem U=0. Eine gröbere feste Auswahl wie 0,8/1,0/1,2 wird
damit für den Hauptclaim ersetzt; solche Lastpunkte dürfen weiterhin
illustrative Querschnitte bilden.

Flottencap und Nachfrage werden nicht als volles zweidimensionales Raster
gerechnet. Innerhalb einer Cap wird die Nachfrageleiter fortgesetzt. Eine
größere Cap wird nur geöffnet, wenn die bisherige Lösung die Flottengrenze
nutzt oder das validierte Kappa noch wächst.

### Niedrige Last für RQ-J

Für jede räumliche Familie wird bei K_min zunächst deren vollständig
bedienbare All-Stop-Nachfrage unter den gemeinsamen Fixed-K-Starts bestimmt.
Die Journey-Hauptreihe verwendet 50 % dieses Werts, bei fehlendem U=0-Nachweis
für eine der beiden Betriebsweisen einmalig 40 %. Diese Kalibrierung erklärt
„niedrige Nachfrage“ operational; danach bleibt N über alle K unverändert.
Zeitprofilvergleiche P1/P4/P0-shift verwenden dieselbe absolute Personenzahl
wie ihr P0-Ausgangsfall.

### Konflikt mit älteren Plänen

`demand_case_families.md` definiert rho über die maximale All-Stop-Kapazität
einer vollständigen K-Frontier. Der neuere verbindliche Baselinevertrag verwendet
die gesättigte, regelmäßig verteilte und phasenoptimierte All-Stop-No-Wait-
Bewegung. Diese Definitionen dürfen nicht gemischt werden. Empfehlung für die
Thesis: den neueren betrieblichen Vertrag verwenden und die globale Frontier
nur als zusätzliche stärkere Sensitivität beziehungsweise Schranke ausweisen.

## 15. All-Stop-Referenz — `FROZEN`

Für jeden physischen Fall, jedes Nachfrageprofil und jede Nachfragehöhe:

1. gesättigte All-Stop-Flotte K_AS bestimmen;
2. alle Kabinen gleichmäßig über den Umlauf verteilen;
3. Waiting auf null setzen;
4. eine gemeinsame Phase theta innerhalb einer Headwayperiode optimieren;
5. ganzzahlige Passagierzuordnung gemeinsam mit theta optimieren;
6. Bewegung und Passagiere unabhängig validieren.

Für Kapazität maximiert die Referenz S. Für Reisezeit minimiert sie J unter
U=0. Ein Fixphasenwert ist keine phasenoptimierte Referenz.

### Implementierungsstand

Der direkte Phasenoptimizer und die verschachtelte Kapazitätssuche sind als
versionierte experimentelle Pfade implementiert. Korrektheitstests prüfen unter
anderem nicht teilbare Tick-Umläufe und die vollständige Phasendomäne. Die
zweistündige Kalibrierung bleibt das Gate vor der finalen Kapazitätsmatrix.
Bereits vorhandene globale All-Stop-Bounds bleiben zusätzliche stärkere
Nachweise, sofern ihre Domäne exakt zum Fall passt.

## 16. Skip-Stop-Methoden und Zuordnung zu Fragen — `FROZEN`

| Methode | Zulässige Domäne | Verwendung |
|---|---|---|
| Labelled Arc-Flow | Fixed-K, feste Startpositionen, No-Wait, freie STOP/SKIP-Entscheidungen | kleine exakte Reisezeitfälle und Solver-Gaps |
| Evolutionäre Reservoir-Linienplanung mit kleinem begründetem Katalog | wiederkehrende Muster; K an/oberhalb K_AS; genauer Dispatch-/Waiting- und Flottenvertrag vor Freeze festlegen | hohe Nachfrage, Nichtbedienung und validierte Kapazitätszeugen |
| phasenoptimiertes All-Stop | gesättigte regelmäßige All-Stop-Bewegung, No-Wait | gemeinsame betriebliche Referenz |

Die Methoden werden nicht als Solverrennen ausgegeben, solange ihre Domänen
unterschiedlich sind. Ein Arc-Flow-Gap gilt nicht automatisch für das
Linienmodell und ein Linienmodell-Bound nur innerhalb seines Katalogs.

Die Rollen der beiden Hauptmethoden sind festgelegt; die genaue evolutionäre
Konfiguration noch nicht. V2/V3 bleiben vorhandene native Vergleichspfade,
keine verpflichtende dritte Skip-Stop-Hauptmethode. Für die Evolution gibt es
keinen globalen Solver-Gap. Ein Passagier-IP-Bound gilt nur für den festen
Fahrplan; eine AS-Referenzdifferenz ist kein allgemeiner Optimalitätsgap.

## 17. Versuchsmatrix und Faktortrennung — `OPEN`

Die finale Matrix sollte gestuft statt vollständig faktoriell sein:

### Stufe A — Regression und Baselines

- T5-legacy und bekannte Fälle reproduzieren;
- neue richtungskonsistente T5R-Nachfrage separat einfrieren;
- phasenoptimierte All-Stop-Referenz fertigstellen;
- neue Nachfrage- und Zeitgeneratoren klein prüfen.

### Stufe B — Kernkapazität

- T5R und T6R in der später festgelegten Hauptgeometrie;
- F2/F0/F4 × P0;
- je Zelle zuerst exaktes All-Stop-Kappa, dann verschachtelte geometrische
  Skip-Stop-Nachfrageleiter und bei Bedarf gestufte Flottencaps;
- gleiche Physik, Zeitachse und vorab kalibrierte Solverbudgets.
- T6L anschließend mit einer reduzierten Auswahl als Pflichtterminalvergleich.

### Stufe C — Reisezeit

- T5R, aufsteigender K-Sweep mit je K eingefrorenen Balanced-Starts;
- F3/F0/F4;
- annähernd geometrische K-Reihe mit Faktor 1,5 und gezielten Referenzpunkten;
- über K konstante, am kleinsten K kalibrierte niedrige Nachfrage mit U=0;
- Labelled Arc-Flow gegen All-Stop bei denselben Starts plus gesättigte
  betriebliche Referenz.
- Ende am verkehrlichen Plateau, am vorab festgelegten K-Cap oder nach zwei
  aufeinanderfolgenden ungelösten Stufen; Solver-Timeout nicht als Plateau
  interpretieren.
- T6R und T6L erhalten nur nach bestandenem exakten Build-/Solve-Gate eine
  kleinere Journey-Time-Übertragung; T5R trägt den vollständigen Sweep.

### Stufe D — Robustheit

- F2 und F4 bei einem nach der Kapazitätsleiter festgelegten gemeinsamen
  relativen Lastniveau oberhalb des All-Stop-Kappa;
- P1, P4 und P0-shift;
- F2 zusätzlich 75/25.

### Stufe E — gezielte Sensitivität

- genau eine Längen- oder Ungleichmäßigkeitsvariation;
- `relevant` gegen Hauptkatalog auf höchstens zwei Fällen;
- keine gemeinsame T6D-Doppelringintegration.

### Zu entscheiden

Die tatsächliche Anzahl Zellen erst festlegen, nachdem Haupttopologie,
Hauptgeometrie, Zeitvertrag und Nachfrageauflösung Build-only vermessen wurden.

## 18. Solverbudgets, Startlösungen und Wiederholungen — `OPEN`

Für jede Zelle vorab festlegen:

- Build- und Solverzeit getrennt;
- Worker und Speicherlimit;
- Startplanquelle;
- Seeds beziehungsweise deterministische Wiederholungen;
- Zeitpunkte für Verlaufswerte, zum Beispiel 30/60/120/300 s;
- Plateau-Definition und Abbruchregel;
- Umgang mit Timeout, Speicherabbruch und fehlender nativer Lösung.

Empfehlung: mindestens zwei Seeds für positive Kernaussagen, drei bei hoher
Streuung. Die Initialisierung der neuen evolutionären Hauptmethode wird vorab
festgelegt und fair über Szenarien angewendet. Ein bekannter guter Skip-Stop-Plan
ist nicht automatisch vorgeschrieben. Seedübernahme zählt nicht als Verbesserung.

Die finalen Zeitlimits werden in einer eigenen Budgetkalibrierung festgelegt,
statt aus den bisherigen heterogenen Läufen übernommen zu werden:

1. Je Methode einen einfachen, mittleren und schweren repräsentativen Fall
   auswählen.
2. Jeden Fall in einem zusammenhängenden Lauf bis höchstens 900 s beobachten;
   für das große Linienmodell darf der schwere Fall 1.800 s erhalten.
3. Incumbent, Bound, Gap, letzte Verbesserung und RSS bei
   30/60/120/300/600/900 s erfassen. Für die Kernaussagen zwei Seeds nutzen.
4. Das Standardbudget am frühesten Zeitpunkt setzen, nach dem der überwiegende
   Teil des beobachteten Incumbent-Gewinns erreicht ist. Nur Headline-Zellen
   erhalten ein längeres Budget, wenn nach dem Standardbudget noch echte
   Verbesserungen oder Boundfortschritte auftreten.
5. V2 und V3 im `relevant`-Katalog mit identischen Instanzen und Seeds
   vergleichen; Modellbau und Peak-RSS gehören zum Gate.
6. Die daraus gewählten finalen Zeitlimits, die Kalibrierungsfälle und die
   beobachteten Fortschrittskurven im Methodenanhang der Thesis dokumentieren.
   Die Hauptkapitel berichten nur die vorab festgelegten Budgets und verweisen
   für deren Ableitung auf diesen Anhang.

Bis diese Kalibrierung vorliegt, gelten 300 s als Screening-, 900 s als
Bestätigungs- und 1.800 s als maximale Headline-Laufzeit, nicht als bereits
wissenschaftlich begründete finale Budgets. Die Läufe erfolgen sequenziell mit
bis zu zwölf Workern und höchstens 32 GiB Prozessbaum-RSS. Der Supervisor
beobachtet zusätzlich systemweiten Speicherdruck und Swap; 32 GiB sind kein
reservierter Speicher.

Mehr Betriebszeit, mehr Solverzeit und höhere Nachfrage sind drei getrennte
Faktoren und dürfen nicht im selben Vergleich gemeinsam verändert werden.

## 19. Kennzahlen, Bounds und Ergebnisformat — `FROZEN`

### Verkehrliche Kennzahlen

**Kapazität, Haupttabelle:** exaktes \(\kappa_{AS}\), validiertes
\(\kappa_{SS}^{LB}\), absoluter Gewinn, Faktor
\(\kappa_{SS}^{LB}/\kappa_{AS}\), verfügbare und tatsächlich eingesetzte
Flotte sowie Nachweisstatus U=0.

**Journey Time, Haupttabelle:** mittlere Zeit von Freigabe bis Ziel und relative
Änderung gegenüber All-Stop, personenmengengewichtetes P95 sowie die Zerlegung
in Freigabe bis Plattformabfahrt und Plattformabfahrt bis Ziel. U muss in jeder
ausgewerteten Zelle null sein.

**Mechanismustabellen beziehungsweise Anhang:** Bedienung je OD und
Freigabebucket, Musterverteilung, Stopps, Rundenzahlen, Gesamt- und Maximalwait,
Betriebszeit je Kabine sowie Auslastung der maßgeblichen Rope-, Merge- und
Stationsressourcen. Ein Fairnesswert ist ohne eigene Fairnessfrage keine
Headline-Kennzahl; gruppenweise Resultate bleiben zur Diagnose erhalten.

### Algorithmische Kennzahlen

- Vorbereitung, Modellbau, Suche, Validierung und Gesamtzeit;
- Variablen, Constraints, Intervalle/Ressourcenzeilen und Peak-RSS;
- Seedwert, erste native Lösung, echte Verbesserungen und letzter Fortschritt;
- validierter Incumbent, gültiger Bound, Gap und dessen Gültigkeitsbereich;
- Solverstatus und Abbruchgrund.

### Nachweisstufen

1. unabhängig gültiger Fahrplan;
2. exaktes Optimum innerhalb einer eingeschränkten Domäne;
3. globaler Bound derselben Domäne;
4. Vorteil eines gültigen Skip-Stop-Plans gegenüber einer exakten oder
   abgesicherten All-Stop-Referenz;
5. vollständige Bedienung U=0 als unmittelbarer Optimalitätsnachweis für das
   primäre Ziel bei festem N.

## 20. Quellen, Kalibrierung und Reproduzierbarkeit — `OPEN`

Jeder physische Parameter erhält:

- Name, Einheit und interne Tickdarstellung;
- Quelle, Abschnitt und Abrufdatum;
- Originalwert beziehungsweise veröffentlichter Bereich;
- Ableitung des verwendeten Werts;
- Evidenzklasse: Herstellerwert, regulatorischer Wert, wissenschaftliche
  Literatur, daraus abgeleitet oder ausdrücklich synthetische Annahme.

Jeder Experimentfall speichert:

- versionierte Spezifikation aller Kategorien;
- Problem-, Modell- und Quellenfingerprint;
- exakte Integer-Nachfragegruppen;
- All-Stop-Referenz und Skip-Stop-Startplan;
- Solverparameter, Code-Commit und Arbeitsbaumstatus;
- Verlauf, Endresultat und unabhängiges Zertifikat.

## 21. Frontend und visuelle Prüfung — `PROVISIONAL`

Der Scenario Viewer soll Topologie und Geometrieprofil getrennt auswählen und
jede Abschnittslänge sowie resultierende Fahrzeit anzeigen. Profilwechsel darf
keinen alten Fahrplan mit unpassendem Fingerprint abspielen. Vorgesehen sind:

- schematische Ansicht für Ressourcen und Haltemuster;
- längenbezogene Ansicht für Geometrievergleich;
- Anzeige von Seil-/Plattformgeschwindigkeit, Headways, Umlaufzeit, K_AS,
  Kmax, Betriebsphasen und Nachfrageprofil;
- Quellenstatus beziehungsweise Kennzeichnung synthetischer Werte.

Die visuelle Darstellung prüft Verständlichkeit, ersetzt aber keine physische
Zertifikatsvalidierung.

## 22. Freeze-Checkliste pro Fall

Ein Fall darf erst in die finale Kampagne, wenn alle Felder beantwortet sind:

- [ ] Forschungsfrage und Primärziel
- [ ] Topologie und Stationsarchitektur
- [ ] gerichtete Abschnittslängen
- [ ] Seil-/Plattformgeschwindigkeit und Stationskinematik
- [ ] sämtliche Ressourcenheadways
- [ ] Warm-up, Nachfragefenster, Bedienungsdeadline und Recovery
- [ ] Anfangszustand, Reservoirlebenszyklus, K_AS und Kmax
- [ ] zulässige Betriebsweise, Waiting und Musterkatalog
- [ ] räumliche OD-Familie und zeitliches Profil
- [ ] absolute Nachfrage, rho und verschachtelte Integerfolge
- [ ] phasenoptimierte All-Stop-Referenz
- [ ] Skip-Stop-Methode und Startplan
- [ ] Zeit-/Speicherbudget und Wiederholungen
- [ ] Kennzahlen und erforderliche Nachweisstufe
- [ ] Quellenregister und eindeutige Fall-ID
- [ ] unabhängige Validierung und Frontenddarstellung

## 23. Bestehende Detaildokumente

- [Versuchsplan](experimental_design_20260913.md)
- [Nachfragefamilien und Profile](../reference/demand_case_families.md)
- [Kalibrierungs- und Beispielplan](../plans/thesis_example_calibration_20260913.md)
- [All-Stop-Referenz](../reference/all_stop_no_wait_capacity_baseline.md)
- [Linienmodell und bisherige R2-Ergebnisse](../findings/reservoir_line_dispatch_pilot_20260912.md)
- [Linienmodell-Kompaktion](../findings/reservoir_line_compaction_results_20260913.md)
- [Längenskalierung](../findings/reservoir_line_length_scaling_results_20260913.md)
- [Verdoppelte Betriebszeit](../findings/reservoir_line_operation_horizon_results_20260913.md)
- [Artificial capacity experiments](../plans/artificial_case_capacity_experiments.md)

## 24. Nächste gemeinsame Entscheidungen

Forschungsfragen, Topologien, Stationsarchitektur, Headwaylogik,
All-Stop-Referenz, Solverrollen und Ergebniskennzahlen sind eingefroren.

Als Nächstes werden gemeinsam entschieden:

1. Stationsmaße, Geschwindigkeiten und Kabinenwerte gemeinsam; Streckenlängen
   und Rollen sind in § 6 bestätigt. Quellen und eigene Ableitungen mitführen.
2. Der genaue Betriebszeitvertrag: umlaufabhängiger Warm-up, 60-min-Kohorte,
   Completion-Flush, Recovery und Journey-Beobachtungsdauer.
3. Waiting-Reparatur des Linienmodells, insbesondere maximaler Wait und
   freigegebene Besuche.
4. Ankunftsdarstellung und Aggregationsprüfung für die bestätigten Funktionen
   aus §§ 12–13; Hubwahl und Umgang mit ungleichmäßigen Stationsabständen.
5. Flottengrenzen, finale Fallmatrix und empirische Solverbudgetkalibrierung
   auf Basis der zuvor festgelegten Physik und Betriebsverträge.

## 25. G500-Implementierung und Kalibrierungsentscheidung — `PARTIAL FREEZE`

Die gemeinsame Pipeline und die lokale Read-only-Frontendübersicht sind implementiert.
Live-Integration, Replay und Abbildungsexporte sind noch offen; die Aussage einer
vollständig abgeschlossenen Umsetzung wird durch die
[Nachprüfung vom 15.09.2026](../findings/thesis_implementation_review_20260915.md)
korrigiert. Diese Nachprüfung hat Vorrang vor den folgenden ursprünglichen
Kalibrierungseinschätzungen.
Die erste Kalibrierung verwendet G500/P0. Sie deckt die zwölf vorgesehenen
Gruppen ab; tatsächlich gelöst wurden zunächst die drei F2-Gruppen. Rohdaten,
Zertifikate und Auswertung liegen im Ergebnisordner
`results/thesis_g500_calibration_20260914_v2` und im zugehörigen
[Befund](../findings/thesis_g500_calibration_20260914.md).

Für die Kapazitätsreferenz gilt ausdrücklich das regelmäßige, phasenoptimierte
No-Wait-All-Stop-System mit gemeinsamer Phase. Bei 30-s-Nachfrageauflösung
wurden nachgewiesen:

- T5R/G500/F2: `K_AS = 62`, `kappa_AS = 2.901` Personen;
- T6R/G500/F2: `K_AS = 75`, `kappa_AS = 2.932` Personen.

Der Linienansatz bediente bei jeweils 110 % dieser Referenznachfrage schon am
Referenz-K vollständig: 3.192 Personen mit K=62 auf T5R und 3.226 Personen mit
K=75 auf T6R. Damit ist das Kapazitätsziel für diese beiden festgelegten
Instanzen optimal gelöst (`U=0`). Die verwendete alternierende
Nachfrage-Endpunktmischung war Teil des deterministischen Initialsamplers;
die kurze Zeit bis zum ersten Plan ist deshalb ein Reproduzierbarkeits- und
Modellbefund, kein Nachweis einer schwierigen evolutionären Entdeckung.

Für Journey Time gilt T5R/G500/F2 mit `K_ref = 10` und 150 Personen als
kalibriert. Das Labelled Arc-Flow löste All-Stop und Skip-Stop für K=10, 15 und
23 jeweils bis Gap null. Die Skip-Stop-Reduktionen gegenüber dem direkten
All-Stop-Kontrollmodell betrugen 14,12 %, 16,73 % und 20,04 %. Zwei weitere
K23-Seeds reproduzierten denselben Optimalwert.

Die 30-s-Auflösung weicht bei der Kref-Kapazität um 0,66 % von 15 s ab.
Ein nachgeholter direkter Journey-Vergleich bei gleicher Nachfrage ergab aber
1,17 % Abweichung für Skip-Stop; damit ist die allgemeine 30-s-Freigabe offen.
Vor dem finalen Freeze werden 15 und 5 s verglichen. Bei den beiden Kapazitätsreferenzen blieb die
15-s-Bisektion im kurzen Kalibrierungsbudget mit dem Intervall `[2.900, 3.000)`
offen; die Auflösungsfreigabe für finale Kapazitätsreihen ist ebenfalls noch
zu klären. Die bereits geprüften 30-s-Kapazitätszeugen behalten ihren expliziten
Gültigkeitsbereich.

Für F0, F3 und F4 fehlen noch ihre eigenen All-Stop-Referenzen und
Katalog-Gates. Sie sind im Frontend und in der Fallmatrix vorhanden, gelten
aber noch nicht als kampagnenbereit. Die vollständige Thesis-Kampagne startet
erst nach diesen Referenzläufen. Das Speichermaximum bleibt 32 GiB; die
Kalibrierung zeigte jedoch, dass aktuell Modellaufbau und CPU-Zeit und nicht
der Arbeitsspeicher die engeren Grenzen sind.
