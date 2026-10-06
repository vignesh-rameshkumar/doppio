def build_filter_condition(operator, value, field):
    # a long if/elif ladder -- the exact pattern that motivated this rule's
    # elif-vs-nesting distinction in the first place: Python's ast represents
    # elif as a nested If inside orelse, structurally identical to real
    # nesting, so a naive depth counter reports this as "depth 20+". It's a
    # flat operator-dispatch table, not a pyramid. Must NOT fire.
    if operator == "=":
        return f"{field} = %s", [value]
    elif operator == "!=":
        return f"{field} != %s", [value]
    elif operator == ">":
        return f"{field} > %s", [value]
    elif operator == ">=":
        return f"{field} >= %s", [value]
    elif operator == "<":
        return f"{field} < %s", [value]
    elif operator == "IN":
        if not value:
            return "1=0", []
        return f"{field} IN (%s)", value
    elif operator == "LIKE":
        return f"{field} LIKE %s", [f"%{value}%"]
    else:
        return f"{field} = %s", [value]


def below_threshold(record):
    # genuine nesting, but only 3 levels deep -- under the threshold, must
    # not fire (the threshold exists precisely so shallow, normal
    # conditional logic isn't flagged).
    if record.status == "Active":
        if record.priority == "High":
            if record.assigned:
                return "review"
    return "normal"


def structural_wrapping_is_not_if_depth(records):
    # for/try/with wrapping shallow ifs -- these structural statements
    # must not themselves count as nesting levels, only genuine if-inside-
    # if does.
    for r in records:
        try:
            if r.status == "Active":
                with open("/tmp/log") as f:
                    if r.priority == "High":
                        f.write("high priority active record\n")
        except IOError:
            pass


def outer_with_shallow_nested_function():
    # outer's own if-nesting is 3 levels; the nested function's own body is
    # a separate 2 levels. Neither crosses the threshold (4) on its own --
    # but IF depth accumulated across the scope boundary instead of
    # resetting per-function (a real bug class: the nested function
    # inheriting whatever depth its enclosing code happened to be at), 3+2
    # would wrongly sum past the threshold and fire somewhere in here. It
    # doesn't, because each FunctionDef is evaluated independently from its
    # own body only. Must NOT fire, on either function.
    if True:
        if True:
            if True:
                def inner(record):
                    if record.a:
                        if record.b:
                            return "b"
                    return "shallow"
                return inner
    return None
