# Längenskalierung des kompakten Reservoir-Linienmodells

Stand: 13.09.2026. Die kontrollierte Kampagne ist abgeschlossen. Rohartefakte:
`benchmarks/output/reservoir_line_length_scaling_20260913_campaign_v1/`.

> **Scope note (13.09.2026):** These measurements use the former selectable
> round-prefix lifecycle. They remain implementation history and are not results
> for the revised dispatch-then-continuous-service line model.

## Fragestellung und Gültigkeitsbereich

Der Test prüft, ob längere freie Seilabschnitte und die dadurch größere
All-Stop-Sättigungsflotte das kompakte Linienmodell unhandlich machen. Grundlage
ist der historische Fünf-Stationen-R2-Fall mit 3.074 Personen, 5 m/s
Seilgeschwindigkeit, unveränderten Stationszeiten und Headways sowie No-Wait.
Je Bewegung wurde ausschließlich der freie Seilfahrzeitanteil von 150 m auf
300, 800 beziehungsweise 1.200 m ersetzt. Lokale Stationsphasen,
Ressourcennutzungen, Nachfrage und Mikrosekundenauflösung blieben unverändert.

Alle Modelle verwenden den neuen Linienmodell-Default
`intervals + encoding_specific + shared_rounds` (V2). Das ist eine kontrollierte
synthetische Sensitivität und noch keine quellenkalibrierte Sechs-Stationen-
Thesisgeometrie.

Zwei Verträge trennen die Ursachen:

- **Controlled:** Kmax=50 und der historische absolute Zeitvertrag bleiben fest.
- **Saturation:** Aus der regelmäßigen All-Stop-No-Wait-Belegung wird
  `K_AS=floor(C/h)` abgeleitet, Kmax ist `ceil(1.25 K_AS)`. Dispatch ist während
  eines All-Stop-Umlaufs erlaubt; der Rückkehrhorizont endet einen Umlauf nach
  der unveränderten Bedienungsdeadline.

Die gesättigte gleichmäßig verteilte All-Stop-Bewegung wurde je Länge unabhängig
validiert. Ihre Passagierzuordnung wurde bei fixierter Bewegung optimal gelöst.
Sie ist die gemeinsame Startlösung, aber noch kein globaler Phasennachweis über
alle denkbaren All-Stop-Randbedingungen.

## Modellgröße

Median aus drei isolierten Build-Prozessen:

| Länge | Vertrag | Kmax | K_AS | Vorlagen | Variablen | Constraints | Intervalle | Ride-Variablen | Proto | Build | RSS |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 300 m | Controlled | 50 | 60 | 12 | 17.550 | 61.355 | 9.750 | 8.100 | 3,75 MiB | 0,36 s | 158 MiB |
| 300 m | Saturation | 75 | 60 | 14 | 29.775 | 104.005 | 16.725 | 13.725 | 6,47 MiB | 0,63 s | 184 MiB |
| 800 m | Controlled | 50 | 131 | 5 | 3.751 | 14.655 | 3.950 | 1.550 | 0,94 MiB | 0,08 s | 133 MiB |
| 800 m | Saturation | 164 | 131 | 6 | 30.013 | 103.867 | 16.236 | 13.776 | 6,45 MiB | 0,61 s | 182 MiB |
| 1.200 m | Controlled | 50 | 188 | 3 | 2.251 | 8.855 | 2.550 | 900 | 0,57 MiB | 0,05 s | 130 MiB |
| 1.200 m | Saturation | 235 | 188 | 6 | 17.626 | 71.730 | 23.265 | 7.050 | 4,90 MiB | 0,42 s | 168 MiB |

Die größere Flotte verursacht hier keinen Modellgrößendurchbruch. Der Grund ist
strukturell: Mit längeren Umläufen passen weniger Rundenzahlvorlagen in den
Horizont. V2 speichert gemeinsame Rundenvorsätze nur einmal. Dadurch kompensiert
die kleinere Vorlagenzahl einen großen Teil der zusätzlichen Kabinenslots. Das
ist keine allgemeine Komplexitätsgarantie; ein längerer Bedienungshorizont oder
größerer Musterkatalog kann den Effekt umkehren.

## Fünfminütige Suche

Die Tabelle zeigt unabhängig validierte Endwerte. Der All-Stop-Wert ist das
Optimum der ganzzahligen Passagierzuordnung auf der jeweils fixierten
gesättigten Bewegung.

| Länge | All-Stop-Seed | Seed 0 | Seed 1 | nachgewiesener Seedgewinn | End-RSS |
|---:|---:|---:|---:|---:|---:|
| 300 m | 2.384 | 2.384 / K60 | 2.384 / K60 | 0 in beiden Läufen | 6,2 / 6,0 GiB |
| 800 m | 1.496 | 1.504 / K131 | 1.504 / K131 | +8 in beiden Läufen | 5,8 / 7,1 GiB |
| 1.200 m | 808 | 816 / K168 | 840 / K105 | +8 / +32 | 3,7 / 4,3 GiB |

Bei 300 m wurde der Hint nach rund 38--39 s übernommen und danach nicht
verbessert. Bei 800 m entstand die gleiche Bedienungsverbesserung nach 84 s
beziehungsweise 42 s. Bei 1.200 m produzierte Seed 0 erst spät +8; Seed 1
verbesserte stufenweise bis +32 und reduzierte danach die Flotte deutlich.

Die lokalen Linienmodell-Schranken bleiben breit. Für 300 m liegt die
Bedienungsobergrenze bei der Gesamtnachfrage 3.074, für 800 m bei 2.798/2.766
und für 1.200 m bei 1.372. Die Läufe beweisen daher kein globales
Skip-Stop-Optimum. Der 800-m-Gewinn ist gegenüber dem gemeinsamen All-Stop-Seed
reproduziert; ein belastbarer Satz gegen jedes zulässige All-Stop-System braucht
noch den separat geplanten phasenoptimierten All-Stop-Nachweis.

## Schlussfolgerung

V2 bleibt der richtige Default für das Linienmodell. Die befürchtete reine
Modellgrößenexplosion durch 75 bis 235 verfügbare Kabinen tritt in dieser Matrix
nicht auf. Die Suche kann bei längeren Abschnitten den All-Stop-Hint verlassen,
ist aber weiterhin seedabhängig und schließt große Gaps nicht in fünf Minuten.

Für die Thesisfälle folgt daraus:

1. Die 300/800/1.200-m-Geometrien können mit V2 weiterverfolgt werden; Build und
   Speicher sind kein Ausschlussgrund.
2. Als Nächstes müssen die quellenkalibrierten Sechs-Stationen-Zeitverträge und
   ihre phasenoptimierten All-Stop-Referenzen erzeugt werden.
3. Bedienungswerte zwischen Längen dürfen erst nach abgestimmtem
   Bedienungs-/Vorlauf-/Rückkehrvertrag verkehrlich verglichen werden. Die hier
   sinkenden Absolutwerte entstehen wesentlich durch die feste Deadline.
4. Waiting bleibt in diesem Linienmodell null und benötigt eine eigene gezielte
   Reparaturstufe.

Reproduzierbare Quellen sind der Kampagnenrunner
`benchmarks/run_reservoir_line_length_scaling.py`, `manifest.json`,
`build_summary.json`, `search_summary.json`, die einzelnen `result.json`-Dateien
und sämtliche validierten `best.json`-Zertifikate im Artefaktordner.
