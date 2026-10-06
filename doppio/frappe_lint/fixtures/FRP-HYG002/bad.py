def build_where_clause(record):
    # genuine pyramid -- 4 real levels of nested if, each inside the
    # previous one's true branch. FRP-HYG002 must fire.
    if record.status == "Active":
        if record.priority == "High":
            if record.assigned:
                if record.due_soon:
                    return "urgent"
    return "normal"
