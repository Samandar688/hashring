"""Helpers to start real node / gateway processes on this machine."""

import subprocess
import sys
import time

import httpx

GATEWAY = "http://127.0.0.1:8000"


def node_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def start_node(name: str, port: int) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-m", "node", "--name", name, "--port", str(port)])


def start_gateway(nodes: dict[str, int], port: int = 8000, health_interval: float = 1.0) -> subprocess.Popen:
    args = [sys.executable, "-m", "gateway", "--port", str(port), "--health-interval", str(health_interval)]
    for name, node_port in nodes.items():
        args += ["--node", f"{name}={node_url(node_port)}"]
    return subprocess.Popen(args)


def wait_until_up(base_url: str, path: str = "/health", timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            httpx.get(base_url + path, timeout=0.5)
            return
        except httpx.TransportError:
            time.sleep(0.2)
    raise RuntimeError(f"{base_url} did not start")


def stop(procs) -> None:
    for p in procs:
        if p.poll() is None:
            p.terminate()
            p.wait()
