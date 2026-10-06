"""bench install-app doppio hooks. See hooks.py's (commented-out until
now) after_install line."""
from __future__ import annotations


def after_install():
    """Best-effort: install the frappe-lint VS Code extension into the
    developer's local VS Code, if one is present, so live linting works
    with zero manual setup after 'bench install-app doppio'. See
    frappe_lint/vscode_install.py -- every failure mode there is caught
    and logged, never raised; this outer try/except is just a second
    safety net around the import itself. This must never be able to
    break app installation."""
    try:
        from doppio.frappe_lint.vscode_install import install
        install()
    except Exception:
        pass
