import frappe


def commit_once_after_the_batch(names):
    for name in names:
        doc = frappe.get_doc("AGK_Projects", name)
        doc.status = "Processed"
        doc.save()
    frappe.db.commit()  # once, after the whole batch -- must not fire
