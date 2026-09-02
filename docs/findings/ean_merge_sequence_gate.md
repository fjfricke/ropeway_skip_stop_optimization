# Merge-Sequence EAN Gate

Date: 2026-08-31  
Working tree base: `eb8f30e` (the gate implementation was uncommitted at the
time of measurement)  
Method: one Gurobi thread, seed 1, zero MIP gap; 30 seconds for the final
\(10+10\) run and 60 seconds per formulation for \(20+20\)

## Decision

Do not integrate Lattice or Slot Merge-Sequence formulations into the
production EAN. The mandatory isolated performance gate failed. The existing
Pairwise formulation remains the stronger baseline for the tested merge
instances.

The staged experiment and its mathematical contract are retained in:

- [`../plans/ean_merge_sequence_reformulation.md`](../plans/ean_merge_sequence_reformulation.md)
- [`../plans/ean_merge_sequence_implementation_and_experiments.md`](../plans/ean_merge_sequence_implementation_and_experiments.md)

## Semantic Result

Cabins cannot overtake within either the Service or Skip branch. Waiting
changes times and gaps, but not same-branch order. The current EAN already
rejected the audited same-Service reorder because Platform Entry plus Platform
Exit/Waiting occupancy constraints imply the required FIFO order in that case.
An explicit opt-in `PAIRWISE_FIFO` formulation is retained as a semantic audit
reference.

## Performance Evidence

All exact formulations agreed on the objective whenever optimality was proved.
The final adversarial \(10+10\) single-merge run produced:

| Formulation | Objective | Variables | Binary | Rows | Solve time |
|---|---:|---:|---:|---:|---:|
| Pairwise FIFO | 1291.5 | 120 | 100 | 218 | 0.82 s |
| Lattice | 1291.5 | 240 | 220 | 339 | 2.05 s |
| Slots | 1291.5 | 440 | 400 | 477 | 4.70 s |

At \(20+20\) with 60 seconds per formulation, all three found objective 4833.
Their best bounds were approximately 2525.19 (Pairwise), 2007.14 (Lattice),
and 2445.52 (Slots). Thus neither extended formulation improved the proof gap.
Across the \(5+5\) and \(10+10\) uniform, clustered, and adversarial matrix,
Pairwise was generally fastest.

## Consequence

The planned Tranches 3--6 were not activated. No production Pair was omitted,
no `PARTITIONED` artifact scope was added, and no Passenger model can claim a
partial Merge-Sequence certificate. The domain analyzer and isolated runner
remain useful reproducibility and topology-audit tools.
