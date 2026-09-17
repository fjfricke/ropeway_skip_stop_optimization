# Ganzheitliche Neubewertung der Solver und Betriebsverträge

Stand: 14.09.2026. Read-only-Auswertung der Modellfamilien, ihrer Befunde und ausgewählter Rohresultate; zusätzliche unabhängige Replays, keine neue Performancekampagne und kein Standardwechsel. Dies ist keine erneute Zertifizierung sämtlicher historischer Läufe.

**Präzisierung zur automatischen Musterentdeckung:** Die sechs erfolgreichen nativen Kompaktionsläufe hatten ausschließlich den kleinen Katalog `all_stop`, `stop_B_D`, `stop_C_E` und einen bereits 3.036 Personen bedienenden Skip-Stop-Startplan. Die vollständige Musterfolge war nicht fixiert (`fixed_pattern_sequence=[]`), aber die naheliegenden Muster und eine sehr gute ausführbare Kombination waren vorgegeben. Das Ergebnis zeigt Verbesserung und Kombination innerhalb dieses Katalogs, keine zuverlässige eigenständige Entdeckung guter Muster aus dem breiten Katalog. Auch der 2.952-Personen-Kontrolllauf optimiert eine zuvor festgelegte gute Musterfolge. Die Existenz eines überlegenen Plans und die zuverlässige automatische Musterfindung sind getrennte Forschungsbefunde; Letztere ist weiterhin offen.

## 1. Wichtigste Korrektur: Es gibt bereits positive R2-Ergebnisse

Aktuelle Vergleichsdomäne: `benchmarks/output/reservoir_line_evolution_20260914/coupled_seed_comparison_v1/reference.json`, Fingerprint `3b18ab80e8ee5b2473777888efc2baf373b74727b843af4413736ce698fe9182`. Historische Fünf-Stationen-Geometrie, R2 mit 3.074 Personen, Single-Use-Reservoir, maximal 50 Kabinen, aktueller gemeinsamer Portschutz. Nicht mit den neuen Thesis-Geometrien gleichsetzen.

| Nachweis | Bedienung | K | Waiting | Einschränkung |
|---|---:|---:|---:|---|
| `pattern_only_campaign_v1/screen_all_stop_joint_service/best.json` | 2.504 | 38 | 0 | Optimiertes All-Stop-Timing im aktuellen kontinuierlichen No-Wait-Linienvertrag; kein globales All-Stop-Reservoiroptimum |
| `pattern_only_campaign_v1/screen_valid_joint_service/best.json` | 2.952 | 38 | 0 | Aktueller Linienvertrag, vier Drei-Halt-Muster |
| Normalisierter gemeinsamer Referenzplan | 3.036 | 36 | 0 | Zwei letzte leere Umläufe entfernen; erste zulässige Rückkehr danach eingehalten, Passagiermengen und Journey-Wert unverändert |
| Sechs `reservoir_line_compaction_20260913_search_hint_*/best.json` | **3.074** | 37/38 | **0** | Heutige ursprüngliche Physik gültig; einzelne Kabinen kehren vor Bedienungsende zurück |

Alle sechs vollständigen Bedienungspläne wurden erneut gegen die **aktuelle** physikalische Domäne einschließlich Port validiert. Der maschinenlesbare Nachweis mit SHA256 steht in [current_physical_replays.json](../../benchmarks/output/reservoir_line_evolution_20260914/no_wait_correctness_audit_v1/current_physical_replays.json).

Die spätere Linienvorbereitung fordert zusätzlich, dass eine Kabine bis zur ersten vollständigen Umlaufrückkehr am oder nach Bedienungsende weiterfährt. `reservoir_lines/preparation.py::_template` setzt dazu unter anderem `minimum_dispatch >= service_end - duration`. Die ursprüngliche Reservoirphysik erlaubt dagegen eine frühere leere Rückkehr im deklarierten Rückkehrfenster. Das ist eine echte Betriebsrestriktion, keine bloße Kodierungsänderung.

Der separate Replaybericht `historical_current_contract_replays.json` prüft diese strengere Linienregel. Sein `valid=false` für die sechs Pläne bedeutet **nicht physikalisch ungültig**. Die beiden Prüfungen müssen getrennt gelesen werden. Der aktuelle Code wurde hier nicht verändert.

## 2. Bestehender globaler All-Stop-Bound passt zum Vergleich

Archiv: `benchmarks/output/reservoir_capacity_campaign_20260911_v1/R2_all_stop_bound_s0_60s/result.json`.

- Gespeicherter exakt kompensierter rationaler Dual-Bound: ungefähr 124,5142856966 unbediente Personen.
- Ganzzahliger globaler Bound: **U_AS >= 125**, also **S_AS <= 2.949**.
- Scope: vollständiges All-Stop-Single-Use-Reservoir, nicht das eingeschränkte Primalnetz und nicht nur ein regelmäßiger Referenzfahrplan.
- Nach Umstellen auf All-Stop und Entfernen ausschließlich des später ergänzten Portschutzes stimmen die Eingabedataclasses der aktuellen und historischen Domäne exakt überein. Die unterschiedliche abgeleitete Besuchszahl entsteht aus dem Betriebsmodus.
- Der neue Portschutz schränkt die zulässige Menge weiter ein. Deshalb bleibt eine gültige alte Untergrenze auf Nichtbedienung gültig.

Der Vergleich und die Zeugen einschließlich Hashes stehen in [all_stop_bound_containment.json](../../benchmarks/output/reservoir_line_evolution_20260914/no_wait_correctness_audit_v1/all_stop_bound_containment.json).

Damit gilt bereits für den aktuellen kontinuierlichen K38-Linienplan:

`U_SS = 122 < 125 <= U_AS*`.

Der flexible Reservoirplan mit U=0 verstärkt den Abstand. Die Schranke erlaubt All-Stop die vollständigere physikalische Aufgabe einschließlich Waiting; Skip-Stop gewinnt hier sogar ohne Waiting. Das ist ein Nachweis für **diese konkrete R2-Instanz**. Es ist weder eine vollständig bestimmte maximale Profilnachfrage noch eine Aussage über sämtliche sechs Stationen/Thesis-Geometrien.

In dieser Auswertung wurde kein LP erneut gelöst. Verwendet werden das gespeicherte exakt kompensierte Zertifikat, der bestehende Projektionsnachweis und die aktuellen Domänen- und Zeugenprüfungen. Numerische Dualabsicherung und Korrektheit der physikalischen Relaxation sind unterschiedliche Nachweisschritte; siehe [Modellvertrag](../reference/reservoir_capacity_phase_arc_flow.md).

## 3. Was die unterschiedlichen Modellfamilien tatsächlich zeigen

| Familie | Relevanter Befund | Einordnung |
|---|---|---|
| Zeitdiskretes MILP / EAN | Große Zeitmodelle bis zu Millionen Variablen; kleinere EAN-Fälle liefern Verbesserungen und brauchbare Bounds. Historisches K20-EAN bleibt deutlich hinter Labelled Arc-Flow. | Gurobi ist nicht generell ungeeignet. Ereignisse helfen, lösen aber die konfliktbehaftete Fahrzeugkoordination nicht automatisch. |
| Labelled Arc-Flow, Fixed-K No-Wait | K17–22 mehrfach optimale Lösungen in Sekunden bis Minuten. Bei dichtem K39 viel Root-Arbeit und schwache Incumbents. | Bewährter exakter Baustein für kleine Journey-Fälle. Dichte Fixed-K-Startzustände sind kein verschachtelter Vergleich zu K38. |
| Anonymer Reservoir-Arc-Flow / kompakte Passagierflüsse | Deutlich kleinere Modelle und teilweise abgeschlossene Root-LPs; nicht entsprechend bessere native Bedienung. | Größe ist nur ein Engpass. Fraktionale Kabinen-/Passagierkoordination bleibt schwierig. |
| DDD / Korridorhüllen | Optimistische Bounds und Verfeinerungen möglich; konservative ausführbare Pläne bleiben schwach. K39-W14-Korridorpilot blieb bei U=2.658, CP-SAT erreichte U=2.314 in einem kurzen Vergleich. | Optimistische Kombinationen lassen sich nicht leicht gemeinsam ausführen; Rasterverfeinerung allein war kein Durchbruch. |
| Vollständiges CP-SAT | Gute historische Journey-Incumbents, schwache globale Bounds. Im echten 8h-Lauf noch Verbesserung nach rund 7,25h, aber kein großer Sprung. | Ein Plateau ist nicht zwingend dauerhaft; längere Zeit garantiert trotzdem keinen praktisch großen Nutzen. |
| Verstärkte CP-/IBM-Formulierungen | 24-Lauf-Vergleich ohne bestätigten allgemeinen Sieger; native Besuchsintervalle kein reproduzierbarer Durchbruch. | Globale Ressourcenkoordination und gekoppelte Entscheidungen bleiben. |
| DIDP / symbolisches DP | Kleine Modelle korrekt, aber große Zustandsräume und Waiting-Verzweigung. Ein symbolischer 5min-Versuch expandierte etwa 25 Millionen Zustände und blieb bei geringer Bedienung. | Andere Suchengine entfernt die Zustandskomplexität nicht. |
| Z3 / Hexaly / temporale Planer | Z3 scheiterte bereits an relevanten Skalierungsgates; lizenzierter Hexaly-Vergleich ohne Vorteil. Temporale Planer teils nicht semantisch freigegeben. | Nicht alle waren vollständige faire große Performancevergleiche. Kein beobachteter Wechselvorteil. |
| Zuordnungs-Master + Timing / Benders-artige Ansätze | Neue Masterlösungen teils nach rund 6.800s Timing weiterhin UNKNOWN. Bekannte gültige Pläne dagegen schnell reproduzierbar. | UNKNOWN liefert keinen zulässigen Infeasibility-Cut. Zerlegung verschiebt den schwierigsten Teil nach unten. |
| Eigene Nachbarschaften / festgelegte Ressourcenordnung | Auf damaligem R-Journey-Fall keine Verbesserung; feste Zuordnung und Timing teils schnell als optimal bestätigt. | Bereits getestet. Nicht als ungetestete neue Reparaturidee verkaufen; anderer Zweck als heutiges R2-Kapazitätsziel. |
| Evolution + Decoder / Dispatch-Untermodell | Viele Kandidaten, aber bei K38 häufig keine gültige Bewegung. Freie K erleichtert All-Stop-Aufbau; feste hochdiverse Mustermischungen oft bewiesen unzulässig. | Ohne gültige Pläne kaum passagierbezogenes Lernsignal. Mehr Exploration allein behebt das nicht. |
| **Integrierte native No-Wait-Linienplanung** | Mit S=3.036-Hint sechs Läufe zu U=0 nach rund 142–231s. Ohne Hint nach 300s nur S=1.048–1.613. | **Stärkster konkrete R2-Befund.** Gute Konstruktion und gute Verbesserung sind unterschiedliche Aufgaben. |

Fortschritt darf nur innerhalb desselben Laufs verglichen werden. Unterschiedliche Seeds, Betriebsregeln und Ziele ergeben keine gemeinsame Zeitkurve. Ordnernamen wie „6h“ sind kein Laufzeitnachweis; tatsächliche Resultatzeiten sind maßgeblich.

Die Linienkompaktion reduziert im Vergleich V0→V2 Variablen um etwa 68 %, Constraints um 72 % und Intervalle um 76 %. Das hilft Aufbau und Speicher, macht U=0 aber nicht in jedem Seed schneller. Bei V3 gab es nach rund 171s ohne Verbesserung noch einen großen Sprung. [Messungen und Verläufe](reservoir_line_compaction_results_20260913.md).

## 4. Keine generelle No-Wait-Implementierungsunzulässigkeit gefunden

Die frühere Diagnose ist unter `no_wait_correctness_audit_v1/` gespeichert:

- Drei erfolglose Musterfolgen wurden im Dispatch-Domänenmodell und im ursprünglichen Reservoir-Ereignismodell mit W=0 als INFEASIBLE bestätigt.
- Bekannte gemischte und All-Stop-Folgen liefern in beiden Darstellungen gültige Pläne.
- 491 geprüfte Templatepaar-Differenzen, einschließlich Grenzticks, stimmen mit dem unabhängigen physikalischen Validator überein.

Das ist belastbare Gegenevidenz zur Vermutung, der kompakte No-Wait-Builder erkläre einfach alles falsch für unzulässig. Es ist kein Vollbeweis sämtlicher Software. Bei mehreren anderen Testfällen blieb ein Encoding UNKNOWN; das wurde nicht zu INFEASIBLE umgedeutet.

Dispatch ist eine freie Zeit **je Kabine**, verschiebt aber ihren gesamten No-Wait-Verlauf. Ein früher konfliktfreier Kontakt kann deshalb später kollidieren. Die geordnete Dispatchfolge verbietet keine späteren Überholungen. Die 252 erfolglosen Stichproben verwendeten überwiegend 11–14 verschiedene Masken; ein guter aktueller K38-Plan braucht nur vier Drei-Halt-Masken. Das ist ein beobachteter Strukturunterschied, kein Beweis gegen vielfältige Muster.

## 5. Bewertung des vorgeschlagenen integrierten Gurobi-Linienmodells

Gemeinsame Auswahl von K, Maske, Dispatch, Waiting, Rückkehr und Passagieren ist konzeptionell sinnvoller als eine äußere Evolution, die häufig kein auswertbares zulässiges Individuum erhält. Gurobi könnte Timing und Musterauswahl gemeinsam ändern und Bounds für genau die modellierte Aufgabe liefern.

Allerdings ist die integrierte No-Wait-Architektur bereits im nativen CP-SAT-Linienmodell vorhanden. Neu wäre insbesondere ein vollständiges Gurobi-Ereignismodell mit wiederholter Maskenkopplung und Waiting. Es wäre EAN-verwandt, kein Zeitnetz, und weiterhin ein disjunktives Scheduling-MIP. Passagierfluss ist linear und beim Kapazitätsziel ohne Journey-Produkte; Ressourcenreihenfolgen und optionale Besuchspaare bleiben potenziell groß. Keine schnelle LP- oder Gap-Konvergenz versprechen.

Einschätzung: gegenüber weiterer Evolution plausibel aussichtsreicher; gegenüber dem bereits erfolgreichen integrierten CP-SAT-Linienmodell **offen**. Ein fairer Vergleich muss Betriebsregeln, K-Bereich, Katalog, Seed und Waiting angleichen. Ein anderer Solvername allein rechtfertigt keinen Neubau.

## 6. Eigene Ansatzpunkte und Priorität

1. **Rückkehr als bewusste Modellvariante wieder freigeben.** Feste wiederholte Masken, aber eine optimierte vollständige letzte Runde statt zwangsläufigem Umlauf bis nach Serviceende. Das entspricht der ursprünglichen Reservoirphysik; sechs aktuelle physikalische Vollbedienungszeugen belegen den Nutzen. Für einen Produktionsversuch zuerst den vorhandenen nativen Linienpfad wiederverwenden. Die bisher akzeptierte kontinuierliche Linienregel nicht still ändern; beide Verträge explizit benennen.
2. **Synchronisation als begrenzte Waiting-Variante.** Statt beliebige heterogene Umlaufzeiten immer wieder reparieren zu müssen, gemeinsame oder wenige kompatible Umlaufzeiten wählen. Wiederholte Waiting-Anteile pro Muster/Station können die zeitliche Drift reduzieren; Dispatch und Passagiere bleiben gemeinsam optimiert. Das schränkt die Aufgabe periodisch ein und ist nur ein zusätzlicher konstruktiver Ansatz, kein Ersatz für das vollständige Modell. Warmup, Rückkehr und periodengrenzenübergreifende Ressourcenkonflikte müssen original validieren. Analogie: [Horváth, cyclic hoist scheduling](https://arxiv.org/abs/2603.24316) vergleicht CP-/MIP-Formulierungen zyklischer Transport-/Prozessplanung und zeigt zugleich, wie stark abweichende Modellannahmen Ergebnisvergleiche verfälschen können. Das Paper garantiert keine Seilbahnperformance.
3. **Gurobi als kontrollierte alternative Engine derselben kompakten Linienaufgabe.** Erst kleine exakte Fälle und vorhandene gute Muster/Pläne reproduzieren, anschließend freie Auswahl unter gleichem Vertrag gegen CP-SAT vergleichen. Enge lokale Zeitgrenzen, nur tatsächlich mögliche Konfliktpaare, Integer-Ride-Mengen, keine Zeitkopien und keine Journey-Produkte bei `unserved`. Kein zusätzlicher äußerer LNS-/Evolutionscontroller.

Empfohlene Reihenfolge: vorhandenen R2-Zeugen und All-Stop-Bound als ein zusammengehöriges Ergebnis sichern; den Rückkehrvertrag für die Thesis bewusst festlegen; dann den bereits erfolgreichen nativen Linienansatz auf die definierten Szenarien übertragen. Eine Gurobi-Variante bleibt ein begrenzter Vergleich, keine Voraussetzung, um den vorhandenen R2-Erfolg anerkennen zu können.

## 7. Weitere eingesehene Befunde

- [Historischer Familienaudit](solver_history_audit.md)
- [CP-/IBM-Ablation](cp_formulation_campaign_20260910.md)
- [Reservoir-Diagnostik](reservoir_diagnostics_20260911.md)
- [DIDP](ddd_fixed_k_didp_pilot_20260910.md)
- [Symbolisches und Pattern-DP](reservoir_symbolic_and_pattern_dp_20260912.md)
- [Alternative Engines](native_solver_pilot_20260911.md), [Hexaly](hexaly_recheck_20260911.md)
- [Zuordnungs-/Timing-Pilot](reservoir_assignment_timing_pilot_20260912.md)
- [Kompakter Reservoir-Arc-Flow](reservoir_compact_architecture_20260911.md)
- [Korridor-Waiting](ddd_corridor_waiting_arc_flow_20260914.md)

Die Familien wurden anhand ihrer Implementierungen, Befunde und entscheidenden Rohresultate eingeordnet. Die neuen Replays und Domänenvergleiche sind enger und stärker als eine bloße Wiederholung alter LLM-Einschätzungen, ersetzen aber keine vollständige erneute Software- und Relaxationsprüfung.
