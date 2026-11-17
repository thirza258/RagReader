"""What an experiment ran on (PRD §42): the git commit and package versions.

The commit comes from the `GIT_COMMIT` environment variable (set it in
deployments built from an archive), else from the nearest `.git` above the
backend's BASE_DIR — read directly (HEAD → loose ref or packed-refs), never
by running `git` — else it is unknown (null).
"""
import os
import platform
import re
from importlib import metadata
from pathlib import Path

from django.conf import settings

PACKAGES = ("django", "djangorestframework", "celery", "numpy", "rank-bm25", "ragas", "openai")
COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
MAX_PARENTS = 8


def _commit(value):
    value = (value or "").strip().lower()
    return value if COMMIT.fullmatch(value) else None


def _git_directory(directory):
    """The git directory for a repository rooted at `directory`, or None."""
    marker = directory / ".git"
    if marker.is_dir():
        return marker
    if marker.is_file():  # worktrees and submodules: "gitdir: <path>"
        try:
            text = marker.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if text.startswith("gitdir:"):
            target = Path(text[len("gitdir:"):].strip())
            target = target if target.is_absolute() else (directory / target)
            return target if target.is_dir() else None
    return None


def _read_ref(git_dir, ref):
    common = git_dir
    commondir = git_dir / "commondir"
    if commondir.is_file():
        try:
            common = (git_dir / commondir.read_text(encoding="utf-8").strip()).resolve()
        except OSError:
            common = git_dir
    for base in dict.fromkeys((git_dir, common)):
        loose = base / ref
        if loose.is_file():
            try:
                return _commit(loose.read_text(encoding="utf-8"))
            except OSError:
                return None
        packed = base / "packed-refs"
        if packed.is_file():
            try:
                lines = packed.read_text(encoding="utf-8").splitlines()
            except OSError:
                return None
            for line in lines:
                parts = line.strip().split(" ", 1)
                if len(parts) == 2 and parts[1] == ref:
                    return _commit(parts[0])
    return None


def read_commit(start):
    """The checked-out commit of the repository containing `start`, or None."""
    directory = Path(start).resolve()
    for _ in range(MAX_PARENTS):
        git_dir = _git_directory(directory)
        if git_dir is not None:
            try:
                head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
            except OSError:
                return None
            if head.startswith("ref:"):
                return _read_ref(git_dir, head[len("ref:"):].strip())
            return _commit(head)
        if directory.parent == directory:
            break
        directory = directory.parent
    return None


def git_commit():
    from_env = os.environ.get("GIT_COMMIT", "").strip()
    if from_env:
        return from_env[:64]
    try:
        return read_commit(settings.BASE_DIR)
    except Exception:  # never fail an experiment over provenance
        return None


def package_versions():
    versions = {}
    for name in PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def environment(models):
    """`{"python", "packages", "models"}`: the software an experiment ran with."""
    return {
        "python": platform.python_version(),
        "packages": package_versions(),
        "models": models,
    }
