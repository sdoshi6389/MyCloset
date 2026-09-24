"""Current conditions for a location, reduced to what outfit scoring cares about.

Uses Open-Meteo, which needs no API key -- one less secret to manage and no
signup for anyone running this. Results are cached briefly per rounded
coordinate, since a closet page can ask several times in a session and the
weather does not move that fast.
"""
import time
from typing import Any

import requests

_CACHE: dict[tuple, tuple[float, dict]] = {}
_TTL = 900          # 15 minutes

# Open-Meteo WMO weather codes, grouped into what actually changes an outfit.
_WET  = set(range(51, 68)) | set(range(80, 83)) | set(range(95, 100))
_SNOW = set(range(71, 78)) | {85, 86}


def _season_for(temp_c: float) -> str:
    """Map temperature onto the season vocabulary the closet is tagged with.

    Garments carry season tags (fall/winter/spring/summer), so translating
    temperature into that same vocabulary lets scoring compare like with like
    instead of inventing a second scale.
    """
    if temp_c <= 4:   return "winter"
    if temp_c <= 14:  return "fall"
    if temp_c <= 23:  return "spring"
    return "summer"


def _layers_for(temp_c: float) -> int:
    """How many layers the temperature justifies: 1 base, 2 add mid, 3 add outer."""
    if temp_c <= 4:  return 3
    if temp_c <= 14: return 2
    return 1


def get_weather(lat: float, lon: float) -> dict[str, Any] | None:
    """Returns {temp_c, feels_c, code, is_wet, is_snow, season, layers, label} or None."""
    key = (round(float(lat), 2), round(float(lon), 2))
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]

    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,apparent_temperature,weather_code",
            },
            timeout=12,
        )
        if r.status_code != 200:
            print(f"⚠️  weather: upstream {r.status_code}")
            return None
        cur = (r.json() or {}).get("current") or {}
        temp = cur.get("temperature_2m")
        if temp is None:
            return None
        feels = cur.get("apparent_temperature", temp)
        code  = int(cur.get("weather_code") or 0)
        # Scoring keys off how it feels outside, not the raw air temperature.
        out = {
            "temp_c":  round(float(temp), 1),
            "feels_c": round(float(feels), 1),
            "code":    code,
            "is_wet":  code in _WET,
            "is_snow": code in _SNOW,
            "season":  _season_for(float(feels)),
            "layers":  _layers_for(float(feels)),
        }
        out["label"] = _label(out)
        _CACHE[key] = (time.time(), out)
        return out
    except Exception as e:
        print(f"⚠️  weather lookup failed: {type(e).__name__}: {e}")
        return None


def _label(w: dict) -> str:
    bits = [f"{w['feels_c']:.0f}°C"]
    if w["is_snow"]:  bits.append("snow")
    elif w["is_wet"]: bits.append("rain")
    bits.append(w["season"])
    return " · ".join(bits)


def season_fit(item: dict, weather: dict | None) -> float:
    """0..1 — how well an item's season tags suit the weather.

    Neutral (0.5) when there is no weather or the item carries no season tag, so
    an untagged garment is never punished for missing metadata.
    """
    if not weather:
        return 0.5
    tags = (item.get("season") or "").lower()
    if not tags:
        return 0.5
    tags = {t.strip() for t in tags.split(",") if t.strip()}
    if "all_season" in tags or "all season" in tags:
        return 0.8
    if weather["season"] in tags:
        return 1.0
    # Adjacent seasons are a near miss, opposites are not.
    adjacent = {
        "winter": {"fall"}, "fall": {"winter", "spring"},
        "spring": {"fall", "summer"}, "summer": {"spring"},
    }
    if tags & adjacent.get(weather["season"], set()):
        return 0.55
    return 0.15
