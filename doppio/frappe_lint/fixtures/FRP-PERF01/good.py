import frappe


def fetch_before_loop():
    docs = frappe.get_all("AGK_Projects", fields=["name", "status"], limit_page_length=0)
    for d in docs:
        process(d.status)  # no DB call per iteration -- must not fire


def save_each_doc_in_bulk_update(records):
    # .save() per iteration on already-fetched docs is a normal ORM
    # bulk-update pattern, not the raw-read-per-iteration this rule
    # targets -- .save()/.insert() are deliberately not in scope.
    for doc in records:
        doc.status = "Reviewed"
        doc.save()


def db_call_after_the_loop_is_fine():
    total = 0
    for i in range(10):
        total += i
    return frappe.db.get_value("AGK_Projects", None, "count(name)")
