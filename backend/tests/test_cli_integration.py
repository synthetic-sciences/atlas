import asyncio
import json
import os
from pathlib import Path
import socket
import sys

import httpx


async def test_cli_creates_and_reads_a_graph_through_the_standalone_server(tmp_path):
    root = Path(__file__).resolve().parents[2]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = {
        **os.environ,
        "ATLAS_MODE": "local",
        "ATLAS_DATA_DIR": str(tmp_path / "store"),
        "ATLAS_API_KEY": "local",
        "ATLAS_LOCAL_TOKEN": "local",
        "ATLAS_BASE_URL": f"http://127.0.0.1:{port}/api/v1",
        "ATLAS_CLI_CONFIG_PATH": str(tmp_path / "config.json"),
    }
    env.pop("ATLAS_DATABASE_URL", None)
    log = (tmp_path / "server.log").open("wb")
    server = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "uvicorn", "atlas_graph.main:app", "--host", "127.0.0.1", "--port", str(port),
        cwd=tmp_path, env=env, stdout=log, stderr=log,
    )
    try:
        async with httpx.AsyncClient(timeout=1) as client:
            for attempt in range(100):
                try:
                    ready = await client.get(f"http://127.0.0.1:{port}/api/health/db")
                    if ready.status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                assert server.returncode is None, "The standalone server stopped during startup"
                await asyncio.sleep(0.05)
            else:
                raise AssertionError("The standalone server did not become ready")

        async def command(*arguments):
            process = await asyncio.create_subprocess_exec(
                "node", str(root / "cli/bin/atlas.mjs"), *arguments, "--format=json",
                cwd=tmp_path, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=20)
            assert process.returncode == 0, stderr.decode()
            return json.loads(stdout)

        created = await command("project:create", "--title", "CLI integration")
        assert created["project_id"]
        await command("note:add", "--project-id", created["project_id"], "--text", "A child research note")
        projects = await command("project:list")
        assert "CLI integration" in json.dumps(projects)
        assert projects["total"] == 1
        assert "A child research note" not in json.dumps(projects)
        viewed = await command("map:view", "--node-id", created["project_id"])
        assert created["project_id"] in json.dumps(viewed)
    finally:
        server.terminate()
        await asyncio.wait_for(server.wait(), timeout=10)
        log.close()

