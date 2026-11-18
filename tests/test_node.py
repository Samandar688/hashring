from fastapi.testclient import TestClient

from node.app import create_app


def client(name: str = "A") -> TestClient:
    return TestClient(create_app(name))


def test_health_shows_name_and_zero_keys():
    r = client("A").get("/health")
    assert r.status_code == 200
    assert r.json() == {"node": "A", "keys": 0}


def test_put_then_get_returns_value():
    c = client()
    assert c.put("/keys/ali", json={"value": {"balance": 100}}).status_code == 200
    r = c.get("/keys/ali")
    assert r.status_code == 200
    assert r.json()["value"] == {"balance": 100}


def test_missing_key_is_404():
    assert client().get("/keys/nobody").status_code == 404


def test_put_overwrites_old_value():
    c = client()
    c.put("/keys/ali", json={"value": 1})
    c.put("/keys/ali", json={"value": 2})
    assert c.get("/keys/ali").json()["value"] == 2
    assert c.get("/health").json()["keys"] == 1


def test_delete_removes_key():
    c = client()
    c.put("/keys/ali", json={"value": 1})
    assert c.delete("/keys/ali").json()["deleted"] is True
    assert c.get("/keys/ali").status_code == 404
    assert c.delete("/keys/ali").json()["deleted"] is False


def test_null_value_can_be_stored_and_deleted():
    c = client()
    c.put("/keys/x", json={"value": None})
    assert c.get("/keys/x").json()["value"] is None
    assert c.delete("/keys/x").json()["deleted"] is True


def test_list_keys_is_sorted():
    c = client()
    for k in ["vali", "ali", "sami"]:
        c.put(f"/keys/{k}", json={"value": 1})
    assert c.get("/keys").json()["keys"] == ["ali", "sami", "vali"]


def test_crash_endpoint_is_off_by_default():
    assert client().post("/admin/crash").status_code == 404


def test_crash_endpoint_schedules_exit(monkeypatch):
    calls = []
    monkeypatch.setattr("node.app._exit", calls.append)
    with TestClient(create_app("A", allow_crash=True)) as c:
        assert c.post("/admin/crash").json() == {"node": "A", "crashing": True}
        import time

        time.sleep(0.4)  # the exit is scheduled 0.2 s later
    assert calls == [1]


def test_full_node_refuses_new_keys_but_allows_updates():
    c = TestClient(create_app("A", max_keys=2))
    c.put("/keys/a", json={"value": 1})
    c.put("/keys/b", json={"value": 1})
    assert c.put("/keys/c", json={"value": 1}).status_code == 507
    assert c.put("/keys/a", json={"value": 2}).status_code == 200  # existing key: fine
    assert c.get("/health").json()["keys"] == 2


def test_two_nodes_do_not_share_storage():
    a, b = client("A"), client("B")
    a.put("/keys/ali", json={"value": 1})
    assert b.get("/keys/ali").status_code == 404
