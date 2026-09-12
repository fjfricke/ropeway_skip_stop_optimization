# Reservoir DP pilot: first findings

Stand: 12.09.2026.

## Result

The implementation now constructs and independently validates positive Max50
R2 plans with variable fleet size and unrestricted legal waiting. It has not
produced a competitive large-instance incumbent. The best observed pilot
served 335 of 3,074 passengers, compared with 2,496 in the frozen external
reference plan. A full five-minute run was worse and served only 195.

| Formulation state | Search | Budget | Best served | Used fleet | Peak RSS | Progress |
|---|---|---:|---:|---:|---:|---|
| initial `symbolic_visits`, all K chosen at root | dual CABS, width 128 | completed in 0.29 s | 0 | 0 | 158 MB | only zero-fleet solution |
| same, width 1,024 | dual CABS | completed in 3.22 s | 0 | 0 | 1.27 GB | only zero-fleet solution |
| lazy fleet, cubic STN | primal CABS, width 512 | 30 s | 64 | 4 | 2.62 GB | 40, 48, 56, 64 |
| lazy singleton whole-trip masks, cubic STN | primal CABS, width 512 | 30 s | 88 | 3 | 3.55 GB | 40, 72, 88 |
| grouped whole-trip masks, incremental STN | primal CABS, width 512 | 30 s nominal | **200** | 7 | 15.31 GB | 40, 80, 104, 128, 152, 176, 200 |
| same, discard old layer registries | primal CABS, width 512 | 30 s | **296** | 7 | 1.13 GB | 72, 80, 96, 112, 152, 192, 232, 272, 296 |
| same, discard old registries | primal CABS, width 512 | stopped at width limit after 79 s | **335** | 10 | 1.23 GB | 296 at 26.6 s, 320 at 37.7 s, 327 at 50.0 s, 335 at 63.8 s |
| same, discard old registries | primal CABS, width 2,048 | stopped at width limit after 17 s | 112 | 3 | 1.62 GB | last improvement at 9.6 s |
| same, effectively unbounded width | primal CABS, width up to 65,536 | **300 s** | 195 | 4 | 14.89 GB | 168 at 30.0 s, 195 at 101.0 s; then 199 s without progress |
| same, 12 workers | primal CAHDBS2, width 512 | completed in 8.55 s | 192 | 4 | 0.88 GB | maximum width reached |
| same, 12 workers | primal CAHDBS2, width 2,048 | 30 s | 208 | 4 | 3.67 GB | 64, 96, 120, 152, 160, 208 |
| same formulation, proof-oriented ordering | dual CABS, width 128 | completed in 0.15 s | 28 | 2 | 172 MB | served upper bound 3,074 |

The last native call returned after 34.2 seconds because a large beam layer is
only cooperatively interruptible. The Python supervisor observed 35.0 seconds
wall time, below its five-second shutdown allowance.

All reported final plans passed the unchanged physical and integer-passenger
validator. The strongest plan used stop mask 10 (`B+D`) for all seven cabins.
No reference schedule was used as a native solution or counted as progress.

## What the experiments established

The first zero-service plateau had two formulation causes rather than a
physical infeasibility:

1. Selecting K=0,...,50 at the root duplicated the same first-cabin search up
   to 50 times. Lazy activation removed that duplication while preserving every
   fleet size.
2. Complementary demand encouraged commitments close to the horizon. Their
   impossibility became visible only at the future destination. Safe
   minimum-arrival constraints now reject them at boarding.

Demand release buckets also created many equivalent partial load allocations.
An explicit “close boarding” transition represents all remaining zero choices
in one step without merging groups or changing the feasible set.

The largest speed change came from replacing a full `O(n^3)` temporal closure
after every constraint with the exact incremental `O(n^2)` update. In the same
30-second scale, the pattern model improved from 104 to 200 served and reached
seven instead of three cabins. It also expanded about 1.42 million states. The
extra throughput converted directly into memory pressure because complete STN
matrices are retained in beam states.

Clearing RPID's duplicate registry between beam depths improved the same profile
from 200 to 296 served and reduced peak RSS from 15.31 to 1.13 GB. This setting
forgets cross-depth duplicate information; it does not remove a transition or
add a dominance relation. It is therefore the recommended primal setting.

Twelve workers expanded 4.24 million states at width 2,048, but produced only
208 served. The serial width-512 run produced 296 from 2.17 million expansions.
Parallel throughput therefore did not translate into better beam diversity in
this deterministic pilot. One worker is the current empirical recommendation.

The explicit five-minute test removed the small maximum-width stop by setting
the cap to 65,536. It expanded 25.31 million states, generated 31.60 million,
and used 14.89 GB at peak. The incumbent improved to 168 at 30 seconds and 195
at 101 seconds, then remained unchanged for the final 199 seconds. A separate
width-512 run reached 335 in 63.8 seconds and stopped at its width limit after
79 seconds. Thus more time, states, and memory did not yield a monotonically
better incumbent. Separate native processes can resolve equal-priority states
differently, and RPID exposes no seed for this search path; maximum beam width
is therefore not a reproducible quality knob in the current integration.

The corrected proof-oriented run retained the safe global served upper bound of
3,074 and stopped at its configured maximum beam width. In unserved notation
that is still only the trivial lower bound zero. It therefore provides no useful
large-instance gap closure at this width.

`pattern_groups` found the human-relevant `B+D` pattern without a supplied
pattern seed and outperformed free visit choices in the short pilots. It did
not yet retain a complementary `C+E` group. This is evidence that pattern
restriction improves incumbent direction, but not evidence that the current DP
can scale to 38–50 cabins.

## Decision

The pilot passes the small correctness and independent-validation gates and is
worth keeping as an experimental backend. It currently fails the practical
large-instance gate: 200 served is far below both the 2,496 reference and the
level needed for the thesis comparison. A long run with the current state
representation is unlikely to bridge that difference because memory reached
15.3 GB at only seven used cabins.

Even the best observed value of 335 remains far below the 2,496 reference at
the same problem scale. The five-minute experiment also shows that merely
raising the width and runtime is not a credible route across that gap. CP-SAT
or the validated reference therefore remains the practical source of large
incumbents for the current thesis experiments.
