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


# --- virtual nodes --------------------------------------------------------

KEYS = [f"user{i}" for i in range(10_000)]


def owners(ring: HashRing) -> dict[str, str]:
    return {k: ring.get_node(k) for k in KEYS}


def test_vnodes_must_be_positive():
    with pytest.raises(ValueError):
        HashRing(vnodes=0)


def test_each_node_is_placed_vnodes_times():
    ring = HashRing(vnodes=50)
    ring.add_node("A")
    ring.add_node("B")
    assert len(ring._positions) == 100
    assert ring.nodes == ["A", "B"]
    points = ring.points()
    assert len(points) == 100
    assert [p for p, _ in points] == sorted(p for p, _ in points)
    assert {n for _, n in points} == {"A", "B"}


def test_keys_are_shared_almost_equally():
    ring = make_ring("A", "B", "C", "D", "E")  # 5 nodes -> 20% each is ideal
    counts = {n: 0 for n in ring.nodes}
    for node in owners(ring).values():
        counts[node] += 1
    for n, c in counts.items():
        assert 0.15 < c / len(KEYS) < 0.25, f"{n} got {c / len(KEYS):.1%}"


# --- removing nodes -------------------------------------------------------

def test_remove_unknown_node_raises():
    with pytest.raises(KeyError):
        make_ring("A").remove_node("Z")


def test_remove_last_node_makes_ring_empty():
    ring = make_ring("A")
    ring.remove_node("A")
    assert ring._positions == [] and ring._owners == {} and ring.nodes == []
    with pytest.raises(LookupError):
        ring.get_node("ali")


def test_remove_moves_only_keys_of_removed_node():
    ring = make_ring("A", "B", "C", "D")
    before = owners(ring)
    ring.remove_node("B")
    after = owners(ring)
    for k in KEYS:
        if before[k] != "B":
            assert after[k] == before[k]  # untouched keys stay put
        else:
            assert after[k] != "B"  # B's keys found a new home


def test_add_moves_keys_only_to_new_node():
    ring = make_ring("A", "B", "C", "D")
    before = owners(ring)
    ring.add_node("E")
    after = owners(ring)
    moved = [k for k in KEYS if before[k] != after[k]]
    assert all(after[k] == "E" for k in moved)


# --- the whole point: ring vs hash % N -------------------------------------

def test_ring_moves_far_fewer_keys_than_modulo():
    ring = make_ring("A", "B", "C", "D")
    before = owners(ring)
    ring.add_node("E")
    after = owners(ring)
    ring_moved = sum(before[k] != after[k] for k in KEYS) / len(KEYS)
    mod_moved = sum(_hash(k) % 4 != _hash(k) % 5 for k in KEYS) / len(KEYS)
    assert ring_moved < 0.30  # ideal is 1/5 = 20%
    assert mod_moved > 0.70  # naive way moves ~80%
