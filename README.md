# Proximity Search API

Returns the 10 closest locations of a given category, where **closest** means the shortest
travel distance over the road network described by a link file, and the results must lie
**within a circular (Euclidean) radius** of the current position.

Dataset: `data/locations.csv`, 10,000 locations (`ID, Latitude, Longitude, Category`) on a
100 × 100 lattice over the unit square (spacing 1/99), with 8 categories of 1,250 locations each.

## Endpoint

`GET` or `POST` `/search/` (also `/search`)

| field  | meaning                                                                    |
|--------|----------------------------------------------------------------------------|
| `lat`  | current latitude                                                           |
| `long` | current longitude                                                          |
| `cat`  | category (`bank, cafe, hospital, park, pharmacy, restaurant, school, store`; case-insensitive) |
| `rad`  | search radius, as a straight-line distance in the same units as lat/long (optional, default ∞) |
| `link` | road linkage `.txt`: one `a b` pair per line, where `a`, `b` are location IDs |

`link` can be sent in any of these forms:

* a multipart file upload: `-F link=@links.txt` (a single file under any other field name also works)
* inline text in the field: `link="1 2\n2 3\n..."`
* an `http(s)://` URL that points to the txt file
* the name of a file that is already in `./links/` on the server

If you send no link information, the API assumes every lattice neighbour is connected.

### Example

```bash
curl -X POST http://10.1.75.53:8265/search/ \
  -F lat=0.5 -F long=0.5 -F cat=cafe -F rad=0.2 -F link=@links/sample_links.txt
```

```python
import requests
r = requests.post("http://10.1.75.53:8265/search/",
                  data={"lat": 0.5, "long": 0.5, "cat": "cafe", "rad": 0.2},
                  files={"link": open("links/sample_links.txt", "rb")})
print(r.json()["ids"])
```

### Response

```json
{
  "ids": [4949, 5051, 4751, 4748, 5047, 5053, 5149, 4551, 4653, 5045],
  "count": 10,
  "results": [
    {"rank": 1, "id": 4949, "lat": 0.494949, "long": 0.484848, "category": "cafe",
     "grid_distance": 0.010101, "euclidean_distance": 0.015972, "hops": 1}
  ],
  "query": {"lat": 0.5, "long": 0.5, "cat": "cafe", "rad": 0.2, "k": 10},
  "meta": {"start_node": {"id": 4950}, "link_source": "upload:sample_links.txt",
           "edges": 13870, "candidates_in_radius": 149, "nodes_settled": 64, "time_ms": 0.9}
}
```

`GET /health` returns the dataset summary.

## Method

1. **Snap the start point.** Find the location nearest to (`lat`, `long`) using a uniform
   bucket grid (spatial hash), which takes O(1) expected time. Ties go to the smaller ID.
2. **Filter by radius.** Keep locations of category `cat` whose Euclidean distance from
   (`lat`, `long`) is ≤ `rad`. Only the bucket cells that overlap the radius's bounding box
   are scanned.
3. **Build the road graph** from the link file as an undirected adjacency list. Each edge's
   weight is the Euclidean length of the road segment, so path length equals actual travel
   distance (an adjacent grid step is 1/99). Duplicate pairs and self-loops are ignored. A
   0-based link file (IDs `0..N-1`) is detected and shifted. Parsed graphs are cached
   (LRU, keyed by the SHA-256 of the file), so repeated queries with the same file skip parsing.
4. **Dijkstra with early termination** from the start node. A location counts as a result
   when it is settled and is also a radius candidate. The search stops once 10 results are
   settled and the frontier has moved past the 10th distance. Every location tied at the
   boundary distance is still collected, so tie-breaking stays deterministic.
5. **Rank** by (grid distance, Euclidean distance, ID) and return the top 10. Candidates
   that cannot be reached through the network are never returned.

On the 10k dataset, a query settles roughly 50–100 nodes and runs in about 1 ms
(about 40 ms the first time a new link file is parsed).

## Project layout

```
app.py               Flask API (input handling, response format)
engine.py            dataset, spatial index, link parsing, graph, Dijkstra search
data/locations.csv   dataset
links/               sample link files (full grid, 30% of roads removed)
tools/make_links.py  generate link files with random missing roads
tests/               correctness tests (Floyd-Warshall / exhaustive-Dijkstra references) + API tests
start.sh             create venv, install deps, run gunicorn
```

## Running

```bash
./start.sh                  # gunicorn on 0.0.0.0:8000
PORT=5000 ./start.sh        # different port
python app.py               # Flask dev server (PORT env var, default 8000)
python -m pytest -q         # tests
python tools/make_links.py --drop 0.3 --seed 7 -o links/my_links.txt
```
