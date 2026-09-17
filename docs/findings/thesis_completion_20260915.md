# Abschluss der Thesis-Pipeline und korrigierte Vorprüfungen

Stand: 15.09.2026. Hauptkampagne nicht gestartet.
Dieser Befund ergänzt die historische
[Implementierungsnachprüfung](thesis_implementation_review_20260915.md) und
[erste Vorprüfung](thesis_profile_preflight_20260915.md).
Bedienungszahlen sind nur bei unabhängiger Bestätigung als Ergebnisse aufgeführt.

## Fertige Softwarebausteine

- Wiederaufnehmbare Fixed-K-/Nachfragereihen mit separaten Seeds, Abbruchregeln,
  Elternprovenienz, neuen Versuchspfaden nach Abbruch und expliziter Gesamtdeadline.
- Evidenzbasiertes Gruppenmanifest: Referenz, Auflösung und gültiger Pilot
  werden getrennt geprüft. `--build-only` startet keine Solver; gesperrte
  Gruppen können nicht versehentlich als vollständige Hauptreihe starten.
- Lesender Atlas mit K-/N-/Auflösungsfiltern, nativen und unabhängig validierten
  Verläufen, zeitsynchronisiertem All-Stop-Fahrplanvergleich, Belegung soweit
  gespeichert, sowie CSV/SVG/PDF- und JSON-Exporten.
- Individuelle evolutionäre Verbesserungszertifikate, Herkunft von Startwerten
  und klare Kennzeichnung nicht abgeschlossener Läufe. Ein erhaltenes gültiges
  Zertifikat macht einen durch Deadline beendeten Prozess nicht „complete“.
- Portabler statischer Export mit Paketgrößen und SHA-256, ohne Python-Solver-
  backend. Unveränderte große Rohdateien werden beim Live-Export nicht erneut
  geparst oder kopiert. Auf der Startseite wird nur der kleine Index geladen.

Bedienung und Befehle: [Ausführungsplan](../../archive/docs/plans/thesis_study_execution_20260915.md).
Die räumliche Szenario-/Videoansicht bleibt eine vorhandene separate Ansicht.
Der neue integrierte Replay zeigt die Ereignis-/Belegungstafel. Bei historischen
Arc-Flow-Läufen ohne Zuordnungsartefakt ist Belegung ausdrücklich nicht verfügbar;
ungeprüfte native Zwischenincumbents werden nicht zu Replayzertifikaten erklärt.

## Gefundene und korrigierte Fehler

### Referenzbudget und Checkpoints

Das Phasenmodell erhielt zunächst ein vor Modellaufbau berechnetes Restbudget
nochmals als volle Suchzeit. Jetzt wird das absolute Restbudget nach Aufbau
berechnet. Neue validierte Referenzfahrpläne werden unmittelbar gesichert.
Eine Fortsetzung liest die alte Domäne, Flotte, No-Wait-Vertrag, regelmäßige
Dispatchbelegung und vollständige Bedienung erneut geprüft ein. Eine angebliche
Unzulässigkeitsgrenze verlangt einen passenden nativen INFEASIBLE-Probeeintrag.

Korrektur der ersten Diagnose: Beim alten T6/F0-Deadlineabbruch waren die finalen
Dateien doch noch geschrieben worden. Der N=1.000-Zeuge ging nicht verloren.
Die separate Fortsetzung hat ihn unabhängig geprüft; der ursprüngliche Prozess
bleibt als abgebrochen dokumentiert. Das ursprüngliche späte Schreiben war
aber ein reales Verlustrisiko und ist behoben.

### Unabhängige Arc-Flow-Passagierbewertung

Ein gültiger Fahrplan kann unabhängig eine bessere ganzzahlige Zuordnung
bekommen als die bisherige integrierte Incumbent-Zuordnung. Der Vergleich auf
exakte Gleichheit hatte deshalb einen F0-Lauf fälschlich als Modellfehler
abgewiesen. Jetzt wird die unabhängig bestätigte Zuordnung als validierte UB
übernommen; ihr Wert darf keine gültige globale LB verletzen. Bei Journey mit
vollständiger Bedienung erzwingt auch das unabhängige Passagier-IP U=0.
Die tatsächlich geprüfte Zuordnung wird für spätere Replays gespeichert.

Das ist keine rückwirkende Laufzeitverbesserung: Der alte Fehlversuch bleibt
im Archiv, der neue F0-Versuch hat ein eigenes Verzeichnis und Quellhashes.

## Prüfungen

Die Reihentests prüfen Wiederaufnahme ohne Doppelrechnung, getrennte Seeds,
Weitergabe ausschließlich als Musterinformation, das Ende des K-Scans bei U=0
und die höchstens drei Nachfrage-Zwischenprüfungen. Exporttests prüfen erhaltene
Werte nach Abbruch, unvollständige JSONL-Enden, lokale Pfade, gecachte Rohdaten und
kanonische Boarding-/Alighting-/Waiting-Zeitpunkte.

Ein Produktionsbuild wurde in ein neues temporäres Verzeichnis kopiert und mit
einem einfachen statischen Server geöffnet. Browserprüfung: Profilwahl, passende
All-Stop-/Skip-Stop-Fahrpläne, gemeinsamer Zeitregler, Abspielen/Pausieren und
CSV-Download funktionieren; keine JavaScriptfehler. Auch bei 390 px Breite kein
horizontaler Seitenüberlauf nach der Korrektur langer Nachweisbezeichnungen.
Es lief kein Python-Datenbackend für diesen Test. Der bestehende Hinweis auf
einen JS-Chunk über 500 kB bleibt; die großen Rohartefakte werden separat geladen.

## Messdaten und Freigabe

Gezielte Korrekturläufe: `results/thesis_g500_corrective_checks_20260915`.
Weitere Referenzfortsetzungen und Manifest:
`results/thesis_g500_completion_20260915`.
Ein separater Supervisor begrenzt die Korrekturläufe auf 40 Minuten. Es laufen
keine konkurrierenden Solverjobs. Das ist keine Wiederholung der Hauptmatrix.

Die nachstehenden Tabellen stammen aus den tatsächlichen Endartefakten. Ein offenes κ oder eine ungeklärte Auflösung wird nicht durch eine
technisch fertige Pipeline ersetzt.

### Auflösung und Journey-Kosten

K10, identische Personen und feste Starts je Profil; Kosten in Passagiersekunden.

| Profil | N | AS 15 s | AS 5 s | SS 15 s | SS 5 s | Entscheidung |
|---|---:|---:|---:|---:|---:|---|
| F0 | 510 | 106.837,99983 | 106.925,99983 | 106.837,99983 | 106.925,99983 | Offen: SS-LBs 105.054,61475 / 105.279,69860 lassen noch >1 % Unsicherheit zu |
| F2 | 150 | 41.903,59995 | 41.618,79995 | 36.474,83995 | 36.666,32995 | Bestanden am Kalibrierpunkt |
| F3 | 360 | 100.865,99988 | 100.028,99988 | 90.499,99988 | 90.227,22488 | Bestanden am Kalibrierpunkt |
| F4 | 772 | 103.351,33308 | 102.684,33308 | 103.351,33308 | 102.684,33308 | Bestanden; kein Vorteil bei diesen K10-Punkten |

F3/F4 sind in diesen Läufen optimal. Bei F2/15 s beträgt die native Lücke nur
etwa 0,0027 Passagiersekunden; sie ist keine offene 1-%-Entscheidung mehr.
F0 zeigt gleiche bestätigte AS-/SS-Kosten, beweist aber noch nicht, dass eine
bessere Skip-Stop-Lösung unmöglich ist. Die Übereinstimmung der Incumbents
allein ersetzt keine geklärte Auflösung.

Das freigegebene erste Journey-Rezept enthält F2/F3/F4, K=10/15/23 und
N=151/360/772, jeweils AS und SS. N=151 folgt exakt aus floor(303/2); der
Sensitivitätspunkt mit N150 wird nicht nachträglich umetikettiert.
`journey_ready_manifest.json` enthält 18 mögliche Stufen zu je höchstens
300 Sekunden, somit höchstens 90 Minuten nominelles Stufenbudget. Es wurde
nur per `--build-only` und durch Hashprüfung geprüft, nicht gestartet.

### Kapazitätsreferenzen bei 15 s

| Topologie | F0 | F2 | F3 | F4 |
|---|---|---|---|---|
| T5R | κ ≥ 8.000 | 2.912 ≤ κ < 2.925 | κ ≥ 4.000 | κ ≥ 8.000 |
| T6R | κ ≥ 4.000 | 2.937 ≤ κ < 2.950 | κ ≥ 4.000 | κ ≥ 8.000 |

κ bezeichnet ausschließlich die regelmäßige volle No-Wait-All-Stop-Flotte
mit gemeinsamer optimierter Phase und verschachtelter Nachfrage. Bei F2/5 s
bleibt auf beiden Topologien 2.900 ≤ κ < 3.000. Die vorhandenen Intervalle
reichen daher noch nicht für eine pauschale 1-%-Auflösungsfreigabe. Für F0/F3/F4
steht die entsprechende Kapazitäts-Sensitivität noch aus.

Neue F2-Piloten bei 15 s bedienen **3.204/3.231 Personen vollständig** auf
T5R/K62 beziehungsweise T6R/K75. Damit übertreffen diese zulässigen Pläne sogar
die oberen Grenzen 2.924/2.949 vollständig bedienbarer Personen der jeweiligen
regelmäßigen All-Stop-Referenz. Das beweist einen Vorteil in diesen quantisierten
Vergleichsinstanzen, kein globales Skip-Stop-Optimum und keinen allgemeinen
All-Stop-Bound bei beliebigen Dispatchabständen. Die einfachen komplementären
Muster kamen bereits aus dem Initialsampler. Dieses Ergebnis ist kein Beleg
für eine anspruchsvolle evolutionäre Musterentdeckung.


### Längere Evolutionspiloten und verbleibender Engpass

| Fall | Genau K | N | Bestätigt bedient | Gültige Bewertungen / Bewertungen | Befund |
|---|---:|---:|---:|---:|---|
| T5/F0 | 62 | 8.800 | 3.705 | 38 / 582 | Erster gültiger Plan bei 74,64 s; Verbesserung 3.695→3.705 bei 133,17 s |
| T5/F3 | 62 | 4.400 | 3.644 | 40 / 739 | Gültiger Pilot; kein Vorteil gegenüber bestätigter AS-Bedienung gezeigt |
| T6/F0 | 75 | 4.400 | kein gültiger Plan | 0 / 597 | No-Wait-Konstruktion im Budget ungeklärt; kein Infeasibility-Beweis |

Die 180-s-Budgets enthalten Aufbau und Abschluss; tatsächliche Prozesszeiten
waren jeweils etwa 166–167 s. Für T5/F0 besteht die beste Mischung aus zehn
verschiedenen Zweihaltmustern. Sie bleibt deutlich unter dem bereits vollständig
bedienbaren All-Stop-N=8.000. Das Finden eines gültigen gemischten Fahrplans
allein ist deshalb kein guter Kapazitätsbefund.

Die beiden Korrekturblöcke dauerten 1.669,17 s beziehungsweise 595,32 s.
Alle 21 Einzelversuche endeten ohne Supervisorabbruch. Gemessener maximaler
Prozessbaum-RSS: rund **9,13 GiB**, deutlich unter 32 GiB. In diesen Blöcken
war der Arbeitsspeicher daher kein beobachteter Abbruchgrund. Das garantiert
keine entsprechende Skalierung bei größeren K oder längeren Horizonten.

### Abschließende Freigabematrix

| Gruppen | Aktueller Stand vor Hauptreihen |
|---|---|
| Journey T5/F2, F3, F4 | Freigegebener erster Block; Manifest und Evidenzhashes geprüft, nicht gestartet |
| Journey T5/F0 | Gültige Ergebnisse, aber 15/5-s-Entscheidung wegen offener SS-Solverintervalle ungeklärt |
| Kapazität T5/F0, F2, F3, F4; T6/F2, F3, F4 | Gültige Optimierungspiloten vorhanden; exakte AS-Referenzen und Auflösungsgates offen |
| Kapazität T6/F0 | Zusätzlich noch kein gültiger Optimierungspilot im längeren Test |

Damit sind Reihensteuerung, Darstellung, Auswertung und Wiederaufnahme fertig.
Die vollständige Zwölf-Gruppen-Kampagne ist wissenschaftlich noch nicht pauschal
freigegeben. Ein sofort sinnvoll ausführbarer nächster Block sind die drei
freigegebenen Journey-Gruppen. Kapazität zunächst als ausdrücklich begrenzte
Referenz-/Auflösungsarbeit fortsetzen; T6/F0 nicht mit der Erwartung eines bereits
kalibrierten leistungsfähigen Optimierers als Großserie starten.

Abschließende Codeprüfung: **149 Pythontests bestanden**, darunter die bestehende
EAN-Passagiersuite und der neue negative Ganzzahligkeitsfall, der bei geforderter
Vollbedienung keinen Teilbedienungsplan als Lösung akzeptiert. **25 Frontendtests**
und der Produktionsbuild bestehen. Die Hauptreihe wurde nicht gestartet;
`results/thesis_main_not_started` wurde auch durch die Build-only-Prüfung nicht
angelegt.

Das finale Exportpaket enthält 74 Laufdatensätze; 897 exportierte Dateien
wurden gegen Größe und SHA-256 des Paketmanifests geprüft. Die eingefrorene
Quellkopie `final_sources.zip` liegt im Abschlussverzeichnis. Originalresultate
blieben erhalten; nur generierte Browserkopien wurden für portable Pfade bereinigt.
