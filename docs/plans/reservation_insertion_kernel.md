# Reservierungs- und Einfügekern für Ropeway

Stand: 9. September 2026. **Weiterführender fachlicher Entwurf.** Der begrenzte Pilot ist inzwischen [implementiert](../reference/ddd_reservation_insertion.md); [Ergebnisse und Grenzen](../findings/ddd_reservation_insertion_gate.md) unterscheiden ihn von den weitergehenden Ideen unten. Konkretisierung von G1/A1/A2 aus der [Heuristik-Roadmap](heuristic_and_non_mip_roadmap.md). Ziel ist ein schneller Verbesserungsoperator für bestehende K39-Waiting-Pläne. Kein neuer globaler Solver und keine Optimalitätsgarantie.

Konkrete Klassen, Schnittstellen, Integration und Implementierungsreihenfolge: [OO-Umsetzungsplan](reservation_insertion_implementation.md).

## 1. Entscheidung und unveränderter Modellvertrag

Wir verbinden vollständige OD-Bedienungsänderungen mit einer ressourcenbasierten Zeitfenstersuche und einer begrenzten Neuplanung der tatsächlich blockierenden Kabinen. Die Suchentscheidung lautet beispielsweise: „Kabine 7 bedient zusätzlich A→D; nötige Änderungen an ihren Folgefahrten und an blockierenden Kabinen werden gemeinsam geprüft.“

Ausgangspunkt ist der beste vorhandene, unter dem endlichen Vertrag validierte K39-Waiting-Plan: Journey-Time-Ziel 1.022.076,357256 Passagiersekunden, 1104 bediente und 176 unbediente Personen. Quelle: [Waiting-Finding](../findings/ddd_integrated_cp_sat_waiting_gate.md), nachgeprüft im [Horizon-Gate](../findings/ddd_horizon_contract_gate.md). Der neue Kern muss zunächst überhaupt andere zulässige Bewegungen finden; eine Verbesserung ist eine zu testende Hypothese.

Es bleiben Five-Station-B, K=39, feste Startpositionen und Boundary, Kapazität 8, 20 OD-Gruppen/1280 Personen, Release 0, H=T=1200 s, Exit-Waiting W=1200 s und Mikrosekunden-Ticks. Keine Periodizität, zusätzliche Warteorte oder frei wählbare Kabinenzahl. Die feste Startanordnung bedeutet keine Fixierung aller zukünftigen Stop-/Skip-Entscheidungen.

**Der Nutzer hat den endlichen Horizont ausdrücklich akzeptiert.** Es gilt [closed_event_entry_horizon_v1](../reference/finite_horizon_contract.md): Ressourceneintritte bis einschließlich H sind aktiv und behalten ihre vollständige Räumzeit; neue Eintritte nach H werden ausgeschlossen. Ein nachgewiesener Dauerbetrieb nach H ist keine Voraussetzung dieses Vorhabens. Jeder geänderte Kabinenpfad muss dennoch den gesamten vereinbarten Horizont abdecken; bloßes Abschneiden am Zielausstieg ist unzulässig.

## 2. Was die Papers beitragen

Die folgende Architektur ist unsere Übertragung. Keines dieser Papers löst genau die Kombination aus dichtem Seilbahnring, Skip-Stop, Exit-Waiting und geteilter Passagierkapazität.

| Quelle / geprüfte Grundlage | Verwendbare Idee | Anpassung und Grenze bei Ropeway |
|---|---|---|
| Ropke & Pisinger, 2006 [S1], Originalmanuskript, Abschnitte 3.2 und 4.2 | Pickup und Delivery gemeinsam einfügen; Greedy und Regret vergleichen; anschließend gegebenenfalls ALNS | Einstieg und Zielausstieg sind ein Paket. Anders als im Paper beeinflusst eine Änderung über gemeinsame Ressourcen auch andere Fahrzeugrouten. Dessen Cache-Regel für unveränderte Routen ist deshalb nicht direkt übertragbar. |
| Haneyah et al., 2011 [S2], Volltext, Abschnitt 2 | Freie Merge-Plätze suchen, Anfragen priorisieren und Reservierungen neu vergeben | Reservierung darf vorläufig sein. Bei uns erfordert eine Neuvergabe die Reparatur aller dadurch geänderten Bewegungen. Das Paper behandelt ein lokales Fördertechnik-Merge-Modul und ein anderes Ziel. |
| Ali & Yakovlev, 2023 [S3], Volltext, Method | Zeitintervalle fortpflanzen, wenn nicht überall gewartet werden kann | Legale Verzögerungen an einem Exit müssen über nachfolgende Abschnitte ohne Wartefreiheit erhalten bleiben. Die erste Ropeway-Version übernimmt dieses Prinzip, nicht die Vollständigkeits-/Optimalitätsgarantie von SIPP-IP. |
| Gholami & Törnquist Krasemann, 2018 [S4], Abstract geprüft | Konflikte im Bahnverkehr durch Retiming, Reordering und lokale Routenänderungen behandeln | Bestärkt die Suche über Konfliktzusammenhänge. Eine alternative graphbasierte Zeitpropagation bleibt ein möglicher Ersatz für den inneren Decoder; sie wird im ersten Pilot nicht zusätzlich gebaut. |
| Dong et al., 2020 [S5], Publisher-Vorschau/Abstract | Stopplanung und Fahrplanung gemeinsam mit ALNS bearbeiten | Stützt den späteren äußeren Verbesserungsrahmen. Belegt weder die Leistung unseres Reservierungskerns noch einen Vorteil auf K39. |

Ropke/Pisinger berichten in ihrem Konstruktionstest ausdrücklich einen deutlichen Qualitätsabstand der schnellen Einfügeheuristiken. Deshalb ist Greedy hier ein kontrollierter Einstieg und Vergleich, keine Erwartung, dass einmaliges Einfügen schon einen sehr guten Gesamtplan liefert [S1].

## 3. Konsequenz aus unseren negativen Ergebnissen

Im [Kohorten-/Mergekorridor-Finding](../findings/ddd_fractional_cabin_neighborhood_gate.md) waren einzelne Nachbarschaften schnell ausgeschöpft: Die K20-Mergekorridor-CP-Aufrufe benötigten zusammen nur 4,24 s ohne Verbesserung. Kleine Kabinenkohorten halfen K39 begrenzt, blieben aber hinter einem früheren globalen CP-Ergebnis. Das waren andere, insbesondere No-Wait-Konfigurationen; absolute Zielwerte sind kein Vergleich zum heutigen Waiting-Fall.

Die Arbeitshypothese lautet deshalb: **Die Freiheit des Änderungspakets ist mindestens so wichtig wie die Geschwindigkeit seiner Lösung.** Ein neuer Decoder, der wieder nur einen Stopp oder einen einzelnen Merge verändert und sonst alles festhält, wäre unzureichend. Das neue Paket verbindet mehrere Stationen über eine konkrete Passagierbedienung und erweitert sich entlang tatsächlicher Blockierungen. Waiting bietet zusätzliche Flexibilität; ob diese reicht, ist offen.

## 4. Eingabe, Ausgabe und Datenhaltung

Eingabe: unveränderte Problemdefinition, vollständiger validierter Bewegungsplan, ganzzahlige Passagierzuordnung, eine Bedienungsabsicht und ein Suchbudget. Eine Absicht enthält OD-Gruppe, angebotene Personenzahl, Kabine, Einstiegs-/Ausstiegsbesuch und erlaubte Stop-/Skip-Änderungen.

Ausgabe: entweder ein vollständig rekonstruierter zulässiger Plan samt Passagierbilanz, oder ein erklärter Fehlschlag. Unterscheiden: fehlende Bedienungsalternative, Ressourcenblockierung, fehlender legaler Wartepunkt, Kapazität, Boundary, Horizont und ausgeschöpftes Suchbudget. Ein Budgetabbruch heißt nicht „unzulässig“.

Pro Ressource einen geordneten Kalender von Eintritten, Räumzeiten und individuellen Folgeabständen führen. Jede Reservierung trägt Kabinen-/Besuchs-ID, Routenoption und Boundary-Kennzeichen. Ressourcenlisten sind Kandidatenindizes; die tatsächliche Paarbedingung bleibt maßgeblich. Nur den unmittelbaren Vorgänger zu prüfen ist ohne Nachweis bei verschiedenen Räumzeiten/Headways nicht ausreichend.

Änderungen erfolgen transaktional: alte Reservierungen der veränderbaren Pfadteile herausnehmen, Kandidat konstruieren, vollständig prüfen, dann gemeinsam übernehmen oder zurückrollen. Unveränderbare Start-/Boundary-Belegungen bleiben immer erhalten. Ein entfernter Planungseintrag bedeutet niemals das Verschwinden einer physischen Kabine.

## 5. Die physische Zeitfensterrechnung

Die vorhandenen `DddRouteOption`/`DddResourceUsage` sind die semantische Grundlage. Für einen Besuch mit Eintrittstick t und Exit-Wait w gelten je Ressourcennutzung:

```text
next(t,w) = t + duration + w
enter(t,w) = t + enter_offset + alpha*w
clear(t,w) = t + clear_offset + beta*w
alpha,beta in {0,1}
```

Für die neue Nutzung n und eine aktive feste Nutzung j derselben Ressource gilt genau die Reihenfolgealternative:

```text
clear_n + separation_n <= enter_j
ODER
clear_j + separation_j <= enter_n
```

`separation_n/j` kommt aus der jeweiligen Nutzung, mit dem vorhandenen Ressourcen-Fallback. Kein neuer pauschaler Headway. Sonderregeln für Boundary-only-Ressourcen müssen identisch zum Referenzmodell bleiben.

Bei festem t und einer gewählten Route beschreibt jedes Konfliktpaar einen verbotenen Bereich von w. Auf ganzzahligen Ticks ist ein Konflikt die Schnittmenge aus:

```text
clear_n(w) + separation_n >= enter_j + 1
enter_n(w) <= clear_j + separation_j - 1
enter_n(w) <= H
```

Die letzte Bedingung berücksichtigt die Aktivierung im endlichen Vertrag. Weil die Koeffizienten 0 oder 1 sind, kann dieser Bereich durch Intervallgrenzen bestimmt werden. Von `[0,W]` die Vereinigung der verbotenen Bereiche abziehen. Bei SKIP gilt w=0; alle zusätzlichen Wartebedingungen des bestehenden Modells bleiben erhalten.

**Dieser lokale Intervallschritt kann ohne Enumeration von bis zu 1,2 Milliarden Mikrosekundenwerten arbeiten.** Er löst nur den festgelegten lokalen Fall exakt. Die kombinierte Suche über mehrere Warteentscheidungen, Stopps und Kabinen bleibt heuristisch.

Warten verschiebt nicht einfach alles: Bei einer bereits betretenen Plattform kann die Eintrittszeit unverändert bleiben und die Räumzeit wachsen. Eine spätere Merge-Einfahrt kann also zugleich eine andere Kabine auf der Plattform blockieren. Deshalb werden stets alle Ressourcen der Bewegung geprüft.

### Mehrere Besuche und erlaubte Warteorte

Ein nachgelagerter Konflikt auf einem SKIP-Abschnitt erzeugt eine Einschränkung am letzten veränderbaren erlaubten Exit. Dessen Warteentscheidung wird erneut geöffnet; anschließend werden alle dazwischenliegenden und nachfolgenden Belegungen neu berechnet. Falls kein solcher Exit existiert, muss eine andere Route/Bedienung oder eine blockierende Kabine verändert werden.

Nicht nur den frühesten Zeitpunkt behalten: Spätere Abfahrten können einen folgenden Merge ermöglichen, während eine frühere Ankunft dort mangels Warteort scheitert. Genau diese Art Informationsverlust motiviert SIPP-IP [S3].

Für den ersten Pilot: Warteintervalle einschließlich Herkunft speichern; konkrete Kandidaten an Intervallgrenzen, dem bisherigen Wartewert und aus rückgerechneten Folgekonflikten erzeugen. Bei späteren Demand-Profilen Release-Grenzen ergänzen. Mit kleiner Beam-Breite zunächst 1 und 8 vergleichen. Diese Auswahl ist ausdrücklich unvollständig; Intervallenden allein sind ohne weiteren Beweis keine ausreichende Menge für ein globales Optimum. Jeder materialisierte Pfad wird unabhängig validiert.

## 6. Einfügung und Reparatur: konkreter Ablauf

1. **Absicht auswählen.** Zunächst besonders teure/unbediente OD-Gruppen betrachten. Kandidaten über mehrere Kabinen und Besuchspaare verteilen. Für den Pilot q=1 und die maximal mögliche Teilgruppe bis Kapazität 8 versuchen; mittlere Gruppengrößen bleiben eine dokumentierte heuristische Auslassung.
2. **Gekoppelte Bedienung erzeugen.** Einstieg am Ursprung und Ausstieg am erlaubten Zielbesuch gemeinsam auf STOP setzen, falls nötig. Der gerichtete Ring und die bestehende Direct-Ride-Semantik bestimmen die Strecke. Nicht lediglich den Einstiegsstopp verbessern.
3. **Pfadteil öffnen.** Ab der frühesten betroffenen Entscheidung neu planen. Falls davor zusätzliche Verzögerung nötig ist, bis zum letzten veränderbaren legalen Exit zurückgehen. Alle zeitlich betroffenen Folgebesuche bis zur Horizontabdeckung gehören dazu; nicht am Ausstieg abschneiden oder eine unerreichbare Rückkehr zur alten Zeit erzwingen.
4. **Zeitfenster suchen.** Zunächst gegen die übrigen festen Reservierungen. Vorhandene Waits dürfen auch verkürzt werden. Unveränderte Stop-/Skip-Entscheidungen dienen als erster Versuch, nicht als dauerhaft unantastbare Vorschrift.
5. **Blockierer aufnehmen.** Scheitert der Versuch, liefert die Kalenderabfrage die verursachende Kabine und Ressource. Deren relevanten Pfadteil ebenfalls öffnen und alternative Prioritäten/zulässige Ressourcenreihenfolgen versuchen. Reihenfolgen können nur durch modellkonforme Bewegungen wechseln; kein beliebiges Überholen auf einer festen Strecke.
6. **Begrenzt erweitern.** Pilotstaffel 1→2→4→8 betroffene Kabinen, innerhalb eines Gesamtzeitbudgets. Diese Werte sind Messparameter. Wenn fast alles an der Grenze scheitert, ist das ein Befund über die Restriktion und kein Beleg gegen größere koordinierte Änderungen. Wiederholte identische Reparaturzustände erkennen und abbrechen.
7. **Passagiere und Gesamtplan prüfen.** Erst eine vollständige physische Reparatur darf bewertet werden. Zulässige neue Belegungen rekonstruieren, Passagierzuordnung aktualisieren und alle Kostenänderungen bilanzieren. Nur der vollständige Schritt kann übernommen werden.

Als erster zusätzlicher Route-Operator darf ein anderweitiger STOP entfernt werden, wenn nach einer zulässigen Passagier-Neuzuordnung dort keine verpflichtende Bedienung verbleibt. So kann das Paket Zeit zurückgewinnen. Stopps mit übernommenen Ein-/Ausstiegsverpflichtungen dürfen nicht kommentarlos entfallen.

```text
try_service(plan, intent, budget):
    for repair_scope, priority in bounded_conflict_expansions:
        transaction = open_affected_suffixes(plan, repair_scope)
        paths, blockers = search_legal_wait_windows(transaction, intent)
        if paths missing:
            record_reason_and_expand(blockers)
            continue
        assignment = repair_integer_passenger_assignment(paths)
        if independent_full_validation(paths, assignment):
            retain_candidate_with_full_objective(paths, assignment)
    return best_valid_candidate_or_explained_failure
```

## 7. Passagierbewertung ohne versteckten globalen Solve pro Versuch

Die schnelle Zuordnung verwendet die vorhandene Direct-Ride-Erzeugung und ganzzahlige Mengen mit Kapazitätsprüfung auf jedem befahrenen Abschnitt. Unverändert zulässige Zuordnungen können zunächst erhalten bleiben; ungültig gewordene werden entfernt und ihre Personen neu zugeordnet oder korrekt unbedient bilanziert. Die angefragte Bedienung wird explizit berücksichtigt. Das ist eine zulässige heuristische Zuordnung, kein Optimum für die neue Bewegung.

Wir planen offline. Zukünftige Fahrgastzuordnungen sind veränderbar. Nur tatsächliche Anfangsverpflichtungen beziehungsweise Verpflichtungen aus einem für diesen Versuch eingefrorenen Präfix müssen erhalten bleiben. Nicht alle Passagiere eines gespeicherten Plans gelten bereits als eingestiegen.

Für das aktuelle Journey-Time-Ziel ist der Beitrag einer bedienten Person `alight - release`, einer unbedienten `H - release`. Beispiel, rein illustrativ: Acht zuvor unbediente Personen erreichen ihr Ziel bei t=500, Release 0. Ihr Nutzen ist `8*(1200-500)=5600` Passagiersekunden. Verzögert die Reparatur andere Zielankünfte insgesamt um 700 Passagiersekunden und verursacht keine weitere Verdrängung, sinkt das Gesamtziel um 4900. Spätes Boarding allein ist noch kein Nutzen.

Greedy wählt die beste gemessene Verbesserung. Für Regret-2 werden für dieselbe Nachfrageportion Kosten der besten und zweitbesten verschiedenen Bedienungsalternativen verglichen. Eine identische Lösung mit anderem Wartewert darf keine künstlich unabhängige Alternative erzeugen. Nichtbedienung bleibt eine endliche Rückfalloption. Die Bewertungen müssen zum selben Ausgangsplan gehören; nach Ressourcen-/Zuordnungsänderungen abhängige Cache-Einträge verwerfen.

Den vorhandenen Fixed-Movement-Passenger-IP für die unveränderte Baseline und wenige ausgewählte Bewegungspläne nachschalten. Damit erkennen wir Fehler der schnellen Zuordnung und eine reine Assignment-Verbesserung. MIP-frei ist der vorgeschlagene Bewegungskern; ein nachgeschalteter IP ist separat auszuweisen. Seine Laufzeit zählt zum Gesamtbudget. Bei Zeitlimit nur den gültigen Incumbent als UB verwenden, nicht ein bewiesenes Assignment-Optimum behaupten.

## 8. Vorhandener Code und neue Verantwortlichkeiten

Alle Pfade relativ zum Software-Repository:

| Vorhandener Ort | Verwendung |
|---|---|
| `src/ropeway_skip_stop_optimization/optimization/ddd/models.py` | Starts, RouteOptions, Ressourcenoffsets und individuelle Headways als einzige Physikdefinition |
| `.../ddd/trajectory_problem.py` | Waiting-Policy und Domänenbedingungen; die enumerierende `wait_values_seconds` nicht als schnellen Suchkern verwenden |
| `.../ddd/reference.py` | `build_ddd_reference_visit`, Trajektorienrekonstruktion und unabhängige Referenzprüfung; die quadratische globale Konfliktsuche nicht pro lokalem Intervalltest aufrufen |
| `.../ddd/cp_sat_certificate.py` | Vorbild für Wiederherstellung der Boundary-Belegungen aus gespeicherten CP-Plänen |
| `.../ean/optimizers/fixed_movement_passenger_model.py` | `build_ean_fixed_movement_rides` und nachgeschalteter Assignment-IP; Ride-Erzeugung allein validiert keine Bewegung |
| `.../ean/passenger_objective.py` | Kanonische Kosten für bediente/unbediente Personen |
| `.../ean/validation.py`, `headway_separator.py`, `horizon_contract.py` | Unabhängige Prüfung des vollständigen Ergebnisses unter dem akzeptierten Vertrag |
| `benchmarks/output/ddd_horizon_contract_gate/waiting_best_audit.json` | Beste aktuelle Baseline erneut passagierbewertet; Verweis auf ursprünglichen Run im Audit |

Neu benötigt werden ein Kalender mit Transaktionen, lokale Warteintervallrechnung, begrenzte Pfadreparatur und Service-Kandidaten/Zuordnungsbewertung. Diese Verantwortlichkeiten trennen, aber zunächst gemeinsam an einem kleinen Pilot erproben. Keine parallele zweite Graph- oder CBS-Engine beginnen.

## 9. Reihenfolge und messbare Entscheidung

**Pilot A: Korrektheit der Zeitfenster.** Unveränderter K39-Plan muss den Roundtrip bestehen. Auf kleinen Konfliktfällen alle w eines kleinen Tickbereichs enumerieren und mit den berechneten Intervallen vergleichen. Einschließen: unterschiedliche Headways, verlängerte Plattformbelegung, unmögliche Verzögerung auf SKIP, rückwärts benötigtes Exit-Wait, Boundary sowie Eintritte bei H und H+1. Diese Tests prüfen die neue mathematische Abkürzung.

**Pilot B: Tatsächliche Bewegungsfreiheit.** Aus drei in der Baseline teuer/unbedient gebliebenen OD-Gruppen ein reproduzierbares Set von 100 Anfragen bilden. Zuerst einzelne Kabine, danach konfliktgesteuerte Erweiterung vergleichen. Innerhalb 30 s prüfen, ob mehrere verschiedene vollständige Bewegungspläne entstehen; danach p50/p95 der Anfragen messen. Ziel p95 unter 100 ms bleibt eine Projektmesslatte, keine Literaturzusage. Vollständige Validierung und Assignment-Laufzeit separat sowie insgesamt ausweisen. Seeds, Kandidaten und Reparaturgrenzen speichern.

**Pilot C: Zielverbesserung.** Nur wenn B funktioniert: Greedy und Regret mit gleichen Kandidaten und Startplänen für 30/120/600 s sowie drei Seeds vergleichen. Unveränderte Bewegung mit reiner Passagiernachoptimierung als Kontrolle. Zielverlauf, Zahl verschiedener Pläne, Zahl verbessernder Schritte, bediente Personen und Plateauzeit erfassen. Erst bei messbarer Verbesserung ALNS ergänzen.

Bei Misserfolg unterscheiden:

- Keine zulässigen Bewegungsalternativen: Kandidatenumfang, fehlender Warte-Spielraum oder zu große Konfliktketten untersuchen; mehr äußere ALNS-Iterationen lösen das nicht automatisch.
- Zulässige Bewegungen, kein Nutzen: Passagierbewertung und gemeinsame Bedienungs-/Stopentfernungsoperatoren sind der nächste Ansatzpunkt.
- Gute Vorschläge, langsame Reparatur: Kalender/Propagation profilieren; erst dann feste Ressourcenreihenfolgen mit graphbasierter Zeitpropagation [S4] als Alternative beurteilen.
- Schnelle Verbesserungen, frühes Plateau: größere zusammenhängende Entfernungs-/Einfügepakete mit ALNS testen.

## 10. Erwartung und Quellen

Die größte Hoffnung ist, viele koordinierte Änderungen günstiger als einen neuen integrierten Solve auszuwerten. Die größte Unsicherheit ist, ob im dichten K39-Ring ausreichend kleine reparierbare Pakete existieren. Eine bessere UB halte ich für einen plausiblen Testgegenstand; einen Durchbruch oder selbstständiges Schließen des globalen Gaps kann diese Heuristik nicht versprechen. Eine bessere Lösung schließt den Gap nur insoweit, wie sie die UB senkt; der Kern erzeugt keine neue globale LB.

- **[S1]** Ropke, S.; Pisinger, D. (2006). *An Adaptive Large Neighborhood Search Heuristic for the Pickup and Delivery Problem with Time Windows*. Transportation Science 40(4), 455–472. [DOI](https://doi.org/10.1287/trsc.1050.0135), [vom Autor bereitgestelltes Manuskript, Stand 8. August 2005](https://www.researchgate.net/publication/220413334_An_Adaptive_Large_Neighborhood_Search_Heuristic_for_the_Pickup_and_Delivery_Problem_with_Time_Windows). Für die Operatoren Abschnitte 3.2.1/3.2.2, für den isolierten Konstruktionstest Abschnitt 4.2 gelesen; Manuskript und Verlagsfassung unterscheiden.
- **[S2]** Haneyah, S.; Hurink, J.; Schutten, M.; Zijm, H.; Schuur, P. (2011). *Planning and Control of Automated Material Handling Systems: The Merge Module*. [Universitäts-Volltext](https://ris.utwente.nl/ws/portalfiles/portal/5374531/Plannin_and_Control_GOR.pdf). Insbesondere Prozesse A/B/C in Abschnitt 2.
- **[S3]** Ali, Z. A.; Yakovlev, K. (2023). *Safe Interval Path Planning with Kinodynamic Constraints*. AAAI 37(10), 12330–12337. [DOI/Verlagsseite](https://doi.org/10.1609/aaai.v37i10.26453), [Volltext](https://ojs.aaai.org/index.php/AAAI/article/view/26453/26225). Insbesondere Gegenbeispiel bei fehlender Wartefreiheit und Interval Projection.
- **[S4]** Gholami, O.; Törnquist Krasemann, J. (2018). *A Heuristic Approach to Solving the Train Traffic Re-Scheduling Problem in Real Time*. Algorithms 11(4), 55. [DOI](https://doi.org/10.3390/a11040055), [institutioneller Eintrag](https://bth.diva-portal.org/smash/record.jsf?pid=diva2%3A1200413). In dieser Vertiefung Abstract geprüft; Volltextabruf fehlgeschlagen. Keine Übernahme ungeprüfter Algorithmusdetails.
- **[S5]** Dong et al. (2020). *Integrated optimization of train stop planning and timetabling for commuter railways with an extended adaptive large neighborhood search metaheuristic approach*. Transportation Research Part C 117, 102681. [DOI](https://doi.org/10.1016/j.trc.2020.102681). Publisher-Vorschau/Abstract; konkrete interne Operatoren hier nicht als überprüft dargestellt.
