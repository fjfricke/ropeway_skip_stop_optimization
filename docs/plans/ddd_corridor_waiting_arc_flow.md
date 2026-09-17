# Kompaktes Waiting-Arc-Flow mit konservativer Suche und globaler Relaxation

Stand: 14. September 2026. Der Pilot ist als eigener Fixed-K-Solverpfad
implementiert. Er verändert keine Legacy-Defaults. Die erste Gate-Messung ist
in `docs/findings/ddd_corridor_waiting_arc_flow_20260914.md` dokumentiert.

## Ziel

Ein gelabeltes Gurobi-Modell verbindet Stop/Skip-Pfade, ganzzahlige
Mikrosekundenzeiten, Exit-Waiting und ganzzahlige direkte Beförderungen. Waiting
wird durch Zeitkorridore beschrieben und nicht pro möglichem Tick expandiert.

Zwei Modelle teilen dieselbe Vorbereitung. Das konservative `inner`-Modell
verbietet bereits die Überlappung der vollständigen möglichen
Ressourcenbelegung zweier Korridorarcs und liefert deshalb ausschließlich
physisch prüfbare Fahrpläne. Das optimistische `outer`-Modell verwendet nur die
in jeder Realisierung zwingend enthaltenen Ressourcenkernintervalle. Sein
Solver-Bound ist eine globale Untergrenze für die deklarierte Fixed-K-Domäne.

Für jeden Besuch gilt die exakte Zeitfortschreibung

\[
t_{k,i+1}=t_{k,i}+d_{k,i}+w_{k,i}.
\]

Dadurch kann ein Kabinenpfad nicht unterschiedliche, gemeinsam unmögliche
Punkte seiner aufeinanderfolgenden Korridore verwenden.

## Konfiguration

Der Runner ist `benchmarks/run_ddd_corridor_arc_flow.py` und unterstützt
`inner`, `outer` und `adaptive`. Die Waiting-Grenze ist standardmäßig

\[
W_K=\left\lceil 2C_{AS}/K\right\rceil\text{ Sekunden},
\]

während die Entscheidung selbst auf dem bestehenden 1-µs-Tick bleibt. Eine
explizite Grenze kann alternativ angegeben werden. Fixed-K, feste vorhandene
Startpositionen und das Ziel `unserved` bilden den Pilotumfang.

## Verfeinerung

`adaptive` löst abwechselnd beide Modelle und isoliert lokal höchstens 16
Beginn- oder Waitingwerte als Ein-Tick-Zellen. Es priorisiert exakte
Ressourcenkollisionen des Outer-Kandidaten und darin passagiertragende Besuche.
Ohne Kandidat gilt eine deterministische breiteste-Zelle-Regel. Alle
Kindzellen bilden ihre Eltern exakt ab; es geht kein Tick verloren.
Vollständige MIP-Starts übertragen die beste bisherige gültige Bewegung und
ihre neu optimierte ganzzahlige Passagierzuordnung.

Die Route wird durch Indikatorgleichungen fortgeschrieben. Große
Mikrosekundendauern stehen dadurch nicht als Koeffizienten vor Binärvariablen.
Ein kleiner Gegenfall hatte sonst einen akzeptierten MIP-Start mit U=6, aber
ohne Start einen falschen angeblichen Optimalwert U=8 geliefert. Dieser
numerische Modellierungsfehler ist als Regressionstest abgedeckt.

## Korrektheit und Gate

Vor größeren Läufen prüfen kleine Fälle Korridorabdeckung, Ressourcenhüllen,
zwingende Kerne, exakte Pfadzeitkopplung, Waitinggrenzen, Passenger Capacity,
physische Rekonstruktion und

\[
LB_{outer}\le U^*\le U_{inner}.
\]

Die erste Performancekampagne vergleicht K20 und K39 mit dem vollständigen
CP-SAT bei gleicher Domäne, zwei Seeds und höchstens 60 Minuten Gesamtzeit.
Ein Ausbau verlangt in beiden K39-Seeds mindestens zehn zusätzlich bediente
Personen oder einen um einen Prozentpunkt kleineren vergleichbaren globalen
Gap ohne schlechteren Incumbent.

Der erste Seed-0-Gate verfehlt dieses Kriterium. Deshalb wurden die weiteren
Wiederholungen nicht automatisch gestartet. Das ist die im Plan vorgesehene
Abbruchentscheidung bei zu konservativen Hüllen; es ist kein Nachweis gegen
andere Intervall- oder DDD-Formulierungen.

Grundlagen sind Marshall et al., *Interval-based Dynamic Discretization
Discovery for Solving the Continuous-Time Service Network Design Problem*,
<https://doi.org/10.1287/trsc.2020.0994>, und Van Dyk und Koenemann, *Sparse
dynamic discretization discovery via arc-dependent time discretizations*,
<https://doi.org/10.1016/j.cor.2024.106715>. Die seilbahnspezifischen äußeren
Ressourcenhüllen sind eine eigene Formulierung und werden nicht als Resultat
dieser Arbeiten ausgegeben.
