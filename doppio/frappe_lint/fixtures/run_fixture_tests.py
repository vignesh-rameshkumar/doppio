"""
Every shipped rule needs a bad.py (proves it fires) and a good.py (proves
it does NOT false-positive on the pattern most likely to be confused with
the bug). A rule with no good.py is how false positives ship.

Run: bench lint-selftest
 or: python3 -m doppio.frappe_lint.fixtures.run_fixture_tests
"""
from __future__ import annotations

import ast
import os
import sys

from doppio.frappe_lint.engine import ProjectIndex, RuleContext, registered_rules
from doppio.frappe_lint.schema import SchemaIndex
import doppio.frappe_lint.rules  # noqa: F401

_HERE = os.path.dirname(os.path.abspath(__file__))


def run_rule_on_dir(rule_id: str, directory: str, apps_root: str) -> list:
    schema = SchemaIndex.build(apps_root)
    project = ProjectIndex.build(directory)
    cls = next(c for c in registered_rules() if c.rule_id == rule_id)
    out = []
    for fn in os.listdir(directory):
        if not fn.endswith(".py"):
            continue
        path = os.path.join(directory, fn)
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src)
        ctx = RuleContext(path=path, source=src, tree=tree, schema=schema, project_index=project)
        out.extend(cls(ctx).run())
    return out


def main(apps_root: str) -> int:
    failures = []
    for rule_id in sorted(os.listdir(_HERE)):
        if not rule_id.startswith("FRP-"):
            continue
        fixture_dir = os.path.join(_HERE, rule_id)
        if not os.path.isdir(fixture_dir):
            continue
        bad_path = os.path.join(fixture_dir, "bad.py")
        good_path = os.path.join(fixture_dir, "good.py")
        if not (os.path.exists(bad_path) and os.path.exists(good_path)):
            failures.append(f"{rule_id}: missing bad.py or good.py")
            continue

        diags = run_rule_on_dir(rule_id, fixture_dir, apps_root)
        bad_hits = [d for d in diags if d.file.endswith("bad.py") and d.rule_id == rule_id]
        good_hits = [d for d in diags if d.file.endswith("good.py") and d.rule_id == rule_id]

        status = "ok"
        if not bad_hits:
            failures.append(f"{rule_id}: bad.py did not trigger the rule (expected >=1 hit)")
            status = "FAIL"
        if good_hits:
            failures.append(f"{rule_id}: good.py triggered the rule (false positive) at "
                             f"{[d.line for d in good_hits]}")
            status = "FAIL"
        print(f"[{status}] {rule_id}: bad.py -> {len(bad_hits)} hit(s), good.py -> {len(good_hits)} hit(s)")

    print()
    if failures:
        print(f"{len(failures)} fixture failure(s):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("all fixtures passed")
    return 0


if __name__ == "__main__":
    from doppio.frappe_lint.cli import get_bench_apps_root
    sys.exit(main(get_bench_apps_root()))
