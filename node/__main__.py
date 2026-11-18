"""Run one cache node:  python -m node --name A --port 8001"""

import argparse

import uvicorn

from node.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one cache node")
    parser.add_argument("--name", required=True, help="node name, e.g. A")
    parser.add_argument("--port", type=int, required=True, help="port, e.g. 8001")
    args = parser.parse_args()
    uvicorn.run(create_app(args.name), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
