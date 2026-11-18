"""Consistent hashing ring.

Servers ("nodes") and keys are placed on the same circle of numbers
0 .. 2**32 - 1. A key belongs to the first node found when walking
clockwise from the key's position. Lookup is a binary search: O(log N).
"""

import bisect
import hashlib

RING_SIZE = 2**32


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

    def __init__(self) -> None:
        # Node positions on the ring, always kept sorted (needed for bisect).
        self._positions: list[int] = []
        # position -> node name
        self._owners: dict[int, str] = {}

    def add_node(self, name: str) -> None:
        """Place a node on the ring."""
        pos = _hash(name)
        if pos in self._owners:
            raise ValueError(f"node {name!r} is already on the ring")
        bisect.insort(self._positions, pos)  # insert and keep the list sorted
        self._owners[pos] = name

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
