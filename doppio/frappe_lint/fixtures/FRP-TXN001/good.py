import frappe


@frappe.whitelist()
def update_without_manual_commit(name):
    # let Frappe commit at the end of the request -- the correct pattern
    doc = frappe.get_doc("AGK_Projects", name)
    doc.status = "Active"
    doc.save()
    return "ok"


def background_job_commit_is_fine():
    # not a whitelisted (request-scoped) function -- a scheduled/background
    # job legitimately needs to manage its own transaction boundaries
    doc = frappe.get_doc("AGK_Projects", "PROJ-0001")
    doc.status = "Archived"
    doc.save()
    frappe.db.commit()
