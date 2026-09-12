# Reservoir-DP: symbolische Zeiten und Gruppen-/Haltemuster gemeinsam testen

Stand: 12.09.2026. **Pilot umgesetzt und mit ersten R2-Läufen geprüft.**

Implementierter Vertrag: [Symbolic reservoir DP](../reference/reservoir_dp.md).
Erste Messungen: [Reservoir DP pilot: first findings](../findings/reservoir_symbolic_and_pattern_dp_20260912.md).

Aus dem Pilot verbleiben als getrennt zu prüfende Formulierungsschritte eine
sichere STN-Variablenprojektion, Zoneninklusion als Dominanz und eine ausdrücklich
approximative FIFO-Ressourcenreihenfolge innerhalb einer Haltemustergruppe. Jeder
Schritt benötigt Differentialtests gegen den hier dokumentierten exakten Kern.

## 1. Ziel, Varianten und Abgrenzung

Wir testen die im Gespräch ausgewählten Optionen 2 und 3:

- **Z2 / `symbolic_visits`:** besuchsweise DP mit freien STOP/SKIP-Entscheidungen,
  ganzzahligen Passagieren und symbolischen Zeitnetzen.
- **Z3 / `pattern_groups`:** derselbe Zeit- und Passagierkern, aber gemeinsame
  Haltemuster für wählbare Gruppen von Kabinen. Dies schränkt den Suchraum
  ausdrücklich ein und soll gute Strukturen mit weniger Entscheidungen finden.

Beide suchen Flottengröße, Dispatch, Trajektorien und Einsatzende gemeinsam.
Die Suche hält keinen All-Stop-Fahrplan als unveränderlichen Hintergrund fest.
Es gibt keine eigene LNS, keine Greedy-Insertion bereits vollständig fixierter
Kabinen und keinen Muster-Master mit anschließendem großen CP-SAT-Timing-Solve.
Die vorhandene Engine **RPID/CABS** übernimmt die Suche. Neu implementiert werden
Domänenzustand, Übergänge, ganzzahlige Zeitpropagation und Zertifikatsadapter.

Umfang des ersten Pakets:

- bestehender gerichteter Fünf-Stationen-Ring;
- maximal 50 identische Kabinen, **Single-Use-Reservoir**;
- eine Kabine darf einmal ausfahren und muss rechtzeitig zurückkehren;
- volle bestehende Waitingbereiche, exakte Integer-Mikrosekunden;
- ausschließlich `unserved`, intern Maximierung rechtzeitig ausgelieferter
  Personen; Reisezeit nur unabhängig berechnete Kontrollkennzahl;
- unabhängige Validierung gegen die unveränderte Reservoir-Domäne;
- bestehende Solver, Defaults, Checkpoints und Ergebnisse bleiben erhalten.

Nicht Bestandteil: wiederholter Reservoireinsatz, Fixed-Start-Backend,
Doppelring, Reisezeitoptimierung, gelernte Wertfunktion, neuer Benders- oder
Column-Generation-Controller, optimistische Zustandsverschmelzung für neue
globale Bounds. Option 1 aus dem Gespräch wird nicht als dritter Solver gebaut.

**Approximation ist keine Lockerung der Physik.** Z2 begrenzt zunächst nur die
Suchbreite. Z3 beschränkt zusätzlich die Haltemuster. Es wird weder eine
prozentuale Approximationsgarantie noch ein praktischer Optimalitätsbeweis
vorausgesetzt. Große Läufe setzen die unten definierten Zwischentests voraus.

## 2. Ausgangspunkt und konkrete Integrationsstellen

| Bestehender Pfad unter `src/ropeway_skip_stop_optimization/optimization/ddd/` | Verwendung |
|---|---|
| `reservoir_cp_sat_problem.py` | maßgebliche Domäne, Besuchsgrenzen, kanonische Ride-IDs, erster Zielbesuch |
| `reservoir_cp_sat_certificate.py` | `DddReservoirCpPlan`, `DddReservoirCpTrip`, Checkpoint-I/O, unabhängige Validierung |
| `cp_formulation.py` | solverfreie `PreparedCpStructure` und sichere Grenzen prüfen/wiederverwenden |
| `native_solvers/model.py` | `PreparedNativeStructure`/`prepare_native_structure` als vorhandene Vorbereitung prüfen; keine Z3-/Hexaly-Algebra übernehmen |
| `reservoir_cp_sat_movement.py` | Referenz für Lebenszyklus, Zustandskollisionen, Waiting-Freigabe und Ressourcengeometrie |
| `reservoir_cp_sat.py` | bestehender vollständiger Kapazitätsoptimizer für Kontrolltests und Vergleich |
| `reservoir_assignment/timing.py` | kleine Differenzialtests mit fixierten Entscheidungen; kein Aufruf je DP-Zustand |
| `didp/` | bisheriger Fixed-K-DIDPPy-Pilot bleibt unverändert |
| `reservoir_hybrid/domain.py` | vorhandenen Referenzimport prüfen/wiederverwenden |

Vor der Übernahme vorbereiteter Grenzen deren Gültigkeit für aktive/inaktive
Reservoirbesuche prüfen. Keine engere alte Arc-Flow-Dispatchdomäne übernehmen.

Der bisherige DIDP-Pilot verwendet bereits CABS. Neuheit ist daher ausdrücklich
die Zustands- und Übergangsformulierung, nicht der Name der Suche. Die jüngste
Assignment-Diagnose endete in allen fünf 120-s-Läufen mit UNKNOWN. Das ist keine
Unzulässigkeit und kein Nachweis einer einzelnen dominanten Ursache.

Bezug: [DIDP-Befund](../findings/ddd_fixed_k_didp_pilot_20260910.md),
[Assignment-Diagnose](../findings/reservoir_assignment_conflict_diagnosis_20260912.md).

## 3. Gemeinsamer Modellvertrag

### 3.1 Unveränderliche Vorbereitung und klare Verantwortlichkeiten

Ein neues Python-Paket `optimization/ddd/reservoir_dp/` erhält:

- `config.py`: unveränderliche Konfigurationen und explizite Profilprüfung;
- `preparation.py`: `PreparedReservoirDp`, Ereignis-/Ressourcenausdrücke,
  Nachfrage, Indizes und JSON-Schema ohne Solvervariablen;
- `engine.py`: versionsgeprüfter RPID-Prozessadapter;
- `certificate.py`: Übergangsreplay, Kabinen-/Ride-Zuordnung, bestehende Prüfer;
- `optimizer.py`: gemeinsame API und getrennte Referenz-/Suchresultate;
- `report.py`: Metriken, Ereignisse und Vergleichsauswertung.

Ein eigenständiges Rust-Crate `native/ropeway_reservoir_dp/` erhält:

- `domain.rs`, `state.rs`, `labels.rs`;
- `temporal.rs`: Integer-STN/DBM, Referenzabschluss, inkrementelle Propagation;
- `resources.rs`: Ressourceneinordnung und Zustandskollisionen;
- `passengers.rs`: Bündel, Nachfragebilanzen und Ausstiegsverpflichtungen;
- `symbolic_visits.rs`, `pattern_groups.rs`: zwei Übergangspolitiken;
- `bounds.rs`, `replay.rs`, `main.rs`.

Zeit-, Ressourcen- und Passagierbausteine werden geteilt. Z3 soll nicht einen
zweiten Gesamtsolver kopieren. Z3 bezeichnet hier **Variante 3, nicht den
SMT-Solver Z3**; öffentliche Profile heißen deshalb ausschließlich
`symbolic_visits` und `pattern_groups`.

Die Python-API nimmt ein `DddReservoirCpSatProblem`, eine Konfiguration und
optional einen geprüften Referenzcheckpoint entgegen. Datenaustausch erfolgt
über versioniertes JSON/JSONL; keine Python-Callbacks je Suchzustand. Rust wird
separat gebaut, sodass bestehende Python-Installation und Solver ohne Rust
weiter funktionieren. Kein automatischer Download während eines Solverlaufs.

Physikalischer Fingerprint und Ride-IDs bleiben unverändert. Modell-Fingerprint
enthält Vorbereitung, Profil, Musterrestriktionen, Zeitkernversion und
Engineversion. Quellen einschließlich uncommitteter Dateien werden gehasht;
der Git-Commit allein reicht im aktuellen Workspace nicht.

### 3.2 Zeitdarstellung und unterstützte Domäne

Rust verwendet geprüfte `i64`-Ticks; Additionen und Pfadschluss verwenden
überlaufgeprüfte beziehungsweise breitere Zwischenrechnung. Unendlich ist
explizit repräsentiert, keine zufällig große physikalische Zeit. Vor Aufbau
werden Zeit-/Mengenobergrenzen geprüft. Keine Float-Toleranz beim Timing.

Der erste STN-Adapter unterstützt **Dispatch- und Waiting-Schrittweite ein Tick**,
wie in R0/R2. Größere Schrittweiten erzeugen Kongruenzbedingungen, die ein reines
STN nicht abbildet: vor Modellbau verständlich ablehnen, niemals still runden.
Tests mit anderen Schrittweiten prüfen zunächst diese Ablehnung.

Alle Ressourcenendpunkte müssen aus einem Ereigniszeitpunkt plus Integerkonstante
darstellbar sein. Der Compiler prüft dies aus den tatsächlichen Koeffizienten.
Nicht unterstützte Geometrie blockiert den Adapter; kein stilles Ersatzmodell.

### 3.3 Unveränderte Physik und Beförderungen

- Plattformankunft ist der Ausstieg; Ziel-Waiting verzögert diesen nicht.
- Einstieg erfolgt am tatsächlichen Plattformausstieg nach Waiting.
- Ausstieg vor Einstieg; ganzzahlige Last vor/nach dem Besuch höchstens Q.
- Freigabe und Servicehorizont gelten exakt wie im Zertifikatsprüfer.
- Positive Wartezeit ist nur erlaubt, wenn bereits der **früheste**
  Plattformausstieg die Waiting-Freigabephase erreicht; Null-Waiting bleibt frei.
- Jeder Passagier muss beim ersten Zielbesuch aussteigen. Kein SKIP mit offener
  Ausstiegsverpflichtung, keine zusätzliche Runde, kein Umstieg.
- Zwischen Bewegungen keine freie Lücke; Waiting nur am erlaubten Ort.
- Ressourcenbetritt genau am Betriebshorizont zählt. Schutzzeit danach bleibt.
- Dispatch, alle aktiven Ereignisknoten und der letzte Rückkehrknoten behalten
  die eindeutige Zustands-/Zeitbelegung. Der Tick für Eindeutigkeit wird nicht
  als neuer physikalischer Port-Headway ausgelegt.
- Rückkehr nur am Port im ursprünglichen Rückkehrfenster und ohne offene
  Ausstiege. Zurückgekehrte Kabinen werden nicht erneut verfügbar.

## 4. Schritt A: Enginefähigkeit und Vertrag zuerst prüfen

RPID zunächst auf Version **0.4.0** aus der veröffentlichten Paketquelle pinnen,
`Cargo.lock`, Rust-Version und Paketchecksumme speichern. Die aktuell gelesene
Quelle verlangt Rust >=1.90. Vor Festlegung der Buildanleitung Verfügbarkeit
und API der gepinnten Version lokal prüfen.

Minimaler technischer Versuch ohne Seilbahnmodell:

1. Nativer `Dp`-Zustand enthält eine kanonisch vergleichbare kleine Zeitmatrix.
2. CABS löst ein winziges Maximierungsproblem mit bekanntem Ergebnis.
3. `search_next` liefert kopierbare Übergangsfolgen für jede gemeldete Lösung.
4. Breitenlimit, Laufzeitlimit, `keep_all_layers`, Status und native Bounds
   werden mit kleinen absichtlich abgeschnittenen Suchen geprüft.
5. Native parallele CABS-Schnittstelle prüfen; tatsächliche Threads und
   Parallelitätskosten messen. Keine selbst gebaute Prozessportfolio-Suche.

**Gate A:** Baubarer, reproduzierbarer Adapter, korrektes Maximierungsziel,
Unterbrechung ohne falschen Beweis und lesbare Ergebnisfolgen. Fehlt eine
notwendige API, vor größerem Modellbau dokumentieren. Keine eigenen Änderungen
am Enginecode als stiller Ersatz.

## 5. Schritt B: Exakten symbolischen Zeitkern bauen

### 5.1 Phasen ausdrücken

Pro STOP-Besuch mit Beginn a, frühestem Plattformausstieg b und tatsächlichem
Plattformausstieg d:

    b = a + platform_exit_offset
    0 <= d - b <= station_max_wait
    next = d + (route_duration - platform_exit_offset)
    arrival = a + platform_entry_offset

Alle Konstanten stammen aus der Domäne. SKIP hat `next = a + duration` und
kein Waiting. Die Alternative `d=b` versus `d>=b+1` verzweigt den Waiting-
Freigabevertrag; sie zählt als explizite interne Entscheidung.

Ein Ressourcenausdruck `a + offset + c*(d-b)` wird bei c=0 zu `a+offset`,
bei c=1 zu `d+offset-platform_exit_offset`. So bleiben frühe Ressourcen,
durchgehende Exit-Belegung und verschobene Merge-Belegung getrennt korrekt.

Bedingte Ressourcenpräsenz wird exakt verzweigt, sofern die Zeitgrenzen sie
nicht schon entscheiden: Eintritt <= H versus Eintritt >= H+1. Keine Abfrage
eines abwesenden Intervalls. Positive Intervallgröße nachweisen.

### 5.2 STN, Reihenfolgen und Konsistenz

Zeitbedingungen haben die Form `t_j - t_i <= c`. Eine geschlossene DBM speichert
auch abgeleitete Beziehungen zwischen Zeitpunkten. Ein negativer Zyklus
beweist die Unzulässigkeit **dieses Zweigs**.

Ressourcen besitzen eine Liste der bisher eingefügten symbolischen Intervalle.
Ein neues Intervall wird an jeder nicht nachweislich unmöglichen Position
versucht; Vorgänger-/Nachfolgerbeziehungen ergänzen die Nichtüberlappung.
Noch nicht geplante Bewegungen dürfen später dazwischen eingefügt werden.
Mehrere Nutzungen derselben Bewegung werden ebenfalls vollständig geprüft.

Die Einordnung wird je Ressource separat gewählt. Keine stationsübergreifende
FIFO-Annahme, keine feste Reihenfolge aller Kabinen. Zustandskollisionen werden
als eigene Ein-Tick-Belegungen behandelt, einschließlich Rückkehrknoten.
Für einen vollständigen Plan müssen sämtliche erforderlichen Disjunktionen
entschieden oder logisch impliziert sein.

Ein konsistentes STN mit Integerkonstanten erlaubt die Extraktion ganzzahliger
Zeitpunkte. Dies allein beweist noch nicht die Korrektheit der Übersetzung:
Phasen, Präsenzfälle, Ressourcen und Passagierentscheidungen müssen vollständig
im STN beziehungsweise diskreten Zustand enthalten sein.

### 5.3 Referenz zuerst, Kompaktheit danach

Zuerst vollständigen Zeitgraphen als langsamen Referenzkern implementieren.
Danach inkrementelle Propagation gegen erneuten vollständigen Abschluss testen.

Erst anschließend alte Zeitpunkte projizieren: nach vollständigem Abschluss
dürfen Variablen entfallen, wenn keine zukünftige Bedingung direkt darauf
zugreifen kann und sämtliche Beziehungen der verbleibenden Grenzvariablen
erhalten bleiben. Für Ressourcen müssen frühere Einfügepositionen zuerst
nachweislich unerreichbar sein. Es gibt bei symbolischen Zeiten keinen frei
gewählten globalen Jetzt-Zeitpunkt, vor dem pauschal gelöscht werden darf.

Ressourcen von zurückgekehrten Kabinen bleiben gegebenenfalls weiter relevant.
Rekonstruktion nutzt unveränderliche Übergangslabels und ein vollständiges
Replay; historische Zeiten dürfen dabei innerhalb der gespeicherten Bedingungen
neu konkretisiert werden. Keine nachträgliche Timing-Suche.

**Gate B:** STN-Feasibility stimmt bei fixierten diskreten Entscheidungen mit
exakter Enumeration kleiner Tickbereiche und CP-SAT überein. Inkrementeller und
vollständiger Abschluss sowie projizierter und unprojizierter Kern stimmen
auf sämtlichen Fortsetzungstests überein.

## 6. Schritt C: Z2 als vollständiges diskretes Modell bauen

### 6.1 Zustand und Konstruktionsreihenfolge

Zustand:

    Flottenentscheidung / noch unbenutzte Slots
    je eingesetzter Kabine: nächster Besuch, Lebenszyklus, Bordmengen nach Ziel
    verbleibende Nachfrage je ursprünglicher Gruppe
    symbolischer Zeitgraph und Ressourcenordnungen
    offene diskrete Arbeitsphase / kanonischer Entscheidungscursor

Vergangene Routen und Ride-Mengen stehen im Übergangszeugnis. Nur ihre noch
relevanten Folgen bleiben im Suchzustand. Vergangene Bedienung ist Suchkosten-
beitrag und wird nicht zusätzlich als unabhängige Entscheidungsvariable geführt.

Die umgesetzte DP aktiviert Kabinen **lazy**. Nach jeder vollständigen Rückkehr
wählt CABS zwischen Beenden mit dem aktuellen K und Aktivieren des nächsten Slots
bis Kmax. Dessen Dispatchzeit bleibt symbolisch frei und wird nur zur sicheren
Symmetriebrechung nach dem vorherigen Dispatch geordnet. Dies ist weder eine
vorgegebene feste Flotte noch ein externer K-Sweep. Die zuerst getestete
K=0,...,Kmax-Wurzelverzweigung wurde verworfen, weil sie denselben
Erstkabinenpräfix bis zu 50-mal duplizierte. K=0 bleibt durch sofortiges Beenden
zulässig, zählt aber nicht als erfolgreicher Bedienungstest.

Kabinenlabels folgen nur der sortierten Dispatchreihenfolge identischer
Reservoirkabinen. Die entsprechende Umbenennung wird beim Export vollständig
auf Rides übertragen. Keine zusätzliche Austauschbarkeitsdominanz aktiver Kabinen.

Besuche werden in einer festen **Konstruktionsreihenfolge** bearbeitet: eine
Kabine bis zur Rückkehr, danach der nächste lazy aktivierte Slot. Diese Reihenfolge
setzt keine Zeitbedingung zwischen Kabinen. Ressourcenlisten erlauben weiterhin
die spätere Einfügung vor, zwischen oder nach schon bearbeiteten Bewegungen.

### 6.2 Besuchsentscheidung und Passagiere

Für die gewählte Kabine:

1. Am Port nach mindestens einem Umlauf: Rückkehr oder Fortsetzung wählen.
2. STOP/SKIP wählen; offene Zielverpflichtung erzwingt rechtzeitigen STOP.
3. Ausstieg verbuchen und Bordkapazität freigeben.
4. Ganzzahliges Einstiegsbündel aus kanonischen Rides dieses Besuchs wählen.
5. Freigaben, Zielverpflichtungen, Phasen und Ressourcenordnungen ergänzen.
6. Konsistenten Folgezustand mit nächstem Besuch ausgeben.

Bündel enthalten alle ganzzahligen Mengen innerhalb Nachfrage und Restkapazität.
Die Generierung erfolgt lazy, mit sicheren frühen Grenzen. Keine bloße Auswahl
zwischen leer/voll. Technisch unvermeidliche Teilentscheidungen über Bündel und
Ressourceneinfügung werden als Phasen sichtbar gezählt, nicht in einer riesigen
unbeobachteten Nachfolgerliste versteckt.

**Exakte erste Kompression:** Bordmengen nach erster Zielstation statt nach allen
künftigen Besuchsslots. Bei dieser Domäne ist der entsprechende Zielbesuch aus
dem laufenden Besuchsindex eindeutig. Bereits gebuchte Freigabebedingungen bleiben
im Zeitnetz; kanonische Herkunft bleibt im Zeugnis.

**Bewusst nicht vorweggenommen:** R2 besitzt neun Freigabegruppen je OD. Solange
Abfahrten symbolisch und nicht chronologisch konstruiert sind, dürfen diese
nicht einfach zu einer Queue zusammenfallen. „Eine OD bedeutet nur neun
Mengenentscheidungen 0..8“ gilt nicht automatisch für die Zuordnung zu neun
Freigabebuckets. Zunächst bleiben die ursprünglichen 36 Gruppen erhalten.
FIFO nach Konstruktionsreihenfolge wäre keine sichere Vereinfachung.

### 6.3 Suchkosten, Schranken und Gleichheit

Ein erzwungener rechtzeitiger Ausstieg gibt positive Integerkosten im
Maximierungsmodell. Nur vollständige Rückkehrpläne ohne offene Verpflichtungen
sind Endzustände. `U = D - S` wird beim Export unabhängig bestätigt.

Erste sichere Restschranke: offene Ausstiege plus verbleibende Nachfrage.
Danach optional Abzug nachweislich unerreichbarer Gruppen anhand optimistischer
Ankunft und Rückkehr, getrennt gegen vollständig gelöste Fortsetzungen geprüft.
Ressourcenkonkurrenz darf für diese Schranke optimistisch ignoriert werden.
Eine heuristische Auslastungsstrafe darf nicht als native Dualschranke auftreten.

Initial nur exakte Zustandsduplikate zusammenfassen: gleicher diskreter Inhalt,
gleiche kanonisch geschlossene Zeitbeziehungen und Ressourcenstruktur. Weder
„früher ist immer besser“ noch allein gleiche Position/Belegung ist Dominanz.
Zoneninklusion als zusätzliche Dominanz gehört erst nach separatem Beweis dazu
und ist nicht Voraussetzung des ersten Vergleichs.

Unbeschränkte Suche auf kleinen Fällen dient dem Äquivalenznachweis. Im Pilot
verwendet native CABS initiale Breite 64 und maximale Breite 1024. Nach direktem
Vergleich ist `keep_all_layers=False` der Primalstandard: ältere
Duplikatregister werden freigegeben, ohne Übergänge zu entfernen. Der Modus
`True` bleibt für Diagnosen auswählbar. Keine eigene Breiten-, K-Quoten- oder
Diversitätssteuerung im ersten Paket.

**Gate C:** Freie kleine Fälle reproduzieren die enumerierten Kapazitätsoptima;
historische Reservoirpläne sind durch Übergangsreplay darstellbar. Vollständigkeit
der diskreten Verzweigung und der Zeitdarstellung wird schriftlich begründet.

## 7. Schritt D: Z3 als gemeinsame Haltemuster, mit demselben Zeitkern

### 7.1 Erste getestete Einschränkung: `whole_trip`

Eine Gruppe besteht aus in Dispatchreihenfolge aufeinanderfolgenden Slots. Die
Suche wählt zunächst eine STOP/SKIP-Maske über alle Stationen. Nach jeder
Kabinenrückkehr entscheidet sie zwischen einem weiteren Slot derselben Gruppe,
dem Schließen der Gruppe mit anschließender neuer Maskenwahl und dem Beenden der
Flotte. Die Gruppengröße bleibt so solverbestimmt, ohne alle möglichen Endgrößen
am Gruppenanfang zu vervielfachen; die Zeiten bleiben symbolisch offen.

- Alle Masken, die mindestens eine vorhandene direkte Nachfrage bedienen können,
  werden automatisch erzeugt; bei fünf Stationen höchstens 32. Masken ohne ein
  mögliches Origin-Ziel-Paar werden entfernt, weil eine völlig leere aktive
  Kabine für `unserved` sicher durch einen ungenutzten Slot dominiert wird.
- Mitglieder teilen lediglich die Maske für ihren gesamten einmaligen Einsatz.
- Dispatch, Waiting, Passagiermengen und Zahl der Umläufe bleiben je Kabine frei.
- Gruppen sind keine Züge mit konstantem Abstand und keine physische FIFO-Kette.
- Verschiedene Gruppen dürfen gleichzeitig unterwegs sein und sich überholen.
- Besuche und Ressourcen werden danach gemeinsam, verschränkt wie in Z2
  konstruiert. Keine vollständige Gruppe wird zeitlich fixiert, bevor die nächste
  Gruppe berücksichtigt wird.

Ein frei optimierter gemeinsamer Abstand in `d_j=d_0+j*delta` wäre im Allgemeinen
kein einfacher STN-Ausdruck. Diese zusätzliche Kopplung wird nicht eingeführt.
Zeitliche Abstände ergeben sich aus individuellen Ereignisvariablen und den
originalen Ressourcenbedingungen.

Die Einschränkung ist klar: Jede Kabine verwendet während ihres Einsatzes
dieselbe stationsbezogene Maske. Zusätzliche Beschränkungen durch Gruppengröße
entfallen, weil Größe eins zulässig bleibt. Benachbarte Gruppen mit gleicher
Maske können kanonisch vereinigt werden, nach Test der Äquivalenz.

Die Maske darf keine offene Zielverpflichtung überspringen. Rides werden nur
angeboten, wenn ihr erster Zielbesuch STOP ist. Nullbeladung bleibt möglich;
eine Kabine wird nicht zur sofortigen Bedienung gezwungen.

### 7.2 Konkrete Kontrollprofile und spätere Erweiterung

Für Tests `singleton_patterns`: gleiche Whole-Trip-Masken, alle Gruppengrößen
gleich eins. Die zulässigen Lösungen müssen exakt mit `pattern_groups/whole_trip`
übereinstimmen; lediglich die Entscheidungstiefe unterscheidet sich.

Ein Testfall mit notwendigem Maskenwechsel zwischen Umläufen muss zeigen, dass
Z2 besser sein darf als beide Whole-Trip-Profile. Diese Differenz ist eine
beabsichtigte Approximation, kein Implementierungsfehler.

`per_lap` mit Maskenwechsel pro Umlauf ist ein **bedingter Folgeschritt**: erst
nach Auswertung von `whole_trip`, nicht zusätzlicher versteckter Kampagnenlauf.
Offene Beförderungen über die Umlaufgrenze müssen bei einem solchen Wechsel
erhalten bleiben. Im ersten Paket wird der Erweiterungspunkt vorbereitet,
der Modus in der CLI jedoch als nicht implementiert abgelehnt.

**Gate D:** Z3 = Singleton-Whole-Trip = Enumeration/CP-SAT unter identischen
Maskenrestriktionen auf kleinen Fällen; alle exportierten Pläne bestehen die
ursprünglichen Prüfer. Freie Suche entdeckt komplementäre Muster aus der
vollständigen Bibliothek, ohne einen Musterseed zu übernehmen.

## 8. Schritt E: Zertifikate, Replay und öffentliche Runner

Neuer Runner `benchmarks/run_reservoir_dp.py`:

- `--variant symbolic_visits|pattern_groups`;
- `--objective unserved`, `--operating-mode all_stop|skip_stop`;
- bisherige Domänen-, Nachfrage-, Flotten-, Horizont- und Waitingparameter;
- `--time-limit`, `--workers`, `--memory-limit-gib`;
- `--initial-beam-width`, `--max-beam-width`;
- `--checkpoint-import`, `--output`, `--build-only`, `--replay-only`;
- `--pattern-scope whole_trip` nur für `pattern_groups`;
- Testoptionen für Vollgraph/Projektion und Singleton-Gruppen, ausdrücklich
  getrennt von produktiven Profilen.

Nicht unterstützte Kombinationen werden vor Modellbau abgelehnt. Ein Build-only
Resultat berichtet Vorbereitung und Ausgangszustand, keine MIP-Modellgrößen und
keine vorgetäuschte vollständige Zustandszahl.

Ein importierter Checkpoint wird unabhängig geprüft und als Referenz geführt.
Er ist **kein behaupteter nativer RPID-Warmstart**. Die erste Kampagne verwendet
ihn weder als Objective-Cutoff noch als bevorzugte Übergangsfolge.

Z2 muss beliebige gültige historische Reservoirpläne nachspielen. Z3 muss sie
nur nachspielen, wenn sie seine Maskenrestriktion erfüllen. Ein unpassender Plan
bleibt gültige externe Referenz, aber ist `not_representable_in_profile`;
niemals Routen oder positive Ride-Mengen still verändern.

Jede native vollständige Lösung wird durch ihre Labels in einen vollständigen
Zeitgraphen übersetzt, ganzzahlig konkretisiert, in bestehende Trip-/Ride-IDs
exportiert und mit `validate_reservoir_cp_plan` geprüft. Validierte Lösungen
werden atomar fortlaufend gespeichert. Ein ungültiger Kandidat zählt nicht als
Incumbent; er stoppt die Performancefreigabe des Profils.

Historische Referenzen werden nicht mit einer neu optimierten Passagierzuordnung
überschrieben. Eine eventuelle Neubewertung wird separat gekennzeichnet. Die
Timing-/Musterübernahme beim Replay zählt nicht als native Suchverbesserung.

## 9. Pflicht-Zwischentests und Freigabereihenfolge

| Testgruppe | Inhalt | Erwarteter Nachweis |
|---|---|---|
| T1 Zeitkern | kleine zufällige und handprüfbare Integer-STNs; negative Zyklen; >32-Bit; Überlauf | gleiche Machbarkeit/Witness-Zeiten wie unabhängige Prüfung |
| T2 Phasen | STOP/SKIP, Waiting=0/W, Freigabephase einen Tick davor/danach | Gleichheit mit Originalvertrag |
| T3 Ressourcen | zwei Ressourcen mit verschiedenen Ordnungen; echte Überholung; später geplante frühere Nutzung | keine globale FIFO-Annahme; keine Kalenderlücke |
| T4 Grenzen | Eintritt genau H und H+1; Schutz über H; gleichzeitige Zustandsknoten; Rückkehrkollision | exakte Präsenz- und Eindeutigkeitssemantik |
| T5 Passagiere | voll, Aus-/Einstieg im selben Besuch, Release während Waiting, Ziel vor Ziel-Waiting | gleiche ganzzahlige Beförderungen |
| T6 Lebenszyklus | K=0/1/2/Kmax, verschiedene Einsatzlängen, leere Rückkehr, offene Ziele | volle optionale Flotte ohne Wiedereinsatz |
| T7 Kompression | Zielmengen gegen visit-/ride-basierte Zusagen; ungleiche Freigabebuckets | keine zusätzliche Runde/Zuordnung; Freigaben bleiben getrennt |
| T8 Projektion | voller versus kompakter Zeitgraph für alle kleinen Fortsetzungen | gleiche Fortsetzungsmengen, nicht nur gleicher bisheriger Wert |
| T9 Muster | alle Masken, Gruppen 1..K, Whole-Trip gegen Singleton; notwendiger Musterwechsel | korrekte Äquivalenz beziehungsweise dokumentierte Einschränkung |
| T10 End-to-end | vollständige Enumeration winziger Tickdomänen und CP-SAT | Z2 gleiche Optima; Z3 gleiche Optima unter Maskenrestriktion |
| T11 Integrality | vorhandenes Odd-Cycle-Passagierprinzip plus Reservoirgegenbeispiel | kein impliziter LP-Ersatz, ganzzahlige Ride-Mengen |
| T12 Betrieb | Timeout, RSS-Abbruch, ungültiger Import, Profilabweichung, keine native Lösung | keine falsche Unzulässigkeit/Optimalität/Seedverbesserung |

Kleine Enumeration verwendet eigene eindeutig dokumentierte Mini-Geometrien
mit kurzen Integer-Tickbereichen. Sie wird nicht als zeitvergröberte Lösung
der großen Instanz ausgegeben. Zusätzlich Tests auf originaler Geometrie mit
vollen Mikrosekundenbereichen über CP-SAT und historische Replays.

Die Exactness-Dokumentation begründet separat:

1. Für jeden Originalplan existiert eine diskrete Z2-Entscheidungsfolge.
2. Konstruktionsreihenfolge legt keine physische Reihenfolge fest.
3. Bei vollständigen Entscheidungen entspricht das Zeitnetz genau dem Vertrag.
4. Bordkompression und Zeitprojektion erhalten alle relevanten Fortsetzungen.
5. Z3 entspricht exakt seiner ausgewiesenen Whole-Trip-Teilmenge.

**Vor großen Suchläufen:** A–D und T1–T12 bestehen; beide Varianten finden in
mindestens einem kleinen Waiting-Fall ohne Hints einen vollständig gültigen
Plan mit positiver Bedienung. Ein leerer Reservoirplan erfüllt das Gate nicht.
Ein Fehler im gemeinsamen Kern blockiert beide, eine Z3-spezifische Einschränkung
blockiert nicht automatisch Z2.

## 10. Erste Performancekampagne — Vorschlag: maximal 60 Minuten

Dieses Dokument startet keine Läufe. Implementierung und kleine Korrektheitstests
liegen außerhalb des vorgeschlagenen Performancebudgets. Kein automatischer
Langlauf nach einem Timeout.

### 10.1 Eingefrorene Fälle und Referenzen

**R0:** historische Batch-Nachfrage, D=3.074, Max50, Waiting bis 1.200 s.
**R2:** historische B↔D-/C↔E-Nachfrage, D=3.074, Max50, neun Freigabebuckets.
Beide unverändert aus:

    benchmarks/output/reservoir_capacity_campaign_20260911_v1/prepare/R0_ss.json
    benchmarks/output/reservoir_capacity_campaign_20260911_v1/prepare/R2_ss.json

R2 muss bei Referenzreplay S=2.496/U=578 und 38 Einsätze reproduzieren. R0-Wert
wird aus der erneut validierten Datei übernommen, nicht aus alten Chatangaben.
All-Stop-Referenzen aus demselben Prepare-Ordner separat prüfen. Abweichende
Domäne stoppt den betroffenen Vergleich.

**Kleine Skalierung:** Max2 und Max4, jeweils No-Wait und Waiting 2 s,
ursprüngliche Fünf-Stationen-Geometrie, Kapazität 2, Dispatch 0..30 s,
Serviceende 330 s, Rückkehr/Betriebsende 360 s, Waitingfreigabe 0 s.
Nachfrage A→B: 3*Kmax, A→C: 2*Kmax, B→C: 2*Kmax, alle Freigabe null.
Volle Mikrosekundenauflösung; keine festen Startpositionen. Diese Fälle sind
neue Reservoirkontrollen und nicht identisch mit dem alten Fixed-K-DIDP-Piloten.

### 10.2 Faire Konfiguration und Budget

Vergleich: Z2, Z3/Whole-Trip und bestehendes CP-SAT Legacy, jeweils Ziel U.
Alle ohne Fahrplan-Hints oder externe Objective-Cutoffs. Referenzen werden für
alle getrennt gezeigt. CP-SAT-Maskenfixierung nur in Korrektheitstests, nicht in
den freien Hauptvergleichen.

| Abschnitt | Läufe und Limit einschließlich Aufbau/Validierung | Summe |
|---|---|---:|
| Kleine Skalierung | 4 Fälle × 3 Verfahren × 60 s | 12 min |
| R0 und R2 | 2 Fälle × 3 Verfahren × 300 s | 30 min |
| R2-Wiederholung in umgekehrter Reihenfolge | 3 Verfahren × 180 s | 9 min |
| Gemeinsames Einfrieren, Abschluss und Reserve | — | 9 min |
| **Harte Gesamtdauer** | | **60 min** |

Die R2-Wiederholung ist ein 180-s-Reproduzierbarkeitstest. Beide Ergebnisse
werden für Empfehlungen am gemeinsamen 180-s-Zeitpunkt verglichen; kein
unmarkierter Vergleich eines 300-s-Endwerts mit einem 180-s-Endwert.

Kleine Fälle ein Worker, Hauptfälle Workerwunsch zwölf, höchstens 24 GiB
Prozessbaum-RSS. Native parallele RPID-Suche nur nach Gate A. Keine zwölf Kerne
behaupten, wenn die gewählte API sie nicht verwendet. CPU-Zeit, tatsächliche
Auslastung und Threadkonfiguration werden gemessen.

Alle Prozesse sequenziell, keine konkurrierenden Solverjobs. Gemeinsame Deadline
umfasst Suspend, Modellaufbau und Abschluss. Kindprozesse kontrolliert beenden;
fehlende Zertifikatsvalidierung gilt als fehlendes Ergebnis. Frei gewordenes
Budget finanziert keine zusätzlichen Profile oder Langläufe.

### 10.3 Messung der tatsächlichen Suchentwicklung

Pro Lauf speichern:

- Vorbereitung, Aufbau, Suche, Zertifikatsreplay, Validierung und Gesamtzeit;
- RSS, CPU-Zeit, effektive Parallelität und Engine-/Quellnachweise;
- erste native Lösung, erste positive Bedienung, jede tatsächliche Verbesserung;
- S/U, eingesetzte und maximal gleichzeitig aktive Flotte, Muster und Waiting;
- native generierte/expandierte Zustände, erreichte Breiten und Abbruchgrund;
- K-Verteilung generierter/expandierter/vollständiger Zustände, soweit über
  Modellinstrumentierung erreichbar; keine erfundenen internen Cachemetriken;
- Nachfolger und Aufwand für Route, Passagierbündel, Ressourcenordnungen;
- Zahl Zeitvariablen, DBM-Speicher, Projektionsgewinn, Propagationszeit und
  Konfliktabbrüche; keine Gleichsetzung mit CP-SAT-Variablenzahlen;
- letzter Fortschrittszeitpunkt und Qualität bei 30/60/120/180/300 s, soweit
  beobachtet; keine Interpolation als tatsächliches Verbesserungsereignis.

Damit lässt sich unterscheiden: zu wenig K-/Musterexploration, große
Passagierverzweigung, teure Zeitpropagation, Ressourcenreihenfolgeexplosion,
viele unvollständige Pläne oder Qualitätseinbuße durch Whole-Trip-Masken.

Native Bounds werden mit Richtung und Gültigkeitsbereich exportiert. Ein
Maximierungsbound B ergibt `LB(U)=max(0,D-B)` nur bei nachgewiesener Gültigkeit.
Z3-Bounds beziehen sich auf die Musterteilmenge und sind kein globaler
Skip-Stop-Bound. Breitenlimit/Timeout sind keine Beweise. Z2 erhält globale
Beweisaussagen erst nach Gate C und überprüfter nativer Statussemantik; fehlt
dies, bleibt der globale Bound unbekannt beziehungsweise nur extern belegt.

## 11. Entscheidung und bedingte Folgeschritte

Reine kleinere Zustände, übernommene Referenzen oder ein guter abstrakter
Bedienungsauftrag reichen nicht. Primär zählt unabhängig gültige Bedienung.

- **Nützlicher Incumbent-Ansatz:** mindestens zehn zusätzlich bediente Personen
  gegenüber CP-SAT auf R2, in beiden Wiederholungen am gemeinsamen 180-s-Zeitpunkt;
  alternativ gleiche Qualität in höchstens halber Zeit, in beiden Versuchen.
- **Eigener Musterbefund:** Z3 findet schneller gute Pläne, bleibt aber unter Z2:
  gezielt `per_lap` planen. Nicht sofort die gesamte Einschränkung entfernen.
- **Z2 ohne Z3-Vorteil:** gemeinsame Zeitdarstellung weiter bewerten; keinen
  Gruppen-Controller zusätzlich ausbauen.
- **Nur kleine Fälle erfolgreich:** Skalierungsgrenze benennen. Längere Läufe
  erst begründen, wenn native Verbesserung und beherrschbarer Speicher sichtbar
  sind; keine Erwartung, dass Zeit allein das löst.
- **Keine positiven vollständigen Waiting-Pläne oder überwiegend Aufbau/RSS:**
  keine Max50-Kampagne; konkreten Engpassbericht schreiben.

S>2.496 übertrifft den historischen R2-Referenzfahrplan, nicht automatisch jeden
All-Stop-Fahrplan. Für den stärkeren Nachweis gilt bei identischer Domäne:

    U_skip_stop_valid < LB(U_all_stop_optimal).

Die bisher dokumentierte Schwelle U_AS>=125 wird nur nach Prüfung von Quelle,
Boundzertifikat und Domänenidentität verwendet. Ein gültiger Plan mit U<=124
würde diese Schwelle übertreffen. Vollständige Bedienbarkeit einer größeren
Profilnachfrage erfordert weiterhin verschachtelte Nachfragefälle und U=0.

Abschlussartefakte:

- `docs/reference/reservoir_dp.md`: tatsächlich implementierter Vertrag;
- `docs/findings/reservoir_symbolic_and_pattern_dp_YYYYMMDD.md`: Ergebnisse,
  Fortschrittskurven, Gültigkeitsbereich und konkrete Fortsetzungsentscheidung;
- neue unveränderliche Ergebnisordner mit Manifest, Zeit-/Entscheidungsreplays,
  unabhängigen Zertifikaten und getrennten Referenz-/Suchwerten.

## 12. Wissenschaftliche Grundlage und offene Eigenleistung

1. [Dechter, Meiri, Pearl (1991): Temporal Constraint Networks](https://doi.org/10.1016/0004-3702(91)90006-6).
   Grundlage für Differenzbedingungen und Konsistenz einfacher Zeitnetze. Die
   Auswahl disjunktiver Ressourcenreihenfolgen bleibt kombinatorisch.
2. [Kuroiwa, Beck (2025): RPID](https://doi.org/10.4230/LIPIcs.CP.2025.23),
   [Enginequelle](https://github.com/domain-independent-dp/rpid),
   [API](https://docs.rs/rpid).
   Programmierbare DP-Zustände und vorhandene native Suche. Kein belegter
   Geschwindigkeitsfaktor für unsere Seilbahninstanz.
3. [Marijnissen et al. (2026): DIDP with Constraint Propagation](https://arxiv.org/abs/2603.16648).
   Belegt den Forschungsansatz, Constraint-Propagation während DP-Suche zu
   verwenden; kein fertiger Adapter für unseren Reservoirvertrag.
4. [Bergman et al.: Discrete Optimization with Decision Diagrams](https://johnhooker.tepper.cmu.edu/discrete_opt_with_DDs.pdf).
   Einordnung beschränkter und relaxierter Zustandsgraphen. Der Pilot verwendet
   native CABS-Suche und baut keinen eigenen Relaxed-DD-Boundsolver.
5. [Horn et al.: A*-Based Construction of Decision Diagrams for Prize-Collecting Scheduling](https://www.ac.tuwien.ac.at/files/tr/ac-tr-18-011a.pdf).
   Verwandte Kombination aus Auswahl und Ressourcenscheduling. Andere
   Ressourcenannahmen und Aufgabenstruktur; keine Übernahme globaler Reihenfolge.

Seilbahnspezifisch und vor Performance zu beweisen bleiben: vollständige
Phasenübersetzung, Behandlung jeder Präsenz-/Waitingdisjunktion, direkte
Passagierverpflichtungen, sichere Zeitprojektion und zulässige Kabinenumbenennung.
Die Whole-Trip-Gruppierung ist eine explizite Modellapproximation dieses Piloten,
keine durch diese Quellen garantierte optimale Struktur.
