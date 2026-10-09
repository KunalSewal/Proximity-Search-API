"""
Generate a sample road-linkage file for testing.

Starts from the full 4-neighbour grid (every location linked to the one above,
below, left and right) and randomly removes a fraction of the roads, mimicking
a real road network with missing links. Output uses the official layout

    Longitude_A Latitude_A Longitude_B Latitude_B

    python tools/make_links.py --drop 0.3 --seed 7 -o links/sample_links.txt
"""

import argparse
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import Dataset  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", default="data/locations.csv")
    p.add_argument("--drop", type=float, default=0.3, help="fraction of grid roads to remove")
    p.add_argument("--diagonal", type=float, default=0.0, help="fraction of diagonal roads to add")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--format", choices=["coords", "ids"], default="coords")
    p.add_argument("-o", "--out", default="links/sample_links.txt")
    a = p.parse_args()

    ds = Dataset.from_csv(a.csv)
    if not ds.grid_shape:
        sys.exit("dataset is not a full lattice")
    rows, cols, g = ds.grid_shape
    rng = random.Random(a.seed)
    lines = []
    for r in range(rows):
        for c in range(cols):
            here = g[r][c]
            for nr, nc, keep_p in ((r + 1, c, 1 - a.drop), (r, c + 1, 1 - a.drop),
                                   (r + 1, c + 1, a.diagonal), (r + 1, c - 1, a.diagonal)):
                if 0 <= nr < rows and 0 <= nc < cols and rng.random() < keep_p:
                    there = g[nr][nc]
                    if a.format == "ids":
                        lines.append(f"{ds.ids[here]} {ds.ids[there]}")
                    else:
                        lines.append(f"{ds.lon[here]:.6f} {ds.lat[here]:.6f} {ds.lon[there]:.6f} {ds.lat[there]:.6f}")
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"wrote {len(lines)} links to {a.out}")


if __name__ == "__main__":
    main()
