#!/usr/bin/env python3
"""Compute Ansible collection SemVer from antsibull-changelog fragments.

Follows Ansible collection releasing rules:
  https://docs.ansible.com/projects/ansible/latest/community/collection_contributors/collection_releasing.html

  - patch: backward-compatible bug/security fixes only
  - minor: new backward-compatible features and deprecations
  - major: removals and breaking/incompatible changes

Fragment mapping (antsibull-changelog categories):
  breaking_changes, removed_features                         -> major
  major_changes, minor_changes, deprecated_features          -> minor
  add object.*, add plugin.* (new content fragments)         -> minor
  bugfixes, security_fixes, known_issues, trivial            -> patch

Also treats newly added modules/plugins/roles/playbooks since the last
release tag as a minor bump (new content is auto-detected by antsibull via
version_added and does not always have a fragment).

Usage:
  semver_bump.py [--bump auto|major|minor|patch] [--galaxy galaxy.yml]
                 [--fragments changelogs/fragments] [--update-galaxy]

  semver_bump.py --next-patch VERSION
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

MAJOR_SECTIONS = frozenset({"breaking_changes", "removed_features"})
MINOR_SECTIONS = frozenset(
    {"major_changes", "minor_changes", "deprecated_features"}
)
# Remaining: bugfixes, security_fixes, known_issues, trivial, release_summary -> patch

# SemVer core: no leading zeros (https://semver.org/)
VERSION_CORE_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)$"
)
TAG_VERSION_RE = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)$"
)
GALAXY_VERSION_RE = re.compile(
    r'^version:\s*["\']?(?P<version>0|[1-9]\d*\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))["\']?\s*$',
    re.MULTILINE,
)

SECTION_RE = re.compile(
    r"^(?P<section>breaking_changes|removed_features|major_changes|"
    r"minor_changes|deprecated_features|bugfixes|security_fixes|"
    r"known_issues|trivial|release_summary|"
    r"add object\.\w+|add plugin\.\w+)\s*:",
    re.MULTILINE,
)

# Paths where new collection content implies a minor bump (Ansible: new
# modules/plugins/roles are minor features).
NEW_CONTENT_PATHS = (
    "plugins/",
    "roles/",
    "playbooks/",
)


def parse_version(version: str) -> tuple[int, int, int]:
    match = VERSION_CORE_RE.fullmatch(version.strip())
    if not match:
        raise ValueError(f"Invalid SemVer version: {version!r}")
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
    )


def format_version(parts: tuple[int, int, int]) -> str:
    return f"{parts[0]}.{parts[1]}.{parts[2]}"


def bump_version(version: str, level: str) -> str:
    major, minor, patch = parse_version(version)
    if level == "major":
        return format_version((major + 1, 0, 0))
    if level == "minor":
        return format_version((major, minor + 1, 0))
    if level == "patch":
        return format_version((major, minor, patch + 1))
    raise ValueError(f"Unknown bump level: {level!r}")


def read_galaxy_version(galaxy_path: Path) -> str:
    text = galaxy_path.read_text(encoding="utf-8")
    match = GALAXY_VERSION_RE.search(text)
    if not match:
        raise ValueError(f"Could not find a valid SemVer version in {galaxy_path}")
    return match.group("version")


def latest_git_tag() -> tuple[str, str] | None:
    """Return (version_without_v, actual_tag_name) for the highest SemVer tag."""
    try:
        raw = subprocess.check_output(
            ["git", "tag", "--list"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    best: tuple[tuple[int, int, int], str, str] | None = None
    for line in raw.splitlines():
        tag = line.strip()
        match = TAG_VERSION_RE.fullmatch(tag)
        if not match:
            continue
        parts = (
            int(match.group("major")),
            int(match.group("minor")),
            int(match.group("patch")),
        )
        version = format_version(parts)
        if best is None or parts > best[0]:
            best = (parts, version, tag)
    if best is None:
        return None
    return best[1], best[2]


def bump_level_from_fragments(fragments_dir: Path) -> str:
    if not fragments_dir.is_dir():
        return "patch"

    level = "patch"
    for path in sorted(fragments_dir.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix and path.suffix not in {".yml", ".yaml"}:
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue

        for match in SECTION_RE.finditer(text):
            section = match.group("section")
            if section in MAJOR_SECTIONS:
                return "major"
            if section in MINOR_SECTIONS or section.startswith("add "):
                level = "minor"
    return level


def has_new_content_since_tag(tag_name: str) -> bool:
    """True if modules/plugins/roles/playbooks were added since tag_name."""
    try:
        raw = subprocess.check_output(
            [
                "git",
                "diff",
                "--name-only",
                "--diff-filter=A",
                f"{tag_name}..HEAD",
                "--",
                *NEW_CONTENT_PATHS,
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

    for line in raw.splitlines():
        path = line.strip()
        if not path:
            continue
        # Ignore non-content noise under plugins/ (e.g. __init__.py-only churn
        # still counts as added file — acceptable minor signal).
        if path.endswith((".py", ".yml", ".yaml", ".md")):
            return True
        # Roles often add directories/files without those suffixes in the first
        # path component; any added path under roles/ or playbooks/ counts.
        if path.startswith(("roles/", "playbooks/")):
            return True
    return False


def resolve_bump_level(
    bump: str,
    fragments_dir: Path,
    tag_name: str | None,
) -> str:
    if bump != "auto":
        return bump

    level = bump_level_from_fragments(fragments_dir)
    if level == "major":
        return level
    if tag_name and has_new_content_since_tag(tag_name):
        return "minor"
    return level


def resolve_release_version(
    bump: str,
    galaxy_path: Path,
    fragments_dir: Path,
) -> tuple[str, str, str | None]:
    """Return (release_version, bump_level, base_version)."""
    galaxy_version = read_galaxy_version(galaxy_path)
    latest = latest_git_tag()

    if latest is None:
        level = resolve_bump_level(bump, fragments_dir, None)
        # First release: keep galaxy.yml as-is.
        return galaxy_version, level, None

    last_version, tag_name = latest
    level = resolve_bump_level(bump, fragments_dir, tag_name)
    calculated = bump_version(last_version, level)
    # Honor a manual pre-bump in galaxy.yml when it is higher (e.g. planned major).
    if parse_version(galaxy_version) > parse_version(calculated):
        return galaxy_version, level, last_version
    return calculated, level, last_version


def write_github_output(**values: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def update_galaxy_version(galaxy_path: Path, new_version: str) -> bool:
    """Set galaxy.yml version to new_version. Return True if the file changed."""
    current = read_galaxy_version(galaxy_path)
    if current == new_version:
        return False

    text = galaxy_path.read_text(encoding="utf-8")
    updated, count = re.subn(
        rf'^(version:\s*)["\']?{re.escape(current)}["\']?\s*$',
        rf'\1"{new_version}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise ValueError(f"Failed to update version in {galaxy_path}")
    galaxy_path.write_text(updated, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bump",
        choices=("auto", "major", "minor", "patch"),
        default="auto",
        help="Bump level (default: auto from fragments / new content)",
    )
    parser.add_argument(
        "--galaxy",
        type=Path,
        default=Path("galaxy.yml"),
        help="Path to galaxy.yml",
    )
    parser.add_argument(
        "--fragments",
        type=Path,
        default=Path("changelogs/fragments"),
        help="Path to antsibull changelog fragments directory",
    )
    parser.add_argument(
        "--update-galaxy",
        action="store_true",
        help="Write the calculated version into galaxy.yml when it differs",
    )
    parser.add_argument(
        "--github-output",
        action="store_true",
        help="Also write TAG_VERSION, BUMP_LEVEL, galaxy_updated to $GITHUB_OUTPUT",
    )
    parser.add_argument(
        "--next-patch",
        metavar="VERSION",
        help="If set, print VERSION bumped by patch (post-release WIP)",
    )
    args = parser.parse_args()

    if args.next_patch:
        next_version = bump_version(args.next_patch, "patch")
        print(next_version)
        if args.github_output:
            write_github_output(NEXT_VERSION=next_version)
        return 0

    release_version, level, base = resolve_release_version(
        args.bump, args.galaxy, args.fragments
    )
    base_msg = base if base is not None else "none"
    print(
        f"semver: base={base_msg} level={level} release={release_version}",
        file=sys.stderr,
    )

    galaxy_updated = False
    if args.update_galaxy:
        galaxy_updated = update_galaxy_version(args.galaxy, release_version)
        if galaxy_updated:
            print(
                f"Updated {args.galaxy}: -> {release_version}",
                file=sys.stderr,
            )
        else:
            print(
                f"{args.galaxy} already at {release_version}",
                file=sys.stderr,
            )

    print(release_version)
    if args.github_output:
        write_github_output(
            TAG_VERSION=release_version,
            BUMP_LEVEL=level,
            galaxy_updated="true" if galaxy_updated else "false",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
