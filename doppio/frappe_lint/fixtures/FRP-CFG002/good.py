POST_CONFIGS = {
    "post_something": {
        "doctype": "AGK_Projects",
        "fields": ["project_name", "status"],
    },
}

# unknown doctype -- that's FRP-CFG001's job, this rule must not also fire
# on the fields list of a config entry it can't resolve a doctype for.
UNKNOWN_DOCTYPE_CONFIG = {
    "doctype": "Not_A_Real_Doctype",
    "fields": ["anything", "at_all"],
}
