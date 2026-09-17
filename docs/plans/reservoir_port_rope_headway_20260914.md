# Plan: Rope-Headway am gemeinsamen Reservoiranschluss

Stand: 14.09.2026. **Umgesetzt und geprüft** für CP-SAT, Linienplanung,
CP-SAT-Reparatur und Reservoir-Phasen-Arc-Flow. IBM und native Alternativsolver
lehnen den neuen Vertrag ausdrücklich ab.
[Abnahme, historische Replays und Messungen](../findings/reservoir_port_rope_headway_20260914.md).
Die Arbeit umfasst Implementierung, kurze Korrektheitsprüfungen und die
anschließende Aktualisierung der Thesis. Keine große Solverkampagne ist Teil
dieses Plans.

## 1. Bestätigter Modellvertrag

Architektur B bleibt unverändert: SKIP bleibt am Hauptseil, STOP verlässt es
über eine idealisierte selektive Ausschleusung. Eine zusätzliche mechanische
Einfahr-/Auskuppelressource wird nicht eingeführt. Plattform, Waiting,
Wiedereinkuppeln, B-Fehlerabstand und Service-Mechanismus bleiben erhalten.

Neueinsätze werden mit Seilgeschwindigkeit am bestehenden Reservoir-Grenzzustand
eingefügt. Ein gemeinsamer Kontrollquerschnitt sichert dort den bereits aus der
Physik abgeleiteten Rope-Headway gegenüber allen anderen Nutzungen dieses
Punkts. Interne Lagerbewegungen und das Beschleunigen vor der Einspeisung
bleiben idealisiert. Single-Use bleibt erhalten.

Für den vorhandenen Ein-Port-Ring werden folgende Ereignisse am selben
Grenzquerschnitt erfasst:

- erstmaliger Dispatch;
- jede weitere Umlaufpassage;
- letzte Ankunft am Grenzpunkt vor dem Ausscheiden ins Reservoir.

Die letzte Ankunft gehört zum gemeinsamen Querschnitt; ein zusätzlicher
gegenläufiger Rückfahrweg innerhalb des Depots wird nicht erfunden. Diese
Topologie wird in der Thesis gezeichnet. Eine spätere Variante mit räumlich
getrennter Entnahme wäre ein anderer Vertrag, keine stillschweigende Optimierung.

Für aktive Ereignisse mit Zeitpunkten t_e ist das geschützte Intervall

    I_e = [t_e, t_e + h_R_tick),  h_R_tick = ceil(h_R / tick_seconds).

Alle Intervalle desselben physischen Ports sind disjunkt. Sortierte Zeitpunkte
erfüllen somit t_(j+1) - t_j >= h_R_tick. Die Sortierung bezeichnet die
tatsächliche zeitliche Folge, nicht eine vorgegebene Kabinen-ID-Reihenfolge.
Genau der geforderte Abstand ist zulässig. Der Eintritt am Betriebshorizont
zählt; die Schutzdauer wird anschließend nicht abgeschnitten.

h_R wird aus der bestehenden Rope-Headway-Ableitung übernommen. Kein
Plattformheadway, STOP-Fehlerheadway, Dispatchraster oder historischer Zahlenwert
ersetzt diese Größe. Für neue Thesisfälle gilt die bestätigte Seilgeschwindigkeit
6 m/s; historische Fälle behalten ihre eigenen Parameter.

## 2. Ausgangsbefund und Integrationsstellen

Pfade in dieser Tabelle sind relativ zu
`src/ropeway_skip_stop_optimization/optimization/ddd/`.

| Stelle | Heutiger Zustand | Geplante Änderung |
|---|---|---|
| `reservoir_cp_sat_problem.py` | idealer Port im Manifest, kein physischer Depotheadway | versionierter Portvertrag und unveränderliche Ressourcenbeschreibung |
| `reservoir_cp_sat_movement.py` | ein Tick je Zustandsereignis; letzte Rückkehr bereits präsent | am Port h_R lange Schutzintervalle für dieselben realen Ereignisse |
| `reservoir_cp_sat_certificate.py` | Ressourcenprüfung und Zustandszeit-Eindeutigkeit | unabhängige Prüfung der vollständigen Portereignisfolge |
| `reservoir_lines/preparation.py` | relative Ressourcenintervalle und Zustandsereignisse, inklusive Rückkehr | Portschutz und Konfliktdomänen vorbereiten, keine Pflicht zur Neuberechnung aller Trajektorien |
| `reservoir_lines/cp_model.py` | Dispatchreihenfolge, Intervall- und Differenzdomänenvarianten, gemeinsame Runden | alle Encodings um denselben Portvertrag ergänzen |
| `reservoir_lines/length_scaling.py::saturated_all_stop_reference` | Sättigungsheadway nur aus Route-Ressourcen | neuen Portschutz in der periodischen Referenz explizit berücksichtigen |
| `reservoir_capacity/network.py`, `resource_structure.py`, `model.py` | anonyme Ereignisknoten und Ressourcenkapazitäten | jede tatsächliche Portpassage genau einmal schützen, auch Sink-Rückkehr |
| `reservoir_ibm_cp_model.py` | Legacy- und native Besuchsmodelle | neue Portintervalle bei Unterstützung; andernfalls frühzeitige Ablehnung des neuen Vertrags |

Die heutige Ressourcenableitung steht in
[`optimization/headway_policy.py`](../../src/ropeway_skip_stop_optimization/optimization/headway_policy.py).
Der [Audit, § 3](../findings/headway_physics_audit_20260911.md) enthält das
reproduzierbare Gegenbeispiel zweier Dispatches im Abstand von einer Mikrosekunde.
Die chronologische Dispatchbedingung allein behebt es nicht allgemein und
schützt insbesondere keine neue Kabine gegenüber einer Umlaufpassage.

## 3. Umsetzung in überprüfbaren Schritten

### A. Portvertrag und Herkunft der Parameter

Eine kleine unveränderliche `ReservoirBoundaryPolicy` vorsehen; vorgeschlagene
Varianten `legacy_ideal` und `shared_rope_headway`. Sie enthält mindestens
Port-ID, Grenzzustand, h_R in Integer-Ticks, Ereignisumfang und Herkunft der
Ableitung. Gemeinsam genutzte Typen bleiben solverfrei.

Den Wert an der vorhandenen physischen Headway-Policy abgreifen und explizit
über den Adapter zum Reservoirproblem transportieren. Falls der DDD-Kern
diese Information nicht trägt, sie in der Reservoirvorbereitung ergänzen;
nicht aus irgendeinem minimalen Exit-Headway schätzen. Fehlt die belastbare
Zuordnung, Modellbau mit verständlicher Fehlermeldung ablehnen.

Parameterkonsistenz: Änderung von Seilgeschwindigkeit oder relevanten
Geometrie-/Abstandsparametern erfordert eine neue Ableitung. Eine reine
Streckenlängenänderung lässt h_R bei gleicher Technik unverändert, ändert
aber die Passagezeitpunkte. Erzeugung über `replace`, Skalierungsadapter,
vorbereitete Linienvorlagen und gespeicherte Konfliktdomänen darauf prüfen.
Alte Vorbereitungen werden über den Problem-Fingerprint abgewiesen. Eine
fehlende Angabe darf nur beim eindeutig historischen Schema als Legacy
interpretiert werden; eine neue Thesisfall-Spezifikation muss die Policy
ausdrücklich enthalten.

Die Umrechnung in Ticks verwendet die bestehende konservative Quantisierung
einmalig. Exakt ganzzahlige Tickwerte dürfen durch binäre Float-Artefakte nicht
versehentlich einen weiteren Tick erhalten; echte Bruchteile dürfen nicht
abgerundet werden. Entsprechende Grenzwerte separat testen.

Die neue Regel verändert die zulässigen Bewegungen: neuer **physischer
Problem-Fingerprint**, zusätzlich wie bisher Modell-Fingerprint. Alte Manifest-
Serialisierung und Hashes für `legacy_ideal` bytekompatibel erhalten. Insbesondere
darf ein neues Dataclass-Feld über `asdict` nicht unbemerkt alle alten Hashes ändern.

Zwischentest: alter Checkpoint lädt unverändert; identische Physik mit neuem
Portvertrag bekommt einen anderen Fingerprint. Fehlende/ungültige Headways
werden abgewiesen. Kein globaler Defaultwechsel für historische Runner.

### B. Unabhängiger Prüfer zuerst

Aus dem vollständigen Zertifikat Dispatch, Umlaufpassagen und letzte Rückkehr
rekonstruieren. Pro Ereignis genau einen Eintrag erzeugen; ein Umlaufgrenzpunkt
ist nicht gleichzeitig zwei verschiedene Intervalle. Sortierte Ereignisse
auf den Mindestabstand prüfen, auch zwischen verschiedenen Ereignistypen und
bei aufeinanderfolgenden Passagen derselben Kabine.

Der Prüfer verwendet den physischen Vertrag und die exportierten Trajektorien,
keine Solverintervalle oder vorberechneten Konfliktlisten. Fehlermeldung:
Port, Kabinen, Ereignistypen, Zeitpunkte, Istabstand und Sollabstand.

Zwischentest: Mikrosekunden-Gegenbeispiel bleibt unter Legacy zulässig und wird
unter dem neuen Vertrag gezielt als Portkonflikt zurückgewiesen. Konfliktfreie
Pläne behalten ihre Beförderungsmengen und Reisezeitwerte.

### C. CP-SAT und Linienplanung

CP-SAT: vorhandene Ereignispräsenz wiederverwenden. Dispatch ist präsent bei
aktivem Einsatz; spätere Knoten einschließlich letzter Rückkehr bei aktiver
vorheriger Bewegung. Ein inaktiver Folgeeintrag erzeugt kein Intervall.
Am Port feste Größe h_R statt lediglich eines Eindeutigkeitsticks verwenden;
andere Zustände behalten ihre bisherige Regel. Eine eigene physische Port-ID
und klare Statistikbezeichnung verhindern Verwechslungen mit synthetischen
Zustandsressourcen. Kein zusätzliches Routenliteral erforderlich.

Linienplanung: für `legacy_templates`, `shared_rounds` und `shared_rides` sowie die
`intervals`-/`dispatch_domains`-Encodings denselben Schutz abbilden. Die
Rückkehrpräsenz aus der vorherigen aktiven Runde erhalten; dies ist bereits
im Kommentar zur Rundengrenze in `cp_model.py` beschrieben. Die längste
Mustervorlage darf keine Phantomrückkehr ungewählter Folgerunden erzeugen.
Differenzdomänen müssen positive Headway-Konfliktfenster berücksichtigen,
nicht nur gleiche Zustandszeitpunkte ausschließen.

Nur heute unterstützte Kombinationen freigeben: `legacy_templates` mit
`intervals` und `dispatch_domains`; `shared_rounds` und `shared_rides` mit
`intervals`. `shared_events` und `path_selection` bleiben wie bisher
nicht implementiert. Die Portänderung erweitert diese Variantenliste nicht.

Auch Timing-/Waiting-Reparatur und fixierte Passagier-Neubewertung müssen
das neue Problem mitsamt Portvertrag übernehmen. Waiting verschiebt spätere
Portpassagen; es gibt kein zusätzliches Waiting direkt auf dem Portquerschnitt.
Die bestehende Dispatchsymmetrie und zulässige Überholungen bleiben erhalten.

Zwischentest: alle Linienencodings und vollständiges CP-SAT stimmen auf kleinen
fixierten Fahrplänen hinsichtlich Portzulässigkeit überein.

### D. Arc-Flow, weitere Backends und Schranken

Im anonymen Phasennetz Portereignisse an Knoten beziehungsweise deren eindeutigem
Nutzungsindikator modellieren. Mehrere ein-/ausgehende Phasenarcs dürfen dieselbe
Passage nicht mehrfach zählen. Dispatch- und Rückkehrarcs allein reichen nicht,
weil auch weiterfahrende Kabinen die Ressource benutzen. Eager Cliquen oder
die bestehende äquivalente Ressourcenstruktur für [t,t+h_R) wiederverwenden.

Nicht portfähige historische Backends dürfen `shared_rope_headway` nicht
still ignorieren. Vor ihrem Modellbau ablehnen, bis ein getesteter Adapter
existiert. Priorität haben die aktuell verwendete Linienplanung, deren
Repair-Pfad und CP-SAT; danach der vorhandene Reservoir-Phasen-Arc-Flow.
Fixed-K-Labelled-Arc-Flow erhält keinen künstlichen Reservoirbetrieb.

All-Stop und Skip-Stop unter demselben Reservoirvertrag vergleichen. Die
regelmäßige Fixed-Start-All-Stop-Referenz behält ihren eigenen Anfangsvertrag;
ihre Passageabstände am entsprechenden Querschnitt einschließlich Randphase
prüfen, statt nachträglich eine Reservoir-Dispatchphase hinzuzufügen.

Konkreter Referenzadapter: `saturated_all_stop_reference` bestimmt den
bindenden Abstand aktuell ausschließlich aus `option.resource_usages`.
Eine separate Boundary-Ressource würde dort sonst fehlen. Für den unterstützten
regelmäßigen Ein-Port-Ring den Referenzheadway als Maximum des bisherigen
bindenden Headways und h_R bilden und K_AS daraus erneut ableiten. Den
tatsächlich erzeugten periodischen Fahrplan einschließlich des Abstands von
der letzten Kabine zur ersten des nächsten Umlaufs unabhängig prüfen.
Diese Berechnung bleibt eine Sättigung innerhalb der regelmäßigen
No-Wait-Referenzklasse, kein globaler All-Stop-Kapazitätsbeweis.

Port-IDs bezeichnen physische Querschnitte, nicht bloß Stationsnamen. Der
Ein-Port-Ringadapter darf nicht ungeprüft auf zwei Richtungen oder T6L mit
Terminals angewendet werden. Nicht unterstützte Topologien explizit ablehnen;
ihre spätere Unterstützung ist kein Bestandteil dieses lokalen Patches.

Relaxationen dürfen den zusätzlichen Portschutz optimistisch weglassen und
bleiben dann schwächer, sofern die restliche Domäne übereinstimmt. Für eine
Übernahme alter globaler Bounds muss die Mengeninklusion ausdrücklich
nachgewiesen sein. Lokale Zeitnetz-Bounds werden dadurch nicht global.
Standardmäßig keine automatische Übernahme fremder Fingerprints.

### E. Checkpoints, Runner und neue Thesisfälle

Gemeinsame Option `--reservoir-port-policy legacy_ideal|shared_rope_headway`
in den betroffenen Reservoir-Runnern; neue Thesisfall-Spezifikationen wählen
explizit `shared_rope_headway`. Export enthält Policy, Headway, Quelle,
Problem-/Modell-Fingerprint und Validierungsstatus.

Eine ausdrücklich ausgeführte Migration rekonstruiert einen alten Plan unter
dem neuen Problem und validiert ihn erneut. Keine Zeiten verschieben, keine
positiven Ride-Mengen löschen und keine Herkunftsdatei überschreiben.
Scheitert die Prüfung, einen Konfliktbericht ausgeben. Eine spätere reparierte
Lösung ist ein neues Ergebnis. Bounds und Optimalitätsbehauptungen werden nicht
mit dem Fahrplan kopiert.

## 4. Testmatrix und Freigabe

| Test | Erwartung |
|---|---|
| Abstand h_R−1 Tick / h_R / h_R+1 Tick | ablehnen / zulassen / zulassen |
| Dispatch–Dispatch mit allen STOP/SKIP-Paaren | gleiche Portregel; Stationsregeln zusätzlich unverändert |
| Dispatch–Durchfahrt und umgekehrte zeitliche Folge | beide geschützt, unabhängig von Kabinen-ID |
| Rückkehr–Dispatch, Durchfahrt–Rückkehr, Rückkehr–Rückkehr | gleicher Schutz am gemeinsamen Querschnitt |
| Weiterfahrt an einer Rundengrenze | genau eine Belegung, keine Selbstkollision durch Doppelzählung |
| Letzte Rückkehr ohne aktiven Folgebesuch | Portintervall bleibt vorhanden |
| Ungenutzte Kabinen/inaktive Runden | keine Phantomintervalle bei Zeit null |
| Eintritt am Horizont | voller Schutz über den Horizont hinaus |
| Waiting verändert spätere Portankunft | neue Zeit wird in Solver und Prüfer berücksichtigt |
| Headway nicht durch Dispatchschritt teilbar | keine Abrundung; tatsächliche Tickzeiten maßgeblich |
| Überholung abseits des Ports | weiterhin zulässig; keine globale Reihenfolgebindung |
| Mehrere verschiedene Port-IDs im Typentest | keine versehentliche gemeinsame Ressource |
| `shared_rides` und sämtliche unterstützten Linienkombinationen | gleicher Portvertrag, gleiche Zulässigkeit bei fixierter Bewegung |
| h_R kleiner/größer als bisheriger All-Stop-Referenzheadway | K_AS unverändert beziehungsweise korrekt reduziert; periodischer Randabstand geprüft |
| Geschwindigkeitsänderung / reine Längenänderung | Headway neu abgeleitet / unverändert; Passagezeiten jeweils korrekt |
| Alte Vorbereitung unter neuer Policy oder Physik | Fingerprintfehler statt Wiederverwendung |
| Neuer Thesisfall ohne explizite Policy | Konfigurationsfehler statt stiller Legacy-Rückfall |
| Legacy und Fixed-K | bestehende Zertifikate, Werte und Defaults unverändert |

Kleine vollständig enumerierbare Fälle zusätzlich gegen die direkte sortierte
Abstandsprüfung testen. Bei erzwungenen Bewegungen Solverzulässigkeit und
unabhängige Prüfung vergleichen; bei mindestens einem kleinen freien
Reservoirfall muss der Solver selbst eine gültige Lösung finden.

Historische Referenzen mit mindestens All-Stop, Skip-Stop und Waiting prüfen.
Neue Ausgabe je Plan: minimaler Portabstand, erforderlicher Abstand,
Konfliktzahl, Status unter altem/neuem Vertrag und unveränderte Passagierwerte
bei erfolgreichem Replay. Historische Artefakte bleiben unangetastet.

Erst nach diesen Tests kurze Aufbau-/Laufzeitvergleiche auf identischen
eingefrorenen Fällen durchführen, höchstens 60 s Suchzeit je Variante,
sequenziell. Variablen, Intervalle, Aufbauzeit, Speicher und validierte
Ergebnisse erfassen. Eine strengere Physik darf die beste Bedienung verringern;
das ist kein Implementierungsfehler. Aus der lokalen Ergänzung folgt kein
Versprechen schnellerer Suche. Lange Optimierungsläufe sind separat zu planen.

Zusätzlicher Ende-zu-Ende-Test: neuer Fall → Runner → Solver → exportierter
Checkpoint → erneutes Laden → unabhängige Prüfung; dabei unveränderte Policy,
h_R und Fingerprints verlangen. Mindestens ein Import eines alten Plans darf
unter neuem Vertrag scheitern und ein anderer erfolgreich migrieren.

Abnahmebericht mit einer unterstützten Backend-/Encoding-Matrix und tatsächlichen
Testergebnissen abschließen. Nicht implementierte Pfade gelten nur dann als
abgesichert, wenn ihre ausdrückliche Ablehnung des neuen Vertrags getestet ist.
Die erste Codeprüfung kann mit der vorhandenen synthetischen Geometrie erfolgen;
die neue Thesisgeometrie wird nach ihrer separaten Kalibrierung erneut geprüft.

## 5. Thesisänderungen und wissenschaftliche Einordnung

Die konkrete Kapitel- und Ergebnischeckliste steht im
[Thesis-Änderungsplan](../../../idp_report/version_2/docs/reservoir_port_headway_plan_20260914.md).
Die Kapitel werden nach Implementierung und Abnahme auf den tatsächlich
getesteten Vertrag umgestellt. Bis dahin bleibt der Unterschied zwischen
heutigem Code und geplantem neuen Thesisfall ausdrücklich sichtbar.

Quellen und Grenzen:

- [Headway-Physikaudit, insbesondere §§ 2–3 und Einfahrtsannahmen](../findings/headway_physics_audit_20260911.md):
  eigener Code-/Modellbefund und Gegenbeispiel, keine Herstellerquelle.
- [Problembeschreibung, Architektur B und Einfahrtsannahmen](../../../idp_report/version_2/chapters/03_problem_definition.tex):
  vorhandene explizite technische Modellannahmen.
- [Headway-Ableitungen](../../../idp_report/version_2/appendices/headway_derivations.tex):
  vorhandene Herleitung der physischen Abstände. Die Portregel verwendet h_R,
  nicht den B-Fehlerabstand am Stationsausgang.
- [Haimerl et al. (2022), § 4.1, S. 1418](https://informs-sim.org/wsc22papers/138.pdf):
  Evidenz für die gewählten Geschwindigkeiten und Kabinenkapazität, kein
  Nachweis unserer Reservoirgeometrie oder unseres konkreten Seilabstands.

Die Ressource am Port ist unsere Modellierung eines gemeinsamen
Einspeisequerschnitts. Es wird keine detaillierte oder zertifizierte reale
Depotanlage behauptet. Die ideale Auskuppelannahme von B bleibt bestehen.
