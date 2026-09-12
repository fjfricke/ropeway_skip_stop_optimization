# IBM CP Optimizer: identischer Reservoir-Vergleich

Auftrag vom 10.09.2026: zweites Backend für die bestehende einmalige Reservoir-Domäne; bestehende CP-SAT-/Fixed-K-Pfade erhalten. Danach kleine Gleichheitstests und ein Lauf über 1.800 s mit maximal 50 Kabinen, Waiting und exakt dem Startplan des CP-SAT-Vergleichs.

- `DddReservoirCpSatProblem` als bestehende solverunabhängig beschriebene Domäne wiederverwenden; keine neue Physik, Startpolitik, Zeitraster oder Kandidatenpruning.
- IBM-Modell mit nativen optionalen Intervallen/NoOverlap, gleichen State-Time-Eindeutigkeitsbedingungen, Integer-Zuordnung und gleichem Produktziel. Kein paarweises EAN-MIP.
- Native Mikrosekundenticks beibehalten; zulässige Integer-/Intervall-/Kostenbereiche der installierten Version prüfen und bei Überschreitung abbrechen, niemals still runden.
- Vorhandene Primal-Checkpoints über gemeinsamen unabhängigen Prüfer importieren/exportieren. Solver-Bounds werden nicht zwischen Backends übernommen. Zielfunktions- und Modellidentität sowie Solverversion und Toleranzen berichten.
- Optionales Dependency-Extra, separater Runner/CLI, echte Laufzeit einschließlich Build/Export, Live-Logs, validierte Zwischenpläne, sauberer Fehler-/Timeoutstatus.
- Kleine bekannte/exhaustive Optima, All-Stop/Skip-Stop, Waiting, optionaler Einsatz, Rückkehr und Ressourcenschutz prüfen. Alten CP-SAT-Pfad regressieren.
- Großen Fall zuerst als CPO exportieren, Startplan prüfen und Engine/Lizenz testen. Community Edition darf nicht umgangen werden; ohne passende Runtime bleibt der große Vergleich ausdrücklich ausstehend.

Die Engine war anfangs nicht installiert. DOcplex 2.32.264 und CPLEX/CP Optimizer Community 22.2.0.1 wurden in der Projekt-venv installiert. Eine Anfrage nach einer vorhandenen unbeschränkten akademischen Runtime ist offen.
