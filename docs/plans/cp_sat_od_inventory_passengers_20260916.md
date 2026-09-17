# Kompaktes vollständiges CP-SAT mit OD-Passagierbeständen

Stand: 16.09.2026. Status: Kernformulierung implementiert und auf kleinen Fällen
gegen die bisherige Formulierung geprüft. Der reale T5R-Build ist deutlich
kleiner; ein Laufzeitvorteil in der freien Suche ist noch nicht nachgewiesen.
Dieser Plan ergänzt den
[Überlast-Piloten](thesis_full_cp_sat_overload_pilot.md).

## 1. Ziel und unveränderter physikalischer Vertrag

Die explizite Zuordnung jeder Ankunftsgruppe zu jeder möglichen Kabinenfahrt
wird durch ganzzahlige Fahrtmengen und einen gemeinsamen Verfügbarkeitsbestand
je OD ersetzt. Das vollständige Reservoir-CP-SAT-Modell entscheidet weiterhin
gemeinsam über optionale Kabinen, Dispatch, einzelne STOP/SKIP-Entscheidungen,
Waiting, Rückkehr und Passagierbeförderung.

Es werden keine Muster, globalen Kabinenreihenfolgen oder gröberen Zeitraster
eingeführt. Insbesondere bleiben Überholen an Stationen und freie Dispatchzeiten
erhalten. Die Seilfahrt ist bereits eine feste Zeitverschiebung; dort liegt
nicht der größte Faktor der aktuellen Modellgröße.

Erster Vergleichsfall: T5R/G500/F2/P0, N=3.210, K≤69, Nachfragefreigaben wie
bisher auf 15 Sekunden, Bewegung in Mikrosekunden, maximal 1.200 Sekunden
Waiting unter der bestehenden Freigaberegel. Ziel: exakt lexikografisch zuerst
Unserved, anschließend das bestehende Journey-Time-Ziel mit Unserved-Strafe.
Die Varianten `unserved` und `journey_time` müssen ebenfalls unterstützt werden.

Der vorherige Überlastlauf wurde auf Wunsch beendet. Sein Ergebnis bleibt als
historische Kontrolle erhalten.

## 2. Ausgangslage und überprüfbare Erwartung

Der Aufbau des aktuellen Überlastmodells ergab vor Presolve:

| Größe | Wert |
|---|---:|
| Variablen | 638.127 |
| Constraints | 2.337.064 |
| Ankunftsgruppenbezogene Ride-Kandidaten | 273.240 |
| Unterschiedliche Kabinen-/Ein-/Ausstiegsbesuche dieser Kandidaten | 1.518 |
| Nachfragegruppen | 360 |

Allein Mengenvariable und Nutzungsliteral pro Ride ergeben 546.480 Variablen.
Die vorhandene zeitliche Vorprüfung markiert 49.680 Kandidaten als außerhalb
des Bedienungshorizonts. Die Gültigkeit dieser Vorprüfung wird vor Wiederverwendung
auch für positives Waiting geprüft.

Die erste Implementierung erreicht 97.361 Variablen und 166.328 Constraints.
Nach Presolve verbleiben 36.868 Variablen und 81.355 Constraints. Andere
Nachfrageprofile können mehr unterschiedliche OD-Fahrten besitzen. Speicher und
tatsächlicher Suchfortschritt werden weiterhin separat gemessen.

## 3. Exakte aggregierte Darstellung

### 3.1 Zulässige Aggregationsklassen

Eine Klasse d enthält Personen mit gleichem Ursprung, Ziel, zulässiger Richtung
und identischen Beförderungsregeln. Sie dürfen sich innerhalb dieser Klasse nur
in Freigabezeit und Anzahl unterscheiden. Gemeinsamer Bedienungshorizont H,
gleiche Zielgewichte und keine individuellen Fristen oder maximalen Wartezeiten
sind Voraussetzungen.

Der Builder prüft diese Voraussetzungen ausdrücklich. Zusätzliche individuelle
Eigenschaften erfordern getrennte Klassen oder die bisherige Darstellung;
unbekannte Eigenschaften dürfen nicht stillschweigend verworfen werden.

Eine Fahrt j identifiziert Klasse, Kabine, Ein- und Ausstiegsbesuch. Es bleiben
die bisherigen Regeln für direkte Fahrten ohne Umstieg oder zusätzliche Runde
maßgeblich. Mengen q_j sind ganzzahlig in [0, Kabinenkapazität].

Bei q_j>0 müssen beide Besuche aktive STOPs sein. Einstieg b_j berücksichtigt
das zulässige Exit-Waiting am Ursprung. Ankunft a_j liegt am Plattformeintritt
des Ziels vor dessen Exit-Waiting. Es gilt 0≤b_j≤a_j≤H.

Für jeden durchfahrenen Besuchsabschnitt bleibt die Summe aller dort
beförderten Mengen höchstens die Kabinenkapazität. Eine Fahrt belegt die
Abschnitte vom Einstiegsindex einschließlich bis zum Ausstiegsindex
ausschließlich; dadurch wird Aussteigen vor erneutem Einsteigen abgebildet.

### 3.2 Verfügbarkeit über einen globalen Cumulative-Constraint

Für Klasse d seien N_d die Gesamtnachfrage und

\[
A_d(t)=\sum_{g\in d:r_g\le t}n_g
\]

die bis t freigegebene Personenzahl. Erforderlich ist für jeden Zeitpunkt:

\[
\sum_{j\in d:b_j\le t}q_j\le A_d(t).
\]

Umsetzung mit einem `Cumulative` je Klasse, Kapazität N_d:

1. Jede Freigabegruppe erhält ein festes Intervall [0,r_g) mit Höhe n_g.
   Es zählt noch nicht verfügbare Personen. Bei r_g=0 wird das Intervall ausgelassen.
2. Jede Fahrt erhält ein Intervall [b_j,E) mit variabler Höhe q_j,
   wobei E=H+1 Tick ist. Es zählt bereits eingestiegene Personen.
3. Die gemeinsame Kapazitätsbedingung ist somit N_d−A_d(t)+B_d(t)≤N_d.

E=H+1 stellt sicher, dass auch Einstiege exakt bei H berücksichtigt werden.
Durch halboffene Intervalle dürfen Freigabe und Einstieg auf demselben Tick
liegen. Gleichzeitig einsteigende Kabinen teilen denselben Bestand.

Für ungenutzte Fahrten darf das Hilfsintervall keine Bewegung einschränken.
Vorgesehen sind ein Nutzungsliteral z_j mit z_j≤q_j≤C·z_j sowie ein separater
Hilfsstart β_j∈[0,H], der nur bei z_j=1 an die tatsächliche Einstiegszeit
gekoppelt ist. Intervall [β_j,E) wird optional mit z_j erzeugt; seine Dauer ist
E−β_j. Unbenutzte Hilfswerte werden deterministisch auf Dummywerte gesetzt.

Es entstehen weder Mikrosekundenrastervariablen noch explizite Paarvergleiche
aller Einstiegszeiten. CP-SAT löst die globale Bedingung. Seine interne Expansion
und Propagationskosten müssen dennoch gemessen werden.

Der native OR-Tools-`Reservoir`-Constraint unterstützt in der derzeit installierten
Version keine variablen Mengenänderungen. Deshalb wird die Konstruktion zunächst
mit `Cumulative` und variablen nichtnegativen Höhen umgesetzt. Eine Zerlegung
jedes Sitzes in ein eigenes Reservoirereignis gehört nicht zur ersten Variante.

### 3.3 Zielwert ohne Zuordnung zu Freigabegruppen

Für Freigaben 0≤r_p≤H gilt unverändert:

\[
J=\sum_{p\text{ bedient}}(a_p-r_p)
 +\sum_{p\text{ unbedient}}(H-r_p)
 =\sum_jq_j a_j+H\left(N-\sum_jq_j\right)-\sum_p r_p.
\]

Der letzte Term ist konstant. Die vorhandene Aggregation nach Ausstiegsbesuch
und das `product`-Encoding werden wiederverwendet; keine Kostenprodukte je
Freigabegruppe. Unserved wird je Aggregationsklasse bilanziert.

Für das lexikografische Ziel bleibt die bestehende, überprüfte Gewichtung
mit B+1 erhalten, wobei B=Σ_p(H−r_p) die obere Journey-Time-Grenze ist.
Ganzzahligkeit, Wertebereiche und sichere numerische Berichterstattung werden
auch für die neue Darstellung geprüft.

Die mittlere Journey Time nur der bedienten Personen ist weiterhin eine
Kontrollkennzahl. Anders als J kann sie davon abhängen, welche freigegebenen
Personen nachträglich ausgewählt werden. Deshalb wird die Rekonstruktionsregel
mitgespeichert; diese Kennzahl darf nicht als eindeutig durch q bestimmt gelten.

## 4. Gleichheit und unabhängiges Zertifikat

Vor Einsatz werden beide Richtungen geprüft:

- **Original → aggregiert:** Mengen der Freigabegruppen je Fahrt summieren.
  Verfügbarkeit, Abschnittskapazität, Unserved und J bleiben erhalten.
- **Aggregiert → Original:** Pro Klasse die positiven Fahrten nach tatsächlicher
  Einstiegszeit sortieren; bei Gleichstand nach stabiler Fahrt-ID. Die Plätze
  deterministisch mit den frühesten bereits freigegebenen, noch nicht zugeordneten
  Personen füllen. Gruppen dürfen ganzzahlig auf mehrere Fahrten verteilt werden.
  B_d(t)≤A_d(t) garantiert dafür ausreichenden Bestand.

Diese Sortierung erfolgt erst bei der Zertifikatserzeugung und schränkt die
Suche nicht ein. Physische Reihenfolgen oder Ankunftsreihenfolgen am Ziel werden
nicht fixiert. Die Rekonstruktion liefert die bisherigen kanonischen Ride-IDs
und ein bestehendes `DddReservoirCpPlan`-Zertifikat.

Der unabhängige Validator prüft weiterhin konkrete Freigaben, STOP-Endpunkte,
Zeiten, Abschnittslasten, Rückkehr und J. Keine Lösung wird nur aufgrund der
aggregierten Modellbewertung als gültiger Incumbent veröffentlicht.

## 5. Implementierung und Integration

1. **Separate Vorbereitung:** unveränderliche Aggregationsklassen und Fahrtkeys
   direkt aus Topologie, Besuchsstruktur und OD-Verbindungen erzeugen. Kein
   vollständiges Kreuzprodukt aus Freigabegruppen und Fahrten als Voraussetzung.
   Historische Kandidatenlisten dienen nur der Gleichheitsprüfung.
2. **Passagierbuilder:** neues Modul neben `cp_sat_passenger.py`, beispielsweise
   `cp_sat_passenger_inventory.py`, mit Fahrtmengen, gemeinsamen Fahrtbedingungen,
   Cumulative-Verfügbarkeit, Abschnittskapazität und vorhandenen Kostentermen.
3. **Gemeinsame Schnittstelle:** Builder, Zielausdruck, Hints, Extraktion und
   Modellstatistik kapseln. Bestehende Optimierung und Bewegungsbuilder bleiben
   gemeinsam; kein zweiter vollständiger Solvercontroller.
4. **Zertifikatsadapter:** originale Mengen als aggregierten Hint übernehmen,
   zusätzliche Bestandsvariablen konsistent belegen und Lösungen deterministisch
   zurückübersetzen. Der Seed bleibt frei optimierbar.
5. **Unabhängige Prüfung:** benötigte kanonische Kandidaten nach Möglichkeit nur
   für tatsächlich benutzte Fahrten erzeugen. Änderungen am Kandidatenzugriff
   des Validators separat gegen den bisherigen vollständigen Zugriff prüfen.
   Ein langsamer Legacy-Validator darf anfangs als Kontrollpfad erhalten bleiben,
   seine Zeit und sein Speicher müssen ausgewiesen werden.
6. **Optionale Konfiguration:** `--passenger-encoding groups|od_inventory`,
   Standard zunächst `groups`. Modellfingerprint enthält Encoding und Version;
   physikalischer Domänenfingerprint bleibt bei identischem Vertrag gleich.
7. **Runner/Frontend:** bestehende Überlastseite weiterverwenden. Encoding,
   Modellgrößen, Startlösung, native Verbesserungen, Bedienung, Journey Time,
   Bounds und Gap eindeutig zuordnen. Rekonstruktion/Validierung separat messen.

Relevante Integrationspunkte sind `reservoir_cp_sat.py`, `cp_sat_passenger.py`,
`reservoir_cp_sat_certificate.py`, die strukturelle Passagiervorbereitung und
`benchmarks/run_thesis_full_cp_sat_overload.py`.

Die Kernformulierung, Umschaltung, Hints, Rückübersetzung, Runner- und
Frontendkennzeichnung sind umgesetzt. Die erste Version nutzt für die
Rückübersetzung noch den bereits vorhandenen vollständigen Legacy-Kandidatenkatalog.
Eine direkte strukturelle Erzeugung nur der 1.518 aggregierten Fahrten bleibt
eine weitere Vorbereitungsoptimierung; sie ändert die mathematische Formulierung
nicht.

## 6. Pflichtprüfungen vor Performancevergleichen

| Prüfung | Erforderlicher Nachweis |
|---|---|
| Vollständige kleine Enumeration | Gleiche zulässige aggregierte Belegungen und gleiche Optima wie Originalmodell |
| Mehrere Ankunftsgruppen | Keine Aufnahme vor Freigabe; zulässige spätere Aufnahme bleibt möglich |
| Gleichzeitige Ereignisse | Freigabe und Einstieg auf gleichem Tick zulässig; zwei Kabinen überbuchen keinen Bestand |
| Tickgrenzen | Freigabe−1/Freigabe/Freigabe+1 sowie H−1/H/H+1 korrekt |
| Nullfälle | Keine Nachfrage, ungenutzte Kabine und q=0 schränken die Bewegung nicht zusätzlich ein |
| Waiting | Freigabe während Ursprung-Waiting nutzbar; Ziel-Waiting verschiebt Ankunft nicht |
| Kapazität | Volle Kabine, überlappende ODs, Aus-/Einstieg beim selben Besuch und bekannte Ganzzahligkeitsfälle |
| Freie Reihenfolge | Zwei Kabinen tauschen ihre Einstiegsreihenfolge; Überholung und verschiedene Zielankunftsreihenfolgen |
| Lebenszyklus | Nicht stattfindende Besuche, Rückkehr und aktive Endpunkte bleiben korrekt |
| Zielwert | Gleiche U und J nach beiden Übersetzungsrichtungen für alle drei Ziele |
| Scope | Individuelle Fristen/Gewichte/abweichende Regeln werden getrennt oder ausdrücklich abgelehnt |
| Historische Zertifikate | All-Stop und vorhandene gültige Skip-Stop-/Waiting-Pläne unverändert bewertbar |
| Fehlerfälle | Timeout/Ressourcenlimit erhält validierten Seed; UNKNOWN ist kein Unzulässigkeitsbeweis |

Zusätzlich variable Timings auf einem kleinen integrierten Fall ohne Fahrplanhint
lösen. Ein Vergleich ausschließlich bei festgehaltener Bewegung reicht nicht.
Auf kleinen zufälligen Instanzen Aggregation und Rekonstruktion systematisch
gegen den Originalvalidator prüfen. Die neue Vorbereitung muss strukturelle
Ride-Regeln für alle unterstützten Profile erhalten, nicht nur für F2.

## 7. Vergleichsablauf und Erfolgskriterien

Nach bestandenen Gates werden zunächst beide Modelle für dieselbe eingefrorene
Instanz aufgebaut: Counts vor/nach Presolve, Vorbereitungszeit, Buildzeit,
Speicher, Anzahl OD-Klassen, aggregierte Fahrten und Cumulative-Intervalle.
Auch die Größe der Python-Vorbereitung wird gemessen.

Vorgeschlagener erster Laufzeitvergleich: `groups` gegen `od_inventory`, Seed 0,
je höchstens 30 Minuten einschließlich Build und Abschluss. Beide bekommen
exakt dasselbe unabhängig validierte All-Stop-Zertifikat unter N=3.210; dessen
Passagierbelegung wird vor dem Vergleich einmal eingefroren. Eine stärkere
Referenzneubewertung nur für eine Variante wäre kein fairer Start.

Zwölf Worker, höchstens 32 GiB Prozessbaum-RSS, systemweiter Speicherdruck und
Wandzeit einschließlich Suspend über den bestehenden Supervisor. Läufe
sequenziell; keine konkurrierenden Solverjobs. Bestehenden Lauf nur dann als
Kontrolle verwenden, wenn Startplan, Vertrag, Budget und Parameter nachweislich
übereinstimmen. Ausfälle erzeugen keine automatischen Zusatzläufe.

Gespeichert werden native Ziel-/Boundereignisse, validierte Incumbents,
Zeit bis zur ersten echten Verbesserung, Fortschritt über Zeit, Presolve,
Modellgrößen, Speicher, Rekonstruktionszeit, Versionen und Codehashes. Die
gestrichelte All-Stop-Linie stammt aus demselben Startzertifikat. Nmax=2.918
bezeichnet vollständige Bedienbarkeit der verschachtelten Nachfrage; eine
Teilbedienung bei N=3.210 kann darüber liegen.

Ein Größenbefund und ein Suchbefund werden getrennt berichtet. Fortsetzung ist
begründet, wenn die exakte Gleichheit besteht und die neue Variante entweder
eine bessere lexikografische Lösung erreicht oder die Endqualität der Kontrolle
in höchstens halber Zeit bei nicht schlechterem Endwert erreicht. Ein Seed ist
ein Pilot, keine robuste Laufzeitaussage. Global bessere Bounds zählen als
zusätzlicher Befund; eine Größenreduktion allein ist kein Durchbruch.

Bei fehlender Verbesserung prüfen: interne Expansion der Cumulative-Constraints,
schwache Weitergabe von Verfügbarkeit an variable Mengen, Dominanz der physischen
Ressourcen oder Kosten der Zertifikatsprüfung. Befund später separat unter
`docs/findings/cp_sat_od_inventory_passengers_20260916.md` dokumentieren.

## 8. Nachgelagerte Optionen

Erst nach dem isolierten Passagiervergleich:

- Bewiesen sichere früheste/späteste Besuchszeiten, STOP-spezifische Reisezeiten
  und Rückkehrgrenzen für weitere Fahrtreduktion verwenden.
- Bereits vorhandene kompakte Ressourcenencodings einzeln vergleichen.
- Gültige Bedienungsobergrenzen aus OD-Beständen, Abschnittskapazitäten und
  Zeitfenstern ergänzen; keine aus Heuristiken abgeleiteten Abschneidungen.
- Bei großen Cumulative-Kosten alternative exakte Bestandsencodings vergleichen.

Eine neue Evo-Schicht, feste STOP-Muster, gröbere Nachfrage, eingeschränktes
Waiting und lokale Suche gehören nicht zu diesem ersten Formulierungsvergleich.

## 9. Literatur und Abgrenzung der eigenen Herleitung

- Schutt, A.; Stuckey, P. J. (2016): **Explaining Producer/Consumer Constraints**,
  CP 2016, S. 438–454, DOI
  [10.1007/978-3-319-44953-1_28](https://doi.org/10.1007/978-3-319-44953-1_28).
  [Institutionelle Beschreibung](https://research.monash.edu/en/publications/explaining-producerconsumer-constraints/).
  Grundlage: Bestandsereignisse, globale Constraints und erklärende Propagation;
  kein Nachweis für die Performance unseres Seilbahnmodells.
- OR-Tools: [Scheduling recipes – Cumulative constraint with min and max capacity profile](https://github.com/google/or-tools/blob/stable/ortools/sat/docs/scheduling.md).
  Grundlage: Kapazitätsprofile durch feste Intervalle und Intervallsemantik.
  Variable nichtnegative Höhen zusätzlich gegen die installierte Python-API
  `CpModel.add_cumulative` prüfen und deren Version protokollieren.
- **Implementing Cumulative Functions with Generalized Cumulative Constraints**
  (2025), [arXiv:2508.01751](https://arxiv.org/abs/2508.01751).
  Verwandte Forschung zu kumulativen Funktionen und Producer/Consumer-Modellen;
  deren spezielle Propagatoren sind nicht automatisch Bestandteil von CP-SAT.

Die konkrete OD-Aggregation, die Anwendung der Intervallkonstruktion auf
Nachfragefreigaben, die Zielwerterhaltung und der Zertifikatsadapter werden als
eigene Herleitung beschrieben. Quellenzugriff: 16.09.2026.
