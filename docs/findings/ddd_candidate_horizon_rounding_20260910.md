# Gemeinsamer EAN-Kandidatengenerator: exakte Horizontgrenze

Beim DIDP-Korrektheitstest am 10.09.2026 wurde ein bestehender Grenzfall gefunden. Er betrifft die Kandidatenvorbereitung vor beiden Solvern, nicht speziell DIDP.

## Reproduktion

Geometrie `five_station_circle_cw_half_skip_no_wait_headway_b_v0`, eine feste Kabine an `A_entry_cw`, Start 0, Kapazität 1, Nachfrage A→B, Freigabe 0. Für die ersten beiden STOP-Besuche ergibt die Integer-Tick-Domäne eine Ankunft bei B von **56.272727 Sekunden**.

Bei genau diesem Bedienungshorizont liefert `build_ean_ride_candidates` keinen A→B-Kandidaten. Die Funktion `_can_serve_within_horizon` rechnet ihre Mindestzeiten noch in Sekunden; der ungerundete Wert liegt geringfügig über dem bereits tickgerundeten Horizont. Der anschließende CP-SAT-Kapazitätslauf meldet dementsprechend U=1. Das ist korrekt für die ihm übergebene Kandidatenmenge, aber diese Menge lässt den Grenztransport aus.

Wird derselbe kanonische Kandidat aus einem längeren Horizont beibehalten, liefert das DIDP-Modell bei genau 56.272727 Sekunden eine validierte Bedienung. Einen Tick davor wird sie ausgeschlossen. Diese Gegenprüfung steht in `tests/test_ddd_didp.py::test_arrival_at_horizon_and_one_tick_after`.

## Konsequenz

Historische Kandidaten und Ergebnisse wurden nicht verändert. Der Pilot verlangt bewusst denselben ursprünglichen Kandidatensatz für CP-SAT und DIDP. Dieser Randfall erklärt allein weder die bisherigen großen Gaps noch die langen Suchplateaus.

Eine spätere Korrektur sollte das gemeinsame konservative Pruning auf dieselbe Integer-Tick-Arithmetik wie die Bewegungsdomäne umstellen, inklusive Nachfragefreigaben und der gesamten minimalen Teilroute. Dafür müssen Kandidaten-/Domänen-Fingerprints und betroffene historische Vergleiche neu geprüft werden. Einfach eine willkürliche Sekunden-Toleranz hinzuzufügen wäre keine saubere Lösung.
