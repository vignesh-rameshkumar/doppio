import frappe


def n_plus_one_read(names):
    for name in names:
        doc = frappe.get_doc("AGK_Projects", name)  # DB query every iteration
        process(doc)


def n_plus_one_in_nested_loop(groups):
    # also proves the dedup logic: this call is reachable via BOTH the
    # outer loop's walk and the inner loop's own walk -- must be reported
    # exactly once, not twice
    for group in groups:
        for name in group:
            frappe.db.get_value("AGK_Projects", name, "status")
