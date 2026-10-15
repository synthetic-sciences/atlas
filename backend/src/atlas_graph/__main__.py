"""Run the local graph service without a dashboard installation."""

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Atlas graph API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8002)
    arguments = parser.parse_args()
    uvicorn.run("atlas_graph.main:app", host=arguments.host, port=arguments.port)


if __name__ == "__main__":
    main()
