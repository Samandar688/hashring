"""Consistent hashing ring.

Servers ("nodes") and keys are placed on the same circle of numbers
0 .. 2**32 - 1. A key belongs to the first node found when walking
clockwise from the key's position. Lookup is a binary search: O(log N).

Each real node is placed on the ring many times ("virtual nodes"),
so the keys are shared between nodes almost equally.
"""

import bisect
import hashlib

RING_SIZE = 2**32
DEFAULT_VNODES = 100


def _hash(text: str) -> int:
    """Turn any text into a stable position on the ring (0 .. 2**32 - 1).

    We use md5 instead of Python's built-in hash(), because hash() gives
    different results in every new Python process. A ring must give the
    same answer on every machine and after every restart.
    """
    digest = hashlib.md5(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


class HashRing:
    """A circle of nodes. Ask it which node owns a given key."""

    def __init__(self, vnodes: int = DEFAULT_VNODES) -> None:
        if vnodes < 1:
            raise ValueError("vnodes must be at least 1")
        self.vnodes = vnodes
        # All virtual node positions on the ring, always kept sorted (for bisect).
        self._positions: list[int] = []
        # position -> real node name
        self._owners: dict[int, str] = {}
        # real node name -> its positions (needed to remove a node quickly)
        self._nodes: dict[str, list[int]] = {}

    @property
    def nodes(self) -> list[str]:
        """Names of the real nodes on the ring."""
        return list(self._nodes)

    def add_node(self, name: str) -> None:
        """Place a node on the ring `vnodes` times."""
        if name in self._nodes:
            raise ValueError(f"node {name!r} is already on the ring")
        placed = []
        for i in range(self.vnodes):
            pos = _hash(f"{name}#{i}")
            if pos in self._owners:
                continue  # extremely rare clash with another point: skip it
            bisect.insort(self._positions, pos)  # insert and keep the list sorted
            self._owners[pos] = name
            placed.append(pos)
        self._nodes[name] = placed

    def remove_node(self, name: str) -> None:
        """Take a node off the ring. Its keys go to the next nodes clockwise."""
        if name not in self._nodes:
            raise KeyError(f"node {name!r} is not on the ring")
        for pos in self._nodes.pop(name):
            i = bisect.bisect_left(self._positions, pos)  # find it fast
            del self._positions[i]
            del self._owners[pos]

    def get_node(self, key: str) -> str:
        """Return the node that owns this key."""
        if not self._positions:
            raise LookupError("ring is empty, add a node first")
        pos = _hash(key)
        # Binary search: index of the first node position >= key position.
        i = bisect.bisect_left(self._positions, pos)
        # Past the last node? Wrap around to the first one (it is a circle).
        if i == len(self._positions):
            i = 0
        return self._owners[self._positions[i]]
