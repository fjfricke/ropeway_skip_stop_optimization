# Bestehende Solver: Folgekampagne vom 9. September 2026

Umsetzung des [beschlossenen Plans](../plans/solver_followup_campaign.md). Dieser Bericht wird mit den abgeschlossenen Versuchen ergänzt. Historische Rohdaten bleiben unverändert.

## Abgesicherte Grundlage

- Neuer vollständiger `fixed_k_problem_v2`-Fingerprint einschließlich Ressourcen-/Routenwerten, Kapazität, Nachfrage, Kandidaten und Horizontvertrag. `legacy_fingerprint` dient nur der expliziten Wiedererkennung historischer primaler CP-Pläne bei zusätzlichem vollständigem Manifestabgleich und erneuter Prüfung.
- Root-CG-LB-Import verlangt vollständiges Manifest, passenden Hash, `certificate_valid=true`, gültigen Status und `FIXED_K_GLOBAL`-Scope. Alte unvollständige Zertifikate werden abgewiesen. Root-CG schreibt die neue Identität mit.
- Der Primal-Seed-Evaluator erhält die kanonische Nachfrage/Kandidaten des konkreten Problems. Das verhindert eine unbemerkte Rückkehr zur Standardnachfrage bei Profilvarianten.
- CP schreibt Ereignisse während des Laufs als JSONL, ergänzt Runnerzeit und Prozess-Peak-RSS. Extraktion, Callbackvalidierung und Eventzustellung werden separat ausgewiesen; sie sind innerhalb der Solvezeit zu interpretieren.
- 140 Tests bestanden im breiteren gezielten Lauf; nach der zusätzlichen Korrektur der Nachfrageübergabe bestanden 68 betroffene Tests. Keine Änderung der Stop-/Skip-/Waiting-Formulierung für die neue Laufzeitbaseline.

## Erneute unabhängige Prüfung historischer Fahrpläne

Alle festen Integer-Passagier-IPs melden OPTIMAL; das ist jeweils ein Beweis bei **fixierter Bewegung**. Frühere globale Schranken werden nicht importiert.

| Bewegung | Aktuell bestätigte Kosten | Bedient / unbedient |
|---|---:|---:|
| K20 All-Stop | 635.519,998080 | 1280 / 0 |
| K20 Skip-Stop | 525.730,908160 | 1280 / 0 |
| K38 All-Stop | 399.287,271408 | 1280 / 0 |
| K39 No-Wait | 1.262.099,935264 | 416 / 864 |
| K39 Waiting, bester Reservierungsseed | 1.007.532,083464 | 1112 / 168 |

Auch die explizite Übertragung nur der K38-All-Stop-Bewegung in die freie Skip-Stop-Waiting-Domäne reproduziert 399.287,271408. Alle geprüften Pläne erfüllen den vereinbarten endlichen Vertrag. Fortsetzung wird nicht behauptet.

Messdaten und kopierte Originalquellen: `benchmarks/output/solver_followup_20260909/frozen/`, jeweils `source.json`, `validation.json`, `problem_manifest.json` und neu zertifizierter `cp_seed.json`. `headline_validation.json` enthält die gemeinsame Übersicht; `software_snapshot.json` Quellcodehashes, Paketversionen, Betriebssystem und damaligen Gitstatus. Reproduktion: `benchmarks/prepare_solver_followup.py`.

## Laufende bzw. folgende Experimente

1. K39 Waiting 1800 s, Produkt, acht Worker, Seed 0, eingefrorener Waiting-Bestseed.
2. Zwei 600-s-Wiederholungen mit Seeds 1 und 2 und derselben Startlösung.
3. K38 Skip-Stop Waiting 600 s aus dem All-Stop-Seed.
4. Kleine K20-Nachfragematrix mit gelabeltem No-Wait-Arc-Flow.
5. Optional anonymes No-Wait-K39-Arc-Flow 1800 s mit passendem CP-No-Wait-Seed.

Abgeschlossene Ergebnisse folgen hier mit klar getrennten Roh-CP-Werten, unabhängiger Assignment-Nachoptimierung und globalen Bounds.
