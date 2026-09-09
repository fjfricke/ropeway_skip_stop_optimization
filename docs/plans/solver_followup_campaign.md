# Bestehende Solver: autorisierte Folgekampagne

Stand 9. September 2026. Auftrag: die Schritte aus dem Solverhistorien-Audit umsetzen. Keine neue Solverfamilie. Endlicher geschlossener Ereignishorizont bleibt unverändert.

## Reihenfolge und Vergleichsregeln

1. Vollständige versionierte Fixed-K-Identität, strenger Root-CG-Boundimport und Regressionen. Historische CP-Fahrpläne nur mit passendem vollständigem Manifest und erneuter primaler Prüfung übernehmen, keine alten Bounds. Live-CP-Ereignisse mit Optimizer-/Runnerzeit, RSS und separaten Callbackkosten. Zusätzlich muss der Seed-Evaluator exakt die Nachfrage/Kandidaten des Problems verwenden, auch bei Profilvarianten.
2. Bestehenden Code einschließlich Waiting/Horizon/Reservierung sichern. Kleine Auswahl historischer Headline-Pläne unter aktuellem Vertrag nachprüfen und mit Quellenhashes kopieren; Originale behalten.
3. K39 Waiting: 1.800 s durchgehend, Produkt, acht Worker, Seed 0, bester bestehender geprüfter Hint 1.007.532,083464. Danach zwei 600-s-Wiederholungen mit Seeds 1/2 und demselben ursprünglichen Hint. Das ist ein Vergleich mit besserer Startlösung; kein isolierter Nachweis des Zeiteffekts gegenüber den alten Runs. Verlaufspunkte innerhalb des 30-min-Laufs erlauben eine direkte 10→30-min-Auswertung.
4. K38 freies Skip-Stop Waiting: 600 s, Produkt, acht Worker, All-Stop-Referenz als Hint; vollständige Entscheidungsfreiheit. Die aktuelle unabhängige Bewertung dieses Hints ist gleichzeitig die feste All-Stop-Kontrolle. Kein Versprechen der globalen Optimalität des freien Modells.
5. Kleine Matrix mit bestehender Fünf-Stationen-B-Topologie, K20 balanced, No-Wait: diffuse / lokale / Express-Nachfrage × Batch / zeitlich verteilt. Jeweils 1.280 Personen, Kapazität 8 und 1.200 s Service-/Betriebshorizont. Gelabeltes vollständiges Arc-Flow für All-Stop und Skip-Stop, jeweils maximal 120 s; gleiche Starts und exakte Nachfrage pro Paar. Richtungsgebundene lokale OD-Paare haben einen Vorwärtsabschnitt, Expresspaare drei oder vier. Zeitlich verteilt: vier gleich gewichtete Releases 0/200/400/600 s, somit verbleiben mindestens 600 s zur Bedienung. Dies ist ein ausdrücklich angepasster Fünf-Stationen-Pilot, nicht die geplante 60-min-Sechs-Stationen-Studie. Gesamtzahl deterministisch nach normalisierten Zellgewichten verteilen; keine Kapazitäts-Bisektion oder Behauptung verschachtelter N-Instanzen.
6. Ein begrenzter anonymer No-Wait-K39-Versuch mit dem passenden vorhandenen No-Wait-Seed, 1.800 s, sofern die laufende Kampagne keine wichtigere Korrektur ergibt. Waiting-Schrankentransfer ausgeschlossen.

Alle Performance-Solves nacheinander in separaten Prozessen. Keine anderen eigenen Solver/Tests gleichzeitig. Konfiguration, Softwarestand, Quellenhashes, Start-/Endzeiten, Status, UB/LB, Bedienung, Modellgröße, RSS und Verlauf protokollieren. Historische und neue Ausgaben nicht überschreiben. Passagier-IP und unabhängige Prüfung nach jedem Hauptlauf separat ausweisen; deren OPTIMAL bezieht sich nur auf die feste Bewegung.

## Auswertung

- UB-/LB-Fortschritt getrennt, keine Extrapolation bis zur Optimalität.
- Seedgewinn, längere Laufzeit, Zufallsstreuung und geänderte physische Domäne unterscheiden.
- Fehlgeschlagene Builds/Timeouts ohne Lösung liefern keinen Unzulässigkeitsnachweis.
- Prozess-RSS und Callbackzeiten sind teilweise Teilmengen der Solvezeit, nicht zusätzliche Summanden.
- Weitere CP-Zeitdomänen-/Portfolioänderungen erst nach dieser unveränderten Formulierungsbaseline entscheiden.

Ergebnisbericht: `docs/findings/solver_followup_campaign.md`. Lokale Messdateien: `benchmarks/output/solver_followup_20260909/`.

## Zusätzliche aussagekräftige Schrankenprüfung

Beim frischen No-Wait-K39-Lauf die gültige globale LB direkt mit der geprüften K38-All-Stop-UB 399287,271408 vergleichen. Falls LB(K39 No-Wait) darüber liegt, ist auch ohne kleinen K39-Gap bewiesen, dass diese genau fixierte K39-No-Wait-Startdomäne die konkrete K38-All-Stop-Referenz nicht schlagen kann. Das ist kein Satz über andere Anfangspositionen, Waiting oder variable Flottenzahl. Historische LBs geben hierfür einen Hinweis; der neue Lauf soll den Vergleich mit vollständiger aktueller Identität absichern.

## Ausführungsstand

- [x] Identität und Zertifikatsimport korrigiert, Regressionen bestanden.
- [x] Baseline einschließlich geprüfter historischer Pläne gesichert (`192b9b7`).
- [x] K39 Waiting: 1800 s Seed 0 und je 600 s Seeds 1/2, alle nachgeprüft.
- [x] K38 Waiting aus All-Stop: 600 s, unabhängig nachgeprüft.
- [x] Zwölf K20-Profilläufe ausgeführt; sechs Paaridentitäten bestätigt, alle Abschlussbewertungen geprüft.
- [x] Anonymer No-Wait-K39-Lauf 1800 s abschließen und auswerten.
- [x] Abschließende Tabellen, Rohdatenarchiv und Ergebniscommit.

Die Profilintegration und Ausführungswerkzeuge sind in `cdf6399` gesichert. Die bisherigen Vergleichsergebnisse stehen im verlinkten Findings-Dokument; alle 17 Hauptläufe sind abgeschlossen und nachgeprüft.
