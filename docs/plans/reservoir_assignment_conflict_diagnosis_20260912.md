# Reservoir: Zuordnungsfixierung und verwertbare Timing-Konflikte prüfen

Stand: 12.09.2026. Status: implementiert; erste Kampagne abgeschlossen. Die
Ergebnisse stehen in
[`../findings/reservoir_assignment_conflict_diagnosis_20260912.md`](../findings/reservoir_assignment_conflict_diagnosis_20260912.md).

## 1. Entscheidung und Ziel

Vor einem weiteren Modellumbau prüfen wir am bestehenden Assignment-Pilot,
welche fixierten Entscheidungen die gemeinsame Realisierbarkeit verhindern und
ob sich daraus eine nachweislich gültige, wiederverwendbare Einschränkung für
den Master gewinnen lässt. Wir entwickeln in diesem Paket weder eine neue
Column-Generation-Architektur noch einen iterativen Benders-/LNS-Controller.

Zwei Fragen entscheiden über die Fortsetzung:

1. Findet CP-SAT für denselben Einsatzrahmen einen gültigen besseren Plan,
   wenn es die Passagiere neu zuordnen darf?
2. Kann ein nachweislich unzulässiger Auftrag schnell durch einen kleinen,
   unabhängig reproduzierten Konflikt erklärt werden, der weitere Aufträge
   ausschließt und bekannte gültige Lösungen erhält?

Eine neue Planungsschleife ist erst nach diesen Nachweisen begründet. Eine
Unzulässigkeit des einzelnen Auftrags beweist keine globale Kapazitätsgrenze.

## 2. Was bereits existiert und was die Ablation tatsächlich zeigt

- Ganze Trajektorien, Pricing und Root-Column-Generation existieren bereits in
  `trajectory_root_column_generation.py`. Die alten Reservoirregeln sind nicht
  identisch mit dem aktuellen Single-Use-Vertrag mit Rückkehr.
- Musterwahl mit anschließendem CP-Timing wurde getestet und litt unter vielen
  ungeklärten Unterproblemen.
- `zero_wait_passenger_master_timing_cuts.md` plant bereits Timing-Cuts;
  Passenger-Benders wurde für eine andere Zerlegung getestet.
- Der aktuelle `reservoir_assignment/master.py` erzeugt individuell gültige
  Kabineneinsätze und Ressourcenlasten, ohne alle Konflikte zwischen Kabinen.
- `reservoir_assignment/timing.py` fixiert derzeit sämtliche Aktivitätswerte
  und sämtliche Ride-Mengen, auch null. Optional fixiert es zusätzlich Routen.

Die jüngste Kontrolle reproduziert den gültigen R2-Auftrag für S=2.496 ohne
Zeit-Hints in 2,84 s bei freien Zeiten und Waiting, aber fixierten Routen.
Feste Ressourcenreihenfolgen benötigten 4,30 s, festes Referenz-Waiting 0,64 s.
Die Referenz hat kein positives Waiting. Alle drei Fälle sind reine
Machbarkeitsprobleme; `OPTIMAL` ist kein Kapazitätsoptimalitätsbeweis.

Der S=2.506-Auftrag verwendet dagegen 40 Kabinen, andere Routen und eine andere
Zuordnung. Seine Langläufe mit freien Nebenrouten endeten nach je rund 6.799 s
mit UNKNOWN. Daraus folgt weder, dass Waiting generell leicht ist, noch dass
die Reihenfolgensuche allein den Unterschied verursacht. Die gemeldeten
520.629 Booleschen Variablen sind Solverstatistik, keine Zählung von ebenso
vielen ursprünglichen Routenentscheidungen.

Historische INFEASIBLE-Meldungen werden erst nach Prüfung von Assignment-Hash,
Quellstand und Fixierungen demselben Auftrag zugeordnet.

## 3. Schritt 1: Fälle einfrieren und Diagnosevertrag sichern

Eingaben:

- Referenz: `benchmarks/output/reservoir_capacity_campaign_20260911_v1/prepare/R2_ss.json`.
- Schwieriger Auftrag:
  `benchmarks/output/reservoir_assignment_timing_overnight_20260912_v1/free_routes_no_hints_seed1/assignment.json`.
- Kontrollen:
  `benchmarks/output/reservoir_assignment_timing_reference_ablation_20260912_v1/`.

Erneut prüfen: gleiche physikalische Domäne, D=3.074, Max50, Waiting bis
1.200 Sekunden, Integer-Mikrosekunden und aktuelle Rückkehrbedingungen.
Referenz muss S=2.496/U=578 reproduzieren, Auftrag exakt S=2.506 ausweisen.
Individuelle Witness-Zeiten eines Auftrags sind kein gemeinsam gültiger Seed.

Speichern: Eingabehashes, tatsächliche Fixierungen, Engineversion, Quellenhashes,
Startparameter und zeitliche Herkunft jedes Resultats. Alte Ergebnisse bleiben
unverändert. Kein Austausch eines problematischen Auftrags gegen einen neuen.

Zwischenergebnis: überprüfbare Vergleichsidentität und eine Tabelle der
Unterschiede bei Einsätzen, Routen, positiven Ride-Mengen und Waiting.

## 4. Schritt 2: Passagierfixierung kontrolliert lösen

Bestehenden Timing-Builder wiederverwenden und seine Fixierungen über eine
unveränderliche Diagnosekonfiguration getrennt steuern:

- `exact`: jede kanonische Ride-Menge gleich Auftrag, einschließlich null;
- `commitments`: positive Ride-Mengen mindestens wie im Auftrag, übrige frei;
- `reassign`: alle Ride-Mengen frei, Gesamtbedienung mindestens Zielwert.

Alle Varianten behalten die vollständige ganzzahlige Passagiermodellierung,
Nachfragebilanzen und ursprünglichen Bewegungsbedingungen. Bei `commitments`
und `reassign` darf das Ergebnis mehr als das Ziel bedienen. Die heutige
Extraktionsprüfung auf exakte Gleichheit wird nur für `exact` angewendet.
Die unabhängigen physikalischen und Passagierprüfer bleiben maßgeblich.

Fixierte Aktivitätspräfixe/Einsatzlängen bleiben in dieser Diagnose ausdrücklich
bestehen. Das ist eine Einschränkung auf den Auftrag, keine globale Suche nach
der besten Flottengröße. Routenfreiheit erlaubt die vorhandenen STOP/SKIP-
Alternativen; vorgeschriebene Ein-/Ausstiege erzwingen weiterhin STOP.

Fünf sequenzielle Versuche, jeweils höchstens 120 s einschließlich Aufbau und
Validierung, zwölf Worker, Seed 0, ohne Witness-Hints:

| Test | Ausgangsauftrag | Routen | Passagiere | Aussage |
|---|---|---|---|---|
| T0 | Referenz S=2.496 | frei | exact | Kontrolliert zusätzlich die Routenfreiheit der Nachtläufe |
| T1 | schwieriger S=2.506 | fixiert | exact | Prüft Unzulässigkeit mit aktuellem Code und identischem Hash |
| T2 | schwieriger S=2.506 | frei | commitments | Prüft den Einfluss fixierter Nullen/exakter Mengen |
| T3 | schwieriger S=2.506 | fixiert | reassign | Prüft die konkrete Zuordnung bei gleichem Routenprogramm |
| T4 | schwieriger S=2.506 | frei | reassign | Prüft Routen und Zuordnung gemeinsam im gleichen Einsatzrahmen |

Der alte Langlauf mit freien Routen und exakten Mengen ist die vorhandene
Referenz; er wird nicht nochmals stundenlang wiederholt. UNKNOWN bleibt
ungeklärt. Ein FEASIBLE-Ergebnis wird unmittelbar exportiert und validiert.

Zwischenergebnis: klare Unterscheidung zwischen einem schlechten konkreten
Passagierauftrag, einem ungeeigneten Routenprogramm und weiterhin ungeklärtem
gemeinsamem Timing. Die Tests isolieren nicht jeden möglichen Wechselwirkungseffekt.

## 5. Schritt 3: Einen echten Konflikt extrahieren

Nur aus einem aktuell reproduzierten INFEASIBLE-Fall wird ein Konfliktnachweis
abgeleitet. Ein Timeout oder eine Kollision der Witness-Zeiten genügt nicht.

### Annahmen statt versteckter Fixierungen

Alle auftragsspezifischen Entscheidungen erhalten stabile Annahme-IDs:

- Aktivitätspräfix und Einsatzende je Kabine;
- gewählte Routen je Besuch, soweit fixiert;
- Ride-Gleichheiten oder Mindestmengen nach Diagnosemodus;
- gegebenenfalls Bedienungsziel;
- zusätzliche Waiting-/Reihenfolgefixierungen ausschließlich als eigene
  Diagnoseannahmen, niemals als ungenannte Grundbedingungen.

Der Hintergrund enthält nur die ursprüngliche Physik und Passagierdomäne.
Insbesondere dürfen vorab hart fixierte Einsatzlängen später nicht aus dem
Gültigkeitsbereich eines Cuts verschwinden. Annahmen reifizieren lediglich
unterstützte lineare/Boolesche Bindungen; globale NoOverlap-Constraints bleiben
im physikalischen Hintergrund.

Die installierte CP-SAT-API liefert einen hinreichenden Unzulässigkeitskern.
Für Kernextraktion wird ein separater Machbarkeitslauf mit einem Worker und
ohne Optimierungsziel verwendet; Unterstützung und Statussemantik werden auf
kleinen Fällen geprüft. Ein Kern ist nicht automatisch minimal.

Zunächst gröbere Gruppen verwenden, bei Bedarf nur den betroffenen Kern
verfeinern. Jeder Kern wird in einem frisch gebauten Modell allein mit den
genannten Annahmen nochmals als unzulässig bestätigt. Begrenzte Löschtests
können ihn verkleinern; UNKNOWN bei einem Löschtest erlaubt keine Entfernung.

### Gültigkeit und Nutzen getrennt bewerten

Für einen bestätigten Kern K gilt unter seinem dokumentierten Hintergrund:

    mindestens eine Entscheidung aus K muss sich ändern.

Bei Booleschen Masterentscheidungen ist dies `sum(literal_i) <= |K|-1`.
Für Integer-Gleichheiten müssen die zugehörigen Wahrheitsindikatoren exakt
reifiziert oder die entsprechende Disjunktion korrekt modelliert werden.
Ein gefundener Gleichheitskern darf nicht unbegründet zu einem Schwellen-Cut
verschärft werden.

Ein Cut mit fixiertem Waiting ist nur mit diesen Waiting-Bedingungen gültig.
Ein Cut unter einem Ziel S>=2.506 ist gegebenenfalls zielabhängig. Ein großer
Kern, der praktisch den ganzen Auftrag nennt, ist ein korrekter No-Good, aber
noch kein nützlicher Benders-Fortschritt.

Optional wird genau ein Konflikt als Ressourcen-/Zeitfensterüberlastung
erklärt: sicher erforderliche Belegung übersteigt verfügbare Zeit. Dabei dürfen
variable Ressourceneintritte, alternative Routen, Schutzzeiten und legale
Überholungen nicht durch Witness-Annahmen ersetzt werden. Ohne vollständigen
Nachweis bleibt es eine Diagnose, kein global gültiger Cut.

Zwischenergebnis: maschinenlesbarer Kern mit Herkunft und Gültigkeitsbereich,
frischer Reproduktion und verständlicher Erklärung oder dokumentiertes Scheitern.

## 6. Schritt 4: Übertragbarkeit einmalig prüfen

Nur bei bestätigtem Kern:

1. Cut in den bestehenden Gurobi-Master übersetzen; alte Masterpunkte müssen
   ihn tatsächlich verletzen, bekannte gültige Zertifikate müssen ihn erfüllen.
2. Auf kleinen vollständig prüfbaren Instanzen nachweisen, dass alle gültigen
   Lösungen erhalten bleiben. Zusätzliche Aufträge mit anderem irrelevanten
   Detail prüfen, um einen bloßen Vollauftragsausschluss zu erkennen.
3. Genau einen Masterlauf mit eingefrorenem Ziel S=2.506 und diesem Cut ausführen.
4. Den neuen Auftrag genau einmal im vollständigen Timing-Modell prüfen. Routen
   und Passagierfixierungen ausdrücklich dokumentieren; keine stillen Änderungen.

Das ist ein begrenzter Transfernachweis, keine automatische Cut-Schleife.
Eine bloße Masterverbesserung oder ein zweiter ungeklärter Auftrag gilt nicht
als Kapazitätsfortschritt. Gibt es keinen brauchbaren Kern, entfällt dieser Schritt.

## 7. Integration, Tests und Messung

Betroffene Pfade:

- `reservoir_assignment/timing.py`: Fixierungsmodi, getrennter Modellbau und
  Solve, statusabhängige Extraktionsprüfungen; Legacy-Defaults erhalten.
- Neues `reservoir_assignment/conflicts.py`: Annahmeregister, Kernexport,
  Reproduktion und geprüfter Master-Cut-Adapter.
- `reservoir_assignment/master.py`: optionale, explizit übergebene geprüfte Cuts.
- `benchmarks/run_reservoir_assignment_timing.py`: Diagnoseoptionen; unpassende
  Stage-/Flag-Kombinationen ablehnen statt ignorieren.
- Eigener begrenzter Diagnoserunner und neue Ergebnisordner.

Kleine Korrektheitstests vor der Kampagne:

- exact reproduziert bisherige Zertifikate; positive und null Ride-Mengen;
- commitments/reassign sind echte Erweiterungen und bleiben ganzzahlig;
- absichtlich falsche Zuordnung bei möglicher alternativer Zuordnung;
- Hintergrund ohne Auftrag ist erfüllbar; Kernreplay und falsche Kernzuordnung;
- bedingte Cuts behalten Einsatzlängen, Ziel und Waiting-Bedingungen;
- Konflikt durch fixe Reihenfolge verschwindet bei erlaubtem Überholen;
- kein Cut aus UNKNOWN, MODEL_INVALID, Abbruch oder bloßer Witness-Kollision;
- bestehende Release-, Horizon-, Waiting- und Rückkehrtests bleiben gültig.

Erfassen: Vorbereitung, Aufbau, Presolve soweit verfügbar, Solve, Validierung,
Gesamtzeit, Prozessbaum-RSS, Modell- und Suchstatistiken, Fixierungsanzahlen,
Kernumfang vor/nach Verkleinerung, Cut-Gültigkeitsbereich sowie native gültige
Bedienung. Keine Kapazitäts-Gaps aus dem zielkonstanten Timing-Solve ableiten.

## 8. Budget und Abbruch

Implementierung und kleine Korrektheitstests liegen außerhalb der Kampagne.
Erste Diagnosekampagne: höchstens 40 Minuten tatsächliche Wandzeit.

| Abschnitt | Gesamtmaximum |
|---|---:|
| Einfrieren, Referenz-/Hashprüfung | 4 min |
| T0 bis T4, fünfmal 120 s | 10 min |
| Kernextraktion, begrenzte Verkleinerung und Reproduktion | 10 min |
| Bedingter Transfer: ein Master- und ein Timinglauf | 10 min |
| Auswertung und Reserve | 6 min |

Transferbudget: höchstens 180 s Master und 420 s Timing, jeweils einschließlich
Aufbau/Abschluss. Gemeinsame Deadline hat Vorrang. Maximal 24 GiB Prozessbaum-RSS,
zwölf Worker/Threads für normale Läufe, ein Worker für Annahmekerne. Tatsächliche
Konfiguration speichern. Alle Solver laufen sequenziell ohne Konkurrenzjobs.
Fehlende Ergebnisse werden als ausstehend ausgewiesen. Ungenutzte Budgets
finanzieren keine zusätzlichen Langläufe. Deadline berücksichtigt Suspend.

## 9. Entscheidung danach

- **Freie Zuordnung realisiert S>=2.506:** Zuerst diesen vorhandenen CP-Pfad als
  bedingten Planer weiterverfolgen. Kein neuer Column-Master allein deshalb.
- **Kleiner gültiger Konflikt plus realisierbarer neuer Masterauftrag:** Ein
  gezielter LBBD-Pilot ist begründet; seine Schleife braucht einen eigenen Plan.
- **Nur vollständige No-Goods oder überwiegend UNKNOWN:** Diesen Ausbau stoppen.
  Kein weiterer Architekturwechsel ohne einen konkreten zusätzlichen Nachweis.
- **Unerwarteter Ausschluss gültiger Pläne:** Korrektheitsfehler zuerst beheben;
  Performanceinterpretation des betroffenen Pfads aussetzen.

S>=2.506 übertrifft nur den bekannten Referenzfahrplan S=2.496. Der dokumentierte
globale All-Stop-Bound U_AS>=125 ist eine andere Schwelle: erst ein gültiger
Skip-Stop-Plan mit U<=124 würde ihn übertreffen, nach erneuter Domänenprüfung.
Eine größere vollständig bedienbare Profilnachfrage verlangt weiterhin
verschachtelte Nachfrageinstanzen und U=0.

Abschluss: ein Findings-Dokument mit Testtabelle, bestätigtem Konflikt oder
konkretem Ausschlussgrund und genau einer daraus abgeleiteten Fortsetzungsentscheidung.
