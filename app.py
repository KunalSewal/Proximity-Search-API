"""
Proximity Search API

    GET/POST  /search/   fields: lat, long, cat, rad, link
    GET       /health
    GET       /

`link` is the road-linkage txt file. Each line is one road between two
neighbouring grid points:

    Longitude_A Latitude_A Longitude_B Latitude_B

(a plain "ID_A ID_B" layout is also recognised). It can be supplied as
  * a multipart file upload            ->  -F "link=@link.txt"
  * raw text in the field              ->  link="0.0 0.0 0.010101 0.0\n..."
  * an http(s) URL to the txt file     ->  link=http://host/link.txt
  * the name of a file in ./links/     ->  link=link.txt
If no link info is sent, every grid neighbour is assumed to be connected.
"""

from __future__ import annotations

import math
import os
import time
import urllib.request

from flask import Flask, jsonify, request

from engine import Dataset, GraphCache, search

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.environ.get("LOCATIONS_CSV", os.path.join(BASE_DIR, "data", "locations.csv"))
LINKS_DIR = os.environ.get("LINKS_DIR", os.path.join(BASE_DIR, "links"))
MAX_URL_BYTES = 64 * 1024 * 1024

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024
app.json.sort_keys = False

DATASET = Dataset.from_csv(DATA_PATH)
GRAPHS = GraphCache(DATASET)

ALIASES = {
    "lat": ("lat", "latitude"),
    "long": ("long", "lon", "lng", "longitude"),
    "cat": ("cat", "category"),
    "rad": ("rad", "radius"),
    "link": ("link", "links", "linkage"),
    "k": ("k",),
}


class BadRequest(Exception):
    pass


def _field(name):
    """Look a field up in query string, form body or JSON body (any alias)."""
    body = request.get_json(silent=True) if request.is_json else None
    for key in ALIASES[name]:
        if key in request.values and request.values[key] != "":
            return request.values[key]
        if isinstance(body, dict) and body.get(key) not in (None, ""):
            return body[key]
    return None


def _float(name, required=True, default=None):
    raw = _field(name)
    if raw is None:
        if required:
            raise BadRequest(f"missing required field '{name}'")
        return default
    try:
        val = float(raw)
    except (TypeError, ValueError):
        raise BadRequest(f"field '{name}' must be a number, got {raw!r}")
    if math.isnan(val):
        raise BadRequest(f"field '{name}' must be a number")
    return val


def _read_link_text():
    """Return (text or None, how it was supplied)."""
    for key in ALIASES["link"]:
        f = request.files.get(key)
        if f is not None:
            return f.read().decode("utf-8", "replace"), f"upload:{f.filename or key}"
    if len(request.files) == 1:  # a single file under some other field name
        f = next(iter(request.files.values()))
        return f.read().decode("utf-8", "replace"), f"upload:{f.filename}"

    raw = _field("link")
    if raw is None:
        if request.mimetype == "text/plain" and request.data:
            return request.get_data(as_text=True), "raw-body"
        return None, "none (full grid assumed)"
    raw = str(raw)
    stripped = raw.strip()

    if stripped.lower().startswith(("http://", "https://")):
        try:
            with urllib.request.urlopen(stripped, timeout=20) as resp:
                data = resp.read(MAX_URL_BYTES + 1)
        except Exception as exc:  # noqa: BLE001
            raise BadRequest(f"could not download link file from URL: {exc}")
        if len(data) > MAX_URL_BYTES:
            raise BadRequest("link file at URL is too large")
        return data.decode("utf-8", "replace"), "url"

    if "\n" not in stripped:
        candidate = os.path.join(LINKS_DIR, os.path.basename(stripped))
        if os.path.isfile(candidate):
            with open(candidate, encoding="utf-8", errors="replace") as fh:
                return fh.read(), f"server-file:{os.path.basename(stripped)}"

    return raw.replace("\\n", "\n"), "inline-text"


@app.errorhandler(BadRequest)
def _bad_request(err):
    return jsonify({"error": str(err)}), 400


@app.errorhandler(413)
def _too_large(_err):
    return jsonify({"error": "request too large (max 64 MB)"}), 413


@app.route("/search", methods=["GET", "POST"])
@app.route("/search/", methods=["GET", "POST"])
def search_endpoint():
    t0 = time.perf_counter()
    lat = _float("lat")
    lon = _float("long")
    rad = _float("rad", required=False, default=math.inf)
    if rad < 0:
        raise BadRequest("field 'rad' must be >= 0")
    k = int(_float("k", required=False, default=10))
    if not 1 <= k <= 1000:
        raise BadRequest("field 'k' must be between 1 and 1000")

    cat = _field("cat")
    cat = str(cat).strip().lower() if cat is not None else None
    if cat in ("", "any", "all", "*"):
        cat = None
    if cat is not None and cat not in DATASET.by_category:
        raise BadRequest(f"unknown category {cat!r}; valid: {DATASET.categories}")

    link_text, link_source = _read_link_text()
    try:
        graph = GRAPHS.get(link_text)
    except ValueError as exc:
        raise BadRequest(str(exc))

    hits, info = search(DATASET, graph, lat, lon, cat, rad, k)
    ds = DATASET
    src = info["source_index"]
    results = [
        {
            "rank": r,
            "id": ds.ids[h.index],
            "lat": ds.lat[h.index],
            "long": ds.lon[h.index],
            "category": ds.cat[h.index],
            "grid_distance": round(h.grid_distance, 6),
            "euclidean_distance": round(h.euclidean_distance, 6),
            "hops": h.hops,
        }
        for r, h in enumerate(hits, 1)
    ]
    payload = {
        "ids": [r["id"] for r in results],
        "count": len(results),
        "results": results,
        "query": {"lat": lat, "long": lon, "cat": cat, "rad": None if math.isinf(rad) else rad, "k": k},
        "meta": {
            "start_node": {"id": ds.ids[src], "lat": ds.lat[src], "long": ds.lon[src]},
            "link_source": link_source,
            "graph": graph.source,
            "edges": graph.edges,
            "link_format": graph.link_format,
            "link_lines_ignored": graph.ignored_lines,
            "link_endpoints_snapped": graph.snapped_endpoints,
            "link_endpoints_unknown": graph.unknown_endpoints,
            "candidates_in_radius": info["candidates_in_radius"],
            "nodes_settled": info["settled_nodes"],
            "time_ms": round((time.perf_counter() - t0) * 1000, 2),
        },
    }
    if len(results) < k:
        payload["warning"] = (f"only {len(results)} matching location(s) inside the radius are "
                              f"reachable through the road network")
    return jsonify(payload)


@app.get("/health")
def health():
    return jsonify({"status": "ok", "locations": DATASET.n, "categories": DATASET.categories,
                    "grid": None if not DATASET.grid_shape else DATASET.grid_shape[:2]})


@app.get("/")
def index():
    return jsonify({
        "service": "Proximity Search API",
        "usage": "GET or POST /search/ with fields lat, long, cat, rad, link",
        "link": "txt with lines 'Longitude_A Latitude_A Longitude_B Latitude_B'; send as multipart file "
                "upload, inline text, http(s) URL, or filename in ./links/",
        "example": "curl -F lat=0.5 -F long=0.5 -F cat=cafe -F rad=0.2 -F link=@link.txt http://HOST:PORT/search/",
        "categories": DATASET.categories,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
