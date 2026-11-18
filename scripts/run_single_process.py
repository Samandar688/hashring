"""The whole cluster in ONE Python process: for small hosts (Render free: 0.1 CPU, 512 MB).

Every node is still its own HTTP server on its own port with its own memory,
so the gateway talks to them exactly as in Docker Compose. But Python and
FastAPI are loaded once, not six times, so it starts fast and uses little RAM.

A crashed node stops only its own server; it comes back empty a few seconds later.

    python scripts/run_single_process.py --host 0.0.0.0 --port $PORT
"""

import argparse
import asyncio
import contextlib
import os

import uvicorn

from gateway.app import create_app as create_gateway
from node.app import create_app as create_node

ACTIVE = {"A": 8001, "B": 8002, "C": 8003}
SPARE = {"D": 8004, "E": 8005}
RESTART_AFTER = 4.0  # seconds
MAX_KEYS = 5000  # per node, keeps a public demo's memory bounded


def url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


class NodeServer(uvicorn.Server):
    """A node server that leaves Ctrl+C / SIGTERM to the gateway server.

    Otherwise a restarted node would take over the signal handlers, and
    stopping the container would stop only that one node.
    """

    @contextlib.contextmanager
    def capture_signals(self):  # uvicorn >= 0.29
        yield

    def install_signal_handlers(self) -> None:  # older uvicorn
        pass


async def wait_started(server: uvicorn.Server) -> None:
    while not server.started:
        await asyncio.sleep(0.05)


async def run_node(name: str, port: int, first_start: asyncio.Event) -> None:
    """Run one node forever: when it crashes, start a fresh (empty) one."""
    while True:
        crashed = asyncio.Event()
        app = create_node(name, allow_crash=True, max_keys=MAX_KEYS, on_crash=crashed.set)
        server = NodeServer(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        task = asyncio.create_task(server.serve())
        await wait_started(server)
        first_start.set()
        await crashed.wait()
        server.should_exit = True
        await task
        print(f"node {name} crashed, restarting it empty in {RESTART_AFTER:.0f} s", flush=True)
        await asyncio.sleep(RESTART_AFTER)


async def main(host: str, port: int) -> None:
    started = {}
    tasks = []
    for name, node_port in {**ACTIVE, **SPARE}.items():
        started[name] = asyncio.Event()
        tasks.append(asyncio.create_task(run_node(name, node_port, started[name])))
    await asyncio.gather(*(e.wait() for e in started.values()))
    print("nodes up:", ", ".join(f"{n}={url(p)}" for n, p in {**ACTIVE, **SPARE}.items()), flush=True)

    gateway = create_gateway(
        {n: url(p) for n, p in ACTIVE.items()},
        health_interval=1.0,
        spares={n: url(p) for n, p in SPARE.items()},
    )
    server = uvicorn.Server(uvicorn.Config(gateway, host=host, port=port, log_level="warning"))
    print(f"dashboard on http://{host}:{port}", flush=True)
    try:
        await server.serve()  # returns on Ctrl+C / SIGTERM
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run nodes + gateway + dashboard in one process")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    args = parser.parse_args()
    asyncio.run(main(args.host, args.port))
