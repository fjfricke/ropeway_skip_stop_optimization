# OIP: feste Typmischungen unter geometrischen Headways

Stand 18.09.2026. Dieser Plan ersetzt die früheren F0-Sperren und OIP-Pilotmatrizen.
Umfang jetzt: **implementieren, prüfen und vorbereiten; keine großen Solves starten.**

## Physikalischer Vertrag

T5R/G500, K62, No-Wait, freie Anfangspositionen; keine Reservoirabfahrten,
Rückkehrpflicht oder Anfangspassagiere. Nachfrage 0–1464 s, Bedienung bis
2364 s, Betrieb bis 2664 s. Bewegungsraster 1 ms, P0-Freigaben 15 s.
Die 1464 s stammen aus zwei physikalischen 732-s-Umläufen; die kompositionell
aufgerundeten OIP-Bewegungszeiten ergeben 732,010 s pro All-Stop-Umlauf.

`geometric_shared_entry_exit_v1`: Ein- und Ausfahrt benutzen für STOP und
SKIP denselben Seilheadway (auf dem Raster 1,053 s); beide Plattformereignisse
benutzen 11,667 s. Kein Notstoppaufschlag, keine mechanische 6-s-Ressource.
Historische Architekturvarianten und gespeicherte Ergebnisse bleiben erhalten.
Neue Vertragskennung: `t5r_g500_geometric_2cycles_900completion_300tail_v3`.

## Nachfrage und Matrix

| Familie | bewiesenes CAL-O-Nmax | Versuchsnachfrage ⌈1,2 Nmax⌉ | Typen 2/3 |
|---|---:|---:|---|
| F2 | 1888 | 2266 | BD / CE |
| F3 | 4525 | 5430 | alternierende Phase 0 / 1 |
| F0 | 6338 | 7606 | alternierende Phase 0 / 1 |

Je Familie in folgender Reihenfolge:

| All-Stop | Typ 2 | Typ 3 |
|---:|---:|---:|
| 62 | 0 | 0 |
| 46 | 8 | 8 |
| 30 | 16 | 16 |
| 16 | 23 | 23 |
| 0 | 31 | 31 |

F2 → F3 → F0: genau 15 Mischungsläufe, davor drei regelmäßige All-Stop-
Referenzbewertungen bei der tatsächlichen Versuchsnachfrage. Freie gemeinsame
Phase und Served-Ziel; keine Journey-Time-Nachoptimierung. Ein gültiges
Referenzzertifikat ist Voraussetzung für die betreffende Familie.

## CAL-O-Übernahme

`benchmarking/oip_calibration_reuse.py` prüft Vertrag, Familie, K62, N/N+1-
Nachweise, Raster, Fenster und die ganzzahlige 120%-Berechnung. Vollständige
Nmax-Zertifikate werden im historischen und neuen Modell unabhängig geprüft.
Die regelmäßige Bewegung und der vollständige Phasenraum müssen identisch sein.
Der kleinste zyklische Abstand beträgt 11806 Ticks und übertrifft alle alten
und neuen All-Stop-Anforderungen (höchstens 11667 Ticks). Daher schränkten die
entfernten Anforderungen keine gemeinsame Phase dieser regelmäßigen Flotte ein.
Der Beweis gilt ausschließlich für die regelmäßige No-Wait-All-Stop-Klasse.

Quellhashes, rekonstruierte Fingerprints und Prüfbericht werden unter
`calibration_adoption/` gespeichert und im Manifest eingefroren. Historische
Dateien werden nicht umetikettiert. Allgemeine Checkpointimporte bleiben strikt.
Eine fehlgeschlagene Voraussetzung blockiert die Vorbereitung.

## Modellaufbau

Feste Typzahlen werden vor Modellbau in kanonische Kabinentypen übersetzt.
Je Kabine entsteht ein Template mit freier Zeitverschiebung; Typwahl- und
Zählvariablen sowie unmögliche Passagierfahrten entfallen. Alternierung läuft
über Umlaufgrenzen. Nur identische Typen werden nach Anfangskategorie geordnet.

Alle physischen Prüfstellen bleiben im Artefakt und Zertifikatsprüfer.
Im Solverbuilder dürfen Plattformausfahrt/Plattformeinfahrt und
Stationsausfahrt/nächste Stationseinfahrt durch feste Zeitverschiebung
normalisiert werden. Intervalle werden nur bei identischer Ereigniszuordnung,
Dauer und Präsenz geteilt. Die ursprünglichen `NoOverlap`-Mengen bleiben
getrennt, solange ihre Randaktivierungen verschieden sind. Nur identische
Intervallmengen werden zusammengefasst. Kein ungeprüftes Vereinigen von Mengen.

Anfangsbelegung, Vorgeschichte und Nachlauf behalten zusätzliche Schutzintervalle.
Ein- und Ausfahrt derselben gemischt genutzten Station bleiben getrennt.
Interne Build-Schalter `specialize_fixed_types=False` und `reduce_headways=False`
erlauben Äquivalenz- und Größenvergleiche; historische Regeln bleiben verfügbar.

## Budgets, Ziel und Abbruch

Jeder Lauf erhält höchstens 300 s **insgesamt**, einschließlich Vorbereitung,
Modellbau, Suche, Prüfung und Speicherung. 10 s Abschlussreserve liegen innerhalb
dieses Budgets. Absolute Deadline in Runner und Supervisor, kein 310-s-Budget.
Seed 0, zwölf CP-SAT-Worker, 32 GiB Prozessbaum-RSS, sequenziell, keine Hints.
Journey Time einschließlich Unserved-Strafe wird ausschließlich gemessen.

Gemischte Läufe dürfen bei `UB_served <= geprüfte Referenzbedienung` abbrechen,
auch ohne neuen Incumbent. Der freie All-Stop-Kontrolllauf hat diesen Abbruch
nicht. Timeout, UNKNOWN und Ressourcenabbruch sind keine Unzulässigkeitsbeweise.
Ein Passagierwert erscheint erst nach unabhängiger Zertifikatsprüfung.

## CLI und Abnahme

```sh
PYTHONPATH=src .venv/bin/python benchmarks/run_oip_fixed_mix_campaign.py \
  --output results/oip_fixed_mixes_geometric_120_20260918 --build-only
```

Vorbereitung erzeugt 15 geplante Mischungsläufe und drei geplante Referenzen.
Erst nach ausdrücklichem Startauftrag denselben Aufruf mit `--resume` statt
`--build-only` verwenden. Wiederaufnahme prüft Konfiguration, Code, Nachfrage
und Quellhashes; abgeschlossene Versuche werden nicht wiederholt, unterbrochene
Versuche behalten ihre Dateien. Kein automatischer Start von Journey-Reihen.

```sh
PYTHONPATH=src .venv/bin/python benchmarks/check_oip_model_reductions.py \
  --output results/oip_geometric_build_ablation_20260918.json
```

Die Größenablation baut 30/16/16 für jede Familie in vier Varianten, ohne Solve:
historische Regeln, neue Regeln, fester Aufbau, zusätzliche Intervallteilung.
Sie ist kein Laufzeitvergleich. Kleine endliche Positionsdomänen prüfen
Feasibility und Served-Optimum zwischen den Darstellungen; Randtests und der
vollständige Prüfer bleiben verpflichtend. Der separate Abnahmebericht nennt
Testergebnisse, tatsächliche Einsparungen und Grenzen der Prüfung.

## Korrektur der Ergebnissicherung (19.09.2026)

Ein F3-All-Stop-Lauf erreichte das harte 300-s-Limit vor dem abschließenden
Zertifikatsexport. Live-Zahlen allein werden nicht nachträglich zu geprüften
Ergebnissen erklärt. Die Kampagne wurde zur Korrektur pausiert.

Neue native Incumbents werden während der Suche vollständig als zunächst
ungeprüfte Kandidaten gesichert. Ein Hintergrundprüfer validiert jeweils den
neuesten anstehenden Kandidaten; ältere ungeprüfte Zwischenstände dürfen dabei
übersprungen werden. Das letzte vollständig geprüfte Ergebnis wird mit seinem
Manifest und Frontendexport in einer einzigen atomaren Datei committed. Eine
unterbrochene Prüfung oder Speicherung ersetzt es nicht. Nach einem harten
Supervisorabbruch übernimmt der Controller ausschließlich diesen geprüften Stand,
mit Abbruchgrund und ohne Optimalitätsbehauptung. Ohne geprüftes Zertifikat bleibt
die Bedienung unbekannt. Ein eigener Deadline-Wächter fordert den Solverstopp an;
die zehn Sekunden Abschlussreserve und die harte 300-s-Grenze bleiben unverändert.

Eine explizite Wiederaufnahme mit `--accept-persistence-fix --skip-interrupted`
protokolliert den Codewechsel und setzt nur noch nicht gestartete Versuche fort.
Alle übrigen Konfigurations- und Nachfrageprüfungen bleiben strikt. Abgeschlossene
und unterbrochene Versuche werden nicht wiederholt; die Ergebnisdarstellung muss
den Wechsel des Sicherungspfads und dessen zusätzlichen Prüfaufwand ausweisen.
