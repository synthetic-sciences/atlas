"""Hosted entry point: graph storage belongs to Atlas, accounts to Dashboard."""

import os

from atlas_graph import config
from atlas_graph.integrations.dashboard import Dashboard
from atlas_graph.runtime import Host, configure


def create_app():
    if config.MODE != "hosted":
        raise RuntimeError("The hosted entry point requires ATLAS_MODE=hosted")
    if not os.environ.get("ATLAS_SIGNING_SECRET", "").strip():
        raise RuntimeError("Hosted Atlas requires its own signing secret")
    accounts = Dashboard(
        os.environ.get("ATLAS_ACCOUNT_URL", ""),
        os.environ.get("ATLAS_ACCOUNT_SERVICE_TOKEN", ""),
        index_token=os.environ.get("ATLAS_INDEX_SERVICE_TOKEN", ""),
    )
    configure(
        Host(
            authenticate=accounts.authenticate,
            optional_auth=accounts.optional_auth,
            collaboration=accounts.collaboration_allowed,
            collaboration_label=accounts.collaboration_label,
            repository=accounts.repository,
            index=accounts.index_node,
            shutdown=accounts.close,
        )
    )
    from atlas_graph.main import app

    return app
