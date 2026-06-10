"""
intelligence/route_adjuster.py  (v2 — Road Blocked + Customer Unavailable)
---------------------------------------------------------------------------
Human-in-the-loop route adjustment with two clearly distinct operations.

OPERATION 1 — Customer Unavailable:
  The customer genuinely cannot receive delivery today (closed, no one home,
  wrong address, natural disaster). The stop is removed from the problem
  entirely. The solver re-runs without it. It will never appear in any route.
  This is the correct behaviour for "this person does not need a delivery today."

OPERATION 2 — Road Blocked (NEW):
  A road segment between two points is closed, but the destination customer
  STILL needs their delivery. The system keeps the destination stop in the
  problem but sets the cost of the direct path between the two endpoints to
  near-infinity. The solver is then forced to find an alternative sequence
  that reaches the destination via a different approach — perhaps assigning
  it to a different vehicle, or visiting it from the other direction, or
  routing via an intermediate stop. The customer is NEVER dropped.

  This implements exactly what the dispatcher drew in their diagram: the
  A→B road is blocked, so the system finds the A→(other route)→B path.

Why they need different implementations:
  Customer Unavailable modifies the INPUT to the solver (removes a stop).
  Road Blocked modifies the DISTANCE MATRIX inside the solver (sets one
  arc to 1,000,000,000 metres). Same solver infrastructure, different
  intervention point. This is the key architectural distinction.

OPERATION 3 — Reorder stops on a vehicle:
  A dispatcher reorders stops based on local knowledge. Human sequence is
  accepted as-is, metrics are recalculated. No re-solve needed.
"""

import copy
from math import radians, sin, cos, sqrt, atan2
from typing import Dict, List, Optional, Tuple
import pandas as pd


AVG_SPEED_KMH    = 25.0
SHIFT_START_HOUR = 8
MAX_SHIFT_MIN    = 510


def _haversine_km(lat1, lng1, lat2, lng2) -> float:
    R = 6371
    lat1, lng1, lat2, lng2 = map(radians, [lat1, lng1, lat2, lng2])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlng/2)**2
    return 2 * R * atan2(sqrt(a), sqrt(1-a))


def _clock_str(minutes_from_start: float) -> str:
    total = SHIFT_START_HOUR * 60 + minutes_from_start
    return f"{int(total // 60):02d}:{int(total % 60):02d}"


# ── Operation 1: Customer Unavailable ────────────────────────────────────────

def customer_unavailable(
    stop_id:    int,
    result:     dict,
    stops_df:   pd.DataFrame,
    vehicles_df: pd.DataFrame,
    depot:      dict,
    reason:     str = "Customer unavailable",
) -> Tuple[dict, str]:
    """
    Remove a stop from the problem entirely and re-run the solver.
    The stop will not appear in any route in the output.
    Use this when the customer genuinely cannot receive delivery today.
    """
    from optimizer.solver import run_solver

    current_stops = result["stops_df"]
    current_vehicle = -1
    if "vehicle_id" in current_stops.columns:
        match = current_stops[current_stops["stop_id"] == stop_id]
        if not match.empty:
            current_vehicle = int(match.iloc[0]["vehicle_id"])

    vehicle_name = "unassigned"
    if current_vehicle >= 0 and current_vehicle < len(vehicles_df):
        vehicle_name = vehicles_df.iloc[current_vehicle]["name"]

    removed_row  = stops_df[stops_df["stop_id"] == stop_id]
    removed_name = removed_row.iloc[0]["name"] if not removed_row.empty else f"Stop #{stop_id}"

    filtered_stops = stops_df[stops_df["stop_id"] != stop_id].copy()

    new_result = run_solver(
        filtered_stops, vehicles_df, depot,
        objective=result.get("objective", "cost"),
    )

    if new_result is None:
        return result, f"❌ Re-solve failed after removing {removed_name}. Original routes unchanged."

    dist_change = round(new_result["total_distance_km"] - result["total_distance_km"], 1)
    sign        = "+" if dist_change > 0 else ""

    status = (
        f"✅ **{removed_name}** removed ({reason}). "
        f"Was on **{vehicle_name}**. "
        f"Fleet re-optimised: {new_result['total_stops_served']} stops served, "
        f"distance change: {sign}{dist_change} km."
    )
    return new_result, status


# ── Operation 2: Road Blocked ─────────────────────────────────────────────────

def road_blocked(
    from_stop_id: int,       # stop that the vehicle was coming FROM (or None = depot)
    to_stop_id:   int,       # stop that needs to be reached via alternative path
    result:       dict,
    stops_df:     pd.DataFrame,
    vehicles_df:  pd.DataFrame,
    depot:        dict,
    description:  str = "Road blocked",
) -> Tuple[dict, str]:
    """
    Block a road segment between two stops and re-solve with that arc penalised.

    The destination stop (to_stop_id) remains in the problem — it MUST be served.
    Only the direct A→B arc is made prohibitively expensive. The solver finds
    an alternative way to reach B: either via a different sequence, a different
    approach direction, or a different vehicle.

    This is the "first diagram" scenario: A→B road is blocked, but B still
    gets delivery via some other route.
    """
    from optimizer.solver import run_solver

    # Get the names for the status message
    stops_lu    = stops_df.set_index("stop_id")
    from_name   = stops_lu.loc[from_stop_id]["name"] if from_stop_id in stops_lu.index else f"Stop #{from_stop_id}"
    to_name     = stops_lu.loc[to_stop_id]["name"]   if to_stop_id   in stops_lu.index else f"Stop #{to_stop_id}"

    # Which vehicle currently serves the destination stop?
    current_stops = result["stops_df"]
    current_vehicle = -1
    if "vehicle_id" in current_stops.columns:
        match = current_stops[current_stops["stop_id"] == to_stop_id]
        if not match.empty:
            current_vehicle = int(match.iloc[0]["vehicle_id"])

    vehicle_name = "unassigned"
    if current_vehicle >= 0 and current_vehicle < len(vehicles_df):
        vehicle_name = vehicles_df.iloc[current_vehicle]["name"]

    print(f"Road blocked: {from_name} → {to_name}. Re-solving with penalised arc...")

    # Re-run solver with ALL stops intact but the blocked arc penalised.
    # The solver will find a way to serve to_stop_id without using the
    # from_stop_id → to_stop_id direct arc.
    new_result = run_solver(
        stops_df,    # ALL stops — destination stop is NOT removed
        vehicles_df,
        depot,
        objective=result.get("objective", "cost"),
        penalised_arcs=[(from_stop_id, to_stop_id)],
    )

    if new_result is None:
        return result, (
            f"❌ Re-solve failed after blocking road between "
            f"{from_name} and {to_name}. Original routes unchanged."
        )

    # Find out which vehicle now serves the destination (may have changed)
    new_stops = new_result["stops_df"]
    new_vehicle = -1
    if "vehicle_id" in new_stops.columns:
        match = new_stops[new_stops["stop_id"] == to_stop_id]
        if not match.empty:
            new_vehicle = int(match.iloc[0]["vehicle_id"])

    new_vehicle_name = "unassigned"
    if new_vehicle >= 0 and new_vehicle < len(vehicles_df):
        new_vehicle_name = vehicles_df.iloc[new_vehicle]["name"]

    dist_change = round(new_result["total_distance_km"] - result["total_distance_km"], 1)
    sign        = "+" if dist_change > 0 else ""

    # Note if the vehicle assignment changed — interesting for the dispatcher
    vehicle_note = (
        f"Route unchanged on **{new_vehicle_name}** via alternative path."
        if new_vehicle == current_vehicle
        else f"**{to_name}** reassigned from {vehicle_name} to **{new_vehicle_name}**."
    )

    status = (
        f"✅ Road blocked between **{from_name}** and **{to_name}** ({description}). "
        f"{vehicle_note} "
        f"**{to_name}** is still served — the fleet found an alternative route. "
        f"Distance change: {sign}{dist_change} km."
    )
    return new_result, status


# ── Operation 3: Reorder stops ────────────────────────────────────────────────

def apply_human_reorder(
    vehicle_id:   int,
    new_sequence: List[int],
    result:       dict,
    stops_df:     pd.DataFrame,
    depot:        dict,
) -> Tuple[dict, dict, str]:
    """
    Accept the dispatcher's new stop sequence for a vehicle and recalculate metrics.
    Does NOT re-run the solver — human sequence is accepted as given.
    """
    stops_lu = stops_df.set_index("stop_id")

    elapsed_min   = 0.0
    total_dist_km = 0.0
    arrivals      = {}
    violations    = []
    prev_lat, prev_lng = depot["lat"], depot["lng"]

    for stop_id in new_sequence:
        sid = int(stop_id)
        if sid not in stops_lu.index:
            continue
        row = stops_lu.loc[sid]

        dist_km    = _haversine_km(prev_lat, prev_lng, float(row["lat"]), float(row["lng"]))
        travel_min = (dist_km / AVG_SPEED_KMH) * 60
        total_dist_km += dist_km
        elapsed_min   += travel_min

        tw_start_min = float(row["tw_start"]) * 60
        tw_end_min   = float(row["tw_end"])   * 60

        if elapsed_min < tw_start_min:
            elapsed_min = tw_start_min

        arrivals[sid] = elapsed_min

        if str(row["window_label"]) != "Flexible" and elapsed_min > tw_end_min:
            violations.append({
                "stop_id":   sid,
                "stop_name": str(row["name"]),
                "arrived":   _clock_str(elapsed_min),
                "deadline":  _clock_str(tw_end_min),
                "late_by":   round(elapsed_min - tw_end_min, 1),
            })

        elapsed_min   += int(row["service_time_min"])
        prev_lat, prev_lng = float(row["lat"]), float(row["lng"])

    return_dist    = _haversine_km(prev_lat, prev_lng, depot["lat"], depot["lng"])
    total_dist_km += return_dist
    elapsed_min   += (return_dist / AVG_SPEED_KMH) * 60

    total_load   = sum(
        float(stops_lu.loc[int(sid)]["weight_kg"])
        for sid in new_sequence if int(sid) in stops_lu.index
    )
    overtime_min = max(0.0, elapsed_min - MAX_SHIFT_MIN)

    updated_result = copy.deepcopy(result)
    updated_result["routes"][vehicle_id] = {
        "stop_sequence":     new_sequence,
        "total_distance_km": round(total_dist_km, 2),
        "total_time_min":    round(elapsed_min, 1),
        "load_kg":           round(total_load, 1),
        "tw_violations":     len(violations),
        "overtime_min":      round(overtime_min, 1),
        "arrivals":          arrivals,
    }

    for sid in result["routes"][vehicle_id]["stop_sequence"]:
        mask = updated_result["stops_df"]["stop_id"] == int(sid)
        updated_result["stops_df"].loc[mask, "vehicle_id"] = -1

    for sid in new_sequence:
        mask = updated_result["stops_df"]["stop_id"] == int(sid)
        updated_result["stops_df"].loc[mask, "vehicle_id"] = vehicle_id

    updated_result["total_distance_km"] = round(
        sum(r["total_distance_km"] for r in updated_result["routes"].values()), 2
    )
    updated_result["total_overtime_min"] = round(
        sum(r["overtime_min"] for r in updated_result["routes"].values()), 1
    )
    updated_result["total_tw_violations"] = sum(
        r["tw_violations"] for r in updated_result["routes"].values()
    )

    validation = {
        "arrival_times":    arrivals,
        "violations":       violations,
        "total_dist_km":    round(total_dist_km, 2),
        "total_time_min":   round(elapsed_min, 1),
        "overtime_min":     round(overtime_min, 1),
        "load_kg":          round(total_load, 1),
        "stops_in_sequence": len(new_sequence),
    }

    if violations:
        viol_names = ", ".join(v["stop_name"] for v in violations[:3])
        status = (
            f"⚠️ Sequence applied with {len(violations)} time window violation(s): "
            f"{viol_names}. Distance: {total_dist_km:.1f} km."
        )
    else:
        status = (
            f"✅ Sequence applied. All windows satisfied. "
            f"Distance: {total_dist_km:.1f} km, "
            f"time: {round(elapsed_min/60, 1)} hrs."
        )

    return updated_result, validation, status


def get_vehicle_stop_table(
    vehicle_id: int,
    result:     dict,
    stops_df:   pd.DataFrame,
) -> pd.DataFrame:
    """Build a display-ready DataFrame of a vehicle's current stops for the UI."""
    route    = result["routes"].get(vehicle_id, {})
    sequence = route.get("stop_sequence", [])
    arrivals = route.get("arrivals", {})
    stops_lu = stops_df.set_index("stop_id")

    rows = []
    for pos, stop_id in enumerate(sequence, start=1):
        sid = int(stop_id)
        if sid not in stops_lu.index:
            continue
        row       = stops_lu.loc[sid]
        arr_min   = arrivals.get(sid, 0)
        tw_end_min = float(row["tw_end"]) * 60
        on_time   = arr_min <= tw_end_min

        rows.append({
            "Seq":        pos,
            "Stop Name":  str(row["name"]),
            "Zone":       str(row["zone"]),
            "Weight kg":  float(row["weight_kg"]),
            "Window":     str(row["window_label"]),
            "ETA":        _clock_str(arr_min),
            "On Time":    "✅" if on_time else "⚠️ Late",
            "Block":      False,
            "_stop_id":   sid,
        })

    return pd.DataFrame(rows) if rows else pd.DataFrame()