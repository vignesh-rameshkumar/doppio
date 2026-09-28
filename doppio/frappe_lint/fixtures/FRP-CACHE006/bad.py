import frappe


def start_job(job_id):
    # 4+ scalar keys sharing one dynamic prefix -- should be one hash
    cache_key = f"bs:{job_id}"
    frappe.cache().set_value(f"{cache_key}:status", "In Progress", expires_in_sec=3600)
    frappe.cache().set_value(f"{cache_key}:total", 0, expires_in_sec=3600)
    frappe.cache().set_value(f"{cache_key}:processed", 0, expires_in_sec=3600)
    frappe.cache().set_value(f"{cache_key}:failed", 0, expires_in_sec=3600)
