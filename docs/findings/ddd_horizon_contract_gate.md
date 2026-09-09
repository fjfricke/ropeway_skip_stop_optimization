# G0: einheitliche Horizontprüfung und Nachlaufdiagnose

Stand: 9. September 2026. Umsetzung zu Schritt 1 des [Algorithmusplans](../plans/heuristic_and_non_mip_roadmap.md). Vertrag und technische Einzelheiten: [Finite Horizon Contract](../reference/finite_horizon_contract.md).

**Der Widerspruch bei H+1 us ist behoben. Eine sichere betriebliche Fortsetzung ist weiterhin nicht nachgewiesen.** Die gespeicherten Fahrpläne wurden nicht verändert und kein globaler Bewegungssolver erneut gestartet.

## Änderungen

EAN prüfte bisher Ereignisse bis `H + tolerance_seconds`. Bei einer Toleranz von 1e-5 s wurde dadurch der Merge bei 1500,000001 s in den 1500-s-Horizont aufgenommen, während CP/DDD ihn ausschloss. Eager-, Sparse- und nachgelagerte Dominanzprüfungen verwenden jetzt denselben geschlossenen Horizont mit ausschließlich maschineller Rundungsbehandlung. Die Toleranz für eigentliche Headwayabweichungen bleibt unverändert.

Der Eintritt in die Exit-Warteposition wird aus den validierten Ereignissen des Plans berechnet: Plattformabfahrt minus Wartezeit. So verschiebt die erneute Verwendung ungerundeter physischer Offsets nicht versehentlich ein Ereignis über H. Zusätzliche Coverage-Prüfung in EAN verhindert das Weglassen noch vor/bei H beginnender Besuche.

Eine separate Auditfunktion prüft außerdem alle verfügbaren Ressourcenereignisse der exportierten Besuche auch nach H. Sie kennzeichnet ihre Aussage ausdrücklich als begrenzt und setzt `continuation_status=NOT_PROVEN`. Diese Diagnose verändert die bisherige Optimierungsdomäne nicht. Neue CP-Ergebnispayloads tragen denselben Fortsetzungshinweis.

## Gespeicherte K39-Fahrpläne erneut geprüft

Alle drei Fälle: Five-Station-B, 1280 Personen, Kapazität 8, Exit-Waiting bis 1200 s, 1-us-Raster. Die Anlaufvariante hat Releases bei 300 und T=H=1500 statt Releases 0 und T=H=1200. Die Passagier-IP optimiert nur die unveränderte gespeicherte Bewegung, mit einem Worker und höchstens 30 s; alle drei IPs beweisen ihr Fixed-Movement-Optimum.

| Gespeicherte Bewegung | Neue endliche EAN-Prüfung | Kosten nach Passenger-IP | Bediente / unbediente Personen | Headwayverletzungen in exportierten Ereignissen einschließlich nach H |
|---|---|---:|---:|---:|
| Früherer bester Waiting-Lauf | bestanden | 1.022.076,357256 | 1104 / 176 | 7 |
| Warmup-Kontrolle, B=0 | bestanden | 1.131.767,098632 | 1096 / 184 | 8 |
| Warmup-Versuch, B=300 | bestanden | 1.127.589,180576 | 1008 / 272 | 8 |

Die rohen CP-Werte bleiben erhalten. Beim B=300-Plan liegt der ursprüngliche Wert bei 1.127.695,888264 mit 1000 bedienten Personen. Die nachträgliche Integer-IP verbessert ausschließlich die Zuordnung geringfügig und bedient acht Personen mehr. Das ist kein neuer Bewegungserfolg. Die historische Ablehnung durch die damalige EAN-Prüfung bleibt im ursprünglichen Finding nachvollziehbar; unter dem jetzt einheitlichen endlichen Vertrag ist dieser Fahrplan passagierbewertbar.

Bei jedem Plan liegt für alle 39 Kabinen das Ende des letzten exportierten Routenteils nach H. Die größten Verletzungen im erweiterten Ereignistest betragen ca. 4,6383 s beim früheren Bestplan, 7,0956 s in der Kontrolle und 5,7371 s im Anlauf. Die Zählung betrifft Ressourcenpaare, nicht notwendigerweise verschiedene physische Kollisionen. Der bekannte C-Merge-Konflikt von ca. 0,484542 s bleibt in der Anlauf-Nachlaufdiagnose enthalten.

**Interpretation:** Es gibt jetzt eine konsistente Antwort für die bisherige endliche Optimierungsaufgabe. Die unveränderten exportierten Nachläufe erfüllen jedoch nicht alle Headways. Keiner dieser Pläne ist dadurch als sicher fortsetzbarer Betrieb zertifiziert. Das widerlegt weder eine andere sichere Fortsetzung noch ein besseres betriebliches Ergebnis nach früheren Planänderungen.

## Tests und Reproduktion

25 neue Regressionen prüfen Plattformbelegung bei H−1 us/H/H+1 us, verschiedene Headwaytoleranzen, eager/sparse-Prüfung, den gleichen kleinen Mergefall in CP/DDD/EAN, fehlende Horizontabdeckung sowie die fehlende Fortsetzungsgarantie trotz konfliktfreier exportierter Ereignisse. Zwei davon prüfen ausdrücklich die Abweichung ungerundeter Offsets von gerundeten Exportereignissen bei H. Die bestehende Waiting-Regression prüft zusätzlich die neuen Ergebnislabels.

Der erste breite Lauf bestand 500 Tests; ein bestehender Integrationstest fand im bisherigen 3-s-Limit keine CP-Lösung (`UNKNOWN/TIME_LIMIT`). Auch isoliert reproduziert: ca. 0,026 s Vorbereitung, 0,067 s Aufbau, 2,91 s Suche ohne Incumbent. Der Test prüft Format und Waiting-Unterstützung, keine Laufzeitgarantie; sein Budget wurde auf 10 s bei einem Worker gesetzt. Anschließend bestanden die 32 direkt betroffenen Tests. **Endgültiger breiter Lauf: 501 Tests bestanden in 131,33 s.** Danach wurden die zwei zusätzlichen Offset-Rundungsfälle ergänzt; der gesamte neue Horizonttest mit 25 Fällen besteht in 0,79 s. Keine Produktionsänderung nach dem breiten Lauf.

```sh
.venv/bin/python -m pytest -q tests/test_optimization_ean*.py \
  tests/test_optimization_ddd_reference.py \
  tests/test_optimization_ddd_trajectory_exhaustive_reference.py \
  tests/test_optimization_ddd_cp_sat*.py \
  tests/test_benchmarking_ddd_fixed_k_cp_sat.py \
  tests/test_benchmarking_ddd_cp_sat_warmup.py
```

Auditcode: [audit_ddd_cp_sat_horizon.py](../../benchmarks/audit_ddd_cp_sat_horizon.py). Ergebnisse unter `benchmarks/output/ddd_horizon_contract_gate/`:

- `waiting_best_audit.json`
- `warmup0_audit.json`
- `warmup300_audit.json`

Diese lokalen Ergebnisdateien enthalten ursprüngliche Domain-Fingerprints, neue endliche Validierung, alle erkannten erweiterten Headwayverletzungen und die getrennte Passenger-IP-Zuordnung. Die beiden ersten Warmup-Audits entstanden vor Ergänzung der Source-Hashfelder im Audit-CLI; die ursprünglichen Quelldateien und Domain-Fingerprints sind angegeben. Historische Ergebnisdateien wurden nicht überschrieben.

## Konsequenz für die nächste Arbeit

G0 ist für die Definition und Regression der endlichen Vergleichsdomäne abgeschlossen. Der stärkere Nachweis sicherer Fortsetzung bleibt ein separater offener Arbeitspunkt. Einen Reservierungsprototyp kann man gegen diese endliche Domäne diagnostisch prüfen; bevor sein Ergebnis als fortsetzbarer Betrieb bewertet wird, muss ein geprüfter Abschluss/Fortsetzungsanschluss vorliegen. Die neue Heuristik darf die beobachteten Nachlaufverletzungen nicht einfach als akzeptable operative Lösung übernehmen.
