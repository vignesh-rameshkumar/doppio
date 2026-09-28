"""
Tier 4 custom rule: cache writes with no TTL and no reachable invalidation.

Deliberately NOT a "no expires_in_sec kwarg" grep. That heuristic
mis-flags any permission-style cache that has no TTL but IS correctly
invalidated on a doc_event wired in hooks.py. The only way to avoid that
false positive is to actually trace where the key comes from (a local
f-string? a helper function's return value?) and check whether anything in
the project deletes a key shaped the same way. See engine.py:compute_shape.
"""
from __future__ import annotations

import ast

from doppio.frappe_lint.engine import (
    FrappeRule, RuleContext, rule, compute_shape, _function_local_shapes, WILDCARD,
)

_TTL_KWARGS = {"expires_in_sec", "ex", "expiry", "ttl"}
_SET_METHOD_SUFFIXES = (".set_value", ".set")


@rule(id="FRP-CACHE001", severity="warn", needs=["project"])
class CacheWriteWithoutInvalidation(FrappeRule):
    """frappe.cache().set_value(key, val) / .set(key, val) with no TTL kwarg
    AND no delete_value/.delete(...) anywhere in the project that resolves
    to the same key shape. Flags real leaks, not just missing kwargs."""

    def run(self):
        if self.ctx.project is None:
            return []
        local_shapes = _function_local_shapes(self.ctx.tree, self.ctx.project.helper_key_shapes)
        for node in ast.walk(self.ctx.tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            fn_name = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
            if not any(fn_name.endswith(s) for s in _SET_METHOD_SUFFIXES):
                continue
            if "cache" not in fn_name:
                continue
            kwargs = {kw.arg for kw in node.keywords}
            if kwargs & _TTL_KWARGS:
                continue  # has a TTL, nothing to flag
            shape = compute_shape(node.args[0], local_shapes, self.ctx.project.helper_key_shapes)
            if self.ctx.project.key_is_invalidated(shape):
                continue
            readable = shape.replace(WILDCARD, "<dynamic>")
            msg = (f"cache write '{readable}' has no TTL and no matching "
                   f"delete_value()/.delete() found anywhere in the project")
            self.findings.append(self.ctx.diag(node, msg, self.rule_id, self.default_severity))
        return self.findings


@rule(id="FRP-CACHE006", severity="info", needs=["project"])
class CacheKeyFamilyShouldBeHash(FrappeRule):
    """4+ separate set_value calls in one function writing to the same key
    shape with different literal suffixes (":total", ":status", ...) --
    should be one Redis hash with one TTL, not N scalar keys that can be
    partially evicted under LRU memory pressure."""

    def run(self):
        if self.ctx.project is None:
            return []
        for func in ast.walk(self.ctx.tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            local_shapes = _function_local_shapes(func, self.ctx.project.helper_key_shapes)
            families: dict[str, list[ast.Call]] = {}
            for node in ast.walk(func):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                fn_name = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
                if not any(fn_name.endswith(s) for s in _SET_METHOD_SUFFIXES) or "cache" not in fn_name:
                    continue
                shape = compute_shape(node.args[0], local_shapes, self.ctx.project.helper_key_shapes)
                if WILDCARD not in shape:
                    continue
                family = shape[: shape.rfind(WILDCARD) + len(WILDCARD)]
                families.setdefault(family, []).append(node)
            for family, calls in families.items():
                if len(calls) >= 4:
                    first = calls[0]
                    msg = (f"{len(calls)} separate cache keys share the prefix "
                           f"'{family.replace(WILDCARD, '<dynamic>')}' in this function -- "
                           f"consider one hash with a single TTL instead of N scalar keys")
                    self.findings.append(self.ctx.diag(first, msg, self.rule_id, self.default_severity))
        return self.findings
