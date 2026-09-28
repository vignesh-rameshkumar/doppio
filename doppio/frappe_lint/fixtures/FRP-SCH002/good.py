import frappe


def ok():
    # all real fields on AGK_Projects -- must stay silent
    return frappe.get_all("AGK_Projects", fields=["name", "project_name", "status"])


def wildcard_is_never_flagged():
    return frappe.get_all("AGK_Projects", fields=["*"])


def sql_aggregate_expressions_are_not_fieldnames():
    # "count(name) as total" is valid Frappe syntax for a SQL aggregate,
    # not a real column -- must NOT be treated as an unknown field
    # (this was a real false positive caught by writing this fixture).
    return frappe.get_all("AGK_Projects", fields=["status", "count(name) as total"])


def unknown_doctype_is_sch001s_job_not_sch002s():
    # a bogus doctype name here should not ALSO get a field-level complaint
    # from this rule -- that overlap would be confusing and redundant.
    return frappe.get_all("Not_A_Real_Doctype", fields=["whatever"])
