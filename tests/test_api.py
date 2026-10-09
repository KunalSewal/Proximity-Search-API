import io
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import app  # noqa: E402

LINKS = os.path.join(ROOT, "links", "link.txt")
Q = {"lat": "0.33", "long": "0.71", "cat": "park", "rad": "0.05"}


@pytest.fixture
def client():
    return app.test_client()


def link_text():
    with open(LINKS) as fh:
        return fh.read()


def test_multipart_upload(client):
    data = dict(Q, link=(io.BytesIO(link_text().encode()), "links.txt"))
    r = client.post("/search/", data=data, content_type="multipart/form-data")
    assert r.status_code == 200, r.json
    body = r.json
    assert body["count"] == 10 and len(body["ids"]) == 10
    assert body["meta"]["link_source"].startswith("upload")
    assert body["meta"]["link_format"] == "coordinates" and body["meta"]["edges"] == 14800
    assert all(x["category"] == "park" for x in body["results"])
    assert all(x["euclidean_distance"] <= 0.05 + 1e-9 for x in body["results"])
    d = [x["grid_distance"] for x in body["results"]]
    assert d == sorted(d)


def test_all_link_transports_agree(client):
    up = client.post("/search/", data=dict(Q, link=(io.BytesIO(link_text().encode()), "l.txt")),
                     content_type="multipart/form-data").json["ids"]
    inline = client.post("/search/", data=dict(Q, link=link_text())).json["ids"]
    by_name = client.get("/search/", query_string=dict(Q, link="link.txt")).json["ids"]
    as_json = client.post("/search/", json=dict(Q, link=link_text())).json["ids"]
    other_field = client.post("/search/", data=dict(Q, file=(io.BytesIO(link_text().encode()), "x.txt")),
                              content_type="multipart/form-data").json["ids"]
    assert up == inline == by_name == as_json == other_field


def test_without_slash_and_aliases(client):
    r = client.get("/search", query_string={"latitude": 0.5, "lon": 0.5, "category": "CAFE", "radius": 0.2})
    assert r.status_code == 200
    assert r.json["meta"]["graph"] == "full-grid-default"
    assert r.json["count"] == 10


def test_errors(client):
    assert client.get("/search/", query_string={"long": 1}).status_code == 400
    assert client.get("/search/", query_string=dict(Q, lat="abc")).status_code == 400
    assert client.get("/search/", query_string=dict(Q, cat="zoo")).status_code == 400
    assert client.get("/search/", query_string=dict(Q, rad=-1)).status_code == 400
    assert client.post("/search/", data=dict(Q, link="hello world")).status_code == 400


def test_health(client):
    assert client.get("/health").json["locations"] == 10000
