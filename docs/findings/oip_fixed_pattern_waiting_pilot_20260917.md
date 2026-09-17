# OIP-EAN fixed-pattern Waiting pilot

The frozen T5R/G500-B pilot completed all twelve planned trials on 17 September
2026.  Every trial used K=62, the F2/P0 technical load of 3,210 passengers, the
1 ms movement grid, a 2,364 s passenger horizon, and physical continuation to
2,664 s.  Movement feasibility and fixed-movement passenger assignment were
kept separate.

| Pattern allocation | Waiting cap | CP-SAT movement | Gurobi movement | Served after validation |
|---|---:|---|---|---:|
| 62 All-Stop | 0 s | feasible, 7.72 s search | no incumbent | 1,907 |
| 31 `{S1,S3}` + 31 `{S2,S4}` | 0 s | feasible, 6.23 s search | no incumbent | 2,347 |
| 16/16 direct + 30 All-Stop | 0 s | unknown | no incumbent | — |
| 62 All-Stop | 120 s | unknown | no incumbent | — |
| 31 `{S1,S3}` + 31 `{S2,S4}` | 120 s | feasible, 29.14 s search | no incumbent | 2,300 |
| 16/16 direct + 30 All-Stop | 120 s | unknown | no incumbent | — |

The passenger figures are optimal assignments for the single movement found in
the corresponding trial.  They are not optima over initial positions.  The
No-Wait and Waiting movements therefore cannot be compared as if they differed
only in Waiting.  The feasible Waiting movement used one 120 s hold; its
movement certificate and passenger assignment both passed the independent
validators.

CP-SAT produced three valid movements in six attempts.  Its movement-model
builds took 1.22–1.49 s.  No negative CP-SAT outcome was an infeasibility proof.
The mixed allocation was harder than either homogeneous allocation, and adding
Waiting made All-Stop unresolved within the same budget.

Gurobi found no movement incumbent in six attempts.  Even after fixed-pattern
pruning, its models contained about 555,000–1,361,000 variables and
1.39–3.01 million constraints.  Setup alone took 22–51 s, leaving only 1–33 s
of the 60 s budget for search.  Under this contract Gurobi is therefore not a
competitive short-budget feasibility generator.

The result supports the corrected CP-SAT EAN as a fixed-pattern start-solution
generator.  It also shows that a 120 s Waiting domain is materially harder and
does not by itself improve a first arbitrary feasible phase.  A causal Waiting
comparison would require fixed initial positions or an optimization objective
over phases, rather than one first-feasible movement per domain.

The machine-readable campaign is stored in
`results/oip_pattern_waiting_pilot_20260917_v2/campaign.json`.  All twelve run
directories retain their movement status, model metrics, actual Waiting use,
and passenger-evaluation status separately.
