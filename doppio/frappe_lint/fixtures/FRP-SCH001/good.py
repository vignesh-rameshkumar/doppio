import frappe


def ok():
    # correctly-spelled, real DocType -- FRP-SCH001 must stay silent
    return frappe.get_all("AGK_Projects")


def dynamic_doctype_is_never_flagged(dt):
    # not a string literal -- can't resolve statically, must not false-positive
    return frappe.get_all(dt)
