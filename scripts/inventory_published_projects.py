#!/usr/bin/env python3
"""Inventory locally published projects and their homepage/git URLs."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_ROOT = Path("/home/username/code_projects")
DEFAULT_OUT = Path("docs/published-projects.md")
GITHUB_URL_RE = re.compile(r"(?:git@github\.com:|https://github\.com/)([^/\s]+)/([^/\s]+?)(?:\.git)?$")


@dataclass(frozen=True, slots=True)
class ProjectInventoryRow:
    name: str
    path: Path
    git_url: str
    homepage: str
    branch: str
    status: str


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return result.stdout.strip()


def normalize_git_url(remote: str) -> str:
    match = GITHUB_URL_RE.match(remote)
    if not match:
        return remote
    owner, repo = match.groups()
    return f"https://github.com/{owner}/{repo}"


def github_owner(url: str) -> str | None:
    match = GITHUB_URL_RE.match(url)
    if not match:
        return None
    return match.group(1)


def read_pyproject_homepage(repo: Path) -> str | None:
    path = repo / "pyproject.toml"
    if not path.exists():
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        return None
    urls = data.get("project", {}).get("urls", {})
    if isinstance(urls, dict):
        for key in ("Homepage", "homepage", "Home", "Repository", "Source"):
            value = urls.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def read_package_homepage(repo: Path) -> str | None:
    path = repo / "package.json"
    if not path.exists():
        return None
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    homepage = data.get("homepage")
    if isinstance(homepage, str) and homepage:
        return homepage
    repository = data.get("repository")
    if isinstance(repository, str) and repository:
        return normalize_git_url(repository)
    if isinstance(repository, dict):
        url = repository.get("url")
        if isinstance(url, str) and url:
            return normalize_git_url(url)
    return None


def repo_status(repo: Path) -> tuple[str, str]:
    branch = run_git(repo, "branch", "--show-current") or "-"
    status = run_git(repo, "status", "--short", "--branch").splitlines()
    if not status:
        return (branch, "unknown")
    head = status[0].replace("## ", "")
    dirty = any(line and not line.startswith("## ") for line in status)
    details: list[str] = []
    if "ahead" in head:
        details.append("ahead")
    if "behind" in head:
        details.append("behind")
    if dirty:
        details.append("dirty")
    return (branch, ",".join(details) if details else "clean")


def find_git_repos(root: Path) -> list[Path]:
    repos: list[Path] = []
    for git_dir in root.rglob(".git"):
        if git_dir.is_dir():
            repos.append(git_dir.parent)
    return sorted(set(repos), key=lambda item: str(item))


def inventory(root: Path, owner: str | None) -> list[ProjectInventoryRow]:
    rows: list[ProjectInventoryRow] = []
    for repo in find_git_repos(root):
        remote = run_git(repo, "remote", "get-url", "origin")
        if not remote:
            continue
        git_url = normalize_git_url(remote)
        if owner and github_owner(git_url) != owner:
            continue
        homepage = read_pyproject_homepage(repo) or read_package_homepage(repo) or git_url
        branch, status = repo_status(repo)
        rows.append(
            ProjectInventoryRow(
                name=repo.name,
                path=repo,
                git_url=git_url,
                homepage=homepage,
                branch=branch,
                status=status,
            )
        )
    return rows


def markdown_table(rows: list[ProjectInventoryRow], root: Path, owner: str | None) -> str:
    lines = [
        "# Published Projects Inventory",
        "",
        "Generated from local git remotes and project metadata.",
        "",
        f"- Scan root: `{root}`",
        f"- GitHub owner filter: `{owner or 'none'}`",
        f"- Project count: `{len(rows)}`",
        "",
        "| Project | Homepage | Git URL | Local Path | Branch | Status |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        rel_path = row.path
        try:
            rel_path = row.path.relative_to(root)
        except ValueError:
            pass
        lines.append(
            f"| `{row.name}` | {row.homepage} | {row.git_url} | `{rel_path}` | `{row.branch}` | `{row.status}` |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--owner", default="Amarel-Taylor-Scott")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    rows = inventory(args.root, args.owner or None)
    rendered = markdown_table(rows, args.root, args.owner or None)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered, encoding="utf-8")
    print(json.dumps({"ok": True, "count": len(rows), "out": str(args.out)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
