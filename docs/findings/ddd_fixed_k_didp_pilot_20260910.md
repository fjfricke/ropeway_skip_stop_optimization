# DIDP Fixed-K Pilot: Ergebnis

Die erste CABS/DIDPPy-Kampagne wurde am 10.09.2026 abgeschlossen. Sie verwendete eingefrorene Instanzen und Quellen, keine Hints und keine externen Objective-Cutoffs. Die vollständigen Rohdaten liegen unter [benchmarks/output/didp_pilot_20260910](../../benchmarks/output/didp_pilot_20260910). Die Implementierungsbeschreibung steht in [docs/plans/ddd_fixed_k_didp_pilot_20260910.md](../plans/ddd_fixed_k_didp_pilot_20260910.md).

## Ergebnisübersicht

| Fall | CABS/DIDP | CP-SAT Legacy | Aussage |
|---|---:|---:|---|
| K2, No-Wait | U=6, optimal in 0,8 s | U=6, optimal in 0,7 s | gleiches Optimum |
| K2, Waiting 2 s | U=14 nach 60 s, Timeout, LB=0 | U=6, optimal in 0,8 s | CP-SAT klar besser |
| K4, No-Wait | U=14, optimal in 41,5 s | U=14, optimal in 0,8 s | gleiches Optimum, DIDP etwa 50× langsamer |
| K4, Waiting 2 s | U=28 nach 60 s, Timeout, LB=0 | U=14, optimal in 0,8 s | CP-SAT klar besser |
| K38, Waiting 1.200 s | keine native Lösung nach 180 s; Referenz U=315 separat | U=318 nach 180 s | CP-SAT kommt nahe an historische Referenz |
| K39, Waiting 1.200 s | keine native Lösung nach 180 s; Referenz U=1.402 separat | U=2.610 nach 180 s | CP-SAT verbessert, bleibt im Kaltstart weit zurück |
| K39 Wiederholung, CP-SAT zuerst, danach DIDP | keine native Lösung nach 180 s | keine native Lösung nach 180 s | CP-SAT-Ergebnis nicht reproduziert; Ursache nicht isoliert |

`U` bedeutet unbediente Personen. Die historischen Referenzen K38 U=315 und K39 U=1.402 wurden vor der Kampagne unabhängig validiert und nicht als native Solverlösungen gezählt. Alle großen Läufe verwendeten zwölf Worker. Eine Prozessstichprobe zeigte bei CABS ungefähr 1.070 % CPU, also etwa elf ausgelastete Kerne; die fehlende Lösung ist kein versehentliches Einthread-Problem.

Die nominellen Solverbudgets summierten sich auf 26 Minuten. Mit Vorbereitung und Abschluss dauerte die Kampagne 1.251,6 Sekunden. Jeder Lauf wurde in einem separaten Prozess mit 8-GiB-RSS-Grenze und hartem Wandzeitlimit überwacht. Timeout- und Speicherabbrüche wurden nicht als Unzulässigkeit oder Optimalität interpretiert.

## Was der Pilot gezeigt hat

Die native Formulierung ist auf kleinen No-Wait-Fällen korrekt: vollständig aufzählbare Pläne, CP-SAT und unabhängige physikalische/passagierbezogene Validierung stimmen überein. Die Tests decken Waiting-Intervallteilung, spätere Einfügung vor einer bereits geplanten Ressourcennutzung, Überholen, volle Kabinen, Aus- und Einstieg am selben Besuch, Verpflichtungen am Betriebsende, Horizontgrenzen, Odd-Cycle-Ganzzahligkeit und exakte Tickdarstellung oberhalb der 32-Bit-Grenze ab. Historische K38-/K39-Zertifikate lassen sich vollständig durch DIDP-Übergänge nachspielen.

Der Engpass ist die Suchstruktur. Waiting erzeugt zusätzliche Split-, Wait-, Ressourcen- und Commit-Übergänge. Die K2- und K4-Waiting-Fälle finden zwar schnell einen gültigen Plan, aber nur mit sehr schlechter Bedienung und verbessern bis zum Timeout nicht. Ihre gemessenen Spitzen-RSS lagen bei etwa 6,4 beziehungsweise 5,9 GiB. K38/K39 bauen in etwa 8,6 Sekunden Modelle mit 6.059/6.230 Zustandsvariablen und 71.088/73.670 Übergängen; CABS expandiert dort innerhalb von 180 Sekunden keine native vollständige Lösung. Die Restschranke bleibt in den großen Läufen zu schwach, sobald die Passagier- und Waitingentscheidungen noch nicht gebunden sind.

Die Korrektheitstests stützen die Kostenfunktion und Übergangsfolge. Lange Entscheidungsketten, Waiting-Verzweigung und eine grobe Restschranke sind plausible Ursachen der schlechten Suche; ihr jeweiliger Anteil wurde nicht durch Ablationen isoliert. Die Messungen begründen derzeit keinen langen Lauf derselben Formulierung. Sie beweisen aber nicht, dass ein längerer Lauf erfolglos bleiben oder DIDP CP-SAT grundsätzlich niemals überholen würde.

## Präzisierung: Kann DIDP CP-SAT später überholen?

Ja, grundsätzlich. Ein beobachtetes Plateau ist bei keinem der beiden Solver ein Beweis, dass weitere Verbesserungen ausgeschlossen sind. CABS kann mit wachsender Suchbreite zuvor verworfene Alternativen erreichen. Ob es innerhalb praktikabler Zeit und des Speicherlimits eine bessere Lösung als CP-SAT findet, ist hier offen. Die kurze Kampagne beantwortet diese Langzeitfrage nicht.

Die bisher getestete DIDP-Formulierung und DIDP als allgemeiner Ansatz müssen getrennt bewertet werden. Insbesondere sind die grobe Restschranke und die Reihenfolge von Mengen-/Waitingentscheidungen noch nicht ausgereizt. Das sind mögliche Ansatzpunkte, keine bereits nachgewiesenen Ursachen oder Verbesserungen.

Vor einem weiteren großen Lauf sollte ein begrenzter Kontrolltest auf K2/K4 mit unverändert mikrosekundengenauem Waiting prüfen, ob bessere Suchführung schnell gute native Lösungen findet. Zunächst nur Entscheidungspriorität und danach eine nachweislich gültige stärkere Restschranke einzeln verändern; zulässige Mengen, Waitingwerte und Bewegungen vollständig erhalten. Erstlösung, Verbesserungsverlauf, Schranke und Speicher gegen die eingefrorene Ausgangsversion vergleichen. Ein Erfolg würde einen größeren Test begründen, noch keinen Vorteil auf K38/K39 beweisen. Diese Folgetests sind hier dokumentiert, noch nicht umgesetzt oder gestartet.

Auch die frühere Aussage über eine nachgewiesene Reihenfolgeabhängigkeit war zu stark: In der K39-Wiederholung änderten sich gleichzeitig CP-SAT-Seed und Ausführungsreihenfolge. Mit diesen zwei Läufen lässt sich die Ursache des unterschiedlichen Ergebnisses nicht isolieren.

## Empfehlung

DIDP sollte als korrekt implementierter Forschungsversuch und Skalierungsbefund in der Thesis bleiben, aber nicht zum Hauptsolver werden. Der nächste produktive Schritt ist, CP-SAT als Hauptmethode weiterzuverwenden und die bereits validierte K38-/K39-Referenz als Seed-/Benchmarkpfad zu dokumentieren. Für neue Solverarbeit würde ich zuerst nur eine gezielte DIDP-Variante mit vorab aggregierter Passagierentscheidung testen; eine vollständige Überarbeitung von Reservoir, variabler Flotte oder zusätzlicher Waitinglogik ist durch diese Ergebnisse nicht gerechtfertigt.

Für die Präsentation ist die Aussage belastbar: Der getestete DIDP-Pilot stimmt in den Kontrollfällen mit den Referenzverfahren überein, zeigt im kurzen Vergleich aber deutlich schlechtere Ergebnisse mit Waiting. CP-SAT erreicht im K38-Kaltstart U=318 gegenüber U=315 historischer Referenz. Auf K39 erreicht CP-SAT einmal U=2.610 und findet in der Wiederholung keine Lösung; ein reproduzierbarer K39-Erfolg wurde damit nicht gezeigt. DIDP erzeugt in keinem großen Versuch eine native Lösung. Daraus folgt kein allgemeines Unmöglichkeitsurteil über DIDP.

## Zwei weitere Konzepte aus der Recherche

**Zeitautomaten:** Betriebszustände wie Fahren, STOP, SKIP und Exit-Waiting werden mit Uhren und Bedingungen für Zustandswechsel kombiniert. Symbolische Zonen können viele zulässige Uhrbelegungen gemeinsam darstellen, etwa einen Zeitbereich und Abstandsbedingungen zwischen zwei Ereignissen. Der Unterschied zum aktuellen DIDP-Piloten: Dieser teilt Waitingbereiche zwar kompakt auf, wählt vor der Reservierung aber letztlich einen einzelnen Tickwert. Ein symbolisches Verfahren kann Bereiche über weitere Schritte hinweg erhalten. Das könnte die Waiting-Verzweigung reduzieren; viele Kabinen, Ressourcen und ganzzahlige Belegungen können trotzdem sehr viele Zustände/Zonen erzeugen. Die bestehende Integer-Tick-Semantik müsste ausdrücklich erhalten oder als äquivalent nachgewiesen werden. Kostenbewertete Varianten unterstützen Optimierungsprobleme in geeigneten Modellklassen; das ist keine automatische Skalierungsgarantie für unsere Seilbahn. Grundlage: [Bouyer, Colange, Markey: Symbolic Optimal Reachability in Weighted Timed Automata](https://arxiv.org/abs/1602.00481).

**Passagierbündel:** Eine eigene Modellierungs-/Suchidee aus dem Aufzugstransfer, kein einzelner fertiger Solver. Eine Entscheidung könnte gleichzeitig festlegen: Kabine k nimmt an Besuch A vier Personen nach C und zwei nach D auf. Das legt sechs belegte Plätze bis C, zwei bis D und verpflichtende STOPs an A, C und D fest. Anschließend werden Zeiten, Waiting und Konflikte geplant. Die Suche muss solche Zuordnungen wieder tauschen und aufteilen können. Unsere Modelle verwenden bereits ganzzahlige Mengen je Beförderungskandidat; die Neuerung wäre deshalb eine gemeinsame Entscheidung über mehrere Kandidaten samt ihren STOPs. Nur ausgewählte Bündel zu erlauben wäre eine Heuristik beziehungsweise eingeschränkte Domäne. Für Exaktheit müssten alle zulässigen ganzzahligen Zuordnungen erreichbar bleiben. Forschungsbezug und Abgrenzung der eigenen Übertragung: [Recherche, Abschnitt 8](../research/ropeway_cross_domain_algorithms_20260910.md#8-aufzüge-von-passagieren-statt-von-fahrplanbits-ausgehen).

## Bekannter gemeinsamer Randfall

Der Kandidatengenerator kann eine tickgenaue Ankunft am Horizont wegen seines bestehenden Sekundenprunings verwerfen. Das ist in [docs/findings/ddd_candidate_horizon_rounding_20260910.md](ddd_candidate_horizon_rounding_20260910.md) reproduziert. Der Pilot hat diesen Generator nicht verändert, damit beide Solver denselben eingefrorenen Kandidatensatz verwenden.
