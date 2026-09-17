# Gemeinsamer 1-ms-OIP-Vergleich: Implementierungsbefund

Stand: 17.09.2026. Dieser Befund dokumentiert Implementierung und kleine
Korrektheitstests. Er enthält keine Aussage über die Leistungsfähigkeit auf den
großen Thesis-Fällen.

## Umgesetzter Vertrag

- Eigene, versionierte OIP-Domäne mit optimierter Anfangsaufstellung und ohne
  Reservoir-Dispatch.
- Gemeinsames konservatives 1-ms-Raster. Mindestdauern, Freigaben, Headway-Regeln,
  materialisierte Headway-Paare und Schutzabstände werden aufgerundet;
  Bedienungsfristen werden abgerundet. Das Manifest speichert jede Abweichung.
- Freie aktive Flotte bis `Kmax` oder Exact-K, freie STOP/SKIP-Entscheidungen,
  Überholen und vollständige Weiterfahrt bis zum operativen Ende.
- Neue OIP-Läufe sind No-Wait. Positive Waiting-Konfigurationen werden vor dem
  Modellbau abgelehnt.
- Exaktes lexikografisches Ziel: zuerst Unserved, danach Journey Time inklusive
  der Zeitstrafe unbedienter Nachfrage. Keine Flottenzielstufe.
- CP-SAT: Passagierencodings `od_inventory` und `groups`.
- Gurobi-EAN: bisheriges `slots` sowie neues `ride_counts` mit ganzzahligen
  Fahrtmengen und exakter Binärzerlegung der Menge-mal-Ereigniszeit-Produkte.
- Gemeinsamer Runner, unabhängiger Zertifikatsprüfer und Liveansicht für
  Bedienung, Journey Time, native Schranken, Gap, Flotte und Anfangszustände.

## Kleine Abnahme

Auf `three_station_optimized_initial_placement_v0`, Exact-K=1, Skip-Stop,
No-Wait und einem 15-s-Solverbudget ergaben CP-SAT/OD-Inventar und
Gurobi/`ride_counts` dasselbe validierte Ergebnis:

| Größe | Wert |
|---|---:|
| Bedient | 176 |
| Unbedient | 3.304 |
| Journey Time inkl. Unserved-Strafe | 4.068.920,368 Personen-s |
| Lexikografischer Skalarwert | 13.801.572.923.672 |

Gurobi/`slots` rekonstruierte ebenfalls denselben Zielwert und dieselbe
Bedienung; innerhalb des kurzen Budgets blieb der native Optimalitätsnachweis
offen. Dies ist ein Korrektheitsvergleich, kein Laufzeitvergleich.

Build-only auf demselben Fall:

| Modell | Variablen | Constraints | Buildzeit |
|---|---:|---:|---:|
| CP-SAT + OD-Inventar | 649 | 1.379 | 0,007 s |
| Gurobi-EAN + `ride_counts` | 3.791 | 8.819 | 0,076 s |

Die CP-Zahl der Constraints summiert die von OR-Tools ausgegebenen
Constraintfamilien. Größenunterschiede sind wegen unterschiedlicher nativer
Primitive nicht als Laufzeitprognose zu lesen.

## Abnahmegrenzen

- Das Raster ist eine explizite diskrete Modellannahme. Historische
  Mikrosekunden- oder kontinuierliche Resultate sind keine direkten
  Vergleichsreferenzen.
- Gestrichelte All-Stop-Referenzen werden nur akzeptiert, wenn ihr
  Vergleichsfingerprint mit Nachfrage, K-Vertrag, Horizont und Raster
  übereinstimmt.
- Timeout und `UNKNOWN` bleiben von bewiesener Unzulässigkeit getrennt.
- Große T5/F2- oder F3-Läufe gehören zum nachfolgenden Experimentplan und wurden
  bei dieser Abnahme absichtlich nicht gestartet.

## Reproduzierbare Einstiegspunkte

Der Runner ist `benchmarks/run_oip.py`. Die neuen Bibliothekseinstiege sind
`optimization/oip/domain.py`, `optimization/oip/cp_sat.py`,
`optimization/oip/validation.py` und `optimization/oip/runner.py`. Das kompakte
Gurobi-Passagiermodell liegt in
`optimization/ean/optimizers/ride_count_passenger_model.py`.
