import datetime as dt
import hashlib
import hmac
import json
import os
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from db import get_conn, init_db
from score_engine import (
    ampel,
    clamp_score,
    classify_area,
    classify_road,
    decay,
    haversine_m,
    nearest_distance_m,
    night_window_for,
    score_area_modifier,
    spot_id_for,
    weekend_or_holiday,
)

HOST = "127.0.0.1"
PORT = 8787

DEFAULT_SALT = "change-me-in-production"
SERVER_SALT = os.environ.get("STAYSENSE_SERVER_SALT", DEFAULT_SALT)
SIGNAL_COOLDOWN_HOURS = int(os.environ.get("STAYSENSE_SIGNAL_COOLDOWN_HOURS", "24"))

FALLBACK_POLICE_POINTS = [(51.2507, 6.9751), (51.2965, 6.8494), (51.3398, 7.0438)]
FALLBACK_FIRE_POINTS = [(51.2518, 6.9800), (51.2937, 6.8568), (51.3314, 7.0540)]
FALLBACK_HOSPITAL_POINTS = [(51.2556, 6.9723), (51.2891, 6.8457), (51.3321, 7.0403)]


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def parse_iso8601(value: str | None) -> dt.datetime:
    if not value:
        return utc_now()
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def to_iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    raw = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(raw)


def read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        return {}
    body = handler.rfile.read(length)
    return json.loads(body.decode("utf-8"))


def hashed_device(device_token: str) -> str:
    return hmac.new(
        key=SERVER_SALT.encode("utf-8"),
        msg=device_token.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()


def fetch_points(sql: str, params: tuple) -> list[tuple[float, float]]:
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [(float(r["lat"]), float(r["lon"])) for r in rows]


def nearest_from_db(
    lat: float, lon: float, table: str, type_col: str, value: str, fallback_points: list[tuple[float, float]]
) -> tuple[int, bool]:
    rows = fetch_points(
        f"SELECT lat, lon FROM {table} WHERE {type_col} = ?",
        (value,),
    )
    if rows:
        return int(min(haversine_m(lat, lon, x, y) for x, y in rows)), False
    if fallback_points:
        return nearest_distance_m(lat, lon, fallback_points), True
    return 5000, True


def area_from_db(lat: float, lon: float) -> str:
    with get_conn() as conn:
        rows = conn.execute("SELECT zone_type, lat, lon FROM osm_zone").fetchall()

    if not rows:
        return classify_area(lat, lon)

    best_type = "residential"
    best_dist = 999999.0
    for row in rows:
        dist = haversine_m(lat, lon, float(row["lat"]), float(row["lon"]))
        if dist < best_dist:
            best_dist = dist
            best_type = row["zone_type"]

    return best_type if best_dist <= 500 else "residential"


def road_from_db(lat: float, lon: float) -> str:
    with get_conn() as conn:
        rows = conn.execute("SELECT road_type, lat, lon FROM osm_road").fetchall()

    if not rows:
        return classify_road(lat, lon)

    best_type = "unknown"
    best_dist = 999999.0
    for row in rows:
        dist = haversine_m(lat, lon, float(row["lat"]), float(row["lon"]))
        if dist < best_dist:
            best_dist = dist
            best_type = row["road_type"]

    return best_type if best_dist <= 300 else "unknown"


def ensure_spot(lat: float, lon: float, now_iso: str) -> dict:
    s_id = spot_id_for(lat, lon)
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM spot WHERE id = ?", (s_id,)).fetchone()
        if row:
            return dict(row)

        area_type = area_from_db(lat, lon)
        road_type = road_from_db(lat, lon)

        police_d, police_fallback = nearest_from_db(lat, lon, "osm_poi", "poi_type", "police", FALLBACK_POLICE_POINTS)
        fire_d, fire_fallback = nearest_from_db(lat, lon, "osm_poi", "poi_type", "fire", FALLBACK_FIRE_POINTS)
        hosp_d, hosp_fallback = nearest_from_db(lat, lon, "osm_poi", "poi_type", "hospital", FALLBACK_HOSPITAL_POINTS)

        conn.execute(
            """
            INSERT INTO spot (
                id, lat, lon, osm_area_type, road_type,
                distance_police_m, distance_fire_m, distance_hospital_m,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (s_id, lat, lon, area_type, road_type, police_d, fire_d, hosp_d, now_iso, now_iso),
        )

        return {
            "id": s_id,
            "lat": lat,
            "lon": lon,
            "osm_area_type": area_type,
            "road_type": road_type,
            "distance_police_m": police_d,
            "distance_fire_m": fire_d,
            "distance_hospital_m": hosp_d,
            "used_fallback_pois": police_fallback or fire_fallback or hosp_fallback,
        }


def collect_local_event_factors(lat: float, lon: float, night_end: dt.datetime) -> list[dict]:
    next_morning_start = night_end
    next_morning_end = night_end + dt.timedelta(hours=4)

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT event_type, risk_modifier, source, lat, lon, start_datetime, end_datetime
            FROM open_data_event
            WHERE start_datetime <= ?
              AND end_datetime >= ?
            """,
            (to_iso(next_morning_end), to_iso(next_morning_start)),
        ).fetchall()

    factors = []
    seen = set()
    for row in rows:
        distance = haversine_m(lat, lon, float(row["lat"]), float(row["lon"]))
        if distance > 1000:
            continue

        event_type = row["event_type"]
        label = {
            "waste": "Müllabfuhr am Morgen",
            "market": "Marktbetrieb am Morgen",
            "event": "Lokale Veranstaltung",
            "construction": "Baustelle",
        }.get(event_type, "Lokales Ereignis")
        dedupe_key = (
            event_type,
            row["risk_modifier"],
            row["start_datetime"] if "start_datetime" in row.keys() else "",
            row["end_datetime"] if "end_datetime" in row.keys() else "",
            round(float(row["lat"]), 4),
            round(float(row["lon"]), 4),
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        factors.append(
            {
                "key": f"event_{event_type}",
                "label": label,
                "points": float(row["risk_modifier"]),
                "source": row["source"],
            }
        )
    return factors


def collect_community_factors(spot_id: str, at_time: dt.datetime) -> list[dict]:
    max_window = at_time - dt.timedelta(days=30)
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT signal_type, timestamp
            FROM community_signal
            WHERE spot_id = ?
              AND timestamp >= ?
            """,
            (spot_id, to_iso(max_window)),
        ).fetchall()

    buckets = {
        "knock": {"base": -25.0, "half_life": 10.0, "window": 30, "label": "Klopfen gemeldet"},
        "noise": {"base": -15.0, "half_life": 7.0, "window": 14, "label": "Lärm gemeldet"},
        "calm": {"base": 10.0, "half_life": 7.0, "window": 14, "label": "Ruhig gemeldet"},
        "police": {"base": -18.0, "half_life": 10.0, "window": 30, "label": "Polizei-Einsatz gemeldet"},
    }

    by_type: dict[str, float] = {key: 0.0 for key in buckets}
    for row in rows:
        signal_type = row["signal_type"]
        if signal_type not in buckets:
            continue
        cfg = buckets[signal_type]
        sig_ts = parse_iso8601(row["timestamp"])
        age_days = max(0.0, (at_time - sig_ts).total_seconds() / 86400.0)
        if age_days > cfg["window"]:
            continue
        by_type[signal_type] += cfg["base"] * decay(age_days, cfg["half_life"])

    out = []
    for signal_type, points in by_type.items():
        if abs(points) < 0.5:
            continue
        label = buckets[signal_type]["label"]
        out.append(
            {
                "key": f"community_{signal_type}",
                "label": label,
                "points": points,
                "source": "community",
            }
        )
    return out


def data_source_meta() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT source_name, imported_at, record_count, notes FROM data_source_state ORDER BY imported_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def source_health(sources: list[dict], now: dt.datetime) -> dict:
    if not sources:
        return {"freshest_age_hours": None, "stalest_age_hours": None, "stale_sources": [], "has_data": False}

    ages = []
    stale_sources = []
    for src in sources:
        try:
            age_h = (now - parse_iso8601(src["imported_at"])).total_seconds() / 3600.0
        except Exception:
            continue
        age_h = max(0.0, age_h)
        ages.append((src["source_name"], age_h))
        if age_h > 24:
            stale_sources.append(src["source_name"])

    if not ages:
        return {"freshest_age_hours": None, "stalest_age_hours": None, "stale_sources": [], "has_data": False}

    freshest = min(age for _, age in ages)
    stalest = max(age for _, age in ages)
    return {
        "freshest_age_hours": round(freshest, 2),
        "stalest_age_hours": round(stalest, 2),
        "stale_sources": stale_sources,
        "has_data": True,
    }


def compute_score_payload(lat: float, lon: float, at_time: dt.datetime) -> dict:
    now_iso = to_iso(utc_now())
    spot = ensure_spot(lat, lon, now_iso)
    sources = data_source_meta()
    health = source_health(sources, utc_now())

    night_start, night_end = night_window_for(at_time)
    factors = []

    area_factor = score_area_modifier(spot["osm_area_type"])
    factors.append({"key": area_factor.key, "label": area_factor.label, "points": area_factor.points, "source": "osm"})

    if spot["distance_police_m"] < 200:
        factors.append({"key": "dist_police", "label": "Polizei in <200m", "points": -15.0, "source": "osm"})
    if spot["distance_hospital_m"] < 200:
        factors.append({"key": "dist_hospital", "label": "Krankenhaus in <200m", "points": -10.0, "source": "osm"})

    if weekend_or_holiday(night_start):
        factors.append({"key": "time_weekend", "label": "Wochenende/Feiertag", "points": -10.0, "source": "time"})
    else:
        factors.append({"key": "time_weekday", "label": "Werktagnacht", "points": 5.0, "source": "time"})

    factors.extend(collect_local_event_factors(lat, lon, night_end))
    factors.extend(collect_community_factors(spot["id"], at_time))

    raw_score = 100.0 + sum(item["points"] for item in factors)
    score = clamp_score(raw_score)

    top_reasons = sorted(factors, key=lambda item: abs(item["points"]), reverse=True)[:4]
    reasons = [f"{item['label']} ({item['points']:+.0f})" for item in top_reasons]

    return {
        "spot_id": spot["id"],
        "score": score,
        "ampel": ampel(score),
        "reasons": reasons,
        "factors": top_reasons,
        "night_window": {
            "start": to_iso(night_start),
            "end": to_iso(night_end),
        },
        "meta": {
            "data_updated_at": now_iso,
            "region": "DE-NW (Pilot: Kreis Mettmann)",
            "attribution": "Kartendaten: OpenStreetMap-Mitwirkende (ODbL)",
            "sources": sources,
            "health": health,
            "used_fallback_pois": bool(spot.get("used_fallback_pois", False)),
        },
    }


def handle_score(handler: BaseHTTPRequestHandler, query: dict[str, list[str]]) -> None:
    try:
        lat = float(query.get("lat", [""])[0])
        lon = float(query.get("lon", [""])[0])
        at = parse_iso8601(query.get("at", [""])[0])
    except Exception:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid_query"})
        return

    if not (47.0 <= lat <= 55.5 and 5.0 <= lon <= 16.0):
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "lat_lon_out_of_bounds"})
        return

    payload = compute_score_payload(lat, lon, at)
    json_response(handler, HTTPStatus.OK, payload)


def handle_signal(handler: BaseHTTPRequestHandler) -> None:
    try:
        body = read_json(handler)
    except Exception:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
        return

    spot_id = body.get("spot_id")
    signal_type = body.get("signal_type")
    device_token = body.get("device_token")
    timestamp = parse_iso8601(body.get("timestamp"))

    if not isinstance(spot_id, str) or not spot_id:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "spot_id_required"})
        return
    if signal_type not in {"calm", "noise", "knock", "police"}:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid_signal_type"})
        return
    if not isinstance(device_token, str) or len(device_token) < 16:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid_device_token"})
        return

    hashed = hashed_device(device_token)
    now = utc_now()
    if timestamp > now + dt.timedelta(minutes=5):
        timestamp = now

    cooldown_start = timestamp - dt.timedelta(hours=SIGNAL_COOLDOWN_HOURS)

    with get_conn() as conn:
        spot_exists = conn.execute("SELECT 1 FROM spot WHERE id = ?", (spot_id,)).fetchone()
        if not spot_exists:
            json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "unknown_spot_id"})
            return

        latest = conn.execute(
            """
            SELECT timestamp
            FROM community_signal
            WHERE spot_id = ?
              AND hashed_device = ?
              AND timestamp >= ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (spot_id, hashed, to_iso(cooldown_start)),
        ).fetchone()

        if latest:
            next_allowed = parse_iso8601(latest["timestamp"]) + dt.timedelta(hours=SIGNAL_COOLDOWN_HOURS)
            json_response(
                handler,
                HTTPStatus.TOO_MANY_REQUESTS,
                {
                    "accepted": False,
                    "error": "cooldown_active",
                    "next_allowed_at": to_iso(next_allowed),
                },
            )
            return

        day_bucket = timestamp.date().isoformat()
        try:
            conn.execute(
                """
                INSERT INTO community_signal (
                    id, spot_id, signal_type, hashed_device, timestamp, day_bucket
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    spot_id,
                    signal_type,
                    hashed,
                    to_iso(timestamp),
                    day_bucket,
                ),
            )
        except Exception:
            json_response(
                handler,
                HTTPStatus.TOO_MANY_REQUESTS,
                {
                    "accepted": False,
                    "error": "daily_limit",
                },
            )
            return

    json_response(
        handler,
        HTTPStatus.CREATED,
        {
            "accepted": True,
            "cooldown_hours": SIGNAL_COOLDOWN_HOURS,
        },
    )


class StaySenseHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            sources = data_source_meta()
            json_response(self, HTTPStatus.OK, {"status": "ok", "sources": sources, "health": source_health(sources, utc_now())})
            return
        if parsed.path == "/spot/score":
            query = parse_qs(parsed.query)
            handle_score(self, query)
            return
        json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/spot/signal":
            handle_signal(self)
            return
        json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})


def main() -> None:
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), StaySenseHandler)
    print(f"StaySense API listening on http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
