POST_CONFIGS = {
    "post_something": {
        "doctype": "AGK_Projects",
        "fields": ["name"],
    },
}

# has a "doctype" key naming something that doesn't exist, but no "fields"
# key -- not shaped like a config entry at all, so must NOT be flagged.
# (this rule only fires on the doctype+fields combination that identifies
# a real POST_CONFIGS/FIELD_CONFIG-style registry entry.)
UNRELATED_DICT = {
    "doctype": "Also_Not_Real",
    "owner": "someone",
}
