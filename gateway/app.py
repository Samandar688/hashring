"""Gateway HTTP API. Clients talk only to this server, never to nodes."""

import asyncio
import json
import logging
import os
import pathlib
from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx
from fastapi import FastAPI, HTTPException, Path
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from gateway.core import Gateway, NoNodesAlive
from hashring.ring import _hash

log = logging.getLogger("gateway")

DASHBOARD_DIR = pathlib.Path(
    os.environ.get("HASHRING_DASHBOARD_DIR", pathlib.Path(__file__).resolve().parent.parent / "dashboard")
)
MAX_VALUE_BYTES = 1024  # a cache demo does not need big values; protects a public deploy

# Keys go into node URLs, so we allow only safe characters.
Key = Annotated[str, Path(pattern=r"^[A-Za-z0-9_.:-]{1,200}$")]


class Item(BaseModel):
    value: Any


class NewNode(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")
    url: str = Field(pattern=r"^https?://")


class SimulatorSettings(BaseModel):
    running: bool
    rate: int = Field(default=20, ge=1, le=500)


async def _health_loop(gw: Gateway, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await gw.check_health()
        except Exception:  # keep the loop alive no matter what
            log.exception("health check failed")


async def _simulator_loop(gw: Gateway) -> None:
    while True:
        if gw.sim_running:
            try:
                await gw.simulate_once()
            except Exception:
                log.exception("simulator step failed")
            await asyncio.sleep(1 / gw.sim_rate)
        else:
            await asyncio.sleep(0.2)


def create_app(
    nodes: dict[str, str],
    health_interval: float = 2.0,
    transport: httpx.AsyncBaseTransport | None = None,
    spares: dict[str, str] | None = None,
    max_value_bytes: int = MAX_VALUE_BYTES,
) -> FastAPI:
    """Build the gateway. `transport` lets tests plug in fake nodes."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with httpx.AsyncClient(transport=transport) as client:
            gw = Gateway(nodes, client, spares=spares)
            app.state.gw = gw
            await gw.check_health()
            tasks = [
                asyncio.create_task(_health_loop(gw, health_interval)),
                asyncio.create_task(_simulator_loop(gw)),
            ]
            try:
                yield
            finally:
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="hashring gateway", lifespan=lifespan)

    def gw() -> Gateway:
        return app.state.gw

    async def route(method: str, key: str, **kwargs) -> tuple[str, httpx.Response]:
        try:
            return await gw().request(method, key, **kwargs)
        except NoNodesAlive:
            raise HTTPException(status_code=503, detail="no cache nodes are alive")

    # ---- keys -----------------------------------------------------------

    @app.get("/keys/{key}")
    async def get_key(key: Key) -> dict:
        node, r = await route("GET", key)
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail={"node": node, "error": "key not found"})
        return r.json()

    @app.put("/keys/{key}")
    async def put_key(key: Key, item: Item) -> dict:
        size = len(json.dumps(item.value))
        if size > max_value_bytes:
            raise HTTPException(status_code=413, detail=f"value is {size} bytes, limit is {max_value_bytes}")
        node, r = await route("PUT", key, json={"value": item.value})
        if r.status_code == 507:
            raise HTTPException(status_code=507, detail={"node": node, "error": "node is full"})
        if r.is_error:
            raise HTTPException(status_code=502, detail={"node": node, "error": "node refused the write"})
        return r.json()

    @app.delete("/keys/{key}")
    async def delete_key(key: Key) -> dict:
        node, r = await route("DELETE", key)
        if r.is_error:
            raise HTTPException(status_code=502, detail={"node": node, "error": "node refused the delete"})
        return r.json()

    @app.get("/locate/{key}")
    async def locate(key: Key) -> dict:
        """Where does this key live? No node is contacted."""
        node = gw().ring.get_node(key) if gw().alive else None
        return {"key": key, "position": _hash(key), "node": node}

    # ---- cluster --------------------------------------------------------

    @app.get("/cluster")
    async def cluster(refresh: bool = False) -> dict:
        """Cluster state. Key counts come from the last health check,
        or from a fresh one if refresh=true (slower: asks every node)."""
        if refresh:
            await gw().check_health()
        return gw().snapshot()

    @app.get("/events")
    async def events(since: float = 0.0) -> list[dict]:
        return [e for e in gw().events if e["time"] > since]

    @app.post("/nodes", status_code=201)
    async def add_node(node: NewNode) -> dict:
        try:
            await gw().add_node(node.name, node.url)
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))
        return {"name": node.name, "alive": node.name in gw().alive}

    @app.delete("/nodes/{name}")
    async def remove_node(name: str) -> dict:
        try:
            moved = await gw().remove_node(name)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))
        return {"removed": name, "moved": moved}

    @app.post("/nodes/{name}/crash")
    async def crash_node(name: str) -> dict:
        try:
            await gw().crash_node(name)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except PermissionError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except httpx.HTTPError:
            raise HTTPException(status_code=502, detail=f"node {name!r} did not answer")
        return {"crashed": name}

    # ---- simulator ------------------------------------------------------

    @app.post("/simulator")
    async def simulator(settings: SimulatorSettings) -> dict:
        gw().sim_running = settings.running
        gw().sim_rate = settings.rate
        return {"running": gw().sim_running, "rate": gw().sim_rate}

    # ---- dashboard (mounted last, so API routes win) ---------------------

    if DASHBOARD_DIR.is_dir():
        app.mount("/", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")

    return app
