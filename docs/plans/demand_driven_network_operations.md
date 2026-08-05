# Demand-Driven Network Operations Planner

Status: **proposed research and implementation plan**

Research snapshot: **2026-07-23**

## Decision Summary

The next prototype should not be another globally integrated cabin-indexed
MILP. It should test a substantially simpler planning architecture:

```text
physical movement network + demand profile + operating parameters
    -> anonymous service intentions
    -> continuous-time reservation decoder
    -> feasible cabin trajectories
    -> exact fixed-timetable passenger assignment
    -> passenger-guided local improvement
```

The core experiment is a **continuous-time, reservation-based schedule
generator with limited local repair**. A compact service plan specifies route,
stop/skip, and priority choices without exact times or cabin identities. The
decoder assigns physical cabins, schedules each selected route through free
resource intervals, and writes reservations immediately. A complete decoded
plan is then evaluated using the existing fixed-movement passenger optimizer.

This combines four ideas that have already worked in related domains without
requiring their most sophisticated exact machinery:

- safe-interval and reservation-table planning from multi-agent pickup and
  delivery;
- serial schedule generation and local repair from resource-constrained and
  job-shop scheduling;
- passenger-oriented stop-pattern improvement from railway planning;
- rolling-horizon replanning from warehouse, elevator, AGV, and dial-a-ride
  operations.

The first implementation is deliberately **not** Benders decomposition,
full CBS, column generation, or a new full time-expanded MILP. Alternative
graphs and bounded CBS remain possible local repair engines after the decoder
has established whether the basic architecture works.

## Target Contract

The intended public input is:

1. a physical `Scenario`, deterministically converted to an
   `EanMovementNetwork`;
2. a demand profile with origin, destination, release time, and passenger
   count;
3. operating parameters that cannot be inferred from topology alone:
   horizon and tail semantics, cabin capacity, fleet limit or depot supply,
   headways, waiting policy, and the passenger objective.

No manually designed skip-stop example or prescribed service pattern should
be required. The planner may derive candidate circulations, route options, and
stop patterns internally from the physical network.

The output is:

- an `EanMovementPlan` containing explicit cabin identities only after
  decoding, complete visit decisions, and continuous event times;
- an `EanPassengerServicePlan` and passenger assignment;
- validation results for topology, movement continuity, horizon semantics,
  resource reservations, and every final headway;
- solution metrics and an explicit heuristic status.

The status contract must distinguish:

```text
FEASIBLE_HEURISTIC
  a complete plan passed movement, reservation, and headway validation

CONSTRUCTION_FAILED
  the selected heuristic could not decode a plan in its budget

INVALID_INTERNAL
  the decoder produced a plan that failed independent validation
```

`CONSTRUCTION_FAILED` must never be reported as mathematical infeasibility.

## Why This Problem Has No Single Perfect Analogue

The ropeway problem combines aspects that are normally separated:

- homogeneous vehicles move repeatedly through a shared physical network;
- stop, skip, waiting, turnback, and rope-transfer decisions change travel
  times and resource use;
- short headways create many potential conflicts;
- cabins carry multiple passengers with different OD pairs;
- passenger assignment and vehicle stopping decisions affect one another;
- a finite-horizon plan is required, not necessarily a periodic plan;
- exact physical feasibility matters, but global optimality is not required.

No reviewed paper covers all of these properties simultaneously. The useful
conclusion is therefore architectural: use the service-assignment methods from
passenger transport and the conflict-free decoding methods from AGV/MAPF and
railway scheduling, while retaining an independent physical validator.

## Closest Related Problems and Transferable Lessons

### 1. Passenger-Oriented Line Planning and Timetabling

This literature directly addresses the trade-off that motivates skip-stop:
stopping benefits boarding and alighting passengers, while skipping benefits
through passengers and can release vehicle or infrastructure capacity.

Kaspi and Raviv integrate line planning and timetabling and solve the model
with a cross-entropy metaheuristic. Their Israel Railways case reports a 20%
reduction in average passenger journey time with the same resources
([paper](https://doi.org/10.1287/trsc.1120.0424)). The relevant lesson is not
the particular metaheuristic, but that a compact service/timetable
representation can be searched directly against a passenger objective without
proving global optimality.

The Copenhagen stopping-pattern study alternates a stopping-pattern problem
with schedule-based passenger assignment. It reports a 3.2% reduction in
generalized passenger cost on a large urban rail network
([paper](https://doi.org/10.1016/j.tra.2018.04.012)). This is strong evidence
for evaluating a proposed operating plan with a separate passenger-routing
model and feeding the result back into the service search.

Cao and Ceder jointly optimize skip-stop timetabling and vehicle scheduling
for autonomous shuttle buses on a circular route. Their case study reports
1.83% lower passenger travel time and 8.11% fewer vehicles
([paper](https://doi.org/10.1016/j.trc.2019.03.018)). The route is much simpler
than a ropeway network and lacks guideway conflicts, but the service design,
finite operating horizon, capacity, and skip-stop trade-off are unusually
close to the target problem.

Train timetabling with stop-skipping, passenger flows, and platform choices
has also been formulated as a constrained multi-commodity flow on a
time-space network and solved with Lagrangian heuristics
([paper](https://doi.org/10.1016/j.trb.2021.06.001)). This supports a
decomposed heuristic, but it does not justify building another full
time-expanded ropeway model as the first experiment.

**Transferable lesson:** search over service decisions and evaluate them with
a passenger model. Do not require the detailed physical scheduler to discover
the passenger-service structure and all conflict orders simultaneously.

### 2. Multi-Car Elevators

Multi-car elevators are a surprisingly close physical analogue: multiple
vehicles share a constrained guideway, serve passenger calls, choose stops,
and must avoid interference. Tanaka, Hoshino, and Watanabe separate
optimization-based collision/reversal avoidance from simple immediate or
delayed passenger-call allocation policies
([paper](https://doi.org/10.1007/s10696-016-9238-6)).

Elevator dispatch with destination information is commonly solved in a
rolling horizon. A static subproblem repeatedly redesigns car routes from the
currently known requests; assignment formulations can leave the request order
to a dispatch heuristic
([paper](https://doi.org/10.1016/j.ejor.2016.01.019)). Earlier work explicitly
uses a two-level formulation with passenger-to-elevator assignment above
single-elevator dispatching
([paper](https://doi.org/10.1109/TASE.2007.895217)).

Elevators have simpler topologies, fewer vehicles per shaft, and different
boarding rules. Nevertheless, their deployed-algorithm philosophy is highly
relevant: use a fast assignability test and a collision-safe dispatcher rather
than repeatedly solving the complete integrated problem.

**Transferable lesson:** a simple high-level passenger/service assignment can
work when every decision is checked by a fast low-level route and collision
scheduler.

### 3. Lifelong Multi-Agent Pickup and Delivery

Multi-agent pickup and delivery separates task assignment from collision-free
path planning. It is structurally similar to assigning passenger-serving
movements to homogeneous cabins, although warehouse robots normally carry one
or a few discrete loads rather than a shared passenger capacity.

Ma et al. introduce lifelong MAPD and show that token-passing variants remain
efficient with hundreds of agents and tasks
([paper](https://arxiv.org/abs/1705.10868)). Their later SIPP with Reservation
Table method plans continuous movements with kinematic constraints and reports
hundreds of agents and thousands of tasks in seconds
([paper](https://doi.org/10.1609/aaai.v33i01.33017651)).

Li et al.'s Rolling-Horizon Collision Resolution decomposes lifelong MAPF into
bounded-window collision problems and reports high-quality plans for up to
1,000 warehouse agents at 38.9% map occupancy
([paper](https://arxiv.org/abs/2005.07371)). The absolute scale is not directly
transferable because grid conflicts differ from station merges, but it is
strong evidence that bounded collision horizons are more scalable than a
single global multi-agent solve.

Chen et al. couple capacitated task assignment and path planning by evaluating
assignments with their actual collision-free routing cost and improving them
with Large Neighborhood Search
([paper](https://doi.org/10.1109/LRA.2021.3074883)). This is almost exactly the
proposed feedback loop: service choices must be judged by the schedule they
actually produce, not only by uncongested lower-bound travel times.

Zahradka et al. compare an integrated multi-agent multi-item pickup-and-delivery
problem with a naive assignment-then-routing decomposition and find that the
decoupled method is near-optimal in a wide range of tested cases
([paper](https://doi.org/10.1609/socs.v15i1.21802)). This does not prove that
decomposition is sufficient here, but it justifies testing it before building
a complex integrated exact method.

**Transferable lesson:** prioritized reservation planning gives solutions very
quickly; actual conflict-aware costs and LNS can recover much of the quality
lost by initial decomposition.

### 4. Safe-Interval and Reservation-Based Routing

Safe Interval Path Planning represents time at a physical state by maximal
collision-free intervals rather than by every time step. The original SIPP
paper shows that this preserves single-agent completeness and optimality
against fixed dynamic obstacles while greatly reducing the search space
([paper](https://www.cs.cmu.edu/afs/cs/Web/People/maxim/files/sipp_icra11.pdf)).

For this project, already planned cabins act as dynamic obstacles. A resource
calendar contains their occupied or headway-blocked intervals. A new cabin can
therefore be planned in continuous time without creating a global time grid.

This is more appropriate than literal grid MAPF because ropeway movements are
already expressed as a small graph of movement states and route options with
deterministic or bounded travel times. Waiting is permitted only at explicitly
modelled locations.

**Transferable lesson:** replace a full time expansion by the complement of a
small set of reservation intervals, and plan one trajectory against those
intervals.

### 5. Conflict-Free AGV Routing

AGV systems combine task assignment, repeated vehicle movements, constrained
guideways, collisions, and deadlocks. Krishnamurthy, Batta, and Karwan use
column generation for known AGV demands and report routes within a few percent
of a bound in reasonable time
([paper](https://doi.org/10.1287/opre.41.6.1077)). Column generation is not
needed for the first ropeway prototype, but the path-based representation is
relevant.

Möhring et al. describe a dynamic algorithm based on an implicit time-expanded
network that performed efficiently at high traffic density at the HHLA
container terminal. Their comparison also warns that static routes plus
heuristic collision handling can deadlock; explicit reservations or a
deadlock-safe claiming mechanism are required
([paper](https://doi.org/10.1007/s13676-012-0008-7)).

A CP-master/MIP-routing logic-cut decomposition for integrated AGV assignment,
scheduling, and conflict-free routing solved instances with only up to six
AGVs
([paper](https://doi.org/10.1016/j.cor.2005.07.004)). This is useful negative
evidence: a formally clean decomposition can still be too expensive when both
levels remain combinatorial.

**Transferable lesson:** explicit reservations and dynamic replanning are
promising; full exact hybrid decomposition is not automatically scalable.

### 6. Railway Dispatching and Alternative Graphs

Once a cabin's route and stop decisions are fixed, its movement resembles a
blocking/no-wait job visiting shared resources in a fixed sequence. The
Alternative Graph was developed for job-shop scheduling with blocking and
no-wait constraints
([paper](https://doi.org/10.1016/S0377-2217(01)00338-1)).

Gholami and Törnquist Krasemann model railway dispatch as a hybrid mixed and
alternative graph and resolve conflicts by retiming, reordering, and local
rerouting. On a one-hour scenario with approximately 80 active trains and 290
block sections, their heuristic generated a solution in less than ten seconds
([paper](https://doi.org/10.3390/a11040055)). This is the strongest direct
evidence that graph-based local conflict resolution can outperform a global
MILP on a physically detailed shared-resource schedule.

Logic-Based Benders has produced major gains for microscopic railway
timetabling: Leutwiler and Corman report instances twice as large and up to
40-fold speedups over centralized MILP benchmarks
([paper](https://doi.org/10.1016/j.ejor.2022.02.043)). It remains a valuable
later direction, but their method relies on specifically designed SAT
subproblems and aggregated cuts. Reproducing that machinery is not the minimum
experiment needed here.

**Transferable lesson:** an alternative graph is an excellent representation
for a small repair neighborhood. It need not be the global optimizer.

### 7. Rolling-Horizon Passenger Transport

Gaul, Klamroth, and Stiglmayr solve dynamic dial-a-ride using an event-based
MILP inside a rolling horizon. On real-world instances with more than 500
requests, 99.5% of their iterations found the optimal insertion position for
the current schedule within 30 seconds; average response time was 2.8 seconds
([paper](https://doi.org/10.4230/OASIcs.ATMOS.2021.8)).

The relevance is the planning contract, not dial-a-ride routing itself: freeze
a near-term prefix, retain an overlap and terminal state, and repeatedly solve
small insertion or repair problems. The complete demand profile can still be
known offline; rolling horizon is used as a computational decomposition rather
than an online-information assumption.

**Transferable lesson:** finite-horizon operational plans can be assembled
from small, overlapping, event-based problems without assuming periodicity.

### 8. Resource-Constrained Scheduling with Alternative Modes

A service movement can be interpreted as a job whose operations consume
physical resources. Stop, skip, turnback, and rope transfer are alternative
execution modes or alternative subgraphs. The RCPSP with Alternative
Subgraphs explicitly separates alternative selection and resource-feasible
scheduling and has been solved with guided tabu search
([paper](https://doi.org/10.1016/j.ejor.2018.09.005)).

This suggests a compact search representation:

```text
mode vector + priority list -> deterministic schedule generator -> feasible plan
```

The decoder plays the role of a serial schedule generation scheme. Local
search changes modes and priority order, then decodes again. This avoids
continuous timing variables in the outer search entirely.

**Transferable lesson:** search over a compact mode/priority representation and
use a deterministic resource-feasible decoder.

## Assessment of Candidate Architectures

The scores below are project-specific judgments, not literature results.

| Architecture | Chance of useful solutions | Initial effort | Role |
|---|---:|---:|---|
| Global integrated EAN MILP | low at larger scale | already high | small exact reference and validator |
| Full discrete time-expanded MILP | medium for short/coarse horizons | medium-high | optional coarse benchmark |
| Global CBS/CCBS | low-medium under dense recurring conflicts | high | bounded local repair only |
| Global Alternative Graph search | medium | medium-high | timing/merge repair, not passenger planning |
| Classical or Logic-Based Benders | medium long-term | very high | defer until repeated cut structure is observed |
| Column generation of complete trajectories | medium long-term | very high | defer until trajectory pool becomes bottleneck |
| CP-SAT full model | unknown | medium-high | later backend comparison |
| Reservation decoder only | high feasibility, uncertain quality | low-medium | first construction baseline |
| Reservation decoder + passenger-guided LNS | **highest near-term** | **medium** | recommended method |
| Rolling horizon + bounded graph repair | high scaling potential | medium | add after full-horizon decoder works |

## Proposed Mathematical Representation

### Anonymous Service Intentions

A `ServiceIntent` is not yet assigned to a cabin and contains:

- a start or release window;
- a source movement state;
- a finite sequence or admissible set of route options;
- stop/skip choices, or a small admissible mode set;
- optional turnback or transfer choice;
- a priority and passenger-service score.

For deterministic lines and rings, one service intent can cover one traversal
between two repeated decision states. For a network, it ends at the next state
where a route, turnback, transfer, or depot decision is made. Long trajectories
are created by chaining service intentions during decoding.

The initial prototype should use explicit service intentions rather than
integer frequency variables. This preserves individual finite-horizon service
times while avoiding cabin labels in the high-level search. Aggregated
line-plan variables may be added later if the explicit list itself becomes a
bottleneck.

### Resource Reservations

Every route option induces one or more resource uses. A canonical reservation
must support both point headways and interval occupancy:

```text
ResourceReservation
  resource_id
  service_id
  cabin_id
  entry_seconds
  release_seconds
  clearance_before_seconds
  clearance_after_seconds
  provenance
```

For a point event at time \(t_i\) with symmetric headway \(h\), another event
time \(t\) may not lie in

\[
  (t_i-h,\;t_i+h).
\]

For a platform or segment occupancy interval
\([e_i,r_i]\), the forbidden interval additionally includes the physical
occupancy and directional clearances. If the current semantics use different
headways by candidate direction, the calendar must query
\(h(i,j)\) rather than assuming symmetry.

Reservations are stored in sorted per-resource calendars. The safe intervals
are the complement of the union of forbidden intervals. No persistent
all-pairs set is created.

### Single-Service Safe-Interval Scheduling

Against fixed calendars, the low-level planner searches labels of the form

\[
  \ell=(v,I,t,c),
\]

where:

- \(v\) is a movement state;
- \(I\) is a safe interval at that state or resource event;
- \(t\in I\) is the earliest attainable time;
- \(c\) contains the bounded service state required by route and stop choices.

Extending a label through route option \(a\) propagates its minimum travel
time and finds the earliest compatible intervals for every resource use of
\(a\). Waiting is permitted only where the physical model permits it. For a
fixed option sequence this degenerates to fast forward propagation through
calendars; route alternatives require a Dijkstra/A*-style label-setting
search.

The low-level search is exact only for one service against the already fixed
reservations and the represented route-option state. It says nothing about
whether a different ordering of previously planned services would be better.

### Serial Decoder

A high-level candidate solution is

\[
  x=(m,\pi),
\]

where \(m\) chooses service modes and \(\pi\) is a priority order. The decoder:

1. initializes cabin availability and resource calendars;
2. takes the next eligible service according to \(\pi\);
3. tries a bounded set of compatible cabins;
4. computes the earliest or lowest-cost safe-interval schedule;
5. selects the cabin/schedule with the best incremental score;
6. commits its reservations;
7. continues until all required service intentions are scheduled or a bounded
   repair fails.

The decoder must be deterministic for a fixed seed, mode vector, and priority
list. Randomized restarts change only explicit tie-breaking or priorities and
must remain reproducible.

### Passenger Evaluation

For a complete decoded movement plan \(M\), solve

\[
  Q(M)=\min_p J(p\mid M)
\]

with the existing exact fixed-movement passenger optimizer. The first version
may retain its current direct-ride semantics. General network passenger paths
and transfers require a later event-based passenger graph, but they must not
block testing the movement architecture on the currently supported networks.

The search objective is lexicographic or explicitly weighted:

1. minimize unserved passengers;
2. minimize passenger journey or waiting time;
3. optionally penalize deployed cabins, operational waiting, and fragile
   headway slack.

Only \(Q(M)\), not a purely uncongested service estimate, decides whether a
complete incumbent is better.

## Initial Service-Plan Generation

The planner needs a feasible baseline before passenger-guided improvement.
The first generator should be intentionally conservative:

1. derive admissible circulation patterns and route options from the physical
   network;
2. construct an all-stop service plan over the finite horizon;
3. insert cabins from declared depots or a valid initial fleet state;
4. decode at minimum travel times with earliest feasible waiting;
5. if necessary, try deterministic priority variants and reduced dispatch
   rates;
6. retain the best validated all-stop plan.

For a closed network without depots, an initial physical fleet state is an
unavoidable boundary condition. It may be generated by the existing placement
and packing tools, but that is a one-time seed construction rather than a
joint optimization with all passenger decisions. For a network with depots,
the decoder can dispatch cabins over time and the initial state is empty or
explicitly supplied.

The phrase “network and demand profile as input” must therefore mean that
manually designed operating examples are unnecessary; it cannot eliminate
physical fleet supply, capacity, horizon, or boundary semantics from the
problem definition.

## Passenger-Guided Improvement

### Minimal Local Search

Begin with first-improvement or best-of-sample local search. Do not implement
adaptive operator weights initially. Candidate moves are:

- flip one service visit from stop to skip or skip to stop;
- change the priority of one service near a merge;
- swap two adjacent services competing for a resource;
- shift a service release window;
- reassign one service chain to another compatible cabin;
- change one local route, turnback, or rope-transfer option;
- destroy and rebuild all services in one station/time window;
- destroy and rebuild a small set serving a poorly performing OD pair.

Every move is decoded and physically validated before passenger evaluation.
Infeasible moves are rejected; they do not need a mathematical cut.

### Adaptive Large Neighborhood Search

Add ALNS only after at least two neighborhoods produce measurable
improvements. Operator weights are updated from:

- feasible decode rate;
- passenger-objective improvement;
- runtime;
- ability to escape the current local optimum.

Simulated-annealing or threshold acceptance may admit a worse feasible plan to
escape local optima. Keep the best validated incumbent independently.

### Cheap Guidance Without Invalidating Evaluation

The exact fixed-movement passenger solve is currently cheap and should be used
whenever practical. If repeated candidate construction dominates, rank moves
first by a proxy such as:

\[
  \text{stop benefit}
  = \text{boarding/alighting benefit}
    - \text{through-passenger delay}
    - \text{resource congestion price}.
\]

Only the most promising candidates receive exact passenger evaluation. Cache
evaluations by a canonical hash of service modes and decoded event times.

## Limited Conflict Repair

Prioritized planning can fail because an early reservation blocks a later
service even though another ordering would be feasible. The first repair
should be a bounded ejection mechanism:

1. collect the reservations directly responsible for the failed extension;
2. unplan at most \(q\) conflicting services, initially
   \(q\in\{2,4,8\}\);
3. reorder the failed service and the ejected services;
4. replan only this conflict set against the unchanged external calendars;
5. accept the first complete validated repair.

This is much smaller than full CBS. It can initially enumerate a few priority
orders or use beam search.

If bounded ejection is insufficient, implement one optional local backend:

- **Alternative Graph repair:** orient only the disjunctions among the ejected
  services and their boundary predecessors/successors, then compute event
  times by longest-path propagation;
- **bounded CBS/CCBS repair:** branch only on conflicts inside the ejected set
  and stop at the first feasible solution;
- **local EAN repair:** reuse the existing Gurobi model with all external
  movements and resource orders fixed.

The backends should share the same repair request and result contract so their
feasibility rate and runtime can be compared. Do not choose one before the
simple ejection experiment exposes the actual failure modes.

## Rolling-Horizon Scaling

After the full-horizon decoder works, add an offline rolling-horizon mode:

```text
planning window W
commit interval C < W
overlap W - C
boundary reservations and cabin states
```

At step \(k\):

1. include known demand and cabin states through \(k+W\);
2. plan and improve the complete window;
3. commit only the prefix through \(k+C\);
4. export cabin states, onboard passengers, queues, and resource reservations
   crossing the boundary;
5. advance by \(C\).

This is a computational decomposition, not a periodic model and not an online
uncertainty assumption. A second improvement pass may reopen overlapping
windows after the first complete plan is available.

The boundary state is correctness-critical. A window may not discard:

- a cabin occupying a resource across the commit time;
- required clearance after the boundary;
- onboard passengers and their destinations;
- queued passengers released before the boundary;
- a movement whose no-wait continuation has already become compulsory.

## Deadlock Policy for General Networks

Directed rings and deterministic corridors largely avoid classical routing
deadlocks. Rope transfers, turnbacks, and bidirectional shared resources may
introduce them. The first general-network implementation should use a
conservative claim policy:

- before entering a no-wait corridor, reserve the complete corridor through
  the next legal waiting state;
- never let a cabin wait on a resource that must be released for another
  cabin to leave its current state;
- reject a new reservation if it introduces a cycle in the wait-for graph;
- include terminal and depot capacity in the same claim graph.

This may exclude some feasible plans but preserves predictable construction.
More permissive partial claims should be considered only after the conservative
version is stable and its capacity loss has been measured.

## Exactness Boundary

The method intentionally separates three claims:

### Exact physical validation

A returned plan is accepted only if the independent movement and complete
headway validators pass. The reservation decoder is not trusted as its own
validator.

### Exact passenger evaluation for fixed movement

Given the supported passenger semantics and a fixed movement plan, the current
passenger subproblem may still be solved exactly.

### Heuristic integrated search

Service generation, cabin assignment, priority ordering, local moves, repair,
and rolling-horizon commitment are heuristic. The method provides no global
optimality proof and no infeasibility certificate.

This boundary is appropriate for the target: produce safe and useful cabin
operations from a general input, then compare service quality against robust
baselines.

## Proposed Software Structure

Add a new package rather than embedding heuristic state into the integrated
EAN optimizer:

```text
optimization/operations/
  models.py                 # service intentions, calendars, planner results
  service_generator.py      # automatic baseline and demand-guided intentions
  resource_calendar.py      # interval insertion, removal, and safe intervals
  safe_interval_planner.py  # one-service continuous-time path planning
  serial_decoder.py         # priority/mode vector -> movement plan
  repair.py                 # bounded ejection and interchangeable backends
  passenger_evaluator.py    # fixed-movement passenger solve and cache
  local_search.py           # initial neighborhoods
  rolling_horizon.py        # optional later orchestration
  validation.py             # reservation checks independent of EAN validation
```

Reuse rather than duplicate:

- `EanMovementNetwork`, `EanMovementState`, `EanRouteOption`, and
  `EanResourceUsage` as the physical planning graph;
- `EanMovementPlan` as the canonical movement output;
- `EanFixedMovementPassengerModelBuilder` for exact incumbent evaluation;
- `validate_ean_movement_plan_against_artifact` and the complete headway
  separator as independent safety checks;
- existing replay and export infrastructure.

Do not require eager `HeadwayPair` materialization for the reservation
planner. Its final plan may be validated by direct complete separation over
the active events.

## Implementation Phases

### Phase 0: Executable Feasibility Spike

Goal: determine whether continuous-time calendar insertion can reproduce known
feasible all-stop operations without a global MILP.

Implement:

- point-headway resource calendar;
- interval reservations for waiting/platform semantics;
- earliest-feasible propagation along one fixed circulation;
- deterministic serial insertion of fixed-start cabins;
- conversion to `EanMovementPlan`;
- independent complete validation.

Do not include passenger optimization, LNS, CBS, or dynamic routing.

Acceptance:

- every returned plan passes the existing validator and separator;
- the decoder reproduces feasible One-, Three-, and Five-Station baselines;
- no all-pairs artifact is required during decoding;
- construction metrics include attempts, interval queries, conflicts, waits,
  reservations, and runtime;
- a construction failure is reproducible and reports the blocking resource
  and services.

Go/no-go:

- proceed if known feasible medium-density baselines decode reliably under at
  most a small set of deterministic priority restarts;
- if they do not, implement bounded ejection before any passenger search;
- stop the architecture experiment if even bounded repair cannot reliably
  reproduce small solutions already proven feasible by EAN.

### Phase 1: Anonymous Service Intents and Cabin Assignment

Implement:

- service intentions independent of cabin IDs;
- automatic all-stop service generation from network patterns;
- assignment to compatible cabin states by minimum incremental schedule cost;
- canonical chaining into complete cabin trajectories;
- depot dispatch when explicitly represented by the network.

Acceptance:

- relabeling cabins does not change the decoded physical plan or score;
- service intentions can be reordered without rebuilding the physical
  network;
- closed-network and depot-start boundary modes are explicit and tested.

### Phase 2: Exact Passenger Evaluation

Implement:

- adapter from decoded plan to the fixed-movement passenger solve;
- lexicographic unserved/journey or unserved/waiting objective;
- objective and validation cache;
- all-stop reference result for every benchmark input.

Acceptance:

- passenger accounting and cabin capacity pass existing validation;
- repeated evaluation of the same canonical plan is deterministic;
- small decoded plans agree with the existing integrated model when movement
  is fixed identically.

### Phase 3: Minimal Passenger-Guided Local Search

Implement only three initial neighborhoods:

1. one stop/skip flip;
2. one adjacent resource-priority swap;
3. one station/time-window destroy and serial rebuild.

Use a fixed runtime or iteration budget and retain the best validated
incumbent.

Acceptance:

- every intermediate incumbent is physically valid;
- search starts producing incumbents within seconds rather than waiting for a
  global root relaxation;
- objective traces, feasible-move rates, and neighborhood runtimes are
  exported;
- at least one non-handcrafted demand profile yields a validated improvement
  over the all-stop reference.

### Phase 4: Bounded Conflict Repair

Implement conflict-set extraction and ejection sizes 2, 4, and 8. Compare
priority enumeration, beam search, and the existing local EAN as repair
backends before adding a new solver dependency.

Acceptance:

- repair improves decode success on dense or merge-heavy cases;
- runtime is bounded per repair call;
- external reservations remain unchanged;
- repaired plans pass full validation, not only local checks.

### Phase 5: Adaptive LNS

Add operator scoring, demand-guided destroy operators, threshold or
simulated-annealing acceptance, multi-start, and reproducible parallel runs.

Acceptance:

- improvement over simple local search is measured on a held-out benchmark
  set;
- ablation identifies which operators contribute;
- no acceptance decision uses an invalid or partially decoded plan.

### Phase 6: Rolling Horizon

Add overlapping windows and full boundary-state transfer. Compare against the
same decoder on the complete horizon.

Acceptance:

- concatenated windows pass global movement and headway validation;
- no passenger or resource occupancy disappears at a boundary;
- runtime scales approximately with active window size rather than total
  horizon length;
- quality loss against full-horizon planning is reported.

### Phase 7: Dynamic Network Choices

Extend service generation and safe-interval search to multiple route options,
turnbacks, rope transfers, and depots already represented by
`EanMovementNetwork`.

Acceptance:

- no ring-specific ordering assumption enters the planner;
- a shared resource used by different route options is represented by one
  calendar;
- conservative corridor claims prevent deadlocks;
- passenger reachability is recomputed from the decoded movement plan.

### Phase 8: Optional Advanced Methods

Only measured failure modes justify these additions:

- Alternative Graph repair for recurring local order failures;
- bounded CBS/CCBS if repair conflicts are sparse but order-sensitive;
- CP-SAT local repair if optional intervals express the neighborhood more
  compactly than EAN;
- Logic-Based Benders if the same service-plan infeasibilities recur and yield
  strong reusable explanations;
- column generation if automatic service/trajectory enumeration dominates;
- a coarse anonymous time-expanded master if the service generator, rather
  than physical decoding, is the limiting factor.

## Benchmark Design

Avoid validating the method only on examples constructed to favor skip-stop.
Create a factorial benchmark generator with held-out seeds.

### Physical factors

- directed line, directed ring, and multiple connected circulations;
- number of stations and route-decision states;
- one or multiple merge resources;
- terminal and intermediate turnbacks;
- rope transfers;
- headway-to-travel-time ratio;
- waiting allowed or forbidden;
- fleet density relative to the packing bound.

### Demand factors

- spatially uniform OD demand;
- one dominant origin or destination;
- clustered long-distance demand;
- clustered short-distance demand;
- directional imbalance;
- stationary, peaked, and shifting temporal profiles;
- low, medium, and capacity-constrained volume.

### Baselines

- earliest feasible all-stop plan;
- best all-stop plan found by the same decoder and local search budget;
- random feasible stop patterns with identical decoder budget;
- integrated EAN optimum on tiny instances;
- integrated EAN incumbent under the same wall-clock budget on manageable
  instances;
- reservation decoder without repair;
- reservation decoder with repair;
- passenger-guided local search and ALNS ablations.

### Metrics

Report at least:

- validated-plan rate and time to first feasible plan;
- best passenger objective over wall-clock time;
- unserved passengers;
- mean, median, 95th percentile, and maximum journey and waiting time;
- in-vehicle time and number of stops experienced;
- station- and OD-level distributional effects;
- active cabins and cabin utilization;
- reservation density, headway slack, and merge waiting;
- decode attempts, ejections, repair calls, and maximum repair set;
- peak memory;
- small-instance gap to the exact EAN optimum when available.

Use performance profiles or anytime curves across the complete benchmark set,
not only selected best cases.

## Expected Outcome and Main Risks

### Why the prototype is likely to construct feasible plans

- Ropeway motion is strongly constrained by the guideway, reducing route
  branching compared with general MAPF.
- Most corridors are deterministic; genuine order choices occur mainly at
  merges, transfers, turnbacks, and initial/depot insertion.
- The number of blocked intervals per physical resource should be much smaller
  than the number of time-grid states or all candidate pairs.
- Waiting is localized and can be handled explicitly.
- A feasible all-stop plan provides a robust initial incumbent.

### Why it may find useful skip-stop solutions

- The exact passenger evaluator supplies the true value of a decoded plan.
- Stop flips and station/time-window rebuilds directly express the central
  skip-stop trade-off.
- LNS can change complementary groups of services together, avoiding the
  failure of one-flip local search when two coordinated patterns are needed.
- Actual conflict-aware decode cost prevents the service planner from
  selecting attractive but operationally impossible patterns.

### Main risks

1. **Priority lock-in:** serial insertion may block later services. Mitigate
   with multiple priority rules and bounded ejection.
2. **Dense merges:** local repair sets may grow too large. Measure conflict-set
   size before choosing Alternative Graph or CBS.
3. **Poor service generation:** an all-stop seed plus local flips may not
   discover major route changes. Add station/time-window destroy before any
   sophisticated master problem.
4. **Initial closed-network state:** general initial placement remains a
   boundary problem. Keep depot dispatch and closed preloading explicit.
5. **Passenger transfers:** the current fixed-movement evaluator is primarily
   direct-ride oriented. General network transfers require an event-based
   passenger graph.
6. **Rolling-horizon myopia:** early commitments may harm later demand. Use
   overlap, terminal penalties, and a second improvement pass.
7. **Conservative claims:** reserving complete no-wait corridors may reduce
   capacity. Measure the loss before relaxing deadlock protection.

## Thesis Positioning

If successful, the thesis contribution should be framed as a general
passenger-oriented operational planning method rather than as a proof that one
manually selected skip-stop pattern wins:

> A finite-horizon matheuristic for urban ropeway networks that separates
> anonymous passenger-oriented service design from continuous-time
> conflict-free cabin scheduling, combines safe-interval resource reservation
> with local repair, and evaluates every incumbent by exact passenger
> assignment and independent physical validation.

The experimental claims may then be:

- the planner automatically produces physically valid cabin trajectories from
  topology and demand;
- it reaches useful incumbents substantially faster than the integrated EAN;
- passenger-guided skip-stop decisions improve service under identifiable
  demand and infrastructure conditions;
- the effects remain visible across a benchmark family rather than only a
  constructed instance;
- exact small-instance comparisons quantify, but do not eliminate, the
  heuristic quality gap.

The method should not be called Logic-Based Benders unless a genuine master,
complete subproblem, and valid reusable logic cuts are implemented. It should
not be called CBS unless conflict-tree branching is actually used. The initial
method is most accurately described as **passenger-guided local search with a
continuous-time reservation decoder and bounded conflict repair**.

## Recommended Immediate Experiment

Implement only Phase 0 before extending the integrated optimizer further.
The decisive question is:

> Can a calendar-based continuous-time decoder rapidly reconstruct known
> feasible all-stop operations at realistic cabin density and pass the full
> existing headway validator without materializing all cabin pairs?

If yes, the project gains a fast feasibility-preserving decoder around which
passenger-guided search can be built. If no, the blocking conflict traces will
show whether a small Alternative Graph repair is sufficient or whether the
reservation architecture is inappropriate. Either result is more informative
than another long global EAN run.

## Core Bibliography

- Phillips, M.; Likhachev, M. (2011). *SIPP: Safe Interval Path Planning for
  Dynamic Environments.* [ICRA paper](https://www.cs.cmu.edu/afs/cs/Web/People/maxim/files/sipp_icra11.pdf).
- Ma, H.; Hönig, W.; Kumar, T. K. S.; Ayanian, N.; Koenig, S. (2019).
  *Lifelong Path Planning with Kinematic Constraints for Multi-Agent Pickup
  and Delivery.* [DOI](https://doi.org/10.1609/aaai.v33i01.33017651).
- Li, J. et al. (2021). *Lifelong Multi-Agent Path Finding in Large-Scale
  Warehouses.* [Preprint](https://arxiv.org/abs/2005.07371).
- Ma, H.; Li, J.; Kumar, T. K. S.; Koenig, S. (2017). *Lifelong Multi-Agent
  Path Finding for Online Pickup and Delivery Tasks.*
  [Preprint](https://arxiv.org/abs/1705.10868).
- Chen, Z.; Alonso-Mora, J.; Bai, X.; Harabor, D. D.; Stuckey, P. J. (2021).
  *Integrated Task Assignment and Path Planning for Capacitated Multi-Agent
  Pickup and Delivery.* [DOI](https://doi.org/10.1109/LRA.2021.3074883).
- Zahradka, D.; Andreychuk, A.; Kulich, M.; Yakovlev, K. (2022). *Lower and
  Upper Bounds for Multi-Agent Multi-Item Pickup and Delivery: When a
  Decoupled Approach is Good Enough.*
  [DOI](https://doi.org/10.1609/socs.v15i1.21802).
- Möhring, R. H.; Köhler, E.; Gawrilow, E.; Stenzel, B. (2012).
  *Conflict-Free Vehicle Routing: Load Balancing and Deadlock Prevention.*
  [DOI](https://doi.org/10.1007/s13676-012-0008-7).
- Krishnamurthy, N. N.; Batta, R.; Karwan, M. H. (1993). *Developing
  Conflict-Free Routes for Automated Guided Vehicles.*
  [DOI](https://doi.org/10.1287/opre.41.6.1077).
- Corréa, A. I.; Langevin, A.; Rousseau, L.-M. (2007). *Scheduling and Routing
  of Automated Guided Vehicles: A Hybrid Approach.*
  [DOI](https://doi.org/10.1016/j.cor.2005.07.004).
- Mascis, A.; Pacciarelli, D. (2002). *Job-Shop Scheduling with Blocking and
  No-Wait Constraints.* [DOI](https://doi.org/10.1016/S0377-2217(01)00338-1).
- Gholami, O.; Törnquist Krasemann, J. (2018). *A Heuristic Approach to Solving
  the Train Traffic Re-Scheduling Problem in Real Time.*
  [DOI](https://doi.org/10.3390/a11040055).
- Leutwiler, F.; Corman, F. (2022). *A Logic-Based Benders Decomposition for
  Microscopic Railway Timetable Planning.*
  [DOI](https://doi.org/10.1016/j.ejor.2022.02.043).
- Kaspi, M.; Raviv, T. (2013). *Service-Oriented Line Planning and Timetabling
  for Passenger Trains.* [DOI](https://doi.org/10.1287/trsc.1120.0424).
- Cao, Z.; Ceder, A. (2019). *Autonomous Shuttle Bus Service Timetabling and
  Vehicle Scheduling Using Skip-Stop Tactic.*
  [DOI](https://doi.org/10.1016/j.trc.2019.03.018).
- *Reducing Passengers' Travel Time by Optimising Stopping Patterns in a
  Large-Scale Network: A Case-Study in the Copenhagen Region* (2018).
  [DOI](https://doi.org/10.1016/j.tra.2018.04.012).
- Gaul, D.; Klamroth, K.; Stiglmayr, M. (2021). *Solving the Dynamic
  Dial-a-Ride Problem Using a Rolling-Horizon Event-Based Graph.*
  [DOI](https://doi.org/10.4230/OASIcs.ATMOS.2021.8).
- Tanaka, S.; Hoshino, D.; Watanabe, M. (2016). *Group Control of Multi-Car
  Elevator Systems Without Accurate Information of Floor Stoppage Time.*
  [DOI](https://doi.org/10.1007/s10696-016-9238-6).
- Servranckx, T.; Vanhoucke, M. (2019). *A Tabu Search Procedure for the
  Resource-Constrained Project Scheduling Problem with Alternative
  Subgraphs.* [DOI](https://doi.org/10.1016/j.ejor.2018.09.005).
