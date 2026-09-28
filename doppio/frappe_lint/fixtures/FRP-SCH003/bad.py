import frappe


def leak_via_filters_dict():
    # 'staus' is a typo of 'status' -- FRP-SCH003 must fire
    return frappe.get_all("AGK_Projects", filters={"staus": "Active"})


def leak_via_filters_list():
    return frappe.get_all("AGK_Projects", filters=[["projet_name", "=", "X"]])


def leak_via_order_by():
    return frappe.get_all("AGK_Projects", order_by="project_nam desc")
