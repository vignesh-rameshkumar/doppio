import frappe


@frappe.whitelist()
def fstring_injection(name):
    # direct f-string interpolation of a whitelisted param -- classic case
    return frappe.db.sql(f"SELECT * FROM tabUser WHERE name = '{name}'")


@frappe.whitelist()
def format_injection(name):
    # same bug, built via .format() into a variable, then passed by name --
    # proves the rule resolves through a local variable, not just literal call sites
    query = "SELECT * FROM tabUser WHERE name = '{}'".format(name)
    return frappe.db.sql(query)


@frappe.whitelist()
def percent_injection(name):
    # same bug again, via the % operator
    return frappe.db.sql("SELECT * FROM tabUser WHERE name = '%s'" % name)


def form_dict_injection_without_whitelist_param():
    # not a whitelisted function's own parameter, but frappe.form_dict is
    # always request-controlled regardless of which function reads it
    user = frappe.form_dict.get("user")
    return frappe.db.sql(f"SELECT * FROM tabUser WHERE name = '{user}'")


@frappe.whitelist()
def tainted_table_name_despite_bound_value_param(table, name):
    # the VALUE is correctly bound via %(name)s -- but the table name is
    # still directly interpolated, and you can't parameterize an
    # identifier with a bound placeholder. Still unsafe; binding one part
    # of the query doesn't make the whole query safe.
    return frappe.db.sql(
        f"SELECT * FROM `{table}` WHERE name = %(name)s",
        {"name": name},
    )
