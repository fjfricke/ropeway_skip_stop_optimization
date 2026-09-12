# CP-SAT: einmaliger Reservoir-Einsatz mit variabler genutzter Flotte

Auftrag: bisheriges Fixed-K einschließlich Waiting/Warmup erhalten; Reservoir im bestehenden integrierten CP-SAT ergänzen. Stufe 1 erlaubt pro Kabine höchstens einen Einsatz, keinen Wiedereinsatz.

## Betriebsvertrag

- Bestehende ideale Reservoirgrenze am konfigurierten Entry-State übernehmen, im Fünf-Stationen-Beispiel `A_entry_cw`. Keine erfundene physische Depotweiche oder zusätzliche numerische Headways.
- Die Grenze liegt vor der Stationsroute. Rückkehr ist nur dort und leer möglich. Eine Ankunft an der Grenze allein ist kein Passagierausstieg an der Plattform.
- Alle Kabinen starten abgestellt. Ausfahrtszeit und verwendete Kabinenzahl <= verfügbare Flotte sind Variablen. Ausfahrt während Anlauf oder Service; Rückkehr auch während Service, spätestens am operativen Ende. Abgestellte Kabinen belegen keine Strecke. Ressourcenschutzintervalle bereits gefahrener Bewegungen bleiben bestehen.
- Bestehende Stop-/Skip-Routen, Mikrosekundenticks und Exit-Wait-Koeffizienten verwenden. Die ideale Grenze besitzt wie im bisherigen Reservoir-Netz keine eigenen Depotfahrzeiten. Eindeutige State-Time-Belegung umfasst auch Dispatch und Rückkehr.
- Eigene vollständige Domänenidentität und Checkpoints; kein Fixed-K-/Legacy-Boundimport. All-Stop und Skip-Stop verwenden dieselbe Reservoirpolitik.
- Start mit einem gerichteten deterministischen Umlauf, entsprechend der vorhandenen CP-/Reservoir-Unterstützung. Sechs-Stationen-Linie/Doppelring werden damit nicht stillschweigend als unterstützt behauptet.

## Integration

1. Neue unveränderliche Problem-/Planobjekte und unabhängiger Physik-/Integer-Passagierprüfer.
2. Eigener Reservoir-Lifecycle-Builder; vorhandene CP-Ressourcenintervalle wiederverwenden. Zahl möglicher Besuche aus minimalen Fahrzeiten und Horizont herleiten, keine willkürliche Umlaufkürzung.
3. Bestehende integrierte Integer-Passagierformulierung über eine allgemeine Eingabeschnittstelle teilen; Fixed-K-Wrapper unverändert nutzbar. Journey Time und optional unbediente Personen als ausdrücklich verschiedene Ziele/Schrankeneinheiten.
4. Eigener Solver/CLI mit Live-Ereignissen, Modellgrößen, Zeitanteilen, validiertem Seed/Checkpoint und sauberem Timeout. Kein Überschreiben bestehender Runs.
5. Kleine exakte Gegenprüfungen, Ein-/Ausfahr- und Headwaytests, Freiwilligkeit der Flotte, frühe Rückkehr, Empty-Return und Checkpoint-Manipulation. Fixed-K-/Waiting-/Warmup-/Reservoir-Regressionen.
6. Begrenzter echter Fünf-Stationen-Smoke; Ergebnis und Grenzen dokumentieren.

Eine separate physische Depotzufahrt mit Weichen-, Lager- oder Rangierkapazität ist im alten Modell nicht definiert und wird hier nicht als bereits kalibriert ausgegeben. Diese idealisierte Semantik ist Teil des Fingerprints.

## Umsetzung abgeschlossen (2026-09-09)

Alle sechs Schritte umgesetzt. 121 Tests bestanden, ursprüngliches Fixed-K-39-Waiting-Modell mit identischem Fingerprint nachgewiesen, drei sequenzielle 60-s-Fünf-Stationen-Läufe validiert. [Ergebnisse, Codekarte, Aufruf und Grenzen](../findings/ddd_cp_sat_reservoir.md). Wiedereinsatz, physische Depotweiche und Sechs-Stationen-Linie bleiben separate Erweiterungen.
