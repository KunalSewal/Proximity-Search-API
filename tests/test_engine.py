import heapq
import math
import os
import random
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine import Dataset, GraphCache, build_graph, parse_links, search  # noqa: E402

CATS = ["a", "b", "c"]


def small_grid(n, seed):
    rng = random.Random(seed)
    ids, lats, lons, cats = [], [], [], []
    for r in range(n):
        for c in range(n):
            ids.append(r * n + c + 1)
            lats.append(round(r / (n - 1), 6))
            lons.append(round(c / (n - 1), 6))
            cats.append(rng.choice(CATS))
    return Dataset(ids, lats, lons, cats)


def random_links(ds, n, drop, seed):
    """Official layout: Longitude_A Latitude_A Longitude_B Latitude_B, grid neighbours only."""
    rng = random.Random(seed)
    out = []
    for r in range(n):
        for c in range(n):
            a = r * n + c
            for nr, nc in ((r + 1, c), (r, c + 1)):
                if nr < n and nc < n and rng.random() >= drop:
                    b = nr * n + nc
                    out.append(f"{ds.lon[a]:.6f} {ds.lat[a]:.6f} {ds.lon[b]:.6f} {ds.lat[b]:.6f}")
    rng.shuffle(out)
    return "\n".join(out)


def reference_adjacency(ds, text):
    """Independent parser for the reference solvers (does not use engine code)."""
    where = {(round(ds.lat[i], 6), round(ds.lon[i], 6)): i for i in range(ds.n)}
    adj = [[] for _ in range(ds.n)]
    for line in text.splitlines():
        lon_a, lat_a, lon_b, lat_b = map(float, line.split())
        i = where[(round(lat_a, 6), round(lon_a, 6))]
        j = where[(round(lat_b, 6), round(lon_b, 6))]
        w = math.hypot(ds.lat[i] - ds.lat[j], ds.lon[i] - ds.lon[j])
        adj[i].append((j, w))
        adj[j].append((i, w))
    return adj


def nearest_ref(ds, lat, lon):
    return min(range(ds.n), key=lambda i: (round(math.hypot(ds.lat[i] - lat, ds.lon[i] - lon), 12), ds.ids[i]))


def rank(ds, dist_from_src, lat, lon, cat, rad, k):
    rows = []
    for i in range(ds.n):
        e = math.hypot(ds.lat[i] - lat, ds.lon[i] - lon)
        if ds.cat[i] == cat and e <= rad + 1e-9 and dist_from_src[i] < math.inf:
            rows.append((round(dist_from_src[i], 9), round(e, 12), ds.ids[i]))
    rows.sort()
    return [r[2] for r in rows[:k]]


def all_pairs(ds, text):
    """Floyd-Warshall all-pairs shortest paths."""
    n = ds.n
    INF = math.inf
    d = [[INF] * n for _ in range(n)]
    for i in range(n):
        d[i][i] = 0.0
    for i, nbrs in enumerate(reference_adjacency(ds, text)):
        for j, w in nbrs:
            d[i][j] = min(d[i][j], w)
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


@pytest.mark.parametrize("seed", range(6))
def test_matches_floyd_warshall_on_small_grids(seed):
    n = 12
    ds = small_grid(n, seed)
    text = random_links(ds, n, drop=0.35, seed=seed)
    graph = build_graph(ds, text)
    d = all_pairs(ds, text)
    rng = random.Random(100 + seed)
    for _ in range(25):
        lat, lon = rng.random(), rng.random()
        cat = rng.choice(CATS)
        rad = rng.choice([0.2, 0.4, 0.7, 2.0])
        got = [ds.ids[h.index] for h in search(ds, graph, lat, lon, cat, rad, 10)[0]]
        assert got == rank(ds, d[nearest_ref(ds, lat, lon)], lat, lon, cat, rad, 10)


def exhaustive_dijkstra(adj, src):
    dist = [math.inf] * len(adj)
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
    return dist


@pytest.fixture(scope="module")
def real():
    return Dataset.from_csv(os.path.join(ROOT, "data", "locations.csv"))


def check_against_exhaustive(real, text, queries=40, seed=7):
    graph = build_graph(real, text)
    adj = reference_adjacency(real, text)
    rng = random.Random(seed)
    for _ in range(queries):
        lat, lon = rng.random(), rng.random()
        cat = rng.choice(real.categories)
        rad = rng.choice([0.05, 0.1, 0.2, 0.5, 1.5])
        got = [real.ids[h.index] for h in search(real, graph, lat, lon, cat, rad, 10)[0]]
        dist = exhaustive_dijkstra(adj, nearest_ref(real, lat, lon))
        assert got == rank(real, dist, lat, lon, cat, rad, 10)


@pytest.mark.parametrize("drop", [0.0, 0.25, 0.45])
def test_early_stop_matches_exhaustive_on_real_data(real, drop):
    check_against_exhaustive(real, random_links(real, 100, drop=drop, seed=int(drop * 100)))


def test_provided_link_file(real):
    with open(os.path.join(ROOT, "links", "link.txt")) as fh:
        text = fh.read()
    g = build_graph(real, text)
    assert g.link_format == "coordinates"
    assert g.edges == 14800 and g.unknown_endpoints == 0 and g.snapped_endpoints == 0
    check_against_exhaustive(real, text, queries=60, seed=11)


def test_longitude_comes_first(real):
    # Road from (lat=0, lon=0) [ID 1] to (lat=0, lon=1/99) [ID 2]; written lon-first.
    g = build_graph(real, "0.000000 0.000000 0.010101 0.000000\n")
    assert [real.ids[j] for j, _ in g.adj[real.index_of[1]]] == [2]
    # Road from (lat=0.5051, lon=0) [ID 5001] to (lat=0.5152, lon=0) [ID 5101].
    g = build_graph(real, "0.000000 0.505051 0.000000 0.515152\n")
    assert [real.ids[j] for j, _ in g.adj[real.index_of[5001]]] == [5101]


def test_slightly_off_coordinates_are_snapped(real):
    g = build_graph(real, "0.000004 0.0 0.01010 0.0\n0.0 0.0 5.0 5.0\n")
    assert g.edges == 1 and g.snapped_endpoints == 2 and g.unknown_endpoints == 1


def test_id_pair_format_still_supported(real):
    one = "1 2\n2 3\n1 101\n"
    zero = "0 1\n1 2\n0 100\n"
    g1, g0 = build_graph(real, one), build_graph(real, zero)
    assert g1.link_format == g0.link_format == "ids"
    assert g0.index_base == 0 and g1.index_base == 1
    assert sorted(g0.adj[0]) == sorted(g1.adj[0])
    coords = build_graph(real, "0 0 0.010101 0\n0.010101 0 0.020202 0\n0 0 0 0.010101\n")
    assert sorted(coords.adj[0]) == sorted(g1.adj[0])


def test_parser_tolerates_noise():
    fmt, links, ignored = parse_links(
        "lonA latA lonB latB\n0.1 0.2 0.3 0.4\n0.1,0.2,0.3,0.4\n0.1\t0.2\t0.3\t0.4\n\n# c\n1 2\n")
    assert fmt == "coordinates"
    assert links == [((0.2, 0.1), (0.4, 0.3))] * 3
    assert ignored == 2  # header line + the stray id pair


def test_nearest_snaps_to_grid(real):
    i = real.nearest(0.5051, 0.4949)  # row 50, col 49
    assert real.ids[i] == 50 * 100 + 49 + 1
    assert real.ids[real.nearest(-5, -5)] == 1
    assert real.ids[real.nearest(9, 9)] == 10000


def test_unreachable_candidates_are_excluded(real):
    # Only a tiny island around ID 1 is connected: IDs 1-2-3 and 1-101.
    graph = build_graph(real, "0 0 0.010101 0\n0.010101 0 0.020202 0\n0 0 0 0.010101\n")
    hits, _ = search(real, graph, 0.0, 0.0, None, 1.0, 10)
    assert sorted(real.ids[h.index] for h in hits) == [1, 2, 3, 101]


def test_default_graph_is_full_grid(real):
    g = GraphCache(real).default
    assert g.edges == 2 * 100 * 99
