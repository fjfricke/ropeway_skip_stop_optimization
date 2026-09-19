# OIP K50: Vorbereitung der Flottensensitivität

Status: **vorbereiten und testen; keine großen Läufe starten**.

## Frage und Vertrag

Kann dieselbe Nachfrage mit 50 statt 62 aktiven Kabinen bedient werden, und
findet die Suche für die Zwischenmischungen häufiger einen gültigen Fahrplan?
Ein Erfolg bei K50 würde keinen Unzulässigkeitsbeweis für K62 liefern.

T5R/G500, geometrische Headways, No-Wait, freie Anfangspositionen, keine
Reservoirabfahrt, Rückkehrpflicht oder anfänglichen Passagiere. Zeitfenster und
Raster bleiben unverändert: 1464 s Nachfrage, 2364 s Bedienung, 2664 s Betrieb;
1 ms Bewegung und 15 s Nachfragefreigaben. Genau 50 Kabinen sind aktiv.

Absolute Nachfragen bleiben F2=2266, F3=5430, F0=7606. Sie stammen aus der
120%-Last der bewiesenen **K62**-CAL-O-Referenz. Sie sind keine 120%-Last einer
K50-Kalibrierung. Der Import prüft zusätzlich sämtliche Nachfragegruppen,
Freigaben und OD-Zuordnungen gegen die eingefrorene abgeschlossene K62-Reihe.

## Matrix und Ausführung

F2 → F3 → F0, jeweils:

| All-Stop | BD / alternierend 0 | CE / alternierend 1 |
|---:|---:|---:|
| 50 | 0 | 0 |
| 38 | 6 | 6 |
| 24 | 13 | 13 |
| 12 | 19 | 19 |
| 0 | 25 | 25 |

Die Anteile sind auf ganze Kabinen angepasst und nicht exakt identisch mit
K62. Jeder Fall optimiert allein Served; Journey Time wird aus dem geprüften
Zertifikat gemessen. Keine Fahrplanhints und **kein früher Referenzabbruch**.
Damit darf die Suche weiter nach Feasibility suchen, selbst wenn eine Schranke
bereits ausschließt, die bisherige K62-Bedienung zu erreichen.

15 sequenzielle Versuche, jeweils höchstens 300 s tatsächliche Gesamtwandzeit
inklusive Vorbereitung, Prüfung und Speicherung; zehn Sekunden Abschlussreserve
innerhalb dieses Budgets. Seed 0, zwölf CP-SAT-Worker, 32 GiB Prozessbaum-RSS.
Maximal 75 Minuten Versuchsbudget plus gemeinsame Vorbereitung. Keine neuen
Referenzsolves; der All-Stop-Kontrolllauf ist bereits eine der fünf Belegungen.
Keine automatische Verlängerung, kein automatischer Start nach Build-only.

Die korrigierte atomare Incumbent-Sicherung, unabhängige Validierung und
Supervisor-Wiederherstellung bleiben aktiv. UNKNOWN und fehlende Incumbents
sind keine Unzulässigkeitsbeweise. Resume prüft Konfiguration und Quellen,
überspringt abgeschlossene Versuche und bewahrt unterbrochene Versuche.

## Frontend und Vergleich

Eigene Kampagne `oip_fixed_mixes_geometric_k50_20260919`. Die Übersicht zeigt
K50-Typzahlen, Bedienung, gemessene Journey Time, Status und Links zu den
bestehenden Live-Detailseiten mit Verlauf und Bounds. Daneben stehen die
jeweiligen K62-Bedienungswerte mit Links zur abgeschlossenen Reihe.

K62 ist ausdrücklich ein Vergleich mit anderer Flottengröße. Seine Zahlen,
Schranken und Zertifikate werden nicht als K50-Start, K50-Baseline oder K50-Bound
in den Solver importiert. Fehlende K50-Werte bleiben leer; die K62-Reihe bleibt
unverändert. Kein zusätzlicher K50-Phasenreferenzlauf ist in dieser Reihe enthalten.

## CLI

```sh
PYTHONPATH=src .venv/bin/python benchmarks/run_oip_fixed_mix_campaign.py \
  --fixed-k 50 \
  --comparison-campaign results/oip_fixed_mixes_geometric_120_20260918 \
  --output results/oip_fixed_mixes_geometric_k50_20260919 \
  --build-only
```

Nach gesondertem Startauftrag derselbe Aufruf mit `--resume` statt `--build-only`.
Die verwendeten K62-Dateien und Code-/Domänen-/Nachfragefingerprints werden im
neuen Manifest eingefroren. Historische K62-Manifeste werden nicht umetikettiert.

## Abnahme

Tests prüfen 15 konkrete Belegungen mit Summe 50, unveränderte K62-Defaults,
CLI-K50 ohne Hint/Referenz/Cutoff, strikten Nachfrageimport und Build-only ohne
Solverstart. Frontendtests trennen K50-Platzhalter von vorhandenen K62-Werten.
Der reale Build-only-Schritt verifiziert die K62-CAL-O-Zertifikate erneut und
prüft vollständige Gleichheit der Nachfragegruppen bei der K50-Vorbereitung.

## Ergänzung: regelmäßige K50-Phasenreferenzen

Die Mischungsläufe sind abgeschlossen. Drei zusätzliche Referenzbewertungen
werden separat vorbereitet, noch nicht gestartet: F2/2266, F3/5430, F0/7606,
jeweils genau 50 All-Stop-Kabinen mit regelmäßigen Abständen und frei optimierter
gemeinsamer Phase. Served wird maximiert, Journey Time nur gemessen. Keine neue
Nachfragekalibrierung, keine Änderung oder Wiederholung der 15 Mischungsläufe.

Der vorhandene Gurobi-Phasenzellen-Solver prüft den gesamten gemeinsamen
Phasenraum auf dem Millisekundenraster. Je Fall gelten 300 Sekunden tatsächliches
Budget einschließlich Vorbereitung und Export, mit zehn Sekunden Abschlussreserve,
zwölf Threads, Seed 0 und 32 GiB Prozessbaum-RSS. Drei sequenzielle Versuche ergeben
höchstens 15 Minuten Einzelbudgets zuzüglich gemeinsamer Vertragsprüfung.

Originalkampagne und eingefrorene Nachfragegruppen werden per Hash gebunden.
Ein eigener Ausgabeordner bewahrt Versuche und Fortsetzungen; nur der
Frontend-Snapshot der K50-Seite erhält eine ergänzende Referenztabelle.
Die ursprüngliche `campaign.json`, ihre Ergebnisse und Schranken bleiben unverändert.
Schranken der Ergänzung gelten ausschließlich für die regelmäßige Phasenreferenz.
Fehlende Zertifikate liefern keinen Bedienungswert; UNKNOWN und Ressourcenabbrüche
werden nicht zu Unzulässigkeitsbeweisen. Kein Referenzwert wird nachträglich als
Start oder Abbruchkriterium der bereits abgeschlossenen Mischungen verwendet.

```sh
PYTHONPATH=src .venv/bin/python benchmarks/run_oip_k50_phase_references.py \
  --source-campaign results/oip_fixed_mixes_geometric_k50_20260919 \
  --output results/oip_k50_phase_references_20260919 --build-only

# Erst nach Startauftrag, dieselben Pfade:
PYTHONPATH=src .venv/bin/python benchmarks/run_oip_k50_phase_references.py \
  --source-campaign results/oip_fixed_mixes_geometric_k50_20260919 \
  --output results/oip_k50_phase_references_20260919 --run --resume
```
