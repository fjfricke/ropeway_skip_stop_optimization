# Evolution: konfliktfreie Dispatchintervalle und begrenzte Waiting-Reparatur

Stand: 2026-09-14. Autorisiert im Chat nach den Fixed-Dispatch-Waiting-Tests.

## Zweck

Die äußere pymoo-Evolution behält K, geordnete Stationsmasken und Zeitgene.
Ein optionaler Decoder legt Kabinen nacheinander in die vollständige Menge
zulässiger No-Wait-Dispatchintervalle. Scheitert diese Einfügung, darf ein
begrenzter CP-SAT-Aufruf den vollständig konstruierten Vorschlag mit Exit-Waiting
reparieren. Alle dann gewählten Dispatchzeiten und vollständigen Routen bleiben
fix. Auch früher eingefügte Kabinen dürfen warten; deshalb prüft CP-SAT stets den
gesamten Vorschlag. Es werden keine Kabinen still entfernt.

Bestehender `legacy`-Decoder und Solverstandards bleiben unverändert.

## Darstellung und Reichweite

- Bisherige Integer-Gene sind im neuen Modus **bevorzugte** Dispatchzeiten.
  Liegt der bevorzugte Tick in der zulässigen Menge, bleibt er unverändert.
  Andernfalls wird der nächste zulässige Tick gewählt; nach dem letzten Intervall
  beginnt die Auswahl beim ersten. Das ist eine bewusst einfache, nicht uniforme
  Auswahlregel. Originalgene und tatsächliche Dispatchzeiten werden getrennt gespeichert.
- K, Muster und Reihenfolge werden nicht geändert. Für noch nicht eingefügte
  Kabinen bleibt zumindest ihr notwendiger Portabstand im Dispatchfenster frei.
- Für bewegte Intervalle `[d+a,d+b)` und vorhandene `[s,e)` sind genau die
  Integer-Dispatches `[s-b+1,e-a-1]` verboten. Vereinigung über **alle** Ressourcen,
  Zustandsereignisse, Portdurchfahrten und Rückkehrereignisse aller früheren Kabinen.
  Schutzzeiten bleiben vollständig. Kein Mikrosekundenraster wird aufgezählt.
- Die zeitabhängige Rundenzahl kommt aus den bestehenden Lebenszyklus-Templates.
  Ihre Dispatchbereiche werden getrennt behandelt, anschließend vereinigt.
- Jeder bisher gültige No-Wait-Fahrplan ist ein Fixpunkt des Decoders. Das beweist
  Darstellbarkeit, nicht vollständige Erkundung oder einen Optimalitätsanspruch.
- Ein gescheiterter Präfix kann durch frühere andere Entscheidungen vermeidbar
  sein. `CONSTRUCTION_FAILED` ist daher kein globaler Unzulässigkeitsbeweis.
  Die Zahl noch nicht platzierter Kabinen dient nur als Suchsignal und wird
  ausdrücklich nicht als physikalische Konfliktzahl ausgegeben.

## Waiting-Fallback

1. Zunächst vollständige No-Wait-Intervalle prüfen.
2. Fehlen sie, nur notwendige Anfangsbedingungen für eine Waiting-Reparatur
   anwenden. Vor dem ersten freigegebenen STOP mit positiver Waitingkapazität
   bleiben Zeitpunkte fest. Am STOP selbst bleiben Nutzungen mit festem Eintritt
   und lediglich verlängerbarer Räumung in jeder Ausführung enthalten.
3. Den Dispatch gegen diese unvermeidlichen Belegungen aller früheren Kabinen
   wählen. Die Freigabephase wird über exakte Intervallgrenzen berücksichtigt.
4. Alle übrigen Kabinen ebenfalls konstruieren. Ein unvollständiger Vorschlag
   wird nicht als kleinerer gültiger Fahrplan ausgegeben.
5. Erst den vollständigen Kandidaten im vorhandenen Reservoir-Bewegungsmodell
   reparieren: K, Dispatches, Routen und Rundenzahl fix; Waiting aller Kabinen frei.
   Der gesamte Fahrplan erhält neue Reservierungen und wird unabhängig validiert.
6. Auf dem ersten gültigen Timing ganzzahlige Passagiere optimieren. Dieses Timing
   ist nicht als bestes Passenger-Timing bewiesen. Keine globale Suchschranke.

Unveränderte Rückkehrregel: erste vollständige Rückkehr am/nach Serviceende;
vorherige Umlaufrückkehr davor. Waiting, das eigentlich eine andere Rundenzahl
erfordern würde, liegt außerhalb dieser Reparatur. Insbesondere deckt der
Fallback **nicht alle Waiting-Fahrpläne** ab.

`UNKNOWN`, Aufbauabbruch, erschöpftes Reparaturbudget und bewiesenes
`INFEASIBLE_FIXED_CANDIDATE` bleiben getrennt. Cachewerte sind gemessene Ergebnisse
dieses Budgets; ungeklärte Kandidaten werden nicht automatisch erneut länger geprüft.

## Einstellungen und Messung

- `--dispatch-decoder legacy|intervals`, Standard `legacy`.
- `--waiting-repair-seconds 5` aktiviert Reparatur; Standard 0.
- **Aktualisierung nach Nutzerentscheidung:** Jeder neue reparaturbedürftige
  Kandidat erhält sein eigenes Budget (im Pilot 5 s), auch spät im Lauf.
  Es gibt standardmäßig **keine kumulierte Reparaturquote**. Nur die verbleibende
  gesamte Laufzeit begrenzt den nächsten Versuch. Ein bereits bewerteter identischer
  Fahrplan verwendet weiterhin den Cache; es ist keine automatische Wiederholung
  identischer `UNKNOWN`-Versuche beabsichtigt.
- `--waiting-budget-fraction 0.2` bleibt ausschließlich als ausdrücklich gewählte
  optionale Begrenzung zur Reproduktion alter Vergleiche erhalten, nicht als Standard.
  Reparaturzeit umfasst Aufbau und anschließende Passagierbewertung.
  Laufzeitlimits sind kooperativ; gemessene Überziehungen werden ausgewiesen,
  der äußere Supervisor begrenzt den gesamten Prozess.
- `--earliest-wait-seconds 0`: explizite physikalische Falländerung für Warmup.
  Kein versteckter globaler Standardwechsel.
- Zwölf Worker nur für CP-SAT-Reparaturen; Decoder und Gurobi-Passagier-IP jeweils
  ein Thread. Ein Suchprozess gleichzeitig, maximal 32 GiB Prozessbaum-RSS.
- Genotyp- und Fahrplancache getrennt; gleiche dekodierte Fahrpläne teilen ihre
  Bewertung. Doppelte Phänotypen können zunächst noch Populationsplätze belegen;
  eine Veränderung der Bibliotheks-Duplikatbehandlung ist nicht Teil dieses Tests.
- Speichern: tatsächliche Dispatches, Masken, K, Waiting, getrennte gemischte
  Fahrplanfronten, Decoder- und Reparaturzeiten, Reparaturstatus, Cachetreffer,
  unabhängige Bedienung und Verlauf. Übernommene Referenzen sind keine Verbesserung.

## Tests vor Performance

1. Alle gültigen kleinen No-Wait-Pläne bleiben unverändert darstellbar.
2. Dispatchintervalle gegen unabhängigen Decoder vollständig aufzählen.
3. Exakte Tickgrenzen, Grid-Schritt, zulässige Übergabe bei Berührung.
4. Späte Ressourcenbelegung und mehrere bereits eingefügte Kabinen.
5. Gescheiterter Präfix bei zugleich anders ausführbarer gleicher Musterfolge.
6. Kein Timing-Solver im No-Wait-Decoder.
7. Kleine erfolgreiche Waiting-Reparatur bei identischen Abfahrten und Routen.
8. Unheilbare Anfangskollision vor CP-SAT ablehnen; Waitingfreigabe beachten.
9. Cache, unbekannte Ergebnisse, Budget- und Timeoutbehandlung.
10. Historischer All-Stop-Plan bleibt Fixpunkt mit identischem Passagierwert;
    historische kollidierende Vorschläge werden erneut konstruiert, nicht als
    unveränderte Dispatch-Replays ausgegeben.

## Begrenzter erster Verlaufstest

Dieser bereits gestartete Vergleich ist eingefroren und verwendet noch die
damalige 20-%-Grenze. Er wird nicht rückwirkend auf die neue Budgetregel geändert.
Künftige reguläre Läufe lassen `--waiting-budget-fraction` weg; für eine gezielte
Wiederholung des alten Dreifachvergleichs bleibt dessen Runner unverändert.

R2: historische fünf Stationen, 3.074 Personen, Kapazität 8, max50, Dispatch 0–300 s,
Serviceende 1.500 s, Betriebsende 1.800 s, aktueller Portschutz. Waitingfreigabe
explizit 0 s in allen drei Domänen; No-Wait-Verfahren benutzen weiterhin kein Waiting.

Drei sequenzielle GA-Läufe mit Seed 0, `mixed_global`, Population 32, acht
Nachkommen, jeweils 300 s einschließlich Aufbau/Abschluss:

1. Legacy-Dispatchgene, ohne Waiting.
2. Intervall-Decoder, ohne Waiting.
3. Intervall-Decoder mit maximal 5 s Reparatur je Kandidat und 20 % Gesamtanteil.

Ohne importierte gute Startlösung; der geprüfte All-Stop-Wert wird separat
geführt. Identischer Initialsampler, keine weiteren Solverparameteränderungen.
Quellen und Instanzen vorab einfrieren. Gesamtdeadline **16 Minuten**, keine
automatische Ausweitung oder zusätzlichen Seeds.

Auswertung bei 30/60/120/180/300 s: beste gültige Bedienung, beste gemischte
Bedienung, größtes gültiges gemischtes K, letzter Fortschritt, gültiger Anteil,
Anzahl erfolgreicher Reparaturen und ihr Zeitbedarf. Ein Seed ist diagnostisch,
kein Beweis statistischer Überlegenheit. Ein anschließender längerer Lauf oder
ein anderer Decoder benötigt einen begründeten Folgeschritt.

## Wissenschaftlicher Bezug

Ausgangspunkte und Originalquellen sind im
[Algorithmusreview](../research/reservoir_line_evolution_algorithm_review_20260914.md)
aufgeführt, insbesondere Bürgy/Gröflin zur No-Wait-Job-Insertion
([Preprint](https://reinhardbuergy.ch/research/pdf/buergy_groeflin12_oji_nwjs_preprint.pdf),
[DOI](https://doi.org/10.1007/s10878-012-9466-y)). Der obige Decoder ist eine eigene
Seilbahnübertragung mit getesteter Intervallarithmetik; Ergebnisse des Papers
werden nicht als Laufzeit- oder Vollständigkeitsgarantie für diesen Piloten übernommen.
