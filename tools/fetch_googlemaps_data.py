#!/usr/bin/env python3
"""
Fetches businesses/places from Google Maps for lead generation and research.
Requires GOOGLE_PLACES_API_KEY in .env (free $200/month credit from Google Cloud).
Output format: same as youtube_data.json.

Usage:
  python tools/fetch_googlemaps_data.py --query "coffee shop" --location "Moscow"
  python tools/fetch_googlemaps_data.py --query "yoga studio" --location "Saint Petersburg" --radius 5000
Output: .tmp/{slug}/youtube_data.json
"""

import os
import sys
import json
import re
import argparse
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))

_proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
PROXIES = {"https": _proxy, "http": _proxy} if _proxy else None

PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
GEOCODE_BASE = "https://maps.googleapis.com/maps/api/geocode/json"
PLACES_BASE = "https://maps.googleapis.com/maps/api/place"


def make_slug(query: str) -> str:
    slug = query.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    return slug or "query"


def geocode_location(location: str) -> tuple:
    """Convert city/address string to (lat, lng)."""
    try:
        resp = requests.get(
            GEOCODE_BASE,
            params={"address": location, "key": PLACES_API_KEY},
            proxies=PROXIES, timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if results:
            loc = results[0]["geometry"]["location"]
            return loc["lat"], loc["lng"]
    except Exception as e:
        print(f"[WARN] Geocoding failed for '{location}': {e}")
    return None, None


def search_places(query: str, lat: float, lng: float, radius: int = 5000, max_results: int = 60) -> list:
    """Search places with pagination (each page = 20 results, max 3 pages = 60)."""
    places = []
    url = f"{PLACES_BASE}/nearbysearch/json"
    params = {
        "location": f"{lat},{lng}",
        "radius": radius,
        "keyword": query,
        "key": PLACES_API_KEY,
    }

    while len(places) < max_results:
        try:
            resp = requests.get(url, params=params, proxies=PROXIES, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            places.extend(data.get("results", []))
            next_token = data.get("next_page_token")
            if not next_token or len(places) >= max_results:
                break
            # Google requires 2s delay before next_page_token works
            import time; time.sleep(2)
            params = {"pagetoken": next_token, "key": PLACES_API_KEY}
        except Exception as e:
            print(f"[WARN] Places API request failed: {e}")
            break

    return places[:max_results]


def place_to_item(place: dict, search_query: str, location: str) -> dict:
    """Convert Google Places result to unified item format."""
    place_id = place.get("place_id", "")
    name = place.get("name", "")
    address = place.get("vicinity", "") or place.get("formatted_address", "")
    rating = place.get("rating", 0)
    review_count = place.get("user_ratings_total", 0)
    types = place.get("types", [])
    open_now = place.get("opening_hours", {}).get("open_now")

    url = f"https://www.google.com/maps/place/?q=place_id:{place_id}"

    # Photo reference
    photo_ref = ""
    photos = place.get("photos", [])
    if photos and PLACES_API_KEY:
        ref = photos[0].get("photo_reference", "")
        if ref:
            photo_ref = f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=400&photo_reference={ref}&key={PLACES_API_KEY}"

    # Compose description
    description_parts = [f"Адрес: {address}"]
    if types:
        clean_types = [t.replace("_", " ") for t in types[:5] if t not in ("point_of_interest", "establishment")]
        if clean_types:
            description_parts.append(f"Тип: {', '.join(clean_types)}")
    if open_now is not None:
        description_parts.append("Открыто сейчас" if open_now else "Закрыто сейчас")
    description = " | ".join(description_parts)

    return {
        "video_id": f"maps_{place_id}",
        "url": url,
        "title": name,
        "channel_id": place_id,
        "channel_title": location,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "description": description,
        "tags": types[:8],
        "thumbnail_url": photo_ref,
        "view_count": review_count,
        "like_count": int(rating * 20),  # Normalized: 5.0 rating → 100
        "comment_count": review_count,
        "duration": f"★{rating}" if rating else "N/A",
        "duration_seconds": 0,
        "search_query": search_query,
        # Google Maps extras
        "rating": rating,
        "address": address,
        "place_id": place_id,
    }


def main():
    parser = argparse.ArgumentParser(description="Fetch Google Maps places for lead gen")
    parser.add_argument("--query", required=True, help='Business category, e.g. "yoga studio"')
    parser.add_argument("--location", default="Moscow", help="City or address to search in")
    parser.add_argument("--radius", type=int, default=5000, help="Search radius in meters (default: 5000)")
    parser.add_argument("--days", type=int, default=7, help="Ignored (Google Maps has no date filter)")
    parser.add_argument("--max_videos", type=int, default=60, help="Max places (max 60 per API)")
    args = parser.parse_args()

    if not PLACES_API_KEY:
        print("[ERROR] GOOGLE_PLACES_API_KEY не задан в .env")
        print("  Получите ключ на console.cloud.google.com → Places API")
        sys.exit(1)

    slug = make_slug(f"{args.query}-{args.location}")
    out_dir = os.path.join(".tmp", slug)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "youtube_data.json")

    print(f"Ищу '{args.query}' в '{args.location}' (радиус {args.radius}м)...")

    lat, lng = geocode_location(args.location)
    if lat is None:
        print(f"[ERROR] Не удалось геокодировать '{args.location}'")
        sys.exit(1)
    print(f"  Координаты: {lat:.4f}, {lng:.4f}")

    places = search_places(args.query, lat, lng, radius=args.radius, max_results=args.max_videos)
    items = [place_to_item(p, args.query, args.location) for p in places]
    # Sort by review count (popularity) desc
    items.sort(key=lambda x: x["view_count"], reverse=True)

    result = {
        "query": f"{args.query} в {args.location}",
        "slug": slug,
        "source": "google-maps",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "days_back": 0,
        "total_videos": len(items),
        "total_channels": 1,
        "search_queries": [f"{args.query} @ {args.location}"],
        "videos": items,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Сохранено {len(items)} мест → {out_path}")


if __name__ == "__main__":
    main()
