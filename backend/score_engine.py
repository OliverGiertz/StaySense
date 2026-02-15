import datetime as dt
import math
import uuid
from dataclasses import dataclass

NRW_HOLIDAYS_2026 = {
    dt.date(2026, 1, 1),
    dt.date(2026, 4, 3),
    dt.date(2026, 4, 6),
    dt.date(2026, 5, 1),
    dt.date(2026, 5, 14),
    dt.date(2026, 5, 25),
    dt.date(2026, 6, 4),
    dt.date(2026, 10, 3),
    dt.date(2026, 11, 1),
    dt.date(2026, 12, 25),
    dt.date(2026, 12, 26),
}

POLICE_POINTS = [
    (51.2507, 6.9751),  # Mettmann
    (51.2965, 6.8494),  # Ratingen
    (51.3398, 7.0438),  # Velbert
]

FIRE_POINTS = [
    (51.2518, 6.9800),
    (51.2937, 6.8568),
    (51.3314, 7.0540),
]

HOSPITAL_POINTS = [
    (51.2556, 6.9723),
    (51.2891, 6.8457),
    (51.3321, 7.0403),
]

INDUSTRIAL_ZONES = [
    (51.2348, 6.9902),
    (51.3022, 6.8340),
]
COMMERCIAL_ZONES = [
    (51.2512, 6.9878),
    (51.2934, 6.8541),
]
NATURE_ZONES = [
    (51.2715, 6.9440),
    (51.3188, 7.0274),
]
PARKING_ZONES = [
    (51.2499, 6.9831),
]
MAIN_ROAD_POINTS = [
    (51.2524, 6.9921),
    (51.2951, 6.8615),
]


@dataclass
class Factor:
    key: str
    label: str
    points: float


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_distance_m(lat: float, lon: float, points: list[tuple[float, float]]) -> int:
    return int(min(haversine_m(lat, lon, p_lat, p_lon) for p_lat, p_lon in points))


def classify_area(lat: float, lon: float) -> str:
    candidates = [
        ("industrial", nearest_distance_m(lat, lon, INDUSTRIAL_ZONES)),
        ("commercial", nearest_distance_m(lat, lon, COMMERCIAL_ZONES)),
        ("nature", nearest_distance_m(lat, lon, NATURE_ZONES)),
        ("parking", nearest_distance_m(lat, lon, PARKING_ZONES)),
    ]
    best_type, best_dist = min(candidates, key=lambda x: x[1])
    if best_dist <= 400:
        return best_type
    return "residential"


def classify_road(lat: float, lon: float) -> str:
    if nearest_distance_m(lat, lon, MAIN_ROAD_POINTS) < 250:
        return "primary"
    return "residential"


def spot_id_for(lat: float, lon: float) -> str:
    key = f"{lat:.4f}:{lon:.4f}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"staysense:{key}"))


def score_area_modifier(area_type: str) -> Factor:
    mapping = {
        "residential": Factor("area", "Wohngebiet", -10),
        "industrial": Factor("area", "Industriegebiet", 10),
        "commercial": Factor("area", "Gewerbegebiet", 6),
        "parking": Factor("area", "Parkplatzumfeld", -5),
        "nature": Factor("area", "Naturnah", 8),
    }
    return mapping.get(area_type, Factor("area", "Umgebung", 0))


def night_window_for(reference: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    ref = reference.replace(second=0, microsecond=0)
    if ref.hour >= 22:
        start = ref.replace(hour=22, minute=0)
    elif ref.hour < 6:
        start = (ref - dt.timedelta(days=1)).replace(hour=22, minute=0)
    else:
        start = ref.replace(hour=22, minute=0)
    end = start + dt.timedelta(hours=8)
    return start, end


def weekend_or_holiday(night_start: dt.datetime) -> bool:
    weekday = night_start.weekday()  # 0=Mon, 4=Fri
    if weekday in (4, 5):
        return True
    if night_start.date() in NRW_HOLIDAYS_2026:
        return True
    if (night_start + dt.timedelta(days=1)).date() in NRW_HOLIDAYS_2026:
        return True
    return False


def decay(age_days: float, half_life_days: float) -> float:
    if age_days <= 0:
        return 1.0
    return 0.5 ** (age_days / half_life_days)


def clamp_score(value: float) -> int:
    return max(0, min(100, int(round(value))))


def ampel(score: int) -> str:
    if score >= 70:
        return "green"
    if score >= 45:
        return "yellow"
    return "red"
