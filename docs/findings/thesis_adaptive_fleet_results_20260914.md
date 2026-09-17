# Adaptive Flottenleiter: erster Warmstart-Test

Stand: 14.09.2026. Der Test prüft die im Entscheidungsregister beschriebene
adaptive Flottenleiter auf T5R/G800, F2/P0, 2.750 Personen und 15-Sekunden-
Nachfrageauflösung. Jede Stufe verwendet `shared_rides`, den relevanten
Musterkatalog, zwölf Worker und ein Prozesslimit von 32 GiB. Das Gesamtbudget
je Stufe beträgt 300 Sekunden; 70 % entfallen auf die No-Wait-Konstruktion und
der Rest auf Waiting und Passagierzuordnung.

## Kette

Der Startzeuge hatte 11 Kabinen und 448 bediente Personen. Die adaptive Formel
mit (K_{AS}=84) ergibt Schrittweite (b=4) und startet bei Kmax 16. Die
Stufen wurden mit dem validierten `construction_best.json` der vorigen Stufe
gestartet. Der Waiting-Plan wurde separat bewertet; für die nächste Stufe wird
bewusst der No-Wait-Plan verwendet, weil der Linienmaster positive Waiting-
Entscheidungen nicht als Linienvorlage repräsentiert.

| Cap | No-Wait bedient | Waiting bedient | verwendete Kabinen | Variablen | Constraints | Peak-RSS | Ergebnis |
|---:|---:|---:|---:|---:|---:|---:|---|
| 16 | 640 | 648 | 16 | 41.712 | 536.602 | 11,6 GiB | Cap bindet |
| 20 | 800 | 808 | 20 | 52.140 | 670.658 | 10,6 GiB | Cap bindet |
| 28 | 880 | 880 | 22 | 72.996 | 938.770 | 11,7 GiB | Suchlauf endet nach drei Stufen |

Die tatsächlichen Stufenlaufzeiten lagen bei 272,6 s, 283,1 s und 283,2 s.
Alle drei Konstruktionen fanden eine native Lösung; die übernommene Lösung
blieb zusätzlich als validierter Rückfall erhalten. K28 hätte nach der Formel
als nächste Stufe K32 erhalten, wurde wegen des begrenzten Piloten aber nicht
mehr gestartet.

## Interpretation

Die Kette zeigt einen klaren praktischen Effekt gegenüber den früheren
unabhängigen K84/K154/K280-Läufen: Der Wert steigt monoton von 448 auf 640,
800 und 880 No-Wait-Bedienungen. K16 und K20 sind vollständig ausgelastet;
K28 verwendet 22 von 28 Slots. Das ist ein belastbarer Hinweis, dass die
Flottengrenze bei den ersten Stufen tatsächlich gesucht wird und der
Warmstart nicht nur eine formale Übergabe ist.

Der Test beweist weder ein Skip-Stop-Optimum noch eine Nähe zur All-Stop-
Kapazität. Für die All-Stop-Referenz liegen weiterhin ungefähr 2.875 bis 2.881
Personen als offene Kapazitätsklemme vor. Der Abstand zeigt, dass weitere
Stufen allein noch nicht genügen; als nächstes muss geprüft werden, ob K32/K40
weiterhin systematisch bessere Muster finden oder ob die Konstruktion erneut
plateaued.

## Implementationsbefund

Die Kampagne hatte zuvor versehentlich alle großen Caps unabhängig gestartet.
Die neue Kette verwendet deshalb einen expliziten Fleet-Resize-Checkpoint,
validiert die unveränderte Domäne und erlaubt ausschließlich eine Änderung der
verfügbaren Flottengrenze. Ein Seed mit anderer Nachfrage, Auflösung,
Geometrie oder Betriebsregel wird abgewiesen. Korrektheitstests für diese
Übertragung und den validierten Rückfall bestehen.

