"""Run the gateway:

    python -m gateway --port 8000 --node A=http://127.0.0.1:8001 --node B=http://127.0.0.1:8002 \
        --spare D=http://127.0.0.1:8004
"""

import argparse

import uvicorn

from gateway.app import create_app


def parse_pairs(parser: argparse.ArgumentParser, items: list[str], flag: str) -> dict[str, str]:
    pairs = {}
    for item in items:
        name, sep, url = item.partition("=")
        if not sep:
            parser.error(f"{flag} must look like NAME=URL, got {item!r}")
        pairs[name] = url
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the hashring gateway")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 inside Docker")
    parser.add_argument("--node", action="append", default=[], metavar="NAME=URL", help="repeat for each node")
    parser.add_argument("--spare", action="append", default=[], metavar="NAME=URL",
                        help="running node the dashboard can add later")
    parser.add_argument("--health-interval", type=float, default=2.0, help="seconds between health checks")
    args = parser.parse_args()

    app = create_app(
        parse_pairs(parser, args.node, "--node"),
        health_interval=args.health_interval,
        spares=parse_pairs(parser, args.spare, "--spare"),
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
