import argparse
import datetime as dt
import json
import uuid
from urllib import parse, request

from db import get_conn, init_db

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
DEFAULT_BBOX = (51.16, 6.79, 51.38, 7.15)  # Kreis Mettmann approx: s,w,n,e


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_query(south: float, west: float, north: float, east: float) -> str:
    bbox = f"({south},{west},{north},{east})"
    return f"""
[out:json][timeout:120];
(
  node[amenity=police]{bbox};
  way[amenity=police]{bbox};
  relation[amenity=police]{bbox};

  node[amenity=fire_station]{bbox};
  way[amenity=fire_station]{bbox};
  relation[amenity=fire_station]{bbox};

  node[amenity=hospital]{bbox};
  way[amenity=hospital]{bbox};
  relation[amenity=hospital]{bbox};

  way[landuse=residential]{bbox};
  relation[landuse=residential]{bbox};

  way[landuse=industrial]{bbox};
  relation[landuse=industrial]{bbox};

  way[landuse=commercial]{bbox};
  relation[landuse=commercial]{bbox};

  node[amenity=parking]{bbox};
  way[amenity=parking]{bbox};
  relation[amenity=parking]{bbox};

  way[natural=wood]{bbox};
  relation[natural=wood]{bbox};
  way[leisure=nature_reserve]{bbox};
  relation[leisure=nature_reserve]{bbox};

  way[highway=primary]{bbox};
  way[highway=secondary]{bbox};
  way[highway=residential]{bbox};
  way[highway=service]{bbox};
);
out center;
"""


def element_coords(element: dict) -> tuple[float, float] | None:
    if "lat" in element and "lon" in element:
        return float(element["lat"]), float(element["lon"])
    center = element.get("center")
    if center and "lat" in center and "lon" in center:
        return float(center["lat"]), float(center["lon"])
    return None


def map_poi(tags: dict) -> str | None:
    amenity = tags.get("amenity")
    if amenity == "police":
        return "police"
    if amenity == "fire_station":
        return "fire"
    if amenity == "hospital":
        return "hospital"
    return None


def map_zone(tags: dict) -> str | None:
    landuse = tags.get("landuse")
    amenity = tags.get("amenity")
    natural = tags.get("natural")
    leisure = tags.get("leisure")

    if landuse == "residential":
        return "residential"
    if landuse == "industrial":
        return "industrial"
    if landuse == "commercial":
        return "commercial"
    if amenity == "parking":
        return "parking"
    if natural in {"wood", "scrub", "heath"} or leisure == "nature_reserve":
        return "nature"
    return None


def map_road(tags: dict) -> str | None:
    highway = tags.get("highway")
    if highway in {"primary", "secondary", "residential", "service"}:
        return highway
    return None


def fetch_overpass(query: str) -> dict:
    payload = parse.urlencode({"data": query}).encode("utf-8")
    req = request.Request(OVERPASS_URL, data=payload, method="POST")
    with request.urlopen(req, timeout=180) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8"))


def import_osm(south: float, west: float, north: float, east: float) -> dict:
    init_db()
    data = fetch_overpass(build_query(south, west, north, east))
    elements = data.get("elements", [])

    imported_at = now_iso()
    source = "osm_overpass"

    poi_rows = []
    zone_rows = []
    road_rows = []

    for element in elements:
        tags = element.get("tags", {})
        coords = element_coords(element)
        if not coords:
            continue

        lat, lon = coords
        base_id = f"{element.get('type', 'x')}:{element.get('id', uuid.uuid4())}"

        poi_type = map_poi(tags)
        if poi_type:
            poi_rows.append((f"poi:{base_id}", poi_type, lat, lon, source, imported_at))

        zone_type = map_zone(tags)
        if zone_type:
            zone_rows.append((f"zone:{base_id}", zone_type, lat, lon, source, imported_at))

        road_type = map_road(tags)
        if road_type:
            road_rows.append((f"road:{base_id}", road_type, lat, lon, source, imported_at))

    with get_conn() as conn:
        conn.execute("DELETE FROM osm_poi WHERE source = ?", (source,))
        conn.execute("DELETE FROM osm_zone WHERE source = ?", (source,))
        conn.execute("DELETE FROM osm_road WHERE source = ?", (source,))

        conn.executemany(
            """
            INSERT INTO osm_poi (id, poi_type, lat, lon, source, imported_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            poi_rows,
        )
        conn.executemany(
            """
            INSERT INTO osm_zone (id, zone_type, lat, lon, source, imported_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            zone_rows,
        )
        conn.executemany(
            """
            INSERT INTO osm_road (id, road_type, lat, lon, source, imported_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            road_rows,
        )

        total = len(poi_rows) + len(zone_rows) + len(road_rows)
        conn.execute(
            """
            INSERT INTO data_source_state (source_name, imported_at, record_count, notes)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source_name) DO UPDATE SET
              imported_at = excluded.imported_at,
              record_count = excluded.record_count,
              notes = excluded.notes
            """,
            ("osm_overpass", imported_at, total, f"bbox={south},{west},{north},{east}"),
        )

    return {
        "elements": len(elements),
        "pois": len(poi_rows),
        "zones": len(zone_rows),
        "roads": len(road_rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import OSM data for StaySense from Overpass")
    parser.add_argument("--south", type=float, default=DEFAULT_BBOX[0])
    parser.add_argument("--west", type=float, default=DEFAULT_BBOX[1])
    parser.add_argument("--north", type=float, default=DEFAULT_BBOX[2])
    parser.add_argument("--east", type=float, default=DEFAULT_BBOX[3])
    args = parser.parse_args()

    result = import_osm(args.south, args.west, args.north, args.east)
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
