# OIP No-Wait: EAN gegen affine Typ-Templates

Der technische Vergleich prüft, ob eine spezialisierte No-Wait-Formulierung
schneller gute Lösungen liefert als der allgemeine OIP-EAN-Builder. Beide
Modelle wählen bei genau K62 gemeinsam den Kabinentyp, die individuellen
Anfangspositionen und die ganzzahlige Passagierzuordnung. Optimiert wird nur die
bediente Nachfrage; Journey Time wird aus jedem validierten Zertifikat gemessen.

F2 erlaubt All-Stop, BD und CE. F0 und F3 erlauben All-Stop sowie beide Phasen
eines über Umlaufgrenzen fortgesetzten alternierenden STOP/SKIP-Typs. Waiting,
Reservoirabfahrten, Rückkehrpflicht, anfängliche Passagiere und freie
Einzelhaltentscheidungen sind ausgeschlossen. Es gilt der kurze T5R/G500-Vertrag
mit aktueller Thesis-Geometrie: 1464 s Nachfrage, Bedienung bis 2364 s und
Weiterfahrt bis 2664 s im 1-ms-Raster.

Die Last jeder Familie ist `ceil(1.2*Nmax)` aus der bewiesenen regelmäßigen
All-Stop-Referenz mit frei optimierter gemeinsamer Phase. Fehlt der exakte
N/N+1-Nachweis einer Familie, startet die Vergleichskampagne nicht. Für jeden
freigegebenen Fall wird bei der tatsächlichen 120-%-Nachfrage ein validierter
regelmäßiger All-Stop-Start erzeugt und identisch an beide Formulierungen
übergeben. Der Hint setzt keine Entscheidung fest.

Die affine Formulierung ersetzt rekursive und konditionale Zeitgleichungen durch
eine Verschiebung pro Kabine und deterministische typabhängige Ereignisoffsets.
Ressourcen, Anfangsgrenze, Horizontschutz, Passagiere, Zertifikate und Frontend
bleiben gemeinsam. Im Served-Modus werden keine Journey-Time-Produkte gebaut.

Die Reihenfolge ist F2 EAN/Template, F3 Template/EAN und F0 EAN/Template. Jeder
der sechs Läufe erhält fünf Minuten, Seed 0, zwölf Worker und höchstens 32 GiB
Prozessbaum-RSS. Modellgrößen vor und nach Presolve, Bedienungsschranken,
Typanzahlen, Anfangspositionen und native Verbesserungen werden gespeichert.

```bash
.venv/bin/python benchmarks/run_oip_nowait_formulation_comparison.py \
  --output results/oip_nowait_formulation_comparison_20260918 \
  --build-only

.venv/bin/python benchmarks/run_oip_nowait_formulation_comparison.py \
  --output results/oip_nowait_formulation_comparison_20260918 \
  --resume
```

Der erste Vergleich startet erst nach bestandenen Korrektheitstests und drei
bewiesenen Phasenreferenzen. Die alte lexikografische Typkatalogkampagne wird
nicht fortgesetzt. Waiting und längere Hauptläufe werden erst nach der
Auswertung dieses Vergleichs entschieden.
