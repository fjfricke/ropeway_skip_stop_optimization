# OIP No-Wait: EAN gegen affine Templates

Status: wartet auf vollständige F0/F2/F3-Phasenkalibrierung.

Verglichen werden bei K62 und `ceil(1.2*Nmax)` je Familie das allgemeine
EAN-CP-SAT-Modell und der affine No-Wait-Templatebuilder. Beide erhalten
denselben validierten regelmäßigen All-Stop-Start, Seed 0, zwölf Worker und
fünf Minuten tatsächliche Wandzeit. Ziel ist ausschließlich maximale
Bedienung. Journey Time wird aus jedem Zertifikat gemessen.

Die Auswertung berichtet je Fall Bedienung, Bedienungsschranke, Zeit bis zur
ersten echten Verbesserung, Typmischung, Modellbauzeit, Modellgröße und
Speicher. Ergebnisse werden erst nach Abschluss der sechs Kurzläufe ergänzt.
