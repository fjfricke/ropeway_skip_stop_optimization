# Lastbewusste Beförderungszuordnung und exaktes Reservoir-Timing

Stand: 12.09.2026. **Pilot implementiert und getestet.** Ergebnisse und
Abbruchentscheidung stehen in
[`reservoir_assignment_timing_pilot_20260912.md`](../findings/reservoir_assignment_timing_pilot_20260912.md).

## 1. Fragestellung und Entscheidung

Wir prüfen Idee 1 aus der Conveyor-Recherche: Kann ein kleines Zuordnungsmodell vollständige, nachfragebezogene Kabinenaufträge erzeugen, deren gemeinsame zeitliche Umsetzung CP-SAT schnell findet?

Der Pilot besteht pro Versuch aus genau zwei nativen Solveraufrufen:

1. **Gurobi:** ganzzahlige Beförderungen, Haltemuster und Einsatzlängen festlegen; die Belastung der Ressourcen berücksichtigen, gegenseitige zeitliche Konflikte zunächst auslassen.
2. **CP-SAT:** diese Entscheidungen fixieren und gemeinsam exakte Dispatchzeiten, Exit-Waiting und konfliktfreie Bewegungen suchen.

Es gibt zunächst keine adaptive Rückkopplung, Benders-Schleife, eigene LNS, Prioritätensuche oder Bibliothek fertig getakteter Fahrten. Scheitert das Timing, ist genau dieser Auftragssatz nicht bestätigt. Er wird nicht still repariert oder durch den Referenzfahrplan ersetzt.

**Erste Erfolgsfrage:** Finden wir einen neuen, unabhängig gültigen Plan, der mindestens zehn Personen mehr bedient als die eingefrorene All-Stop-Referenz? Erst danach lohnt eine größere Entwicklung. Die Referenz zu übertreffen ist noch kein Beweis gegen sämtliche möglichen All-Stop-Fahrpläne.

## 2. Forschungsbasis und vorhandene Evidenz

### Literatur

- [Debold, Gönsch, Dochow (2025): Order routing in sequential zone picking systems](https://doi.org/10.1007/s00291-025-00833-y). Stationsbesuche und Auftragszuordnung werden über eine Arbeitslastapproximation bzw. adaptive Verfahren gewählt. Die statische Approximation lässt Transport- und Zeitkonflikte aus; sie ist kein exakter Fahrplan. Übertragen wird die Trennung von sinnvoller Bedienungsentscheidung und detaillierter Ausführung. Unsere exakte zweite Stufe ist eine eigene Ergänzung.
- [Souiden et al. (2020): Retail order picking scheduling with missing operations and limited buffer](https://ifatwww.et.uni-magdeburg.de/ifac2020/media/pdfs/3344.pdf). Vorgegebene Stationsbesuche werden als Non-Permutation Flow Shop mit Transportzeiten und begrenzten Puffern eingeplant. Übertragen wird das Scheduling eines bereits bestimmten Aufgabensatzes. Der Originalartikel liefert keine Skalierungsgarantie für unsere Instanz.
- [Van der Gaast et al. (2020): Capacity Analysis of Sequential Zone Picking Systems](https://doi.org/10.1287/opre.2019.1885). Stützt die Bedeutung von Blocking und Ressourcenauslastung. Seine stochastische Kapazitätsapproximation wird weder als deterministischer Seilbahnfahrplan noch als globale Schranke übernommen.

Keine dieser Arbeiten beweist die Leistungsfähigkeit des hier vorgeschlagenen Gesamtverfahrens. Insbesondere können Waren teilweise aus mehreren Zonen bezogen werden; unsere Fahrgäste behalten feste Ursprungs- und Zielstationen.

### Was wir bereits wissen

Die [Reservoir-Diagnose](../findings/reservoir_diagnostics_20260911.md) untersuchte Max50, Waiting und 1.280 Personen mit Reisezeitziel:

| Freie Entscheidungen | Beobachtung |
|---|---|
| Nur Passagierzuordnung, Bewegung fest | Optimum in 3,4–3,6 s |
| Nur Zeiten, Halte und Mengen fest | Optimum in 8,8–13,4 s |
| Zeiten und Mengen frei, Halte fest | Nach rund 116 s noch 14,7–15,0 % Teilproblem-Gap |
| Zusätzlich Ressourcenordnung fest, Mengen frei | Weiterhin 12,3–12,5 % Teilproblem-Gap |

Diese Ergebnisse motivieren die Fixierung **beider** Entscheidungen: Halte und Beförderungsmengen. Sie stammen von einem bereits gültigen Referenzplan. Dass neu erzeugte Aufträge ebenso schnell taktbar sind, ist die zu prüfende Hypothese.

Der Pilot optimiert `unserved`. Dieses Ziel enthält schon heute keine Reisezeitprodukte. Eine Verbesserung darf deshalb nicht mit der vermeintlichen Entfernung solcher Produkte erklärt werden.

Abgrenzung zur [Mustersuche](../findings/ddd_pattern_search_followup_20260910.md) und zum [Reservoir-Reparaturversuch](../findings/reservoir_global_passengers_conflict_test_20260911.md): Es werden nicht lediglich einzelne STOP-Bits verändert und anschließend alle Passagiermengen erneut freigegeben. Der neue Versuch erzeugt einen vollständigen anderen Beförderungsauftrag und fixiert ihn für das Timing. Reines abwechselndes Optimieren der beiden alten, am Seed bereits optimalen Blöcke wird nicht wiederholt.

## 3. Umfang und unveränderter Modellvertrag

- Fünf-Stationen-Reservoir, maximal 50 verfügbare Kabinen, ein zusammenhängender Einsatz je verwendeter Kabine.
- Die Anzahl verwendeter Kabinen ist in Stufe 1 frei; Stufe 2 fixiert die gefundene Anzahl und die einzelnen Einsätze.
- STOP/SKIP, vollständiger bestehender Waitingbereich, ursprüngliche Integer-Mikrosekunden und Waiting-/Dispatch-Schrittweiten.
- Nur kanonische Ride-IDs aus `DddReservoirCpSatProblem.passenger_build`; der Zielbesuch ist der erste nachfolgende Besuch der Zielstation.
- Ein-/Ausstiegsmengen ganzzahlig, Freigabe beim tatsächlichen Plattformausstieg einschließlich Waiting, Zielankunft vor Ziel-Waiting.
- Kapazität auf jedem befahrenen Abschnitt; Aussteigen vor neuem Einstieg.
- Leere rechtzeitige Rückkehr zum Port, letzter Zustandsknoten vorhanden, Schutzzeiten nicht am Horizont abschneiden.
- Keine künstliche globale physische Kabinenreihenfolge; Überholen bleibt erlaubt.
- `journey_time` bleibt Kontrollkennzahl. Kein Reisezeit-Zweitoptimierer in diesem Pilot.
- Fixed-Start, sechs Stationen, Mehrfacheinsatz, neue Headwayannahmen und Vergröberung des Zeitrasters gehören nicht zum Paket.

**Physikalische Aussagegrenze:** Der [Headway-Audit](../findings/headway_physics_audit_20260911.md) identifiziert die idealisierte Reservoir-Einfahrt als offene geometrische Annahme. Der Pilot bleibt für Vergleichbarkeit im bestehenden Vertrag. Dispatchabstände und Portnutzungen werden mitexportiert. Ein Erfolg belegt zunächst einen Vorteil innerhalb dieses Modells; eine reale gemeinsame Einfahrt muss vor einer entsprechenden physikalischen Aussage gesondert abgesichert werden. Keine stillschweigende Portänderung und keine Übernahme alter Bounds nach einer Geometrieänderung.

## 4. Daten und öffentliche Architektur

Neues, getrenntes Paket unter `optimization/ddd/reservoir_assignment/`:

| Geplante Datei / Typ | Verantwortung |
|---|---|
| `preparation.py` / `PreparedReservoirAssignment` | Unveränderliche solverfreie Indizes, sichere Bounds, Ressourcenkoeffizienten |
| `models.py` / `ReservoirServiceAssignment` | Verwendete logische Kabinen, aktive Besuche, konkrete Route je Besuch, kanonische Mengen; kein Fahrplanzertifikat |
| `config.py` / `ReservoirAssignmentConfig` | Bedienungsziel, Lastprofil, Zeitbudgets, Seed, Flottenobergrenze |
| `master.py` / `ReservoirAssignmentOptimizer` | Ein Gurobi-Modell und ein nativer Optimize-Aufruf |
| `timing.py` / `ReservoirAssignmentTimingSolver` | Ein CP-SAT-Machbarkeitsmodell mit fixierten Aufträgen |
| `validation.py` | Statische Auftragsprüfung und Abgleich zwischen Auftrag und exportiertem Plan |
| `result.py` | Getrennte Referenz-, Master-, Timing- und Validierungsergebnisse |

Gemeinsame Vorbereitung und dünne Adapter verwenden; keine Kopie des vollständigen Reservoirsolvers.

### Vorhandene Schnittstellen wiederverwenden

- `reservoir_cp_sat_problem.py`: Lebenszyklus, `visit_states`, kanonische Kandidaten und physikalischer Fingerprint.
- `cp_formulation.py`: `PreparedCpStructure`, `prepare_cp_structure`, Boarding-/Alighting-/Onboard-Indizes und sichere Zeitgrenzen. Die Vorbereitung wird auch bei ansonsten unveränderter CP-Formulierung explizit aufgerufen.
- `reservoir_cp_sat_movement.py`: `build_reservoir_cp_movement`, Zeitgleichungen und native Ressourcenintervalle.
- `reservoir_cp_sat.py`: `build_reservoir_cp_sat`, bestehende Extraktion und Hilfsfunktionen nach kleiner gezielter API-Aufteilung.
- `reservoir_cp_sat_certificate.py`: `DddReservoirCpPlan`, Checkpoint-I/O, `validate_reservoir_cp_plan`.
- `reservoir_capacity/bound.py`: Vergleichsidentität und Import bereits abgesicherter All-Stop-Bounds, keine neue Boundkampagne.
- `benchmarking/native_solvers.py`: bestehende Prozessüberwachung nach Prüfung ihrer Deadline-/RSS-Semantik.

Neuer Runner: `benchmarks/run_reservoir_assignment_timing.py` mit `--stage master|timing|pipeline`, `--reference-checkpoint`, `--assignment-input`, `--additional-served`, `--assignment-profile balanced|total_work`, `--fleet-cap`, `--master-seconds`, `--timing-seconds`, `--threads`, `--seed`, `--memory-gib`, `--output`, `--build-only`.

Ein separater Kampagnenrunner enthält ausschließlich die vorab festgelegte Versuchsliste. `pipeline` ruft jede Engine höchstens einmal auf. Fehlender Master-Incumbent überspringt das Timing mit dokumentiertem Grund.

Domänen- und Checkpointformate bleiben bestehen. Ein zusätzlicher Modell-Fingerprint enthält Zielbedienung, Profil, Vorbereitung, Zuordnung, Symmetrieoptionen und Quellenhash. Ein Auftrag erhält ein eigenes Schema und darf nicht als bereits gültiger Checkpoint gespeichert werden.

## 5. Stufe 1: lastbewusste ganzzahlige Zuordnung

### 5.1 Kein sofortiges Vollbedienungsziel

Seien `D` die Nachfrage und `S_ref` die unabhängig bestätigte Bedienung der eingefrorenen Referenz. Zunächst wird exakt

\[
S_{target}=\min(D,S_{ref}+\Delta),\qquad \Delta\in\{10,25\}
\]

zugeordnet. Wenn `S_ref = D`, ist diese Instanz für den Verbesserungstest ungeeignet und wird ausgelassen.

Das Modell darf selbst entscheiden, welche Personen bzw. Mengen es innerhalb der ursprünglichen Gruppen bedient. Die Referenzzuordnung muss nicht als Teilmenge erhalten bleiben. Keine separate Mindestbedienung je OD ohne ausdrückliche neue Fragestellung.

Die begrenzte Mehrbedienung ist eine Machbarkeitsfrage: Wir vermeiden zunächst einen maximal beladenen Auftragssatz für alle 3.074 Personen, der das Timing unnötig überfordert. Das Masterziel ist daher Arbeitslast bei vorgegebener Bedienung, kein globales Kapazitätsoptimum.

### 5.2 Variablen und statische Bedingungen

Für Kabine `k`, Besuch `i`, Route `o` und kanonischen Ride `r`:

- `y_k` binär: Einsatz verwendet.
- `a_ki` binär: Besuch aktiv; gültiges Präfix, Beendigung ausschließlich am Port.
- `x_kio` binär: genau eine zulässige Route je aktivem Besuch.
- `q_r` ganzzahlig zwischen null und `min(Q, D_g)`.
- `z_r` binär und äquivalent zu `q_r > 0`, für bedingte zeitliche Anforderungen.
- `u_g` ganzzahlig: nicht zugeordnete Nachfrage.

\[
\sum_o x_{kio}=a_{ki},\quad
\sum_{r:g(r)=g}q_r+u_g=D_g,\quad
\sum_r q_r=S_{target},\quad
\sum_k y_k\le K_{cap}\le50.
\]

Positive `q_r` benötigen aktive STOPs am exakten Einstiegs- und Zielbesuch. Für jeden Abschnitt gilt

\[
\sum_{r:k(r)=k,\ b_r\le i<d_r}q_r\le Q a_{ki}.
\]

Zusätzlich die gültigen aggregierten Ein-/Ausstiegskopplungen an STOP. Ein- und Aussteiger am selben Besuch werden nicht zu einer falschen gemeinsamen Kapazitätssumme addiert.

Auch leere STOPs bleiben zulässig: Sie können einen legalen Warteort bereitstellen. `STOP` wird deshalb nicht durch eine Äquivalenz mit positiver Passagiermenge definiert. Die Lastbewertung darf unnötige STOPs unattraktiver machen, sie aber nicht grundsätzlich verbieten.

Verwendete Kabinen können auf ein Labelpräfix normalisiert werden. Die Flotte wird nicht als sekundäres Ziel minimiert und nicht auf 38 fixiert, außer im ausdrücklich bezeichneten Kontrollversuch.

### 5.3 Einzelkabinen zeitlich plausibel halten

Eine reine Summenlast ohne Freigaben würde beliebig schlechte Aufträge zulassen. Deshalb enthält der Master zusätzlich einen **ressourcenentkoppelten Zeitpfad je Kabine**:

- Integer-Ereigniszeiten `tau_ki`, Dispatch- und Waiting-Schrittzahlen.
- Exakte Routendauern und lückenlose Folgezeitgleichungen.
- Waiting ausschließlich bei STOP und nach der ursprünglichen Freigabephase.
- Exakte Dispatch-, Service- und Rückkehrgrenzen einschließlich Endknoten.
- Für `q_r > 0`: Nachfragefreigabe vor tatsächlichem Einstieg und rechtzeitige Zielankunft; Einstieg liegt nicht nach Ankunft.

Alle Bedingungen sind linear bzw. mit binären Indikatoren formulierbar. Routeabhängiges Waiting wird mit getrennten beschränkten Variablen je Route und Auswahlkopplungen linearisiert; keine allgemeinen Produkte zweier freier Integer-Variablen.

Diese individuellen Zeiten müssen **noch nicht zueinander konfliktfrei** sein. Der Master erhält keine paarweisen Kabinenkonflikte, keine NoOverlap-Zerlegung und keine globale Reihenfolgenmatrix. Das ist die beabsichtigte Entkopplung. Die Vorbereitung verwendet keine diskreten Suchanker und entfernt nur sicher unmögliche Kandidaten.

Die Zeitvariablen dürfen beim nachfolgenden Timing vollständig geändert werden. Sie sind lediglich nachvollziehbare Einzelkabinen-Zeugen und optionale Startwerte. Auch Konflikte zwischen wiederholten Nutzungen derselben Kabine müssen spätestens die originale CP-Physik prüfen; die Masterprüfung ersetzt diese nicht.

### 5.4 Lastbewertung

Für eine Ressourcennutzung ergibt sich die geschützte Dauer aus dem Originalvertrag:

\[
d_u(w)=l_u-f_u+h_u+(\beta_u-\alpha_u)w.
\]

Damit zählt Exit-Waiting beim belegten Plattformausgang als zusätzliche Arbeit; ein zeitlich verschobener Merge mit gleicher Ein-/Austrittsverschiebung erhält keine zusätzliche Dauer. Keine pauschale Zusatzwartezeit auf jeder Ressource.

`L_j` summiert diese Dauern der ausgewählten Nutzungen auf Ressource `j`, berechnet mit den individuellen Masterzeiten/-waitings. Ressourcen werden getrennt bewertet. Dass dieselbe Kabine mehrere Ressourcen belegt, ist keine mehrfache Passagierbedienung.

Profil `balanced` minimiert mit Gurobis nativer hierarchischer Zielfunktion:

1. maximale normierte Last `rho`, mit `L_j <= rho * T_j`;
2. anschließend die Summe der normierten Lasten.

`T_j` ist im ersten Profil ein vorab dokumentierter positiver Vergleichszeitraum; standardmäßig die gemeinsame Betriebsdauer. Es wird keine Kapazitätsgrenze `rho <= 1` hinzugefügt. Ganze Schutzintervalle hinter dem Betriebsende dürfen für diese Heuristik mitgezählt werden; diese Definition ist ausdrücklich **kein** globaler Ressourcenbound. Abhängigkeiten der Ressourcenauslastung von den späteren gemeinsamen Waitingzeiten bleiben approximiert.

Kontrollprofil `total_work` minimiert nur die Summe dieser Lasten, bei identischen sonstigen Bedingungen. Damit prüfen wir, ob das gezielte Entlasten des höchsten Engpasses mehr bringt als bloß insgesamt wenig Ressourcenarbeit. Keine nachträgliche Gewichtssuche.

Numerisch ungenügende Integerlösungen werden abgelehnt: Gurobiwerte nur innerhalb festgelegter Exporttoleranz in Integer rekonstruieren, dann alle Einzelkabinen-Zeitgleichungen und statischen Bedingungen exakt nachprüfen. Rundung darf keinen ungültigen Auftrag retten. Einheitliche Mikrosekundenwerte, endliche Big-M-Grenzen bzw. Indikatoren, dokumentierte Toleranzen.

### 5.5 Ergebnis

Export: `assignment.json`, `master_timing_witness.json`, OD-Mengen, Auslastung je Abschnitt, STOP-/SKIP-Zahlen, verwendete Kabinen, Lasten je Ressource und nativer Status.

Bei Zeitlimit genügt ein exakt nachgeprüfter Master-Incumbent. Ohne ihn keine Stufe 2. Ein optimaler Master beweist nur Optimalität seiner Lastapproximation bei festem Bedienungsziel. Sein Zielfunktionsbound ist weder eine globale `unserved`-Schranke noch ein gültiger Fahrplan.

## 6. Stufe 2: exakte gemeinsame Machbarkeit mit CP-SAT

### Fixiert / frei

Fixiert werden Kabinenverwendung, aktive Besuchsfolgen, jede Routenauswahl und sämtliche `q_r` einschließlich der impliziten Nullen. Frei bleiben Dispatch, Waiting, alle Ereigniszeiten sowie Ressourcenreihenfolgen.

Erster Builder: das bestehende Reservoirmodell mit `objective=unserved` bauen und die Auftragsfixierungen ergänzen. Die Zielfunktion ist danach konstant; sie wird für den Machbarkeitssolve entfernt. Keine Reisezeitprodukte, keine zusätzliche Reisezeitsuche. CP-SAT darf nach der ersten unabhängig geprüften Lösung beenden.

Die vollständigen Ressourcenbedingungen, Horizontpräsenzen und Zustandskollisionen bleiben bestehen. Es werden keine ursprünglichen NoOverlap-Bedingungen gegen eine approximierte Reservierungsprüfung ausgetauscht.

### Zwei notwendige API-Anpassungen

**A. Auftrag ist noch kein Referenzfahrplan.** `ReservoirDiagnostic.apply` verlangt heute `validate_reservoir_cp_plan(reference)`. Der bestehende Optimizer führt außerdem den Referenzwert als Rückfalllösung und setzt Hints. Dieser Diagnosepfad darf nicht mit einem erfundenen, konfliktbehafteten Plan aufgerufen werden. Der neue Timingadapter verwendet den gemeinsamen Builder, eine eigene statische Auftragsfixierung und einen expliziten nullable nativen Lösungsausgang. Bestehende Diagnose- und Legacy-APIs bleiben funktionsfähig.

**B. Dispatchsymmetrie nach Fixierung der Aufträge.** Der Bewegungsbuilder erzwingt heute `t[k,0] >= t[k-1,0]` für verwendete Kabinen. Bei austauschbaren freien Aufträgen ist das Labelsymmetrie; bei bereits verschiedenen fixierten Aufträgen kann es zulässige Dispatchreihenfolgen ausschließen.

Daher eine gezielte Builderoption `dispatch_order_symmetry=True` mit unverändertem Legacy-Standard ergänzen. Der neue Timingadapter verwendet `False`; das Präfix verwendeter Kabinen kann nach Labelnormalisierung erhalten bleiben. Keine nachträgliche Entfernung von Proto-Constraints. Das Mastermodell legt ebenfalls keine Dispatchreihenfolge nach Label fest.

Nach erfolgreichem Timing werden Kabinen bei Bedarf nach tatsächlichem Dispatch kanonisch umbenannt, **einschließlich aller Ride-IDs und Auftragsreferenzen**. Das Mapping wird gespeichert. Dadurch sind Checkpoints mit den bestehenden hintbasierten Runnern kompatibel. Replays prüfen die Zuordnung vor bzw. nach dokumentiertem Mapping.

### Startinformation

- Individuelle Masterzeiten dürfen als ausdrücklich möglicherweise gemeinsam unzulässige Hints dienen. `fix_variables_to_their_hinted_value` bleibt aus.
- Alle Hints werden auf die fixierten Aufträge abgestimmt und dedupliziert.
- Historische Zeiten werden nur übernommen, wenn sie zur jeweiligen Auftragsstruktur passen; kein vollständiger inkompatibler All-Stop-Hint.
- Die historische Referenz bleibt separat verfügbar. Sie darf nie als native Lösung eines anderen fixierten Auftragssatzes ausgegeben werden.

`FEASIBLE` plus unabhängige Validierung bestätigt die vorgegebene Bedienung. `INFEASIBLE` widerlegt nur den konkreten Auftragssatz. `UNKNOWN`, Timeout oder Speicherabbruch bedeutet ungeklärt. Da die Mengen fest sind, ist ein `OPTIMAL` dieses Machbarkeitsmodells kein globales Kapazitätsoptimum.

Anschließend kann eine getrennte, budgetierte ganzzahlige Passagieroptimierung auf der gefundenen festen Bewegung zusätzliche Bedienung messen. Ihre Verbesserung wird getrennt ausgewiesen; primäre Pilotwertung bleibt die exakt realisierte Masterzuordnung. Dieser Zusatz wird im ersten Vergleich nicht benötigt.

## 7. Umsetzungsschritte und Zwischentests

### Schritt A — Vorbereitung, Auftragsschema und Referenz-Replay

1. Gemeinsame Indizes und Ressourcenkoeffizienten vorbereiten.
2. Auftrag aus einem geprüften historischen Plan extrahieren; kein Verlust positiver Rides.
3. Statische Validatoren, eindeutige Serialisierung, Modellidentitäten implementieren.
4. R0/R2-Referenzen sowie kleine Fälle vollständig fixiert reproduzieren.

**Gate:** identische Beförderungsmengen, unveränderte Originalprüfung und nachvollziehbare IDs. Kein neuer großer Solverlauf bei Fehlern.

### Schritt B — Timingadapter ohne gültigen Seed

1. Legacy-kompatible Symmetrieoption hinzufügen.
2. Auftragsfixierung ohne erfundenes Fahrplanzertifikat implementieren.
3. Native Status-/Exportbehandlung einschließlich fehlender Lösung.
4. Historische Aufträge zunächst ohne Zeitfixierung und danach ohne Zeithints takten.

**Gate:** mindestens ein kleiner nichttrivialer Waiting-Auftrag ohne gültigen gemeinsamen Zeithint selbständig gelöst. Historische Replays sind Korrektheitskontrollen, kein neuer Kapazitätserfolg. Ihre Laufzeit wird gemessen; die alten 9–13 Sekunden werden nicht vorausgesetzt.

### Schritt C — Master mit Einzelkabinenzeiten

1. Statische Nachfrage-, Kapazitäts- und Lebenszyklusbedingungen.
2. Individuelle Zeitpfade mit Integerfreigaben und Waitingvertrag.
3. Lastprofile `balanced` und `total_work`.
4. Exakte Nachprüfung des exportierten Auftrags.

**Gate:** auf kleinen enumerierbaren Fällen dieselben auftragsbezogenen Einzelkabinenmöglichkeiten wie in einer unabhängigen Enumeration ohne gegenseitige Ressourcenbedingungen. Keine Pflicht auf Gleichheit mit dem vollständigen globalen Fahrplanoptimum: Der Master lässt Konflikte absichtlich aus.

### Schritt D — Pipeline und begrenzte Kampagne

Eine Masterlösung einmal an Timing übergeben, native Ergebnisse validieren, getrennte Artefakte speichern. Keine Reparatur nach Timeout, keine automatische Nachgenerierung und keine Verlängerung über das Gesamtbudget.

### Pflichtfälle

- Ein leerer, ein vollständig bedienter und ein nicht bedienbarer Nachfragefall.
- Volle Kabine, Aus-/Einstieg am selben Besuch, Wiederverwendung frei gewordener Plätze.
- Verpflichtende STOP-Endpunkte; leerer STOP als notwendiger Warteort bleibt zulässig.
- Keine künstliche zusätzliche Runde einer Beförderung und kein Umstieg.
- Freigabe während Waiting, unzulässiges Waiting vor Freigabephase, nichttriviale Waiting-Schrittweite.
- Ankunft exakt am Servicehorizont bzw. einen Tick danach; Rückkehr exakt am Betriebshorizont.
- Exit-Waiting verlängert nur die richtigen Ressourcenintervalle; Schutz hinter dem Horizont.
- Ein Master-Auftrag mit individuellen Zeitzeugen, aber gemeinsam unmöglichem Timing: korrekt `INFEASIBLE`, keine Referenzübernahme.
- Ein gemeinsam gültiger Auftrag, dessen nötige Dispatchreihenfolge nicht der Labelreihenfolge entspricht; Roundtrip nach Kabinenumbenennung.
- Bypass-Überholen und gekoppelte Ressourcen.
- Positive unbekannte/geprunte Ride-ID, falsche Mengen, falscher Fingerprint: Fehler statt stiller Korrektur.
- Grenzwerte über 32 Bit, numerische Exporttoleranzen und exakte Integernachprüfung.
- Timeout/Abbruch vor erster Lösung; abweichende Referenzzuordnung nicht als Timinglösung ausgeben.
- Legacy-Defaults und vorhandene Diagnose-/Checkpointtests bleiben unverändert erfolgreich.

## 8. Vorgeschlagene erste Kampagne: maximal 60 Minuten

Dies ist ein Budgetvorschlag für die spätere Umsetzung. Mit dem Schreiben dieses Plans wird kein Lauf gestartet. Implementierung und kleine Korrektheitstests liegen außerhalb der Kampagne.

### Eingefrorene Fälle

Vorhandene Artefakte: `benchmarks/output/reservoir_capacity_campaign_20260911_v1/prepare/`.

| Fall | Nachfrage | Geprüfte All-Stop-Referenz | Ziel +10 / +25 |
|---|---|---|---|
| R0 | ursprüngliche Batch-Nachfrage, D=3.074 | U=285, S=2.789 | S=2.799 / 2.814 |
| R2 | B↔D und C↔E, neun Freigabebuckets, D=3.074 | U=578, S=2.496 | S=2.506 / 2.521 |

Max50, Waiting bis 1.200 Sekunden, Physik und Nachfrageverteilung bleiben unverändert. Die genannten Werte werden beim Einfrieren erneut aus den Zertifikaten geprüft. Abweichungen stoppen die betroffene Instanz; keine stillen Austauschreferenzen. Weitere inzwischen bekannte Pläne können als zusätzliche Referenzen mit eigener Herkunft dokumentiert werden.

### Screening: vier Auftragssätze je Fall, Seed 0

| Variante | Lastprofil | Mehrbedienung | Flottenobergrenze |
|---|---|---:|---:|
| A | balanced | 10 | 50 |
| B | balanced | 25 | 50 |
| C | total_work | 10 | 50 |
| D | balanced | 10 | 38 |

D ist eine ausdrücklich eingeschränkte Kontrollformulierung innerhalb derselben Max50-Physik. Sie prüft, ob die zusätzlichen verfügbaren Kabinen für diesen Ansatz einen Unterschied machen. Mehr genutzte Kabinen allein sind kein Erfolg; mehr Bedienung ist das Kriterium. Es werden keine Modelle mit Mindestflotte 39 erzwungen.

| Abschnitt | Versuche / Budget | Maximum |
|---|---|---:|
| Einfrieren, Referenzprüfung, Abschlussreserve | gemeinsam | 6 min |
| Screening Pipeline | 8 × 180 s: bis 60 s Master, 100 s Timing, 20 s Abschluss | 24 min |
| CP-SAT Legacy, vollständig frei, R0/R2 | 2 × 300 s einschließlich Aufbau/Validierung | 10 min |
| Bestätigung auf R2 | bestes neues Profil und CP-SAT Legacy, Seeds 1 und 2, 4 × 300 s | 20 min |
| **Gesamtmaximum** | | **60 min** |

Bestätigung startet nur, wenn ein neues Profil auf R2 im Screening die geforderte Mehrbedienung unabhängig realisiert. Auswahl nach validierter Bedienung, dann Gesamtzeit bis zum bestätigten Plan. Masterlasten sind kein Auswahlersatz für fehlende Fahrpläne.

Bei bestätigenden Pipelineversuchen gelten bis 60 s Master, 220 s Timing, 20 s Abschluss. Aufbau zählt jeweils zum Stufenbudget; alle Teilbudgets stehen zusätzlich unter der gemeinsamen Deadline. Fehlgeschlagene bzw. ausgelassene Zeitfenster werden nicht für weitere Suchversuche verwendet.

Alle Prozesse sequenziell, zwölf Threads/Worker, höchstens 24 GiB Prozessbaum-RSS auf dem vorhandenen Mac. Native Solverparallelität wird gemessen, nicht vorausgesetzt. Bestehende laufende Solverjobs werden nicht unterbrochen; die Kampagne startet erst ohne konkurrierenden Solverjob. Suspend und Kindprozesse müssen im Gesamtlimit berücksichtigt werden.

Screening ist keine faire Geschwindigkeitsrangliste zwischen 180-s-Pipeline und 300-s-Legacy. Eine Performanceempfehlung verlangt den gleich budgetierten R2-Vergleich in beiden zusätzlichen Seeds. CP-SAT Legacy bekommt die gleiche unabhängig geprüfte Referenz als Hint, die Pipeline darf sie für Zieldefinition und passende Teilhints verwenden. Der neue Auftrag selbst zählt noch nicht als Startlösung. Seeds steuern beide Engines, tatsächliche Quellen/Versionen und Parameter werden gespeichert.

## 9. Messung, Beweisumfang und Abbruchentscheidung

Pro Stufe separat erfassen:

- Vorbereitung, Modellbau, Presolve soweit verfügbar, Suche, Validierung, Gesamtzeit und Peak-RSS.
- Variablen nach Typ, Constraints, MIP-Nichtnullkoeffizienten, Anzahl Visits/Rides/Intervalle vor und nach Presolve soweit verfügbar.
- Master-Erstlösung, Lastverbesserungen und Zielfunktionsbounds als **Lastmodellwerte**.
- Native Timing-Erstlösung, Status, Suchknoten/Konflikte und Zeit bis zur unabhängigen Bestätigung; bei konstanter Zielfunktion keine erfundene Kapazitäts-Gap-Kurve.
- Bedienung je OD/Bucket, Flotte, STOP/SKIP, Dispatch/Rückkehr, Waiting und Ressourcenlasten vor/nach Timing.
- Referenzwert, gewünschte Bedienung, zugeordnete Menge und tatsächlich bestätigte Bedienung als getrennte Felder.
- Quellcodehashes, Engineversionen, Auftrag, optionale Zeithints und validierter Endcheckpoint.

### Fortsetzungsentscheidung

1. **Master findet keinen geeigneten Auftrag:** Engpass ist bereits die Zuordnungs-/Einzelkabinenformulierung; Modellgröße, Presolve und Lastfortschritt dokumentieren.
2. **Master findet Aufträge, Timing meist UNKNOWN:** Die Annahme einer günstigen zeitlichen zweiten Stufe trägt für neue Muster noch nicht. Keine automatische Reparatur-/LNS-Erweiterung.
3. **Timing beweist Aufträge unzulässig:** Die Lastapproximation übersieht wesentliche Kopplungen. Konkrete verletzte Struktur anhand kleiner Gegenfälle untersuchen, keinen globalen Unzulässigkeitsbeweis behaupten.
4. **Ein gültiger Plan übertrifft die Referenz:** Die Aufteilung ist ein brauchbarer Ansatzpunkt für Incumbents, unabhängig davon, ob mehr als 38 Kabinen verwendet werden.
5. **In beiden Bestätigungen mindestens zehn Personen mehr als CP-SAT bei gleichem Budget:** belastbarer kurzfristiger Performancehinweis. Andernfalls nur Referenzverbesserung bzw. unentschieden dokumentieren.

Eine schnellere erste Lösung gleicher Qualität darf als Laufzeitbefund berichtet werden; sie allein rechtfertigt keinen größeren Ausbau. Keine nachträglich gelockerte Erfolgsschwelle und keine weiteren Langläufe aus dem Pilot ableiten, ohne die Befunde zu prüfen.

### Was der Pilot nicht beweist

Er schließt den globalen Skip-Stop-Gap nicht. Selbst perfekt gelöste Master- und Timingstufen machen die einmalige Zerlegung nicht global exakt. Ein gescheiterter Auftrag widerlegt weder die Zielbedienung mit anderen Aufträgen noch Skip-Stop insgesamt.

Für R2 wurde im [Kapazitätspilot](../findings/reservoir_capacity_phase_pilot_20260911.md) unter identischer Domäne `U_AS >= 125` abgesichert. Erst ein gültiger Skip-Stop-Plan mit `U <= 124` übertrifft diesen globalen All-Stop-Bound. Die hier zunächst angestrebten `U=568` bzw. `553` übertreffen nur die konkrete Referenz. Diese Ebenen stehen im Bericht getrennt.

Größere vollständig bedienbare Profilnachfrage erfordert weiterhin verschachtelte Nachfrageinstanzen und `U=0`. Mehr Teilbedienung bei D=3.074 wird nicht als solcher Nachweis bezeichnet.

## 10. Abschlussartefakt

Ein Findings-Markdown enthält die Screening- und Bestätigungstabelle, Zeit bis zu gültigen Plänen, Lastverteilung vor/nach Timing, Modellgrößen, Gegenbeispiele und eine eindeutige Empfehlung: Aufteilung weiterverfolgen, nur als Startplaner nützlich, oder anhand des gemessenen Engpasses beenden.

Die nächste Entscheidung betrifft ausschließlich diesen zweistufigen Pilot. Beförderungspaketbibliotheken, DOPP, eigene Suche und sechs Stationen sind mögliche spätere Arbeiten, keine versteckten Bestandteile dieses Plans.
