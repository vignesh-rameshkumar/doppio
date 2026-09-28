import frappe


def leak():
    # 'project_nam' is a typo -- FRP-SCH002 must fire
    return frappe.get_all("AGK_Projects", fields=["name", "project_nam"])
