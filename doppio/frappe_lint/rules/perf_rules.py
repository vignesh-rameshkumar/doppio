"""
Tier 4: performance patterns that need only the AST of one file, no
schema or cross-file index -- but still need real structural understanding
(is this call inside a loop? does it already bound its result set?), not
a text pattern.
"""
from __future__ import annotations

import ast

from doppio.frappe_lint.engine import FrappeRule, RuleContext, rule, safe_unparse

# Read-oriented / single-record calls: the classic N+1 shape is fetching
# one record's worth of data per loop iteration instead of bulk-fetching
# before the loop. Deliberately excludes doc.save()/doc.insert() -- saving
# each of a batch of already-fetched docs one at a time is a normal ORM
# bulk-update pattern, not the "raw read per iteration" this rule targets;
# flagging it would just be noise on legitimate code.
_PER_ITERATION_DB_CALLS = {
    "frappe.get_doc", "frappe.db.get_value", "frappe.get_all", "frappe.get_list",
    "frappe.db.sql", "frappe.db.exists", "frappe.db.set_value", "frappe.db.count",
}

_UNBOUNDED_CALL_NAMES = {
    "frappe.get_all", "frappe.get_list", "frappe.db.get_all", "frappe.db.get_list",
}
_LIMIT_KWARGS = {"limit_page_length", "limit", "page_length"}


@rule(id="FRP-PERF01", severity="warn")
class DbCallInsideLoop(FrappeRule):
    """A DB read/write call reachable inside a for/while loop body -- runs
    once per iteration (N+1) instead of once, bulk-fetched before the
    loop. Doesn't flag doc.save()/doc.insert() on already-fetched
    records -- see module docstring."""

    def run(self):
        seen_ids: set[int] = set()
        for loop in ast.walk(self.ctx.tree):
            if not isinstance(loop, (ast.For, ast.AsyncFor, ast.While)):
                continue
            for node in ast.walk(loop):
                if not isinstance(node, ast.Call):
                    continue
                fn_name = safe_unparse(node.func)
                if fn_name not in _PER_ITERATION_DB_CALLS:
                    continue
                if id(node) in seen_ids:
                    continue  # already reported via an outer loop's walk (nested loops)
                seen_ids.add(id(node))
                msg = (f"'{fn_name}(...)' runs a DB query on every loop iteration (N+1) -- "
                       f"fetch this in bulk before the loop instead")
                self.findings.append(self.ctx.diag(node, msg, self.rule_id, self.default_severity))
        return self.findings


@rule(id="FRP-PERF02", severity="info")
class UnboundedGetAll(FrappeRule):
    """get_all/get_list/db.get_all/db.get_list with no limit -- fine on a
    small table today, loads the whole table into memory as it grows.
    Deliberately doesn't touch frappe.db.count() or similar, which are
    legitimately unbounded by design."""

    def visit_Call(self, node: ast.Call, ctx: RuleContext):
        fn_name = safe_unparse(node.func)
        if fn_name not in _UNBOUNDED_CALL_NAMES:
            return None
        kwargs = {kw.arg for kw in node.keywords}
        if kwargs & _LIMIT_KWARGS:
            return None
        msg = (f"'{fn_name}(...)' has no limit -- an unbounded result set can load the "
               f"entire table into memory as the underlying data grows")
        return ctx.diag(node, msg, self.rule_id, self.default_severity)
