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

Baseline entries are keyed by path *relative to the baseline file's own
directory* (`FRP-ERR001:core/sync_handler.py:30`), so a baseline committed
from one machine matches on a teammate's bench and in CI regardless of
where the checkout lives. (An earlier version keyed on the absolute scan
path, which silently matched nothing anywhere else -- `bench lint-selftest`
now includes a regression test that moves a baselined app to a different
path and checks nothing resurfaces.) Line numbers still drift if code above
a finding changes; re-run `bench lint-baseline <app>` after large edits.

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

## Live in-editor feedback (LSP)

**VS Code: zero setup.** `bench install-app doppio` installs the
frappe-lint extension into your actual VS Code automatically (via an
`after_install` hook), if `code` is on PATH. Reload any open VS Code
window (command palette -> "Developer: Reload Window") and any Python
file inside the bench gets live diagnostics -- no settings, no
per-project config. The extension auto-detects the bench root by walking
up from whatever's open looking for `sites/apps.txt`, then derives
`env/bin/python3` and `apps/doppio` from that.

If `doppio` was installed before VS Code was, or the extension needs
reinstalling after an update:

```bash
bench lint-vscode-install
```

`frappeLint.benchPythonPath` / `frappeLint.doppioPath` still exist as
settings, but only as an override for a non-standard bench layout the
auto-detection can't find -- never required.

**Other editors:** one server, standard LSP -- any editor with an LSP
client can attach.

- `bench lint-lsp` -- starts the language server on stdio, for pointing
  a generic LSP client at.
- `editors/nvim/frappe-lint.lua` -- Neovim's built-in `vim.lsp`, no
  plugin needed. Set `BENCH_PATH` and source it.

**What was actually verified, stated precisely:** the server was tested
end-to-end over the real LSP protocol -- a genuine JSON-RPC client
(`lsp/smoke_test.py`) spawns the real `bench lint-lsp` subprocess and
confirms the initialize handshake, `didOpen` producing the correct
diagnostic, a debounced `didChange` correctly clearing it once the bug
is fixed, invalid syntax mid-edit not crashing the server (last-known-
good diagnostics stay up rather than blanking), and baseline suppression
working in the live path:

```bash
python3 -m doppio.frappe_lint.lsp.smoke_test
```

The VS Code path specifically was also confirmed against a real,
already-running VS Code window (not just the Extension Development
Host): `bench lint-vscode-install` was run for real, `code
--list-extensions` confirmed `doppio.frappe-lint` installed, and a
screenshot from that actual window showed the correct diagnostic --
message, rule code, and `frappe-lint` as the source -- on a deliberately
broken file, with no manual settings.json anywhere. The Neovim config
was not GUI-tested (Neovim isn't installed in the environment that built
this) -- standard, correct wiring for the same proven server, but treat
it like any other unreviewed diff before trusting it blindly.

**Performance numbers that shaped the design** (measured against the
`core` reference app, and corrected once already -- see "Why cache the
schema at all?" below): building the DocType schema from a whole bench
takes ~0.9s on a warm filesystem -- still never done on a keystroke, but
cheap enough to always live-scan once per session whenever a real bench
is available, in preference to any `.frappe_lint_schema_cache.json` file
even if one exists. Rebuilding one app's `ProjectIndex` takes ~0.6s --
done on save, not on every keystroke. A full 19-rule pass against one
file, reusing cached schema/project state, takes ~4ms -- that's the only
thing that runs on the debounced (300ms) per-keystroke path.

### Why cache the schema at all, if live-scanning is fast?

Speed was never the real reason. `SchemaIndex.build(apps_root)` *is* the
live scan -- glob every `doctype/*.json` across the bench, parse each
one. Timed in this session: ~0.87s of that ~0.9s is the directory walk
itself (`glob`), ~0.05s is parsing 1,200+ small JSON files. An earlier
"~9s, so it has to be cached" framing was a cold-filesystem-cache
outlier, not a stable cost, and got corrected once that was checked
properly.

The cache file (`.frappe_lint_schema_cache.json`) exists for exactly one
reason: **CI, and a solo app checkout, don't have the other apps' source
on disk at all.** A GitHub Actions runner that checks out only `core`
has no `doctype/*.json` for the other 19 apps to glob -- no scan, live
or otherwise, can find files that aren't there. The cache is a portable
snapshot that ships with the one app's repo for exactly that situation.

Because of this, `bench lint`/`bench lint-lsp` **prefer a live scan over
the cache file whenever a real bench is available** (frappe importable),
even if a cache file exists -- freshness costs nothing at ~0.9s, so
there's no reason to risk a stale cache locally (add a DocType elsewhere
in the bench, forget to re-run `bench lint-schema`, and a
cache-preferring linter would silently keep flagging it as unknown). The
cache is only ever read when there's no reliable bench under the process
at all -- see `cli.py`'s `_load_schema` and `lsp/server.py`'s
`_get_schema`, which both implement this same priority.

## Adding a rule tomorrow

Mechanical (forbidden/required call shape)? Drop a YAML file in
`rules.d/`. Needs the schema, cross-file state, or dataflow? Add a
`@rule(...)`-decorated class in `rules/`. Either way, add a fixture pair
and run `bench lint-selftest` before shipping above `info`.
