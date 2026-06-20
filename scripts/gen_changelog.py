#!/usr/bin/env python3
"""Generate the changelog section for a release and prepend it to CHANGELOG.md.

Groups commit subjects since the last v* tag into Features / Fixes / Other
(Conventional-Commits-lite). Skips the bot's own release commits. Also writes the
section alone to .release_notes.md for use as the GitHub Release body.

Usage:
    python scripts/gen_changelog.py <new-version>
"""

from __future__ import annotations

import datetime
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"
NOTES = ROOT / ".release_notes.md"
HEADER = "# Changelog\n\nAll notable changes to this project are documented here.\n"


def _run(*args: str) -> str:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True).stdout.strip()


def _commits_since_last_tag() -> list[str]:
    last_tag = _run("git", "describe", "--tags", "--abbrev=0", "--match", "v*")
    rng = f"{last_tag}..HEAD" if last_tag else "HEAD"
    log = _run("git", "log", rng, "--format=%s", "--no-merges")
    return [line.strip() for line in log.splitlines() if line.strip()]


def _classify(subjects: list[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {"Features": [], "Fixes": [], "Other": []}
    for s in subjects:
        low = s.lower()
        if low.startswith("chore(release)"):
            continue
        if low.startswith("feat"):
            groups["Features"].append(_clean(s))
        elif low.startswith("fix"):
            groups["Fixes"].append(_clean(s))
        else:
            groups["Other"].append(_clean(s))
    return groups


def _clean(subject: str) -> str:
    # strip a leading "type(scope): " / "type: " prefix for readability
    for sep in (": ",):
        if sep in subject[:40]:
            head, rest = subject.split(sep, 1)
            if head.replace("!", "").replace("(", "").replace(")", "").isalnum() or "(" in head:
                return rest.strip()
    return subject.strip()


def _render_section(version: str, groups: dict[str, list[str]]) -> str:
    today = datetime.date.today().isoformat()
    lines = [f"## [{version}] - {today}", ""]
    any_entry = False
    for title in ("Features", "Fixes", "Other"):
        items = groups[title]
        if not items:
            continue
        any_entry = True
        lines.append(f"### {title}")
        lines.extend(f"- {it}" for it in items)
        lines.append("")
    if not any_entry:
        lines.append("_No notable changes._")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("usage: gen_changelog.py <version>")
    version = sys.argv[1]
    section = _render_section(version, _classify(_commits_since_last_tag()))

    NOTES.write_text(section, encoding="utf-8")

    existing = CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.exists() else HEADER
    body = existing[len(HEADER):] if existing.startswith(HEADER) else "\n" + existing
    CHANGELOG.write_text(HEADER + "\n" + section + body, encoding="utf-8")
    print(f"changelog updated for {version}")


if __name__ == "__main__":
    main()
