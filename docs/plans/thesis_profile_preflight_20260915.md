# G500: Auflösungs- und Profilprüfungen vor der Hauptkampagne

Freigegeben durch „ok go“ nach der Nachprüfung vom 15.09.2026. Diese Vorprüfung
startet keine vollständige Thesis-Kampagne. Ergebnisse liegen unter
`results/thesis_g500_preflight_20260915`.

## Reihenfolge und Budget

1. T5R/F2, K10, N150: All-Stop und Skip-Stop bei 5-s-Freigaben, ohne Startplan,
   mit den bereits gespeicherten 15-s-Fällen vergleichen. Native LB/UB müssen
   die 1-%-Entscheidung tragen; reine Incumbent-Unterschiede genügen nicht.
2. F2-Kapazität: T5R/K62 und T6R/K75 bei 15 und 5 s, je höchstens 120 s.
   Die Werte 2.900 und 3.000 sind angeforderte Prüfstellen, keine übernommenen
   Schranken. Jede wird im jeweiligen Modell neu geprüft. Historische gleichartige
   Schranken dürfen anschließend mit ausdrücklicher Provenienz kombiniert werden.
3. Neun Referenzen: T5R/T6R × F0/F3/F4 für Kapazität und T5R × F0/F3/F4 für
   Journey-Kref10; jeweils 15 s, höchstens 90 s.
4. Sechs evolutionäre Kapazitätsprüfungen, je 45 s, genau K_AS, N=ceil(1,1 L),
   wobei L die bestätigte All-Stop-Untergrenze ist. Ist die Referenz offen,
   ist dieser Lastpunkt nur eine Größenprüfung und kein Kapazitätsvergleich.
5. Je fehlendem Journey-Profil All-Stop/Skip-Stop mit denselben festen Starts,
   K10 und N=floor(L/2), je höchstens 45 s. Keine Primalstarts.

Die Schritte 2–5 haben 1.830 s nominelles Budget und eine harte gemeinsame
Obergrenze von 2.100 s einschließlich Aufbau und Abschluss. Schritt 1 wird
separat mit höchstens 30/60 s ausgeführt. Alle Solver laufen nacheinander,
mit zwölf Workern/Threads und höchstens 32 GiB Prozessbaum-RSS. Der gemeinsame
Supervisor beendet bei Deadline, Suspend oder anhaltend kritischem Speicherdruck.
Ausfälle führen nicht zu weiteren Langläufen.

## Nachweis und Anzeige

- Gesamter Solverquellstand wird vor dem sequenziellen Block als ZIP gespeichert;
  jeder Einzelversuch führt zusätzlich Quellenhashes und Paketversionen mit.
- Legacy-Standards bleiben erhalten. Das neue optionale `probe_demands` erlaubt
  nur eine geänderte Prüfungsreihenfolge der bestehenden Kapazitätsbisektion.
- Vollständige Bedienung ist ein gültiger Zeuge. Timeout ist kein
  Unzulässigkeitsbeweis und keine Bestätigung einer Kapazitätsschwelle.
- Fertige Versuche und gelöste Referenzen werden getrennt gezählt.
- Die Thesis-Seite erhält einen eigenen Read-only-Bereich für diese Prüfungen;
  die bisherige 30-s-Kampagne bleibt getrennt sichtbar. Veröffentlicht werden
  portable Summaries ohne lokale Befehle oder private Pfade.
- Früh erreichte Vollbedienung eines Nachfrage-Endpunktmusters ist weiterhin
  kein Nachweis einer schwierigen evolutionären Musterentdeckung.

## Erste Auflösungsbefunde

T5R/F2, K10, N150, Passagiersekunden:

| Modus | 15 s | 5 s | Relative Abweichung zum feineren Wert |
|---|---:|---:|---:|
| All-Stop | 41.903,59995 | 41.618,79995 | 0,6843 % |
| Skip-Stop | 36.474,83995 | 36.666,32995 | 0,5223 % |

Die beiden 5-s-Läufe sind optimal; der 15-s-Skip-Stop-Bound liegt nur etwa
0,0027 Passagiersekunden unter der UB. Damit besteht F2-Journey das 15/5-s-Gate.
Der All-Stop-Vorteil von Skip-Stop bleibt erhalten. Die Freigabe betrifft zunächst
diesen geprüften Fall; die Kapazitätsauflösung und andere Profile bleiben offen.
