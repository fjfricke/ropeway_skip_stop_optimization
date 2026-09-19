# OIP: exakte regelmäßige All-Stop-Referenz

Stand 18.09.2026. Ersetzt für neue OIP-Versuche die Auswahl aus fünf Phasen.

## Vertrag

T5R/G500, aktuelle Thesis-Weichen-Headways, genau K62, No-Wait.
Regelmäßige Anfangsaufstellung mit einer gemeinsamen frei optimierten Phase;
keine Reservoirabfahrten, Rückkehrpflicht oder anfänglichen Fahrgäste.
Nachfragefreigaben über 1.464 s, Bedienung bis 2.364 s, Weiterfahrt bis 2.664 s.
F0/F2/F3, P0, deterministische geschachtelte Nachfrage mit 15-s-Freigaben.

Das 1-ms-Raster bestimmt die tatsächlichen Bewegungsdauern. Regelmäßige
Kabinenabstände werden ganzzahlig ausgeglichen (`floor(i * cycle_ticks / K)`).
Die Phase umfasst einen vollständigen quantisierten Umlauf. Damit wird keine
unzulässige Periodizität von einem Kabinenabstand bei Restticks angenommen.

## Methode und Nachweis

Für jede mögliche Beförderung bestimmen Freigabe und Bedienungsdeadline ein
zulässiges Phasenintervall. Dessen Grenzen zerlegen den gesamten Phasenraum
exakt in Zellen. Gurobi wählt eine Zelle und ganzzahlige Beförderungsmengen;
Kapazitäten gelten auf jedem Fahrtabschnitt. Keine Stichprobe aus fünf Phasen.
Fahrpläne werden als OIP-Bewegung exportiert und unabhängig geprüft.

Die Nachfrage wird verdoppelt, bis eine unzulässige obere Grenze vorliegt,
danach binär gesucht. Nmax ist erst bewiesen, wenn N vollständig bedient wird
und N+1 über alle Phasen nachweislich unzulässig ist. UNKNOWN ist kein Beweis.
Der Nachweis gilt für diese regelmäßige Referenzfamilie, nicht für frei
verteilte All-Stop-Kabinen oder Skip-Stop. Das Journey-Time-Ergebnis eines
Machbarkeitssolves ist kein Reisezeitoptimum.

Erst nach dem Nachweis: neue Versuchsnachfrage `ceil(1.2 * Nmax)`.
Darauf muss All-Stop erneut bewertet werden, bevor ein Startwert oder
Skip-Stop-Vergleich ausgewiesen wird. Nmax ist nicht automatisch die maximale
Bedienung einer höheren angebotenen Nachfrage.

## Ausführung und Anzeige

`benchmarks/run_oip_phase_calibration.py`: F2, F3, F0 sequenziell;
maximal 30 Minuten je Familie, zwölf Gurobi-Threads, 32 GiB Prozessbaum-RSS,
Supervisor einschließlich Modellbau und Abschluss. Unterbrochene Versuche
bleiben in eigenen Versuchspfaden erhalten. `--build-only`, `--resume`.
Keine automatische neue Hauptreihe.

Live: `/calibration-live`, nachgewiesene Unter-/Obergrenzen, letzte Prüfung,
Status und abgeleitete 120%-Nachfrage. Keine künstlichen Optimierungsgaps.

## Historische Ergebnisse

Die bisherigen CAL-O-Zahlen (u.a. F2=2.918) verwenden einen anderen, langen
Reservoirvertrag und sind keine Kapazitäten des kurzen OIP-Vertrags.
Die ungefähr 1.600 aus fünf OIP-Phasen waren ein gefundener Referenzfahrplan,
kein bewiesenes Maximum. Daraus lässt sich kein Vorteil freier Positionen
ableiten, ohne dieselbe Nachfrage und denselben Vertrag zu vergleichen.
Alte Hauptläufe bleiben erhalten und pausiert; ihre Referenzbasis ist überholt.

## Korrektheitsprüfung

Phasenzellen werden an sämtlichen Zellgrenzen und ihren benachbarten Ticks
gegen die unabhängige feste EAN-Passagieroptimierung verglichen. Weitere
Prüfungen decken Anfangsbelegung, Umlaufgrenzen, Weiterfahrt, No-Wait und
Timeout ab. Positive Kalibrierpunkte erhalten Bewegungs-/Passagierzertifikate.
