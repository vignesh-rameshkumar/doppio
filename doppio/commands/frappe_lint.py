"""
bench lint* commands (frappe-lint).

These are plain (siteless) bench commands -- frappe-lint is pure
filesystem/AST analysis, it never touches a site's database, so unlike
`bench backup-app` etc. there's no `--site` to pass.

    bench lint <app> [--path SUBPATH] [--format text|json] [--fail-on new_only|all]
    bench lint-baseline <app>
    bench lint-schema <app>
    bench lint-rules
    bench lint-selftest
"""
from __future__ import annotations

import os
import sys

import click


def _apps_root():
    from doppio.frappe_lint.cli import get_bench_apps_root
    return get_bench_apps_root()


@click.command("lint")
@click.argument("app")
@click.option("--path", "subpath", default=None,
              help="Lint only this subpath of the app instead of the whole package "
                   "(relative to the app's repo root, e.g. 'core/api').")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text")
@click.option("--fail-on", type=click.Choice(["new_only", "all"]), default="new_only",
              help="'new_only' (default) gates CI on violations not already in the baseline. "
                   "'all' gates on every error, including baselined debt.")
@click.option("--no-baseline", is_flag=True, help="Ignore the baseline file; show every finding as new.")
@click.option("--show-baselined", is_flag=True, help="Also print findings already in the baseline.")
def lint(app, subpath, fmt, fail_on, no_baseline, show_baselined):
    """Lint an installed app's Python code with frappe-lint."""
    from doppio.frappe_lint.baseline import load_baseline, split_baselined
    from doppio.frappe_lint.cli import resolve_app_paths, run_check, print_report, require_apps_root
    from doppio.frappe_lint.config import LintConfig

    apps_root = require_apps_root(_apps_root())
    locations = resolve_app_paths(app, apps_root)
    if not os.path.isdir(locations["scan_path"]):
        click.echo(f"'{app}' has no importable package at {locations['scan_path']}", err=True)
        sys.exit(2)

    scan_path = os.path.join(locations["app_root"], subpath) if subpath else locations["scan_path"]
    config = LintConfig.load(locations["config"])
    diags = run_check([scan_path], apps_root, config, _rules_dir(), locations["schema_cache"])

    baseline_keys = set() if no_baseline else load_baseline(locations["baseline"])
    new, baselined = split_baselined(diags, baseline_keys, locations["baseline"])
    print_report(diags, new, baselined, show_baselined, sys.stdout.isatty(), fmt)

    gate = diags if fail_on == "all" else new
    if any(d.severity == "error" for d in gate):
        sys.exit(1)


@click.command("lint-baseline")
@click.argument("app")
@click.option("--path", "subpath", default=None)
def lint_baseline(app, subpath):
    """Freeze this app's current findings so `bench lint` only gates on new ones."""
    from doppio.frappe_lint.baseline import save_baseline
    from doppio.frappe_lint.cli import resolve_app_paths, run_check, require_apps_root
    from doppio.frappe_lint.config import LintConfig

    apps_root = require_apps_root(_apps_root())
    locations = resolve_app_paths(app, apps_root)
    scan_path = os.path.join(locations["app_root"], subpath) if subpath else locations["scan_path"]
    config = LintConfig.load(locations["config"])
    diags = run_check([scan_path], apps_root, config, _rules_dir(), locations["schema_cache"])
    save_baseline(locations["baseline"], diags)
    click.echo(f"baseline written: {locations['baseline']}  ({len(diags)} findings frozen)")
    click.echo(f"commit it: git -C {locations['app_root']} add {os.path.basename(locations['baseline'])}")


@click.command("lint-schema")
@click.argument("app")
def lint_schema(app):
    """Snapshot the whole bench's DocType schema into <app>'s own repo, so
    CI (which checks out only that one app, not the full bench) can run
    the schema-aware rules without the sibling apps present."""
    from doppio.frappe_lint.cli import resolve_app_paths, require_apps_root
    from doppio.frappe_lint.schema import SchemaIndex

    apps_root = require_apps_root(_apps_root())
    locations = resolve_app_paths(app, apps_root)
    schema = SchemaIndex.build(apps_root)
    schema.to_json(locations["schema_cache"])
    click.echo(f"schema cache written: {locations['schema_cache']}  "
               f"({len(schema.doctypes)} doctypes from {apps_root})")
    click.echo("Regenerate this whenever a DocType is added/renamed anywhere in the bench, "
               "then commit it -- stale cache means stale schema rules.")
    click.echo(f"commit it: git -C {locations['app_root']} add {os.path.basename(locations['schema_cache'])}")


@click.command("lint-rules")
def lint_rules():
    """Show every active rule: Tier B (Python) and Tier A (YAML, hot-reloaded from rules.d/)."""
    import doppio.frappe_lint.rules  # noqa: F401  (import registers all Tier-B rules)
    from doppio.frappe_lint.engine import registered_rules
    from doppio.frappe_lint.yaml_engine import load_yaml_rules

    rules_dir = _rules_dir()
    click.echo("Tier B (Python):")
    for cls in registered_rules():
        doc = cls.__doc__.strip().splitlines()[0] if cls.__doc__ else ""
        click.echo(f"  {cls.rule_id:14} {cls.default_severity:6} {doc}")
    click.echo("\nTier A (YAML, rules.d/ -- drop a file here to add one, no restart needed):")
    for r in load_yaml_rules(rules_dir):
        click.echo(f"  {r.id:14} {r.severity:6} {r.message}  [{os.path.basename(r.source_file)}]")


@click.command("lint-selftest")
def lint_selftest():
    """Run the bad.py/good.py fixture pairs shipped with every rule -- the
    check that stops a rule shipping with an unverified false-positive rate
    -- plus the baseline-portability and VS Code packaging regression tests."""
    from doppio.frappe_lint.fixtures.run_fixture_tests import main as run_fixtures
    from doppio.frappe_lint.selftest_baseline import main as run_baseline_test
    from doppio.frappe_lint.selftest_vsix import main as run_vsix_test
    fixtures_rc = run_fixtures(_apps_root())
    baseline_rc = run_baseline_test()
    vsix_rc = run_vsix_test()
    sys.exit(1 if (fixtures_rc or baseline_rc or vsix_rc) else 0)


@click.command("lint-lsp")
def lint_lsp():
    """Start the frappe-lint language server on stdio, for live in-editor
    diagnostics. Point your editor's LSP client at `bench lint-lsp` (run
    from inside an activated bench, same requirement as every other
    lint* command) -- see frappe_lint/README.md for editor setup."""
    from doppio.frappe_lint.lsp.server import main as run_lsp
    run_lsp()


@click.command("lint-vscode-install")
def lint_vscode_install():
    """Package and install the frappe-lint VS Code extension into your
    actual VS Code (not a throwaway dev host). Runs automatically on
    'bench install-app doppio' if VS Code is present; run this by hand
    to (re)install -- e.g. VS Code wasn't installed yet, or after an
    extension update."""
    from doppio.frappe_lint.vscode_install import install
    ok = install(echo=click.echo)
    sys.exit(0 if ok else 1)


@click.command("lint-lsp-watch")
@click.argument("path")
def lint_lsp_watch(path):
    """Watch one file and print live diagnostics as it changes -- a way to
    see frappe-lint's live-editing behavior working without setting up an
    editor's LSP client first. Edit the file with any tool; this polls it
    and re-lints on change. Ctrl+C to stop."""
    from doppio.frappe_lint.lsp.watch_file import main as run_watch
    sys.argv = [sys.argv[0], path]
    sys.exit(run_watch())


def _rules_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "frappe_lint", "rules.d")


commands = [
    lint,
    lint_baseline,
    lint_schema,
    lint_rules,
    lint_selftest,
    lint_lsp,
    lint_lsp_watch,
    lint_vscode_install,
]
