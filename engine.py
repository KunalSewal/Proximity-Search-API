"""
Core search engine for the Proximity Search API.

Pipeline for one query
----------------------
1. Snap the query point (lat, long) to the nearest location node
   (spatial bucket index, O(1) expected).
2. Candidate filter: locations of the requested category whose straight-line
   (Euclidean) distance from the query point is <= rad   -> "in radius".
3. Run Dijkstra over the road graph defined by the link file, starting at the
   snapped node. Edge weight = Euclidean length of the road segment, so the
   path length is the real traversal ("grid") distance.
4. Stop as soon as k candidates are settled and the frontier has moved past the
   k-th distance (all ties at the boundary are still collected).
5. Rank by (grid distance, euclidean distance, id) and return the top k.
"""

from __future__ import annotations

import csv
import hashlib
import heapq
import math
import re
from collections import OrderedDict
from dataclasses import dataclass, field

EPS = 1e-9


# --------------------------------------------------------------------------- #
# Dataset + spatial index
# --------------------------------------------------------------------------- #
class Dataset:
    """All locations, stored column-wise by internal index 0..N-1."""

    def __init__(self, ids, lats, lons, cats):
        self.ids = ids
        self.lat = lats
        self.lon = lons
        self.cat = cats
        self.n = len(ids)
        self.index_of = {loc_id: i for i, loc_id in enumerate(ids)}
        self.coord_index = {(round(la, 6), round(lo, 6)): i for i, (la, lo) in enumerate(zip(lats, lons))}
        self.categories = sorted(set(cats))
        self.by_category: dict[str, list[int]] = {}
        for i, c in enumerate(cats):
            self.by_category.setdefault(c, []).append(i)
        self._build_buckets()
        self.grid_shape = self._detect_grid()

    @classmethod
    def from_csv(cls, path: str) -> "Dataset":
        ids, lats, lons, cats = [], [], [], []
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            cols = {k.strip().lower(): k for k in reader.fieldnames or []}
            c_id = cols.get("id")
            c_lat = cols.get("latitude") or cols.get("lat")
            c_lon = cols.get("longitude") or cols.get("long") or cols.get("lon")
            c_cat = cols.get("category") or cols.get("cat")
            if not all([c_id, c_lat, c_lon, c_cat]):
                raise ValueError(f"CSV must have ID, Latitude, Longitude, Category columns, got {reader.fieldnames}")
            for row in reader:
                ids.append(int(float(row[c_id])))
                lats.append(float(row[c_lat]))
                lons.append(float(row[c_lon]))
                cats.append(row[c_cat].strip().lower())
        return cls(ids, lats, lons, cats)

    # Uniform bucket grid ("spatial hashing"): each cell holds ~1 point on average.
    def _build_buckets(self):
        self.min_lat, self.max_lat = min(self.lat), max(self.lat)
        self.min_lon, self.max_lon = min(self.lon), max(self.lon)
        span = max(self.max_lat - self.min_lat, self.max_lon - self.min_lon) or 1.0
        cells_per_side = max(1, int(math.sqrt(self.n)))
        self.cell = span / cells_per_side
        self.buckets: dict[tuple[int, int], list[int]] = {}
        for i in range(self.n):
            self.buckets.setdefault(self._cell_of(self.lat[i], self.lon[i]), []).append(i)

    def _cell_of(self, lat, lon):
        return (int((lat - self.min_lat) // self.cell), int((lon - self.min_lon) // self.cell))

    def nearest(self, lat: float, lon: float) -> int:
        """Index of the location closest (Euclidean) to (lat, lon); ties -> smaller ID."""
        def key(i):
            return round(math.hypot(self.lat[i] - lat, self.lon[i] - lon), 12), self.ids[i]

        ci, cj = self._cell_of(lat, lon)
        best_key = None
        # Expand square rings of cells around the query cell; only each ring's perimeter is visited.
        for ring in range(8):
            if ring == 0:
                cells = [(ci, cj)]
            else:
                cells = [(ci + d, cj + e) for d in (-ring, ring) for e in range(-ring, ring + 1)]
                cells += [(ci + d, cj + e) for e in (-ring, ring) for d in range(-ring + 1, ring)]
            for cell in cells:
                for i in self.buckets.get(cell, ()):
                    k = key(i)
                    if best_key is None or k < best_key:
                        best_key = k + (i,)
            # Anything in ring r+1 or beyond is at least r*cell away.
            if best_key is not None and best_key[0] < ring * self.cell:
                return best_key[2]
        # Query far from the data (or sparse data): plain linear scan.
        return min(range(self.n), key=key)

    def within_radius(self, lat: float, lon: float, rad: float, category: str | None) -> dict[int, float]:
        """{index: euclidean distance} for points of `category` within `rad` of (lat, lon)."""
        out = {}
        if math.isinf(rad):
            pool = self.by_category.get(category, []) if category else range(self.n)
            for i in pool:
                out[i] = math.hypot(self.lat[i] - lat, self.lon[i] - lon)
            return out
        lo = self._cell_of(max(lat - rad, self.min_lat), max(lon - rad, self.min_lon))
        hi = self._cell_of(min(lat + rad, self.max_lat), min(lon + rad, self.max_lon))
        for a in range(lo[0], hi[0] + 1):
            for b in range(lo[1], hi[1] + 1):
                for i in self.buckets.get((a, b), ()):
                    if category and self.cat[i] != category:
                        continue
                    d = math.hypot(self.lat[i] - lat, self.lon[i] - lon)
                    if d <= rad + EPS:
                        out[i] = d
        return out

    def _detect_grid(self):
        """If the points form a full rows x cols lattice, return (rows, cols, index_grid)."""
        lat_vals = sorted({round(v, 9) for v in self.lat})
        lon_vals = sorted({round(v, 9) for v in self.lon})
        if len(lat_vals) * len(lon_vals) != self.n:
            return None
        r_of = {v: r for r, v in enumerate(lat_vals)}
        c_of = {v: c for c, v in enumerate(lon_vals)}
        grid = [[-1] * len(lon_vals) for _ in lat_vals]
        for i in range(self.n):
            grid[r_of[round(self.lat[i], 9)]][c_of[round(self.lon[i], 9)]] = i
        if any(v < 0 for row in grid for v in row):
            return None
        return len(lat_vals), len(lon_vals), grid

    def edge_length(self, i: int, j: int) -> float:
        return math.hypot(self.lat[i] - self.lat[j], self.lon[i] - self.lon[j])


# --------------------------------------------------------------------------- #
# Road graph (from link file)
# --------------------------------------------------------------------------- #
_TOKEN_SPLIT = re.compile(r"[\s,;|]+")


@dataclass
class Graph:
    adj: list[list[tuple[int, float]]]
    edges: int
    link_format: str = "none"
    ignored_lines: int = 0
    unknown_endpoints: int = 0
    snapped_endpoints: int = 0
    index_base: int = 1
    source: str = "link-file"
    fingerprint: str = ""
    extra: dict = field(default_factory=dict)


def parse_links(text: str):
    """Parse a link file. Two layouts are recognised (decided per file, by majority):

      coordinates:  Longitude_A Latitude_A Longitude_B Latitude_B   (official format)
      ids:          ID_A ID_B

    Commas/tabs/semicolons as separators, headers, comments and blank lines are tolerated.
    Returns (format, links, ignored_lines) where each link is
      ((lat_a, lon_a), (lat_b, lon_b))   for "coordinates"
      (id_a, id_b)                       for "ids"
    """
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        nums = []
        for tok in _TOKEN_SPLIT.split(line):
            if tok:
                try:
                    nums.append(float(tok))
                except ValueError:
                    pass
        rows.append(nums)

    n_coord = sum(1 for r in rows if len(r) >= 4)
    n_ids = sum(1 for r in rows if len(r) in (2, 3) and r[0].is_integer() and r[1].is_integer())
    fmt = "coordinates" if n_coord >= n_ids else "ids"

    links, ignored = [], 0
    for r in rows:
        if fmt == "coordinates" and len(r) >= 4:
            lon_a, lat_a, lon_b, lat_b = r[:4]
            links.append(((lat_a, lon_a), (lat_b, lon_b)))
        elif fmt == "ids" and len(r) >= 2 and r[0].is_integer() and r[1].is_integer():
            links.append((int(r[0]), int(r[1])))
        else:
            ignored += 1
    return fmt, links, ignored


def build_graph(ds: Dataset, text: str) -> Graph:
    fmt, links, ignored = parse_links(text)
    if not links:
        raise ValueError("link file contained no valid links; expected lines like "
                         "'Longitude_A Latitude_A Longitude_B Latitude_B'")

    unknown = snapped = 0
    base = 1
    endpoints: list[tuple[int | None, int | None]] = []
    if fmt == "coordinates":
        def node(lat, lon):
            nonlocal unknown, snapped
            i = ds.coord_index.get((round(lat, 6), round(lon, 6)))
            if i is not None:
                return i
            i = ds.nearest(lat, lon)  # tolerate rounding differences in the file
            if math.hypot(ds.lat[i] - lat, ds.lon[i] - lon) <= ds.cell / 2:
                snapped += 1
                return i
            unknown += 1
            return None
        endpoints = [(node(*a), node(*b)) for a, b in links]
    else:
        # IDs in the CSV are 1-based. If the link file uses 0..N-1 instead, shift it.
        ids_seen = {v for p in links for v in p}
        if 0 in ids_seen and 0 not in ds.index_of and max(ids_seen) + 1 in ds.index_of:
            base = 0
        for a, b in links:
            ia, ib = ds.index_of.get(a + 1 - base), ds.index_of.get(b + 1 - base)
            unknown += (ia is None) + (ib is None)
            endpoints.append((ia, ib))

    adj: list[list[tuple[int, float]]] = [[] for _ in range(ds.n)]
    seen = set()
    for ia, ib in endpoints:
        if ia is None or ib is None or ia == ib:
            continue
        key = (ia, ib) if ia < ib else (ib, ia)
        if key in seen:
            continue
        seen.add(key)
        w = ds.edge_length(ia, ib)
        adj[ia].append((ib, w))  # roads are two-way
        adj[ib].append((ia, w))
    return Graph(adj=adj, edges=len(seen), link_format=fmt, ignored_lines=ignored,
                 unknown_endpoints=unknown, snapped_endpoints=snapped, index_base=base,
                 source="link-file")


def build_full_grid_graph(ds: Dataset) -> Graph:
    """Fallback when no link file is supplied: every lattice neighbour is connected
    (4-neighbourhood). If the data is not a lattice, an empty graph is returned and
    the engine falls back to Euclidean ranking."""
    adj: list[list[tuple[int, float]]] = [[] for _ in range(ds.n)]
    edges = 0
    if ds.grid_shape:
        rows, cols, g = ds.grid_shape
        for r in range(rows):
            for c in range(cols):
                i = g[r][c]
                for nr, nc in ((r + 1, c), (r, c + 1)):
                    if nr < rows and nc < cols:
                        j = g[nr][nc]
                        w = ds.edge_length(i, j)
                        adj[i].append((j, w))
                        adj[j].append((i, w))
                        edges += 1
    return Graph(adj=adj, edges=edges, source="full-grid-default" if edges else "euclidean-fallback")


class GraphCache:
    """Small LRU so the same link file is parsed only once."""

    def __init__(self, ds: Dataset, size: int = 16):
        self.ds = ds
        self.size = size
        self._cache: OrderedDict[str, Graph] = OrderedDict()
        self.default = build_full_grid_graph(ds)

    def get(self, text: str | None) -> Graph:
        if text is None or not text.strip():
            return self.default
        fp = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
        g = self._cache.get(fp)
        if g is not None:
            self._cache.move_to_end(fp)
            return g
        g = build_graph(self.ds, text)
        g.fingerprint = fp[:12]
        self._cache[fp] = g
        if len(self._cache) > self.size:
            self._cache.popitem(last=False)
        return g


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #
@dataclass
class Hit:
    index: int
    grid_distance: float
    euclidean_distance: float
    hops: int


class _LazyCandidates:
    """Radius/category test done per node as Dijkstra settles it. Used when the radius
    circle holds so many points that listing them up front would dominate the query."""

    def __init__(self, ds: Dataset, lat: float, lon: float, rad: float, category: str | None):
        self.ds, self.lat, self.lon, self.rad, self.cat = ds, lat, lon, rad, category

    def __contains__(self, i: int) -> bool:
        ds = self.ds
        if self.cat and ds.cat[i] != self.cat:
            return False
        return math.hypot(ds.lat[i] - self.lat, ds.lon[i] - self.lon) <= self.rad + EPS

    def __getitem__(self, i: int) -> float:
        return math.hypot(self.ds.lat[i] - self.lat, self.ds.lon[i] - self.lon)



EAGER_CELL_LIMIT = 4096


def search(ds: Dataset, graph: Graph, lat: float, lon: float, category: str | None,
           rad: float, k: int = 10, lazy: bool | None = None) -> tuple[list[Hit], dict]:
    source = ds.nearest(lat, lon)
    euclid_only = graph.edges == 0 and graph.source == "euclidean-fallback"
    if lazy is None:
        # Bucket cells covered by the radius' bounding box ~ points to scan eagerly.
        side = min(2 * rad, ds.max_lat - ds.min_lat + ds.cell, ds.max_lon - ds.min_lon + ds.cell)
        lazy = not euclid_only and (side / ds.cell + 1) ** 2 > EAGER_CELL_LIMIT
    if lazy:
        candidates = _LazyCandidates(ds, lat, lon, rad, category)
    else:
        candidates = ds.within_radius(lat, lon, rad, category)
    info = {"source_index": source, "candidates_in_radius": None if lazy else len(candidates),
            "settled_nodes": 0, "mode": "lazy" if lazy else "eager"}

    if not lazy and not candidates:
        return [], info

    if euclid_only:
        hits = [Hit(i, d, d, 0) for i, d in candidates.items()]
        hits.sort(key=lambda h: (h.euclidean_distance, ds.ids[h.index]))
        return hits[:k], info

    total = None if lazy else len(candidates)  # unknown up front in lazy mode
    adj = graph.adj
    dist = {source: 0.0}
    hops = {source: 0}
    done = set()
    heap = [(0.0, source)]
    found: list[Hit] = []
    kth = math.inf
    while heap:
        d, u = heapq.heappop(heap)
        if u in done:
            continue
        if d > kth + EPS:  # everything left is strictly farther than the k-th result
            break
        done.add(u)
        if u in candidates:
            found.append(Hit(u, d, candidates[u], hops[u]))
            if len(found) == k:
                kth = d
            if len(found) == total:  # every in-radius candidate already found
                break
        for v, w in adj[u]:
            nd = d + w
            if v not in done and nd < dist.get(v, math.inf) - EPS:
                dist[v] = nd
                hops[v] = hops[u] + 1
                heapq.heappush(heap, (nd, v))
    info["settled_nodes"] = len(done)
    info["reachable_candidates_seen"] = len(found)

    found.sort(key=lambda h: (round(h.grid_distance, 9), round(h.euclidean_distance, 12), ds.ids[h.index]))
    return found[:k], info
