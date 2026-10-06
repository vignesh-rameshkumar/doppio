"""
Tier 4: general readability/complexity rules -- no schema, no project
index, no Frappe-specific API knowledge needed, just AST shape.
"""
from __future__ import annotations

import ast

from doppio.frappe_lint.engine import FrappeRule, RuleContext, rule

# Fixed for now, not read from frappe_lint.toml: no rule in this codebase
# is parameterized beyond severity/path overrides yet (LintConfig applies
# those as post-processing on returned diagnostics; rules never see
# LintConfig at construction time). Making the threshold configurable
# needs that plumbing built out as its own deliberate change, not bolted
# on as a side effect of this one rule.
_MAX_IF_DEPTH = 4


def _max_if_depth(stmts: list[ast.stmt], depth: int = 0) -> int:
    """Depth of the deepest genuinely-nested `if` in a list of statements.

    Critical distinction, found by checking this against real code before
    shipping it: Python's ast represents `elif` (and `else: if ...:`
    written out explicitly) as a nested If inside `orelse` -- structurally
    identical to real nesting. A naive walk that counts every If as +1
    depth badly misfires on a long if/elif ladder (an operator-dispatch
    table in this repo hit "depth 21" that way -- it's a flat chain, not
    a pyramid). So: descending into `if.body` (the true branch) is a
    genuine +1 step; descending into `if.orelse` (whether it's an elif or
    an explicit else) stays at the SAME depth, since it's a sibling
    branch, not a deeper level -- though anything genuinely nested inside
    that else block still counts from there.

    Deliberately stops at a nested function/class definition: that's its
    own lexical scope with its own readability concern, evaluated
    independently when the outer AST walk reaches it as its own
    FunctionDef, not blended into the depth of whatever encloses it.
    """
    best = depth
    for s in stmts:
        if isinstance(s, ast.If):
            best = max(best, _max_if_depth(s.body, depth + 1))
            if s.orelse:
                best = max(best, _max_if_depth(s.orelse, depth))
        elif isinstance(s, (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith)):
            best = max(best, _max_if_depth(s.body, depth))
        elif isinstance(s, ast.Try):
            best = max(best, _max_if_depth(s.body, depth))
            for h in s.handlers:
                best = max(best, _max_if_depth(h.body, depth))
            best = max(best, _max_if_depth(s.orelse, depth))
            best = max(best, _max_if_depth(s.finalbody, depth))
        # ast.FunctionDef / ast.AsyncFunctionDef / ast.ClassDef: deliberately
        # not descended into here -- own scope, own independent depth count.
    return best


@rule(id="FRP-HYG002", severity="info")
class DeeplyNestedIf(FrappeRule):
    """A function whose `if` blocks nest more than a few levels deep --
    readability, not correctness: nothing here is wrong, just harder to
    follow than an early-return or a lookup table would be. elif/else
    chains are deliberately not counted as nesting (see _max_if_depth's
    docstring) -- only a genuinely nested `if` inside another `if`'s
    true branch."""

    def visit_FunctionDef(self, node, ctx: RuleContext):
        return self._check(node, ctx)

    def visit_AsyncFunctionDef(self, node, ctx: RuleContext):
        return self._check(node, ctx)

    def _check(self, node, ctx: RuleContext):
        depth = _max_if_depth(node.body)
        if depth < _MAX_IF_DEPTH:
            return None
        msg = (f"'{node.name}' nests if-blocks {depth} levels deep (elif/else chains not "
               f"counted) -- consider early returns or a lookup table instead of a pyramid")
        return ctx.diag(node, msg, self.rule_id, self.default_severity)
