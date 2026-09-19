# Algorithmischer Thesis-Kern: exakte Referenzen und skalierbare Linienplanung

Stand: 12.09.2026. Dieses Dokument formuliert die derzeit belastbare
Argumentationslinie für die Thesis. Zahlen und Aussagen beziehen sich auf die
jeweils genannten Instanzen und dürfen nicht ohne erneuten Vergleich auf andere
Nachfrageprofile oder Topologien übertragen werden.

Der konkrete [Versuchsplan vom 13.09.2026](experimental_design_20260913.md)
ordnet Nachfrage- und Streckenkonzepte, Reisezeit- und Kapazitätsziele,
Beweisaussagen, Implementierungslücken und priorisierte Laufbudgets zu.

## Forschungsziel

Untersucht wird, ob eine nachfrageorientierte Skip-Stop-Steuerung bei identischer
Seilbahnphysik mehr Personen bedienen beziehungsweise ihre Reisezeiten senken
kann als ein konventioneller All-Stop-Betrieb. Dafür werden drei methodisch
unterschiedliche Bausteine kombiniert:

1. eine exakt optimierte betriebliche All-Stop-Referenz;
2. ein vollständiges gelabeltes Arc-Flow-Modell für kleine und mittlere
   Fixed-K-Instanzen;
3. eine beschränkte Linienplanung für größere Instanzen mit optionaler Flotte.

Diese Aufteilung ist beabsichtigt. Ein vollständiges Modell liefert auf kleinen
Instanzen exakte Aussagen, skaliert aber nicht zuverlässig zu den großen
Kapazitätsfällen. Die Linienplanung reduziert dort die Zahl unabhängiger
STOP-/SKIP-Entscheidungen und erzeugt schnell hochwertige, physikalisch gültige
Fahrpläne. Globale Aussagen werden nur aus tatsächlich gültigen Schranken oder
aus unmittelbar optimalen Zielwerten abgeleitet.

## 1. Verbindliche All-Stop-Referenz

Alle Kapazitätsergebnisse werden gegen ein gesättigtes **All-Stop-System ohne
Waiting** verglichen. Der vollständige Vertrag steht in der
[All-Stop-Kapazitätsreferenz](../reference/all_stop_no_wait_capacity_baseline.md).

Im aktuellen Fünf-Stationen-Fall werden die maximal gleichzeitig in einem
All-Stop-Umlauf unterzubringenden 38 Kabinen eingesetzt. Alle Kabinen halten an
allen Stationen und füllen den Umlauf gleichmäßig. Bei Umlaufdauer \(C\) und
Kabinenzahl \(K_{AS}\) ist der zeitliche Abstand

\[
h=\frac{C}{K_{AS}}.
\]

Damit sind alle relativen Ereigniszeiten fest. Frei bleibt nur eine gemeinsame
Phase \(\theta\) innerhalb einer Headwayperiode:

\[
d_k=\theta+k h.
\]

Die gemeinsame Phase und die ganzzahlige Passagierzuweisung werden im
Hauptmodell zusammen auf maximale Bedienung optimiert. Kleine unabhängige
Phasensweeps dienen ausschließlich der Kontrolle. Die betriebliche Referenz ist deshalb

\[
S_{AS}^{phase}=\max_{\theta\in[0,h)}
S(\text{All-Stop},\text{No-Wait},K_{AS},\theta).
\]

Sie muss für jede Nachfragehöhe, OD-Verteilung und zeitliche Freigabestruktur
neu bestimmt werden. Der bekannte R2-Wert von 2.496 bedienten Personen ist das
exakte Passagieroptimum für eine feste erste Dispatchzeit von 29,090910 s. Bis
zur nachgewiesenen gemeinsamen Phasenoptimierung ist er nur ein Fixphasenwert und noch nicht
\(S_{AS}^{phase}\).

Ein globaler All-Stop-Bound über eine größere Domäne mit freieren
Dispatchentscheidungen, optionaler Flotte oder Waiting wird zusätzlich
berichtet. Er ersetzt die betriebliche Referenz nicht, kann aber eine stärkere
Aussage ermöglichen.

## 2. Vollständiges gelabeltes Arc-Flow für Fixed K

Das gelabelte Arc-Flow-Modell bildet jede Kabine einzeln in einem vollständigen
zeitlichen Bewegungsnetz ab. Es entscheidet über STOP/SKIP und ganzzahlige
Passagierflüsse unter den exakten Ressourcen- und Headwaybedingungen. In der
hier verwendeten Ausprägung gelten:

- feste Kabinenzahl;
- feste Anfangspositionen;
- kein Waiting;
- vollständige Route- und Passagierentscheidung;
- globaler Optimalitätsnachweis, sobald Upper und Lower Bound übereinstimmen.

Das Modell ist die exakte Skip-Stop-Methode für die lösbare Skalierungsstufe.
Im Five-Station-B-Sweep wurden die Instanzen K17 bis K22 optimal gelöst. Für
den besonders gut kontrollierten Balanced-K20-Vergleich gelten identische
Kabinenzahl, Nachfrage und Anfangsanordnung. All-Stop erreicht dort
635.519,998080 Passagiersekunden, Skip-Stop optimal 525.730,908160. Das
entspricht einer Senkung um 17,28 %.

Dieser Befund betrifft bei vollständig bedienter Nachfrage die Reisezeitkosten,
nicht eine höhere bediente Personenzahl. Eine Kapazitätsaussage benötigt
zusätzliche Nachfrage und das Ziel `unserved`.

Mit steigender Kabinenzahl verliert die Formulierung ihre praktische Stärke.
Für K39 bleiben nach langen Läufen große Gaps und schwache Incumbents. Diese
Skalierungsgrenze ist selbst ein Ergebnis: Die vollständige gemeinsame
Optimierung von Kabinenpfaden, Ressourcenreihenfolgen und Passagieren wird
bereits auf der kleinen Ringtopologie kombinatorisch schwierig.

## 3. Beschränkte Linienplanung für große Kapazitätsfälle

Die Linienplanung ersetzt die freie STOP-/SKIP-Wahl jedes einzelnen Besuchs
durch wiederkehrende Haltemuster. Für R2 enthält der getestete kleine Katalog:

| Linienmuster | Halte je Runde | übersprungene Stationen |
|---|---|---|
| `all_stop` | A, B, C, D, E | keine |
| `stop_B_D` | B, D | A, C, E |
| `stop_C_E` | C, E | A, B, D |

Eine eingesetzte Kabine behält ihr Muster während ihres gesamten Einsatzes.
CP-SAT entscheidet weiterhin gemeinsam über:

- die optionale Flotte bis maximal 50 Kabinen;
- das Linienmuster und die Rundenzahl jeder eingesetzten Kabine;
- streng geordnete Dispatchzeiten;
- sämtliche Ressourcen- und Zustandskonflikte;
- ganzzahlige direkte Passagierzuordnungen.

Das Modell verwendet im aktuellen Pilot kein Waiting. Alle Zeitwerte bleiben
exakte Integer-Mikrosekunden; jeder exportierte Plan wird durch den
ursprünglichen unabhängigen Reservoirvalidator geprüft.

Die Methode ist innerhalb ihres Linienkatalogs eine exakte mathematische
Formulierung. Gegenüber der vollständigen Skip-Stop-Domäne ist sie eine
Approximation, weil eine Kabine ihr Haltemuster nicht frei von Runde zu Runde
oder Besuch zu Besuch ändern kann. Solver-Bounds gelten daher grundsätzlich
nur für den Linienkatalog.

## 4. Hauptbefund auf R2

R2 enthält 3.074 Personen in komplementären Märkten B↔D und C↔E sowie neun
Freigabebuckets. Der finale unabhängig validierte Linienplan verwendet:

- 38 Kabinen;
- 19 Kabinen mit dem Muster B/D;
- 19 Kabinen mit dem Muster C/E;
- keine All-Stop-Kabine;
- kein Waiting;
- vollständige Bedienung aller 3.074 Personen.

Damit gilt

\[
S_{SS}=3.074,\qquad U_{SS}=0.
\]

Obwohl die Linienplanung nur einen Teil der allgemeinen Skip-Stop-Fahrpläne
durchsucht, ist ihr primärer Bedienungswert für diese feste Nachfrage auch in
der größeren Skip-Stop-Domäne optimal: Mehr als alle 3.074 Personen können
nicht bedient werden. Nicht bewiesen sind die minimale notwendige Flotte, die
beste Reisezeit und die globale Optimalität des konkreten Fahrplans bezüglich
sekundärer Ziele.

Für dieselbe vollständige Single-Use-Max50-R2-Domäne liegt bereits ein globaler
All-Stop-Bound vor:

\[
S_{AS}^{*}\le 2.949.
\]

Daraus folgt unmittelbar

\[
S_{SS}=3.074>2.949\ge S_{AS}^{*}.
\]

Der gültige Skip-Stop-Plan bedient somit mindestens 125 Personen mehr als jeder
All-Stop-Plan dieser größeren Domäne. Der Nachweis benötigt kein globales
Skip-Stop-Solverbound. Der noch ausstehende phasenoptimierte
All-Stop-No-Wait-Wert wird trotzdem als obligatorische betriebliche Referenz in
die finale Ergebnistabelle aufgenommen.

## 5. Gemeinsames Versuchsdesign

Die drei Bausteine werden nicht als austauschbare Solver in einem einzigen
Ranking behandelt. Sie beantworten verschiedene Teile der Forschungsfrage.

| Ebene | Methode | Zweck | zulässige Aussage |
|---|---|---|---|
| Betriebliche Baseline | phasenoptimiertes All-Stop-No-Wait | konventionelle Kapazitätsreferenz | bester Wert in der festgelegten gesättigten Referenzdomäne |
| Exakte Skalierungsstufe | gelabeltes Fixed-K-Arc-Flow | vollständige Skip-Stop-Optimierung | globales Optimum, wenn der Gap geschlossen ist |
| Große Kapazitätsstufe | beschränkte Linienplanung | gute gültige Fahrpläne bei optionaler Flotte | validierter Incumbent; Bound nur im Katalog |
| Stärkerer Nachweis | globale All-Stop-Relaxation | Obergrenze bedienbarer All-Stop-Nachfrage | Vorteil eines Skip-Stop-Zeugen bei strikter Boundüberschreitung |

Für jeden direkten Vergleich müssen mindestens folgende Größen identisch oder
ausdrücklich als unterschiedlich gekennzeichnet sein:

- Topologie, Stationskinematik und Headwayregeln;
- Kabinenkapazität und verfügbares Flottenmaximum;
- Nachfragegruppen, Mengen und Freigabezeiten;
- Warm-up, Bedienungshorizont und Rückkehrvertrag;
- Optimierungsziel und Definition rechtzeitiger Bedienung;
- Anfangszustand beziehungsweise zulässige Dispatchphase.

Beim Fixed-K-Arc-Flow werden feste Anfangspositionen verwendet. Ein Vergleich
gegen eine phasenoptimierte All-Stop-Referenz gibt All-Stop mehr Freiheit und
ist damit für einen gefundenen Skip-Stop-Vorteil konservativ, ersetzt aber
keinen kontrollierten Vergleich mit identischen Starts. Deshalb werden zwei
Zeilen berichtet: derselbe feste Anfangszustand für den methodischen Vergleich
und die phasenoptimierte All-Stop-Referenz für die betriebliche Einordnung.

## 6. Vorgeschlagene Ergebnisdarstellung

Die finale Auswertung trennt Bedienung und Reisezeit:

| Szenario | Methode | K / Kmax | Starts/Phase | Waiting | bedient | unbedient | Reisezeit | Status/Gültigkeit |
|---|---|---:|---|---:|---:|---:|---:|---|
| kleine Instanz | All-Stop | fest | gleiche Starts | 0 | … | … | … | exakt |
| kleine Instanz | Labelled Arc-Flow | fest | gleiche Starts | 0 | … | … | … | exakt bei Gap 0 |
| R2 | All-Stop-No-Wait | 38 | Phase optimiert | 0 | **ausstehend** | **ausstehend** | … | exakte Referenz |
| R2 | Linienplanung | max. 50, genutzt 38 | Dispatch optimiert | 0 | 3.074 | 0 | Kontrollwert | validierter Primärwert |
| R2 | globale All-Stop-Domäne | max. 50 | frei | bis 1.200 s | höchstens 2.949 | mindestens 125 | – | globaler Bound |

Für Solverläufe werden übernommene Hints, erste native Lösungen,
Verbesserungsereignisse und globale Bounds getrennt ausgewiesen. Ein Timeout
oder `UNKNOWN` ist kein Unzulässigkeitsbeweis. Ein kleiner Gap darf nur aus
Bounds derselben Domäne berechnet werden.

## 7. Belastbare Thesis-Aussagen

Auf Basis des aktuellen Stands sind folgende Aussagen zulässig:

1. **Exakter kleiner Vergleich:** Im kontrollierten Balanced-K20-Fall senkt
   das optimale Skip-Stop-Ergebnis die Reisezeitkosten gegenüber All-Stop um
   17,28 %.
2. **Skalierungsbefund:** Das vollständige gelabelte Arc-Flow löst die kleine
   K-Stufe exakt, skaliert aber bei dichterer Belegung nicht ausreichend.
3. **Wirksame Suchraumstrukturierung:** Wiederkehrende komplementäre
   Linienmuster erzeugen auf R2 innerhalb kurzer Laufzeit einen physikalisch
   gültigen Vollbedienungsplan.
4. **Kapazitätsvorteil auf R2:** Der Skip-Stop-Zeuge bedient 3.074 Personen und
   damit mindestens 125 mehr als jeder All-Stop-Plan der untersuchten größeren
   R2-Domäne.
5. **Primäroptimum auf R2:** Null unbediente Personen ist für die feste
   R2-Nachfrage bezüglich der Bedienungszahl optimal, auch wenn sekundäre Ziele
   und die minimale Flotte offenbleiben.

Nicht zulässig sind daraus allgemeine Aussagen, dass B/D- und C/E-Muster für
jede Nachfrage optimal seien, dass die Linienplanung die vollständige
Skip-Stop-Domäne löse oder dass Waiting grundsätzlich keinen Nutzen habe.

## 8. Noch erforderliche Absicherung

Vor der finalen Thesisfassung sind folgende Schritte vorrangig:

1. die gesättigte R2-All-Stop-No-Wait-Referenz mit direkter gemeinsamer
   Phasenvariable und Integer-Passagierzuweisung optimieren;
2. dieselbe Referenz für jede tatsächlich berichtete Nachfrageinstanz
   berechnen;
3. die kleinen Arc-Flow-Vergleiche nach Bedienung und Reisezeit sauber trennen;
4. mindestens einen neutraleren Nachfragefall verwenden, um die
   R2-Spezialisierung sichtbar zu machen;
5. Modellgrößen, Laufzeiten, letzte Verbesserung und Gapentwicklung für beide
   Skip-Stop-Methoden gemeinsam berichten;
6. alle final verwendeten Zertifikate erneut mit dem unabhängigen Validator
   prüfen und ihre Quellversionen festhalten.

Weitere Solverarchitekturen sind für diese Argumentationslinie derzeit weniger
wichtig als diese konsistente Absicherung. Der Beitrag liegt in der Verbindung
aus exakter kleiner Referenz, dokumentierter Skalierungsgrenze und einer
strukturierten Linienplanung, die auf der großen Kapazitätsinstanz einen
vollständig bedienenden gültigen Fahrplan findet.

## Interne Evidenzquellen

- [Verbindliche All-Stop-Kapazitätsreferenz](../reference/all_stop_no_wait_capacity_baseline.md)
- [Reservoir-Linienmodell und R2-Ergebnisse](../findings/reservoir_line_dispatch_pilot_20260912.md)
- [Audit der Solverläufe](../findings/solver_history_audit.md)
- [Fixed-K-Kapazitätstest](../findings/fixed_start_capacity_20260910.md)
- [Globale R2-All-Stop-Schranke](../findings/reservoir_capacity_phase_pilot_20260911.md)
- [Implementierter Fixed-K-Arc-Flow-Vertrag](../reference/ddd_fixed_k_arc_flow.md)
