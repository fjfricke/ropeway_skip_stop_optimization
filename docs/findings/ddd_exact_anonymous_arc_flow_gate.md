# Exact anonymous state-time arc-flow gate

Date: 2026-08-26. Implementation branch: `ddd`.

## Question

Can the complete fixed-(K), fixed-start, no-wait MILP remove cabin-label and
visit-layer symmetry without losing exact Passenger optimization or certified
bounds?

## Implemented formulation

The experimental `exact_anonymous` formulation is a quotient of the already
complete labeled time-expanded cabin DAG. Its nodes are exact physical
state-time pairs, not coarse DDD cells. Fixed start slots supply $K$ source
tokens; after those sources, binary Movement flow is anonymous. Exact node
capacity, flow conservation, terminal cardinality, and the original maximal
resource-interval cliques define the Movement polytope.

Direct Passenger multicommodity flow uses the same exact nodes and exact Stop
event times. A complete labeled Passenger seed can be projected onto movement,
boarding, onboard, and alighting variables. Every extracted integer solution
is decomposed into labeled trajectories and independently evaluated by the EAN
Passenger model.

## Correctness gates

- deterministic quotient construction and fingerprints;
- exact half-open resource-clique reuse;
- projection of complete labeled schedules;
- equal integer optima for the $K=1$ and $K=2$ physical Five-Station
  instances;
- independent EAN objective equality after reconstruction;
- explicit rejection of an imported lower bound above a validated incumbent.

## First measured result

On Five-Station architecture B, half demand, Skip-Stop, no waiting, balanced
fixed starts, $K=20$:

| formulation | Movement binaries | Passenger variables | rows | result |
|---|---:|---:|---:|---|
| labeled | 21,630 | 158,925 | 288,435 | optimum 525,730.908 in 24.0 s |
| exact anonymous | 16,250 | 171,010 | 207,596 | optimum 525,730.908 in 134.9 s |

The quotient removes about 24.9% of Movement binaries and about 28.0% of all
rows. Passenger-domain construction also falls from about 6.5 seconds to 0.34
seconds after indexing arc lookup once. This does **not** translate into a
faster solve. A first 60-second screening ended before the anonymous root LP
completed and therefore still reported the objective floor as its bound. The
five-minute follow-up changes that interpretation: the anonymous root
relaxation itself reaches 525,730.908, equal to the integer optimum and to the
labeled optimum. Root processing is the bottleneck. It takes about 121.4
seconds, including a barrier factorization reported at roughly 1.3 GB,
whereas the complete labeled run needs only 24.0 seconds in total. After the
anonymous root finishes, Gurobi closes the integer problem at one explored
node in about six further seconds.

## Decision

The exact anonymous model is correct and useful as a controlled research
alternative, but it does not pass the performance gate as a replacement for
the labeled model: on this instance it is about 5.6 times slower despite being
smaller. The evidence does **not** support the earlier hypothesis of a weak
root objective; it instead identifies expensive root-LP linear algebra as the
limitation. The labeled complete arc-flow and Root-CG certificate path remain
the production defaults. A bounded $K=39$ comparison is now scientifically
meaningful, but should be treated as a scaling experiment rather than as an
expected improvement.
