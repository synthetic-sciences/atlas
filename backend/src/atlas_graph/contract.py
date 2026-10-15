"""Export graph-owned HTTP paths for a gateway without graph imports."""

import json


def routes() -> list[dict]:
    from atlas_graph.main import GRAPH_ROUTERS

    result: dict[str, set[str]] = {}
    for module, prefix in GRAPH_ROUTERS:
        for route in module.router.routes:
            path = prefix + route.path
            if not route.include_in_schema or path.startswith("/api/internal/"):
                continue
            result.setdefault(path, set()).update(route.methods)
    return [{"path": path, "methods": sorted(methods)} for path, methods in result.items()]


if __name__ == "__main__":
    print(json.dumps(routes(), indent=2))
