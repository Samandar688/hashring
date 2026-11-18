"""Cache node: one small server that keeps key/value pairs in memory.

Many copies of this service run at the same time (A, B, C ...).
The gateway uses the HashRing to decide which node gets each key.
"""

import asyncio
import os
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Kept as a module name so tests can replace it and survive a "crash".
_exit = os._exit


class Item(BaseModel):
    value: Any


def create_app(
    name: str,
    allow_crash: bool = False,
    max_keys: int | None = None,
    on_crash: Callable[[], None] | None = None,
) -> FastAPI:
    """Build one cache node. Every node has its own empty storage.

    allow_crash=True adds POST /admin/crash, which kills the process
    (or calls on_crash instead, when several nodes share one process).
    It exists only for demos (the dashboard "Crash" button).
    max_keys limits how many keys the node keeps, so a public demo
    cannot be filled until it runs out of memory.
    """
    app = FastAPI(title=f"cache node {name}")
    store: dict[str, Any] = {}

    @app.get("/health")
    async def health() -> dict:
        return {"node": name, "keys": len(store)}

    @app.put("/keys/{key}")
    async def put_key(key: str, item: Item) -> dict:
        if max_keys is not None and key not in store and len(store) >= max_keys:
            raise HTTPException(status_code=507, detail=f"node {name} is full ({max_keys} keys)")
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

    if allow_crash:

        @app.post("/admin/crash")
        async def crash() -> dict:
            # Answer first, then die a moment later: like a real crash, all data is lost.
            die = on_crash if on_crash is not None else (lambda: _exit(1))
            asyncio.get_running_loop().call_later(0.2, die)
            return {"node": name, "crashing": True}

    return app
