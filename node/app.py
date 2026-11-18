"""Cache node: one small server that keeps key/value pairs in memory.

Many copies of this service run at the same time (A, B, C ...).
The gateway uses the HashRing to decide which node gets each key.
"""

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class Item(BaseModel):
    value: Any


def create_app(name: str) -> FastAPI:
    """Build one cache node. Every node has its own empty storage."""
    app = FastAPI(title=f"cache node {name}")
    store: dict[str, Any] = {}

    @app.get("/health")
    async def health() -> dict:
        return {"node": name, "keys": len(store)}

    @app.put("/keys/{key}")
    async def put_key(key: str, item: Item) -> dict:
        store[key] = item.value
        return {"node": name, "key": key, "stored": True}

    @app.get("/keys/{key}")
    async def get_key(key: str) -> dict:
        if key not in store:
            raise HTTPException(status_code=404, detail=f"key {key!r} not found on node {name}")
        return {"node": name, "key": key, "value": store[key]}

    @app.delete("/keys/{key}")
    async def delete_key(key: str) -> dict:
        existed = key in store
        store.pop(key, None)
        return {"node": name, "key": key, "deleted": existed}

    @app.get("/keys")
    async def list_keys() -> dict:
        return {"node": name, "keys": sorted(store)}

    return app
