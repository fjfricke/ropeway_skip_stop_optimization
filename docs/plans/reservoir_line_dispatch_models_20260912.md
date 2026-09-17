# Reservoir-Linienmodell: Varianten und Umsetzung über Dispatchabstände

Stand: 12.09.2026. **Planungsstand; keine Implementierung oder Kampagne durch dieses Dokument gestartet.**

**Vertragsrevision vom 13.09.2026:** Die Rundenzahl ist keine freie
Entscheidung mehr. Alle eingesetzten Kabinen verlassen das Reservoir bis zum
Beginn der Personenbedienung und fahren ihr gewähltes Haltemuster danach
durchgehend. Die Rückkehr erfolgt an der ersten Mustergrenze am oder nach der
Bedienungsdeadline. Eine interne Aufteilung nach Rundenzahl darf nur noch die
Dispatchdomain partitionieren; sie darf keine frühe Herausnahme ermöglichen.

## 1. Ziel und Entscheidung

Wir wollen nachfragegeeignete, physikalisch gültige Skip-Stop-Fahrpläne für eine
optionale Flotte finden. Die Suche wählt Linien und Dispatchzeiten gemeinsam,
damit sie nicht nacheinander viele vollständig vorgegebene, schwer fahrbare
Patternkombinationen prüfen muss.

Die erste Umsetzung ist **V1: kompakte No-Wait-Linienwahl mit vorberechneten
erlaubten Dispatchabständen**. V2 liefert zunächst eine kleine unabhängige
Modellreferenz und später den möglichen Waiting-Kern. V3 bleibt dokumentierte
Alternative; kein gleichzeitiger großer Arc-Flow-Umbau.

**Festgelegter Hauptpfad:** Reine Machbarkeit ist der vorgeschaltete Gate-Test.
Die anschließende Optimierung verwendet `exact_service`: Linienwahl, Dispatch
und tatsächlich zeitlich mögliche ganzzahlige Beförderungen werden gemeinsam
optimiert. `optimistic_service` bleibt eine ausdrücklich getrennte Ablation
und Boundquelle, nicht das alleinige Ziel der Hauptsuche. Die nachgelagerte
Passagieroptimierung prüft und verbessert bereits gültige Zuordnungen.

Erfolg wird an unabhängig gültiger Passagierbedienung gemessen. Eine kleinere
Darstellung, hohe optimistische Bewertung oder ein schnelles leeres Ergebnis
sind allein kein Erfolg. Ein globales Skip-Stop-Optimum wird nicht vorausgesetzt.

Alle Kapazitätsergebnisse werden verbindlich nach
[`all_stop_no_wait_capacity_baseline.md`](../reference/all_stop_no_wait_capacity_baseline.md)
gegen das phasenoptimierte, vollständig gefüllte All-Stop-No-Wait-System mit
exakter freier Passagierzuweisung verglichen. Ein historischer Fahrplan mit
fester Phase ist nur ein Zwischenwert. Ein zusätzlicher globaler Bound für
eine größere All-Stop-Domäne wird separat ausgewiesen und ersetzt diese
betriebliche Referenz nicht.

## 2. Gemeinsamer Betriebsvertrag

- Bestehender gerichteter Fünf-Stationen-Ring, unveränderte Geometrie,
  Ressourcen und Sicherheitsabstände.
- Maximal 50 identische Kabinen; Single-Use-Reservoir, keine Wiedereinsätze.
- Eingesetzte Kabinen bilden ein Präfix. Für K > 0:
  `0 <= d[0] < d[1] < ... < d[K-1] <= T`.
- T ist Beginn der Personenbedienung und eine **vorab festgelegte
  Instanzgröße**, für All-Stop und Skip-Stop identisch. Es ist weder
  Solvervariable noch von der gewählten ersten Linie oder deren Waiting
  abhängig. Vor T dürfen keine modellierten Passagiere einsteigen.
- Kein erfundener numerischer T-Standard: Der Runner verlangt T explizit.
  Als dokumentierte Referenz für die Wahl kann eine vorab berechnete
  No-Wait-Umlaufdauer dienen. Der konkrete Wert wird vor einem Vergleich
  eingefroren.
- Die strikte Dispatchreihenfolge entspricht mindestens einem zulässigen Tick;
  zusätzliche physikalische Headways folgen ausschließlich aus der Domäne.
  Sie gilt nicht als globale physische Reihenfolge an allen Stationen.
- Nachfragefreigaben bleiben auf der bestehenden absoluten Zeitachse. Der freie
  erste Dispatch `d[0]` bestimmt deshalb die Phase des Kabinenstroms am
  Servicebeginn. Er ist keine Symmetrievariable, die auf null fixiert werden
  dürfte.
- Zunächst No-Wait. Die spätere Waiting-Stufe verwendet den vollständigen
  bisherigen Waitingvertrag einschließlich Freigabephase und Schrittweite.
- Jede eingesetzte Kabine fährt ab ihrem Dispatch ohne Unterbrechung durch alle
  Runden, die vor der Bedienungsdeadline beginnen. Rechtzeitige Rückkehr und
  letzter Zustandsknoten bleiben enthalten.
  Ressourcenbetritt genau am Horizont zählt; Schutzzeiten werden nicht gekappt.
- Ganzzahlige direkte Passagiere, keine zusätzlichen Runden oder Umstiege.
  Ausstieg am Ziel vor dessen Exit-Waiting, Einstieg am tatsächlichen
  Plattformausstieg des Ursprungs.
- Ziel der Hauptsuche: `unserved`, intern Maximierung tatsächlich bedienter
  Personen mit vollständiger Kopplung an die gewählten Ereigniszeiten.
  Reisezeit bleibt Kontrollkennzahl.

**Einschränkung:** Die kompakte Startphase und der Linienkatalog sind neue
Such-/Betriebsrestriktionen. Keine Übernahme historischer Bounds oder Werte
ohne Prüfung ihrer Domänen und ihres Gültigkeitsbereichs. Eine erste Abfahrt
bei null ist bei absoluten Nachfragefreigaben keine kostenlose Symmetrie.

K=0 bleibt zur vollständigen Modellierung optionaler Flotten darstellbar.
Diagnosefälle mit vorgegebenem K erzwingen dagegen genau diese Einsätze.
Ein leerer Plan erfüllt keinen positiven Machbarkeitsgate.

## 3. Linienkatalog statt freier Besuchsentscheidungen

Ein unveränderliches Haltemuster beschreibt die wiederholte Bewegung:

- stabile Linien-ID und zugrunde liegendes Haltemuster;
- Start am bestehenden Reservoirport;
- konkrete Route je Besuch und Besuchszustände einer Runde;
- No-Wait-Zeitversätze aller Ereignisse;
- Plattform-Ein-/Ausstiegsversätze;
- geschützte Ressourcennutzungen und Zustandsbelegungen;
- kanonisch zulässige direkte Beförderungsabschnitte;
- Nachweise für interne Unzulässigkeit.

Die vollständige Einsatzdauer folgt aus Muster und Dispatch. Intern darf die
Implementierung unterschiedliche Anzahlen vollständiger Runden als
Domainklassen führen. Deren Dispatchbereiche sind disjunkt und erzwingen, dass
die letzte Runde die erste Rückkehrmöglichkeit am oder nach der
Bedienungsdeadline erreicht. Die Rundenzahl bleibt dadurch abgeleitet.

Erster Katalogtyp: feste Stationsmengen pro Einsatz. Für R2 All-Stop, B+D und
C+E als kleiner Diagnosekatalog. Der erweiterte R2-Katalog enthält alle 14
Stationsmasken mit B+D oder C+E: BD, CE, ABD, BCD, BDE, ACE, BCE, CDE,
ABCD, ABCE, ABDE, ACDE, BCDE und ABCDE. Zusätzliche Halte können das Timing
verbessern und werden nicht allein wegen fehlender Nachfrage an diesem Halt
entfernt. Verteilung und Dispatchreihenfolge der Linien bleiben in der
Hauptsuche frei; keine feste 50:50-Verteilung oder Alternierung.
Das ist ein bewusster Katalogfilter, keine Behauptung
vollständiger Äquivalenz zum bisherigen freien Reservoirmodell.

„Jeder zweite Stationsbesuch“ ist ein anderer Katalogtyp: Auf fünf Stationen
rotieren die Haltestationen über die Umläufe. Solche Muster benötigen ihren
eigenen expliziten Besuchsverlauf. Sie gehören nicht stillschweigend zu einer
festen Stationsmaske. Die kanonische erste Zielbegegnung bleibt maßgeblich;
ein übersprungenes Ziel darf keine zusätzliche Passagierrunde erzeugen.

Der gemeinsame Katalog bewahrt Templates auch dann für spätere Waitingtests,
wenn sie nur im No-Wait-Profil unmöglich sind. Beispielsweise kann eine zu
frühe Rückkehr bei No-Wait später durch legales Waiting verändert werden.
Profilbezogene Ausschlüsse dürfen keine globale Unmöglichkeit behaupten.

## 4. Die drei Varianten

| Variante | Zeitdarstellung und Linienwahl | Stärke | Hauptrisiko |
|---|---|---|---|
| **V1 Dispatchabstände** | Eine Dispatchvariable pro Slot; Linienauswahl; erlaubte Abstandsbereiche je Linienpaar | Voller Integer-Dispatchbereich ohne Zeitnetz und ohne Einzelzeiten pro Besuch | Viele disjunkte Abstandsbereiche; schwächere globale Ressourcenpropagation möglich |
| **V2 Native CP-Intervalle** | Optionale, vom Dispatch verschobene Intervalle je Linienalternative; `NoOverlap` | Direkte Ressourcenmodellierung; günstiger Übergang zu Waiting | Viele Intervalle bei großem Katalog |
| **V3 Linien-Arc-Flow/Pfadauswahl** | Exakte Trajektorien für endliche Dispatchalternativen; Auswahl verträglicher Pfade | Wiederverwendung der Ressourcencliquen; konkrete Passagierzeiten | Dispatchaufzählung, später erneutes Wachstum durch Waiting |

### V1: vorgesehene Hauptumsetzung

Zunächst CP-SAT mit reifizierten Vereinigungen ganzzahliger Intervallbereiche.
Die Präparation ist solverfrei; ein Gurobi-Adapter ist später möglich, aber
nicht Voraussetzung für den ersten Test. Alle Linienzuweisungen und Abfahrten
werden in einem nativen Solveraufruf gemeinsam gesucht. Keine eigene
LNS-, Beam- oder Benders-Schleife.

### V2: Referenz und mögliche Waiting-Erweiterung

Je Linie und Nutzung entsteht ein optionales Intervall mit
`start = dispatch + enter_offset`, fester geschützter Dauer und Präsenz der
Linienauswahl. Ressourcen verwenden `NoOverlap`; Zustandskollisionen bleiben
separat modelliert. Keine freien STOP/SKIP-Variablen pro Besuch.

Für kleine Differentialtests ist ein schlanker Builder ausreichend.
Die große Performancevariante und Waitingintegration bleiben separate Gates.
Der bestehende vollständige CP-SAT-Builder mit fixierten Linien kann zusätzlich
als Testreferenz dienen, soll aber nicht der neue Produktionsbuilder werden.

### V3: begrenzte Zeit-/Pfadalternativen

Pro Linie, abgeleiteter Einsatzlänge und angebotener Dispatchzeit entsteht ein exakter
No-Wait-Pfad. Bewegungsketten können zu Auswahlvariablen kontrahiert werden,
solange sämtliche Ressourcenbelegungen und Passagierinzidenzen erhalten bleiben.
Linienidentität darf an gemeinsamen Knoten nicht verloren gehen.

Die endliche Dispatchmenge ist eine dokumentierte Einschränkung. Infeasibility
und Bounds gelten nur für dieses Netz. Mehr Dispatch- oder Waitingalternativen
vergrößern es; die Geschwindigkeit des historischen Fixed-K20-Arc-Flows ist
keine Prognose für diese Variante.

## 5. V1: mathematischer No-Wait-Kern

### 5.1 Vollständige Einsätze auf Dispatchvariablen reduzieren

Für Template p und Ereignis i gilt exakt:

    t[k,i] = d[k] + offset[p,i].

Hat Muster p die Rundendauer c[p] und enthält eine interne Domainklasse j
Runden, muss ihr Dispatch zusätzlich
`d[k] + (j-1)c[p] < service_end <= d[k] + jc[p]` erfüllen. Damit ist die
Rückkehr nach j Runden die erste Mustergrenze am oder nach der
Bedienungsdeadline. Dieser Bereich wird mit
`return_start - jc[p] <= d[k] <= operational_end - jc[p]`, [0,T] und dem
bestehenden Dispatchraster geschnitten. Leere Domains entfallen. Für die erste
eingesetzte Kabine muss null enthalten sein.

Selbstkonflikte der Nutzungen innerhalb eines Templates werden unabhängig
geprüft. Schutzintervalle können über Bewegungsenden hinausreichen und dürfen
auch bei aufeinanderfolgenden eigenen Umläufen nicht einfach ignoriert werden.

### 5.2 Verbotene Dispatchabstände

Eine Nutzung von p besitzt das halb offene geschützte Intervall [a,b), eine
Nutzung von q auf derselben Ressource [c,e), jeweils relativ zur Abfahrt.
Für `delta = d[j] - d[i]` überschneiden sich diese Intervalle genau dann, wenn

    a - e < delta < b - c.

Für Integer-Ticks lautet der verbotene abgeschlossene Bereich:

    [a - e + 1, b - c - 1].

Leere Bereiche entfallen. Über alle Nutzungen aller gemeinsamen Ressourcen
bilden wir die exakte Vereinigung, vereinigen auch direkt benachbarte
Integerbereiche und schneiden mit der erreichbaren Delta-Domain.
Ihr Komplement ist `AllowedDelta[p,q]`.

Beispiel: [100,110) und [70,80) ergeben 20 < delta < 40. Randberührung bei
20 oder 40 ist konfliktfrei; alle Zahlen sind in diesem Beispiel Ticks.

Gleiche Zustandsknoten erhalten die bestehende Ein-Tick-Eindeutigkeitsbelegung,
einschließlich Dispatch und letztem Rückkehrknoten. Das ist kein neu erfundener
physischer Headway. Absolute Anfangsreservierungen erzeugen entsprechende
unäre verbotene Dispatchbereiche statt relativer Paarbedingungen.

**Präsenzgate:** Die Übersetzung ist nur dann rein von delta abhängig, wenn
die betrachteten Nutzungen im gesamten erlaubten Dispatchbereich denselben
Präsenzvertrag haben. Für diese Geometrie ist dies aus Routen-/Rückkehrgrenzen
nachzuweisen. Falls Horizont-Präsenz absolute Dispatchfallunterscheidungen
erfordert, darf die Tabelle sie nicht ignorieren: entweder exakte Domain-
Partitionierung oder vorläufige Ablehnung dieser Geometrie zugunsten V2.

### 5.3 Solvermodell

- `used[k]` mit `used[k+1] <= used[k]`.
- `choose[k,p,j]`, Summe über alle Muster und ihre disjunkten, durch Dispatch
  bestimmten Rundenzahlklassen gleich `used[k]`. Der Index j ist eine
  Encodingklasse und keine Entscheidung zur frühen Rückkehr.
- `d[k]` in Integer-Ticks, für inaktive Slots kanonisch null.
- `d[0]` bleibt bei aktiver Flotte innerhalb `[0,T]` frei und bildet die
  optimierte globale Phase; bei leerer Flotte ist der Wert kanonisch null.
- Bedingte strikte Reihenfolge und [0,T] für aktive Slots.
- Gewähltes Template impliziert seine erlaubte Dispatchdomain.
- Für i < j und gewählte Templates p,q:
  `d[j]-d[i] in AllowedDelta[p,q]`.
- Leeres AllowedDelta verbietet die gemeinsame Auswahl; die volle Domain
  benötigt keine zusätzliche Zeile.

Erste CP-Implementierung: bedingte lineare Domain-Bedingungen für das Paar
der Linienliterale. Keine Auswahlvariable für jeden einzelnen Mikrosekundenwert.
Nicht unterstützte API-Kombinationen werden durch einen kleinen Modelltest
geprüft, bevor der große Builder entsteht.

Tabellen werden einmal je geordnetem Templatepaar berechnet und über alle
Kabinenpaare wiederverwendet. Keine falsche Symmetrie p,q = q,p: Beim Tausch
ändert sich das Vorzeichen der relativen Abfahrt.

### 5.4 Exaktheitsargument und Größenrisiko

Unter dem Präsenzgate ist ein festgelegter Linien-/Dispatchplan genau dann
ressourcengültig, wenn seine unären Domains, Selbstprüfungen und sämtliche
Paarbedingungen erfüllt sind. Für exklusive Ressourcen entspricht globale
Nichtüberlappung paarweiser Nichtüberlappung. Kopplungen zwischen Ressourcen
bleiben über dieselben Dispatchvariablen erhalten. Physische Reihenfolgen
müssen nicht als zusätzliche globale Kabinenreihenfolge festgelegt werden.

Bei Kmax=50 gibt es 1.225 Slotpaare. Das ist **nicht** die Zahl aller
Modellbedingungen: Mit P Templates und J Abstandsintervallen kann deren Umfang
bis zu O(Kmax² P² J) wachsen. Vor dem Solve erfassen wir P, Tabellenfragmente,
Zeilen und Bytes. Optional nötige Aufbaulimits führen zu `build_limit`, nicht
zu `INFEASIBLE` und nicht zu stiller Entfernung weiterer Alternativen.

## 6. Passagierbewertung und Bedeutung der Bounds

### 6.1 Drei klar getrennte Modi

- `feasibility`: reine Bewegungskontrolle, bei Diagnosefällen K/Patternfolge
  ausdrücklich vorgegeben; keine Passagierzusagen. Ende nach der ersten gültigen
  Lösung oder einem nativen Abschluss/Laufzeitlimit.
- **`exact_service` (Hauptsuche):** gemeinsame Linien-/Dispatchsuche mit exakt
  zeitgekoppelten ganzzahligen Beförderungen. Die erste Lösung beendet die
  Optimierung nicht; danach sucht die Engine nach höherer tatsächlicher Bedienung.
- `optimistic_service` (Ablation): gleiche Bewegung, Gruppenbilanzen und
  Abschnittskapazitäten, aber gelockerte zeitliche Passagierkopplung. Ein besserer
  Score zählt nicht als tatsächliche Verbesserung.

Ein optimistisches Ziel kann einen Fahrplan mit Score 3.000 und Bedienung 2.000
gegenüber einem Fahrplan mit Score 2.800 und Bedienung 2.700 bevorzugen. Die
nachgelagerte Zuordnung korrigiert nur die Bewertung, nicht die Suchrichtung.
Deshalb ist die exakte Zeitkopplung Pflichtbestandteil der ersten Hauptumsetzung.

### 6.2 Exakte Bedienung im kompakten No-Wait-Modell

Für jede kanonisch zulässige Beförderung r=(g,k,p,i,j) entstehen Integer-Menge
q[r] und ein Literal positive[r], äquivalent zu q[r] > 0. i und j sind die
Einstiegs- und erste Zielbegegnung des Templates p. STOP am Ursprung/Ziel und
die direkte Beförderungsdefinition werden bereits im Kandidatenbau geprüft.

Für ein gewähltes Template sind b[p,i] und a[p,j] die relativen tatsächlichen
Plattformausstiegs- beziehungsweise Zielankunftszeiten. Dann gilt:

    0 <= q[r] <= min(group_count[g], cabin_capacity) * choose[k,p]
    positive[r] => d[k] + b[p,i] >= release[g]
    positive[r] => d[k] + b[p,i] <= service_end
    positive[r] => d[k] + a[p,j] <= service_end
    positive[r] => d[k] + a[p,j] >= d[k] + b[p,i]

Die letzte Relation kann bei entsprechend geprüftem Template strukturell
garantiert sein. Für jede Gruppe gilt Summe q <= Nachfrage. Für jeden
Templateabschnitt gilt Summe der ihn belegenden q <= Q * choose[k,p].
Aussteigen vor neuem Einsteigen bleibt erhalten; es gibt keine fehlerhafte
gemeinsame Kapazitätssumme aus Aussteigern und anschließendem Bordbestand.

Ziel ist S = Summe q, gleichbedeutend mit min U = D-S. Jeder native Incumbent
enthält damit bereits eine vollständige physikalische Bewegung und eine
zeitlich gültige Integer-Zuordnung. Deren unabhängige Validierung bleibt Pflicht.

Diese Ergänzung führt Beförderungsvariablen und Präsenzliterale ein, aber
keine zusätzlichen unabhängigen Besuchszeiten, freien STOP/SKIP-Entscheidungen
oder Reisezeitprodukte. Eine günstige Gesamtgröße ist zu messen, nicht
vorauszusetzen: ungefähr Kmax * Templates * passende Gruppen/Besuchspaare.
Sicheres zeitliches Pruning erfolgt vor dem Solverbau; kein willkürliches
Abschneiden von Kandidaten oder unbewiesenes Zusammenfassen der Freigabebuckets.

Die erste Hauptkonfiguration maximiert ausschließlich S. Ein später optionaler
lexikografischer Fleet-Tiebreak darf nur bei gleicher echter Bedienung wirken.
Keine positive Belohnung für bloßes Aktivieren und keine Kabinenstrafe, die
mehr bediente Personen aufwiegen könnte.

### 6.3 Rolle der nachgelagerten Zuordnung und optimistischen Bounds

Auf ausgewählten gültigen Incumbents wird die Bewegung fixiert und die
ganzzahlige Passagierzuordnung erneut optimiert. Das prüft/reproduziert die
native Zuordnung und kann vor Solveroptimalität weitere Bedienung finden.
Nur ein abgeschlossener Beweis ergibt ein Passagieroptimum dieses Fahrplans.
Eine Verbesserung wird als separates Ereignis mit eigener Laufzeit gespeichert.
Ein gemeinsames Modelloptimum und das optimale Zuordnungsergebnis desselben
Fahrplans müssen denselben Wert haben; Abweichungen sind ein Fehlergate.

Optimistische Musterbounds dienen der Vorverarbeitung, Einordnung und Ablation.
Sie dürfen keine konkrete schlechte Zuordnung als unzulässigen Gesamtfahrplan
verwerfen. Ein gefundener primaler Wert des Hilfsmodells ist keine Obergrenze;
dafür sind dessen Optimum oder eine gültige obere Solverschranke erforderlich.
Dasselbe gilt für LP-Abbrüche. Bei numerischen Zertifikaten bestehende
konservative Boundprüfung verwenden; ohne abgesicherten Wert bleibt D sicher.

Für `exact_service` ist der validierte Incumbent eine Bedienungsuntergrenze,
die native obere Schranke begrenzt die Bedienung des gesamten bezeichneten
eingeschränkten Modells. Umrechnung: LB(U) = max(0, D - UB(S)).
Eine ganzzahlige Schrankenverschärfung erfolgt nur mit numerisch abgesicherter
Rundung. Kein globaler Bound für das ursprüngliche freie Reservoirmodell.

Ein No-Wait-Bound gilt nicht automatisch für Waiting. Ein Bound nach Fixierung
von Dispatchzeiten gilt nicht für alle Abfahrten derselben Patternfolge.
Katalog, T, Waitingorte und alle weiteren Restriktionen werden beim Bound
explizit gespeichert. Relaxierte Bounds dürfen nur bei nachgewiesener
Überdeckung auf ein anderes Profil übertragen werden.

### 6.4 Suchsteuerung und tatsächlicher Fortschritt

Die K-Leiter ist eine Diagnose vor der Hauptsuche, kein eigener Algorithmus
zur Flottenoptimierung. Die Hauptsuche enthält direkt optionale Slots bis Kmax;
Linienwahl, K, Einsatzlängen und Dispatch werden vom nativen Solver entschieden.
Ein gültiger Startplan bleibt außerhalb der Engine als Rückfalllösung erhalten;
ein Hint allein garantiert keine native Übernahme. Entscheidungen werden nicht
fixiert, und es gibt keinen harten höheren Bedienungscutoff, der den Startplan
aus dem Modell entfernen würde.

Konzeptioneller Ablauf, keine behauptete `search_step`-API:

```python
prepared = prepare_line_catalog_and_dispatch_domains(problem)
run_small_feasibility_gates(prepared)
best = validate_compatible_reference_if_present()

for stage in explicitly_enabled_and_gated_stages:
    # Anfangs ausschließlich No-Wait; Waiting ist kein automatischer Folgelauf.
    if deadline_reached():
        break
    model = build_joint_line_timing_model(prepared, stage)
    add_exact_integer_passenger_links(model, stage)
    maximize_actual_served(model)
    add_compatible_hint(model, best)

    # Native Suche enthält Branching, Propagation und interne Heuristiken.
    result = solve_once(model, stage_budget, callback=copy_native_incumbent)

    for candidate in recorded_candidates_within_validation_budget:
        validate_original_physics_and_integer_assignment(candidate)
        best = keep_better_validated(best, candidate)

    if best is not None and evaluation_budget_remains():
        refined = optimize_integer_passengers_on_fixed_movement(best)
        best = keep_better_validated(best, refined)
    save_progress_and_scope(result, best)
    if best_serves_all_demand(best):
        break

return best
```

Der Callback kopiert vollständige Werte und protokolliert Ereignisse; er startet
keinen verschachtelten Optimierungslauf. Kopierte Kandidaten werden budgetiert
unabhängig geprüft. Ungültige Kandidaten stoppen das Korrektheitsgate und gelten
niemals als Fortschritt. Nachgelagerte Verbesserungen können Startinformation
für einen später ausdrücklich geplanten Lauf sein; sie gelangen nicht
rückwirkend in den bereits abgeschlossenen Solve.

Fortschritt bedeutet steigende validierte S-Werte und/oder engere gültige
Schranken innerhalb derselben Modelldomäne. Für den exakten Hauptpfad ist kein
Umweg über einen steigenden Ersatzscore nötig. Weder stetige Verbesserung noch
ein enger Gap wird garantiert. Kleine Neustarts übernehmen im Allgemeinen
nicht die vollständige gelernte Suchinformation; deshalb wenige begründete
Stufen, keine automatische Schleife aus UNKNOWN und neuen Patternfolgen.

## 7. V1: konkrete Umsetzungsschritte und Zwischentests

### Schritt A — Vertrag und gemeinsame Vorbereitung

Neues Paket `optimization/ddd/reservoir_lines/` mit unveränderlichen Typen:

| Modul | Aufgabe |
|---|---|
| `config.py` | Variante, Katalogprofil, T, Zielmodus, Limits |
| `catalog.py` | `LineTemplate`, deterministische vollständige Einsatzkataloge |
| `preparation.py` | `PreparedLineProblem`, exakte Ressourcen-/Ereignisversätze |
| `dispatch_domains.py` | Selbstprüfung, unäre Domains, `AllowedDelta` |
| `cp_model.py` | spezialisierter V1-Builder |
| `interval_reference.py` | kleiner V2-Builder für Differentialtests |
| `passenger_model.py` | exakte zeitgekoppelte Integer-Beförderungen, `exact_service` |
| `passenger_bounds.py` | optimistische Ablation und klar begrenzte Bounds |
| `certificate.py` | bestehende Trip-/Ride-IDs, Export, unabhängige Prüfung |
| `optimizer.py` | nativer Solve und gemeinsame Ergebnisstruktur |

Keine duplizierten Komplettsolver. Vorbereitung enthält keine Solvervariablen.
Vorhandene solverfreie Ressourcengeometrie wiederverwenden, soweit deren
Lebenszyklusvertrag identisch ist.

**Zwischentest A:** Jeder Templateversatz stimmt mit einer separat aufgebauten
No-Wait-Trajektorie der ursprünglichen Domäne überein. Tests für alle Masken,
mehrere Rückkehrbesuche, Schutz hinter dem Horizont und ungültige Templates.

### Schritt B — Exakte Abstandsberechnung

Halb offene Intervalle in Integer-Ausschlüsse übersetzen; Intervallvereinigung,
Komplement und Dispatchdomain-Schnitt implementieren. Pro Ausschluss die
verursachenden Ressourcen-/Besuchs-IDs für Diagnose erhalten, ohne sie pro
Slotpaar zu duplizieren.

**Zwischentest B:** Kleine Tickdomänen vollständig enumerieren. Für jedes
Templatepaar und jeden Dispatchabstand exakte Gleichheit zwischen direkter
Intervallprüfung und AllowedDelta nachweisen. Zusätzlich Drei-/Vierkabinenfälle
gegen vollständige Pläne prüfen; Paarprüfungen allein testen nicht den Builder.

Pflichtfälle: Randberührung, Ein-Tick-Konflikt, gleiche Ressource mehrfach,
zwei gekoppelte Ressourcen, echtes Überholen, Selbstkonflikt über Umläufe,
Start-/Rückkehrkollision, absolute Anfangsreservierung, negative Delta-Werte
in der Präparation und große Tickwerte oberhalb 32 Bit.

### Schritt C — Reiner V1-Machbarkeitsbuilder

Linienwahl und Dispatch gemeinsam gemäß Abschnitt 5 implementieren. Zunächst
fixierte kleine Patternfolgen, anschließend freie Auswahl bei Kmax=2/4.
Inaktive Slots dürfen keine Domains oder Pair-Constraints aktivieren.

**Zwischentest C:** Auf enumerierbaren Fällen identische zulässige
Linien-/Dispatchbelegungen wie V2 und ursprünglicher physikalischer Prüfer.
Keine bloße Übereinstimmung eines einzigen Optimalwerts.

Zusätzlich K=0/1/Kmax, erste Abfahrt null und positiv, d=T, d=T+1, Dispatchraster,
eine nur durch Überholung fahrbare Kombination und eine beweisbar nicht
fahrbare Kombination. Modellinvalidität, Timeout und Speicherabbruch dürfen
keinen Unzulässigkeitsbeweis erzeugen.

### Schritt D — Exakte Bedienung, Ablation und Zertifikate

Zuerst `exact_service` nach Abschnitt 6.2 implementieren. Danach dieselbe
Kandidaten-/Kapazitätsvorbereitung mit explizit gelockerter Zeitkopplung als
`optimistic_service` verfügbar machen. Der reine Machbarkeitsbuilder erzeugt
weiterhin keine Passagiervariablen. Den Adapter zur bestehenden festen
Fahrplan-Passagieroptimierung für unabhängige Prüfung und Nachoptimierung
ergänzen. Ursprüngliche kanonische Ride-IDs erhalten, insbesondere den ersten
Zielbesuch. Positive importierte Mengen auf nicht darstellbaren Beförderungen
führen zu einer klaren Ablehnung.

**Zwischentest D:** Kleine vollständige Zuordnungsenumeration; volle Kabinen,
Aus-/Einstieg beim selben Besuch, konkurrierende OD-Gruppen, unbedienbare
Nachfrage, Releases exakt zum Einstieg, Zielankunft bei H/H+1 und bestehendes
Odd-Cycle-Ganzzahligkeitsprinzip. Jede gültige Bedienung liegt unter dem
korrekt berechneten optimistischen Bound für denselben Gültigkeitsbereich.

Zusätzliche Pflichtprüfungen:

- Auf kleinen vollständigen Fällen liefert `exact_service` dasselbe Optimum
  wie unabhängige Enumeration von Linien, Dispatch und Integer-Zuordnungen.
- Bei fixierter Bewegung stimmt das Passagieroptimum mit dem bestehenden
  unabhängigen Zuordnungssolver überein; Abbruchwerte als solche kennzeichnen.
- Die optimistische Ablation enthält jede exakte Lösung und kann nur einen
  gleich hohen oder höheren nachgewiesenen Optimalwert haben.
- Gegenbeispiel mit attraktivem optimistischem Score, aber schlechten konkreten
  Dispatchzeiten: `exact_service` darf nicht die unrealistische Menge zählen.
- Inaktive und nicht gewählte Templates haben q=0; Gruppenmengen dürfen nicht
  über mehrere Linienalternativen desselben Slots vervielfacht werden.
- Seedimport enthält Zeit- und Passagierwerte, fixiert aber keine Entscheidungen.
  Der bekannte Plan bleibt beim optionalen Erhöhen von Kmax darstellbar.
- Zeitlimit und nachgelagerte Bewertung ändern keine protokollierten nativen
  Zeitpunkte; nur unabhängig gültige tatsächliche Bedienung zählt als Erfolg.

Historische Pläne nur bei passendem T, erster Abfahrt, No-Wait und darstellbaren
Linien replaysicher übernehmen. Sonst `reference_not_representable` mit Grund;
keine stille Änderung von Zeiten oder Zuordnungen.

### Schritt E — Integration und Messung

Neuer Runner `benchmarks/run_reservoir_lines.py` mit:

    --variant dispatch_domains|intervals|path_selection
    --mode feasibility|exact_service|optimistic_service
    --dispatch-window-end <T>
    --catalog <file-or-profile>
    --max-cabins <Kmax>
    --fixed-pattern-sequence <optional-file>
    --fixed-cabins <optional-K>
    --time-limit --workers --memory-limit-gib --seed
    --reference-checkpoint --output --build-only
    --fix-reference-movement

Zunächst nur `dispatch_domains` öffentlich suchfähig; nicht implementierte
Varianten werden vor Aufbau abgelehnt. Kleine V2-Tests dürfen eine interne
Test-API verwenden. Neuer Runner verwendet standardmäßig `exact_service`;
Feasibilitytests und optimistische Ablation setzen ihren Modus ausdrücklich.
Bestehende Runner und Standards bleiben unverändert.

**Umsetzungspräzisierung (12.09.2026):** V1 darf eine bestehende
`bounded_wait`-Quelldomäne laden, fixiert aber nachweisbar alle Waitings auf
null. Das ist nötig, weil der eingefrorene R2-Fall eine Waiting-Policy besitzt,
sein Referenzplan aber tatsächlich ohne Waiting fährt. Modellfingerprint,
Statistik und `proof_scope` tragen deshalb ausdrücklich
`waiting_fixed_to_zero`; jeder Bound gilt nur für das eingeschränkte
No-Wait-Linienmodell. Ein positives Waiting im Seed bleibt nicht darstellbar.
OR-Tools 9.15 stellt am gebundenen Proto zwar keine direkte `ByteSize`-Methode
bereit, kann das Modell aber verlustfrei temporär binär exportieren. V1 misst
daher die tatsächliche Exportgröße unter `serialized_model_bytes`; der
Modellfingerprint wird ohne eine speicherintensive vollständige Textkopie aus
Präparationsfingerprint, Konfiguration und Buildervertrag gebildet.

Das erste reale R2-Größengate ergab beim kleinen Katalog bereits für Kmax=50
592.900 konditionale Templatepaar-Constraints, 913.585 Constraints insgesamt
und rund 285 MB Proto-Text in der ersten Diagnose (Aufbau 7,4 s). Eine
unveränderte Hochrechnung des
14-Muster-Katalogs läge bei über zwölf Millionen Templatepaar-Constraints.
Deshalb wird die zuvor nur als Differentialreferenz geplante exakte
`intervals`-Variante bereits im Pilot öffentlich implementiert: optionale
Intervalle mit affinem Start `d_k + offset` und je Ressource ein natives
`NoOverlap`. Separate Ressourcenlisten erhalten Überholungen. Diese Anpassung
ändert keinen zulässigen Linienfahrplan; kleine Fälle müssen weiterhin exakt
mit den vorberechneten Delta-Domains übereinstimmen. Der erweiterte Katalog
wird nur mit bestandenem Modellgrößengate gebaut und nicht als zwölf Millionen
Zeilen großes Delta-Modell erzwungen.

Das anschließende Kmax=50-Größengate der Intervallkodierung ist bestanden. Der
kleine Katalog baut 100.950 Variablen, 393.205 Constraints und 72.500 native
Intervalle bei 26,3 MB Binärproto in rund 2,4 s. Der erweiterte Katalog baut
400.100 Variablen, 1.613.155 Constraints und 336.750 Intervalle bei 111,5 MB
Binärproto in rund 11,9 s; gemessene Prozess-RSS rund 1,10 GB. Damit ist er
groß, aber innerhalb des 24-GiB-Gates. Der erste Suchvergleich verwendet für
den erweiterten Katalog zwingend `intervals`; `dispatch_domains` bleibt dort
wegen der prognostizierten zwölf Millionen Paarzeilen gesperrt.

Ein erster, bewusst noch ungesäter Kmax=50-Smoke-Lauf mit kleinem Katalog,
`intervals` und `exact_service` fand in 30 s keine native Lösung und beendete
mit `UNKNOWN`; das Modell hatte 100.950 Variablen und 393.205 Constraints.
Dieser Befund bestätigt die geplante Reihenfolge: zuerst kleine/fixierte
Machbarkeitsgates und daraus einen darstellbaren vollständigen Hint erzeugen,
danach die exakte freie Bedienungssuche. Der rohe CP-SAT-Defaultbound `0` bei
`UNKNOWN` vor einer belastbaren Suchschranke wird nicht exportiert; in diesem
Fall bleiben Served-Upper-Bound und Unserved-Lower-Bound ausdrücklich `null`.

Auch ein vollständiger K16-Bewegungs-Hint wurde im Kmax=50-Modell innerhalb
von rund 31 s Presolve nicht erreicht (`integers=0`, `branches=0`, keine
Callbacklösung). Deshalb erhält der Runner eine explizite
`--presolve/--no-presolve`-Ablation. Das ist Solverkonfiguration, keine eigene
Suche und keine Domänenänderung. `presolve=true` bleibt Standard. Der
No-Presolve-Test übernahm den K16-Hint nach 3,0 s und verbesserte in 30 s bis
S=1.414. Ein danach erzeugter, physikalisch in 1,7 s bestätigter K32-BD/CE-Hint
führte in der freien Kmax=50-Suche innerhalb 60 s zu **S=2.682 / U=392**; die
letzte Verbesserung trat bei rund 47,6 s ein. Damit ist No-Presolve für die
erste Bestätigung das experimentell empfohlene Profil, ohne den Standard
automatisch zu ändern. Der globale Line-Domain-Gap blieb dabei weit offen.

Die anschließende 300-s-Bestätigung verbesserte fortlaufend bis
**S=3.036 / U=38** bei 36 Kabinen; die letzte Verbesserung kam bei rund
293,35 s. Der ursprüngliche Validator bestätigte den Abschlusscheckpoint.
Zusammen mit dem bestehenden globalen R2-All-Stop-Bound `U_AS* >= 125` ist
damit das Vergleichsziel erreicht: `38 < 125`. Der zweite Seed bleibt für die
Robustheitsbewertung vorgesehen, ist aber für die logische Gültigkeit dieses
bereits geprüften Zeugen nicht erforderlich.

Die Seed-1-Wiederholung auf dem sauberen Commit `4f4ab9c` verbesserte weiter
und erreichte nach rund 89,69 s **S=3.074 / U=0** mit 38 Kabinen. Der finale
Checkpoint wurde unabhängig gegen die ursprüngliche vollständige Domäne
bestätigt. Damit ist auch das primäre Bedienungsoptimum für diese konkrete
Nachfrage trivial erreicht; offen bleibt nur die sekundäre minimale
Flottenzahl. Gegen den globalen All-Stop-Bound entspricht dies einem
nachgewiesenen Vorteil von mindestens 125 Personen. Die Umsetzung wechselt
deshalb von „Incumbent-Gate“ zu Reproduktions- und Übertragbarkeitsprüfung;
weitere Formulierungsvarianten sind für den R2-Kapazitätsnachweis nicht mehr
erforderlich.

Physikalische Domäne, neue Vergleichsrestriktionen und Modellencoding erhalten
getrennte Fingerprints. Modellfingerprint enthält Katalog, T, erlaubte
Abstandsbereiche, Zielmodus und Präparationsversion. Ergebnisse speichern
Engineversionen, Quellhashes und komplette Konfigurationen.

Erfassen: Katalog-/Tabellenbau, Modellbau, native Suche, Passagierbewertung,
Validierung, Gesamtlaufzeit und Peak-Prozessbaum-RSS. Größen: Templates,
Ressourcennutzungen, Intervalle je Delta-Tabelle, Variablen, Constraints und
serialized model bytes; Integer-Beförderungen, Positive-Literale und
Zeitkopplungszeilen separat. Ergebnisverlauf: erster gültiger Bewegungsplan,
erste gültige Zuordnung, native tatsächliche Bedienung in `exact_service`,
optimistische Scores nur in der Ablation, unabhängig gültige Bedienung,
Linienmix, Flottengröße, Dispatchspanne, letzter Fortschritt und Status.

Native Verbesserungen und spätere Passagierbewertungen haben getrennte
Zeitstempel. Keine günstige Passagierbewertung in die Solverzeit zurückdatieren.
Checkpoints werden atomar geschrieben; historische Ergebnisse bleiben erhalten.
`--fix-reference-movement` ist der getrennte Zuordnungsadapter: Er fixiert nur
den bereits unabhängig validierten Linienfahrplan und optimiert die exakten
Integer-Beförderungen. Er wird als `FIXED_LINE_MOVEMENT` ausgewiesen und darf
nicht mit einem globalen Fahrplanbound verwechselt werden.

## 8. Bestehende Bausteine und Wiederverwendung

| Bestehender Pfad unter `optimization/ddd/` | Verwendung |
|---|---|
| `reservoir_cp_sat_problem.py` | maßgeblicher Lebenszyklus, Zustandsfolge, kanonische Rides |
| `reservoir_cp_sat_movement.py` | Referenz für Dispatch, Rückkehr, Präsenz und Ressourcen |
| `cp_sat_passenger.py` | Referenz für Release-/Horizontkopplung, Integer-Mengen und Kapazitäten; spezialisierte Templateinzidenzen statt vollständigem Besuchsmodell |
| `reservoir_cp_sat_certificate.py` | `DddReservoirCpPlan`/`Trip`, Checkpoints, unabhängiger Validator |
| `native_solvers/model.py` | solverfreie Vorbereitung auf Wiederverwendung prüfen |
| `reservoir_assignment/timing.py` | Differentialtests; nicht als neuer Hauptbuilder verwenden |
| `reservoir_capacity/network.py` | Ressourcengeometrie einschließlich Waiting-Koeffizienten |
| `arc_flow_network.py` | spätere V3-Anbindung, kein Aufbau des freien Netzes für V1 |

Der aktuelle Assignment-Timingbuilder baut zunächst das vollständige
Passagiermodell und fixiert dann Entscheidungen. Das ist ausdrücklich nicht
die beabsichtigte Implementierung der neuen reinen Machbarkeitsstufe.

## 9. Vorgeschlagene erste Performanceprüfung

Implementierung/Korrektheitstests getrennt. **Vorgeschlagenes Kampagnenmaximum:
30 Minuten tatsächliche Wandzeit**, erst nach Freigabe der Korrektheitsgates;
dieses Planungsdokument startet keine Läufe.

R2 mit 3.074 Personen zuerst. T und der neue Domänen-/Vergleichsfingerprint
werden vorab eingefroren. Die historische Referenz S=2.496 ist zunächst nur
Kontext, solange ihre Zugehörigkeit zum neuen Vertrag nicht nachgewiesen ist.

| Abschnitt | Versuche | Budget |
|---|---:|---:|
| Einfrieren, Referenzprüfung, gemeinsame Tabellen | — | 120 s |
| Reine Machbarkeit K4/K8/K16, kleiner Katalog | 3 × 30 s | 90 s |
| Reine Machbarkeit K24/K32 nach bestandenem kleineren Gate | 2 × 60 s | 120 s |
| Ein erster schwieriger Fall als gezielte längere Diagnose | 1 × 300 s | 300 s |
| Freie Linienwahl Kmax50, `exact_service`, kleiner und erweiterter Katalog | 2 × 300 s | 600 s |
| `optimistic_service`-Ablation, kleiner Katalog | 1 × 180 s | 180 s |
| Wiederholung des aussichtsreicheren exakten Profils mit Seed 1 | 1 × 180 s | 180 s |
| Abschließende Passagierbewertung, Bericht und Reserve | — | 210 s |
| **Gesamt** | | **1.800 s** |

In den Machbarkeitstests ist K exakt vorgegeben, die Linienwahl frei; vorhandene
fixierte Sequenzen dienen zusätzlich als kleine Korrektheitskontrollen.
Einsatzkataloge und -längen vorab eindeutig festhalten; sie dürfen nicht je
Solver nach Ergebnis angepasst werden. No-Wait-Machbarkeit mit kurzen Einsätzen
ist getrennt von deren produktiver Passagierbedienung zu berichten.

Nach dem ersten UNKNOWN die K-Skalierung anhalten. Die gezielte 300-s-Diagnose
prüft genau diesen Fall länger; sie wird einschließlich ihrer kompletten
Laufzeit zusätzlich budgetiert und nicht als fortgesetzter interner Suchzustand
ausgegeben. Endet sie weiterhin UNKNOWN, bleiben größere Stufen ausstehend.
Ein INFEASIBLE bei festem K widerlegt nur diesen Katalog/Betriebsvertrag.
Bei schneller Diagnose ein repräsentatives größeres Machbarkeitsgate verwenden,
keine Serie weiterer Langläufe. Max50-Hauptläufe setzen einen unabhängig
gültigen positiven Startplan im neuen Vertrag und bestandene Skalierungsgates
voraus. Die K-Leiter bleibt Diagnose, keine äußere Flottenoptimierung.

Alle Prozesse sequenziell, zwölf Worker, maximal 24 GiB Prozessbaum-RSS.
Einzelbudgets enthalten instanzspezifischen Aufbau und Abschluss. Gemeinsame
harte Deadline einschließlich Suspend; keine automatische Umverteilung
ausgefallener Budgets. Bei dominierendem Aufbau keine große Suche starten.

Auswertung bei 30/60/120/180/300 Sekunden, sofern tatsächlich gelaufen:
Machbarkeit, tatsächliche native Bedienung und vergleichbare Boundentwicklung.
Score-Abstand nur für die Ablation ausweisen. Die 180-s-Wiederholung und Ablation
werden mit dem 180-s-Zwischenstand der Hauptläufe verglichen; keine unmarkierten
Vergleiche mit 300-s-Endwerten. Kein Fortschrittsversprechen aus bloßer
Branch-/Propagationszahl.

## 10. Waiting und weitere Entscheidungen nach dem No-Wait-Gate

Waiting ist ein eigener Ausbau, keine unveränderte Anwendung der Tabellen.
Mit Wartezeiten verschieben sich nachfolgende Nutzungen; die No-Wait-
AllowedDelta-Bedingungen können dann gültige Pläne ausschließen oder falsche
Konfliktfreiheit suggerieren.

Vorgesehener Weg: Katalog/Dispatch/Zertifikat wiederverwenden und in V2
Waitingvariablen an ausgewählten STOP-Exits ergänzen. Alle betroffenen
Folgeereignisse und Ressourcen erhalten exakte affine Warteabhängigkeiten.
Vorläufige No-Wait-Paarbedingungen müssen ersetzt werden, sofern ihre
Gültigkeit für die erweiterten Alternativen nicht separat bewiesen ist.

Waiting bleibt null zulässig. Positives Waiting, Ressourcenbelegung am Exit,
Mergeverschiebung, maximale Wartezeit und rechtzeitige Rückkehr werden separat
gegen das Originalmodell getestet. Ein Timeout des No-Wait-Kerns ist kein
Nachweis, dass Waiting erforderlich ist; ein Konflikt eines einzelnen
Dispatchvektors ist kein Beweis gegen alle Dispatchzeiten derselben Linien.

Auch in der Waiting-Hauptsuche bleiben die Integer-Mengen an die tatsächlichen
Einstiegs- und Zielankunftszeiten gekoppelt. Die exakte zeitliche Kopplung wird
nicht durch optimistische Fenster ersetzt. Zusätzliche Verzögerung kann
Nachfrageaufnahme ermöglichen, aber andere Beförderungen verhindern; minimale
Wartezeit ist kein Ersatz für das primäre Bedienungsziel.

Keine automatische Stufenfolge `No-Wait -> einige Orte -> alle Orte` nach
Zeitablauf. Jede Erweiterung benötigt einen dokumentierten Befund und ein
eigenes freigegebenes Budget. Ein nachweislich inkompatibler konkreter
No-Wait-Linienauftrag kann eine Reparaturdiagnose begründen. Bereits gute
No-Wait-Pläne können einen kontrollierten Waitingvergleich begründen. UNKNOWN
allein öffnet keine weiteren Variablen. Alte No-Wait-Incumbents bleiben bei
echter Erweiterung mit Waiting=0 zulässig, ihre Bounds werden nicht übertragen.
Hints übernehmen Fahrpläne, nicht automatisch den internen Lernzustand der Engine.

Entscheidungen anhand der ersten Kampagne:

- **Reines Timing schnell, exakte Bedienungssuche langsam:** Zusätzliche
  Passagierverzweigung und Zeitkopplung isoliert messen; keine Rückkehr zu einem
  unkontrollierten Ersatzscore als Hauptziel.
- **Gültige Pläne, Bedienung schlecht:** Katalog, Einsatzlängen, Nachfragefenster
  und tatsächlichen Solverfortschritt untersuchen; nicht allein mehr Flotte
  oder mehr Waiting zulassen.
- **Fixierte Muster schnell, freie Wahl langsam:** Katalog-/Paarmodellgröße
  untersuchen und V2 auf identischen Fällen vergleichen.
- **Tabellen stark fragmentiert:** V2 oder später V3 als alternative Darstellung
  prüfen; keine willkürliche Intervallabrundung.
- **No-Wait beweisbar unzulässig für interessante konkrete Kombinationen:**
  begrenzte Waiting-Stufe testen.
- **Nur UNKNOWN ohne gültigen Plan:** keinen äußeren Patterncontroller bauen,
  der dieselbe ungeklärte Machbarkeit immer wieder aufruft.
- **Gültige konkurrenzfähige Pläne:** Gemeinsame exakte Linien-/Dispatch- und
  Passagiersuche weiter untersuchen, mit Wiederholung bestätigen.

Der Vergleich mit dem besten All-Stop-Referenzplan ist ein Fahrplanvergleich.
Der stärkere Nachweis verlangt bei derselben Vergleichsdomäne weiterhin
`U_skip_stop_valid < LB(U_all_stop_optimal)`. Eine No-Wait- oder Linienkatalog-
Schranke darf nicht ungeprüft für das vollständige Waitingproblem verwendet werden.

## 11. Quellen und Einordnung

- [Pätzold et al. (2017): Look-Ahead Approaches for Integrated Planning in Public Transportation](https://drops.dagstuhl.de/entities/document/10.4230/OASIcs.ATMOS.2017.17).
  Motiviert die Berücksichtigung späterer Machbarkeit bei Linienplanung;
  keine Garantie für unsere Zerlegung.
- [Fischer (2015): Ordering Constraints in Time Expanded Networks for Train Timetabling Problems](https://drops.dagstuhl.de/entities/document/10.4230/OASIcs.ATMOS.2015.97).
  Verwandte zeitliche Ressourcenplanung auf vorgegebenen Routen; V3-Einordnung.
- [OR-Tools: The Job Shop Problem](https://developers.google.com/optimization/scheduling/job_shop).
  Native Modellierung von Ressourcenbelegung und Reihenfolgekonflikten.
- [OR-Tools: Channeling Constraints](https://developers.google.com/optimization/cp/channeling).
  Bedingte lineare Kopplung positiver Beförderungen an gewählte Dispatchzeiten.
- [Gurobi: Constraints](https://docs.gurobi.com/projects/optimizer/en/current/concepts/modeling/constraints.html).
  Bedingte lineare Modellierung, endliche Genauigkeit und Toleranzen bei
  einem späteren Gurobi-Backend.

Die seilbahnspezifische Vereinigung verbotener Dispatchabstände, Präsenzprüfung,
Rückkehrbehandlung und Passagierbounds benötigen die beschriebenen eigenen
Nachweise. Die Literatur ist kein Beleg für einen erwarteten Geschwindigkeitsfaktor.

Verwandte lokale Befunde:

- [Bisheriger Assignment-/Timing-Pilot](../findings/reservoir_assignment_timing_pilot_20260912.md)
- [Konfliktdiagnose mit weiterhin enthaltenen Passagierbedingungen](../findings/reservoir_assignment_conflict_diagnosis_20260912.md)
- [Symbolischer DP und bisherige Skalierung](../findings/reservoir_symbolic_and_pattern_dp_20260912.md)
