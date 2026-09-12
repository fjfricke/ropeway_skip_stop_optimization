# Stop/Skip-Mustersuche mit freiem Timing

Stand: 2026-09-10. Implementierter Pilot. Screening bestanden; lange Vergleichskampagne auf Nutzerwunsch pausiert.

## Fragestellung und Geltungsbereich

Findet eine äußere Mustersuche schneller gute Fahrpläne als die globale CP-SAT-Suche,
wenn ein inneres Oracle ausschließlich Stop/Skip fixiert und Timing, Exit-Warten,
Ressourcenreihenfolgen und ganzzahlige Passagierzuordnung weiter optimiert?

Zunächst **unbediente Personen minimieren**, ohne Journey-Time-Tie-Break. Journey Time
bleibt Bestandteil des exportierten physikalisch/passagierseitig geprüften Zertifikats,
ist aber weder Suchziel noch Capacity-Bound. Keine periodischen Muster und kein Reservoir.

Vergleichsdomäne: `five_station_circle_cw_half_skip_no_wait_headway_b_v0`, feste
Balanced-Reference-Startpositionen, exakt K=38 bzw. K=39, acht Plätze, H=1200 s,
maximales Exit-Warten W=1200 s, Zeitgitter 1 µs, verschachtelte Nachfrage N=3074.
Dies sind 120 % der nachgewiesenen Kapazität **eines festen All-Stop-38-Fahrplans**
(2561 Personen), kein Nachweis eines globalen All-Stop-Maximums.

## Architektur und Dateien

- `src/ropeway_skip_stop_optimization/optimization/ddd/pattern_search.py`:
  `StopPattern`, `PatternEvaluation`, `PatternTimingOracle`, `PatternNeighborhoods`,
  `PatternVnsConfig`, `PatternVnsOptimizer`.
- `src/ropeway_skip_stop_optimization/benchmarking/pattern_search.py`:
  Domäne, gemeinsame Seeds, Laufprotokollierung, unabhängige EAN/Gurobi-Nachbewertung,
  Screening-Gate.
- `benchmarks/run_pattern_search.py`: isolierte sequenzielle Einzelprozesse,
  Quellcodearchiv, Screening, bedingte Vergleichskampagne, Ergebnistabelle.
- `tests/test_ddd_pattern_search.py`: Oracle-, Domain-, Hint-, Warte-, Aktivierungs-,
  Cache-, Suchsteuerungs-, Gate- und unabhängige Passagiertests.

Vorhandene CP-Bewegungs- und Passagierbuilder sowie Zertifikatsprüfer werden verwendet.
Der globale Capacity-Solver wird durch den Piloten nicht geändert.

## Inneres Oracle

1. Gemeinsames vollständiges Modell einmal pro VNS-Lauf bauen, ohne Journey-Time-Produkte.
2. Muster enthält pro Kabine und strukturellem Besuch eine Route. Der Domain-Hash
   verhindert Cache-Wiederverwendung für andere Starts, Nachfrage oder Zeitgitter.
3. Modell klonen; für jede gewählte Route `route_selected == visit_active` ergänzen.
   Damit bleiben Besuchsaktivierung, Endhorizont und alle Zeit-/Wartevariablen frei.
   Nicht im Seed vorkommende strukturelle Besuche erhalten zunächst STOP.
4. Normales CP-SAT mit 12 Workern; keine Änderung seiner internen Suchalgorithmen.
   Über Mustergrenzen werden nur Zeitwerte als unverbindliche Hinweise verwendet.
5. Nur ein zum Muster passendes, unabhängig validiertes Zertifikat darf als Incumbent
   übernommen werden. **Keine Zielfunktionsschranke des vorherigen Musters übernehmen.**
6. Standardbudget 5 s einschließlich Klonen; Solver erhält das Restbudget.
   Zertifikatsprüfung kann weich darüber hinauslaufen und wird separat gemessen.
7. UNKNOWN bleibt unbekannt und wird nach jeweils fünf neuen Auswertungen höchstens
   einmal mit 15 s erneut versucht. Ein neues bestes FEASIBLE-Muster wird einmal mit
   15 s nachoptimiert. Gesamtbudget und 10-s-Finalisierungsreserve begrenzen Aufrufe.
8. Cache speichert bestes validiertes UB, stärkstes lokales LB, Anzahl und kumulierte Zeit.
   Nur vollständige bewiesene INFEASIBLE-Muster werden ausgeschlossen; keine kleinen
   Konfliktkerne oder generalisierten Cuts im Piloten.

**Ein Muster-LB gilt nur für dieses Muster.** Der VNS-Bericht setzt das globale Capacity-LB
auf 0. Nur ein Fahrplan mit 0 unbedienten Personen beweist globale Capacity-Optimalität.

## Äußere Suche

Die Suche hält aktuellen Zustand, bisher besten Zustand und einen Pool von fünf Mustern
getrennt. Auswahl von OD-Gruppen wird durch die aktuelle unbediente Nachfrage gewichtet.

- N1: Ein kanonisches Ride-Angebot auswählen, Ein- und Ausstieg auf STOP setzen.
- N2: Dieselbe OD-Bedienung auf eine andere Kabine verlagern: Empfänger an beiden
  Endpunkten STOP, beim tatsächlich genutzten Spender einen Endpunkt auf SKIP setzen.
- N3: Zeitlich nahe, gemeinsame Ressourcen nutzende Kabinen auswählen; Gruppenbreite
  2/4/8, maximal zwei Änderungen pro Kabine im OD-Zeitband. Empfängerendpunkte schützen.

Duplikate und ausschließlich inaktive Änderungen werden verworfen. Nach fünf ausgewerteten
Nichtverbesserungen nächstes Neighborhood; strikte Verbesserung setzt auf N1 zurück.
Gleich gute Kandidaten dürfen den aktuellen Zustand ändern. Nach N3 Pool-Neustart oder
schlechterer gültiger Shake, während das beste Ergebnis erhalten bleibt. Nach 50 erfolglosen
Generierungsversuchen `SEARCH_STALLED`. Nach 15/30 solchen Versuchen bereits zum nächsten
Neighborhood wechseln: Ein ausgeschöpftes N1 darf N2/N3 nicht unerreichbar machen.

## Tests und experimenteller Entscheid

- [x] No-Wait-Tiny-Muster gegen vollständig enumerierte Bewegungen und feste Zuordnung.
- [x] Zusätzliches Warten bedient späte Nachfrage; Stop/Skip bleibt gleich.
- [x] Unterschiedlich lange aktive Besuchspräfixe bei gleichem Stop-Muster zulässig.
- [x] Schlechteres Muster trotz besserem Seed weiterhin zulässig.
- [x] UNKNOWN erneut prüfbar, Cache/Domain korrekt, lokale Bounds niemals global.
- [x] Reproduzierbare Operatoren, Neighborhood-Wechsel und Retry-Steuerung.
- [x] Unabhängige ganzzahlige EAN/Gurobi-Zuordnung stimmt auf Tiny-Instanz überein.
- [x] Vorhandene integrierte CP-SAT- und Capacity-Regressionen: zusammen 38 Tests bestanden, einschließlich Snapshot- und Berichtstests.
- [x] Screening K38/K39, je 120 s: zusammen mindestens 10 verschiedene Muster und
  mindestens 2 veränderte gültige Muster. Erreicht: 40 verschiedene, 2 veränderte gültige Muster.
- [ ] Nach bestandenem Gate gestartet, später pausiert: K38/K39 × Seeds 0/1 × VNS/global CP-SAT, je 900 s,
  sequenziell mit 12 Workern. Reihenfolge bei Seed 1 umkehren. Unabhängige finale
  Passagierauswertung für beide Verfahren zusätzlich und getrennt ausweisen.
- [ ] Vergleich der UB-Zeitkurven, Zeit bis zum Zielwert, Modellbau, Oracle-Median/p95,
  UNKNOWN/INFEASIBLE-Anteile, Mustervielfalt und Peak-RSS.

Beide Verfahren starten je K vom gleichen eingefrorenen End-Incumbent der abgeschlossenen
Kapazitätskampagne: K38 U=315, K39 U=1426. Keine Übernahme von Verbesserungen des Screenings
als einseitiger Startvorteil. Vorbereitung wird vom jeweiligen Suchbudget abgezogen.

Vielversprechend erst, wenn für mindestens ein K **beide** VNS-Seeds ein besseres finales UB
erreichen oder den jeweiligen finalen CP-SAT-Wert in höchstens halber Laufzeit erreichen.
Sonst Ergebnis als negativ oder unentschieden berichten; keine automatische Erweiterung
auf ALNS, ML oder Benders.

## Reproduzierbarkeit und parallele Arbeit

Während der Umsetzung wurde in einem anderen Task die gemeinsame CP-Formulierung verändert.
Deshalb nutzt das Experiment den vorhandenen `fixed_start_capacity_20260910/source_snapshot.tar.gz`
plus die neuen Pilotdateien. Die Laufbasis liegt in
`benchmarks/output/pattern_search_runtime_20260910/`. Der Worker erhält einen absoluten
PYTHONPATH auf diese Kopie. Im Arbeitsrepository verbleiben sämtliche parallelen Änderungen.

Ergebnisse des gültigen Starts: `benchmarks/output/pattern_search_20260910_v2/`.
Ein erster Start unter `pattern_search_20260910/` wurde wegen eines relativen PYTHONPATH vor
Ergebnissen abgebrochen und ausdrücklich als ungültig markiert.

```sh
.venv/bin/python benchmarks/run_pattern_search.py \
  --stage auto --output-dir benchmarks/output/pattern_search_NEW
```

Die CLI überschreibt keine bestehenden Experimentordner. `--stage screen` führt nur das
Screening aus; `--stage job --cabins 38 --method vns --seconds 120` einen einzelnen Lauf.
Für Wiederholung der eingefrorenen Basis deren CLI und absoluten PYTHONPATH verwenden.

## Screeningbefund und laufende Auswertung

K38 bleibt bei U=315 (25 Muster, kein geändertes gültiges Muster). K39 erreicht U=1418
statt 1426 (15 Muster, zwei geänderte gültige Muster). Die acht Personen Verbesserung
stammen bereits aus der Timing-Nachoptimierung des ursprünglichen Musters, nicht aus
einer neuen Stop/Skip-Belegung. Beide Endfahrpläne unabhängig durch EAN/Gurobi bestätigt.

Der Bericht `docs/findings/ddd_pattern_search_20260910.md` wird nach abgeschlossenen
Läufen und nach Kampagnenende aus den Resultaten aktualisiert. Rohresultate bleiben
unverändert. `pattern_search_report.py` prüft gepaarte Domänen und unterscheidet
echte Beschleunigung von einem unverändert übernommenen gemeinsamen Seed.

Die aktuelle CLI extrahiert ihren Quellcodesnapshot zusätzlich in einen eigenen
Runtime-Ordner und startet sämtliche Worker von dort. Die bereits laufende Kampagne
nutzt die zuvor manuell eingefrorene Runtime mit derselben Oracle-/VNS-Implementierung.
Die spätere Erweiterung betrifft ausschließlich Startisolierung und Berichterstattung.

Fortsetzung: `ddd_pattern_oracle_diagnostic.md`. Der längere Einzeltest beweist das ursprüngliche K38-Muster bereits nach 24,03 s optimal (U=LB=315). Die früheren 5-s-UNKNOWN-Ergebnisse waren dafür nicht aussagekräftig.
