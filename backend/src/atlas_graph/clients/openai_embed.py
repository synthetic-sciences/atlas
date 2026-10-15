"""Embedding interface with explicit host or user-owned provider selection."""

from atlas_graph.runtime import host


def __getattr__(name: str):
    if name.startswith("__"):
        raise AttributeError(name)
    provider = host().embeddings
    if provider is not None:
        return getattr(provider(), name)
    from atlas_graph.clients import _direct_embed

    return getattr(_direct_embed, name)

