"""
optimizer/baseline.py
---------------------
Implements the naive baseline routing that represents what a dispatcher
does manually today: divide the city into geographic zones, assign one
vehicle per zone, then sequence stops within each zone by nearest-neighbour.

Why this matters for the demo:
  The optimizer's output only looks impressive when compared against something.
  This baseline is deliberately "reasonable but flawed" — not completely random,
  because a real dispatcher isn't completely random either, but also not optimal.
  It's the honest representation of current-state operations.

Key flaws the baseline has that the optimizer will fix:
  1. It ignores time windows entirely — stops are sequenced by proximity,
     not by when the customer needs them.
  2. It ignores vehicle capacity — a zone might get more load than the
     assigned vehicle can carry.
  3. It creates route crossings — vehicles from different zones often
     pass through each other's territory to reach outlier stops.
  4. It produces uneven workloads — some drivers finish hours early
     while others go into overtime.
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Tuple
from math import radians, sin, cos, sqrt, atan2


# ── Haversine Distance ────────────────────────────────────────────────────────
def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Calculate the great-circle distance in kilometres between two coordinates.
    This is the standard formula for geographic distance on a sphere.
    We use it everywhere in the project for consistency — not driving distance,
    but for a demo it's close enough and requires no API calls.
    """
    R = 6371  # Earth's radius in km
    lat1, lng1, lat2, lng2 = map(radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))


def nearest_neighbour_sequence(
    stops: pd.DataFrame,
    depot_lat: float,
    depot_lng: float,
) -> List[int]:
    """
    Given a set of stops, find a visitation order using the nearest-neighbour
    heuristic: always go to the closest unvisited stop next.

    This is the classic "travelling salesman" approximation that most
    manual dispatchers intuitively apply. It's fast to compute and
    produces routes that look reasonable on a map but are rarely optimal —
    crucially, it ignores time windows completely.

    Returns a list of stop_ids in the order they should be visited.
    """
    unvisited = stops.copy()
    sequence  = []
    current_lat, current_lng = depot_lat, depot_lng

    while not unvisited.empty:
        # Calculate distance from current position to all remaining stops
        distances = unvisited.apply(
            lambda r: haversine_km(current_lat, current_lng, r["lat"], r["lng"]),
            axis=1
        )
        # Pick the closest one
        nearest_idx = distances.idxmin()
        nearest_row = unvisited.loc[nearest_idx]
        sequence.append(int(nearest_row["stop_id"]))
        current_lat  = nearest_row["lat"]
        current_lng  = nearest_row["lng"]
        unvisited    = unvisited.drop(nearest_idx)

    return sequence


def run_baseline(
    stops_df:  pd.DataFrame,
    vehicles:  pd.DataFrame,
    depot:     dict,
    avg_speed_kmh: float = 25.0,  # Bengaluru city average — deliberately conservative
) -> Dict:
    """
    Run the naive baseline routing and return a structured result dict
    that mirrors the shape of what solver.py returns, so metrics.py
    can process both with the same code.

    The assignment logic:
      1. Sort vehicles by capacity descending (give biggest zones to biggest vehicles).
      2. Divide stops into N geographic sectors using the depot as the centre
         and assigning each stop to its closest vehicle's "home quadrant."
      3. Within each sector, sequence by nearest-neighbour from the depot.
      4. Ignore capacity violations — the baseline "doesn't check" (which is
         realistic; many dispatchers don't either until a driver calls in overloaded).
    """
    depot_lat = depot["lat"]
    depot_lng = depot["lng"]
    num_vehicles = len(vehicles)

    # ── Step 1: Assign each stop to a zone based on bearing from depot ────────
    # We divide the compass into equal sectors, one per vehicle.
    # This is the geographic-zone approach most manual dispatchers use.
    def bearing_to_sector(lat, lng) -> int:
        """Convert a stop's compass bearing from the depot into a sector index."""
        dlat = lat - depot_lat
        dlng = lng - depot_lng
        # atan2 gives bearing in radians; convert to 0-360 degrees
        bearing = (np.degrees(np.arctan2(dlng, dlat)) + 360) % 360
        # Map bearing to one of N equal sectors
        sector = int(bearing / (360 / num_vehicles)) % num_vehicles
        return sector

    stops_df = stops_df.copy()
    stops_df["vehicle_id"] = stops_df.apply(
        lambda r: bearing_to_sector(r["lat"], r["lng"]), axis=1
    )

    # ── Step 2: Sequence each vehicle's stops by nearest-neighbour ────────────
    routes = {}

    for vehicle_id in range(num_vehicles):
        vehicle_stops = stops_df[stops_df["vehicle_id"] == vehicle_id]

        if vehicle_stops.empty:
            routes[vehicle_id] = {
                "stop_sequence":    [],
                "total_distance_km": 0.0,
                "total_time_min":   0.0,
                "load_kg":          0.0,
                "tw_violations":    0,
                "overtime_min":     0.0,
                "arrivals":         {},
            }
            continue

        # Sequence the stops
        sequence = nearest_neighbour_sequence(vehicle_stops, depot_lat, depot_lng)

        # ── Step 3: Compute route metrics ─────────────────────────────────────
        # Simulate driving the route and track time, distance, and window violations.
        total_distance = 0.0
        total_time_min = 0.0   # Minutes elapsed since shift start (08:00)
        tw_violations  = 0
        arrivals       = {}    # stop_id → arrival time in minutes from shift start
        prev_lat, prev_lng = depot_lat, depot_lng
        stop_lookup = vehicle_stops.set_index("stop_id")

        for stop_id in sequence:
            row      = stop_lookup.loc[stop_id]
            dist_km  = haversine_km(prev_lat, prev_lng, row["lat"], row["lng"])
            travel   = (dist_km / avg_speed_kmh) * 60  # minutes
            total_distance += dist_km
            total_time_min += travel

            # Arrival time in hours from shift start (for window comparison)
            arrival_hr = total_time_min / 60
            arrivals[stop_id] = total_time_min

            # Check time window — baseline ignores windows during sequencing
            # so violations are expected and that's exactly the point
            tw_start = row["tw_start"]
            tw_end   = row["tw_end"]
            if arrival_hr < tw_start or arrival_hr > tw_end:
                tw_violations += 1

            # Add service time (unloading) at stop
            total_time_min += row["service_time_min"]
            prev_lat, prev_lng = row["lat"], row["lng"]

        # Return trip to depot
        return_dist = haversine_km(prev_lat, prev_lng, depot_lat, depot_lng)
        total_distance  += return_dist
        total_time_min  += (return_dist / avg_speed_kmh) * 60

        # Overtime: anything beyond 8 hours (480 minutes) + 30 min lunch
        max_shift_min  = (8 * 60) + 30
        overtime_min   = max(0.0, total_time_min - max_shift_min)

        routes[vehicle_id] = {
            "stop_sequence":     sequence,
            "total_distance_km": round(total_distance, 2),
            "total_time_min":    round(total_time_min, 1),
            "load_kg":           round(vehicle_stops["weight_kg"].sum(), 1),
            "tw_violations":     tw_violations,
            "overtime_min":      round(overtime_min, 1),
            "arrivals":          arrivals,
        }

    # ── Step 4: Aggregate summary ─────────────────────────────────────────────
    total_dist     = sum(r["total_distance_km"] for r in routes.values())
    total_overtime = sum(r["overtime_min"]      for r in routes.values())
    total_violations = sum(r["tw_violations"]   for r in routes.values())
    total_stops_served = sum(len(r["stop_sequence"]) for r in routes.values())

    return {
        "routes":              routes,
        "stops_df":            stops_df,        # with vehicle_id column added
        "total_distance_km":   round(total_dist, 2),
        "total_overtime_min":  round(total_overtime, 1),
        "total_tw_violations": total_violations,
        "total_stops_served":  total_stops_served,
        "method":              "baseline_nearest_neighbour",
    }