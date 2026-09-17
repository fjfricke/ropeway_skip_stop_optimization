# Erster freigegebener Journey-Block

Gestartet am 15.09.2026 um 10:00 Uhr (Europe/Berlin), ausdrücklich durch „dann let’s go“.

- T5R/G500/P0, F2/F3/F4, 15-s-Freigaben; No-Wait.
- N=151/360/772, jeweils K=10/15/23, Seed 0.
- Labelled Arc-Flow, All-Stop und Skip-Stop bei gleichen festen Starts, vollständige Bedienung erforderlich.
- Keine importierten oder automatisch erzeugten All-Stop-Startpläne.
- 18 mögliche Stufen, je höchstens 300 s einschließlich Aufbau/Abschluss.
- Gesamtdeadline 5.700 s: 90 Minuten nominelle Stufen plus fünf Minuten gemeinsame Reserve.
- Sequenziell, zwölf Threads, höchstens 32 GiB Prozessbaum-RSS; bestehende Speicherdruckkontrolle.
- Zwei aufeinanderfolgende K-Punkte ohne bestätigte vollständige Skip-Stop-Bedienung beenden die betreffende Reihe.

Rohdaten und sofort gesicherter Status: `results/thesis_g500_journey_main_20260915/study.json`.
Manifest: `results/thesis_g500_completion_20260915/journey_ready_manifest.json`; Evidenzhashes beim Start geprüft.
Quellenkopie: `supervision_001/sources.zip` im neuen Ergebnisverzeichnis.
Der read-only Exporter aktualisiert den Thesisatlas während des Laufs.

Die historische Abschlussdokumentation beschreibt den Stand vor diesem Start.
Kapazitätsgruppen und Journey F0 werden in diesem Block nicht ausgeführt.
