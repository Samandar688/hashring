"""Gateway logic: the only door clients use.

The gateway keeps a HashRing of the nodes that are alive right now and
sends every key to its owner node. It also:

* checks node health and takes dead nodes off the ring (and puts them back),
* moves keys when a node joins or leaves on purpose ("rebalance"),
* can generate fake traffic (simulator) so the dashboard has something to show.
"""

import asyncio
import random
import time
from collections import Counter, deque

import httpx

from hashring.ring import RING_SIZE, HashRing

# A dead node must be noticed fast: connecting gets 0.3 s (on Windows a refused
# localhost connection can hang ~2 s otherwise), reading an answer gets 2 s.
TIMEOUT = httpx.Timeout(2.0, connect=0.3)


class NoNodesAlive(Exception):
    """Every node is down, or none is registered."""


class Gateway:
    def __init__(self, nodes: dict[str, str], client: httpx.AsyncClient, vnodes: int = 100) -> None:
        self.urls: dict[str, str] = dict(nodes)  # every known node: name -> base url
        self.client = client
        self.ring = HashRing(vnodes=vnodes)  # only the nodes that are alive
        self.alive: set[str] = set()
        self.key_counts: dict[str, int] = {}  # from the last health check
        self.requests: Counter[str] = Counter()  # requests served per node
        self.stats: Counter[str] = Counter()  # simulator results
        self.events: deque[dict] = deque(maxlen=200)
        self.sim_running = False
        self.sim_rate = 20  # simulated requests per second
        # Only one membership change (health check, add, remove) at a time.
        self._lock = asyncio.Lock()

    # ---- events ---------------------------------------------------------

    def _event(self, kind: str, node: str, **extra) -> None:
        self.events.append({"time": time.time(), "type": kind, "node": node, **extra})

    # ---- membership -----------------------------------------------------

    async def _ping(self, name: str) -> int | None:
        """Number of keys on the node, or None if it does not answer."""
        try:
            r = await self.client.get(f"{self.urls[name]}/health", timeout=httpx.Timeout(1.0, connect=0.3))
            r.raise_for_status()
            return int(r.json()["keys"])
        except (httpx.HTTPError, KeyError, ValueError, TypeError):
            return None

    def _mark_down(self, name: str) -> None:
        if name in self.alive:
            self.alive.discard(name)
            self.ring.remove_node(name)
            self.key_counts.pop(name, None)
            self._event("node_down", name)

    async def _mark_up(self, name: str) -> None:
        if name in self.alive:
            return
        self.alive.add(name)
        self.ring.add_node(name)
        moved = await self._pull_keys_to(name)
        self._event("node_up", name, moved=moved)

    async def _check_health(self) -> None:
        for name in list(self.urls):
            keys = await self._ping(name)
            if keys is None:
                self._mark_down(name)
                continue
            if name not in self.alive:
                await self._mark_up(name)
                keys = await self._ping(name) or 0  # count changed after the pull
            self.key_counts[name] = keys

    async def check_health(self) -> None:
        async with self._lock:
            await self._check_health()

    async def add_node(self, name: str, url: str) -> None:
        """Register a new node. If it answers, it joins the ring right away."""
        async with self._lock:
            if name in self.urls:
                raise ValueError(f"node {name!r} is already registered")
            self.urls[name] = url
            await self._check_health()

    async def remove_node(self, name: str) -> int:
        """Remove a node on purpose. Its keys are handed to the next nodes first."""
        async with self._lock:
            if name not in self.urls:
                raise KeyError(f"node {name!r} is not registered")
            moved = 0
            if name in self.alive:
                self.alive.discard(name)
                self.ring.remove_node(name)
                self.key_counts.pop(name, None)
                moved = await self._push_keys_from(name)
            del self.urls[name]
            self._event("node_removed", name, moved=moved)
            return moved

    async def crash_node(self, name: str) -> None:
        """Ask a node to kill itself (demo only). The health check notices later."""
        if name not in self.urls:
            raise KeyError(f"node {name!r} is not registered")
        r = await self.client.post(f"{self.urls[name]}/admin/crash", timeout=TIMEOUT)
        if r.status_code == 404:
            raise PermissionError(f"node {name!r} was not started with --allow-crash")
        r.raise_for_status()

    # ---- moving keys ----------------------------------------------------

    async def _list_keys(self, name: str) -> list[str]:
        try:
            r = await self.client.get(f"{self.urls[name]}/keys", timeout=TIMEOUT)
            r.raise_for_status()
            return list(r.json()["keys"])
        except (httpx.HTTPError, KeyError, ValueError, TypeError):
            return []

    async def _move(self, key: str, src: str, dst: str) -> bool:
        """Copy one key from src to dst, then delete it from src."""
        try:
            r = await self.client.get(f"{self.urls[src]}/keys/{key}", timeout=TIMEOUT)
            if r.status_code != 200:
                return False
            value = r.json()["value"]
            put = await self.client.put(f"{self.urls[dst]}/keys/{key}", json={"value": value}, timeout=TIMEOUT)
            put.raise_for_status()
            await self.client.delete(f"{self.urls[src]}/keys/{key}", timeout=TIMEOUT)
            return True
        except (httpx.HTTPError, KeyError, ValueError):
            return False

    async def _pull_keys_to(self, new: str) -> int:
        """A node joined: take from the other nodes the keys it now owns."""
        moved = 0
        for other in sorted(self.alive - {new}):
            for key in await self._list_keys(other):
                if new not in self.alive:
                    return moved
                if self.ring.get_node(key) == new and await self._move(key, other, new):
                    moved += 1
        return moved

    async def _push_keys_from(self, leaving: str) -> int:
        """A node leaves on purpose: give each of its keys to the new owner."""
        moved = 0
        for key in await self._list_keys(leaving):
            if not self.alive:
                break
            if await self._move(key, leaving, self.ring.get_node(key)):
                moved += 1
        return moved

    # ---- client requests ------------------------------------------------

    async def request(self, method: str, key: str, **kwargs) -> tuple[str, httpx.Response]:
        """Send a key request to its owner node.

        If the owner does not answer, it is taken off the ring and we try
        again with the next owner. So writes keep working when a node dies.
        """
        for _ in range(len(self.urls) + 1):
            if not self.alive:
                break
            node = self.ring.get_node(key)
            try:
                r = await self.client.request(method, f"{self.urls[node]}/keys/{key}", timeout=TIMEOUT, **kwargs)
            except httpx.TransportError:
                self._mark_down(node)
                continue
            self.requests[node] += 1
            return node, r
        raise NoNodesAlive("no cache nodes are alive")

    # ---- simulator ------------------------------------------------------

    async def simulate_once(self) -> None:
        """One fake client request: half writes, half reads."""
        key = f"user{random.randrange(1000)}"
        try:
            if random.random() < 0.5:
                await self.request("PUT", key, json={"value": random.randrange(1_000_000)})
                self.stats["writes"] += 1
            else:
                _, r = await self.request("GET", key)
                self.stats["hits" if r.status_code == 200 else "misses"] += 1
        except NoNodesAlive:
            self.stats["errors"] += 1

    # ---- view for the dashboard -----------------------------------------

    def snapshot(self) -> dict:
        return {
            "ring_size": RING_SIZE,
            "nodes": [
                {
                    "name": name,
                    "url": url,
                    "alive": name in self.alive,
                    "keys": self.key_counts.get(name, 0),
                    "requests": self.requests[name],
                }
                for name, url in sorted(self.urls.items())
            ],
            "points": [{"pos": pos, "node": node} for pos, node in self.ring.points()],
            "stats": dict(self.stats),
            "simulator": {"running": self.sim_running, "rate": self.sim_rate},
        }
