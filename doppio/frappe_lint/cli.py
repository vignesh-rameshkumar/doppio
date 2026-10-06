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


def get_bench_apps_root() -> str | None:
    """Resolve <bench>/apps the reliable way: frappe importable means we're
    genuinely running inside a bench's own venv (always true via `bench
    lint`). Returns None otherwise -- e.g. the standalone CLI in a bare CI
    checkout with no frappe installed -- rather than guessing a relative
    path. That guess used to be `_HERE/../../..`, which happened to land on
    a real bench `apps/` directory in local testing purely because doppio
    sits exactly three levels under it here; in a real CI checkout (just
    the target app + doppio, no sibling apps) the same guess resolves to
    the workspace root, and silently walking it finds only those two
    repos' DocTypes -- an incomplete schema with no error, not a loud
    failure. Callers must treat None as "no reliable apps_root" and
    require --schema-cache instead; see _load_schema below."""
    try:
        import frappe.utils
        return os.path.join(frappe.utils.get_bench_path(), "apps")
    except Exception:
        return None


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


def _load_schema(apps_root: str | None, schema_cache: str | None) -> SchemaIndex:
    """Live-scan wins whenever a real bench is available -- ignoring the
    cache even if one exists. Measured in this session: walking ~1200
    DocTypes across a warm local filesystem takes well under a second
    (the "~9s" quoted earlier was a cold-cache outlier during
    development, not a stable property of the approach -- see the
    breakdown in frappe_lint/README.md). At that cost there's no reason
    to ever risk a stale cache locally -- add a DocType elsewhere in the
    bench and forget to regenerate the cache, and a cache-preferring
    linter would silently keep flagging it as unknown.

    The cache is reached only when apps_root isn't reliable at all: CI,
    or a solo app checkout, where the other apps' DocType JSON files
    simply aren't present on disk to scan, live or otherwise. That's the
    one thing caching actually buys -- portability, not speed."""
    if apps_root:
        return SchemaIndex.build(apps_root)

    if schema_cache and os.path.exists(schema_cache):
        return SchemaIndex.load_cache(schema_cache)

    if schema_cache:
        # Explicitly asked for a cache file that isn't there, AND no
        # reliable apps_root to fall back to -- almost certainly a
        # forgotten `bench lint-schema <app>` step, not an intentional
        # choice. Erroring here is the whole point: silently building an
        # incomplete schema from a wrong directory would look like
        # success and just be wrong.
        raise SystemExit(
            f"--schema-cache was given as '{schema_cache}' but that file doesn't exist, "
            f"and there's no reliable --apps-root to fall back to (this doesn't look like "
            f"it's running inside a real bench). Generate the cache with "
            f"'bench lint-schema <app>' where the full bench is present, and commit it."
        )
    raise SystemExit(
        "No reliable --apps-root (this doesn't look like it's running inside a real bench) "
        "and no --schema-cache given -- can't resolve the DocType schema at all. Generate a "
        "cache with 'bench lint-schema <app>' and pass it via --schema-cache."
    )


def run_check(paths: list[str], apps_root: str | None, config: LintConfig, rules_dir: str,
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
    new, baselined = split_baselined(diags, baseline_keys, baseline_path)
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


def require_apps_root(apps_root: str | None) -> str:
    """dump-schema fundamentally needs to walk a real bench -- there's no
    cache to fall back to here, this command IS what generates the cache.
    Fail with a clear message rather than crash inside SchemaIndex.build
    on a None path."""
    if not apps_root:
        raise SystemExit(
            "No reliable --apps-root (this doesn't look like it's running inside a real "
            "bench -- frappe isn't importable). dump-schema has to walk a real bench's "
            "apps/ directory; run this via 'bench lint-schema <app>' instead, or pass "
            "--apps-root explicitly if you know the right path."
        )
    return apps_root


def cmd_dump_schema(args):
    schema = SchemaIndex.build(require_apps_root(args.apps_root))
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
