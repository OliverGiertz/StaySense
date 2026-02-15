import csv
import datetime as dt
import hashlib
import json
import math
import subprocess
from pathlib import Path
from urllib import request

from db import get_conn, init_db

VALID_TYPES = {"market", "waste", "event", "construction"}
DE_BOUNDS = {"lat_min": 47.0, "lat_max": 55.5, "lon_min": 5.0, "lon_max": 16.0}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_iso(value: str) -> str:
    value = value.strip()
    if value.isdigit():
        # ArcGIS dates are commonly unix timestamps in milliseconds.
        ts = int(value)
        if ts > 10_000_000_000:
            ts = ts / 1000.0
        parsed = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc)
        return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _get_by_path(record: dict, path: str):
    if not path:
        return None
    current = record
    for token in path.split("."):
        if isinstance(current, dict):
            current = current.get(token)
            continue
        if isinstance(current, list):
            try:
                idx = int(token)
            except Exception:
                return None
            if idx < 0 or idx >= len(current):
                return None
            current = current[idx]
            continue
        return None
    return current


def _as_text(value) -> str:
    return "" if value is None else str(value).strip()


def _utm_epsg25832_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    # WGS84 / UTM zone 32N (EPSG:25832) to lat/lon conversion.
    a = 6378137.0
    e = 0.08181919084262149
    e1sq = 0.00673949674227643
    k0 = 0.9996

    x = easting - 500000.0
    y = northing
    zone_cm = 9.0  # UTM zone 32 central meridian

    m = y / k0
    mu = m / (a * (1 - e**2 / 4 - 3 * e**4 / 64 - 5 * e**6 / 256))
    e1 = (1 - math.sqrt(1 - e**2)) / (1 + math.sqrt(1 - e**2))

    j1 = 3 * e1 / 2 - 27 * e1**3 / 32
    j2 = 21 * e1**2 / 16 - 55 * e1**4 / 32
    j3 = 151 * e1**3 / 96
    j4 = 1097 * e1**4 / 512
    fp = mu + j1 * math.sin(2 * mu) + j2 * math.sin(4 * mu) + j3 * math.sin(6 * mu) + j4 * math.sin(8 * mu)

    sin_fp = math.sin(fp)
    cos_fp = math.cos(fp)
    tan_fp = math.tan(fp)

    c1 = e1sq * cos_fp**2
    t1 = tan_fp**2
    r1 = a * (1 - e**2) / (1 - e**2 * sin_fp**2) ** 1.5
    n1 = a / math.sqrt(1 - e**2 * sin_fp**2)
    d = x / (n1 * k0)

    q1 = n1 * tan_fp / r1
    q2 = d**2 / 2
    q3 = (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * e1sq) * d**4 / 24
    q4 = (61 + 90 * t1 + 298 * c1 + 45 * t1**2 - 252 * e1sq - 3 * c1**2) * d**6 / 720
    lat = fp - q1 * (q2 - q3 + q4)

    q5 = d
    q6 = (1 + 2 * t1 + c1) * d**3 / 6
    q7 = (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * e1sq + 24 * t1**2) * d**5 / 120
    lon = math.radians(zone_cm) + (q5 - q6 + q7) / cos_fp

    return math.degrees(lat), math.degrees(lon)


def _stable_id(source_name: str, external_id: str | None, payload: dict) -> str:
    if external_id:
        raw = f"{source_name}:{external_id}"
    else:
        raw = (
            f"{source_name}:{payload['event_type']}:{payload['lat']:.6f}:{payload['lon']:.6f}:"
            f"{payload['start_datetime']}:{payload['end_datetime']}:{payload['risk_modifier']}"
        )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _map_event_type(raw_value: str, event_type_map: dict[str, str], default_value: str | None) -> str | None:
    raw = (raw_value or "").strip().lower()
    if raw and raw in event_type_map:
        raw = event_type_map[raw]
    if not raw and default_value:
        raw = default_value
    if raw in VALID_TYPES:
        return raw
    return None


def _extract_json_records(payload: dict | list, json_path: str | None) -> list[dict]:
    current = payload
    if json_path:
        for part in json_path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            else:
                current = None
            if current is None:
                return []
    if isinstance(current, list):
        return [item for item in current if isinstance(item, dict)]
    return []


def _read_text(location: str, config_dir: Path) -> str:
    if location.startswith("http://") or location.startswith("https://"):
        try:
            with request.urlopen(location, timeout=60) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception:
            # Fallback for environments where Python DNS/network stack is restricted.
            raw = subprocess.check_output(["curl", "-sL", location], timeout=60)
            return raw.decode("utf-8", errors="replace")

    file_path = Path(location)
    if not file_path.is_absolute():
        file_path = (config_dir / location).resolve()
    return file_path.read_text(encoding="utf-8")


def import_event_rows(rows: list[dict], source_name: str, notes: str) -> dict:
    init_db()
    imported_at = now_iso()

    db_rows = []
    seen_ids = set()
    for item in rows:
        event_type = item.get("event_type")
        if event_type not in VALID_TYPES:
            continue
        if item["id"] in seen_ids:
            continue
        seen_ids.add(item["id"])

        db_rows.append(
            (
                item["id"],
                event_type,
                float(item["lat"]),
                float(item["lon"]),
                normalize_iso(item["start_datetime"]),
                normalize_iso(item["end_datetime"]),
                int(item["risk_modifier"]),
                source_name,
                imported_at,
            )
        )

    with get_conn() as conn:
        conn.execute("DELETE FROM open_data_event WHERE source = ?", (source_name,))
        conn.executemany(
            """
            INSERT INTO open_data_event (
                id, event_type, lat, lon, start_datetime, end_datetime,
                risk_modifier, source, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            db_rows,
        )
        conn.execute(
            """
            INSERT INTO data_source_state (source_name, imported_at, record_count, notes)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source_name) DO UPDATE SET
              imported_at = excluded.imported_at,
              record_count = excluded.record_count,
              notes = excluded.notes
            """,
            (source_name, imported_at, len(db_rows), notes),
        )

    return {"rows": len(db_rows), "source_name": source_name}


def import_from_source(source_cfg: dict, config_dir: Path) -> dict:
    source_name = source_cfg.get("source_name") or source_cfg.get("id") or "open_data_source"
    location = source_cfg.get("url") or source_cfg.get("file")
    if not location:
        raise ValueError(f"source '{source_name}' missing url/file")

    source_format = (source_cfg.get("format") or "csv").lower()
    field_map = source_cfg.get("field_map") or {}
    defaults = source_cfg.get("default_values") or {}
    event_type_map = {str(k).lower(): str(v).lower() for k, v in (source_cfg.get("event_type_map") or {}).items()}
    json_path = source_cfg.get("json_path")
    date_range_cfg = source_cfg.get("date_range")
    coord_crs = str(source_cfg.get("coord_crs", "")).upper().strip()

    text = _read_text(location, config_dir)

    records: list[dict]
    if source_format == "csv":
        reader = csv.DictReader(text.splitlines())
        records = [dict(row) for row in reader]
    elif source_format == "json":
        payload = json.loads(text)
        records = _extract_json_records(payload, json_path)
    else:
        raise ValueError(f"unsupported format: {source_format}")

    rows = []
    stats = {
        "input_records": len(records),
        "accepted": 0,
        "rejected_invalid_event_type": 0,
        "rejected_parse_error": 0,
        "rejected_missing_datetime": 0,
        "rejected_out_of_bounds": 0,
        "rejected_invalid_window": 0,
    }
    for record in records:
        lat_key = field_map.get("lat", "lat")
        lon_key = field_map.get("lon", "lon")
        start_key = field_map.get("start_datetime", "start_datetime")
        end_key = field_map.get("end_datetime", "end_datetime")
        risk_key = field_map.get("risk_modifier", "risk_modifier")
        event_type_key = field_map.get("event_type", "event_type")
        external_id_key = field_map.get("external_id")

        raw_event_type = _as_text(_get_by_path(record, event_type_key))
        if not raw_event_type:
            raw_event_type = _as_text(defaults.get("event_type", ""))
        event_type = _map_event_type(raw_event_type, event_type_map, defaults.get("event_type"))
        if not event_type:
            stats["rejected_invalid_event_type"] += 1
            continue

        try:
            lat_raw = _get_by_path(record, lat_key)
            lon_raw = _get_by_path(record, lon_key)
            lat = float(_as_text(lat_raw) or _as_text(defaults.get("lat", "")))
            lon = float(_as_text(lon_raw) or _as_text(defaults.get("lon", "")))
            if coord_crs == "EPSG:25832":
                lat, lon = _utm_epsg25832_to_wgs84(lon, lat)

            start_dt = _as_text(_get_by_path(record, start_key)) or _as_text(defaults.get("start_datetime", ""))
            end_dt = _as_text(_get_by_path(record, end_key)) or _as_text(defaults.get("end_datetime", ""))

            if date_range_cfg and (not start_dt or not end_dt):
                range_field = _as_text(_get_by_path(record, date_range_cfg.get("field", "")))
                separator = date_range_cfg.get("separator", " bis ")
                date_fmt = date_range_cfg.get("input_date_format", "%d-%m-%Y")
                if separator in range_field:
                    start_raw, end_raw = [part.strip() for part in range_field.split(separator, 1)]
                    start_dt = dt.datetime.strptime(start_raw, date_fmt).replace(tzinfo=dt.timezone.utc).isoformat()
                    end_dt = dt.datetime.strptime(end_raw, date_fmt).replace(tzinfo=dt.timezone.utc).isoformat()

            risk_raw = _get_by_path(record, risk_key)
            risk_modifier = int(_as_text(risk_raw) or _as_text(defaults.get("risk_modifier", "0")))
        except Exception:
            stats["rejected_parse_error"] += 1
            continue

        if not start_dt or not end_dt:
            stats["rejected_missing_datetime"] += 1
            continue

        if not (
            DE_BOUNDS["lat_min"] <= lat <= DE_BOUNDS["lat_max"]
            and DE_BOUNDS["lon_min"] <= lon <= DE_BOUNDS["lon_max"]
        ):
            stats["rejected_out_of_bounds"] += 1
            continue

        try:
            start_iso = normalize_iso(start_dt)
            end_iso = normalize_iso(end_dt)
        except Exception:
            stats["rejected_parse_error"] += 1
            continue

        if end_iso <= start_iso:
            stats["rejected_invalid_window"] += 1
            continue

        external_id = None
        if external_id_key:
            value = _get_by_path(record, external_id_key)
            external_id = str(value).strip() if value is not None else None

        payload = {
            "event_type": event_type,
            "lat": lat,
            "lon": lon,
            "start_datetime": start_iso,
            "end_datetime": end_iso,
            "risk_modifier": risk_modifier,
        }
        payload["id"] = _stable_id(source_name, external_id, payload)
        rows.append(payload)
        stats["accepted"] += 1

    note = f"connector={source_cfg.get('id', source_name)} location={location} format={source_format}"
    result = import_event_rows(rows, source_name=source_name, notes=note)
    result["connector_id"] = source_cfg.get("id", source_name)
    result["stats"] = stats
    return result


def prune_sources_not_in_config(config_source_names: set[str], protected_sources: set[str] | None = None) -> dict:
    protected = protected_sources or {"osm_overpass"}
    with get_conn() as conn:
        rows = conn.execute("SELECT DISTINCT source FROM open_data_event").fetchall()
        existing_sources = {row["source"] for row in rows}
        state_rows = conn.execute("SELECT source_name FROM data_source_state").fetchall()
        existing_state_sources = {row["source_name"] for row in state_rows}

        to_prune = sorted((existing_sources - config_source_names) - protected)
        state_to_mark = sorted((existing_state_sources - config_source_names) - protected)
        pruned_rows = 0
        ts = now_iso()
        for source_name in to_prune:
            count = conn.execute("SELECT COUNT(*) AS c FROM open_data_event WHERE source = ?", (source_name,)).fetchone()["c"]
            pruned_rows += int(count)
            conn.execute("DELETE FROM open_data_event WHERE source = ?", (source_name,))
        for source_name in state_to_mark:
            conn.execute(
                """
                INSERT INTO data_source_state (source_name, imported_at, record_count, notes)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source_name) DO UPDATE SET
                  imported_at = excluded.imported_at,
                  record_count = excluded.record_count,
                  notes = excluded.notes
                """,
                (source_name, ts, 0, "pruned_not_in_config"),
            )

    return {"sources": sorted(set(to_prune + state_to_mark)), "rows": pruned_rows}


def import_from_config(config_path: Path, prune_legacy: bool = False) -> dict:
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    sources = cfg.get("sources")
    if not isinstance(sources, list):
        raise ValueError("config requires 'sources' list")

    imported = []
    skipped = []
    disabled_source_names = []
    all_source_names = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        source_name = source.get("source_name") or source.get("id") or "open_data_source"
        all_source_names.add(source_name)
        if not source.get("enabled", False):
            skipped.append(source.get("id", "unknown"))
            disabled_source_names.append(source_name)
            continue
        try:
            imported.append(import_from_source(source, config_path.parent))
        except Exception as exc:
            imported.append(
                {
                    "connector_id": source.get("id", source_name),
                    "source_name": source_name,
                    "rows": 0,
                    "error": str(exc),
                }
            )

    if disabled_source_names:
        ts = now_iso()
        with get_conn() as conn:
            for source_name in disabled_source_names:
                conn.execute("DELETE FROM open_data_event WHERE source = ?", (source_name,))
                conn.execute(
                    """
                    INSERT INTO data_source_state (source_name, imported_at, record_count, notes)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(source_name) DO UPDATE SET
                      imported_at = excluded.imported_at,
                      record_count = excluded.record_count,
                      notes = excluded.notes
                    """,
                    (source_name, ts, 0, "disabled in config"),
                )

    pruned = {"sources": [], "rows": 0}
    if prune_legacy:
        pruned = prune_sources_not_in_config(all_source_names)

    return {
      "imported": imported,
      "skipped": skipped,
      "pruned": pruned,
      "count": len(imported),
    }
