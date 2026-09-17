# Vollständiger Musterkatalog und gemeinsame Linienänderungen

## Entscheidung und Vergleich

Am 16.09.2026 auf Nutzerwunsch: Stage-2-Kampagne anhalten, historische Ergebnisse
erhalten, `relevant` statt `od_endpoints_v1` testen. Der Katalog umfasst alle
fest wiederholten Stationsmasken mit mindestens einem nachgefragten OD-Paar.
Keine zeitlich wechselnden Haltemuster, kein Waiting und keine neue Timingengine.

Das bestehende Genom (Muster je Kabine, bevorzugte Dispatchzeiten) bleibt erhalten.
Der optionale Modus `--pattern-search line_groups` verändert Initialisierung und
Variation; Standard `independent` bleibt reproduzierbar.

## Initialisierung

- Ein bis vier Muster je neu erzeugtem Individuum, höchstens K und Kataloggröße.
- Haltzahlen werden gleichwahrscheinlich gezogen; innerhalb einer Haltzahl werden
  bislang nicht abgedeckte OD-Mengen höher gewichtet. Bereits abgedeckte OD-Paare
  behalten Gewicht 0,1. Dies ist nur ein Vorschlagsgewicht, keine Kapazitätsschranke.
- Jede gezogene Linie bekommt mindestens eine Kabine. Die übrigen Kabinen werden
  anhand zufälliger Dirichlet-Anteile verteilt.
- Gruppierte, alternierende und zufällige Dispatchreihenfolgen.
- Kein externer Fahrplan und kein erzwungener All-Stop-Kandidat. All-Stop bleibt
  regulär erreichbar, auch zufällig als einzige Linie.
- Kein globales Limit auf die Zahl verwendeter Linien: Aufteilungen können über
  die anfänglichen vier Linien hinausgehen.

## Variation

50 % bisherige lokale Änderungen (ein Halt, Nachbartausch, Phase, Abstand).
30 % gleichwahrscheinlich aus:

1. Einen Halt einer gesamten Liniengruppe hinzufügen/entfernen.
2. Eine zufällige Teilmenge einer Linie einer anderen vorhandenen Linie zuweisen.
3. Eine Linie aufteilen: echte Teilmenge auf ein neues Muster übertragen;
   Ein-Halt-Nachbarn bevorzugen.
4. Bestehende gekoppelte Blockübernahme vom zweiten Elternteil.

20 % gleichwahrscheinlich: globale Reihenfolge permutieren, Dispatchgene neu
ziehen bei unveränderten Mustern, Neustart mit wenigen Linien.

Die drei Linienoperatoren erhalten K und sämtliche bevorzugten Dispatchzeiten.
Der unveränderte Intervall-Decoder kann diese Zeiten anschließend verschieben.
Ein gescheiterter Aufbau ist weiterhin kein Beweis der Unzulässigkeit.

## Tests

- Reproduzierbarkeit, K, Dispatchraster und Budgetgrenzen.
- Gemeinsame Haltänderung betrifft exakt die gesamte gewählte Linie.
- Umverteilung/Aufteilung erhalten alle bevorzugten Dispatchzeiten.
- Alle Katalogmuster und mehr als vier gleichzeitig verwendete Linien erreichbar.
- Alle neuen Operatoren werden tatsächlich ausgeführt und protokolliert.
- Kleiner freier Suchfall ohne Fahrplanhint mit unabhängig validierter positiver
  Bedienung; CP-SAT-Aufruf im Decoder durch Test verboten.
- Bestehende Evolution, Intervall-Decoder, Auswahl und Kampagnenweitergabe.

## Begrenzter Pilot

T5R/G500/F3/P0, N=7.153, K=62, Freigabeauflösung 15 s, Seed 0.
Je 300 Sekunden einschließlich Aufbau, Population 32, acht Nachkommen,
maximal 32 GiB Prozessbaum-RSS. Sequenziell, kein konkurrierender Solverjob.
Primär Bedienung, Journey-Tie-Break; frühes Ende bei validierter Vollbedienung.

1. `relevant` + `line_groups`.
2. `relevant` + bisherige `independent`-Operatoren.

Der neue Ansatz läuft zuerst, damit sein Verlauf direkt beobachtbar ist. Beide
Läufe haben dasselbe Limit. Der bestehende OD-Endpunktlauf bleibt zusätzliche
historische Vergleichsbasis (3.710 bedient, 97/938 gültige Bewertungen).
Der Vergleich misst das Paket aus Initialisierung und Operatoren; er isoliert
noch nicht deren Einzelwirkung und verwendet nur einen Seed.

Gemeinsame Gesamtdeadline 720 s; keine automatischen weiteren Nachfragepunkte.
LaunchAgents ermöglichen Weiterlauf unabhängig von Codex. Darstellung über das
bestehende Live-Dashboard.

## Auswertung

Erste gültige Lösung und deren Herkunft; Qualität des Initialsamplers gegenüber
späteren Generationen; Bedienungsverlauf und Journey-Tie-Break; gültiger Anteil;
Decoder-/Passagierzeiten; verwendete Haltzahlen und Linienanteile; Operatorherkunft.
Keine Verbesserungsbehauptung allein aufgrund von Vielfalt oder Bewertungsrate.
Ergebnisse: `docs/findings/reservoir_evolution_line_groups_20260916.md`.
