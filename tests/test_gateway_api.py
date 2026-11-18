import pytest
from fastapi.testclient import TestClient

from gateway.app import create_app
from tests.fake_cluster import FakeCluster, urls


@pytest.fixture
def api():
    app = create_app(urls("A", "B", "C"), health_interval=3600, transport=FakeCluster("A", "B", "C"))
    with TestClient(app) as c:  # "with" runs startup: first health check
        yield c


def test_put_and_get_through_gateway(api):
    assert api.put("/keys/ali", json={"value": 100}).status_code == 200
    r = api.get("/keys/ali")
    assert r.status_code == 200
    assert r.json()["value"] == 100
    assert r.json()["node"] in {"A", "B", "C"}


def test_missing_key_is_404_with_node(api):
    r = api.get("/keys/nobody")
    assert r.status_code == 404
    assert r.json()["detail"]["node"] in {"A", "B", "C"}


def test_unsafe_key_is_rejected(api):
    assert api.get("/keys/bad key!").status_code == 422


def test_locate_matches_where_data_lands(api):
    where = api.get("/locate/ali").json()
    api.put("/keys/ali", json={"value": 1})
    assert api.get("/keys/ali").json()["node"] == where["node"]
    assert 0 <= where["position"] < 2**32


def test_cluster_snapshot(api):
    snap = api.get("/cluster").json()
    assert [n["name"] for n in snap["nodes"]] == ["A", "B", "C"]
    assert all(n["alive"] for n in snap["nodes"])
    assert len(snap["points"]) == 300  # 3 nodes x 100 virtual nodes


def test_cluster_refresh_gives_fresh_key_counts(api):
    for i in range(10):
        api.put(f"/keys/user{i}", json={"value": i})
    stale = sum(n["keys"] for n in api.get("/cluster").json()["nodes"])
    fresh = sum(n["keys"] for n in api.get("/cluster", params={"refresh": True}).json()["nodes"])
    assert stale == 0  # health check has not run since startup
    assert fresh == 10


def test_events_after_startup(api):
    events = api.get("/events").json()
    assert [e["type"] for e in events] == ["node_up"] * 3
    assert api.get("/events", params={"since": events[-1]["time"]}).json() == []


def test_add_existing_node_is_409_and_unknown_remove_is_404(api):
    assert api.post("/nodes", json={"name": "A", "url": "http://a.node"}).status_code == 409
    assert api.delete("/nodes/Z").status_code == 404


def test_graceful_remove_over_http(api):
    for i in range(30):
        api.put(f"/keys/user{i}", json={"value": i})
    r = api.delete("/nodes/A")
    assert r.status_code == 200
    assert all(api.get(f"/keys/user{i}").status_code == 200 for i in range(30))


def test_simulator_settings(api):
    r = api.post("/simulator", json={"running": True, "rate": 50})
    assert r.json() == {"running": True, "rate": 50}
    assert api.post("/simulator", json={"running": True, "rate": 0}).status_code == 422
    api.post("/simulator", json={"running": False})
