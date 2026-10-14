"""Shared address/name identity helpers for imports, crawling, and display."""

import math
import re

NEIGHBORHOODS = ("중곡동", "군자동", "화양동", "능동")
GWANGJIN_DONGS = (*NEIGHBORHOODS, "구의동", "자양동", "광장동")


def normalize_name(name):
    return re.sub(r"[^0-9a-z가-힣]", "", (name or "").lower())


def find_address_dong(address):
    """Find a real administrative dong token, excluding road names like 능동로."""
    address = address or ""
    for dong in GWANGJIN_DONGS:
        if re.search(rf"(?<![가-힣]){re.escape(dong)}(?![가-힣])", address):
            return dong
    return ""


def road_address_key(address):
    """Normalize a Korean road-name/building-number pair for source matching."""
    address = address or ""
    match = re.search(r"([가-힣0-9·]+?(?:대로|로|길))\s*(\d+(?:-\d+)?)", address)
    return "".join(match.groups()) if match else ""


def exemplary_source(source_url):
    return bool(source_url and "gwangjin.go.kr/health/bbs/B0000064/view.do" in source_url)


def distance_meters(place_a, place_b):
    if any(place.get(key) is None for place in (place_a, place_b) for key in ("latitude", "longitude")):
        return None
    lat1, lon1 = math.radians(place_a["latitude"]), math.radians(place_a["longitude"])
    lat2, lon2 = math.radians(place_b["latitude"]), math.radians(place_b["longitude"])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    haversine = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6_371_000 * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))


def duplicate_place(place_a, place_b):
    if normalize_name(place_a.get("name")) != normalize_name(place_b.get("name")):
        return False
    road_a, road_b = road_address_key(place_a.get("address")), road_address_key(place_b.get("address"))
    if road_a and road_a == road_b:
        return True
    distance = distance_meters(place_a, place_b)
    return distance is not None and distance <= 18


def deduplicate_places(rows):
    """Collapse repeat licenses/source rows at the same named street location."""
    grouped = {}
    for row in rows:
        place = dict(row)
        name_key = normalize_name(place.get("name"))
        possible = grouped.setdefault(name_key, [])
        existing = next((item for item in possible if duplicate_place(item, place)), None)
        if existing is None:
            possible.append(place)
            continue

        # Retain the richer address and its coordinates; carry over the official
        # source so the single displayed record still gets the exemplary badge.
        if len(place.get("address") or "") > len(existing.get("address") or ""):
            existing["address"] = place["address"]
            if place.get("longitude") is not None and place.get("latitude") is not None:
                existing["longitude"] = place["longitude"]
                existing["latitude"] = place["latitude"]
            if place.get("neighborhood") in NEIGHBORHOODS:
                existing["neighborhood"] = place["neighborhood"]
        if not existing.get("category") and place.get("category"):
            existing["category"] = place["category"]
        if not existing.get("business_status") and place.get("business_status"):
            existing["business_status"] = place["business_status"]
        if exemplary_source(place.get("source_url")):
            existing["source_url"] = place["source_url"]
        if not existing.get("source_url") and place.get("source_url"):
            existing["source_url"] = place["source_url"]
    return [place for places in grouped.values() for place in places]
