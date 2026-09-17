# Kurzer OIP-Kapazitätsvergleich und Startlösungen aus festen Mustern

Stand: 17.09.2026. Der OIP-EAN-Pilot mit festen Mustern ist für No-Wait und
120 Sekunden End-of-Platform-Waiting implementiert; die Kampagne startet erst
nach den Korrektheitsgates. Der technische Befund steht in
[`oip_fixed_pattern_waiting_implementation_20260917.md`](../findings/oip_fixed_pattern_waiting_implementation_20260917.md).
Dieser Entwurf aktualisiert für den nächsten Piloten den
[bisherigen OIP-Plan](ean_cp_sat_optimized_initial_placement_20260917.md),
insbesondere Nachfragefenster, Nachlauf und Initialisierung.

## 1. Ergänzung der bestehenden Journey-Reihe

- **K25 ergänzen:** T5/G500/P0, F0/F2/F3/F4, jeweils All-Stop und Labelled
  Arc-Flow Skip-Stop: acht zusätzliche Läufe.
- Konstante Nachfrage unverändert: F0=1.553, F2=469, F3=1.105, F4=2.327.
- Wie bei K20/30: gleiche feste Starts innerhalb des Vergleichspaars, No-Wait,
  volle Bedienung, Journey-Time-Ziel, 15-s-Freigaben, höchstens 30 Minuten
  einschließlich Aufbau/Abschluss und 1 % relatives MIP-Gap.
- Kein zusätzliches K31. Historische Ergebnisse und deren Endvertrag bleiben.

## 2. Neuer, kürzerer Betriebsvertrag für Kapazität

- Bereits laufender Betrieb mit **optimierten Anfangspositionen (OIP)**;
  kein Reservoir, keine Rückkehrpflicht, keine anfänglichen Fahrgäste.
- Nachfragefreigaben über **zwei feste All-Stop-Umläufe**, anschließend
  **15 Minuten Abschlusszeit** und **5 Minuten Weiterfahrt**.
- T5/G500: 24,4 + 15 + 5 = **44,4 Minuten** modellierter Betrieb.
  Die Umlaufbasis ist auch für Skip-Stop stets die All-Stop-Umlaufzeit.
- Alle eingesetzten Kabinen fahren bis zum Betriebshorizont weiter.
  Begonnene Bewegungen samt sämtlichen Ressourcen- und Schutzintervallen
  vollständig prüfen; keine Kabine verschwindet an der Zeitgrenze.
- Physik, deterministische OD-Nachfrage und 15-s-Freigabeauflösung beibehalten.
  Bewegungsraster vor dem Einfrieren mit dem neuen OIP-Code abgleichen.
- Zunächst No-Wait. Waiting bis 120 s ist ein gesonderter Vergleich unter
  demselben Fenster; die 5-min-Regel nicht ungeprüft auf 1.200 s übertragen.
- Ziel: zuerst minimale Nichtbedienung, danach bestehende Journey-Time-Kosten
  einschließlich Unserved-Strafe. Keine zusätzliche Flottenstrafe.

**Referenzen neu bestimmen:** Alte Reservoir-Nmax und Nachfragezahlen sind
keine Referenzkapazitäten dieses Vertrags. All-Stop und Skip-Stop erhalten
gleiche Anfangsfreiheit, Flottengrenze, Nachfrage und Zeitgrenzen. Ein regelmäßiger
All-Stop-Zeuge ist kein bewiesenes Optimum über beliebige OIP-All-Stop-Aufstellungen.
110-%-Lasten erst nach Festlegung und Prüfung der neuen Referenzklasse einfrieren.
Ergebnisse betreffen das endliche Fenster, nicht automatisch dauerhafte
Stundenkapazität oder unbegrenzte Fortsetzbarkeit.

## 3. Startlösungen aus festen Mustern

1. Wenige unterschiedliche, nachfragebezogene **Musterbelegungen** vorgeben:
   wiederkehrende STOP-/SKIP-Maske und Kabinenzahl je Muster. Anfangspositionen
   und spätere Ressourcenreihenfolgen bleiben frei. Keine Reservoir-Dispatchfolge.
2. Zunächst vorhandenes OIP-Ereignismodell erweitern: Muster fixieren,
   Passagiervariablen gar nicht bauen, erste zulässige Bewegung suchen und
   unabhängig prüfen. Alle Kabinen der getesteten Belegung sind aktiv;
   K=0 darf den Machbarkeitstest nicht trivial erfüllen.
3. Falls der Aufbau zu teuer ist: spezialisiertes No-Wait-Phasenmodell.
   Eine Phase je Kabine bestimmt die Ereignisse ihrer festen Umlaufvorlage;
   Ressourcenbedingungen, Anfangsbelegungen und Horizontübergänge bleiben exakt.
4. Jede gültige Bewegung mit ganzzahliger Passagierzuordnung bewerten.
   Reine Bewegungszulässigkeit ist noch kein guter Passagier-Incumbent.
5. Gute, unterschiedliche vollständige Zertifikate an das freie OIP-Modell
   übergeben. Dort sind Muster, Anfangsaufstellung und Flotteneinsatz wieder
   Entscheidungen; ein Hint fixiert sie nicht.

## 4. Vorgeschlagenes Screening und Auswahl – noch einzufrieren

- Startvorschlag: vier Musterbelegungen × drei Seeds, je höchstens 60 s für
  Aufbau und Bewegungssuche; Passagierbewertung separat begrenzen und mitmessen.
- Messen: Aufbau, Zeit bis zur ersten validierten Bewegung, Erfolgsanteil,
  INFEASIBLE/UNKNOWN getrennt, Bedienung und Journey Time nach Bewertung.
- Höchstens drei Starts auswählen: bester lexikographischer Wert, bester aus
  anderer Mustermischung, weiterer guter strukturell unterschiedlicher Plan.
- CP-SAT: **ein Hint pro Solve**, nicht pro Worker. Vorschlag: drei kurze
  Fortsetzungen à fünf Minuten, danach beste Lösung länger fortsetzen;
  neue Solves übernehmen keine Suchbäume. Gesamtes Budget noch festlegen.
- Gurobi mit dem einzelnen gewichteten Zielausdruck kann mehrere MIP-Starts
  erhalten; Importadapter ergänzen. Native `setObjectiveN`-Pfade gesondert
  behandeln. Startaufwand und spätere Verbesserungen getrennt ausweisen.
- Vor großen Läufen: Musterfixierung, freie Phasen, Anfangskollisionen,
  vollständige Endintervalle, Zertifikatsübertragung und kleine Modellgleichheit
  prüfen. Bestehenden Supervisor mit maximal zwölf Workern und 32 GiB verwenden.

## 5. Als Nächstes offen: Muster je Szenario

- **F2:** komplementäre OD-Muster als Kontrolle; Mischungsverhältnisse und K.
- **F3:** Drei-/Vierhaltmuster und All-Stop berücksichtigen; reine Zweihaltmuster
  können Sitzplatzwiederverwendung verlieren. Konkrete Kombinationen offen.
- **F0:** breitere Stationsabdeckung und Kombinationen mit All-Stop prüfen;
  konkrete Kombinationen offen.
- F4 bleibt von neuen Hochlastreihen ausgeschlossen; K25-Journey ergänzt die
  bestehende Reihe einschließlich F4. F1 ist keine beschlossene Zusatzreihe.
- Ebenfalls offen: erstes Profil, genaue Flottenbelegungen, Referenzverfahren,
  Nachfragepunkte, Waiting-Vergleich und Gesamtbudget. Keine automatische Freigabe
  einer größeren Kampagne durch diesen Entwurf.

Grundlagen: [bisherige Reihen](../../archive/docs/plans/thesis_study_execution_20260915.md),
[Kapazitätsergebnisse](../../results/thesis_capacity_final_campaign_20260917_summary.json),
[CP-SAT-Hint](https://github.com/google/or-tools/blob/stable/ortools/sat/cp_model.proto),
[Gurobi-MIP-Starts](https://docs.gurobi.com/projects/optimizer/en/current/reference/parameters.html#parameterstartnumber).

## Implementierungsstand: reine Bewegungsmachbarkeit

Der gemeinsame OIP-Runner unterstützt `--movement-only` mit `--backend cp_sat`
und `--backend gurobi`. Beide verwenden ihren bestehenden Bewegungsmodellbau;
Passagierkandidaten, Passagiervariablen und Bedienungsziel entfallen vollständig.
CP-SAT beendet die Suche bei der ersten Lösung; Gurobi löst das vorhandene
Machbarkeitsmodell mit konstantem Ziel. Jeder ausgegebene Fahrplan wird gegen
die unabhängigen Bewegungs-, Anfangs- und Weiterfahrtsprüfer geprüft.

Für aussagekräftiges Screening `--fixed-k K` verwenden: Bei `--k-max K` bleibt
auch die leere Flotte zulässig. Zeitlimit umfasst wie bisher Modellbau und
Suche; ein Abbruch ohne Lösung bedeutet UNKNOWN, nicht INFEASIBLE. Ergebnisse
kennzeichnen `solve_mode=movement_feasibility`; Bedienung, Journey Time und
Optimierungsgap bleiben leer. Physikalische Fingerprints ändern sich nicht.

Aufruf über `benchmarks/run_oip.py` mit den bisherigen Fall-/Zeitparametern,
ergänzt um `--movement-only`. Ohne diesen Schalter bleibt die vollständige
Optimierung unverändert. Aktuell gilt weiterhin der No-Wait-OIP-Vertrag.
Die gezielte Vorgabe der wiederkehrenden Muster und die anschließende
Passagierbewertung dieser Bewegungszertifikate gehören zum nächsten Schritt.
Der Runner importiert im Bewegungsmodus noch keine Checkpoints; die direkte
CP-SAT-Schnittstelle unterstützt bereits Bewegungs-/Flottenhints ohne Passagiere.

### Erster K62-Mustertest auf T5R/G500

Am 17.09.2026 wurden drei wiederkehrende Musterbelegungen mit jeweils 60 s
Gesamtbudget getestet. Anfangspositionen und sämtliche Ereigniszeiten blieben
frei. Die F2-Direktmuster bedienen die OD-Paare S1–S3 und S2–S4.

| Musterbelegung | CP-SAT | Gurobi |
|---|---:|---:|
| 62 × All-Stop | gültig nach 21,50 s Suche | kein Incumbent |
| 31 × {S1,S3}, 31 × {S2,S4} | gültig nach 9,25 s Suche | kein Incumbent |
| 16 × {S1,S3}, 16 × {S2,S4}, 30 × All-Stop | UNKNOWN nach 59,24 s | kein Incumbent |

CP-SAT benötigte jeweils rund 0,92 s Modellbau. Gurobi baute für jede Variante
1.517.605 Variablen und 3.387.607 Constraints auf; 56,7–57,8 s entfielen auf
den Modellbau und nur 2,1–3,3 s auf die Suche. Keines der negativen Ergebnisse
ist ein Unzulässigkeitsnachweis. Die exportierten CP-SAT-Pläne wurden unabhängig
validiert und ihre Haltefolgen entsprechen exakt den vorgegebenen Masken.

Der Befund spricht für CP-SAT als Machbarkeitsstufe. Als Nächstes sind die beiden
gültigen Bewegungen unter der eingefrorenen F2-Nachfrage ganzzahlig zu bewerten.
Erst diese Bewertung zeigt, ob das aggressive Direktmuster einen brauchbaren
Passagier-Incumbent liefert. Für Gurobi müsste die Musterfixierung schon die
Erzeugung der Paarrestriktionen reduzieren; nachträgliche Gleichungen helfen
zwar mathematisch, sparen aber den dominanten Modellbau nicht ein.
