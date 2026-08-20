# Certified Fixed-K Trajectory Root-CG

This is the production solver contract for the first thesis experiment
campaign. Reservoir dispatch and optimized initial placement remain separate
experimental modes.

## Instance identity

`DddFixedKTrajectoryProblem` fixes the physical network, demand, exact active
fleet size, objective, horizon, waiting domain, operating mode, and initial
state policy. `ALL_STOP` and `SKIP_STOP` use the same skip-capable physical
artifact and the same cabin starts; All-Stop only removes Skip route options.
The fingerprint includes all of these choices.

`canonical_rope` places cabins on stable slots of interstation rope segments
that are common to every route option. Its reported slot capacity is a
conservative capacity of this start constructor, not a global network-capacity
claim. Version 1 rejects entry states with more than one incoming rope.

## Certificate channels

The restricted trajectory LP is solved optimally in every completed round.
Complete pricing gives the proof-safe correction

$$
LB_t = z_t^{RMP} + \sum_c \min\{0,\underline\rho_{ct}\}.
$$

Only a column with reduced cost below the numerical tolerance is normally
added in certified mode. CP-SAT may contribute a complete jointly validated
trajectory package as a primal seed, but never a reduced-cost bound.

The restricted integer master runs in round 1, every third completed round,
at root convergence, and for final polishing. Any time-limited integer
incumbent is validated and may improve the upper bound. The restricted MIP's
best bound is never exported as a global lower bound.

A full root-LP certificate is not an integer-optimality certificate. Integer
optimality is reported only when a validated upper bound meets the certified
root lower bound.

## Runtime safeguards

All setup, seed, LP, MIP, pricing, validation, and polishing time is charged to
one wall-clock budget. Fixed-start pricing is breadth-first over deterministic
tiers: every still-required cabin receives the short tier before any unresolved
one receives a longer tier. A pricing problem is not repeated after an exact
solve, a negative column, or a certified nonnegative lower bound.

Every completed stage checks monotonic lower and upper bounds as well as
`LB <= RMP <= UB`. A violation returns `INTERNAL_CERTIFICATE_ERROR`, marks the
certificate invalid, and exports only the explicit objective floor as the
current safe lower bound.

## Campaign runner

Run the supplied screening matrix with live frontend output:

```bash
.venv/bin/python benchmarks/run_ddd_fixed_k_campaign.py \
  --config benchmarks/configs/five_station_fixed_k_screening.json \
  --progress \
  --frontend-live
```

The default terminal line shows only the certificate interval, restricted-LP
value, pool growth, pricing coverage, MIP activity, and remaining budget. Add
`--verbose-progress` for the complete per-round diagnostic record; the JSON
and live frontend retain all metrics in either mode.

Profiles are fixed and reproducible:

| Profile | Total | Rounds | Pricing tiers | Intermediate MIP | Final MIP | CP seed |
|---|---:|---:|---|---:|---:|---:|
| Screening | 10 min | 30 | 5, 15 s | 15 s | 60 s | 30 s |
| Regular | 60 min | 60 | 5, 15, 60 s | 30 s | 300 s | 120 s |
| Headline | 4 h | 100 | 5, 15, 60, 120 s | 60 s | 1,800 s | 600 s |

For a fleet with at most $K$ cabins, the runner derives prefix envelopes only
from independently solved exact-cardinality cells:

$$
LB^{\le K}=\min_{k\le K}LB^{=k},\qquad
UB^{\le K}=\min_{k\le K}UB^{=k}.
$$

For the minimization benefit $\Delta_K=z_{AS,K}-z_{SS,K}$ it exports

$$
[LB(\Delta_K),UB(\Delta_K)]
=
[LB_{AS,K}-UB_{SS,K},\;UB_{AS,K}-LB_{SS,K}].
$$
