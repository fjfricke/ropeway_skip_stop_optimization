# Freie Passagiere und ressourcenbasierte Nachbarschaften

11.09.2026. Autorisierter begrenzter Folgetest zum Reservoir-Hybrid.
Kein neuer Standard und kein Anspruch auf globale Gap-Konvergenz.

Abgeschlossen: 18 Läufe in 17.48 Minuten, kein Kostengewinn; 70 Tests bestehen.
[Ergebnisbericht](../findings/reservoir_global_passengers_conflict_test_20260911.md).

## Hypothesen und Trennung

1. Die Fixierung von 83–92% der Fahrgäste in früheren Reparaturen verhindert
   nützliche gemeinsame Änderungen. Dieselben geöffneten Einsätze erhalten jetzt
   eine global freie ganzzahlige Passagierzuordnung.
2. Nachbarschaften aus tatsächlichen Ressourcenkonflikten einer optimistischen
   Skip-Änderung sind hilfreicher als benachbarte Dispatch-IDs um einen Scoreanker.

Es werden zuerst gleiche Nachbarschaften mit/ohne freie Außenpassagiere getestet,
danach zusätzlich die Konfliktauswahl. Vollständiges CP-SAT ist Kontrollarm.
Die bereits optimal geprüfte globale Zuordnung bei vollständig festem Fahrplan
hat keine Verbesserung gebracht. Es geht deshalb um gemeinsame Änderungen.

## Implementierung

`reservoir_hybrid/global_repair.py` verwendet den bisherigen kleinen physischen
Reparaturbuilder mit leerer Nachfrage und dessen vollständigem Außenkalender.
Danach wird der vorhandene ganzzahlige Passagierbuilder auf einer gemeinsamen
Sicht aus lokalen Variablen und festen Außenereignissen aufgerufen. Es entstehen
keine variablen Außenfahrzeiten. Slots, Waiting und Headways bleiben unverändert.

Temporäre IDs trennen lokale Slots und Außenfahrten. Die Symmetrie gilt nur für
lokale Einsätze; beim Export werden alle Einsätze nach Dispatch kanonisiert und
sämtliche positiven Ride-Mengen mitübersetzt. Die unabhängige Originalprüfung
muss jeden exportierten Plan akzeptieren.

Außenkandidaten mit fehlenden STOP-Endpunkten oder verletzter fixer
Freigabe-/Horizontbedingung sind nachweislich unmöglich und werden ausgelassen.
Alle anderen Zuordnungen bleiben frei, inklusive Nachfragewechsel zwischen
Außen- und Innenfahrten. Gemeinsame Nachfrage- und Sitzplatzsummen sowie das
bisherige exakte Reisezeitziel stammen aus dem gemeinsamen Passagierbuilder.
Ein All-Closed-Fall fixiert auch den technisch erforderlichen leeren Dummyslot.

`reservoir_hybrid/conflict_neighborhoods.py` betrachtet besetzte STOP-Besuche mit
Durchreisenden. Als reine Auswahlheuristik wird der STOP durch SKIP ersetzt und
der Rest der betreffenden Fahrt um die eingesparte Zeit nach vorne verschoben.
Alle daraus entstehenden Konflikte gegen tatsächliche Außenreservierungen werden
mit vollständiger Schutzzeit, Waitinggeometrie und Zustandszeit-Eindeutigkeit
ermittelt. Intervalle bleiben halboffen; später beginnende Reservierungen werden
nicht durch einen einzigen Frei-Zeitpunkt ersetzt.

Der Anker und seine direkten Blockierer bilden eine Nachbarschaft, maximal sechs
Einsätze. Vorschläge mit mehr Blockierern werden als zu groß protokolliert; sie
sind nicht global unzulässig. Priorität: optimistische eingesparte
Passagiersekunden pro geöffnetem Einsatz. Die vorgeschlagene Skip-Änderung wird
nicht festgesetzt, ist kein gültiger Fahrplan und keine garantierte Verbesserung.
Die Reparatur entscheidet STOP/SKIP/Waiting und Passagiere selbst.

## Vergleich und Abbruch

Gemeinsamer geprüfter Max50-Seed: 368765.817136 Passagiersekunden, 1280 bedient,
38 Einsätze. Gesamte Single-Use-Domäne und vollständiges Waiting unverändert.

- Screening: vier alte Mengen × Legacy/global, plus vier Konfliktmengen/global;
  je 30 Sekunden äußerer Rahmen, Seed 0, je zwölf Worker.
- Lokale Vergleiche durchgehend ohne Presolve, um nicht gleichzeitig die
  Solverparameter zu verändern. Vollständiges CP-SAT verwendet wie bisher
  Presolve und das Hints-Profil.
- Beste neue Menge nach validierter UB; bei Gleichstand Konfliktmenge, dann
  stabiler Name. Keine neue Startlösung zwischen Screeningfällen weiterreichen.
- Bestätigung: beste globale Reparatur, Legacy mit exakt derselben Menge und
  vollständiges CP-SAT; Seeds 1/2, je 120 Sekunden inklusive Aufbau und Abschluss.
- Nominal 18 Minuten, Gesamtlimit 30 Minuten einschließlich Vorbereitung.
  Keine konkurrierenden Solver, 16 GiB Prozess-RSS-Limit.
- Erfolg nur bei mindestens 0.1% niedrigeren validierten Kosten als beide
  Kontrollen, in beiden Bestätigungsseeds. Übernahme des Seeds zählt nicht.
  Ein früher optimal gelöstes Teilproblem ist kein globales Optimum.
- Systemzeit und monotone Laufzeit getrennt erfassen; größere Abweichung macht
  einen Lauf für die Leistungsbestätigung unbrauchbar (Systemschlaf).

Ergebnisse: `benchmarks/output/reservoir_global_repair_campaign_20260911_v1/`.
Runner: `benchmarks/run_reservoir_global_repair_campaign.py`.

## Wissenschaftlicher Bezug

Die konkrete Seilbahnübertragung und ihre Auswahlheuristik sind projektspezifisch.
Verwandte Arbeiten begründen die Untersuchung, nicht ihren Erfolg hier:

- [Dong et al. (2020), integrierte Zugstopps und Fahrpläne mit ALNS](https://doi.org/10.1016/j.trc.2020.102681).
- [Ropke & Pisinger (2006), adaptive Auswahl verschiedener Nachbarschaften](https://doi.org/10.1287/trsc.1050.0135).
