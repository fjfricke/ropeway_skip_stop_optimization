# OD-Inventory-Passagiere im vollständigen CP-SAT

Stand: 16.09.2026. Vorläufiger Implementierungs- und Buildbefund.

## Korrektheit

Die neue Passagierdarstellung bündelt Freigabegruppen gleicher OD zu
ganzzahligen Mengen je tatsächlicher Kabinenfahrt. Ein `Cumulative` je OD
erzwingt, dass zu jedem Einstiegszeitpunkt höchstens die bereits freigegebene
Nachfrage an Bord gegangen ist. Die Lösung wird anschließend deterministisch
auf die bisherigen Ride-IDs zurückübersetzt und mit dem unabhängigen
Reservoirvalidator geprüft.

72 gezielte Tests bestanden. Darin enthalten sind Vergleiche mit der bisherigen
Gruppenformulierung für `unserved` und `journey_time`, mehrere Kabinen und
Freigabebatches, Tickgrenzen, Seedübernahme sowie die angrenzenden Thesis- und
Fortsetzungsverträge. Unterschiedliche Zuordnungen gleichwertiger
Freigabebatches sind zulässig; Zielwert und Bedienung bleiben gleich.

## Modellgröße auf T5R/G500/F2/P0

Eingefrorener Fall: N=3.210, K≤69, 15-Sekunden-Freigaben, Waiting bis 1.200 s.

| Kennzahl | Gruppen | OD inventory | Änderung |
|---|---:|---:|---:|
| Variablen vor Presolve | 638.127 | 97.361 | −84,7 % |
| Constraints vor Presolve | 2.337.064 | 166.328 | −92,9 % |
| Ride-Mengen | 273.240 | 1.518 | −99,4 % |
| Build-Wandzeit | 16,33 s | 4,41 s | −73,0 % |
| maximaler Prozess-RSS beim Build | 3,14 GB | 0,49 GB | −84,5 % |

Für OD inventory meldete CP-SAT nach Presolve 36.868 Variablen und 81.355
Constraints. Die zwei OD-Profile enthielten zusammen 1.878
Bestandsintervalle, davon 1.518 variable Fahrtintervalle und 360 feste
Freigabeintervalle.

## Kurzer Suchtest

Ein 60-Sekunden-Gesamttest verwendete fünf Sekunden zur festen
All-Stop-Neubewertung. Diese erhöhte die bestätigte Bedienung von 2.918 auf
2.928 Personen auf derselben Bewegung. Der freie Solver erhielt anschließend
knapp 38 Sekunden, verbrauchte diese vollständig im Presolve und begann noch
keine Branch-and-Bound-Suche. Der validierte Startplan blieb erhalten.

Ein anschließender Dreiminuten-Pilot erreichte nach Presolve die freie Suche.
CP-SAT meldete 21.801 Branches und zwei native Lösungen. Die beste Lösung blieb
bei 2.928 bedienten Personen, reduzierte deren lexikografischen Journey-Term
aber um 1.258.065 Mikrosekunden. Das Zertifikat wurde unabhängig validiert.
Der Solver-RSS erreichte 5,94 GB. Die native Schranke blieb negativ; nach der
sicheren Nichtnegativitätsgrenze ist der berichtete Lower Bound daher 0 und der
globale Gap weiterhin 100 %.

Der Größenbefund ist damit eindeutig positiv und die freie Suche ist technisch
funktionsfähig. Ein relevanter Suchvorteil gegenüber dem Legacy-Modell ist noch
offen; der erste native Fortschritt war nur eine kleine Journey-Time-Verbesserung
und der Beweisbound blieb schwach.
Die aktuelle Implementierung verwendet außerdem weiterhin den vollständigen
Legacy-Kandidatenkatalog als Zertifikatsadapter. Dessen direkte strukturelle
Ersetzung ist eine separate Speicher- und Vorbereitungsoptimierung.
