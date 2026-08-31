#!/usr/bin/env python3
"""Embed TAZ geometry + 2020 zonal data into Haifa/population_density_map.html.

Reads  Haifa/Taz_North/TAZ North.shp  (Israel TM Grid, EPSG:2039)
and    Haifa/Data/Zonal_2020.csv      (TAZ_ID, POPULATION, AREA ...),
joins on TAZ_NUMBER = TAZ_ID, simplifies rings (Douglas-Peucker, 12 m),
computes density = POPULATION / AREA and septile class breaks over
inhabited zones, and rewrites the `const DATA = ...` line in the HTML.

Requires: pyshp, pyproj   (pip install pyshp pyproj)
"""
import csv
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHP = ROOT / "Haifa/Taz_North/TAZ North.shp"
CSV = ROOT / "Haifa/Data/Zonal_2020.csv"
HTML = ROOT / "Haifa/population_density_map.html"
TOLERANCE_M = 12.0
N_CLASSES = 7

# Reference cities for orientation labels (name, lon, lat — WGS84).
CITIES = [
    ("Haifa", 34.9896, 32.7940), ("Nazareth", 35.3035, 32.6996),
    ("Akko", 35.0818, 32.9281), ("Nahariya", 35.0946, 33.0058),
    ("Karmiel", 35.2951, 32.9186), ("Tiberias", 35.5312, 32.7922),
    ("Safed", 35.4953, 32.9646), ("Afula", 35.2898, 32.6100),
    ("Hadera", 34.9196, 32.4340), ("Kiryat Shmona", 35.5697, 33.2075),
]


def simplify(points, tol):
    """Iterative Douglas-Peucker on a list of (x, y) tuples."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        ax, ay = points[i]
        bx, by = points[j]
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        dmax, imax = -1.0, -1
        for k in range(i + 1, j):
            px, py = points[k]
            if seg2 == 0:
                d2 = (px - ax) ** 2 + (py - ay) ** 2
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
                d2 = (px - (ax + t * dx)) ** 2 + (py - (ay + t * dy)) ** 2
            if d2 > dmax:
                dmax, imax = d2, k
        if imax >= 0 and dmax > tol * tol:
            keep[imax] = True
            stack.append((i, imax))
            stack.append((imax, j))
    return [p for p, k in zip(points, keep) if k]


def quantile(sorted_vals, q):
    idx = q * (len(sorted_vals) - 1)
    lo = math.floor(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo)


def nice(v):
    """Round a break to two significant digits."""
    if v <= 0:
        return 0
    mag = 10 ** (len(str(int(v))) - 2) if v >= 10 else 1
    return round(v / mag) * mag


def main():
    import shapefile
    from pyproj import Transformer

    with open(CSV, encoding="utf-8", errors="replace") as f:
        rows = {int(float(r["TAZ_ID"])): r for r in csv.DictReader(f)}

    sf = shapefile.Reader(str(SHP))
    zones = []
    for shp, rec in zip(sf.shapes(), sf.records()):
        taz = rec["TAZ_NUMBER"]
        r = rows[taz]
        pop, area = float(r["POPULATION"]), float(r["AREA"])
        parts = list(shp.parts) + [len(shp.points)]
        rings = []
        for a, b in zip(parts[:-1], parts[1:]):
            s = simplify(shp.points[a:b], TOLERANCE_M)
            if len(s) >= 4:
                rings.append([[round(x), round(y)] for x, y in s])
        zones.append({
            "t": taz, "p": round(pop), "a": area,
            "d": round(pop / area, 1) if area > 0 else 0.0,
            "sz": rec["SUPERZONE"], "n": (rec["NAFA"] or "").strip(),
            "g": rings,
        })

    nonzero = sorted(z["d"] for z in zones if z["d"] > 0)
    breaks = [nice(quantile(nonzero, i / N_CLASSES)) for i in range(1, N_CLASSES)]

    tr = Transformer.from_crs("EPSG:4326", "EPSG:2039", always_xy=True)
    cities = []
    for name, lon, lat in CITIES:
        x, y = tr.transform(lon, lat)
        cities.append({"n": name, "x": round(x), "y": round(y)})

    xmin, ymin, xmax, ymax = sf.bbox
    data = {
        "bbox": [round(xmin), round(ymin), round(xmax), round(ymax)],
        "breaks": breaks, "cities": cities, "zones": zones,
    }
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    html = HTML.read_text(encoding="utf-8")
    html, n = re.subn(
        r"const DATA = .*?;\n",
        "const DATA = /*__DATA_JSON__*/" + blob + ";\n",
        html, count=1, flags=re.S,
    )
    if n != 1:
        raise SystemExit("could not find the `const DATA = ...;` line in the HTML")
    HTML.write_text(html, encoding="utf-8")
    print(f"embedded {len(zones)} zones ({len(blob) // 1024} KB), breaks: {breaks}")


if __name__ == "__main__":
    main()
