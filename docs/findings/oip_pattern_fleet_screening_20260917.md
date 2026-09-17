# OIP pattern and fleet screening: technical F2 result

## Result

The frozen screening completed all 18 trials in 716 seconds. Eleven pattern/K
combinations produced independently valid movements. Their fixed-movement
passenger assignments were solved to optimality. Five trials ended `UNKNOWN`
without a movement and two were proven infeasible under the exact-K,
No-Wait contract.

| K | Allocation | Movement | Served | Journey time (person-s) |
|---:|---|---|---:|---:|
| 40 | All-Stop | feasible | 1,220 | 3,939,898.030 |
| 40 | Direct | feasible | 1,510 | 3,550,511.330 |
| 40 | Four-stop | feasible | 1,307 | 3,761,642.749 |
| 40 | Direct + Four-stop | feasible | 1,450 | 3,634,876.710 |
| 40 | Direct + All-Stop | feasible | 1,350 | 3,746,203.300 |
| 40 | Four-stop + All-Stop | feasible | 1,247 | 3,778,468.189 |
| 50 | All-Stop | feasible | 1,547 | 3,515,620.800 |
| 50 | Direct | feasible | 1,940 | 2,998,138.450 |
| 50 | Four-stop | feasible | 1,667 | 3,383,353.160 |
| 50 | Direct + Four-stop | unknown | — | — |
| 50 | Direct + All-Stop | unknown | — | — |
| 50 | Four-stop + All-Stop | unknown | — | — |
| 62 | All-Stop | feasible | 1,907 | 3,113,788.287 |
| 62 | Direct | feasible | 2,347 | 2,748,992.446 |
| 62 | Four-stop | infeasible | — | — |
| 62 | Direct + Four-stop | unknown | — | — |
| 62 | Direct + All-Stop | unknown | — | — |
| 62 | Four-stop + All-Stop | infeasible | — | — |

The direct allocation dominates the other found movements at each tested K.
The result is still sensitive to the first movement returned by CP-SAT: the
passenger optimum is exact for that movement, not over all initial placements.
Consequently, 2,347 served at K=62 is a validated incumbent and not a capacity
bound for the direct allocation.

The mixed allocations become substantially harder from K=50 onward. Their
`UNKNOWN` outcomes must not be read as infeasibility. The two K=62
infeasibility proofs show that requiring every available cabin can itself make
a fixed allocation impossible; later capacity experiments should therefore
also test smaller exact K or an explicit up-to-K variant.

## Next experiment suggested by this screening

Use the direct allocation as the first F2 incumbent generator and refine K near
50–62. If mixed patterns remain relevant, improve movement quality or add
Waiting before expanding their proportions. Do not infer the value of Waiting
from this No-Wait campaign and do not promote the first feasible movement to a
pattern optimum.
