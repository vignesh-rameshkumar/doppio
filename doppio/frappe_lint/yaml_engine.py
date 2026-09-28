"""
Tier A: declarative rules. Drop a .yaml file in rules.d/ and it's picked up
on the next run -- no Python, no import, no restart of anything (an LSP
would file-watch this directory; a bench command just re-globs it each run,
which is the same end result for "add a rule tomorrow").

Deliberately small surface: this engine only expresses "a call to X (as a
plain call or a decorator) is forbidden, or must/must-not carry a given
keyword argument". Anything needing dataflow, cross-file resolution, or the
DocType schema belongs in a Tier-B Python rule instead -- see rules/*.py
for where that line actually falls (the cache-invalidation and schema
rules could NOT be expressed here).
"""
from __future__ import annotations

import ast
import glob
import os

import yaml

from doppio.frappe_lint.engine import Diagnostic


class YamlRule:
    def __init__(self, spec: dict, source_file: str):
        self.id = spec["id"]
        self.message = spec["message"]
        self.severity = spec.get("severity", "warn")
        self.node_kind = spec.get("node_kind", "call")
        self.call = spec.get("call")
        self.require_kwarg = spec.get("require_kwarg")
        if isinstance(self.require_kwarg, str):
            self.require_kwarg = [self.require_kwarg]
        self.forbidden = spec.get("forbidden", False)
        self.forbidden_kwarg_value = spec.get("forbidden_kwarg_value", {})
        self.path_exclude = spec.get("path_exclude", [])
        self.source_file = source_file

    def applies_to_path(self, path: str) -> bool:
        norm = path.replace("\\", "/")
        return not any(sub in norm for sub in self.path_exclude)

    def check_call(self, node: ast.Call) -> str | None:
        fn_name = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
        if self.call and fn_name != self.call and fn_name.split(".")[-1] != self.call:
            return None
        if self.forbidden:
            return self.message
        if self.require_kwarg:
            present = {kw.arg for kw in node.keywords}
            if not (present & set(self.require_kwarg)):
                return self.message
        if self.forbidden_kwarg_value:
            for kw in node.keywords:
                if kw.arg in self.forbidden_kwarg_value:
                    want = self.forbidden_kwarg_value[kw.arg]
                    if isinstance(kw.value, ast.Constant) and kw.value.value == want:
                        return self.message
        return None


def load_yaml_rules(rules_dir: str) -> list[YamlRule]:
    out = []
    for path in sorted(glob.glob(os.path.join(rules_dir, "*.yaml"))):
        with open(path, encoding="utf-8") as fh:
            spec = yaml.safe_load(fh)
        if not spec or spec.get("id") in (None,):
            continue
        if spec.get("deprecated"):
            continue
        out.append(YamlRule(spec, source_file=path))
    return out


def run_yaml_rules(rules: list[YamlRule], path: str, tree: ast.AST) -> list[Diagnostic]:
    out = []
    applicable = [r for r in rules if r.applies_to_path(path)]
    if not applicable:
        return out

    # Decorator Call nodes (e.g. the `frappe.whitelist(...)` in `@frappe.whitelist()`)
    # are already reachable through the plain ast.Call branch below via ast.walk,
    # since decorator_list is just another child list on the FunctionDef. Track
    # their ids so we check each one exactly once, anchored to the def line
    # (more useful than the decorator's own line, and it avoids double-reporting
    # the same violation once per branch).
    decorator_ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call):
                    decorator_ids.add(id(dec))
                    for r in applicable:
                        if r.node_kind != "call":
                            continue
                        msg = r.check_call(dec)
                        if msg:
                            out.append(Diagnostic(rule_id=r.id, message=msg, file=path,
                                                   line=node.lineno, severity=r.severity, origin="yaml"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if id(node) in decorator_ids:
                continue
            for r in applicable:
                if r.node_kind != "call":
                    continue
                msg = r.check_call(node)
                if msg:
                    out.append(Diagnostic(rule_id=r.id, message=msg, file=path,
                                           line=node.lineno, severity=r.severity, origin="yaml"))
        elif isinstance(node, ast.ExceptHandler):
            for r in applicable:
                if r.node_kind == "bare_except" and node.type is None:
                    out.append(Diagnostic(rule_id=r.id, message=r.message, file=path,
                                           line=node.lineno, severity=r.severity, origin="yaml"))
                elif r.node_kind == "except_pass" and node.type is not None \
                        and len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    out.append(Diagnostic(rule_id=r.id, message=r.message, file=path,
                                           line=node.lineno, severity=r.severity, origin="yaml"))
    return out
