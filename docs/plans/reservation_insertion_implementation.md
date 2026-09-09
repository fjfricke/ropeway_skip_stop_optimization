# Reservierungs-/Einfügekern: Umsetzung und Abschlussentscheidung

Stand: 9. September 2026. Der OO-Prototyp und der begrenzte Profil-/Verbesserungsschritt sind umgesetzt. [Architektur und CLI](../reference/ddd_reservation_insertion.md), [Messwerte, Grenzen und Ergebnisorte](../findings/ddd_reservation_insertion_gate.md), [Research-Entwurf](reservation_insertion_kernel.md).

## Erledigte Schritte

1. **Profiling:** Fensterabfrage als dominanten konkreten Engpass identifiziert. Lookahead, Materialisierung und übergeordnete Suchfunktionen im cProfile erfasst. Das Profil ist diagnostisch; wegen zeitbegrenzter Suche werden seine Lösungszahlen nicht als Leistungsvergleich verwendet.
2. **Begrenzte Optimierung:** Horizont/Ressourcen pro Lauf zwischengespeichert; Kalenderabfragen durch Eintrittsindex und Präfixmaxima konservativ eingegrenzt. Differentialtests gegen volle Suche und Enumeration. 1.000 gleiche K39-Abfragen im gepaarten Vergleich: 6,17-mal schneller, 73,3 % weniger Paarprüfungen, identische Intervalle und Blockierer. Ganze Reparaturen sind weiterhin erheblich teurer.
3. **Validierung geprüft:** Wiederholungen zwischen EAN-Adapter und gemeinsamem Zertifikat bleiben bewusst bestehen. Es fehlt ein domänengebundener unveränderlicher Validierungsnachweis; ein allgemeines Überspringen wäre falsch. Der Aufwand erklärt die überwiegenden Budgetabbrüche ohne Kandidaten nicht. Kein weiterer Architekturumbau dafür.
4. **Optionaler Passagier-IP integriert:** `DddReservationAssignmentRefiner` komponiert den bestehenden Evaluator mit explizitem Kandidatenuniversum. Der Runner behandelt bis zu drei unterschiedliche native Finalisten und die Ausgangsbewegung als Kontrolle, reicht verbleibendes Budget weiter, protokolliert native/optimierte Kosten und schreibt einen geprüften CP-Seed. Kein eigenes zweites Zuordnungsmodell. Der nach schneller Zuordnung begrenzte Dreierpool ist eine dokumentierte Heuristikrestriktion; ein gezielter Wiederholungstest prüft diese Integration.
5. **Bedingten Ausbau entschieden:** Die p95-Messlatte von 100 ms wird weiter verfehlt; gemeinsame Reparaturen liefern bisher keinen Vorteil. Deshalb ist die Voraussetzung für Greedy/Regret-Vergleich und anschließendes ALNS nicht erfüllt. Diese Schritte werden für diesen Pilot **nicht freigegeben und nicht als offene Implementierung weitergeführt**. Eine Wiederaufnahme wäre eine neue, begründete Forschungsentscheidung.

Abschließender K39-Test: 100 gleiche Anfragen, 0,25 s je Reparatur, neun statt zuvor zwei Bewegungen, 41,501 s gesamt einschließlich Prüfung und IP-Abschluss. Neue UB 1.008.673,472296; bisheriger Best-Seed 1.007.532,083464 bleibt besser. 150 gemeinsame Tests sowie Ruff bestanden.

## Integrationsvertrag

- Gemeinsame Domäne: `DddFixedKTrajectoryProblem`, `DddReferenceSolution`, kanonische Ride-IDs, Integer-Ticks, bestehende Ressourcen- und EAN-Regeln.
- Komposition von Calendar, WaitWindowSolver, SuffixRepairer, PassengerEvaluator, Validator und optionalem AssignmentRefiner. Keine Vererbung vom CP-SAT-Optimizer.
- Private Änderungen bis zur vollständigen Abnahme; alte CP-Schemas und Domänenidentität bleiben kompatibel.
- Der akzeptierte endliche Horizont bleibt unverändert. Keine zusätzliche Fortsetzung nach H als Gate.
- Budgetabbruch ist kein Unzulässigkeitsnachweis. Bounded Beam, begrenzte Blockiererauswahl und eingefrorene Präfixe bleiben Suchrestriktionen.
- Globale Zeitgrenze ist weich: laufender Modellaufbau, Validierung und Persistenz können sie überschreiten; der Runner weist das aus. Kein neuer Assignment-IP nach Budgetablauf.
- Assignment-OPTIMAL gilt nur bei fester Bewegung. Der Reservierungskern erzeugt keine globale LB.

## Weitere Nutzung

Den Kern als begrenzte Verbesserung vorhandener Pläne und Lieferant validierter CP-Warmstarts behalten. Die korrigierte effiziente Fensterabfrage ist wiederverwendbar. Für die verbleibende Thesis-Zeit keine offene ALNS-/Decoder-Entwicklung daraus machen. Die konkreten Qualitäts- und Laufzeitergebnisse einschließlich des längeren K39-Versuchs stehen im Finding; sie bestimmen die Abschlussbewertung.
