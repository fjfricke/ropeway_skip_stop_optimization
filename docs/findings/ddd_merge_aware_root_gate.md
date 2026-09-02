# Merge-aware trajectory Root-CG gate

Date: 2026-09-02. Implementation branch: `ddd`.

## Question

Can universal rows restricted to physical Stop/Skip merge resources, together
with a compatible batch of negative trajectory columns, improve the certified
fixed-$K$ trajectory Root-CG enough to justify a Branch-Price-and-Cut tree?

The comparison uses Five-Station architecture B, half demand, No-Wait,
Skip-Stop, balanced fixed starts, and journey-time objective. Every comparison
at a fixed $K$ uses the same `DddFixedKTrajectoryProblem` fingerprint.

## Implemented gate

- a typed row contract distinguishes universal, node-universal, and pool-local
  rows;
- an exact coefficient oracle evaluates resource-window rows on present and
  future whole-horizon trajectories;
- a canonical merge domain derives Stop/Skip reconvergence and FIFO
  provenance from the movement network;
- an optional deterministic MILP selects a mutually compatible subset of
  negative priced candidates;
- exact single-cabin pricing remains the only omitted-column certificate;
- a matched runner compares complete arc-flow LP, pair-only Root-CG,
  universal windows, merge-only windows, and merge-only compatible batches.

## Tiny exactness gate

For `three_station_v0`, $K=1$, all four Root-CG variants converge to
$4{,}072{,}807.999616$. The complete labeled arc-flow LP returns
$4{,}072{,}807.999621$. All Root-CG certificates validate and all variants
also close the integer gap. This establishes coefficient and orchestration
correctness, not scalability.

## Five-Station $K=20$ screening

The complete labeled arc-flow LP solves to $525{,}730.908162$ in about 16--17
seconds. With 120 seconds per Root-CG variant:

| variant | certified LB | RMP | validated UB | rounds | columns |
|---|---:|---:|---:|---:|---:|
| pair-only | 518,241 | 532,711 | 635,520 | 9 | 200 |
| merge-only windows | 510,348 | 533,543 | 635,520 | 8 | 180 |
| all resource windows | 488,713 | 541,870 | 635,520 | 8 | 180 |
| merge windows + compatible batch | 473,590 | 560,183 | 635,520 | 4 | 76 |

The batch MILP itself is cheap. The loss comes from generating three priced
candidates per cabin: pricing time roughly triples, while the compatibility
filter admits fewer columns. Universal rows are mathematically stronger but
their duals also make column discovery tail off earlier under the fixed time
budget.

## Five-Station $K=39$ screening

Fingerprint:
`2f82126c06273d2299ab258ca5c5d92acc9d83d829360422f8473c26521cc0f0`.

Pair-only Root-CG completes eleven rounds in 300 seconds:

- certified LB: $303{,}899$;
- RMP: $318{,}167$;
- validated UB: $1{,}441{,}586$;
- columns after the last update: 468.

Thus the proof channel makes material progress; the remaining LP-side
distance between the last certified LB and RMP is about 4.5%. The global gap
is large because every periodic restricted-MIP solve returns only the original
balanced-start seed.

Merge-only windows leave the RMP at the seed for the first four rounds. The
compatible-batch variant also fails within 300 seconds: four rounds generate
117, 114, 114, and 46 candidates, select only 18, 17, 15, and 13 compatible
columns, and never move the RMP or UB. Its final certified LB remains zero.
The batch does not create a complete compatible 39-cabin replacement; it only
filters finite independently priced candidates.

## Decision

The root gate fails. Do **not** implement a full Branch-Price-and-Cut tree on
the merge-window/batch formulation: each tree node would multiply a Root-CG
process that is already slower and weaker than pair-only at both measured
fleet sizes.

Retain:

- typed proof scopes and the future-column coefficient oracle;
- canonical merge provenance for diagnostics and later branching research;
- the matched gate runner;
- pair-only exact Root-CG as the strongest observed trajectory lower-bound
  engine for $K=39$.

The measured bottleneck is now specifically primal. Independent pricing can
produce a strong fractional bound, but neither the restricted integer master
nor finite candidate batching constructs a better complete 39-cabin
schedule. The next experiment should target a passenger-aware complete
schedule heuristic or a globally coordinated movement neighborhood while
preserving pair-only Root-CG as the independent proof channel. It should not
add more master rows or build a Branch-Price tree before it demonstrably lowers
the validated UB.
