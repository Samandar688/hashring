"""Stage 3 live demo: gateway + real nodes.

Run from the project root:  python scripts/demo_gateway.py
"""

import time
from collections import Counter

import httpx

from cluster import GATEWAY, node_url, start_gateway, start_node, stop, wait_until_up

NODES = {"A": 8001, "B": 8002, "C": 8003}
KEYS = [f"user{i}" for i in range(30)]


def keys_per_node() -> dict[str, int]:
    return {n["name"]: n["keys"] for n in httpx.get(f"{GATEWAY}/cluster", params={"refresh": "true"}, timeout=30).json()["nodes"] if n["alive"]}


def read_all() -> Counter:
    return Counter(httpx.get(f"{GATEWAY}/keys/{k}").status_code for k in KEYS)


def new_events(since: float) -> list[str]:
    return [f"{e['type']} {e['node']}" + (f" (moved {e['moved']})" if "moved" in e else "")
            for e in httpx.get(f"{GATEWAY}/events", params={"since": since}).json()]


def main() -> None:
    procs = {name: start_node(name, port) for name, port in NODES.items()}
    try:
        for port in NODES.values():
            wait_until_up(node_url(port))
        procs["gateway"] = start_gateway(NODES, health_interval=1.0)
        wait_until_up(GATEWAY, "/cluster")
        print("1) Cluster is up. Clients talk only to the gateway on :8000")

        for k in KEYS:
            httpx.put(f"{GATEWAY}/keys/{k}", json={"value": f"data of {k}"})
        print(f"\n2) Wrote {len(KEYS)} keys through the gateway: {keys_per_node()}")

        t = time.time()
        print("\n3) Killing node B and waiting for the health check ...")
        stop([procs.pop("B")])
        time.sleep(2.5)
        print(f"   Gateway noticed by itself: {new_events(t)}")
        print(f"   Reading all keys (200 = found, 404 = lost with B): {dict(read_all())}")
        for k in KEYS:
            httpx.put(f"{GATEWAY}/keys/{k}", json={"value": f"data of {k}"})
        print(f"   Wrote the keys again, B's keys went to live nodes: {keys_per_node()}")

        t = time.time()
        print("\n4) Starting a NEW node D and adding it to the cluster ...")
        procs["D"] = start_node("D", 8004)
        wait_until_up(node_url(8004))
        httpx.post(f"{GATEWAY}/nodes", json={"name": "D", "url": node_url(8004)}, timeout=30)
        print(f"   Events: {new_events(t)}")
        print(f"   Keys per node: {keys_per_node()}")
        print(f"   Reading all keys: {dict(read_all())}")

        t = time.time()
        print("\n5) Removing node A on purpose (graceful: hand keys over first) ...")
        r = httpx.delete(f"{GATEWAY}/nodes/A", timeout=30).json()
        print(f"   {r}")
        print(f"   Keys per node: {keys_per_node()}")
        print(f"   Reading all keys: {dict(read_all())}")
    finally:
        stop(procs.values())


if __name__ == "__main__":
    main()
