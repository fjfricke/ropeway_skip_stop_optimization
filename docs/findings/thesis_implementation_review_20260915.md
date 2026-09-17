# Nachprüfung der G500-Thesisintegration

**Aktualisierung 15.09.2026:** Die späteren Korrekturen, Reihensteuerung,
Frontenddetails und verbleibenden Messgates stehen im
[Abschlussbefund](../findings/thesis_completion_20260915.md). Die nachfolgende
frühere Bestandsaufnahme bleibt als Verlauf erhalten.

Stand: 15.09.2026. Prüfung von Implementierung, Plan, gespeicherten Ergebnissen
und Zertifikaten. Keine Hauptkampagne gestartet. Prüfartefakte:
`results/thesis_g500_review_20260915`.

## Ergebnis

Die gespeicherten F2-Fahrpläne und Kosten sind reproduzierbar. Die vorige
Abschlussmeldung hat den Implementierungsumfang und die Auflösungsfreigabe
jedoch überschätzt. Das Paket ist noch nicht für eine unbeaufsichtigte komplette
Thesis-Kampagne freigegeben.

## Unabhängig nachgeprüfte Ergebnisse

- Alle zwölf Reservoircheckpoints wurden gegen neu erzeugte Domänen geladen
  und unabhängig validiert. Bedienung, Flottengröße, Null-Waiting, Portschutz
  und erste vollständige Rückkehr ab der Bedienungsdeadline stimmen.
- Alle acht Arc-Flow-Endfahrpläne wurden aus den gespeicherten Bewegungen
  rekonstruiert; unabhängige Passagieroptimierung reproduziert die Kosten
  innerhalb 0,0001 Passagiersekunden. All-Stop und Skip-Stop haben je K dieselben
  Starts, Nachfrage, Randbelegungen und Betriebshorizonte.
- Die sechs wiederverwendeten Referenzdatensätze bestehen die neue Prüfung
  von Fallspezifikation, Flotte und physikalischem Fingerprint. Die vier
  Reservoirreferenzen besitzen erneut bestätigte Vollbedienungszertifikate.
- K=63 auf T5R und K=76 auf T6R verletzen als regelmäßige All-Stop-Flotten
  den bindenden Headway. Weil die kleinsten regelmäßigen Abstände bei größerem
  K nicht zunehmen, sind auch größere regelmäßige Flotten ausgeschlossen.

Die 30-s-F2-Zeugen bleiben gültig: 3.192 Personen mit K=62 auf T5R und 3.226
mit K=75 auf T6R vollständig bedient, gegenüber maximal vollständig bedienbarer
regelmäßiger All-Stop-Profilnachfrage von 2.901 beziehungsweise 2.932 Personen.
Das ist ein Vergleich vollständig bedienbarer verschachtelter Nachfrage.
Er behauptet weder ein Maximum für beliebige All-Stop-Dispatches noch, dass
All-Stop bei der erhöhten Nachfrage exakt 291/294 Personen weniger teilbedient.

## Gefundene Abweichungen und Korrekturen

| Befund | Bedeutung | Behandlung |
|---|---|---|
| Arc-Flow hatte `seed_kind=all_stop` | Alte Laufzeiten messen Suche mit einem All-Stop-Start; Optima bleiben gültig | Neuer Schalter `use_primal_start`, Legacy-Default an, Thesis explizit aus. Nativer kleiner Solvetest prüft, dass Seedkoordinator und Seedfactory nicht aufgerufen werden. Historische Starts im Export sichtbar. |
| Nur vier Quelldateien gehasht | Evolution, Decoder und Geometrie waren nicht vollständig im Laufnachweis erfasst | Künftige Läufe hashen Pythonquellen in src/benchmarks und Abhängigkeitsdateien; Paketversionen ergänzt. Alte Nachweise nicht rückwirkend ersetzt. |
| Elternprozesse konnten Fehler verschlucken | Reihe/Kampagne konnte trotz gescheitertem Kind als fertig erscheinen | Nichtnull-Exitcodes für unterbrochene/gescheiterte Einzel- und Reihenläufe; Kampagne kennzeichnet Teilausfälle. |
| Gesamtbudget nur zwischen Jobs geprüft | Suspend oder Kindprozess-Overhead konnte Gesamtlimit verletzen | Zusätzlicher äußerer Prozessbaum-Supervisor mit civil/awake Deadline, 32 GiB und Speicherdruckkontrolle. |
| Referenzwiederverwendung nur per Verzeichnisname | Falsche Physik oder Nachfrage konnte als Referenz übernommen werden | Fall-, Flotten-, Schema-, Fingerprint- und Checkpointprüfung vor Wiederverwendung. |
| Export konnte rohen Solverwert als validiert anzeigen | Ungültiger oder ungeprüfter Wert könnte zum Frontend-Incumbent werden | Validierung explizit erforderlich; fehlende Validierung ergibt keinen Bedienungs-/Journeywert. Nullwerte bleiben erhalten. |
| Ein bestes Ergebnis über verschiedene N | Mehr Nachfrage würde automatisch einen größeren Bedienungswert erzeugen | Solche Gruppen erhalten keine gemeinsame Best-Rangfolge; N wird je Lauf angezeigt. Ein echter N-Filter bleibt Teil der offenen Detailansicht. |
| `ready` bei beliebigen vorhandenen Resultaten | Anzeige implizierte Freigabe aller zwölf Gruppen | Datenpaket zeigt `partial`; neun Gruppen bleiben unkalibriert. |
| Evolution überschrieb nur best.json | Frühere vollständige Verbesserungszertifikate gingen verloren | Künftige Verbesserungen werden zusätzlich einzeln unter `incumbents/` gespeichert und exportiert. |

## Auflösung: zusätzlicher direkter Test

T5R/F2, K=10, dieselben 150 Personen und festen Starts:

| Auflösung | All-Stop Journey | Skip-Stop Journey | Skip-Stop-Vorteil |
|---|---:|---:|---:|
| 30 s, archivierte Läufe | 41.976,79995 | 36.049,77995 | 14,12 % |
| 15 s, neue Läufe ohne Start | 41.903,59995 | 36.474,83995 | 12,96 % |

Einheiten: Passagiersekunden. All-Stop ist im neuen Test optimal. Der neue
Skip-Stop-Lauf hat eine validierte UB von 36.474,83995 und eine native LB von
36.474,83728353371; die Lücke von etwa 0,0027 ist für diesen Vergleich
vernachlässigbar. Sie wird nicht zu einem exakten Optimalitätsbeweis umbenannt.

Die All-Stop-Kostenabweichung beträgt 0,175 %, die Skip-Stop-Abweichung rund
1,165 % (jeweils relativ zum feineren Wert). Die bisher verwendete Abweichung
301 versus 303 bei der Kref-Kapazität reicht allein nicht für die Freigabe der
Journey-Kosten. Der Vorteil bleibt bestehen, aber vor dem finalen Freeze ist
15 gegen 5 s zu prüfen. Für die hohen Kapazitätsreferenzen ist bereits der
15-s-Abgleich noch offen.

Die Zeiten dieser neuen Läufe ersetzen keine vollständige Laufzeitkalibrierung:
Startinformation und Auflösung wurden geändert, und All-Stop verwendete einen,
Skip-Stop zwölf Threads. Hier wurde die Auflösung, nicht die Solvergeschwindigkeit
zwischen diesen beiden Tests verglichen.

## Noch offen vor den vollständigen Reihen

1. **Auflösung festlegen.** Direkter 15/5-s-Vergleich bei gleicher Nachfrage für
   All-Stop und Skip-Stop; die zwei hochbelasteten All-Stop-Referenzen gezielt
   nahe ihren bekannten Intervallen abschließen. Keine pauschale 30-s-Freigabe.
2. **Neun fehlende Referenzen und Pilotprüfungen.** Kapazität T5R/T6R × F0/F3/F4
   (sechs Gruppen), Journey T5R × F0/F3/F4 (drei). Die Kataloge sind solverfrei
   geprüft: T5 F0/F2/F3/F4 = 11/3/6/6 Muster, T6 = 16/3/4/7. F2-Erfolg mit
   drei Mustern ist kein Skalierungsnachweis für F0.
3. **Unseeded Arc-Flow-Budgets nachkalibrieren.** K10/K23 und gegebenenfalls K35
   auf der freigegebenen Auflösung. Die alten Werte von 23–61 s stammen aus
   Läufen mit All-Stop-Start. Frühere Optima dürfen als externe Referenz dienen.
4. **Automatische Hauptreihen fertigstellen.** Der aktuelle K-Runner verarbeitet
   eine explizite K-Liste bei festem N. Nachfrageleiter, Abbruch nach zwei
   ungeklärten Journey-Punkten, sofortiges Ende bei validiertem U=0, Wiederaufnahme
   und vollständige Eltern-/kumulierte Zeitmetadaten sind noch nicht durchgängig
   implementiert. Vergleich immer bei gleichem K/N/Vertrag.
5. **Frontend vervollständigen.** Die Übersicht mit Rohresultaten ist vorhanden.
   Live-Snapshots der neuen Reihen, Verläufe, Auswahl nach N/K, integrierte
   Verbesserung-Replays, synchronisierter All-Stop-Vergleich und CSV/SVG/PDF
   fehlen. Das Kopieren von events.jsonl allein macht noch kein Live-Dashboard.
   Historische Archivseiten sind verlinkt, aber kein vollständiger portabler
   Ersatz für die neuen Details.
6. **Versuche einfrieren.** Nach diesen Gates die konkreten N/K-Punkte, Seeds,
   Budgets, Abbruchregeln und Datenauflösung je Gruppe in ein Manifest schreiben;
   ausführbaren Quellstand archivieren oder committen. Hashes eines schmutzigen
   Arbeitsbaums allein erlauben keine vollständige spätere Rekonstruktion.

Empfohlene Reihenfolge: Auflösung → fehlende Referenzen und kurze Profiltests →
Budgetfreeze und Reihen-/Frontendabschluss → Hauptkampagne. Größere Hardware
ist derzeit kein notwendiger nächster Schritt.

## Prüfungen

106 betroffene Pythonprüfungen bestanden, einschließlich des nativen Tests
ohne Startplan. 24 Frontendtests und Produktionsbuild bestanden. Zusätzlich
wurden die oben genannten 20 gespeicherten Fahrpläne erneut geprüft. Die
Archivdateien und ihre ursprünglichen Messzeiten bleiben erhalten.

Ein separater 0,2-s-Grenztest beendete den gesamten Kampagnenworker mit
`interrupted/WALL_DEADLINE` und Nichtnull-Exitcode. Ein achtsekündiger kleiner
Evolutionslauf bestätigte 40 bediente Personen und die separate Ablage des
Incumbent-Zertifikats. Der erneut exportierte Atlas enthält weiterhin die 22
historischen Läufe, jetzt mit Status `partial` und sichtbarer Arc-Flow-
Startprovenienz. Die neuen Sensitivitäts-/Grenztests liegen getrennt im
Prüfverzeichnis und wurden nicht in die ursprüngliche Kampagne hineingerechnet.
