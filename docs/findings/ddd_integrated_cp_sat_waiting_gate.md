# Exit-Waiting im integrierten CP-SAT: erster kontrollierter Versuch

Stand: 9. September 2026. Implementierung `integrated_cp_sat_v2`.

## Einordnung gegenüber All-Stop mit 38 Kabinen

**Der neue K39-Waiting-Fahrplan schlägt die All-Stop-Referenz K38 bisher nicht.** All-Stop K38 erreicht **399.287,271408** Kosten und bedient **alle 1.280 Personen**. K39 Skip-Stop mit Waiting liegt bei **1.022.076,357256** und 1.104 bedienten Personen: **155,98 % höhere Kosten (Faktor 2,56)**. Die zuvor genannten 19,02 % Verbesserung beziehen sich ausschließlich auf den frischen K39-Skip-Stop-No-Wait-Lauf.

Die All-Stop-Quelle ist `benchmarks/output/ddd_fixed_k_arc_flow_campaigns/five_station_b_balanced_fixed_k_boundary_screening/policies/all_stop/k38/result.json` (integer-optimal innerhalb der vorgegebenen Fixed-K-/Startdomäne). Die vollständige Bedienung ist auch durch die gespeicherte ganzzahlige Zuordnung in `benchmarks/output/ddd_fixed_k_campaigns/five_station_b_half_demand_fixed_k_hybrid_screening/policies/all_stop/k38/five_station_circle_cw_half_skip_no_wait_headway_b_v0__journey_time.json` belegt. Die All-Stop-Domäne wurde neu vorbereitet und der historische Problem-Fingerprint bestätigt; Nachfragegruppen, Releases, Horizonte, Kabinenkapazität und Objective stimmen mit dem Waiting-Lauf überein. Kabinenzahl, feste Startanordnung und Betriebsvariante unterscheiden sich.

Der Fortschritt bei K39 ist damit ein Fortschritt der dort gefundenen Lösungen, noch kein nachgewiesener betrieblicher Vorteil gegenüber All-Stop K38. Wegen des großen K39-Gaps ist zugleich nicht bewiesen, dass ein optimaler Skip-Stop-Waiting-Fahrplan die All-Stop-Referenz nicht schlagen könnte.

## Diagnose des Abstands zu All-Stop K38

Zusätzliche Prüfung am 9. September 2026, ohne Änderung der Modellimplementierung:

- Der historische K38-All-Stop-Fahrplan wurde als konkrete Bewegung in das **Skip-Stop-CP-SAT-Modell mit K38** eingesetzt. Beide Varianten, No-Wait und Waiting W=1200 s mit tatsächlichen Wartezeiten null, akzeptieren ihn und liefern **399.287,271408**, 1.280 bediente Personen und `OPTIMAL` für die **fixierte Bewegung**. Laufzeiten einschließlich Modellaufbau ca. 1,94 bzw. 2,53 s. Kein externer Incumbent wurde als Ergebnisfallback übergeben. Das prüft, dass das neue Modell den bekannten guten Fahrplan enthält und seine Passagierkosten reproduziert; es beweist weder globale Optimalität im freien Skip-Stop-Modell noch generelle Fehlerfreiheit.
- Reproduktion und Ergebnisse: `benchmarks/output/ddd_integrated_cp_sat_waiting/diagnostics/allstop38_inclusion/reproduce.py`, `summary.json`, `no_wait/result.json`, `waiting_w1200/result.json`. Der Import überträgt ausdrücklich nur die historische Bewegung in die neu vorbereitete Skip-Stop-Domäne; historische Bounds werden nicht übernommen.
- Die Startlayouts wechseln am Flottenübergang: K38 beginnt gleichmäßig auf All-Stop verteilt. Der für K39 erneut erzeugte `balanced_reference` besteht aus **einer All-Stop- und 38 All-Skip-Referenztrajektorien** (zusammen nur 22 Stopps über den Horizont). Deren Anfangssnapshot wird fixiert, ihre Zukunft nicht. Im tatsächlich verwendeten K39-Manifest stehen 38 Kabinen auf Seilstrecken nach Skip und eine im Stationszweig. An jedem Stationseingang gibt es erste Ankünfte mit nur etwa **1,268656 s** Abstand. Das ist keine Behauptung einer Sicherheitsverletzung: Stationszweig, Bypass und Zusammenführung haben unterschiedliche Ressourcenregeln.
- Der gemeinsame, bereits verbesserte Solver-Seed hatte 78 Stopps; die finale Waiting-Lösung hat 201 Stopps und 1.051 Skips. K38-All-Stop hat 842 Stopps. Beim Waiting liegen 46 / 31 / 40 / 84 Stopps in den vier aufeinanderfolgenden 300-s-Fenstern, gemessen am Routeneintritt. Diese Zahlen beschreiben die gefundene Lösung, keine bewiesene Obergrenze erreichbarer Bedienung.
- Von 1.022.076,357256 Waiting-Kosten entfallen **211.200** auf 176 unbediente Personen und **810.876,357256** auf die 1.104 bedienten Personen. Ihre mittlere Zeit von Freigabe bis Ziel beträgt **734,49 s (12,24 min)**; bei All-Stop K38 sind es **311,94 s (5,20 min)**. Alle Personen werden bei t=0 freigegeben. Der Kostenabstand entsteht also sowohl aus fehlender als auch verspäteter Bedienung.
- Codekontrolle: Im globalen Lauf sind die Anfangsereignisse und die Vorbewegung fest; der Seed wird als Hint verwendet. Die Fixierung der zukünftigen Bewegung steht ausschließlich hinter dem expliziten Diagnoseargument `fixed_movement`. Es wurde keine versehentliche Fixierung des Seed-Fahrplans gefunden. Die unabhängige Passenger-IP bestätigt außerdem die Kosten beider K39-Endfahrpläne; ein Fehler in der Bewegungsdomäne wird dadurch allein nicht ausgeschlossen.

**Einordnung:** Bisher kein nachgewiesener Codefehler als Ursache dieses Abstands. Belegt sind ein stark anderer Anfangssnapshot, ein bedienungsarmer Seed und eine auch nach 600 s bedienungsarme gefundene Lösung. Dass der Startzustand bzw. die Suche darin den Abstand wesentlich verursacht, ist eine plausible Hypothese, noch kein quantitativ isoliertes Ergebnis. Genau 39 aktive Kabinen mit festen Starts sind keine einfache Erweiterung des K38-Problems, bei der die zusätzliche Kabine beliebig entfernt werden darf.

Die nächsten sinnvollen Kontrollen sind ein freier K38-Skip-Stop-Lauf mit dem guten All-Stop-Seed (gleiche Starts, vollständige Entscheidungsfreiheit) und anschließend ein K39-Vergleich mit anderen unabhängig validierten, bedienungsorientierten Anfangssnapshots sowie unterschiedlichen Seeds innerhalb jedes identischen Snapshots. Anfangspositionen und Solver-Hints müssen dabei als getrennte Faktoren ausgewiesen werden. Eine Anlaufphase oder spätere Nachfragefreigabe würde die Instanz ändern und muss für beide Betriebsvarianten gleich behandelt werden. Diese weiteren Kontrollen wurden hier noch nicht ausgeführt.

## Versuchsaufbau

Untersucht wird dasselbe Five-Station-B-Beispiel mit K=39, 1.280 Personen, 20 OD-Gruppen, Freigabe aller Personen bei t=0, Kapazität 8 und Service-/Betriebshorizont 1.200 s. Je 600 s Gesamtbudget, 8 CP-Worker, Random-Seed 0 und Produktkodierung. Die beiden Läufe werden nacheinander auf demselben Rechner ausgeführt. Während der eigentlichen Performance-Läufe werden keine weiteren Solver oder Tests ausgeführt; lediglich kurze Log-/Dateiauswertungen und Dokumentation.

Beide erhalten den bisherigen validierten Fahrplan mit Kosten **1.272.673,026168** und **400 bedienten Personen** als Startlösung. Die Eingabe ist `benchmarks/output/ddd_integrated_cp_sat/k39/product_600s_seed0/arc_flow_seed.json`. Der Seed wird in jeder Zieldomäne erneut physisch geprüft und mit einer Integer-Passagierzuweisung versehen. Seine frühere untere Schranke wird nicht übernommen.

- **No-Wait:** unveränderte feste Startpositionen und Zeitpunkte.
- **Exit-Waiting:** dieselben Starts, Fahrzeiten, Nachfrage, Kandidaten und Kapazität; zusätzliche Warteentscheidungen nach STOP am Plattformende. `W=1200 s` je Besuch, Raster `0,000001 s`. SKIP kann nicht warten.
- Das Wartelimit ist ausdrücklich Teil dieses endlichen Experiments. Keine Behauptung, dass dies unbeschränktes Warten verlustfrei abbildet.
- Die Vorbewegung vor den festen Starts bleibt unverändert. Für die neue Plattformende-Ressource wird die aus dem Anfangszustand bekannte Belegung ergänzt: in diesem K39-Snapshot ein zusätzlicher Belegungsfall von Kabine 0 an Station A.
- Die Warteposition wird bis zur Abfahrt einschließlich Sicherheitsabstand belegt. Nachfolger auf dem Stationszweig und die Zusammenführung bleiben geschützt. Kein zusätzlicher Puffer mit mehreren frei wählbaren Plätzen.
- Boarding bleibt entsprechend dem vorhandenen EAN-Modell am tatsächlichen Plattformausgang einschließlich Wartezeit. Die Variante setzt damit voraus, dass bis zu diesem Zeitpunkt zugestiegen werden darf. In diesem Versuch liegt die gesamte Nachfrage bereits bei t=0 vor.

Dies ist ein einzelnes Laufpaar, kein belastbarer Vergleich über mehrere Seeds, Nachfragemuster oder Hardwareplattformen. Parallel arbeitendes CP-SAT kann auch bei identischem Seed unterschiedliche Suchverläufe zeigen.

## Implementierung und Prüfung

Der gemeinsame Bewegungsbaustein hatte begrenztes Warten bereits unterstützt. V2 verbindet diese Variablen mit dem integrierten Passagiermodell, Hints, Lösungsextraktion, Fixierung vollständiger Fahrpläne, Domain-Fingerprints und nativen Checkpoints. Die Zertifizierung verwendet echte Wartezeiten und den vorhandenen unabhängigen Ressourcenvalidator. Die Grid-Prüfung im Referenzvalidator erfolgt jetzt arithmetisch statt durch Enumeration: 1.200 s im Mikrosekundenraster wären sonst 1,2 Milliarden Werte.

**257 Tests bestanden vor den Performance-Läufen; die abschließende Regression umfasst 259 bestandene Tests.** Zwei zusätzliche Prüfungen sichern Alighting vor der Wartezeit am Ziel und die All-Stop-Schnittstelle ab. Die entsprechende Korrektur der All-Stop-Vorbereitung verändert die berichtete Skip-Stop-Formulierung nicht. Darunter beide Kostenkodierungen gegen vollständige Aufzählung kleiner Waiting-Fahrpläne und die unabhängige Integer-Passagier-IP, eine Mikrosekunde Wartezeit zum Erreichen einer Passagierfreigabe, Plattformblockierung gegenüber Bypass, Warten über das Horizontende, Checkpointmanipulation, Fixierung der Warteentscheidungen und Erhalt des K39-Anfangszustands. Hinzu kommen die bestehenden CP-, EAN-, Fixed-K-, Reservoir-, Waiting- und Referenztests.

Der No-Wait-Code bleibt als Standard verfügbar. Die bestehende CLI erhält `--maximum-wait-seconds` und `--waiting-step-seconds`. V2-Checkpoints schreiben sowohl Wait-Ticks als auch Sekunden. Alte V1-Checkpoints sind nur bei passendem Domain-Manifest importierbar; ein Cross-Domain-Start erfolgt über einen erneut validierten Fahrplanexport.

Geänderte Kernstellen:

- [Gemeinsame Bewegung](../../src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_movement.py)
- [Passagierkopplung](../../src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_passenger.py)
- [Integrierter Solver](../../src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_integrated.py)
- [Zertifikat und Checkpoint](../../src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_certificate.py)
- [Referenzvalidierung](../../src/ropeway_skip_stop_optimization/optimization/ddd/reference.py)
- [Anfangszustand in Waiting überführen](../../src/ropeway_skip_stop_optimization/benchmarking/ddd_cp_sat_waiting.py)
- [Neue Waiting-Tests](../../tests/test_optimization_ddd_cp_sat_waiting.py)

## Horizonte

Die bestehende DDD-Regel bleibt erhalten: Besuche mit Eintritt bis H sind aktiv; die letzte begonnene Route wird abgeschlossen, auch wenn ihre Beendigung nach H liegt. Ressourcen mit Eintritt bis H behalten ihr vollständiges Schutzintervall über H hinaus. Erst nach H betretene Ressourcen gehören nicht zur bisherigen betrieblichen Prüfdomain. Boarding und Alighting bleiben spätestens bei T.

Ein wartender letzter Besuch kann deshalb über H hinausreichen. Das ist ein gültiger endlicher Plan in dieser Domain, kein Nachweis einer unbegrenzt nachhaltigen Fortsetzung. Die Nachauswertung berichtet Zahl und Dauer solcher Wartevorgänge separat. Ein periodischer Betrieb wurde nicht vorgeschrieben.

## Ergebnisse

**Exit-Waiting liefert in diesem Laufpaar deutlich bessere Fahrpläne, aber schwächere native Schranken und höheren Speicherbedarf.** Beide enden `FEASIBLE` am Zeitlimit. Die finale unabhängige Integer-Passagier-IP bestätigt für beide festen Fahrpläne den CP-Kostenwert exakt und meldet `OPTIMAL` für diese feste Bewegung, nicht global.

| Kennzahl | No-Wait | Exit-Waiting, W=1200 s |
|---|---:|---:|
| Validierte Kosten (UB) | 1.262.099,935264 | **1.022.076,357256** |
| Native CP-Untergrenze | 396.586,502464 | 76.434,936077 |
| Gap | 68,58 % | 92,52 % |
| Bediente Personen | 416 / 1.280 | **1.104 / 1.280** |
| Nicht bediente Personen | 864 | 176 |
| Tatsächliche Gesamtdauer | 600,336 s | 600,533 s |
| Variablen vor → nach Presolve | 43.986 → 17.268 | 51.076 → 27.978 |
| Constraints vor → nach Presolve | 92.596 → 31.820 | 106.782 → 56.056 |
| Ressourcenintervalle vor Presolve | 5.677 | 7.096 |
| Peak-RSS des gesamten Prozesses | 1.984,5 MB | 3.486,5 MB |

Waiting senkt die Kosten gegenüber dem frischen No-Wait-Lauf um **19,02 %** und bedient **688 zusätzliche Personen**. Gegenüber der gemeinsamen Startlösung beträgt die Kostenverbesserung 19,69 %. No-Wait verbessert die gemeinsame Startlösung um 0,83 %.

Dies ist ein Vergleich zweier Betriebsvarianten: Waiting erweitert die zeitlichen Entscheidungen und ergänzt dafür die physischen Belegungen. Es ist kein Beleg, dass CP-SAT dieselbe mathematische Aufgabe schneller löst. Die größere Flexibilität kann bessere Fahrpläne zulassen, während das Beweisen ihrer Qualität schwieriger bleibt.

### Zeitanteile

| Phase | No-Wait | Waiting |
|---|---:|---:|
| Instanz/Startzustand vorbereiten | 4,259 s | 4,060 s |
| Gemeinsamen Seed neu bewerten | 0,695 s | 0,702 s |
| Integrierter Aufbau inkl. Prüfung/Hints | 1,088 s | 1,102 s |
| Solveraufruf inkl. Presolve und Callbacks | 593,974 s | 594,313 s |
| Davon bis zum protokollierten Suchstart | 16,52 s | 22,89 s |
| Abschließende Validierung/Checkpoint | 0,197 s | 0,231 s |

Die Suchstartzeit ist eine Teilmenge des Solveraufrufs. Kleine weitere Runnerarbeiten erklären die verbleibenden Differenzen zur Gesamtdauer. Callback- und Loggingzeiten sind noch nicht separat als End-to-End-Komponenten gemessen. Die native Modellgröße vor Presolve steigt moderat; nach Presolve bleiben beim Waiting jedoch rund 62 % mehr Variablen und 76 % mehr Constraints übrig. Peak-RSS steigt ebenfalls um etwa 76 %.

### Verlauf

Zeit seit Optimizerstart, nach Instanzvorbereitung/Seedimport. Zwischenwerte aus dem Eventprotokoll, finale Kosten unabhängig validiert. UB berücksichtigt die externe Startlösung bereits ab Zeitpunkt null. Native Bounds werden konservativ abgerundet und unten bei null abgeschnitten.

| Zeitpunkt | No-Wait UB | No-Wait LB | Waiting UB | Waiting LB |
|---|---:|---:|---:|---:|
| 1 min | 1.270.826,05 | 0 | 1.196.698,58 | 0 |
| 2 min | 1.269.311,08 | 370.816,68 | 1.160.190,77 | 50.503,09 |
| 5 min | 1.264.365,78 | 388.092,94 | 1.087.296,24 | 50.504,69 |
| 7 min | 1.263.718,29 | 392.757,40 | 1.034.566,29 | 57.854,52 |
| Laufende, etwa 10 min | 1.262.099,94 | 396.586,50 | 1.022.076,36 | 76.434,94 |

Waiting verbessert die UB zwischen Minute fünf und Laufende um weitere **6,00 %**. Die letzte Incumbentmeldung kommt bei **594,63 s**, also unmittelbar vor Laufende; die letzte gespeicherte LB-Verbesserung bei **532,12 s**. Insgesamt gibt es 309 CP-Incumbentmeldungen, inklusive Seed und eventueller nahezu identischer Werte. Daraus folgt kein beobachtetes spätes Lösungsplateau für diesen zehnminütigen Waiting-Lauf.

No-Wait meldet 16 Incumbents; zuletzt bei 532,41 s. Die letzte gespeicherte Schrankenverbesserung liegt bei 454,45 s. Von Minute fünf bis Laufende verbessert sich seine UB um etwa 0,18 %. Die Unterschiede sind Beobachtungen eines Laufpaars, keine Prognose für jede weitere Stunde.

Im Waiting-Log kommen die meisten Incumbentbeiträge aus Graph- und anderen LNS-Nachbarschaften. Die späten LB-Verbesserungen kommen vor allem aus `max_lp`. Das passt zur Hypothese, dass zeitliche Reparaturen bei festgehaltenen Teilen eines Fahrplans nützlich sind; eine kausale Zerlegung der Wirkung wurde nicht durchgeführt.

### Tatsächlich verwendetes Warten

Im finalen Waiting-Fahrplan:

- **86 positive Wartevorgänge**, zusammen **500,931118 s** über alle Kabinen und Stationen.
- Median der positiven Wartezeiten **3,88949 s**, Maximum **33,236228 s**.
- **Kein finaler Wartevorgang reicht über H hinaus**; keiner erreicht das Limit W=1200.
- 201 STOP-Besuche unter 1.252 aktiven Besuchen. Warten wird an allen fünf Stationen verwendet.

| Station | Positive Wartevorgänge | Summe Sekunden | Maximum Sekunden |
|---|---:|---:|---:|
| A | 17 | 114,390295 | 24,650234 |
| B | 20 | 118,418307 | 17,382936 |
| C | 17 | 105,696749 | 33,236228 |
| D | 20 | 114,236854 | 17,376903 |
| E | 12 | 48,188913 | 9,525855 |

Einige frühere Zwischenstände enthielten Wartevorgänge über H; der finale Plan tut dies nicht. Der beobachtete Gewinn beruht somit nicht auf solchen finalen Wartevorgängen. Daraus folgt trotzdem kein Beweis für eine nachhaltige Fortsetzung nach H oder dafür, dass 34 s als globale Warteobergrenze ausreichen würden.

### Unabhängige Nachprüfung und Identität

Beide finalen Checkpoints wurden gegen neu vorbereitete Zieldomänen eingelesen und physisch/integer validiert. Danach erfolgte die EAN-Konvertierung und bestehende Fixed-Movement-Passagier-IP mit einem Gurobi-Thread, maximal 30 s und MIPGap=0. Sie bestätigt die exakten Kosten beider Pläne. Die reinen Solve-Zeiten waren etwa 0,00030 s (No-Wait) und 0,00088 s (Waiting); Konvertierung, Validierung und IP-Aufbau/Solve nach Instanzvorbereitung etwa 0,420 bzw. 0,433 s. Dieser Postprocess lief nach beiden Performance-Läufen und außerhalb ihrer Budgets.

Der Vergleich bestätigt identische kanonische Starts, Horizonte, Releases, Nachfrage, Ride-Kandidaten, Kapazität, Objective, Operating Mode und initiale physische Zustände. Die Waiting-Policy und der um Wartebelegungen ergänzte Ressourcenbestand unterscheiden sich ausdrücklich.

- No-Wait Domain-Fingerprint: `f8b765b7b1821a2ac4746aed1cbdc3511fc813d47ed5cb8e347dac913ba6186b`.
- Waiting Domain-Fingerprint: `9825bcd8af25c3d0d5eea6613158f4c548477771c4c763b855831574c88a96a4`.

### Entscheidung für die nächste Runde

Waiting als relevante Hauptvariante weiter untersuchen. Ein längerer unveränderter Waiting-Lauf ist durch die bis zuletzt fallende UB begründet; parallel im Arbeitsplan, nicht gleichzeitig auf derselben Benchmarkmaschine, stärkere gültige Zeit-/Produktgrenzen vorbereiten. Eine zweite Zufalls-Seed-Wiederholung bleibt nötig.

Ein späterer Vergleich mit einem engeren W kann untersuchen, wie stark die breite Warte-Domäne die Suche erschwert. Ein kleineres W wäre dabei eine explizite Modellvariante, keine bereits bewiesene verlustfreie Reduktion. Insbesondere begründet das beobachtete Maximum von 33,24 s keine allgemein gültige Obergrenze.

Noch offen: vollständige Bedienung (176 Personen verbleiben unbedient), engere globale Schranke, längere Läufe, Wiederholungen, zeitlich verteilte Nachfrage und Prüfung des gewünschten Betriebs nach dem Horizont. Kein weiterer Langlauf oder W-Sweep wurde automatisch gestartet.

## Reproduktion und Artefakte

Software-Repository als Arbeitsverzeichnis:

```sh
.venv/bin/python benchmarks/run_ddd_fixed_k_cp_sat.py \
  --example five_station_circle_cw_half_skip_no_wait_headway_b_v0 \
  --cabins 39 --start-policy balanced_reference \
  --maximum-wait-seconds 1200 --waiting-step-seconds 0.000001 \
  --time-limit 600 --num-workers 8 --seed 0 --cost-encoding product \
  --primal-seed-result benchmarks/output/ddd_integrated_cp_sat/k39/product_600s_seed0/arc_flow_seed.json \
  --log-search-progress \
  --output-dir benchmarks/output/ddd_integrated_cp_sat_waiting/k39/w1200_repeat
```

Für die No-Wait-Referenz `--maximum-wait-seconds 0` und einen anderen Output-Ordner verwenden. Wiederholungen können aufgrund der parallelen Suche abweichende Ergebnisse liefern.

Die eigentlichen Läufe liegen in `benchmarks/output/ddd_integrated_cp_sat_waiting/k39/w1200_600s_seed0/` und `no_wait_600s_seed0/`. Jeder enthält Konfiguration, Resultat, natives Solverlog, strukturierte Events und einen validierten Checkpoint. Zusätzlich liegen `progress.csv`, `post_ip_validation.json` und `best_incumbent.json` je Lauf vor, sowie `comparison.json` im gemeinsamen K39-Ordner. Das verwendete Nachauswertungsskript ist dort als `analyze_results.py` abgelegt. Der gemeinsame Output-Bereich ist lokal gitignored.

Vorläufe: `build_w1200/` scheiterte vor dem Solve am unvollständig erhaltenen Ressourcenbestand; der Rebuild verwendet seit der Korrektur deaktivierte Ressourcenreduktion. `build_w1200_v2/` baute das vollständige Modell erfolgreich. `smoke_w1200_30s/` endete nach Presolve ohne interne CP-Lösung, behielt aber den unabhängig gültigen externen Seed. Dieser Smoke-Test zählt nicht zum Performancevergleich.
