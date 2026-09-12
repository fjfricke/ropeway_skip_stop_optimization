# Reservoir-Diagnose: Wo bricht die integrierte Suche ein?

Autorisierung: Chat „ok mach mal“, 11.09.2026. Keine neue Suchheuristik,
kein Standardwechsel. Ausgangspunkt ist derselbe unabhängig geprüfte
Max50-/Waiting-Fahrplan mit 38 eingesetzten Kabinen, 1.280 Personen und
368.765,817136 Passagiersekunden.

## Varianten

| Profil | Fest | Frei |
|---|---|---|
| passengers | gesamte Bewegung | Integer-Passagiere |
| timing | aktive Besuche und STOP/SKIP | Dispatch, Waiting, Passagiere |
| timing_order | wie timing, zusätzlich Ressourcenreihenfolgen aus Referenz | Zeiten und Passagiere innerhalb dieser Reihenfolgen |
| routes | aktive Besuche einschließlich letzter Bewegung | STOP/SKIP, Dispatch, Waiting, Passagiere |
| lifecycle | genau 38 eingesetzte Kabinen | zusätzlich letzte Besuche/Rückkehr, alle übrigen Bewegungen |
| full | keine der obigen Entscheidungen | vollständiges bestehendes Reservoir bis Max50 |

Alle Varianten verwenden dasselbe unveränderte Mikrosekundenraster, dieselben
Ressourcenregeln, dieselbe Nachfrage und denselben Startwert. Die ursprünglichen
NoOverlap-Bedingungen bleiben erhalten. Eine Einschränkung ist kein globaler
Optimalitätsnachweis: nur `full` hat globale Proof-Scope. Auch eine neue gültige
Lösung eines eingeschränkten Modells ist dagegen eine gültige globale UB.

Bei `timing_order` werden ausschließlich die im Referenzplan präsenten Nutzungen
pro Ressource geordnet. Eine bedingte Kette aus bisherigen Räumungsenden erhält
auch dann die Reihenfolge, wenn eine mittlere Nutzung abwesend wird. Nicht im
Seed präsente Nutzungen werden nicht willkürlich einsortiert. Ihre Zahl wird
angegeben. Zustandszeit-Eindeutigkeit bleibt separat bestehen. Für den
Hauptfall wurden 3.039 Nutzungen geordnet; keine ausgewählte Nutzung lag im
Seed außerhalb des Präsenzhorizonts. Das Zusatzmodell erhält 9.117 Hilfsvariablen;
es ist daher kein reiner gleich großer Parametervergleich.

## Prüfungen und Budget

- Kleine Regressionen: Fixierungen halten die Referenz zulässig, volle
  Passagieroptimierung, korrekte Proof-Scope, freie Zeitvariablen im Timingprofil,
  unterschiedliche Rückkehrbesuche bei festem K, zulässiges Überholen und
  dessen gezielter Ausschluss durch die diagnostische Ressourcenreihenfolge.
- Vor Suchläufen alle sechs Profile mit vollständig fixierter historischer
  Bewegung und Belegung reproduzieren; 30 Sekunden Prozessbudget pro Prüfung.
- Anschließend sechs Profile mit Seeds 0 und 1, je 120 Sekunden tatsächlichem
  Prozessbudget einschließlich Aufbau. Solver erhält fünf Sekunden weniger
  für Abschluss/Validierung. Zweite Reihenfolge umgekehrt.
- Zwölf Worker, Legacy-Formulierung, identischer Seed, bestehender gültiger
  Incumbent-Cutoff. Kein konkurrierender Solverprozess, 8 GiB Prozessbaumlimit.
- Harte Gesamtdauer 1.800 Sekunden ab Kampagnenstart; offene Slots bleiben offen.

Die vorhandene beständige globale Schranke wird getrennt aus ihrem historischen
Zertifikat beurteilt. Eingeschränkte CP-SAT-Schranken werden nicht global
übernommen. Eine Aussage über die Hauptursache verlangt reproduzierbare
Unterschiede; ein einzelner Fahrplan und zwei Seeds begrenzen die Aussage.

## Integration und Ergebnisse

- `optimization/ddd/reservoir_diagnostics.py`: unveränderliche Profildefinition,
  zusätzliche Constraints und unabhängiger Check exportierter Einschränkungen.
- `DddReservoirCpSatOptimizer.solve(..., diagnostic=...)`: optionaler Zusatz;
  Default bleibt unverändert. Ohne Referenz oder zusammen mit `fixed_plan`
  wird die Verwendung abgelehnt.
- `benchmarks/run_reservoir_diagnostics.py`: Quellen/Input einfrieren, historische
  Freigaben, sequenzielle Kampagne, native und validierte Ereignisse,
  Prozessmetriken und Abbruchüberwachung.
- `benchmarks/output/reservoir_diagnostics_20260911_v1/`: eigenständige Ausgaben.
- Abschluss: `docs/findings/reservoir_diagnostics_20260911.md`.

## Gezielter Zusatz nach den ersten Timingbefunden

Auch `timing_order` schließt den eingeschränkten Gap in Seed 0 nicht. Um die
noch freie Passagier-/Zeitkopplung zu prüfen, folgen innerhalb derselben
1.800-Sekunden-Deadline zwei zusätzliche Profile:

- `timing_assignment`: wie `timing`, zusätzlich alle kanonischen Ride-Mengen fest.
- `timing_order_assignment`: wie `timing_order`, zusätzlich Ride-Mengen fest.

Beide behalten Dispatch und das vollständige Waiting frei. Bei festen Mengen
werden die bisherigen Zeitprodukte durch Presolve linear; es wird keine
Zielfunktion ersetzt. Die unabhängige Extraktionsprüfung prüft auch die Mengen.
Je Profil zuerst historischer Replay, dann Seeds 0 und 1 mit 90 Sekunden
Prozessbudget. Ein Unterschied zu den 120-Sekunden-Hauptläufen ist ausdrücklich
zu berücksichtigen; ein bewiesenes Optimum in kürzerer Zeit ist belastbarer als
bloß ausbleibender Fortschritt bei unterschiedlichen Zeitlimits.

Die Hauptkampagne läuft mit unveränderten eingefrorenen Quellen weiter. Der
Zusatz bekommt eine eigene Quellenkopie und Hashliste. Er startet erst nach
Abschluss der Hauptkampagne und wird bei fehlendem Restbudget ausgelassen.

## Abschluss

Am 11.09.2026 ausgeführt: sechs Hauptprofile und zwei Zusatzprofile, jeweils zwei
Seeds; acht historische Replays und 33 Tests bestanden. Suchkampagne 20 min 52 s,
inklusive anschließender Auswertung innerhalb von 30 Minuten. Kein weiterer Lauf
und kein Standardwechsel. Ergebnisse und nächste begrenzte Hypothese stehen im
[Abschlussbericht](../findings/reservoir_diagnostics_20260911.md).
