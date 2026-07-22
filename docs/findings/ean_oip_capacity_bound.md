# OIP Capacity-Certificate Model Size

Date: 2026-07-22

Base commit: `67aa73b` (dirty worktree containing optimized initial placement)

The optimized-initial-placement capacity layer derives the physical bound

```text
U_pack = sum(ceil(segment_length / required_spacing))
         + one slot per end-of-platform waiting resource
```

An earlier prototype maximized the active fleet in the passenger-free OIP
movement model.
On the synthetic single-station test ring, it proves

```text
U_pack = 4
K_LB = K_UB = K_max^OIP(H) = 4
```

The current eager all-pairs headway artifact does not scale to the physical
packing bounds of the production examples:

| Example | `U_pack` | Visits | Candidates | Headway pairs |
|---|---:|---:|---:|---:|
| Three Station OIP | 214 | 6,848 | 17,120 | 14,646,160 |
| Five Station OIP No-Skip | 260 | 7,280 | 14,560 | 10,673,520 |
| Five Station OIP Skip | 290 | 11,890 | 23,780 | 28,329,810 |

For Three Station, materializing the artifact alone took 27.1 seconds on the
development machine. Each headway pair subsequently creates an order binary
and two disjunctive rows, so full Gurobi model construction is the dominant
obstacle before branch-and-bound starts.

The Five-Station No-Skip max-active run was also attempted with a hard
300-second wall-clock limit.  With `U_pack = 260`, it materialised
10,673,520 pairs, used approximately 4--4.7 GB RAM and timed out during model
construction before Gurobi optimization began.  The 28,329,810-pair Skip case
was therefore not started.

The max-active measurements are retained only as a small-instance reference;
that prototype is no longer a production code path.
The production certificate path is now an exact fixed-K feasibility search:
each probe builds only K active cabins, brackets the largest feasible K and
reports an open interval whenever a probe is unknown.  `U_pack` remains the
conservative upper bound until that interval is closed.
