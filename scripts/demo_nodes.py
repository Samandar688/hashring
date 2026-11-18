"""Stage 2 live demo: 3 real cache nodes + HashRing routing.

Starts nodes A, B, C as separate processes, writes keys to the node the
ring picks, then kills node B and shows that only B's keys are lost.

Run from the project root:  python scripts/demo_nodes.py
"""

import subprocess
import sys
import time
from collections import Counter

import httpx

from hashring.ring import HashRing

NODES = {"A": 8001, "B": 8002, "C": 8003}
KEYS = [f"user{i}" for i in range(30)]


def url(node: str) -> str:
    return f"http://127.0.0.1:{NODES[node]}"


def start_node(name: str, port: int) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-m", "node", "--name", name, "--port", str(port)])


def wait_until_up(name: str, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            httpx.get(f"{url(name)}/health", timeout=0.5)
            return
        except httpx.TransportError:
            time.sleep(0.2)
    raise RuntimeError(f"node {name} did not start")


def main() -> None:
    procs = {name: start_node(name, port) for name, port in NODES.items()}
    try:
        for name in NODES:
            wait_until_up(name)
        print("1) Nodes are up:", ", ".join(f"{n} -> :{p}" for n, p in NODES.items()))

        ring = HashRing()
        for name in NODES:
            ring.add_node(name)

        for key in KEYS:
            owner = ring.get_node(key)
            httpx.put(f"{url(owner)}/keys/{key}", json={"value": f"data of {key}"})
        print(f"\n2) Wrote {len(KEYS)} keys. Keys per node (asked each node itself):")
        for name in NODES:
            print(f"   {name}: {httpx.get(f'{url(name)}/health').json()['keys']} keys")

        b_keys = [k for k in KEYS if ring.get_node(k) == "B"]
        print(f"\n3) Killing node B (it holds {len(b_keys)} keys) ...")
        procs["B"].terminate()
        procs["B"].wait()

        status = Counter()
        for key in KEYS:
            owner = ring.get_node(key)  # ring still thinks B is alive
            try:
                r = httpx.get(f"{url(owner)}/keys/{key}", timeout=1.0)
                status["found" if r.status_code == 200 else "missing"] += 1
            except httpx.TransportError:
                status["node down"] += 1
        print(f"   Reading all keys: {dict(status)}")

        before = {k: ring.get_node(k) for k in KEYS}
        ring.remove_node("B")
        moved_to = Counter(ring.get_node(k) for k in b_keys)
        print(f"\n4) Removed B from the ring. B's keys now route to: {dict(moved_to)}")
        others_same = all(ring.get_node(k) == before[k] for k in KEYS if before[k] != "B")
        print(f"   Other keys kept their node: {others_same}")
        print("   (B's data is gone - stage 3 gateway will handle this)")
    finally:
        for p in procs.values():
            if p.poll() is None:
                p.terminate()
                p.wait()


if __name__ == "__main__":
    main()
