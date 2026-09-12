# DIDP-Pilot: Fixed-K, Exit-Waiting und ganzzahlige Passagiere

Implementierung vom 10.09.2026. Experimenteller, separater Solverpfad; bestehende Standards bleiben unverändert. Ziel ist `unserved`. Reservoir, variable Flotte, Platzierungsoptimierung und Reisezeitoptimierung gehören nicht zu diesem Piloten.

## Einstieg und Dateien

Installation: `uv sync --extra didp` (DIDPPy exakt 0.10.1). Der normale Paketimport benötigt DIDPPy nicht.

```sh
.venv/bin/python benchmarks/run_ddd_fixed_k_didp.py \
  --cabins 39 --demand 3074 --maximum-wait-seconds 1200 \
  --time-limit 180 --threads 12 \
  --output-dir benchmarks/output/mein_neuer_didp_run
```

Mit `--small-case` gelten die im Pilotplan festgelegten Starts und Nachfragegruppen; beispielsweise `--cabins 2 --maximum-wait-seconds 2`. `--waiting-step-seconds` ist standardmäßig 0.000001. `--reference-checkpoint` importiert einen historischen Plan ausschließlich als geprüfte Referenz/Rückfalllösung. `--build-only` baut das native Modell und spielt eine angegebene Referenz nach, startet aber keine Optimierung. Jeder CLI-Aufruf verlangt einen neuen Ausgabeordner.

| Datei unter dem Projektverzeichnis | Aufgabe |
|---|---|
| `src/ropeway_skip_stop_optimization/optimization/ddd/didp/structure.py` | Unveränderliche Vorbereitung ohne Solverobjekte, kanonische Indizes, Grenzen, Ressourcen-Speicherbedarf |
| `.../didp/model.py` | Native DyPDL-Zustandsvariablen, Übergänge, Basiszustände und Restschranke |
| `.../didp/certificate.py` | Übergangsreplay, Tickprüfung, Export in vorhandenes Zertifikat, unabhängige Validierung |
| `.../didp/optimizer.py` | CABS, Ergebnisabgrenzung, Prozessaufsicht für Laufzeit/RSS |
| `src/ropeway_skip_stop_optimization/benchmarking/ddd_fixed_k_didp.py` | Große historische und kleine festgelegte Vergleichsinstanzen |
| `benchmarks/run_ddd_fixed_k_didp.py` | Separater CLI-Runner |
| `benchmarks/run_didp_pilot_campaign.py` | Korrektheitsgate, Quellen-/Instanzsnapshot, sequenzielle Vergleichskampagne |
| `tests/test_ddd_didp.py` | Enumeration, Replays, Grenzfälle, Schranken und Abbruchverhalten |

API: `DddDidpOptimizer(DddDidpConfig(...)).solve(fixed_k_problem)`. Der vorhandene Domänen-/Zertifikatsvertrag führt weiterhin Journey Time zur Validierung mit; die tatsächliche DIDP-Zielfunktion ist ausschließlich die Zahl rechtzeitiger Aussteiger. Ergebnisse nennen `objective=unserved` und `bound_units=persons` ausdrücklich.

## Zustand und native Übergänge

Pro Kabine werden nächster Besuch und nächste Beginnzeit gespeichert. Pro Nachfragegruppe verbleibt die noch unzugeordnete Menge. Pro Kabine und Zielbesuch wird eine ganzzahlige Ausstiegsverpflichtung gespeichert. Die Belegung nach dem aktuellen Ausstieg ist die Summe aller späteren Verpflichtungen dieser Kabine. Arbeitsvariablen speichern Route, Kandidaten-/Ressourcencursor, Waiting-Intervall und sichere späteste Zeitgrenzen.

1. Abgelaufene Reservierungen werden deterministisch entfernt.
2. Die Kabine mit dem kleinsten nächsten Besuchsbeginn wird bearbeitet; ID löst Gleichstände.
3. STOP/SKIP wird gewählt. Bestehende Ausstiegsverpflichtungen erzwingen einen rechtzeitigen STOP. Die rechtzeitig ausgestiegene Menge erhöht den Maximierungswert.
4. Die kanonischen Kandidaten dieses Einstiegs werden einzeln behandelt. Jede ganzzahlige Menge von 0 bis `min(Q, Gruppengröße)` erhält einen Übergang, eingeschränkt durch aktuelle Restnachfrage und Belegung. Positive Mengen erzeugen verbindliche spätere Ausstiege.
5. Waiting wird durch binäre Teilung des vollständigen ganzzahligen Schrittintervalls bestimmt. Mindestfreigabe, Bedienungshorizont und sichere Restfahrzeiten prüfen ganze Teilintervalle. Es gibt keine vorberechnete Mikrosekundenliste.
6. Jede Ressourcennutzung berechnet ihr exaktes geschütztes Intervall. Eine gemeinsame native Einfügeoperation je Ressource prüft sämtliche bestehenden und festen Randintervalle und fügt die Nutzung sortiert ein.
7. Der Besuch wird abgeschlossen. Die neue Beginnzeit ist exakt die alte Zeit plus Routendauer plus Waiting. Temporäre Variablen werden zurückgesetzt.

Die gemeinsame Einfügeoperation ist eine interne zusätzliche Phase. Dadurch wird dieselbe Kalenderlogik nicht für jeden Besuch erneut aufgebaut. Sie verändert keine Entscheidung und keine zulässige Bewegung.

## Warum dies keine physische Kabinenreihenfolge festschreibt

Für einen zulässigen vollständigen Fahrplan können alle Besuchsbeginne nach `(Zeit, Kabinen-ID)` sortiert werden. Diese Reihenfolge ist eine topologische Bearbeitungsfolge, da eine Bewegung positive Dauer hat. Eine zuerst bearbeitete Bewegung kann eine Ressource später betreten als eine danach bearbeitete Bewegung. Deshalb bleibt ihr vollständiges Intervall gespeichert und die spätere Entscheidung darf davor eingefügt werden. Nur tatsächliche Überlappungen geschützter Intervalle werden ausgeschlossen. Der Test mit echter Bypass-Überholung prüft diese Eigenschaft an der vorhandenen Geometrie.

Jede gültige ganzzahlige Zuordnung kann beim zugehörigen Einstiegsbesuch festgelegt werden. Sie reduziert die globale Restnachfrage genau einmal und erzeugt einen späteren verpflichtenden Ausstieg. Ein- und Ausstieg beim selben Besuch sind zulässig, weil zuerst die bereits zugesagten Aussteiger die Kabine verlassen. Ungeplante Umstiege entstehen nicht: Verwendet werden ausschließlich die ursprünglichen Beförderungskandidaten.

Jeder erlaubte Waiting-Wert bleibt über einen eindeutigen Pfad binärer Teilintervalle erreichbar. Die Wartezeitverlängerung wirkt entsprechend den ursprünglichen 0/1-Koeffizienten auf die Ressourcengeometrie. Bedingte späteste Zeiten verwenden minimale weitere Routendauern und verpflichtenden Ziel-STOP; eine Verletzung kann daher keinen gültigen Plan ausschließen.

## Kalendergrenze und Horizont

Pro Ressource wird ein konservativer Speicherbedarf verwendet:

`min(alle möglichen Nutzungen, K × maximale Nutzungen pro Route × (2 + ceil(maximale Schutzzeit / minimale Routendauer)))`.

Begründung: Pro Kabine kann im Zeitpunkt der Bearbeitung höchstens eine bereits geplante Bewegung noch laufen. Für frühere abgeschlossene Bewegungen kann Schutz höchstens bis Bewegungsende plus maximale Schutzzeit relevant bleiben. Wegen positiver Mindestdauer passen nur beschränkt viele solche Bewegungen in dieses Rückblickfenster. Der zusätzliche Slot deckt Rand-/Gleichheitsfälle ab. Die Geometriedomäne garantiert, dass Ressourcenoffsets innerhalb der Bewegung und Schutzzeiten innerhalb der Ressourcengrenzen liegen. Wartedauern sind nicht negativ und können diese Anzahl nicht vergrößern. Mehrfachnutzungen derselben Ressource werden mitgezählt.

Feste Anfangsreservierungen werden separat geprüft. Intervalle werden nur entfernt, wenn ihr geschütztes Ende höchstens dem aktuellen kleinsten Besuchsbeginn entspricht. Padding und Listenpositionen sind kanonisch. Es gibt kein Abschneiden belegter Einträge; ein beim Replay verletzter Speicherbeweis löst einen Fehler aus.

Ressourceneintritt genau am Betriebshorizont ist aktiv. Das geschützte Ende wird nicht abgeschnitten. Jeder Fixed-K-Besuch mit Beginn höchstens dem Betriebshorizont muss vollständig entschieden werden; seine letzte Bewegung darf dahinter enden. Terminal ist nur ein Zustand ohne offene Beförderungsverpflichtung, in dem alle nächsten Besuchsbeginne hinter dem Betriebshorizont liegen.

## Numerik und Schranken

DIDPPy 0.10.1 verwendet `i32` für ganzzahlige und `f64` für kontinuierliche Variablen. Deshalb werden Zeiten als exakt ganzzahlige Tickwerte in Float64 gespeichert. Vergleiche verwenden keine Toleranz. Es gibt keine Float-zu-Integer-Rundung im Suchmodell; Waiting wird als geprüfter Integer-Schrittzähler geführt und vor Zeitrechnung exakt konvertiert. Die Vorbereitung prüft einen konservativen Zwischenwertbereich unterhalb 2^53 sowie Integer-Zähler inklusive Kapazitäts-Zwischensummen. Der Export lehnt nichtganzzahlige Werte ab.

Die Restschranke zählt offene Ausstiegsverpflichtungen plus unzugeordnete Nachfrage, sofern Freigabe und frühestmöglicher nächster Besuchsbeginn eine Bedienung noch nicht ausschließen. Ressourcen-/Kapazitätskonkurrenz wird ignoriert. Jeder verbleibende Mensch kann höchstens einmal zum künftigen Wert beitragen. Die Schranke ist daher optimistisch, aber bei großen Fällen voraussichtlich schwach. Auf kleinen erreichbaren Zuständen wird sie gegen deren vollständig enumerierte optimale Fortsetzung geprüft.

Bei `D` Personen gilt: native Maximierungs-UB für weitere/gesamte Bedienung → `max(0, D - native_best_bound)` als Untergrenze für unbediente Personen. Eine geprüfte native Lösung liefert `D - native_cost` als obere Schranke. Historische Referenzen werden separat ausgewiesen. Weder ihre Übernahme noch ihr Replay wird als native Verbesserung gezählt.

## Solver und Begrenzung

CABS: `initial_beam_size=1`, `max_beam_size=None`, `keep_all_layers=True`. Keine Zeitdominanz, kein Austausch von Kabinen, kein Primal-Bound-Cutoff und kein Startplan im nativen Solver. Threads werden direkt an CABS übergeben; Wiederholungen sind keine DIDP-Seeds.

Ein eigener Prozess erlaubt Abbruch auch während Modellbau und nativer Suche. Der Elternprozess prüft RSS und Wandzeit etwa alle 0,1 Sekunden, beendet den Kindprozess bei Überschreitung und erhält bereits unabhängig geprüfte, gestreamte Lösungen. RSS ist ein gemessener Prozessgrenzwert, kein vorreserviertes Speichersegment; ein einzelner sehr schneller Allokationssprung kann zwischen zwei Messungen die Grenze kurz überschreiten. Timeout, Speicherabbruch und Prozessfehler heißen ausdrücklich nicht INFEASIBLE oder OPTIMAL.

Modellidentität enthält Domäne, Encoding, DIDPPy-Version, Kalendergrößen und Quellcode-Hashes. Domänen-Fingerprints und Kandidaten-IDs bleiben unverändert. `events.jsonl`, `incumbent.json` und `result.json` unterscheiden native Erstlösung, Verbesserung, Schranken und externe Referenz. Exakte Duplikatraten sind nicht öffentlich verfügbar und bleiben `null`.

## Korrektheitsgate und erste Kampagne

Der Kampagnenrunner führt zuerst die DIDP-Tests und bestehenden CP-Passagierregressionen einschließlich Odd-Cycle-Ganzzahligkeitsfall aus. Beide historischen Dateien müssen vorhanden sein; Replays bestätigen K38 U=315 und K39 U=1402. Die historische Odd-Cycle-Geometrie besitzt nicht die für den integrierten Adapter benötigte Netzprovenienz; ihr bestehender Test bleibt erhalten. DIDP-Ganzzahligkeit wird zusätzlich durch vollständige Mengenaufzählung auf unterstützten integrierten Instanzen geprüft.

Die Kampagnenzeit startet erst nach dem Korrektheitsgate. Quellen, Versionen, Instanzen und externe Referenzen werden eingefroren. Instanzen werden nicht für einen Solver verändert. Vier kleine Instanzen × zwei Solver erhalten je höchstens 60 Sekunden. K38/K39 × zwei Solver und die K39-Wiederholung erhalten je höchstens 180 Sekunden. Kleine Läufe verwenden einen Thread, große zwölf. Keine konkurrierenden Solverjobs. Die Gesamtdauer ist auf 30 Minuten begrenzt; ein weiterer Versuch startet nur, wenn sein Budget samt Abschlussreserve noch hineinpasst.

Große Suchläufe werden ausgelassen, wenn CABS in keinem kleinen Waiting-Versuch einen eigenen gültigen Gesamtplan gefunden hat. Beide Solver arbeiten ohne Hints und ohne externen Objective-Cutoff. Ein mindestens zehn Personen besseres großes Ergebnis muss in der K39-Wiederholung bestätigt werden. Reine Referenzwerte reichen dafür nicht.

## Erkannter bestehender Randfall

`optimization/ean/builders/passenger_builder.py::_can_serve_within_horizon` rechnet für das Kandidatenpruning in Sekunden. Im Grenzfixture A→B ist die tickgerundete früheste Ankunft 56.272727 Sekunden; bei genau diesem Horizont wird der Kandidat bereits dort verworfen. CP-SAT und DIDP erhalten dann beide keinen solchen Kandidaten. Der DIDP-Horizonttest übernimmt deshalb den kanonischen Kandidaten aus dem längeren Kontrollfixture, um die eigentliche exakte Ereignisbedingung zu testen. Dieser Pilot verändert den historischen Kandidatengenerator nicht. Eine spätere Korrektur muss den gemeinsamen Generator und seine Fingerprint-/Ergebnisfolgen ausdrücklich behandeln; dies ist kein gefundener Vorteil eines Solvers.

## Primärquellen

- [DIDP 0.10.1: tatsächliche Datentypen i32 und f64](https://raw.githubusercontent.com/domain-independent-dp/didp-rs/v0.10.1/dypdl/src/variable_type.rs).
- [CABS-Schnittstelle und Anforderungen an Kosten, Beam und Duplikatbehandlung](https://didppy.readthedocs.io/en/stable/_autosummary/didppy.CABS.html). Für die Implementierung zusätzlich gegen die installierte 0.10.1-Signatur und deren Docstrings geprüft.
- [DIDP-RS / DIDPPy offizielles Repository](https://github.com/domain-independent-dp/didp-rs).
