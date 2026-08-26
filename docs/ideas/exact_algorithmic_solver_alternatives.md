# Exact algorithmic alternatives for passenger-guided ropeway scheduling

Status: **research ideas and gated implementation candidates**

## Purpose

The current solver stack can already solve three important subproblems:

- CP-SAT finds complete movement-feasible schedules for comparatively large
  fixed fleets;
- trajectory Root Column Generation (Root-CG) produces certified lower bounds;
- the fixed-timetable Passenger Assignment is comparatively cheap to solve
  exactly.

The unresolved high-density problem is the simultaneous construction of a
good integral Skip-Stop timetable and the closure of its certified Passenger
gap. This note records six algorithmic alternatives that use systematic
search, mathematical bounds, or complete conflict learning. They are distinct
from an unrestricted neighbourhood heuristic, although some can contain
primal heuristics as accelerators.

No method below promises polynomial runtime: the integrated problem is
combinatorial. `Exact` means that a finite declared domain is searched without
discarding admissible solutions and that termination can prove optimality or
infeasibility.

## 1. Resource-clique Branch-Cut-and-Price

### Core idea

Retain one whole-horizon trajectory variable

\[
\lambda_{cp}\in\{0,1\}
\]

for each cabin \(c\) and admissible trajectory \(p\). Exact pricing generates
omitted trajectories. Instead of representing a shared-resource conflict only
by pair rows

\[
\lambda_i+\lambda_j\le 1,
\]

separate maximal resource-time cliques. If all trajectories in \(Q(r,t)\)
occupy capacity-one resource \(r\) at tick \(t\), add

\[
\sum_{(c,p)\in Q(r,t)}\lambda_{cp}\le 1.
\]

For three mutually conflicting trajectories, the pair relaxation admits
\(\lambda_1=\lambda_2=\lambda_3=1/2\), whereas the clique row cuts it off.
Because membership in a resource-time window is a physical predicate, every
omitted trajectory can compute its coefficient during pricing. These rows are
therefore compatible with exact column generation.

If the cut-complete root remains fractional, branch on original physical
decisions that pricing can enforce: Stop/Skip, movement-arc use, event-time
thresholds and eventually resource precedence. Solving pricing and separation
at every open node yields an exact Branch-Cut-and-Price tree with a global
best-node lower bound.

### Relationship to the implementation

The repository already contains:

- exact fixed-start route/load pricing;
- deterministic resource-window separation;
- pricing-compatible resource-window dual terms;
- typed Stop/Skip branch domains and bounded dives.

The first high-density gate was nevertheless run in `PAIR_ONLY` mode because
fixed initial-boundary occurrences were not represented in resource-window
pricing. This missing coefficient has now been implemented: a fixed boundary
occurrence of the priced cabin contributes its constant membership to every
relevant resource-window row, while occurrences of other cabins remain fixed
physical obstacles. No-Wait time-expanded pricing applies active window duals
directly to route arcs instead of constructing redundant membership binaries.

### Evidence and risk

Branch-Cut-and-Price over agent paths and lazily separated resource conflicts
is an established exact MAPF method. It is the closest published algorithmic
analogue to the current trajectory model:

- Lam, Le Bodic, Harabor, and Stuckey (2019), *Branch-and-Cut-and-Price for
  Multi-Agent Pathfinding*, IJCAI, <https://doi.org/10.24963/ijcai.2019/179>.

The main project-specific risk is expensive route/load MILP pricing at every
branch node. A complete tree is built only if clique strengthening materially
improves the root relaxation or integrality.

## 2. Alternative-graph Branch-and-Bound

### Core idea

Represent deterministic movement and minimum-time relations by directed arcs.
Every unresolved capacity-one resource conflict produces two alternative
precedence arcs:

\[
t_j\ge t_i+h
\quad\lor\quad
t_i\ge t_j+h.
\]

A branch selects one alternative. Longest-path propagation computes earliest
event times and exposes infeasible positive cycles or deadlocks. Static and
dynamic implication rules infer additional precedences and prune equivalent
subtrees.

This is an exact scheduling algorithm and is especially natural once bounded
Waiting is enabled. It avoids a large Big-M disjunctive MILP. Stop/Skip route
selection and the non-additive Passenger objective would, however, require an
outer service master or Passenger recourse.

### Evidence and role

- D'Ariano, Pacciarelli, and Pranzo (2007), *A branch and bound algorithm for
  scheduling trains in a railway network*, EJOR,
  <https://doi.org/10.1016/j.ejor.2006.10.034>.
- Lamorgese and Mannino (2015), *An Exact Decomposition Approach for the
  Real-Time Train Dispatching Problem*, Operations Research,
  <https://doi.org/10.1287/opre.2014.1327>.

The most credible use here is an exact movement/timing subsolver beneath a
Passenger-aware master, not an immediate replacement for the complete model.

## 3. Lazy CBS and SMT-CBS

### Core idea

Conflict-Based Search initially plans agents independently. When two plans
conflict, it creates exhaustive children that forbid the conflicting use for
one agent or the other. Lazy CBS and SMT-CBS retain the same completeness but
store reusable nogoods in a CP/SAT layer instead of repeatedly rebuilding
equivalent explicit conflict-tree branches.

### Evidence and limitation

- Sharon, Stern, Felner, and Sturtevant (2012), *Conflict-Based Search for
  Optimal Multi-Agent Path Finding*, AAAI,
  <https://doi.org/10.1609/aaai.v26i1.8140>.
- Gange, Harabor, and Stuckey (2019), *Lazy CBS: Implicit Conflict-Based Search
  Using Lazy Clause Generation*, ICAPS,
  <https://doi.org/10.1609/icaps.v29i1.3471>.

Standard CBS relies on separable per-agent path costs. Ropeway Passenger
Assignment couples cabins through shared demand, ride alternatives and cabin
capacity. CBS is therefore promising for complete movement feasibility and
local timing repair, but would need a more complex outer optimization layer to
certify the integrated Passenger optimum.

## 4. Variable-splitting Lagrangian decomposition

### Core idea

Dualize selected shared-resource and Passenger/Movement coupling constraints.
For fixed multipliers, the problem decomposes into cabin trajectory and
Passenger-flow subproblems. Subgradient, bundle, or volume methods update the
multipliers. Every dual iterate provides a valid lower bound; multiplier-guided
primal recovery constructs feasible schedules.

### Evidence and limitation

- Caprara, Fischetti, and Toth (2002), *Modeling and Solving the Train
  Timetabling Problem*, Operations Research,
  <https://doi.org/10.1287/opre.50.5.851.362>.
- *A variable-splitting Lagrangian decomposition for train timetabling and
  skip-stopping with train-type decision* (2024),
  <https://www.sciencedirect.com/science/article/pii/S0968090X24001669>.

Lagrangian relaxation and Dantzig-Wolfe Column Generation are dual relatives.
If the same coupling is relaxed, this may compute essentially the same root
bound more quickly or in parallel, but does not automatically close the
integer gap. Exactness still needs branching or another enumeration layer.

## 5. Partial-Passenger Branch-and-Benders

### Core idea

Keep a deliberately small but informative Passenger representation in the
timetable master: aggregate station-time demand, coarse capacity allocation,
minimum service and an optimistic Passenger cost. Solve detailed Passenger
Assignment as recourse and return LP optimality cuts plus exact logical cuts
for integer recourse where necessary.

This differs from a weak pure timetable master: partial Passenger information
prevents the master from repeatedly selecting schedules that are obviously
poor for demand before the recourse solve.

### Evidence and limitation

Recent urban-rail work embeds Benders in branch-and-cut and retains partial
Passenger allocations specifically to reduce ineffective feasibility cuts:

- *Integrated demand-side management and timetabling for an urban transit
  system: A Benders decomposition approach* (2025),
  <https://www.sciencedirect.com/science/article/abs/pii/S0191261525002000>.

The current direct-ride Passenger LP is not integral in general, and the
repository's standard LP Benders gate produced weak cuts. A partial-Passenger
master is a materially different and larger formulation, so it remains behind
the resource-clique gate.

## 6. Sparse MDD/SAT compilation

### Core idea

Compile every cabin's feasible time-expanded trajectory domain into a compact
multi-value decision diagram (MDD). Shared prefixes and suffixes are stored
once. Boolean variables select MDD arcs, while resource conflicts are inserted
incrementally as SAT or pseudo-Boolean clauses. Increasing cost or time layers
systematically yields optimality or bounded suboptimality certificates for the
declared grid.

### Evidence and limitation

- Surynek (2022), *Sparse Decision Diagrams for SAT-based Compilation of
  Multi-Agent Path Finding*, SoCS,
  <https://doi.org/10.1609/socs.v15i1.21798>.

This can be very strong for discrete Movement feasibility. Long horizons,
bounded Waiting and integrated Passenger capacities can make the diagrams or
pseudo-Boolean coupling large. It is a fallback compilation experiment, not
the first Passenger-optimization path.

## Ranked research programme

| Rank | Method | Certificate | Fit to current code | Primary risk |
|---:|---|---|---|---|
| 1 | Resource-clique Branch-Cut-and-Price | exact LB/UB and eventual optimality | very high | expensive pricing tree |
| 2 | Alternative-graph Branch-and-Bound | exact movement/timing | medium | Passenger integration |
| 3 | Partial-Passenger Branch-and-Benders | exact if integer recourse is closed | medium | weak or numerous cuts |
| 4 | Lagrangian decomposition | certified dual bound | medium-high | same relaxation, primal recovery |
| 5 | Lazy CBS / SMT-CBS | exact movement | medium | nonseparable Passenger cost |
| 6 | Sparse MDD/SAT | exact declared discrete domain | low-medium | horizon and Passenger coupling |

## Implemented root gate

The experiment extended the existing fixed-start, fixed-\(K\), No-Wait
Root-CG only:

1. account exactly for fixed boundary occurrences in resource-window rows and
   pricing;
2. run pair fallback plus maximal resource-window separation;
3. confirm tiny-instance integer equivalence and reduced-cost equality;
4. compare \(K=20\) and boundary case \(K=39\) against `PAIR_ONLY`;
5. record root lower bound, fractional option mass, windows, pairs, pricing
   time, Restricted-MIP incumbent and total runtime.

### Results

The boundary-aware implementation passed exact reduced-cost comparison against
exhaustive pricing. It also exposed an important algorithmic distinction:

| instance and budget | final certified LB | validated UB | columns | resource windows | observation |
|---|---:|---:|---:|---:|---|
| Five-Station B, \(K=20\), 180 s | 512,709.7 | 635,520.0 | 240 | 692 | RMP moves after several rounds |
| Five-Station B, \(K=39\), 180 s | 0.0 | 1,441,586.4 | 231 | 394 | RMP remains at the integral seed |
| Five-Station B, \(K=39\), pair-only reference | 315,690.6 | 1,441,586.4 | 568 | 0 | root LP certified in about 340 s |

At \(K=39\), the clique rows make the restricted master very strong, but the
current independent pricing step returns one best trajectory per cabin. Those
trajectories have negative reduced cost individually yet are mutually
incompatible, so the RMP cannot replace the seed by a complete new schedule.
The pricing correction consequently remains at the objective floor. Switching
the RMP to barrier duals did not change this behaviour. Skipping zero-dual rows
and applying No-Wait row coefficients directly on route arcs reduced a
post-separation pricing round from roughly 475 seconds to roughly 30 seconds,
but did not solve the coordination problem.

### Decision

The resource-window formulation is exact and remains useful as a strengthening
component. The current gate does **not** justify building a complete
Branch-Cut-and-Price tree on top of one-best-column pricing: every tree node
would inherit the same heading-in/coordination problem.

The next meaningful gate inside this method family is coordinated column
generation: obtain several sufficiently different negative-reduced-cost
trajectories per cabin, or solve a restricted multi-cabin pricing/repair
problem that returns a jointly compatible batch. It must first improve the
\(K=39\) RMP and certified bound within a fixed root budget. If that gate also
fails, the next independent exact spike is the alternative-graph
movement/timing solver rather than a larger Branch-Cut-and-Price tree.

### Multi-column and coordinated-primal follow-up

Sequentially generating up to three negative columns per cabin did not resolve
the K=39 clique pathology. In five minutes it stored 468 columns and 1,703
resource windows, yet the RMP stayed at the original 1,441,586.4 and the
corrected lower bound stayed at zero. The experiment also exposed that the old
extra-column loop did not clamp each solve to the remaining global budget;
that defect has been corrected.

The next implementation therefore reuses the complete CP-SAT movement model
as a strictly primal coordinated generator. A deterministically balanced set
of the strongest Passenger-dual ride preferences guides CP-SAT, but the model
still enforces all cabin trajectories and physical resource conflicts jointly.
Every returned complete schedule is independently converted and validated,
then all of its trajectory columns enter the RMP as one package. This heuristic
signal never enters the reduced-cost certificate:

\[
LB^{\mathrm{root}}
\quad\text{uses only exact per-cabin proof pricing, while}\quad
UB\quad\text{may use validated CP packages.}
\]

With 200 balanced preferences and a validated incumbent as CP hint, a
three-minute K=39 clique run generated three complete packages. The RMP fell
from 1,441,586.4 to 1,379,312.8 and the validated UB to 1,380,616.0. Running CP
only every third round improved the five-minute UB further to 1,374,088.5, but
the clique-based corrected LB still stayed at zero. The evidence therefore
supports coordinated packages as a primal channel, not resource cliques as the
default proof channel. The next combined gate uses the established pair-only
Root-CG for the lower bound and invokes coordinated CP only periodically for
upper-bound improvement.

That combined K=39 gate passed. With a ten-minute budget, pair-only proof
pricing, a 20-second coordinated CP call every fifth round, 200 balanced
preferences and one candidate package per call, Root-CG closed the same exact
root value as the earlier reference:

| quantity | pair-only reference | coordinated hybrid |
|---|---:|---:|
| certified root LB | 315,690.6 | 315,690.6 |
| validated UB | 1,441,586.4 | 1,326,950.7 |
| certified integer gap | 78.10% | 76.21% |
| root rounds | 15 | 17 |
| runtime | about 340 s | about 530 s |

Thus the coordinated channel improves the incumbent without weakening the
eventual proof certificate or exhausting the declared budget. It is now the
preferred exact-root/primal hybrid for the next calibration experiments. It
still does not close the large integer gap; a full Branch-Price tree or a
stronger fix-and-optimize mechanism remains a separate decision.

### Fixed-K calibration on two demand levels

The next screening campaign used the same physical architecture-B ring,
balanced fixed starts, no waiting, pair-only proof rows, a ten-minute budget,
and one 20-second coordinated CP call every fifth round. It compared exact
fleet sizes 20, 38, and 39 under 64 and 128 passengers per OD pair. The
all-stop capacity certificate is

$$
K_{\max}^{AS}=38.
$$

The exact-$K$ results were:

| demand | mode | $K$ | certified LB | validated UB | gap | status |
|---|---|---:|---:|---:|---:|---|
| half | all-stop | 20 | 635,520.0 | 635,520.0 | 0.00% | integer optimal |
| half | skip-stop | 20 | 525,730.9 | 631,494.5 | 16.75% | root LP certified |
| half | all-stop | 38 | 399,287.3 | 399,287.3 | 0.00% | integer optimal |
| half | skip-stop | 38 | 331,476.4 | 399,287.3 | 16.98% | root LP certified |
| half | all-stop | 39 | -- | -- | -- | movement infeasible |
| half | skip-stop | 39 | 315,690.6 | 1,381,788.5 | 77.15% | root LP certified |
| full | all-stop | 20 | 1,866,349.1 | 1,866,349.1 | 0.00% | integer optimal |
| full | skip-stop | 20 | 1,737,454.5 | 1,737,454.5 | 0.00% | integer optimal |
| full | all-stop | 38 | 1,339,294.6 | 1,339,294.6 | 0.00% | integer optimal |
| full | skip-stop | 38 | 1,107,175.5 | 1,339,294.6 | 17.33% | time limit |
| full | all-stop | 39 | -- | -- | -- | movement infeasible |
| full | skip-stop | 39 | 1,045,570.3 | 2,906,554.7 | 64.03% | time limit |

This yields two distinct thesis-grade statements. At full demand and $K=20$,
Skip-Stop improves the objective by exactly

$$
1{,}866{,}349.1-1{,}737{,}454.5=128{,}894.5,
$$

or about 6.91%. At $K=39$, all-stop is analytically infeasible while Skip-Stop
has a validated schedule for both demand levels, proving a capacity advantage
without claiming objective optimality.

The calibration also identifies the remaining algorithmic bottleneck. Root
proofs close reliably through $K=39$, but above the all-stop capacity no strong
all-stop incumbent exists. Periodic CP packages then improve the upper bound
only slowly. The next primal experiment should therefore keep pair-only proof
pricing unchanged and increase coordinated-package frequency (for example,
every third round), followed by fix-and-optimize over whole package
neighbourhoods. A Branch-Price tree is justified only if this stronger primal
gate still leaves the $K=39$ upper bound far from the certified root value.

### Exact anonymous state-time flow follow-up

A separate exact formulation spike quotiented the complete labeled no-wait
arc-flow by physical `(state, tick)` and integrated direct Passenger flow on
the quotient. Tiny $K=1,2$ cases matched the labeled integer optimum and every
reconstructed timetable passed independent EAN validation. At Five-Station B,
$K=20$, it reduced Movement binaries by about 25% and all rows by about 28%.
A first 60-second screening ended before root processing and misleadingly
showed only the objective floor. A five-minute follow-up proved the same exact
525,730.908 optimum in 134.9 seconds, compared with 24.0 seconds for the
labeled formulation.

The anonymous root objective is therefore not weaker on this instance: it
equals the integer optimum. The bottleneck is root-LP linear algebra, which
takes about 121.4 seconds before Gurobi closes the MIP at one explored node.
The anonymous formulation remains available as `--formulation
exact_anonymous`, but is not the next production default because it is about
5.6 times slower on the first representative gate. A bounded $K=39$ run may
still test scaling, without assuming that fewer rows imply a faster solve.
