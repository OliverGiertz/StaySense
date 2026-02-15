import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

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
NOMINATIM_BASE_URL = os.environ.get("STAYSENSE_NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org/search")
NOMINATIM_USER_AGENT = os.environ.get(
    "STAYSENSE_NOMINATIM_USER_AGENT",
    "StaySense/0.1 (staysense.vanityontour.de)",
)
OSM_TILE_BASE_URL = os.environ.get("STAYSENSE_OSM_TILE_BASE_URL", "https://tile.openstreetmap.org")
ADMIN_SESSION_HOURS = int(os.environ.get("STAYSENSE_ADMIN_SESSION_HOURS", "12"))
ADMIN_PBKDF2_ITERATIONS = int(os.environ.get("STAYSENSE_ADMIN_PBKDF2_ITERATIONS", "390000"))
ADMIN_MANUAL_SOURCE = "admin_manual"

FALLBACK_POLICE_POINTS = [(51.2507, 6.9751), (51.2965, 6.8494), (51.3398, 7.0438)]
FALLBACK_FIRE_POINTS = [(51.2518, 6.9800), (51.2937, 6.8568), (51.3314, 7.0540)]
FALLBACK_HOSPITAL_POINTS = [(51.2556, 6.9723), (51.2891, 6.8457), (51.3321, 7.0403)]
ADMIN_SESSIONS: dict[str, dict] = {}


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


def binary_response(
    handler: BaseHTTPRequestHandler, status: int, payload: bytes, content_type: str, cache_control: str = "public, max-age=3600"
) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("Cache-Control", cache_control)
    handler.end_headers()
    handler.wfile.write(payload)


def read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        return {}
    body = handler.rfile.read(length)
    return json.loads(body.decode("utf-8"))


def require_fields(handler: BaseHTTPRequestHandler, body: dict, fields: list[str]) -> bool:
    missing = [field for field in fields if not body.get(field)]
    if missing:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "missing_fields", "fields": missing})
        return False
    return True


def hashed_device(device_token: str) -> str:
    return hmac.new(
        key=SERVER_SALT.encode("utf-8"),
        msg=device_token.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()


def pbkdf2_hash(password: str, salt_hex: str) -> str:
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        ADMIN_PBKDF2_ITERATIONS,
        dklen=32,
    )
    return dk.hex()


def admin_exists() -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM admin_user WHERE id = 1").fetchone()
    return bool(row)


def get_admin_user() -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT id, username, password_hash, password_salt FROM admin_user WHERE id = 1").fetchone()
    return dict(row) if row else None


def validate_admin_password(password: str) -> bool:
    if not isinstance(password, str):
        return False
    return len(password) >= 10


def create_admin_user(username: str, password: str) -> tuple[bool, str]:
    if not isinstance(username, str) or len(username.strip()) < 3:
        return False, "invalid_username"
    if not validate_admin_password(password):
        return False, "invalid_password"
    if admin_exists():
        return False, "already_initialized"

    now_iso = to_iso(utc_now())
    username_clean = username.strip()
    salt_hex = secrets.token_hex(16)
    pw_hash = pbkdf2_hash(password, salt_hex)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO admin_user (id, username, password_hash, password_salt, created_at, updated_at)
            VALUES (1, ?, ?, ?, ?, ?)
            """,
            (username_clean, pw_hash, salt_hex, now_iso, now_iso),
        )
    return True, "created"


def create_admin_session(username: str) -> dict:
    token = secrets.token_urlsafe(32)
    expires_at = utc_now() + dt.timedelta(hours=ADMIN_SESSION_HOURS)
    ADMIN_SESSIONS[token] = {
        "username": username,
        "expires_at": expires_at,
    }
    return {"token": token, "expires_at": to_iso(expires_at), "session_hours": ADMIN_SESSION_HOURS}


def cleanup_admin_sessions() -> None:
    now = utc_now()
    expired = [token for token, item in ADMIN_SESSIONS.items() if item["expires_at"] <= now]
    for token in expired:
        ADMIN_SESSIONS.pop(token, None)


def admin_auth(handler: BaseHTTPRequestHandler) -> tuple[bool, str]:
    cleanup_admin_sessions()
    auth_header = handler.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return False, "missing_token"
    token = auth_header.replace("Bearer ", "", 1).strip()
    session = ADMIN_SESSIONS.get(token)
    if not session:
        return False, "invalid_token"
    if session["expires_at"] <= utc_now():
        ADMIN_SESSIONS.pop(token, None)
        return False, "expired_token"
    return True, session["username"]


def parse_admin_event(body: dict) -> tuple[dict | None, str | None]:
    try:
        event_type = str(body.get("event_type", "")).strip()
        lat = float(body.get("lat"))
        lon = float(body.get("lon"))
        risk_modifier = int(body.get("risk_modifier"))
        start_datetime = to_iso(parse_iso8601(body.get("start_datetime")))
        end_datetime = to_iso(parse_iso8601(body.get("end_datetime")))
        source = str(body.get("source", ADMIN_MANUAL_SOURCE)).strip() or ADMIN_MANUAL_SOURCE
    except Exception:
        return None, "invalid_payload"

    if event_type not in {"market", "waste", "event", "construction"}:
        return None, "invalid_event_type"
    if not (47.0 <= lat <= 55.5 and 5.0 <= lon <= 16.0):
        return None, "lat_lon_out_of_bounds"
    if start_datetime >= end_datetime:
        return None, "invalid_time_window"
    if risk_modifier < -50 or risk_modifier > 50:
        return None, "invalid_risk_modifier"
    return {
        "event_type": event_type,
        "lat": lat,
        "lon": lon,
        "risk_modifier": risk_modifier,
        "start_datetime": start_datetime,
        "end_datetime": end_datetime,
        "source": source,
    }, None


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


def handle_geocode_search(handler: BaseHTTPRequestHandler, query: dict[str, list[str]]) -> None:
    raw_q = (query.get("q") or [""])[0].strip()
    if len(raw_q) < 2:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "query_too_short"})
        return
    if len(raw_q) > 160:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "query_too_long"})
        return

    params = urlencode(
        {
            "q": raw_q,
            "format": "jsonv2",
            "limit": "5",
            "addressdetails": "0",
            "countrycodes": "de",
        }
    )
    request = Request(
        f"{NOMINATIM_BASE_URL}?{params}",
        headers={
            "User-Agent": NOMINATIM_USER_AGENT,
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(request, timeout=5) as response:
            if response.status != 200:
                raise RuntimeError("nominatim_status")
            raw = response.read().decode("utf-8")
            data = json.loads(raw)
    except Exception:
        json_response(handler, HTTPStatus.BAD_GATEWAY, {"error": "geocoder_unavailable"})
        return

    results = []
    for item in data[:5]:
        try:
            lat = float(item.get("lat"))
            lon = float(item.get("lon"))
        except Exception:
            continue
        if not (47.0 <= lat <= 55.5 and 5.0 <= lon <= 16.0):
            continue
        results.append(
            {
                "display_name": str(item.get("display_name", "Unbekannter Treffer")),
                "lat": round(lat, 6),
                "lon": round(lon, 6),
            }
        )

    json_response(handler, HTTPStatus.OK, {"results": results})


def handle_tile_proxy(handler: BaseHTTPRequestHandler, path: str) -> None:
    parts = path.strip("/").split("/")
    if len(parts) != 5 or parts[0] != "map" or parts[1] != "tile":
        json_response(handler, HTTPStatus.NOT_FOUND, {"error": "not_found"})
        return

    z_raw, x_raw, y_raw = parts[2], parts[3], parts[4]
    if not y_raw.endswith(".png"):
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid_tile_path"})
        return

    try:
        z = int(z_raw)
        x = int(x_raw)
        y = int(y_raw[:-4])
    except Exception:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid_tile_path"})
        return

    if z < 0 or z > 19:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid_zoom"})
        return

    max_tile = 2**z - 1
    if x < 0 or x > max_tile or y < 0 or y > max_tile:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "tile_out_of_bounds"})
        return

    request = Request(
        f"{OSM_TILE_BASE_URL}/{z}/{x}/{y}.png",
        headers={
            "User-Agent": NOMINATIM_USER_AGENT,
            "Accept": "image/png",
        },
    )

    try:
        with urlopen(request, timeout=5) as response:
            if response.status != 200:
                raise RuntimeError("tile_status")
            payload = response.read()
    except Exception:
        json_response(handler, HTTPStatus.BAD_GATEWAY, {"error": "tile_unavailable"})
        return

    binary_response(handler, HTTPStatus.OK, payload, "image/png", cache_control="public, max-age=43200")


def handle_admin_bootstrap_status(handler: BaseHTTPRequestHandler) -> None:
    json_response(
        handler,
        HTTPStatus.OK,
        {
            "initialized": admin_exists(),
            "session_hours": ADMIN_SESSION_HOURS,
            "password_policy": {"min_length": 10},
        },
    )


def handle_admin_bootstrap(handler: BaseHTTPRequestHandler) -> None:
    try:
        body = read_json(handler)
    except Exception:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
        return
    if not require_fields(handler, body, ["username", "password"]):
        return

    ok, status = create_admin_user(body["username"], body["password"])
    if not ok:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": status})
        return
    session = create_admin_session(body["username"].strip())
    json_response(handler, HTTPStatus.CREATED, {"created": True, "session": session})


def handle_admin_login(handler: BaseHTTPRequestHandler) -> None:
    try:
        body = read_json(handler)
    except Exception:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
        return
    if not require_fields(handler, body, ["username", "password"]):
        return
    if not admin_exists():
        json_response(handler, HTTPStatus.PRECONDITION_FAILED, {"error": "admin_not_initialized"})
        return

    admin = get_admin_user()
    if not admin:
        json_response(handler, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "admin_lookup_failed"})
        return
    if body["username"].strip() != admin["username"]:
        json_response(handler, HTTPStatus.UNAUTHORIZED, {"error": "invalid_credentials"})
        return

    expected = pbkdf2_hash(body["password"], admin["password_salt"])
    if not hmac.compare_digest(expected, admin["password_hash"]):
        json_response(handler, HTTPStatus.UNAUTHORIZED, {"error": "invalid_credentials"})
        return

    session = create_admin_session(admin["username"])
    json_response(handler, HTTPStatus.OK, {"login": "ok", "session": session})


def handle_admin_logout(handler: BaseHTTPRequestHandler) -> None:
    auth_header = handler.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "", 1).strip() if auth_header.startswith("Bearer ") else ""
    if token:
        ADMIN_SESSIONS.pop(token, None)
    json_response(handler, HTTPStatus.OK, {"logout": "ok"})


def handle_admin_overview(handler: BaseHTTPRequestHandler) -> None:
    ok, username = admin_auth(handler)
    if not ok:
        json_response(handler, HTTPStatus.UNAUTHORIZED, {"error": username})
        return

    with get_conn() as conn:
        counts = {
            "spots": conn.execute("SELECT COUNT(*) AS c FROM spot").fetchone()["c"],
            "signals": conn.execute("SELECT COUNT(*) AS c FROM community_signal").fetchone()["c"],
            "events": conn.execute("SELECT COUNT(*) AS c FROM open_data_event").fetchone()["c"],
            "data_sources": conn.execute("SELECT COUNT(*) AS c FROM data_source_state").fetchone()["c"],
        }
        latest_signals = [dict(r) for r in conn.execute(
            """
            SELECT spot_id, signal_type, timestamp
            FROM community_signal
            ORDER BY timestamp DESC
            LIMIT 20
            """
        ).fetchall()]
        latest_events = [dict(r) for r in conn.execute(
            """
            SELECT id, event_type, lat, lon, start_datetime, end_datetime, risk_modifier, source, imported_at
            FROM open_data_event
            ORDER BY start_datetime DESC
            LIMIT 20
            """
        ).fetchall()]
        sources = [dict(r) for r in conn.execute(
            """
            SELECT source_name, imported_at, record_count, notes
            FROM data_source_state
            ORDER BY imported_at DESC
            LIMIT 20
            """
        ).fetchall()]
    json_response(
        handler,
        HTTPStatus.OK,
        {
            "admin_user": username,
            "counts": counts,
            "latest_signals": latest_signals,
            "latest_events": latest_events,
            "data_sources": sources,
        },
    )


def handle_admin_events_list(handler: BaseHTTPRequestHandler, query: dict[str, list[str]]) -> None:
    ok, username = admin_auth(handler)
    if not ok:
        json_response(handler, HTTPStatus.UNAUTHORIZED, {"error": username})
        return
    try:
        limit = int((query.get("limit") or ["100"])[0])
    except Exception:
        limit = 100
    limit = max(1, min(limit, 500))
    with get_conn() as conn:
        events = [dict(r) for r in conn.execute(
            """
            SELECT id, event_type, lat, lon, start_datetime, end_datetime, risk_modifier, source, imported_at
            FROM open_data_event
            ORDER BY start_datetime DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()]
    json_response(handler, HTTPStatus.OK, {"admin_user": username, "events": events})


def handle_admin_events_create(handler: BaseHTTPRequestHandler) -> None:
    ok, username = admin_auth(handler)
    if not ok:
        json_response(handler, HTTPStatus.UNAUTHORIZED, {"error": username})
        return
    try:
        body = read_json(handler)
    except Exception:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
        return
    event, error = parse_admin_event(body)
    if error:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": error})
        return

    now_iso = to_iso(utc_now())
    event_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO open_data_event (
                id, event_type, lat, lon, start_datetime, end_datetime, risk_modifier, source, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                event["event_type"],
                event["lat"],
                event["lon"],
                event["start_datetime"],
                event["end_datetime"],
                event["risk_modifier"],
                event["source"],
                now_iso,
            ),
        )
        count = conn.execute("SELECT COUNT(*) AS c FROM open_data_event WHERE source = ?", (event["source"],)).fetchone()["c"]
        conn.execute(
            """
            INSERT INTO data_source_state (source_name, imported_at, record_count, notes)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source_name) DO UPDATE SET
              imported_at = excluded.imported_at,
              record_count = excluded.record_count,
              notes = excluded.notes
            """,
            (event["source"], now_iso, count, f"manual update by {username}"),
        )
    json_response(handler, HTTPStatus.CREATED, {"created": True, "id": event_id})


def handle_admin_events_update(handler: BaseHTTPRequestHandler, event_id: str) -> None:
    ok, username = admin_auth(handler)
    if not ok:
        json_response(handler, HTTPStatus.UNAUTHORIZED, {"error": username})
        return
    try:
        body = read_json(handler)
    except Exception:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
        return
    event, error = parse_admin_event(body)
    if error:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": error})
        return

    now_iso = to_iso(utc_now())
    with get_conn() as conn:
        existing = conn.execute("SELECT source FROM open_data_event WHERE id = ?", (event_id,)).fetchone()
        if not existing:
            json_response(handler, HTTPStatus.NOT_FOUND, {"error": "event_not_found"})
            return
        conn.execute(
            """
            UPDATE open_data_event
            SET event_type = ?, lat = ?, lon = ?, start_datetime = ?, end_datetime = ?, risk_modifier = ?, source = ?, imported_at = ?
            WHERE id = ?
            """,
            (
                event["event_type"],
                event["lat"],
                event["lon"],
                event["start_datetime"],
                event["end_datetime"],
                event["risk_modifier"],
                event["source"],
                now_iso,
                event_id,
            ),
        )
        count_new = conn.execute("SELECT COUNT(*) AS c FROM open_data_event WHERE source = ?", (event["source"],)).fetchone()["c"]
        conn.execute(
            """
            INSERT INTO data_source_state (source_name, imported_at, record_count, notes)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source_name) DO UPDATE SET
              imported_at = excluded.imported_at,
              record_count = excluded.record_count,
              notes = excluded.notes
            """,
            (event["source"], now_iso, count_new, f"manual update by {username}"),
        )
        old_source = existing["source"]
        if old_source != event["source"]:
            count_old = conn.execute("SELECT COUNT(*) AS c FROM open_data_event WHERE source = ?", (old_source,)).fetchone()["c"]
            if count_old == 0:
                conn.execute("DELETE FROM data_source_state WHERE source_name = ?", (old_source,))
            else:
                conn.execute(
                    """
                    UPDATE data_source_state
                    SET imported_at = ?, record_count = ?, notes = ?
                    WHERE source_name = ?
                    """,
                    (now_iso, count_old, f"manual update by {username}", old_source),
                )
    json_response(handler, HTTPStatus.OK, {"updated": True, "id": event_id})


def handle_admin_events_delete(handler: BaseHTTPRequestHandler, event_id: str) -> None:
    ok, username = admin_auth(handler)
    if not ok:
        json_response(handler, HTTPStatus.UNAUTHORIZED, {"error": username})
        return

    now_iso = to_iso(utc_now())
    with get_conn() as conn:
        existing = conn.execute("SELECT source FROM open_data_event WHERE id = ?", (event_id,)).fetchone()
        if not existing:
            json_response(handler, HTTPStatus.NOT_FOUND, {"error": "event_not_found"})
            return
        source_name = existing["source"]
        conn.execute("DELETE FROM open_data_event WHERE id = ?", (event_id,))
        count = conn.execute("SELECT COUNT(*) AS c FROM open_data_event WHERE source = ?", (source_name,)).fetchone()["c"]
        if count == 0:
            conn.execute("DELETE FROM data_source_state WHERE source_name = ?", (source_name,))
        else:
            conn.execute(
                """
                UPDATE data_source_state
                SET imported_at = ?, record_count = ?, notes = ?
                WHERE source_name = ?
                """,
                (now_iso, count, f"manual delete by {username}", source_name),
            )
    json_response(handler, HTTPStatus.OK, {"deleted": True, "id": event_id})


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
        if parsed.path == "/geocode/search":
            query = parse_qs(parsed.query)
            handle_geocode_search(self, query)
            return
        if parsed.path.startswith("/map/tile/"):
            handle_tile_proxy(self, parsed.path)
            return
        if parsed.path == "/admin/bootstrap/status":
            handle_admin_bootstrap_status(self)
            return
        if parsed.path == "/admin/overview":
            handle_admin_overview(self)
            return
        if parsed.path == "/admin/events":
            query = parse_qs(parsed.query)
            handle_admin_events_list(self, query)
            return
        json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/spot/signal":
            handle_signal(self)
            return
        if parsed.path == "/admin/bootstrap":
            handle_admin_bootstrap(self)
            return
        if parsed.path == "/admin/login":
            handle_admin_login(self)
            return
        if parsed.path == "/admin/logout":
            handle_admin_logout(self)
            return
        if parsed.path == "/admin/events":
            handle_admin_events_create(self)
            return
        json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/admin/events/"):
            event_id = parsed.path.replace("/admin/events/", "", 1).strip()
            if not event_id:
                json_response(self, HTTPStatus.BAD_REQUEST, {"error": "event_id_required"})
                return
            handle_admin_events_update(self, event_id)
            return
        json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/admin/events/"):
            event_id = parsed.path.replace("/admin/events/", "", 1).strip()
            if not event_id:
                json_response(self, HTTPStatus.BAD_REQUEST, {"error": "event_id_required"})
                return
            handle_admin_events_delete(self, event_id)
            return
        json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})


def main() -> None:
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), StaySenseHandler)
    print(f"StaySense API listening on http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
