# Fixed-Movement Direct-Ride LP Is Not Integral in General

Date: 2026-07-15

Software baseline: `08ac095`

## Scope

This finding concerns the passenger-assignment problem after all cabin
movements, stop decisions, and event times have been fixed. Passengers use
direct rides only; transfers are not allowed. Each demand group contains one
passenger and cabin capacity is one.

For fixed movement, the unary slots of one ride candidate can be aggregated
to a passenger count \(x_r\). The relevant constraints are

\[
  \sum_{r\in\mathcal R_g}x_r+u_g=n_g
\]

for every demand group and

\[
  \sum_{r:\,q\in r}x_r\leq Q
\]

for every cabin interval. Each ride column therefore has one entry in its
demand row and a consecutive block of entries on one cabin timeline.

That structure alone does not make the complete matrix totally unimodular.

## Direct-Ride Ring Counterexample

Consider a directed three-station ring \(0\to1\to2\to0\), two cabins, unit
travel times, horizon \(H=5\), and the visit sequences

```text
cabin 0: 0, 1, 2, 0, 1, 2
cabin 1: 1, 2, 0, 1, 2, 0
```

Visits 1 through 4 are stops for both cabins; visits 0 and 5 are not usable
for boarding or alighting. The release times for demands
\(0\to1,0\to2,1\to0,1\to2,2\to1\) are \(0,1,0,1,2\), respectively. These
choices leave the following seven direct ride candidates:

| Candidate | Demand | Cabin | Occupied intervals | Board time |
|---|---|---:|---|---:|
| \(a\) | \(0\to1\) | 0 | \([3,4)\) | 3 |
| \(b\) | \(0\to1\) | 1 | \([2,3)\) | 2 |
| \(c\) | \(0\to2\) | 1 | \([2,4)\) | 2 |
| \(d\) | \(1\to0\) | 0 | \([1,3)\) | 1 |
| \(e\) | \(1\to2\) | 0 | \([1,2)\) | 1 |
| \(f\) | \(1\to2\) | 1 | \([3,4)\) | 3 |
| \(h\) | \(2\to1\) | 0 | \([2,4)\) | 2 |

For the final demand group, release time 2 removes the otherwise possible
cabin-1 ride boarding at time 1. All listed rides are shorter than one full
ring, so the example remains valid with directed-ring dominance pruning.

Demand alternatives and interval capacities contain the following active
rows:

\[
\begin{aligned}
 a+b&\leq1, &
 b+c&\leq1, &
 c+f&\leq1,\\
 f+e&\leq1, &
 e+d&\leq1, &
 d+h&\leq1, &
 h+a&\leq1.
\end{aligned}
\]

They form an odd conflict cycle. In column order
\((a,b,c,f,e,d,h)\), the corresponding row matrix is

\[
\begin{pmatrix}
1&1&0&0&0&0&0\\
0&1&1&0&0&0&0\\
0&0&1&1&0&0&0\\
0&0&0&1&1&0&0\\
0&0&0&0&1&1&0\\
0&0&0&0&0&1&1\\
1&0&0&0&0&0&1
\end{pmatrix}.
\]

Its determinant has absolute value \(2\). The passenger constraint matrix is
therefore not totally unimodular in general. The unique solution obtained by
making these seven rows tight is

\[
  a=b=c=d=e=f=h=\tfrac12,
\]

which is a fractional vertex.

The current waiting-time objective also exposes an objective gap on this
example. Serving a ride boarding at time \(t\) instead of leaving its passenger
unserved has benefit \(H-t\). The seven benefits are

\[
  (2,3,3,2,4,4,3)
\]

in the column order above. The fractional vertex has benefit \(10.5\), whereas
the best integer assignment has benefit \(10\).

## Interpretation

Transfers are not required for nonintegrality. It already results from the
combination of:

- alternatives belonging to the same demand group;
- interval capacities on different cabin timelines; and
- an odd cycle alternating between demand and capacity conflicts.

A single cabin without cross-cabin ride alternatives retains an interval
structure and may admit a stronger integrality result. That special case does
not cover the optimization model, where one demand group may choose among
several cabins.

The counterexample rules out a general claim that the fixed-movement passenger
LP is exact. It does not determine the practical LP/IP gap on the evaluated
instances. The implemented fixed-movement optimizer therefore exposes matched
integer and LP modes for measuring that gap, constructing passenger bounds and
starts, and deciding between integer, logic-based, or branch-and-Benders
variants.
