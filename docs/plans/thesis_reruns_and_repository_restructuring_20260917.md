# Thesis-Wiederholungen und anschließende Repository-Bereinigung

Stand: 17.09.2026. Code-Sicherung vor den Anpassungen: `ae62642`.

Der aktuelle Versuchsablauf steht zentral in der
[Thesis-Versuchs-README](../experiments/README.md). Neu vereinbart sind **27
Kalibrierungen zuerst**: 24 feste Journey-Starts und drei regelmäßige
All-Stop-Phasenreferenzen bei geometrisch ermitteltem K_AS,max für F0/F2/F3.
Der gemeinsame reine Kalibrierungscontroller ist noch umzusetzen.

Nachträglich bestätigt: OIP wird bei **100 % und 110 %** der jeweiligen neuen
CAL-O-Kapazität verglichen (110 % auf ganze Personen aufrunden). Frühere Hinweise
auf einen offenen Lastfaktor unten sind damit überholt; K-Raster und endgültige
Kampagnenbudgets bleiben offen. Details stehen in der zentralen Versuchs-README.

**Abgrenzung:** Die Thesis-Laufverträge, ihre Vorbereitung sowie die erste
Repo-, Archiv- und Frontend-Trennung sind umgesetzt und getestet. Keine Kampagne
wird durch diesen Umbau gestartet. Weitere Archivierung alter Optimierer bleibt
eine getrennte, anhand der unten beschriebenen Grenzen auszuführende Etappe.
Thesis, Präsentation, temporäre Dateien und Laufdaten gehören nicht zum
Code-Sicherungscommit. Bestehende Ergebnisse werden weder gelöscht noch umetikettiert.

## 1. Bestätigte Versuchsverträge

| Bestandteil | Journey-Reihen | OIP-Musterscreening |
|---|---|---|
| Geometrie | T5R/G500 | T5R/G500 |
| Schutz an Weichen | Architektur B: STOP-Leader-Schutz an Ein- **und** Ausfahrt | identisch |
| Geschwindigkeit | Seil 6 m/s, Plattform 0,3 m/s | identisch |
| Anfangszustand | feste ausgeglichene Positionen, keine Passagiere | optimierte Positionen, keine Passagiere |
| Betrieb | kein Reservoir, keine Rückkehrpflicht | identisch |
| Nachfrage | P0, deterministisch, Freigabeauflösung 15 s | identisch |
| Zeitfenster | zwei All-Stop-Umläufe + 900 s Bedienungsabschluss + 300 s Weiterfahrt | identisch |
| Waiting | zunächst aus | zunächst aus |
| Raster | bestehende Mikrosekunden | bestehende konservative Millisekunden |
| Ziel | volle Bedienung, dann Journey Time | lexikografisch Unserved, dann Journey Time |

Für die aktuelle Geometrie ist der All-Stop-Umlauf 732 s: Freigaben im Fenster
0–1464 s, Bedienung bis 2364 s, Betrieb bis 2664 s. Begonnene Bewegungen und ihre
Schutzintervalle werden am Betriebsende nicht abgeschnitten. Die 300 Sekunden
sind zusätzliche Weiterfahrt **nach** dem Bedienungshorizont, keine zusätzliche
Nachfrage- oder Bedienungszeit. Endlicher Betrieb ist kein Nachweis unbegrenzter
periodischer Wiederholbarkeit.

Gemeinsame Geometrie und Zeitfenster machen die Startmodelle nicht identisch.
Diese Unterscheidung muss bei Vergleichen sichtbar bleiben. Kapitel 3.2 verwendet
für Architektur B dieselben Schutzannahmen an beiden Weichen; die Darstellung
mit Plattformgeschwindigkeit 0,5 m/s ist ein Rechenbeispiel, nicht die
Versuchsgeometrie mit 0,3 m/s.

## 2. Wiederholung der Journey-Reihen

F0/F2/F3/F4, jeweils All-Stop und freies Skip-Stop:

- **Relative Nachfrage:** K=10,15,20,25,30; pro K jeweils
  `floor(0.25 * κ_AS(K))` und `floor(0.75 * κ_AS(K))` — 80 Vergleichsläufe.
- **Konstante Nachfrage:** K=20,25,30; jeweils
  `floor(0.50 * κ_AS(31))` desselben Profils — 24 Vergleichsläufe.
- κ_AS bezieht sich hier ausschließlich auf den jeweiligen **festen
  ausgeglichenen All-Stop-Start**, nicht auf frei optimierte Anfangspositionen.
- K31 bleibt die Kalibrierungsflotte der konstanten Reihe; es ist kein zusätzlicher
  Vergleichspunkt und nicht die aktuell untersuchte Kabinenzahl.
- 24 neue Kalibrierungen: vier Profile × K10/15/20/25/30/31. Alte Nachweise mit
  abweichendem Weichenschutz/Nachlauf werden nicht automatisch wiederverwendet.
- 1800 s je Job einschließlich Aufbau; bei Optimierung 1 % relative Gapgrenze;
  Seed 0, zwölf Solverthreads, 32 GiB Prozessbaum-RSS, sequenziell.

Das sind 128 Jobs insgesamt: maximal 64 Stunden Einzelbudgets plus 30 Minuten
Kampagnenreserve. Dies ist die Obergrenze der vorbereiteten Matrix, keine erneute
Startfreigabe. Fehlende exakte N/N+1-Referenz blockiert ausschließlich ihre
abhängigen Vergleiche. UNKNOWN wird nicht als Unzulässigkeit behandelt.

`benchmarks/run_thesis_revised_journey_campaign.py` erzeugt standardmäßig nur das
Manifest; ein späterer Start verlangt explizit `--run`. Wiederaufnahme prüft den
Code-/Vertragsfingerprint und behält die ursprüngliche Ausführungsdeadline.

## 3. Neue OIP-Nachfragekalibrierung

Bestätigt: **regelmäßig verteilte All-Stop-Flotte mit freier gemeinsamer Phase**.
Die Referenz darf nicht als Optimum über alle unabhängigen OIP-Anfangspositionen
bezeichnet werden. Keine alten 45-Minuten-Mengen als Default für zwei Umläufe.

Vor OIP-Hauptläufen erforderlich:

1. Regelmäßige All-Stop-Bewegung unter dem kurzen Vertrag konstruieren und
   unabhängig einschließlich Anfangsbelegung und Nachlauf prüfen.
2. Gemeinsame Phase und ganzzahlige Passagierzuordnung optimieren. Bestehende
   Phasen-/Passagierbausteine prüfen und wiederverwenden; der alte Reservoir-
   Phasenrunner ist wegen Start-/Rückkehrvertrag kein unveränderter Ersatz.
3. Pro F0/F2/F3 verschachtelte Nachfrage erhöhen und ein N/N+1-Intervall bestimmen.
   Offene Intervalle bleiben offen; Zeitlimit ist kein Kapazitätsbeweis.
4. Referenzkind, genaue Flotte, Geometrie, beide Horizonte, Raster, Freigaben,
   geprüfte Zertifikate, Codeidentität und Schranken gemeinsam sichern.
5. Erst dann Lastfaktor und Haupt-K-Raster einfrieren. Die zuletzt technischen
   K40/50/62 sowie sechs Belegungen sind keine neue Kapazitätsaussage. Ein
   möglicherweise gewünschter Fünferschritt im OIP-Screening ist separat vom
   bereits bestätigten Journey-Raster festzulegen.

**Noch offen:** OIP-Lastfaktor nach der neuen Kalibrierung, endgültige OIP-K-Liste
und Budget der Referenzsuchen. Die bisherige unterschiedliche Lastwahl für F0
wird nicht still fortgeschrieben. Kein zusätzlicher Kalibrierungssolver wird im
Rahmen des Repository-Audits ungeprüft implementiert oder gestartet.

Die Suite verlangt künftig `--calibrated-cases`. Ohne diese Datei erzeugt
`--build-only` ausschließlich `pending_calibration`; ein Start bricht vor dem
ersten Solverjob ab. Das Eingabeformat nennt `contract_id`,
`reference_kind=regular_all_stop_free_common_phase` und genau drei `cases` mit
`family`, `demand_total`, `load_numerator`, `load_denominator`,
`reference_result`, `reference_sha256`. Die verlinkten Zusammenfassungen müssen
denselben Vertrag/dasselbe Referenzkind/Profil sowie `capacity_proven` und ein
benachbartes `proven_feasible_demand`/`proven_infeasible_demand` enthalten.
`demand_total=ceil(N * numerator / denominator)`. Diese Eingangsprüfung sichert
Provenienz; sie ersetzt nicht die unabhängige Prüfung der Kalibrierungszertifikate.

## 4. In diesem Schritt umgesetzt

- Gemeinsame Fensterdefinition für Journey und OIP; expliziter 300-s-Nachlauf
  im Fixed-K-Builder. Allgemeine Solverdefaults außerhalb der Thesis-Vorbereitung
  bleiben erhalten.
- Bestätigtes Fünferschrittraster, frische Referenzabhängigkeiten und
  Vorbereitung ohne Solverstart.
- Korrekte Ergebnisumhüllung der Fixed-K-Kalibrierung: keine irreführende
  Reservoir-Domäne um die tatsächlichen Fixed-Start-Probes.
- Keine automatisch übernommenen alten OIP-Nachfragemengen.
- Screening-Wiederaufnahme prüft Domäne, Masken, Nachfrage, Code und
  Solverversionen; sie setzt eine bereits laufende Gesamtdeadline nicht zurück.
- Regressionsprüfung des schon vorhandenen ENTRY_SWITCH-Schutzes bis in DDD.
  Die Formel wurde nicht nochmals verändert.

## 5. Umgesetzte Repository- und Frontend-Struktur

Der [Audit](../audits/repository_20260917.md) enthält Befunde, Belege und eine
priorisierte PR-Folge. Wichtig: Ein großer Teil der DDD-Dateien ist gemeinsame
Infrastruktur, nicht isoliert entfernbarer historischer Code.

Die erste sichere Umbauetappe ist umgesetzt. Die Zielstruktur lautet:

```text
src/             aktive Domäne, Solveradapter, unabhängige Prüfer
benchmarks/      aktuelle Thesis-Runner und explizite Konfigurationen
frontend/        Thesis-Ergebnisse, Scenario Viewer, passende EAN-Ansichten
docs/            aktuelle Verträge, Bedienung und Befunde
archive/         historische Controller/Methoden/Dokumente mit Herkunft
results/         lokale Laufdaten; separat veröffentlichbares Datenpaket
```

1. **Ergebnisse:** OIP bewahrt echte Nullwerte und exportiert fehlende Incumbents
   als `null`. Exact-K wird auch in der Laufbeschreibung als Exact-K ausgewiesen.
2. **Infrastruktur:** Prozessüberwachung und transaktionale Frontend-Indizes sind
   solverneutral. Alte Supervisor-Imports bleiben kompatibel.
3. **Archiv:** der einmalige Abschlusscontroller und der abgelöste Studienplan
   liegen mit Herkunftshinweis unter `archive/`. Gemeinsam genutzte DDD-, EAN-
   und Reservoirmodule bleiben wegen aktiver Importpfade in `src/`.
4. **Abhängigkeiten:** `psutil` ist Basisabhängigkeit; Plotting liegt im optionalen
   `analysis`-Extra.
5. **Frontend:** Thesis Atlas, aktuelle Thesis-Läufe, Scenario Viewer und Archiv
   sind getrennte Haupteinstiege. Alte direkte URLs bleiben gültig; Evolution
   wird lazy geladen. Nur `study_membership=current_thesis` und die passende
   `contract_id` erscheinen als aktuelle Evidenz.
6. **Weiter offen:** OIP-Kalibrierung, Lastfaktor, K-Raster und Budgets bleiben
   fachlich offen. Weitere Solververzeichnisse werden erst nach einem gesonderten
   Import- und Reproduktionstest archiviert.

## 6. Prüfung vor dem nächsten Start

- Prüfstand des Vertragscommits: 66 gezielt ausgewählte Tests bestanden (Vertrag,
  Headways, Horizontereignisse, Fixed-K-Kalibrierung, Wiederaufnahme,
  Reporting-Bestand und Importgrenzen). Kein vollständiger Lauf aller
  170 Testmodule und keine Performancekampagne.
- Kleine Vertrags-/Import-/Horizonttests und benachbarte Tickgrenzen bestehen.
- Build-only zeigt 24 Referenzen und 104 Journey-Vergleiche; keine Solver laufen.
- Neue Nachfragekalibrierung liefert passende geprüfte Referenzen.
- OIP-Lastfaktor/K-Raster/Budgets sind festgelegt.
- Umbauprüfung: 59 gezielte Python-Tests sowie 25 Frontend-Tests bestanden;
  Produktionsbuild und visuelle Prüfung von Thesis-, Run- und Archivansicht sind
  erfolgreich. Von der vollständigen Python-Suite bestanden 1.830 Tests, 22
  wurden übersprungen und sechs bereits fachlich veraltete/historische Tests
  scheitern (zwei Checkpoint-Fingerprints, Corridor-Verfeinerung, zwei Reservoir-
  Lebenszyklus-/Fixture-Verträge und ein alter Overload-Referenzvertrag). Diese
  Fehler liegen außerhalb der geänderten Module und werden nicht als bestanden
  dargestellt. Der Build meldet nur die bestehende Warnung zu einem großen Chunk.
- Erst danach ausdrücklich die gewünschte Teilreihe starten.
