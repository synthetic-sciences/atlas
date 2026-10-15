"""Hosted entry point: graph storage belongs to Atlas, accounts to Dashboard."""

import os

from atlas_graph import config
from atlas_graph.integrations.dashboard import Dashboard
from atlas_graph.runtime import Host, configure


def create_app():
    if config.MODE != "hosted":
        raise RuntimeError("The hosted entry point requires ATLAS_MODE=hosted")
    if len(os.environ.get("ATLAS_SIGNING_SECRET", "").strip()) < 32:
        raise RuntimeError("Hosted Atlas requires its own signing secret")
    if os.environ.get("ATLAS_SUPABASE_SERVICE_ROLE_KEY", "").strip():
        raise RuntimeError("Hosted Atlas must use graph-owned blob storage")
    if os.environ.get("ATLAS_ADMIN_SERVICE_TOKEN", "").strip():
        from atlas_graph.routes.administration import credential

        credential()
    index_token = os.environ.get("ATLAS_INDEX_SERVICE_TOKEN", "")
    if config.INDEXING_ENABLED and (
        len(index_token.strip()) < 32
        or index_token == os.environ.get("ATLAS_ACCOUNT_SERVICE_TOKEN", "")
    ):
        raise RuntimeError("Hosted indexing requires a separate index service credential")
    accounts = Dashboard(
        os.environ.get("ATLAS_ACCOUNT_URL", ""),
        os.environ.get("ATLAS_ACCOUNT_SERVICE_TOKEN", ""),
        index_token=index_token,
    )
    configure(
        Host(
            authenticate=accounts.authenticate,
            optional_auth=accounts.optional_auth,
            collaboration=accounts.collaboration_allowed,
            collaboration_label=accounts.collaboration_label,
            repository=accounts.repository,
            query=accounts.query,
            upload_ticket=accounts.upload_ticket,
            index=accounts.index_node,
            shutdown=accounts.close,
        )
    )
    from atlas_graph.main import app

    return app
