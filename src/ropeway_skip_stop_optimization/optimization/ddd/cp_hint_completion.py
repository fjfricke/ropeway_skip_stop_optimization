"""Complete deterministically implied hints, without solving or fixing decisions."""

from math import prod


def complete_cp_hints(model):
    proto = model.proto
    known = {}

    def copy(field):
        return tuple(field[i] for i in range(len(field)))

    domains = [copy(proto.variables[i].domain) for i in range(len(proto.variables))]

    def assign(i, value):
        value = int(value)
        if i in known and known[i] != value:
            raise ValueError("contradictory derived hint")
        d = domains[i]
        if not any(a <= value <= b for a, b in zip(d[::2], d[1::2])):
            raise ValueError("derived hint outside variable domain")
        known[i] = value

    for i, v in zip(copy(proto.solution_hint.vars), copy(proto.solution_hint.values)):
        assign(i, v)
    for i, d in enumerate(domains):
        if len(d) == 2 and d[0] == d[1]:
            assign(i, d[0])

    def lit(literal):
        i = literal if literal >= 0 else -literal - 1
        return None if i not in known else (known[i] if literal >= 0 else 1 - known[i])

    def set_lit(literal, v):
        assign(literal if literal >= 0 else -literal - 1, v if literal >= 0 else 1 - v)

    # Copy repeated fields once: repeatedly traversing the pybind protobuf views
    # in a fixed-point loop is very expensive on the full reservoir model.
    pending = []
    for ci in range(len(proto.constraints)):
        c = proto.constraints[ci]
        en = copy(c.enforcement_literal)
        if c.has_linear():
            x = c.linear
            pending.append(
                ("linear", en, tuple(zip(copy(x.vars), copy(x.coeffs))), copy(x.domain))
            )
        elif c.has_bool_and():
            pending.append(("and", en, copy(c.bool_and.literals), ()))
        elif c.has_bool_or():
            pending.append(("or", en, copy(c.bool_or.literals), ()))
        elif c.has_int_prod():
            x = c.int_prod

            def pack(e):
                return (tuple(zip(copy(e.vars), copy(e.coeffs))), e.offset)

            pending.append(
                (
                    "product",
                    en,
                    tuple(pack(x.exprs[i]) for i in range(len(x.exprs))),
                    pack(x.target),
                )
            )

    def value(e):
        terms, offset = e
        return (
            None
            if any(i not in known for i, c in terms)
            else offset + sum(c * known[i] for i, c in terms)
        )

    while pending:
        before = len(known)
        remaining = []
        for kind, en, data, other in pending:
            flags = [lit(literal) for literal in en]
            if 0 in flags:
                continue
            enabled = all(f == 1 for f in flags)
            false = False
            keep = False
            if kind == "linear":
                missing = [(i, c) for i, c in data if i not in known]
                total = sum(c * known[i] for i, c in data if i in known)
                if not missing:
                    false = not any(
                        a <= total <= b for a, b in zip(other[::2], other[1::2])
                    )
                elif (
                    enabled
                    and len(missing) == 1
                    and len(other) == 2
                    and other[0] == other[1]
                ):
                    i, c = missing[0]
                    if (other[0] - total) % c:
                        raise ValueError("nonintegral hint equality")
                    assign(i, (other[0] - total) // c)
                else:
                    keep = True
            elif kind == "and":
                false = any(lit(literal) == 0 for literal in data)
                if not false:
                    if enabled:
                        for literal in data:
                            set_lit(literal, 1)
                    else:
                        keep = any(lit(literal) is None for literal in data)
            elif kind == "or":
                values = [lit(literal) for literal in data]
                if 1 not in values:
                    unknown = [literal for literal in data if lit(literal) is None]
                    if not unknown:
                        false = True
                    elif enabled and len(unknown) == 1:
                        set_lit(unknown[0], 1)
                    else:
                        keep = True
            elif kind == "product":
                values = [value(e) for e in data]
                terms, offset = other
                if enabled and all(v is not None for v in values) and len(terms) == 1:
                    i, c = terms[0]
                    numerator = prod(values) - offset
                    if numerator % c:
                        raise ValueError("nonintegral hint product")
                    assign(i, numerator // c)
                else:
                    keep = True
            if false:
                unknown = [literal for literal in en if lit(literal) is None]
                if len(unknown) == 1:
                    set_lit(unknown[0], 0)
                elif enabled:
                    raise ValueError("hint violates a constraint")
                else:
                    keep = True
            if keep:
                remaining.append((kind, en, data, other))
        if len(known) == before:
            break
        pending = remaining
    model.clear_hints()
    for i, v in sorted(known.items()):
        model.add_hint(model.get_int_var_from_proto_index(i), v)
    return {"hinted_variables": len(known), "variables": len(domains)}
