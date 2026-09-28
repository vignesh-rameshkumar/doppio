import frappe

POST_CONFIGS = {
    "post_something": {
        "doctype": "AGK_Projects",
        "fields": ["project_name"],
        "filters": {
            "static": {"status": "Active"},
            "optional": ["project_name"],
        },
    },
    "post_lambda_value": {
        "doctype": "AGK_Projects",
        "fields": ["project_name"],
        "filters": {
            # value is a lambda (a real pattern in this codebase, e.g.
            # binding a filter to the current session user) -- only the
            # KEY is checked against the schema, so this must not be
            # flagged just because the value isn't a plain literal.
            "static": {"status": lambda payload: frappe.session.user},
        },
    },
    "post_no_filters_key": {
        "doctype": "AGK_Projects",
        "fields": ["project_name"],
        # no "filters" key at all -- must not crash or false-positive
    },
}
