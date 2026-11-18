"""Benchmarks: prove the three claims of the project with numbers.

1. Key movement   - adding a node moves ~1/(N+1) keys with the ring, ~N/(N+1) with hash % N.
2. Load balance   - more virtual nodes -> each node gets closer to an equal share.
3. Lookup speed   - binary search on the ring is O(log N), a linear scan is O(N).

Run from the project root:  python benchmarks/run.py
Writes results.json, RESULTS.md and three PNG charts next to this file.
"""

import bisect
import json
import pathlib
import random
import statistics
import time

import matplotlib

matplotlib.use("Agg")  # draw to files, no window
import matplotlib.pyplot as plt  # noqa: E402

from hashring.ring import HashRing, _hash  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent
random.seed(42)

# Chart style: light surface, recessive grid, two fixed series colors.
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e2dc"
RING_COLOR, MOD_COLOR = "#2a78d6", "#eb6834"  # slot 1 blue, slot 2 orange
plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False,
    "font.size": 11, "axes.titlesize": 13, "axes.titleweight": "bold", "axes.titlecolor": INK,
    "legend.frameon": False, "lines.linewidth": 2,
})


def save(fig, name: str) -> None:
    fig.tight_layout()
    fig.savefig(OUT / name, dpi=150)
    plt.close(fig)


# ---- 1. key movement ------------------------------------------------------

def bench_movement(num_keys: int = 20_000, max_nodes: int = 20) -> list[dict]:
    keys = [f"user{i}" for i in range(num_keys)]
    hashes = [_hash(k) for k in keys]
    rows = []
    ring = HashRing()
    for n in range(2):
        ring.add_node(f"n{n}")
    for n in range(2, max_nodes + 1):  # n nodes -> n + 1 nodes
        before = [ring.get_node(k) for k in keys]
        ring.add_node(f"n{n}")
        after = [ring.get_node(k) for k in keys]
        ring_moved = sum(a != b for a, b in zip(before, after)) / num_keys
        mod_moved = sum(h % n != h % (n + 1) for h in hashes) / num_keys
        rows.append({"nodes_before": n, "ring_moved": ring_moved, "mod_moved": mod_moved, "ideal": 1 / (n + 1)})

    x = [r["nodes_before"] for r in rows]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(x, [r["mod_moved"] * 100 for r in rows], color=MOD_COLOR, marker="o", markersize=5, label="hash % N")
    ax.plot(x, [r["ring_moved"] * 100 for r in rows], color=RING_COLOR, marker="o", markersize=5, label="hash ring")
    ax.plot(x, [r["ideal"] * 100 for r in rows], color=MUTED, linestyle="--", linewidth=1.2, label="ideal 1/(N+1)")
    ax.set_title("Keys that move when one node is added")
    ax.set_xlabel("nodes before adding one")
    ax.set_ylabel("keys moved (%)")
    ax.set_ylim(0, 100)
    ax.set_xticks(x[::2])
    last = rows[-1]
    ax.annotate(f"{last['mod_moved']:.0%}", (x[-1], last["mod_moved"] * 100), xytext=(6, 0),
                textcoords="offset points", va="center", color=INK)
    ax.annotate(f"{last['ring_moved']:.0%}", (x[-1], last["ring_moved"] * 100), xytext=(6, 6),
                textcoords="offset points", va="center", color=INK)
    ax.legend(loc="center right")
    save(fig, "key_movement.png")
    return rows


# ---- 2. load balance vs virtual nodes --------------------------------------

def bench_balance(num_keys: int = 100_000, num_nodes: int = 10) -> list[dict]:
    keys = [f"user{i}" for i in range(num_keys)]
    rows = []
    for vnodes in [1, 5, 10, 25, 50, 100, 200, 500]:
        ring = HashRing(vnodes=vnodes)
        for n in range(num_nodes):
            ring.add_node(f"n{n}")
        counts = {n: 0 for n in ring.nodes}
        for k in keys:
            counts[ring.get_node(k)] += 1
        shares = [c / num_keys * 100 for c in counts.values()]
        rows.append({
            "vnodes": vnodes,
            "min_share": min(shares),
            "max_share": max(shares),
            "stdev_share": statistics.pstdev(shares),
            "max_over_avg": max(shares) / (100 / num_nodes),
        })

    x = [r["vnodes"] for r in rows]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.fill_between(x, [r["min_share"] for r in rows], [r["max_share"] for r in rows],
                    color=RING_COLOR, alpha=0.18, linewidth=0, label="range: least to most loaded node")
    ax.plot(x, [r["max_share"] for r in rows], color=RING_COLOR, marker="o", markersize=5, label="most loaded node")
    ax.plot(x, [r["min_share"] for r in rows], color=RING_COLOR, marker="o", markersize=5, linewidth=1.2,
            linestyle=":", label="least loaded node")
    ax.axhline(100 / num_nodes, color=MUTED, linestyle="--", linewidth=1.2, label=f"ideal {100 / num_nodes:.0f}%")
    ax.set_xscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels([str(v) for v in x])
    ax.set_title(f"Share of keys per node ({num_nodes} nodes)")
    ax.set_xlabel("virtual nodes per server (log scale)")
    ax.set_ylabel("share of all keys (%)")
    ax.set_ylim(0, None)
    ax.legend(loc="upper right")
    save(fig, "load_balance.png")
    return rows


# ---- 3. lookup speed: binary vs linear -------------------------------------

def linear_search(positions: list[int], x: int) -> int:
    for i, p in enumerate(positions):
        if p >= x:
            return i
    return len(positions)


def per_lookup_us(fn, positions: list[int], targets: list[int]) -> float:
    best = float("inf")
    for _ in range(3):  # best of 3 runs, to hide noise from other programs
        start = time.perf_counter()
        for t in targets:
            fn(positions, t)
        best = min(best, time.perf_counter() - start)
    return best / len(targets) * 1e6


def bench_lookup() -> list[dict]:
    rows = []
    for points in [100, 1_000, 10_000, 100_000]:
        positions = sorted(random.sample(range(2**32), points))
        targets = [random.randrange(2**32) for _ in range(max(50, 200_000 // points))]
        bin_us = per_lookup_us(bisect.bisect_left, positions, targets)
        lin_us = per_lookup_us(linear_search, positions, targets)
        rows.append({"points": points, "binary_us": bin_us, "linear_us": lin_us, "speedup": lin_us / bin_us})

    x = [r["points"] for r in rows]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(x, [r["linear_us"] for r in rows], color=MOD_COLOR, marker="o", markersize=5, label="linear scan  O(N)")
    ax.plot(x, [r["binary_us"] for r in rows], color=RING_COLOR, marker="o", markersize=5, label="binary search  O(log N)")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{v:,}" for v in x])
    ax.set_title("Time to find the owner of one key")
    ax.set_xlabel("points on the ring (servers x virtual nodes)")
    ax.set_ylabel("microseconds per lookup (log scale)")
    last = rows[-1]
    ax.annotate(f"{last['speedup']:,.0f}x faster", (x[-1], last["binary_us"]), xytext=(-10, 14),
                textcoords="offset points", ha="right", color=INK)
    ax.legend(loc="upper left")
    save(fig, "lookup_speed.png")
    return rows


# ---- report ------------------------------------------------------------------

def write_markdown(movement, balance, lookup) -> str:
    lines = ["# Benchmark results", "", "Generated by `python benchmarks/run.py`.", ""]
    lines += ["## 1. Keys moved when one node is added (20,000 keys)", "",
              "![key movement](key_movement.png)", "",
              "| Nodes | hash % N | hash ring | ideal 1/(N+1) |", "|---:|---:|---:|---:|"]
    for r in movement:
        if r["nodes_before"] in (2, 3, 4, 5, 10, 15, 20):
            lines.append(f"| {r['nodes_before']} → {r['nodes_before'] + 1} | {r['mod_moved']:.1%} "
                         f"| {r['ring_moved']:.1%} | {r['ideal']:.1%} |")
    lines += ["", "## 2. Load balance vs virtual nodes (10 nodes, 100,000 keys, ideal 10%)", "",
              "![load balance](load_balance.png)", "",
              "| Virtual nodes | Least loaded | Most loaded | Std dev | Most loaded ÷ average |",
              "|---:|---:|---:|---:|---:|"]
    for r in balance:
        lines.append(f"| {r['vnodes']} | {r['min_share']:.1f}% | {r['max_share']:.1f}% "
                     f"| {r['stdev_share']:.2f} | {r['max_over_avg']:.2f}× |")
    lines += ["", "## 3. Lookup time: binary search vs linear scan", "",
              "![lookup speed](lookup_speed.png)", "",
              "| Points on ring | Binary search | Linear scan | Speed-up |", "|---:|---:|---:|---:|"]
    for r in lookup:
        lines.append(f"| {r['points']:,} | {r['binary_us']:.2f} µs | {r['linear_us']:,.1f} µs | {r['speedup']:,.0f}× |")
    lines += ["", "Times depend on the machine; the shape of the curves does not.", ""]
    return "\n".join(lines)


def main() -> None:
    t0 = time.perf_counter()
    print("1/3 key movement ...")
    movement = bench_movement()
    print("2/3 load balance ...")
    balance = bench_balance()
    print("3/3 lookup speed ...")
    lookup = bench_lookup()
    (OUT / "results.json").write_text(
        json.dumps({"movement": movement, "balance": balance, "lookup": lookup}, indent=2), encoding="utf-8")
    (OUT / "RESULTS.md").write_text(write_markdown(movement, balance, lookup), encoding="utf-8")
    print(f"done in {time.perf_counter() - t0:.1f} s -> {OUT}")


if __name__ == "__main__":
    main()
