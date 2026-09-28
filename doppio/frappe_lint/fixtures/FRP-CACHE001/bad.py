import frappe


def start_job(job_id):
    # no TTL, and nothing anywhere deletes a 'bs:...' key -- FRP-CACHE001 must fire
    cache_key = f"bs:{job_id}"
    frappe.cache().set_value(f"{cache_key}:status", "In Progress")
    frappe.cache().set_value(f"{cache_key}:total", 0)
