# Reservoir-Portschutz: Umsetzung und Abnahme

Stand: 14.09.2026. Der gemeinsame Rope-Headway ist implementiert. Architektur B,
ideales Auskuppeln, Passagierdefinitionen und historische Defaults bleiben erhalten.

## Implementierter Umfang

| Pfad | Neuer Portvertrag |
|---|---|
| Vollständiges Reservoir-CP-SAT | unterstützt, einschließlich Waiting und letzter Rückkehr |
| Linienplanung `legacy_templates` | `intervals` und `dispatch_domains` unterstützt |
| Linienplanung `shared_rounds`, `shared_rides` | `intervals` unterstützt |
| CP-SAT-Reparatur mit fixierten Außenkabinen | auch Außenpassagen und Außenrückkehr physisch geschützt |
| Reservoir-Phasen-Arc-Flow | Portschutz auf genau einer gewählten ausgehenden Kante je realem Grenzereignis, einschließlich Rückkehr zum Sink |
| IBM CP und native Z3-/Hexaly-Adapter | neuer Vertrag ausdrücklich vor Modellbau abgelehnt; Legacy bleibt verfügbar |
| Fixed-Start-Labelled-Arc-Flow | unverändert, kein künstlicher Reservoiranschluss |

Neue Quellendatei:
[`reservoir_boundary.py`](../../src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_boundary.py).
Die unveränderliche Policy bindet den dokumentierten Headway an den Port und
die Bewegungsgeometrie. Der Headway kommt aus der ausdrücklich abgeleiteten
Größe `rope_headway_seconds`, nicht aus dem kleinsten Exit-Headway. Der Export
enthält auch die konservativ quantisierte Tickdauer.

Physische Problem-Fingerprints ändern sich für den neuen Vertrag. Bei Legacy
wird das zusätzliche optionale Feld aus dem bisherigen Manifest ausgelassen;
auch die historische All-Stop-/Skip-Stop-Vergleichsidentität bleibt erhalten.
Geänderte Geometrie beziehungsweise ein anderer Vertrag invalidieren alte
Vorbereitungen. Beim kontrollierten Längenskalieren bleibt der Headway
unverändert und die Geometriebindung wird explizit aktualisiert.

Die CLI-Option lautet `--reservoir-port-policy shared_rope_headway` in
`run_ddd_reservoir_cp_sat.py`, `run_reservoir_lines.py` und
`run_reservoir_capacity_arc_flow.py`. Ohne Option bleibt ein importierter
Vertrag erhalten; neu gebaute historische Beispiele behalten Legacy.
Künftige neue Thesisfall-Spezifikationen müssen die neue Policy explizit wählen.
Die noch geplante Stationskalibrierung wird dadurch nicht vorweggenommen.

## Prüfungen

- Breite betroffene Testsuite: **187 bestanden**; danach ein zusätzlicher
  negativer Arc-Flow-Test ergänzt und bestanden. Abschließende fokussierte
  Porttests: **18 bestanden**. Insgesamt 188 unterschiedliche Tests in diesen
  Läufen; keine Behauptung eines vollständigen Repository-Testlaufs.
- Rohmodelle prüfen fixierte Bewegungen getrennt vom Zertifikatsprüfer.
  Die Prüferabweisung allein dient nicht als Solver-Korrektheitsnachweis.
- Getestet: Mindestabstand minus/exakt/plus ein Tick, STOP-/SKIP-Paare,
  Umlaufpassagen, letzte Rückkehr, inaktive Runden, volle Schutzdauer,
  Waiting-Verschiebung, eingefrorene Außenkabinen und Legacy-Kompatibilität.
- Alle vier implementierten Linienkombinationen stimmen bei fixierten
  Bewegungen überein. Ein kleiner freier Linienfall und ein kleiner freier
  Waiting-Phasenfall liefern unabhängig gültige native Lösungen.
- Der native Gurobi-Phasenbuilder weist fixierte Legacy-Pfade mit zu engem
  Portabstand als unzulässig zurück.
- All-Stop-Sättigungsberechnung berücksichtigt h_R zusätzlich zu den bisherigen
  Routenressourcen. Die Aussage bleibt auf regelmäßiges No-Wait beschränkt.
- Hinzufügen des neuen Vertrags zu einem alten Checkpoint erfordert explizite
  Headway-Evidenz; kein stilles Umdeuten von Modell oder Beförderungsmengen.

Testdatei: [`test_reservoir_boundary.py`](../../tests/test_reservoir_boundary.py).
Die breite Regression umfasst außerdem bestehende Linien-, CP-SAT-,
Phasen-Arc-Flow-, Schranken-, Repair-, Runner- und IBM-Legacy-Tests.

## Historische Replays

Diese Tabelle prüft Modellkompatibilität, nicht den Methodenvergleich über
verschiedene Nachfrageprofile. Alle genannten historischen Fälle verwenden
5 m/s Seilgeschwindigkeit; h_R beträgt dort **1.262.927 Ticks = 1,262927 s**.

| Zertifikat | D | Bedient / unbedient | Kleinster Portabstand | Neuer Vertrag |
|---|---:|---:|---:|---|
| Konstruiertes Mikrosekunden-Gegenbeispiel | 3.074 | 2 / 3.072 | 0,000001 s | abgelehnt |
| R2-All-Stop-Referenz, No-Wait | 3.074 | 2.496 / 578 | 7,129186 s | unverändert gültig |
| R2-All-Stop mit Waiting | 3.074 | 2.496 / 578 | 7,000000 s | unverändert gültig |
| R2-Linien-Skip-Stop, No-Wait | 3.074 | 3.036 / 38 | 1,262927 s | unverändert gültig |
| Journey-Time-Waiting-Startplan des früheren 6h-Versuchs | 1.280 | 1.280 / 0 | 0,818183 s | abgelehnt |

Der letzte Plan enthält Dispatches bei 266,727273 s und 267,545456 s. Dieser
Abstand unterschreitet den neuen Schutz. Der alte Plan bleibt als Legacy
erhalten und wurde nicht repariert oder als neue zulässige Lösung exportiert.
Der Linien-Skip-Stop-Plan liegt dagegen exakt auf der neuen Grenze und bleibt
mitsamt unveränderter Passagierzuordnung gültig.

Artefakte liegen unter
[`benchmarks/output/reservoir_port_20260914/`](../../benchmarks/output/reservoir_port_20260914/):
`counterexample`, `waiting_reference` (historischer R2-No-Wait-Referenzplan),
`all_stop`, `line_skip_stop`, `skip_stop_waiting`. Jede Migration enthält
Quellpfad, alte/neue Fingerprints, Evidenzdatei und Ergebnisbericht. Nur bei
erfolgreicher Prüfung wird `validated.json` geschrieben. Globale/native
Solver-Bounds und Optimalitätsbehauptungen werden nicht übernommen.

Reproduzierbarer Migrationsrunner:
[`migrate_reservoir_port.py`](../../benchmarks/migrate_reservoir_port.py).
Er baut das explizit genannte Beispiel neu auf und verlangt Gleichheit der
Bewegungsgeometrie mit dem Checkpoint, bevor er dessen Rope-Headway übernimmt.
Er unterstützt dabei die bestehenden Fälle mit einheitlichem Waitingmaximum.
Andere Geometrien benötigen passende nachgewiesene Evidenz, keinen geratenen
Fallbackwert.

Beispielaufruf mit einem neuen, noch nicht existierenden Ausgabeordner:

```sh
.venv/bin/python benchmarks/migrate_reservoir_port.py \
  --checkpoint benchmarks/output/reservoir_lines_20260912_exact_r2_k50_small_300s_s0_v1/best.json \
  --example five_station_circle_cw_half_skip_no_wait_headway_b_v0 \
  --output benchmarks/output/port_replay_NEW
```

## Kleiner Ende-zu-Ende-Vergleich

Zwei sequenzielle CLI-Läufe mit einem Worker und höchstens 5 s Suchzeit;
beide solve-to-completion im kleinen synthetischen Fall:

| Kennzahl | Legacy | Gemeinsamer Port |
|---|---:|---:|
| Variablen | 30 | 30 |
| Constraints | 105 | 105 |
| Native Ressourcenintervalle | 34 | 34 |
| Modellbau | 1,28 ms | 1,80 ms |
| Solve | 3,81 ms | 4,06 ms |
| Gesamtzeit Optimizer | 5,80 ms | 7,00 ms |
| Unbediente Personen | 0 | 0 |

Artefakte: `small/legacy_run` und `small/shared_run`. Beide exportierten
Checkpoints wurden erneut geladen und unabhängig geprüft. Hier ersetzt die
Schutzdauer lediglich die bisherigen Eindeutigkeitsticks. Diese Millisekunden-
Einzelmessungen belegen keinen Laufzeitvorteil oder Nachteil auf großen Fällen.
Keine neue Langlaufkampagne wurde gestartet.

## Thesis und verbleibende Arbeit

Kapitel 3 definiert Querschnitt und Schutzintervalle; die neue Abbildung trennt
Reservoirannahme und Stationsmechanik. Kapitel 4 behandelt Portintervalle und
die letzte Rückkehr im Linienmodell. Kapitel 5 beschreibt Implementierung,
Prüfung und Checkpointversionierung; Kapitel 6 trennt die Vertragsversionen.
Anhang C.4 enthält die historischen Replays. Das PDF wurde erfolgreich gebaut;
die neue Skizze und die Tabelle wurden gerendert geprüft. Der abschließende
Build meldet keine undefinierten Referenzen oder übervollen Boxen.

Quellen und Plan:
[Umsetzungsplan](../plans/reservoir_port_rope_headway_20260914.md),
[ursprünglicher Physikaudit](headway_physics_audit_20260911.md),
[Thesisplan](../../../idp_report/version_2/docs/reservoir_port_headway_plan_20260914.md).
Die reale Stationskalibrierung, neue 6-m/s-Fälle und getrennte Terminal-/
Zweirichtungsanschlüsse bleiben ihre eigenen Aufgaben. Die Änderung ist eine
Präzisierung der angenommenen Physik, keine neue Suchstrategie.
