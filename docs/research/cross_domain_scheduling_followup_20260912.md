# Fördertechnik und andere Schedulinggebiete: vertiefender Vergleich

Stand: 12. September 2026. Recherche, keine neue Implementierung oder Laufkampagne. Ergänzt [automatische Haltemusterwahl](automatic_stop_pattern_design_20260912.md) und [gebietübergreifende Recherche vom 10. September](ropeway_cross_domain_algorithms_20260910.md).

## Fragestellung und Ergebnis

Gesucht werden Verfahren, die ein nachfragegerechtes Angebot selbst auswählen und mit einem zeitlich konfliktfreien Betrieb verbinden. Die Seilbahn kombiniert drei Ebenen: Auswahl der STOP-/SKIP-Folgen, ganzzahlige Beförderungszuordnung und Belegung gemeinsamer Ressourcen durch bewegliche Kabinen mit begrenztem Exit-Waiting. Keine der hier geprüften Quellen liefert ein unmittelbar austauschbares Komplettmodell für diese Kombination.

Die zusätzliche Recherche liefert konkrete Formulierungsquellen. Besonders prüfenswert sind relative Startabstände aus dem Hoist-Scheduling, Reihenfolge-/Differenzconstraint-Modelle aus Blocking Job Shops und gemeinsame Alternativenwahl/Timing aus der integrierten Prozessplanung. Reine Förderband-Beladungsprobleme sehen unserer Anlage ähnlich, haben aber oft eine wesentlich einfachere Bewegungsseite.

## 1. Closed-loop sortation: Beladung umlaufender Träger

**Briskorn, Emde, Boysen (2017): Scheduling shipments in closed-loop sortation conveyors.** Journal of Scheduling 20, 25–42; online 2016. [Verlag und Abstract](https://link.springer.com/article/10.1007/s10951-016-0498-5).

Die Arbeit untersucht die Zuordnung endlicher Sendungen zu umlaufenden Sortierschalen, unterschiedliche Freiheiten auf den Zuführungen und ein-/zweigerichtete Systeme. Ziel ist der Makespan. In den untersuchten Fällen schneiden geeignete Prioritätsregeln überraschend gut gegenüber aufwendiger Optimierung ab. Das ist empirische Evidenz für diese Fälle, kein Approximationssatz für Ropeway.

**Übertragung:** Ein stabiles Bewegungsangebot zuerst als kontrollierbares Objekt herstellen, anschließend seine Kapazität intelligent belegen. Beladungsprioritäten wären ein Vergleichsmaßstab. Eine einfache Belegungsregel erzeugt aber keine Haltemuster und löst keine bewegungsabhängigen Mergekonflikte. Bei Ropeway darf die allgemeine Integer-Passagierzuordnung wegen des Odd-Cycle-Gegenbeispiels nicht ungeprüft durch Min-Cost-Flow ersetzt werden.

**Zugriff:** Verlagsabstract und öffentlich sichtbare Anhänge, kein vollständiger Haupttext. Die konkreten besten Prioritätsregeln werden daher hier nicht behauptet.

## 2. Fördertechnik mit begrenzten Puffern

**Fan und Su (2022): Mathematical Modelling and Heuristic Approaches to Job-shop Scheduling Problem with Conveyor-based Continuous Flow Transporters.** Computers & Operations Research 148, 105998. [Verlagsdarstellung](https://www.sciencedirect.com/science/article/pii/S0305054822002313).

Maschinen sind durch Fördersegmente verbunden. FIFO und begrenzte Puffer koppeln die Operationen: Eine abgeschlossene Bearbeitung kann die Maschine weiter blockieren. Die Autoren nutzen mathematische Programmierung für kleine Fälle und Simulated Annealing mit einer speziellen Nachbarschaft für größere Fälle; optimiert wird insbesondere die Eintrittsreihenfolge.

**Übertragung:** Relevant sind die Blockierungsbedingungen und die Bedeutung der Einspeisereihenfolge. Eine globale FIFO-Reihenfolge wäre bei unseren Bypässen unzulässig streng. Das SA-Verfahren wäre eine eigene angepasste Suche und widerspräche dem bisherigen Wunsch, die Suche vorhandenen Engines zu überlassen. Deshalb Formulierungsquelle, keine Empfehlung für einen weiteren selbstgebauten Controller.

**Zugriff:** Abstract, Einleitung und Verlagsauszüge.

## 3. Blocking Job Shop: Ressourcenreihenfolgen statt Zeitnetz

**Mascis und Pacciarelli (2002): Job-shop scheduling with blocking and no-wait constraints.** EJOR 143, 498–517. [Verlag](https://www.sciencedirect.com/science/article/abs/pii/S0377221701003381), [Forschungsinstitut-PDF](https://homepages.laas.fr/ehebrard/ExperimentCP2011/Results/Entrees/2011/5/3_Job_shop_with_%22no_wait%22_constraints_files/jtl_mascis.pdf).

Alternative Graphs erweitern die klassische Job-Shop-Darstellung um Blocking und No-Wait. Maschinenreihenfolgen werden durch alternative Kanten ausgedrückt. Relevant ist die Unterscheidung zwischen erlaubten simultanen Übergaben und unzulässigen Blockierungszyklen.

**Eigene Ableitung für Ropeway:** Wenn Routen, Aktivität, alle notwendigen Fallentscheidungen und Ressourcenreihenfolgen feststehen, kann eine Belegungsbedingung zu einer Differenzbedingung zwischen Ereigniszeiten werden. Beispielsweise hält ein Exit bis zur tatsächlichen Ausfahrt plus Schutzzeit; der nächste Eintritt muss dahinter liegen. Das ist genauer als eine pauschale Stations-Servicezeit.

Für einen aktiven Besuch mit Dauer d und Waiting w gilt t_next = t + d + w. Ressourcenzeitpunkte mit Waiting-Koeffizient 0 oder 1 lassen sich dadurch als t + Konstante oder t_next + Konstante ausdrücken. Unter-/Obergrenzen für Waiting werden ebenfalls Differenzbedingungen. Ein widersprüchlicher gewichteter Zyklus kann dann eine kleine Gruppe unvereinbarer Entscheidungen identifizieren.

**Grenze:** Nur das vollständig festgelegte temporale Teilproblem wird einfach. Die Wahl der Reihenfolgen, aktiven Routen und Passagiere bleibt kombinatorisch. Waiting-Freigabe und Horizontpräsenz benötigen passende Fallentscheidungen; größere Waiting-Schrittweiten können zusätzliche Kongruenzbedingungen verursachen. Ein beliebiger gerichteter Zyklus ist nicht automatisch ein Konflikt.

Diese Richtung war bereits am 10. September dokumentiert. Der aktuelle Fixed-assignment-CP-Lauf ist kein vollständiger Test dieses Ansatzes: Er lässt weiterhin zahlreiche Reihenfolgen offen. CP-SAT/IBM enthalten selbst Scheduling-Propagation; die Darstellung allein garantiert keinen Fortschritt.

## 4. Hoist-Scheduling: verbotene relative Startabstände

**Che, Yan, Yang und Chu (2010): Optimal cyclic scheduling of a hoist and multi-type parts with fixed processing times.** IJPR 48, 1225–1243. [Verlagsabstract](https://www.tandfonline.com/doi/full/10.1080/00207540802552659).

Die Arbeit behandelt festdauernde No-Wait-Abläufe verschiedener Teile. Eintrittszeiten sind zentrale Entscheidungen. Verbotene Intervalle werden berechnet; ein Branch-and-Bound-Verfahren durchsucht die verbleibenden Bereiche. Die günstigen Komplexitätseigenschaften hängen von der eingeschränkten Problemklasse ab.

**Eigene Übertragung, ausdrücklich nicht das Originalmodell:** Eine Kabinentrajektorie mit festem internem Zeitverlauf hat je Ressource Belegungen [d+a, d+b), wobei d ihr noch frei wählbarer Dispatch ist. Für zwei solche Belegungen ist eine Überschneidung genau dann vorhanden, wenn

`a_i - b_j < d_j - d_i < b_i - a_j`.

Die Vereinigung dieser offenen verbotenen Intervalle über alle gemeinsamen Ressourcen beschreibt unzulässige Dispatchdifferenzen. Bereits in a/b enthaltene Schutzzeiten dürfen nicht nochmals addiert werden. Grenzgleichheit entspricht nur dann einer erlaubten Übergabe, wenn der Originalvertrag dies zulässt.

Man könnte Muster und Anzahl gemeinsam wählen und ihre Dispatchzeiten in Gurobi oder CP-SAT platzieren. Die vielen inneren Zeiten wären dann abgeleitet, statt unabhängig optimiert oder als Zeitnetzkopien angelegt zu werden. Anfangsreservierungen und zusätzliche Zustandskollisionen müssen gesondert erfasst werden; Paarintervalle sind kein Ersatz für höherkapazitive Ressourcenbedingungen.

**Waiting-Grenze:** Feste legal gewählte Warteprofile können Bestandteil der Vorlagen sein. Frei variables Waiting verschiebt die inneren Belegungen und hebt die einfache Vorberechnung auf. Ein kleiner Vorlagenpool wäre deshalb eine eingeschränkte Primalsuche. Er liefert keinen globalen Bound für das vollständige Modell. Nachfragefreigaben und Rückkehrhorizont schränken die Dispatchbereiche zusätzlich ein.

**Neuheitsabgleich:** Unsere früheren Safe-Interval-Pläne verwenden verbotene Zeiten gegen einen bereits belegten Kalender. Hier würden relative Abstände zwischen gemeinsam verschiebbaren kompletten Abläufen verwendet. Es ist eine konkrete Variante der Trajektorienidee, keine völlig neue Forschungsfamilie. Auch die verbleibende Paarzahl und die Passagiergrößen müssen gemessen werden.

**Zugriff:** Verlagsabstract; keine Behauptung, den vollständigen Originalalgorithmus reproduziert zu haben.

## 5. Waferfertigung, Petri-Netze und Umlaufbestand

**Mashaei und Lennartson (2012): A Universal Framework for Lean Design and Control of Automated Material Handling Systems.** ETFA. [Autoren-PDF](https://publications.lib.chalmers.se/records/fulltext/171011/local_171011.pdf).

Das Paper behandelt Palettensysteme mit Puffern, Reihenfolgeänderungen, Bypassmechanismen und Work-in-process. Ein CPN-Modell verbindet Struktur- und Steuerungsbetrachtung; die Studie ist keine fertig übernehmbare globale Optimierungsengine.

**Ergänzende Quelle:** Lee (2008), *A Review of Scheduling Theory and Methods for Semiconductor Manufacturing Cluster Tools*. [WSC-Paper](https://www.informs-sim.org/wsc08papers/263.pdf). Für wiederholte festgelegte Abläufe beschreibt die Literatur zeitbehaftete Ereignisgraphen und Durchsatzanalysen.

**Übertragung:** Kabinenanzahl als Umlaufbestand betrachten und anhand konkreter Ressourcen erklären, wann mehr Kabinen zusätzliche Bedienung ermöglichen und wann sie nur zusätzliche Blockierung erzeugen. Ein optimaler stationärer Zyklus ist noch kein optimaler endlicher Betrieb mit neun Nachfragefreigaben, leerem Reservoirstart und Rückkehrpflicht. Max-Plus/Petri-Netze waren bereits in unserer früheren Recherche enthalten.

## 6. Integrierte Prozessplanung: Alternativen und Timing gemeinsam

**Zhang, Yu und Wong (2021): A graph-based constraint programming approach for the integrated process planning and scheduling problem.** COR 131, 105282. [Verlagsdarstellung](https://www.sciencedirect.com/science/article/pii/S0305054821000745).

Die Autoren bilden alternative Fertigungswege mit AND/OR-Graphen ab und optimieren Auswahl sowie zeitliche Belegung gemeinsam in IBM CP Optimizer. Präsenzabhängigkeiten und optionale Intervalle beschreiben zusammenhängende Alternativen, ohne jede vollständige Prozessfolge aufzuzählen.

**Übertragung:** Ein wählbares Bedienungsprogramm kann mehrere Besuchsentscheidungen gemeinsam aktivieren. Die Passagierzuordnung muss dabei offen bleiben. Eine bloße OR-Verzweigung STOP/SKIP je Besuch ist bereits nahe an unserem nativen IBM-Kern; das Paper rechtfertigt daher keinen Neubau desselben Modells. Ein tatsächlicher Unterschied wäre eine kompakte gemeinsame Struktur ganzer Bedienungsprogramme, deren Reduktion experimentell nachzuweisen wäre.

**Zugriff:** Verlagsabstract und Einleitung. Berichtete Benchmarkvorteile gelten für IPPS, nicht für unsere Passagiere und Reservoirregeln.

## 7. Zeitkritische Datennetze: Routen, Warten und Konfliktkonfigurationen

**Vlk, Hanzálek und Tang (2021): Constraint programming approaches to joint routing and scheduling in time-sensitive networks.** CIE 157, 107317. [Verlagsdarstellung](https://www.sciencedirect.com/science/article/pii/S0360835221002217).

Sie vergleichen CP-Formulierungen, darunter explizite optionale Warteintervalle, und LBBD für gemeinsame Routenwahl und Scheduling. Das ist eine konkrete Quelle für Ressourcen-, Warte- und Präsenzmodellierung. Periodische Nachrichten und feste Nutzlast unterscheiden sich von frei besetzten Kabinen.

**Falk, Dürr und Rothermel (2020): Time-Triggered Traffic Planning for Data Networks with Conflict Graphs.** RTAS. [Autoreninstitution](https://www2.informatik.uni-stuttgart.de/cgi-bin/NCSTRL/NCSTRL_view.pl?engl=0&id=INPROC-2020-28).

Vollständige Streamkonfigurationen bilden Knoten eines Konfliktgraphen; kompatible Mengen entsprechen unabhängigen Knotenmengen. Der Graph kann aus einem kleinen Konfigurationspool wachsen.

**Übertragung:** Physikalisch zulässige Kabinenkonfigurationen einschließlich Waiting kombinieren. Für paarweise exklusive Ressourcen lassen sich Konflikte vorab bestimmen; Nachfragekonkurrenz, Flottenlimit und ganzzahlige Passagiere brauchen zusätzliche Masterbedingungen. Das ist eng verwandt mit unserer Trajektorienauswahl. Ein endlicher Konfigurationspool beschränkt den Suchraum; seine Qualität bestimmt mit, ob gute Muster überhaupt enthalten sind.

**Reproduzierbarkeit:** [TSNKit](https://tsnkit.readthedocs.io/en/latest/schedule.html) dokumentiert unter anderem CP-WA und CG sowie native Listenverfahren. CG bezeichnet dort den Konfliktgraphansatz, nicht automatisch Column Generation. Die Software ist ein Referenzfundus, kein unverändert verwendbares Ropeway-Backend. TSNKit war bereits in unseren Dokumenten erwähnt.

## 8. Simulationsoptimierung und Backpressure

**Simulation optimization for parcel hub scheduling problem in closed-loop sortation system with shortcuts (2023).** [Verlagsdarstellung](https://www.sciencedirect.com/science/article/pii/S1569190X23000060). Die Studie kombiniert Simulation eines stochastischen Sortiersystems mit einer hybriden populationsbasierten Suche über Lkw-Zeitpläne und Dockzuordnung.

**Capacity-Aware Backpressure Traffic Signal Control (2015).** [IEEE](https://ieeexplore.ieee.org/document/6979216/). Die Arbeit behandelt den Unterschied zwischen idealisierten unendlichen Warteschlangen und endlichen Straßenkapazitäten; kapazitätsbewusster Druck soll Blockierung und Stauausbreitung vermeiden.

**Übertragung:** Nachfrage-/Kapazitätsdruck könnte Kabinenrollen, Freigaben oder Dispatchprioritäten steuern. Solche Politiken sind schnelle Heuristiken. Sie ergeben keine globale Unserved-Schranke für unseren endlichen Betrieb. Eine eigene Simulations-/Suchschleife wäre erhebliche Zusatzarbeit und ist nicht die derzeit bevorzugte Entwicklungsrichtung. Diese Methoden werden als reale Alternativen dokumentiert, nicht als unmittelbar zugesagte Integration.

## 9. Aktuelle Formulierungsprüfung statt Performanceversprechen

**Horváth (2026): A unified modeling framework and improved formulations for single-hoist cyclic scheduling.** [Preprint vom März 2026](https://arxiv.org/html/2603.24316v1), [verlinkte Referenzimplementierung](https://github.com/hmarko89/CyclicHoistScheduling).

Die Studie untersucht widersprüchliche Benchmarkoptima, Modellierungsunterschiede und stärkere CP-/MIP-Formulierungen. Sie ist besonders nützlich als Beispiel dafür, warum gleicher Problemname keine gleiche zulässige Lösungsmenge garantiert. Wir sollten aus anderen Papers weder ausgelassene Lade-/Entladebedingungen noch eingeschränkte Zyklen still übernehmen. Die Existenz der verlinkten Bibliothek ist dokumentiert; sie wurde hier nicht installiert oder ausgeführt.

## Priorisierung für Ropeway

Die folgende Einstufung ist unsere technische Einschätzung, keine aus den Papers geschätzte Erfolgswahrscheinlichkeit.

| Ansatz | Konkreter möglicher Gewinn | Hauptgrenze | Einordnung |
|---|---|---|---|
| Gemeinsam verschiebbare vollständige Ablaufvorlagen | Innere Zeitvariablen eliminieren, ganze Dispatchabstände prüfen | Internes Waiting muss fixiert oder durch Vorlagen beschränkt werden | Stärkster zusätzlicher Kandidat für eine bewusst eingeschränkte Primalsuche |
| Ressourcenreihenfolgen + temporale Differenzbedingungen | Timing nach diskreten Entscheidungen billig prüfen; erklärbare Konflikte | Die diskreten Entscheidungen selbst bleiben schwierig | Technisch relevanter Diagnose-/Formulierungsbaustein, bereits früher erkannt |
| AND/OR-Serviceprogramme in bestehendem CP/IBM | Koordinierte Musterauswahl ohne Fixierung der Passagiere | Ähnlichkeit zum schon implementierten Besuchskern | Erst strukturellen Unterschied nachweisen |
| Konfigurations-Konfliktgraph | Kleine kombinatorische Auswahl bei gutem Pool | Poolabdeckung, Konfliktzahl, Integerpassagiere | Bestehenden Trajektorienansatz daran messen, keinen pauschalen Neustart |
| Petri-/Max-Plus-Analyse | Engpass und nötigen Umlaufbestand erklären | Stationäre/strukturierte Annahmen | Gute wissenschaftliche Ergänzung |
| Förderband-Prioritäten, SA, Backpressure | Schnelle Kandidaten/Steuerung | Kein übertragbarer globaler Gap; eigener Adapter/Controller | Nicht unmittelbar priorisiert |

Die Ergänzung ändert die vorige Empfehlung insofern: Ein wiederkehrendes Haltemuster reduziert Stopentscheidungen, aber lässt fast das gesamte Timingproblem stehen. Eine vollständige relative Ablaufvorlage reduziert zusätzlich zeitliche Freiheitsgrade. Das ist ein echter weiterer Trade-off. Ob solche Vorlagen gute Skip-Stop-Lösungen enthalten, ist offen. Eine faire Diagnose muss deshalb Musterwahl, interne Zeitflexibilität und freie Passagierzuordnung getrennt vergleichen.

Ein guter validierter Plan aus einer eingeschränkten Familie kann unseren All-Stop-Nachweis trotzdem liefern. Sein eigener optimaler Wert oder Solver-Bound darf aber niemals als globaler Wert des vollständigen Skip-Stop-Modells ausgegeben werden.
