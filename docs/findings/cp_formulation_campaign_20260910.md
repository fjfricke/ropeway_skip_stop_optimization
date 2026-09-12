# CP-SAT-/IBM-Formulierungskampagne: abgeschlossene Auswertung

Stand: 10.09.2026. **24 gültige Läufe, keine fehlgeschlagenen Läufe; keine bestätigte Performanceempfehlung und kein Standardwechsel.** Die Varianten bleiben experimentell. Die Kampagne zeigt kleine Verbesserungen gefundener Lösungen, aber keinen Durchbruch bei den globalen Schranken.

## Ausführung und Vergleichbarkeit

Start am 10.09.2026 um 12:20:12, Ende um 13:50:07 (Europe/Berlin). Tatsächliche Kampagnenzeit 5.395,296206 Sekunden, etwa 89 Minuten 55 Sekunden, unter dem Limit von zwei Stunden. Zuvor 555,750 Sekunden separate Wartezeit hinter der vorherigen Kampagne. Sechzehn Screeningläufe mit jeweils 180 Sekunden und Seed 0; acht Bestätigungsläufe mit jeweils 300 Sekunden und Seeds 1/2. Alle Läufe sequenziell, zwölf Worker, isolierter Quellstand.

CP-SAT: OR-Tools 9.15.6755. IBM: unbeschränkte CP-Optimizer-Engine 22.2, Pfad `/Users/felix/Applications/CPLEX_Studio222/cpoptimizer/bin/arm64_osx/cpoptimizer`. Der Startdatensatz speichert Enginehash, Quellen und Checkpointhashes. Solverlimits und tatsächliche Laufzeit sind verschieden; insbesondere einzelne IBM-Aufrufe überschreiten ihr nominelles Limit beim Abschluss.

- **R:** bestehende Fünf-Stationen-Instanz, Max50-Reservoir, Waiting bis 1.200 Sekunden, 1.280 Personen, Reisezeitziel. Gemeinsamer validierter Seed: 369.892,972760 Passagiersekunden.
- **C:** ursprüngliches Fixed-K39-Placement, Waiting, 3.074 Personen, Ziel unbediente Personen. Historischer Startwert: 1.610 Unbediente. Spätere Mustersuchkampagnen verwenden andere, bessere Seeds und sind kein unmittelbarer gleichgestellter Laufzeitvergleich.

R und C sind unterschiedliche Domänen und Ziele. Keine der beiden Reihen ist bereits die geplante vollständige Sechs-Stationen-Auswertung. Für R wird bei allen Varianten einschließlich Legacy dieselbe analytische Untergrenze 109.032,727040 berücksichtigt. Seedübernahme ist keine Verbesserung.

## Vollständige Ergebnisse

UB ist bei R Passagiersekunden, bei C unbediente Personen. Kleinere Werte sind besser. Sekunden sind die erfassten tatsächlichen Laufzeiten je Versuch. Encodingfolge: Ressourcen / Bewegung.

| Phase | Case | Backend | Profile / encoding | Seed | UB | Comparable LB | Seconds |
|---|---|---|---|---:|---:|---:|---:|
| screen | R | cp_sat | legacy / legacy / legacy | 0 | 369864.956456 | 109032.727040 | 180.61 |
| screen | R | cp_sat | hints / legacy / legacy | 0 | 369212.057680 | 109032.727040 | 180.61 |
| screen | R | cp_sat | temporal / legacy / legacy | 0 | 369869.891408 | 109032.727040 | 180.57 |
| screen | R | cp_sat | passenger_links / legacy / legacy | 0 | 369331.712656 | 109032.727040 | 180.65 |
| screen | R | cp_sat | journey_bounds / legacy / legacy | 0 | 369887.002096 | 109032.727040 | 180.62 |
| screen | R | cp_sat | strengthened / legacy / legacy | 0 | 369266.715024 | 109032.727040 | 180.83 |
| screen | C | cp_sat | legacy / legacy / legacy | 0 | 1562.000000 | 0.000000 | 180.74 |
| screen | C | cp_sat | hints / legacy / legacy | 0 | 1530.000000 | 0.000000 | 180.56 |
| screen | C | cp_sat | temporal / legacy / legacy | 0 | 1514.000000 | 0.000000 | 180.61 |
| screen | C | cp_sat | passenger_links / legacy / legacy | 0 | 1522.000000 | 0.000000 | 181.15 |
| screen | C | cp_sat | strengthened / legacy / legacy | 0 | 1506.000000 | 0.000000 | 180.63 |
| screen | R | ibm | legacy / legacy / legacy | 0 | 369892.972760 | 109032.727040 | 199.46 |
| screen | R | ibm | strengthened / legacy / legacy | 0 | 369892.972760 | 109032.727040 | 184.31 |
| screen | R | ibm | strengthened / legacy / native_visits | 0 | 369892.972760 | 109032.727040 | 183.11 |
| screen | R | cp_sat | strengthened / compact_fixed / legacy | 0 | 369266.714104 | 109032.727040 | 181.08 |
| screen | R | cp_sat | strengthened / merged_exit / legacy | 0 | 369266.714504 | 109032.727040 | 180.88 |
| confirm | R | cp_sat | hints / legacy / legacy | 1 | 369765.970080 | 109032.727040 | 300.84 |
| confirm | R | ibm | legacy / legacy / legacy | 1 | 369892.972760 | 109032.727040 | 311.61 |
| confirm | C | cp_sat | strengthened / legacy / legacy | 1 | 1482.000000 | 0.000000 | 300.55 |
| confirm | C | cp_sat | legacy / legacy / legacy | 1 | 1482.000000 | 0.000000 | 300.57 |
| confirm | R | cp_sat | hints / legacy / legacy | 2 | 369549.823232 | 109032.727040 | 300.51 |
| confirm | R | ibm | legacy / legacy / legacy | 2 | 369892.972760 | 109032.727040 | 310.81 |
| confirm | C | cp_sat | strengthened / legacy / legacy | 2 | 1498.000000 | 0.000000 | 300.57 |
| confirm | C | cp_sat | legacy / legacy / legacy | 2 | 1506.000000 | 0.000000 | 300.56 |

## Interpretation

Im R-Screening war CP-SAT `hints` mit 369.212,057680 am besten; `strengthened` und seine Ressourcenvarianten lagen um 369.266,714–715. Die minimale Differenz zwischen Ressourcenencodings ist kein belastbarer Performancegewinn. IBM übernahm in allen getesteten Profilen/Bewegungskernen den Seedwert ohne Verbesserung.

In der R-Bestätigung verbesserte CP-SAT `hints` den IBM-Referenzwert um etwa 0,0343 % beziehungsweise 0,0928 %. Beide Effekte liegen unter der vorab festgelegten 0,1-%-Schwelle. Die vergleichbare Untergrenze blieb unverändert; kein Lauf steigerte sie über die analytische Schranke. Die Bestätigung verglich **CP-SAT hints gegen IBM legacy**, nicht CP-SAT hints gegen CP-SAT legacy. Ein bestätigter Vorteil des Hint-Profils gegenüber CP-Legacy kann daraus nicht abgeleitet werden.

Bei C war `strengthened` im Screening mit 1.506 statt 1.562 Unbedienten besser als Legacy. In der Bestätigung gab es bei Seed 1 Gleichstand (1.482); bei Seed 2 lag `strengthened` acht Personen vorn (1.498 statt 1.506). Die geforderten zehn zusätzlichen Bedienungen in beiden Seeds wurden nicht erreicht. Die vergleichbare globale Untergrenze blieb null.

Die vorab festgelegte Empfehlung verlangte in **beiden** zusätzlichen Seeds mindestens 0,1 % niedrigere R-Kosten, zehn weniger unbediente Personen bei C oder einen Prozentpunkt kleineren vergleichbaren Gap ohne schlechtere UB. Alle drei Richtungsvergleiche in `evaluation.json` sind deshalb `inconclusive`. Das bedeutet keinen bewiesenen Gleichstand der Algorithmen, sondern unzureichende Bestätigung eines relevanten Vorteils unter diesem Budget.

## Konsequenz

`legacy` bleibt Standard. Vollständige Hints und kompaktere Modelle sind implementierte Optionen, aber kleinere Variablenzahlen belegen keine schnellere Suche. Ein erneuter langer Lauf ist allein auf Basis dieser Kampagne nicht begründet. Der nächste experimentelle Schritt sollte eine konkrete Engpasshypothese prüfen.

Die spätere Mustersuche und deren Hint-Ablation zeigen einen teuren inneren Suchschritt und starke Abhängigkeit von Startwerten. Die [breite Literaturauswertung](../research/ropeway_cross_domain_algorithms_20260910.md) formuliert dazu zwei getrennte Piloten: Zeitgraph nach festgelegten lokalen Entscheidungen sowie ereignisbasierte Zustandsoptimierung. Daraus ist noch kein neuer Solverlauf gestartet.

## Artefakte

- [Historischer vollständiger Vergleich](../../benchmarks/output/cp_formulation_campaign_20260910_121055/comparison.md)
- [Automatische Schwellenprüfung](../../benchmarks/output/cp_formulation_campaign_20260910_121055/evaluation.json)
- [Einzelergebnisse](../../benchmarks/output/cp_formulation_campaign_20260910_121055/results.json)
- [Abschlussstatus](../../benchmarks/output/cp_formulation_campaign_20260910_121055/status.json)
- [Startprotokoll und Hashes](../../benchmarks/output/cp_formulation_campaign_20260910_121055/launch.json)
- Quellkopie: `benchmarks/output/cp_formulation_runtime_20260910_121055/`
- [Implementierungsplan und Korrektheitskontrollen](../plans/cp_formulation_strengthening_20260910.md)

Die historischen Ergebnisdateien bleiben unverändert. Die Implementierungsprüfung ist von der Performancekampagne getrennt: 158 gezielte Tests bestanden; die dokumentierten Legacy-/Horizont-/Referenzkontrollen bleiben maßgeblich.
