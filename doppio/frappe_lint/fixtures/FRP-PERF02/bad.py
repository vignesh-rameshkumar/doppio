import frappe


def unbounded_get_all():
    return frappe.get_all("AGK_Projects")


def unbounded_get_list():
    return frappe.get_list("AGK_Projects")
