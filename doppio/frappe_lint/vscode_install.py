"""
Packages the VS Code client shim into a .vsix and installs it into the
user's actual VS Code (not a throwaway Extension Development Host) via
`code --install-extension`. Wired into doppio's after_install hook so
`bench install-app doppio` sets this up with no separate step -- and also
exposed as `bench lint-vscode-install` to run by hand (e.g. VS Code
wasn't installed yet when doppio was, or to reinstall after an update).

Safe to call in any context, including a non-interactive CI/server site
install with no VS Code and no desktop at all: every step is defensive,
missing prerequisites are logged and skipped, never raised -- this must
never be able to break `bench install-app doppio` itself.
"""
from __future__ import annotations

import os
import shutil
import subprocess

_EXT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "editors", "vscode")


def install(echo=print) -> bool:
    """Returns True if the extension was (re)installed, False if skipped
    or failed -- never raises."""
    code_bin = shutil.which("code")
    if not code_bin:
        echo("frappe-lint: no 'code' CLI found on PATH -- skipping VS Code extension install "
             "(expected on a server/CI install with no desktop; run 'bench lint-vscode-install' "
             "by hand later if VS Code is installed on this machine).")
        return False

    npm_bin = shutil.which("npm")
    if not npm_bin:
        echo("frappe-lint: no 'npm' found on PATH -- can't build the VS Code extension "
             "(needs Node.js to package it). Skipping.")
        return False

    try:
        node_modules = os.path.join(_EXT_DIR, "node_modules")
        if not os.path.isdir(node_modules):
            echo("frappe-lint: installing the VS Code extension's own dependencies...")
            subprocess.run([npm_bin, "install", "--no-audit", "--no-fund"],
                            cwd=_EXT_DIR, check=True, capture_output=True, text=True)

        vsix_path = os.path.join(_EXT_DIR, "frappe-lint.vsix")
        echo("frappe-lint: packaging the VS Code extension...")
        subprocess.run(["npx", "--yes", "@vscode/vsce", "package", "-o", vsix_path],
                        cwd=_EXT_DIR, check=True, capture_output=True, text=True)

        echo("frappe-lint: installing into VS Code...")
        subprocess.run([code_bin, "--install-extension", vsix_path, "--force"],
                        check=True, capture_output=True, text=True)

        echo("frappe-lint: VS Code extension installed. Reload any open VS Code window "
             "(command palette -> 'Developer: Reload Window') to activate it -- diagnostics "
             "then appear automatically on any Python file inside this bench, no settings needed.")
        return True
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "")[-2000:]
        echo(f"frappe-lint: VS Code extension install failed ({e}). stderr: {stderr}\n"
             f"Not fatal -- run 'bench lint-vscode-install' to retry.")
        return False
    except Exception as e:
        echo(f"frappe-lint: VS Code extension install failed unexpectedly: {e!r}. Not fatal.")
        return False
