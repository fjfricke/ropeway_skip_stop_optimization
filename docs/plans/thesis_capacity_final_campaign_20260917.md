# Abschließende Kapazitätsstudie: neue Läufe und gemeinsame Betriebsregeln

Stand: 17.09.2026. Kampagne abgeschlossen. Der Befund steht unter
[`docs/results/thesis_capacity_final_campaign_20260917.md`](../results/thesis_capacity_final_campaign_20260917.md).

## 1. Ziel und Abgrenzung

Wir untersuchen, ob Skip-Stop bei gleicher Kabinenzahl mehr Profilnachfrage vollständig bedienen kann als der reguläre All-Stop-No-Wait-Betrieb. Anschließend prüfen wir getrennt den Nutzen gemeinsamer CP-SAT-Nachoptimierung und zusätzlicher Waitingfreiheit.

Die bestehenden Netze und Betriebsfenster bleiben erhalten. Keine kürzeren Seile, kein kürzerer Horizont und keine neue kleine Netzfamilie in dieser Kampagne. Die abgeschlossene Journey-Studie mit Labelled Arc-Flow bleibt eine separate Untersuchung.

**Alle hier vorgesehenen F2-Suchläufe werden neu gestartet, einschließlich T5/F2, N=2.918 und N=3.210, Seed 0.** Alte Evo-Ergebnisse ersetzen keinen neuen Lauf. Alte Skip-Stop-Fahrpläne werden auch nicht als Startpläne importiert. Die bestehenden nachgewiesenen All-Stop-Referenzkapazitäten dürfen nach Vertragsprüfung zur Wahl der Nachfrage dienen; sie sind Referenzkalibrierung, keine neuen Suchergebnisse.

Dieser Plan ersetzt die Ausführungsempfehlungen aus [der Methodenbewertung](thesis_methods_and_final_experiments_20260917.md), insbesondere deren Empfehlung, einen alten identischen F2-Seed-0-Lauf wiederzuverwenden.

## 2. Gemeinsamer Betriebsvertrag: keine vorzeitige Rückkehr

**Für sämtliche Verfahren gilt: Jede eingesetzte Kabine bleibt bis zur ersten vollständigen Umlaufrückkehr am oder nach der Bedienungsdeadline im Betrieb. Das gilt auch für die freie CP-SAT-Nachoptimierung.**

Sei H die eingefrorene Bedienungsdeadline. Für jede aktive Kabine gilt:

- Dispatch innerhalb des bestehenden Warmup-/Dispatchfensters, danach durchgehende Bewegung nach STOP/SKIP und gegebenenfalls zulässigem Waiting.
- Rückkehr ins Reservoir erst bei einer vollständigen Umlaufrückkehr mit Zeit `r >= H`.
- Die gewählte Rückkehr muss die **erste** vollständige Umlaufrückkehr am oder nach H sein. Frühere Portpassagen sind Durchfahrten; spätere zusätzliche Umläufe sind nicht frei wählbar.
- Bei Rückkehr exakt zu H endet der Einsatz dort. Bei einer Rückkehr einen Tick vor H muss die Kabine weiterfahren.
- Auch eine leere Kabine darf nicht vorzeitig ausscheiden. Fehlende Nachfrage, leere Kabine oder bereits abgeschlossene Beförderungen sind keine Ausnahme.
- Ressourcenbelegung, Portschutz und Schutzintervalle bis einschließlich des Einsatzendes bleiben maßgeblich, auch hinter der Bedienungsdeadline.
- Die vorhandene operative Endgrenze bleibt erhalten. Eine Halte-/Waitingfolge, deren vorgeschriebene Rückkehr nicht mehr hineinpasst, ist unzulässig; der Horizont wird dafür nicht automatisch verlängert.

Eine von Anfang an ungenutzte Kabine ist bei einem Modell mit optionalen Einsätzen zulässig. Das ist etwas anderes als eine bereits eingesetzte Kabine vorzeitig zurückzunehmen. In den Fixed-K-Hauptläufen sind dagegen genau K Kabinen aktiv.

**Umsetzungsanforderung:** Diese Lebenszyklusregel muss in Modell, Export und unabhängigem Validator übereinstimmen. Eine bloße Textbeschriftung oder ein spätes Herausfiltern früher Rückkehr genügt nicht. Alle künftig vergleichbaren Reservoir-Verfahren müssen denselben Vertrag verwenden. Historische Resultate mit anderer Rückkehrregel bleiben separat gekennzeichnet.

Die vorhandene Linienvorbereitung implementiert bereits die erste Umlaufrückkehr an/nach H. Vor Kampagnenstart ist insbesondere zu prüfen, dass das vollständige CP-SAT-Modell und dessen Validator dieselbe Regel erzwingen, auch bei frei wechselnden Haltefolgen und Waiting. Bereits vorhandene `return_start`-Grenzen allein belegen diese Gleichheit noch nicht.

Weitere gemeinsame Parameter:

| Parameter | Festlegung |
|---|---|
| Geometrie | T5R/G500; T6R/G500 nur im Übertragungsblock |
| Nachfrage | P0, bestehende deterministische Profile, Freigabebatches alle 15 s |
| Reservoir | Single-Use, gemeinsamer Port einschließlich Dispatch, Durchfahrt und Rückkehr |
| Hauptreihe | No-Wait |
| Nachoptimierung | getrennte Varianten W=0 und Wmax=120 s je zulässigem STOP |
| Waitingfreigabe | bestehende zeitliche Freigaberegel unverändert; kein zusätzliches Warten im Reservoir |
| Zeitauflösung | Hauptvergleich und Nachoptimierung zunächst auf derselben bestehenden Mikrosekunden-Domäne; kein gleichzeitiger Auflösungswechsel |
| Nachfragebedienung | direkte, ganzzahlige Beförderung; keine Pflicht zur Vollbedienung |
| Ziel | lexikografisch: Unserved, anschließend Journey Time gemäß bestehendem Zielvertrag |

Die gemeinsame Zeitauflösung vermeidet eine neue Übertragungs-/Rundungsfrage in dieser Kampagne. Ein späterer 1-ms-Vergleich wäre ein gesonderter Versuch mit erneut validierten Starts und Referenzen.

## 3. Verfahren und Initialisierung

### All-Stop-Referenz

Für jede konkrete Nachfrage wird die ganzzahlige Bedienung des regulären All-Stop-Betriebs bewertet. Die gemeinsame Phase wird im bestehenden spezialisierten Referenzpfad berücksichtigt. Festes Timing mit optimalen Passagieren und bewiesenes Optimum über die Phase werden getrennt ausgewiesen.

Die bekannte maximale vollständig bedienbare Profilnachfrage ist kein pauschaler Served-Wert bei einer anderen Nachfrage. Bei N=3.210 darf daher nicht ungeprüft „All-Stop bedient 2.918“ eingetragen werden.

### Strukturierte Linienkonstruktion und Evolution

- Vorhandene pymoo-Suche, Population 32, acht Nachkommen, lokale/Block/globale Variation mit 50/30/20 %.
- Vorhandener No-Wait-Intervalldecoder und ganzzahliger Passagier-IP für gültige Bewegungen.
- F2-Katalog: All-Stop und die beiden minimalen OD-Masken B–D / C–E; im T6-Fall die entsprechenden OD-Endpunktmasken aus dessen Instanz.
- F3: vorhandener `od_endpoints_v1`-Katalog. Wie in F2 wird jede
  Kabinenposition mit der unabhängigen Musterdarstellung (`independent`)
  entwickelt. `line_groups` wird in dieser Kampagne nicht verwendet. Die
  konkreten Masken werden vor Start aus der Instanz exportiert und eingefroren.
- Keine zusätzliche freie `relevant`-Katalogkampagne.
- Frische Population, frischer Laufcache und frische Zeitmessung für jeden Seed. Kein Resume alter Suchläufe.
- Gemeinsame deterministische Initialsampler: nachfragebezogene Mischungen, insbesondere alternierend/gruppiert, sowie zufällige Varianten. Ein für die jeweilige Domäne geprüfter All-Stop-Start/Rückfall ist erlaubt und wird als Startinformation protokolliert.
- **Keine importierten alten Skip-Stop-Seeds.** Die Tatsache, dass ein frischer Sampler dieselbe gute Struktur erneut konstruiert, ist zulässig und wird als Initialisierungserfolg berichtet.
- Unverändert lassen, was nicht Teil des Vergleichs ist; Auswahlprofil, Decoderparameter, Passagierbudget und Katalog vor Start im Manifest festhalten.

Das Suchziel ist lexikografisch: zuerst Unserved, anschließend Journey Time.
Eine unabhängig validierte Lösung mit U=0 beendet den Evolutionslauf daher
nicht. Sie schließt nur die erste Zielstufe ab; die verbleibende Laufzeit wird
für Journey-Time-Verbesserungen und alternative Skip-Stop-Strukturen genutzt.

## 4. Versuchsblöcke und Reihenfolge

### A. Neue T5-Hauptreihe

| ID | Familie | Aktive Kabinen | Nachfrage N | Bezug | Seed | Maximalbudget |
|---|---|---:|---:|---|---:|---:|
| A1 | F2 | 62 | 2.918 | reguläre All-Stop-Grenze | 0 | 30 min |
| A2 | F2 | 62 | 3.210 | `ceil(1.1 * 2918)` | 0 | 30 min |
| A3 | F3 | 62 | 7.153 | reguläre All-Stop-Grenze | 0 | 10 min |
| A4 | F3 | 62 | 7.869 | `ceil(1.1 * 7153)` | 0 | 10 min |

**A1 und A2 werden ausdrücklich neu gerechnet.** Alte Resultate dienen ausschließlich dem historischen Vergleich.

A3/A4 sind feste zehnminütige F3-Screenings. Ihr Ende ist ein Zeitlimit und
kein Unzulässigkeitsbeweis. Ein bloß mitgeführter All-Stop-Kandidat wird nicht
als evolutionäre Verbesserung gewertet.

### B. F2-Bestätigung

T5/F2, K=62, N=3.210 zusätzlich **frisch mit Seeds 1 und 2**, jeweils höchstens 30 Minuten. Startinformationen und Konfiguration bleiben wie A2. Keine Lösung aus Seed 0 als Start für Seeds 1/2.

Damit gibt es drei neue unabhängige Seedläufe für den entscheidenden T5/F2-Überlastpunkt. Falls bereits die Initialisierung überall U=0 erreicht, berichten wir genau das; daraus wird kein Evolutionsvorteil konstruiert.

### C. Übertragung auf T6

Ein neuer Lauf T6/F2, K=75, N=3.237=`ceil(1.1 * 2942)`, Seed 0, höchstens 30 Minuten. Kein importierter T5-Fahrplan. Gleiche Katalogregel und gleicher Algorithmus, instanzspezifische Zeiten/Referenz.

Weitere T6-Seeds und T6/F3 gehören nicht zum verpflichtenden Restprogramm.

### D. Freie CP-SAT-Nachoptimierung

Zwei neue Läufe von **demselben besten gültigen Skip-Stop-Zeugen aus den neuen T5/F2-Läufen bei N=3.210**:

| Variante | Flottengrenze | Waiting | Budget |
|---|---:|---:|---:|
| D1 | höchstens 62 aktive Kabinen | 0 | 30 min |
| D2 | höchstens 62 aktive Kabinen | höchstens 120 s je zulässigem STOP | 30 min |

Auswahl des gemeinsamen Starts: beste bestätigte lexikografische Qualität, bei Gleichstand kleinster Seed. Ein gültiger Start mit U>0 darf verwendet werden. Falls die neue Kampagne gar keinen gültigen Skip-Stop-Zeugen liefert, wird D als nicht gestartet dokumentiert; kein stiller Ersatz durch einen alten Zeugen.

Beide Modelle übernehmen Bewegung und Passagiere nur als Hint. Dispatch, STOP/SKIP pro Besuch, Waiting innerhalb der jeweiligen Grenze, aktive Kabinen und Passagierzuordnung bleiben frei. Kein `fixed_plan`, kein `fixed_route_plan` und keine feste Musterbindung. OD-Inventar-Passagiere verwenden.

**Die Rückkehr bleibt trotz freier Entscheidungen durch Abschnitt 2 gebunden. Auch D1/D2 dürfen keine aktive Kabine vorzeitig ausscheiden lassen.** Weniger Kabinen bedeutet: einzelne Einsätze gar nicht aktivieren, nicht ihre Fahrten vorzeitig beenden.

D2 beginnt mit demselben No-Wait-Zeugen wie D1, nicht mit dem Ergebnis von D1. Sonst wären die Verbesserungen nicht sauber vergleichbar. Beide verwenden Seed 0, zwölf Worker und dieselben übrigen Suchparameter. Die genauen Parameter werden eingefroren; keine neue Parameterablation.

Ein besseres Ergebnis mit Waiting wird als Ergebnis eines erweiterten Betriebsvertrags ausgewiesen. Native Schranken und Gap gelten nur für das jeweilige vollständige Modell. Kein globaler Gap für die Evo-Suche.

### E. Optionale K-Sensitivität

Nur nach Abschluss der Hauptblöcke und bei verbleibendem Budget:

- T5/F2, N=3.210, **exakt K=56** und **exakt K=69**, Seed 0, jeweils höchstens 30 Minuten.
- Gleicher Linienalgorithmus, No-Wait, frische Initialisierung und gleiche Katalogregel. Die Nachfrage bleibt unverändert.
- K=62 stammt aus der neuen Hauptreihe. Kein weiterer K-Sweep.

Dies sind Fixed-K-Vergleiche. Ein schwaches Resultat bei exakt K=69 beweist keinen Nachteil einer Verfügbarkeit von höchstens 69 Kabinen; dort bliebe der K62-Plan zulässig. Für All-Stop kein infeasibles dichtes K69-Schema als normale Referenz erzwingen: Der K62-Referenzplan bleibt als Referenz unter einer Verfügbarkeitsgrenze 69 erhalten und wird entsprechend beschriftet.

F0 und F4 werden in dieser neuen Kapazitätskampagne nicht zusätzlich gerechnet. Ihre bestehenden Befunde bleiben erhalten. F0 besitzt zudem noch ein offenes Referenzintervall; F1 ist im aktuellen Fallbuilder nicht implementiert.

## 5. Budget und Prozessführung

| Block | Höchstes Gesamtbudget |
|---|---:|
| Vorbereitung, Referenzbewertung und Korrektheitsgates | 40 min |
| A: vier neue Hauptläufe | 80 min |
| B: zwei neue F2-Bestätigungen | 60 min |
| C: ein neuer T6-Übertragungsversuch | 30 min |
| D: zwei CP-SAT-Nachoptimierungen | 60 min |
| E: zwei optionale K-Varianten | 60 min |
| Abschluss, Validierung und Bericht | 30 min |
| **Maximum einschließlich optionalem Block** | **360 min = 6 h** |

Ohne E höchstens 5 h. Die festen F3-Screenings dauern jeweils höchstens zehn
Minuten. Eingesparte Zeit startet keine zusätzlichen Versuche.

Vor Ausführung eine absolute Kampagnendeadline entsprechend der noch verfügbaren Zeit setzen. Bei kürzerem Restfenster zuerst E streichen, anschließend optionale Erweiterungen nicht beginnen; bereits gestartete Ergebnisse bleiben gesichert. Abschlussreserve schützen.

Alle Solverjobs sequenziell, bestehender Supervisor, höchstens 32 GiB Prozessbaum-RSS und systemweite Speicherdruckkontrolle. CP-SAT zwölf Worker; der feste Passagier-IP innerhalb der Evolution ein Thread. Die sequentielle Decoderarbeit wird nicht als Zwölf-Kern-Suche beschrieben. Beste Zertifikate sofort sichern und unabhängige Prozessführung/Fortsetzung beibehalten.

Jeder Einzelbudgetwert umfasst Vorbereitung des jeweiligen Laufs, Modellbau, Suche und Abschluss. Eine fehlende notwendige Korrektheitsprüfung wird nicht zugunsten eines Performanceversuchs übersprungen. Reicht der Vorbereitungsblock nicht, wird die offene Voraussetzung dokumentiert und der betroffene Versuch nicht gestartet.

## 6. Gates vor Ausführung

1. **Lebenszyklus:** Kleine Fälle mit Rückkehr genau zu H und benachbarten Ticks prüfen. Vorzeitige Rückkehr auch für leere Kabinen ablehnen; Durchfahrt vor H und Fortsetzung akzeptieren. Eine spätere als die erste mögliche Umlaufrückkehr an/nach H ablehnen.
2. **Waiting:** Dieselbe Regel mit W120 prüfen. Wartefreigabe, maximale Wartezeit und operative Endgrenze unverändert einhalten. Schutzintervalle hinter H berücksichtigen.
3. **Modell/Validator:** Die Regeln sowohl im Linienpfad als auch im vollständigen CP-SAT erzwingen und unabhängig validieren. Alte Referenzchecks, die nur physikalische Kollisionsfreiheit prüfen, reichen nicht aus.
4. **Frischer Start:** Kein alter Skip-Stop-Checkpoint, keine alten Cacheeinträge und kein Resume in A/B/C/E. Initialkandidaten und All-Stop-Startinformationen im Manifest protokollieren.
5. **Nachoptimierung:** Gemeinsamen neuen Start in D1/D2 vor Übergabe validieren. Ein kleiner Test bestätigt, dass der Hint frühere Halte-/Timingentscheidungen nicht fixiert und inaktive Einsätze zulässig bleiben.
6. **Referenzen:** Nachfragezahl, Freigaben, Horizont, Port und Rückkehrvertrag abgleichen. Referenzkapazität und Served-Wert bei höherem N nicht verwechseln.
7. **Frontend:** Anzeige von K exakt versus Kmax, Waiting, Lebenszyklus, neuer/übernommener Lösung, tatsächlichem Laufstatus und gültigem Scope der Schranken prüfen.

## 7. Auswertung und Darstellung

Je Fall speichern und anzeigen:

- verfügbare und tatsächlich aktive Kabinen, Nachfrage und Referenzvertrag;
- Bedienung, Unserved und Journey Time in Personen-Sekunden;
- Qualität des frisch erzeugten Initialbesten und echte Verbesserungen danach;
- erste gültige Lösung, Zeit bis U=0, letzter Fortschritt und Abbruchgrund;
- Mustermischung, Dispatchzeiten und bei D die frei optimierten Haltefolgen/Waitingwerte;
- explizite Bestätigung der Rückkehrregel, Code-/Domänenhashes und validierte Zertifikate;
- beim CP-SAT native Incumbents, Lower Bound und Gap; beim Evo ausschließlich tatsächlich vorhandene Kennzahlen.

Im Frontend die gestrichelte All-Stop-Bedienung/Journey-Linie für **dieselbe Nachfrage** verwenden. Eine zusätzliche Markierung der Profilkapazität muss anders beschriftet sein. Unbewiesene Referenzoptimalität und ungeklärte Suchausgänge sichtbar lassen.

Der Abschlussbericht beantwortet getrennt:

1. Gibt es neue gültige Zeugen oberhalb der regulären All-Stop-Profilgrenze?
2. Hat Evolution gegenüber der frischen Konstruktion etwas verbessert?
3. Kann CP-SAT diese Zeugen weiter verbessern, ohne vorzeitige Rückkehr?
4. Was gewinnt die zusätzliche Waitingfreiheit?
5. Falls E ausgeführt wird: Welche beobachteten Unterschiede entstehen bei kleinerem/größerem festem K?

Neue und historische Läufe werden nicht zu einer gemeinsamen Fortschrittskurve oder einer scheinbar einheitlichen Seedserie zusammengeführt.
