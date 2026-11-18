"""Run one cache node:  python -m node --name A --port 8001 [--allow-crash] [--max-keys 5000]"""

import argparse

import uvicorn

from node.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one cache node")
    parser.add_argument("--name", required=True, help="node name, e.g. A")
    parser.add_argument("--port", type=int, required=True, help="port, e.g. 8001")
    parser.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 inside Docker")
    parser.add_argument("--allow-crash", action="store_true", help="enable POST /admin/crash (demos only)")
    parser.add_argument("--max-keys", type=int, default=None, help="refuse new keys after this many")
    args = parser.parse_args()
    app = create_app(args.name, allow_crash=args.allow_crash, max_keys=args.max_keys)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
