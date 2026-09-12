# Automatische Haltemusterwahl: Literatur und nächste Diagnose

Stand: 2026-09-12. Recherche und Empfehlung; keine Implementierung oder neue Laufkampagne. Literaturergebnisse sind keine Performanceprognose für die Seilbahn.

## Was wir tatsächlich erklären müssen

Für R2 soll die Optimierung selbst komplementäre Bedienungen wie B/D und C/E finden, deren Flottenanteile bestimmen und daraus einen physikalisch gültigen Fahrplan mit ganzzahligen Passagieren erzeugen. Die vom Nutzer vorgeschlagene Aufteilung ist eine plausible Hypothese, noch kein validierter Kapazitätsvorteil. Freigaben, Anfangs-/Endfahrten und gemeinsam benutzte Ressourcen verhindern eine belastbare Bewertung allein durch Umlaufzahl × Sitze.

Der jüngste Timingversuch beantwortet diese Frage nicht: `reservoir_assignment/timing.py` fixiert Aktivitätspräfixe und jede kanonische Ride-Menge; auch bei freien Routen darf er Passagiere nicht neu auf Kabinen und Besuche verteilen. Er prüft die zeitliche Realisierbarkeit einer vorgegebenen Zuordnung.

Das vollständige CP-SAT-Modell besitzt dagegen grundsätzlich solche Entscheidungsfreiheit. Seine bisherigen Plateaus beweisen weder Unmöglichkeit dieser Muster noch eine rein lokale Suche. Außerdem implementiert `trajectory_root_column_generation.py` bereits ganze Trajektorien mit Root-Column-Generation und optionalen Verfahren zur gemeinsamen Primallösung. „Ganze Muster statt Einzelentscheidungen“ allein wäre deshalb keine neue Architektur.

## Forschungsrichtungen

### 1. Limited-stop service design: Muster, Frequenzen und Flotte gemeinsam

Wang, Nayan und Szeto (2018), *Optimal bus service design with limited stop services in a travel corridor*, modellieren die bedienten Haltestellen ausdrücklich als Entscheidungen, gemeinsam mit Frequenzen und Flottenzuordnung. Das Modell berücksichtigt die Verkehrsmittel-/Servicewahl der Passagiere und wird über Linearisierung und Konvexifizierung behandelt. Es liefert eine direkte Grundlage für automatische Musterwahl, aber keinen fertigen mikroskopischen Reservoir-Scheduler. [Verlagsquelle](https://www.sciencedirect.com/science/article/pii/S1366554517302922), DOI: 10.1016/j.tre.2018.01.007.

Unsere Ableitung: Eine endliche Familie wiederkehrender Haltemuster integrieren, deren Auswahl und Kabinenanteile der Solver bestimmt. Die Zeit- und Ressourcenbedingungen müssen aus unserer Domäne kommen.

### 2. Linienplanung mit Column Generation

Borndörfer, Grötschel und Pfetsch (2007), *A Column-Generation Approach to Line Planning in Public Transport*, erzeugen Linien dynamisch und koppeln sie mit Passagierwegen. Dualpreise steuern, welche zusätzlichen Linien wirtschaftlich nützlich sind. [Autorenfassung](https://www.zib.de/userpage/groetschel/pubnew/paper/borndoerfergroetschelpfetsch2007_pp.pdf).

Unsere Ableitung: Nicht bediente Nachfrage kann neue Muster attraktiv machen; knappe Ressourcen können sie verteuern. Bei uns ist aber gerade die kompatible ganzzahlige Kombination zeitlich genauer Trajektorien schwierig. Root-CG ist bereits vorhanden. Ein geschlossener LP-Gap ist kein ganzzahliger Optimalitätsbeweis; vollständiges Pricing und gegebenenfalls Branch-and-Price wären zusätzliche Anforderungen. Kein Neustart allein unter anderem Namen.

### 3. Integrierte Linienplanung und Fahrplanerstellung

Burggraeve, Bull, Vansteenwegen und Lusby (2017), *Integrating robust timetabling in line plan optimization for railway systems*, koppeln Linienplanung und Fahrplanoptimierung in einem heuristischen Verfahren. Kritische Linien und zeitliche Robustheit beeinflussen die weiteren Linienentscheidungen. [Autorenfassung](https://orbit.dtu.dk/files/123901887/TRpC.pdf), DOI: 10.1016/j.trc.2017.01.015.

Die Analogie passt, aber die periodische Bahnformulierung und ihre Betriebsannahmen sind keine äquivalente Beschreibung unseres Rings mit Überholungen. Übertragbar ist die Rückkopplung zwischen Angebot und zeitlicher Realisierbarkeit, nicht unverändert das Modell.

### 4. Logic-based Benders für Zuordnung und Scheduling

Ciré, Çoban und Hooker (2016) untersuchen Bedingungen erfolgreicher LBBD-Verfahren. Besonders wichtig sind Scheduling-Relaxationen bereits im Master und brauchbare Konfliktcuts. [Autorenfassung](https://johnhooker.tepper.cmu.edu/bendersKER.pdf), [Verlag](https://maxapress.com/article/doi/10.1017/S0269888916000254).

Für uns wären nachgewiesene Überlastungen konkreter Ressourcen-Zeitfenster nützlich. Ein Timing-Timeout mit `UNKNOWN` erlaubt hingegen keinen Unzulässigkeitscut. Solange unsere Unterprobleme stundenlang ohne Zertifikat bleiben, ist eine zusätzliche Benders-Schleife keine begründete Lösung. Zuerst müsste gezeigt werden, dass relevante Zuordnungen schnell realisiert oder durch verallgemeinerbare Konflikte ausgeschlossen werden können.

### 5. Analytische AB-Skip-Stop-Planung

Mei, Gu, Cassidy und Fan, *Planning Skip-Stop Transit Service under Heterogeneous Demands*, behandeln heterogene Nachfrage mit kontinuierlicher Approximation und einer effizienten Heuristik. [Preprint](https://arxiv.org/abs/2011.12674).

Das kann Betriebsstrukturen und Vergleichskandidaten liefern. Es ersetzt weder die exakte Ressourcenprüfung noch einen Kapazitätsnachweis für unsere Integer-Zeitdomäne.

## Konkrete Empfehlung: beschränkte integrierte Musterwahl

Dies ist unsere Übertragung der Literatur, kein dort bereits getesteter Seilbahnalgorithmus:

1. Alle Haltemasken der Stationen zulassen: höchstens 32 bei fünf und 64 bei sechs Stationen. Keine manuelle Beschränkung auf B/D und C/E; leere oder unproduktive Masken dürfen nur begründet behandelt werden.
2. Jede eingesetzte Kabine wählt zunächst ein während ihres Einsatzes wiederkehrendes Muster. Der Solver wählt Muster und Flottenverteilung selbst. Das schränkt den Fahrplanraum bewusst ein; unabhängige Muster je Runde wären lediglich eine andere Kodierung der bisherigen Stopentscheidungen.
3. Im selben bestehenden CP-SAT-Modell bleiben Dispatch, Waiting, rechtzeitige Rückkehr, optionale Flotte und sämtliche Passagiermengen frei. Musterbits koppeln an STOP/SKIP. Kein externes Fixieren der Passagierzuordnung.
4. Exakte Ressourcen, Überholungen, Freigaben und kanonische Ride-IDs bleiben erhalten. Wiederkehrende Haltemuster erzwingen keine periodischen Abfahrtszeiten.

Erwartung: weniger unabhängige Stopentscheidungen und koordinierte Änderungen mehrerer Besuche. Keine Zusage kleiner Passagiermodelle oder schneller Suche: Zeitkonflikte und Zuordnung bleiben schwierig. Eine Solver-Schranke gilt nur für diese eingeschränkte Musterfamilie.

## Diagnostische Reihenfolge vor einem weiteren Ausbau

- Kontrollfall mit B/D- und C/E-Mustern, aber frei optimierter Passagierzuordnung und Zeitlage; eine 50/50-Verteilung wäre nur ein separat bezeichnetes Nutzerszenario.
- Danach automatische Auswahl aus allen Masken, ohne vorgegebene Aufteilung. Nur dieser Versuch prüft automatische Musterentdeckung.
- Vergleich mit vollständigem Legacy-CP-SAT bei gleichem Budget; Referenzübernahme, native Lösungen und Verbesserungen getrennt erfassen.
- Falls schon feste Muster schwer zu timen sind, liegt der verbleibende Engpass nicht allein bei der Musterwahl. Dann keine weitere Mustergenerierung als vermeintliche Lösung verkaufen.

Die All-Stop-Referenz mit 2.496 Bedienten ist kein globales All-Stop-Optimum. Ein gültiger besserer Plan schlägt zunächst diese Referenz. Für einen globalen Vorteil muss sein Unserved-Wert einen abgesicherten All-Stop-Unterbound unterschreiten. Auch ein eingeschränkt erzeugter Plan kann diesen Nachweis liefern; ein globales Skip-Stop-Optimum ist dafür nicht erforderlich.
