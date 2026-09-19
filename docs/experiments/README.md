# K50: ergänzende regelmäßige All-Stop-Referenzen vorbereitet

Drei zusätzliche Phasenbewertungen bei unveränderter Nachfrage (F2 2266,
F3 5430, F0 7606), K50 und je fünf Minuten. Noch nicht gestartet. Eigener
Runner `benchmarks/run_oip_k50_phase_references.py`; CLI und Vertrag im
[K50-Plan](../plans/oip_k50_fleet_sensitivity_20260919.md#ergänzung-regelmäßige-k50-phasenreferenzen).
Die abgeschlossenen Mischungen bleiben unverändert; die K50-Seite zeigt die
Referenzen separat. Keine neue Nmax-Kalibrierung.

# Ergänzung: K50-Flottensensitivität vorbereitet

[Plan und CLI](../plans/oip_k50_fleet_sensitivity_20260919.md): 15 No-Wait-Läufe,
K50 bei denselben absoluten Nachfragen wie K62, ohne frühen Referenzabbruch.
Eigene Kampagne und Frontendvergleich mit K62. **Noch nicht gestartet.**

# Aktuelle OIP-Reihe: 15 feste Mischungen

[Verbindlicher Plan und CLI](../plans/oip_fixed_mixtures_120_20260918.md).
T5R/G500, K62, No-Wait, geometrische Headways (Seil 1,053 s, Plattform 11,667 s).
Keine Sonderressourcen an Weichen. F2/F3/F0 erhalten 2266/5430/7606 Personen,
je fünf Mischungen: 62/0/0, 46/8/8, 30/16/16, 16/23/23 und 0/31/31.

CAL-O ist für alle drei Familien abgeschlossen (1888/4525/6338).
Die begrenzte Äquivalenzprüfung und erneute Zertifikatsprüfung dokumentieren die
Übernahme in den neuen Vertrag. Drei neue regelmäßige All-Stop-Bewertungen
verwenden danach dieselbe 120%-Nachfrage wie die Experimente.

Pro Referenz und Mischung maximal 300 s gesamte Wandzeit, darin 10 s
Abschlussreserve; ursprünglich höchstens 90 Minuten für die 18 Solves; die zwei später autorisierten Ersatzversuche erhielten zusätzlich je fünf Minuten.
Served ist das einzige Ziel; Journey Time wird gemessen. Keine Fahrplanhints.
**Abgeschlossen am 19.09.2026:** alle 15 Fälle abgearbeitet; zwei unterbrochene F3-Versuche wurden ausdrücklich als Ersatzversuche wiederholt.
[Abschlussbericht und vollständige Ergebnismatrix](../results/oip_fixed_mixtures_geometric_20260919.md).
F2 und F3 erreichen mit reinen Skip-Stop-Typen Vollbedienung; F0 bleibt bei Mischungen teilweise ungeklärt. Weitere Läufe sind nicht vorgesehen.

Historischer Vorbereitungsaufruf (der Ergebnisordner existiert bereits):

```sh
PYTHONPATH=src .venv/bin/python benchmarks/run_oip_fixed_mix_campaign.py \
  --output results/oip_fixed_mixes_geometric_120_20260918 --build-only
```

# Journey-Reihen: laufende Kampagne (19.09.2026)

**Vorläufig reduzierte Ausführung:** K15/K25 werden auf Nutzerwunsch in beiden
Vergleichsreihen zurückgestellt. Damit laufen 48 relative Vergleiche (K10/20/30)
und 16 konstante Vergleiche (K20/30). Die 20 bereits abgeschlossenen
Kalibrierungen bleiben erhalten, einschließlich K25 als zusätzlichem
Feasibilitätsnachweis. Die vollständige geplante Matrix steht weiterhin unten.
Zurückgestellte Fälle starten nicht automatisch bei Wiederaufnahme.
Zusätzlich sind die fünf noch nicht gestarteten F0-Skip-Stop-Vergleiche
zurückgestellt (relativ K20/75 %, K30/25 % und K30/75 %; konstant K20/K30).
Fertige F0-Ergebnisse bleiben erhalten. Damit umfasst die aktive Auswahl
59 Vergleichsläufe. `control.json` erlaubt dem Controller, ungestartete Fälle
zwischen den Läufen zurückzustellen; laufende Versuche bleiben unverändert.

F0/F2/F3/F4, T5R/G500, geometrische Headways (v3), feste ausgeglichene Starts,
No-Wait und Vollbedienung. Nachfrage bis 1464 s, Bedienung bis 2364 s,
Weiterfahrt bis 2664 s. Minimiert wird Journey Time mit Labelled Arc-Flow.

- **20 Kalibrierungen:** je Familie K10,15,20,25,30; exakte All-Stop-N/N+1-Nachweise.
- **80 relative Vergleiche:** dieses Raster × 25/75 % der jeweiligen Kapazität × All-Stop/Skip-Stop.
- **24 konstante Vergleiche:** K20,25,30 × All-Stop/Skip-Stop bei `floor(0.5*Nmax(K30))`.
  Die verschachtelte Nachfrage muss durch die neuen Referenzen bei allen drei K
  vollständig bedienbar sein. Fehlende oder zu kleine Kapazitäten sperren die
  konstante Reihe dieser Familie; UNKNOWN ist kein Unzulässigkeitsbeweis.

124 Jobs, je höchstens 1800 s einschließlich Aufbau; zwölf Threads, Seed 0,
32 GiB, sequenziell. Vergleiche enden auch bei 1 % Gap. Kein Fahrplanhint.
Maximal 62 Stunden Einzelbudgets plus 30 Minuten Kampagnenreserve.

```sh
.venv/bin/python benchmarks/run_thesis_revised_journey_campaign.py \
  --output-dir results/thesis_journey_geometric_20260919 --build-only
# Erst nach gesonderter Startentscheidung:
.venv/bin/python benchmarks/run_thesis_revised_journey_campaign.py \
  --output-dir results/thesis_journey_geometric_20260919 --resume --run
```

Vorbereitung startet keinen Solver. Live-Export standardmäßig nach
`frontend/public/generated` (änderbar mit `--frontend-root`). Die Übersicht
`/optimization/<Ordnername>` zeigt Referenzgates, native Incumbents, bestätigte
Journey Time, Lower Bounds und Gap; Detailverläufe sind ab dem ersten Export
verlinkt. Unbekannte Werte bleiben leer. Historische Dateien bleiben erhalten.
Wiederaufnahme prüft Quellcode/Vertrag und erneuert die Gesamtdeadline nicht.

Die folgenden Abschnitte dokumentieren **historische Reihen und frühere Pläne**.
Ihre Headways, F0-Sperren und Referenzen sind keine Vorgaben für diese neue Reihe.
Vorhandene Journey-Ergebnisse bleiben unverändert; keine automatische Neuberechnung.

# Historie: OIP-Referenzkorrektur (18.09.2026)


**Template-Korrektur:** Der No-Wait-Pfad besitzt jetzt einen eigenständigen
Bewegungsbuilder. Die gespeicherten F2/F3-K62-Starts wurden darin vollständig
reproduziert und unabhängig geprüft. Die Vergleichskampagne bleibt gestoppt.
[Änderung und Testergebnisse](../results/oip_nowait_template_repair_20260918.md).

Für neue OIP-Läufe gilt die [exakte kurze Phasenreferenz](../plans/oip_exact_phase_reference_20260918.md).
Die alten CAL-O-Kapazitäten und die fünfphasigen OIP-Starts sind dafür keine bewiesenen Kapazitätsreferenzen.
Zunächst werden F2/F3/F0 bei K62 kalibriert; danach ist `ceil(1.2*Nmax)` vorgesehen.
Die vorherige Hauptreihe ist pausiert. Neue Hauptläufe starten separat.

```sh
.venv/bin/python benchmarks/run_oip_phase_calibration.py \
  --output results/oip_exact_phase_short_k62_20260918 \
  --frontend frontend/public/generated/calibration
```

`--build-only` erzeugt nur das Manifest. `--resume` setzt dieselbe Konfiguration fort.
Live-Ansicht: `/calibration-live`. Jede Familie erhält höchstens 30 Minuten.

Nach drei bewiesenen Referenzen bereitet der folgende Runner den kontrollierten
Served-only-Vergleich vor. Er verwendet `ceil(1.2*Nmax)`, K62, No-Wait und
denselben All-Stop-Start für beide Formulierungen. Journey Time wird gemessen,
nicht optimiert.

```sh
.venv/bin/python benchmarks/run_oip_nowait_formulation_comparison.py \
  --output results/oip_nowait_formulation_comparison_20260918 \
  --build-only

.venv/bin/python benchmarks/run_oip_nowait_formulation_comparison.py \
  --output results/oip_nowait_formulation_comparison_20260918 \
  --resume
```

Der erste Aufruf verweigert das Manifest, solange F0, F2 oder F3 kein
bewiesenes N/N+1-Intervall besitzt. Die sechs Hauptläufe dauern jeweils
höchstens fünf Minuten; die drei gemeinsamen Referenzstarts ebenfalls höchstens
fünf Minuten. Alte lexikografische Typkatalogläufe werden nicht fortgesetzt.

Ein ausdrücklich begrenzter Teilvergleich darf nur bereits bewiesene Familien
enthalten. Beispielsweise erzeugt `--families f2 f3` vier Hauptläufe und zwei
Referenzstarts; F0 bleibt darin sichtbar ausgeschlossen und blockiert diese
eigenständige Kampagne nicht.

# Thesis-Versuchsreihen

Stand: 17.09.2026. Diese Seite ist der zentrale Einstieg für die neu zu
berechnenden Thesis-Ergebnisse. Sie dokumentiert den vereinbarten Umfang und
trennt ihn von bereits vorhandenen CLI-Funktionen. Alte Pilotbefunde bleiben
unter ihrem ursprünglichen Vertrag erhalten; sie ersetzen keine neue Referenz.

## 1. Laufgruppen und Reihenfolge

| Kennung | Zweck | Nachfragefamilien | Kabinen | Anzahl | Stand |
|---|---|---|---|---:|---|
| CAL-J | All-Stop-Kapazität bei festen Starts | F0, F2, F3, F4 | 10, 15, 20, 25, 30, 31 | 24 | Separater Kalibrierungscontroller vorhanden |
| CAL-O | All-Stop-Kapazität mit freier gemeinsamer Phase | F0, F2, F3 | geometrisch ermitteltes K_AS,max | 3 | Separater Kalibrierungscontroller vorhanden |
| J-REL | Journey Time bei mit K skalierter Nachfrage | F0, F2, F3, F4 | 10, 15, 20, 25, 30 | 80 | Im Journey-Kampagnenrunner enthalten |
| J-CONST | Journey Time bei unveränderter Nachfrage | F0, F2, F3, F4 | 20, 25, 30 | 24 | Im Journey-Kampagnenrunner enthalten |
| OIP | Feste Muster und Flotten vergleichen | F0, F2, F3 | endgültiges Raster offen | offen | Screeningrunner vorhanden; neue Referenzen fehlen |

**Zuerst alle 27 Kalibrierungen ausführen und auswerten.** Danach werden die
gewünschten Vergleichsgruppen ausdrücklich gestartet. Ein abgeschlossener
Kalibrierungsversuch bedeutet nicht automatisch eine bewiesene Kapazität.
Ungeklärte Referenzen blockieren nur ihre abhängigen Vergleiche.

```text
CAL-J: 24 feste All-Stop-Starts ──→ J-REL: 80 Vergleiche
                              └─→ J-CONST: 24 Vergleiche
CAL-O: 3 All-Stop-Phasenreferenzen → OIP-Musterscreening → ggf. Nachoptimierung
```

F4 bleibt in den Journey-Reihen enthalten. Im OIP-Musterscreening wird das
rein lokale Profil entsprechend der Vereinbarung ausgeschlossen. Evolution,
Reservoirpiloten, Waiting-Ablationen und Greedy-Vergleiche sind keine automatisch
angehängten Jobs dieser Matrix. Neue Vergleiche benötigen einen eigenen Umfang
und dasselbe eingefrorene Szenario.

## 2. Gemeinsamer physikalischer Vertrag

| Einstellung | Wert |
|---|---|
| Geometrie | T5R/G500, fünf Stationen |
| Weichenschutz | Architektur B: STOP-Leader-Schutz an Ein- und Ausfahrt |
| Geschwindigkeiten | Seil 6 m/s, Plattform 0,3 m/s |
| Anfangsbeladung | keine Passagiere |
| Betriebsart | Anfangsaufstellung, kein Reservoir, keine Rückkehrpflicht |
| Zeitprofil | P0, deterministisch, Freigaben im 15-s-Raster |
| Nachfragefenster | zwei All-Stop-Umläufe: derzeit 1464 s |
| Bedienungsabschluss | weitere 900 s; Bedienung bis 2364 s |
| Weiterfahrt | weitere 300 s; Betrieb bis 2664 s |
| Waiting | zunächst aus |
| Bewegungsraster | Journey: Mikrosekunden; OIP: konservative Millisekunden |

Die Fenster werden aus der gemeinsamen Geometrie abgeleitet; der aktuelle
All-Stop-Umlauf beträgt 732 s. Begonnene Bewegungen und relevante Schutzintervalle
werden am Betriebsende vollständig geprüft. Die Weiterfahrt ist eine endliche
Betriebsgarantie, kein Beweis unbegrenzter periodischer Machbarkeit.

Vertragsquelle: [thesis_contract.py](../../src/ropeway_skip_stop_optimization/benchmarking/thesis_contract.py).
Vertragskennung: `t5r_g500_b_entry_exit_2cycles_900completion_300tail_v2`.
Identische Geometrie bedeutet nicht identische Anfangsbedingungen: Die Journey-
Reihen fixieren die Starts; OIP darf die einzelnen Anfangspositionen optimieren.

## 3. Nachfragekalibrierung

### CAL-J: feste Anfangspositionen

Für jede Kombination aus Familie F und K wird die größte vollständig bedienbare
verschachtelte Nachfrage `N_AS,fixed(F,K)` bestimmt. Die Kabinen stehen
ausgeglichen und fest, halten überall und fahren ohne Waiting.

Ein exakter Abschluss benötigt eine unabhängig geprüfte vollständige Bedienung
bei N und einen gültigen Unzulässigkeitsnachweis bei N+1. Ein Timeout ist kein
Unzulässigkeitsnachweis; ohne beide Seiten wird nur ein offenes Intervall exportiert.

### CAL-O: regelmäßige Flotte mit freier gemeinsamer Phase

Für F0/F2/F3 wird `N_AS,phase(F,K_AS,max)` unter demselben kurzen Vertrag bestimmt.
Alle Kabinen halten überall. Ihre regelmäßigen Abstände bleiben erhalten; die
gemeinsame Phase und die ganzzahlige Passagierzuordnung werden optimiert.

`K_AS,max` wird unter der korrigierten Geometrie aus den physikalischen
Schutzbedingungen ermittelt und durch eine gültige regelmäßige Bewegung geprüft.
Die frühere Zahl 62 wird nicht ungeprüft übernommen. Diese Referenz ist weder
ein Kapazitätsoptimum über frei wählbare Einzelpositionen noch eine allgemeine
Obergrenze für die Skip-Stop-Flotte.

Beide Kalibrierungsarten haben getrennte Referenzkennungen. Eine feste Startphase
darf nicht als phasenoptimierte Referenz verwendet werden. Das bloße Vorhandensein
eines Runners namens `all_stop_phase` belegt dessen Startvertrag nicht.

## 4. Journey-Vergleiche

Beide Reihen verwenden Labelled Arc-Flow mit genau K Kabinen. Pro Nachfragefall
werden All-Stop und freie STOP/SKIP-Entscheidungen bei identischen festen Starts
verglichen. Vollständige Bedienung ist vorgeschrieben; minimiert wird Journey
Time. Unzulässigkeit bedeutet hier, dass die verlangte Vollbedienung nicht
möglich ist, sofern sie tatsächlich bewiesen wurde.

- **J-REL:** Nachfrage `floor(0.25 × N_AS,fixed(F,K))` und
  `floor(0.75 × N_AS,fixed(F,K))`.
  4 Familien × 5 K-Werte × 2 Lasten × 2 Betriebsarten = **80 Läufe**.
- **J-CONST:** Nachfrage `floor(0.50 × N_AS,fixed(F,31))`, unverändert für
  K=20,25,30. 4 Familien × 3 K-Werte × 2 Betriebsarten = **24 Läufe**.

K31 ist ausschließlich die Nachfragebasis der konstanten Reihe. Diese verwendet
keine halbe Nachfrage des jeweils untersuchten K und auch nicht die OIP-Referenz.
Ein auf null abgerundeter Nachfragefall wird als solcher blockiert.

## 5. OIP-Musterscreening

### Gemeinsame Typkatalogkampagne

Die aktuelle Folgekampagne vergleicht den allgemeinen EAN-Builder mit dem
affinen No-Wait-Templatebuilder. Beide wählen bei K62 je Kabine einen Typ sowie
freie Anfangspositionen und maximieren die Bedienung. Die Nachfrage beträgt je
Familie `ceil(1.2*Nmax)` der bewiesenen kurzen Phasenreferenz. Details und CLI:
[No-Wait-Formulierungsvergleich](../plans/oip_joint_cabin_type_campaign_20260918.md).

Die frühere lexikografische Typkatalogkampagne mit den absoluten Last-B-Werten
ist ein historischer Pilot und wird nicht fortgesetzt.

Bestätigt sind zwei Laststufen je Familie: **100 % und 110 %** der jeweiligen
CAL-O-Kapazität. Die Nachfrage beträgt `N_AS,phase` beziehungsweise
`ceil(11 × N_AS,phase / 10)` und bleibt innerhalb jeder Familie und Laststufe
über alle K und Musterbelegungen identisch. Das ausgeführte Screeningraster ist
K40/50/62. Beide Laststufen wurden als getrennte Kampagnen vollständig
ausgeführt.

Pro Belegung werden genau K aktive Kabinen modelliert. Die Stationsmasken sind
fest; Anfangspositionen und räumliche Reihenfolge bleiben frei. CP-SAT sucht
zunächst eine zulässige Bewegung ohne Fahrplanhint. Anschließend optimiert der
feste Gurobi-Passagier-IP lexikografisch Unserved und dann Journey Time einschließlich
Unserved-Strafe. Diese Nachbewertung ist nur für die gefundene Bewegung optimal.

Der vorhandene Controller unterstützt danach eine gesondert protokollierte
gemeinsame CP-SAT-Nachoptimierung. Dafür werden alle Kandidaten mit validierter
zulässiger Bewegung und abgeschlossener Passagierbewertung übernommen. Die
Passagierwerte des jeweils ersten gefundenen Fahrplans dienen nicht zur
Vorauswahl. UNKNOWN und Ressourcenabbrüche werden in dieser Runde nicht
fortgesetzt, gelten aber nicht als unzulässig; bewiesen unzulässige Kandidaten
werden getrennt ausgeschlossen. Screening und Nachoptimierung sind getrennte
Ergebnisstufen; verbesserte Werte werden nicht in den früheren Suchverlauf
zurückdatiert. `--screening-only` schaltet die Nachoptimierung aus.

Gefundene All-Stop-Fahrpläne des Screenings sind Vergleichspunkte, keine neuen
Kapazitätsbeweise. UNKNOWN und Ressourcenabbruch bekommen keinen künstlichen
Bedienungswert null und keinen Machbarkeitsgap.

## 6. Budgets und Ausführung

| Gruppe | Budget und Abbruch |
|---|---|
| CAL-J | 1800 s je Referenz einschließlich Aufbau; exaktes N/N+1 oder offenes Ergebnis |
| CAL-O | Vorschlag: 1800 s je Referenz; noch im neuen Ablauf festzulegen |
| J-REL / J-CONST | 1800 s je Job einschließlich Aufbau; Optimierungsabbruch bei 1 % Gap |
| OIP | Abgeschlossenes Screening: 60 s Bewegung und bis 30 s feste Passagierbewertung; danach 300 s gemeinsame Warmstart-Nachoptimierung für jeden validiert zulässigen Kandidaten |

Seed 0, sequenzielle Jobs, höchstens zwölf Solverworker und 32 GiB
Prozessbaum-RSS. Der feste OIP-Passagier-IP verwendet einen Thread. Für die
Kalibrierung reicht ein Optimierungsgap von 1 % nicht als exakter Kapazitätsnachweis.
Bei 1800 s für alle 27 Referenzen beträgt die Summe der Einzelbudgets 13,5 Stunden;
eine Gesamtreserve muss im Controller zusätzlich explizit ausgewiesen werden.

Die abgeschlossenen Screenings umfassen 108 Kandidaten. Davon besitzen 43 eine
validierte Bewegung und abgeschlossene Passagierbewertung, 61 endeten UNKNOWN
und vier wurden als unzulässig bewiesen. Damit umfasst die nächste Stufe genau
43 gleich budgetierte Nachoptimierungen. Bei 300 s je Kandidat beträgt deren
Budgetobergrenze **215 Minuten**, zuzüglich Orchestrierung und Abschluss. Die
Screeningwerte werden erst nach der Nachoptimierung zum Ranking verwendet.

Die vorhandenen Screeningartefakte werden mit
`benchmarks/run_oip_pattern_refinement_followup.py` fortgesetzt. Der Runner
prüft die unveränderten Quellen, übernimmt den vollständigen validierten
Incumbent nur als Hint und führt ein eigenes fortsetzbares Manifest. Die
ursprünglichen Screeningzeiten und die 300-s-Fortsetzung werden getrennt
ausgewiesen.

## 7. CLI: verfügbar und noch umzusetzen

Alle Befehle werden vom Repository-Stamm ausgeführt. Die folgenden Befehle
bereiten nur vor und starten keine Solverkampagne:

```bash
# Vorhanden: 24 Journey-Referenzen UND 104 Journey-Vergleiche vorbereiten.
uv run python benchmarks/run_thesis_revised_journey_campaign.py \
  --output-dir results/thesis_journey_v2 --build-only

# Vorhanden: OIP-Suite ohne Referenzdatei als pending_calibration vorbereiten.
uv run python benchmarks/run_oip_thesis_pattern_campaigns.py \
  --output results/thesis_oip_v2 --build-only
```

**Reine Kalibrierung ohne Folgeläufe:**

```bash
uv run python benchmarks/run_thesis_calibration_campaign.py \
  --output-dir results/thesis_calibration_v2 --build-only

uv run python benchmarks/run_thesis_calibration_campaign.py \
  --output-dir results/thesis_calibration_v2 --run --resume
```

Der Controller enthält genau 24 CAL-J- und drei CAL-O-Jobs. `--run` startet
keine Journey- oder OIP-Vergleiche. CAL-O ermittelt das physikalische
All-Stop-Flottenmaximum aus der eingefrorenen Geometrie; aktuell sind dies 62
Kabinen. `references.json` wird nach jedem Versuch atomar aktualisiert und
kennzeichnet offene Kapazitätsintervalle ausdrücklich.

**Achtung zur Journey-CLI:** `--run` startet aktuell den gesamten Journey-Ablauf,
einschließlich abhängiger Vergleiche. Einen reinen Modus für die 27 Kalibrierungen
stellt deshalb ausschließlich der obige Kalibrierungscontroller bereit. Alte
`run_thesis_calibration.py`-/G500-Pilotbefehle sind kein Ersatz für diesen Umfang.

Die vorhandene OIP-Suite verlangt zum Start `--calibrated-cases` mit nachweisbaren
CAL-O-Ergebnissen, Hashes und Lastverhältnissen. Direkte technische Screenings
werden standardmäßig als Archiv geführt.

### Vorgesehene saubere Trennung

Diese Schnittstelle ist ein Implementierungsziel, noch kein ausführbarer Befehl:

- Ein Kalibrierungscontroller mit Auswahl `journey`, `oip` oder `all` und
  getrennten Referenzfunktionen für feste Starts bzw. freie gemeinsame Phase.
- Ein Journey-Controller mit Auswahl `relative` oder `constant`, der einen
  eingefrorenen Referenzindex liest und keine Referenzen neu berechnet.
- Der OIP-Controller liest denselben Referenzindex mit explizitem Referenzkind
  und führt nur seine freigegebene Muster-/K-Matrix aus.
- Jeder Controller unterstützt Vorbereitung, expliziten Start, Wiederaufnahme
  und eine eigene tatsächliche Gesamtdeadline. Keine Gruppe startet automatisch
  die nächste. Ein Resume vergibt kein neues Budget.

Gemeinsam bleiben Geometrie, Nachfragegenerator, Validierung, Prozessüberwachung
und Ergebnisexport. Die Solver werden für diese Aufteilung nicht dupliziert.

## 8. Ergebnisse, Frontend und Reproduzierbarkeit

Vorgesehene Ablage je eingefrorener Studienversion:

```text
results/<study-id>/
  manifest.json
  calibration/journey/   # 24 getrennte Referenzen
  calibration/oip/       # 3 getrennte Phasenreferenzen
  references.json        # geprüfte Werte, offene Intervalle, Quellen und Hashes
  journey/relative/
  journey/constant/
  oip/screening/
  oip/refinement/
```

Das ist die Zielstruktur; vorhandene Runner schreiben derzeit jeweils in ihren
eigenen Ausgabeordner. Historische Verzeichnisse werden nicht nachträglich
umetikettiert. Jeder Job speichert Vertrag, Familie, K, Nachfrage, Startpolitik,
Waiting, Raster, Seed, Code-/Solverversionen, Budgets, Status und Zertifikate.
Vergleiche referenzieren die konkrete Kalibrierung einschließlich Inhaltshash.

Im Frontend bleiben Kalibrierung, Journey und OIP unterscheidbar. Aktuelle
Thesis-Evidenz verlangt passende Vertragskennung und Studienzuordnung; ältere
oder explorative Ergebnisse gehören ins Archiv. Schranken gelten ausschließlich
für ihre jeweilige Domäne. Fehlende Nachweise und fehlende Werte bleiben sichtbar.

## 9. Vor dem Start der 27 Referenzen noch erforderlich

1. Build-only-Manifest auf genau 27 Jobs und beide korrekten Startpolitiken
   prüfen; kleine End-to-End-Tests für beide Referenzarten ausführen.
2. Getesteten Codestand sichern, Ergebnisablage und Referenzindex einfrieren.
3. Kalibrierungen ausdrücklich starten; danach offene Intervalle und die
   Freigabe abhängiger Vergleiche auswerten.

Weiterer Kontext: [Umsetzungsplan](../plans/thesis_reruns_and_repository_restructuring_20260917.md).
