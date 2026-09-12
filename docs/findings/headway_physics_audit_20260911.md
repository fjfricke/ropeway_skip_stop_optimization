# Headway-Audit: Ressourcenvertrag, Weicheneinfahrt und physikalische Annahmen

Stand: 11.09.2026. Anlass: Prüfung der Headways während des zweistündigen P2-R2-Laufs. Die Solverimplementierung, eingefrorenen Quellen und laufenden Versuche wurden nicht verändert. Es liefen ausschließlich kurze solverfreie Prüfungen zusätzlich zur Codelektüre. Dieser Audit ist keine vollständige Prüfung sämtlicher historischer Backendvarianten.

## Ergebnis

Die untersuchten Ressourcenbedingungen setzen den heutigen abstrakten Vertrag konsistent um. Daraus folgt noch nicht, dass jede akzeptierte Trajektorie eine real ausführbare Seilbahnbewegung ist. Ein konkretes Gegenbeispiel zeigt eine Lücke bei der Interpretation des idealen Reservoirports als reale gemeinsame Einfahrstelle. Die STOP-Merge-Regel ist dagegen innerhalb ihres angenommenen Fehlerszenarios bewusst konservativ. Die kurze Stationsgeometrie enthält zudem starke, bisher nicht über Beschleunigungsgrenzen abgesicherte Bewegungsannahmen.

Empfehlung: bestehende native Ressourcen-/Intervallmodelle beibehalten, den Port und die Einfahrgeometrie zuerst präzisieren, Architektur B als dokumentierten Referenzfall erhalten. Eine engere Bremswegformel ist eine gesonderte physikalische Sensitivität. Architektur A oder C ist eine Änderung der Anlagentechnik, keine bloße Solververbesserung.

## Untersuchte Codekette

| Schicht | Dateien | Befund |
|---|---|---|
| Geometrie und Architektur | `examples/artificial_headway_cases.py`, `examples/circular_skip_stop.py`, `models/headway.py` | B, experimentelle Parameter, feste Geschwindigkeitsprofile |
| Ableitung | `optimization/headway_policy.py` | Plattformabstand, Seilhüllkurve, gerichteter STOP-Fehlerabstand, separater Mechanikzyklus |
| Reduktion | `optimization/headway_resource_reduction.py` | Mechanik wird nur nach lokalem Dominanznachweis entfernt |
| EAN | `optimization/ean/builders/headway_checkpoint_builder.py`, `headway_rule_evaluation.py`, `headway_semantics.py` | Richtungsabhängige Paarabstände, besondere Waiting-Belegung |
| DDD-Übertragung | `optimization/ddd/artifact_adapter.py`, `models.py`, `time_ticks.py` | Route trägt eigene Schutzdauer; Headways werden nach oben quantisiert |
| CP-SAT | `optimization/ddd/cp_sat_movement.py`, `reservoir_cp_sat_movement.py` | Optionale geschützte Intervalle und `NoOverlap`; getrennte Ressourcenreihenfolgen |
| IBM, Ressourcenabschnitt | `optimization/ddd/reservoir_ibm_cp_model.py` | Dieselben affinen Eintritts-/Räumzeiten und `no_overlap` |
| Aktueller Arc-Flow | `optimization/ddd/reservoir_capacity/network.py`, `model.py`, `resource_structure.py` | Exakte Intervallbelegung auf dem eingeschränkten Zeitnetz; Waiting phasenweise |
| Reservoir-Prüfer | `optimization/ddd/reservoir_cp_sat_certificate.py` | Prüft ursprüngliche DDD-Ressourcen und Passagiere, rekonstruiert keine Anlagengeometrie |
| Zusätzliche Geometrieprüfung | `frontend/src/safety/geometry.ts`, `certifyReplaySafety.ts` | Kontinuierliche Prüfung für EAN-Replayartefakte; nicht Bestandteil des Reservoir-Checkpointprüfers |

Dateipfade sind relativ zu `src/ropeway_skip_stop_optimization`, sofern nicht anders angegeben. Die acht zentral geprüften Python-Dateien sind bytegleich mit dem laufenden eingefrorenen Versuch; siehe `frozen_source_checks.json`.

## 1. Aktuelle Werte und ihre Bedeutung

Fünf-Stationen-Geometrie: Kabinenlänge 3 m, geometrischer Aufhängungsabstand 4,22 m, Schwingwinkel 0,34 rad, Clearance 0,5 m, Seilgeschwindigkeit 5 m/s und Plattformgeschwindigkeit 0,5 m/s.

\[
d_R=3+2(4{,}22)\sin(0{,}34)+0{,}5
 =6{,}3146310577\ \mathrm m,
\qquad h_R=d_R/5.
\]

Nach Aufrundung auf Mikrosekunden ergibt sich am Exit-Merge:

| Führende Kabine | Folgende SKIP | Folgende STOP |
|---|---:|---:|
| SKIP | 1,262927 s | 1,262927 s |
| STOP | 4,620070 s | 4,620070 s |

Diese Tabelle gilt **am gemeinsamen Exit-Merge**, nicht pauschal an jedem Stationsbeginn. Zusätzlich gelten für STOP an der Plattform 7 s und ursprünglich 6 s für den Service-Kuppelmechanismus. Für zwei STOP-Kabinen auf demselben deterministischen Servicepfad ist damit die effektive Einschränkung mindestens 7 s. SKIP nutzt die Plattform nicht.

Der größere Wert nach STOP gehört zur Annahme, dass eine fehlerhaft eingekuppelte Servicekabine ihren Nachfolger behindern kann. Er ist keine allgemeine Wartepflicht von 4,62 s nach jeder beliebigen Kabine. Die Richtung der Matrix ist im untersuchten Code korrekt.

## 2. Ressourcen, Waiting und Randzeiten

Die geschützte Ressourcennutzung ist

\[
[t+f+\alpha w,\ t+l+\beta w+h_{\mathrm{Route}}).
\]

Für den aktuellen Vertrag bedeutet das:

- Plattformankunft: beide Waiting-Koeffizienten null; die frühe Ressource verschiebt sich nicht.
- Plattformausgang: Eintritt am frühesten Ausgang, Räumung am tatsächlichen Ausgang; Waiting verlängert die Belegung.
- Exit-Merge: Eintritt und Räumung verschieben sich gemeinsam um Waiting; die Schutzdauer selbst wird nicht um Waiting verlängert.
- Phasen-Arc-Flow: Holdingkanten schützen den Aufenthalt, die Austrittskante trägt die abschließende Schutzzeit. Sie wird nicht auf jeder Holdingkante erneut addiert.
- Ressourcenintervalle sind halboffen. Genau der geforderte Abstand ist zulässig, ein Tick weniger nicht.
- Betritt am Betriebshorizont zählt; eine begonnene Schutzzeit wird nicht am Horizont abgeschnitten.
- Die Ressourcen dürfen unterschiedliche Reihenfolgen haben. Bypass-Überholen wird nicht durch eine globale Kabinenreihenfolge verboten.

Die Plattformregel ist für die festgelegte Geometrie eines einzelnen Wartepunkts am Ende eines mit konstanter Geschwindigkeit durchfahrenen Plattformabschnitts sinnvoll: Der Nachfolger muss beim Beginn des Wartens und bis zur Freigabe ausreichend weit zurückbleiben. Sie ist **kein** Modell eines FIFO-Puffers mit mehreren unabhängig wartenden Kabinen oder variablen Fahrgeschwindigkeiten auf der Plattform.

Die Entfernung der 6-s-Mechanikressource ist hier begründet: Bei No-Wait überträgt sich die 7-s-Plattformfolge durch feste Zeitoffsets auf die Mechanik. Mit Waiting übernimmt die verlängerte Plattformausgangsbelegung diesen Nachweis. Ein pauschales Löschen der Mechanik bei anderen Geometrien wäre nicht zulässig; dafür bestehen Ablehnungs-/Beibehaltungstests.

## 3. Konkretes Gegenbeispiel: idealer Reservoirport

`reservoir_cp_sat_problem.py` bezeichnet den Vertrag ausdrücklich als `ideal_entry_state_no_depot_resource_unique_state_tick_v1`. In `reservoir_cp_sat_movement.py` reserviert ein Zustandsbesuch nur einen Tick. Der Kommentar stellt klar, dass dies Eindeutigkeit und kein physikalischer Depotheadway ist. Arc-Flow verwendet entsprechend höchstens eine Kabine pro identischem Zustandszeitpunkt. Der Validator lehnt gleiche Zeitpunkte ab, aber nicht beliebig kleine positive Abstände.

Auf der **unveränderten R2-Domäne** wurde folgender vollständiger Plan konstruiert:

- Kabine 0 startet an `A_entry_cw` bei 300,000000 s und fährt überall STOP.
- Kabine 1 startet dort bei 300,000001 s, fährt an A SKIP, danach STOP.
- Beide kehren rechtzeitig zurück und bedienen jeweils eine Person B→D.
- `validate_reservoir_cp_plan` akzeptiert den Plan.
- Das Phasennetz kann beide Pfade auf einem kleinen expliziten Kalender reproduzieren; seine Ressourcenzeilen sind erfüllt.

Das beweist eine Lücke gegenüber einer **gemeinsamen realen Einfahrstelle**, keine Verletzung des ausdrücklich idealisierten Softwarevertrags. Aus dieser Prüfung folgt nicht, dass genau diese Mikrosekundenanker im laufenden `seed_events_v1`-Netz vorhanden sind.

Bei einer realen gemeinsamen Einfahrt sind zwei Kabinen im Abstand von einer Mikrosekunde nicht durch die Kabinengeometrie gedeckt. Ausfahrende, durchfahrende und gegebenenfalls zurückkehrende Kabinen müssen entsprechend ihrer tatsächlichen gemeinsamen Konfliktzone geprüft werden. Ob Ein- und Rückfahrten dieselbe Zone teilen, muss aus der Porttopologie folgen.

Auf den normalen Seilabschnitten entsteht der Abstand bereits aus dem vorherigen Exit-Merge: Für dieselbe Seilkante gilt eine identische konstante Fahrtzeit, also bleibt der zeitliche Abstand erhalten. Diese Implikation fehlt für eine neu eingesetzte Kabine, die im Port ohne vorherige Seilkante erscheint. Deshalb ist die Aussage „im ganzen Netz fehlt die Einfahrtsseparation“ zu weitgehend.

Die geprüfte aktuelle Referenz hat an sämtlichen Zustandsbesuchen einschließlich Dispatch/Rückkehr einen kleinsten Abstand von **7,129186 s**. Sie nutzt die Ein-Mikrosekunden-Lücke nicht. Das ersetzt keinen vollständigen geometrischen Nachweis dieser Referenz.

## 4. Konservative STOP-Regel und engere Alternative

Die aktuelle Formel lautet

\[
h_{S,*}=\max\{h_R,d_M/v_M+\tau+v_M/a_M\}.
\]

Sie rechnet für den gesamten Zeitraum bis zum Stillstand mit voller Geschwindigkeit. Mit \(v_M=5\), \(\tau=0{,}5\) und \(a_M=1{,}75\) ergibt das unquantisiert 4,6200690687 s. Das ist unter den dokumentierten Geschwindigkeits-, Verzögerungs- und Hüllkurvenannahmen konservativ; keine falsch herum implementierte Bremsformel.

Wenn ein passendes Bremsprofil einschließlich aller Reaktionsverzögerungen tatsächlich begründet ist, lässt sich stattdessen die zurückgelegte Strecke verwenden:

\[
h_{S,r'}=\max\{h_R,(d_M+d_{\mathrm{stop},r'})/v_M\}.
\]

Bei ideal konstanter Verzögerung und vorgeschalteter Verzögerungszeit wäre
\(d_{\mathrm{stop}}=v_M\tau+v_M^2/(2a_M)\), also hier **3,191498 s** nach Aufrundung. Das ist eine analytische Alternative, kein nachgewiesener sicherer Parameter für eine reale Anlage. Lastzustand, Ruck, Detektionsort, Kopplungszustand und Schwingung müssen zum angenommenen Profil passen. Der offizielle [EMSD-Code, Abschnitt 21](https://www.emsd.gov.hk/filemanager/en/content_623/Code%20of%20Practice%20on%20the%20Design%2C%20Manufacture%20and%20Installation%20of%20Aerial%20Ropeways%202018.pdf) betont insbesondere die Anpassung des Bremsverhaltens an Last und Geschwindigkeit zur Begrenzung der Kabinenschwingung. Er zertifiziert nicht unseren lokalen Mechanismus.

Die engere Regel würde vor allem STOP→SKIP am Merge betreffen. STOP→STOP bleibt in der heutigen Geometrie durch die 7-s-Plattformfolge begrenzt. Ein Performancegewinn oder Kapazitätsdurchbruch folgt daraus nicht automatisch.

Die heute unterstützte Regel hängt nur vom Leader ab. Eine künftig wirklich vom Follower abhängige Bremskurve benötigt eine vollständige Paarregel. Im DDD-Adapter wird gegenwärtig nur ein routebezogener Nachlauf gespeichert; dort dürfte man eine solche neue Matrix nicht ohne Erweiterung hineinreichen.

## 5. Weichenarchitektur und nominale Kinematik

### Einfahrt und Merge sind verschiedene Vorgänge

Die physikalische Policy besitzt Plattform-Eintritt/-Austritt, Exit-Merge und Service-Mechanik. Eine separat parametrierte **Einfahrweiche beziehungsweise Auskuppelzone** fehlt. Für Architektur B wird vorausgesetzt, dass SKIP auf der Hauptlinie bleibt und STOP selektiv auf den Seitenpfad gelangt. Dass dieser Vorgang beliebige zulässige Seilfolgen ohne zusätzliche Belegungs- oder Umstellzeit bewältigt, ist damit eine Modellannahme und kein Ergebnis der Ressourcenprüfung.

Für eine konkrete technische Auslegung sollte der lokale Konfliktbereich mit Einfahr-, Räum- und gegebenenfalls Umstellzeiten beschrieben werden. Daraus folgen routeabhängige Belegungsintervalle oder Paarheadways für STOP→STOP, STOP→SKIP, SKIP→STOP und SKIP→SKIP. Ein einzelner willkürlich größerer Wert an allen Stationen wäre keine saubere Ableitung. Auch zwei geometrisch benachbarte Pfade können einander schon vor dem abstrakten Punktknoten beeinflussen; eine dreidimensionale Hüllkurve ist im aktuellen DDD-Core nicht enthalten.

### A/B/C dürfen nicht nach gewünschtem Optimierungsergebnis gewählt werden

- **A:** Aktive Mehrgleisweiche mit Herstellerintervall. [LEITNER nennt höchstens 2 s Schaltzeit und mindestens 9 s Fahrzeugabstand](https://www.leitner.com/fileadmin/userdaten/00-home/Ordner-Facelift/PDF_s_Logo_neu/Station_sheets/The_LEITNER_Station_quick_switch.pdf). Aus 2 s Schaltzeit darf nicht 2 s Headway werden. Gilt dieser Mechanismus auch am Einlauf, muss dort seine Ressource ausdrücklich abgebildet werden.
- **B:** Default-Bypass mit Stoppen bei Kuppelfehler; entspricht der derzeitigen asymmetrischen Matrix. Die selektive Einfahrt und lokale Fehlerbehandlung bleiben technische Voraussetzungen.
- **C:** Fehlerhafte Servicekabinen bleiben vollständig außerhalb des gemeinsamen Seilbereichs. Nur dann kann der kurze Seilabstand am Merge für alle Kombinationen gelten. Eine dokumentierte konventionelle Kuppelsicherung beweist diese spezielle Ausweicharchitektur nicht. [LEITNERs Kuppelsystem](https://www.leitner.com/fileadmin/userdaten/00-home/Ordner-Facelift/PDF_s_Logo_neu/Station_sheets/The_LEITNER_Station_grip_Coupling.pdf) behandelt Fehlkupplungen, ist aber keine Bestätigung unserer gesamten C-Topologie.

### Kinematische Auffälligkeit des Fünf-Stationen-Testfalls

Der Servicepfad enthält 5 m bei 5 m/s, danach **3 m von 5 auf 0,5 m/s**, 10 m Plattform und symmetrische Beschleunigung/Ausfahrt. `travel_seconds` interpretiert das lineare Geschwindigkeitsprofil über die Durchschnittsgeschwindigkeit. Es ergibt sich für die 3-m-Phase

\[
T=2L/(v_0+v_1)=1{,}090909\ \mathrm s,
\quad |a|=|v_1^2-v_0^2|/(2L)=4{,}125\ \mathrm{m/s^2}.
\]

Das ist nicht der Parameter 1,75 m/s² der separaten Notstoppformel, sondern die implizite nominale Stationskinematik. Der Code weist dafür keine Komfort-/Ruckgrenze nach. Daraus allein folgt kein hier festgestellter Normverstoß; die Anlage und Betriebsart wurden dafür nicht zertifiziert. Für reale Kapazitätsaussagen müssen diese künstlichen kurzen Phasen jedoch begründet oder als Sensitivität durch realistisch begründete Profile ersetzt werden. Änderungen beeinflussen Zykluszeiten, Startpositionen und All-Stop-Referenzen gemeinsam.

## 6. Aussagekraft der Validatoren

Der Reservoir-Prüfer ist unabhängig von Gurobi und CP-SAT, verwendet aber deren zugrunde liegenden **gemeinsamen DDD-Ressourcenvertrag**. Er kann einen vergessenen physikalischen Konfliktbereich nicht aus der Kabinenform rekonstruieren. Insbesondere ruft er nicht die kontinuierliche Frontend-Geometrieprüfung auf. Diese benötigt EAN-Replayartefakte und prüft gleiche sowie benachbarte Graphkanten; sie ist ebenfalls kein allgemeiner CAD-/Hüllkurvenprüfer.

„Unabhängig validiert“ bedeutet hier daher: Zeitkontinuität, Ressourcen, Waiting, Horizont und ganzzahlige Beförderungen innerhalb der vorgegebenen Domäne geprüft. Es bedeutet nicht: die Auslegung der neuartigen Weiche und alle physikalischen Annahmen bewiesen.

## 7. Nächste Schritte, ohne laufenden Versuch umzudeuten

1. Physikalischen Reservoirport festlegen: tatsächliche gemeinsame Einfahr-/Ausfahrbereiche, Anschluss an den laufenden Seilfluss, mechanische Belegung. Zunächst das konkrete Ein-Mikrosekunden-Gegenbeispiel ausschließen; Durchfahrten und Rückkehr nicht vergessen.
2. Einfahrweiche lokal prüfen: gemeinsamer Pfad, Abzweigung, Detektions- und Schaltvorgang, Räumung der Kabinenhülle. Gleichmäßig fahrende Seilabschnitte benötigen keinen künstlich verschärften pauschalen Headway, wenn der vorherige Merge die Separation schon beweist.
3. Separaten geometrischen Replayprüfer für Reservoirzertifikate ergänzen, einschließlich Geburts-/Rückkehrereignissen und Stationsphasen. Bekannte zulässige Grenzfälle sollen ebenso getestet werden wie Kollisionen; nicht nur alte Ressourcenformeln nochmals auswerten.
4. B mit der heutigen konservativen Stoppregel als dokumentierte Referenz behalten. Erst bei begründeter Bremskurve ein getrenntes Bremswegprofil vergleichen. A/C sind eigene Anlagenszenarien.
5. Nominale Stationsbeschleunigung und Schwingungsannahmen begründen; danach All-Stop und Skip-Stop unter derselben geänderten Physik neu bewerten.

Der aktuelle Zweistundenlauf bleibt als Suchdiagnose der eingefrorenen idealisierten Domäne aussagekräftig. Neue physikalische Einschränkungen dürfen nicht still rückwirkend als bereits enthalten dargestellt werden. Jede neue Skip-Stop-Lösung muss vor einem realitätsbezogenen Kapazitätsnachweis auch den ergänzten Port-/Geometrieprüfungen genügen. Die gefundene Portlücke erklärt keine schlechte Incumbentsuche: Sie erweitert zunächst den zulässigen Raum.

## Prüfungen und Artefakte

Unter [`benchmarks/output/headway_audit_20260911/`](../../benchmarks/output/headway_audit_20260911/):

- `reproduce.py`: vollständige solverfreie Reproduktion.
- `near_simultaneous_port_dispatch.json`: akzeptiertes vollständiges R2-Zertifikat mit zwei bedienten Personen.
- `dispatch_counterexample.json`, `phase_counterexample_replay.json`: Domain- und Phasenprüfung des Gegenbeispiels.
- `entry_gaps.json`: Prüfung der aktuellen Referenz und des Gegenbeispiels.
- `merge_endpoint_probes.json`: zwölf Tests für alle vier Routenpaare bei Headway minus einem Tick, exakt Headway und plus einem Tick.
- `physical_calculations.json`: unabhängig nachgerechnete Headways und Stationsbeschleunigungen.
- `frozen_source_checks.json`: Übereinstimmung der auditierten zentralen Quellen mit dem laufenden Versuch.
- `structural_tests.log`: **34 bestanden, 5 abgewählt**, 0,65 s. Abgewählt wurden Solververgleichsfälle und ein größerer Artefaktzähltest, um keinen konkurrierenden Solverjob zu starten.

Die positiven Tests beweisen die geprüften Softwareeigenschaften. Sie widerlegen nicht das daneben dokumentierte physikalische Portgegenbeispiel und zertifizieren keine Hardware.
