"""
intelligence/stop_insertion.py  (v2 — uses solver arrival times correctly)
---------------------------------------------------------------------------
The Point C urgent stop insertion algorithm.

THE KEY FIX FROM v1:
  v1 re-simulated the entire route from scratch to check feasibility.
  This was fundamentally wrong because straight-line distance simulation
  accumulates wildly different elapsed times from what the solver actually
  planned. A route the solver correctly scheduled across 8 hours appeared
  to take 16+ hours in simulation, making every stop look like a window
  violation and every insertion infeasible.

  v2 uses the ORIGINAL SOLVER ARRIVAL TIMES for all existing stops.
  The solver already verified those arrivals are feasible — we trust them.
  We only calculate the INCREMENTAL IMPACT of inserting one new stop:

    1. How long does it take to detour from the previous stop to the new
       stop and then back on route to the next stop?
    2. Does the new stop itself arrive within its time window?
    3. Does the propagated delay push any TIGHT-WINDOW stop past its
       deadline? Flexible stops are never a feasibility constraint —
       that is what "flexible" means.
    4. Does the insertion push the vehicle into overtime?

  This approach is both faster and correct.

Why use solver arrivals rather than re-simulating?
  The solver used a full distance matrix and carefully optimised the
  sequence. Our simulation uses the same haversine distances, but the
  solver also accounts for waiting at stops (arriving early and waiting
  for the window to open), which adds time to the schedule in ways our
  simple sequential simulation does not replicate. Using solver arrivals
  means we start from a verified, correct schedule and only measure
  the delta introduced by the new stop.
"""

from math import radians, sin, cos, sqrt, atan2
from typing import Dict, List, Optional, Tuple
import pandas as pd
import copy


AVG_SPEED_KMH    = 25.0
SHIFT_START_HOUR = 8
MAX_SHIFT_MIN    = 8 * 60 + 30   # 510 minutes including mandatory lunch break


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371
    lat1, lng1, lat2, lng2 = map(radians, [lat1, lng1, lat2, lng2])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlng/2)**2
    return 2 * R * atan2(sqrt(a), sqrt(1-a))


def _travel_min(lat1, lng1, lat2, lng2) -> float:
    return (_haversine_km(lat1, lng1, lat2, lng2) / AVG_SPEED_KMH) * 60


def _clock_str(minutes_from_start: float) -> str:
    """Convert minutes from shift start to HH:MM clock format."""
    total = SHIFT_START_HOUR * 60 + minutes_from_start
    return f"{int(total // 60):02d}:{int(total % 60):02d}"


def _check_insertion(
    pos:        int,           # insert before this index in the route (0 = first stop)
    new_stop:   dict,          # new stop attrs (lat, lng, tw_start_min, tw_end_min, etc.)
    route_stops: List[dict],   # existing stops in route order, each with lat, lng, tw_*, arrivals
    depot:      dict,
) -> Tuple[bool, float, float, float]:
    """
    Check whether inserting new_stop at position pos is feasible, and what
    it costs.

    Uses the original solver arrival times for all existing stops.
    Only re-computes arrival times for stops that follow the insertion point,
    by adding the propagated delay to their original solver arrivals.

    Returns:
      feasible (bool)       — True if no tight-window stop is violated
      extra_dist_km (float) — additional kilometres from the detour
      extra_time_min (float)— additional minutes added to the route
      new_stop_arrival (float) — minutes from shift start when vehicle arrives
                                  at the new stop
    """
    n = len(route_stops)

    # ── Step 1: Find departure time from the stop BEFORE the insertion ────────
    # If inserting at position 0, we depart from the depot at time 0 (shift start).
    # Otherwise we depart from the previous stop after its service time.
    if pos == 0:
        prev_lat = depot["lat"]
        prev_lng = depot["lng"]
        prev_departure = 0.0
    else:
        prev = route_stops[pos - 1]
        prev_lat = prev["lat"]
        prev_lng = prev["lng"]
        # Departure = original solver arrival + service time
        prev_departure = prev["arrival_min"] + prev.get("service_time_min", 10)

    # ── Step 2: Compute arrival at the new stop ───────────────────────────────
    travel_to_new   = _travel_min(prev_lat, prev_lng, new_stop["lat"], new_stop["lng"])
    arr_new         = prev_departure + travel_to_new

    # Respect the new stop's opening window — wait if we arrive early
    if arr_new < new_stop["tw_start_min"]:
        arr_new = new_stop["tw_start_min"]

    # Check the new stop's own deadline
    if arr_new > new_stop["tw_end_min"]:
        return False, 0.0, 0.0, arr_new

    dep_new = arr_new + new_stop.get("service_time_min", 10)

    # ── Step 3: Compute the delay propagated to subsequent stops ──────────────
    # The next stop after the insertion was originally reached directly from
    # prev. Now the vehicle must first go to the new stop and then come back
    # to the route. The extra time this adds propagates forward to all
    # subsequent stops uniformly (assuming travel speeds stay constant).
    if pos < n:
        next_stop = route_stops[pos]
        travel_to_next_original = _travel_min(prev_lat, prev_lng,
                                               next_stop["lat"], next_stop["lng"])
        travel_new_to_next      = _travel_min(new_stop["lat"], new_stop["lng"],
                                               next_stop["lat"], next_stop["lng"])
        # Delay = (detour travel + service at new stop) vs what we would have spent
        # going directly prev → next
        delay_min = (
            travel_to_new +
            new_stop.get("service_time_min", 10) +
            travel_new_to_next -
            travel_to_next_original
        )
        delay_min = max(0.0, delay_min)  # delay can't be negative
    else:
        # Inserting after the last stop — no subsequent stops to delay
        # but we need to check the return-to-depot shift limit
        delay_min = 0.0

    # ── Step 4: Check whether the delay violates any TIGHT-WINDOW stop ────────
    # We propagate the delay to all stops after the insertion point.
    # Flexible-window stops are NEVER a feasibility constraint — if a flexible
    # stop now arrives at 4:35pm instead of 4:20pm, that is completely fine.
    # Only stops with explicit tight deadlines (morning or afternoon windows)
    # can make an insertion infeasible.
    for i in range(pos, n):
        stop = route_stops[i]
        new_arrival = stop["arrival_min"] + delay_min

        # Only check tight-window stops for feasibility
        if stop.get("window_label", "Flexible") != "Flexible":
            if new_arrival > stop["tw_end_min"]:
                return False, 0.0, 0.0, arr_new

    # ── Step 5: Check the shift limit ─────────────────────────────────────────
    # The last stop's original arrival + delay + service + return to depot
    # must not exceed the maximum shift time.
    if n > 0:
        last_stop  = route_stops[-1]
        last_arr   = last_stop["arrival_min"] + delay_min
        last_dep   = last_arr + last_stop.get("service_time_min", 10)
        return_min = _travel_min(last_stop["lat"], last_stop["lng"],
                                  depot["lat"], depot["lng"])
        shift_end  = last_dep + return_min
        if shift_end > MAX_SHIFT_MIN + 30:   # 30 min grace for demo realism
            return False, 0.0, 0.0, arr_new

    # ── Step 6: Calculate extra distance cost ─────────────────────────────────
    if pos < n:
        next_stop = route_stops[pos]
        dist_detour = (
            _haversine_km(prev_lat, prev_lng, new_stop["lat"], new_stop["lng"]) +
            _haversine_km(new_stop["lat"], new_stop["lng"],
                          next_stop["lat"], next_stop["lng"])
        )
        dist_direct = _haversine_km(prev_lat, prev_lng,
                                     next_stop["lat"], next_stop["lng"])
    else:
        # Inserting after last stop — compare detour via new stop to depot
        # vs direct last-stop-to-depot
        dist_detour = (
            _haversine_km(prev_lat, prev_lng, new_stop["lat"], new_stop["lng"]) +
            _haversine_km(new_stop["lat"], new_stop["lng"],
                          depot["lat"], depot["lng"])
        )
        dist_direct = _haversine_km(prev_lat, prev_lng,
                                     depot["lat"], depot["lng"])

    extra_dist_km  = max(0.0, dist_detour - dist_direct)
    extra_time_min = delay_min

    return True, round(extra_dist_km, 2), round(extra_time_min, 1), arr_new


def find_best_insertion(
    new_stop_attrs:  dict,
    result:          dict,
    stops_df:        pd.DataFrame,
    depot:           dict,
    vehicles_df:     pd.DataFrame,
) -> Optional[Dict]:
    """
    Find the best position to insert a new urgent stop into the existing routes.

    Iterates through every vehicle and every possible insertion position.
    Uses solver arrival times for existing stops (not re-simulation).
    Only tight-window stops can make an insertion infeasible.
    Returns the lowest-extra-distance feasible insertion found, or a clear
    infeasibility report if nothing works.
    """
    # Convert time windows from hours to minutes from shift start
    new_stop = {
        **new_stop_attrs,
        "tw_start_min": float(new_stop_attrs["tw_start"]) * 60,
        "tw_end_min":   float(new_stop_attrs["tw_end"])   * 60,
    }

    stops_lu = stops_df.set_index("stop_id")
    routes   = result["routes"]

    best           = None
    best_dist      = float("inf")
    cap_failures   = []   # vehicles rejected for weight capacity
    tw_failures    = []   # vehicles rejected because all positions caused TW violations

    for v_id, route in routes.items():
        sequence = route["stop_sequence"]
        if not sequence:
            continue

        # Capacity check — hard constraint, no exceptions
        v_cap    = float(vehicles_df.iloc[v_id]["capacity_kg"])
        v_load   = float(route["load_kg"])
        v_name   = vehicles_df.iloc[v_id]["name"]

        if v_load + new_stop["weight_kg"] > v_cap:
            cap_failures.append(
                f"{v_name} is full "
                f"({v_load:.0f}kg + {new_stop['weight_kg']:.0f}kg > {v_cap:.0f}kg capacity)"
            )
            continue

        # Build the ordered stop list for this vehicle, enriching with
        # ORIGINAL SOLVER ARRIVAL TIMES — this is what makes v2 correct
        route_stops = []
        for stop_id in sequence:
            sid = int(stop_id)   # ensure plain int for DataFrame lookup
            if sid not in stops_lu.index:
                continue
            row = stops_lu.loc[sid]
            route_stops.append({
                "stop_id":          sid,
                "name":             str(row["name"]),
                "zone":             str(row["zone"]),
                "lat":              float(row["lat"]),
                "lng":              float(row["lng"]),
                "tw_start_min":     float(row["tw_start"]) * 60,
                "tw_end_min":       float(row["tw_end"])   * 60,
                "service_time_min": int(row["service_time_min"]),
                "weight_kg":        float(row["weight_kg"]),
                "window_label":     str(row["window_label"]),
                # Use the solver's actual arrival time — not re-simulated
                "arrival_min":      float(route["arrivals"].get(sid, 0)),
            })

        # Try every possible insertion position
        found_feasible_for_vehicle = False
        for pos in range(len(route_stops) + 1):
            feasible, extra_dist, extra_time, arr_new = _check_insertion(
                pos, new_stop, route_stops, depot
            )

            if feasible and extra_dist < best_dist:
                best_dist = extra_dist
                found_feasible_for_vehicle = True

                # Human-readable position description
                n = len(route_stops)
                if pos == 0:
                    pos_desc = f"first delivery (before {route_stops[0]['name']})"
                elif pos == n:
                    pos_desc = f"last delivery (after {route_stops[-1]['name']})"
                else:
                    pos_desc = (
                        f"between stop {pos} ({route_stops[pos-1]['name']}) "
                        f"and stop {pos+1} ({route_stops[pos]['name']})"
                    )

                best = {
                    "feasible":              True,
                    "vehicle_id":            v_id,
                    "vehicle_name":          v_name,
                    "vehicle_type":          vehicles_df.iloc[v_id]["type"],
                    "insert_position":       pos,
                    "position_desc":         pos_desc,
                    "extra_dist_km":         extra_dist,
                    "extra_time_min":        extra_time,
                    "eta_clock":             _clock_str(arr_new),
                    "new_stop_arrival_min":  arr_new,
                    "total_route_stops":     len(route_stops) + 1,
                    "capacity_remaining_after": round(v_cap - v_load - new_stop["weight_kg"], 1),
                    "new_stop":              new_stop,
                    "route_stops":           route_stops,
                    "depot":                 depot,
                }

        # If this vehicle had capacity but no feasible position, record why
        if not found_feasible_for_vehicle and best is None:
            # Figure out what the new stop's time window looks like in clock time
            tw_open  = _clock_str(new_stop["tw_start_min"])
            tw_close = _clock_str(new_stop["tw_end_min"])
            tw_failures.append(
                f"{v_name}: no gap in the route satisfies the "
                f"{new_stop.get('window_label','?')} window ({tw_open}–{tw_close}) "
                f"without delaying a tight-deadline stop"
            )

    if best is None:
        # Build an informative, honest explanation of why every vehicle failed
        parts = []
        if cap_failures:
            parts.append("Weight capacity exceeded: " + "; ".join(cap_failures))
        if tw_failures:
            parts.append("Time window conflicts: " + "; ".join(tw_failures))
        if not parts:
            parts.append("All positions across all vehicles were checked")

        # Give a specific tip based on what failed
        if cap_failures and not tw_failures:
            tip = "Try reducing the package weight or splitting the delivery."
        elif tw_failures and not cap_failures:
            tip = (
                "The selected time window is too restrictive for the current routes. "
                "Try switching to 'Flexible (any time)' — flexible stops can almost "
                "always be absorbed because they impose no deadline constraint."
            )
        else:
            tip = (
                "Try 'Flexible (any time)' window first. If that also fails, "
                "the fleet is at capacity and a new vehicle is needed."
            )

        return {
            "feasible": False,
            "reason":   ". ".join(parts) + ". " + tip,
            "new_stop": new_stop,
        }

    return best


def apply_insertion(
    best_insertion: dict,
    result:         dict,
    stops_df:       pd.DataFrame,
    new_stop_id:    int = 9999,
) -> Tuple[dict, pd.DataFrame]:
    """
    Apply a confirmed insertion to the in-memory result dict.
    Called when the dispatcher clicks Confirm — updates routes without
    re-running the full solver.
    """
    updated_result = copy.deepcopy(result)

    v_id = best_insertion["vehicle_id"]
    pos  = best_insertion["insert_position"]
    ns   = best_insertion["new_stop"]

    updated_result["routes"][v_id]["stop_sequence"].insert(pos, new_stop_id)
    updated_result["routes"][v_id]["load_kg"] = round(
        updated_result["routes"][v_id]["load_kg"] + ns["weight_kg"], 1
    )
    updated_result["routes"][v_id]["total_distance_km"] = round(
        updated_result["routes"][v_id]["total_distance_km"] +
        best_insertion["extra_dist_km"], 2
    )
    updated_result["routes"][v_id]["arrivals"][new_stop_id] = (
        best_insertion["new_stop_arrival_min"]
    )
    updated_result["total_stops_served"] = (
        updated_result.get("total_stops_served", 0) + 1
    )

    new_row = {
        "stop_id":          new_stop_id,
        "name":             ns.get("name", "Urgent Stop"),
        "lat":              ns["lat"],
        "lng":              ns["lng"],
        "weight_kg":        ns["weight_kg"],
        "tw_start":         ns["tw_start"],
        "tw_end":           ns["tw_end"],
        "window_label":     ns.get("window_label", "Flexible"),
        "is_priority":      True,
        "is_slow_client":   False,
        "service_time_min": ns.get("service_time_min", 10),
        "zone":             ns.get("zone", "Custom"),
        "vehicle_id":       v_id,
    }

    updated_stops_df = pd.concat(
        [stops_df, pd.DataFrame([new_row])], ignore_index=True
    )
    updated_result["stops_df"] = pd.concat(
        [updated_result["stops_df"], pd.DataFrame([new_row])], ignore_index=True
    )

    return updated_result, updated_stops_df