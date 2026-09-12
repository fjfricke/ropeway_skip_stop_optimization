# Hexaly nach Lizenzfreigabe: Reproduktion und Vergleich

Stand: 11.09.2026, Vergleich abgeschlossen. **Die getestete Hexaly-Formulierung
verbessert in keinem der sechs großen Versuche den gemeinsamen Startplan.**
CP-SAT verbessert K39 in allen drei Seeds, aber nicht das Max50-Reservoir.
Ein Wechsel zu Hexaly oder ein längerer unveränderter Hexaly-Lauf wird durch
diesen Vergleich nicht gestützt. Legacy bleibt Standard.

## Engine und unveränderte Formulierung

Hexaly 15.0.20260909 ist lokal ausführbar. Die private Lizenz liegt außerhalb
des Repositories; kein Lizenzinhalt gehört zu den Ergebnisartefakten.
Die bestehende Implementierung in `optimization/ddd/native_solvers` bleibt
unverändert: gemeinsame solverfreie Vorbereitung, optionale Besuchsintervalle,
native Ressourcenlisten, ganzzahlige Ride-Mengen und exakte Zertifikatsextraktion.
Es wurde kein eigener Suchcontroller ergänzt.

## Vorprüfungen und deren Grenzen

- 18 zusätzliche Hexaly-Semantiktests bestanden, darunter unabhängige
  Überholpläne, Ressourcenberührung und -überlappung, abwesende Intervalle,
  Tickwerte über 32 Bit, Nachfragefreigabe während Waiting, Zielankunft vor
  Ziel-Waiting, Horizontgrenzen und volle Kabinen.
- Fünf Runner-Regressionstests bestanden.
- Die vier ursprünglichen Kaltstarttests mit insgesamt fünf Sekunden Budget
  bestanden ihre Optimalitätsforderungen nicht. Diese Fehlschläge bleiben
  erhalten; sie werden nicht nachträglich als bestanden ausgewiesen.
- Vier vollständig fixierte kleine Replays und vier freie Modelle mit
  geprüftem Startplan reproduzierten die jeweiligen Referenzwerte.

Ein zusätzlicher Kaltstartvergleich mit 30 Sekunden und zwölf Workern ergab:

| Kleiner Fall | Native UB | Native LB | Bekannter Optimalwert | Verlauf |
|---|---:|---:|---:|---|
| Fixed-K, Reisezeit (Personenticks) | 726.996.592 | 723.454.544 | 723.454.544 | Verbesserung bei 3,49 s; danach keine weitere |
| Fixed-K, unbediente Personen | 3 | 3 | 3 | optimal nach etwa 0,11 s |
| Reservoir, Reisezeit (Personenticks) | 3.000.000 | 2.000.000 | 2.000.000 | keine Verbesserung der vollständigen Nichtbedienung |
| Reservoir, unbediente Personen | 1 | 0 | 0 | keine Verbesserung der vollständigen Nichtbedienung |

Alle vier 30-Sekunden-Läufe lieferten unabhängig gültige native Gesamtpläne.
Die beiden kleinen Reservoirfälle zeigen bereits eine Suchschwäche ohne Seed.
Zeitlimit und Workerzahl wurden gegenüber den ursprünglichen Kurztests zusammen
geändert; daraus folgt keine isolierte Aussage zum Nutzen zusätzlicher Worker.

## Historische Zertifikate

| Fall | Referenz | Vollständig fixierter Replay | Freie Passagiere bei festen Bewegungen |
|---|---:|---|---|
| R, Max50 Reservoir | 368.765,817136 Passagiersekunden | exakt, nativ optimal; 9,20 s | exakt erreicht; nach ca. 89 s kein nativer Optimalitätsbeweis |
| K38, Kapazität | U=315 | exakt, nativ optimal; 2,31 s | exakt erreicht; nach ca. 89 s kein nativer Optimalitätsbeweis |
| C, K39 Kapazität | U=1.402 | exakt, nativ optimal; 1,83 s | exakt erreicht; nach ca. 89 s kein nativer Optimalitätsbeweis |

CP-SAT hat die jeweiligen Passagieroptima bei denselben festen Bewegungen erneut
bewiesen. Hexaly erreicht diese Werte, liefert aber selbst noch keinen Beweis.
Die strengere vorhandene Replay-Prüfung verlangt diesen zusätzlichen Beweis und
bleibt deshalb **nicht bestanden** (`historical/gate.json`, Exitcode 1).

Die separate Vergleichszulassung in `admission/hexaly.json` beruht auf korrekter
Zertifikatsreproduktion, Erreichen unabhängig bewiesener Passagieroptima und den
Semantiktests. `native_proof_gate_passed=false` bleibt ausdrücklich erhalten.
Das ist eine dokumentierte Unterscheidung zwischen Darstellbarkeit und eigener
Beweisleistung, keine nachträgliche Änderung der ursprünglichen Testergebnisse.

## Unterbrochene Kampagne v1

`hexaly_comparison_20260911_v1` enthält einen fertigen CP-SAT-R-Lauf: unveränderte
UB 368.765,817136, native LB 0, gemeinsame globale LB 209.409,890299 und damit
43,21 % vergleichbarer Gap. Keine echte Verbesserung in 150 Sekunden.

Der folgende Hexaly-R-Lauf wurde beim Modellaufbau durch Mac-Ruhezustand
unterbrochen: 6,52 Sekunden Wachzeit gegenüber 907,15 Sekunden Kalenderzeit.
Der Wächter stoppte mit `SUSPEND_DETECTED`; die übrigen zehn Hauptläufe starteten
nicht. Die gespeicherte Referenz ist keine native Hexaly-Lösung dieses Laufs.
Diese Unterbrechung erlaubt keine Aussage über große Hexaly-Suchleistung.

Die ursprüngliche Stunden-Deadline lief während der Unterbrechung/anschließenden
Wartezeit ab. Spätere Berichtserzeugung ist in `finalization_civil_seconds`
sichtbar; nach dem Suspend-Abbruch liefen keine weiteren Solver in v1.

## Neuer Vergleich v2

Mit dem anschließenden „go on“ beginnt ein eigener Vergleich mit maximal
60 Minuten Gesamtbudget und `caffeinate -i`. Die Suspend-Überwachung bleibt
aktiv. Zwölf sequenzielle Läufe zu je 150 Sekunden einschließlich Aufbau:
CP-SAT und Hexaly, R und C, Seeds 0/1/2. Beide Engines erhalten zwölf Worker
und dieselben geprüften Startpläne. v1-Ergebnisse werden nicht hineingemischt.

R und C sind vollständige freie Modelle mit Waiting; Bewegungen und
Passagierzuordnungen sind nicht fixiert. Für R gilt der bestehende einmalige
Reservoireinsatz mit optionalen Kabinen bis Max50. C behält die festen
K39-Startpositionen und 3.074 Personen.

Die Kampagne absolvierte alle zwölf Slots in **1.806,29 Sekunden** einschließlich
gemeinsamer Vorbereitung und unmittelbarem Abschluss. Die erneute Prüfung und
Berichtserzeugung erfolgten später, ab etwa 2.951 Sekunden nach Kampagnenbeginn;
auch diese Zwischenzeit zählt zum 60-Minuten-Gesamtbudget. Es liefen keine
konkurrierenden Solverjobs und es gab in v2 keinen Suspend- oder Speicherabbruch.

### Ergebnisse aller Seeds

| Fall / Engine | Seed 0 | Seed 1 | Seed 2 | Native LB | Vergleichbare LB |
|---|---:|---:|---:|---:|---:|
| R / CP-SAT, Passagiersekunden | 368.765,817136 | 368.765,817136 | 368.765,817136 | 0 | 209.409,890299 |
| R / Hexaly, Passagiersekunden | 368.765,817136 | 368.765,817136 | 368.765,817136 | 109.032,727040 | 209.409,890299 |
| C / CP-SAT, unbediente Personen | 1.386 | 1.362 | 1.370 | 0 | 0 |
| C / Hexaly, unbediente Personen | 1.402 | 1.402 | 1.402 | 0 | 0 |

Alle Endwerte wurden aus den erhaltenen Zertifikaten erneut unabhängig geprüft.
Die Hexaly-Ereignisse bestätigen in allen sechs Versuchen die native Übernahme
des Startplans; es handelt sich also nicht lediglich um externe Fallbackwerte.
Bei R beträgt der vergleichbare Gap durchgehend **43,21 %**, bei C **100 %**.
Hexalys native R-LB ist stärker als die native CP-SAT-LB, liegt aber unter der
bereits unabhängig vorhandenen gemeinsamen globalen Schranke. Sie bedeutet
hier deshalb keinen verbesserten vergleichbaren Gap.

### Fortschritt und Plateau

- R: Beide Engines behalten in allen Seeds die UB; die vergleichbare LB ändert
  sich nicht. Hexaly verbringt pro Lauf rund 100–101 Sekunden in der nativen
  Suche nach Aufbau/Startwertvorbereitung und führt Millionen Iterationen aus.
- C / Hexaly: Rund 143 Sekunden native Suche pro Seed, jeweils U=1.402 bis zum
  Ende. Keine echte Verbesserung in einem der drei Seeds.
- C / CP-SAT: 16, 40 beziehungsweise 32 zusätzlich bediente Personen. Die letzten
  unabhängig geprüften Verbesserungen wurden nach **92,37 / 97,98 / 141,07 s**
  beobachtet. Die eigentlichen Solverereignisse liegen geringfügig davor;
  Checkpointprüfung und Abtastung erklären die Differenz.
- Seed 2 von CP-SAT verbessert sich noch kurz vor Schluss. Daher wäre die Aussage,
  alle CP-SAT-Läufe seien früh und dauerhaft festgefahren, für diese Daten falsch.
  Gleichwohl bleibt die Kapazitätsschranke null, und auch der beste neue Wert
  U=1.362 ist noch weit von vollständiger Bedienung entfernt.

![Geprüfte UB-Verläufe und globale Schranken](../../benchmarks/output/hexaly_comparison_20260911_v2/progress.png)

Die R-UB-Kurven liegen exakt übereinander. Die Grafik verwendet geprüfte
Checkpointwerte; rohe CP-SAT-Callbacks können zusätzliche Zwischenwerte zeigen,
die nicht alle als separates Zertifikat gesichert wurden.

### Beobachteter Darstellungsumfang

Der erste freie Hexaly-R-Aufbau enthält 26.120 skalare Entscheidungen, 2.650
optionale Besuchsintervalle und 15 Ressourcenlisten. Hinzu kommen 794.584
Bedingungen. Die Statistik `variables` zählt die skalaren Entscheidungen;
Intervalle und Listen müssen zusätzlich angegeben werden und dürfen bei einem
Vergleich mit CP-SAT-Variablen nicht untergehen.

728.650 Bedingungen entstehen aus paarweisen Zustandskollisionen zwischen den
2.700 Reservoir-Zustandsknoten: 91,7 % aller Bedingungen. Die Zahl folgt aus
dem unveränderten Builder und den eingefrorenen Besuchsfolgen
(`structural_review.json`). Der erste Aufbau benötigt etwa 34,5 Sekunden.
Das ist ein konkreter Darstellungsengpass, aber noch kein kausaler Nachweis für
die fehlenden Incumbent-Verbesserungen.

Das freie K39-Hexaly-Modell ist wesentlich kleiner: 12.218 skalare
Entscheidungen, 1.418 Besuchsintervalle, 20 Ressourcenlisten und 33.491
Bedingungen; der erste Aufbau benötigt 3,28 Sekunden. Ein dort beobachtetes
Plateau kann deshalb nicht allein mit der großen Reservoir-Kollisionsmatrix
erklärt werden. Interne `nbImprovingMoves` sind keine Verbesserungen der besten
unabhängig gültigen Gesamtlösung; dafür zählen ausschließlich die Zertifikate.

### Harte Einzelbudgets und fehlende Endexporte

Mehrere Prozesse erreichen das harte 150-Sekunden-Limit, bevor `result.json`
geschrieben ist. Bei den großen Hexaly-Läufen liegen bereits eine native
Endmeldung und fortlaufende Bound-Ereignisse vor; der anschließende Abbau der
Engine gehört noch zur Prozesszeit. Zwei Sekunden Abschlussreserve reichen
also nicht verlässlich. Die eingefrorene Kampagne wird dafür nicht verändert.

Der Bericht erhält `INTERRUPTED` und rekonstruiert ausschließlich belegte Werte
aus gespeicherten Artefakten. `best.json` wird erneut unabhängig geprüft;
Live-Schranken werden mit derselben konservativen Integer-Rundung wie im
jeweiligen Adapter übernommen. Ein fehlendes finales Ergebnis wird niemals
synthetisch als `FEASIBLE` oder `OPTIMAL` gespeichert. Nicht gespeicherte
Endstatistiken bleiben unbekannt. Die ursprünglichen Manifeste bleiben erhalten.

Für einen später separat beschlossenen Vergleich sollte der Runner mehr Zeit
für Prüfung, Checkpoint und Engineabbau reservieren. Das wäre eine Verbesserung
der Messzuverlässigkeit und noch keine Verbesserung der Optimierungsformulierung.

In v2 betrifft der fehlende finale Workerexport fünf Slots: R/CP-SAT/Seed 0,
C/CP-SAT/Seed 0 sowie alle drei R/Hexaly-Slots. Ihre Endpläne sind erhalten und
unabhängig geprüft; ihre Schranken stammen ausdrücklich aus Live-Ereignissen.
Die anderen sieben Slots besitzen vollständige finale Ergebnisse. Keine dieser
Unterbrechungen wird als Unzulässigkeits- oder Optimalitätsbeweis verwendet.

### Speicher und tatsächliche CPU-Nutzung

| Fall / Engine | Peak-RSS des Prozessbaums | CPU-Kernäquivalente im Mittel über den Slot |
|---|---:|---:|
| R / CP-SAT | 5,11–6,64 GiB | 6,69–8,15 |
| R / Hexaly | 5,53–5,60 GiB | 7,01–7,97 |
| C / CP-SAT | 3,38–3,59 GiB | 8,49–9,16 |
| C / Hexaly | 0,86–0,89 GiB | 10,74–11,10 |

Beide Engines erhielten zwölf Worker. Kernäquivalente sind gemessene CPU-Sekunden
geteilt durch Slot-Wachzeit einschließlich Aufbau und Abschluss, keine direkte
Aussage zur Zahl gleichzeitig rechnender Worker. Die bei Hexaly beobachteten
bis zu 24 Prozessthreads bedeuten nicht 24 angeforderte Suchworker.

### Entscheidung aus diesem Vergleich

1. **Kein Enginewechsel und kein automatischer Hexaly-Langlauf.** Hexaly erreicht
   in keiner Bestätigungsrunde ein Verbesserungskriterium. CP-SAT ist bei C in
   beiden Bestätigungsseeds um mehr als zehn bediente Personen besser. Bei R
   besteht in UB und vergleichbarer LB Gleichstand auf dem Startwert.
2. Hexaly bleibt als funktionierender experimenteller Backend erhalten. Weniger
   Speicher bei C ist ein struktureller Vorteil, aber kein Vorteil in
   Lösungsqualität oder Beweisleistung.
3. Der Versuch löst unser Forschungsproblem nicht: Das Reservoir bleibt im
   Plateau, und bei K39 liefert keine Engine eine brauchbare Kapazitätsschranke.
   Die gemessenen CP-SAT-Verbesserungen allein rechtfertigen keinen
   Optimalitätsanspruch.
4. Eine spätere Hexaly-Weiterentwicklung müsste eine konkrete Formulierungs-
   hypothese prüfen. Besonders auffällig sind die Reservoir-Kollisionsmatrix
   sowie die zusätzliche Kopplung skalarer Zeiten mit optionalen Intervallen
   und Ressourcenlisten. Dass gerade diese Kopplung die Suche blockiert, ist
   **eine Hypothese**, kein durch diesen Vergleich bewiesener Befund. Eine
   weitere unveränderte Laufzeitverlängerung testet diese Hypothese nicht.

Die Schlussfolgerung gilt für diese Formulierung, Instanzen, Seeds und 150-Sekunden-
Slots. Sie ist keine allgemeine Rangfolge der Engines. Es wurden keine weiteren
Suchläufe gestartet und keine physikalischen Regeln oder Standards verändert.

## Fundstellen

- [Vorprüfungen und Rohdaten](../../benchmarks/output/hexaly_recheck_20260911_v1)
- [Strengere historische Replay-Prüfung](../../benchmarks/output/hexaly_recheck_20260911_v1/historical/gate.json)
- [Separate Vergleichszulassung](../../benchmarks/output/hexaly_recheck_20260911_v1/admission/hexaly.json)
- [Unterbrochener Vergleich v1](../../benchmarks/output/hexaly_comparison_20260911_v1)
- [Neuer Vergleich v2](../../benchmarks/output/hexaly_comparison_20260911_v2)
- [Erneut geprüfter maschinenlesbarer Bericht](../../benchmarks/output/hexaly_comparison_20260911_v2/campaign_reviewed.json)
- [Fortschritt, Zeiten und CPU/RSS je Lauf](../../benchmarks/output/hexaly_comparison_20260911_v2/progress_analysis.json)
- [Exportierbare Vektorgrafik](../../benchmarks/output/hexaly_comparison_20260911_v2/progress.svg)
- [Plan und Vergleichskriterien](../plans/hexaly_recheck_20260911.md)
- [Semantiktests](../../tests/test_hexaly_semantics.py)
