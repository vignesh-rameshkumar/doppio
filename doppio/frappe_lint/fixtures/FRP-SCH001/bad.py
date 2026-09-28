import frappe


def leak():
    # typo'd doctype name -- FRP-SCH001 must fire
    return frappe.get_all("AGK_Projcts")
