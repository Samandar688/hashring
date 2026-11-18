"""In-memory cluster for tests: real node apps, no real network.

http://a.node/... goes to node app "A", http://b.node/... to "B", and so on.
A node can be killed (connection refused) and started again (empty storage).
"""

import httpx

from node.app import create_app as create_node


def urls(*names: str) -> dict[str, str]:
    return {n: f"http://{n.lower()}.node" for n in names}


class FakeCluster(httpx.AsyncBaseTransport):
    def __init__(self, *names: str) -> None:
        self.nodes: dict[str, httpx.ASGITransport] = {}
        self.down: set[str] = set()
        for name in names:
            self.start(name)

    def start(self, name: str) -> None:
        """Start (or restart) a node. A restarted node has lost its data."""
        self.nodes[name] = httpx.ASGITransport(app=create_node(name))
        self.down.discard(name)

    def kill(self, name: str) -> None:
        self.down.add(name)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        name = request.url.host.split(".")[0].upper()
        if name in self.down or name not in self.nodes:
            raise httpx.ConnectError(f"node {name} is down", request=request)
        return await self.nodes[name].handle_async_request(request)
