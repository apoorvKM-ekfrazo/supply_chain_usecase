"""
intelligence/route_explainer.py
--------------------------------
LLM-powered explanation layer. Three stages:
  Stage 1 — Route Analyst (pure Python): produces structured diagnosis dicts
  Stage 2 — LLM Narrator (OpenAI): converts facts to plain English
  Stage 3 — Streamlit display (in app.py): renders the explanations

Key improvement over v1:
  analyse_unserved_stop() now identifies the TRADE-OFF BENEFICIARY — the
  specific tight-window stop that would have been violated if the dropped
  stop had been inserted. This gives the LLM the honest story to tell
  ("Indiranagar #34 would have missed its 11am deadline by 18 minutes")
  rather than the bureaucratic deflection ("time window conflict with
  existing routes").
"""

import os
from typing import Dict, List, Optional
import pandas as pd


AVG_SPEED_KMH    = 25.0
SHIFT_START_HOUR = 8
OPENAI_MODEL       = "gpt-4o-mini"
OPENAI_API_URL     = "https://api.openai.com/v1/chat/completions"


def _haversine_km(lat1, lng1, lat2, lng2) -> float:
    from math import radians, sin, cos, sqrt, atan2
    R = 6371
    lat1, lng1, lat2, lng2 = map(radians, [lat1, lng1, lat2, lng2])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlng/2)**2
    return 2 * R * atan2(sqrt(a), sqrt(1-a))


# ── STAGE 1: Route Analyst ────────────────────────────────────────────────────

def analyse_unserved_stop(
    stop_row: pd.Series,
    depot:    dict,
    result:   dict,
    stops_df: pd.DataFrame,
) -> dict:
    """
    Diagnose why a stop was not served AND identify which stop benefited.

    The beneficiary identification works by simulating a stop insertion:
    for each tight-window stop on the nearest vehicle's route, we calculate
    how much extra time inserting the dropped stop before it would add, then
    check whether that pushes it past its deadline. The first tight-window
    stop that would have been violated is the trade-off beneficiary — the
    stop the system was protecting when it chose to drop this one.
    """
    stop_lat   = stop_row["lat"]
    stop_lng   = stop_row["lng"]
    tw_start   = stop_row["tw_start"] * 60
    tw_end     = stop_row["tw_end"]   * 60
    weight_kg  = stop_row["weight_kg"]
    zone       = stop_row["zone"]
    window_lbl = stop_row["window_label"]

    dist_from_depot_km   = _haversine_km(depot["lat"], depot["lng"], stop_lat, stop_lng)
    min_travel_min       = (dist_from_depot_km / AVG_SPEED_KMH) * 60
    time_feasible_direct = min_travel_min <= tw_end
    time_gap_min         = tw_end - min_travel_min

    routes   = result["routes"]
    stops_lu = stops_df.set_index("stop_id")

    # Find closest served stop and which vehicle it belongs to
    closest_vehicle_id = None
    closest_dist_km    = float("inf")
    closest_stop_id    = None

    for v_id, route in routes.items():
        for stop_id in route["stop_sequence"]:
            if stop_id not in stops_lu.index:
                continue
            served = stops_lu.loc[stop_id]
            d = _haversine_km(stop_lat, stop_lng, served["lat"], served["lng"])
            if d < closest_dist_km:
                closest_dist_km    = d
                closest_vehicle_id = v_id
                closest_stop_id    = stop_id

    # ── Trade-off beneficiary identification ──────────────────────────────────
    # For the vehicle that passed nearest to the dropped stop, simulate
    # inserting the dropped stop before each tight-window stop in sequence.
    # The first tight-window stop that would overshoot its deadline is the
    # one the system was protecting — the honest reason for the trade-off.
    trade_off_beneficiary = None

    if closest_vehicle_id is not None:
        route    = routes[closest_vehicle_id]
        sequence = route["stop_sequence"]
        arrivals = route["arrivals"]

        for i, sid in enumerate(sequence):
            if sid not in stops_lu.index:
                continue
            s = stops_lu.loc[sid]
            if s["window_label"] == "Flexible":
                continue  # Only tight-window stops create urgency pressure

            # Coordinates of the stop before this one in the route
            prev_lat, prev_lng = depot["lat"], depot["lng"]
            if i > 0:
                prev_sid = sequence[i - 1]
                if prev_sid in stops_lu.index:
                    prev_row   = stops_lu.loc[prev_sid]
                    prev_lat   = prev_row["lat"]
                    prev_lng   = prev_row["lng"]

            # Extra time = detour to dropped stop + service there + detour back
            detour_to   = _haversine_km(prev_lat, prev_lng, stop_lat, stop_lng)
            detour_from = _haversine_km(stop_lat, stop_lng, s["lat"], s["lng"])
            direct      = _haversine_km(prev_lat, prev_lng, s["lat"], s["lng"])
            extra_travel_min = (detour_to + detour_from - direct) / AVG_SPEED_KMH * 60
            total_delay_min  = extra_travel_min + float(stop_row["service_time_min"])

            current_arrival = arrivals.get(sid, 0)
            new_arrival_min = current_arrival + total_delay_min
            tw_end_min      = s["tw_end"] * 60
            overshoot_min   = new_arrival_min - tw_end_min

            if overshoot_min > 5:
                dhr  = SHIFT_START_HOUR + int(new_arrival_min // 60)
                dmin = int(new_arrival_min % 60)
                xhr  = SHIFT_START_HOUR + int(tw_end_min // 60)
                xmin = int(tw_end_min % 60)
                trade_off_beneficiary = {
                    "stop_name":       s["name"],
                    "zone":            s["zone"],
                    "window_label":    s["window_label"],
                    "deadline_clock":  f"{xhr:02d}:{xmin:02d}",
                    "would_arrive_at": f"{dhr:02d}:{dmin:02d}",
                    "overshoot_min":   round(overshoot_min, 1),
                    "delay_added_min": round(total_delay_min, 1),
                }
                break  # First conflict found is the most critical

    # ── Capacity analysis ─────────────────────────────────────────────────────
    from data.scenario import get_vehicles
    vehicles_df = get_vehicles()
    capacity_feasible_vehicles = []
    for v_id, route in routes.items():
        v_cap     = int(vehicles_df.iloc[v_id]["capacity_kg"])
        remaining = v_cap - route["load_kg"]
        if remaining >= weight_kg:
            capacity_feasible_vehicles.append({
                "vehicle_id":   v_id,
                "vehicle_name": vehicles_df.iloc[v_id]["name"],
                "remaining_kg": round(remaining, 1),
            })

    # ── Primary reason ────────────────────────────────────────────────────────
    if not time_feasible_direct:
        primary_reason = "time_infeasible_even_direct"
    elif window_lbl != "Flexible" and time_gap_min < 30:
        primary_reason = "tight_window_insufficient_margin"
    elif not capacity_feasible_vehicles:
        primary_reason = "capacity_exceeded_all_vehicles"
    else:
        primary_reason = "time_window_conflict_with_existing_routes"

    return {
        "stop_id":               int(stop_row["stop_id"]),
        "stop_name":             stop_row["name"],
        "zone":                  zone,
        "weight_kg":             float(weight_kg),
        "window_label":          window_lbl,
        "tw_start_min":          float(tw_start),
        "tw_end_min":            float(tw_end),
        "dist_from_depot_km":    round(dist_from_depot_km, 1),
        "min_travel_min":        round(min_travel_min, 1),
        "time_gap_min":          round(time_gap_min, 1),
        "time_feasible_direct":  time_feasible_direct,
        "closest_vehicle_id":    closest_vehicle_id,
        "closest_dist_km":       round(closest_dist_km, 1),
        "capacity_options":      capacity_feasible_vehicles,
        "primary_reason":        primary_reason,
        "is_priority":           bool(stop_row["is_priority"]),
        "trade_off_beneficiary": trade_off_beneficiary,
    }


def analyse_overall_result(
    result:      dict,
    base_result: dict,
    stops_df:    pd.DataFrame,
    depot:       dict,
) -> dict:
    routes        = result["routes"]
    vehicles_used = sum(1 for r in routes.values() if r["stop_sequence"])
    stops_lu      = stops_df.set_index("stop_id")
    vehicle_zones = {}
    for v_id, route in routes.items():
        zones = set()
        for stop_id in route["stop_sequence"]:
            if stop_id in stops_lu.index:
                zones.add(stops_lu.loc[stop_id]["zone"])
        if zones:
            vehicle_zones[v_id] = sorted(zones)

    return {
        "vehicles_used":           vehicles_used,
        "total_vehicles":          len(routes),
        "total_stops":             len(stops_df),
        "stops_served":            result["total_stops_served"],
        "stops_unserved":          len(stops_df) - result["total_stops_served"],
        "tw_violations_baseline":  base_result["total_tw_violations"],
        "tw_violations_optimized": result["total_tw_violations"],
        "overtime_hrs_baseline":   round(base_result["total_overtime_min"] / 60, 1),
        "overtime_hrs_optimized":  round(result["total_overtime_min"] / 60, 1),
        "distance_km_baseline":    base_result["total_distance_km"],
        "distance_km_optimized":   result["total_distance_km"],
        "vehicle_zones":           vehicle_zones,
        "depot_name":              depot["name"],
    }


# ── STAGE 2: LLM Narrator ─────────────────────────────────────────────────────

def _call_groq(prompt: str, system: str) -> str:
    try:
        import requests
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            return "[OPENAI_API_KEY not set — add your key in the sidebar to enable explanations]"

        resp = requests.post(
            OPENAI_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model":       OPENAI_MODEL,
                "max_tokens":  450,
                "temperature": 0.3,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": prompt},
                ],
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"[Explanation unavailable: {str(e)}]"


def generate_overall_explanation(summary: dict) -> str:
    system = (
        "You are a logistics analyst writing a brief, confident explanation of "
        "an AI route optimization result for a fleet manager audience. "
        "Write 2-3 sentences maximum. Be specific with numbers. "
        "Do not use bullet points. Do not use jargon like 'metaheuristic' or 'VRP'. "
        "Tone: professional, factual."
    )
    zone_text = "; ".join(
        f"Vehicle {v+1} covering {', '.join(z)}"
        for v, z in summary.get("vehicle_zones", {}).items()
    ) or "multiple zones"

    prompt = (
        f"The AI optimizer just ran on a Bengaluru delivery fleet:\n"
        f"- Vehicles used: {summary['vehicles_used']} of {summary['total_vehicles']}\n"
        f"- Stops served: {summary['stops_served']} of {summary['total_stops']}\n"
        f"- Time window violations: {summary['tw_violations_baseline']} → {summary['tw_violations_optimized']}\n"
        f"- Overtime: {summary['overtime_hrs_baseline']}hrs → {summary['overtime_hrs_optimized']}hrs\n"
        f"- Distance: {summary['distance_km_baseline']:.1f}km → {summary['distance_km_optimized']:.1f}km\n"
        f"- Routing: {zone_text}\n\n"
        f"Write 2-3 sentences summarising the result. If distance increased, "
        f"explain honestly why the trade-off (zero overtime, zero TW violations) justifies it."
    )
    return _call_groq(prompt, system)


def generate_unserved_explanation(diagnosis: dict) -> str:
    system = (
        "You are a logistics analyst explaining to a dispatcher why a delivery stop "
        "could not be served. Be direct and honest — name the specific trade-off. "
        "Write exactly 2-3 sentences. Be specific with times and stop names. "
        "End with one concrete actionable suggestion. "
        "Do not say 'the algorithm' — say 'the system'. "
        "If a specific stop was being protected, name it directly. "
        "Tone: clear, honest, not evasive."
    )

    tw_start_hr = SHIFT_START_HOUR + int(diagnosis["tw_start_min"] // 60)
    tw_end_hr   = SHIFT_START_HOUR + int(diagnosis["tw_end_min"]   // 60)
    window_str  = f"{tw_start_hr:02d}:00 – {tw_end_hr:02d}:00"

    cap_text = (
        "Vehicles with remaining weight capacity: " +
        ", ".join(
            f"{v['vehicle_name']} ({v['remaining_kg']}kg free)"
            for v in diagnosis["capacity_options"][:2]
        )
        if diagnosis["capacity_options"]
        else "No vehicle had sufficient remaining weight capacity."
    )

    # Build the trade-off context — this is the key addition
    beneficiary = diagnosis.get("trade_off_beneficiary")
    if beneficiary:
        trade_off_text = (
            f"IMPORTANT — THE SPECIFIC TRADE-OFF: If this stop had been inserted "
            f"into the route, {beneficiary['stop_name']} in {beneficiary['zone']} "
            f"(which has a {beneficiary['window_label']} deadline of "
            f"{beneficiary['deadline_clock']}) would have arrived at "
            f"{beneficiary['would_arrive_at']} — missing its deadline by "
            f"{beneficiary['overshoot_min']} minutes. The system chose to protect "
            f"that committed deadline by not serving the flexible stop instead."
        )
    else:
        trade_off_text = (
            "No single tight-window stop could be identified as the specific "
            "beneficiary — the conflict was spread across multiple stops on the route."
        )

    is_flexible = diagnosis["window_label"] == "Flexible"
    flexibility_note = (
        "Note: this is a FLEXIBLE-window customer (no hard deadline), which means "
        "they were deprioritised in favour of customers with fixed time commitments. "
        "This is the correct logistics decision — flexible customers implicitly accept "
        "lower priority than time-committed customers."
        if is_flexible else ""
    )

    prompt = (
        f"A delivery stop could not be served. Full diagnosis:\n"
        f"- Stop: {diagnosis['stop_name']} in {diagnosis['zone']}\n"
        f"- Window type: {diagnosis['window_label']} ({window_str})\n"
        f"- Package: {diagnosis['weight_kg']} kg\n"
        f"- Distance from depot: {diagnosis['dist_from_depot_km']} km "
        f"(min travel: {diagnosis['min_travel_min']} min)\n"
        f"- Nearest served stop: {diagnosis['closest_dist_km']} km away\n"
        f"- Capacity: {cap_text}\n"
        f"- {trade_off_text}\n"
        f"- {flexibility_note}\n\n"
        f"Write 2-3 sentences explaining why this stop was not served. "
        f"Name the specific trade-off if provided above — do not be vague. "
        f"End with one actionable suggestion for tomorrow."
    )
    return _call_groq(prompt, system)


# ── Public entry point ────────────────────────────────────────────────────────

def generate_all_explanations(
    result:      dict,
    base_result: dict,
    stops_df:    pd.DataFrame,
    depot:       dict,
) -> dict:
    overall_summary     = analyse_overall_result(result, base_result, stops_df, depot)
    overall_explanation = generate_overall_explanation(overall_summary)

    unserved_df   = result["stops_df"][result["stops_df"]["vehicle_id"] == -1]
    unserved_list = []

    for _, row in unserved_df.iterrows():
        orig_row = stops_df[stops_df["stop_id"] == row["stop_id"]]
        if orig_row.empty:
            continue
        orig_row    = orig_row.iloc[0]
        diagnosis   = analyse_unserved_stop(orig_row, depot, result, stops_df)
        explanation = generate_unserved_explanation(diagnosis)
        unserved_list.append({
            "stop_id":     diagnosis["stop_id"],
            "stop_name":   diagnosis["stop_name"],
            "zone":        diagnosis["zone"],
            "diagnosis":   diagnosis,
            "explanation": explanation,
        })

    return {
        "overall":  overall_explanation,
        "summary":  overall_summary,
        "unserved": unserved_list,
    }







