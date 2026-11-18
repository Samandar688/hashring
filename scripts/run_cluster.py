"""Start a whole cluster in one go and keep it running until Ctrl+C.

* nodes A, B, C start and join the gateway,
* nodes D and E start as spares: add them from the dashboard,
* a crashed node is restarted after a few seconds (empty, like a real restart).

Local:   python scripts/run_cluster.py            -> open http://127.0.0.1:8000
Docker:  python scripts/run_cluster.py --host 0.0.0.0 --port $PORT   (one-container deploy)
"""

import argparse
import os
import time

from cluster import node_url, start_gateway, start_node, stop, wait_until_up

ACTIVE = {"A": 8001, "B": 8002, "C": 8003}
SPARE = {"D": 8004, "E": 8005}
RESTART_AFTER = 4.0  # seconds
MAX_KEYS = 5000  # per node, keeps a public demo's memory bounded


def main() -> None:
    parser = argparse.ArgumentParser(description="Run nodes + gateway + dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="gateway bind address (0.0.0.0 in Docker)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)), help="gateway port")
    args = parser.parse_args()

    all_nodes = {**ACTIVE, **SPARE}

    def launch(name: str):
        return start_node(name, all_nodes[name], allow_crash=True, max_keys=MAX_KEYS)

    procs = {name: launch(name) for name in all_nodes}
    died_at: dict[str, float] = {}
    gateway = None
    try:
        for port in all_nodes.values():
            wait_until_up(node_url(port))
        gateway = start_gateway(ACTIVE, port=args.port, health_interval=1.0, host=args.host, spares=SPARE)
        wait_until_up(f"http://127.0.0.1:{args.port}", "/cluster")
        print(f"Dashboard: http://127.0.0.1:{args.port}   (API docs: /docs)")
        print("Active nodes:", ", ".join(f"{n}={node_url(p)}" for n, p in ACTIVE.items()))
        print("Spare nodes (add from the dashboard):", ", ".join(f"{n}={node_url(p)}" for n, p in SPARE.items()))
        print("Press Ctrl+C to stop.")

        while True:  # tiny supervisor: bring crashed nodes back
            time.sleep(0.5)
            if gateway.poll() is not None:
                raise RuntimeError("gateway stopped")
            for name, p in procs.items():
                if p.poll() is None:
                    continue
                died_at.setdefault(name, time.monotonic())
                if time.monotonic() - died_at[name] >= RESTART_AFTER:
                    print(f"node {name} died, restarting it (empty)")
                    procs[name] = launch(name)
                    del died_at[name]
    except KeyboardInterrupt:
        pass
    finally:
        stop([*procs.values(), *([gateway] if gateway else [])])
        print("Stopped.")


if __name__ == "__main__":
    main()
