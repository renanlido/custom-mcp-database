#!/usr/bin/env python3
"""Decide the next semantic version from commits since the last release tag.

Rules (Conventional-Commits-lite, with a safe default):
  - any commit with "BREAKING CHANGE" or a "type!:" subject -> major
  - any "feat" commit                                       -> minor
  - otherwise (fix/chore/docs/refactor/plain messages)      -> patch

So a plain push to main always produces at least a patch release. Writes the new
version back into pyproject.toml and prints it. In GitHub Actions it also appends
`version=` and `bumped=` to $GITHUB_OUTPUT.

Skip logic: if the only commit is the bot's own release commit (or it carries
[skip release]), nothing is bumped and `bumped=false` is emitted.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
VERSION_RE = re.compile(r'(?m)^(?P<prefix>\s*version\s*=\s*")(?P<ver>[^"]+)(?P<suffix>")')


def _run(*args: str) -> str:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True).stdout.strip()


def current_version() -> str:
    m = VERSION_RE.search(PYPROJECT.read_text(encoding="utf-8"))
    if not m:
        sys.exit("error: version not found in pyproject.toml")
    return m.group("ver")


def commits_since_last_tag() -> list[str]:
    last_tag = _run("git", "describe", "--tags", "--abbrev=0", "--match", "v*")
    rng = f"{last_tag}..HEAD" if last_tag else "HEAD"
    log = _run("git", "log", rng, "--format=%s%n%b%n---")
    return [c.strip() for c in log.split("---") if c.strip()]


def decide_bump(commits: list[str]) -> str | None:
    if not commits:
        return None
    text = "\n".join(commits)
    if "[skip release]" in text:
        return None
    # ignore a lone release commit
    meaningful = [c for c in commits if not c.lower().startswith("chore(release)")]
    if not meaningful:
        return None
    blob = "\n".join(meaningful)
    if re.search(r"BREAKING CHANGE", blob) or re.search(r"(?m)^\w+(\([^)]*\))?!:", blob):
        return "major"
    if re.search(r"(?m)^feat(\([^)]*\))?:", blob):
        return "minor"
    return "patch"


def next_version(version: str, bump: str) -> str:
    major, minor, patch = (int(x) for x in version.split("."))
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def write_version(new: str) -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    text = VERSION_RE.sub(lambda m: f'{m.group("prefix")}{new}{m.group("suffix")}', text, count=1)
    PYPROJECT.write_text(text, encoding="utf-8")


def emit_output(version: str, bumped: bool) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"version={version}\n")
            f.write(f"bumped={'true' if bumped else 'false'}\n")


def main() -> None:
    cur = current_version()
    bump = decide_bump(commits_since_last_tag())
    if bump is None:
        print(f"no release needed (version stays {cur})")
        emit_output(cur, bumped=False)
        return
    new = next_version(cur, bump)
    write_version(new)
    print(f"bump {bump}: {cur} -> {new}")
    emit_output(new, bumped=True)


if __name__ == "__main__":
    main()
