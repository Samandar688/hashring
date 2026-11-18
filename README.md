# HashRing

A small distributed cache built on **consistent hashing**, with a live web dashboard
that shows keys flowing to nodes and moving when a node joins or dies.

## Why

With naive `hash(key) % N`, adding or removing one server moves almost every key.
With a hash ring, only the keys of the affected server move (about `1/N` of them).
Finding the owner of a key is a binary search over the sorted ring: `O(log N)`.

## Results

Measured with `python benchmarks/run.py` (full tables in [benchmarks/RESULTS.md](benchmarks/RESULTS.md)).

| Claim | Number |
|---|---|
| Adding a 21st node moves only the keys it now owns | **4.5%** of keys move with the ring vs **95.1%** with `hash % N` |
| Virtual nodes spread keys evenly (10 nodes, ideal 10%) | 1 vnode: 0.6%–22.5% per node · 100 vnodes: 8.9%–11.9% |
| Binary search finds the owner fast | 100,000 points: **0.18 µs** vs 1,561 µs for a linear scan (~8,500×) |

![Keys moved when a node is added](benchmarks/key_movement.png)
![Share of keys per node vs virtual nodes](benchmarks/load_balance.png)
![Lookup time: binary search vs linear scan](benchmarks/lookup_speed.png)

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
- [x] 3. Gateway + API + simulator (`python scripts/run_cluster.py`, demo: `python scripts/demo_gateway.py`)
- [x] 4. Live dashboard (`python scripts/run_cluster.py`, then open http://127.0.0.1:8000)
- [x] 5. Benchmarks (`pip install -e ".[bench]"`, then `python benchmarks/run.py`)
- [ ] 6. Docker, deploy, demo GIF

## Run (dev)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest
```
