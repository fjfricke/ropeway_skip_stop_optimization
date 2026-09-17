"""Exact linear/Boolean translation of the shared insertion structure.

Intervals against constants use free-window choices. Variable interval pairs
retain ordering disjunctions. Unsupported constraint kinds fail explicitly.
"""

from itertools import combinations, pairwise
from time import perf_counter

import gurobipy as gp
from gurobipy import GRB


def free_windows(intervals):
    merged = []
    for a, b in sorted(intervals):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    if not merged:
        return [(None, None)]
    return [
        (None, merged[0][0]),
        *[(x[1], y[0]) for x, y in pairwise(merged)],
        (merged[-1][1], None),
    ]


class GurobiInsertion:
    def __init__(self, built, *, deadline=None):
        p = built.movement.model.proto
        self.model = gp.Model("single_cabin_insertion")
        m = self.model
        m.Params.OutputFlag = 0
        self.variables = []
        self.window_choices = 0
        for j, v in enumerate(p.variables):
            d = list(v.domain)
            self.variables.append(
                m.addVar(
                    lb=d[0],
                    ub=d[-1],
                    vtype=GRB.BINARY if d == [0, 1] else GRB.INTEGER,
                    name=v.name or f"v{j}",
                )
            )
        m.update()

        def lit(i):
            return self.variables[i] if i >= 0 else 1 - self.variables[-i - 1]

        def conjunction(ids):
            ids = list(ids)
            if not ids:
                return None
            if len(ids) == 1:
                i = ids[0]
                return self.variables[i if i >= 0 else -i - 1], int(i >= 0)
            z = m.addVar(vtype=GRB.BINARY)
            for i in ids:
                m.addConstr(z <= lit(i))
            m.addConstr(z >= sum(lit(i) for i in ids) - len(ids) + 1)
            return z, 1

        def row(expr, sense, rhs, guard=None):
            if guard is None:
                m.addLConstr(expr, sense, rhs)
            else:
                m.addGenConstrIndicator(guard[0], guard[1], expr, sense, rhs)

        def expr(e):
            return (
                gp.LinExpr(list(e.coeffs), [self.variables[i] for i in e.vars])
                + e.offset
            )

        def bounds(e):
            lo = hi = e.offset
            for i, c in zip(e.vars, e.coeffs):
                d = list(p.variables[i].domain)
                lo += min(c * d[0], c * d[-1])
                hi += max(c * d[0], c * d[-1])
            return lo, hi

        def constant(e):
            lo, hi = bounds(e)
            return lo if lo == hi else None

        def domain(expression, d, guard=None):
            d = list(d)
            if len(d) == 2 and d[0] == d[1]:
                row(expression, GRB.EQUAL, d[0], guard)
            elif len(d) == 2:
                if d[0] > -(2**63):
                    row(expression, GRB.GREATER_EQUAL, d[0], guard)
                if d[1] < 2**63 - 1:
                    row(expression, GRB.LESS_EQUAL, d[1], guard)
            else:
                zs = [m.addVar(vtype=GRB.BINARY) for _ in range(len(d) // 2)]
                row(sum(zs), GRB.EQUAL, 1, guard)
                for z, lo, hi in zip(zs, d[::2], d[1::2]):
                    row(expression, GRB.GREATER_EQUAL, lo, (z, 1))
                    row(expression, GRB.LESS_EQUAL, hi, (z, 1))

        for j, v in enumerate(p.variables):
            if len(v.domain) > 2:
                domain(self.variables[j], v.domain)
        for j, c in enumerate(p.constraints):
            if deadline is not None and perf_counter() >= deadline:
                raise TimeoutError("Gurobi translation deadline")
            guard = conjunction(c.enforcement_literal)
            if c.has_linear():
                row_expr = gp.LinExpr(
                    list(c.linear.coeffs), [self.variables[i] for i in c.linear.vars]
                )
                domain(row_expr, c.linear.domain, guard)
            elif c.has_bool_or():
                row(
                    sum(lit(i) for i in c.bool_or.literals), GRB.GREATER_EQUAL, 1, guard
                )
            elif c.has_bool_and():
                for i in c.bool_and.literals:
                    row(lit(i), GRB.EQUAL, 1, guard)
            elif c.has_interval():
                row(
                    expr(c.interval.start)
                    + expr(c.interval.size)
                    - expr(c.interval.end),
                    GRB.EQUAL,
                    0,
                    guard,
                )
            elif not c.has_no_overlap():
                raise ValueError(f"unsupported shared constraint: {c}")
        pair_seen = set()
        for c in p.constraints:
            if not c.has_no_overlap():
                continue
            fixed = []
            variable = []
            for i in c.no_overlap.intervals:
                q = p.constraints[i]
                a, b = constant(q.interval.start), constant(q.interval.end)
                if a is not None and b is not None and not q.enforcement_literal:
                    fixed.append((a, b))
                else:
                    variable.append(i)
            for i in variable:
                q = p.constraints[i]
                wins = free_windows(fixed)
                _start_lo, start_hi = bounds(q.interval.start)
                end_lo, _end_hi = bounds(q.interval.end)
                wins = [
                    (lo, hi)
                    for lo, hi in wins
                    if (lo is None or start_hi >= lo) and (hi is None or end_lo <= hi)
                ]
                if fixed:
                    zs = [
                        m.addVar(
                            vtype=GRB.BINARY,
                            name=f"window[{i},{j},{self.window_choices}]",
                        )
                        for j in range(len(wins))
                    ]
                    self.window_choices += len(zs)
                    guard = conjunction(q.enforcement_literal)
                    if guard is None:
                        m.addConstr(sum(zs) == 1)
                    else:
                        m.addConstr(sum(zs) == (guard[0] if guard[1] else 1 - guard[0]))
                    for z, (lo, hi) in zip(zs, wins):
                        if lo is not None:
                            row(expr(q.interval.start), GRB.GREATER_EQUAL, lo, (z, 1))
                        if hi is not None:
                            row(expr(q.interval.end), GRB.LESS_EQUAL, hi, (z, 1))
            for i, j in combinations(variable, 2):
                key = tuple(sorted((i, j)))
                if key in pair_seen:
                    continue
                pair_seen.add(key)
                x, y = p.constraints[i], p.constraints[j]
                _xl, xh = bounds(x.interval.end)
                yl, _yh = bounds(y.interval.start)
                if xh <= yl:
                    continue
                _xl, xh = bounds(y.interval.end)
                yl, _yh = bounds(x.interval.start)
                if xh <= yl:
                    continue
                z = m.addVar(vtype=GRB.BINARY)
                ids = list(x.enforcement_literal) + list(y.enforcement_literal)
                guard = conjunction(ids)
                # Both-presence plus each direction, linearized without global M.
                for direction in (0, 1):
                    g = m.addVar(vtype=GRB.BINARY)
                    conditions = [z if direction else 1 - z]
                    if guard:
                        conditions.append(guard[0] if guard[1] else 1 - guard[0])
                    for v in conditions:
                        m.addConstr(g <= v)
                    m.addConstr(g >= sum(conditions) - len(conditions) + 1)
                    row(
                        expr(x.interval.end) - expr(y.interval.start)
                        if direction
                        else expr(y.interval.end) - expr(x.interval.start),
                        GRB.LESS_EQUAL,
                        0,
                        (g, 1),
                    )
        obj = p.objective
        m.setObjective(
            gp.LinExpr(list(obj.coeffs), [self.variables[i] for i in obj.vars])
            + obj.offset,
            GRB.MINIMIZE,
        )
        for i, v in zip(p.solution_hint.vars, p.solution_hint.values):
            self.variables[i].Start = v
        m.update()

    def value(self, variable, values=None):
        if isinstance(variable, int):
            return variable
        raw = (
            values[variable.index]
            if values is not None
            else self.variables[variable.index].X
        )
        if abs(raw - round(raw)) > 1e-4:
            raise ValueError("nonintegral Gurobi certificate value")
        return round(raw)
