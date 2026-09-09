# Reservierungs-/Einfügepilot: K39

Stand: 9. September 2026. **Prototyp integriert und getestet.** Korrektheit und erste Verbesserungsmöglichkeit bestätigt; das Geschwindigkeitsziel und ein Vorteil größerer Reparaturen sind noch nicht erreicht. [Implementierte Architektur](../reference/ddd_reservation_insertion.md), [abgeschlossener Umsetzungsauftrag](../plans/reservation_insertion_implementation.md).

## Vergleichsvertrag

Identischer ursprünglicher K39-Waiting-Plan, feste Startanordnung, Nachfrage und akzeptierter endlicher Horizont. Startziel: **1.022.076,357256 Passagiersekunden**, 1104 bedient, 176 unbedient. Alle drei Varianten verwenden dieselben 100 gespeicherten Anfragen aus drei OD-Gruppen; die Identität von `requests.json` wurde geprüft. Jede Anfrage startet erneut von der unveränderten Baseline; gefundene Verbesserungen werden hier nicht akkumuliert.

Reparaturbudget pro Anfrage: 0,25 s. Vollständige Validierung folgt separat. Gesamtgrenzen 30/60/40 s für die drei Läufe; alle 100 Anfragen wurden jeweils abgeschlossen. Der Vergleich betrifft gleiche Anfragen und lokale Budgets, keinen Mehrseed-Vergleich gleicher globaler Suchzeit. Die Varianten wurden nacheinander ausgeführt. Es war keine CPU-isolierte Messung: Kurze Entwicklungsprüfungen liefen zum Teil nebenher. Die Laufzeiten sind diagnostische Messwerte, kein statistisch abgesicherter Leistungsvergleich.

## Messwerte

| Variante | Gesamtlaufzeit | Vorbereitung | Reparatur gesamt | vollständige Kandidatenvalidierung | zulässige Serviceversuche / verschiedene Bewegungen | bester schneller Zielwert |
|---|---:|---:|---:|---:|---:|---:|
| Max. 1 Kabine, Beam 8 | 27,886 s | 6,107 s | 18,768 s | 2,117 s | 4 / 2 | 1.014.271,187944 |
| Max. 4 Kabinen, Beam 8 | 34,229 s | 6,154 s | 25,061 s | 2,117 s | 4 / 2 | 1.014.271,187944 |
| Max. 4 Kabinen, Beam 1 | 33,291 s | 6,054 s | 24,236 s | 2,109 s | 4 / 2 | 1.020.993,580848 |

Die übrige Zeit liegt unter anderem in initialer Validierung, Kalenderaufbau und Checkpoint-Ausgabe. Schnelle Passagierbewertung insgesamt nur rund 0,018 s pro Lauf. Peak-RSS etwa 147–157 MiB, Prozesslebenszeit; kein isolierter Speicherbedarf einzelner Klassen. Der Kern erzeugt keine CP-/MIP-Variablen, sondern explizite Belegungen und Suchlabels.

Median/p95 der vollständigen Anfrage:

- Eine Kabine, Beam 8: 0,233 / 0,251 s; 72 eingeschränkte Suchmisserfolge, 24 Budgetabbrüche, 4 zulässige Anfragen.
- Vier Kabinen, Beam 8: 0,251 / 0,251 s; 96 Budgetabbrüche, 4 zulässige Anfragen.
- Vier Kabinen, Beam 1: 0,251 / 0,251 s; 96 Budgetabbrüche, 4 zulässige Anfragen.

Ein erfolgreicher Versuch braucht zusätzlich ungefähr eine halbe Sekunde Validierung; nur vier solcher Versuche liegen oberhalb der 95-%-Quantilsgrenze. Das p95 allein beschreibt deshalb die erfolgreichen Einfügungen nicht ausreichend. **Die vorläufige Messlatte p95 < 100 ms wird verfehlt.**

Die größere Beam-8-Reparatur erreicht bei 76 Anfragen zwei und bei 20 Anfragen drei freigegebene Kabinen. Mit Beam 1 erreichen 94 Anfragen vier Kabinen. Die vier erfolgreichen Anfragen bleiben jeweils Ein-Kabinen-Reparaturen. Daraus folgt kein Unzulässigkeitsnachweis für größere Pakete: Fast alle betreffenden Versuche laufen ins Budget.

## Qualität und unabhängige Passagiernachoptimierung

Der beste neue Bewegungsplan verändert **Kabine 34**. Die schnelle Zuordnung erreicht 1112 bediente und 168 unbediente Personen: acht zusätzliche Personen und **0,7637 %** weniger Kosten. Die andere neue Bewegung verändert Kabine 38. Jeweils q=1 und q=8 erzeugen dieselbe Bewegung mit anschließendem Auffüllen der Kapazität; vier erfolgreiche Anfragen sind deshalb nur zwei verschiedene Pläne.

Die bestehende `DddEanPassengerPrimalEvaluator`-Nachoptimierung wurde getrennt auf unveränderter Baseline und bestem neuem Plan ausgeführt, mit einem Worker und maximal 10 s pro Assignment-IP. Das Kandidatenuniversum wurde gegen das gemeinsame Problem geprüft.

| Feste Bewegung | Beste vorherige Zuordnung | Optimale Zuordnung für diese Bewegung | Bedient / unbedient |
|---|---:|---:|---:|
| Ursprünglicher K39-Plan | 1.022.076,357256 | 1.022.076,357256 | 1104 / 176 |
| Neuer Reservierungsplan | 1.014.271,187944 | **1.007.532,083464** | **1112 / 168** |

Beide Assignment-IPs melden OPTIMAL. Die Evaluator-Gesamtzeit inklusive Adapter lag im ersten Vergleich bei 0,450 bzw. 0,433 s; separate Instanzvorbereitung/Import gehören nicht zu diesen beiden Zahlen. Der zweite Wert verbessert den bisherigen K39-Ausgangspunkt um **14.544,273792 Passagiersekunden bzw. 1,4230 %**. Die Verbesserung kommt nicht allein aus Nachoptimierung der alten Bewegung. Das neue Assignment wurde nochmals mit dem gemeinsamen Integer-Zertifikat geprüft und als CP-Seed gespeichert und zurückgelesen.

OPTIMAL bezieht sich ausschließlich auf das Assignment bei fester Bewegung. Es gibt keine neue globale LB und keinen Beleg, dass der globale Gap durch längere Laufzeit geschlossen wird. Auch ein Vorteil gegenüber der anders gestarteten All-Stop-K38-Referenz ist damit nicht gezeigt.

## Tests und Integration

226 gezielte neue und bestehende Tests bestanden im abschließenden kombinierten Lauf (30,01 s). Abgedeckt sind lokale Intervalle gegen vollständige Enumeration, Wait-Raster, H-Grenzen, Wait-Orte, Transaktionen, zwei gemeinsam zu reparierende Kabinen, vollständige Service-/Kapazitätsprüfung, Checkpoint-/CP-Kompatibilität und die bestehenden DDD/EAN-/Waiting-/Benchmark-Verträge. Neue Module bestehen Ruff-Prüfung und Formatierung.

Ein gezielter kleiner Fall scheitert mit nur einer veränderbaren Kabine und gelingt mit zwei; die resultierende Bedienung besteht die unabhängige Prüfung. Ein weiterer Fall erzwingt Warten am vorherigen Exit, weil ein späterer Eintritt nicht durch Warten an diesem Eintritt verzögert werden darf. Der Mehrkabinentest verbietet Aufrufe von Gurobi-Modellen und CP-SAT-Solves.

Die gemeinsame Zertifikatslogik liegt jetzt in `fixed_k_certificate.py`, vorhandene CP-Funktionen bleiben kompatible Wrapper. Alte Ergebnisdateien wurden nicht verändert. Der neue Algorithmus verwendet die vorhandenen DDD-Trajektorien, EAN-Adapter, Ressourcendefinitionen, Ride-Kandidaten und Fortschrittsereignisse.

## Ergebnisorte

Alle folgenden Pfade sind relativ zum Software-Repository und liegen im gitignorierten Benchmark-Ausgabeordner:

- `benchmarks/output/ddd_reservation_insertion/k39_scope1_beam8_v1/`
- `benchmarks/output/ddd_reservation_insertion/k39_scope4_beam8_v1/`
- `benchmarks/output/ddd_reservation_insertion/k39_scope4_beam1_v1/`
- `benchmarks/output/ddd_reservation_insertion/assignment_comparison_v1.json`
- **Bester geprüfter Stand:** `benchmarks/output/ddd_reservation_insertion/assignment_polished_v1/incumbent.json`
- **CP-kompatibler Warmstart:** `benchmarks/output/ddd_reservation_insertion/assignment_polished_v1/cp_seed.json`

Quell-Run: `benchmarks/output/ddd_integrated_cp_sat_waiting/k39/w1200_600s_seed0/`. Domain-Fingerprint: `9825bcd8af25c3d0d5eea6613158f4c548477771c4c763b855831574c88a96a4`.

## Entscheidung nach dem ersten Pilot (durch Abschlussbewertung unten ergänzt)

Der Pilot belegt eine kleine neue Verbesserungsmöglichkeit. Er belegt noch keinen skalierbaren schnellen Konstruktionsalgorithmus. Zunächst Reparaturprofiling und begrenzte Verbesserung der Kandidaten-/Zeitfenstersuche; **keine ALNS-Ausweitung auf Basis dieses Ergebnisses**. Insbesondere gemeinsame Blockiererkombinationen, Prioritätswahl und das Festhalten früherer Präfixe sind aktuelle Heuristikrestriktionen. Die unterschiedlichen Ergebnisse bei Beam 1 und 8 zeigen zudem, dass bloßes Verengen der Suche keine ausreichende Beschleunigungsstrategie ist.

## Abgeschlossener Profil-/Integrationsschritt

Der erste Profil-Lauf mit 30 Anfragen und vier Kabinen lokalisierte 4,795 s kumulierte Zeit in den Fensterabfragen von insgesamt 7,557 s Reparaturzeit; Lookahead 1,078 s, Reservierungsmaterialisierung 0,487 s. Diese Zeiten sind verschachtelt und dürfen nicht addiert werden. `_path` inklusive Beam und Unterfunktionen belegt 7,460 s; die eigene Zeit des übergeordneten `repair` beträgt nur 0,005 s. Eine separate exakte Beam-Sortiermessung wurde nicht eingeführt. Der dominierende konkrete Fehler in der Implementierungseffizienz war das wiederholte Lesen der Horizont-Property: Sie konstruiert intern einen MovementCore. Im gesamten Profil wurde sie 818.952-mal gelesen. Profilierte, zeitbegrenzte Suchläufe sind keine unverzerrten Qualitätsbenchmarks.

Der begrenzte Verbesserungsversuch speichert unveränderte Horizont-/Ressourcendaten je Solver und ergänzt einen konservativen Kalenderindex aus Eintrittszeiten und Präfixmaxima von Räumzeit plus Headway. Er erhält auch lange frühere Belegungen. Kein neues Dominanzargument, kein verändertes Warte-Raster und keine gelockerte Ressourcenbedingung.

Direkter ABBA-Vergleich auf derselben vorbereiteten K39-Instanz, 1.000 identische Abfragen:

| Fensterimplementierung | Zeiten für 1.000 Abfragen | Paarprüfungen |
|---|---:|---:|
| Rekonstruierte bisherige vollständige Schleife | 2,085 / 1,903 s | 306.788 |
| Cache und Kalenderindex | 0,323 / 0,323 s | 81.873 |

Alle Intervalle und Blockierermengen stimmen überein. Medianfaktor **6,17**, rund **73,3 % weniger Paarprüfungen**. Das ist ein lokaler Fixed-Work-Vergleich, kein Faktor für den vollständigen Algorithmus. Quellskript, rekonstruierte Vergleichsschleife, Rohwerte und ursprüngliches Profil liegen in `followup_profile_evidence/` unter dem Ergebnisordner.

Die erneuten 0,25-s-Läufe finden unter der aktuellen Rechnerlast keine neue Bewegung: eine Kabine 78 Budgetabbrüche / 22 begrenzte Suchmisserfolge, vier Kabinen 100 Budgetabbrüche. Vorbereitung jetzt 27–29 s statt zuvor etwa 6 s. Parallel lief eine CPU-intensive Anwendung; diese wurde nicht verändert. Die früheren und späteren absoluten Laufzeiten sind deshalb kein sauberer Beschleunigungsnachweis. Gleiche Requests und Domäne bleiben gewahrt.

### Validierungsentscheidung

Adapter und gemeinsames Zertifikat prüfen teilweise dieselbe DDD-Bewegung. Die APIs tragen jedoch keinen expliziten, unveränderlichen Validierungsnachweis, der an die vollständige Domäne gebunden ist; das eingefrorene Plan-Dataclass enthält zudem mutable Count-Dictionaries. Deshalb bleibt die unabhängige Prüfung bestehen. Bei überwiegend erfolglosen Reparaturen erklärt sie nicht das Suchplateau. Ein neues Zertifikats-Caching-System wäre ein zusätzlicher Architekturumbau ohne hier nachgewiesenen Nutzen.

### Optionaler Assignment-Abschluss

`DddReservationAssignmentRefiner` komponiert den bestehenden Evaluator, mit explizitem kanonischem Kandidatenuniversum und Prüfung von Bewegung, Waiting, Artefakt und Ziel. Die abgeschlossene Implementierung prüft höchstens drei unterschiedliche native Finalisten und die ursprüngliche Bewegung als Kontrolle. Der ursprüngliche 100-Anfragen-Folgelauf unten entstand noch mit einem Suchfinalisten. Die Auswahl ist bewusst klein und kann einen anderen, nach optimalem Assignment besseren Finalisten übersehen. Es wurde kein zweites Assignment-Modell implementiert.

`--passenger-seconds` aktiviert diesen Schritt. Höchstens 25 % des nach Vorbereitung verbleibenden Budgets, gedeckelt durch viermal das IP-Limit (in den ersten Folgeläufen noch zweimal), werden vor der Suche reserviert. Jeder IP erhält höchstens sein Limit bzw. die verbleibende Zeit. Modellaufbau, Adapter und Zertifizierung sind nicht präemptiv; die globale Grenze ist weich und Überschreitungen werden ausgewiesen. Ergebnisse trennen native UB und Assignment-Ergebnis. Jeder abgeschlossene Lauf schreibt einen validierten CP-Seed. Die Zuordnungsoptimierung ersetzt einen Plan nur bei Verbesserung; sie liefert keine globale LB.

### Längerer Suchversuch und Abschlussbewertung

`followup_cached_scope4_1500ms/`: dieselben 100 Anfragen und dieselbe Domäne, maximal vier Kabinen, Beam 8, jetzt **1,5 s Reparaturbudget je Anfrage**, 240 s Gesamtbudget, 5 s je optionalem Assignment-IP. Gesamtzeit **209,052 s**, davon Vorbereitung 25,441 s, Reparatur 131,651 s, schnelle Passagierbewertung 0,336 s und Kandidatenvalidierung 41,211 s. 10.261.857 Paarprüfungen, 324.774 erzeugte Labels, Peak-RSS 165,2 MiB. Kein eigener globaler MIP-/CP-Bewegungsmodellaufbau im Reparaturkern.

- 18 zulässige Versuche erzeugen **9 unterschiedliche Bewegungen**, alle mit genau **einer** geänderten Kabine. 82 Budgetabbrüche.
- Die erfolglosen Versuche erreichen 61-mal drei und 21-mal vier freigegebene Kabinen. Mehr gemeinsamer Suchumfang ist damit tatsächlich erreicht, bisher ohne zusätzlichen validierten Mehrkabinen-Erfolg.
- Anfrage-Median **1,505 s**, p95 **2,936 s** einschließlich Validierung. Mehr Zeit findet mehr Bewegungen, verfehlt aber weiter das Ziel eines sehr schnellen Reparaturkerns.
- Native beste UB **1.011.534,810440**; integrierter Assignment-IP **1.008.673,472296**, **1120 bedient / 160 unbedient**. Verbesserung gegenüber Ausgangs-K39 **1,3113 %**. Der IP benötigt einschließlich Evaluator und Zertifizierung 2,973 s; Baseline-Kontrolle 2,390 s und unverändert 1.022.076,357256. Beide Assignment-Status OPTIMAL.
- Der vorher gesicherte Plan **1.007.532,083464** bleibt bei Journey-Time besser, obwohl er mit 1112 Personen acht weniger bedient. Ziel ist die Summe der Passagierzeiten einschließlich unbedienter Nachfrage, nicht allein die Anzahl bedienter Personen.

Die Auswahl nach schneller Zuordnung garantiert keine identische Rangfolge nach Assignment-IP. Dieser Messlauf verwendete noch nur den nativen besten Suchfinalisten plus Baseline. Die finale Implementierung erweitert dies auf drei Suchfinalisten; sie optimiert weiterhin nicht automatisch alle Bewegungen. Deshalb ist hier **kein Nachweis erbracht, dass unter den anderen acht Bewegungen keine weitere Verbesserung liegt**. Ebenso beweisen 82 Budgetabbrüche keine Unzulässigkeit gemeinsamer Reparaturen. Die Ergebnisse tragen eine begrenzte Entwicklungsentscheidung, keinen generellen Negativsatz über Reservierungsalgorithmen.

**Entscheidung für die verbleibende Thesis-Zeit:** Den Kern und beide validierten Ergebnisse als begrenzte UB-Heuristik/CP-Seed-Erzeuger behalten; die effiziente exakte Fensterberechnung wiederverwenden. Jetzt keine Greedy-/Regret-/ALNS-Implementierung darauf aufbauen. Der lokale Rechenengpass ist verbessert, aber ganze Reparaturen bleiben teuer, größere gekoppelte Änderungen bringen noch keinen Mehrwert, und der längere Lauf schlägt den gespeicherten Bestwert nicht. Eine neue globale LB oder Aussicht auf automatisches Gap-Schließen ist damit nicht entstanden. Das bedingte Ausbau-Gate im Umsetzungsplan ist entschieden und der begrenzte Auftrag abgeschlossen.

Zusätzliche Ergebnisorte (alle unter `benchmarks/output/ddd_reservation_insertion/`):

- `followup_profile_before/`, `followup_profile_evidence/` — Profil, gepaartes Vergleichsskript und Rohwerte.
- `followup_cached_scope4/`, `followup_cached_scope1_integrated/` — identische 0,25-s-Anfragen unter aktueller Rechnerlast.
- `followup_cached_scope4_1500ms/` — längerer Test, integrierte Zuordnung, `incumbent.json` und `cp_seed.json`.

Die `requests.json` dieser drei Folgeversuche sind bytegleich mit dem ursprünglichen Pilot. Historische Ergebnisse und der vorherige Bestplan wurden nicht überschrieben.

### Finale Integration: drei Suchfinalisten

Die abgeschlossene Version hält die drei nach schneller Zuordnung besten unterschiedlichen Bewegungen in `DddReservationInsertionResult.finalist_plans`; identische Bewegungen werden zusammengeführt. Der Runner prüft diesen Pool plus Baseline mit dem bestehenden IP. Damit hängt die Nachoptimierung nicht mehr ausschließlich von einer einzigen nativen Rangentscheidung ab. Die Poolgröße bleibt eine bewusste Einschränkung, keine Garantie vollständiger Kandidatenauswertung.

`followup_finalist_replay/` reproduziert die neun vorher erfolgreichen Anfragen (jeweils eine Menge pro Ride-ID). **9/9 zulässig**, dieselben neun Bewegungen; Assignment-Ergebnisse der drei ausgewählten Finalisten **1.008.673,472296 / 1.008.673,472296 / 1.008.945,472296**, alle OPTIMAL, Baseline unverändert. Bestwert bleibt 1.008.673,472296. Das ist ein gezielter Integrations-/Rangfolgetest auf vorher ausgewählten Erfolgen, kein neuer unvoreingenommener Suchvergleich. Gesamtlauf 15,392 s, Vorbereitung wieder 6,171 s, Reparatur der neun Fälle insgesamt 0,897 s, Validierung 4,797 s. Die stark veränderte Rechnerlast erklärt, weshalb diese Zeiten nicht gegen den vorigen belasteten Gesamtversuch gerechnet werden dürfen. Reproduktionsskript: `followup_profile_evidence/replay_finalists.py`.

### Abschließender gleicher 0,25-s-Vergleich

`followup_final_scope4_250ms/` verwendet die finale Implementierung mit Dreierpool, dieselben 100 Requests, Beam 8, maximal vier Kabinen, 0,25 s Reparaturbudget, 60 s Gesamtbudget und 5 s pro optionalem Assignment-IP. Vorbereitung **6,077 s**, wieder ähnlich zum ursprünglichen Pilot. Es lief kein weiterer eigener Benchmark/Test parallel; die Umgebung blieb ohne CPU-Isolation.

**18 zulässige Versuche / 9 unterschiedliche Bewegungen**, 82 Budgetabbrüche; alle Erfolge bleiben Ein-Kabinen-Reparaturen. Native UB **1.011.534,810440**, nach den drei Assignment-Finalisten **1.008.673,472296**, 1120/160. Baseline-Assignment unverändert. Gesamt **41,501 s**, Reparatur **22,365 s**, Kandidatenvalidierung **9,553 s**, schnelle Zuordnung 0,085 s. Median/p95 vollständiger Anfragen **0,251 / 0,637 s**. Die vier IP-Abschlüsse einschließlich Zertifizierung benötigen jeweils rund 0,54–0,57 s. Kein Deadline-Overrun.

Der ursprüngliche Vier-Kabinen-/Beam-8-Lauf mit demselben lokalen Budget fand vier zulässige Versuche / zwei Bewegungen. Der optimierte Kern findet also unter wieder vergleichbarer Vorbereitungslaufzeit mehr Bewegungen; die zusätzliche Validierung erfolgreicher Kandidaten und die neu hinzugefügten IP-Abschlüsse erhöhen zugleich die Gesamtzeit. Das höhere p95 erklärt sich auch aus mehr erfolgreichen und vollständig geprüften Anfragen, nicht allein aus langsamerer Suche. Das 100-ms-Ziel wird trotzdem verfehlt. Der gespeicherte, zuvor separat nachoptimierte Bestplan mit **1.007.532,083464** bleibt der bessere Journey-Time-Seed.

Dieses Ergebnis unterstützt die Abschlussentscheidung: **begrenzte Weiterverwendung ja, Ausbau zur zentralen neuen Suchmethode vor der Präsentation nein**. Der lokale Verbesserungsversuch war erfolgreich; ein Durchbruch für gekoppelte Mehrkabinenänderungen oder globale Schranken ist weiterhin nicht belegt.

### Abschließende Verifikation

**150 Tests bestanden in 28,88 s** im kombinierten Lauf nach der finalen Dreierpool-Integration: Reservierungen, Primal-Evaluator, gemeinsame Referenz-/Fixed-K-Verträge, CP-SAT-Passagiere/Waiting/Integration, Horizon-Vertrag und betroffene Benchmark-Runner. Ruff und `git diff --check` bestanden. Die neuen Tests prüfen zusätzlich konservatives Kalender-Pruning, unveränderte Intervalle/Blockierer, kanonische Nachfrageinjektion, unabhängigen Assignment-IP-Vergleich, abgelaufene Budgets, Ablehnung fremder Domänen und optionale Runner-Nachoptimierung.

Unter der vorherigen hohen Rechnerlast scheiterte ein bestehender Test zweimal daran, innerhalb seines 10-s-CP-Budgets einen Incumbent zu finden (UNKNOWN, kein Validierungsfehler). Eine separate 60-s-Kontrolle lieferte FEASIBLE mit geprüfter UB 1.365.098,181290 (`followup_cp_waiting_60s_control/`). Im abschließenden vollständigen Lauf besteht auch der unveränderte 10-s-Test. Sein Budget und seine Assertions wurden nicht abgeschwächt.
