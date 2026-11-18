import httpx
import pytest

from gateway.core import Gateway, NoNodesAlive
from tests.fake_cluster import FakeCluster, urls

pytestmark = pytest.mark.anyio

KEYS = [f"user{i}" for i in range(60)]


@pytest.fixture
async def setup():
    cluster = FakeCluster("A", "B", "C")
    async with httpx.AsyncClient(transport=cluster) as client:
        gw = Gateway(urls("A", "B", "C"), client)
        await gw.check_health()
        yield gw, cluster


async def put_all(gw: Gateway) -> None:
    for k in KEYS:
        _, r = await gw.request("PUT", k, json={"value": f"data of {k}"})
        assert r.status_code == 200


async def read_all(gw: Gateway) -> dict[str, tuple[str, int]]:
    result = {}
    for k in KEYS:
        node, r = await gw.request("GET", k)
        result[k] = (node, r.status_code)
    return result


async def total_keys(gw: Gateway) -> int:
    await gw.check_health()  # refreshes key_counts
    return sum(gw.key_counts.values())


async def test_health_check_brings_all_nodes_up(setup):
    gw, _ = setup
    assert gw.alive == {"A", "B", "C"}
    assert sorted(gw.ring.nodes) == ["A", "B", "C"]
    assert [e["type"] for e in gw.events] == ["node_up"] * 3


async def test_put_then_get_goes_to_ring_owner(setup):
    gw, _ = setup
    owner = gw.ring.get_node("ali")
    node, r = await gw.request("PUT", "ali", json={"value": 42})
    assert node == owner
    node, r = await gw.request("GET", "ali")
    assert node == owner and r.json()["value"] == 42


async def test_keys_are_spread_over_nodes(setup):
    gw, _ = setup
    await put_all(gw)
    await gw.check_health()
    assert all(gw.key_counts[n] > 0 for n in "ABC")
    assert sum(gw.key_counts.values()) == len(KEYS)


async def test_health_check_removes_dead_node(setup):
    gw, cluster = setup
    await put_all(gw)
    b_keys = {k for k in KEYS if gw.ring.get_node(k) == "B"}
    cluster.kill("B")
    await gw.check_health()
    assert "B" not in gw.alive and "B" not in gw.ring.nodes
    assert gw.events[-1]["type"] == "node_down" and gw.events[-1]["node"] == "B"
    # B's data is gone (404), everything else is still there (200). No crash.
    for k, (_, status) in (await read_all(gw)).items():
        assert status == (404 if k in b_keys else 200)


async def test_write_fails_over_when_owner_is_dead(setup):
    gw, cluster = setup
    owner = gw.ring.get_node("ali")
    cluster.kill(owner)  # dead, but no health check has noticed yet
    node, r = await gw.request("PUT", "ali", json={"value": 1})
    assert r.status_code == 200
    assert node != owner
    assert owner not in gw.alive


async def test_new_node_receives_its_keys(setup):
    gw, cluster = setup
    await put_all(gw)
    cluster.start("D")
    await gw.add_node("D", "http://d.node")
    assert gw.events[-1] == {**gw.events[-1], "type": "node_up", "node": "D"}
    assert gw.events[-1]["moved"] > 0
    reads = await read_all(gw)
    assert all(status == 200 for _, status in reads.values())  # nothing lost
    assert any(node == "D" for node, _ in reads.values())  # D serves its keys
    assert await total_keys(gw) == len(KEYS)  # moved, not copied


async def test_graceful_remove_keeps_every_key(setup):
    gw, _ = setup
    await put_all(gw)
    moved = await gw.remove_node("A")
    assert moved > 0
    assert "A" not in gw.urls
    reads = await read_all(gw)
    assert all(status == 200 for _, status in reads.values())
    assert all(node != "A" for node, _ in reads.values())
    assert await total_keys(gw) == len(KEYS)


async def test_dead_node_comes_back(setup):
    gw, cluster = setup
    cluster.kill("B")
    await gw.check_health()
    assert "B" not in gw.alive
    cluster.start("B")
    await gw.check_health()
    assert "B" in gw.alive
    assert gw.events[-1]["type"] == "node_up"


async def test_no_nodes_alive_raises(setup):
    gw, cluster = setup
    for n in "ABC":
        cluster.kill(n)
    await gw.check_health()
    with pytest.raises(NoNodesAlive):
        await gw.request("GET", "ali")


async def test_add_twice_and_remove_unknown_raise(setup):
    gw, _ = setup
    with pytest.raises(ValueError):
        await gw.add_node("A", "http://a.node")
    with pytest.raises(KeyError):
        await gw.remove_node("Z")


async def test_simulator_counts_every_request(setup):
    gw, _ = setup
    for _ in range(50):
        await gw.simulate_once()
    assert sum(gw.stats.values()) == 50
    assert gw.stats["errors"] == 0
    assert sum(gw.requests.values()) == 50
