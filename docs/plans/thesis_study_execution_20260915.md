# Ausführbare Fixed-K-Reihen und Ergebnisatlas

Stand: 15.09.2026. Ergänzung zum
[Integrationsplan](thesis_experiment_frontend_integration_20260914.md).
Die Hauptkampagne wird durch diese Umsetzung **nicht gestartet**.

## Implementierter Ablauf

`benchmarks/run_thesis_study.py` verarbeitet ein eingefrorenes Manifest.
Jede Kombination aus Gruppe, Seed, Nachfrage, K und Betriebsmodus besitzt einen
stabilen Schlüssel. Unterbrechungen erzeugen bei Wiederaufnahme einen neuen
Versuchsordner; abgeschlossene Versuche werden eingelesen und nicht neu gerechnet.
Die Regeln werden aus ihren gespeicherten Ergebnissen erneut angewendet.

- Kapazität: pro Seed eine eigene N-/K-Reihe. N wächst nach vollständiger
  Bedienung mit Faktor 1,1 (aufgerundet). Für jedes N werden die festgelegten
  K-Werte nacheinander mit **genau K aktiven Kabinen** geprüft. U=0 beendet
  diesen K-Scan. Nach einem ungeklärten N folgen höchstens drei ganzzahlige
  Zwischenprüfungen zur letzten vollständig bedienten Nachfrage. Ein erfolgloser
  heuristischer Versuch ist keine physikalische Kapazitätsobergrenze.
- Journey: All-Stop und Skip-Stop bei identischem K/N und identischen festen
  Starts. N bleibt je Gruppe konstant. Zwei aufeinanderfolgende K-Punkte ohne
  unabhängig bestätigte vollständige Skip-Stop-Bedienung beenden diese Reihe.
  Es gibt keinen automatischen All-Stop-Startplan für Arc-Flow.
- Musterinformation darf innerhalb derselben evolutionären Seed-Reihe
  weitergereicht werden. Die vollständige Dispatchbelegung wird beim nächsten
  K neu konstruiert. Die zyklisch ergänzte beziehungsweise gekürzte Musterfolge
  ist **Elterninformation, kein übernommener zulässiger Incumbent**. Zwischen
  unabhängigen Seeds oder Gruppen wird nichts weitergereicht.
- Der Prozessbaum-Supervisor begrenzt jede ausdrücklich gestartete Sitzung
  einschließlich Aufbau, Kindprozessen, Abschluss und Suspend. Höchstens
  zwölf Worker und 32 GiB Prozessbaum-RSS; kritischer Speicherdruck wird nach
  30 Sekunden beendet. Eine Wiederaufnahme erhält ein neues explizites Budget,
  eigene Quellcodekopie und getrennte Sitzungszeit. Frühere Zeiten bleiben erhalten.

Die zunächst erzeugten Rezepte enthalten K=10/15/23 für Journey und
K_AS/K_AS+1/ceil(1,1 K_AS) für Kapazität, höchstens fünf geometrische N-Stufen
plus drei Zwischenprüfungen. 300 Sekunden je Stufe sind ein **vorläufiges
Startbudget**, keine Behauptung, dass alle großen Punkte darin optimal lösbar
sind. Die Summe sämtlicher theoretisch möglicher Stufen kann etwa 50 Stunden
betragen. Das ist ein rechnerischer Deckel des vollen Rezepts, **kein gestarteter
oder pauschal freigegebener Langlauf**. `--group` ermöglicht getrennte Blöcke.
Jeder tatsächliche Start verlangt zusätzlich `--wall-time-limit`.

## Freigabe und Referenzbegriff

`benchmarks/summarize_thesis_resolution.py` vergleicht passende 15-/5-s-Fälle
mit nativen LB und unabhängig validierter UB. Beim Kapazitätsintervall werden
nur bewiesene nicht bedienbare Nachfragepunkte als obere Grenzen verwendet.
Ohne ausreichende Grenzen bleibt die Auflösungsentscheidung offen.
Ein 15/5-s-Test bei K10 ist eine Kalibrierung dieses Lastpunkts und keine
allgemeine Fehlerschranke für alle K und Nachfrageprofile.

`benchmarks/freeze_thesis_study.py` erzeugt zwölf Rezepte oder eine explizit
gewählte Teilmenge. Standard `--reference-mode exact` verlangt die vollständige
All-Stop-Referenz und einen validierten Optimierungspiloten sowie das bestandene
Auflösungsgate. Fehlt ein Nachweis, listet die Gruppe ihre Blocker und der
Reihenrunner startet sie nicht.

Der im ursprünglichen Plan zugelassene Modus `--reference-mode witness` darf
statt des exakten κ einen unabhängig bestätigten unteren Referenzwert benutzen.
Das Manifest kennzeichnet dann `demandBasis=validated_reference_lower_bound`.
Er erlaubt explorative Lastvergleiche, **keine Aussage über einen prozentualen
Zuwachs gegenüber unbekannter maximaler All-Stop-Kapazität**. Er umgeht weder
fehlende gültige Fahrpläne noch das Auflösungsgate.

## Kommandos

Alle Aufrufe aus dem Repository, mit der Projektumgebung:

```sh
.venv/bin/python benchmarks/summarize_thesis_resolution.py \
  --results-root results/thesis_g500_calibration_20260914_v2 \
  --results-root results/thesis_g500_preflight_20260915 \
  --results-root results/thesis_g500_review_20260915 \
  --results-root results/thesis_g500_completion_20260915 \
  --results-root results/thesis_g500_corrective_checks_20260915 \
  --results-root results/thesis_g500_final_gates_20260915 \
  --output results/thesis_g500_completion_20260915/resolution_evidence.json

.venv/bin/python benchmarks/freeze_thesis_study.py \
  --results-root results/thesis_g500_calibration_20260914_v2 \
  --results-root results/thesis_g500_preflight_20260915 \
  --results-root results/thesis_g500_review_20260915 \
  --results-root results/thesis_g500_completion_20260915 \
  --results-root results/thesis_g500_corrective_checks_20260915 \
  --results-root results/thesis_g500_final_gates_20260915 \
  --resolution-evidence results/thesis_g500_completion_20260915/resolution_evidence.json \
  --output results/thesis_g500_completion_20260915/study_manifest.json

.venv/bin/python benchmarks/run_thesis_study.py \
  --manifest results/thesis_g500_completion_20260915/study_manifest.json \
  --output-dir results/thesis_main_example \
  --wall-time-limit 3600 --build-only
```

`--build-only` prüft auch gesperrte Rezepte und startet keinen Solver. Erst ein
bewusster Aufruf ohne dieses Flag startet eine freigegebene Auswahl. Eine
Wiederaufnahme verwendet dasselbe Manifest und Ausgabeziel mit `--resume`;
geänderte Manifestidentität wird abgewiesen. Vor dem Start werden auch die
Hashes der eingefrorenen Referenz- und Auflösungsevidenz geprüft. Geänderter Quellcode wird als neue
Sitzungsquelle archiviert; Laufzeiten verschiedener Quellstände sind getrennt
zu beurteilen.

## Lesendes Frontend und portables Paket

```sh
.venv/bin/python benchmarks/export_thesis_frontend.py \
  --results-root results/thesis_g500_calibration_20260914_v2 \
  --results-root results/thesis_g500_preflight_20260915 \
  --results-root results/thesis_g500_corrective_checks_20260915 \
  --results-root results/thesis_g500_final_gates_20260915 \
  --watch-seconds 3600
npm --prefix frontend run build
npm --prefix frontend run preview
```

Der Exporter liest nur Dateien. Unveränderte große Ergebnis-/Verlaufsdateien
werden gecacht; die Startseite lädt lediglich den kleinen Index. Details und
Replays werden erst bei Auswahl geladen. Für ein abgeschlossenes Paket den
Watcher weglassen. `frontend/dist` enthält danach das lokale, statisch
betrachtbare Paket ohne Pythonprozess oder Solverlizenz. Vorhandene historische
Archivseiten bleiben erreichbar, soweit deren Daten ebenfalls mitgeliefert werden.

- Filter nach Topologie, Ziel, K, N und Freigabeauflösung; kein gemeinsames
  Best-Ranking über verschiedene N oder Auflösungen.
- Native Incumbents, unabhängig validierte Ergebnisse und gültige globale
  Grenzen werden getrennt gezeichnet. Evolution erhält keinen globalen Gap.
- Evolution speichert und exportiert jedes neue Verbesserungszertifikat.
  Arc-Flow speichert seinen nativen Verlauf und das unabhängig geprüfte
  Endzertifikat. Ungeprüfte Zwischenincumbents sind nicht als Replay auswählbar.
- Der integrierte Replay ist eine zeitsynchronisierte Besuchs-/Belegungstafel,
  keine neue räumliche Videoanimation. Die vorhandene Szenarioansicht bleibt
  separat erreichbar. Historische Arc-Flow-Ergebnisse ohne gespeicherte
  Passagierzuordnung zeigen Belegung ausdrücklich als nicht verfügbar.
- Referenzsuchen zeigen Nachfrageproben und Intervalle; ihr Suchmaximum wird
  nicht als tatsächlich gelöste Nachfrage angezeigt.
- CSV, SVG, Drucken/PDF sowie Fall-, Ergebnis-, Quellen- und Zertifikats-JSON
  sind aus dem Laufdetail erreichbar. `package_manifest.json` enthält Größen
  und SHA-256 der exportierten Dateien. Private lokale Pfade werden entfernt;
  Prozesslogs und Lizenzdateien werden nicht übernommen.

## Noch wissenschaftlich zu entscheiden

Ein technisch ausführbarer Versuch und eine exakt bewiesene Referenz sind
verschiedene Ergebnisse. Die abschließende Freigabematrix im Befund benennt
für jede Gruppe, ob Auflösung, Referenz und Optimierungspilot bereits tragen.
Offene Referenzen werden nicht durch Zeitlimits oder vorhandene UI-Felder
zu angeblich fertigen Kapazitätsnachweisen.

## Aktualisierung: Journey-Laufbudget (15.09.2026)

Für neu eingefrorene Journey-Läufe gelten maximal 1.800 Sekunden Wandzeit
einschließlich Aufbau und Abschluss sowie ein relatives Gurobi-MIPGap von 0,01.
Die unabhängige Validierung bleibt erforderlich; ein Erreichen der Gap-Toleranz
ist kein Beweis eines mathematisch exakten Optimums. Historische Manifeste und
Ergebnisse bleiben unverändert. Der Reihenrunner reicht das manifestierte
`mip_gap` an `run_thesis_experiment.py --mip-gap` weiter.

Die Nachfrage bleibt pro Profil und über alle K fest bei floor(0,5 κ_AS(K_ref)),
mit K_ref=10: F0=510, F2=151, F3=360, F4=772 Personen.
Eine äquidistante Erweiterung K=10,15,20,…,60,62 wird vorgeschlagen, ist noch
nicht eingefroren. Bestehende K23-Messungen bleiben zusätzliche Messpunkte.
Auflösungs-Kalibrierungen benötigen weiterhin ausreichend enge gemeinsame
UB/LB-Intervalle; 1 % Suchgap garantiert nicht automatisch deren 1-%-Kriterium.

## Verbindliche neue Journey-Reihen (15.09.2026)

Diese Entscheidung ersetzt die oben vorgeschlagene K10-Nachfragebasis für die
Hauptreihe. Bereits eingefrorene Ergebnisse bleiben historische Niedriglastversuche.

1. **Vergleich bei gleicher relativer Last:** Für jedes getestete K und jedes
   F0/F2/F3/F4 wird κ_AS(K) bei den gemeinsamen festen Balanced-Starts bestimmt.
   Beide Methoden erhalten dieselbe verschachtelte Nachfrage mit
   floor(0,25 κ_AS(K)) beziehungsweise floor(0,75 κ_AS(K)). Keine weitere Halbierung.
2. **Konstante Nachfrage:** K_ref=floor(K_AS/2)=31 für T5R/G500 mit K_AS=62.
   N=κ_AS(31), vollständig übernommen und für sämtliche K unverändert.
   Dies ist nicht 50 % von κ_AS(62) und nicht 50 % von κ_AS(31).
   Unterhalb voller Bedienung keine Journey-Vergleiche auf unterschiedlichen
   bedienten Teilmengen. Ungeklärte Lösbarkeit ist kein Unzulässigkeitsnachweis.

No-Wait, gemeinsame Startpositionen pro K, P0, 15-s-Nachfragefreigaben und die
G500-Physik bleiben bestehen. Zunächst sind K10/20/30 als Screening vorgesehen;
5er-Zwischenpunkte und weitere Stufen werden anschließend eingefroren. Für
Reihe 2 ist K31 zusätzlich die direkte Referenzkontrolle. Die Stopregel mit zwei
ungelösten kleinen K darf diese Reihe nicht vor Erreichen K_ref beenden.

Journey-Optimierung: maximal 30 Minuten pro Lauf, natives relatives Gap 1 %,
unabhängige Validierung. Referenzkapazität: exakte Ganzzahligkeit und Nachweis
N/N+1; offene Intervalle werden nicht automatisch als exakte Lastbasis benutzt.

Vorbereitung beginnt mit vier sequenziellen K31-Referenzen, maximal 30 Minuten
je Profil plus zwei Minuten Gesamtreserve, 12 Worker und 32 GiB Prozessbaum-RSS.
Der technische Suchdeckel 20.000 Personen ist kein Kapazitätsnachweis; bei
Erreichen bleibt eine Fortsetzung offen. Danach fehlen für Reihe 1 die
Referenzen K20/K30; vorhandene K10-Nachweise dürfen nach Identitätsprüfung
wiederverwendet werden. Der alte Freezer erzeugt weiterhin das historische
K10-Rezept und darf nicht als Manifest dieser beiden neuen Reihen verwendet
werden. Neue Hauptmanifeste werden erst mit den neuen Referenzen erzeugt.

### Freigegebener vollständiger Screening-Block

Auf Nutzeranweisung „starte alles bis alles fertig ist“ werden beide obigen
Journey-Screenings vollständig sequenziell ausgeführt: vier Profile, K10/20/30,
zwei relative Lasten und zwei Bewegungsmodi (48 Versuche), anschließend konstante
Nachfrage bei K10/20/30/31 mit zwei Bewegungsmodi (32 Versuche). Die vier vorhandenen
K31-Referenzen werden mit Quellpfad/Hash und Vertragsprüfung übernommen. Zwölf
Referenzsuchen bei K10/20/30 gehen voraus. Insgesamt maximal 46 Stunden nominelle
Laufbudgets plus 30 Minuten Kampagnenreserve. Die reale Deadline gilt auch nach
Suspend und Wiederaufnahme. Kein weiterer Solverjob läuft parallel.

`benchmarks/run_thesis_revised_journey_campaign.py` führt diesen Block aus.
Fehlgeschlagene Einzeljobs werden protokolliert; übrige unabhängige Versuche
laufen weiter. Fehlende exakte Referenzen blockieren nur die davon abhängigen
relativen Lastpunkte. Eine Wiederaufnahme mit `--resume` nutzt die ursprüngliche
Gesamtdeadline und neue Versuchspfade für fehlgeschlagene Einzeljobs.

Die 15-s-Auflösung bleibt fest. Die bisherige Sensitivitätskalibrierung wird nicht
als Nachweis für die neuen, höheren Lasten ausgegeben. Neue Ergebnisse tragen
diese Einschränkung. Ebenso bedeutet „complete“ nur abgeschlossen: Optimalität,
1-%-Gap, volle Bedienung und Unzulässigkeit sind anhand der nativen und geprüften
Ergebnisfelder getrennt auszuwerten. Evolutionäre Kapazitätskampagnen sowie eine
Erweiterung bis K62 gehören nicht zu diesem Journey-Screening-Block.

### Reihenfolge auf Nutzerwunsch geändert

Die noch offenen Journey-Vergleiche laufen nun nach voraussichtlicher Schwierigkeit:
relative Last vor konstanter hoher Nachfrage, K aufsteigend, 25 % vor 75 %, dann
Profilreihenfolge F2/F4/F3/F0. All-Stop und Skip-Stop bleiben paarweise zusammen.
Die 80 Aufgaben, Nachfragewerte und ursprüngliche Gesamtdeadline bleiben erhalten.
Der bereits laufende F0/K20-Solver wurde nicht beendet; ein protokollierter
Controller-Handoff wartet dessen Abschluss ab und übernimmt anschließend die
neue Reihenfolge. Dies ist eine Priorisierung anhand bisheriger Ergebnisse,
keine Garantie der tatsächlichen Laufzeit jedes Falls.

### Fortsetzung unabhängig von Codex

Die nach Reihe 1 pausierte Kampagne wird über den macOS-LaunchAgent
`local.ropeway.journey-campaign` mit `--resume` fortgesetzt. Der lesende
Frontendexport läuft separat als `local.ropeway.journey-export`. Beide Prozesse
werden von launchd gestartet (Elternprozess PID 1), ohne Codex-Prozess als
Vorfahren. Die ursprüngliche Kampagnen-Deadline bleibt bestehen. Die Agenten
haben weder KeepAlive noch automatischen Loginstart; keine Endlosschleife nach
Kampagnenende. Definitionen: `~/Library/LaunchAgents/local.ropeway.journey-*.plist`.
Status und Logs liegen im Ergebnisordner unter `launchd/` und
`launchd_services.json`. App-Neustart ist damit vom Solverlauf unabhängig;
Mac-Neustart, Abmelden und Ruhezustand sind davon getrennt (Supervisor behandelt
Suspend weiterhin als Abbruchgrund). Der Vite-Webserver wird dadurch nicht
zum LaunchAgent; die Ergebnisdateien werden unabhängig weiter exportiert.

### Korrektur auf Nutzeranweisung: konstante halbe K31-Nachfrage

Die volle K31-Kapazität als konstante Nachfrage ist verworfen. Reihe 2 verwendet
nun floor(κ_AS(31)/2): F0=1553, F2=469, F3=1105, F4=2327. Wie Reihe 1 werden
K10/20/30 getestet, einschließlich eventuell nicht vollständig bedienbarer kleiner
K. Keine automatische Auslassung von K10. Je K dieselben Startpositionen und
Nachfragen für All-Stop und Skip-Stop. Weiterhin 30 Minuten, Gapziel 1 %, 15-s-
Freigaben und No-Wait. Gültige Referenzen sowie Reihe 1 bleiben erhalten.
Die acht bereits gestarteten falschen Vollnachfrage-Läufe wurden einschließlich
exportierter Kopien auf ausdrücklichen Wunsch gelöscht. Neue IDs heißen
`constant_half_*`, somit keine Vermischung. Der Block umfasst jetzt 48 bestehende
und 24 neue Vergleiche. Fortsetzung wieder über launchd, unabhängig von Codex.

### Finale Festlegung Reihe 2: Journey Time ab K20

Auf ausdrücklichen Nutzerwunsch bleiben vollständige Bedienung und Minimierung
der Journey Time das Ziel. Keine zusätzliche Bedienungsoptimierungsphase.
Konstante Nachfrage weiterhin F0=1553, F2=469, F3=1105, F4=2327. Die bisherigen
Reihe-2-Läufe einschließlich exportierter Kopien wurden gelöscht. Neustart bei
K20, anschließend K30; K10 entfällt. Dies ergibt 16 neue Vergleiche, neben den
48 abgeschlossenen Vergleichen von Reihe 1. 30 Minuten und 1 % Gap pro Lauf,
No-Wait, feste Balanced-Starts, 15-s-Freigaben, zwölf Threads und 32 GiB bleiben.
Fortsetzung erfolgt unabhängig von Codex über die vorhandenen LaunchAgents.

## Evo-Kapazität und anschließender Greedy-Vergleich (16.09.2026)

Bestätigte Konfiguration: T5R/T6R, G500/P0, F2/F4/F3/F0 in dieser
Prioritätsreihenfolge; feste K, No-Wait, lexikografisch zuerst `unserved` und
bei gleicher Bedienung `journey_time`, bestehende pymoo-GA,
Population 32, acht Nachkommen, `mixed_global`, Intervall-Decoder und
`od_endpoints_v1`. Keine bekannte gute All-Stop-Initialisierung. Seeds 0/1/2,
30 Minuten pro Versuch ohne globales Evo-Gap-Abbruchkriterium. Je Gruppe
K_AS/K_AS+1/ceil(1,1 K_AS), also T5: 62/63/69, T6: 75/76/83. Nachfrage ab
exakter All-Stop-Referenzkapazität, danach Faktor 1,1 und bisherige Stopregeln.
Die vorgeschlagene K-Leiter ist ein erster Block, keine optimale Flottengrenze.

Greedy anschließend **mit und ohne Waiting** auf denselben G500-Instanzen,
Nachfragen und Port-/Lebenszyklusverträgen. Erster Waiting-Vergleich 120 Sekunden
je legalem STOP, wie im jüngsten historischen Test; dies ist eine zusätzliche
Bewegungsfreiheit gegenüber No-Wait. Kein Vergleich historischer R2/Q8-Zahlen
mit G500/Q10 als identische Instanz. Die historische Greedy-Journey-Strafkosten-
Zielfunktion ist nicht identisch zu maximaler Bedienung; das Ziel ist vor dem
Kapazitätsvergleich explizit anzugleichen. 30 s Einfügung und 120 s Retry sind
der vorhandene historische Startwert, nicht automatisch dasselbe Gesamtbudget
wie ein 30-minütiger Evo-Lauf. Gesamtzeit und Bedienung-über-Zeit sind gemeinsam
zu berichten; finale Fairnessbudgets werden beim Greedy-Adapter festgehalten.

Inventarabgleich `results/thesis_capacity_reference_inventory_20260916.json`:
keine der acht r15-Vollflottenreferenzen exakt. F2 T5 [2912,2925), T6
[2937,2950); andere Profile bisher nur bestätigte untere Werte. Daher starten
acht sequenzielle Referenzfortsetzungen mit bis zu 30 Minuten einschließlich
Aufbau/Validierung, zwölf Workern, 32 GiB und maximal 4 h 5 min Gesamtzeit.
Vorhandene geprüfte Nachweise werden wiederverwendet. Suchdeckel 100000 ist kein
Kapazitätsnachweis. Das anschließend erzeugte Evo-Manifest bleibt bis zur
Prüfung exakter Referenzen und Auflösungsfreigaben als `gated` gekennzeichnet;
keine stillschweigende Freigabe durch Ablauf des Vorbereitungsbudgets.


## Amendment 2026-09-16: exclude F4 from remaining campaigns

At the user’s request, F4 is excluded from all remaining reference preparation, Evo and Greedy runs (with and without Waiting), and future optimisation queues. Active T6R/F4 preparation was stopped. Completed F4 results remain archived as local-demand controls. Active families are F0, F2 and F3. Completed non-F4 references are reused; no saved run is repeated and no excluded budget is reassigned. This experiment-scope decision does not establish global All-Stop optimality for F4.

## Final capacity stages: demand families F0--F3

The remaining capacity study uses F0 (diffuse), F1 (common destination hub),
F2 (complementary markets), and F3 (long trips). F4 remains an archived local
negative control and receives no new capacity runs. F1 must be added to the
frozen case generator before its reference or optimisation runs begin.

### Stage 1 -- exact regular All-Stop references

For every admitted topology/family pair, determine the adjacent full-service
threshold for the saturated, regular, common-phase, No-Wait All-Stop timetable.
The specialised reference path separates the single common phase from integer
passenger assignment:

1. Build the deterministic regular All-Stop trajectories and their safe phase
   interval.
2. Derive exact integer phase cells. Cell boundaries are release/departure,
   horizon/arrival, and early-return thresholds. No microsecond grid is
   enumerated, and every original phase tick belongs to exactly one cell.
3. For one representative tick per cell, solve only the fixed-timetable integer
   passenger assignment. A full-service witness at any cell proves feasibility.
   Infeasibility is exported only when every cell is solved to a valid
   infeasibility/optimal-capacity certificate.
4. Reuse phase preparation and passenger structure during monotone bracketing
   and bisection of the nested demand prefix. Unknown cells or deadlines leave
   the reference interval open.
5. Reproduce the established T5R/F2 value 2,918 and T6R/F2 value 2,942 before
   using the path for F0, F1, or F3.

The historical integrated CP-SAT common-phase model remains a regression and
fallback. It is not the preferred large-profile reference formulation because
it couples one phase variable to hundreds of thousands of symmetric ride and
activation variables.

### Stage 2 -- common-fleet evolutionary screening

For T5R and T6R, and for each of F0--F3 with an exact Stage-1 reference, run
the No-Wait evolutionary line planner at exactly K_AS. Screen N=kappa_AS and
N=ceil(1.1 kappa_AS) with seed 0. Stop a run immediately after an independently
validated U=0 incumbent, because zero unserved is globally minimal for that
fixed demand. Journey time breaks ties between candidates with the same
validated unserved count and may never trade away a served passenger. The
fixed-timetable passenger IP uses the same hierarchical objective. The
catalogue is generated before results from the demand
support: All-Stop plus unique minimal OD-endpoint masks.

### Stage 3 -- confirmation and capacity extension

If 1.1 kappa_AS is fully served, confirm that point with seeds 1 and 2 and
screen ceil(1.21 kappa_AS) with seed 0. If a point is unresolved or only partly
served, report its incumbent trajectory and do not treat it as a capacity upper
bound. Additional K=ceil(1.1 K_AS) runs are a separate fleet-saturation
sensitivity and are started only for selected Stage-2 cases; K_AS+1 is not a
mandatory main point.

The main capacity statistic is the largest independently validated fully served
demand divided by the exact regular All-Stop reference capacity. Evolution has
no global Skip-Stop gap. Results therefore distinguish valid lower capacity
witnesses, unresolved searches, and exact regular All-Stop thresholds.
