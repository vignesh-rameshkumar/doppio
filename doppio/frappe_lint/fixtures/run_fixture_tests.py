"""
Every shipped rule needs a bad case (proves it fires) and a good case
(proves it does NOT false-positive on the pattern most likely to be
confused with the bug). A rule with no good case is how false positives
ship.

Two fixture layouts, auto-detected per rule:

  Flat (most rules): fixtures/<RULE_ID>/bad.py, fixtures/<RULE_ID>/good.py
  Two single files, checked in isolation.

  Project (rules needing multiple files or a specific filename -- e.g.
  FRP-SCH006 only ever looks at a file literally named hooks.py, and
  FRP-OBS001's path_exclude only means something with a real path):
  fixtures/<RULE_ID>/bad/**.py, fixtures/<RULE_ID>/good/**.py
  Each side is its own self-contained mini-project (its own ProjectIndex),
  so cross-file rules (cache invalidation, hooks.py dotted-path
  resolution) don't leak state between the bad case and the good case.

Covers both rule tiers: Tier B (Python classes, via the shared schema +
per-side ProjectIndex) and Tier A (YAML rules in rules.d/, via
run_yaml_rules scoped to just the one rule under test).

Run: bench lint-selftest
 or: python3 -m doppio.frappe_lint.fixtures.run_fixture_tests
"""
from __future__ import annotations

import ast
import os
import sys

from doppio.frappe_lint.engine import ProjectIndex, RuleContext, registered_rules
from doppio.frappe_lint.schema import SchemaIndex
from doppio.frappe_lint.yaml_engine import load_yaml_rules, run_yaml_rules
import doppio.frappe_lint.rules  # noqa: F401  (import registers all Tier-B rules)

_HERE = os.path.dirname(os.path.abspath(__file__))
_RULES_DIR = os.path.join(os.path.dirname(_HERE), "rules.d")


def _walk_py(root: str) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in sorted(filenames):
            if fn.endswith(".py"):
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def _hits_for_side(rule_id: str, files: list[str], root: str, schema: SchemaIndex,
                    tier_b_cls: type | None, yaml_rule) -> list:
    project = ProjectIndex.build(root) if tier_b_cls is not None else None
    out = []
    for path in files:
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src)
        if tier_b_cls is not None:
            ctx = RuleContext(path=path, source=src, tree=tree, schema=schema, project_index=project)
            out.extend(d for d in tier_b_cls(ctx).run() if d.rule_id == rule_id)
        else:
            out.extend(d for d in run_yaml_rules([yaml_rule], path, tree) if d.rule_id == rule_id)
    return out


def main(apps_root: str) -> int:
    schema = SchemaIndex.build(apps_root)  # built once, reused for every rule/side
    tier_b_by_id = {c.rule_id: c for c in registered_rules()}
    yaml_by_id = {r.id: r for r in load_yaml_rules(_RULES_DIR)}

    failures = []
    for rule_id in sorted(os.listdir(_HERE)):
        if not rule_id.startswith("FRP-"):
            continue
        fixture_dir = os.path.join(_HERE, rule_id)
        if not os.path.isdir(fixture_dir):
            continue

        tier_b_cls = tier_b_by_id.get(rule_id)
        yaml_rule = yaml_by_id.get(rule_id)
        if tier_b_cls is None and yaml_rule is None:
            failures.append(f"{rule_id}: has a fixture directory but no such rule is registered "
                             f"(Tier B or YAML) -- stale fixture or renamed rule ID?")
            continue

        flat_bad, flat_good = os.path.join(fixture_dir, "bad.py"), os.path.join(fixture_dir, "good.py")
        proj_bad, proj_good = os.path.join(fixture_dir, "bad"), os.path.join(fixture_dir, "good")

        if os.path.exists(flat_bad) and os.path.exists(flat_good):
            bad_files, bad_root = [flat_bad], fixture_dir
            good_files, good_root = [flat_good], fixture_dir
        elif os.path.isdir(proj_bad) and os.path.isdir(proj_good):
            bad_files, bad_root = _walk_py(proj_bad), proj_bad
            good_files, good_root = _walk_py(proj_good), proj_good
        else:
            failures.append(f"{rule_id}: missing bad.py/good.py (or bad/ good/ subdirs)")
            continue

        bad_hits = _hits_for_side(rule_id, bad_files, bad_root, schema, tier_b_cls, yaml_rule)
        good_hits = _hits_for_side(rule_id, good_files, good_root, schema, tier_b_cls, yaml_rule)

        status = "ok"
        if not bad_hits:
            failures.append(f"{rule_id}: the bad case did not trigger the rule (expected >=1 hit)")
            status = "FAIL"
        if good_hits:
            failures.append(f"{rule_id}: the good case triggered the rule (false positive) at "
                             f"{[(d.file, d.line) for d in good_hits]}")
            status = "FAIL"
        print(f"[{status}] {rule_id}: bad -> {len(bad_hits)} hit(s), good -> {len(good_hits)} hit(s)")

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
