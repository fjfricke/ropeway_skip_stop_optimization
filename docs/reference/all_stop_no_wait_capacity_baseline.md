# Verbindliche All-Stop-Kapazitätsreferenz

Stand: 13.09.2026. Diese Referenz ist der verbindliche betriebliche Vergleich
für alle Kapazitätsexperimente der Thesis.

## Vergleichsvertrag

Jeder Skip-Stop-Kapazitätsversuch wird auf derselben Physik, Nachfrage,
Zeitachse und demselben verfügbaren Flottenmaximum gegen ein vollständig
gefülltes **All-Stop-System ohne Waiting** ausgewertet.

Für diese Referenz gilt:

- Alle physisch gleichzeitig im All-Stop-Umlauf unterzubringenden Kabinen
  werden eingesetzt. Im aktuellen Fünf-Stationen-Fall sind das 38 Kabinen.
- Jede Kabine hält bei jedem Stationsbesuch.
- Waiting ist null.
- Die Kabinen füllen den Umlauf gleichmäßig. Bei All-Stop-Umlaufdauer \(C\)
  und \(K_{AS}\) Kabinen ist der Abstand \(h=C/K_{AS}\).
- Sämtliche relativen Ereigniszeiten sind damit fest. Frei bleibt nur die
  gemeinsame Phase \(\theta\) innerhalb einer Headwayperiode. Dispatchzeiten
  haben die Form \(d_k=\theta+k h\), unter den unveränderten Randbedingungen
  für Warm-up, Bedienungshorizont und Betriebsende.
- Die gemeinsame Phase und die ganzzahlige Passagierzuweisung werden in
  einem CP-SAT-Modell gemeinsam auf maximale Bedienung optimiert. Ein Greedy
  Loading ist keine Baseline.

Die maßgebliche Referenz ist somit

\[
S_{AS}^{phase}=\max_{\theta\in[0,h)}
  S(\text{All-Stop},\text{No-Wait},K_{AS},\theta).
\]

Die Formulierung \(T/n\) bezeichnet nur dann das Phasenintervall, wenn \(T\)
die All-Stop-Umlaufdauer und \(n=K_{AS}\) ist. Im Code und in Berichten werden
dafür die eindeutigen Größen `all_stop_cycle`, `all_stop_cabins`, `headway`
und `phase` verwendet.

## Direkte Phasenvariable als Hauptformulierung

Die Phase wird als einzige zeitliche Entscheidungsvariable in ein gemeinsames
CP-SAT-Modell aufgenommen. Ein externer Phasensweep ist nicht die Hauptmethode.
Bei relativer Boardingzeit \(\beta_\rho\), relativer Ankunftszeit
\(\alpha_\rho\) und ganzzahliger Beförderungsmenge \(q_\rho\) gilt:

\[
\theta\in\Theta_{AS}\subseteq[0,h),\qquad
q_\rho>0\Rightarrow
r_{g(\rho)}\le\theta+\beta_\rho\le H_{service},\quad
\theta+\alpha_\rho\le H_{service}.
\]

\(\Theta_{AS}\) enthält sämtliche auf dem Zeitraster zulässigen Phasen unter
dem vereinbarten Bewegungs- und Randvertrag. Ein positiver Ride muss außerdem
bei der gewählten Phase tatsächlich existieren. Die übrigen Bedingungen sind
die ganzzahligen Nachfragebilanzen und Abschnittskapazitäten. Primärziel ist
\(\min U\), ohne Flotten-Tie-Break, da die Baseline-Flotte bereits feststeht.

Die Vorbereitung muss die Vereinigung aller über das Phasenintervall möglichen
Besuche und direkten Beförderungen erzeugen. Ein einzelner Fixphasen-Checkpoint
ist keine vollständige Kandidatenbasis. Anfangsbelegung, Dispatch, Rückkehr und
Horizontgrenzen werden entsprechend dem jeweiligen Baselinevertrag mitgeführt.
Die gemeinsame Verschiebung erhält relative Ressourcenabstände, ersetzt aber
keine Prüfung dieser absoluten Randbedingungen. Die gleiche Kabine bleibt über
alle Abschnitte einer Beförderung identifizierbar.

Für Reisezeitvergleiche bleibt das Ziel getrennt. Mit \(S=\sum_\rho q_\rho\)
und einem begrenzten ganzzahligen Produkt \(z=\theta S\) lautet es:

\[
\min C=\sum_\rho(\alpha_\rho-r_{g(\rho)})q_\rho+z+\sum_g\pi_g u_g,
\qquad z=\theta S.
\]

Alle Zeitwerte verwenden dieselbe Tickeinheit; Zahlenbereiche für das Produkt
werden vor Modellbau geprüft. Im Kapazitätsmodell entfällt dieses Produkt.
Es gibt keine freie Wahl einzelner Kabinenabfahrten, Haltemuster, Rundentimings
oder Ressourcenreihenfolgen. Die Phase muss die vollständige vereinbarte
Referenzdomäne abdecken; zusätzliche Muster- oder Dispatchrestriktionen des
Linienmodells werden nicht übernommen.

## Umsetzung und unabhängige Kontrolle

Der direkte Phasenoptimizer ist noch zu implementieren. Es existiert auch kein
fertiger Produktions-Phasensweep, dessen Code hier ersetzt würde. Vorgesehen:

1. Gesättigte Zirkulation und exakte Rasterdarstellung festlegen; vollständige
   Besuchs-/Ride-Vereinigung und zulässige Phasenbereiche vorbereiten.
2. Phase, Integer-Passagiere und temporale Implikationen gemeinsam modellieren;
   Kapazität zuerst, getrennten Reisezeitmodus danach prüfen.
3. Physikalische und Passagierzertifikate unabhängig validieren.
4. Kleine Fälle gegen eine unabhängige Enumeration beziehungsweise kritische
   Phasen testen: Freigaben, Horizontgleichheit, angrenzende Ticks, Beginn- und
   Rückkehrgrenzen sowie wechselnde Kandidatenmengen. Bei Reisezeit auch beide
   legalen Endpunkte von Regionen mit unveränderten Supports prüfen.
5. Erst mit vollständiger Modellabdeckung und Optimalitätsnachweis einen
   Phasenoptimalwert melden. Bei Timeout Incumbent und gültigen Bound separat
   ausweisen; `UNKNOWN` ist kein Unzulässigkeitsnachweis.

Der Sweep bleibt damit ein kleiner Referenztest. Er darf weder zum versteckten
Produktionscontroller werden noch einzelne Phasen aus der direkten Suche
entfernen. Historische Referenzwerte bleiben bis zum neuen Nachweis Fixphasenwerte.
Ein Zertifikat enthält Phase, vollständige Bewegung, Passagierzuweisung und
unabhängige Validierung.

## Verbindliche Auswertung

Die Referenz wird für **jede Nachfragefamilie, Nachfragehöhe und jedes
Freigabeprofil neu berechnet**. Ein Wert aus R0, R2 oder einem anderen
Demandprofil darf nicht übertragen werden.

Jeder Ergebnisbericht weist mindestens aus:

1. `S_AS_phase` und `U_AS_phase` der phasenoptimierten All-Stop-No-Wait-
   Referenz;
2. die optimale Phase und die eingesetzte All-Stop-Kabinenzahl;
3. `S_SS` und `U_SS` des unabhängig validierten Skip-Stop-Zeugen;
4. die Differenz `S_SS - S_AS_phase`;
5. den Gültigkeitsbereich zusätzlicher globaler Bounds.

Ein Skip-Stop-Plan zeigt für den betrieblichen Thesisvergleich einen Vorteil,
wenn

\[
S_{SS}>S_{AS}^{phase}
\quad\text{beziehungsweise}\quad
U_{SS}<U_{AS}^{phase}.
\]

Ein zusätzlicher globaler All-Stop-Bound über eine größere Domäne, etwa freie
Dispatchzeiten, optionale Flotte oder Waiting, ist ein stärkerer separater
Nachweis. Er wird weiterhin berichtet, ersetzt aber die festgelegte
All-Stop-No-Wait-Referenz nicht.

## Aktueller R2-Status

Der bekannte R2-All-Stop-Plan bedient bei \(D=3.074\) exakt 2.496 Personen
und lässt 578 unbedient. Seine Passagierzuweisung ist für die feste Bewegung
optimal. Die verwendete erste Dispatchzeit beträgt 29,090910 Sekunden; die
Phase wurde nicht optimiert. **2.496 ist daher bis zur nachgewiesenen Phasenoptimierung ein
Fixphasen-Referenzwert und noch nicht `S_AS_phase`.**

Der validierte Skip-Stop-Linienplan bedient alle 3.074 Personen. Der bereits
vorhandene globale Bound von höchstens 2.949 bedienten All-Stop-Personen in
der größeren Single-Use-Max50-R2-Domäne liefert unabhängig davon einen
stärkeren Nachweis. Der obligatorische Phasenvergleich ist trotzdem noch zu
berechnen und in die Ergebnistabelle aufzunehmen.
