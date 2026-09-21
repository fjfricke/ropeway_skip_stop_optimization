# Guide for thesis reviewers

> AI-generated documentation.

This repository contains the optimization code and result viewer. The reported
raw data is supplied in a separate ZIP. Start with [viewing the results](../README.md#view-the-submitted-results);
no optimization run or solver license is needed.

## What was evaluated

Both reported studies use the five-station ring (T5R), G500 geometry, geometric
headways, synthetic demand and **no waiting**. They answer different questions:

| | Study 1: journey time | Study 2: passengers served |
|---|---|---|
| Method | Labelled arc-flow MIP, Gurobi | Event-based CP-SAT, No-Wait trajectory templates |
| Fixed inputs | Cabin count and initial positions | Cabin count and stopping-pattern counts |
| Free decisions | STOP/SKIP choices and integer passenger flows | Individual trajectory shifts/initial positions and integer passenger assignment |
| Objective | Minimize total journey time with full service | Maximize passengers served before the deadline |
| Reported fleet sizes | K10/20/30; constant-demand subset K20/30 | K50 and K62 |

Journey time includes waiting from demand release until destination arrival.
In Study 2, the pattern mixtures are specified per trial; the solver does not
search all possible mixtures. Regular all-stop service references optimize a
common phase. The all-stop mixture trials additionally allow individual shifts.
Those are different comparison classes.

## Which results count

[The submission manifest](../results/submission_manifest.json) fixes the raw
files and the selected attempts. The [experiment guide](experiments/README.md#submitted-data)
maps the six packaged campaigns to the studies.

- **Journey:** 64 selected run records (48 relative-demand, 16 constant-demand),
  including both all-stop and skip-stop runs. The 22 MIP-start follow-ups replace
  their original cases; they are not additional independent comparisons.
- **Service:** 30 fixed-mixture trials, including 19 validated incumbents and
  trials without an incumbent. K50 and K62 use the same absolute demand per family.
- The diffuse family is called **F0 in code/data and F1 in the thesis**.
- The viewer uses this frozen Journey selection. Historical attempts remain
  accessible separately and must not replace the reported selection.

A missing incumbent or timeout is not a proof of infeasibility. For journey-time
minimization, an incumbent is an upper bound and a solver bound is a lower bound.
For service maximization these directions reverse. Service bounds apply to the
specified mixture, not to unrestricted pattern choice. These synthetic cases
do not establish a general capacity gain for urban ropeways.

Journey rides end at their first destination visit; service assignment permits
a later destination STOP in the same cabin within the deadline. The four extra
service-contract checks and the excluded historical replay warning are documented
in the [submission check](results/submission_check_20260921.md). All 83 reported
incumbents passed the recorded replay check.

## Where to check the implementation

Paths below are relative to `src/ropeway_skip_stop_optimization/`.

| Topic | Main source |
|---|---|
| Geometry, demand and case preparation | [benchmarking/thesis_cases.py](../src/ropeway_skip_stop_optimization/benchmarking/thesis_cases.py) |
| Shared time/headway contract | [benchmarking/thesis_contract.py](../src/ropeway_skip_stop_optimization/benchmarking/thesis_contract.py) |
| Journey solver | [optimization/ddd/arc_flow.py](../src/ropeway_skip_stop_optimization/optimization/ddd/arc_flow.py) |
| Journey passenger constraints | [optimization/ddd/arc_flow_passenger_model.py](../src/ropeway_skip_stop_optimization/optimization/ddd/arc_flow_passenger_model.py) |
| Service motion and resource constraints | [optimization/oip/nowait_templates.py](../src/ropeway_skip_stop_optimization/optimization/oip/nowait_templates.py) |
| Service passenger constraints | [optimization/oip/cp_sat.py](../src/ropeway_skip_stop_optimization/optimization/oip/cp_sat.py) |
| Service certificate validation | [optimization/oip/validation.py](../src/ropeway_skip_stop_optimization/optimization/oip/validation.py) |
| Frozen selection and portable paths | [submission.py](../src/ropeway_skip_stop_optimization/submission.py) |

`ddd/` is a historical package name; the reported labelled arc-flow runs do not
perform adaptive Dynamic Discretization Discovery. Other solvers, Waiting and
reservoir prototypes remain in the repository but are outside these two studies.
See the [benchmark index](../benchmarks/README.md) for execution entry points and
the [experiment guide](experiments/README.md) for reproduction commands.
