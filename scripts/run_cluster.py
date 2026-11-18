"""Start a local cluster for the dashboard and keep it running until Ctrl+C.

* nodes A, B, C start and join the gateway,
* nodes D and E start as spares: add them from the dashboard,
* a crashed node is restarted after a few seconds (empty, like a real restart).

Run from the project root:  python scripts/run_cluster.py
Then open http://127.0.0.1:8000
"""

import time

from cluster import GATEWAY, node_url, start_gateway, start_node, stop, wait_until_up

ACTIVE = {"A": 8001, "B": 8002, "C": 8003}
SPARE = {"D": 8004, "E": 8005}
RESTART_AFTER = 4.0  # seconds


def main() -> None:
    all_nodes = {**ACTIVE, **SPARE}
    procs = {name: start_node(name, port, allow_crash=True) for name, port in all_nodes.items()}
    died_at: dict[str, float] = {}
    gateway = None
    try:
        for port in all_nodes.values():
            wait_until_up(node_url(port))
        gateway = start_gateway(ACTIVE, health_interval=1.0)
        wait_until_up(GATEWAY, "/cluster")
        print(f"Dashboard: {GATEWAY}   (API docs: {GATEWAY}/docs)")
        print("Active nodes:", ", ".join(f"{n}={node_url(p)}" for n, p in ACTIVE.items()))
        print("Spare nodes (add from the dashboard):", ", ".join(f"{n}={node_url(p)}" for n, p in SPARE.items()))
        print("Press Ctrl+C to stop.")

        while True:  # tiny supervisor: bring crashed nodes back
            time.sleep(0.5)
            for name, p in procs.items():
                if p.poll() is None:
                    continue
                died_at.setdefault(name, time.monotonic())
                if time.monotonic() - died_at[name] >= RESTART_AFTER:
                    print(f"node {name} died, restarting it (empty)")
                    procs[name] = start_node(name, all_nodes[name], allow_crash=True)
                    del died_at[name]
    except KeyboardInterrupt:
        pass
    finally:
        stop([*procs.values(), *([gateway] if gateway else [])])
        print("Stopped.")


if __name__ == "__main__":
    main()
