# Binäre CP-SAT-Reisezeitkosten: begrenzter Vergleich

Freigabe: Nutzer am 11.09.2026. Umsetzung und kleine Korrektheitstests vor der
Performancekampagne; danach höchstens 30 Minuten tatsächliche Wandzeit.

## Hypothese und unveränderte Semantik

Die [Diagnose](../findings/reservoir_diagnostics_20260911.md) zeigt: Bei festen
Haltemustern sind Zeiten und ganzzahlige Beförderung jeweils einzeln einfach,
gemeinsam bleibt ein deutlicher Gap. Die binäre Kostendarstellung testet einen
Teil dieser Kopplung. Sie ist keine neue Suche und kein Nachweis, dass direkte
Integerprodukte allein das Problem verursachen.

Für jede Aussteigermenge `0 <= n <= Q` entstehen `Q.bit_length()` Bits:

- `n = Summe(2^j * b_j)`; die ursprüngliche Grenze `n <= Q` bleibt bestehen.
- `z_j = t`, wenn `b_j = 1`, andernfalls `z_j = 0`.
- Das exakte Produkt ist `Summe(2^j * z_j)`.

Alle Werte bleiben Integer-Ticks; keine Rundung, Zeitrasteränderung, zusätzliche
Fahrplanrestriktion oder Relaxation der Beförderungsmengen. Die verbleibende
Zielfunktion und Nichtbedienungskosten bleiben gleich. Beim Kapazitätsziel
entstehen weiterhin keine Kostenprodukte oder binären Kostenhilfen.

Gemeinsamer CP-SAT-Passagierbuilder, zusätzliche Enum-Option `binary`, bestehende
CLIs übernehmen `--cost-encoding binary`. Produkt bleibt Standard. Hints für
binäre Hilfswerte werden im vorhandenen vollständigen Hintpfad unterstützt.
Für den isolierten Vergleich bleibt das Formulierungsprofil `legacy`: Beide
Varianten erhalten dieselben Bewegungs- und Ride-Hints; zusätzliche vollständige
Hints werden nicht als zweite Änderung eingeführt.

## Korrektheit

- Vollständige Projektion kleiner Mengen-/Zeitbereiche, auch Q=0, Q=8 und Q=10.
- Zeitwerte über 2^31, eindeutige Bitdarstellung und exakte Produktwerte.
- Bestehende vollständig enumerierte Fixed-K-/Reservoir- und Waitingfälle,
  Bypass-Überholen, Horizontgrenzen und Odd-Cycle-Ganzzahligkeit.
- Positive Startmengen, korrekte eindeutige Hintindizes, `legacy`/`hints`/
  `strengthened`, weiterhin fehlende Kostenhilfen beim Kapazitätsziel.
- Historischer Max50-Fahrplan vollständig fixiert mit beiden Encodings exakt
  reproduziert, bevor die freie Suche beginnt.

## Eingefrorener Vergleich

Derselbe Max50-Single-Use-Reservoirfall und dieselbe Referenz wie in der Diagnose:
38 eingesetzte Kabinen, 1.280 Personen, Waiting bis 1.200 s bei Mikrosekunden.
UB 368.765,817136 Passagiersekunden. Physikalischer Fingerprint:
`ea2b46d53da6f34147bfd5a9c1a635116e89eb47afd84cfd036b56971376ac65`.

1. **Timing:** Haltemuster und aktive Besuche fest, Zeiten, Ressourcenreihenfolgen
   und Passagiermengen gemeinsam frei. Je Encoding Seeds 0/1, 180 s Prozessbudget.
   Reihenfolge Produkt 0, Binär 0, Binär 1, Produkt 1.
2. **Nur nach bestandenem Timing-Vergleich:** dieselben vier Läufe im vollständigen
   Max50-Modell, ohne Diagnosefixierungen. Kein stärkeres Profil, keine Änderung
   an Ressourcenencoding oder Workerzahl.

Je Paar Erfolg bei mindestens 0,1 % besserer validierter UB oder einem
Prozentpunkt geringerem Gap ohne schlechtere UB. Beide Seeds müssen bestehen.
Der Kampagnencontroller protokolliert den nativen CP-SAT-Gap; die Schlussbewertung
weist zusätzlich den vergleichbaren Gap mit der bereits gültigen gemeinsamen
Schranke aus. Ein nativer Bound unter dieser gemeinsamen Schranke zählt nicht
als neuer globaler Nachweis. Eingeschränkte Timing-LBs gelten nicht global.

Zwölf Worker; sequenzielle Prozesse mit 8-GiB-RSS-Limit. Je 180-s-Prozessbudget
bleiben fünf Sekunden Reserve; Modellbau ist enthalten. Harte gemeinsame Deadline
von 1.800 s, keine neuen Läufe ohne verbleibendes vollständiges Einzelbudget.
Keine eigenen Suchentscheidungen zwischen den Versuchen, nur vorab festgelegte
Experimentauswahl. Keine Übernahme einer neuen Lösung als Seed für spätere Läufe.

## Nachweise

[Runner](../../benchmarks/run_reservoir_binary_cost_comparison.py),
[gemeinsamer Kindprozess](../../benchmarks/run_reservoir_diagnostics.py),
[Passagiermodell](../../src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_passenger.py),
[zusätzliche Tests](../../tests/test_cp_sat_binary_cost.py).

Neue Ergebnisordner mit gefrorenen Quellen, Engineversion, Modellfingerprints,
Konfigurationen, unabhängigen Checkpointprüfungen, nativen Ereignissen,
Prozesszeit/CPU/RSS und Presolve-Größen. Historische Resultate bleiben unverändert.
