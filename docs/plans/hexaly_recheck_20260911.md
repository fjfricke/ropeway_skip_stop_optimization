# Hexaly nach Lizenzfreigabe erneut prüfen

Nutzerfreigabe am 11.09.2026: Hexaly-Test mit bereitgestellter Lizenz wiederholen.
Der Code wird ausschließlich in einer privaten Lizenzdatei außerhalb des Projekts
gehalten. Kein Lizenzinhalt in Quellen, Ergebnissen oder Dokumentation.

## Vorprüfung

1. Native Engine öffnen und unabhängiges kleines Modell lösen.
2. Bestehende Kaltstarttests ausführen und ihre tatsächlichen Ergebnisse erhalten.
   Ihre Fünf-Sekunden-Optimalitätsforderungen vermischen Semantik und Leistung;
   ein Timeout bei einer gültigen suboptimalen Lösung ist kein Modellfehler.
3. Kleine historische Replays für beide Betriebsarten/Ziele; freie Modelle mit
   Startplan müssen ihn als native, unabhängig geprüfte Lösung übernehmen.
4. Native Ressourcenlisten auf Überlappungen, berührende Intervalle, Abwesenheit,
   unsortierte Nutzungen und große Tickwerte prüfen. Bestehende unabhängige
   Überholpläne müssen ihre ganzzahligen Passagieroptima reproduzieren.
5. Kaltstart einmal mit 30 s und zwölf Workern prüfen; gültige native Lösungen,
   Qualität und Beweisleistung getrennt ausweisen.
6. Historische R-/K38-/K39-Zertifikate vollständig fixiert reproduzieren und bei
   festen Bewegungen freie Passagiermengen mit den erneut berechneten CP-SAT-
   Kontrolloptima vergleichen. Jede Exportprüfung bleibt unabhängig.

Die vorhandene Replay-Routine verlangt zusätzlich einen **nativen**
Optimalitätsbeweis für das Passagierteilproblem. Ihr ursprüngliches Gate bleibt
unverändert erhalten. Für die Beurteilung werden zwei Aussagen getrennt:

- `reaches_independently_certified_optimum`: Hexaly exportiert genau den durch
  den unabhängigen Kontrollsolver bewiesenen optimalen Wert, ohne Modellfehler.
- `native_proof`: Hexaly schließt zusätzlich seine eigene Schranke auf diesen Wert.

Für den gewünschten Vergleich mit geprüfter Startlösung genügt die erste
Aussage zusammen mit vollständig korrekten Replays und Semantikprüfungen; ein
fehlender eigener Beweis wird nicht als bestandener Beweistest ausgegeben.
Die gescheiterten ursprünglichen Kurztests und das strengere Gate werden weder
überschrieben noch nachträglich als bestanden markiert. Diese Unterscheidung
ändert keine Solverformulierung und keine zulässigen Fahrpläne.

## Begrenzter Leistungsvergleich

Nach erfolgreichen Reproduktionsprüfungen: vorhandener Kampagnenrunner, nur
CP-SAT und Hexaly zugelassen. Z3 und temporale Planer werden nicht neu gestartet.

- R: ursprüngliches Max50-Reservoir, Waiting, Reisezeit; Referenz
  368.765,817136 Passagiersekunden.
- C: ursprüngliches Fixed-K39 mit festen Starts, Waiting und 3.074 Personen;
  Referenz U=1.402.
- Beide Engines, beide Fälle, Seeds 0/1/2, jeweils 150 s einschließlich Aufbau und
  Abschluss: zwölf tatsächliche Solverläufe, 30 Minuten nominelles Budget.
- Sequenziell, zwölf angeforderte Worker, rotierende Engine-Reihenfolge.
- Vorhandene maximale Kampagnendauer 60 Minuten einschließlich Vorbereitung
  und Auswertung; kein eigener Suchcontroller und kein Langlauf.
- Gleiche geprüfte Startpläne; Startwertübernahme und echte Verbesserungen trennen.
- Dieselbe gültige historische globale LB auf identischer Domäne für beide
  Engines berücksichtigen. Keine eingeschränkte Replay-LB global übernehmen.
- Empfehlung nur bei bestätigtem Vorteil in Seeds 1 und 2 nach den bestehenden
  Kriterien: 0,1 % bessere Reisezeit, zehn zusätzliche bediente Personen oder
  ein Prozentpunkt kleinerer vergleichbarer Gap ohne schlechtere UB.

## Artefakte

Der erste große Vergleich `hexaly_comparison_20260911_v1` wurde beim ersten
Hexaly-Modellaufbau nach etwa 15 Minuten Mac-Ruhezustand vom Suspend-Wächter
gestoppt. Es liegt daraus kein großer Hexaly-Suchlauf vor. Die ursprüngliche
Deadline ist abgelaufen. Das anschließende „go on“ gibt einen neuen Vergleich
in `hexaly_comparison_20260911_v2` mit erneut höchstens 60 Minuten frei.
`caffeinate -i` verhindert währenddessen automatischen Leerlauf-Ruhezustand;
die vorhandene Suspend- und Deadlineüberwachung bleibt bestehen. Beide
Engines werden frisch verglichen; Ergebnisse von v1 werden nicht vermischt.

[Vorprüfungen](../../benchmarks/output/hexaly_recheck_20260911_v1),
[Semantiktests](../../tests/test_hexaly_semantics.py),
[vorhandener Kampagnenrunner](../../benchmarks/run_native_solver_campaign.py).

Lizenzschnittstelle gemäß
[offizieller macOS-Dokumentation](https://www.hexaly.com/docs/last/installation/installationonmacosx.html).
Die tatsächliche Engine-/Paketversion wird aus der lokalen Installation erfasst.
