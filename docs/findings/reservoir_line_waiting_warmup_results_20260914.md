# Waiting ab Betriebsbeginn bei festen Dispatchzeiten

## Ergebnis

Die Wiederholung mit Waiting ab Sekunde 0 statt 300 hat keinen der drei kollidierenden Kandidaten repariert. CP-SAT beweist die Unzulässigkeit jeweils bereits in der Vorverarbeitung. Die All-Stop-Kontrolle bleibt gültig und bedient unverändert 2.496 Personen. Alle vier Prozesse enden regulär; kein Timeout oder Speicherabbruch.

| Kandidat | K | Ursprüngliches Potenzial | Waiting ab 300 | Waiting ab 0 | Solverzeit ab 0 |
|---|---:|---:|---|---|---:|
| All-Stop-Kontrolle | 38 | gültig 2.496 | gültig, 2.496 bedient | gültig, 2.496 bedient, kein Waiting | 1,247 s |
| Nahe Referenz | 38 | 2.504 | INFEASIBLE | INFEASIBLE | 0,280 s |
| Maximales Potenzial | 45 | 3.074 | INFEASIBLE | INFEASIBLE | 0,289 s |
| Komplementäre Muster | 34 | 2.715 | INFEASIBLE | INFEASIBLE | 0,224 s |

Die drei Potenzialwerte sind keine gültige Bedienung. Die zweite Zeile ist selbst All-Stop und darf nicht als Skip-Stop-Ergebnis interpretiert werden. Eine andere Auswahl von Dispatchzeiten oder Rundenzahlen wurde nicht getestet.

## Kontrollierter Unterschied

Die Kandidatendateien sind bytegleich zur ersten Probe. Quelle, Dispatchzeiten, K, vollständige Routenfolgen und Rundenzahlen bleiben identisch. Die einzige Domainänderung ist `waiting_policy.earliest_wait_time_seconds: 300 → 0`. Headways, Ressourcengeometrie, Waiting-Maximum 1.200 Sekunden, Mikrosekundenauflösung, Nachfrage und Betriebsfenster bleiben erhalten. Source- und Zielfingerprints sind deshalb verschieden und separat gespeichert.

Die Tests umfassen weiterhin zwölf CP-SAT-Worker und höchstens 32 GiB Prozessbaum-RSS. Die Unzulässigkeitsfälle enden vor einer eigentlichen parallelen Suche. Längere Solverzeit würde an diesen bewiesenen Aussagen nichts ändern.

## Konkrete Konfliktzeugen vor dem ersten beeinflussbaren Wartepunkt

Zusätzlich zum nativen Unzulässigkeitsbeweis wurden geschützte Intervalle des ursprünglichen Zeitplans untersucht, deren Start durch kein vorheriges Waiting verändert werden kann. Für frühe Ressourcen vor dem ersten möglichen Exit-Waiting bleibt ihre Belegung fest; bei Eintrittskoeffizient null und nichtnegativem Waiting-Koeffizienten der Räumung bleibt das ursprüngliche Intervall mindestens enthalten.

- **Nahe Referenz:** Zwei solche Ressourcenüberschneidungen. Beispielsweise `platform_entry::A_entry_cw`, Kabinen 19 und 20 beim ersten Besuch. Geschützte Intervalle [171,804068; 178,804068) und [177,031070; 184,031070) Sekunden, Überlappung **1,772998 Sekunden**. Das Waiting am Stationsausgang kann den vorherigen Plattformeintritt nicht verschieben.
- **Komplementäre Muster:** Sechs solche Überschneidungen. Beispielsweise `platform_entry::B_entry_cw`, Kabinen 1 und 2 beim Besuchsindex 1: [98,149295; 105,149295) und [101,911219; 108,911219) Sekunden, Überlappung **3,238076 Sekunden**. Vor diesem Konflikt wurde noch kein beeinflussbarer Wartepunkt erreicht.
- **Maximales Potenzial:** Diese einfache Präfixprüfung findet keinen Konfliktzeugen. Die vollständige CP-SAT-Vorverarbeitung beweist dennoch Unzulässigkeit (`during probing initial propagation`). Der konkrete minimale Widerspruch zwischen den übrigen Ressourcen-/Zeitbedingungen wurde nicht isoliert. Die Ursache wird deshalb nicht pauschal als erster Plattformeintritt beschrieben.

Die vollständigen Zeugen stehen in `immutable_prefix_conflicts.json` im neuen Ergebnisordner. Die Prüfung liefert hinreichende Ausschlussgründe, keinen vollständigen Zulässigkeitstest.

## Konsequenz

Waiting kann bei festen Dispatchzeiten nur Konflikte beeinflussen, vor denen ein legaler Wartepunkt liegt. Frühere Überschneidungen muss bereits die Erzeugung der Dispatch-/Musterkombination verhindern. Für die getesteten Kandidaten reicht auch früher freigegebenes Exit-Waiting nicht aus.

Das widerlegt weder Waiting-Reparatur für andere Kandidaten noch die Existenz besserer Skip-Stop-Pläne. Es zeigt, dass eine Auswahl allein nach Transportpotenzial und Gesamtzahl der Konflikte strukturell nicht reparierbare Kandidaten enthalten kann. Eine zukünftige Auswahl könnte solche eindeutigen Präfixkonflikte vor einem Solveraufruf aussondern. Änderungen der Evolution oder des Decoders wurden im Rahmen dieser Wiederholung nicht vorgenommen.

## Artefakte

- Neu: `benchmarks/output/reservoir_line_evolution_20260914/fixed_dispatch_waiting_warmup_v1`.
- Kontrolle: `benchmarks/output/reservoir_line_evolution_20260914/fixed_dispatch_waiting_probe_v1`.
- Runner: `benchmarks/run_reservoir_line_waiting_probe.py`, zusätzliche Parameter `--repeat-probe` und `--earliest-wait-seconds`.
- Je Probe: `input.json`, `cp_sat.log`, `result.json`, Supervisionsdaten; bei Erfolg `movement.json` und `best.json`.
- Kampagne: eingefrorene Quellen, Lockfile, Kandidatenhashes, `campaign.json`, `summary.json`, `report.md`.
- 63 passende Tests bestanden, einschließlich einer kleinen Instanz, die durch den Wechsel der Waiting-Freigabe tatsächlich reparierbar wird.
