"""Start nodes A, B, C and the gateway, then keep them running until Ctrl+C.

Run from the project root:  python scripts/run_cluster.py
Then open http://127.0.0.1:8000/docs to try the API in the browser.
"""

import time

from cluster import GATEWAY, node_url, start_gateway, start_node, stop, wait_until_up

NODES = {"A": 8001, "B": 8002, "C": 8003}


def main() -> None:
    procs = [start_node(name, port) for name, port in NODES.items()]
    try:
        for port in NODES.values():
            wait_until_up(node_url(port))
        procs.append(start_gateway(NODES))
        wait_until_up(GATEWAY, "/cluster")
        print("Cluster is running:")
        for name, port in NODES.items():
            print(f"  node {name}: {node_url(port)}")
        print(f"  gateway: {GATEWAY}   (API docs: {GATEWAY}/docs)")
        print("Press Ctrl+C to stop.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        stop(procs)
        print("Stopped.")


if __name__ == "__main__":
    main()
