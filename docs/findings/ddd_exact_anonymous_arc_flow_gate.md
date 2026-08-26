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

| formulation | Movement binaries | Passenger variables | rows | 60 s result |
|---|---:|---:|---:|---|
| labeled | 21,630 | 158,925 | 288,435 | optimum 525,730.908 in 24.0 s |
| exact anonymous | 16,250 | 171,010 | 207,596 | LB 0, seeded UB 635,520 after 60 s |

The quotient removes about 24.9% of Movement binaries and about 28.0% of all
rows. Passenger-domain construction also falls from about 6.5 seconds to 0.34
seconds after indexing arc lookup once. This does **not** translate into a
stronger solve. The labeled candidate-flow relaxation reaches the exact root
bound quickly, whereas fractional anonymous Movement can split and re-pair
flow at exact nodes. Node capacity prevents that behavior only after
integrality.

## Decision

The exact anonymous model is correct and useful as a controlled research
alternative, but it fails the first production gate. It must not replace the
labeled complete arc-flow or the Root-CG certificate path. No long $K=39$
campaign is justified before a proof-strengthening mechanism closes this root
relaxation deficit. Reintroducing source commodities would remove much of the
symmetry gain; taking the convex hull of source paths leads back toward
Dantzig--Wolfe/trajectory column generation. This negative result therefore
supports retaining the labeled candidate structure for the immediate thesis
experiments.
