# Liniengruppen-Pilot: Umsetzung und laufende Messung

Stand: 16.09.2026, Pilot gestartet; noch keine abgeschlossene Performanceaussage.
Vertrag: [Plan](../plans/reservoir_evolution_line_groups_20260916.md).

Die bisherige Stage-2-Kampagne wurde auf Nutzerwunsch gestoppt. Fünf abgeschlossene
Versuche und der unterbrochene sechste bleiben in
`results/thesis_evo_stage2_lexicographic_20260916` erhalten; kein automatisches Resume.

## Prüfungen

77 gezielte Tests bestanden: neue Linienoperatoren, Evolution, Intervall-Decoder,
Gruppenauswahl, Kampagnenweitergabe und Ergebnisdarstellung. Ein freier kleiner
Suchfall mit positiver, unabhängig validierter Bedienung bestand ohne Timing-Solver.
Frontend-Produktionsbuild erfolgreich. Das Live-Dashboard zeigt den neuen Versuch,
21 erlaubte Muster und den Modus gemeinsamer Linienänderungen.

Die T5R/F3-Vorbereitung liefert 21 relevante Muster und 42 Templates gegenüber
sechs Mustern und zwölf Templates im bisherigen OD-Endpunktkatalog.
Keine neue Zeitdiskretisierung und keine Aufzählung von Dispatchzeitpunkten.

## Messartefakte

- Eingefrorener Manifest: `results/thesis_line_groups_pilot_manifest_20260916.json`.
- Resultate/Verläufe: `results/thesis_line_groups_pilot_20260916`.
- Code-Snapshot: `supervision_001/sources.zip` im Pilotordner.
- Je Versuch: Vorbereitung, `events.jsonl`, Checkpoints und `result.json`.
- Laufreihenfolge: `line_groups`, danach `independent`, jeweils `relevant`, 300 s.
- Gesamtlimit 720 s, Prozessbaumlimit 32 GiB; Start via LaunchAgent.

## Erste Beobachtung, ausdrücklich vorläufig

Die neue Initialisierung erzeugte nach etwa 8,8 Suchsekunden einen gültigen
All-Stop-Plan mit 5.070 bedienten Personen. Der Fahrplan war kein importierter
Seed. Das ist ein Initialisierungsergebnis und noch keine Skip-Stop-Verbesserung.
Es liegt über der bisherigen F3-Endbedienung 3.710 aus dem OD-Endpunktlauf,
belegt aber weder die Wirkung der neuen Mutationen noch das Erreichen der
phasenoptimierten All-Stop-Kapazität 7.153.

Endwerte, Herkunft späterer Verbesserungen und der Kontrolllauf sind zum
Dokumentationszeitpunkt ausstehend. Ein einzelner Seed erlaubt keine robuste
allgemeine Performanceempfehlung.
