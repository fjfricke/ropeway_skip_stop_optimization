# No-Wait-Templateaufbau: Korrektur und Abnahme

Stand: 18.09.2026. Keine neue Optimierungskampagne gestartet.

## Ursache und Änderung

Der erste Templatepfad ergänzte affine Zeitgleichungen im bestehenden EAN.
Dabei blieben Zeitgrenzen erhalten, die für den ersten aktiven Stationsbesuch,
aber nicht für die gesamte deterministische Vorgeschichte geeignet waren.
Eine Kabine weit hinter dem Templateursprung benötigt für dessen erste Ereignisse
stärker negative Zeiten. Die Kombination konnte zulässige Starts ausschließen.
Die früheren nativen `INFEASIBLE`-Ergebnisse dieses Templatepfads sind deshalb
kein Nachweis gegen den beabsichtigten OIP-Vertrag.

`nowait_templates.py` baut die Bewegung jetzt unabhängig auf:

- Eine Typwahl und eine ganzzahlige Verschiebung je Kabine bestimmen die Ereignisse.
- Anfangszustände werden aus den Zeiten abgeleitet. Stations- und Seilstarts sind enthalten.
- Alternierende Typen behalten ihre Besuchsparität über Umlaufgrenzen.
- Ressourcen entstehen aus derselben Trajektorie vor und nach null. Relevante
  Schutzintervalle werden vollständig erhalten, einschließlich des Betriebsendes.
- Identische Verschiebungsgrenzen werden als Boolesche Bedingungen wiederverwendet.
- Der bestehende Passagierbuilder und Served-only-Zielvertrag bleiben erhalten.
- Beim Hintimport werden Kabinen, Anfangszustände und Passagierzuordnungen gemeinsam
  nach Typ und Anfangskategorie umnummeriert. Positionen und Entscheidungen bleiben frei.

## Nachspielen gespeicherter Referenzen

Die vollständigen gespeicherten Starts der gestoppten F2/F3-Kampagne wurden im
neuen Modell **für den Test fixiert**, gelöst, extrahiert und unabhängig geprüft.
Im normalen Runner bleiben Hints unverbindlich.

| Fall | K | Nachfrage | Bestätigt bedient | Unserved |
|---|---:|---:|---:|---:|
| F2 | 62 | 2.266 | 1.902 | 364 |
| F3 | 62 | 5.430 | 4.549 | 881 |

Die fixierten Replays wurden unmittelbar im Presolve bestätigt. Das beweist die
Darstellbarkeit dieser Starts, kein Optimum und keine Geschwindigkeit der freien Suche.
Die Journey-Time-Werte der extrahierten Zuordnung wurden ebenfalls unabhängig geprüft.

## Regressionen

70 bestehende OIP-Tests bestanden. Ergänzt wurden zwölf Grenztests über drei Typen
mit Eintritt bei null, Ausfahrt bei null sowie erstem/letztem Tick auf dem Seil.
Beide gespeicherten K62-Referenzen werden zusätzlich als lokale Integrationstests
geprüft; ohne die Laufartefakte werden nur diese beiden Tests übersprungen.

```sh
PYTHONPATH=.:src .venv/bin/python -m pytest tests/test_oip*.py -q
```

Die kleinen Tests vergleichen Served-Optima beider Formulierungen und beide
Passagierencodings, prüfen Alternierung und gegenseitigen Hintimport. Sie sind
kein vollständiger Beweis der Modelläquivalenz für beliebige Geometrien.

## Nächster Schritt

Nach gesondertem Startauftrag ist ein begrenzter freier Template-Lauf mit dem
geprüften Start sinnvoll. Erst dessen native Lösungen, Bounds und unabhängige
Zertifikatsprüfung zeigen die praktische Suchleistung. Historische Ergebnisse
bleiben unverändert; alte Bounds werden nicht übernommen.
