# CP-SAT stärken / IBM mit nativen Besuchsintervallen

Stand: 10.09.2026. Umsetzung des freigegebenen Sechs-Schritte-Plans. Die experimentellen Varianten sind implementiert und die erste Vergleichskampagne ist abgeschlossen: 24 gültige Läufe, keine bestätigte Performanceempfehlung. `legacy` bleibt Standard. [Abgeschlossene Auswertung](../findings/cp_formulation_campaign_20260910.md).

## Schnittstellen und Code

Alle Pfade relativ zum Repository. Gemeinsame Module unter `src/ropeway_skip_stop_optimization/optimization/ddd/`:

| Datei | Aufgabe |
|---|---|
| `cp_formulation.py` | Unveränderliche Konfiguration und PreparedCpStructure; kanonische Besuchs-/Beförderungsindizes, sichere Zeit-/Kostenuntergrenzen, Pruninggründe, CLI-Argumente und Modellidentität |
| `cp_hint_completion.py` | Deterministische Vervollständigung implizierter Startwerte einschließlich Hilfsvariablen, ohne Fixierung oder separate Suche; eindeutige Hint-Indizes |
| `cp_sat_passenger.py` | Gemeinsame ganzzahlige Passagiermodellierung, aggregierte Stop-/Aktivitätskopplung, Reisezeit- und Produktuntergrenzen |
| `cp_sat_integrated.py`, `cp_sat_capacity.py` | Fixed-K-Integration für Reisezeit bzw. unbediente Personen |
| `reservoir_cp_sat.py` | Reservoirintegration, validierte Seeds, Extraktion und Messwerte |
| `cp_resource_variants.py` | Optionale Intervalle fester Größe und zusammengeführte Exit-Merges; benutzt von beiden CP-SAT-Bewegungsbuildern |
| `reservoir_ibm_cp_model.py` | IBM-Basismodell, Passagiere, Vorverarbeitung und stabile Intervallreferenzen |
| `ibm_cp_native.py` | Besuchsintervalle mit STOP-/SKIP-Alternativen, exakte Ereignisverkettung und Ressourcenankern; Intervallstartwerte |
| `reservoir_ibm_cp.py` | IBM-Konfiguration und Solversteuerung |

Öffentliche Exporte: `DddCpFormulationConfig`, `DddCpFormulationProfile`, `PreparedCpStructure` im bestehenden DDD-Paket.

Runner: `benchmarks/run_ddd_fixed_k_cp_sat.py`, `run_ddd_reservoir_cp_sat.py`, `run_ddd_reservoir_ibm_cp.py`, `run_fixed_start_capacity_campaign.py`.

## Profile

| `--formulation-profile` | Eingeschaltete Änderung |
|---|---|
| `legacy` | Bisherige Formulierung und bisherige Startwerte |
| `hints` | Vollständige Startwerte |
| `temporal` | Optimistische Zeitgrenzen und sichere Kandidatenentfernung |
| `passenger_links` | Ein-/Aussteiger ≤ Kapazität × STOP, Belegung ≤ Kapazität × Aktivität |
| `journey_bounds` | Explizite exakte Kostenvariable, analytische sowie mengenabhängige Reisezeit-/Ankunftsschranken |
| `strengthened` | Kombination der vier Erweiterungen |

Zusätzlich CP-SAT: `--resource-encoding legacy|compact_fixed|merged_exit`. IBM: `--movement-encoding legacy|native_visits`. Ungültige Backendkombinationen werden vor dem Modellbau abgelehnt. `journey_bounds` fügt beim Kapazitätsziel keine Reisezeitprodukte ein.

Bei `compact_fixed` entfallen Hilfsvariablen für konstante Intervalldauern, soweit der Startausdruck direkt unterstützt wird. `merged_exit` vereinigt ausschließlich nachweislich passende STOP-/SKIP-Nutzungen desselben Exit-Merges; andere Ressourcen bleiben einzeln. Die variable Dauer kann die Propagation verschlechtern und wird deshalb separat gemessen.

## Unveränderte Semantik

- Integer-Mikrosekunden und ursprüngliche Waiting-Grenzen bleiben bestehen. Keine feste Kabinenreihenfolge, Periodizität oder zusätzliche Nutzung des Reservoirs.
- Fixed-K darf eine am Horizont bereits begonnene letzte Bewegung abschließen; Reservoirfahrten müssen bis Betriebsende zum Port zurückkehren.
- Zeituntergrenzen gelten nur für aktive Besuche. Inaktive Folgeeinträge bleiben künstliche Platzhalter. Ein notwendiger Rückkehr-Endknoten bleibt auch ohne anschließenden aktiven Besuch erhalten.
- Nachfragefreigabe bezieht sich weiterhin auf den Plattformausstieg einschließlich Waiting. Ausstieg der Passagiere am Ziel muss rechtzeitig erfolgen.
- Ressourcenbelegung beginnt auch bei Eintritt genau am Horizont und wird beim Räumen nicht am Horizont abgeschnitten. Überholen im Bypass bleibt zulässig.
- Originaldomäne und Kandidaten-IDs bleiben Grundlage der Checkpoints und unabhängigen Prüfer. Intern entfernte Beförderungen sind beim Export null. Positive importierte Belegung einer entfernten Beförderung löst einen Fehler aus.
- Formulierungsprofil, Encoding und vorbereitete Struktur fließen ausschließlich in den Modell-Fingerprint ein; Messzeiten nicht.
- Hints fixieren keine Entscheidungen. Fixierte Fahrpläne verwenden die getrennte bestehende Funktion.

Die Vorverarbeitung ignoriert Ressourcenkonflikte und Kapazität für optimistische Untergrenzen. Sie kombiniert frühestmöglichen Besuchsbeginn mit Nachfragefreigabe plus Mindestfahrzeit; Ursprung und Ziel erfordern STOP. Für Reservoirfahrten wird die schnellste anschließende Port-Rückkehr berücksichtigt. Waiting wird konservativ aus der verbleibenden Betriebszeit begrenzt, ohne die bestehende globale Grenze zu verkleinern.

## Kontrollen und Messung

`tests/test_cp_formulation_profiles.py` prüft Profile und Encodings gegen bekannte kleine Optima und unabhängig enumerierte Waiting-Fahrpläne. Ergänzt werden bestehende Horizont-, Überhol-, Kapazitäts- und Odd-Cycle-Prüfungen in `tests/test_optimization_ddd_cp_sat_passenger.py`. Die IBM-Tests verwenden ausdrücklich die unbeschränkte lokale Engine.

Der große R-Kontrollfall reproduziert **1.800 entfernbare von 10.100 kanonischen Beförderungskandidaten** und die abgeleitete Untergrenze **109.032,727040 Passagiersekunden**. Diese Zahlen sind Testassertionen, keine Modellkonstanten.

Vollständige R-Hints mit `strengthened` im Buildcheck:

| Ressourcenencoding | Variablen | Gehintete Variablen | Hint-Vervollständigung ungefähr |
|---|---:|---:|---:|
| legacy | 82.521 | 82.521 | 2,2 s |
| compact_fixed | 61.321 | 61.321 | 1,9 s |
| merged_exit | 63.971 | 63.971 | 1,9 s |

Diese Werte sind vor Presolve und belegen keine bessere Suchleistung. Explizites Indexieren der OR-Tools-Protobuf-Felder vermeidet sehr langsame C++-Exceptions beim Ende der Python-Iteration; dadurch sank der ursprüngliche Hint-Vervollständigungsschritt von etwa 29 auf 2 Sekunden.

Messfelder unterscheiden physische Vorbereitung (`prepare_seconds`), Vorverarbeitung im Builder (`model_stats.preprocessing_seconds`), Modell-/Hintaufbau, Solveraufruf, Validierung und reale Gesamtlaufzeit. `build_seconds` bleibt für Kompatibilität der inklusive Aufbauwert; `model_build_seconds` schließt den separat ausgewiesenen Hintanteil aus und enthält weiterhin Vorverarbeitung/Modellprüfung/Hashbildung. Seedübernahme wird getrennt von Verbesserung ausgewiesen. Der tatsächlich validierte importierte Seedwert wird gespeichert.

## Erste Vergleichskampagne

`benchmarks/run_cp_formulation_campaign.py --output-dir benchmarks/output/<neues_verzeichnis> --wall-seconds 7200`

- Neue Ergebnisverzeichnisse; keine historischen Ergebnisse überschreiben.
- Quellenarchiv, SHA-256-Hashes, Enginepfad/-hash, Versionen, Eingangscheckpoints und vollständige Profile werden gespeichert. Quellenänderungen während der Kampagne führen zum Abbruch.
- R: Max50, Waiting 1.200 s, 1.280 Personen, Reisezeit; Seed 369.892,972760 Passagiersekunden.
- C: ursprüngliches Fixed-K39-Placement, Waiting, 3.074 Personen, unbediente Personen; ursprünglicher Kapazitätstest-Seed.
- 16 Screeningläufe à 180 s, Seed 0; danach acht Bestätigungsläufe à 300 s mit Seeds 1 und 2. Je zwölf Worker, strikt nacheinander.
- Hartes Gesamtbudget inklusive Unterprozessaufbau, Nachverarbeitung und Abschluss. Vor Ablauf werden keine weiteren Läufe gestartet, wenn Laufbudget plus Reserve nicht mehr passt; ein Watchdog beendet überziehende Unterprozesse. Ausstehende/fehlgeschlagene Bestätigungen werden nicht als Erfolg gewertet.
- Auswahl nach validierter UB, vergleichbarer LB, erster Verbesserung. Alle R-Varianten erhalten in der Auswertung dieselbe analytische LB-Untergrenze.
- Empfehlung erfordert in beiden zusätzlichen Seeds mindestens 0,1 % niedrigere R-Kosten, zehn weniger unbediente Personen bei C oder einen Prozentpunkt kleineren vergleichbaren relativen Gap ohne schlechtere UB. Sonst `inconclusive`; fehlende Bestätigung `pending`.
- `status.json`, `results.json`, `selected.json`, `evaluation.json` und `comparison.md` enthalten Verlauf und Bewertung. Pro Lauf liegen Modellgrößen, Log, Ereignisse und unabhängig geprüfte Ergebnisse vor.

## Bewusst zurückgestellt

Eine explizite Belegungsfortschreibung `L_i = L_(i-1) + B_i - A_i` wäre ein weiterer Ansatz, benötigt aber genaue Anfangs-/Endbelegung und soll die jetzige Ablation nicht vermischen. Bestehende Abschnittskapazitätssummen bleiben erhalten. IBM-Fixed-Start, Reservoir-Wiedereinsatz und eine lexikografische Zielfunktion sind nicht Bestandteil dieses Pakets. Kein automatischer Standardwechsel nach der Kampagne.

## Verifikation des Ausgangsstands und Ausführung

Der reine Legacy-R-Modellbau wurde gegen das Archiv vor der Umsetzung verglichen (identischer Python-Hashseed): Beide erzeugen 87.020 Variablen, 190.188 Constraints und den Modell-Fingerprint `a39d0ea4e69cac271dc94f98b3773262d6c28b7cba5e96806c706a33998efbdc`.

Der große fixierte R-Referenzfahrplan wurde auch mit IBM `strengthened/native_visits` und Engine 22.2.0.0 geprüft: Solverstatus `Feasible`, unabhängig bestätigte Kosten 369.892,972760. Das ist eine Kompatibilitätsprüfung und kein freier Performancevergleich.

Wegen einer bereits laufenden separaten Pattern-Search-Kampagne wird diese Kampagne über `--wait-for-pid` hinter deren Supervisor eingereiht. Wartedauer zählt separat (`queue_seconds`); die maximal 7.200 Sekunden Vergleichsbudget starten erst nach Ende der Vorgängerkampagne. Für diese Ausführung wird eine isolierte Kopie von Quellen, Runnern und den zwei historischen Seeds verwendet; laufende Arbeit im Hauptcheckout verändert die Kampagne dadurch nicht.

Abschließende gezielte Testsuite: **158 bestanden** (32,66 s). Ruff für die neuen Module, Kampagnensteuerung und neuen Tests ohne Befund. Die I/O-Pfade aller drei Kampagnenkombinationen (R/CP-SAT, C/CP-SAT, R/IBM) wurden einschließlich historischer Seedimporte und Ergebnisexport geprüft. Verifikationsprotokoll: `benchmarks/output/cp_formulation_implementation_20260910/verification.json`.

Zusätzliche historische Kontrollen (`controls.json` im Verifikationsordner): In allen drei Ressourcenencodings bleiben der bekannte K20-No-Wait-Plan mit 525.730,908160 Passagiersekunden und der K38-All-Stop-Kapazitätszeuge für 2.561 vollständig bediente Personen zulässig. Diese Kontrollen fixieren für den Test sämtliche vollständigen Hints und reproduzieren die Werte; sie behaupten keinen neuen globalen Optimalitätsbeweis. Produktiv bleiben Hints unverbindlich.

Abgeschlossene Kampagne: `benchmarks/output/cp_formulation_campaign_20260910_121055/`. Nach separater Wartedauer von 555,750 Sekunden lief sie am 10.09.2026 von 12:20:12 bis 13:50:07: 24 gültige Läufe, keine Ausfälle, 5.395,296206 Sekunden tatsächliche Kampagnenzeit. Alle Bestätigungsvergleiche sind nach den vorab festgelegten Schwellen `inconclusive`; kein Standardwechsel. [Ergebnisse und Einschränkungen](../findings/cp_formulation_campaign_20260910.md).

Isolierter Quellstand: `benchmarks/output/cp_formulation_runtime_20260910_121055/`. Prozessdaten einschließlich Supervisorlog: `benchmarks/output/cp_formulation_implementation_20260910/campaign_process.json`. Maßgeblich bleiben `comparison.md` und `evaluation.json` im historischen Kampagnenordner.
