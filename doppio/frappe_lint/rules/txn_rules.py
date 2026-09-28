"""
Tier 4: transaction-boundary rules. Both need to know whether a
frappe.db.commit() call sits somewhere it shouldn't -- inside a
request-scoped (whitelisted) function, or inside a loop -- which is
structural, not a text pattern.

FRP-TXN002's severity was originally "error" on the assumption that
per-iteration commits are almost always wrong. Verifying it against a
real app immediately contradicted that: every real hit was either
explicitly comment-documented as a deliberate checkpoint ("commit after
each batch", "commit per doctype" -- so a crash partway through a
long-running restore doesn't lose everything already processed), a
negligible fixed-size test loop, or an early-return-after-one-commit
shape that isn't really "per iteration" in the harmful sense at all.
Zero of the real hits were bugs. Shipped at "info" instead -- the pattern
is still worth a human glance (it *can* be a real N+1-commit bug), but it
should never gate CI on its own judgment, because "commit inside a loop"
just isn't reliably wrong the way a bare except or a SQL injection is.
"""
from __future__ import annotations

import ast

from doppio.frappe_lint.engine import FrappeRule, RuleContext, rule, is_whitelisted, safe_unparse


@rule(id="FRP-TXN001", severity="warn")
class ManualCommitInRequestScope(FrappeRule):
    """An explicit frappe.db.commit() inside a @frappe.whitelist()'d
    function. Frappe already commits at the end of a successful request,
    so this is at minimum redundant -- and if the function later grows
    another statement after this commit that can fail, there's nothing
    left to roll back once this line has already run."""

    def run(self):
        for func in self.ctx.tree.body:
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not is_whitelisted(func):
                continue
            for node in ast.walk(func):
                if isinstance(node, ast.Call) and safe_unparse(node.func) == "frappe.db.commit":
                    msg = ("explicit frappe.db.commit() inside a whitelisted (request-scoped) "
                           "function -- Frappe already commits at the end of a successful "
                           "request, so this is redundant, and risks leaving a partial "
                           "transaction committed if a later statement ever gets added after it")
                    self.findings.append(self.ctx.diag(node, msg, self.rule_id, self.default_severity))
        return self.findings


@rule(id="FRP-TXN002", severity="info")
class CommitInsideLoop(FrappeRule):
    """frappe.db.commit() reachable inside a for/while loop. Can be a real
    N+1-commit bug (needless per-iteration overhead with no benefit) --
    but just as often it's a deliberate checkpoint in a long-running
    batch/restore job, so a mismatch or crash partway through doesn't
    lose everything already processed. This rule can't tell those apart
    from the AST alone, which is why it's info-level: worth a glance,
    never a CI gate on its own say-so."""

    def run(self):
        seen_ids: set[int] = set()
        for loop in ast.walk(self.ctx.tree):
            if not isinstance(loop, (ast.For, ast.AsyncFor, ast.While)):
                continue
            for node in ast.walk(loop):
                if isinstance(node, ast.Call) and safe_unparse(node.func) == "frappe.db.commit":
                    if id(node) in seen_ids:
                        continue
                    seen_ids.add(id(node))
                    msg = ("frappe.db.commit() inside a loop -- commits once per iteration. "
                           "If this is a deliberate checkpoint in a long batch job, ignore; if "
                           "it's meant to run once after the whole batch, move it outside the loop")
                    self.findings.append(self.ctx.diag(node, msg, self.rule_id, self.default_severity))
        return self.findings
