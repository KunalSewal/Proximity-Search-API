import heapq
import math
import os
import random
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine import Dataset, GraphCache, build_graph, parse_link_pairs, search  # noqa: E402

CATS = ["a", "b", "c"]


def small_grid(n, seed):
    rng = random.Random(seed)
    ids, lats, lons, cats = [], [], [], []
    for r in range(n):
        for c in range(n):
            ids.append(r * n + c + 1)
            lats.append(r / (n - 1))
            lons.append(c / (n - 1))
            cats.append(rng.choice(CATS))
    return Dataset(ids, lats, lons, cats)


def random_links(n, drop, seed, diag=0.0):
    rng = random.Random(seed)
    out = []
    for r in range(n):
        for c in range(n):
            a = r * n + c + 1
            for nr, nc, p in ((r + 1, c, 1 - drop), (r, c + 1, 1 - drop), (r + 1, c + 1, diag)):
                if nr < n and nc < n and rng.random() < p:
                    out.append(f"{a} {nr * n + nc + 1}")
    return "\n".join(out)


def all_pairs(ds, text):
    """Floyd-Warshall all-pairs shortest paths. Independent of engine.search."""
    n = ds.n
    INF = math.inf
    d = [[INF] * n for _ in range(n)]
    for i in range(n):
        d[i][i] = 0.0
    for a, b in parse_link_pairs(text)[0]:
        i, j = ds.index_of[a], ds.index_of[b]
        w = math.hypot(ds.lat[i] - ds.lat[j], ds.lon[i] - ds.lon[j])
        d[i][j] = d[j][i] = min(d[i][j], w)
    for m in range(n):
        dm = d[m]
        for i in range(n):
            dim = d[i][m]
            if dim == INF:
                continue
            di = d[i]
            for j in range(n):
                if dim + dm[j] < di[j]:
                    di[j] = dim + dm[j]
    return d


def floyd_reference(ds, d, lat, lon, cat, rad, k):
    INF = math.inf
    n = ds.n
    src = min(range(n), key=lambda i: (round(math.hypot(ds.lat[i] - lat, ds.lon[i] - lon), 12), ds.ids[i]))
    rows = []
    for i in range(n):
        e = math.hypot(ds.lat[i] - lat, ds.lon[i] - lon)
        if ds.cat[i] == cat and e <= rad + 1e-9 and d[src][i] < INF:
            rows.append((round(d[src][i], 9), round(e, 12), ds.ids[i]))
    rows.sort()
    return [r[2] for r in rows[:k]]


@pytest.mark.parametrize("seed", range(6))
def test_matches_floyd_warshall_on_small_grids(seed):
    n = 12
    ds = small_grid(n, seed)
    text = random_links(n, drop=0.35, seed=seed, diag=0.15 if seed % 2 else 0.0)
    graph = build_graph(ds, text)
    d = all_pairs(ds, text)
    rng = random.Random(100 + seed)
    for _ in range(25):
        lat, lon = rng.random(), rng.random()
        cat = rng.choice(CATS)
        rad = rng.choice([0.2, 0.4, 0.7, 2.0])
        got = [ds.ids[h.index] for h in search(ds, graph, lat, lon, cat, rad, 10)[0]]
        assert got == floyd_reference(ds, d, lat, lon, cat, rad, 10)


def full_dijkstra_reference(ds, text, lat, lon, cat, rad, k):
    """Exhaustive Dijkstra over the whole graph (no early stop), then sort."""
    adj = [[] for _ in range(ds.n)]
    for a, b in parse_link_pairs(text)[0]:
        i, j = ds.index_of[a], ds.index_of[b]
        w = math.hypot(ds.lat[i] - ds.lat[j], ds.lon[i] - ds.lon[j])
        adj[i].append((j, w))
        adj[j].append((i, w))
    src = min(range(ds.n), key=lambda i: (round(math.hypot(ds.lat[i] - lat, ds.lon[i] - lon), 12), ds.ids[i]))
    dist = [math.inf] * ds.n
    dist[src] = 0.0
    pq = [(0.0, src)]
    while pq:
        du, u = heapq.heappop(pq)
        if du > dist[u]:
            continue
        for v, w in adj[u]:
            if du + w < dist[v] - 1e-12:
                dist[v] = du + w
                heapq.heappush(pq, (dist[v], v))
    rows = []
    for i in range(ds.n):
        e = math.hypot(ds.lat[i] - lat, ds.lon[i] - lon)
        if ds.cat[i] == cat and e <= rad + 1e-9 and dist[i] < math.inf:
            rows.append((round(dist[i], 9), round(e, 12), ds.ids[i]))
    rows.sort()
    return [r[2] for r in rows[:k]]


@pytest.fixture(scope="module")
def real():
    return Dataset.from_csv(os.path.join(ROOT, "data", "locations.csv"))


@pytest.mark.parametrize("drop", [0.0, 0.25, 0.45])
def test_early_stop_matches_exhaustive_on_real_data(real, drop):
    text = random_links(100, drop=drop, seed=int(drop * 100))
    graph = build_graph(real, text)
    rng = random.Random(7)
    for _ in range(40):
        lat, lon = rng.random(), rng.random()
        cat = rng.choice(real.categories)
        rad = rng.choice([0.05, 0.1, 0.2, 0.5, 1.5])
        got = [real.ids[h.index] for h in search(real, graph, lat, lon, cat, rad, 10)[0]]
        assert got == full_dijkstra_reference(real, text, lat, lon, cat, rad, 10)


def test_zero_based_link_file_is_detected(real):
    one = "1 2\n2 3\n1 101\n"
    zero = "0 1\n1 2\n0 100\n"
    g1, g0 = build_graph(real, one), build_graph(real, zero)
    assert g0.index_base == 0 and g1.index_base == 1
    assert sorted(g0.adj[0]) == sorted(g1.adj[0])


def test_parser_tolerates_noise():
    pairs, ignored = parse_link_pairs("a b\n1 2\n3,4\n5\t6\n\n# comment\n7 8 9\nfoo\n")
    assert pairs == [(1, 2), (3, 4), (5, 6), (7, 8)]
    assert ignored == 2


def test_nearest_snaps_to_grid(real):
    i = real.nearest(0.5051, 0.4949)  # row 50, col 49
    assert real.ids[i] == 50 * 100 + 49 + 1
    assert real.ids[real.nearest(-5, -5)] == 1
    assert real.ids[real.nearest(9, 9)] == 10000


def test_unreachable_candidates_are_excluded(real):
    # Only a tiny island around node 1 is connected.
    graph = build_graph(real, "1 2\n2 3\n1 101\n")
    hits, _ = search(real, graph, 0.0, 0.0, None, 1.0, 10)
    assert sorted(real.ids[h.index] for h in hits) == [1, 2, 3, 101]


def test_default_graph_is_full_grid(real):
    g = GraphCache(real).default
    assert g.edges == 2 * 100 * 99
