"""
Tier 2: rules that need the cross-app DocType schema index to resolve.
This is the family that a generic linter (ruff, semgrep-without-context)
cannot express, because "is this a real field on this DocType" isn't a
syntax question -- it needs every installed app's doctype JSON loaded.
"""
from __future__ import annotations

import ast
import os

from doppio.frappe_lint.engine import FrappeRule, RuleContext, rule

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


@rule(id="FRP-SCH006", severity="error", needs=["project"])
class HooksDottedPathMissing(FrappeRule):
    """hooks.py doc_events/scheduler_events point at 'module.sub.func' --
    verify that dotted path actually resolves to a real function."""

    def visit_Constant(self, node: ast.Constant, ctx: RuleContext):
        if os.path.basename(ctx.path) != "hooks.py":
            return None
        if not isinstance(node.value, str) or "." not in node.value or " " in node.value:
            return None
        if not node.value.startswith(("core.", "frappe.", "erpnext.")):
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
