"""
meio/fleet_analyzer.py
-----------------------
Fleet utilisation analysis and right-sizing recommendations.

The fleet right-sizing question is: given historical utilisation data,
are any vehicles consistently underused enough that the cost of keeping
them exceeds the value they provide? And if we remove an underutilised
vehicle, can the remaining fleet absorb its workload without going
into overtime?

This module answers both parts of that question using the 30-day
synthetic utilisation history from data/meio_scenario.py.

The financial case is built from two numbers:
  1. The annual cost of keeping the vehicle (insurance + maintenance +
     driver wages + depreciation). This is the saving if you sell or
     release the vehicle.
  2. The redistribution feasibility: can remaining vehicles absorb the
     removed vehicle's average daily load without their utilisation
     exceeding a practical ceiling (90%)?

If both conditions are met — the vehicle is underutilised AND the
remaining fleet can absorb its work — the recommendation is to consider
releasing the vehicle with a quantified annual saving.
"""

from typing import Dict, List, Optional
import pandas as pd
import numpy as np

from data.meio_scenario import VEHICLES, VEHICLE_ANNUAL_COSTS


# A vehicle is flagged as underutilised if its average utilisation
# over the history period is below this threshold.
UNDERUTILISATION_THRESHOLD = 0.55   # 55% — anything below is worth examining

# When checking whether redistribution is feasible, we require that
# remaining vehicles don't exceed this ceiling after absorbing extra load.
REDISTRIBUTION_CEILING = 0.90       # 90% — leaves a buffer for demand spikes


def classify_utilisation(avg_pct: float) -> tuple:
    """
    Classify a vehicle's average utilisation and return a (label, colour) pair
    for use in the UI.

    Three tiers:
      Green  (≥75%): healthy — vehicle is earning its keep
      Amber  (55-75%): moderate — monitor but not urgent
      Red    (<55%): underutilised — worth a formal review
    """
    if avg_pct >= 75:
        return "✅ Healthy", "#2e7d32"
    elif avg_pct >= 55:
        return "⚠️ Moderate", "#e65100"
    else:
        return "🔴 Underutilised", "#c62828"


def compute_redistribution_feasibility(
    vehicle_to_remove: str,
    utilisation_summary: pd.DataFrame,
) -> dict:
    """
    Check whether the remaining fleet can absorb the removed vehicle's
    average daily load.

    The logic: the removed vehicle's average daily load (in kg) needs to
    be redistributed to the remaining vehicles. We distribute it
    proportionally to their spare capacity (remaining headroom below 90%).
    If the total spare capacity across the remaining fleet is greater than
    the load to redistribute, the redistribution is feasible.

    Returns a dict with:
      feasible (bool): whether redistribution is possible
      new_utilisation (dict): projected new utilisation per vehicle after
        redistribution (only for vehicles receiving extra load)
      excess_kg (float): how many kg cannot be absorbed, if infeasible
      absorbing_vehicles (list): which vehicles absorb the extra load
    """
    v_row  = utilisation_summary[utilisation_summary["vehicle_name"] == vehicle_to_remove]
    if v_row.empty:
        return {"feasible": False, "reason": "Vehicle not found in history."}

    load_to_redistribute = float(v_row.iloc[0]["avg_load_kg"])

    # Remaining vehicles — all except the one being removed
    remaining = utilisation_summary[
        utilisation_summary["vehicle_name"] != vehicle_to_remove
    ].copy()

    # Spare capacity = (ceiling% - current%) × capacity_kg
    remaining["spare_capacity_kg"] = (
        (REDISTRIBUTION_CEILING - remaining["avg_utilisation_pct"] / 100)
        * remaining["capacity_kg"]
    ).clip(lower=0)

    total_spare = float(remaining["spare_capacity_kg"].sum())

    if total_spare >= load_to_redistribute:
        # Distribute proportionally to spare capacity
        absorbers = remaining[remaining["spare_capacity_kg"] > 0].copy()
        absorbers["extra_load_kg"] = (
            absorbers["spare_capacity_kg"] / total_spare * load_to_redistribute
        )
        absorbers["new_utilisation_pct"] = (
            (absorbers["avg_load_kg"] + absorbers["extra_load_kg"])
            / absorbers["capacity_kg"] * 100
        ).round(1)

        return {
            "feasible":             True,
            "total_spare_capacity": round(total_spare, 1),
            "load_redistributed":   round(load_to_redistribute, 1),
            "absorbing_vehicles":   absorbers["vehicle_name"].tolist(),
            "new_utilisation":      absorbers.set_index("vehicle_name")["new_utilisation_pct"].to_dict(),
            "excess_kg":            0,
        }
    else:
        return {
            "feasible":    False,
            "excess_kg":   round(load_to_redistribute - total_spare, 1),
            "reason": (
                f"Remaining fleet has only {total_spare:.0f}kg of spare capacity, "
                f"but {load_to_redistribute:.0f}kg needs redistribution. "
                "Consider keeping the vehicle or adding capacity elsewhere."
            ),
        }


def generate_fleet_recommendations(
    utilisation_summary: pd.DataFrame,
) -> List[dict]:
    """
    Generate actionable recommendations for each underutilised vehicle.

    For each vehicle below UNDERUTILISATION_THRESHOLD, the function:
      1. Calculates the annual cost of keeping the vehicle
      2. Checks redistribution feasibility
      3. Produces a recommendation with a quantified annual saving

    Returns a list of recommendation dicts, one per underutilised vehicle,
    sorted by net annual saving descending.
    """
    recommendations = []

    for _, row in utilisation_summary.iterrows():
        name     = row["vehicle_name"]
        util_pct = row["avg_utilisation_pct"] / 100

        if util_pct >= UNDERUTILISATION_THRESHOLD:
            continue   # well-utilised vehicle, no recommendation needed

        costs    = VEHICLE_ANNUAL_COSTS.get(name, {})
        ann_cost = sum(costs.values())

        feasibility = compute_redistribution_feasibility(name, utilisation_summary)

        label, colour = classify_utilisation(row["avg_utilisation_pct"])

        if feasibility["feasible"]:
            recommendation_text = (
                f"Consider releasing {name}. "
                f"Its average daily load of {feasibility['load_redistributed']:.0f}kg "
                f"can be absorbed by {', '.join(feasibility['absorbing_vehicles'])}. "
                f"Annual saving: ₹{ann_cost:,.0f}."
            )
            action = "Release / Sell"
        else:
            recommendation_text = (
                f"{name} is underutilised but redistribution is not fully feasible. "
                f"{feasibility.get('reason', '')} "
                f"Monitor for the next month before deciding."
            )
            ann_cost = 0   # no saving since we can't remove it yet
            action = "Monitor"

        recommendations.append({
            "vehicle_name":     name,
            "avg_utilisation":  row["avg_utilisation_pct"],
            "status_label":     label,
            "status_colour":    colour,
            "annual_cost_inr":  ann_cost,
            "feasible":         feasibility["feasible"],
            "action":           action,
            "recommendation":   recommendation_text,
            "new_utilisation":  feasibility.get("new_utilisation", {}),
            "absorbing_vehicles": feasibility.get("absorbing_vehicles", []),
        })

    recommendations.sort(key=lambda x: x["annual_cost_inr"], reverse=True)
    return recommendations


def build_utilisation_chart_data(util_df: pd.DataFrame) -> pd.DataFrame:
    """
    Build the time-series utilisation data for the trend chart.
    Returns daily average utilisation per vehicle, working days only.
    """
    working = util_df[util_df["date"].apply(lambda d: d.weekday() < 5)].copy()
    working["date_str"] = working["date"].astype(str)
    return working[["date_str", "vehicle_name", "utilisation_pct", "load_kg", "km_driven"]]