import pytest

from hashring.ring import RING_SIZE, HashRing, _hash


def make_ring(*names: str) -> HashRing:
    ring = HashRing()
    for name in names:
        ring.add_node(name)
    return ring


def linear_owner(ring: HashRing, key: str) -> str:
    """Slow but obviously correct answer: walk the sorted list one by one."""
    pos = _hash(key)
    for p in ring._positions:
        if p >= pos:
            return ring._owners[p]
    return ring._owners[ring._positions[0]]


def test_hash_is_stable_and_in_range():
    assert _hash("ali") == _hash("ali")
    assert 0 <= _hash("ali") < RING_SIZE


def test_empty_ring_raises():
    with pytest.raises(LookupError):
        HashRing().get_node("ali")


def test_single_node_owns_everything():
    ring = make_ring("A")
    assert {ring.get_node(f"user{i}") for i in range(100)} == {"A"}


def test_same_key_always_same_node():
    ring = make_ring("A", "B", "C")
    assert ring.get_node("ali") == ring.get_node("ali")


def test_duplicate_node_raises():
    ring = make_ring("A")
    with pytest.raises(ValueError):
        ring.add_node("A")


def test_positions_stay_sorted():
    ring = make_ring("A", "B", "C", "D", "E")
    assert ring._positions == sorted(ring._positions)


def test_binary_search_matches_linear_search():
    ring = make_ring("A", "B", "C", "D", "E")
    for i in range(2000):
        key = f"user{i}"
        assert ring.get_node(key) == linear_owner(ring, key)


def test_key_after_last_node_wraps_to_first():
    ring = make_ring("A", "B", "C")
    last = ring._positions[-1]
    first_owner = ring._owners[ring._positions[0]]
    key = next(f"k{i}" for i in range(100_000) if _hash(f"k{i}") > last)
    assert ring.get_node(key) == first_owner
