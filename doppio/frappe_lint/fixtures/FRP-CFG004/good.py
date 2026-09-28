POST_CONFIGS = {
    "post_self_info": {
        "doctype": "AGK_Employee",
        "fields": ["personal_email_id"],
    },
    "post_projects": {
        "doctype": "AGK_Projects",
        "fields": ["project_name"],
    },
}

# a key repeated in a DIFFERENT dict literal is not a duplicate -- each
# dict is checked independently, must not be flagged just for reusing a
# string that also appears as a key somewhere else in the file.
GET_CONFIGS = {
    "post_self_info": {
        "doctype": "AGK_Employee",
        "fields": ["personal_email_id"],
    },
}
