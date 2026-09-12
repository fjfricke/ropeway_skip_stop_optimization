# Reservoir, Waiting, gute Fahrpläne und globale Schranken: Neubewertung

Stand: 11.09.2026. S0–S5 sind als experimenteller Single-Use-Pilot implementiert;
die breite ursprüngliche Prüfmatrix ist nicht pauschal vollständig abgenommen.
G2/G3 erreichen globale LB **209409.89030**. G4 erreicht ohne Presolve zwölf
native zulässige Reparaturen und einen mikroskopischen Gewinn (0.000048).
S5 ist abgeschlossen: kein relevanter UB-Vorteil in beiden Seeds, kein
automatischer Ausbau. Die S5-Auswertung und der genaue Abdeckungsstand stehen im
[Abschlussbericht](../findings/reservoir_hybrid_pilot_20260910.md).
S6/S7 werden erst nach einer gesonderten Entscheidung weiterverfolgt.
Die noch offenen Checkboxen kennzeichnen weitergehende oder nicht vollständig
umgesetzte Anforderungen; die nachstehende ursprüngliche Planung bleibt erhalten.

## Entscheidungsvorschlag

Ein gemeinsamer Reservoir-Optimizer mit zwei klar getrennten Aufgaben:

1. Gute vollständige Fahrpläne aus einem geprüften All-Stop-Plan und dem
   vorhandenen Reservoir-Incumbent verbessern. CP-SAT repariert gemeinsam
   ausgewählte Einsätze, STOP/SKIP, Waiting und ganzzahlige Passagiere.
2. Ein optimistisches, zunächst kleines Zeitintervallmodell in Gurobi begrenzt,
   wie viele Personen bis zu welchen Zeiten ihr Ziel erreichen können.
   Ressourcen, Fahrzeugbestand und direkte Beförderungen werden dabei explizit
   berücksichtigt oder mit ausgewiesener Gültigkeit relaxiert. Verfeinerung
   beseitigt nachgewiesene Ursachen zu optimistischer Schranken.

Das ist eine vorgeschlagene eigene Übertragung bekannter Methoden. Für dieses
Seilbahnproblem ist weder ihre Geschwindigkeit noch eine schnelle Schließung
des globalen Gaps bewiesen. Die Entwicklung des Schrankenmodells ist das
größere Forschungsrisiko. Eine kleine Modellbeschreibung garantiert keinen
kleinen Suchraum.

## Was die bisherigen Ergebnisse tatsächlich tragen

| Befund | Konsequenz |
|---|---|
| Geprüfter Reservoir-Plan: 368765.821408 Passagiersekunden, 1280/1280 bedient, 38 eingesetzte Kabinen, 8 SKIPs, Waiting vorhanden | Es gibt bereits einen brauchbaren Ausgangsfahrplan für diese Domäne. |
| 24 CP-SAT-/IBM-Formulierungsläufe: kein bestätigter großer Vorteil; vergleichbare R-Untergrenze 109032.727040 | Produktkopplungen und reine Formulierungsvarianten haben das Schrankenproblem bisher nicht gelöst. |
| A–D: K39 No-Wait D verbessert wenig, bleibt am Root; K20 lässt sich schnell beweisen | Nicht als Waiting-/Reservoir-Beleg verwenden. |
| Whole-horizon Root-CG: einzeln attraktive Spalten sind gemeinsam oft unverträglich; Merge-Gate gescheitert | Keine neue Branch-and-Price-Architektur allein mit dem Argument kleinerer Master empfehlen. |
| Partial Passenger Benders: schwache globale Schnitte, nur eine gekoppelte Passagierkomponente | Passagierkonkurrenz nicht hinter voneinander unabhängigen OD-Teilproblemen verstecken. |
| Reservierungsheuristik: kleine Verbesserungen, größere Reparaturen überwiegend Timeout | Unveränderte Greedy-/Beam-Suche nicht als Durchbruch verkaufen. |
| Muster mit Zeit-Hints nach etwa 4 s zulässig, ohne Hints nach 300 s UNKNOWN | Den vollständigen bisherigen Fahrplan bei Reparaturen nutzen. |
| DIDP: Waiting schon bei K2/K4 sehr teuer | Kein weiterer großer CABS-Lauf derselben Formulierung. |

Belege:
[Reservoir-Audit](../findings/ddd_cp_sat_correctness_audit_20260910.md),
[CP-Kampagne](../findings/cp_formulation_campaign_20260910.md),
[A–D](../../benchmarks/output/arc_flow_passenger_campaign_20260910_v2/comparison.md),
[Root-CG-Gate](../findings/ddd_merge_aware_root_gate.md),
[Benders-Gate](../findings/ddd_partial_passenger_benders_root_gate.md),
[Reservierungsversuche](../findings/ddd_reservation_insertion_gate.md),
[Zeit-Hints](../findings/ddd_pattern_time_hint_ablation_20260910.md),
[DIDP](../findings/ddd_fixed_k_didp_pilot_20260910.md).

Der vorhandene Reservoir-Plan ist noch kein isolierter Vorteil gegenüber einem
global optimalen Reservoir-All-Stop-Betrieb. All-Stop und Skip-Stop müssen
denselben Anlauf, Nachfrageverlauf, Betriebshorizont, Anschluss und Flottenvertrag
verwenden. Der feste K38-Plan mit 399287 und der feste K39-No-Wait-Plan sind keine
solche Paarung. Ihre Bounds dürfen nicht in eine Reservoir-Auswertung eingehen.

## Betriebsmodell: Einsätze und ein gemeinsamer Kabinenbestand

Ein Einsatz beginnt mit einer Ausfahrt, enthält beliebig unterschiedliche
STOP/SKIP-Entscheidungen über einen oder mehrere Umläufe und endet mit leerer
Rückkehr. Es gibt keine erzwungene Periodizität und keine Pflicht zur Rückkehr
nach jeder Runde. Waiting findet weiterhin nur am erlaubten STOP-Exit statt.

Der aktuelle CP-Kern erlaubt genau einen zusammenhängenden Einsatz je Kabine.
Wiedereinsatz ist eine echte Domänenerweiterung und erhält einen eigenen
Fingerprint, einen unabhängigen Validator und neue Baselines/Bounds.

Für identische Kabinen an genau einem idealen Reservoir ohne individuelle
Wartungs-/Schichtregeln lässt sich die physische Kabinen-ID zunächst weglassen.
Jeder aktive Einsatz belegt eine Einheit des Bestands von Ausfahrt bis erneuter
Verfügbarkeit. Für konkrete Einsatzintervalle gilt:

\[
\sum_p 1\{d_p\le t<a_p\}\le K_{\max}\quad\text{für alle }t.
\]

Bei diesen Annahmen können die Intervalle anschließend durch chronologische
Vergabe freier Kabinen auf höchstens Kmax physische Kabinen verteilt werden.
Eine minimale Depotbearbeitungszeit würde in a_p eingehen. Physische Port-
Headways und Schutzzeiten werden unabhängig davon geprüft; gleichzeitige
Rückkehr/Ausfahrt wird nicht allein durch die Bestandsrechnung freigegeben.
Die Rückkehr ist kein automatischer Passagierausstieg an Station A.

Im anonymen Netz ist dieselbe Idee eine Bestandsfortschreibung:

\[
R(t)=K_{\max}-\#\mathrm{Ausfahrten}_{\le t}
                   +\#\mathrm{verfügbare\ Rückkehrer}_{\le t}\ge0.
\]

Damit begrenzt Kmax physische Kabinen, nicht die Gesamtzahl aller Einsätze.
Bei unveränderter Ereignisstruktur ändert Kmax vor allem eine Kapazität;
es erzwingt keine Kopie sämtlicher Besuche und Passagiervariablen pro
zusätzlicher ungenutzter Kabine. Mehr erlaubte Einsätze können die Suche
trotzdem vergrößern. Die Zahl benötigter Einsatzobjekte ist nicht automatisch
klein. Ein begrenzter Einsatzpool ist zunächst nur ein Primalverfahren.

Das Flottenlimit bleibt für einen beweisbaren endlichen Versuch ausgewiesen.
Ein empirisches Plateau bei Kmax=50 beweist nicht, dass 100 nie helfen können.
Ein fleet-unbeschränkter Claim braucht eine gültige abgeleitete Grenze oder
eine passende Relaxation, die den Incumbent erreicht.

## Gute Incumbents: gemeinsam reparierte Einsätze

Die erste Implementierungsstufe kann den aktuellen Single-Use-Vertrag behalten,
um Suchwirkung und Wiedereinsatz nicht gleichzeitig zu verändern.

- Seed: geprüfter All-Stop-Plan derselben Reservoir-Domäne plus bester kompatibler
  vorhandener Incumbent. Die beste validierte UB bleibt jederzeit erhalten.
- Wähle einen Nachfrage-/Ressourcenengpass, beispielsweise die lange Wartezeit
  einer OD-Gruppe oder dicht belegte STOP-Exits.
- Öffne gemeinsam wenige betroffene Einsätze, zunächst beispielsweise 3–6,
  einschließlich tatsächlicher Blockierer. STOP/SKIP, Waiting, Dispatch,
  Rückkehr und Passagiermengen dieser Einsätze sind gleichzeitig veränderbar.
- Erlaube zusätzlich ein bis zwei neue optionale Einsätze sowie Entfernen oder
  Verkürzen vorhandener Einsätze. So wird eine andere Flottennutzung aktiv als
  Suchentscheidung angeboten.
- Unveränderte Bewegungen werden als feste Ressourcenkalender eingesetzt;
  deren Passagiermengen können zunächst als feste Residualnachfrage behandelt
  werden. Das ist eine ausgewiesene Nachbarschaft, keine globale Beschränkung.
- Nutze vollständige Zeit-/Mengen-Hints und gleiche physische Ressourcenregeln.
  Waiting bleibt eine Integer-Tick-Variable, kein Netz mit allen Wartewerten.
- Validiere jeden akzeptierten Gesamtplan unabhängig und optimiere seine
  Passagierzuordnung mit dem bestehenden ganzzahligen Evaluator nach.
- Variiere Größe und Auswahl der Nachbarschaft. Ein Timeout ist UNKNOWN, kein
  Unzulässigkeitsbeweis. Lokale Schranken sind niemals globale Schranken.

Die Hypothese gegenüber früheren Versuchen lautet: vollständige Zeit-Hints,
kleinere gemeinsam reparierte Reservoir-Einsätze und Einfügen/Entfernen umgehen
einige Barrieren der fest vorgeschriebenen K39-Anordnung. Das ist noch kein
gemessener Vorteil. Auch diese Nachbarschaften können durch unveränderte
Außenpläne blockiert bleiben. Dann müssen Blockierer mit geöffnet oder die
Nachbarschaft erweitert werden; eine globale Kabinenreihenfolge wird nicht
festgeschrieben.

## Globale Untergrenze: Zielankunftskurven statt Mengen-Zeit-Produkte

Für Gruppe g sei d_g ihre Menge, r_g die Freigabe, H das Serviceende und
Y_g(t) die Anzahl der bis t tatsächlich am Ziel angekommenen Personen.
Das bestehende Reisezeitziel ist exakt

\[
C=\sum_g\int_{r_g}^{H}(d_g-Y_g(t))\,dt.
\]

Die noch nicht angekommenen Personen umfassen Wartende, Fahrgäste unterwegs
und am Ende Unbediente. Dies ist keine Änderung des Ziels auf bloße Bahnsteig-
Wartezeit. Für Tickzeit wird die entsprechende exakte Summe verwendet.

Wähle zunächst wenige Intervalle mit sämtlichen Nachfragefreigaben als Grenzen.
Mit \(Y_{g,j+1}=Y_g(\tau_{j+1}^{-})\) für **streng vor** dem Intervallende
gelieferte Personen ergibt die
optimistische Rechnung

\[
C_{LB}=\sum_j(\tau_{j+1}-\tau_j)
      \sum_{g:r_g\le\tau_j}(d_g-Y_{g,j+1})
\]

eine Kostenunterbewertung: Alle Lieferungen eines Intervalls werden zu dessen
Beginn gutgeschrieben. Die Koeffizienten sind konstant; ein Produkt aus
variabler Menge und variabler Zeit entfällt. Die Formel allein ist keine starke
Schranke. Entscheidend sind gültige Obergrenzen für Y:

- Mindestfahrzeiten mit STOP am Ursprung und Ziel, Freigaben und Servicehorizont;
- anonyme Kabinenbewegung und Reservoirbestand einschließlich Rückkehr;
- gemeinsame Sitzkapazität der OD-Flüsse;
- optimistisch, aber sicher begrenzte STOP-/SKIP-Nutzungen der Ressourcen;
- direkte Fahrt zum ersten nachfolgenden Ziel; kein stiller zusätzlicher Umlauf;
- nachweisbar notwendige Belegungsanteile und Headways innerhalb von Zeitfenstern.

Bei Ressourcenfenstern sind Randübertritte und Schutzzeiten gesondert zu
behandeln. Eine pauschale Kapazität floor(Intervallbreite/Headway) kann gültige
Pläne ausschließen und ist ohne Randbeweis unzulässig. Variable Waiting-
Belegung darf weder als freie Parkmöglichkeit noch als unbewiesene konstante
Mindestbelegung angesetzt werden.

Ein LP ist als erste globale Relaxation zulässig, auch mit fraktionalen
Passagieren. Ein solcher Fluss ist kein exportierbarer Fahrplan. Für den exakten
Abschluss müssen Ganzzahligkeit und Kabinen-/Passagierkontinuität wiederhergestellt
werden; der bekannte Odd-Cycle-Fall bleibt Gegenprobe.

## Was eine echte Gap-Schließung zusätzlich benötigt

1. Jede gültige Originalbewegung muss in jedem Schrankenmodell darstellbar sein,
   zu nicht höheren Kosten. Das ist die zentrale Gültigkeitsprüfung.
2. Nur die globale Solver-BestBound dieses vollständigen Relaxationsmodells
   aktualisiert LB; weder ein Pool-MIP-Bound noch ein lokaler Reparatur-Bound.
3. Zeitbereiche werden anhand optimistischer Ankünfte, Ressourcenkollisionen
   und unzulässiger Kapazitäts-Neuzuordnungen verfeinert. Verbesserungen der
   Original-UB kommen ausschließlich aus vollständig geprüften Plänen.
4. Bei fraktionalen oder weiterhin unechten Lösungen reicht Zeitverfeinerung
   allein nicht. Zusätzliche Fluss-/Belegungsstruktur und schließlich ein
   ganzzahliger Master bzw. Branch-and-Bound sind erforderlich.
5. Für eine Vollständigkeitsbehauptung braucht es eine faire Verfeinerungsregel
   und ein vollständiges exaktes Endmodell der endlichen Tickdomäne. Im
   schlechtesten Fall wird dieses wieder sehr groß. Mit festem Speicher-/Zeit-
   limit kann nur ein Restgap berichtet werden.

Die frühere DDD-Unterstützungssuche hatte gerade das Problem, zahlreiche
optimistische Muster punktweise auszuschließen, ohne die entscheidende
Kapazitäts-/Zeitstruktur zu verstärken. Der neue Kern muss gegenüber diesem
Fehlermuster nachweislich bessere Schranken liefern. Das Wort DDD genügt nicht
als Begründung, und LNS allein schließt keinen globalen Gap.

## Geplanter Umfang und Reihenfolge

Das erste Paket umfasst S0–S5 im **bestehenden Single-Use-Reservoir** mit
Waiting, optionaler Flotte und unverändertem Reisezeitziel. S6–S7 planen den
anschließenden Wiedereinsatz und einen exakten Abschluss auf Kontrollfällen.
Der Ausbau hängt von den vorangehenden Ergebnissen ab; ein fehlgeschlagenes
Gate wird dokumentiert, nicht durch einen längeren Lauf derselben Variante
umgangen. Eine Umsetzung dieses Plans muss erreichte und ausstehende Stufen
getrennt ausweisen.

| Stufe | Implementierung | Prüfbares Zwischenergebnis | Voraussetzung |
|---|---|---|---|
| S0 | Domänenadapter, Referenzen, getrennte Zertifikate | gleicher Betriebsvertrag und reproduzierte Kosten | keine |
| S1 | exakte Ankunftskurven, optimistische Intervallkosten | mathematisch richtige Kostenabbildung | S0 |
| S2 | anonymer Fluss-Bound mit Ressourcenfenstern | gültige und hinreichend stärkere globale LB | S1 |
| S3 | gezielte Zeit-/Waiting-Verfeinerung | weitere LB-Steigerung bei gemessenem Modellwachstum | S2 |
| S4 | kleine warme CP-Reparaturmodelle | reproduzierte Nachbarschaftsoptima und native Verbesserungen | S0, danach S2-Gate auswerten |
| S5 | gemeinsamer Optimizer, Runner, fairer Vergleich | UB-/LB-Verlauf bei gleichem Budget | S3 und S4 |
| S6 | Einsätze ohne physische Labels, Wiedereinsatz | äquivalente Bestands-/Kabinenzuordnung | S5-Auswertung |
| S7 | Bound für Wiedereinsatz, exakter kleiner Abschluss | gleiche kleine Optima und ehrlicher großer Restgap | S6 |

Es erfolgt kein Wechsel des bestehenden Standards. IBM, DIDP, neue
Branch-and-Price-Verfahren, periodische Fahrplanbeschränkungen, individuelle
Kabinenregeln und mehrere Reservoirports sind nicht Teil dieses Pakets.
Die Sechs-Stationen-Geometrie folgt erst nach einem expliziten Topologiecheck.

## Gemeinsame Architektur und Schnittstellen

Neues Unterpaket `optimization/ddd/reservoir_hybrid/`; Solverbausteine werden
komponiert, nicht als kopierte Gesamtsolver angelegt. Die nachfolgenden Namen
sind geplante neue APIs. Bestehende Namen im Abschnitt Codekarte sind real.

| Geplante Datei | Klassen / Aufgabe |
|---|---|
| `domain.py` | `ReservoirOperatingDomain`, `ReservoirLifecycle`, `PreparedReservoirStructure`: unveränderliche Geometrie, Integer-Ticks, Nachfrage, sichere Zeit-/Routengrenzen; keine Solvervariablen |
| `certificates.py` | `ValidatedReservoirIncumbent`, `GlobalReservoirBound`, `LocalRepairResult`, `ReservoirCertificateLedger`: ausdrücklich verschiedene Gültigkeitsbereiche |
| `arrival_curves.py` | `ArrivalCurveEvaluator`, `ArrivalIntervalPartition`: exakte Kosten, Intervallprojektion, deterministische Verfeinerung |
| `bound_domain.py` | `PreparedReservoirBound`, `BoundProjectionWitness`: optimistische Bewegungs-/Passagier-Arcs und Nachweis ihrer Abdeckung |
| `bound_model.py` | `ReservoirArrivalBoundBuilder`, `ReservoirArrivalBoundOptimizer`: Gurobi-Modell, Zeilenfamilien, globale BestBound |
| `refinement.py` | `ReservoirRefinementPolicy`: Auswahl und Protokoll gültiger Zeit-, Waiting- und Ressourcenverfeinerungen |
| `repair.py` | `ReservoirNeighborhood`, `ReservoirRepairBuilder`, `ReservoirRepairOptimizer`: ausgewählte Einsätze, fixe Kalender, Residualnachfrage, vollständige Hints |
| `search.py` | `ReservoirNeighborhoodSelector`: deterministische Engpassauswahl, Zufallsanteil, wechselnde Nachbarschaftsgrößen |
| `optimizer.py` | `ReservoirHybridOptimizer`, `ReservoirHybridConfig`: Budgetverteilung, Checkpoints, Koordination und Abbruch |
| `deployments.py` ab S6 | `ReservoirDeployment`, `ReservoirFleetAllocator`: Einsatzidentität, Verfügbarkeit, nachträgliche Vergabe physischer Kabinen |

Die neue Benchmarkintegration liegt in `benchmarking/ddd_reservoir_hybrid.py`;
Einstieg `benchmarks/run_ddd_reservoir_hybrid.py`. Bestehende Runner bleiben
funktionsfähig. Vorgesehene Argumente:

```text
--phase replay|bound|repair|hybrid
--lifecycle single_use|reusable
--objective journey_time
--max-cabins K
--maximum-wait-seconds W
--resume-checkpoint PATH
--initial-bound-step-seconds 60
--bound-profile arrival_only|movement_capacity|resource_windows
--repair-sizes 3,6
--new-deployment-slots 2
--time-limit SECONDS --num-workers 12 --seed 0
--memory-limit-gib 8 --output-dir NEW_DIR --build-only
```

`reusable` wird bis S6 vor Modellbau abgelehnt. Das Bound-Zeitintervall verändert
**nicht** das physische Waiting-/Dispatch-Raster. Neue CLI-Werte werden vor
teurer Vorbereitung geprüft. Im ersten Paket ist nur Journey Time verfügbar;
Kapazitätsziele oder lexikografische Ziele werden nicht still eingeführt.

Single-Use-Adaption erhält den bisherigen physischen Problem-Fingerprint und
kanonische Ride-IDs. Das zusätzliche Modellmanifest enthält Profile,
Partitionsgrenzen, Relaxationsannahmen und Quellenhashes. Wiedereinsatz bekommt
einen neuen physischen Fingerprint und ein versioniertes Zertifikatsformat.
Eine kleinere verfügbare Flotte oder andere Nachfrage ist ebenfalls eine neue
Domäne. Solverzustände werden nicht als fortgesetzter Suchbaum ausgegeben.

## S0 — Betriebsvertrag und Referenzen festhalten

**Implementierung**

- [x] Bestehendes `DddReservoirCpSatProblem` in den solverfreien Domainadapter
  überführen. Zunächst ein gerichteter Ring, ein idealer Port, identische Kabinen.
- [x] Fixture **R** einfrieren: Fünf-Stationen-Geometrie, Max50, 1280 Personen,
  300 s Anlauf, 1200 s Service, 300 s Räumung, Exit-Waiting bis 1200 s,
  unveränderte Mikrosekundenticks und aktuelle Dispatch-/Rückkehrfenster.
- [x] Geprüften Plan aus
  `benchmarks/output/model_correctness_audit_20260910/checked_incumbent.json`
  neu validieren. Der historische Kontrollwert 368765.821408 ist ein Sollwert
  für diesen Checkpoint, keine einprogrammierte Konstante.
- [x] Analytischen All-Stop-Seed über `all_stop_reservoir_movement` erzeugen und
  seine ganzzahlige Passagierzuordnung auswerten. Die unveränderte Bewegung
  muss auch im Skip-Stop-Modell zulässig sein. Ein optimaler Assignment-Wert
  bleibt ein Wert für feste Bewegung, kein globales All-Stop-Optimum.
- [x] `ReservoirCertificateLedger` akzeptiert eine UB nur mit geprüftem Plan;
  globale LB nur mit passender Domäne, Ziel, gültigem Modell und Solvernachweis.
  Importierte historische UB ist keine native Suchverbesserung.

**Zwischentests / Gate G0**

1. Beide Referenzen unabhängig physisch und mit Integer-Passagieren prüfen;
   Import, Export und erneutes Lesen erhalten Werte und Belegungen.
2. Fremde Fixed-K-/No-Wait- oder Reservoir-Fingerprints ablehnen. Lokale
   Repair-Bounds und Pool-Bounds dürfen den globalen Ledger nicht aktualisieren.
3. All-Stop-Inklusion und optionale Flotte auf kleinen vollständig gelösten
   Fällen testen: höhere Kmax darf das Optimum bei sonst gleicher Domäne nicht
   verschlechtern. Das ist kein Anspruch auf monotone heuristische Endwerte.
4. Den bekannten Fixed-K-Horizont-Rundungsfall als Adapter-Gegenprobe aufnehmen.
   Falls neue Vorbereitung ihn betrifft, tickgenau korrigieren, versionieren
   und beide Vergleichsarme neu einfrieren; keine willkürliche Zeit-Toleranz.

G0 besteht nur mit übereinstimmenden Kosten innerhalb der bestehenden
Zertifikatstoleranz. Abweichungen zuerst erklären; keine Performancekampagne
auf ungeklärten Referenzen starten.

## S1 — Kostenabbildung ohne Optimierung beweisen und testen

**Implementierung**

- [x] Aus einem validierten Fahrplan Zielankünfte je Nachfragegruppe extrahieren.
  Kosten sowohl direkt aus Ride-Mengen als auch durch Integration/Summation der
  noch nicht angekommenen Personen berechnen.
- [x] Partition aus Servicegrenzen, sämtlichen Releases und ergänzenden
  gleichmäßigen 60-s-Grenzen erstellen. Nullbreite Intervalle entfernen.
- [x] Für einen konkreten Plan exakte kumulative Ankünfte an den Intervallenden
  und die oben definierte optimistische Kostenprojektion erzeugen.
- [x] Zusätzlich den instanzabhängigen analytischen Bound separat berechnen.
  Der spätere veröffentlichte LB ist mindestens dessen gültiger Wert; im
  Diagnosebericht bleibt der reine Intervallwert sichtbar.
- [ ] Python-Integer für Tickkosten und Personen verwenden. Vor Gurobi-Aufbau
  Koeffizienten-/Zählergrenzen und Skalierung prüfen; nach außen Tickkosten und
  Passagiersekunden eindeutig kennzeichnen.

**Zwischentests / Gate G1**

- Direkte Kosten = Ankunftskurvenkosten exakt in Ticks, einschließlich leerer
  Nachfrage, vollständiger Nichtbedienung und gesplitteter Gruppen.
- Ankunft bei Release, exakt bei H, einen Tick vor/nach einer Intervallgrenze;
  bei H unbedient versus genau ankommend mit identischer Resthorizontkostenregel.
- Release während Waiting am Ursprung; Zielankunft **vor** dessen Exit-Waiting.
- Für jeden enumerierten kleinen Plan: Intervallkosten <= exakte Kosten.
  Unterteilung einer Partition darf seine projizierten Kosten nicht senken.
- Partition mit allen Ankunftszeiten reproduziert für diesen Plan die exakten
  Kosten. Das beweist noch kein Optimum für andere mögliche Fahrpläne.

Artefakt: `arrival_identity.json` mit Originalkosten, Flächenkosten,
Intervallwerten und den verwendeten Grenzen. Noch kein Solverbenchmark.

## S2 — Kleine globale Relaxation mit Ressourcenwirkung

**Implementierung in drei getrennt messbaren Profilen**

- [x] `arrival_only`: Bediente kumulative Mengen, Releases, absolute
  Mindestankünfte, Nichtbedienung und Intervallkosten. Dient als schwache Kontrolle.
- [x] `movement_capacity`: anonymer Fahrzeugfluss zwischen Zustandsintervallen,
  STOP-/SKIP-Arcs, Dispatch, Rückkehr und gemeinsame Sitzkapazität. Für
  Single-Use gilt insgesamt `dispatch_count = return_count <= Kmax`.
- [x] `resource_windows`: ergänzend nachweislich notwendige Ressourcenbelegung
  innerhalb ausgewählter Zeitfenster. Bisherige Restriktionen bleiben erhalten.

Ein Bewegungsarc mit Intervallen I/J und Waitingbereich V wird aufgenommen,
wenn es mindestens ein lokal zulässiges Paar (t,w) mit t in I, w in V und
t + Routendauer + w in J gibt. Waiting-Freigabe, STOP-Only-Waiting und
Lebenszyklusgrenzen sind Teil dieses lokalen Prädikats. Optimistische Ankunfts-
und Boardingereignisse müssen zu den ursprünglichen Plattformoffsets passen.
Unterschiedliche lokale Realisierungen desselben abstrakten Pfades können
zunächst eine Relaxationslücke erzeugen; das wird ausdrücklich protokolliert.

Für Ressource r und Fenster W wird pro abstrakter Nutzung ein Koeffizient
gebildet, der **höchstens** der kleinsten Überlappung ihres geschützten
Intervalls mit W über alle lokal zulässigen (t,w) entspricht. Dann ist

\[
\sum_a e^{min}_{a,r,W}\,x_a\le |W|
\]

eine notwendige Belegungsbedingung. Mehrere Nutzungen derselben Ressource werden
mit ihrer tatsächlichen Multiplizität berücksichtigt. Minima über Teilbereiche
dürfen optimistisch unabhängig gewählt werden. Nicht bewiesene Koeffizienten
werden zunächst null, niemals geraten. Die Berechnung nutzt die vorhandenen
affinen Waitingkoeffizienten; keine vereinfachte neue Headway-Geometrie.
Diese Minima werden aus den endlich vielen Knickstellen der stückweise linearen
Überlappung und den lokalen Zeitgrenzen berechnet, nicht durch Enumeration aller
Waiting-Ticks. Ein Minimum über den kontinuierlich relaxierten lokalen Bereich
ist ebenfalls sicher, sofern es nachweisbar nach unten gerundet wird. Die
Wartefreigabe wird dabei als Vereinigung des Null-Wait-Falls und des zulässigen
positiven Wait-Bereichs behandelt. Eine nur bedingt vorhandene Ressourcennutzung
darf keinen positiven Mindestkoeffizienten erhalten, wenn sie für eine ihrer
repräsentierten Bewegungen gemäß Originalvertrag entfällt.

**Darstellungs- und Beweispflichten**

- [ ] `BoundProjectionWitness` projiziert jede Bewegung und jede ganzzahlige
  Beförderung eines Originalplans auf das Bound-Netz und prüft jede Zeilenfamilie.
- [ ] Freie Passagierwechsel innerhalb grober Zellen, relaxierte Ganzzahligkeit
  und gegebenenfalls zu frühe virtuelle Bewegungen als Relaxationen ausweisen.
  Export in einen physischen Fahrplan ist daraus nicht direkt zulässig.
- [ ] Fahrzeugfluss darf keine realen Starts erfinden. Optimistische Kreisläufe
  innerhalb einer groben Zelle aufdecken und mit gültigen Zeit-/Arbeitsbudgets
  begrenzen oder durch Verfeinerung beseitigen; nicht als echte Flotte behandeln.
- [ ] Ressourcenbetritt bei Betriebsende und Schutz darüber hinaus abbilden.
  Fenster jenseits des Endes dürfen Belegung erfassen; Räumzeit nicht abschneiden.
- [ ] Ein initiales LP ist zulässig. Bei einem später ganzzahligen Master wird
  dessen BestBound verwendet, nicht der bloße Wert seines besten Relaxationsplans.

**Zwischentests / Gate G2-Korrektheit**

Vollständige Enumeration kleiner K1/K2-Fälle mit STOP/SKIP und Waiting in kleinen
Tickbereichen; K4-Kontrollen gegen CP-SAT. Für jedes Profil:

1. Jede zulässige Originalbewegung muss einen erfüllten Projektionsnachweis haben.
2. Globale LB <= unabhängig bestimmtes Originaloptimum; bekannte UB nur zusätzlich
   als Gegenprobe. Ein Bound unter einem schlechten Seed allein genügt nicht.
3. Zwei Ressourcen, Bypass-Überholen, alle Sitze belegt, Aus-/Einstieg im selben
   Besuch, vor/nach Release, H/H+1, leere Rückkehr, vollständig ungenutzte Flotte.
4. Ressourcenfenster an beiden Intervallrändern; Waiting verlängert Freigabe
   beziehungsweise verschiebt Eintritt genau entsprechend der realen Nutzung.
5. Profile sind geschachtelte Relaxationen; optimal gelöste LP-Werte dürfen beim
   Hinzufügen gültiger Zeilen nicht sinken. Numerische Fehler sind kein Fortschritt.

**Zwischentest auf R / Gate G2-Nutzen**

Drei Läufe, je 300 s einschließlich Aufbau und Abschluss, identische Partition,
zwölf Threads, kein importierter Root-CG-Bound. Zielgröße des ersten Kerns:
höchstens 50000 Variablen, 250000 Zeilen und 4 GiB gemessene Peak-RSS. Das sind
vorab gewählte technische Grenzen, keine bekannten Messwerte. Überschreitung
beendet den Pilot mit Befund; sie rechtfertigt kein stilles Abschneiden der Domäne.

**Aktualisierung durch Nutzerentscheidung:** Der Nachtest darf vollständig ohne
Variablen-/Zeilenlimits bauen. Zeit und 4-GiB-Speichergrenze bleiben maßgeblich.
Die obige Größenvorgabe beschreibt den ersten Versuch, nicht den aktuellen
Abbruchvertrag. Vollständiger Nachtest und seine fehlende zusätzliche LB-Wirkung
sind im Umsetzungsbericht dokumentiert.

Als Weiterbau-Gate soll `resource_windows` mindestens **10 % des bisherigen
Abstands zwischen analytischer LB und gemeinsamer Start-UB** zusätzlich
schließen:

\[
LB_{neu}\ge LB_{analytisch}+0.10(UB_0-LB_{analytisch}).
\]

Bei den heutigen Kontrollwerten liegt das Ziel ungefähr bei 135006
Passagiersekunden. Das ist ein Mindestnutzen für Weiterarbeit, noch kein guter
Endgap. Profilwirkung, reiner Bound und Maximum mit analytischem Bound werden
separat berichtet. Scheitert G2-Nutzen, wird S3/S5 als globaler Ausbau zunächst
nicht begonnen. Ein begrenzter S4-Diagnosetest bleibt möglich; das ursprüngliche
Ziel der Gap-Schließung ist damit aber nicht erfüllt.

## S3 — Verfeinerung, die messbar mehr als ein größeres Netz liefert

**Implementierung**

- [ ] Zunächst eine gemeinsame Partition verwenden; arc-spezifische Raster erst
  später, falls nachgewiesen unnötige Kopien dominieren. Releases bleiben Grenzen.
- [ ] Begrenzte Verfeinerungsvorschläge aus optimistischen Zielankünften,
  belegten Ressourcenfenstern und nicht konsistent zeitlich realisierbaren
  Übergängen erzeugen. Waitingbereiche nur lokal an betroffenen STOP-Arcs teilen.
- [ ] Kindarcs auf Elternarcs abbilden und die Projektion des feineren Modells
  in das gröbere testen. Gültige bisherige Schranken bleiben im Ledger erhalten.
- [ ] Nur vollständig bewiesene Unzulässigkeit erzeugt eine Ausschlussbedingung.
  Ein CP-Timeout liefert keinen Cut. Ein Konflikt bei einer einzelnen Wahl
  konkreter Zeiten verbietet nicht automatisch das gesamte Zeitintervall.
- [ ] Wiederkehrende gleiche Konflikte und unveränderte LB zählen. Nach drei
  abgeschlossenen Runden ohne Verbesserung oberhalb numerischer Toleranz den
  Engpass ausgeben, statt automatisch immer weiter zu expandieren.

**Zwischentests / Gate G3**

- Kleine Beispiele, in denen eine zu frühe virtuelle Ankunft durch einen
  gezielten Split verschwindet und die optimale Relaxations-LB strikt steigt.
- Kleine Beispiele, in denen die Lücke aus Passagier-Ganzzahligkeit stammt:
  korrekt erkennen, dass Zeitverfeinerung allein nicht genügt.
- Alle ursprünglichen Kontrollpläne müssen vor und nach jedem Split darstellbar
  bleiben. Raw Solver-Bounds und monotones Ledger getrennt prüfen.
- Ein 300-s-Lauf auf R mit höchstens fünf Verfeinerungsrunden; Aufbauzeit,
  Zeilen-/Variablenzuwachs und LB-Gewinn pro Runde erfassen.

Weitergabe an S5 verlangt mindestens eine auf R beobachtete zusätzliche
LB-Steigerung von **1 % des Startgaps dieser Stufe** bei höchstens doppelter
Modellgröße gegenüber S2 und eingehaltenem Speicherlimit. Andernfalls ist
Verfeinerung korrekt, aber als Skalierungsstrategie noch nicht bestätigt.

## S4 — Gemeinsame CP-Reparaturen im bestehenden Reservoir

**Implementierung**

- [x] Ein Reparaturproblem aus offenen Einsatz-IDs, optionalen neuen Einsätzen,
  festen Außenbewegungen und deren Passagierbelegung bilden. Zunächst ganze
  Einsätze öffnen; keine willkürlichen Schnitte durch belegte Kabinenfahrten.
- [x] Ressourcen außerhalb der Nachbarschaft als konstante Intervalle einsetzen.
  Nur nach sicherem Zeitbereichsnachweis irrelevante Außenintervalle weglassen.
  Nicht einfach das ganze Max50-Modell bauen und danach fast alles fixieren.
- [x] Gemeinsame Routentiming-/Ressourcenfunktionen aus dem bestehenden Builder
  wiederverwenden. Wenn dafür ein lokaler Builder extrahiert werden muss,
  dessen Legacy-Aufruf und Fingerprint kontrollieren.
- [x] Residualnachfrage = Nachfrage minus feste Außenzuordnung; Restflotte im
  Single-Use-Modell = Kmax minus Anzahl unveränderter eingesetzter Kabinen.
  Weggenommene innere Beförderungen gehen zurück in die Residualnachfrage.
- [x] Alle Variablen des erhaltenen Fahrplans hintbar halten. In lokalen
  Hilfs-IDs darf die globale Prefix-/Dispatch-Symmetrie nicht versehentlich
  neue Ausfahrten vor einem festen Nachbareinsatz verbieten. Erst den kompletten
  exportierten Single-Use-Plan wieder kanonisch umbenennen, inklusive Ride-IDs.
- [x] STOP/SKIP, volle Waitingbereiche, Dispatch und frühere Rückkehr gemeinsam
  öffnen. Während der Reparatur bleiben fest zugeordnete Außenpassagiere
  geschützt; nach Akzeptanz darf der ganzzahlige Evaluator global neu zuordnen.
- [ ] Erste Auswahlregeln: OD-Kostenschwerpunkt, belegter Exit samt Blockierern,
  Entfernen/Ersetzen eines schwachen Einsatzes; zusätzlich Zufallsauswahl.
  Größen 3 und 6, ein oder zwei neue Slots; lokale Limits zunächst 10/30 s.
- [ ] Beste UB monoton halten. Wenige unterschiedliche gültige Pläne dürfen
  separat als Suchstarts dienen; deren Auswahl ist keine neue Zielfunktion.

**Zwischentests / Gate G4-Korrektheit**

1. Alle Einsätze offen: kleines Reparaturmodell = kleines bisheriges globales
   CP-Modell hinsichtlich zulässiger Pläne und Optimum.
2. Alle Einsätze geschlossen: Seed exakt reproduziert; null neue Freiheitsgrade.
3. Teilmenge offen: Vergleich mit einem unabhängig aufgebauten Gesamtmodell,
   in dem die gleichen Außenbewegungen und Außenpassagiere fixiert sind.
4. Entfernen eines Einsatzes gibt dessen Nachfrage frei; Einfügen vor einem
   früher nummerierten Außenplan bleibt möglich. Kanonisierung erhält alle Mengen.
5. Einzelfall, in dem zwei gemeinsam geänderte Einsätze eine Verbesserung
   ermöglichen, während jede isolierte Änderung blockiert ist.
6. Volle Kabinen, Außenblockierer, Überholen, Waiting-Freigabe und Schutz über
   die Rückkehr hinaus; keine Außenpassagiere verschwinden beim Zusammenfügen.

**Zwischentest auf R / Gate G4-Suche**

Zwölf eingefrorene Nachbarschaften, je 10 s einschließlich Aufbau/Validierung,
jeder Versuch startet zunächst vom gleichen geprüften Seed. Je vier
nachfragebezogene, ressourcenbezogene und Einfüge-/Entferneversuche. Pro Versuch
erfassen: native Lösung, Verbesserung, UNKNOWN, aktive Freiheitsgrade,
Aufbau-/Suchzeit und globale Nachvalidierung.

Das diagnostische Gate verlangt mindestens einen unabhängig gültigen nativen
Gewinn und mindestens sechs native zulässige Reparaturen im Budget. Diese
kleine selektierte Reihe begründet noch keinen Performancevorteil. Scheitert
sie, zuerst Modell-/Hint-/Blockiererursache isolieren, keinen langen LNS-Lauf
anhängen. Der bessere historische Seed bleibt erhalten.

## S5 — Koordinator und erste gemeinsame Auswertung

**Implementierung**

- [x] `ReservoirHybridOptimizer` erhält Domain, optionale Referenz und Config;
  liefert getrennt beste validierte Lösung, gültige globale LB, Messverlauf
  und ausstehende Prüfungen. Ein lokales Optimum bekommt keinen globalen Status.
- [x] Bound- und Reparaturaufrufe sequenziell ausführen. Zu Beginn der
  Vergleichsphase höchstens 25 % des Laufbudgets für weitere Bounds reservieren;
  feste Regel im Manifest, keine nachträgliche Anpassung pro günstigem Ergebnis.
- [x] Die bisherige Gesamt-CP-Suche bleibt Kontrollarm und optionaler späterer
  Vollsuchkanal. Lokale Nachbarschaften allein werden nicht als exakt bezeichnet.
- [x] Gesamtdeadline in einem übergeordneten Prozess; Vorbereitung, Aufbau,
  Hintaufbau, Solver, Validierung und Schreiben zählen. Kontrolliertes Beenden
  der Prozessgruppe, Speichergrenze und atomische Checkpoints vorsehen.
- [x] Keine weitere Stufe automatisch starten, wenn Gate oder Budget fehlen.
  Abbruch ohne neue Lösung erhält den Seed; Abbruch ohne Bound erhält nur die
  letzte gültige Schranke, niemals einen Unzulässigkeitsbeweis.

**Vorgeschlagener Messrahmen für S0–S5: höchstens 90 Minuten Wandzeit.**
Implementierung und kleine Korrektheitstests sind getrennt; größere Replays,
Vorbereitung, Modellbau, Validierung und Auswertung der Messkampagne zählen mit.
Die Obergrenze ist Teil des künftigen Versuchsplans, kein jetzt gestarteter Lauf.

| Messabschnitt | Versuche | Budget | Nominell |
|---|---:|---:|---:|
| S2: drei Bound-Profile auf R | 3 | 300 s | 15 min |
| S3: adaptive Verfeinerung | 1 | 300 s | 5 min |
| S4: eingefrorene Reparaturen | 12 | 10 s | 2 min |
| S5: CP-Legacy gegen Hybrid, Seeds 0/1 | 4 | 600 s | 40 min |
| gemeinsame Vorbereitung, große Referenzprüfungen, Bericht und Reserve | — | — | 28 min |

Die G2-/G3-/G4-Gates werden zwischen den Abschnitten ausgewertet. Nicht
ausgeführte Abschnitte stehen als ausstehend im Bericht. Kein Lauf startet,
wenn sein vollständiges Budget plus Abschlussreserve nicht mehr passt.

Beide S5-Arme erhalten dieselbe unveränderte Start-UB und dieselbe bereits
zertifizierte anfängliche LB; deren Erzeugungsaufwand bleibt separat in der
Kampagnenzeit sichtbar. Eine weitere LB-Steigerung im Hybrid wird auf dessen
600 s angerechnet. CP verwendet Legacy-Formulierung und vollständige bestehende
Hints; die lokale Suche wird nicht mit einem künstlich kalten CP-Lauf verglichen.
Seed 0: CP zuerst, Seed 1: Hybrid zuerst; zwölf Worker, keine konkurrierenden
Solverjobs. CP-Seeds sind keine vollständige Determinismusgarantie.

**Performanceempfehlung nur bei Bestätigung in beiden Seeds:** entweder
mindestens 1 % niedrigere validierte Kosten oder mindestens 5 Prozentpunkte
kleinerer vergleichbarer globaler Gap ohne schlechtere UB. Kleinere Effekte
sind ein Befund, keine Empfehlung zum Hauptsolverwechsel. Ein Erfolg nur bei
UB oder nur bei LB wird genau so benannt; keine Zusammenfassung als Erfolg
beider Ziele. Diese Schwellen sind vorab gewählte Nutzengrenzen, keine Prognose.

## S6 — Wiedereinsatz und Trennung von Einsatz- und Kabinenidentität

Diese Stufe folgt erst auf den S5-Bericht. Sie kann fachlich sinnvoll bleiben,
auch wenn einzelne Suchkomponenten unentschieden sind; ein gescheiterter
Schrankenansatz wird dadurch jedoch nicht zum exakten Gesamtverfahren.

**Implementierung**

- [ ] `ReservoirDeployment` enthält stabile Einsatz-ID, Route, Zeiten, Waiting,
  Rückkehr und einsatzbezogene Passagierzuordnung. Physische Kabinen-ID ist eine
  gesonderte Zuordnung im endgültigen Zertifikat.
- [ ] In CP belegt jeder ausgewählte Einsatz ein optionales Intervall von
  Dispatch bis Verfügbarkeit; `Cumulative` mit Bedarf 1 und Kapazität Kmax
  ersetzt die feste Zuordnung zu einer bestimmten Kabine.
- [ ] Vorläufige Einsatzpools als Primalbeschränkung kennzeichnen und beim
  Einfügen erweitern. Ein künstliches Limit der Poolgröße ist kein gültiges
  globales Flottenlimit und erzeugt keinen Originalproblem-Bound.
- [ ] Bereits vorhandene Single-Use-Pläne in die erweiterte Domäne übersetzen,
  vollständig prüfen, als Referenz führen. Ihre **UB**, aber nicht ihre LB,
  darf nach erfolgreicher Prüfung übernommen werden.
- [ ] Kabinen nach Verfügbarkeit chronologisch zuweisen; freie Kapazität und
  Minimum der benötigten IDs entsprechen für feste Intervalle deren maximaler
  Überlappung. Gleiche Zeitpunkte deterministisch nach dem deklarierten
  Verfügbarkeitsvertrag behandeln; der separate Portcheck bleibt zwingend.
- [ ] Keine Lade-/Wartungszeiten oder Depotheadways erfinden. Vorerst dieselbe
  ideale Anschlussgeometrie verwenden; Schutzintervalle bleiben auch nach
  Rückkehr erhalten. Neue Depotphysik wäre eine eigene Domänenänderung.

**Zwischentests / Gate G6**

- Kleine feste Einsatzmengen: Greedy-Kabinenvergabe gegen vollständige Enumeration
  aller Kabinenzuordnungen; gleiche minimale Flotte und gleiche Zulässigkeit.
- Mehr Einsätze als Kabinen, zwei getrennte Einsätze derselben Kabine, echter
  Reservoiraufenthalt und wechselnde Zahl aktiver Kabinen.
- Rückkehr exakt zum nächsten Dispatch: Bestand kann zulässig sein, Portressource
  trotzdem unzulässig. Beide Fälle separat testen.
- Keine zweite Fahrt vor Verfügbarkeit, keine besetzte Rückkehr, keine
  Passagierübertragung zwischen Einsätzen oder künstlicher Ausstieg am Port.
- Alle Legacy-Pläne bleiben in der Erweiterung zulässig. Ein kleiner Kontrollfall
  muss mit Wiedereinsatz bei gleicher Kmax strikt besser sein können; Single-Use
  bleibt mit seinem bisherigen Ergebnis reproduzierbar.
- Strukturvergleich Kmax 50/100 bei **demselben Einsatzpool**: keine Verdopplung
  der CP-Besuchsmatrix. Zusätzlich offen berichten, wenn größere Pools für
  tatsächliche neue Einsätze das Modell anschließend wachsen lassen.

S6 startet keinen weiteren großen Performanceblock. Dessen Budget und
Vergleichsfälle werden erst anhand des S5-Berichts festgelegt.

## S7 — Globaler Bound für Wiedereinsatz und exakter Abschluss

**Implementierung / Beweispflichten**

- [ ] Den Single-Use-Dispatchdeckel im Bound durch konservativ zeitgekoppelten
  Reservoirbestand ersetzen. Innerhalb grober Zellen wird Rückkehr nötigenfalls
  optimistisch früh verfügbar; der genaue Unterschied ist eine Relaxationslücke.
- [ ] Alle neuen gültigen Wiedereinsatzpläne müssen projektierbar sein. Als
  schwache Start-LB ist auch eine explizite Relaxation ohne Flottenlimit möglich;
  eine alte Single-Use-LB ist es im Allgemeinen nicht.
- [ ] Fahrzeug-/Passagierkontinuität, Boarding vor Kapazitätszählung, Ausstieg
  vor Neueinstieg und erste Zielstation im exakten Endmodell nachweisen.
- [ ] Einen vollständigen exakten Referenzbuilder auf sehr kleinen Tickdomänen
  bereitstellen; Ganzzahligkeit und sämtliche Ressourcen werden dort erhalten.
  Verfeinerung muss bis zu dieser Darstellung gelangen können. LP-Konvergenz
  allein wird nicht als ganzzahlige Optimalität ausgegeben.
- [ ] Eine faire vollständige Verfeinerungs-/Verzweigungsregel spezifizieren;
  begrenzte lokale Suchpools dürfen den Beweiskanal nicht einschränken.
  Ein produktiver großer exakter Ausbau ist vom Bestehen dieses Gates abhängig.

**Zwischentests / Gate G7**

1. Enumerierte Single-Use- und Reusable-Kontrollen: `LB <= optimum <= UB` in
   jeder Runde; am exakten kleinen Endmodell gleicher optimaler Wert wie CP.
2. Der Odd-Cycle-Fall muss im Integer-Abschluss seinen Integer-Wert erhalten.
3. Beispiel mit innerhalb grober Zellen getauschter Kabinen-/Passagierzuordnung:
   im optimistischen Bound erlaubt und dokumentiert, am exakten Ende ausgeschlossen.
4. Wiedereinsatz darf nicht durch den alten Gesamtausfahrtsdeckel abgeschnitten
   werden; ein Test verwendet mehr Ausfahrten als physische Kabinen.
5. Timeout, Speicherabbruch, nicht vollständige Verfeinerung und LP-Integrality-Gap
   liefern einen Restgap und niemals den Status global optimal.

Erst nach G7 darf das Verfahren für die getestete endliche Tickdomäne als
theoretisch vollständig beschrieben werden. Eine schnelle Gap-Schließung auf
R oder sechs Stationen verlangt zusätzliche Messungen. Im schlechtesten Fall
bleibt das exakte Endmodell groß; das wird nicht durch ein festes Speicherlimit
oder eine endliche Zahl ausgewählter Zeitpunkte wegdefiniert.

## Messung des Fortschritts und Berichtspflicht

Neue Ergebnisse unter `benchmarks/output/reservoir_hybrid_<timestamp>/`;
historische Daten bleiben unverändert. Gemeinsame Dateien: `domain.json`,
`references.json`, `source_hashes.json`, `versions.json`, `gate_results.json`,
`status.json` und abschließender `comparison.md`. Pro Versuch: Config,
Model-Fingerprint, Partition, Projektionsnachweise, Solverlog, `events.jsonl`,
validierte Checkpoints und Modellgrößen nach Zeilenfamilie.

Jedes Ereignis enthält tatsächliche Zeit seit Versuchsbeginn, Phase,
unveränderte Domänenidentität und Gültigkeitsbereich. Erfassen:

- Vorbereitung, Netzwerk-/Passagieraufbau, Hints, Solver, Validierung,
  Gesamtwandzeit, Peak-RSS, Variablen nach Typ, Zeilen und Nichtnullkoeffizienten;
- native erste Lösung, Seedübernahme, tatsächliche Verbesserungen, letzte
  UB-/LB-Verbesserung und deren Alter bei Laufende;
- rohe Solverwerte, beste validierte UB und vergleichbare globale LB getrennt;
  lokale Bounds nur mit ihrem Nachbarschaftsbezug;
- Zahl geprüfter/reparierter Nachbarschaften, UNKNOWN-Anteil, gewählte Einsätze,
  Einfügungen/Entfernungen, Waiting, bediente Personen und maximale aktive Flotte;
- bei S3: Partitionen, neue Arcs/Zeilen, Projektionslücken und LB-Gewinn pro Runde.

Für jeden größeren Lauf werden UB/LB bei 0/25/50/75/100 % der tatsächlichen
Laufzeit sowie eine Fortschrittskurve ausgegeben. Ein operatives Plateau wird
als **kein materieller Gewinn während der letzten 25 % der Laufzeit** markiert:
materiell = 0.1 % Kostenverbesserung bzw. 0.1 Prozentpunkte Gap-Verbesserung bei
festgehaltener UB für die LB-Bewertung. Kleinere Änderungen bleiben sichtbar.
Ein Plateau ist kein Unmöglichkeitsbeweis für spätere Fortschritte; umgekehrt
zählen fortlaufende Solveriteration oder Seedübernahme nicht als Verbesserung.

Der Bericht benennt pro Gate bestanden / gescheitert / ausstehend, erklärt die
jeweilige Ursache und empfiehlt nur den durch Daten getragenen nächsten Schritt.
Das Ergebnis darf lauten: guter Primal-Optimizer mit offener globaler Schranke,
stärkerer Bound ohne bessere Fahrpläne oder beides noch unzureichend.

## Wiederverwendung im Code

Pfade relativ zu `src/ropeway_skip_stop_optimization/optimization/ddd/`:

| Bestehender Baustein | Verwendung / Abgrenzung |
|---|---|
| `reservoir_cp_sat_problem.py`, `reservoir_cp_sat_movement.py` | Single-Use-Vertrag, Besuchsfortschreibung, optionale Einsätze; Wiedereinsatz ist neu. |
| `cp_sat_movement.py`, `models.py` | Exakte affine Waiting-/Ressourcengeometrie. |
| `cp_sat_passenger.py` | Ganzzahlige Beförderungen und exakte Bewertung in Reparaturen. |
| `reservoir_cp_sat_certificate.py`, `primal_evaluation.py` | Unabhängige Zertifikate und Assignment, Lifecycle-Adapter erweitern. |
| `passenger_master.py`, `network_refinement_model.py` | Bestehende optimistische Flüsse und Verfeinerungsprotokolle; nicht unverändert als neuen starken Bound ausgeben. |
| `anonymous_reservoir_network.py`, `reservoir_arc_flow.py` | Anonymer Fahrzeugfluss; alter Zeitraster-/Phasenvertrag ist enger und kein Bound für den neuen CP-Vertrag. |
| `arc_flow_passenger_formulation.py` | A-/C-Beweisprinzipien wiederverwenden; D nicht ungeprüft auf anonyme Flüsse übertragen. |

## Forschungsgrundlagen und Grenzen der Übertragung

- [Fermín Cueto et al. (2021), Multi-trip routing, fleet sizing and depot
  location](https://onlinelibrary.wiley.com/doi/full/10.1002/net.22028):
  Mehrere Einsätze pro Fahrzeug und Trennung von Routen und Fahrzeugzuordnung.
  Die oben formulierte reine Bestandsäquivalenz ist eine eigene Ableitung unter
  den engeren Annahmen eines einzigen idealen Reservoirs und identischer Kabinen.
- [Hà et al., CP und LP-basierte ALNS mit Synchronisationsbedingungen](https://arxiv.org/abs/1910.13513):
  Motivation für gezielte Nachbarschaften mit exakten Teilproblemen. Deren
  Fahrzeugproblem und Experimente sind kein Performancebeweis für die Seilbahn.
- [Marshall et al., Interval-based DDD](https://par.nsf.gov/servlets/purl/10226533):
  Optimistische Zeitintervalle und gezielte Verfeinerung anstelle eines vorab
  vollständig expandierten Zeitnetzes. Frachtkonsolidierung erlaubt andere
  Bewegungen als unsere direkte Passagierbeförderung; der Beweis ist anzupassen.
- [Van Dyk und Koenemann, Sparse DDD](https://arxiv.org/abs/2305.19176):
  Unterschiedliche Diskretisierungen je Arc können unnötige Netzkopien vermeiden;
  die dort besonders günstigen hochgradigen Netze sind nicht unser Ring.
- [Van Dyk und Koenemann, Hard node storage](https://arxiv.org/abs/2303.01419):
  Begrenzte Warte-/Lagerkapazität verlangt sorgfältige Relaxationen. Das liefert
  keine fertige Formel für die längenabhängigen STOP-Exit-Schutzintervalle.

Die Ankunftskurven-Gleichung und ihre optimistische Intervallsumme sind hier
direkt aus unserem bisherigen Reisezeitziel abgeleitet. Die vollständige
ressourcenbewusste Seilbahnrelaxation ist vorgeschlagen, nicht implementiert
oder durch die zitierten Papers bereits bewiesen.
