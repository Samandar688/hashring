# HashRing

A small distributed cache built on **consistent hashing**, with a live web dashboard
that shows keys flowing to nodes and moving when a node joins or dies.

## Why

With naive `hash(key) % N`, adding or removing one server moves almost every key.
With a hash ring, only the keys of the affected server move (about `1/N` of them).
Finding the owner of a key is a binary search over the sorted ring: `O(log N)`.

## Structure

| Folder        | What it holds                                   |
|---------------|-------------------------------------------------|
| `hashring/`   | Core algorithm: ring, `bisect`, virtual nodes   |
| `node/`       | Cache node service (stores key/value)           |
| `gateway/`    | FastAPI router + traffic simulator              |
| `dashboard/`  | HTML + D3.js live visualization                 |
| `benchmarks/` | Ring vs `hash % N`, load balance vs vnodes      |
| `tests/`      | pytest tests                                    |

## Roadmap

- [x] 1. Core `HashRing` + tests (virtual nodes, add/remove)
- [x] 2. Cache nodes (`python -m node --name A --port 8001`, demo: `python scripts/demo_nodes.py`)
- [ ] 3. Gateway + API + simulator
- [ ] 4. Live dashboard
- [ ] 5. Benchmarks
- [ ] 6. Docker, deploy, demo GIF

## Run (dev)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest
```
