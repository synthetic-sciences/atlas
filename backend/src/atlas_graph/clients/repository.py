"""Repository operations without exposing a hosted account's GitHub grant."""

from typing import Protocol

from atlas_graph.clients import github_client


class Repository(Protocol):
    async def is_connected(self, repo: str) -> bool: ...

    async def create_ref(self, repo: str, ref: str, sha: str) -> dict: ...

    async def get_ref(self, repo: str, ref: str) -> dict: ...

    async def get_commit(self, repo: str, sha: str) -> dict: ...


class DirectRepository:
    def __init__(self, token: str | None):
        self.token = token

    async def is_connected(self, repo: str) -> bool:
        return bool(self.token)

    async def create_ref(self, repo: str, ref: str, sha: str) -> dict:
        return await github_client.create_ref(repo, ref, sha, auth_token=self.token)

    async def get_ref(self, repo: str, ref: str) -> dict:
        return await github_client.get_ref(repo, ref, auth_token=self.token)

    async def get_commit(self, repo: str, sha: str) -> dict:
        return await github_client.get_commit(repo, sha, auth_token=self.token)
