# Reservoir-Diagnose: Entscheidungen, Fortschritt und Schranken

Stand: 11.09.2026. **Abgeschlossen: 16 Suchläufe, acht historische Replays,
33 bestandene Tests. Kein verbesserter Fahrplan; der Engpass ist genauer eingegrenzt.**

[Versuchsplan](../plans/reservoir_diagnostics_20260911.md),
[Messwerte](../../benchmarks/output/reservoir_diagnostics_20260911_v1/report.md),
[Maschinenlesbare Daten](../../benchmarks/output/reservoir_diagnostics_20260911_v1/comparison.csv).

## Was dieser Versuch beantworten kann

Die Varianten ändern ausschließlich Fixierungen im bestehenden integrierten
CP-SAT-Modell. Keine eigene Suche, kein neuer Backend, keine Änderung am
Waitingraster oder den zulässigen globalen Bewegungen. Die Einschränkungen
sind Diagnosewerkzeuge. Ihre optimalen Werte und Schranken gelten nur für das
jeweilige Teilproblem. Gültige exportierte Fahrpläne bleiben dagegen global
zulässige obere Schranken.

Die Domäne ist weiterhin das Max50-Single-Use-Reservoir mit 1.280 Personen,
Waiting bis 1.200 Sekunden und 300/1.200/300 Sekunden Betriebsphasen. Es handelt
sich nicht um das frühere Fixed-K-Modell mit Balanced-Reference-Startpositionen.
Der Startplan nutzt 38 Kabinen und hat Kosten 368.765,817136 Passagiersekunden.
Sein physikalischer Fingerprint lautet
`ea2b46d53da6f34147bfd5a9c1a635116e89eb47afd84cfd036b56971376ac65`.

| Profil | Fixierung |
|---|---|
| passengers | gesamte Bewegung, Passagiermengen frei |
| timing | Haltemuster und sämtliche aktiven Besuche, Zeiten/Passagiere frei |
| timing_order | zusätzlich Reihenfolge je Ressource |
| routes | nur aktive Besuche einschließlich Rückkehrbesuch |
| lifecycle | nur Zahl eingesetzter Kabinen = 38 |
| full | vollständige bisherige Reservoir-Domäne bis Max50 |
| timing_assignment | wie timing, zusätzlich Passagiermengen fest |
| timing_order_assignment | wie timing_order, zusätzlich Passagiermengen fest |

Die Hauptreihe verwendet 120 Sekunden Prozessbudget pro Variante, die gezielte
Zusatzreihe 90 Sekunden; jeweils Seeds 0 und 1. Aufbau und Abschluss sind
enthalten. Solverzeit ist das Prozessbudget minus fünf Sekunden Reserve.
Alle Läufe verwenden zwölf Worker und dieselbe geprüfte Startinformation.
Sie laufen sequenziell. Die Reihenfolge wird in der Wiederholung umgekehrt.

## Referenz bleibt in jeder Einschränkung enthalten

Alle acht Profile reproduzierten vor ihrer Suche den vollständig fixierten
historischen Fahrplan und dessen Beförderungsmengen exakt. Die vollständige
Bewegung ist in `timing` ausdrücklich nicht festgehalten: sämtliche Dispatch-
und Waitingentscheidungen bleiben frei. STOP/SKIP wird erst in `routes`
freigegeben; die Folgezeiten werden dabei nicht künstlich am Seed festgehalten.

`timing_order` ordnet 3.039 Ressourcennutzungen des Seeds. Für diesen Fall
befindet sich keine ausgewählte Nutzung außerhalb des ursprünglichen
Präsenzhorizonts. Die bedingte Kette speichert das bisher größte Räumungsende;
eine später abwesende mittlere Nutzung kann die Ordnung nicht unterbrechen.
Die ursprünglichen NoOverlap-Bedingungen und die separate Zustandszeit-
Eindeutigkeit bleiben bestehen. Es entstehen 9.117 zusätzliche Hilfsvariablen,
von denen Presolve viele entfernt. Deshalb ist dies eine Formulierungsänderung
mit zusätzlicher Ordnung, kein identischer Modellbau mit bloß anderem Seed.

Ein kleiner Gegenfall bestätigt: Ein durch Waiting physikalisch zulässiges
Überholen bleibt in `timing` erlaubt und wird in `timing_order` genau durch die
zusätzliche Reihenfolgevorgabe ausgeschlossen. Diese Einschränkung ist
beabsichtigt und wird nicht als vollständiges Seilbahnmodell ausgegeben.

## Ergebnisse und tatsächlicher Fortschritt

Alle 16 Läufe behalten die unabhängig bestätigte UB **368.765,817136**. Es gibt
**keine native Verbesserung** gegenüber dem gemeinsamen Startplan. Die Übernahme
dieses Plans zählt nicht als Verbesserung. Beide Zusatzprofile erreichen denselben
Wert nachweislich optimal innerhalb ihrer Einschränkung.

Die Tabelle zeigt beide Seeds; Zeiten sind beobachtete Prozesszeiten einschließlich
Aufbau und Abschluss. LB-Werte sind zur Lesbarkeit auf ganze Passagiersekunden
gerundet; exakte Werte stehen in der verlinkten CSV.

| Freie Entscheidungen / Profil | LB Seed 0 / 1 | Gap im jeweiligen Teilproblem | Zeit Seed 0 / 1 | Variablen nach Presolve |
|---|---:|---:|---:|---:|
| Nur Passagiere (`passengers`) | 368.766 / 368.766 | 0 %; optimal | 3,4 / 3,6 s | 3.665 |
| Zeiten + Passagiere (`timing`) | 313.596 / 314.687 | 15,0 / 14,7 % | 116,4 / 116,0 s | 8.978 / 8.974 |
| Dasselbe mit Ressourcenordnung (`timing_order`) | 322.617 / 323.566 | 12,5 / 12,3 % | 116,7 / 116,1 s | 8.108 / 7.820 |
| Zusätzlich STOP/SKIP frei (`routes`) | 0 / 0 | 100 / 100 % | 116,3 / 116,4 s | 14.539 |
| Nur Flottenzahl = 38 fest (`lifecycle`) | 0 / 0 | 100 / 100 % | 116,6 / 116,4 s | 31.426 |
| Vollständiges Max50 (`full`) | 0 / 0 | 100 / 100 % native CP-SAT-LB | 116,6 / 116,8 s | 41.859 |
| Nur Zeiten frei (`timing_assignment`) | 368.766 / 368.766 | 0 %; optimal | 8,8 / 13,4 s | 1.924 / 1.920 |
| Nur Zeiten, Ressourcenordnung fest (`timing_order_assignment`) | 368.766 / 368.766 | 0 %; optimal | 5,5 / 6,3 s | 654 |

Die Suchkampagne einschließlich Replays und Zusatz lief **1.252,35 Sekunden
(20 Minuten 52 Sekunden)** ab gemeinsamer Vorbereitung. Alle Prozesse endeten
regulär. Kein Speicherabbruch, kein übersprungener Versuch. Die anschließende
Auswertung bleibt innerhalb der gemeinsamen 30-Minuten-Deadline; ihr Abschluss
wird in `completion.json` festgehalten. Kein weiterer Solverlauf wurde gestartet.

Der Aufbau der Hauptmodelle dauert etwa 1,3–1,5 Sekunden, Hintaufbau einschließlich
Diagnosebedingungen weitere 0,4–0,6 Sekunden. Das Problem ist somit in diesen
Versuchen nicht überwiegend die Aufbauzeit. Maximal wurden ungefähr 6,0 GiB
Prozessbaum-RSS gemessen, unterhalb des 8-GiB-Limits. Zwölf Worker waren konfiguriert;
die gemessene CPU-Zeit bedeutet nicht durchgehend zwölf voll ausgelastete Kerne.

### Plateau genauer betrachtet

- `full`, `lifecycle` und `routes`: in beiden Seeds keine Verbesserung der UB
  und keine positive native LB im beobachteten Budget.
- `timing`: die letzten materiellen LB-Zuwächse liegen bei rund 18,8 / 20,3 s;
  kleinere Änderungen reichen bis 63,9 / 55,5 s. Danach keine erfassten Zuwächse.
- `timing_order`: materielle Zuwächse bis 30,7 / 86,4 s; kleinere Änderungen bis
  49,2 / 102,7 s. Seed 1 macht also auch spät noch Schrankenfortschritt, erreicht
  aber weder eine bessere UB noch den Beweis.
- `passengers` und beide Assignment-Profile enden optimal. Deren Ende ist
  kein Suchplateau, sondern ein abgeschlossener Beweis im Teilproblem.

„Materiell“ bedeutet hier kumulativ mindestens 0,1 % der Referenzkosten gegenüber
dem letzten so markierten LB-Wert. Native Bound-Callbacks werden vom bestehenden
Optimizer zeitlich gedrosselt; erfasst wird der beobachtete Verlauf, nicht jede
interne Schrankenänderung. Die Uhr beginnt beim Solver-Wrapper einschließlich
Modellbau. Die Nullkurven mehrerer Profile liegen in der Grafik übereinander.

![Fortschritt der getrennten Teilprobleme](../../benchmarks/output/reservoir_diagnostics_20260911_v1/bound_progress.png)

## Was sich daraus ableiten lässt

**1. Die variable Flotte ist nicht die alleinige Ursache.** Schon `routes` hat
exakt dieselben eingesetzten Kabinen und Rückkehrbesuche wie der Seed und bleibt
trotzdem bei nativer LB null. Zurück zu einer festen Flottenzahl innerhalb dieses
Reservoirs reicht in diesen Tests nicht. Dies ist keine Messung des anderen
Fixed-Start-Modells und rechtfertigt keine pauschale Aussage darüber.

**2. Waiting allein ist bei gegebenem Haltemuster und gegebener Beförderung gut
lösbar.** `timing_assignment` beweist in 8,8–13,4 s die optimalen Zeiten, ohne die
Ressourcenreihenfolgen vorzuschreiben. Der volle Waitingbereich bleibt erhalten.
Es wird deshalb nicht durch diese Daten gestützt, Waiting zu streichen oder sein
Raster zu vergröbern.

**3. Die gemeinsame Optimierung von Zeiten und Beförderung ist ein klarer
Engpass.** Bei festem Fahrplan ist die ganzzahlige Zuordnung schnell gelöst. Bei
festen Mengen sind die Zeiten schnell gelöst. Gemeinsam bleibt bereits bei
festen STOP/SKIP-Mustern ein Gap von etwa 15 %. Im Presolve bleiben dann rund
820 Mengen-mal-Ankunftszeit-Produkte übrig; mit festen Mengen verschwinden sie.
Gleichzeitig verschwinden jedoch Zuordnungsentscheidungen und weitere logische
Kopplungen. Dieser Versuch beweist daher ausdrücklich **nicht**, dass allein
`add_multiplication_equality` für die Schwierigkeit verantwortlich ist.

**4. Reines abwechselndes Optimieren ist an diesem Seed kein überzeugender
Ausweg.** Beide Einzelblöcke haben bereits denselben optimalen Kostenwert.
Eine strikt verbessernde Wechseloptimierung zwischen genau diesen Blöcken
kann hier keinen ersten Schritt machen. Gleich gute Wechsel könnten andere
Anschlusspunkte schaffen; deren Erfolg wurde nicht geprüft. Eine Verbesserung
kann gemeinsame Änderungen an Mengen und Zeiten oder andere Halte-/Einsatzmuster
erfordern. Eine eigene lokale Suche wird durch diesen Befund nicht gerechtfertigt.

**5. Ressourcenordnung hilft beim eingeschränkten Nachweis, ist aber keine
vollständige Lösung.** Mit festen Mengen sinkt die Größe weiter auf 654 Variablen;
mit freien Mengen bleibt auch nach Fixierung der Ordnung ein deutlicher Gap.
Diese künstliche Einschränkung als globalen Algorithmus auszugeben würde gerade
die gewünschten freien Überholungen aufgeben.

### Konsequenz für die nächste Entscheidung

Ein weiterer langer unveränderter Max50-Lauf ist durch diese Diagnose nicht
begründet. Ebenso wenig eine Rückkehr zu bloß festem K oder eine neue eigene
Wechsel-/Nachbarschaftssuche.

Falls wir noch eine Formulierungsänderung verfolgen, wäre der kleinste gezielte
Versuch eine **exakte binäre Darstellung der beschränkten Aussteigermenge** im
bestehenden CP-SAT-Passagierbaustein: `n = Summe(2^j * b_j)` und für jedes Bit ein
reifiziertes `z_j = t` beziehungsweise `z_j = 0`; dann ist
`n*t = Summe(2^j*z_j)`. Dies erhält alle Integerzeiten und Mengen. Der Z3-Adapter
verwendet diese mathematische Darstellung bereits; der aktuelle CP-SAT-Pfad
bietet `product` und `unary`, aber noch keine binäre Variante.

Das wäre zunächst ausschließlich auf **`timing` mit freien Passagiermengen** gegen
die hier gemessene Produkt-Baseline zu prüfen. So testen wir die vermutete
Kostenkopplung, bevor Flotten- und Haltemusterfreiheit wieder hinzukommen.
Kein Nutzen in diesem Teilproblem wäre ein guter Grund, diesen Versuch zu beenden;
ein Erfolg wäre noch kein Nachweis für das volle Reservoir. Der frühere K20-Test
hat `unary` bereits schlechter als `product` gesehen; eine bloße Wiederholung
dieser alten Idee sollte nicht als neue Lösung verkauft werden.

Diese binäre Variante ist **eine begründete, ungetestete Hypothese**, kein
versprochener Durchbruch. Sie wurde in dieser Diagnose nicht implementiert oder
zusätzlich gestartet. Bestehende Algorithmen und Standards bleiben erhalten.

Code-/Ergebnisbezüge:
[CP-SAT-Passagierkosten](../../src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_passenger.py),
[binäre Z3-Kosten](../../src/ropeway_skip_stop_optimization/optimization/ddd/native_solvers/model.py),
[früherer Produkt-/Unary-Vergleich](ddd_integrated_cp_sat_runtime_analysis.md).

## Was der bestehende globale Bound bereits berücksichtigt

Die bisherige zertifizierte globale Untergrenze beträgt 209.409,890300
Passagiersekunden. Sie stammt aus der separaten kontinuierlichen
Bewegungs-/Passagierflussrelaxation mit Zeitmomenten. Das ist ein anderer
Nachweis als die nativen CP-SAT-Schranken der eingeschränkten Tests. Mit der
unveränderten UB beträgt der damit belegte globale Gap weiterhin **43,21 %**.
Die höheren eingeschränkten LBs aus diesem Versuch dürfen ihn nicht verkleinern.

Der Code verwendet unter anderem:

- Kontinuierliche anonyme Kabinenflüsse `x` statt indivisibler gelabelter Fahrten.
- Ganzzahlige physikalische Zeitgrenzen, aber zusammengefasste Zeitbereiche in
  der Relaxation; das vollständige Modell selbst behält Mikrosekunden.
- Passagiermassen `f` mit Kapazitätskopplung `Summe(f) <= Q*x`.
- Separate Zeitmomente je Nachfragegruppe, Einstiegsbesuch und Bewegungsarc.
  Zeitmomenterhaltung verhindert beliebige Sprünge mittlerer Passagierzeiten.
- Im Ressourcenprofil konservative Mindestüberlappung je Zeitfenster, anstelle
  einer vollständigen gemeinsamen exakten Reihenfolge aller Intervalle.

Die Relaxation erzwingt damit **keine einzige gemeinsame exakte Kabinenzeit für
alle auf einem zusammengefassten Arc beförderten Gruppen**. Außerdem darf
Flussmasse fraktional sein. Diese Freiheiten erklären, warum Zeitverfeinerung
allein kein Versprechen für Gap-Schließung ist; ihre jeweilige quantitative
Bedeutung ist damit noch nicht bestimmt.

Ein einfacher zusätzlicher Ressourcenfenster-Test wurde bereits früher
versucht: Auf dem groben Zeitmomentmodell verbesserte er die LB von rund
176.187 nicht und kostete deutlich mehr Laufzeit. Deshalb wurde anschließend
`movement_capacity` verfeinert. Es wäre falsch, die bloße Wiederholung dieses
Ressourcenfensterprofils nun als neue Idee zu verkaufen.

Quellen im Projekt:
[Bound-Modell](../../src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_hybrid/bound_model.py),
[optimistische Zeitbereiche](../../src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_hybrid/bound_domain.py),
[frühere Messergebnisse](reservoir_hybrid_pilot_20260910.md),
[globale Bound-Provenienz](../../benchmarks/output/reservoir_hybrid_comparison_20260911_v1/bound_provenance.json).

## Dateien und Reproduzierbarkeit

- [Optionale Diagnosebedingungen](../../src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_diagnostics.py)
- [Bestehender Optimizer mit optionalem Diagnoseargument](../../src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_cp_sat.py)
- [Hauptkampagne](../../benchmarks/run_reservoir_diagnostics.py)
- [Gezielter Zusatz](../../benchmarks/run_reservoir_diagnostic_followup.py)
- [Auswertung ohne Optimierung](../../benchmarks/report_reservoir_diagnostics.py)
- [Regressionstests](../../tests/test_reservoir_diagnostics.py): **33 bestanden**, einschließlich bestehender Reservoir-Regressionen; [JUnit](../../benchmarks/output/reservoir_diagnostics_20260911_v1/tests.xml)
- [Zusatzmanifest](../../benchmarks/output/reservoir_diagnostics_20260911_v1/followup.json)
- [Zusatzquellen](../../benchmarks/output/reservoir_diagnostics_20260911_v1/source_hashes_followup.json)
- [Kampagnenmanifest](../../benchmarks/output/reservoir_diagnostics_20260911_v1/campaign.json)
- [Tatsächlich ausgeführte Quellen](../../benchmarks/output/reservoir_diagnostics_20260911_v1/source_hashes.json)

Native Ereignisse, unabhängig geprüfte Checkpoints, Endpläne, Solverlogs,
Modellgrößen vor/nach Presolve und Prozessmetriken bleiben getrennt erhalten.
Die Zusatzreihe bekommt eigene Quellcode-Hashes. Historische Ergebnisse und
Standards werden nicht überschrieben.
