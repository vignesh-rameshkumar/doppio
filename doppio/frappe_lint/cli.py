"""
The reusable engine-runner. `doppio/commands/frappe_lint.py` wraps these
functions in click commands so the real entry point for developers is
`bench lint <app>`, not this module directly -- but everything here also
works standalone (`python3 -m doppio.frappe_lint.cli check ...`) for
scripting or a CI job that doesn't want to boot a full bench.
"""
from __future__ import annotations

import argparse
import ast
import os
import sys

from doppio.frappe_lint.baseline import load_baseline, save_baseline, split_baselined
from doppio.frappe_lint.config import LintConfig
from doppio.frappe_lint.engine import Diagnostic, ProjectIndex, RuleContext, registered_rules
from doppio.frappe_lint.schema import SchemaIndex
from doppio.frappe_lint.suppressions import apply_suppressions
from doppio.frappe_lint.yaml_engine import load_yaml_rules, run_yaml_rules

import doppio.frappe_lint.rules  # noqa: F401  (import registers all Tier-B rules)

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_RULES_DIR = os.path.join(_HERE, "rules.d")

SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}
SEVERITY_COLOR = {"error": "\033[31m", "warn": "\033[33m", "info": "\033[36m"}
RESET = "\033[0m"


def get_bench_apps_root() -> str:
    """Resolve <bench>/apps the proper way when frappe is importable (i.e.
    when running inside a bench's own venv, which is how `bench
    frappe-lint-*` always invokes this). Falls back to a relative-path
    guess (../../ from this file) for standalone use outside a bench."""
    try:
        import frappe.utils
        return os.path.join(frappe.utils.get_bench_path(), "apps")
    except Exception:
        return os.path.abspath(os.path.join(_HERE, "..", "..", ".."))


def resolve_app_paths(app_name: str, apps_root: str) -> dict:
    """Every per-app lint artifact (config, baseline, schema cache) lives at
    the *target* app's own repo root, tracked in that app's own git history
    -- not inside doppio. doppio only ships the engine."""
    app_root = os.path.join(apps_root, app_name)
    return {
        "app_root": app_root,
        "scan_path": os.path.join(app_root, app_name),  # apps/<app>/<app> -- the python package
        "config": os.path.join(app_root, "frappe_lint.toml"),
        "baseline": os.path.join(app_root, ".frappe_lint_baseline.json"),
        "schema_cache": os.path.join(app_root, ".frappe_lint_schema_cache.json"),
    }


def _iter_py_files(paths: list[str]):
    for p in paths:
        if os.path.isfile(p) and p.endswith(".py"):
            yield p
        elif os.path.isdir(p):
            for dirpath, dirnames, filenames in os.walk(p):
                dirnames[:] = [d for d in dirnames if d not in
                               ("node_modules", "__pycache__", ".git", "frappe_lint")]
                for fn in filenames:
                    if fn.endswith(".py"):
                        yield os.path.join(dirpath, fn)


def _load_schema(apps_root: str, schema_cache: str | None) -> SchemaIndex:
    if schema_cache and os.path.exists(schema_cache):
        return SchemaIndex.load_cache(schema_cache)
    return SchemaIndex.build(apps_root)


def run_check(paths: list[str], apps_root: str, config: LintConfig, rules_dir: str,
              schema_cache: str | None = None) -> list[Diagnostic]:
    schema = _load_schema(apps_root, schema_cache)
    project = ProjectIndex.build(paths[0] if len(paths) == 1 else os.path.commonpath(paths))
    yaml_rules = load_yaml_rules(rules_dir)
    rule_classes = registered_rules()

    all_diags: list[Diagnostic] = []
    lines_by_file: dict[str, list[str]] = {}

    for path in _iter_py_files(paths):
        try:
            src = open(path, encoding="utf-8").read()
            tree = ast.parse(src)
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue
        lines_by_file[path] = src.splitlines()
        ctx = RuleContext(path=path, source=src, tree=tree, schema=schema, project_index=project)

        for cls in rule_classes:
            instance = cls(ctx)
            all_diags.extend(instance.run())

        all_diags.extend(run_yaml_rules(yaml_rules, path, tree))

    resolved = []
    for d in all_diags:
        sev = config.effective_severity(d.rule_id, d.severity, d.file)
        if sev is None:
            continue
        d.severity = sev
        resolved.append(d)

    resolved = apply_suppressions(resolved, lines_by_file)
    return sorted(resolved, key=lambda d: (SEVERITY_ORDER.get(d.severity, 9), d.file, d.line))


def print_report(diags: list[Diagnostic], new: list, baselined: list,
                  show_baselined: bool, use_color: bool, fmt: str = "text") -> None:
    if fmt == "json":
        import json
        payload = [
            {"rule": d.rule_id, "severity": d.severity, "file": d.file, "line": d.line,
             "message": d.message, "baselined": d in baselined}
            for d in (diags if show_baselined else new)
        ]
        print(json.dumps(payload, indent=2))
        return

    color_map = SEVERITY_COLOR if use_color else {}
    reset = RESET if use_color else ""
    to_print = diags if show_baselined else new
    for d in to_print:
        color = color_map.get(d.severity, "")
        tag = "[baselined]" if d in baselined else ""
        print(f"{color}{d.severity.upper():5}{reset} {d.file}:{d.line}  {d.rule_id}  {d.message} {tag}")

    counts: dict = {}
    for d in new:
        counts[d.severity] = counts.get(d.severity, 0) + 1
    print()
    print(f"{len(new)} new finding(s)  ({', '.join(f'{v} {k}' for k, v in counts.items()) or 'none'})"
          f"  |  {len(baselined)} baselined  |  {len(diags)} total")


# --- standalone argparse entry point (python3 -m doppio.frappe_lint.cli ...) ---

def cmd_check(args):
    config = LintConfig.load(args.config)
    diags = run_check(args.paths, args.apps_root, config, args.rules_dir, args.schema_cache)
    baseline_path = args.baseline or config.baseline_file
    baseline_keys = load_baseline(baseline_path) if not args.no_baseline else set()
    new, baselined = split_baselined(diags, baseline_keys)
    print_report(diags, new, baselined, args.show_baselined, sys.stdout.isatty(), args.format)
    gate = diags if args.fail_on == "all" else new
    return 1 if any(d.severity == "error" for d in gate) else 0


def cmd_baseline_update(args):
    config = LintConfig.load(args.config)
    diags = run_check(args.paths, args.apps_root, config, args.rules_dir, args.schema_cache)
    baseline_path = args.baseline or config.baseline_file
    save_baseline(baseline_path, diags)
    print(f"baseline written: {baseline_path}  ({len(diags)} findings frozen)")
    return 0


def cmd_dump_schema(args):
    schema = SchemaIndex.build(args.apps_root)
    schema.to_json(args.out)
    print(f"schema cache written: {args.out}  ({len(schema.doctypes)} doctypes from {args.apps_root})")
    return 0


def cmd_list_rules(args):
    yaml_rules = load_yaml_rules(args.rules_dir)
    print("Tier B (Python):")
    for cls in registered_rules():
        doc = cls.__doc__.strip().splitlines()[0] if cls.__doc__ else ""
        print(f"  {cls.rule_id:14} {cls.default_severity:6} {doc}")
    print("\nTier A (YAML, rules.d/):")
    for r in yaml_rules:
        print(f"  {r.id:14} {r.severity:6} {r.message}  [{os.path.basename(r.source_file)}]")
    return 0


def main():
    p = argparse.ArgumentParser(prog="frappe-lint")
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("paths", nargs="+")
    common.add_argument("--apps-root", default=get_bench_apps_root())
    common.add_argument("--rules-dir", default=_DEFAULT_RULES_DIR)
    common.add_argument("--config", default="frappe_lint.toml")
    common.add_argument("--baseline", default=None)
    common.add_argument("--schema-cache", default=None)

    check_p = sub.add_parser("check", parents=[common])
    check_p.add_argument("--no-baseline", action="store_true")
    check_p.add_argument("--show-baselined", action="store_true")
    check_p.add_argument("--fail-on", choices=["new_only", "all"], default="new_only")
    check_p.add_argument("--format", choices=["text", "json"], default="text")
    check_p.set_defaults(func=cmd_check)

    base_p = sub.add_parser("baseline-update", parents=[common])
    base_p.set_defaults(func=cmd_baseline_update)

    list_p = sub.add_parser("list-rules")
    list_p.add_argument("--rules-dir", default=_DEFAULT_RULES_DIR)
    list_p.set_defaults(func=cmd_list_rules)

    dump_p = sub.add_parser("dump-schema")
    dump_p.add_argument("--apps-root", default=get_bench_apps_root())
    dump_p.add_argument("--out", default=".frappe_lint_schema_cache.json")
    dump_p.set_defaults(func=cmd_dump_schema)

    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
