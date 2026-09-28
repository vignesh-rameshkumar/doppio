POST_CONFIGS = {
    "post_something": {
        "doctype": "AGK_Projects",
        "fields": ["project_name"],
        "filters": {
            "static": {"staus": "Active"},
            "optional": ["projet_name"],
        },
    },
}
