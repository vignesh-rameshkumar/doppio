import frappe


@frappe.whitelist()
def requires_login():
    return "ok"


@frappe.whitelist(allow_guest=False)
def explicit_false_is_fine():
    # allow_guest=False is the safe default spelled out explicitly --
    # must not be flagged just for mentioning the kwarg.
    return "ok"


@frappe.whitelist(methods=["GET"])
def other_kwargs_dont_trigger_it():
    return "ok"
