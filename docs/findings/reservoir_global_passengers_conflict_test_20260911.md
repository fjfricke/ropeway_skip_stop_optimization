# Freie Passagiere und Konfliktnachbarschaften: negativer Vergleich

11.09.2026. [Protokoll und Implementierungsplan](../plans/reservoir_global_passengers_conflict_test_20260911.md).

**Beide Änderungen sind implementiert und korrekt in kleinen Kontrollen, liefern
auf R aber keinen gemessenen Vorteil.** Alle 18 Versuche enden mit denselben
validierten Kosten 368765.817136. Das vorher festgelegte Leistungskriterium wird
in keinem Bestätigungsseed erfüllt. Die eigene lokale Suche wird damit vorerst
als Thesis-Hauptstrategie zurückgestellt. Keine weitere unveränderte Langkampagne.

## Was verändert und isoliert wurde

1. Auf denselben geöffneten Einsätzen wie zuvor bleibt die ganzzahlige Zuordnung
   aller 1280 Personen frei. Außenfahrzeiten bleiben konstant. Neue Fahrten dürfen
   jetzt auch Fahrgäste unveränderter Außenfahrten übernehmen.
2. Die neue Auswahl beginnt bei einem besetzten STOP mit Durchreisenden, berechnet
   eine optimistische frühere Fortsetzung über SKIP und nimmt deren tatsächliche
   Ressourcenblockierer gemeinsam in die Reparatur auf. Der Vorschlag bestimmt
   nur die Nachbarschaft; er wird nicht als Fahrplan angenommen oder festgesetzt.

240 Vorschläge passen in höchstens sechs offene Einsätze; kein Vorschlag wurde
hier wegen zu vieler Blockierer verworfen. Die vier gewählten Mengen sind
`[1,36,37]`, `[0,2,37]`, `[0,1,3]`, `[1,2,4]`, jeweils ein zusätzlicher Slot.
Sie stammen konkret von einem C-SKIP beim Besuch 7 mit acht Durchreisenden und
20.181818 Sekunden optimistischer früherer Fortsetzung. Jeder Vorschlag hat zwei
Blockiererkabinen; 111 einzelne kollidierende Nutzungspaare verteilen sich entlang
der verschobenen Fortsetzung. Dies ist keine garantierte Einsparung: andere
Fahrgäste und die Wiederherstellung physischer Zulässigkeit sind noch zu optimieren.

## Ergebnis

Unveränderte Single-Use-Reservoir-Domäne R: maximal 50 Kabinen, volle Waitinggrenze
1200 Sekunden, 1280 Personen, Mikrosekundenauflösung. Gemeinsamer geprüfter Seed
mit 38 Einsätzen und Kosten 368765.817136. Fingerprint:
`ea2b46d53da6f34147bfd5a9c1a635116e89eb47afd84cfd036b56971376ac65`.

Screening: vier alte Mengen jeweils mit Legacy/globaler Zuordnung, vier weitere
Konfliktmengen mit globaler Zuordnung; je 30 Sekunden äußerer Rahmen, Seed 0.
**Alle zwölf Fälle übernehmen einen nativen gültigen Plan, keiner verbessert ihn.**

Die vorab definierte Gleichstandsregel wählt `conflict_0` für die Bestätigung.
Auch deren Legacy-Kontrolle verwendet exakt `[1,36,37]` und einen Zusatzslot.
Alle Arme starten wieder vom gleichen ursprünglichen Seed, nicht vom Ergebnis
eines anderen Versuchs. Je zwölf Worker, sequenziell, 16 GiB RSS-Limit.

| Arm | Seed | Variablen | Wandzeit | Peak GiB | Validierte Kosten |
|---|---:|---:|---:|---:|---:|
| Freie Passagiere + Konfliktmenge | 1 | 15707 | 118.20 s | 2.28 | 368765.817136 |
| Legacy auf derselben Menge | 1 | 6251 | 117.97 s | 2.49 | 368765.817136 |
| Vollständiges CP-SAT | 1 | 87020 | 119.69 s | 5.80 | 368765.817136 |
| Freie Passagiere + Konfliktmenge | 2 | 15707 | 118.14 s | 2.87 | 368765.817136 |
| Legacy auf derselben Menge | 2 | 6251 | 118.07 s | 2.37 | 368765.817136 |
| Vollständiges CP-SAT | 2 | 87020 | 119.50 s | 6.01 | 368765.817136 |

Alle sechs Bestätigungen enden FEASIBLE, alle 1280 Personen sind weiterhin bedient.
Die lokale globale Variante bestätigt den Seed nach ungefähr einer Sekunde und
liefert dann keine weitere native Lösung. Es gibt hier keine relevante
Verbesserungskurve; die UB bleibt über die ganze gemessene Suche konstant.
Der externe globale Bound bleibt 209409.890300, der vergleichbare Gap 43.2133%.
Lokale rohe Bounds werden nicht als globale Schranken ausgegeben.

Die gesamte Kampagne benötigt **1048.85 Sekunden = 17.48 Minuten** inklusive
Vorbereitung und Prozessabschlüssen, bei 30 Minuten Höchstbudget. Alle Worker
beenden regulär; kein Zeitwächter-/RSS-Abbruch und keine Schlaf-/Uhrendiskrepanz.
Das Leistungskriterium war mindestens 0.1% bessere Kosten als beide Kontrollen,
in beiden zusätzlichen Seeds. Ergebnis: zweimal nicht erfüllt.

## Korrektheit und Aussagegrenzen

**70 Tests bestehen**, einschließlich acht neuer Kontrollen. Diese prüfen:

- Alle Bewegungen offen: Übereinstimmung mit dem ursprünglichen CP-Optimum,
  mit und ohne Waiting.
- Bei festen Fahrten können Fahrgäste von einer Außenfahrt auf eine frühere
  Innenfahrt wechseln; die Legacy-Reparatur kann dies im konstruierten Fall nicht.
  Der Wert stimmt mit der unabhängig vollständig fixierten Originalformulierung überein.
- Alle Bewegungen geschlossen: kein neuer Einsatz, aber globale Neuzuordnung möglich.
- Ein neuer Einsatz vor einem festen Außenplan: kanonische IDs und Passagiere erhalten.
- Unzulässiges Boarding vor Freigabe wird nicht wieder eingeführt; Hints sind eindeutig.
- Später beginnende Reservierungen und halboffene Schutzintervalle.
- Ein unabhängiger Drei-Stationen-Fall: der C-Ressourcenkonflikt eines besetzten
  B-SKIPs identifiziert exakt die richtige Blockiererkabine und Überlappung.

Alle 18 Endzertifikate wurden nach Abschluss erneut durch den ursprünglichen
Validator geprüft. Ruff und `git diff --check` bestehen.

**FEASIBLE ist kein lokaler Optimalitätsbeweis.** Diese Ergebnisse beweisen weder,
dass es keine bessere Lösung in den Nachbarschaften gibt, noch dass der Seed global
optimal oder sehr schlecht ist. Sie widerlegen lediglich die Erwartung eines
schnell sichtbaren Nutzens dieser konkreten Implementierungen auf R.

Die lokalen Arme verwenden beide kein Presolve, um die Passagieränderung isoliert
zu betrachten; der vollständige CP-Kontrollarm behält sein bisheriges Presolve.
Andere Presolve-Einstellungen, größere Gruppen, ganze Bedienungsumbauten oder
andere Nachfrageprofile wurden hier nicht zusätzlich getestet. Daraus wird kein
weiterer automatischer Forschungszweig abgeleitet. Die bisherige erfolglose
Suche nur zu verlängern ist durch diesen Versuch nicht begründet.

## Dateien und Reproduktion

- [Vollständige Vergleichstabelle](../../benchmarks/output/reservoir_global_repair_report_20260911_v1/report.md)
- [CSV-Messwerte](../../benchmarks/output/reservoir_global_repair_report_20260911_v1/comparison.csv)
- [CSV-Verlauf](../../benchmarks/output/reservoir_global_repair_report_20260911_v1/progress.csv)
- [Kampagne, Logs, Konfliktnachweise und Checkpoints](../../benchmarks/output/reservoir_global_repair_campaign_20260911_v1)
- [Globale Passagierreparatur](../../src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_hybrid/global_repair.py)
- [Konfliktauswahl](../../src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_hybrid/conflict_neighborhoods.py)
- [Sequenzieller Kampagnenrunner](../../benchmarks/run_reservoir_global_repair_campaign.py)
- [Tests](../../tests/test_reservoir_global_repair.py)

`source_hashes.json`, Versionen, physische Domäne und ursprünglicher Seed sind im
Kampagnenordner eingefroren. Die damaligen Quellen sind zusätzlich in
`benchmarks/snapshots/reservoir_global_repair_20260911_sources.tar.gz` gesichert.
Nach der Kampagne wurde ausschließlich die interne Modell-Fingerprint-Metadaten-
bildung vervollständigt; Bedingungen und Suchparameter wurden nicht geändert.
Die abschließende Quellen-/Ergebnissicherung trägt den Suffix `_final`.

Literaturbezug und die Abgrenzung der projektspezifischen Übertragung stehen im
verlinkten Plan. Eine experimentelle Reparaturklasse wurde ergänzt; bestehende
Solverstandards und der bisherige Hybridkoordinator sind unverändert.
