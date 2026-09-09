# CP-SAT mit 300 Sekunden Anlauf: Ergebnis und Validierungsgrenze

Stand: 9. September 2026. [Versuchsplan](../plans/ddd_cp_sat_warmup.md).

**Spätere G0-Nachprüfung:** Die unten dokumentierte damalige EAN-Ablehnung ist durch die Trennung von Horizontmitgliedschaft und Headwaytoleranz behoben. Der unveränderte Anlaufplan besteht jetzt die endliche EAN-Prüfung; seine feste Passenger-IP ergibt 1.127.589,180576 bei 1008 bedienten Personen. Die separat geprüften exportierten Nachläufe verletzen weiterhin Headways. [Aktuelle Ergebnisse und Grenzen](ddd_horizon_contract_gate.md). Der folgende Text und die ursprünglichen Ergebnisdateien dokumentieren den historischen Versuch unverändert.

**Kein belastbarer Durchbruch.** Nach je zehn Minuten sind die rohen CP-Kosten mit Anlauf nur 0,402 % niedriger, bei 96 weniger bedienten Personen, größerem Modell und schlechterer Untergrenze. Außerdem lehnt der unabhängige EAN-Validator den Anlauf-Endfahrplan am Horizont ab. Er darf deshalb nicht als vollständig unabhängig bestätigtes Betriebsergebnis bezeichnet werden. Die Hypothese, dass der bisherige Anfangszustand einen Großteil des Abstands zu All-Stop erklärt, wird durch diesen Test nicht bestätigt; freie Anfangspositionen sind damit auch nicht widerlegt.

## Aufbau und Implementierung

K39, Five-Station-B, 20 OD-Gruppen/1280 Personen, Kapazität 8, Exit-Waiting W=1200 s, 1-us-Raster. Kontrolle: Releases 0, T=H=1200 s. Anlauf: Releases 300, T=H=1500 s. Der Bedienungszeitraum bleibt 1200 s, ebenso die Unbedient-Strafe pro Person. Die physische Anfangsanordnung und Boundary bei t=0 sind identisch. Alle zukünftigen Stop-/Skip- und Warteentscheidungen einschließlich Anlaufphase bleiben frei. Kein periodischer Fahrplan ist vorgeschrieben.

`--warmup-seconds` ist implementiert; Standard 0. Die Transformation verschiebt Nachfrage und Horizonte, baut Visitgrenzen und Passagierkandidaten neu und verwirft ungeprüfte endliche Seeds. Code: [Warmup-Transformation](../../src/ropeway_skip_stop_optimization/benchmarking/ddd_cp_sat_warmup.py), [Runner](../../src/ropeway_skip_stop_optimization/benchmarking/ddd_fixed_k_cp_sat.py), [CLI](../../benchmarks/run_ddd_fixed_k_cp_sat.py), [Tests](../../tests/test_benchmarking_ddd_cp_sat_warmup.py).

Beide Hauptläufe erhalten dieselbe bis 1500 s validierte Startbewegung bzw. deren 1200-s-Präfix. Ein separater physischer Seed-Generator fixiert ausschließlich für diesen Hint die Vorlage mit einer All-Stop- und 38 All-Skip-Kabinen und optimiert Exit-Waits. Das war erforderlich, weil die unveränderte Fortsetzung der bisherigen endlichen Referenz außerhalb ihres alten Prüfhorizonts kollidiert. Seedkosten: 1441651,791880 / 1437094,223280, jeweils 168 bediente Personen; schon daraus ergibt sich ein Phaseneffekt von ca. 0,32 %. Der physische Seed-Aufruf benötigt 0,510 s. Details in Plan und `seed_preparation.json`.

Hauptläufe: je 600 s Gesamtbudget, 8 Worker, Random-Seed 0, Produktkodierung, sequenziell in getrennten Prozessen. Keine parallelen Solver während der Hauptläufe. Je ein Lauf pro Variante; paralleles CP-SAT ist auch bei gleicher Seed-Zahl nicht vollständig reproduzierbar. Beide Endstatus `FEASIBLE`, Proof-Scope `FIXED_K_GLOBAL` innerhalb der jeweiligen deklarierten endlichen Domain.

## Ergebnisse direkt aus CP-SAT

| Kennzahl | Kontrolle | 300 s Anlauf |
|---|---:|---:|
| CP-Kosten, im DDD-Validator geprüft | 1.132.243,584088 | 1.127.695,888264 |
| Bediente Personen | 1096 | 1000 |
| Unbediente Personen | 184 | 280 |
| Native Untergrenze, mit Null als Floor | 94.463,455845 | 0 |
| Gap | 91,66 % | 100 % |
| Variablen vor / nach Presolve | 51.076 / 27.978 | 63.767 / 34.947 |
| Constraints vor / nach Presolve | 106.782 / 56.056 | 133.879 / 69.917 |
| Bewegungsbesuche / Passagierkandidaten | 1418 / 5030 | 1761 / 6402 |
| Peak-RSS, MB | 3587,92 | 4702,06 |
| Gesamtzeit, s | 600,506 | 600,622 |
| Vorbereitung / Seed / Modellaufbau, s | 4,013 / 0,670 / 1,063 | 4,356 / 1,020 / 1,371 |
| Solveraufruf, s | 594,405 | 593,412 |
| Davon bis Suchbeginn, s | 22,76 | 29,94 |

Kostenverbesserung roh: **4547,695824 bzw. 0,40165 %**. Das Anlaufmodell hat etwa 25 % mehr Variablen und benötigt rund 31 % mehr Peak-RSS. Der frühere K39-Waiting-Bestwert **1022076,357256** mit besserem Startfahrplan wird nicht erreicht. All-Stop K38 mit **399287,271408** und vollständiger Bedienung bleibt deutlich besser; bei dieser Referenz beginnt die Bedienung im bekannten All-Stop-Zustand. Es wurde kein neuer K38-Fortsetzungsversuch mit 300 s Anlauf gerechnet.

| Zeit seit Optimizerstart | Kontrolle UB | Anlauf UB |
|---|---:|---:|
| 1 min | 1.369.003,81 | 1.373.074,17 |
| 2 min | 1.331.329,48 | 1.291.985,09 |
| 5 min | 1.239.618,75 | 1.224.331,07 |
| 7 min | 1.176.576,09 | 1.152.144,67 |
| Laufende | 1.132.243,58 | 1.127.695,89 |

Letzte Incumbentmeldungen nach 587,05 / 592,64 s. Beide verbessern die UB nach Minute fünf weiter; kein vollständiges spätes Plateau. Der Zwischenvorsprung des Anlaufs schrumpft bis Laufende stark. Seine Untergrenze bleibt während des gesamten Versuchs bei null nach Anwendung des gültigen Floors.

## Was die gefundenen Fahrpläne machen

Kontrolle: 187 Stopps im Bedienungsfenster. Anlauf: **nur 4 Stopps während der 300-s-Anlaufphase**, danach 172 Stopps. Die Rohzuordnung im Anlauf hat mittlere Zeit bis Ziel **791,70 s** für die 1000 bedienten Personen: 715,85 s bis Boarding und 75,85 s an Bord. Dazu kommen 336000 Kosten für Unbediente. Die vier frühen Stopps bedeuten nicht, dass die Anlaufphase fest auf Skip beschränkt wäre; dies ist die vom Solver gefundene Bewegung.

Anlauf-Fahrplan: 98 positive Wartevorgänge, insgesamt 609,764498 s, davon über alle Kabinen summiert 100,356067 s innerhalb der Anlaufphase. Maximale einzelne Wartezeit 71,575574 s. Kein eigentlicher Plattform-Wartevorgang reicht über H; eine danach liegende Zusammenführung kann trotzdem erst nach H erreicht werden.

Als Gegenprobe wurde der unveränderte **1200-s-Präfix des Anlauf-Endfahrplans mit Nachfrage ab t=0** bewertet. DDD- und EAN-Prüfung bestehen für diesen Präfix; die unabhängige Integer-IP liefert **1347437,517224** (optimal nur für diese feste Bewegung). Er ist also kein neu gefundener guter Fahrplan für unsere ursprüngliche Nachfragefreigabe. Die Auswertung ersetzt weder die fehlende Bestätigung des ganzen 1500-s-Plans noch einen weiteren globalen Solverlauf.

## Unabhängige Prüfung: zwei getrennte Befunde

### Passagierzuordnung in der Kontrolle

Die unabhängige Integer-Passagier-IP akzeptiert die feste Kontrollbewegung und verbessert die Kosten geringfügig auf **1131767,098632**, weiterhin 1096 bediente Personen. Differenz zum CP-Wert: 476,485456. CP-SAT hatte seine ganzzahlige Passagierzuordnung am Zeitlimit also nicht vollständig für den zuletzt gefundenen Fahrplan ausoptimiert. Das ist kein Nachweis einer falschen CP-Kostenberechnung. Der nachoptimierte Checkpoint ist getrennt als `warmup0_600s_seed0/best_incumbent.json` gespeichert; Rohresultat und Rohcheckpoint bleiben erhalten.

### Horizontabweichung beim Anlauf-Endfahrplan

Der DDD-Validator akzeptiert den Rohfahrplan gemäß seiner exakten Tick-Domain. Die unabhängige EAN-Prüfung im Passenger-IP-Builder lehnt ihn ab:

- Station C, Exit-Merge: Kabine 35/Besuch 43 (Skip) erreicht den Merge bei **1499,221617 s**.
- Kabine 8/Besuch 41 (Stop, Eintritt 1472,397255 s, Wait 3,420928 s) erreicht den Merge nach Tickrechnung bei **1500,000001 s**.
- Der CP-/DDD-Ressourcenindikator ist für den zweiten Merge aus, weil sein Eintritt eine Mikrosekunde nach H liegt. Sein zuvor begonnener Plattformaufenthalt wird weiterhin geprüft.
- Der EAN-Validator verwendet im Fixed-Movement-IP-Pfad 1e-5 s Toleranz auch für die Entscheidung, ob ein Ressourcenereignis noch zum Horizont gehört. Er nimmt den zweiten Merge deshalb auf und meldet eine Headwayverletzung von ca. **0,484542 s**. Die EAN-Zeitberechnung verwendet dabei teilweise ungerundete physische Offsets; die deklarierte CP-Domain verwendet kanonische Ticks.

Fundstellen: [CP-Ressourcenaktivierung](../../src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_movement.py), [EAN-Separator](../../src/ropeway_skip_stop_optimization/optimization/ean/headway_separator.py), [Fixed-Movement-IP mit Validator-Toleranz](../../src/ropeway_skip_stop_optimization/optimization/ean/optimizers/fixed_movement_passenger_model.py).

**Es wurde keine Toleranz aufgeweicht und kein Validator umgangen. Für den vollständigen Anlauf-Endfahrplan liegt kein unabhängiges Passenger-IP-Zertifikat vor.** Die neue Warmup-Transformation ist nicht die Ursache dieser unterschiedlichen Aktivierungsregeln; der längere Versuch macht einen bestehenden Schnittstellen-/Horizontfall sichtbar.

Zusätzlich wurde für beide Endfahrpläne eine strengere physische Nachprüfung versucht: alle Ressourcen sämtlicher exportierter Besuche auch nach H berücksichtigen, Zeiten und Routen festlassen, nur letzte STOP-Wartezeiten verlängern und deren Summe minimieren. **Beide eingeschränkten Reparaturmodelle melden INFEASIBLE.** Es wurde keine Reparatur angewandt. Das beweist weder globale Unmöglichkeit einer Fortsetzung noch Infeasibility innerhalb der ursprünglichen Domain. Es zeigt, dass bloßes Verlängern der letzten Wartezeiten keinen sicheren Abschluss aller begonnenen Routenteile herstellt. Eine strengere Endbehandlung würde Änderungen früherer Entscheidungen benötigen.

Die Toleranzabweichung und die fehlende Sicherung aller Routenteile nach H sind getrennte offene Punkte. Eine einheitliche Horizontaktivierung würde den ersten Punkt beheben, allein aber noch keine betrieblich sichere Fortsetzung garantieren. Beide Punkte müssen vor belastbaren Aussagen über fortsetzbaren Betrieb geklärt werden.

## Tests, Artefakte und Reproduktion

**41 gezielte Tests bestehen**, einschließlich 9 neuer Warmup-Fälle: unveränderte K39-Startressourcen und Bewegung, verschobene Releases bei gleicher Unbedient-Strafe, längere Visitgrenzen, keine Übernahme ungeprüfter Seed-Fortsetzungen, Kostenvergleich eines festen Warmup-Fahrplans mit unabhängiger IP und INFEASIBLE bei erzwungenem Boarding vor Freigabe. Diese Tests ersetzen nicht die oben gescheiterte Prüfung des großen Endfahrplans.

```sh
.venv/bin/python -m pytest -q tests/test_benchmarking_ddd_cp_sat_warmup.py tests/test_benchmarking_ddd_fixed_k_cp_sat.py tests/test_optimization_ddd_cp_sat_waiting.py tests/test_optimization_ddd_cp_sat_integrated.py
```

Alle Messdateien liegen unter `benchmarks/output/ddd_integrated_cp_sat_warmup/k39/` (lokal gitignored):

- `prepare_shared_seed.py`, `seed_preparation.json`, `shared_seed_warmup0.json`, `shared_seed_warmup300.json`: gemeinsame Hint-Vorbereitung.
- `run_pair.py`: sequenzielle Hauptläufe; verweigert Überschreiben fertiger Ergebnisse.
- `warmup0_600s_seed0/`, `warmup300_600s_seed0/`: jeweils `command.json`, `config.json`, `result.json`, `incumbent.json`, `solver.log`, `events.jsonl`, `progress.csv`, `post_ip_validation.json`, `terminal_tail_repair.json`.
- `analyze_pair.py`, `repair_terminal_waits.py`, `comparison.json`: reproduzierbare Nachprüfung, Kostenzerlegung, Domainabgleich und ausdrücklich gespeicherte fehlgeschlagene Validierung/strengere Reparaturversuche.
- `warmup_plan_with_original_demand.json`, `warmup_plan_original_demand_seed.json`: unabhängige Neubewertung des 1200-s-Präfixes.

Zum Reproduzieren aus dem Software-Repository zunächst `prepare_shared_seed.py`, danach `run_pair.py`, anschließend `analyze_pair.py` aus diesem Verzeichnis mit `.venv/bin/python` starten. Hauptläufe benötigen zusammen ca. 20 Minuten. Für eine Wiederholung ein neues Ausgabeverzeichnis verwenden bzw. die Skripte entsprechend konfigurieren; vorhandene Ergebnisse erhalten.
