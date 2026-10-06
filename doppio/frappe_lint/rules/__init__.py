"""Importing this package registers every Tier-B (Python-class) rule via the
@rule decorator's side effect. Adding a new Tier-B rule = add a file here
and import it below; no separate registry to hand-maintain."""

from doppio.frappe_lint.rules import (  # noqa: F401
    schema_rules, cache_rules, security_rules, perf_rules, txn_rules, complexity_rules,
)
