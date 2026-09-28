import frappe


@frappe.whitelist()
def no_methods_declared():
    return "ok"
