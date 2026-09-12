# Reservoir-Linienmodell: Implementierungs- und erster Suchbefund

Stand: 12.09.2026. Maßgeblicher Plan:
[`reservoir_line_dispatch_models_20260912.md`](../plans/reservoir_line_dispatch_models_20260912.md).

## Implementierter Stand

Der neue Pfad modelliert vollständige, wiederholte Haltemuster als
No-Wait-Einsatztemplates. CP-SAT entscheidet nativ über optionale Kabinen,
Template beziehungsweise Rundenzahl, streng geordnete Dispatchzeiten und
ganzzahlige Beförderungsmengen. Der erste Dispatch liegt bei null; alle
Dispatches liegen in einem expliziten gemeinsamen Fenster. Einstieg wird an
der tatsächlichen Plattformausfahrt, Ausstieg an der Plattformankunft und jede
Freigabe in Integer-Mikrosekunden gekoppelt. Exportierte Lösungen durchlaufen
den unveränderten unabhängigen Reservoirvalidator.

Zwei physikalisch äquivalente Ressourcenkodierungen sind implementiert:

- `dispatch_domains`: vorab berechnete erlaubte Intervalle für jeden
  Templatepaar-Dispatchabstand;
- `intervals`: optionale Intervalle mit Start `dispatch + offset` und natives
  `NoOverlap` je Ressource sowie je synthetischer Zustandszeit-Ressource.

`optimistic_service` bleibt als klar bezeichnete Ablation verfügbar. Dessen
Ride-Mengen werden nicht als gültige Bedienung exportiert. Waiting aus einer
geladenen `bounded_wait`-Domäne wird in diesem V1 ausdrücklich auf null
fixiert; Bounds gelten nur für dieses eingeschränkte Linienmodell.
Der Runner kann mit `--fix-reference-movement` ausschließlich Bewegung und
Dispatch eines geprüften Linienplans fixieren und dessen ganzzahlige
Passagierzuordnung exakt nachoptimieren. Dieser Modus besitzt den eigenen
Proof-Scope `FIXED_LINE_MOVEMENT`.

## Korrektheit und Modellgröße

Die neuen Tests prüfen ganzzahlige Intervallkomplemente, direkte
Ressourcenüberlappung gegen vorberechnete Delta-Domains, beide
Ressourcenkodierungen, optionale Flotte, exakte Freigaben, optimistische
Ablation, Checkpointhints und unabhängige Zertifikatsvalidierung. Zusammen mit
den bestehenden Reservoir-CP-SAT-Tests bestanden zunächst 31 Tests; weitere
Runner- und Timeoutkontrollen wurden danach ergänzt.

Auf R2, T=300 s, Kmax=50:

| Katalog / Encoding | Variablen | Constraints | native Intervalle | Binärproto | Build |
|---|---:|---:|---:|---:|---:|
| 3 Muster / Delta-Domains | 100.950 | 913.585 | 0 | nicht erneut exportiert | 7,4 s |
| 3 Muster / Intervalle | 100.950 | 393.205 | 72.500 | 26,3 MB | 2,4 s |
| 14 Muster / Intervalle | 400.100 | 1.613.155 | 336.750 | 111,5 MB | 11,9 s |

Die Intervallkodierung ist damit für den großen Katalog klar kompakter. Das
Delta-Encoding wird vor mehr als zwei Millionen möglichen
Slot-/Templatepaarzeilen abgewiesen und verweist auf die exakte
Intervallalternative.

## Erste R2-Ergebnisse

Quelle ist der unveränderte R2-Fall mit 3.074 Personen. Der historische Plan
bediente 2.496 Personen mit 38 Kabinen. Er ist kein direkter Hint für den neuen
Vertrag, weil sein erster Dispatch bei 29,090910 s statt null liegt.

Reine Timingtests mit dem kleinen Katalog:

| Fall | Ergebnis |
|---|---|
| K=8, Linienwahl frei | zulässig in 1,05 s |
| K=16, Linienwahl frei | zulässig in 3,90 s |
| K=24, Linienwahl frei | `UNKNOWN` nach 20 s |
| K=32, feste alternierende BD/CE-Sequenz | zulässig in 1,70 s |

Ein ungesäter exakter Kmax=50-Lauf mit Presolve fand in 30 s keine Lösung. Ein
K16-Bewegungshint änderte das nicht: CP-SAT blieb rund 31 s vollständig im
Presolve. Ohne Presolve wurde derselbe Hint nach 3,0 s übernommen und die
Bedienung bis Sekunde 32,6 auf 1.414 gesteigert; eine 17. Kabine wurde dabei
nativ aktiviert.

Der anschließende freie Kmax=50-Lauf mit dem gültigen K32-BD/CE-Bewegungshint
erreichte in 60 s:

- **2.682 bediente Personen, U=392**;
- **186 Personen mehr als die historische R2-Referenz**;
- 32 eingesetzte Kabinen, davon 16 mit BD und 16 mit CE;
- 31 Einsätze mit sieben Runden, ein Einsatz mit acht Runden;
- Dispatchspanne 0 bis 235,165524 s;
- letzte Verbesserung auf 2.682 bei rund 47,6 s Gesamtlaufzeit des Optimizers.

Das Ergebnis liegt in
`benchmarks/output/reservoir_lines_20260912_exact_r2_k50_small_seedk32bdce_nopresolve_v1/`.
`best.json` wurde unabhängig geprüft. Der Lauf beweist kein globales
Skip-Stop-Optimum und schließt den Gap nicht; die native Relaxationsschranke
blieb für Unserved bei null. Er übertrifft auch noch nicht den abgesicherten
globalen All-Stop-Vergleich: Dafür wäre im aktuellen R2-Nachweis U≤124 nötig.

## Konsequenz

Das Linienmodell besteht den Incumbent-Test deutlich: Die menschlich plausible
komplementäre Musterstruktur lässt sich in Sekunden physikalisch timen, und
der integrierte Solver verbessert den gültigen Passagierplan weiter. Das
Problem liegt nun nicht mehr beim Finden irgendeines Fahrplans, sondern bei
der freien Mustersuche ohne Startstruktur und bei der globalen Schranke.

Der fünfminütige Lauf unten prüft, ob dieser Fortschritt anhält. Der erweiterte
Katalog und Waiting bleiben getrennte spätere Prüfungen; die jetzigen
No-Wait-Bounds dürfen nicht auf eine Waiting-Erweiterung übertragen werden.

## Fünfminuten-Bestätigung und All-Stop-Nachweis

Der geplante längere Lauf mit dem unabhängig bestätigten S=2.682-Checkpoint als
Hint ist abgeschlossen. Er fand bis zum Ende weiter bessere Incumbents:

- **3.036 bedient, 38 unbedient**;
- 36 Kabinen, davon 18 BD und 18 CE;
- 33 Einsätze mit sieben Runden, zwei mit sechs und einer mit acht Runden;
- Dispatchspanne 0 bis 263,990200 s;
- letzte Verbesserung von 3.031 auf 3.036 bei rund 293,35 s;
- 10,53 GB gemessene Peak-RSS, Solverstatus `FEASIBLE` nach Zeitlimit;
- keine brauchbare neue globale Schranke des Linienmodells.

Der Checkpoint liegt in
`benchmarks/output/reservoir_lines_20260912_exact_r2_k50_small_300s_s0_v1/best.json`
und wurde nach Abschluss erneut mit dem ursprünglichen unabhängigen Validator
geprüft: S=3.036, U=38, Peak-Flotte 36.

Damit ist das Thesis-Vergleichskriterium erfüllt. Der frühere globale
All-Stop-Kapazitätsbound auf genau dieser unveränderten R2-Domäne beweist
`U_AS* >= 125`, also höchstens 2.949 bediente Personen. Der neue gültige Plan
erfüllt

\[
U_{SS}=38 < 125 \le U_{AS}^*,
\]

und bedient somit mindestens 87 Personen mehr als jeder zulässige
All-Stop-Plan dieser Domäne. Dieser Schluss benötigt kein globales
Skip-Stop-Optimum. Das Linienmodell selbst bleibt ein eingeschränkter
No-Wait-Suchraum; sein Plan ist dennoch ein gültiges Element der vollständigen
Skip-Stop-Domäne mit erlaubtem Waiting, weil Waiting=0 dort zulässig ist.

Der nächste Lauf soll diese Incumbentqualität mit Seed 1 reproduzieren. Für
die Aussage `U_SS < LB(U_AS*)` genügt bereits der unabhängig validierte Zeuge;
die Wiederholung bewertet Robustheit und Laufzeit, nicht die logische
Gültigkeit des vorhandenen Nachweises.

## Seed-1-Wiederholung: vollständige Bedienung

Die auf dem sauberen Commit `4f4ab9c` ausgeführte Seed-1-Wiederholung ist
abgeschlossen. Der Runner bestätigte einen unveränderten Arbeitsbaum und nahm
den U=38-Hint nach 3,14 s an. Danach folgten weitere echte Verbesserungen:

- U=30 bei 34,39 s mit 37 Kabinen;
- U=22 bei 87,58 s mit 38 Kabinen;
- **U=0, S=3.074 bei 89,69 s mit 38 Kabinen**.

Der finale Checkpoint liegt in
`benchmarks/output/reservoir_lines_20260912_exact_r2_k50_small_180s_s1_v1/best.json`.
Er wurde nach dem Solverlauf erneut unabhängig bestätigt: sämtliche 36
Nachfragegruppen sind vollständig bedient, alle Ressourcen- und
Zustandsheadways gelten, alle Kabinen kehren rechtzeitig zurück und die
Peak-Flotte ist 38. Der Plan verwendet 19 BD- und 19 CE-Linien. 34 Einsätze
fahren sieben Runden, zwei sechs Runden, einer acht und einer drei; die
Dispatchspanne reicht von 0 bis 275,610270 s. Peak-RSS war 9,85 GB.

Der Solverstatus bleibt wegen der sekundären Minimierung der Flottenzahl nach
180 s `FEASIBLE`. Für das primäre Bedienungsziel ist der Wert trotzdem
offensichtlich optimal: Bei Gesamtnachfrage 3.074 kann kein Plan mehr als
3.074 Personen bedienen. Die minimal notwendige Flottenzahl ist nicht
bewiesen.

Der endgültige Vergleich lautet damit:

\[
S_{SS}=3.074 > 2.949 \ge S_{AS}^*,
\]

also bedient der Skip-Stop-Zeuge mindestens **125 Personen mehr** als jeder
All-Stop-Plan in der vollständigen Single-Use-Max50-R2-Domäne. Dies beantwortet
die Kapazitätsfrage für R2 ohne Waiting-Nutzung und ohne einen globalen
Skip-Stop-Gap schließen zu müssen.
