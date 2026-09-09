# Ropeway: Plan für schnelle Heuristiken und Verfahren außerhalb von MIP

Stand: 9. September 2026. Status: **offene Folgeschritte für Heuristiken und Nicht-MIP-Suche**. Der separat beauftragte G0-Vertrag liegt inzwischen in der [Referenz](../reference/finite_horizon_contract.md); empirische Befunde stehen im [G0-Finding](../findings/ddd_horizon_contract_gate.md). Der begrenzte Reservierungs-/Einfügepilot ist inzwischen [implementiert und getestet](../findings/ddd_reservation_insertion_gate.md): kleine UB-Verbesserung, Geschwindigkeitsziel verfehlt. Der Profil-/Integrationsschritt ist [abgeschlossen](reservation_insertion_implementation.md). Greedy/Regret und ALNS werden für diesen Pilot wegen des verfehlten Laufzeit-Gates nicht umgesetzt. Exakte neue Suchfamilien bleiben eine separate Forschungsoption, kein laufender Auftrag.

## 1. Entscheidung und Ziel

**Auf Grundlage des G0-Vertrags einen begrenzten diagnostischen Versuch mit passagierorientierter Einfügung und physikalischer Reservierung durchführen. ALNS nur ergänzen, wenn dieser Kern schnell genug ist. Ereignissuche, Decision Diagrams und CBS als getrennten Forschungsweg erhalten.** Der Nutzer hat den endlichen Horizont akzeptiert; eine Fortsetzung nach H ist keine zusätzliche Voraussetzung. Der konkrete G1-Entwurf steht im [Reservierungs- und Einfügekern](reservation_insertion_kernel.md).

Das kurzfristige Ziel ist ein unabhängig validierter, reproduzierbar besserer Fahrplan oder eine belastbare Diagnose, warum diese Konstruktion nicht hilft. Das längerfristige Ziel ist eine wirksame Suche mit gültigen globalen Schranken. Beides ist wissenschaftlich relevant, aber nicht dieselbe Aufgabe.

Die Priorität für Heuristiken folgt aus dem Ziel, vor der Präsentation am 21. September Ergebnisse zu erhalten. Die fachliche Prüfung exakter Ereignissuche und Decision Diagrams bleibt interessant; ihre Umsetzung ist wesentlich riskanter. Ein auswertbarer Stand soll am 18. September vorliegen; am 19./20. September ist Felix nicht verfügbar. Die Zeitbudgets unten sind selbst gesetzte Projektgrenzen, keine Literaturprognosen.

Dieser Plan konkretisiert den älteren [Demand-Driven Network Operations Planner](demand_driven_network_operations.md), insbesondere dessen Verbindung von Serviceintentionen, Reservierungsdecoder und Passagierbewertung. Er ergänzt die [Forschungslandkarte](../../../RESEARCH_CONCEPTS.md). Er ersetzt nicht die dokumentierten Modellverträge. Frühere Pläne sind Kontext, keine zusätzlichen Ausführungsaufträge.

## 2. Begriffe und Grenzen

| Klasse | Was sie liefern kann | Was daraus nicht folgt |
|---|---|---|
| Greedy, Regret, priorisierte Reservierung | Schnell konstruierte zulässige Fahrpläne, sofern die Konstruktion gelingt | Globale Optimalität oder garantierter Lösungsfund |
| ALNS, begrenzte Beam Search, lokale Reparatur | Verbesserungen innerhalb eines vorgegebenen Budgets | Automatisch enger werdende globale Untergrenze |
| Approximationsalgorithmus mit Faktor | Nachgewiesene Qualitätsgarantie für eine genau definierte Problemklasse | Übertragbarkeit dieser Garantie auf Ropeway |
| A*/ARA*, vollständige DP, Decision-Diagram-Suche, geeignete CBS-Varianten | Unter ihren Voraussetzungen Schranken und schließlich Optimalität | Praktisch kurze Laufzeit oder Korrektheit einer ungeprüften Übertragung |

Für die vollständige Ropeway-Kombination ist hier **kein schneller Algorithmus mit bewiesenem Approximationsfaktor** identifiziert. „Approx“ bezeichnet im Heuristikteil eine Näherungslösung, keine zugesagte 10-%-Garantie. Die Heuristiken sind selbst überwiegend Nicht-MIP-Verfahren; die beiden Teile unterscheiden vor allem schnelle Lösungssuche und Suche mit möglichem Optimalitätsnachweis. CP-SAT ist bereits ein SAT/CP-Hybrid, kein gewöhnliches MILP.

## 3. Ausgangsbefunde und gemeinsamer Vergleichsvertrag

Maßgebliche Befunde stehen im [Waiting-Gate](../findings/ddd_integrated_cp_sat_waiting_gate.md) und im [Warmup-Gate](../findings/ddd_cp_sat_warmup_gate.md):

- K39, Waiting: bisheriger Wert 1.022.076,357256, 1104/1280 Personen, nach 600 s; in der damaligen endlichen Domain unabhängig passagierbewertet.
- All-Stop K38: 399.287,271408, 1280/1280 Personen. Gleiche Nachfrage, aber andere Flotte und Anfangsanordnung; betriebliche Referenz, keine gültige K39-Lösung oder K39-Untergrenze.
- Die neuere Warmup-Paarung verbessert den rohen Zielwert nur um ca. 0,402 %. Nach G0 bestehen beide Warmup-Pläne die vereinheitlichte endliche EAN-Prüfung; der frühere Befund ist im [Horizon-Gate](../findings/ddd_horizon_contract_gate.md) eingeordnet.
- G0 vereinheitlicht die Aktivierung an H. Die zusätzlich gefundenen Konflikte unter Einbeziehung neuer Eintritte nach H liegen außerhalb des akzeptierten endlichen Problems und blockieren die nächsten Vergleiche nicht.
- Alte Reservoir-Modelle liefern keinen Beleg für einfachere Optimierung. Eine Flottenobergrenze oder ein Reservoir verändert das Betriebsmodell, beseitigt aber keine Suchkomplexität.

### 3.1 Erster Algorithmusvergleich

Für den ersten K39-Vergleich unverändert lassen: Five-Station-B, feste physische Startanordnung und Boundary, 20 OD-Gruppen/1280 Personen, Kapazität 8, Nachfragefreigabe 0, Servicehorizont 1200 s, Exit-Waiting bis W=1200 s und kanonische Mikrosekunden. Dies ist ein Batch-Nachfragefall. Keine Periodizität, freie Startpositionen, zusätzliche Warteorte oder optionale Kabinen einführen.

Neue Solver dürfen eine heuristische Teilmenge der Entscheidungen erkunden; dies muss im Manifest stehen. Eine Einschränkung der Suchkandidaten ist keine globale Unzulässigkeits- oder Optimalitätsaussage. Änderungen an Flotte, Nachfrage, Aufwärmphase und Abschlussvertrag erhalten eigene Instanzkennungen.

### 3.2 Verbindliche endliche Bewertungsgrundlage

Die nächsten Vergleiche verwenden [closed_event_entry_horizon_v1](../reference/finite_horizon_contract.md). Eintritte bis einschließlich H behalten ihre vollständigen Räumzeiten; neue Eintritte nach H sind ausgeschlossen. Alle Kabinenpfade müssen den vereinbarten Horizont abdecken. Dies ist der akzeptierte Aufgabenrahmen, kein noch offenes Gate. Ein später untersuchter Dauerbetrieb wäre eine gesonderte Modellfrage.

## 4. Teil A: schnelle Heuristiken

### A1. Greedy- und Regret-Einfügung von vollständigen Bedienungen

**Basis:** Einfügeoperatoren aus Pickup-and-Delivery mit Zeitfenstern und Kapazität, insbesondere Ropke/Pisinger [S1]. Die feste Ringroute ist eine mögliche Vereinfachung gegenüber freiem Routing; gemeinsame Merges sind eine zusätzliche Erschwernis.

**Vorgeschlagene Ropeway-Anpassung:**

1. Mit einer unter dem gewählten Vertrag validierten vollständigen Bewegung starten. Nachfrage bleibt explizit bedient oder unbedient bilanziert.
2. Für eine unterversorgte OD-Gruppe eine ganzzahlige Teilmenge und mehrere kompatible Kabinenbesuche bestimmen. Ein Kandidat enthält Einstieg, Zielausstieg, Kapazitätsbedarf auf jedem dazwischenliegenden Abschnitt und notwendige Stop-/Skip-Änderungen.
3. Zusätzliche Kosten für alle betroffenen Personen bewerten: eingesparte Warte-/Unbedient-Kosten, Verzögerung bereits bedienter Personen, verdrängte Bedienungen. Ein Stopp mit vielen Boardings allein ist kein ausreichendes Ziel.
4. Greedy wählt die beste geschätzte Verbesserung. Regret-2 priorisiert die Gruppe, deren zweitbeste zulässige Einfügung wesentlich schlechter als die beste ist. Die Nichtbedienungsoption bleibt mit ihren echten Kosten sichtbar; fehlende Alternativen dürfen nicht als kostenfreie Einfügung erscheinen.
5. Alternative Prioritätsfolgen mit gespeicherten Zufallsseeds testen. Nur tatsächlich zulässige vollständige Pläne als Ergebnis übernehmen.

**Erster Test:** derselbe Kandidaten- und Reservierungskern, Greedy gegen Regret-2, ohne ALNS. Zusätzlich reine Passagiernachoptimierung der unveränderten Bewegung als Kontrolle. So ist erkennbar, ob neue Bewegung oder nur bessere Zuordnung hilft.

**Risiko:** Eine Änderung wirkt über mehrere Kabinen und Umläufe. Nicht betroffene Einfügekosten dürfen nur dann aus dem Cache übernommen werden, wenn ihre Abhängigkeiten tatsächlich unverändert sind.

### A2. Prioritätsbasierte Merge-Reservierung und begrenzte Neuvergabe

**Basis:** Haneyah et al. [S2] verwenden freie Förderbandplätze, eine priorisierte Warteliste und Neuvergabe von Reservierungen. Dies ist eine Heuristik für ein Merge-Modul; Passagierziel und gekoppelte Ropeway-Folgebewegungen sind eigene Erweiterungen. Die konkrete Zeitfensterrechnung, Konfliktreparatur und Quellenübertragung stehen im [G1-Entwurf](reservation_insertion_kernel.md).

**Vorgeschlagener Kern:**

- Physische Abschnitte ohne Wartefreiheit als Bewegung mit festen Zeitoffsets behandeln. Nur am erlaubten Plattformende warten. Zulässige Zeitfenster entlang der gesamten betroffenen Bewegung fortpflanzen.
- Reservierungen für alle bestehenden Ressourcen und die tatsächlichen vorgänger-/routenabhängigen Headways führen. Kein pauschaler symmetrischer Abstand als Ersatz.
- Einfügeanfragen mit Passagiernutzen, Alternativverlust und physikalischer Dringlichkeit priorisieren. Diese Gewichte sind Heuristikparameter, keine Änderung des abschließenden Journey-Time-Ziels.
- Bei einer Neuvergabe die verdrängte Kabine ebenfalls reparieren. Ein begrenzter Suchbaum über Prioritäten/Reihenfolgen ist erlaubt; scheitert die Reparatur, den gesamten Änderungsschritt zurückrollen.
- Kandidaten erst akzeptieren, wenn alle betroffenen Pfade den vereinbarten endlichen Horizont vollständig und validierbar abdecken. Eine lokal freie Lücke genügt nicht. Keine Fahrgäste über ihr Ziel hinaus in eine weitere Runde schicken, wenn der Modellvertrag das ausschließt.

**Gate G1:** Zunächst Roundtrip eines bekannten Plans durch den neuen Datenpfad ohne Entscheidungsänderung. Danach eine zulässige und eine unzulässige gemeinsame Bedienungsänderung mit mehreren Ressourcen prüfen. Physische Zeiten und Ressourcennutzung gegen den unabhängigen Validator abgleichen.

**Geschwindigkeitstest:** 100 vorab definierte Einfüge-/Reparaturanfragen messen; Median, p95, betroffene Kabinen, Ressourcen und verworfene Anfragen melden. Vorläufiges Ziel für einen brauchbaren Suchkern: p95 unter 100 ms auf dem Testrechner und mehrere gültige Alternativen in 30 s. Das ist eine Projektmesslatte, keine behauptete Laufzeit. Erfordert fast jede Anfrage eine große Optimierung oder entsteht kaum ein gültiger Kandidat, zunächst den Engpass auswerten statt ALNS darumzubauen.

### A3. ALNS mit passagierorientierten Änderungen

**Basis:** Dong et al. [S3] verbinden Stopplanung und Fahrplanung unter zeitabhängiger Nachfrage mit ALNS. Ropke/Pisinger [S1] liefern den Mechanismus konkurrierender, adaptiv ausgewählter Operatoren. Daraus folgt keine bewiesene Leistung auf einem dichten Ropeway-Ring.

**Nur nach erfolgreichem G1/G2 entwickeln.** Wiederverwendung der A1-Einfügung und A2-Reparatur; kein vollständiges globales MIP pro Nachbarschaft.

Vorgesehene Entfernungsoperatoren:

- schlecht bediente OD-Gruppen samt ihren Bedienungsalternativen;
- räumlich und zeitlich gekoppelte Kabinen an mehreren aufeinanderfolgenden Merges;
- Stopps mit geringem Beitrag zum Gesamtziel;
- zufällige zusammenhängende Pakete zur Diversifikation.

Eine Bewegung oder Bedienungszuweisung zu entfernen bedeutet eine interne Planänderung, keine physische Kabine verschwinden zu lassen. Bereits eingestiegene Personen behalten Ziel- und Kapazitätsverpflichtungen. Reparatur mit Greedy oder Regret; größere Pakete nur, wenn die messbare Reparaturzeit dies zulässt. Der beste validierte Plan bleibt jederzeit erhalten. Eine zeitweise Verschlechterung des Suchzustands kann ein späteres Experiment sein; keine unzulässige Zwischenlösung als UB ausgeben.

**Ablation:** Greedy, Regret, Regret mit Mehrfachstarts, danach gleiche Konstruktion plus ALNS. Nur der jeweils neue Baustein darf sich unterscheiden. Frühere erfolglose kleine Kohorten/Mergekorridore als Gegenbeleg berücksichtigen: Die neue Variante muss tatsächlich gemeinsame Bedienung und Folgekonflikte verändern können.

### A4. Priorisierte Planung mit Auftragswechseln

**Basis:** Token Passing / Task Swaps [S4], später Mehrfachaufträge mit LNS/PBS [S5]. Die Arbeiten koordinieren Transportaufträge und konfliktfreie Fahrzeugwege. Lagerannahmen über sichere Endpunkte und Ausweichmöglichkeiten passen nicht automatisch zum Ring.

**Mögliche Anpassung:** noch nicht eingestiegene Gruppen zwischen Kabinen tauschen, reservierte Bewegungen schrittweise neu planen, mehrere Prioritätsreihenfolgen probieren. Als späterer Operator innerhalb von A3 prüfen. Ein kompletter zweiter Planner lohnt sich vor der Präsentation nicht, solange A2 dieselben Engpässe bereits sichtbar macht.

### A5. Begrenzte Ereignis-/Beam-Suche als Reparatur

Wenn eine einzige Greedy-Folge zu früh festlegt, eine kleine Menge alternativer Fortsetzungen behalten. Beam-Breiten 1, 8 und 32 sind mögliche Pilotwerte. Solange verworfene Zweige nicht vollständig nachgeholt werden, bleibt dies heuristisch. Das ist eine eigene Ropeway-Übertragung des Suchprinzips, kein hier belegter spezieller Seilbahnalgorithmus.

Nur implementieren, wenn G1 zeigt, dass Reihenfolgeentscheidungen und nicht die physische Auswertung dominieren. Nicht zusätzlich zu einer großen neuen CBS-Implementierung beginnen.

## 5. Teil B: Verfahren außerhalb von MIP mit möglichen Schranken

### B1. Ereignisbasierte DP / A* / ARA*

**Basis:** ARA* [S6] verbessert Lösungen und Suboptimalitätsschranken durch Wiederverwendung von Sucharbeit. Die Garantie setzt eine passende Suchdomäne, Kosten und zulässige Heuristik voraus.

**Vorgeschlagene Zustandsbeschreibung:** Zeit; Kabinenpositionen und Bewegungsphasen einschließlich Restzeiten; für künftige Konflikte relevante Ressourcenbelegungen und Vorgänger; wartende Nachfrage je OD/Release; ganzzahlige Belegung je Kabine und Ziel; offene Bedienungs-/Endverpflichtungen; bisherige Kosten. Eine Zusammenfassung nur über Kabinenzahl oder Gesamtwarteschlange ist im Allgemeinen nicht ausreichend.

**Entscheidungen:** Stop/Skip, erlaubte Austrittszeit, Boarding/Zuordnung und gegebenenfalls Ressourcenreihenfolge. Dispatch nur in einem gesonderten Reservoirvertrag. Zwischen Entscheidungen deterministische Bewegung berechnen.

**Untere Schranke:** Zunächst eine nachweislich optimistische Restkostenrechnung ohne Kapazitäts- und Ressourcenkonkurrenz: jede Person darf ihre individuell günstigste physikalisch mögliche Restbedienung erhalten, alternativ Nichtbedienung gemäß Ziel. Bereits aufgelaufene Kosten konsistent verbuchen. Diese Relaxation kann schwach sein; sie darf weder Boarding vor Release erlauben und trotzdem zu teuer schätzen noch Kosten doppelt zählen. Zulässigkeit formal prüfen, auf kleinen Instanzen gegen exakte Restoptima testen.

**Gate G3 vor größerer Umsetzung:**

1. Kleine vollständige endliche Domäne mit denselben Ressourcenarten und gezielt ausgelösten Mergekonflikten definieren. Ihre Zeitauflösung ausdrücklich angeben.
2. Mit vollständiger Enumeration oder CP-SAT in genau derselben Domäne vergleichen: zulässige Lösungen, Optimum und Untergrenzen.
3. Zustandszahl, Verzweigung, Speicher, Dominanzquote, Zeit zum ersten Plan und Schrankenverlauf messen.
4. Erst dann Horizont und Dichte erhöhen. Ein Spielzeugfall ohne Konflikte ist kein Skalierbarkeitsbeleg.

**Offene Hürde:** Bei kontinuierlicher oder mikrosekundengenauer Wartewahl ist eine vollständige kleine Nachfolgermenge nicht selbstverständlich. Nur „frühester freier Slot“ kann Lösungen verlieren. Ein gröberes Raster oder ausgewählte Zeitfenster machen eine prüfbare beschränkte Domäne, beweisen aber nicht das ursprüngliche kontinuierliche Optimum. Keine unbegründete Dominanz „früher ist besser“ an Orten ohne Wartefreiheit.

### B2. Decision Diagrams

**Basis:** eingeschränkte und relaxierte Decision Diagrams können zulässige Lösungen und Schranken liefern; zusammen mit vollständiger Verzweigung entsteht ein exaktes Verfahren [S7]. Ein exaktes Diagramm kann exponentiell wachsen.

**Pilot nach B1:** dieselbe kleine endliche DP verwenden. Gleichwertige Zustände zunächst exakt zusammenführen. Danach einen formal spezifizierten optimistischen Merge-Operator und ein Diagramm begrenzter Breite entwickeln. Beim Minimieren liefert ein eingeschränktes Diagramm eine UB, ein korrekt relaxiertes Diagramm eine LB. Eine bloße Beam Search ist noch kein relaxiertes Diagramm.

**Akzeptanz:** Auf kleinen Instanzen stets LB <= bekanntes Optimum <= UB; vollständige Lösungserhaltung des Merge-Operators zusätzlich argumentieren. Bei ausreichender Breite das exakte Ergebnis reproduzieren. Breite, Speicher, Kompressionsquote und Gap über Laufzeit berichten. Die beste bisherige UB/LB separat speichern; einzelne Diagrammneubauten müssen nicht automatisch monoton besser sein.

**Entscheidung:** Nur verfolgen, wenn die Zustandskompression bei konfliktbeladenen Fällen sichtbar hilft und die Relaxation informative Schranken liefert. Bleiben alle Zustände verschieden oder ist jede LB trivial, besteht noch kein Vorteil gegenüber Arc-Flow. Keine vollständige Diagramm-Engine vor der Präsentation einplanen.

### B3. Kontinuierliche Conflict-Based Search / AOC-CBS

**Basis:** Der Preprint AOC-CBS vom 8. August 2026 [S8] kombiniert kontinuierliche Konfliktsuche und Reparatur mit Gap-Schranken. Er ist ein neuer, noch nicht replizierter Kandidat, keine etablierte Ropeway-Lösung. Garantien gelten innerhalb seiner Graphen und Annahmen; insbesondere braucht er geeignete unabhängige Planoptima und eine monotone Aggregation ihrer Kosten. Aufgabenfolgen sind vorgegeben; jeder Plan endet in einem dauerhaft wartbaren Zustand.

**Übertragungsprüfung zuerst:** Paarweise Headways, erlaubte Wartezustände, wiederholte Besuche und Abschluss abbilden. Für physische Bewegungskoordination könnte dies passen. Gemeinsame Passagierzuordnung und frei gewählte Bedienungsaufgaben sind zusätzliche Kopplungen, für die die Schranke neu begründet werden müsste. Ein exakt gelöster Bewegungsdecoder macht eine äußere Heuristik nicht global exakt.

**Pilot:** Erst ein physisches Teilproblem mit vorgegebenen Bedienungsaufgaben und passendem Abschluss, explizit anderer Proof-Scope. Konfliktbaumgröße und wiederholte Neuplanung bei wachsender Dichte messen. Keine Vollintegration beginnen, bevor die Kostenzerlegung geklärt ist. Für den dichten Ring wegen vieler wiederkehrender Konflikte hinter B1/B2 priorisieren.

### B4. Weitere CP-/SAT-Formulierungen

Eine Suche über Ressourcenreihenfolgen mit zeitlicher Propagation bleibt eine weitere Möglichkeit. Das Projekt besitzt jedoch bereits CP-SAT und EAN-Strukturen. Vor einer neuen Engine einen konkreten strukturellen Vorteil zeigen: weniger Entscheidungen, stärkere Propagation oder billigere Reparatur. Ein Solverwechsel allein rechtfertigt keinen neuen Implementierungszweig. Bis dahin zurückstellen.

## 6. Konkrete Arbeitsfolge und Abbruchkriterien

| Schritt | Umfang / Obergrenze | Weiter nur bei | Falls nicht erfüllt |
|---|---|---|---|
| G1: Reservierung und Einfügung | Höchstens zwei weitere Arbeitstage | Korrekte Roundtrips, gültige Änderungen und messbar günstige Reparatur | Findings schreiben; keine ALNS-Ausweitung |
| G2: Greedy/Regret-Vergleich | Anschließend ein begrenzter Messtag | Wiederholte Zielverbesserung gegenüber derselben Startlösung; sinnvoller Zeit-/Qualitätsverlauf | Ursachen nach Kandidatenmangel, Konflikten und Bewertung trennen |
| A3: ALNS | Nur nach G2, maximal zwei Entwicklungstage | Mehrwert gegenüber Mehrfachstarts bei gleichem Gesamtbudget | Einfachere beste Variante behalten |
| G3: exakte Ereignissuche | Optional nach Heuristikentscheidung; maximal ein Tag für Zustands-/Domänenpilot | Vollständigkeit der kleinen Domäne und vielversprechende Zustandszahlen | Als Forschungsrichtung dokumentieren |
| B2/B3: DD oder CBS | Erst bei positivem fachlichem Gate | Begründete Schranken und Strukturvorteil | Nach der Präsentation vertiefen |

Kalenderziel: G0/G1 bis etwa 12. September, G2-Entscheidung am 13. September, optionale Verbesserung bis 15. September; 16.–18. September für ausgewählte Nachfragefälle, Auswertung und Präsentation reservieren. Wenn frühere Schritte länger dauern, entfallen optionale Algorithmen. Die Zeitgrenzen begrenzen Entwicklung; sie garantieren keinen fertigen Solver.

G2 soll keine willkürliche Prozentverbesserung erzwingen. Weiterentwicklung ist begründet, wenn mehrere unabhängige Starts valide Fortschritte zeigen und die Auswertung nicht fast das gesamte Budget verschlingt. Ein einzelner glücklicher Lauf reicht nicht. Ein Fehlschlag der Heuristik ist kein Nachweis fehlender Skip-Stop-Potenziale.

## 7. Messprotokoll

Erste Budgets: 30, 120 und 600 s inklusive Vorbereitung, Konstruktion, Bewertung und finaler Prüfung. Pro stochastischer Variante drei Seeds; zuerst 30-s-Screening. Nur bei gültigen aussichtsreichen Resultaten länger laufen lassen. Auf demselben Rechner sequenziell messen. CP-SAT mit deklarierter Workerzahl und gleicher Instanz als Referenz; CPU-Zeit und Peak-Speicher zusätzlich zur Walltime ausweisen.

Ein Lauf bleibt innerhalb seines Gesamtbudgets, indem Zeit für Export/Validierung reserviert und nur fertig geprüfte Incumbents ausgegeben werden. Eine spätere exakte Passenger-IP-Nachbewertung ist separat zu messen und für alle Methoden gleich zu behandeln. Sie ist eine unterstützende MIP-Komponente außerhalb des heuristischen Bewegungskerns und darf nicht unsichtbar in angeblich rein heuristische Laufzeit eingehen.

Pro Lauf speichern:

- Codeversion samt Änderungen/Manifest, Instanzfingerprint, Startplan, Algorithmusparameter, Seed, Hardware, Worker und Vertragsversion;
- Zeit für Aufbau, Kandidatenerzeugung, Reservierung/Reparatur, Passagierbewertung, unabhängige Prüfung;
- Zahl versuchter/gültiger/verbessernder Änderungen, Reparaturtiefe und betroffene Kabinen;
- Zielwert, bediente/unbediente Personen, Warte-/Fahrzeitanteile, Stopps ohne Bedienung, Exit-Waits;
- Incumbentverlauf, bei exakten Verfahren getrennt die gültige LB und ihren Proof-Scope;
- Fehlschläge einschließlich Validierungsgrund. CONSTRUCTION_FAILED ist nicht INFEASIBLE.

Eine heuristisch geschätzte Bewertung ist keine UB. Eine vollständige zulässige ganzzahlige Passagierzuweisung liefert eine UB auch ohne optimal gelöste Zuordnung. Wird die feste Bewegung per IP optimal bewertet, beweist das nur deren beste Passagierzuweisung. Eine globale LB darf nur aus derselben vollständigen Domäne oder einer nachweislich gültigen Relaxation stammen; historische Schranken nicht über Vertragsänderungen hinweg kombinieren.

Nach positivem G2 eine kleine vorab festgelegte Matrix aus diffuser, Hub-/Express- und Peak-Nachfrage gemäß [Demand Case Families](../reference/demand_case_families.md) verwenden. All-Stop jeweils neu und mit passender Nachfrage bewerten. Zuerst bei K<=38 die Methoden bei gleicher Flotte und Anfangsanordnung vergleichen; K39 als zusätzliche dichte Betriebsfrage erhalten. Keine Auswahl nur zugunsten eines günstigen Skip-Stop-Falls.

## 8. Code- und Ergebnisorte

| Bestehender Ort | Geplante Nutzung |
|---|---|
| [DDD reference.py](../../src/ropeway_skip_stop_optimization/optimization/ddd/reference.py) | Besuchskonstruktion, Trajektorien und `validate_ddd_reference_solution` |
| [DDD time_ticks.py](../../src/ropeway_skip_stop_optimization/optimization/ddd/time_ticks.py) | Kanonische Zeitumrechnung |
| [CP-Zertifikate](../../src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_certificate.py) | Vorbild für Fingerprints und vollständige Checkpoints; kein CP-Proof-Label für Heuristiken wiederverwenden |
| [EAN validation.py](../../src/ropeway_skip_stop_optimization/optimization/ean/validation.py) | Unabhängige Bewegungs- und Boundary-Prüfung |
| [EAN headway_separator.py](../../src/ropeway_skip_stop_optimization/optimization/ean/headway_separator.py) | Headwayprüfung und G0-Grenzfall |
| [Feste Passagieroptimierung](../../src/ropeway_skip_stop_optimization/optimization/ean/optimizers/fixed_movement_passenger_model.py) | Bewertung fertiger Bewegungen; Vorbild für ganzzahlige Bilanz und Ziel |
| [CP-Movement](../../src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_movement.py) | Vergleich der physischen Semantik; nicht als obligatorischer innerer Solver |
| [CP-Benchmark](../../src/ropeway_skip_stop_optimization/benchmarking/ddd_fixed_k_cp_sat.py) | Bestehende Vergleichsmethode und Messstruktur |

Vorgeschlagene neue Orte, **noch nicht vorhanden**: ein gemeinsamer Heuristikkern unter `src/ropeway_skip_stop_optimization/optimization/reservation/`, Benchmarkadapter unter `benchmarking/reservation_heuristic.py`, CLI unter `benchmarks/run_reservation_heuristic.py`. Kleine exakte Zustandsprototypen getrennt halten. Vor Anlage der Module die Schnittstellen des älteren Reservierungsplans mit den aktuellen EAN/DDD-Datentypen abgleichen.

Geplante Ausgaben: `benchmarks/output/reservation_heuristic_gate/<instance>/<variant>/<seed>/` und für exakte Prototypen `benchmarks/output/non_mip_state_search_gate/`. Pro Lauf Manifest, Events, vollständiger Plan, Passagierzuweisung, Validierung und Messwerte. Findings in `docs/findings/`; umgesetzte Teile aus diesem Plan in Referenzdokumentation überführen. Output ist derzeit überwiegend gitignored: benötigte Reproduktionsdaten ausdrücklich sichern.

## 9. Quellen und Evidenzumfang

Die Quellen begründen Mechanismen in verwandten Problemen. Keiner der Nachweise belegt die Leistung der hier vorgeschlagenen vollständigen Ropeway-Anpassung. Keine unüberprüften Laufzeit- oder Gütegarantien übertragen.

- **S1 — Ropke, S.; Pisinger, D. (2006):** *An Adaptive Large Neighborhood Search Heuristic for the Pickup and Delivery Problem with Time Windows*. Transportation Science 40(4), 455–472. [Originalartikel](https://doi.org/10.1287/trsc.1050.0135). Grundlage für Einfügung und adaptive Operatorwahl; Verlagsabstract und bibliografischer Nachweis geprüft. Für die genaue Operatorimplementierung vor Umsetzung den Originalvolltext heranziehen.
- **S2 — Haneyah et al. (2011):** *Planning and Control of Automated Material Handling Systems: The Merge Module*. [Originalvolltext](https://ris.utwente.nl/ws/portalfiles/portal/5374531/Plannin_and_Control_GOR.pdf), DOI 10.1007/978-3-642-20009-0_45. Algorithmusabschnitt geprüft: Platzsuche, priorisierte Vergabe, Neuvergabe. Simulation eines Merge-Moduls; kein globaler Passagierfahrplan.
- **S3 — Dong et al. (2020):** *Integrated optimization of train stop planning and timetabling for commuter railways with an extended adaptive large neighborhood search metaheuristic approach*. Transportation Research Part C 117, 102681. [Originalartikel](https://doi.org/10.1016/j.trc.2020.102681). Verlagsvorschau/Abstract geprüft. Belegt die Kombination von Stopplanung, Nachfrage und ALNS; keine hier verifizierte konkrete Laufzeitprognose.
- **S4 — Ma et al. (2017):** *Lifelong Multi-Agent Path Finding for Online Pickup and Delivery Tasks*. [Autorenpreprint](https://arxiv.org/abs/1705.10868). Token Passing und Task Swaps; Abstract geprüft. Garantien für well-formed MAPD-Instanzen, nicht für unseren Ring nachgewiesen.
- **S5 — Xu et al. (2022):** *Multi-Goal Multi-Agent Pickup and Delivery*. [Autorenpreprint](https://arxiv.org/abs/2208.01223). Abstract geprüft: Auftragsfolgen mit LNS und Pfadplanung mit PBS; mögliche Erweiterung, keine fertige Ropeway-Integration.
- **S6 — Likhachev, Gordon, Thrun (2003):** ARA*: Anytime A* with Provable Bounds on Sub-Optimality. [CMU-Publikationsseite](https://publications.ri.cmu.edu/ara-anytime-a-with-provable-bounds-on-sub-optimality), [Originalpaper](https://www.cs.cmu.edu/~maxim/files/ara_nips03.pdf). Nachweis/Abstract geprüft; Such- und Kostenannahmen vor einem exakten Implementierungsanspruch vollständig herleiten.
- **S7 — van Hoeve:** *Decision Diagrams for Optimization*. [CMU-Forschungsübersicht](https://www.andrew.cmu.edu/user/vanhoeve/mdd/), [Tutorial 2024](https://doi.org/10.1287/educ.2024.0276). Übersicht und Tutorialauszüge geprüft: eingeschränkte/relaxierte Diagramme, DP und exakte Verzweigung.
- **S8 — Combrink, Roselli, Fabian (2026):** *AOC-CBS: Anytime-Optimal Continuous-time Conflict-Based Search for Generalised Multi-Agent Path Finding*. [Volltext](https://arxiv.org/html/2608.08175v1). Preprint vom 8. August 2026; Problemdefinition, Kosten-/Endannahmen und Algorithmusbeschreibung geprüft. Keine eigene Replikation, keine Übertragung des Beweises auf die gemeinsame Passagieroptimierung.

Weitere Quellen zu SIPP/No-Wait, Alternative Graphs und Förderanlagen stehen in der [bestehenden Forschungslandkarte](../../../RESEARCH_CONCEPTS.md). Literaturprüfung und kleine Tests ersetzen keinen Vollständigkeitsbeweis. Die operative Empfehlung dieses Plans ist deshalb der begrenzte Heuristikversuch; die exakten Wege bleiben an eigene Nachweise gebunden.
