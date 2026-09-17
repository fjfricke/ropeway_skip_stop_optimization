# Einfluss einer verdoppelten Betriebszeit auf das Reservoir-Linienmodell

Stand: 13.09.2026. Dieser Folgetest trennt **mehr Betriebszeit** von mehr
Solverzeit. Die Solverläufe erhielten weiterhin 300 Sekunden. Rohartefakte:

- `benchmarks/output/reservoir_line_length_scaling_20260913_double_operation_build_v1/`
- `benchmarks/output/reservoir_line_length_scaling_20260913_double_operation_search_300m_s0_v1/`
- `benchmarks/output/reservoir_line_length_scaling_20260913_double_operation_search_800m_s0_v1/`
- `benchmarks/output/reservoir_line_length_scaling_20260913_double_operation_search_1200m_s0_v1/`

> **Scope note (13.09.2026):** These measurements use the former selectable
> round-prefix lifecycle. They remain implementation history and are not results
> for the revised dispatch-then-continuous-service line model.

## Versuchsvertrag

Der Bedienungszeitraum nach dem 300-s-Warm-up wurde von 1.200 auf 2.400 s
verdoppelt. Die Bedienungsdeadline verschiebt sich dadurch von 1.500 auf
2.700 s. Der betriebliche Endzeitpunkt liegt je Geometrie einen vollständigen
All-Stop-Umlauf später, damit alle eingesetzten Kabinen weiter rechtzeitig ins
Reservoir zurückkehren können. Umlaufzeit, Headway, All-Stop-Sättigungsflotte
und Kmax ändern sich nicht.

Zwei Nachfrageverträge sind notwendig:

- **Fixed demand:** Die ursprünglichen 3.074 Personen bleiben unverändert.
  Dieser Fall misst, ob mehr Zeit dieselbe Nachfrage leichter bedienbar macht.
- **Fixed rate:** Die ursprünglichen Nachfragegruppen werden um 1.200 s
  verschoben wiederholt. Damit verdoppeln sich Zeitraum und Nachfrage auf
  6.148 Personen. Dieser Fall ist der aussagekräftigere Kapazitätsvergleich.

Alle Modelle verwenden `intervals + encoding_specific + shared_rounds` (V2),
No-Wait und die gesättigte, gleichmäßig phasenverschobene All-Stop-Bewegung als
geprüften Startplan.

## Modellgröße

| Länge | Nachfrage | Vorlagen | Variablen | Constraints | Intervalle | Ride-Variablen | Proto | Build |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 300 m | 3.074 | 23 | 66.225 | 223.480 | 27.525 | 31.275 | 13,81 MiB | 1,49 s |
| 300 m | 6.148 | 23 | 95.775 | 312.166 | 27.525 | 46.050 | 19,15 MiB | 2,20 s |
| 800 m | 3.074 | 11 | 63.140 | 214.239 | 28.700 | 29.520 | 13,36 MiB | 1,44 s |
| 800 m | 6.148 | 11 | 94.629 | 308.739 | 28.700 | 45.264 | 19,05 MiB | 2,20 s |
| 1.200 m | 3.074 | 9 | 55.695 | 196.280 | 34.545 | 25.380 | 12,55 MiB | 1,37 s |
| 1.200 m | 6.148 | 9 | 84.366 | 282.326 | 34.545 | 39.715 | 17,70 MiB | 1,95 s |

Gegenüber dem 20-min-Sättigungsfall steigt das Fixed-Rate-Modell auf etwa das
3,0- bis 4,8-Fache der Variablen und das 3,0- bis 3,9-Fache der Constraints.
Die Ursache ist, dass jede Kabine mehr mögliche Rundenzahlvorlagen und jeder
Ride mehr zeitlich erreichbare Besuche erhält. Die Builds bleiben mit höchstens
95.775 Variablen, 312.166 Constraints und 2,20 s schnell. Der Engpass ist die
Suche und nicht die Modellerzeugung.

## All-Stop-Kapazität bei fixierter Bewegung

Die Werte sind exakte ganzzahlige Passagieroptima auf der fixierten,
gleichmäßig phasenverschobenen All-Stop-Bewegung:

| Länge | 20 min, D=3.074 | 40 min, D=3.074 | 40 min, D=6.148 |
|---:|---:|---:|---:|
| 300 m | 2.384 | **3.074** | **5.134** |
| 800 m | 1.496 | **3.074** | **4.236** |
| 1.200 m | 808 | **2.816** | **3.448** |

Bei fester Gesamtnachfrage kann All-Stop nach der Verdopplung bei 300 und
800 m alle Personen bedienen. Dieser Vergleich eignet sich deshalb nicht mehr,
um einen Skip-Stop-Kapazitätsvorteil sichtbar zu machen. Bei gleichbleibender
Nachfragerate bleibt dagegen in allen drei Geometrien ausreichend Überlast:
1.014, 1.912 beziehungsweise 2.700 Personen bleiben unbedient.

Die Bedienung wächst überproportional gegenüber zwei Kopien des kurzen
20-min-Ergebnisses, besonders auf langen Strecken. Ein längerer Zeitraum
reduziert Anfahr-, Freigabe- und Horizont-Randeffekte und erlaubt mehr vollständig
nutzbare Umläufe. Das ist ein verkehrliches Ergebnis und kein Solvereffekt.

Diese Werte sind noch keine globalen All-Stop-Optima über alle denkbaren
Dispatchphasen. Sie sind exakt **bedingt auf die fixierte gesättigte
All-Stop-Bewegung**.

## Freie Skip-Stop-Suche bei konstanter Nachfragerate

Je Geometrie wurde V2 mit demselben All-Stop-Startplan und 300 s Solverzeit
ausgeführt:

| Länge | Start | validiertes Ende | Flotte | native Bedienungs-UB | erste Lösung | Peak-RSS |
|---:|---:|---:|---:|---:|---:|---:|
| 300 m | 5.134 | 5.134 | 60 | 6.148 | 62,7 s | 9,55 GB |
| 800 m | 4.236 | 4.236 | 131 | 5.978 | 28,1 s | 7,38 GB |
| 1.200 m | 3.448 | 3.448 | 188 | 5.295 | 18,4 s | 7,21 GB |

Keiner der drei Läufe verbesserte den Startplan. Die einzige gemeldete native
Lösung war jeweils die Übernahme des All-Stop-Hints; danach folgte ein Plateau
bis zum Zeitlimit. Die oberen Schranken lassen viel theoretischen Spielraum,
führen die Suche aber nicht zu besseren Linienmustern.

## Folgerung für den Versuchsplan

Ein längerer Bedienungszeitraum ist für realistischere stationäre
Kapazitätsaussagen sinnvoll. Dabei muss die Nachfrage proportional zum Zeitraum
wachsen; andernfalls wird der Fall bei 300 und 800 m bereits durch All-Stop
vollständig bedient und kann keinen Kapazitätsvorteil von Skip-Stop zeigen.

Für die Thesis sollte der längere Zeitraum deshalb mit einer konstanten
Nachfragerate, getrenntem Warm-up und ausreichender Rückkehrzeit verwendet
werden. Die resultierenden Modelle sind baubar, benötigen in der Suche aber
bereits 7,2 bis 9,6 GB und zeigen mit einem All-Stop-Hint in fünf Minuten kein
Musterlernen. Vor einer großen Matrix braucht das Linienmodell daher bessere
konstruktive Skip-Stop-Startpläne beziehungsweise explizit vorgegebene
Musterfamilien. Mehr Betriebszeit allein behebt das Suchplateau nicht.
