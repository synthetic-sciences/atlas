"""Project shared filesystem.

Provides a per-project persistent volume mounted on the backend (and - in
future phases - also into sub-agent Modal containers). The brain agent has
read + primitive-write access; sub-agents own code execution inside their
workdir.

See ``docs/agent-harness.md`` for the full architecture.
"""

from atlas_graph.fs.volume import (
    MAX_WRITE_BYTES,
    VolumePath,
    VolumeError,
    append_research_log_line,
    ensure_project_volume,
    glob,
    grep,
    list_dir,
    project_stats,
    read_text,
    resolve_project_root,
    write_text,
)

__all__ = [
    "MAX_WRITE_BYTES",
    "VolumePath",
    "VolumeError",
    "append_research_log_line",
    "ensure_project_volume",
    "glob",
    "grep",
    "list_dir",
    "project_stats",
    "read_text",
    "resolve_project_root",
    "write_text",
]
