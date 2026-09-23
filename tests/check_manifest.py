#!/usr/bin/python3
"""Manifest and repo checks that mirror `omarchy plugin validate`, for machines
(and CI runners) without Omarchy. Run: /usr/bin/python3 tests/check_manifest.py"""

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
KINDS = {"bar-widget": "barWidget", "panel": "panel", "overlay": "overlay",
         "menu": "menu", "service": "service", "bar": "bar"}
REQUIRED = ("schemaVersion", "id", "name", "version", "author", "description", "kinds", "entryPoints")

errors = []


def check(condition, message):
    if not condition:
        errors.append(message)


manifest = json.loads((ROOT / "manifest.json").read_text())
plugin_id = manifest.get("id", "")

for key in REQUIRED:
    check(key in manifest, f"manifest: missing {key}")
check(manifest.get("schemaVersion") == 1 and type(manifest.get("schemaVersion")) is int,
      "manifest: schemaVersion must be the number 1")
check(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", plugin_id) and ".." not in plugin_id,
      f"manifest: bad id {plugin_id!r}")
check(not plugin_id.startswith("omarchy."), "manifest: the omarchy. prefix is reserved")
check(len(str(manifest.get("version", ""))) <= 64, "manifest: version longer than 64 characters")
check(re.fullmatch(r"\d+\.\d+\.\d+", str(manifest.get("version", ""))), "manifest: version is not semver")
check(manifest.get("license") == "MIT", "manifest: license must stay MIT")

kinds = manifest.get("kinds") or []
check(isinstance(kinds, list) and kinds, "manifest: kinds must be a non-empty array")
entry_points = manifest.get("entryPoints") or {}
for kind in kinds:
    check(kind in KINDS, f"manifest: unknown kind {kind}")
    check(KINDS.get(kind) in entry_points, f"manifest: kind {kind} has no entry point")
for name, path in entry_points.items():
    check(isinstance(path, str) and not path.startswith("/") and ".." not in path and "\n" not in path,
          f"manifest: unsafe entry point {name}={path!r}")
    check((ROOT / str(path)).is_file(), f"manifest: entry point {name} missing: {path}")

bar_widget = manifest.get("barWidget", {})
check(bar_widget.get("defaultSection", "center") in ("left", "center", "right"),
      "manifest: defaultSection must be left, center or right")
schema_keys = {entry["key"] for entry in bar_widget.get("schema", [])}
check(schema_keys == set(bar_widget.get("defaults", {})),
      f"manifest: schema keys {sorted(schema_keys)} != defaults {sorted(bar_widget.get('defaults', {}))}")

# The validator rejects symlinks anywhere but .git.
for path in ROOT.rglob("*"):
    if ".git" in path.relative_to(ROOT).parts:
        continue
    check(not path.is_symlink(), f"symlink not allowed: {path.relative_to(ROOT)}")

# The id is repeated in QML and docs; they must not drift from the manifest.
for rel in ("Service.qml", "Panel.qml", "README.md", "tools/eq-probe.py", "AGENTS.md"):
    text = (ROOT / rel).read_text()
    check(plugin_id in text, f"{rel}: does not mention {plugin_id}")
    for other in set(re.findall(r"io\.github\.[\w-]+\.galaxy-buds[\w-]*", text)) - {plugin_id}:
        errors.append(f"{rel}: stale plugin id {other}")

for rel in ("LICENSE", "README.md", "CONTRIBUTORS.md"):
    check("Aislan Dener Souza Vicentini" in (ROOT / rel).read_text(), f"{rel}: upstream credit missing")

changelog = (ROOT / "CHANGELOG.md").read_text()
check(f"## [{manifest.get('version')}]" in changelog, "CHANGELOG.md: no entry for the manifest version")

for error in errors:
    print("FAIL", error)
print("ok   manifest and repo checks" if not errors else f"{len(errors)} problem(s)")
sys.exit(1 if errors else 0)
