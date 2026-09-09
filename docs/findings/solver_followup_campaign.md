# Bestehende Solver: Folgekampagne vom 9. September 2026

Umsetzung des [beschlossenen Plans](../plans/solver_followup_campaign.md). Dieser Bericht wird mit den abgeschlossenen Versuchen ergänzt. Historische Rohdaten bleiben unverändert.

## Abgesicherte Grundlage

- Neuer vollständiger `fixed_k_problem_v2`-Fingerprint einschließlich Ressourcen-/Routenwerten, Kapazität, Nachfrage, Kandidaten und Horizontvertrag. `legacy_fingerprint` dient nur der expliziten Wiedererkennung historischer primaler CP-Pläne bei zusätzlichem vollständigem Manifestabgleich und erneuter Prüfung.
- Root-CG-LB-Import verlangt vollständiges Manifest, passenden Hash, `certificate_valid=true`, gültigen Status und `FIXED_K_GLOBAL`-Scope. Alte unvollständige Zertifikate werden abgewiesen. Root-CG schreibt die neue Identität mit.
- Der Primal-Seed-Evaluator erhält die kanonische Nachfrage/Kandidaten des konkreten Problems. Das verhindert eine unbemerkte Rückkehr zur Standardnachfrage bei Profilvarianten.
- CP schreibt Ereignisse während des Laufs als JSONL, ergänzt Runnerzeit und Prozess-Peak-RSS. Extraktion, Callbackvalidierung und Eventzustellung werden separat ausgewiesen; sie sind innerhalb der Solvezeit zu interpretieren.
- 140 Tests bestanden im breiteren gezielten Lauf; nach der zusätzlichen Korrektur der Nachfrageübergabe bestanden 68 betroffene Tests. Keine Änderung der Stop-/Skip-/Waiting-Formulierung für die neue Laufzeitbaseline.

## Erneute unabhängige Prüfung historischer Fahrpläne

Alle festen Integer-Passagier-IPs melden OPTIMAL; das ist jeweils ein Beweis bei **fixierter Bewegung**. Frühere globale Schranken werden nicht importiert.

| Bewegung | Aktuell bestätigte Kosten | Bedient / unbedient |
|---|---:|---:|
| K20 All-Stop | 635.519,998080 | 1280 / 0 |
| K20 Skip-Stop | 525.730,908160 | 1280 / 0 |
| K38 All-Stop | 399.287,271408 | 1280 / 0 |
| K39 No-Wait | 1.262.099,935264 | 416 / 864 |
| K39 Waiting, bester Reservierungsseed | 1.007.532,083464 | 1112 / 168 |

Auch die explizite Übertragung nur der K38-All-Stop-Bewegung in die freie Skip-Stop-Waiting-Domäne reproduziert 399.287,271408. Alle geprüften Pläne erfüllen den vereinbarten endlichen Vertrag. Fortsetzung wird nicht behauptet.

Messdaten und kopierte Originalquellen: `benchmarks/output/solver_followup_20260909/frozen/`, jeweils `source.json`, `validation.json`, `problem_manifest.json` und neu zertifizierter `cp_seed.json`. `headline_validation.json` enthält die gemeinsame Übersicht; `software_snapshot.json` Quellcodehashes, Paketversionen, Betriebssystem und damaligen Gitstatus. Reproduktion: `benchmarks/prepare_solver_followup.py`.

## Laufende bzw. folgende Experimente

1. K39 Waiting 1800 s, Produkt, acht Worker, Seed 0, eingefrorener Waiting-Bestseed.
2. Zwei 600-s-Wiederholungen mit Seeds 1 und 2 und derselben Startlösung.
3. K38 Skip-Stop Waiting 600 s aus dem All-Stop-Seed.
4. Kleine K20-Nachfragematrix mit gelabeltem No-Wait-Arc-Flow.
5. Optional anonymes No-Wait-K39-Arc-Flow 1800 s mit passendem CP-No-Wait-Seed.

Abgeschlossene Ergebnisse folgen hier mit klar getrennten Roh-CP-Werten, unabhängiger Assignment-Nachoptimierung und globalen Bounds.

## Abgeschlossener 30-Minuten-Lauf K39 Waiting

Commit der Solverbaseline: `192b9b7`. Unveränderte Produktformulierung, acht Worker, Seed 0, eingefrorener Hint 1007532,083464. Gesamtzeit 1800,517 s. Finale geprüfte Kosten **874705,109680**, **1280 bedient / 0 unbedient**, globale native LB **131762,776090**, Gap **84,94 %**. Die unabhängige feste Passagier-IP bestätigt genau denselben Wert und meldet OPTIMAL für diese Bewegung; kein globaler Optimalitätsbeweis.

Kostenverbesserung gegenüber Seed 13,18 %, gegenüber dem Zustand nach zehn Minuten 4,95 %. Die Physik-/Nachfrage-/Kandidatendomäne ist gegenüber dem früheren K39-Waiting-Fall unverändert. Der stärkere Hint und die längere Zeit sind getrennt von einem Formulierungsgewinn zu interpretieren.

Zeitanteile: Vorbereitung 3,950 s, integrierter Aufbau 1,066 s, Solveraufruf 1795,000 s, abschließende Prüfung/Checkpoint 0,241 s. Callback-Extraktion 4,998 s und Callback-Validierung 10,427 s liegen **innerhalb** des Solveraufrufs; Eventzustellung insgesamt 0,050 s. Modell 51076 Variablen / 106782 Constraints vor Presolve, 27978 Variablen nach Presolve, Suchstart nach 22,10 Solver-s. Peak-RSS 4090,8 MB.

Die zusätzliche unabhängige Nachoptimierung/Prüfung benötigt nach erneuter Instanzvorbereitung etwa 0,98 s; sie gehört nicht zum 1800-s-Hauptbudget.

| Runnerzeit | Beste gemeldete UB | Globale Solver-LB |
|---|---:|---:|
| 60 s | 1005329.684 | 0.000 |
| 120 s | 997888.938 | 50501.851 |
| 300 s | 993368.027 | 50503.613 |
| 600 s | 920283.208 | 74872.837 |
| 900 s | 907548.975 | 94697.996 |
| 1200 s | 905617.105 | 113344.002 |
| 1500 s | 883803.910 | 131580.501 |
| Ende | 874705,110 | 131762,776 |

Zwischenwerte sind Solverberichte; finale Bewegung und Zuweisung wurden unabhängig geprüft. Ergebnisse unter `benchmarks/output/solver_followup_20260909/k39_waiting_1800s_seed0/`.

## Profilintegration geprüft

94 Tests bestehen nach Ergänzung der kleinen Nachfragefallklasse, kanonischer Nachfrageübergabe auch in der Arc-Flow-Abschlussprüfung und Erhalt individueller Nachfrage beim Waiting-Übergang. Dieser Testlauf erfolgte erst nach Ende des langen CP-Laufs. Für die Standardnachfrage bleibt die erzeugte CP-Domäne gleich; die nächsten Wiederholungen müssen denselben vollständigen Domänenhash und dasselbe Modell wie der erste Lauf ausweisen.
