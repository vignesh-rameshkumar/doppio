import frappe


def correct_filters_dict():
    return frappe.get_all("AGK_Projects", filters={"status": "Active"})


def correct_filters_with_operator():
    # {"field": ["in", [...]]} -- still just checking the KEY, not
    # misreading the operator/value list as a fieldname
    return frappe.get_all("AGK_Projects", filters={"status": ["in", ["Active", "Draft"]]})


def correct_filters_list():
    return frappe.get_all("AGK_Projects", filters=[["project_name", "=", "X"]])


def correct_order_by():
    return frappe.get_all("AGK_Projects", order_by="project_name desc")


def implicit_field_name_is_always_valid():
    # "name" is on every DocType even though it's never in a doctype's own
    # field list -- must not be flagged
    return frappe.get_all("AGK_Projects", filters={"name": "PROJ-0001"}, order_by="name")


def dynamic_filters_cant_be_resolved_statically(filters_dict):
    # filters built elsewhere and passed in as a variable -- can't be
    # checked without running the code, so must not be flagged
    return frappe.get_all("AGK_Projects", filters=filters_dict)
