"""Convert the Rwanda district shapefile into a small GeoJSON file for the web map.

The shapefile only has the shapes (no attribute table), so each polygon is
matched to a district name by comparing its position and its area with
reference values. Run it from the project root:

    python tools/build_geojson.py

Output:
    static/geo/rwanda_districts.geojson   (used by the Leaflet map)
    locations/data/districts.json         (used to create provinces and districts)
"""
import json
from pathlib import Path

import numpy as np
import shapefile                      # pip install pyshp
from pyproj import Transformer        # pip install pyproj
from scipy.optimize import linear_sum_assignment
from shapely.geometry import Polygon, mapping

ROOT = Path(__file__).resolve().parent.parent
SHP = ROOT / "tools" / "District.shp"

# The shapefile uses the Rwanda Transverse Mercator grid.
RTM = ("+proj=tmerc +lat_0=0 +lon_0=30 +k=0.9999 +x_0=500000 "
       "+y_0=5000000 +ellps=WGS84 +units=m +no_defs")

# province, approximate latitude, approximate longitude, approximate area (km2)
REFERENCE = {
    "Nyarugenge": ("Kigali City", -1.97, 30.04, 134), "Gasabo": ("Kigali City", -1.88, 30.13, 429),
    "Kicukiro": ("Kigali City", -2.01, 30.10, 167),
    "Burera": ("Northern", -1.47, 29.83, 644), "Gakenke": ("Northern", -1.69, 29.78, 704),
    "Gicumbi": ("Northern", -1.58, 30.10, 829), "Musanze": ("Northern", -1.50, 29.63, 530),
    "Rulindo": ("Northern", -1.75, 30.00, 567),
    "Gisagara": ("Southern", -2.60, 29.84, 679), "Huye": ("Southern", -2.60, 29.74, 581),
    "Kamonyi": ("Southern", -2.00, 29.90, 656), "Muhanga": ("Southern", -2.08, 29.75, 647),
    "Nyamagabe": ("Southern", -2.47, 29.40, 1090), "Nyanza": ("Southern", -2.35, 29.75, 675),
    "Nyaruguru": ("Southern", -2.72, 29.55, 1011), "Ruhango": ("Southern", -2.22, 29.78, 626),
    "Bugesera": ("Eastern", -2.23, 30.17, 1337), "Gatsibo": ("Eastern", -1.65, 30.45, 1585),
    "Kayonza": ("Eastern", -1.87, 30.62, 1935), "Kirehe": ("Eastern", -2.21, 30.70, 1205),
    "Ngoma": ("Eastern", -2.17, 30.47, 868), "Nyagatare": ("Eastern", -1.30, 30.33, 1741),
    "Rwamagana": ("Eastern", -1.95, 30.43, 682),
    "Karongi": ("Western", -2.17, 29.38, 989), "Ngororero": ("Western", -1.88, 29.60, 683),
    "Nyabihu": ("Western", -1.65, 29.50, 531), "Nyamasheke": ("Western", -2.35, 29.15, 1195),
    "Rubavu": ("Western", -1.69, 29.30, 388), "Rusizi": ("Western", -2.60, 29.05, 970),
    "Rutsiro": ("Western", -1.95, 29.35, 1157),
}


def ring_area(ring):
    return abs(sum(ring[i][0] * ring[(i + 1) % len(ring)][1] - ring[(i + 1) % len(ring)][0] * ring[i][1]
                   for i in range(len(ring)))) / 2


def main():
    reader = shapefile.Reader(str(SHP))
    to_wgs84 = Transformer.from_crs(RTM, "EPSG:4326", always_xy=True)
    polygons = []
    for shape in reader.shapes():
        parts = list(shape.parts) + [len(shape.points)]
        rings = [shape.points[parts[i]:parts[i + 1]] for i in range(len(parts) - 1)]
        area_km2 = sum(ring_area(r) for r in rings) / 1e6
        lonlat = [to_wgs84.transform(x, y) for x, y in rings[0]]
        polygons.append((Polygon(lonlat), area_km2))

    names = list(REFERENCE)
    cost = np.zeros((len(polygons), len(names)))
    for i, (poly, area) in enumerate(polygons):
        c = poly.centroid
        for j, name in enumerate(names):
            _, lat, lon, ref_area = REFERENCE[name]
            km = ((c.y - lat) ** 2 + (c.x - lon) ** 2) ** 0.5 * 111
            cost[i, j] = km + 0.02 * abs(area - ref_area)
    rows, cols = linear_sum_assignment(cost)

    features, table = [], []
    for i, j in zip(rows, cols):
        name = names[j]
        province = REFERENCE[name][0]
        poly = polygons[i][0].simplify(0.0008, preserve_topology=True)
        coords = json.loads(json.dumps(mapping(poly)))
        coords["coordinates"] = [[[round(x, 5), round(y, 5)] for x, y in ring] for ring in coords["coordinates"]]
        features.append({"type": "Feature", "properties": {"name": name, "province": province}, "geometry": coords})
        c = polygons[i][0].centroid
        table.append({"name": name, "province": province, "latitude": round(c.y, 6), "longitude": round(c.x, 6)})

    features.sort(key=lambda f: f["properties"]["name"])
    table.sort(key=lambda r: (r["province"], r["name"]))
    (ROOT / "static" / "geo").mkdir(parents=True, exist_ok=True)
    (ROOT / "static/geo/rwanda_districts.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":")))
    (ROOT / "locations/data/districts.json").write_text(json.dumps(table, indent=2))
    print(f"{len(features)} districts written")


if __name__ == "__main__":
    main()
