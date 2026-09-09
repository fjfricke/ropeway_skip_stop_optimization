# CP-SAT-Anlaufphase: kontrollierter K39-Versuch

Stand: 9. September 2026. Vor Ausführung festgelegter Plan.

**Ausgeführt:** Zwei 600-s-Läufe abgeschlossen. Rohkosten nur 0,402 % besser mit Anlauf, 96 weniger bediente Personen, Gap 100 % statt 91,66 %. Unabhängige EAN-Prüfung des Anlauf-Endfahrplans scheitert an einer Horizont-/Toleranzabweichung; kein vollständig bestätigter Vorteil. Ergebnisse, Artefakte und offene Endbehandlung: [Warmup-Gate](../findings/ddd_cp_sat_warmup_gate.md).

## Frage und Grenzen

Verbessert eine gemeinsam mit dem Passagierfahrplan optimierte, leere Anlaufphase die gefundenen Lösungen aus dem bisherigen K39-Snapshot? Die Anfangspositionen bleiben bei t=0 physisch fest; der Zustand bei Nachfragefreigabe ist Ergebnis der Optimierung. Dies ist eine erreichbare Teilmenge freier Anfangsanordnungen, kein allgemeines Initial-Placement-Modell. Keine Periodizität und kein fixierter Anlauf-Fahrplan im Solver.

## Zwei neue, sequenzielle Läufe

Five-Station-B, halbe Nachfrage, genau 39 aktive Kabinen, Skip-Stop mit Exit-Waiting W=1200 s und 1-us-Raster. Je 600 s Gesamtbudget, 8 Worker, Seed 0, Produktkodierung. Dieselbe bisherige physische Anfangsanordnung und Vorbewegung; alle Sicherheitsressourcen bleiben auch während der Anlaufphase aktiv.

| Variante | Nachfragefreigabe | Serviceende T / Betriebsende H | Zeit je Person bis Cutoff |
|---|---:|---:|---:|
| Kontrolle | 0 s | 1200 s | 1200 s |
| Anlauf | 300 s | 1500 s | 1200 s |

20 OD-Gruppen mit zusammen 1280 Personen, Kapazität 8 bleiben gleich. Kosten sind Zeit ab individueller Freigabe bis Ziel; Unbedient-Strafe bleibt 1200 pro Person. Keine Passagierbedienung vor Freigabe. Ein wartender, schon vor Freigabe begonnener Stationsbesuch darf danach bedienen, entsprechend bestehender Boarding-Semantik.

Beide Läufe nutzen dieselbe durchgehend bis 1500 s validierte Startbewegung; die Kontrolle erhält deren bis 1200 s reichenden Präfix. Der Seed ist lediglich ein Hint. Die bessere frühere K39-Startlösung hat keine validierte Fortsetzung über 1200 s hinaus; ihr bisheriger 600-s-Waiting-Lauf dient daher nur als zusätzliche Referenz (UB 1022076,357256), nicht als alleinige Kontrolle. Seedkosten werden separat berichtet, da die Nachfrage in einer anderen Phase einsetzt.

### Anpassung vor den Hauptläufen: sichere Seed-Fortsetzung

Die geplante unveränderte periodische Fortsetzung wurde vom Ressourcenvalidator abgelehnt: ein zusätzlicher Konflikt an `exit_switch::C_entry_cw` zwischen Kabine 0/Besuch 21 und Kabine 18/Besuch 35 wird im längeren Zertifizierungshorizont sichtbar. Daher wird kein endlicher Seed automatisch extrapoliert; die Benchmark-Transformation verwirft bestehende Seeds.

Stattdessen erzeugt ein separater physischer CP-SAT-Aufruf die gemeinsame 1500-s-Startbewegung: dieselbe Routingvorlage (eine All-Stop-, 38 All-Skip-Kabinen), aber freie Exit-Wartezeiten und minimale Gesamtwartezeit. Nur dieser Seed-Generator fixiert die Routingvorlage, die beiden Hauptläufe nicht. Er findet in 0,510 s eine optimale Lösung seiner eingeschränkten physischen Aufgabe. Gesamte Vorbereitung einschließlich Snapshot und beider Passagierbewertungen wird in `seed_preparation.json` gespeichert. Seedkosten: Kontrolle **1441651,791880**, Anlauf **1437094,223280**; beide bedienen 168 Personen. Der geringe Unterschied von ca. 0,32 % besteht bereits ohne weitere Fahrplanoptimierung. Die vollständige Startbewegung benötigt insgesamt 8,289283 s Exit-Waiting.

Die 41 gezielten Tests für Benchmark, Warmup, Waiting und integriertes CP-SAT bestehen vor Beginn der Hauptläufe. Darunter unabhängige IP-Kostenprüfung mit verschobener Nachfrage, INFEASIBLE bei erzwungenem vorzeitigem Boarding, unveränderte K39-Anfangsressourcen und ausreichende neue Visitgrenzen.

## Umsetzung und Prüfungen

1. Kleine Benchmark-Transformation: Releases und Serviceende gemeinsam verschieben, Artefakt/Visitgrenzen/Passagierkandidaten für längeren Horizont neu bauen, physische Anfangspositionen und Boundary unverändert übernehmen. CLI `--warmup-seconds`, Standard 0.
2. Prüfungen für unveränderte physische Randbedingungen und Nachfrage, konstantes Objective-F0, ausreichende Visitgrenzen, verlängerten Seed und Verbot vorzeitigen Boardings. Kosten des konkreten Fahrplans durch unabhängige Integer-Passagier-IP kontrollieren.
3. Zwei Läufe sequenziell, keine weiteren Solver während ihrer Laufzeit. Logs, Incumbents, Modellgröße, Zeitverlauf, Bounds und Peak-RSS speichern.
4. Endlösungen unabhängig validieren und mit fester Bewegung erneut ganzzahlig zuordnen. Bedienung, Kosten, Stopps im Servicefenster und Anlaufentscheidungen getrennt auswerten. K38-All-Stop mit Kosten 399287,271408 bleibt Betriebsreferenz für seinen bekannten Zustand zu Beginn der Bedienung; keine ungeprüfte Annahme identischer Kosten nach 300 s Fortsetzung desselben K38-Snapshots.

## Interpretation

Ein besseres Ergebnis zeigt, dass die erlaubte Anlaufphase in diesem Versuch nutzbar ist; ein Teil kann schon aus der Phasenlage des Seeds stammen. Es isoliert nicht die gesamte Ursache des bisherigen Abstands. Ein schlechtes Ergebnis widerlegt die Anfangszustands-Hypothese nicht, weil das längere Modell zusätzliche Sucharbeit verlangt. Je ein Lauf pro Variante ist ein erster Test, keine statistisch belastbare Solverbewertung.
