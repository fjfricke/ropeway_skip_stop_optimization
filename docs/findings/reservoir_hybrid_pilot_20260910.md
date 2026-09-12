# Reservoir-Hybrid: Abschluss des Single-Use-Piloten

Stand: 11.09.2026. [Plan](../plans/reservoir_hybrid_reassessment_20260910.md),
[API und mathematische Begründung](../reference/reservoir_hybrid.md),
[historische Zwischenbefunde](reservoir_hybrid_pilot_20260910_history.md).

## Ergebnis und Entscheidung

Das experimentelle Paket S0–S5 ist implementiert. **Die neue globale Untergrenze
ist ein brauchbarer Fortschritt; die Reparatursuche ist bisher kein praktisch
besserer Fahrplanoptimizer.** Legacy bleibt Standard. Wiederverwendbare
Reservoireinsätze (S6) und ein vollständiges exaktes Abschlussverfahren (S7)
gehören zu den bedingten Folgestufen und wurden nicht gestartet.

Die globale LB steigt von **109032.727040 auf 209409.890300**. Bei praktisch
unveränderter UB 368765.82 sinkt der nachgewiesene Gap von **70.43 % auf 43.21 %**.
Das stärkere LP ist eine notwendige Relaxation. Weitere Zeitverfeinerung allein
schließt weder Fahrzeug-/Passagiermischung noch die Ganzzahligkeitslücke.
Es gibt daher keinen Beweis, dass dieser Hybrid bei längerer Laufzeit den Gap
auf null bringt.

## Unveränderte Vergleichsdomäne

R: Max50, einmaliger Reservoir-Einsatz je Kabine, frei wählbarer Dispatch und
Rückkehr, vollständiges Exit-Waiting bis 1200 Sekunden, 1280 Personen,
300/1200/300 Sekunden Anlauf/Service/Räumung, Mikrosekundenauflösung.
Fingerprint: `ea2b46d53da6f34147bfd5a9c1a635116e89eb47afd84cfd036b56971376ac65`.

| Referenz | Passagiersekunden | Bedient | Einsätze |
|---|---:|---:|---:|
| Unabhängig geprüfter gemeinsamer Startplan | 368765.821408 | 1280 | 38 |
| Analytischer All-Stop-Fahrplan derselben Domäne | 371911.194288 | 1280 | 38 |

Nur die ganzzahlige Passagierzuordnung zum festgehaltenen All-Stop-Fahrplan ist
optimal bewiesen. Der zweite Wert ist kein globales All-Stop-Optimum. Die ältere
Fixed-K-Referenz 399287 gehört zu einer anderen Domäne.

## Schranken: deutlicher Anfangsfortschritt, danach Timeout

| Formulierung | Variablen / Zeilen | Aufbau | LP-Suche | Gültige globale LB |
|---|---:|---:|---:|---:|
| Alte Zellrelaxation, Ressourcen | 85001 / 19359 | 9.54 s | 2.14 s | 109032.72704 (analytisch; rohes LP 32228.57) |
| Mindestfahrzeiten, Ressourcen | 85001 / 19359 | 9.84 s | 2.46 s | 109032.72704 |
| Zeitmomente, Bewegung/Kapazität | 236107 / 546293 | 4.81 s | 11.67 s | 176187.38245 |
| Zeitmomente plus Ressourcen, Dual-Simplex | 236107 / 547154 | 14.38 s | 130.13 s | 176187.38245 |

Zeitmomente transportieren mit dem Passagierfluss seine absolute Zeit entlang
aufeinanderfolgender Bewegungen. Lokale optimistische Zeiten können dadurch
nicht mehr ohne jede Konsequenz auseinanderfallen. Die Ressourcenfenster
liefern auf dieser Instanz anschließend keinen zusätzlichen Bound. Deshalb
wird die schnellere Bewegung-/Kapazitätsvariante verfeinert.

| Verfeinerungsrunde | Variablen | Kumulative Zeit | Bester abgeschlossener Bound |
|---|---:|---:|---:|
| 0 | 236107 | 17.74 s | 176187.38245 |
| 1 | 252164 | 38.97 s | 205163.79223 |
| 2 | 274480 | 63.40 s | 209409.89030 |
| 3 | 304239 | 294.92 s | unverändert; LP-Zeitlimit |

Gesamt inklusive Aufsicht 296.53 Sekunden, Peak-RSS 3.378 GB. G2 und G3 sind
inhaltlich erfüllt. Die letzte Runde verbraucht 220.11 Sekunden LP-Suche ohne
neuen nachgewiesenen Bound. Ihr primaler Timeoutwert wird nicht als LB verwendet.
Der historische Abbruchtext `no_splits` wurde im Code zu `lp_status_9` korrigiert;
die alten Ergebnisdateien bleiben unverändert.

**Empfehlung für die Schranke:** diese drei abgeschlossenen Zeitmomentmodelle
nutzen (`--refinement-rounds 3`) und das globale Zertifikat auch neben der
bestehenden CP-Suche ausweisen. Keine weitere lange Verfeinerung derselben
Auswahlregel allein aufgrund der bisherigen Anfangsverbesserung starten.

## Reparaturen: Startübernahme behoben, Hauptengpass bleibt

Die kleinen Modelle enthalten nur drei/sechs geöffnete Einsätze und ein/zwei
neue Slots: ungefähr 5500–12500 Variablen statt 87020 im Gesamt-CP-Modell.
Außenfahrpläne und ihre Passagiere bleiben als konstante Randbedingungen erhalten.
Globale Neuindizierung und unabhängige Gesamtprüfung erfolgen nach jedem Merge.
Lokale Solver-Bounds gelangen niemals in das globale Bound-Ledger.

Mit normalem Presolve liefern zunächst nur sechs von zwölf Zehn-Sekunden-Versuchen
einen nativen Plan. Ein vollständig fixierter Hint bestätigt die Zulässigkeit
in 0.104 Sekunden; gewöhnliche Startübernahme dauert bei sechs Einsätzen etwa
12.68 Sekunden. Ohne Presolve fallen die Übernahmezeiten auf rund 0.38/0.74 Sekunden.
Die erneute eingefrorene Zwölferreihe liefert zwölf native Pläne und einen
Gewinn von **0.000048 Passagiersekunden**. G4 besteht damit formal, dieser Gewinn
ist aber praktisch bedeutungslos. Die längere S5-Prüfung ist deshalb entscheidend.

Die Auswahl nutzt Nachfrageschwerpunkt, Waiting-Summe als Blockierungsproxy und
schwach bedienende Einsätze. Eine genaue kausale Blockierer-Nachbarschaft und ein
Pool bewusst unterschiedlicher Suchstarts sind noch nicht umgesetzt. Der
Koordinator ist eine begrenzte Heuristik, keine vollständige Suche.

## S5: vollständiger Zehn-Minuten-Vergleich, zwei Seeds

[Vergleichstabelle](../../benchmarks/output/reservoir_hybrid_report_20260911_v2/report.md),
[Messwerte CSV](../../benchmarks/output/reservoir_hybrid_report_20260911_v2/comparison.csv),
[Fortschrittskurven CSV](../../benchmarks/output/reservoir_hybrid_report_20260911_v2/progress.csv).
Alle vier Läufe sind abgeschlossen, je zwölf Worker, dieselbe geprüfte Start-UB
und dieselbe globale LB 209409.89030. Diese externe LB wird beiden Armen gleich
angerechnet; sie ist kein nativer CP-Suchfortschritt und kein zusätzlicher
Objective-Cut im CP-Modell. Der Hybrid verwendet sie wieder und investiert seine
Suchzeit in Reparaturen.

| Lauf | Validierte UB | Gap | Wandzeit | Peak GiB | Erste / letzte Verbesserung |
|---|---:|---:|---:|---:|---:|
| cp_sat_0 | 368765.820880 | 43.213% | 597.66 s | 6.10 | 150.65 / 505.26 s |
| hybrid_0 | 368765.819352 | 43.213% | 596.05 s | 3.00 | 337.51 / 512.99 s |
| cp_sat_1 | 368765.820824 | 43.213% | 597.86 s | 6.57 | 145.87 / 591.80 s |
| hybrid_1 | 368765.819528 | 43.213% | 596.03 s | 3.28 | 170.55 / 427.19 s |

Seedübernahme wird nicht als Verbesserung gezählt. CP-Zwischenpunkte sind native
Solverwerte; Endpläne sind unabhängig validiert. Hybridverbesserungen werden
vor jedem akzeptierten Ereignis validiert. Beide Hybridpläne bedienen weiterhin
1280 Personen mit 38 Einsätzen.

Gegenüber dem jeweiligen CP-Endwert gewinnt der Hybrid nur 0.001528 bzw.
0.001296 Passagiersekunden. Gegenüber dem ursprünglichen Seed ist sein größter
Gewinn 0.002056. **Das vorher festgelegte Leistungsgate wird in keinem Seed erfüllt.**
In allen vier Läufen verbessert sich im letzten Zeitviertel weder UB noch LB
um 0.1% der UB; es liegt ein praktisches Plateau vor. Weitere Incumbentereignisse
bis fast zum Ende sind deshalb kein Beleg für einen nützlichen Fortschritt.

Der Hybrid benötigt etwa die Hälfte des Speichers des Gesamt-CP-Modells. Das ist
ein struktureller Vorteil, jedoch kein Nachweis besserer Lösungen. Beide Hybrid-
Endpläne enthalten 1020 statt 1055 Bewegungen; Änderungen betreffen überwiegend
leere Nachläufe, alle SKIPs bleiben leer. Die aktuelle lokale Suche mobilisiert
die für Fahrgäste wichtigen Änderungen noch nicht ausreichend.

Im ersten Durchgang beendete der 4-GiB-Wächter die beiden CP-Kontrollen nach
71.43/65.71 Sekunden. Diese werden nicht als vollständige Kontrollen gewertet.
Auf dem Mac mit 36 GiB RAM wurden ausschließlich die CP-Kontrollen mit 8 GiB
neu ausgeführt. Die bereits abgeschlossenen Hybridläufe werden ausdrücklich
mit ursprünglichen Quellen-/Konfigurationsnachweisen übernommen: ihr Speicher
blieb unter beiden Grenzen, kein Wächter griff dort ein. Historische Ergebnisse
wurden nicht überschrieben.

![Globale Schranken und praktisch unveränderte Incumbents](../../benchmarks/output/reservoir_hybrid_report_20260911_v2/progress.png)

**Konsequenz:** Den neuen LB-Baustein behalten, die aktuelle lokale Suchregel
nicht als neuen Standard übernehmen und keine weitere lange unveränderte
Hybridkampagne starten. Für eine spätere Primalverbesserung müssten zuerst die
Nachbarschaften anhand tatsächlicher Konflikte und besetzter Fahrten verbessert
werden. Eine automatische Erweiterung auf Mehrfacheinsatz wäre derzeit nicht
experimentell begründet.

## Kostenneutraler leerer Nachlauf

Im geprüften Startplan lassen sich **440 von 1055 Bewegungen** entfernen, indem
Kabinen nach ihrem letzten Ausstieg bei der ersten bereits vorhandenen zulässigen
Port-Rückkehr enden. Es bleiben 615 Bewegungen, 38 Einsätze, 1280 bediente Personen
und exakt dieselben Kosten. Die Transformation setzt keine neue Zeit und bewahrt
den gesamten letzten Ausstiegs-STOP sowie die früheste erlaubte Rückkehr.

`--trim-empty-tails` aktiviert diese unabhängig validierte Normalisierung optional.
Sie verändert Startzertifikate, keine Modellbedingungen. Der ursprüngliche
S5-Vergleich verwendet weiterhin den unveränderten gemeinsamen Startplan.
Alle SKIPs der ursprünglichen und bisherigen Hybridpläne liegen auf leeren
Kabinenabschnitten. Diese Reservoir-Ergebnisse allein belegen daher keinen
Zeitgewinn durch Überspringen mit Fahrgästen an Bord.


Der anschließende begrenzte Nachtest `reservoir_hybrid_trimmed_probes_20260911`
verwendet die eingefrorenen Nachbarschaften `demand_0`/`demand_1`, je 28 Sekunden
inneres und 30 Sekunden äußeres Budget, zwölf Worker, kein Presolve und den
geprüften gekürzten Seed. Beide liefern native zulässige Lösungen, jedoch
**keine UB-Verbesserung** (je 368765.821408). Das ist eine negative kurze Diagnose,
kein bestätigter Laufzeitvergleich der Normalisierung.

## Korrektheit und Grenzen

**62 Tests bestanden**, einschließlich der bestehenden Reservoir-CP-/Runner-Regressionen; Ruff und `git diff --check` bestanden.

Die Prüfung deckt kleine vollständige K1-Bewegungsenumerationen mit/ohne Waiting,
LP-Projektionen aller enumerierten Pläne, Vergleich mit CP-SAT, K2-Kapazitätswechsel,
optionale Flotten K1/K2/K4, Releases, Waiting-Freigabe, Horizontgrenzen,
Ressourcen-Minimalüberlappung gegen Enumeration, historische Checkpoints,
kanonische ID-Übersetzung und Einfügung vor festen Außeneinsätzen ab.
Alle offenen/geschlossenen sowie teilweise fixierten kleinen Reparaturen werden
gegen den bestehenden Gesamtbuilder geprüft. Ledger-Domänen, Timeout/RSS-Abbruch,
Koeffizientenbereich, Refiner-Projektion und unveränderte Legacy-Pfade sind getestet.

Der große Seed projiziert auf alle 547154 Ressourcenmodellzeilen; maximale
numerische Verletzung 6.4e-12, exakte Kosten werden bis zur Gurobi-Toleranz
reproduziert. Das ergänzt das allgemeine Projektionsargument, ersetzt es nicht.
Die LP-Bounds sind numerische Solverzertifikate, keine rational nachgerechneten
Beweise. Nicht vollständig abgeschlossen sind die breite K2-Vollenumeration,
eine eigene vollständige Bypass-/Zwei-Ressourcen-Matrix des neuen LPs und der
besondere Fixed-K-Adaptertest; Fixed-K wurde hier nicht erweitert.

## Ablage und Reproduktion

Code: `src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_hybrid/`.
`domain.py` rekonstruiert die unveränderte Domäne; `arrival_curves.py` behandelt
die Kostenidentität; `bound_domain.py`/`bound_model.py` bauen und prüfen LPs;
`refinement.py` verfeinert; `repair.py` bildet lokale CP-Modelle und normalisiert
optionale Seeds; `certificates.py` trennt globale/lokale Ergebnisse;
`optimizer.py` koordiniert sequenziell. Der öffentliche Runner ist
`benchmarks/run_ddd_reservoir_hybrid.py`.

Alle folgenden Ordner liegen unter `benchmarks/output/`:

- `model_correctness_audit_20260910/checked_incumbent.json`: gemeinsamer Originalseed.
- `reservoir_hybrid_uncapped_20260910_v1`: Nachtest ohne künstliche Größenlimits.
- `reservoir_hybrid_ride_bounds_20260910_v1`: Mindestfahrzeiten ohne Zeitmomente.
- `reservoir_hybrid_time_moments_20260910_v1`: erste starke Zeitmomentmodelle.
- `reservoir_hybrid_moments_dual_20260910_v1`: Ressourcen-LP mit Dual-Simplex.
- `reservoir_hybrid_refine_20260910_v1/run`: Partitionen, LPs, Projektionen, Boundverlauf.
- `reservoir_hybrid_repairs_20260910_v1`: ursprüngliche zwölf kurze Reparaturen.
- `reservoir_hybrid_repairs_no_presolve_20260910_v1`: wiederholtes G4-Gate.
- `reservoir_hybrid_comparison_20260911_v1`: S5 mit zunächst 4 GiB; CP-Arme abgebrochen.
- `reservoir_hybrid_comparison_20260911_v2`: vollständiger Vergleich unter 8 GiB.
- `reservoir_hybrid_trimmed_seed_20260911/seed.json`: kostenneutral gekürzter Startplan.

Konfigurationen, Versionen, Python-Quellcodehashes, Events, native Logs und geprüfte
Zertifikate bleiben pro Lauf erhalten. Die künstliche 50000-Variablen-Grenze war
ein Engineering-Limit und kein Nachweis mangelnder Skalierung. Sie wurde nach
Autorisierung optional entfernt. Die 4-GiB-Grenze bleibt für den LP-Piloten;
für den Gesamt-CP-Vergleich erwies sie sich als zu eng.

## Abschlussartefakte und Prüfkommando

Der [Ergebnisordner](../../benchmarks/output/reservoir_hybrid_report_20260911_v2)
enthält auch `validation.json` für alle vier Endpläne, `best_validated.json`,
seine kostenneutral gekürzte Version und `best_certificate.json` mit getrenntem
globalem Bound und dessen Herkunft. Ein gekürztes Zertifikat ist keine neue
Solververbesserung. `progress.png` und `progress.pdf` sind eigenständige Grafiken;
die PNG wurde visuell geprüft.

```sh
.venv/bin/pytest -q tests/test_reservoir_hybrid*.py \
  tests/test_optimization_ddd_reservoir_cp_sat.py \
  tests/test_benchmarking_ddd_reservoir_cp_sat.py
```

Die endgültige Quellensicherung ist
`benchmarks/snapshots/reservoir_hybrid_20260911_final_sources.tar.gz` samt SHA256.
Die frühere Quellensicherung bleibt für die S5-Hybridläufe erhalten. Matplotlib
für die Berichtsgrafik wurde nur in einer separaten temporären Umgebung genutzt;
es wurden keine Projektabhängigkeiten für die Grafik geändert.
