# Native Solver-Pilot: Implementierung, Prüfungen und Ergebnis

Stand: 11. September 2026. **Es gibt noch keinen nachgewiesenen besseren Solver.**
Z3 und Hexaly haben getrennte native Backendpfade erhalten. Z3 besteht die
kleinen Modelltests und reproduziert historische Zertifikate, scheitert bislang
aber an der freien Passagieroptimierung der großen festen Fahrpläne innerhalb
des Prüfbudgets. Hexaly bleibt bis zur Lizenz und den anschließenden Tests
ungeprüft. Die direkten temporalen Übersetzungen haben die Semantikfreigabe
nicht bestanden.

Die freigegebene Kampagne wurde deshalb als CP-SAT-Kontrolle mit sechs Läufen
ausgeführt. Nicht freigegebene Slots wurden nicht gestartet und ihre Zeit nicht
umverteilt. **Die zwölf ausgefallenen Hexaly-/Z3-Läufe sind keine verlorenen
Solververgleiche, sondern fehlende Vergleiche.**

## Umgesetzt und unverändert

- Gemeinsame unveränderliche Vorbereitung aus der ursprünglichen Domäne;
  kanonische Besuche/Rides und physikalische Fingerprints bleiben erhalten.
- Fixed-K mit festen Starts und Single-Use-Reservoir mit optionalen Einsätzen,
  Dispatch und Rückkehr; STOP/SKIP und das vollständige bisherige Waitingraster.
- Integrierte ganzzahlige Beförderung; getrennte Ziele `journey_time` und
  `unserved`; Extraktion in bestehende, unabhängig geprüfte Zertifikate.
- Z3: ein nativer `Optimize.check()`-Aufruf, Integerzeiten, bedingte
  Ressourcendisjunktionen und exakte binäre Linearisierung der Zeitprodukte.
- Hexaly: native optionale Besuchsintervalle und eine native Reihenfolgeliste
  je Ressource. Die Implementierung ist vorhanden, ihre Ausführung ist noch
  nicht geprüft. Eine Liste pro Ressource erlaubt unterschiedliche Reihenfolgen
  und damit Bypass-Überholen.
- Separater Runner, Build-only, geprüfte Referenzen/Startwerte, getrennte native
  Verbesserungen, Schranken und Rückfallwerte, Prozessbaumüberwachung,
  Quellenkopien und neue Ergebnisordner. Keine eigene Suche oder Cutoff-Schleife.
- Vorhandene Solver und Standards wurden für diesen Pilot nicht umgestellt.

Details und CLI-Aufrufe: [Backend-Vertrag](../reference/native_solver_backends.md).

## Korrektheit und Freigaben

Der abschließende gezielte Testlauf hat **61 bestandene Tests und vier
lizenzbedingt übersprungene Hexaly-Tests**. Die Prüfsuite umfasst kleine
enumerierbare Fälle, Vergleich mit CP-SAT und dem unabhängigen ganzzahligen
Passagier-IP, Waiting/Freigaben, Überholen, gekoppelte Ressourcen, Kapazitäten,
Horizontgrenzen, die letzte Fixed-K-Bewegung, Reservoir-Rückkehrkollisionen,
Odd-Cycle-Ganzzahligkeit, große Tickwerte und Abbruchbehandlung.

Nachweis:
[tests_final_verified.xml](../../benchmarks/output/native_solver_gates_20260911/tests_final_verified.xml).
Vier Skips sind ausdrücklich keine bestandenen Hexaly-Prüfungen. Die gesamte
historische Repository-Testsuite wurde nicht erneut ausgeführt.

### Historische Z3-Replays

| Fall | Historischer Wert | Vollständig fixiert im Z3-Modell | Dauer des abschließenden Replays |
|---|---:|---|---:|
| R, Max50-Reservoir | 368.765,817136 Passagiersekunden | exakt reproduziert | 6,15 s |
| K38, Fixed-K/Waiting | U = 315 | exakt reproduziert | 4,04 s |
| C, K39/Waiting | U = 1.402 | exakt reproduziert | 3,88 s |

Diese Replays beweisen die Darstellbarkeit dieser konkreten Pläne, keine globale
Optimalität. Zusätzlich wurden bei festgehaltener Bewegung die Passagiere mit
dem bestehenden CP-SAT-Modell frei optimiert: **alle drei historischen Werte
sind auch die jeweiligen nachgewiesenen Passagieroptima dieser Fahrpläne.**
Die Verifikation berechnet diesen Kontrollwert ausdrücklich; sie setzt einen
historischen Incumbent nicht allgemein mit einem Optimum gleich.

- [Abschließende Z3-Replays](../../benchmarks/output/native_solver_gates_20260911/z3_replays_final/gate.json)
- [Separate Passagier-Kontrolloptima](../../benchmarks/output/native_solver_gates_20260911/passenger_oracles/oracles.json)
- [R-Kontrolloptimum](../../benchmarks/output/native_solver_gates_20260911/passenger_oracles/R_passenger_oracle.json)

### Engpass Z3: Passagiere selbst finden

Bei freier Passagierzuordnung und weiterhin fixierter Bewegung reproduzierte
Z3 diese Optima in den drei 90-Sekunden-Prüfungen nicht. Die tatsächlich
abgeschlossenen kooperativen API-Aufrufe dauerten ungefähr 94,08 / 91,27 /
90,08 Sekunden. Als beste native Zuordnung wurde jeweils nur die zulässige
All-unserved-Lösung protokolliert: R = 1.536.000 Passagiersekunden, K38 und C
jeweils U = 3.074. Der geprüfte gute Referenzplan blieb separat erhalten.

Nach Ergänzung sicherer Zeitgrenzen und direkter linearer Produkte bei festen
Zeiten blieben die abschließenden kurzen Wiederholungen ebenfalls ohne
Reproduktion des Passagieroptimums. Die Startwerte wurden über Z3s native API
übergeben; diese API garantiert keine Übernahme als Incumbent.

Das ist **kein Unzulässigkeitsbeweis und kein gefundener Modellfehler**. Es ist
ein negativer Leistungsbefund auf einer bereits deutlich einfacheren
Teilaufgabe. Nach dem vereinbarten Freigabekriterium wurden daher keine großen
freien Z3-Läufe gestartet. Das Modell könnte mit anderen nativen Einstellungen
oder mehr Zeit anders reagieren; dafür liegt hier kein positiver Nachweis vor.

[90-Sekunden-Prüfungen](../../benchmarks/output/native_solver_gates_20260911/z3_replays_v2/gate.json).

### Hexaly

Installiert: Python/Engine-Paket `15.0.20260909`. Die Engine konnte ohne
Lizenzdatei `/opt/hexaly_15_0/license.dat` nicht geöffnet werden. Felix wartet
auf die Lizenzfreigabe. Es gibt deshalb noch keine Aussage zu Modellzulässigkeit,
Startwertübernahme, Suchgeschwindigkeit oder Schranken dieses Backends.

Nach Eintreffen der Lizenz bleiben die kleinen freien Modelle, Grenzfälle und
historischen Replays zwingend vor einem großen Vergleich zu prüfen. Der
Vier-Test-Smoke-Test allein ersetzt nicht sämtliche Semantikprüfungen.

## Temporale Planung: tatsächlich geprüfte Quellen

### TemPEST

Geprüft wurde Commit `a888dc25d2fb705be42a4790cf4f3ceea83fcb6c`
in einer getrennten Umgebung. Im veröffentlichten `SymbolEncoder` wird ein
Parameter mit `IntType(0,2)` als Real kodiert. **Der Wert 1/2 erfüllt die vom
Encoder erzeugten Typbedingungen.** Auch Ereigniszeiten sind Real.

Das Gegenbeispiel betrifft den direkten symbolischen Parameterpfad. Es ist
kein vollständiger vom Planer ausgegebener Seilbahnfahrplan und kein Beweis,
dass ganzzahlige Passagiermengen durch konstante Integerupdates unmöglich wären.
Eine alternative exakte Tickübersetzung einschließlich gleichzeitiger
Ressourcenübergaben wurde nicht zertifiziert. Die direkte Übersetzung wird
deshalb nicht für den Performancevergleich zugelassen.

[Probe](../../benchmarks/output/native_solver_gates_20260911/tempest.json),
[veröffentlichter Encoder](https://github.com/fbk-pso/tempest/blob/a888dc25d2fb705be42a4790cf4f3ceea83fcb6c/src/tempest/encoders/symbol_encoder.py).

### Patty / InSTraDi

Die erste Prüfung des numerischen Hauptzweigs `651a813d…` konnte keine
durative STOP-Aktion parsen. **Das ist kein Ausschlussgrund für die temporale
Patty-Variante.** Deshalb wurde zusätzlich der veröffentlichte `instradi`-Zweig
mit Commit `6246e9a8a878f4299adbb111773267504ab8b05a` separat installiert und
dessen vollständige native ICE-Regelerzeugung getestet. Die genaue Zuordnung
dieses WIP-Commits zur finalen Paper-Artefaktversion bleibt offen.

Zwei reproduzierbare Prüfungen:

1. Eine Aktion mit fester Dauer zwei Ticks und vorgeschriebenem Start bei
   1/2 Tick ist unter den vollständigen nativen Regeln zulässig; das Ende liegt
   bei 5/2. Die Häufigkeitsvariablen sind Integer, die Zeiten Real.
2. Bei direkter boolescher Ressourcenfreigabe/-anforderung ist die Übergabe
   genau bei Tick 2 unzulässig. Mit dem veröffentlichten positiven
   `EPSILON = 0.01` in Modellzeiteinheiten wird sie zulässig. Die Originaldomäne
   erlaubt dagegen berührende geschützte Intervalle ohne zusätzliche Lücke.

Die erforderlichen privaten Vorbedingungen/Effekte der kleinen Testaktionen
wurden ergänzt, um einen separaten Empty-action-Fehler des eingefrorenen Codes
nicht mit dem Zeitsemantiktest zu vermischen. Der Enginecode wurde nicht
geändert. Python 3.11 statt der alten dokumentierten Umgebung erfordert die
passenden kompilierten PyEDA-0.28-Abhängigkeiten; deren Binärhashes und sämtliche
Paketversionen werden erfasst.

Das schließt die **direkte getestete Übersetzung** aus. Es beweist nicht, dass
jede alternative Planungs-Kompilierung unmöglich wäre. Ein Engineumbau oder
eine kontinuierliche Relaxation mit nachträglichem Runden wurde nicht als
erfolgreiche Integration ausgegeben. Es gibt keinen freigegebenen temporalen
Kapazitätsadapter und keinen daraus abgeleiteten Kapazitätsbound.

[ICE-Probe](../../benchmarks/output/native_solver_gates_20260911/patty_instradi_final.json),
[Zeitvariablen](https://github.com/matteocarde/patty/blob/6246e9a8a878f4299adbb111773267504ab8b05a/src/ices/ICETransitionVariables.py),
[Präzedenzregeln](https://github.com/matteocarde/patty/blob/6246e9a8a878f4299adbb111773267504ab8b05a/src/ices/ICEPatternPrecedenceGraph.py).

## Ausgeführte Kampagne und Fortschritt

Die Inputs und tatsächlichen Quellen wurden vor den Läufen eingefroren.
Alle sechs gestarteten Läufe waren sequenzielle CP-SAT-Legacy-Läufe mit zwölf
angeforderten Workern und je 150 Sekunden einschließlich Aufbau/Abschluss.
Referenzen wurden nicht als Verbesserungen gezählt.

| Fall | Seed | Validierte End-UB | Vergleichbare LB | Verbesserungen | Letzte beobachtete Verbesserung |
|---|---:|---:|---:|---:|---:|
| R | 0 | 368.765,817136 s | 209.409,890299 s | 0 | keine |
| R | 1 | 368.765,817136 s | 209.409,890299 s | 0 | keine |
| R | 2 | 368.765,817136 s | 209.409,890299 s | 0 | keine |
| C / K39 | 0 | U = 1.362 | 0 | 6 | 108,49 s |
| C / K39 | 1 | U = 1.346 | 0 | 9 | 127,70 s |
| C / K39 | 2 | U = 1.370 | 0 | 4 | 114,97 s |

Die Zeiten stammen aus beobachteten und unabhängig geprüften Checkpoints;
exakte native Meldungszeiten stehen separat in `result.json`/`events.jsonl`.

**R plateauiert im beobachteten Budget:** keine bessere UB und keine stärkere
vergleichbare LB, Gap 43,2133 %. Die verwendete globale R-Schranke stammt aus
dem früheren zertifizierten Modell mit identischem Domänen-Fingerprint, gilt
für alle verglichenen Engines und wird nicht als neuer CP-SAT-Fortschritt
gewertet. Die native verwendbare CP-SAT-LB bleibt null; negative Rohwerte werden
separat aufbewahrt.

**C verbessert sich in allen drei Wiederholungen:** 40, 56 bzw. 32 zusätzlich
bediente Personen gegenüber U=1.402. Der letzte Fortschritt liegt zwischen
108 und 128 Sekunden. Damit gibt es innerhalb dieses Budgets echte
Suchverbesserungen, aber weiterhin keinerlei globale Gap-Schließung (LB=0).
Ein endgültiges Plateau lässt sich aus den letzten 22–42 Sekunden nicht
ableiten. Die K38-Referenz mit U=315 bleibt wesentlich besser; der bekannte
Fixed-K39-Engpass ist damit nicht behoben.

### Größe und CPU-Nutzung

| Fall | Variablen | Constraints | Ride-Kandidaten | Ressourcenintervalle |
|---|---:|---:|---:|---:|
| R | 87.020 | 190.189 | 10.100 | 10.600 |
| C | 49.760 | 105.467 | 5.030 | im normalisierten Ergebnis nicht verfügbar |

Beobachteter Peak-Prozessbaum-RSS: R ungefähr 5,33–6,05 GiB; C mit vollständiger
Messung ungefähr 3,50–3,53 GiB. Die gemessene CPU-Zeit entspricht über den
gesamten Lauf etwa 8,0–8,7 ausgelasteten Kernen im Mittel, bei zwölf angeforderten
Workern und bis zu 13 beobachteten Threads. Aufbau und Validierung sind darin
enthalten; „zwölf Worker“ bedeutet nicht durchgehend zwölf voll ausgelastete
Kerne.

### Abschlussfehler und Erhaltung der Daten

Beim letzten Lauf schlug das Prozessgruppensignal am Zeitlimit mit macOS
`PermissionError` fehl. Der Solver hatte sein Ergebnis und den Checkpoint
bereits geschrieben und war beim anschließenden Prozesscheck beendet. Der
Checkpoint wurde erneut unabhängig bestätigt (U=1.370). Die fehlenden
Supervisor-Metriken dieses Laufs stehen auf **nicht verfügbar**, nicht auf null.

Die ursprüngliche unvollständige `campaign.json` und alle eingefrorenen Quellen
bleiben erhalten. `campaign_reviewed.json` und `report_reviewed.md` enthalten
den nachvollziehbar wiederhergestellten Abschluss. Der Supervisor behandelt
in der aktuellen Implementierung den Exit-Wettlauf und verweigerte
Prozessgruppensignale mit direkter Signalisierung eigener Kindprozesse;
ein zusätzlicher Regressionstest deckt den Fall ab. Es wurde kein Lauf
heimlich wiederholt.

Die sechs Solver-Slots beanspruchten rund 15 Minuten; der erste geprüfte
Abschluss lag nach 1.184 Sekunden, also rund 19,7 Minuten einschließlich
Zwischenprüfung und Wiederherstellung. Damit wurde das 60-Minuten-Limit
eingehalten. Aktuelle Abschlusszeit siehe `campaign_reviewed.json`.

## Dateien und reproduzierbarer Einstieg

- [Plan](../plans/native_solver_pilot_20260911.md)
- [Backend-API und Installation](../reference/native_solver_backends.md)
- [Modellcode](../../src/ropeway_skip_stop_optimization/optimization/ddd/native_solvers/model.py)
- [Native Optimierung, Hints und Zertifikate](../../src/ropeway_skip_stop_optimization/optimization/ddd/native_solvers/optimizer.py)
- [Öffentlicher Runner](../../benchmarks/run_ddd_native_solver.py)
- [Historische Replays und Kontrolloptima](../../benchmarks/verify_native_solver_replays.py)
- [Temporale Gegenbeispiele](../../benchmarks/probe_temporal_solvers.py)
- [Kampagnenrunner](../../benchmarks/run_native_solver_campaign.py)
- [Reine Ergebnisprüfung ohne neue Suche](../../benchmarks/report_native_solver_campaign.py)
- [Auswertung](../../benchmarks/output/native_solver_campaign_20260911_v1/report_reviewed.md)
- [Geprüftes Gesamtmanifest](../../benchmarks/output/native_solver_campaign_20260911_v1/campaign_reviewed.json)
- [Fortschrittsdaten](../../benchmarks/output/native_solver_campaign_20260911_v1/progress.csv)
- [Quellcode-Hashes der tatsächlich gelaufenen Modelle](../../benchmarks/output/native_solver_campaign_20260911_v1/source_hashes.json)

## Konsequenz für die Fortsetzung

**Kein Standardwechsel und keine Empfehlung eines neuen Backends für sechs
Stationen.** Keine neue Engine hat die beiden Bestätigungswiederholungen mit
einem Vorteil bestanden. Z3 würde ich nach diesen Prüfungen aktuell nicht mit
einem langen freien Lauf priorisieren. TemPEST/Patty sind ohne weitere exakte
Übersetzungsarbeit kein Ersatz für das bestehende Modell.

Hexaly ist der noch offene Teil dieses Piloten: Lizenz, vollständige
Semantikprüfung, anschließend die bereits festgelegten kurzen Vergleiche.
Ob die native Listensuche etwas bringt, ist weiterhin eine offene Frage.
Die vorhandenen positiven K39-Schritte verbessern Incumbents, beantworten
aber die offenen Forschungsfragen nicht und liefern keinen Optimalitätsbeweis.
Weitere Langläufe, neue Suchcontroller oder ein automatischer Wechsel auf die
Sechs-Stationen-Szenarien wurden nicht gestartet.
