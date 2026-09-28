# frappe-lint

AST-based, schema-aware static checks for Frappe apps. Ships as part of
`doppio`, exposed as `bench lint*` commands.

## Run it

```bash
bench lint <app>                # e.g. bench lint core
bench lint <app> --path api     # only that subpath of the app
bench lint-rules                # list every active rule
```

First run in a fresh app: freeze the existing findings so CI only ever
gates on *new* violations, and snapshot the DocType schema so CI (which
typically checks out only that one app, not the whole bench) can resolve
DocTypes without the sibling apps present.

```bash
bench lint-schema <app>     # writes .frappe_lint_schema_cache.json
bench lint-baseline <app>   # writes .frappe_lint_baseline.json
git add frappe_lint.toml .frappe_lint_baseline.json .frappe_lint_schema_cache.json
```

Regenerate the schema cache whenever a DocType changes anywhere in the
bench -- not just in the app being linted -- otherwise schema-aware rules
run against a stale picture.

## Rule tiers

- **Tier A (YAML, `rules.d/*.yaml`)** -- mechanical call-shape checks
  (forbidden call, required/forbidden kwarg). Drop a file in, it's picked
  up on the next run, no code change.
- **Tier B (Python, `rules/*.py`)** -- anything needing cross-file
  resolution, the DocType schema, or dataflow (e.g. the SQL-injection
  taint tracer in `security_rules.py`). A class decorated `@rule(...)`,
  auto-registered by import.

Every shipped rule has a `fixtures/<RULE_ID>/{bad.py,good.py}` pair (or a
`bad/`/`good/` project-style pair for rules needing a specific filename
or a real path). Run `bench lint-selftest` before raising any rule above
`info` -- a rule with no `good.py` is how false positives ship.

## Turning a rule off or down (no code change)

Edit the target app's `frappe_lint.toml`:

```toml
[rules]
FRP-SCH006 = "off"
FRP-CACHE006 = "info"
[rules.FRP-OBS001]
severity = "off"
paths = ["/scripts/", "/commands/"]
```

Or suppress one occurrence inline, with a mandatory reason:

```python
result = frappe.get_all("X")  # frappe-lint: ignore[FRP-SEC005] perms enforced by factory layer
```

## CI and pre-commit

Templates in `ci_templates/` -- copy into the target app's own repo,
replace `<APP_NAME>`, read the comments at the top of each (they state
what's assumed and why):

- `ci_templates/pre-commit-config.yaml` -- local git hook, runs inside an
  activated bench (`bench lint` needs one).
- `ci_templates/github-actions-frappe-lint.yml` -- runs on a plain
  `ubuntu-latest` runner with **no bench at all**. The engine itself
  never imports `frappe` -- pure AST analysis plus reading DocType JSON
  off disk -- so CI only needs Python, PyYAML, tomli, this app's repo,
  and a checkout of `doppio`. Verified by running it with `frappe`
  import actively blocked and confirming it still works correctly, and
  separately confirming it fails loudly (not silently-wrong) when
  `.frappe_lint_schema_cache.json` is missing and there's no bench to
  fall back to walking.

## Adding a rule tomorrow

Mechanical (forbidden/required call shape)? Drop a YAML file in
`rules.d/`. Needs the schema, cross-file state, or dataflow? Add a
`@rule(...)`-decorated class in `rules/`. Either way, add a fixture pair
and run `bench lint-selftest` before shipping above `info`.
