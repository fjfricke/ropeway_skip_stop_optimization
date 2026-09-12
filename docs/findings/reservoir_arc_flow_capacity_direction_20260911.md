# Reservoir-Arc-Flow/DDD für einen belastbaren Kapazitätsvergleich

Stand: 11.09.2026. Code- und Literaturprüfung; kein neuer Solverlauf und keine
Änderung bestehender Modelle. Empfehlung für die nächste begrenzte Entwicklung.

## Forschungsziel und benötigter Nachweis

Ziel ist mehr bedienbare Nachfrage als All-Stop, bei gleichem physikalischem
System, Nachfrageprofil, Waitingvertrag, Flottenmaximum und Reservoirzugang.
Eine zusätzliche Kabine allein und niedrigere Reisezeitkosten beantworten
diese Frage nicht.

Für einen festen Nachfrageumfang D sei U die Zahl unbedienter Personen.
Ein unabhängig gültiger Skip-Stop-Plan und eine globale All-Stop-Untergrenze
reichen für einen strengen Vergleich aus:

\[
 U_{SS}^{\mathrm{Plan}} < LB(U_{AS}^{*})
 \quad\Longrightarrow\quad
 D-U_{SS}^{\mathrm{Plan}} > \max S_{AS}.
\]

Das Skip-Stop-Optimum muss dafür nicht bewiesen sein. Auch ein sicher
eingeschränkter Skip-Stop-Suchraum darf einen solchen Fahrplan liefern.
Sein MIP-Bound gilt dann nur für den eingeschränkten Suchraum. Umgekehrt darf
eine eingeschränkte All-Stop-Zeitliste keine globale Kapazitätsobergrenze liefern.

Für maximale vollständig bedienbare Nachfrage muss der Nachfragegenerator
verschachtelt sein. Ein vollständig bedienbarer SS-Prefix mit N Personen und
ein bewiesen nicht vollständig bedienbarer AS-Prefix mit M Personen liefern
`kappa_SS >= N`, `kappa_AS <= M-1`. Eine höhere Zahl ausgewählter bedienter
Personen bei teilweiser Bedienung beweist nicht dieselbe Aussage über die
vollständige Bedienbarkeit eines vorgegebenen OD-Profils.

Ein All-Stop-Referenzfahrplan bleibt eine nützliche schwächere Vergleichsstufe.
Sein optimal gelöstes Passagierproblem ist aber nicht automatisch das Optimum
über alle All-Stop-Fahrpläne. Die alten 2.561 Personen gelten nur für den
dokumentierten festen Fünf-Stationen-Fahrplan, nicht für das Reservoir.

## Konkrete Codebefunde

1. **Max-K ist vorhanden.** In
   [`reservoir_arc_flow.py`](../../src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_arc_flow.py)
   bildet `_DddReservoirMovementMasterBuilder` anonyme binäre Bewegungsflüsse,
   Knotenerhaltung, eindeutige Zustandsbelegung, Ressourcenkliquen und
   `sum(dispatch) == sum(recovery) <= available_fleet_count` ab.
2. **Passagiere sind integriert und ganzzahlig.**
   [`reservoir_passenger.py`](../../src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_passenger.py)
   enthält Nachfragebilanzen, Ein-/Ausstiegsaktivierung und gemeinsame
   Abschnittskapazität. Direkte Wege enden am ersten Zielbesuch. Im exakten
   Zustandszeitnetz verhindert die Knotenbelegung mit höchstens einer Kabine
   eine beliebige Umverteilung zwischen mehreren Kabinen am selben Knoten.
   Das ist nicht auf eine grobe Zeit-Zelle mit mehreren Kabinen übertragbar.
3. **Waiting ist bisher eine vollständige Bewegungskopie.**
   [`anonymous_reservoir_network.py`](../../src/ropeway_skip_stop_optimization/optimization/ddd/anonymous_reservoir_network.py)
   expandiert jeden erreichbaren Knoten über Route und expliziten Waitingwert.
   `target_tick = source_tick + duration_tick + wait_tick`. Diese Expansion
   und die anschließenden Passagierkopien sind der relevante Größenengpass.
4. **Die alte Reservoirsemantik ist enger.** Dispatch nur vor Ende des Warmups,
   Rückkehr erst nach Ende des Passagierbetriebs; der Validator erzwingt das
   ebenfalls. Das heutige CP-Reservoir erlaubt andere Dispatch-/Rückkehrzeiten.
   Diese Unterschiede müssen vor einem Vergleich vereinheitlicht werden.
5. **Das aktuelle Reservoir-DDD ist ein Reisezeit-LP-Boundpfad.**
   [`bound_model.py`](../../src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_hybrid/bound_model.py)
   erzeugt kontinuierliche Variablen und Reisezeitkosten; es ist kein fertiger
   ganzzahliger Kapazitätsoptimizer. Einfach nur `x` ganzzahlig zu machen
   repariert weder die gemittelten Zeiten noch künstliche Flussmischung.
6. **Die aktuelle Verfeinerung ist nicht ressourcenspezifisch.**
   [`refinement.py`](../../src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_hybrid/refinement.py)
   halbiert bis zu drei Zellen nach Passagierfluss mal Zellbreite, verwendet
   `movement_capacity` und beendet die Schleife unter anderem bei LP-Timeout
   oder Stagnation. Das ist keine vollständige konfliktgetriebene DDD-Schleife
   mit globaler Konvergenzgarantie.

Die ältere Grundidee ist bereits im
[`DDD-Plan`](../plans/dynamic_discretization_cabin_passenger.md) beschrieben,
einschließlich Holding und Speicherkapazitätsrisiken. Sie wird hier nicht als
neu entdecktes Verfahren ausgegeben. Neu wäre der gezielte Einsatz für den
Kapazitätsvergleich und der nachfolgend abgegrenzte Ausbau des Reservoirpfads.

## Empfohlener Ausbau

### A. Gemeinsamer Kapazitätsvertrag

Ein gemeinsames vorbereites Problem mit `all_stop`/`skip_stop`, Max50,
unverändertem Waiting und zunächst einmaligem Reservoireinsatz. Quelle ist
der heutige physikalische CP-Vertrag, nicht das alte Dispatchraster.
Bestehende Zertifikate werden übernommen und erneut geprüft. Alte Runner und
ihre Standards bleiben unverändert.

Zielfunktion zunächst ausschließlich `unserved`. Kein sekundärer
Reisezeit-Solve im Pilotbudget. Reisezeit bleibt eine geprüfte Kennzahl.
Zusätzlich eine feste vollständige Bedienungsanforderung für Nachfrageprefixe.

### B. Kompakter exakter Primalgraph als erster Umsetzungstest

STOP in physikalische Phasen zerlegen: Anfahrt/Service, legaler Exit-Warteort,
Ausfahrt/Merge und Weiterfahrt. SKIP bleibt eine eigene Alternative.
Auf einer gegebenen Menge exakter Exitzeitpunkte können aufeinanderfolgende
Holding-Arcs die bisherige Wiederholung ganzer Bewegungen für viele Wartewerte
reduzieren. Die lokale Zahl der Holding-Verbindungen kann linear statt
quadratisch in der Zahl der Exitzeitpunkte sein; das ist noch keine Schranke
für die Größe des gesamten zulässigen Ropeway-Netzes.

Pflichtbedingungen für diese Faktorisierung:

- Ressourceneintritt und geschütztes Ende einschließlich Waiting werden exakt
  aus den bestehenden affinen Ressourcenbeschreibungen übernommen.
- Waiting darf nur am erlaubten Exit beginnen, mit unveränderter Freigabephase.
- Die maximale Wartezeit gilt für den gesamten Besuch, nicht einzeln je
  Holding-Arc. Eine schlichte Kette mit lokalen Grenzen wäre falsch. Falls die
  Zusammenführung Herkunfts-/Altersinformation verliert, müssen Zustandsklassen
  oder zusätzliche exakte Bedingungen sie erhalten; ihr Größenpreis ist zu messen.
- Zielausstieg vor Ziel-Waiting, Einstiegsfreigabe am tatsächlichen
  Plattformausstieg nach Waiting, Aussteigen vor Einsteigen.
- Passagiere bleiben auf ihrem direkten Kabinenpfad; keine neue Runde,
  kein künstlicher Umstieg zwischen anonymen Flüssen.
- Horizontpräsenz, Räumung nach dem Horizont und Rückkehr bleiben unverändert.

Zunächst nur ausgewählte **exakte** Zeiten aufnehmen, einschließlich aller
Zeiten des gültigen Seeds. Das ist eine deklarierte Einschränkung für die
Fahrplansuche, kein global vollständiges Zeitraster. Ein solveroptimaler Wert
dieses Netzes ist nicht automatisch ein globales Kapazitätsmaximum.
Gurobi sucht darin Bewegungen und Passagiere gemeinsam. Es wird kein eigener
greedy/LNS-Fahrplancontroller ergänzt.

Akzeptanz zuerst über vollständig enumerierbare Bewegungs-/Waitingfälle und
Replays bekannter Gesamtpläne. Ein bloßes kleineres Netz reicht nicht: Es muss
auch neue gültige Pläne erzeugen können und die unabhängige Prüfung bestehen.
Wenn die zur Exaktheit nötigen Zustandsklassen den Größenvorteil aufheben,
endet diese Hypothese vor dem großen Ausbau.

### C. All-Stop-Nachweis parallel zum Primalpfad konzeptionell getrennt

Für den vollständig freien All-Stop-Vertrag eine gültige optimistische
Kapazitätsrelaxation aus dem vorhandenen Zeitbereichs-/Ressourcen-Bausteinen
ableiten. Das Ziel wird `min sum(unserved)`; alle echten All-Stop-Pläne müssen
projizierbar sein. LP/DDD-Bounds werden konservativ mit ihren numerischen
Toleranzen zertifiziert. Ein positiver Unserved-Bound beweist eine Begrenzung,
ein Bound null oder ein Timeout beweist keine volle Bedienbarkeit.

Wegen der festgelegten STOP-Routen ist dieses Vergleichsproblem strukturell
einfacher als freies SS; eine schnell enge Schranke ist trotzdem unbewiesen.
Waiting oder Dispatch dürfen nicht ohne Dominanzbeweis für All-Stop reduziert
werden. Insbesondere ist 38 im Reservoir keine bereits bewiesene universelle
maximale Einsatzzahl.

### D. Erst danach vollständige adaptive Zeitdarstellung

Intervalle stations-/ressourcenbezogen verfeinern, statt für jede Änderung
globale Zeitgrenzen zu vervielfachen. Exakte Konflikte sollen bestimmen, welche
Region getrennt wird. Alte gültige Ressourcenbedingungen müssen erhalten
bleiben; eine engere Partition allein impliziert nicht automatisch einen
stärkeren Bound. Routenspezifische Partitionen sind eine mögliche zweite
Größenverbesserung, aber bei zwei ausgehenden Routen vermutlich weniger wichtig
als bei den hochgradigen Netzen der zugehörigen Veröffentlichung.

Das ist eine Adaption eines veröffentlichten DDD-Verfahrens. Der äußere
Refinement-Mechanismus wäre problembezogener eigener Code; es wäre falsch,
dies als unveränderte Nutzung eines fertigen Ropeway-Solvers zu bezeichnen.
Die kombinatorische Optimierung der jeweiligen Modelle übernimmt Gurobi.
Für den ersten Überlegenheitsnachweis kann dieser vollständige SS-Ausbau
entfallen, falls ein gültiger Primalplan bereits die globale AS-Grenze schlägt.

## Welche Nachfrage zuerst?

Die geplanten Familien aus
[`demand_case_families.md`](../reference/demand_case_families.md) beibehalten:

- F2 komplementäre OD-Gruppen zuerst: unterschiedliche vermeidbare
  Stationsressourcen sind eine konkrete Hypothese für mehr Durchsatz.
- F0 diffuse Nachfrage als neutraler Vergleich; nicht verschwinden lassen,
  wenn F2 bessere Ergebnisse liefert.
- F4 lokale Nachfrage als Kontrolle; später F5 gemischt lokal/Express.

Zuerst P0 stationär zur Untersuchung nachhaltigen Durchsatzes, P4 Batch als
separater Horizont-/Startbedingungsvergleich. Ein gemeinsamer Pflichtterminal
kann jeden Kapazitätsgewinn begrenzen; deshalb ist der geplante Sechs-Stationen-
Doppelring besonders interessant. Seine beiden Richtungen müssen dieselbe
Nachfrage teilen. Die aktuelle einzelne gerichtete Reservoir-Domäne ist noch
kein vollständiger Doppelring-Adapter.

Nachfrageintensität anhand einer neuen passenden AS-Kalibrierung bestimmen,
zunächst knapp über der Grenze, anschließend etwa +5 %, +10 % und +20 % als
Untersuchungspunkte. Diese Prozentsätze sind keine prognostizierten Gewinne.
Für alle Vergleiche gleiche Profile und verschachtelte ganzzahlige Nachfrage.

Pilotgates: winzige exakte Kontrollen; bekannter Fünf-Stationen-Reservoirfall
als Regression; eine begrenzte Kapazitätsprobe mit freiem Max50; anschließend
Sechs-Stationen-Topologieadapter und die vorab festgelegte Profilmatrix.
Bei unverändert schlechtem Primalwert und schwachem AS-Bound nicht einfach die
Laufzeit vervielfachen, sondern den gemessenen Engpass als negatives Ergebnis
festhalten.

## Literatur und Übertragungsgrenzen

Die folgenden Quellen wurden über veröffentlichte Abstracts/Modellübersichten
und das Autorenrepository geprüft. Es wird keine vollständige Übernahme ihrer
Beweise für das Ropeway-Modell behauptet.

1. **Boland, Hewitt, Marshall, Savelsbergh (2017):**
   [The Continuous-Time Service Network Design Problem](https://doi.org/10.1287/opre.2017.1624).
   Grundidee partieller Zeitnetze und iterativer exakter Verfeinerung. Stützt
   die Architektur, nicht automatisch unsere Headway-/Passenger-Semantik.
2. **Marshall, Boland, Savelsbergh, Hewitt (2021; online 2020):**
   [Interval-Based Dynamic Discretization Discovery](https://doi.org/10.1287/trsc.2020.0994).
   Intervallbasierte Verfeinerung mit berichteten deutlichen Größen- und
   Laufzeitvorteilen auf Service-Network-Design-Instanzen. Kein Ropeway-Benchmark.
3. **Van Dyk, Könemann (2024):**
   [Sparse DDD via arc-dependent time discretizations](https://doi.org/10.1016/j.cor.2024.106715),
   [Autorenimplementierung](https://github.com/madisonvandyk/SND-RR).
   Unterschiedliche Zeitmengen je Arc verhindern unnötige Kopien. Der stärkste
   Effekt betrifft hochgradige Netze; unsere geringe lokale Routenzahl begrenzt
   die unmittelbare Übertragbarkeit. Repository ist kein fertiger Ropeway-Solver.
4. **Croella, Luteberget, Mannino, Ventura (2024):**
   [DDD/MaxSAT für Zugdisposition](https://iris.uniroma1.it/handle/11573/1709358),
   DOI 10.1016/j.cor.2024.106679. Relevanter Scheduling-/Ressourcenbezug;
   zeitindizierter Ansatz war bei stückweise konstanten Zielen günstiger,
   Big-M bei linearen kontinuierlichen Zielen. Unser diskretes Bedienungsziel
   ist deshalb ein plausibler Testgegenstand; dies ist eine Übertragungshypothese,
   kein bewiesener Vorteil für integrierte Seilbahnpassagiere.
5. **Van Dyk, Könemann (2023, Preprint):**
   [DDD under hard node storage constraints](https://arxiv.org/abs/2303.01419).
   Begrenzter Speicher ist eine besondere Schwierigkeit; die Arbeit entwickelt
   stärkere Relaxationen für diskrete Packet-Routing-Probleme. Relevant für
   belegte Wartezustände, aber ihre Speichergrenzen ersetzen nicht unsere
   Ressourcengeometrie und Schutzzeiten.
6. **Mei, Gu, Cassidy, Fan (2021):**
   [Planning skip-stop transit service under heterogeneous demands](https://doi.org/10.1016/j.trb.2021.06.008),
   [Autorenpreprint](https://arxiv.org/abs/2011.12674).
   Hohe und heterogene Nachfrage ist ein begründeter Untersuchungsbereich.
   Berichtete Systemkostengewinne für AB-Angebote sind kein Nachweis größerer
   Seilbahnkapazität. Deshalb positive Hypothesen mit neutralen/ungünstigen
   Kontrollprofilen vergleichen.
7. **Van Lieshout, van der Schaft (online 2025):**
   [DDD for multidepot vehicle scheduling with trip shifting](https://doi.org/10.1287/ijoc.2024.0698).
   Belegt die Nutzbarkeit adaptiver Zeitdarstellung im Depot-/Fahrzeugeinsatz-
   Kontext. Dort vorgegebene Fahrten sind deutlich anders als unsere gemeinsam
   zu erzeugenden Bewegungen und Passagierzuweisungen.

## Einschätzung

Eine kapazitätsorientierte anonyme Reservoir-Flussformulierung ist ein
wissenschaftlich plausibler Entwicklungspfad. Der erwartete Nutzen stammt aus
gemeinsamen Flüssen, fehlenden Kabinenlabelkopien und einer anderen Behandlung
der Zeit. Ein gelöstes kleines LP oder ein kleineres Netz beweist noch keine
brauchbare große Suche. Der harte Test bleibt: gültige neue SS-Bedienung und
eine ausreichend enge AS-Kapazitätsgrenze unter demselben Vertrag.

Der unmittelbare Beitrag zur Thesis kann schon ein getrennter
Kapazitätsnachweis sein. Ein universeller Algorithmus, der alle Nachfrageprofile,
freie Wiederverwendung und Reisezeit gleichzeitig mit kleinem Gap löst, ist
dafür keine notwendige Vorbedingung und wird hier nicht versprochen.
