"""frappe-lint: AST-based static checks for Frappe apps, with schema
awareness across every installed app in the bench.

Shipped as part of the `doppio` app so any Frappe dev team that already
uses doppio for scaffolding gets this for free, and gets it via
`bench frappe-lint-*` commands rather than a per-developer local script.
See `doppio/commands/frappe_lint.py` for the bench command wrappers.
"""

__version__ = "0.1.0-prototype"
