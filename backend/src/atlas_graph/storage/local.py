"""Graph-owned blob files, accessed relative to directory descriptors."""

from contextlib import contextmanager
import errno
import os
from pathlib import PurePosixPath
import stat
from uuid import uuid4

from atlas_graph import config


def path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 4096
        or "\\" in value
        or "\x00" in value
        or value.startswith("/")
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError("Invalid artifact storage path")
    return str(PurePosixPath(value))


@contextmanager
def directory(value: str, *, create: bool = False, root=None):
    parts = path(value).split("/")
    root = config.BLOBS_DIR if root is None else root
    if create:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptors = []
    try:
        descriptors.append(os.open(root, flags))
        for part in parts[:-1]:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptors[-1])
                except FileExistsError:
                    pass
            descriptors.append(os.open(part, flags, dir_fd=descriptors[-1]))
        yield descriptors[-1], parts[-1]
    except OSError as error:
        if error.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise ValueError("Invalid artifact storage path") from None
        raise
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def upload(value: str, data: bytes, *, root=None) -> None:
    with directory(value, create=True, root=root) as (parent, name):
        temporary = f".atlas-upload-{uuid4().hex}"
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent,
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass


def download(value: str, *, root=None, limit: int | None = None) -> bytes:
    with directory(value, root=root) as (parent, name):
        descriptor = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
        )
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("Invalid artifact storage path")
            if limit is not None and os.fstat(stream.fileno()).st_size > limit:
                raise ValueError("File exceeds the read limit")
            return stream.read() if limit is None else stream.read(limit)


def delete(value: str, *, root=None) -> None:
    try:
        with directory(value, root=root) as (parent, name):
            os.unlink(name, dir_fd=parent)
    except FileNotFoundError:
        pass
