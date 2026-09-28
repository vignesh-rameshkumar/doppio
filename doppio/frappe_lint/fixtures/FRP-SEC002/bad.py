import frappe


@frappe.whitelist(allow_guest=True)
def leak_everything():
    return frappe.get_all("AGK_Projects")
