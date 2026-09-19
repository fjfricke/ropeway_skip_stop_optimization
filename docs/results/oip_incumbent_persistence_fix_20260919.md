# OIP: Sicherung bei Zeitabbruch

Der F3-All-Stop-Versuch der geometrischen Mischungsreihe wurde nach 300,11 s mit
`WALL_DEADLINE` beendet. Die Live-Daten enthielten 4550 bediente Personen, aber
kein vollständiges Fahrplan-/Passagierzertifikat. Diese Zahl wird daher nicht als
geprüftes Endergebnis übernommen. Der folgende F3-Versuch 46/8/8 wurde zur Reparatur
manuell gestoppt; Dateien bleiben erhalten.

Die Korrektur speichert vollständige Kandidaten im Callback und prüft anstehende
Incumbents im Hintergrund. Ein atomar gespeichertes Bündel enthält nur unabhängig
geprüfte Bewegungen, Passagiere, Manifest und Darstellung. Ein harter Prozessabbruch
kann auf dieses Bündel zurückfallen. Rohkandidaten und Live-Zahlen sind dafür
unzulässig. Wiederherstellung prüft Domäne und feste Typzahlen und behauptet kein
Optimum. Zusätzlich fordert ein eigener Wächter den Solverstopp bei Ablauf der
Suchdeadline an. Normale endgültige Ergebnisdateien werden ebenfalls atomar ersetzt.

Die native Zielfunktion, Constraints, 300-s-Gesamtbudgets und zehn Sekunden Reserve
bleiben gleich. Export und Hintergrundprüfung benötigen zusätzliche Rechenzeit.
Die Fortsetzung wird deshalb mit eigenem Quellhash dokumentiert. Es gibt keine
automatischen Wiederholungen bereits abgeschlossener oder unterbrochener Versuche.

Tests umfassen vollständige Callback-Zertifikate, normale Optimalitätsausgabe,
gezielten SIGKILL eines echten kleinen Solverprozesses, abgebrochene Validierung,
ungültige Zertifikate, fremde Domänen/Typmischungen und den Deadline-Wächter.

Abnahme: 68 Tests im kombinierten OIP-Regressionslauf bestanden; anschließend
16 gezielte Tests einschließlich des ergänzten Tests gegen fremde Typmischungen
bestanden. TypeScript/Vite-Produktionsbuild erfolgreich (bestehende Chunkwarnung).
Fortsetzung: acht bisher ungestartete Versuche; kein Ersatzlauf für die zwei
unterbrochenen F3-Versuche.
