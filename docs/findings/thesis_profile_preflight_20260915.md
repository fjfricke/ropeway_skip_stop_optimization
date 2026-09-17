# G500-Vorprüfung: Auflösung und bisher fehlende Profile

Stand: abgeschlossene Vorprüfung am 15.09.2026; gezielte Nachprüfungen separat. Hauptkampagne nicht gestartet.
Rohdaten: `results/thesis_g500_preflight_20260915`.
Vertrag und Budget: [Vorprüfungsplan](../plans/thesis_profile_preflight_20260915.md).

## Bereits abgeschlossene Auflösungsprüfung

T5R/F2, K10, dieselben 150 Personen, feste Starts, kein Fahrplanstart:

| Modus | 15-s-Freigaben | 5-s-Freigaben | Abweichung zum feineren Wert |
|---|---:|---:|---:|
| All-Stop | 41.903,59995 | 41.618,79995 | 0,6843 % |
| Skip-Stop | 36.474,83995 | 36.666,32995 | 0,5223 % |

Kosten in Passagiersekunden. Beide 5-s-Ergebnisse sind optimal. Die native
15-s-Skip-Stop-Untergrenze liegt nur 0,0027 unter der validierten Lösung.
Damit ist die 1-%-Toleranz für diesen Fall erfüllt; keine pauschale Freigabe
anderer Profile, Flotten oder Kapazitätsreferenzen.

Die vier F2-Kapazitätsprüfungen (T5R/K62, T6R/K75, jeweils 15/5 s) bestätigen
jeweils N=2.900 vollständig. N=3.000 bleibt jeweils UNKNOWN. Daher lässt sich
aus diesen neuen Läufen noch keine Kapazitätsabweichung von höchstens 1 %
ableiten. Ein fehlender Nachweis ist keine festgestellte Abweichung.

## Aufgedeckter Abbruchfall

`reference_t6r_f0_capacity_r15` wurde nach 90,09 s vom Supervisor mit
`WALL_DEADLINE` beendet. Der innere Prozess hatte bei 32,29 s bereits einen
vollständig validierten N=1.000-Zeugen protokolliert und bei 88,93 s den
ungeklärten N=2.000-Versuch beendet. Der vollständige Checkpoint wurde erst
nach Rückkehr der gesamten Referenzsuche geschrieben. Die spätere Dateiprüfung
fand `best.json`, `best_case.json` und `result.json` doch noch vollständig vor:
Die erste Vermutung eines verlorenen Checkpoints war falsch. Der gültige
N=1.000-Zeuge wurde für die separate Fortsetzung erneut unabhängig geprüft.
Der Lauf selbst bleibt wegen des Supervisorabbruchs als abgebrochen markiert.

Ursachen im Code:

- Der Phasenmodellbuilder erhielt die verbleibende Zeit vor dem Aufbau und
  gab anschließend denselben Betrag als reine CP-SAT-Suchzeit weiter.
- Ein neuer Referenz-Incumbent wurde erst am Ende aller Kapazitätsproben
  dauerhaft als Plan gesichert.

Die eingefrorene Folge wurde nicht während ihres Laufs umgebaut. Absolute
Budgetweitergabe und sofortige Checkpointablage sind anschließend korrigiert
worden und werden in den separaten Nachprüfungen verwendet. Das historische Abbruchergebnis
wird dabei nicht überschrieben oder rückwirkend als erfolgreicher Versuch gezählt.

## Messartefakte

`measurements.csv`, `capacity_probes.csv` und `evolution_improvements.csv`
werden durch `benchmarks/summarize_thesis_preflight.py` aus den Rohresultaten
erzeugt. Fehlende Grenzen bleiben leer. Ein Nachfrage-Endwert in der
Referenzsuche ist kein tatsächlich gelöster Nachfragepunkt; dafür sind die
einzelnen Proben maßgeblich. Ein Incumbent-Ereignis ist noch kein Plateau-
oder Entdeckungsnachweis; Initialsampler und Laufphase werden mit ausgewertet.

Die Live-Anzeige zeigt die Vorprüfung getrennt vom bisherigen 30-s-Datenpaket.
Portable Zusammenfassungen enthalten keine lokalen Befehle oder privaten Pfade.
Der Frontend-Produktionsbuild besteht; vorhandene Warnung: ein JS-Chunk liegt
knapp über 500 kB. Das ist kein Solver- oder Korrektheitsfehler.
