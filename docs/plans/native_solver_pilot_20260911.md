# Native Solver-Pilot: Hexaly, Z3 und temporale Planung

## Vertrag

Umgesetzt wird der im Chat freigegebene Drei-Ansätze-Plan: Fixed-K mit festen
Starts und Single-Use-Reservoir, STOP/SKIP, Exit-Waiting auf dem ursprünglichen
Tickraster, ganzzahlige Direktbeförderungen, getrennte Ziele `journey_time` und
`unserved`. Keine eigene Suche, kein LNS-Controller, kein automatischer
Standardwechsel. Wiederverwendung einer bereits zurückgekehrten Kabine bleibt
außerhalb dieser Reservoir-Domäne.

## Implementierung und Zwischenprüfungen

1. Gemeinsame unveränderliche Domänenvorbereitung mit ursprünglichen Ride-IDs,
   Zeitgrenzen, Ressourcen und getrennten Lebenszyklen. Eigenständiger
   Modell-Fingerprint; ursprünglicher physischer Fingerprint bleibt erhalten.
2. Z3: native `Optimize`-Suche, Integer-Ticks, logische Ressourcenreihenfolgen,
   Integer-Passagiere und exakte binäre Linearisierung variabler Zeitprodukte.
   Bei diagnostisch festem Fahrplan sind die Zeitprodukte bereits linear.
3. Hexaly: native Besuchsintervalle und Ressourcenlisten, integrierte
   Passagiermengen. Ausführung und Freigabe verlangen eine vorhandene Lizenz.
4. TemPEST/Patty: eingefrorene veröffentlichte Quellen, isolierte Umgebungen,
   ausführbare Gegenbeispiele zur unveränderten Zeit-/Aktionssemantik.
5. Bestehende unabhängige Zertifikate für Extraktion, Hints und Replays;
   Vergleich kleiner enumerierbarer Optima mit CP-SAT/Gurobi, historische
   K38-/K39-/Reservoir-Replays, anschließend freie Passagieroptimierung bei
   festem Fahrplan. Timeout ist kein Korrektheits- oder Unzulässigkeitsbeweis.
6. Gemeinsamer CLI-Runner, Prozessbaumüberwachung, Quellenkopien, persistierte
   Fortschrittsereignisse und getrennte Referenz-/native Ergebniswerte.

## Erste Kampagne

Harte gemeinsame Obergrenze: 3.600 Sekunden einschließlich Vorbereitung,
Modellbau, Validierung und Auswertung. Implementierung/Korrektheitsprüfungen
werden separat protokolliert. Kein konkurrierender Solverjob.

| Abschnitt | Slots | Budget |
|---|---:|---:|
| R und C, CP-SAT Legacy/Hexaly/Z3, drei Wiederholungen | 18 × 150 s | 45 min |
| Zwei kleine Betriebsformen je temporalem Planer | 4 × 90 s | 6 min |
| Vorbereitung und Abschluss | — | 9 min |

R: Max50, Waiting 1.200 s, 1.280 Personen, Kostenreferenz
368.765,817136 Passagiersekunden. C: ursprüngliche Fixed-K39-Starts, Waiting,
3.074 Personen, Referenz U=1.402. K38 mit U=315 dient der Regression.

Jeder Slot enthält Aufbau und Abschluss. Ohne bestandene Freigabe wird der Slot
ausgewiesen und nicht gestartet; die eingesparte Zeit wird nicht umverteilt.
Eine fehlende Hexaly-Lizenz ist keine bestandene Prüfung. Die großen Z3-Replays
und die Reproduktion der Passagieroptima werden separat ausgewiesen; ungeklärte
Passagieroptima halten die strenge Kampagnenfreigabe zurück.

CP-SAT und Hexaly erhalten zwölf angeforderte Worker, Z3 verwendet die native
einthreadige Optimize-Konfiguration. Reihenfolge rotiert; Z3-Wiederholungen
werden nicht als eigenständige Solver-Seeds ausgegeben. Alle Engines erhalten
denselben geprüften Startplan. Übernahme zählt nicht als Verbesserung.

Eine Empfehlung verlangt Bestätigung in beiden zusätzlichen Wiederholungen:
0,1 % bessere Kosten, zehn zusätzlich bediente Personen oder einen Prozentpunkt
kleineren vergleichbaren Gap ohne schlechtere UB. Nach Timeout darf ein
bekannter Fahrplan als Referenz erhalten bleiben, aber nicht als native Lösung
ausgegeben werden. Bestehende globale Schranken werden nur mit passendem
Domänen-Fingerprint und gemeinsam für alle Engines verwendet.

## Nachweise und Einstiegspunkte

- [Backend-Vertrag und Aufrufe](../reference/native_solver_backends.md)
- [Ergebnisse und offene Punkte](../findings/native_solver_pilot_20260911.md)
- [Recherche mit Quellen](../research/ropeway_published_solver_alternatives_20260911.md)

Die geplanten sechs Stationen sind der folgende Anwendungstest. Dieser Pilot
ersetzt weder die noch offenen Szenariodefinitionen noch die Untersuchung der
Nachfragefamilien und beantwortet die Thesis-Fragen nicht automatisch.
