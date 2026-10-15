"""Project volume primitives.

Every project (root node) gets a persistent directory tree on disk:

    <VOLUME_ROOT>/projects/<root_node_id>/
        research_context/       # deep-research reports, notes
        shared/                 # reusable datasets, snippets, models
        skills/                 # project-bound hydrated skill files
        agent_<id>_workdir/     # one per spawn; preserved forever
        research_log.jsonl      # append-only mirror of the DB log

Dev: ``VOLUME_ROOT`` defaults to ``BLOBS_DIR / "volumes"``.
Prod: set ``FS_VOLUME_ROOT`` env var to the mount point (e.g. a Fly Volume
at ``/data/volumes``).

Access rules enforced here (not just policy):

1. Every call takes an explicit ``project_id``. We never expose paths
   outside ``<VOLUME_ROOT>/projects/<project_id>/``.
2. All paths are normalized and rejected if they escape the project root
   (no ``..`` traversal, no absolute paths, no symlinks).
3. Writes are blocked from paths starting with ``agent_<id>_workdir/``
   when that agent is flagged "active" - passed in via ``agent_active``
   callback. For Phase 1 we don't have that signal yet; the check is in
   place as a hook.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from atlas_graph import config


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class VolumeError(Exception):
    """Base for all volume-related errors."""


class PathEscapeError(VolumeError):
    """A requested path escapes the project root."""


class AgentWorkdirWriteError(VolumeError):
    """Attempted write into a running sub-agent's workdir."""


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _volume_root() -> Path:
    """Base directory that holds every project's volume tree.

    Honors ``FS_VOLUME_ROOT`` if set, otherwise falls back to
    ``BLOBS_DIR / 'volumes'`` so dev Just Works without extra config.
    """
    env = os.environ.get("FS_VOLUME_ROOT")
    if env:
        return Path(env)
    return config.BLOBS_DIR / "volumes"


def resolve_project_root(project_id: str) -> Path:
    """Absolute on-disk path of ``<VOLUME_ROOT>/projects/<project_id>/``."""
    if not project_id or "/" in project_id or ".." in project_id:
        raise PathEscapeError(f"invalid project_id: {project_id!r}")
    return _volume_root() / "projects" / project_id


@dataclass(frozen=True)
class VolumePath:
    """Normalized, project-scoped relative path + its resolved absolute path."""
    project_id: str
    relative: str           # e.g. "research_context/plan.md" (never starts with /)
    absolute: Path          # /vol/.../projects/<pid>/research_context/plan.md

    @property
    def is_in_agent_workdir(self) -> bool:
        return self.relative.startswith("agent_") and "_workdir/" in self.relative


def normalize(project_id: str, relative: str) -> VolumePath:
    """Validate and resolve a project-relative path to an absolute one.

    Rejects absolute paths, ``..`` traversal, and symlink escapes.
    """
    if relative is None:
        raise PathEscapeError("path must be a string")
    s = str(relative).strip()
    # Accept leading slashes as a convenience - they just mean "from the
    # project root", not the host filesystem root.
    while s.startswith("/"):
        s = s[1:]
    # Block Windows-style drives and NULs.
    if ":" in s or "\x00" in s:
        raise PathEscapeError(f"invalid characters in path: {relative!r}")
    # Collapse redundant separators.
    parts = [p for p in s.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise PathEscapeError(f"path escapes project root: {relative!r}")
    normalized = "/".join(parts)

    root = resolve_project_root(project_id)
    full = (root / normalized).resolve()
    # Make sure resolution didn't escape even via symlinks that may have
    # been planted after normalization.
    try:
        full.relative_to(root.resolve())
    except ValueError:
        raise PathEscapeError(
            f"path escapes project root after resolve: {relative!r}"
        )

    return VolumePath(
        project_id=project_id, relative=normalized, absolute=full
    )


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


_SEED_DIRS = ("research_context", "shared", "skills")


def ensure_project_volume(project_id: str) -> Path:
    """Create the project volume tree if missing. Idempotent."""
    root = resolve_project_root(project_id)
    root.mkdir(parents=True, exist_ok=True)
    for d in _SEED_DIRS:
        (root / d).mkdir(exist_ok=True)
    # research_log.jsonl is touched lazily on first append.
    return root


# ---------------------------------------------------------------------------
# Primitives: read / write / list / search
# ---------------------------------------------------------------------------


# Cap writes at 1 MiB to keep brain write_file primitive; sub-agents can
# write larger outputs directly (they don't go through this path).
MAX_WRITE_BYTES = 1 * 1024 * 1024
# Cap the number of list entries returned in one call.
MAX_LIST_ENTRIES = 2000


AgentActiveCheck = Callable[[str, str], bool]  # (project_id, workdir_name) -> bool


def read_text(
    project_id: str,
    relative: str,
    *,
    max_bytes: int = 512 * 1024,
    encoding: str = "utf-8",
) -> str:
    """Read a text file under the project volume.

    Returns decoded text (never raises on encoding; errors are replaced).
    Raises ``FileNotFoundError`` if the path does not exist.
    """
    vp = normalize(project_id, relative)
    if not vp.absolute.exists():
        raise FileNotFoundError(vp.relative)
    if vp.absolute.is_dir():
        raise IsADirectoryError(vp.relative)
    size = vp.absolute.stat().st_size
    to_read = min(size, max_bytes)
    with vp.absolute.open("rb") as f:
        raw = f.read(to_read)
    return raw.decode(encoding, errors="replace")


def write_text(
    project_id: str,
    relative: str,
    content: str,
    *,
    append: bool = False,
    agent_active: AgentActiveCheck | None = None,
) -> dict:
    """Write (or append) text content to a file under the project volume.

    Auto-creates parent directories. Blocks writes into an active agent's
    workdir when ``agent_active`` returns True. Size is capped at
    ``MAX_WRITE_BYTES`` to keep the brain's write surface primitive.
    """
    vp = normalize(project_id, relative)
    if vp.is_in_agent_workdir and agent_active is not None:
        # Extract "agent_<uuid>_workdir" prefix
        workdir_name = vp.relative.split("/", 1)[0]
        if agent_active(project_id, workdir_name):
            raise AgentWorkdirWriteError(
                f"cannot write into active agent workdir: {workdir_name}"
            )

    data = content.encode("utf-8")
    if len(data) > MAX_WRITE_BYTES:
        raise VolumeError(
            f"write exceeds {MAX_WRITE_BYTES} bytes ({len(data)} given). "
            "Brain writes are primitive; have a sub-agent emit large files."
        )

    vp.absolute.parent.mkdir(parents=True, exist_ok=True)
    mode = "ab" if append else "wb"
    with vp.absolute.open(mode) as f:
        f.write(data)

    st = vp.absolute.stat()
    return {
        "path": vp.relative,
        "bytes": len(data),
        "total_size": st.st_size,
        "appended": append,
    }


def list_dir(
    project_id: str,
    relative: str = "",
    *,
    depth: int = 1,
    include_hidden: bool = False,
) -> list[dict]:
    """List entries under a directory (or the project root for empty path).

    ``depth`` controls how deep to recurse. ``depth=1`` = direct children
    only. Useful for sidebar trees.
    """
    vp = normalize(project_id, relative or "")
    if not vp.absolute.exists():
        return []
    if not vp.absolute.is_dir():
        return []

    entries: list[dict] = []
    count = 0

    def visit(p: Path, d: int) -> None:
        nonlocal count
        if count >= MAX_LIST_ENTRIES:
            return
        try:
            children = sorted(
                p.iterdir(), key=lambda c: (c.is_file(), c.name.lower())
            )
        except PermissionError:
            return
        for child in children:
            if count >= MAX_LIST_ENTRIES:
                break
            if not include_hidden and child.name.startswith("."):
                continue
            rel = child.relative_to(resolve_project_root(project_id)).as_posix()
            try:
                st = child.stat()
            except OSError:
                continue
            entries.append(
                {
                    "name": child.name,
                    "path": rel,
                    "type": "dir" if child.is_dir() else "file",
                    "size": None if child.is_dir() else st.st_size,
                    "mtime": int(st.st_mtime),
                }
            )
            count += 1
            if child.is_dir() and d > 1:
                visit(child, d - 1)

    visit(vp.absolute, max(1, depth))
    return entries


def glob(
    project_id: str,
    pattern: str,
    *,
    limit: int = 200,
) -> list[dict]:
    """Glob files under the project volume using a rglob pattern.

    Accepts patterns like ``*.py``, ``**/*.json``, ``research_context/*``.
    """
    root = resolve_project_root(project_id)
    if not root.exists():
        return []
    out: list[dict] = []
    pat = pattern.strip() or "*"
    for p in sorted(root.glob(pat)):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        try:
            st = p.stat()
        except OSError:
            continue
        out.append(
            {
                "path": rel,
                "size": st.st_size,
                "mtime": int(st.st_mtime),
            }
        )
        if len(out) >= limit:
            break
    return out


def grep(
    project_id: str,
    pattern: str,
    *,
    path_pattern: str = "**/*",
    max_matches: int = 50,
    max_per_file: int = 5,
    context_chars: int = 80,
) -> list[dict]:
    """Regex search across files under the project volume.

    Skips binary files, hidden dirs, and entries larger than 1 MiB.
    Returns ``[{path, line, text}]`` hits.
    """
    try:
        rx = re.compile(pattern)
    except re.error as e:
        raise VolumeError(f"bad regex: {e}")

    root = resolve_project_root(project_id)
    if not root.exists():
        return []

    matches: list[dict] = []
    for p in sorted(root.glob(path_pattern)):
        if not p.is_file():
            continue
        # Skip hidden dirs.
        if any(part.startswith(".") for part in p.relative_to(root).parts):
            continue
        try:
            if p.stat().st_size > 1024 * 1024:
                continue
        except OSError:
            continue
        try:
            with p.open("r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception:
            continue
        # Skip if we hit a lot of NULs (likely binary).
        if "\x00" in text[:4096]:
            continue
        rel = p.relative_to(root).as_posix()
        per_file = 0
        for i, line in enumerate(text.splitlines(), 1):
            if per_file >= max_per_file:
                break
            if rx.search(line):
                snippet = line if len(line) <= context_chars else line[:context_chars] + "…"
                matches.append({"path": rel, "line": i, "text": snippet})
                per_file += 1
                if len(matches) >= max_matches:
                    return matches
    return matches


# ---------------------------------------------------------------------------
# Research log (mirror on disk - DB is source of truth, file is human-readable)
# ---------------------------------------------------------------------------


def append_research_log_line(project_id: str, entry: dict) -> None:
    """Append one JSON line to the project's research_log.jsonl."""
    root = resolve_project_root(project_id)
    root.mkdir(parents=True, exist_ok=True)
    log_path = root / "research_log.jsonl"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Stats (for the UI)
# ---------------------------------------------------------------------------


def project_stats(project_id: str) -> dict:
    """Return lightweight stats for the Files tab header.

    {
      total_bytes, file_count, dir_count,
      top_level: [{name, type, size, mtime}]
    }
    """
    root = resolve_project_root(project_id)
    if not root.exists():
        return {"exists": False, "total_bytes": 0, "file_count": 0, "dir_count": 0, "top_level": []}

    total_bytes = 0
    file_count = 0
    dir_count = 0
    for p in root.rglob("*"):
        try:
            if p.is_file():
                total_bytes += p.stat().st_size
                file_count += 1
            elif p.is_dir():
                dir_count += 1
        except OSError:
            continue

    top_level = []
    for p in sorted(root.iterdir()):
        try:
            st = p.stat()
        except OSError:
            continue
        top_level.append(
            {
                "name": p.name,
                "type": "dir" if p.is_dir() else "file",
                "size": None if p.is_dir() else st.st_size,
                "mtime": int(st.st_mtime),
            }
        )

    return {
        "exists": True,
        "root": str(root),
        "total_bytes": total_bytes,
        "file_count": file_count,
        "dir_count": dir_count,
        "top_level": top_level,
        "stat_at": int(time.time()),
    }


__all__ = [
    "VolumePath",
    "VolumeError",
    "PathEscapeError",
    "AgentWorkdirWriteError",
    "normalize",
    "ensure_project_volume",
    "resolve_project_root",
    "read_text",
    "write_text",
    "list_dir",
    "glob",
    "grep",
    "append_research_log_line",
    "project_stats",
    "MAX_WRITE_BYTES",
]
