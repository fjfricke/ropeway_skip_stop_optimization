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

Bestätigt sind zwei Laststufen je Familie: **100 % und 110 %** der jeweiligen
CAL-O-Kapazität. Die Nachfrage beträgt `N_AS,phase` beziehungsweise
`ceil(11 × N_AS,phase / 10)` und bleibt innerhalb jeder Familie und Laststufe
über alle K und Musterbelegungen identisch. **Das endgültige K-Raster und damit
die Laufanzahl sind noch offen.** K40/50/62 ist bisher nur ein technisches Raster.
Die Suite muss beide Laststufen als getrennte Kampagnen abbilden; bisher liest
sie nur eine Nachfragemenge je Familie ein.

Pro Belegung werden genau K aktive Kabinen modelliert. Die Stationsmasken sind
fest; Anfangspositionen und räumliche Reihenfolge bleiben frei. CP-SAT sucht
zunächst eine zulässige Bewegung ohne Fahrplanhint. Anschließend optimiert der
feste Gurobi-Passagier-IP lexikografisch Unserved und dann Journey Time einschließlich
Unserved-Strafe. Diese Nachbewertung ist nur für die gefundene Bewegung optimal.

Der vorhandene Controller unterstützt danach eine gesondert protokollierte
gemeinsame CP-SAT-Nachoptimierung ausgewählter Kandidaten. Screening und
Nachoptimierung sind getrennte Ergebnisstufen; verbesserte Werte werden nicht
in den früheren Suchverlauf zurückdatiert. `--screening-only` schaltet diese
Nachoptimierung aus.

Gefundene All-Stop-Fahrpläne des Screenings sind Vergleichspunkte, keine neuen
Kapazitätsbeweise. UNKNOWN und Ressourcenabbruch bekommen keinen künstlichen
Bedienungswert null und keinen Machbarkeitsgap.

## 6. Budgets und Ausführung

| Gruppe | Budget und Abbruch |
|---|---|
| CAL-J | 1800 s je Referenz einschließlich Aufbau; exaktes N/N+1 oder offenes Ergebnis |
| CAL-O | Vorschlag: 1800 s je Referenz; noch im neuen Ablauf festzulegen |
| J-REL / J-CONST | 1800 s je Job einschließlich Aufbau; Optimierungsabbruch bei 1 % Gap |
| OIP | Aktuelle technische Defaults: 60 s Bewegung, 30 s Passagiere; Nachoptimierung 180 s für bis zu zwei Kandidaten je K; endgültiges Kampagnenbudget offen |

Seed 0, sequenzielle Jobs, höchstens zwölf Solverworker und 32 GiB
Prozessbaum-RSS. Der feste OIP-Passagier-IP verwendet einen Thread. Für die
Kalibrierung reicht ein Optimierungsgap von 1 % nicht als exakter Kapazitätsnachweis.
Bei 1800 s für alle 27 Referenzen beträgt die Summe der Einzelbudgets 13,5 Stunden;
eine Gesamtreserve muss im Controller zusätzlich explizit ausgewiesen werden.

Planungsrechnung für OIP bei sechs Belegungen und beiden Laststufen:
Pro K-Wert ergeben sich 3 Familien × 2 Lasten × 6 Belegungen = 36 Screenings,
also höchstens 54 Minuten Einzelbudgets. Zwei Nachoptimierungen pro
Familie/Last/K ergänzen bis zu 36 Minuten. Insgesamt sind das **90 Minuten je
K-Wert**, bei drei K-Werten 4,5 Stunden, jeweils zuzüglich Orchestrierungsreserve.
Diese Rechnung ist eine Budgetobergrenze, keine gemessene Laufzeitprognose und
keine Festlegung auf drei K-Werte. Die bisherigen einstündigen Suite-Limits
müssen zur später eingefrorenen Matrix passen; sie garantieren deren Abschluss
nicht automatisch.

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
