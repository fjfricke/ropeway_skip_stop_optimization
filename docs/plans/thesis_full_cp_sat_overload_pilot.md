# Vollständiges CP-SAT bei 110 % der All-Stop-Kapazität

Der erste Pilot verwendet T5R/G500/F2/P0 mit 3.210 Personen, entsprechend
`ceil(1.1 * 2918)`, und höchstens 69 optionalen Kabinen. Die nachgewiesene
regelmäßige No-Wait-All-Stop-Lösung mit 62 Kabinen wird unter der erweiterten
Nachfrage neu belegt und anschließend als freier Hint an das vollständige
Reservoir-Modell übergeben.

Das exakte lexikografische Ziel minimiert zuerst Unserved und danach die
bestehenden Journey-Time-Kosten. STOP/SKIP, Dispatch, Waiting bis 1.200 Sekunden,
Rückkehr, Flotteneinsatz und Passagiere bleiben frei. Der 30-Minuten-Pilot
einschließlich Vorbereitung läuft mit zwölf Workern und höchstens 32 GiB RSS.

Die Live-Seite zeigt den Bound und Gap des kombinierten lexikografischen Ziels,
Bedienung und Journey Time des jeweils selben validierten Incumbents sowie die
neu bewertete All-Stop-Lösung als gestrichelte Referenz. Referenzlinien sind
keine globalen Bounds. Weitere Profile, Seeds und Langläufe starten nicht
automatisch.
