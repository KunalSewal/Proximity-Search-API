"""Compare container API (via gateway) with the engine run natively on the host."""
import json, random, sys, time, urllib.request, uuid
sys.path.insert(0, ".")
from engine import Dataset, GraphCache, search

ds = Dataset.from_csv("data/locations.csv"); graphs = GraphCache(ds)
link = open("links/link.txt", encoding="utf-8").read(); g = graphs.get(link)
rng = random.Random(42); cats = ds.categories
same = 0; N = 200; lat_ms = []
for _ in range(N):
    q = dict(lat=round(rng.random(), 4), long=round(rng.random(), 4), cat=rng.choice(cats), rad=round(rng.uniform(0.05, 0.4), 3))
    native = [ds.ids[h.index] for h in search(ds, g, q["lat"], q["long"], q["cat"], q["rad"], 10)[0]]
    url = "http://localhost:8080/search/?" + "&".join(f"{k}={v}" for k, v in q.items()) + "&link=link.txt"
    t = time.perf_counter(); d = json.load(urllib.request.urlopen(url)); lat_ms.append((time.perf_counter() - t) * 1000)
    same += d["ids"] == native
lat_ms.sort()
print(f"queries: {N}   identical top-10 lists (container vs native): {same}/{N}")
print(f"round-trip via gateway: median {lat_ms[N//2]:.1f} ms, p95 {lat_ms[int(N*.95)]:.1f} ms")
