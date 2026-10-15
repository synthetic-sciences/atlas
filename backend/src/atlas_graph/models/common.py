from enum import Enum


class NodeKind(str, Enum):
    untyped = "untyped"
    empirical = "empirical"
    insight = "insight"
    # Research semantic layer: a falsifiable claim under investigation and
    # a recorded choice between alternatives. Structured fields live in the
    # node's ``semantic_data`` JSON, written by routes/semantics.py.
    hypothesis = "hypothesis"
    decision = "decision"


class NodeLifecycle(str, Enum):
    staged = "staged"
    committed = "committed"


class NodeOutcome(str, Enum):
    completed = "completed"
    failed = "failed"
    canceled = "canceled"
    # Flight Recorder: runs the recorder couldn't classify (process died
    # before producing a metric, ambiguous eval). Keeps the matrix honest
    # instead of forcing every run into completed/failed.
    inconclusive = "inconclusive"


class SharingMode(str, Enum):
    private = "private"
    public = "public"
    unlisted = "unlisted"


class Visibility(str, Enum):
    private = "private"
    shared = "shared"
    unlisted = "unlisted"
    public = "public"


class CollaboratorRole(str, Enum):
    viewer = "viewer"
    editor = "editor"
    admin = "admin"


class AccessLevel(str, Enum):
    USER = "USER"
    USER_WRITE = "USER_WRITE"
    USER_ADMIN = "USER_ADMIN"


class ArtifactType(str, Enum):
    text = "text"
    table = "table"
    json = "json"
    image = "image"
    banner = "banner"
    html = "html"
    plotly_html = "plotly_html"
    vega = "vega"
    checkpoint = "checkpoint"
    binary = "binary"
    diff_carousel = "diff_carousel"


class ExecutionStatus(str, Enum):
    running = "running"
    completed = "completed"
    failed = "failed"
    terminated = "terminated"


class Projection(str, Enum):
    core = "core"
    topology = "topology"
    full = "full"


class DeleteMode(str, Enum):
    cascade = "cascade"
    detach_shared = "detach_shared"


ROLE_TO_ACCESS = {
    CollaboratorRole.viewer: AccessLevel.USER,
    CollaboratorRole.editor: AccessLevel.USER_WRITE,
    CollaboratorRole.admin: AccessLevel.USER_ADMIN,
}

ACCESS_TO_ROLE = {v: k for k, v in ROLE_TO_ACCESS.items()}
