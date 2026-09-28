"""
Tier 2: rules that need the cross-app DocType schema index to resolve.
This is the family that a generic linter (ruff, semgrep-without-context)
cannot express, because "is this a real field on this DocType" isn't a
syntax question -- it needs every installed app's doctype JSON loaded.
"""
from __future__ import annotations

import ast
import os
import re

from doppio.frappe_lint.engine import FrappeRule, RuleContext, rule

# A plausible Python dotted import path: "module.sub.func". Deliberately
# app-name-agnostic (earlier drafts hardcoded "core."/"frappe."/"erpnext."
# which only worked because this was first built against one specific
# app) -- real disambiguation happens below by checking whether the path
# actually resolves to a file in this project's own index; anything that
# doesn't resolve is assumed to belong to a different installed app and
# silently skipped, same as before.
_DOTTED_PATH_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)+$")

_DOCTYPE_CALL_NAMES = {
    "frappe.get_all", "frappe.get_list", "frappe.db.get_all",
    "frappe.db.get_list", "frappe.get_doc", "frappe.new_doc",
    "frappe.db.get_value", "frappe.db.exists", "frappe.db.count",
}


@rule(id="FRP-SCH001", severity="error", needs=["schema"])
class UnknownDocType(FrappeRule):
    """A string literal passed as a DocType name to a Frappe data API that
    doesn't resolve to any doctype/*.json across the installed apps."""

    def visit_Call(self, node: ast.Call, ctx: RuleContext):
        if ctx.schema is None:
            return None
        func = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
        if func not in _DOCTYPE_CALL_NAMES or not node.args:
            return None
        arg0 = node.args[0]
        if not (isinstance(arg0, ast.Constant) and isinstance(arg0.value, str)):
            return None  # dynamic doctype name -- can't resolve statically
        doctype = arg0.value
        if doctype in ctx.schema:
            return None
        suggestion = ctx.suggest_closest(doctype, ctx.schema.doctypes.keys())
        msg = f"'{doctype}' does not match any installed DocType"
        if suggestion:
            msg += f" (did you mean '{suggestion}'?)"
        return ctx.diag(node, msg, self.rule_id, self.default_severity, fix=suggestion)


@rule(id="FRP-SCH002", severity="error", needs=["schema"])
class UnknownField(FrappeRule):
    """A fieldname passed in fields=[...] that isn't declared on the
    resolved DocType (and isn't one of the implicit Frappe fields)."""

    def visit_Call(self, node: ast.Call, ctx: RuleContext):
        if ctx.schema is None:
            return None
        doctype, fields = ctx.resolve_doctype_call(node)
        if not doctype or doctype not in ctx.schema:
            return None
        out = []
        info = ctx.schema[doctype]
        for f in fields:
            base = f.split(" as ")[0].strip()
            if base in ("*",) or base.startswith("`"):
                continue
            if not ctx.schema.has_field(doctype, base):
                suggestion = ctx.suggest_closest(base, info.fields)
                msg = f"{doctype} has no field '{base}'"
                if suggestion:
                    msg += f" (did you mean '{suggestion}'?)"
                out.append(ctx.diag(node, msg, self.rule_id, self.default_severity, fix=suggestion))
        return out


def _filter_fieldnames(value_node: ast.AST):
    """Yield (fieldname, anchor_node) from a filters= argument. Frappe
    accepts two shapes: a dict ({"status": "Active"} or {"status": ["in", [...]]}
    -- the key is the fieldname either way) and a list of [field, op, value]
    triples. Anything else (a Name pointing at a variable built elsewhere,
    a function call) can't be resolved statically -- yield nothing rather
    than guess, same principle as everywhere else in this rule family."""
    if isinstance(value_node, ast.Dict):
        for k in value_node.keys:
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                yield k.value, k
    elif isinstance(value_node, (ast.List, ast.Tuple)):
        for elt in value_node.elts:
            if isinstance(elt, (ast.List, ast.Tuple)) and elt.elts:
                first = elt.elts[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    yield first.value, first


@rule(id="FRP-SCH003", severity="error", needs=["schema"])
class UnknownFilterOrOrderByField(FrappeRule):
    """A fieldname in filters=... or order_by=... on a get_all/get_list/
    db.get_all/db.get_list call that isn't on the resolved DocType. Same
    failure mode as FRP-SCH002 (a typo that's invisible until the request
    runs) but for the other two places a fieldname shows up in these
    calls, which SCH002 -- scoped to fields=[...] only -- doesn't cover."""

    def visit_Call(self, node: ast.Call, ctx: RuleContext):
        if ctx.schema is None:
            return None
        func = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
        if func not in _DOCTYPE_CALL_NAMES or not node.args:
            return None
        arg0 = node.args[0]
        if not (isinstance(arg0, ast.Constant) and isinstance(arg0.value, str)):
            return None
        doctype = arg0.value
        if doctype not in ctx.schema:
            return None
        info = ctx.schema[doctype]
        out = []
        for kw in node.keywords:
            if kw.arg == "filters":
                for fieldname, anchor in _filter_fieldnames(kw.value):
                    if not ctx.schema.has_field(doctype, fieldname):
                        suggestion = ctx.suggest_closest(fieldname, info.fields)
                        msg = f"{doctype} has no field '{fieldname}' (in filters=...)"
                        if suggestion:
                            msg += f" (did you mean '{suggestion}'?)"
                        out.append(ctx.diag(anchor, msg, self.rule_id, self.default_severity, fix=suggestion))
            elif kw.arg == "order_by" and isinstance(kw.value, ast.Constant) \
                    and isinstance(kw.value.value, str):
                for token in kw.value.value.split(","):
                    fieldname = token.strip().split(" ")[0].strip()
                    if not fieldname or fieldname.lower() in ("asc", "desc"):
                        continue
                    if not ctx.schema.has_field(doctype, fieldname):
                        suggestion = ctx.suggest_closest(fieldname, info.fields)
                        msg = f"{doctype} has no field '{fieldname}' (in order_by=...)"
                        if suggestion:
                            msg += f" (did you mean '{suggestion}'?)"
                        out.append(ctx.diag(kw.value, msg, self.rule_id, self.default_severity, fix=suggestion))
        return out


@rule(id="FRP-CFG004", severity="error")
class DuplicateDictKey(FrappeRule):
    """A dict literal with the same string key repeated. Python silently
    keeps only the last one -- always a bug: either dead code (the first
    value never takes effect) or a copy-paste mistake that dropped an
    earlier entry (e.g. two "post_self_info" keys in the same
    POST_CONFIGS dict -- exactly the silent-overwrite failure mode this
    whole config-registry rule family exists to catch).

    Scoped to duplicates within one dict literal, which is 100%
    statically decidable. The same key registered from two different
    FILES via register_config()/POST_CONFIGS merging at app-load time is
    just as real a bug, but needs whole-bench awareness (every app's
    config registrations, not just the one being linted) that this rule
    doesn't have -- not claimed as covered here, left as future work."""

    def visit_Dict(self, node: ast.Dict, ctx: RuleContext):
        seen: dict[str, int] = {}
        out = []
        for k in node.keys:
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                if k.value in seen:
                    msg = (f"duplicate key '{k.value}' -- the entry at line {seen[k.value]} "
                           f"is silently overwritten by this one")
                    out.append(ctx.diag(k, msg, self.rule_id, self.default_severity))
                else:
                    seen[k.value] = k.lineno
        return out


def _dict_str_value(dict_node: ast.Dict, key: str) -> ast.AST | None:
    for k, v in zip(dict_node.keys, dict_node.values):
        if isinstance(k, ast.Constant) and k.value == key:
            return v
    return None


@rule(id="FRP-CFG001", severity="error", needs=["schema"])
class ConfigUnknownDocType(FrappeRule):
    """A POST_CONFIGS / FIELD_CONFIG / GET_CONFIGS style dict literal whose
    "doctype" key names something not present in the schema index. These
    are silent until a request actually hits the endpoint at runtime."""

    def visit_Dict(self, node: ast.Dict, ctx: RuleContext):
        if ctx.schema is None:
            return None
        keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
        if "doctype" not in keys or "fields" not in keys:
            return None
        dt_node = _dict_str_value(node, "doctype")
        if not (isinstance(dt_node, ast.Constant) and isinstance(dt_node.value, str)):
            return None
        doctype = dt_node.value
        if doctype in ctx.schema:
            return None
        suggestion = ctx.suggest_closest(doctype, ctx.schema.doctypes.keys())
        msg = f"config entry names unknown DocType '{doctype}'"
        if suggestion:
            msg += f" (did you mean '{suggestion}'?)"
        return ctx.diag(dt_node, msg, self.rule_id, self.default_severity, fix=suggestion)


@rule(id="FRP-CFG002", severity="error", needs=["schema"])
class ConfigUnknownField(FrappeRule):
    """Same config dict literal, but validating each entry in its "fields"
    list against the resolved DocType's actual fields."""

    def visit_Dict(self, node: ast.Dict, ctx: RuleContext):
        if ctx.schema is None:
            return None
        keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
        if "doctype" not in keys or "fields" not in keys:
            return None
        dt_node = _dict_str_value(node, "doctype")
        fields_node = _dict_str_value(node, "fields")
        if not (isinstance(dt_node, ast.Constant) and isinstance(dt_node.value, str)):
            return None
        doctype = dt_node.value
        if doctype not in ctx.schema or not isinstance(fields_node, ast.List):
            return None
        info = ctx.schema[doctype]
        out = []
        for elt in fields_node.elts:
            if not (isinstance(elt, ast.Constant) and isinstance(elt.value, str)):
                continue
            base = elt.value.split(".")[0].strip()
            if not base or not ctx.schema.has_field(doctype, base):
                suggestion = ctx.suggest_closest(base, info.fields)
                msg = f"config for {doctype}: unknown field '{base}'"
                if suggestion:
                    msg += f" (did you mean '{suggestion}'?)"
                out.append(ctx.diag(elt, msg, self.rule_id, self.default_severity, fix=suggestion))
        return out


@rule(id="FRP-CFG003", severity="error", needs=["schema"])
class ConfigUnknownFilterField(FrappeRule):
    """Same config dict literal again, but validating filters.static's keys
    and filters.optional's entries -- the third place a fieldname shows up
    in a POST_CONFIGS/FIELD_CONFIG entry, after "doctype" (CFG001) and
    "fields" (CFG002)."""

    def visit_Dict(self, node: ast.Dict, ctx: RuleContext):
        if ctx.schema is None:
            return None
        keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
        if "doctype" not in keys or "fields" not in keys:
            return None
        dt_node = _dict_str_value(node, "doctype")
        if not (isinstance(dt_node, ast.Constant) and isinstance(dt_node.value, str)):
            return None
        doctype = dt_node.value
        if doctype not in ctx.schema:
            return None
        filters_node = _dict_str_value(node, "filters")
        if not isinstance(filters_node, ast.Dict):
            return None
        info = ctx.schema[doctype]
        out = []

        static_node = _dict_str_value(filters_node, "static")
        if isinstance(static_node, ast.Dict):
            for k in static_node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str) \
                        and not ctx.schema.has_field(doctype, k.value):
                    suggestion = ctx.suggest_closest(k.value, info.fields)
                    msg = f"config for {doctype}: unknown field '{k.value}' (in filters.static)"
                    if suggestion:
                        msg += f" (did you mean '{suggestion}'?)"
                    out.append(ctx.diag(k, msg, self.rule_id, self.default_severity, fix=suggestion))

        optional_node = _dict_str_value(filters_node, "optional")
        if isinstance(optional_node, ast.List):
            for elt in optional_node.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str) \
                        and not ctx.schema.has_field(doctype, elt.value):
                    suggestion = ctx.suggest_closest(elt.value, info.fields)
                    msg = f"config for {doctype}: unknown field '{elt.value}' (in filters.optional)"
                    if suggestion:
                        msg += f" (did you mean '{suggestion}'?)"
                    out.append(ctx.diag(elt, msg, self.rule_id, self.default_severity, fix=suggestion))
        return out


@rule(id="FRP-SCH006", severity="error", needs=["project"])
class HooksDottedPathMissing(FrappeRule):
    """hooks.py doc_events/scheduler_events point at 'module.sub.func' --
    verify that dotted path actually resolves to a real function."""

    def visit_Constant(self, node: ast.Constant, ctx: RuleContext):
        if os.path.basename(ctx.path) != "hooks.py":
            return None
        if not isinstance(node.value, str) or not _DOTTED_PATH_RE.match(node.value):
            return None
        if ctx.project is None:
            return None
        module_path, _, func_name = node.value.rpartition(".")
        if not module_path:
            return None
        rel = module_path.replace(".", "/") + ".py"
        candidates = [f for f in ctx.project.files if f.replace("\\", "/").endswith(rel)]
        if not candidates:
            return None  # module lives in a different installed app; out of scope for this repo's index
        try:
            src = open(candidates[0], encoding="utf-8").read()
            tree = ast.parse(src)
        except (OSError, SyntaxError):
            return None
        defined = {n.name for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if func_name not in defined:
            return ctx.diag(node, f"hooks.py points at '{node.value}' but no such function"
                                    f" exists in {candidates[0]}", self.rule_id, self.default_severity)
        return None
