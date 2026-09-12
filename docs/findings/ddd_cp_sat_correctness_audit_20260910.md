# Korrektheitsprüfung des laufenden Reservoir-CP-SAT-Modells

Stand: 10.09.2026, ca. 00:57 Uhr Europe/Berlin. Geprüft wurde das aktuell laufende Fünf-Stationen-Modell mit maximal 50 Kabinen, Exit-Waiting bis 1.200 s und Mikrosekundenticks. Kein neuer Optimierungslauf wurde gestartet; der 8-Stunden-Lauf wurde weder verändert noch unterbrochen.

## Ergebnis

**Kein bestätigter Implementierungsfehler im geprüften Modell und kein ungültiger Fahrplan im zusätzlich geprüften Incumbent gefunden.** Bewegungsfortschreibung, optionale Flotte, leere Rückkehr, Ressourcenintervalle, ganzzahlige Passagierzuordnung und Zielfunktion passen zum dokumentierten Betriebsvertrag. Das ist eine Codeprüfung mit einem zusätzlichen konkreten Gegencheck, kein formaler Vollständigkeitsbeweis für sämtliche Eingaben oder eine Validierung einer realen Depotanlage.

Die wesentlichen offenen Punkte sind Modellgrenzen: idealer Reservoiranschluss, nur ein Einsatz je Kabine, endlicher Betriebszeitraum und eingeschränkte Passagierwege. Diese Grenzen dürfen bei der Interpretation der Ergebnisse nicht verschwinden.

## Was tatsächlich neu geprüft wurde

Der gespeicherte Incumbent wurde einmal eingefroren, damit die Prüfung nicht unterschiedliche Zwischenstände des weiterlaufenden Solvers vermischt. Alle **244 Dateien aus dem Source-Hash-Manifest des Runs** stimmen mit dem Arbeitsstand überein. Ausgangscommit `6071c67` allein beschreibt den Run nicht vollständig, da die Reservoir-Erweiterung noch uncommitted ist.

| Prüfung | Ergebnis |
|---|---:|
| Domain-Fingerprint | `ea2b46d53da6f34147bfd5a9c1a635116e89eb47afd84cfd036b56971376ac65` |
| Validierte Journey Time | 368.765,821408 Personensekunden |
| Bediente / unbediente Personen | 1.280 / 0 |
| Eingesetzte / gleichzeitig aktive Kabinen | 38 / 38 |
| Geprüfte gefahrene Stationsbesuche | 1.055 |
| Tatsächliche Skip-Besuche | 8 |
| Besuche mit positivem Zusatzwait | 106 |
| Gesamtes zusätzliches Waiting | 65,750320 s |
| Größte Sitzbelegung / Kapazität | 8 / 8 |
| Vollständige physische Headway-Checkpoints | 20 |
| Ressourcen im reduzierten DDD-Kern | 15 |
| Paarprüfungen gegen vollständige physische Regeln | 438.081 |
| Gefundene Headway-Verletzungen | 0 |

Zusätzlich zum vorhandenen Reservoir-Zertifikatsprüfer wurde die ursprüngliche EAN-Geometrie neu aufgebaut. Die Prüfung verwendete die **vollständige physische Headway-Policy**, einschließlich der im DDD-Modell als redundant entfernten Ressourcen. Für alle tatsächlich gefahrenen Besuche wurden Plattformankunft, nominaler Plattformexit, tatsächlicher Exit und Merge-Zeit aus den ursprünglichen EAN-Timings rekonstruiert. Anschließend wurden alle Paare je Checkpoint mit dem ursprünglichen EAN-Regelauswerter verglichen. Die DDD-Intervallkoeffizienten wurden dafür nicht übernommen.

Die Vergleichstoleranz betrug 2 Mikrosekunden. Die kleinste tatsächlich beobachtete physische Headway-Marge war nur durch Fließkommaarithmetik negativ: etwa −2,27 × 10⁻¹³ s. Der größte Unterschied zwischen ursprünglichem Geometrieoffset und quantisiertem DDD-Offset betrug 0,182 Mikrosekunden. Die separat aus ursprünglichen Timings berechneten Passagierkosten weichen insgesamt um 0,000116364 Personensekunden vom Tick-Wert ab; das liegt innerhalb der erwarteten Quantisierung. Es gibt keinen relevanten Kostensprung.

Auch OD-Zuordnung, Releases, Nachfrageobergrenzen und Sitzbelegungen wurden zusätzlich direkt aus den Ride-IDs und rekonstruierten Besuchen geprüft, ohne den Passagierkandidaten-Builder zu verwenden. Dieser Gegencheck bleibt von der gemeinsamen Szenariogeometrie und deren physikalischen Annahmen abhängig.

Lokale Nachweise unter `benchmarks/output/model_correctness_audit_20260910/`:

- `inspect_checkpoint.py`: ausgeführtes Prüfskript, ohne Solveraufruf.
- `checked_incumbent.json`: genau der geprüfte Fahrplan samt Domain-Manifest.
- `report.json`: maschinenlesbare Ergebnisse.

Diese lokalen Output-Dateien sind nicht automatisch Teil eines Git-Commits. Das Skript liest bei erneuter Ausführung den dann aktuellen Run-Checkpoint und überschreibt seine Audit-Ausgaben. Für den hier dokumentierten Stand sind die bereits erzeugten Dateien maßgeblich.

## Prüfung der Formulierung

Quellpfade in der Tabelle sind relativ zu `src/ropeway_skip_stop_optimization/`.

| Bereich | Beurteilung | Maßgeblicher Code |
|---|---|---|
| Optionale Kabinen | `sum(route)=active`; unbenutzte Kabinen erzeugen keine aktiven Ressourcen. Maximal 50 bedeutet nicht genau 50. | `optimization/ddd/reservoir_cp_sat_movement.py` |
| Bewegung | Nächste Ereigniszeit = aktuelle Zeit + gewählte Routendauer + Zusatzwait. Nach Deaktivierung bleibt die Zeit konstant; Reaktivierung ist ausgeschlossen. | `optimization/ddd/reservoir_cp_sat_movement.py` |
| Rückkehr | Aktivität darf nur am Anschluss enden. Alle gefahrenen Routen sind bis H abgeschlossen. Der Endslot hat keine ausgehende Route und kann kein Aussteigeereignis für Passagiere sein. | `optimization/ddd/reservoir_cp_sat_movement.py`, `optimization/ddd/reservoir_cp_sat_certificate.py` |
| Besuchsobergrenze | Aus frühester Ausfahrt und den jeweils kürzesten Routen abgeleitet. Späterer Start oder positives Waiting kann nicht mehr Besuche benötigen. Die Grenze von 53 ausgehenden Slots schneidet im aktuellen Domain-Vertrag keine schnellere zulässige Trajektorie ab. | `optimization/ddd/reservoir_cp_sat_problem.py` |
| Symmetrie | Verwendete Kabinen bilden einen ID-Prefix und sind nach Ausfahrt geordnet. Da Kabinen identisch sind, ist dies eine Umbenennung, keine Fixierung auf 38 Kabinen oder All-Stop-Routen. | `optimization/ddd/reservoir_cp_sat_movement.py` |
| Headways | Ein Schutzintervall bildet die Disjunktion „erste vor zweiter oder zweite vor erster“ ab. Die vorhandenen Regeln sind konstant oder nur vom vorausfahrenden Verhalten abhängig; dafür ist die Intervalllänge korrekt. Eine beliebige paarabhängige Regelmatrix wäre damit nicht automatisch abgedeckt. | `optimization/ddd/artifact_adapter.py`, `optimization/ddd/cp_sat_movement.py`, `models/headway.py` |
| Waiting | Am Plattformexit bleibt der Eintritt nominal, während die Freigabe um w verschoben wird. Exit-Switch und Service-Mechanismus verschieben sich beide um w. SKIP kann nicht warten. Schutzzeiten bleiben nach Rückkehr bestehen. | `optimization/ddd/artifact_adapter.py`, `optimization/ddd/cp_sat_movement.py` |
| Passagiere | Positive ganzzahlige Zuordnung verlangt aktive STOP-Endpunkte, passende zeitliche Reihenfolge und Ankunft bis Serviceende. Jeder belegte Fahrtabschnitt trägt zur Sitzkapazität bei; nach Ausstieg sind Plätze wiederverwendbar. | `optimization/ddd/cp_sat_passenger.py`, `optimization/ddd/reservoir_cp_sat_certificate.py` |
| Kosten | `Σg count_g·(T−release_g) + Σe alight_count_e·(arrival_e−T)` entspricht exakt den bedienten Reisezeiten plus Resthorizontkosten unbedienter Nachfrage. Die Produktgleichheiten sind exakt. | `optimization/ddd/cp_sat_passenger.py` |
| Seed und Suche | Die Bewegungen des Seeds werden im Hauptlauf nur als Hint gesetzt. Gleichheitsfixierungen entstehen ausschließlich bei `fixed_plan`. Der validierte Kosten-Cutoff schließt kein besseres Optimum aus. | `optimization/ddd/reservoir_cp_sat.py` |
| Bounds | Beide Gap-Abbruchschwellen sind null. Negative native Bounds werden auf die gültige analytische Nullschranke angehoben. Eine zulässige Lösung wird nicht als optimal bezeichnet. Bounds gelten nur für den ausgewiesenen Modellbereich. | `optimization/ddd/reservoir_cp_sat.py` |

## Grenzen mit praktischer Bedeutung

### 1. Reservoir ist weiterhin ein idealer Anschluss

Der Anschluss liegt bei `A_entry_cw`. Es gibt keine eigene Einfädelweiche mit Fahrzeit und Headway, keine Rangierstrecke und keine physische Lagerkapazität. Ein-Tick-Eindeutigkeit eines State-Time-Punkts ist kein Ersatz für eine solche Depotressource. Die normalen Strecken-/Stationsressourcen gelten anschließend weiter.

Das ist ausdrücklich im Domain-Manifest und bisherigen Plan dokumentiert. Der Gegencheck bestätigt daher die vorhandenen Stations-/Streckenregeln, nicht die Kollisionsfreiheit eines noch nicht spezifizierten realen Depotanschlusses.

### 2. Kein Wiedereinsatz nach Rückkehr

Mehrere Umläufe während eines Einsatzes sind erlaubt. Nach der ersten Rückkehr bleibt die Kabine dauerhaft abgestellt. K begrenzt die Zahl unterschiedlicher eingesetzter Kabinen, nicht nur die Spitze gleichzeitig aktiver Kabinen. Ein vollständiges „rausfahren, zurückkommen, warten, wieder rausfahren“ ist nicht implementiert.

### 3. Journey Time erzwingt keine vollständige Bedienung

Unbediente Nachfrage kostet `T−release`. Beispielsweise kosten bei T=1.500 eine unbediente Person mit Release 1.490 und eine genau bei 1.500 ankommende Person jeweils 10. Deshalb ist das Ziel nicht lexikografisch „zuerst alle bedienen, danach Reisezeit minimieren“. Im geprüften Fahrplan sind tatsächlich alle Personen bedient; bei neuen Nachfrageprofilen muss das separat kontrolliert werden. Der alternative Modus `unserved` ist ein anderes Ziel, keine automatische erste Phase.

### 4. Einsteigen ist bis zum tatsächlichen Plattformexit erlaubt

Das entspricht dem bisherigen EAN-Modell und schließt Nachfrage ein, die während des zusätzlichen Exit-Waitings ankommt. Wenn der reale Wartepunkt hinter dem zugänglichen Einsteigebereich liegt oder dort die Türen geschlossen sind, braucht man eine separate Einsteigeschranke. Im konkret geprüften Fahrplan steigt keine Person erst aufgrund eines Releases während des zusätzlichen Exit-Waitings ein. 120 Personen erscheinen nach Plattformankunft, aber noch bis zum nominalen Plattformexit; das ist die reguläre Boarding-Konvention.

### 5. Passagierwege und Topologie sind beschränkt

Direkte Fahrt zur ersten nachfolgenden Zielstation, ohne Transfers und ohne bewussten zusätzlichen Passagierumlauf. Der Solver optimiert außerdem einen gerichteten Umlauf mit eindeutigen Stations-IDs. Die geplante Sechs-Stationen-Linie bzw. ein Doppelring ist nicht durch diesen Lauf geprüft oder bereits vollständig unterstützt.

### 6. Endlicher Horizont und Baseline-Vergleich

Nachfrage wird um 300 s verschoben; Serviceende ist 1.500 s, Betriebsende 1.800 s. Im Gegensatz zum älteren Fixed-K-Vertrag müssen alle eingesetzten Kabinen vollständig zurückkehren. Der geprüfte Plan fährt zwischen 28,000001 und 291,909091 s aus und kehrt zwischen 1.531,090906 und 1.772,454552 s zurück. Ein stationärer Dauerbetrieb folgt daraus nicht.

Die Verbesserung gegenüber dem früheren festen All-Stop-38-Fahrplan ist kein isolierter Skip-Stop-Nachweis: Startbedingungen und Betriebsgrenzen unterscheiden sich. Für diesen Nachweis wäre ein All-Stop-Vergleich innerhalb derselben Reservoir-Domäne nötig, einschließlich vergleichbarer Lösungsgüte.

## Einordnung und nächste Konsequenz

Aus dieser Prüfung folgt **kein Grund, den laufenden 8-Stunden-Versuch wegen eines bestätigten Modellfehlers abzubrechen**. Das beobachtete Plateau lässt sich damit nicht als Bug erklären. Die Korrektheitsprüfung beweist allerdings auch nicht, dass die Formulierung für eine schnelle Suche gut ist: korrekte Produktkopplungen können schwache Schranken erzeugen, und ein korrekter Hint kann die Suche praktisch beeinflussen, ohne Variablen zu fixieren.

Vor der nächsten Kampagne sollte der für die Thesis behauptete Betriebsvertrag zu den obigen Grenzen passen. Wenn vollständige Bedienung zwingend ist, muss sie künftig als Nebenbedingung oder erste Optimierungsphase abgesichert werden. Eine reale Depotweiche oder Wiedereinsätze sind eigenständige Erweiterungen, keine kleine Solverparameteränderung.

Die bisherigen 121 Regressionstests sind im Reservoir-Befund dokumentiert. **Sie wurden während dieses Audits nicht erneut ausgeführt.** Neu ausgeführt wurden die solverfreien Gegenprüfungen oben. Produktionscode und Solverparameter wurden nicht geändert.
