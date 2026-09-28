import frappe


def commit_every_iteration(names):
    for name in names:
        doc = frappe.get_doc("AGK_Projects", name)
        doc.status = "Processed"
        doc.save()
        frappe.db.commit()
