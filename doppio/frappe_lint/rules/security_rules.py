"""
Tier 1, and the hardest rule in the set: SQL injection via a
dynamically-built frappe.db.sql() string.

Deliberately NOT a "db.sql() called with an f-string" pattern match --
that shape alone was rejected early in this project because it flags safe
code. The reference case: an app's project-search endpoint builds its
WHERE clause as an f-string, but the f-string is assembled entirely from
string literals plus `+=`, and the one real user-supplied value only ever
reaches the query through a %(query)s bound placeholder -- never through
string interpolation. A bare pattern match calls that injection. It isn't.

So instead of matching syntax shape, this traces whether the *value
actually interpolated* into a dynamically-built SQL string can be reached
from a request-controlled source:
  - a parameter of a @frappe.whitelist()-decorated function, or
  - a direct read of frappe.form_dict / frappe.local.form_dict /
    frappe.request.args / frappe.local.request.args (always
    request-controlled, regardless of which function reads it).

Taint propagates through same-function variable assignment and
augmented assignment (`x = y`, `x += f"...{y}..."`) to a fixed point,
then is checked against the three ways a SQL string actually gets built
dynamically at (or resolvable from) the frappe.db.sql() call site: an
f-string, a `.format(...)` call, or a `%` operator. A plain string
literal -- even one built from a tainted value passed as a *bound*
parameter (`%(name)s` + a params dict) rather than interpolated into the
SQL text -- is never flagged, because binding is the actual fix, not
merely "did request data touch this function."

Known limitations, stated rather than silently shipped:
  - Intraprocedural only. If a whitelisted function passes its parameter
    into a helper, and the helper does its own unsafe interpolation with
    it, this rule won't connect the two -- that needs a call graph,
    which is future work, not this rule.
  - Only top-level (module-scope) function defs are treated as their own
    taint scope. A nested function reuses its enclosing function's taint
    set rather than getting its own -- Frappe API modules essentially
    never nest handlers, so this is a deliberate simplification, not an
    oversight.
"""
from __future__ import annotations

import ast

from doppio.frappe_lint.engine import FrappeRule, RuleContext, rule, is_whitelisted, safe_unparse

_TAINT_SOURCE_PREFIXES = (
    "frappe.form_dict", "frappe.local.form_dict",
    "frappe.request.args", "frappe.local.request.args",
)

_MAX_RESOLVE_DEPTH = 4


def _expr_touches_taint_source(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, (ast.Attribute, ast.Subscript, ast.Call)):
            if safe_unparse(sub).startswith(_TAINT_SOURCE_PREFIXES):
                return True
    return False


def _expr_is_tainted(node: ast.AST, tainted_names: set[str]) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in tainted_names:
            return True
    return _expr_touches_taint_source(node)


def _propagate_taint(func, seed: set[str]) -> set[str]:
    tainted = set(seed)
    changed = True
    while changed:
        changed = False
        for node in ast.walk(func):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name not in tainted and _expr_is_tainted(node.value, tainted):
                    tainted.add(name)
                    changed = True
            elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                # x += y: tainted if x already was, or y newly is (e.g. base_sql
                # built purely from literals via += never gets marked -- correct,
                # since neither the prior value nor a plain-literal RHS is tainted)
                name = node.target.id
                if name not in tainted and _expr_is_tainted(node.value, tainted):
                    tainted.add(name)
                    changed = True
    return tainted


def _local_assignments(func) -> dict:
    """Last assignment per simple name -- used to resolve a bare Name
    passed straight to db.sql() back to the expression that built it."""
    out = {}
    for node in ast.walk(func):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            out[node.targets[0].id] = node.value
    return out


def _find_tainted_interpolation(sql_arg: ast.AST, tainted: set[str], locals_map: dict,
                                 depth: int = 0) -> str | None:
    if depth > _MAX_RESOLVE_DEPTH:
        return None
    if isinstance(sql_arg, ast.JoinedStr):
        for v in sql_arg.values:
            if isinstance(v, ast.FormattedValue) and _expr_is_tainted(v.value, tainted):
                return safe_unparse(v.value)
        return None
    if isinstance(sql_arg, ast.Call) and safe_unparse(sql_arg.func).endswith(".format"):
        for a in list(sql_arg.args) + [kw.value for kw in sql_arg.keywords]:
            if _expr_is_tainted(a, tainted):
                return safe_unparse(a)
        return None
    if isinstance(sql_arg, ast.BinOp) and isinstance(sql_arg.op, ast.Mod):
        if _expr_is_tainted(sql_arg.right, tainted):
            return safe_unparse(sql_arg.right)
        return None
    if isinstance(sql_arg, ast.Name) and sql_arg.id in locals_map:
        return _find_tainted_interpolation(locals_map[sql_arg.id], tainted, locals_map, depth + 1)
    return None


@rule(id="FRP-SEC001", severity="error")
class SqlInjectionRisk(FrappeRule):
    """frappe.db.sql() built with an f-string / .format() / % operator
    where the interpolated value traces back to a whitelisted function's
    parameter or a direct form_dict/request.args read -- not just any
    dynamically-built SQL string (see module docstring for why that
    distinction is the whole point of this rule)."""

    def run(self):
        for func in self.ctx.tree.body:
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            seed = set()
            if is_whitelisted(func):
                seed |= {a.arg for a in func.args.args}
                seed |= {a.arg for a in func.args.kwonlyargs}
            tainted = _propagate_taint(func, seed)
            locals_map = _local_assignments(func)

            for node in ast.walk(func):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                if safe_unparse(node.func) != "frappe.db.sql":
                    continue
                culprit = _find_tainted_interpolation(node.args[0], tainted, locals_map)
                if culprit:
                    msg = (f"frappe.db.sql() interpolates '{culprit}', which traces back to "
                           f"request-controlled input -- use a %(name)s placeholder and pass "
                           f"the value as a bound parameter instead")
                    self.findings.append(self.ctx.diag(node, msg, self.rule_id, self.default_severity))
        return self.findings
