# Fractional cabin-neighborhood primal gate

## Question

Can the certified Pair-only trajectory Root-CG obtain substantially better
integer schedules by fixing the current incumbent for most cabins and jointly
reoptimizing only a small Passenger-guided cabin cohort?

The gate used the Five-Station architecture-B half-demand No-Wait instance,
balanced-reference starts, exact fixed K, Pair-only proof pricing, and the
screening budget. Cohort sizes cycled through 4, 8, and 12 cabins. Every CP
candidate was reconstructed and validated as a complete movement schedule and
then evaluated by a dedicated fixed-movement Passenger MIP before it could
update the upper bound.

Output:
`benchmarks/output/ddd_fixed_k_campaigns/five_station_b_half_demand_fixed_k_neighborhood_gate_v2`.

## Results

| K | Time | Root LB | Initial UB | Final UB | Final gap |
|---:|---:|---:|---:|---:|---:|
| 20 | 278.8 s | 525,730.908 | 635,519.998 | 635,519.998 | 17.28% |
| 39 | 469.0 s | 315,690.634 | 1,441,586.411 | 1,403,873.988 | 77.51% |

At K=20, all six neighborhoods returned complete feasible packages, but none
improved the All-Stop incumbent. The package objectives were approximately
635,520 for 4- and 8-cabin cohorts and 635,631--636,117 for 12-cabin cohorts.
The proof side nevertheless converged to 525,730.908, equal to the known
complete arc-flow optimum for this fingerprint. The remaining gap is therefore
entirely the failure to reconstruct the integer combination, not a weak root
bound.

At K=39, the 12-cabin neighborhood in round 7 improved the directly evaluated
UB to 1,434,511.100. After these package columns entered the persistent pool,
the forced Restricted MIP combined them into a better schedule with
UB 1,403,873.988 in round 11. This is a 2.62% improvement over the periodic
seed. The root LB converged unchanged to 315,690.634.

## Interpretation

The implementation contract is successful:

- package search changes no proof bound;
- every exported UB has complete movement and Passenger provenance;
- direct package evaluation exposes improvements that need not be found by the
  large Restricted MIP immediately;
- admitting a package can also improve a later Restricted-MIP combination;
- checkpoint/resume exposed and fixed duplicate-No-Good and seed/resume edge
  cases.

The small whole-horizon cabin cohort is not sufficient as the sole primal
method. Fixing 27--35 complete cabin routes at K=39 leaves little freedom to
change merge sequences, while the K=20 optimum evidently requires coordinated
changes across more than 12 cabins. The earlier global coordinated-CP result
of 1,326,950.7 at K=39 also remains stronger than this isolated cohort gate.

## Decision

Retain the cabin-cohort optimizer as a cheap optional intensification channel,
but do not build a Branch-Price tree from it. The next Stage-B mechanism is now
implemented: it releases many or all cabins in one physical merge/time corridor
while fixing route decisions outside that corridor. This preserves local model
size while allowing a system-wide merge sequence to change. Its gate compares:

1. Pair-only Root-CG without a primal accelerator;
2. global coordinated CP packages;
3. cabin cohorts;
4. corridor neighborhoods plus global packages.

Only after one of these produces material K=20 and K=39 UB progress should a
limited Branch-Price-and-Cut tree be reconsidered.

## Merge/time corridor K=20 gate

The first matched K=20 gate compared Pair-only Root-CG with the implemented
single-merge-family/time-corridor channel. Both variants certified the same
Root LP:

| Quantity | Pair only | Merge/time corridor |
|---|---:|---:|
| certified LB | 525,730.908 | 525,730.908 |
| validated UB | 635,519.998 | 635,519.998 |
| integer gap | 17.275% | 17.275% |
| Root-CG rounds | 19 | 19 |
| final columns | 367 | 346 |
| solve time | 318.2 s | 364.8 s |

Seven corridor calls released all 20 cabins but only 101--105 local route
decisions out of roughly 445 incumbent decisions. Six neighborhoods were
proved exhausted in less than one second. One produced a complete alternative
package and two new columns, but its exact Passenger value equalled the existing
All-Stop UB. The corridor CP calls consumed only 4.24 seconds in total; the
runtime difference arose mainly from a different Root-CG column sequence and
larger LP/pricing time, not from CP stalling.

The gate therefore rejects a single merge-family corridor as the sole K=20
primal accelerator. The result suggests that useful Passenger improvements
need linked changes at multiple station merges or over a visit/time band, so a
cabin can alter both boarding and alighting service. Do not start the K=39
headline gate with the unchanged single-family selector. The next primal gate
must either release a Passenger-linked multi-merge corridor or import a complete
arc-flow/CP incumbent before testing K=39.
