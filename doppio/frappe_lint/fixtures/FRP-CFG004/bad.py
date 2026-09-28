POST_CONFIGS = {
    "post_self_info": {
        "doctype": "AGK_Employee",
        "fields": ["personal_email_id"],
    },
    "post_self_info": {
        # copy-paste mistake: this silently overwrites the entry above --
        # the first one is dead code and nobody will notice
        "doctype": "AGK_Projects",
        "fields": ["project_name"],
    },
}
