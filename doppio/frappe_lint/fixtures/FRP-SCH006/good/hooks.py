doc_events = {
    "AGK_Projects": {
        # correctly spelled, function really exists below -- must stay silent
        "on_update": "doppio_fixture_pkg.helpers.on_project_update",
    },
    "*": {
        # points at a module this fixture project doesn't contain (as if
        # it belonged to a different installed app) -- can't be resolved
        # one way or the other, so it must be silently skipped rather than
        # flagged as broken.
        "on_trash": "some_other_installed_app.utils.cleanup",
    },
}
