import frappe


def only_three_keys(job_id):
    # below the >=4 threshold -- must not fire
    cache_key = f"bs:{job_id}"
    frappe.cache().set_value(f"{cache_key}:status", "In Progress", expires_in_sec=3600)
    frappe.cache().set_value(f"{cache_key}:total", 0, expires_in_sec=3600)
    frappe.cache().set_value(f"{cache_key}:processed", 0, expires_in_sec=3600)


def four_keys_but_all_fully_static():
    # 4+ set_value calls, but none of them build a dynamic key -- there's
    # no "family" here (no per-job/per-user prefix to consolidate), so
    # this must not be treated as the same pattern.
    frappe.cache().set_value("global:flag_a", 1, expires_in_sec=3600)
    frappe.cache().set_value("global:flag_b", 1, expires_in_sec=3600)
    frappe.cache().set_value("global:flag_c", 1, expires_in_sec=3600)
    frappe.cache().set_value("global:flag_d", 1, expires_in_sec=3600)
