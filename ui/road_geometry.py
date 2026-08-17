"""
ui/road_geometry.py  (v2 — per-segment persistent cache)
----------------------------------------------------------
OpenRouteService (ORS) integration with a persistent segment-level cache.

Architecture:

  Level 1 — Full route geometry (per vehicle, per run):
    After the solver produces routes, we call ORS once per active vehicle,
    passing all its stops as waypoints. ORS returns the complete road path
    for the entire route. This is used directly by the map renderer.

  Level 2 — Segment geometry cache (persistent across runs):
    We split each full route path at the waypoint boundaries to extract
    the individual road geometry for every consecutive stop-pair segment.
    These segments are stored in a JSON file on disk keyed by stop-ID pairs.

    This cache serves two purposes:
      a) Speed: on subsequent runs, segments we have already fetched load
         instantly from disk without any API call.
      b) Road Blocked feature: when a dispatcher reports a blocked road,
         we look up the saved geometry for the relevant segment to identify
         which road coordinates are affected, then penalise that arc in
         the solver's distance matrix.

    Cache key format: "depot_to_42" or "17_to_83" (string for JSON compat).
    Cache value: list of [lat, lng] pairs tracing the road geometry.

Coordinate convention:
  ORS API uses [longitude, latitude]. Folium uses [latitude, longitude].
  All conversions are explicit and commented. Never assume — always convert.

Getting an ORS API key (free):
  openrouteservice.org → Sign Up → Dashboard → Tokens → copy your key.
  Free tier: 2,000 req/day, 40 req/min. A typical demo run uses 5 calls.
"""

import os
import json
import time
import requests
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd


ORS_URL         = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"
CALL_DELAY_SEC  = 1.6    # 37.5 calls/min — safely below the 40/min limit
CACHE_FILE      = Path(__file__).parent.parent / "route_geometry_cache.json"


# ── Cache persistence ─────────────────────────────────────────────────────────

def _load_cache() -> Dict[str, List]:
    """Read the segment geometry cache from disk. Returns empty dict if missing."""
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, "r") as f:
                data = json.load(f)
            return data
    except Exception as e:
        print(f"ORS cache: could not load {CACHE_FILE}: {e}")
    return {}


def _save_cache(cache: Dict[str, List]) -> None:
    """Write the segment geometry cache to disk."""
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except Exception as e:
        print(f"ORS cache: could not save {CACHE_FILE}: {e}")


def _segment_key(from_id, to_id) -> str:
    """Consistent string key for a directed road segment between two stop IDs."""
    from_str = "depot" if from_id is None else str(int(from_id))
    to_str   = "depot" if to_id   is None else str(int(to_id))
    return f"{from_str}_to_{to_str}"


# ── ORS API call ──────────────────────────────────────────────────────────────

def _call_ors(
    waypoints: List[Tuple[float, float]],
    api_key:   str,
    label:     str = "route",
) -> Optional[List[List[float]]]:
    """
    Call ORS with a list of (lat, lng) waypoints.
    Returns a list of [lat, lng] pairs in Folium format, or None on failure.

    ORS expects [longitude, latitude] in the request body.
    ORS returns [longitude, latitude] in the GeoJSON response.
    We convert to [latitude, longitude] for Folium before returning.
    """
    if len(waypoints) < 2:
        return None

    # Convert (lat, lng) → [lng, lat] for ORS
    ors_coords = [[lng, lat] for lat, lng in waypoints]

    try:
        resp = requests.post(
            ORS_URL,
            headers={
                "Authorization": api_key,
                "Content-Type":  "application/json",
                "Accept":        "application/geo+json",
            },
            json={"coordinates": ors_coords},
            timeout=20,
        )

        if resp.status_code == 200:
            coords = resp.json()["features"][0]["geometry"]["coordinates"]
            # Convert [lng, lat] → [lat, lng] for Folium
            result = [[lat, lng] for lng, lat in coords]
            print(f"  ORS {label}: {len(result)} road points")
            return result

        print(f"  ORS {label}: HTTP {resp.status_code} — using straight line")
        return None

    except Exception as e:
        print(f"  ORS {label}: {e} — using straight line")
        return None


# ── Geometry splitting ────────────────────────────────────────────────────────

def _find_nearest_index(
    geometry: List[List[float]],
    target_lat: float,
    target_lng: float,
    search_start: int = 0,
) -> int:
    """
    Find the index in `geometry` closest to (target_lat, target_lng).

    We search forward from `search_start` rather than scanning the whole array.
    This works because waypoints appear in the geometry in the same order we
    passed them to ORS — the path is directional. Searching forward ensures we
    find the NEXT occurrence of a waypoint, not an earlier re-visit.

    Uses squared Euclidean distance (no trig needed for close points).
    """
    best_idx  = search_start
    best_dist = float("inf")

    # Search a window of up to 300 points ahead to keep this fast
    end = min(len(geometry), search_start + 300)
    for i in range(search_start, end):
        dlat = geometry[i][0] - target_lat
        dlng = geometry[i][1] - target_lng
        dist = dlat * dlat + dlng * dlng
        if dist < best_dist:
            best_dist = dist
            best_idx  = i

    return best_idx


def _split_route_into_segments(
    full_geometry: List[List[float]],
    waypoints:     List[Tuple[float, float]],
    waypoint_ids:  List,    # stop_id for each waypoint (None = depot)
) -> Dict[str, List[List[float]]]:
    """
    Split a full ORS route geometry into per-segment portions.

    The full geometry is a continuous sequence of road points that passes
    through every waypoint. We find where each waypoint appears in the
    geometry array and slice between consecutive waypoint indices.

    Example with 3 stops:
      geometry:   [depot, ..., stop_1, ..., stop_2, ..., stop_3, ..., depot]
      segments:   depot→stop_1, stop_1→stop_2, stop_2→stop_3, stop_3→depot

    Returns a dict of {segment_key: [lat_lng_list]} for every consecutive pair.
    """
    segments    = {}
    search_from = 0

    # Find the geometry index for each waypoint
    waypoint_indices = []
    for lat, lng in waypoints:
        idx = _find_nearest_index(full_geometry, lat, lng, search_from)
        waypoint_indices.append(idx)
        search_from = idx   # next waypoint must come after this one

    # Slice between consecutive waypoint indices
    for i in range(len(waypoints) - 1):
        from_id  = waypoint_ids[i]
        to_id    = waypoint_ids[i + 1]
        key      = _segment_key(from_id, to_id)
        idx_from = waypoint_indices[i]
        idx_to   = waypoint_indices[i + 1]

        # Include a couple of extra points at each end for smooth visual joins
        segment = full_geometry[max(0, idx_from): idx_to + 2]
        if len(segment) >= 2:
            segments[key] = segment

    return segments


# ── Main public API ───────────────────────────────────────────────────────────

def fetch_all_route_geometries(
    result:   dict,
    stops_df: pd.DataFrame,
    depot:    dict,
    vehicles: pd.DataFrame,
    api_key:  Optional[str] = None,
) -> Dict[int, List[List[float]]]:
    """
    Fetch road-following geometry for all vehicle routes. Uses the persistent
    segment cache to avoid redundant API calls. Only calls ORS for segments
    that have never been seen before.

    Returns:
      full_routes dict: {vehicle_id: full_road_geometry_list}  — used by map renderer
      Side effect: updates the persistent segment cache on disk with any new segments.
    """
    key    = api_key or os.environ.get("ORS_API_KEY", "").strip()
    routes = result.get("routes", {})

    if not key:
        print("ORS: No API key. Route lines will be straight.")
        return {}

    # Load the persistent segment cache from disk
    seg_cache = _load_cache()
    stops_lu  = stops_df.set_index("stop_id")

    full_routes: Dict[int, List[List[float]]] = {}
    cache_updated = False

    print(f"ORS: Processing geometry for {sum(1 for r in routes.values() if r['stop_sequence'])} vehicles...")

    for v_id, route in routes.items():
        sequence = route.get("stop_sequence", [])
        if not sequence:
            continue

        v_name = vehicles.iloc[v_id]["name"] if v_id < len(vehicles) else f"V{v_id}"

        # Build ordered waypoints for this vehicle:
        # depot → stop_1 → stop_2 → ... → stop_N → depot
        waypoints:    List[Tuple[float, float]] = [(depot["lat"], depot["lng"])]
        waypoint_ids: List                      = [None]  # None = depot

        for stop_id in sequence:
            sid = int(stop_id)
            if sid in stops_lu.index:
                row = stops_lu.loc[sid]
                waypoints.append((float(row["lat"]), float(row["lng"])))
                waypoint_ids.append(sid)

        waypoints.append((depot["lat"], depot["lng"]))
        waypoint_ids.append(None)  # return-to-depot

        # Check how many segments are already in the cache
        segment_keys  = [
            _segment_key(waypoint_ids[i], waypoint_ids[i + 1])
            for i in range(len(waypoints) - 1)
        ]
        cached_segs   = [k for k in segment_keys if k in seg_cache]
        missing_segs  = [k for k in segment_keys if k not in seg_cache]

        print(f"  {v_name}: {len(cached_segs)} cached, {len(missing_segs)} new segments")

        if missing_segs:
            # Need to call ORS — this vehicle has at least one new segment
            full_geom = _call_ors(waypoints, key, v_name)
            time.sleep(CALL_DELAY_SEC)

            if full_geom:
                # Split the full geometry into individual segments and cache them
                new_segments = _split_route_into_segments(
                    full_geom, waypoints, waypoint_ids
                )
                seg_cache.update(new_segments)
                cache_updated = True

                # Reconstruct the full route path from the cached segments
                full_path = []
                for seg_key in segment_keys:
                    if seg_key in seg_cache:
                        seg = seg_cache[seg_key]
                        # Avoid duplicating the junction point between segments
                        if full_path:
                            full_path.extend(seg[1:])
                        else:
                            full_path.extend(seg)
                full_routes[v_id] = full_path
            else:
                # ORS failed — stitch together any cached segments we do have,
                # use straight lines only where the cache is missing
                full_path = []
                for i, seg_key in enumerate(segment_keys):
                    if seg_key in seg_cache:
                        seg = seg_cache[seg_key]
                        if full_path:
                            full_path.extend(seg[1:])
                        else:
                            full_path.extend(seg)
                    else:
                        # Straight-line fallback for this segment only
                        from_pt = [waypoints[i][0],     waypoints[i][1]]
                        to_pt   = [waypoints[i + 1][0], waypoints[i + 1][1]]
                        if full_path:
                            full_path.append(to_pt)
                        else:
                            full_path.extend([from_pt, to_pt])
                full_routes[v_id] = full_path if full_path else None
        else:
            # All segments are cached — reconstruct from cache instantly
            full_path = []
            for seg_key in segment_keys:
                seg = seg_cache[seg_key]
                if full_path:
                    full_path.extend(seg[1:])
                else:
                    full_path.extend(seg)
            full_routes[v_id] = full_path

    # Persist any new segments back to disk
    if cache_updated:
        _save_cache(seg_cache)
        print(f"ORS: Cache updated — {len(seg_cache)} total segments stored.")

    return full_routes


def build_geometry_for_result(
    result:   dict,
    stops_df: pd.DataFrame,
    depot:    dict,
    vehicles: pd.DataFrame,
    api_key:  Optional[str] = None,
) -> Dict[int, List[List[float]]]:
    """
    Build road-following geometry for any solver result using the segment cache.

    This is the function used for re-solved results (after a dispatcher blocks
    a customer or a road) and for Point C insertion confirmation maps. Unlike
    fetch_all_route_geometries() which always calls ORS once per vehicle, this
    function first tries to assemble the full path purely from cached segments.
    Only segments that are genuinely missing from the cache trigger API calls.

    Why this is fast for adjusted results:
      After the original optimisation run, the segment cache contains the road
      geometry for every consecutive stop pair in those routes. A re-solve that
      removes one stop or blocks one road changes only a few adjacencies out of
      roughly 125 total. The function stitches together all the cached segments
      instantly and makes targeted ORS calls only for the two or three new pairs.
      This typically takes two to five seconds rather than the full 8-10 seconds
      of fetching geometry from scratch.

    The returned dict has the same shape as the original geometry_cache:
      {vehicle_id: [[lat, lng], [lat, lng], ...]}
    So it can be passed directly to build_optimized_map() as geometry_cache.
    """
    key      = api_key or os.environ.get("ORS_API_KEY", "").strip()
    routes   = result.get("routes", {})
    stops_lu = stops_df.set_index("stop_id")

    # Load the persistent cache — may already contain most or all segments
    seg_cache     = _load_cache()
    full_routes: Dict[int, List[List[float]]] = {}
    cache_updated = False

    # Collect all missing segments across all vehicles before making API calls
    # so we can report clearly what is happening
    total_missing = 0
    for route in routes.values():
        sequence = route.get("stop_sequence", [])
        if not sequence:
            continue
        ids = [None] + [int(s) for s in sequence] + [None]
        for i in range(len(ids) - 1):
            if _segment_key(ids[i], ids[i+1]) not in seg_cache:
                total_missing += 1

    if total_missing > 0:
        if key:
            print(f"ORS: {total_missing} new segment(s) in adjusted result — fetching...")
        else:
            print(f"ORS: {total_missing} new segment(s) but no API key — using straight lines for those.")

    for v_id, route in routes.items():
        sequence = route.get("stop_sequence", [])
        if not sequence:
            continue

        v_name       = vehicles.iloc[v_id]["name"] if v_id < len(vehicles) else f"V{v_id}"
        waypoints    = [(depot["lat"], depot["lng"])]
        waypoint_ids = [None]

        for stop_id in sequence:
            sid = int(stop_id)
            if sid in stops_lu.index:
                row = stops_lu.loc[sid]
                waypoints.append((float(row["lat"]), float(row["lng"])))
                waypoint_ids.append(sid)

        waypoints.append((depot["lat"], depot["lng"]))
        waypoint_ids.append(None)

        segment_keys = [
            _segment_key(waypoint_ids[i], waypoint_ids[i + 1])
            for i in range(len(waypoints) - 1)
        ]
        missing_keys = [k for k in segment_keys if k not in seg_cache]

        # For any missing segments, fetch them individually via ORS.
        # We fetch segment by segment rather than the full route because:
        #   a) We only need the missing pieces, not the whole route again.
        #   b) Individual segment calls are smaller and faster per call.
        #   c) We can immediately cache each new segment as it arrives.
        if missing_keys and key:
            for i, seg_key in enumerate(segment_keys):
                if seg_key not in seg_cache:
                    from_wp = waypoints[i]
                    to_wp   = waypoints[i + 1]
                    geom    = _call_ors([from_wp, to_wp], key, label=seg_key)
                    time.sleep(CALL_DELAY_SEC)
                    if geom:
                        seg_cache[seg_key] = geom
                        cache_updated = True

        # Stitch together the full path from cached segments.
        # For any segment still missing (no API key, or ORS failed), fall back
        # to a straight line between the two waypoint coordinates.
        full_path = []
        for i, seg_key in enumerate(segment_keys):
            if seg_key in seg_cache:
                seg = seg_cache[seg_key]
                if full_path:
                    full_path.extend(seg[1:])   # skip duplicate junction point
                else:
                    full_path.extend(seg)
            else:
                # Straight-line fallback for this one segment only
                from_pt = [waypoints[i][0], waypoints[i][1]]
                to_pt   = [waypoints[i+1][0], waypoints[i+1][1]]
                if full_path:
                    full_path.append(to_pt)
                else:
                    full_path.extend([from_pt, to_pt])

        if full_path:
            full_routes[v_id] = full_path
            cached_count  = sum(1 for k in segment_keys if k in seg_cache)
            missing_count = len(segment_keys) - cached_count
            print(f"  {v_name}: {cached_count} cached, {missing_count} straight-line fallback")

    if cache_updated:
        _save_cache(seg_cache)
        print(f"ORS: Segment cache updated — {len(seg_cache)} total segments stored.")

    return full_routes


def fetch_new_segments_only(
    from_to_pairs: List[Tuple],   # list of (from_stop_id_or_None, to_stop_id_or_None, from_lat, from_lng, to_lat, to_lng)
    api_key: Optional[str] = None,
) -> Dict[str, List[List[float]]]:
    """
    Fetch geometry only for specific new segments — used after a re-solve or
    Point C insertion when only a handful of new segments appear in the routes.

    Each item in from_to_pairs is a tuple of:
      (from_id, to_id, from_lat, from_lng, to_lat, to_lng)

    Returns a dict of {segment_key: geometry} for the newly fetched segments,
    and updates the persistent cache on disk.
    """
    key = api_key or os.environ.get("ORS_API_KEY", "").strip()
    if not key:
        return {}

    seg_cache     = _load_cache()
    new_segments  = {}
    cache_updated = False

    for from_id, to_id, from_lat, from_lng, to_lat, to_lng in from_to_pairs:
        seg_key = _segment_key(from_id, to_id)
        if seg_key in seg_cache:
            continue  # already cached — skip

        waypoints = [(from_lat, from_lng), (to_lat, to_lng)]
        geom = _call_ors(waypoints, key, label=seg_key)
        time.sleep(CALL_DELAY_SEC)

        if geom:
            seg_cache[seg_key]   = geom
            new_segments[seg_key] = geom
            cache_updated         = True

    if cache_updated:
        _save_cache(seg_cache)

    return new_segments


def get_segment_geometry(
    from_id,   # stop_id or None for depot
    to_id,     # stop_id or None for depot
) -> Optional[List[List[float]]]:
    """
    Look up geometry for a specific segment from the persistent cache.
    Returns None if the segment has not been cached yet.
    Used by the Road Blocked feature to identify which road coordinates to penalise.
    """
    seg_cache = _load_cache()
    return seg_cache.get(_segment_key(from_id, to_id))


def geometry_available(geometry_cache: Optional[Dict]) -> bool:
    """True if a non-empty vehicle geometry cache has been fetched this session."""
    return bool(geometry_cache)


def estimate_call_count(result: dict) -> int:
    """
    Estimate how many ORS API calls will be needed for this result.
    Checks the persistent cache and counts only segments not already stored.
    """
    seg_cache = _load_cache()
    new_count = 0

    for v_id, route in result.get("routes", {}).items():
        sequence = route.get("stop_sequence", [])
        if not sequence:
            continue
        # Count segments: depot→first, consecutive pairs, last→depot
        all_ids = [None] + [int(s) for s in sequence] + [None]
        for i in range(len(all_ids) - 1):
            key = _segment_key(all_ids[i], all_ids[i + 1])
            if key not in seg_cache:
                new_count += 1

    # One ORS call per vehicle (multi-waypoint), not one per segment
    active_vehicles = sum(1 for r in result.get("routes", {}).values() if r.get("stop_sequence"))
    # If any vehicle has new segments, we need one call for that vehicle
    return min(active_vehicles, new_count)





