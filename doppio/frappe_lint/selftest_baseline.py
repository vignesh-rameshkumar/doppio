"""
Regression test: a baseline frozen on one machine must still match on
another.

The bug this guards against: baseline keys used to embed the scan path
exactly as given -- absolute for `bench lint` -- so a baseline committed
from /home/alice/bench/apps/core matched nothing on /home/bob/other/apps/
core, or in a CI checkout scanning a relative path, and the whole backlog
reappeared as "new".

Builds a throwaway app, freezes a baseline, moves the entire tree to a
different location, and checks the same findings are still baselined --
scanning both by absolute path (the `bench lint` shape) and by relative
path from the app root (the CI shape).

Run via `bench lint-selftest`, or: python3 -m doppio.frappe_lint.selftest_baseline
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

from doppio.frappe_lint.baseline import load_baseline, save_baseline, split_baselined
from doppio.frappe_lint.cli import run_check
from doppio.frappe_lint.config import LintConfig

_RULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules.d")

_BUGGY = '''import frappe


@frappe.whitelist(allow_guest=True)
def leak():
    return 1
'''


def _scan(app_root: str, paths: list[str], schema_cache: str):
    return run_check(paths, None, LintConfig.load(None), _RULES_DIR, schema_cache)


def main() -> int:
    failures = []
    workdir = tempfile.mkdtemp(prefix="frappe_lint_baseline_")
    try:
        home_a = os.path.join(workdir, "machine_a", "apps", "myapp")
        pkg_a = os.path.join(home_a, "myapp")
        os.makedirs(pkg_a)
        with open(os.path.join(pkg_a, "mod.py"), "w") as fh:
            fh.write(_BUGGY)
        cache_a = os.path.join(home_a, ".frappe_lint_schema_cache.json")
        with open(cache_a, "w") as fh:
            json.dump({}, fh)

        baseline_a = os.path.join(home_a, ".frappe_lint_baseline.json")
        frozen = _scan(home_a, [pkg_a], cache_a)
        if not frozen:
            failures.append("setup: the throwaway buggy file produced no findings to baseline")
        save_baseline(baseline_a, frozen)

        keys = load_baseline(baseline_a)
        machine_specific = [k for k in keys if workdir in k or ":/" in k]
        if machine_specific:
            failures.append(f"baseline contains machine-specific paths: {machine_specific}")

        # "Another machine": the same app copied somewhere with a different absolute path.
        home_b = os.path.join(workdir, "machine_b", "totally", "different", "apps", "myapp")
        shutil.copytree(home_a, home_b)
        pkg_b = os.path.join(home_b, "myapp")
        baseline_b = os.path.join(home_b, ".frappe_lint_baseline.json")
        cache_b = os.path.join(home_b, ".frappe_lint_schema_cache.json")

        new, baselined = split_baselined(_scan(home_b, [pkg_b], cache_b), load_baseline(baseline_b), baseline_b)
        if new or len(baselined) != len(frozen):
            failures.append(f"absolute-path scan after moving the app: expected 0 new / "
                            f"{len(frozen)} baselined, got {len(new)} new / {len(baselined)} baselined")

        # CI shape: cwd is the app's repo root, the scan path is relative.
        previous_cwd = os.getcwd()
        os.chdir(home_b)
        try:
            diags = _scan(home_b, ["myapp"], ".frappe_lint_schema_cache.json")
            new, baselined = split_baselined(diags, load_baseline(".frappe_lint_baseline.json"),
                                              ".frappe_lint_baseline.json")
        finally:
            os.chdir(previous_cwd)
        if new or len(baselined) != len(frozen):
            failures.append(f"relative-path (CI-style) scan: expected 0 new / "
                            f"{len(frozen)} baselined, got {len(new)} new / {len(baselined)} baselined")

        # A genuinely new violation must still surface -- otherwise the checks
        # above would pass trivially by matching everything.
        with open(os.path.join(pkg_b, "mod.py"), "a") as fh:
            fh.write('\n\n@frappe.whitelist(allow_guest=True)\ndef another_leak():\n    return 2\n')
        new, _ = split_baselined(_scan(home_b, [pkg_b], cache_b), load_baseline(baseline_b), baseline_b)
        if not new:
            failures.append("a newly added violation was swallowed by the baseline")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if failures:
        print("baseline portability: FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print("[ok] baseline portability: keys are path-independent (moved tree + relative scan both match; "
          "a new violation still surfaces)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
