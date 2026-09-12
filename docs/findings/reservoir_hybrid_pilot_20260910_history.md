> Historischer Zwischenstand; aktuelle Entscheidung im [Abschlussbericht](reservoir_hybrid_pilot_20260910.md).

# Reservoir-Hybrid: Implementierung und früher Größenbefund

Stand 10.09.2026. Grundlage ist der
[gestufte Plan](../plans/reservoir_hybrid_reassessment_20260910.md).
**Aktueller Befund: Mit durchgängigen Passagier-Zeitmomenten und Verfeinerung
steigt die globale LB von 109032.72704 auf 209409.89030.** Die ursprüngliche
Größenbewertung ist widerlegt. Der geprüfte Fahrplan bleibt bei 368765.821408;
der nachgewiesene Gap sinkt von etwa 70.43 % auf 43.21 %.
S0–S3 und die S4-Reparaturbausteine sind implementiert. S5 und die Wiederverwendung
S6/S7 bleiben an ihre nachfolgenden Erfolgskriterien gebunden.

## Zeitmomente: der erste zusätzliche globale Bound

Die Implementierung ist in [der technischen Referenz](../reference/reservoir_hybrid.md)
einschließlich Projektionsargument und Abgrenzung zum ursprünglichen Modell erklärt.
Alle Änderungen sind experimentell auswählbar, keine Legacy-Standards wurden ersetzt.

| Variante auf R | Variablen / Zeilen | Modellbau | LP-Suche | Gültige LB |
|---|---:|---:|---:|---:|
| Mindestfahrzeit-Koeffizienten + Ressourcen | 85001 / 19359 | 9.84 s | 2.46 s | 109032.72704 |
| Zeitmomente, Bewegung/Kapazität | 236107 / 546293 | 4.81 s | 11.67 s | 176187.38245 |
| Zeitmomente + Ressourcen, Dual-Simplex | 236107 / 547154 | 14.38 s | 130.13 s | 176187.38245 |

Ergebnisordner: `reservoir_hybrid_ride_bounds_20260910_v1`,
`reservoir_hybrid_time_moments_20260910_v1` und
`reservoir_hybrid_moments_dual_20260910_v1` unter `benchmarks/output`.
Die Ressourcenvariante mit automatischer konkurrierender LP-Methode wurde zuvor
bei gemessenen 4351328256 RSS-Bytes kontrolliert beendet. Sie lieferte keinen neuen
LP-Bound. Der anschließende Dual-Simplex-Lauf benötigte maximal rund 1.785 GB,
148.49 s im Runner beziehungsweise 149.83 s inklusive Prozessstart und Aufsicht.

Die Ressourcenfenster erhöhen mit Zeitmomenten den Bound auf R nicht mehr. Deshalb
nutzt die folgende Verfeinerung das schnellere Bewegungs-/Kapazitätsprofil.
Der gemeinsame Kontrollplan erfüllt alle 547154 Ressourcenmodellzeilen mit maximal
6.4e-12 numerischer Verletzung und projizierten Kosten 368765.8214080001.
Die Ganzzahligkeit der Originalpassagiere wurde dabei nicht verändert; das neue LP
ist weiterhin eine kontinuierliche notwendige Relaxation.

## Begrenzte Verfeinerung

[`reservoir_hybrid_refine_20260910_v1`](../../benchmarks/output/reservoir_hybrid_refine_20260910_v1)
enthält den kompletten, überwachten Lauf, alle Partitionen und Projektionsnachweise.

| Runde | Variablen | Native LP-Suche | Kumulative Zeit | Bewiesener LP-Wert / Ledger |
|---|---:|---:|---:|---:|
| 0 | 236107 | 9.19 s | 17.74 s | 176187.38245 |
| 1 | 252164 | 12.09 s | 38.97 s | 205163.79223 |
| 2 | 274480 | 14.36 s | 63.40 s | 209409.89030 |
| 3 | 304239 | 220.11 s | 294.92 s | kein neuer LP-Nachweis; Ledger bleibt 209409.89030 |

Die letzte Runde endet mit Gurobi-Status 9 (Zeitlimit). Ihr Rückfallwert
109032.72704 ist **keine Verschlechterung des gültigen Gesamtbounds**.
Der Ledger behält die beste vorher abgeschlossene Relaxation. Die historische
Ausgabebegründung `no_splits` war hier missverständlich: ohne optimalen LP-Status
werden keine neuen Splits vorgeschlagen. Der Code meldet dafür inzwischen
`lp_status_9` und enthält zusätzlich die Herkunft des besten Bounds.

Gesamtlauf inklusive Aufsicht 296.53 s, Peak-RSS 3.378 GB. G3 ist erfüllt:
33222.50785 zusätzliche LB-Einheiten gegenüber dem Stufenstart, bei geforderten
1925.78439 und weniger als doppelter Modellgröße. Das ist **kein Konvergenzbeweis**:
Zeitverfeinerung beseitigt weder jede Passagiermischung noch die Ganzzahligkeitslücke.
Der letzte große Suchabschnitt liefert keinen weiteren nachgewiesenen Fortschritt.

## Kleine CP-Reparaturen und Startdiagnose

[`reservoir_hybrid_repairs_20260910_v1`](../../benchmarks/output/reservoir_hybrid_repairs_20260910_v1):
zwölf eingefrorene Nachbarschaften, ursprünglicher Seed in jedem Versuch,
je zehn Sekunden äußerer Wandzeitrahmen und acht Sekunden Runnerbudget.
Alle sechs Drei-Einsatz-Versuche liefern eine native zulässige Lösung, alle sechs
Sechs-Einsatz-Versuche enden UNKNOWN. Kein Versuch verbessert die UB.
Der Lauf dauert insgesamt 93.19 s und verfehlt zunächst G4.

Die lokalen Modelle haben rund 5500–12500 Variablen. Die restlichen 32 beziehungsweise
35 Einsätze liegen nur als konstante Außenkalender und feste Passagierzuordnung vor.
Alle Startwerte einschließlich Hilfsgrößen sind gesetzt; sechs geöffnete Einsätze
plus zwei Zusatzslots ergeben zum Beispiel 12459 Variablen und 12459 Hintwerte.

Die unabhängige Diagnose in `reservoir_hybrid_repair_probes_20260910_v1` zeigt:
Mit allen Startwerten fixiert wird das Sechs-Einsatz-Modell in 0.104 s optimal
bestätigt. Der Seed ist also im Modell enthalten. Bei normaler Suche benötigt
CP-SAT dagegen rund 12.68 s bis zum `complete_hint`-Incumbent. In längeren
28-s-Diagnosen erhalten beide Größen den Seed, finden aber keine Verbesserung.
Diese fixierte Diagnose ist kein Optimierungsgewinn und zählt nicht für G4.

In `reservoir_hybrid_repair_no_presolve_20260910_v1` wird ausschließlich Presolve
abgeschaltet. Die gleichen vollständigen Startpläne werden nach 0.383/0.741 s
bestätigt; beide Größen liefern im ursprünglichen kurzen Rahmen FEASIBLE, jedoch
noch keine bessere UB. Das motiviert eine getrennte Wiederholung der zwölf
eingefrorenen Nachbarschaften mit dieser Einstellung. Sie verändert keine
physikalischen Bedingungen und setzt keine Fahrplanentscheidungen fest.

Die nachfolgenden Abschnitte dokumentieren die früheren Versuche historisch;
deren negative Boundaussage wurde durch die Zeitmoment-Variante überholt.

## Nachtest ohne künstliche Größenlimits

Ergebnisordner:
[`reservoir_hybrid_uncapped_20260910_v1`](../../benchmarks/output/reservoir_hybrid_uncapped_20260910_v1).
Der Aufruf ergänzt `--no-size-caps` an der Gate-Kampagne. Damit entfallen sowohl
Variablen- als auch Zeilenlimits; 300 s pro Versuch und 4 GiB RSS bleiben erhalten.
Die Standardlimits anderer Aufrufe bleiben kompatibel. Im einzelnen Runner
deaktivieren `--max-variables 0 --max-rows 0` die Größenlimits, intern jeweils `None`.

| Profil | Variablen | Zeilen | LP-Suche | Gesamt im Runner | Roher optimaler LP-Wert |
|---|---:|---:|---:|---:|---:|
| `arrival_only` | 20 | 0 | 0.0007 s | 0.334 s | 109032.72704 |
| `movement_capacity` | 85001 | 18498 | 0.435 s | 1.723 s | 2880.00 |
| `resource_windows` | 85001 | 19359 | 2.140 s | 12.565 s | 32228.57143 |

Die gesamte Sequenz inklusive All-Stop-Replay und Prozessstarts dauerte 24.05 s.
Der Ressourcenbuilder benötigt 9.54 s; die Netzvorbereitung zusätzlich 0.20 s.
Peak-RSS beträgt 435 MB für Bewegung und 735 MB für Ressourcen, jeweils dezimale MB.
Die 861 Ressourcenfensterzeilen erhöhen die Nichtnullkoeffizienten von 232914
auf 633862. Alle drei LPs wurden optimal gelöst, kein Zeit- oder Speicherabbruch.

Der historische Originalplan erfüllt beim Replay sämtliche 18498 beziehungsweise
19359 Zeilen, jeweils mit maximaler Verletzung null. Sein projizierter LP-Wert
ist 327840.00 gegenüber den exakten 368765.821408. Das ist zusätzlich zur kleinen
Enumeration ein erfolgreicher großer Projektionscheck, kein vollständiger Beweis
für alle denkbaren Pläne.

**Die Ressourcenbedingungen wirken**, denn sie erhöhen den rohen LP-Wert von
2880 auf 32228.57. Dieser bleibt jedoch unter dem analytischen Bound 109032.72704.
Veröffentlicht wird dessen Maximum mit dem LP-Wert: somit **kein LB-Fortschritt**.
Die geprüfte UB bleibt 368765.821408. Das Nutzengate 135006.0364768 ist verfehlt.

Die anonymen Zeit-Zellen erlauben optimistisch unterschiedliche lokale Zeiten
aufeinanderfolgender Bewegungen sowie Passagierwechsel zwischen Fahrzeugflüssen.
Dadurch bleiben ganze Reisezeitketten wesentlich zu locker gekoppelt. Die
analytischen Mindestfahrzeiten werden aktuell separat als globaler Bound geführt,
nicht als gruppenweise Kopplungszeilen in diesem LP. Das erklärt, warum die rohen
Bewegungsprofile trotz zusätzlicher Modellierung unter dem analytischen Wert
liegen können. Eine Ursacheanalyse der konkreten LP-Flüsse steht noch aus;
welcher dieser Relaxationseffekte dominiert, wurde nicht gemessen.

Mehr Laufzeit schließt hier nichts weiter: Gurobi hat das jeweilige LP bereits
optimal gelöst. Ein möglicher nächster Formulierungstest wäre die Verknüpfung
der gruppenweisen Mindestfahrzeiten und der durchgängigen Zeitfortschreibung
mit den Flüssen. Das ist eine Empfehlung, noch keine implementierte Verbesserung.
Die frühere Empfehlung, zuerst wegen Größe Passagierindizes zu reduzieren, wird
durch diesen Nachtest **nicht als vorrangig gestützt**.

44 Tests bestehen nach Ergänzung eines vollständigen Runner-Tests ohne Größenlimits;
die bisherigen Grenz- und Abbruchtests bleiben erhalten. Die nachfolgenden
Abschnitte dokumentieren den ursprünglichen begrenzten Versuch historisch.

## Referenz und Ergebnisse

Unveränderte Single-Use-Domäne R: Max50, Waiting bis 1200 s, 1280 Personen,
300/1200/300 s Anlauf/Service/Räumung, Mikrosekundenauflösung.
Fingerprint: `ea2b46d53da6f34147bfd5a9c1a635116e89eb47afd84cfd036b56971376ac65`.

| Referenz | Passagiersekunden | Bedient | Kabinen | Nachweis |
|---|---:|---:|---:|---|
| Historischer geprüfter Skip-Stop-Plan | 368765.821408 | 1280 | 38 | Originalvalidator, Checkpoint-Roundtrip |
| Neu erzeugter analytischer All-Stop-Plan | 371911.194288 | 1280 | 38 | Originalvalidator; CP-SAT beweist optimale ganzzahlige Zuordnung bei festgehaltener Bewegung |

Das All-Stop-Ergebnis ist **kein globales All-Stop-Optimum**. Die frühere
Fixed-K-All-Stop-Referenz 399287 gehört nicht zu dieser Vergleichsdomäne.
Die Referenzwerte werden aus Zertifikaten gelesen, nicht als Solverziel eingesetzt.

Maßgebliches Ergebnisverzeichnis:
[`reservoir_hybrid_gates_20260910_v2`](../../benchmarks/output/reservoir_hybrid_gates_20260910_v2).
`v1` bleibt erhalten; `v2` wiederholt ausschließlich den kurzen Gate-Test nach
Ergänzung der Aufschlüsselung der Variablen beim Größenabbruch. Keine verlängerte Suche.

| Profil | Variablen | Zeilen | Runnerzeit ohne Python-Start | Ergebnis |
|---|---:|---:|---:|---|
| `arrival_only` | 20 | 0 | 0.327 s | LP optimal, LB 109032.72704000073 |
| `movement_capacity` | >50000 benötigt | 3374 bisher | 0.590 s | kontrollierter Aufbauabbruch |
| `resource_windows` | >50000 benötigt | 3374 bisher | 0.604 s | kontrollierter Aufbauabbruch |

Die letzten beiden Zahlen sind **keine vollständigen Modellgrößen**. Beim Abbruch
waren jeweils 9263 Bewegungs-, 26 Dispatch-, 159 Rückkehr- und 40552
Passagierflussvariablen angelegt. Weitere Passagierflüsse fehlen; Kapazitäts- und
Ressourcenfensterzeilen werden erst danach gebaut. Daher wurde auf R noch keine
Wirkung der Ressourcenfenster gemessen. Ein angefangener Gurobi-Builder ist kein
zulässiges verkleinertes Ersatzmodell und wurde nicht optimiert.

Die native LP-Suche des Kontrollprofils dauerte rund 0.0008 s. Sein Unterschied
von circa 7e-10 zur analytischen LB ist Rundung, kein Fortschritt. Die beiden
anderen Profile haben keine native Suchzeit, Erstlösung, Verbesserungskurve oder
Plateauphase. UB bleibt der übernommene geprüfte Plan, LB bleibt 109032.72704.
Das Weiterbauziel wäre **135006.0364768** gewesen.

Gemessener Prozess-Peak-RSS: rund 0.645 GiB für den All-Stop-Replay,
0.135 GiB für `arrival_only`, 0.158/0.156 GiB für die abgebrochenen Builder.
Speicher war nicht der Abbruchgrund. Beide Gate-Durchgänge zusammen benötigten
rund 25 s einschließlich Prozessstart und Referenzreplay, weit unter 90 Minuten.
`campaign.json` enthält die tatsächlichen Zeiten des überwachenden Elternprozesses.

## Was implementiert wurde

Alle neuen Solverbausteine liegen getrennt unter
[`optimization/ddd/reservoir_hybrid`](../../src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_hybrid).
Bestehende Solverstandards wurden dafür nicht geändert.

| Datei | Verantwortung |
|---|---|
| `domain.py` | Originaldomäne aus historischem Manifest rekonstruieren, unveränderten Fingerprint und Zertifikate prüfen; nur Single-Use |
| `arrival_curves.py` | Ganzzahlige Ankunftskostenidentität, Intervallunterbewertung, Partition und deterministische Verfeinerungsoperation |
| `certificates.py` | geprüfte UB und domänengebundene globale LB getrennt von lokalen Ergebnissen halten |
| `bound_domain.py` | anonyme Besuchs-/Zeit-Zellen, lokale STOP/SKIP/Waiting-Bereiche, sichere Erreichbarkeit und Ressourcen-Minimalüberlappung |
| `bound_model.py` | drei LP-Builderprofile, gemeinsame Sitzkapazität, Projektionsprüfung jeder Modellzeile, Größenlimits und vorsichtiger Boundexport |

Der [Runner](../../benchmarks/run_ddd_reservoir_hybrid.py) delegiert an
[`benchmarking/ddd_reservoir_hybrid.py`](../../src/ropeway_skip_stop_optimization/benchmarking/ddd_reservoir_hybrid.py).
Die [Gate-Kampagne](../../benchmarks/run_reservoir_hybrid_gate_campaign.py) führt
Replay und drei Profile sequenziell aus, überwacht Wandzeit und RSS und startet
keine späteren Stufen. Der All-Stop-Replay ist auf die eingefrorene
Fünf-Stationen-Referenz ausgerichtet; er ist kein allgemeiner neuer Seedgenerator.

Aufruf aus dem Repository:

```sh
.venv/bin/python benchmarks/run_reservoir_hybrid_gate_campaign.py \
  --resume-checkpoint benchmarks/output/model_correctness_audit_20260910/checked_incumbent.json \
  --output-dir benchmarks/output/reservoir_hybrid_new_unique_run
```

Vorhandene Ausgabeordner werden abgelehnt. Jede Teilmessung schreibt Konfiguration,
Domäne, Python-/Gurobi-Versionen, Hashes der Python-Projektquellen, geprüften Seed,
Partition, Ankunftskosten, Ereignisse und Ergebnis. Vollständig gebaute Modelle
schreiben zusätzlich ihre Zeilenprojektion und native Solverlogs.
Bei R sind deshalb nur für `arrival_only` alle Projektionszeilen geprüft; die
größeren Modelle existierten nicht vollständig. Ihre großen Replays bleiben offen.

`phase=repair/hybrid` und `lifecycle=reusable` werden explizit abgelehnt.
Die physikalischen Parameter stammen bisher vollständig aus dem Checkpoint;
eine neue frei parametrierbare Reservoir-CLI ist nicht vorgetäuscht.

## Formulierung und Korrektheitsargumente

Die Kabinenlabels entfallen im LP. Ein Knoten enthält Besuchsindex und Zeitintervall;
jeder reale Einsatz bildet einen zusammenhängenden Dispatch-Rückkehr-Pfad ab.
Besuchsindizes verhindern einen freien Kreislauf innerhalb derselben Zeit-Zelle.
Sie legen keine physische Kabinenreihenfolge fest. STOP und SKIP bleiben wählbar,
Waiting wird durch lokale Bereiche statt einzelner Mikrosekundenwerte abgebildet.

Passagierflüsse werden über Kabinen hinweg geteilt, enthalten aber weiterhin
Nachfragegruppe und Einstiegsbesuch. Der kanonische Generator erlaubt nur das
erste Erreichen des jeweiligen Ziels. Flusserhaltung, gemeinsamer Sitzplatzverbrauch
und getrennte Ausstiegskapazität bilden jeden Originalplan ab. Umgekehrt darf das
LP innerhalb einer Zelle zwischen anonymen Fahrzeugflüssen wechseln und lokal
unterschiedliche Zeitrealisierungen verwenden. Seine Flüsse sind somit keine
direkt exportierbaren Fahrpläne. Diese verbleibende Passagierindexierung ist der
gemessene Größenengpass; bereits Kabinenlabels zu entfernen genügt hier nicht.

Explizite kumulative Y-Variablen werden algebraisch eliminiert: Ausstiegsflüsse
tragen ihre optimistisch gutgeschriebene Ankunftszeit relativ zur konstanten
Nichtbedienungskostenbasis. `arrival_only` eliminiert zusätzlich die frei optimierbare
Zeitentscheidung und reduziert sich auf die analytische Mindestfahrzeit je Gruppe.
Das erklärt seine 20 Variablen ohne Zeilen. Bei Bewegung können optimistische
lokale Ankünfte noch früher sein; veröffentlicht wird stets das Maximum aus
vollständig bewiesenem LP-Wert und analytischer LB.

Für Ressourcen wird der zulässige lokale Bereich mit `u=t+wait` als Rechteck
plus Diagonalstreifen beschrieben. Null-Wait und zulässiges positives Waiting
bilden getrennte Teilbereiche. `min(clear,R)-max(enter,L)` ist konkav in `(t,u)`;
sein Minimum liegt an einem Polygoneckpunkt. Das Maximum mit null kommutiert mit
der Minimumsbildung. Alle Eckpunkte haben bei diesen ganzzahligen Grenzen
ganzzahlige Tickkoordinaten. Das Minimum über den kontinuierlich relaxierten Bereich
ist eine sichere Untergrenze auch für die ursprünglichen Waiting-Schritte.
Bedingt fehlende Ressourcen liefern vorsichtshalber null; Schutzzeiten hinter
Betriebsende werden nicht abgeschnitten. Fensterbedingungen sind notwendig,
erzwingen aber noch nicht jede einzelne Konfliktfreiheit.

**Korrektur des Plantextes:** In der optimistischen Intervallsumme zählt
`Y(b^-)` nur Ankünfte **streng vor** Intervallende b. Eine Ankunft exakt b wird
bei b und nicht am Beginn des vorherigen Intervalls gutgeschrieben. Auf R ergeben
sich 368765821408 exakte Tickkosten und 328800000000 Intervall-Tickkosten bei
60-s-Grenzen. Werden sämtliche tatsächlichen Ankünfte als Grenzen eingefügt,
reproduziert die Summe auf den getesteten Plänen die exakten Kosten.

Ein LP-Primalwert nach Timeout ist kein globaler LB. Der Optimizer exportiert den
LP-Wert ausschließlich bei `OPTIMAL`, sonst nur die analytische Schranke.
Der Ledger prüft Typ, Domäne, Endlichkeit und Konsistenz mit der validierten UB;
die mathematische Gültigkeit bleibt Verantwortung des jeweiligen Bound-Producers.
Die Ergebnisse sind numerische Gurobi-Zertifikate innerhalb der vorhandenen
Toleranz, keine rational nachgerechneten Beweise.

## Tests und offene Pflichten

43 Tests bestanden:

```sh
.venv/bin/pytest -q tests/test_reservoir_hybrid.py \
  tests/test_reservoir_hybrid_runner.py \
  tests/test_optimization_ddd_reservoir_cp_sat.py \
  tests/test_benchmarking_ddd_reservoir_cp_sat.py
```

Neue Tests umfassen vollständige kleine K1-Planenumeration mit Waiting und ohne,
LP-Projektion jedes enumerierten Plans, Übereinstimmung des Originaloptimums mit
CP-SAT, K2-Belegung mit Aus-/Einstieg am selben Besuch, K1/K2/K4-Optimalitätskontrollen
mit optionaler Flotte, Releases und positive Waiting-Freigabe, H-Grenzen,
Eckpunktminima gegen direkte Enumeration für alle vier Waitingkoeffizient-Paare,
Checkpoint-Roundtrip sowie Fehler bei fremden/lokalen Bounds. Größenabbruch erhält
den validierten Seed. Überwachte Zeit- und RSS-Abbrüche töten den Worker und
erfinden kein Solverzertifikat. Ruff-Prüfung bestanden.

Noch **nicht vollständig erfüllt** sind die breite K2-Vollenumeration, eine eigene
gezielte Bypass-Überholungs-/Zwei-Ressourcen-Testmatrix des neuen LPs, der besondere
Fixed-K-Horizont-Adaptertest und allgemeine Koeffizientenbereichsprüfungen für
beliebig große Fremdinstanzen. Die Reservoir-Referenz verwendet den unveränderten
kanonischen Besuchsgenerator; der Fixed-K-Generator wurde nicht verändert.
Die Korrektheitsstufe ist damit nicht pauschal als vollständig abgenommen zu lesen.
Große Optimierung der Bewegungs-/Ressourcenprofile wurde ohnehin nicht erreicht.

## Frühere Entscheidung vor dem Nachtest

Kein neuer UB-Fortschritt und kein neuer nutzbarer LB wurden gefunden.
**Länger laufen lassen hilft bei diesem Befund nicht:** Der Aufbau wird absichtlich
vor der Suche beendet. Die Größenlimits wurden nicht erhöht, Waiting und Domäne
nicht beschnitten und der Standard nicht gewechselt.

Vor einem erneuten globalen Ausbau müsste insbesondere der Passagierfluss kompakter
werden, etwa durch das Zusammenfassen weiterer Einstiegs-/Zielklassen mit explizitem
Projektionsnachweis. Das wäre eine neue Formulierungsänderung mit erneutem G2-Test;
es ist noch keine bewiesene Verbesserung. Alternativ bleibt der begrenzte S4-Test
für bessere gültige Fahrpläne möglich, löst aber allein das globale LB-Problem nicht.
S3/S5 sowie Reservoir-Wiederverwendung werden aus diesem negativen Gate nicht
automatisch gestartet. Die mathematischen Literaturbezüge stehen unverändert im
verlinkten Plan; die hier implementierte Kombination ist projektspezifisch.
