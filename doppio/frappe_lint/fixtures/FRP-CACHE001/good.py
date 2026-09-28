import frappe


def _cache_key(user):
    return f"doctype_list:{user}"


def cache_permitted_doctypes(user, permitted):
    # no TTL -- but invalidate_user_cache() below deletes the same key shape
    # on the doc events that actually change permissions. Must NOT fire:
    # this is the exact pattern a naive "no expires_in_sec" rule would
    # wrongly flag on any correctly event-invalidated permission cache.
    frappe.cache().set_value(_cache_key(user), permitted)


def invalidate_user_cache(doc, method):
    frappe.cache().delete_value(_cache_key(doc.parent))


def cache_with_ttl_instead(key, value):
    # has an explicit TTL -- must NOT fire regardless of invalidation
    frappe.cache().set_value(key, value, expires_in_sec=300)
