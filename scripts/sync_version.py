#!/usr/bin/env python3
"""Single source of truth = pyproject.toml [project].version.

Reads that version and writes it into every distribution artifact so they never
have to be bumped by hand. Run in CI before build, or locally: `make version-sync`.

Usage:
    python scripts/sync_version.py          # sync artifacts to pyproject version
    python scripts/sync_version.py --check   # fail if any artifact is out of sync
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'(?m)^\s*version\s*=\s*"([^"]+)"', text)
    if not m:
        sys.exit("error: could not find version in pyproject.toml")
    return m.group(1)


# (relative path, dotted key path to the version field)
JSON_TARGETS = [
    ("server.json", ["version"]),
    ("server.json", ["packages", 0, "version"]),
    ("manifest.json", ["version"]),
    (".claude-plugin/plugin.json", ["version"]),
    (".claude-plugin/marketplace.json", ["plugins", 0, "version"]),
]


def _get(obj, path):
    for key in path:
        obj = obj[key]
    return obj


def _set(obj, path, value):
    for key in path[:-1]:
        obj = obj[key]
    obj[path[-1]] = value


def main() -> None:
    check = "--check" in sys.argv
    version = read_pyproject_version()
    drift = []

    # group keys per file so we write each file once
    by_file: dict[str, list[list]] = {}
    for rel, path in JSON_TARGETS:
        by_file.setdefault(rel, []).append(path)

    for rel, paths in by_file.items():
        fp = ROOT / rel
        data = json.loads(fp.read_text(encoding="utf-8"))
        changed = False
        for path in paths:
            current = _get(data, path)
            if current != version:
                drift.append(f"{rel}:{'.'.join(map(str, path))} = {current} != {version}")
                _set(data, path, version)
                changed = True
        if changed and not check:
            fp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            print(f"synced {rel} -> {version}")

    if check and drift:
        print("version drift detected:")
        for d in drift:
            print(f"  {d}")
        sys.exit(1)

    if not check:
        print(f"all artifacts at {version}")


if __name__ == "__main__":
    main()
