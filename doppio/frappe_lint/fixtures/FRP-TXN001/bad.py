import frappe


@frappe.whitelist()
def update_and_commit(name):
    doc = frappe.get_doc("AGK_Projects", name)
    doc.status = "Active"
    doc.save()
    frappe.db.commit()
    return "ok"
