"""Run the gateway:

    python -m gateway --port 8000 --node A=http://127.0.0.1:8001 --node B=http://127.0.0.1:8002
"""

import argparse

import uvicorn

from gateway.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the hashring gateway")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--node", action="append", default=[], metavar="NAME=URL", help="repeat for each node")
    parser.add_argument("--health-interval", type=float, default=2.0, help="seconds between health checks")
    args = parser.parse_args()

    nodes = {}
    for item in args.node:
        name, sep, url = item.partition("=")
        if not sep:
            parser.error(f"--node must look like NAME=URL, got {item!r}")
        nodes[name] = url

    app = create_app(nodes, health_interval=args.health_interval)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
