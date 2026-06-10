"""
ui/animation.py
---------------
Simulated GPS tracking animation for the Route Optimizer demo.

This module handles all the frame-by-frame computation for the animation.
The core idea is straightforward: the OR-Tools solver already computed
exact arrival and departure times for every stop on every vehicle. We use
those times as keyframes — known positions at known moments — and interpolate
vehicle positions smoothly between them.

Think of it like animation in traditional film. A keyframe animator draws
the character at position A (frame 1) and position B (frame 24), then the
assistant animators fill in frames 2-23 by interpolating between them. We
do exactly the same thing: the solver's arrival times are our keyframes,
and we interpolate geographic positions between stops.

The animation compresses the full 8.5-hour delivery shift into a 45-second
playback. One real second represents approximately 11 minutes of delivery
time (510 minutes / 45 seconds ≈ 11.3x compression). This is fast enough
to be engaging but slow enough that a client can see individual vehicles
stopping at delivery points and the stops turning green one by one.

Architecture:
  build_animation_frames() — pre-computes the state at every time step.
    This runs once when the Play button is clicked, not on every frame.
    Doing it upfront means the actual animation loop is just displaying
    pre-computed frames rather than computing and displaying simultaneously,
    which makes the playback smoother.

  build_frame_map() — takes a single pre-computed frame and renders it
    as a Folium map with vehicle markers at their current positions,
    completed stops shown as green, and pending stops in their original
    urgency colours.
"""

import folium
import numpy as np
import pandas as pd
from typing import List, Dict, Tuple, Optional
from math import radians, sin, cos, sqrt, atan2

from ui.map_view import (
    TILE_URL, TILE_ATTR, ATTRIBUTION_CSS,
    VEHICLE_COLORS, LEGEND_OPTIMIZED_HTML,
)


# ── Animation parameters ───────────────────────────────────────────────────────
ANIMATION_DURATION_SEC = 45    # how long the playback lasts in real seconds
FRAMES_PER_SECOND      = 2     # how many frames we render per real second
SHIFT_DURATION_MIN     = 510   # total minutes in a working shift (8h + 30min lunch)

# Total number of frames in the animation
TOTAL_FRAMES = ANIMATION_DURATION_SEC * FRAMES_PER_SECOND  # 90 frames

# How many simulated minutes each frame represents
MINUTES_PER_FRAME = SHIFT_DURATION_MIN / TOTAL_FRAMES  # ~5.67 min per frame

# Vehicle icon sizes and styles — slightly larger than stop markers so they
# stand out as "moving objects" against the static stop dots
VEHICLE_ICON_SIZE = 14

SHIFT_START_HOUR = 8   # 08:00 — used for clock display


def _haversine_km(lat1, lng1, lat2, lng2) -> float:
    """Standard great-circle distance formula."""
    R = 6371
    lat1, lng1, lat2, lng2 = map(radians, [lat1, lng1, lat2, lng2])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlng/2)**2
    return 2 * R * atan2(sqrt(a), sqrt(1-a))


def _interpolate_position(
    from_lat: float, from_lng: float,
    to_lat:   float, to_lng:   float,
    fraction: float,                   # 0.0 = at from, 1.0 = at to
) -> Tuple[float, float]:
    """
    Linear interpolation between two geographic coordinates.

    For short distances within a city, linear interpolation is perfectly
    adequate — the curvature of the Earth is negligible at the scale of
    Bengaluru. The vehicle appears to slide smoothly along the straight
    line between two stops, which is close enough to reality given we
    are not using actual road network data.
    """
    fraction = max(0.0, min(1.0, fraction))
    lat = from_lat + (to_lat - from_lat) * fraction
    lng = from_lng + (to_lng - from_lng) * fraction
    return lat, lng


def _minutes_to_clock(minutes_from_start: float) -> str:
    """Convert minutes from shift start to HH:MM display format."""
    total = SHIFT_START_HOUR * 60 + minutes_from_start
    return f"{int(total // 60):02d}:{int(total % 60):02d}"


# ── Frame pre-computation ──────────────────────────────────────────────────────

def build_animation_frames(
    result:   dict,
    stops_df: pd.DataFrame,
    depot:    dict,
    vehicles: pd.DataFrame,
) -> List[Dict]:
    """
    Pre-compute the complete animation as a list of frame state dicts.

    Each frame describes the full state of the simulation at that moment:
    where each vehicle is, which stops are complete, and what the
    aggregate metrics look like. Building all frames upfront (rather than
    computing each frame during playback) means the animation loop is
    just iterating through a list, which is much faster than doing
    geometry calculations on every render cycle.

    A frame dict has the following structure:
      sim_time_min: float          — simulated minutes from shift start
      clock_str:    str            — "HH:MM" display time
      vehicle_positions: dict      — {v_id: (lat, lng)} for each active vehicle
      completed_stop_ids: set      — stop IDs that have been delivered
      in_progress: dict            — {v_id: "stop_name"} if currently unloading
      total_completed: int         — count of completed deliveries
      total_km: float              — aggregate distance driven so far
      frame_number: int
    """
    routes   = result["routes"]
    stops_lu = stops_df.set_index("stop_id")

    # Build a per-vehicle timeline: a sorted list of (time, event) pairs where
    # each event is either "depart_depot", "arrive_stop", "depart_stop", or "return_depot"
    # This is the keyframe data we interpolate between.
    vehicle_timelines = {}

    for v_id, route in routes.items():
        sequence = route["stop_sequence"]
        arrivals = route["arrivals"]
        if not sequence:
            vehicle_timelines[v_id] = []
            continue

        timeline = []
        prev_lat, prev_lng = depot["lat"], depot["lng"]

        for stop_id in sequence:
            sid = int(stop_id)
            if sid not in stops_lu.index:
                continue
            row       = stops_lu.loc[sid]
            arr_min   = float(arrivals.get(sid, 0))
            svc_min   = int(row["service_time_min"])
            dep_min   = arr_min + svc_min

            timeline.append({
                "type":       "stop",
                "stop_id":    sid,
                "stop_name":  str(row["name"]),
                "lat":        float(row["lat"]),
                "lng":        float(row["lng"]),
                "arrive_min": arr_min,
                "depart_min": dep_min,
                "prev_lat":   prev_lat,
                "prev_lng":   prev_lng,
            })
            prev_lat, prev_lng = float(row["lat"]), float(row["lng"])

        # Add return-to-depot as the final "stop"
        if timeline:
            last_dep = timeline[-1]["depart_min"]
            travel_home = (_haversine_km(prev_lat, prev_lng,
                                          depot["lat"], depot["lng"])
                           / 25.0) * 60
            timeline.append({
                "type":       "depot",
                "stop_id":    -1,
                "stop_name":  "Depot",
                "lat":        depot["lat"],
                "lng":        depot["lng"],
                "arrive_min": last_dep + travel_home,
                "depart_min": last_dep + travel_home,
                "prev_lat":   prev_lat,
                "prev_lng":   prev_lng,
            })

        vehicle_timelines[v_id] = timeline

    # Build per-vehicle cumulative distance timeline for the metrics panel.
    # We calculate total km driven by each vehicle up to any given sim time.
    vehicle_distances = {}
    for v_id, timeline in vehicle_timelines.items():
        segs = []
        for event in timeline:
            dist = _haversine_km(event["prev_lat"], event["prev_lng"],
                                  event["lat"], event["lng"])
            segs.append((event["arrive_min"], dist))
        vehicle_distances[v_id] = segs

    # ── Main frame loop ────────────────────────────────────────────────────────
    frames = []

    for frame_num in range(TOTAL_FRAMES + 1):
        sim_time = frame_num * MINUTES_PER_FRAME

        vehicle_positions  = {}
        in_progress        = {}
        completed_stop_ids = set()
        total_km           = 0.0

        for v_id, timeline in vehicle_timelines.items():
            if not timeline:
                vehicle_positions[v_id] = (depot["lat"], depot["lng"])
                continue

            # Determine where this vehicle is at sim_time by finding which
            # segment of its timeline we are currently in.
            # A segment is the period between departing one location and
            # arriving at the next.

            # First, collect all stops that have been fully completed
            for event in timeline:
                if event["type"] == "stop" and event["depart_min"] <= sim_time:
                    completed_stop_ids.add(event["stop_id"])

            # Now find the vehicle's current position
            pos_found = False

            for i, event in enumerate(timeline):
                if sim_time < event["arrive_min"]:
                    # Vehicle is travelling toward this event's location
                    # Interpolate between previous location and this one
                    travel_start = timeline[i-1]["depart_min"] if i > 0 else 0.0
                    travel_end   = event["arrive_min"]
                    travel_dur   = travel_end - travel_start

                    if travel_dur > 0:
                        fraction = (sim_time - travel_start) / travel_dur
                    else:
                        fraction = 1.0

                    lat, lng = _interpolate_position(
                        event["prev_lat"], event["prev_lng"],
                        event["lat"],      event["lng"],
                        fraction,
                    )
                    vehicle_positions[v_id] = (lat, lng)
                    pos_found = True
                    break

                elif event["arrive_min"] <= sim_time <= event["depart_min"]:
                    # Vehicle is currently at this stop — stationary, unloading
                    vehicle_positions[v_id] = (event["lat"], event["lng"])
                    if event["type"] == "stop":
                        in_progress[v_id] = event["stop_name"]
                    pos_found = True
                    break

            if not pos_found:
                # Vehicle has finished its route and returned to depot
                vehicle_positions[v_id] = (depot["lat"], depot["lng"])

            # Accumulate distance driven by this vehicle up to sim_time
            for arrive_min, dist_km in vehicle_distances.get(v_id, []):
                if arrive_min <= sim_time:
                    total_km += dist_km

        frames.append({
            "frame_number":       frame_num,
            "sim_time_min":       sim_time,
            "clock_str":          _minutes_to_clock(sim_time),
            "vehicle_positions":  vehicle_positions,
            "completed_stop_ids": completed_stop_ids,
            "in_progress":        in_progress,
            "total_completed":    len(completed_stop_ids),
            "total_km":           round(total_km, 1),
        })

    return frames


# ── Frame map renderer ─────────────────────────────────────────────────────────

def build_frame_map(
    frame:    dict,
    stops_df: pd.DataFrame,
    depot:    dict,
    result:   dict,
) -> folium.Map:
    """
    Render a single animation frame as a Folium map.

    The map shows three categories of stops distinguished by colour:
    - Green filled circle: delivery completed (stop_id in completed_stop_ids)
    - Original urgency colour (blue/yellow/orange/red): pending delivery
    - Vehicle markers: coloured squares at their interpolated positions

    The vehicle markers are implemented as DivIcons — small HTML squares
    in the vehicle's colour with a brief label. Using squares rather than
    circles distinguishes them from stop markers at a glance, even when
    they happen to be positioned close to a stop.
    """
    m = folium.Map(
        location=[12.9716, 77.5946],
        zoom_start=12,
        tiles=TILE_URL,
        attr=TILE_ATTR,
    )
    m.get_root().html.add_child(folium.Element(ATTRIBUTION_CSS))

    completed = frame["completed_stop_ids"]
    routes    = result["routes"]

    # Draw thin route lines as a faded background — this gives spatial context
    # so the client can see where vehicles are headed, not just where they are.
    for v_id, route in routes.items():
        if not route["stop_sequence"]:
            continue
        color    = VEHICLE_COLORS[v_id % len(VEHICLE_COLORS)]
        stops_lu = stops_df.set_index("stop_id")
        path     = [[depot["lat"], depot["lng"]]]
        for sid in route["stop_sequence"]:
            sid = int(sid)
            if sid in stops_lu.index:
                row = stops_lu.loc[sid]
                path.append([float(row["lat"]), float(row["lng"])])
        path.append([depot["lat"], depot["lng"]])
        folium.PolyLine(
            locations=path,
            color=color,
            weight=2,
            opacity=0.25,   # faded — vehicles and stops are the focus
        ).add_to(m)

    # Draw stop markers — green for completed, original colour for pending
    def _urgency_color(row) -> str:
        if row["is_slow_client"]:              return "red"
        if row["is_priority"]:                 return "orange"
        if row["window_label"] != "Flexible":  return "cadetblue"
        return "#1f77b4"

    for _, row in stops_df.iterrows():
        sid = int(row["stop_id"])
        if sid == 9999:  # skip synthetic urgent stop if present
            continue

        if sid in completed:
            # Completed stop — small solid green circle with a tick
            folium.CircleMarker(
                location=[float(row["lat"]), float(row["lng"])],
                radius=5,
                color="#2e7d32",
                fill=True,
                fill_color="#4caf50",
                fill_opacity=0.9,
                tooltip=f"✓ {row['name']}",
            ).add_to(m)
        else:
            # Pending stop — original urgency colour, slightly transparent
            color = _urgency_color(row)
            folium.CircleMarker(
                location=[float(row["lat"]), float(row["lng"])],
                radius=5,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.5,
                tooltip=row["name"],
            ).add_to(m)

    # Draw vehicle markers at their current interpolated positions
    for v_id, (v_lat, v_lng) in frame["vehicle_positions"].items():
        color    = VEHICLE_COLORS[v_id % len(VEHICLE_COLORS)]
        v_label  = f"V{v_id + 1}"
        is_busy  = v_id in frame.get("in_progress", {})
        # Pulsing border when vehicle is unloading — visual cue for activity
        border   = "3px solid white" if is_busy else f"2px solid {color}"
        bg       = color if not is_busy else "#fff"
        txt_col  = "white" if not is_busy else color

        icon_html = (
            f'<div style="background:{bg};border:{border};'
            f'border-radius:4px;width:{VEHICLE_ICON_SIZE}px;'
            f'height:{VEHICLE_ICON_SIZE}px;line-height:{VEHICLE_ICON_SIZE}px;'
            f'text-align:center;font-size:8px;font-weight:900;'
            f'color:{txt_col};box-shadow:0 1px 4px rgba(0,0,0,.4)">'
            f'{v_label}</div>'
        )
        status = f"🔴 Unloading at {frame['in_progress'][v_id]}" if is_busy else "🟢 En route"
        folium.Marker(
            location=[v_lat, v_lng],
            icon=folium.DivIcon(
                html=icon_html,
                icon_size=(VEHICLE_ICON_SIZE + 4, VEHICLE_ICON_SIZE + 4),
                icon_anchor=((VEHICLE_ICON_SIZE + 4) // 2,
                              (VEHICLE_ICON_SIZE + 4) // 2),
            ),
            tooltip=f"Vehicle {v_id + 1} — {status}",
        ).add_to(m)

    # Depot marker
    folium.Marker(
        location=[depot["lat"], depot["lng"]],
        tooltip="Depot — Central Warehouse",
        icon=folium.Icon(color="black", icon="home", prefix="glyphicon"),
    ).add_to(m)

    # Overlay: current time and completion stats in the top-left corner.
    # This is what makes the animation feel like a live tracking dashboard.
    stats_html = f"""
    <div style="position:fixed;top:12px;left:12px;z-index:2000;
                background:rgba(0,0,0,0.75);color:white;
                padding:10px 14px;border-radius:8px;
                font-family:monospace;font-size:13px;line-height:1.7">
        🕐 <b>{frame['clock_str']}</b><br>
        📦 <b>{frame['total_completed']}</b> deliveries completed<br>
        🚛 <b>{frame['total_km']:.1f} km</b> driven
    </div>"""
    m.get_root().html.add_child(folium.Element(stats_html))

    return m
