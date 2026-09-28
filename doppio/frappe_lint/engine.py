"""
Core engine: rule registry, diagnostic type, and the AST walk that drives
every Tier-B (Python-class) rule. Tier-A (YAML) rules are loaded separately
in yaml_engine.py and plug into the same Diagnostic/Context shapes.
"""
from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from difflib import get_close_matches

from doppio.frappe_lint.schema import SchemaIndex


@dataclass
class Diagnostic:
    rule_id: str
    message: str
    file: str
    line: int
    severity: str = "warn"   # error | warn | info | off
    fix: str | None = None
    origin: str = "py"       # "py" or "yaml", for provenance in reports

    def key(self) -> str:
        """Stable-ish identity for baselining: rule + file + line."""
        return f"{self.rule_id}:{self.file}:{self.line}"


class RuleContext:
    """Passed to every rule's visit_* call. Holds whatever cross-file/global
    state a rule declared it needs (via @rule(needs=[...]))."""

    def __init__(self, path: str, source: str, tree: ast.AST, schema: SchemaIndex | None,
                 project_index: "ProjectIndex | None" = None):
        self.path = path
        self.source = source
        self.lines = source.splitlines()
        self.tree = tree
        self.schema = schema
        self.project = project_index

    def diag(self, node: ast.AST, message: str, rule_id: str, severity: str = "warn",
              fix: str | None = None) -> Diagnostic:
        return Diagnostic(rule_id=rule_id, message=message, file=self.path,
                           line=getattr(node, "lineno", 0), severity=severity, fix=fix)

    def suggest_closest(self, name: str, candidates) -> str | None:
        matches = get_close_matches(name, list(candidates), n=1, cutoff=0.6)
        return matches[0] if matches else None

    def resolve_doctype_call(self, node: ast.Call):
        """For frappe.get_all/get_list/db.get_all(...): return (doctype, [fieldnames])."""
        func = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
        target_fns = {
            "frappe.get_all", "frappe.get_list", "frappe.db.get_all",
            "frappe.db.get_list",
        }
        if func not in target_fns or not node.args:
            return None, []
        arg0 = node.args[0]
        if not (isinstance(arg0, ast.Constant) and isinstance(arg0.value, str)):
            return None, []
        doctype = arg0.value
        fields = []
        for kw in node.keywords:
            if kw.arg == "fields" and isinstance(kw.value, ast.List):
                for elt in kw.value.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        fields.append(elt.value)
        return doctype, fields


_REGISTRY: list[type] = []


def rule(id: str, severity: str = "warn", needs: list[str] | None = None):
    """Decorator: registers a FrappeRule subclass so it runs automatically.
    Adding a Tier-B rule is: write the class, decorate it, done -- no
    separate registration file to edit."""
    def wrap(cls):
        cls.rule_id = id
        cls.default_severity = severity
        cls.needs = needs or []
        _REGISTRY.append(cls)
        return cls
    return wrap


def registered_rules() -> list[type]:
    return list(_REGISTRY)


class FrappeRule:
    """Base class for Tier-B rules. Subclass, implement visit_* methods that
    `yield` Diagnostics via ctx.diag(...), decorate with @rule(...).

    Deliberately does NOT inherit ast.NodeVisitor: that class ships
    deprecated visit_Constant/visit_Num/visit_Str compatibility stubs that
    would otherwise get picked up by the dispatch below on every subclass
    that never defined them, crashing with a wrong-arity TypeError."""
    rule_id: str = ""
    default_severity: str = "warn"
    needs: list[str] = []

    def __init__(self, ctx: RuleContext):
        self.ctx = ctx
        self.findings: list[Diagnostic] = []

    def run(self) -> list[Diagnostic]:
        own_methods = set()
        for klass in type(self).__mro__:
            if klass in (FrappeRule, object):
                continue
            own_methods.update(k for k in vars(klass) if k.startswith("visit_"))
        for node in ast.walk(self.ctx.tree):
            method = "visit_" + type(node).__name__
            if method not in own_methods:
                continue
            visitor = getattr(self, method)
            result = visitor(node, self.ctx)
            if result is None:
                continue
            if isinstance(result, Diagnostic):
                self.findings.append(result)
            else:
                self.findings.extend(d for d in result if d)
        return self.findings


WILDCARD = "{*}"


def compute_shape(node: ast.AST, local_shapes: dict, helper_shapes: dict, depth: int = 0) -> str:
    """Resolve an expression that builds a cache-key string into a "shape":
    the literal parts kept as-is, every dynamic part collapsed to a single
    WILDCARD token. f"bs:{job_id}" -> "bs:{*}". A Name is resolved through
    local_shapes (same-function assignments); a Call to a known helper is
    resolved through helper_shapes (project-wide single-return functions).
    This is what lets the cache rule tell "same key family, different
    dynamic suffix" apart from "genuinely unrelated key" -- both a set-site
    and its invalidator reduce to the same shape when they're really the
    same key.
    """
    if depth > 6:
        return WILDCARD
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            elif isinstance(v, ast.FormattedValue):
                parts.append(compute_shape(v.value, local_shapes, helper_shapes, depth + 1))
            else:
                parts.append(WILDCARD)
        return "".join(parts)
    if isinstance(node, ast.Name):
        return local_shapes.get(node.id, WILDCARD)
    if isinstance(node, ast.Call):
        fn_name = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
        base = fn_name.split(".")[-1]
        if base in helper_shapes:
            return helper_shapes[base]
        return WILDCARD
    return WILDCARD


def _function_local_shapes(func_node, helper_shapes: dict) -> dict:
    """Walk a function body in source order, tracking simple `name = <expr>`
    assignments as key shapes so later references in the same function can
    resolve through them (one level of local dataflow, no branch merging --
    a deliberate prototype simplification)."""
    local_shapes: dict = {}
    for node in ast.walk(func_node):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            shape = compute_shape(node.value, local_shapes, helper_shapes)
            if shape != WILDCARD:
                local_shapes[node.targets[0].id] = shape
    return local_shapes


def _single_return_shape(func_node) -> str | None:
    returns = [n for n in ast.walk(func_node) if isinstance(n, ast.Return) and n.value is not None]
    if len(returns) != 1:
        return None
    return compute_shape(returns[0].value, {}, {})


class ProjectIndex:
    """Lightweight whole-project facts that need more than one file to
    compute: every cache-key shape ever deleted, every helper function that
    builds a cache key, every hooks.py dotted path. Built once per run
    before rules execute, so per-file rules can ask "does *anything* in
    this project invalidate a key shaped like this?" without re-walking
    the whole tree themselves."""

    def __init__(self, root: str):
        self.root = root
        self.deleted_shapes: set[str] = set()
        self.helper_key_shapes: dict[str, str] = {}
        self.hooks_dotted_paths: set[str] = set()
        self.files: list[str] = []

    @classmethod
    def build(cls, root: str) -> "ProjectIndex":
        idx = cls(root)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in
                           ("node_modules", "__pycache__", ".git", "frappe_lint")]
            for fn in filenames:
                if fn.endswith(".py"):
                    idx.files.append(os.path.join(dirpath, fn))

        parsed = {}
        for path in idx.files:
            try:
                src = open(path, encoding="utf-8").read()
                parsed[path] = ast.parse(src)
            except (SyntaxError, OSError, UnicodeDecodeError):
                continue

        # Pass 1: every module-level helper with a single return statement
        # that builds a string -- e.g. `def _cache_key(user): return f"doctype_list:{user}"`.
        for path, tree in parsed.items():
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    shape = _single_return_shape(node)
                    if shape is not None:
                        idx.helper_key_shapes[node.name] = shape

        # Pass 2: every delete_value(...)/.delete(...) call, resolved to a shape
        # using the helper shapes from pass 1 plus that function's own locals.
        for path, tree in parsed.items():
            for func in ast.walk(tree):
                if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                    continue
                local_shapes = _function_local_shapes(func, idx.helper_key_shapes)
                for node in ast.walk(func):
                    if not isinstance(node, ast.Call):
                        continue
                    fn_name = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
                    if fn_name.endswith("delete_value") or fn_name.endswith(".delete"):
                        for a in node.args:
                            idx.deleted_shapes.add(compute_shape(a, local_shapes, idx.helper_key_shapes))

            if os.path.basename(path) == "hooks.py":
                for node in ast.walk(tree):
                    if isinstance(node, ast.Constant) and isinstance(node.value, str):
                        if "." in node.value and " " not in node.value:
                            idx.hooks_dotted_paths.add(node.value)
        return idx

    def key_is_invalidated(self, shape: str) -> bool:
        if shape == WILDCARD:
            return True  # fully dynamic key, nothing we can check -- don't false-positive
        for deleted in self.deleted_shapes:
            if deleted == shape or shape.startswith(deleted) or deleted.startswith(shape):
                return True
        return False
