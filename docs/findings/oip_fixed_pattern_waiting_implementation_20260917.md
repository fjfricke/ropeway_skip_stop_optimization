# OIP-EAN fixed-pattern waiting pilot: implementation record

The pilot uses the existing optimized-initial-placement EAN. It does not add a
second arc-flow or phase model. The frozen technical case is T5R/G500-B, F2/P0,
3,210 passengers, K=62, a 1 ms movement grid, and 15 s release aggregation.
The derived All-Stop cycle is 732 s. Demand spans 1,464 s, passenger service
ends at 2,364 s, and physical continuation ends at 2,664 s.

The three cabin-mask allocations are 62 All-Stop; 31 `{S1,S3}` plus 31
`{S2,S4}`; and 16/16 direct plus 30 All-Stop. Cabin IDs select masks but do not
impose an order after the service boundary. Gurobi's global OIP initial-state
symmetry is disabled for fixed masks and reintroduced only inside equal-mask
classes. CP-SAT likewise orders only equal-mask classes.

CP-SAT now has an integer waiting variable at every visit. Waiting is zero on a
SKIP and is bounded by the station cap on a STOP. It extends the
end-of-platform resource and shifts the merge and every downstream event.
Boarding uses the actual platform exit after waiting; alighting remains at the
platform entry before destination waiting. Extracted plans preserve an initial
`platform_wait` state when a hold straddles time zero.

For fixed patterns, impossible serve/skip headway candidates and their pairs
are removed before the Gurobi movement model is constructed. The independently
validated full artifact remains the certificate authority. In the F2-direct
Waiting build this reduces the measured model to about 643,000 variables and
1.57 million constraints; setup took about 25 s on the development machine.

Every feasible movement is written first as `movement_certificate.json`. A
separate one-thread Gurobi integer assignment then minimizes unserved demand
lexicographically before Journey Time, with a 30 s total limit. Its incumbent,
bound, status, build time, service count, and independently recomputed Journey
Time are stored separately from movement feasibility.

The twelve-run campaign entry point is
`benchmarks/run_oip_pattern_waiting_campaign.py`. It runs three masks, two
waiting caps, and both solvers sequentially under the shared 20 minute and
32 GiB limits. Individual runs remain visible through the existing optimization
frontend export.

The completed pilot and its interpretation are recorded in
[`oip_fixed_pattern_waiting_pilot_20260917.md`](oip_fixed_pattern_waiting_pilot_20260917.md).
