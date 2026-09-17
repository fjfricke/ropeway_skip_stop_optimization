# Exact service-class line master: implementation and pilot finding

Status: 14 September 2026.

## Implemented contract

The experimental pipeline partitions every fixed no-wait line template into
closed dispatch intervals on which the set of feasible canonical rides is
constant.  A Gurobi master chooses integer cabin counts per class and integer
passenger quantities with demand, fleet, visit-segment capacity, and necessary
reservoir-port window constraints.  CP-SAT subsequently assigns the selected
classes to dispatch-ordered cabin slots and finds exact microsecond dispatch
times under the original resource, state, port, and return constraints.

For a successfully timed candidate, an interval-colouring adapter decomposes
the aggregate integer rides into individual cabin ride IDs.  Every exported
plan is checked by the original independent reservoir validator.  Master
objectives and bounds are labelled as belonging to the aggregate no-wait
service-class relaxation until timing and validation succeed.

The implementation is exposed through
`benchmarks/run_reservoir_service_classes.py`.  Existing line solvers and
defaults are unchanged.

## Correctness checks

- Complete tick enumeration confirms that class support changes exactly at
  release and horizon boundaries.
- Configuration rejects incompatible fixed sequences, duplicate class IDs,
  and non-feasibility use of fixed classes.
- A small Gurobi to CP-SAT to certificate round trip preserves the integer
  served count.
- The historical T5R/G800 F2/P0 no-wait certificate with 3,000 served people
  projects into 84 exact classes.  With only these class counts fixed, CP-SAT
  independently reconstructs and validates a 3,000-person plan in 1.59 s.
- The final focused regression run has 80 passing tests, including the existing
  reservoir-line, reservoir CP-SAT, boundary, and package-import tests.

## Model-size gate

The prescribed 15-second release resolution creates substantially more exact
classes than anticipated:

| Catalogue | Templates | Classes | Class-ride variables before master presolve |
|---|---:|---:|---:|
| `small` (three patterns) | 6 | 807 | 435,992 |
| `relevant` (14 patterns) | 28 | 3,190 | 1,501,481 |

The relevant model therefore stops at the explicit default limit of 500,000
class-ride variables and reports `MODEL_SIZE_LIMIT`.  It does not claim
infeasibility.  The limit is configurable for diagnostic builds, but increasing
it does not make the formulation structurally compact.

## First end-to-end result

On the symmetric T5R/G800 F2/P0 case with D=3,000, Kmax=84, seed 0, and the
small catalogue, the master was built with 436,799 integer variables, 8,412
rows, and 1,317,948 nonzeros.  Gurobi proved an aggregate value of 3,000 and
returned three distinct class-count vectors.  All used 84 cabins and mixed
All-Stop with the two complementary patterns.

All three vectors were proven infeasible by the exact CP-SAT timing model in
presolve, each in about 1.5 s.  Consequently this run produced no new valid
incumbent.  In contrast, the projected known 42/42 certificate is timed and
validated immediately.  This isolates the failure: the implementation and
ride decomposition can preserve a valid class plan, while the aggregate master
does not contain enough station-conflict information to select timable class
counts.

## Decision

The exact-class idea is correct but is not a compact replacement for the
integrated passenger objective at the thesis release resolution.  It duplicates
nearly identical ride variables across many narrow dispatch classes and its
current relaxation still proposes physically impossible combinations.

The planned eight-run performance campaign is therefore not continued: its
relevant models fail the pre-search size gate, and the smaller diagnostic model
already fails the master-to-timing gate.  Longer runs cannot repair either
structural result.  The implementation remains as a reproducible negative pilot
and as a precise projection/timing diagnostic.
