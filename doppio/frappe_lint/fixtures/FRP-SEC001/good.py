import frappe


@frappe.whitelist()
def properly_bound(name):
    # plain string literal, real user input passed as a bound parameter --
    # the correct pattern. Must never be flagged.
    return frappe.db.sql("SELECT * FROM tabUser WHERE name = %(name)s", {"name": name}, as_dict=1)


@frappe.whitelist()
def project_search(limit=20, start=0, query=None):
    # this is the exact shape that motivated rejecting a plain "db.sql()
    # called with an f-string" pattern match for SQL injection: the
    # f-string interpolates base_sql, which is built ENTIRELY from string
    # literals via += -- the one real user input (`query`) only ever
    # reaches the query through a %(query)s bound placeholder, never
    # through string interpolation. Must stay silent.
    params = {"limit": int(limit), "start": int(start)}
    base_sql = """
        FROM `tabAGK_Projects` p
        WHERE p.status = 'Active'
    """
    if query:
        base_sql += " AND p.project_name LIKE %(query)s"
        params["query"] = f"%{query}%"

    return frappe.db.sql(f"""
        SELECT p.name
        {base_sql}
        LIMIT %(limit)s OFFSET %(start)s
    """, params, as_dict=1)


def internal_report():
    # f-string SQL, but nothing in it traces back to request input -- a
    # hardcoded local value, not a whitelisted param or form_dict read.
    table_suffix = "2024"
    return frappe.db.sql(f"SELECT * FROM tabArchive_{table_suffix}")


def form_dict_value_bound_properly_is_safe():
    # 'user' IS tainted (a direct form_dict read) -- but it's passed as a
    # bound parameter here, not interpolated into the SQL text, so this
    # is safe. Proves the rule checks WHERE the tainted value ends up,
    # not just whether a tainted value was read anywhere in the function.
    user = frappe.form_dict.get("user")
    return frappe.db.sql("SELECT * FROM tabUser WHERE name = %(user)s", {"user": user})


def internal_helper_param_not_from_request(name):
    # 'name' is just a plain internal function parameter -- the function
    # isn't @frappe.whitelist()'d and 'name' isn't read from form_dict, so
    # nothing marks it as request-controlled. Not flagged by this rule.
    # (A real audit would still want to know where the caller got `name`
    # from -- see the module docstring: this rule is intraprocedural only,
    # it doesn't trace across a call graph.)
    return frappe.db.sql(f"SELECT * FROM tabInternalCache WHERE key = '{name}'")
