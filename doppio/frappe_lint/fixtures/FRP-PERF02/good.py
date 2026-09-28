import frappe


def bounded_with_limit_page_length():
    return frappe.get_all("AGK_Projects", limit_page_length=20)


def bounded_with_limit():
    return frappe.get_all("AGK_Projects", limit=20)


def db_count_is_legitimately_unbounded():
    # not in the target call set -- counting rows isn't the "loads
    # every row into memory" problem this rule targets
    return frappe.db.count("AGK_Projects")
