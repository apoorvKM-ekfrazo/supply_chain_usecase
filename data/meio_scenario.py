"""
data/meio_scenario.py
---------------------
Synthetic 30-day demand history for the MEIO (Multi-Echelon Inventory
Optimisation) demo module.

This file generates the "historical data" that makes the MEIO analysis
credible. It produces three datasets:

  1. Daily delivery counts by zone — the core demand signal. Used to
     compute which zones are high-traffic and which candidate warehouse
     location would reduce total routing cost most.

  2. Vehicle utilisation history — daily load_kg / capacity_kg for each
     vehicle over 30 days. Used to identify underutilised vehicles and
     compute the financial case for fleet right-sizing.

  3. A pre-seeded recommendation history — simulates 7 days of historical
     MEIO recommendations, used to populate the strategic alert system.

Design principles for the synthetic data:
  - Demand is concentrated in the eastern and south-eastern zones
    (Koramangala, Indiranagar, Whitefield, Marathahalli) because those
    zones are furthest from the Bommanahalli depot. This makes the case
    for a second warehouse in that direction compelling and intuitive.
  - Mahindra Van 2 is deliberately underutilised (~40%) while the other
    vehicles run at 80-90%, creating a clear fleet right-sizing signal.
  - All numbers are realistic for a mid-size Bengaluru distribution
    operation. Weekly and monthly patterns reflect Indian business rhythms.
"""

import numpy as np
import pandas as pd
from datetime import date, timedelta
from typing import Dict, List

# ── Constants shared with the route optimizer ─────────────────────────────────
# These must match the hub names in data/scenario.py so the two modules
# can refer to the same zones without confusion.
ZONES = [
    "Koramangala",
    "Indiranagar",
    "Whitefield",
    "Electronic City",
    "Marathahalli",
    "JP Nagar",
    "Hebbal",
    "Jayanagar",
    "MG Road / CBD",
]

# Depot coordinates — Bommanahalli, as used throughout the route optimizer.
DEPOT = {"lat": 12.9150, "lng": 77.6180, "name": "Bommanahalli Depot"}

# Candidate warehouse locations for the placement analysis.
# Each entry has the coordinates, a realistic Bengaluru lease rate (₹/sq ft/month
# for industrial/logistics space, calibrated to 2024-25 market rates), and a
# minimum viable space of 2,000 sq ft for a small city distribution hub.
CANDIDATE_WAREHOUSES = [
    {
        "name": "Marathahalli Hub",
        "lat": 12.9591,
        "lng": 77.7012,
        "lease_per_sqft_per_month": 28,   # ₹/sq ft/month, east Bengaluru industrial
        "min_sqft": 2000,
        "zone": "Marathahalli",
        "description": "Strong coverage for Whitefield, Indiranagar, Koramangala corridors",
    },
    {
        "name": "Electronic City Hub",
        "lat": 12.8406,
        "lng": 77.6770,
        "lease_per_sqft_per_month": 18,   # cheaper, outer ring road
        "min_sqft": 2000,
        "zone": "Electronic City",
        "description": "Best for south Bengaluru; Electronic City, JP Nagar, Jayanagar",
    },
    {
        "name": "Hebbal Hub",
        "lat": 13.0358,
        "lng": 77.5970,
        "lease_per_sqft_per_month": 22,   # north Bengaluru near airport corridor
        "min_sqft": 2000,
        "zone": "Hebbal",
        "description": "Covers north Bengaluru, airport corridor, MG Road via Outer Ring Road",
    },
    {
        "name": "Whitefield Hub",
        "lat": 12.9698,
        "lng": 77.7500,
        "lease_per_sqft_per_month": 32,   # premium, tech-park area
        "min_sqft": 2000,
        "zone": "Whitefield",
        "description": "Dedicated east corridor hub; Whitefield, ITPL, Marathahalli",
    },
]

# Vehicle fleet — mirrors the route optimizer exactly.
VEHICLES = [
    {"name": "Tata Ace 1",    "type": "mini-truck", "capacity_kg": 400, "fuel_cost_per_km": 5.60},
    {"name": "Tata Ace 2",    "type": "mini-truck", "capacity_kg": 400, "fuel_cost_per_km": 5.60},
    {"name": "Mahindra Van 1","type": "van",         "capacity_kg": 250, "fuel_cost_per_km": 11.25},
    {"name": "Mahindra Van 2","type": "van",         "capacity_kg": 250, "fuel_cost_per_km": 11.25},
    {"name": "Courier Bike",  "type": "bike",        "capacity_kg":  30, "fuel_cost_per_km": 2.45},
]

# Annual vehicle operating costs (₹) — realistic Indian estimates.
# These feed the fleet right-sizing recommendation.
VEHICLE_ANNUAL_COSTS = {
    "Tata Ace 1":     {"insurance": 18000, "maintenance": 35000, "driver": 240000, "depreciation": 60000},
    "Tata Ace 2":     {"insurance": 18000, "maintenance": 35000, "driver": 240000, "depreciation": 60000},
    "Mahindra Van 1": {"insurance": 15000, "maintenance": 30000, "driver": 220000, "depreciation": 50000},
    "Mahindra Van 2": {"insurance": 15000, "maintenance": 30000, "driver": 220000, "depreciation": 50000},
    "Courier Bike":   {"insurance":  4000, "maintenance": 12000, "driver": 180000, "depreciation": 20000},
}


# ── Zone demand profile ───────────────────────────────────────────────────────
# Base daily deliveries per zone, scaled to represent a realistic mid-sized
# Bengaluru B2B distributor running ~300 stops/day across the city.
# The original 120-stop demo scenario is appropriate for route visualisation
# but too small for MEIO analysis — the routing savings from adding a warehouse
# are too small to justify any lease cost at that scale.
#
# Why eastern zones are heavier: Koramangala, Indiranagar, Whitefield, and
# Marathahalli are the fastest-growing commercial corridors in Bengaluru.
# A distributor would naturally see 60-70% of their volume in those zones.
# This concentration is also what motivates the Marathahalli warehouse
# recommendation — adding a hub there dramatically shortens routes to the
# zones that currently require the longest drives from Bommanahalli.
ZONE_BASE_DEMAND = {
    "Koramangala":     55,   # dense commercial — restaurants, retail, offices
    "Indiranagar":     45,   # tech & lifestyle corridor
    "Whitefield":      40,   # largest tech-park cluster, growing rapidly
    "Electronic City": 35,   # industrial south, Infosys/Wipro campuses
    "Marathahalli":    35,   # growing east suburb, ORR junction
    "JP Nagar":        30,   # residential south, steady demand
    "Hebbal":          25,   # north corridor, airport logistics
    "Jayanagar":       22,   # older residential, stable
    "MG Road / CBD":   18,   # inner city, parking-constrained, lower volume
}


def _weekly_multiplier(weekday: int) -> float:
    """
    Delivery volumes follow a weekly pattern. Monday/Tuesday are heavy
    (retail restocking), mid-week moderate, Friday lighter (pre-weekend
    deliveries routed early), weekends very low.
    """
    # weekday(): 0=Monday, 6=Sunday
    pattern = {0: 1.15, 1: 1.10, 2: 1.00, 3: 0.95, 4: 0.90, 5: 0.40, 6: 0.20}
    return pattern.get(weekday, 1.0)


def generate_demand_history(
    days: int = 30,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Generate 30 days of synthetic daily delivery demand by zone.

    Returns a DataFrame with columns:
      date, zone, deliveries, weight_kg, avg_weight_per_delivery

    The demand has three components:
      1. Base level per zone (ZONE_BASE_DEMAND)
      2. Weekly seasonality via _weekly_multiplier
      3. Small random noise (±15%) to make it look like real data

    The weight per delivery is drawn from a realistic Indian FMCG/retail
    distribution: most packages are 5-20kg with a long tail up to 80kg.
    """
    rng   = np.random.default_rng(seed)
    start = date(2026, 4, 12)   # 30 days ending just before "today"
    rows  = []

    for day_offset in range(days):
        current_date = start + timedelta(days=day_offset)
        wday_mult    = _weekly_multiplier(current_date.weekday())

        for zone, base in ZONE_BASE_DEMAND.items():
            # Scale by weekday pattern and add ±15% noise
            noise        = rng.uniform(0.85, 1.15)
            deliveries   = max(1, int(round(base * wday_mult * noise)))

            # Average package weight: log-normal centred around 12kg
            avg_weight   = float(np.clip(rng.lognormal(2.5, 0.5), 3, 80))
            total_weight = round(deliveries * avg_weight, 1)

            rows.append({
                "date":                   current_date,
                "zone":                   zone,
                "deliveries":             deliveries,
                "weight_kg":              total_weight,
                "avg_weight_per_delivery": round(avg_weight, 1),
            })

    return pd.DataFrame(rows)


def generate_vehicle_utilisation(
    days: int = 30,
    seed: int = 99,
) -> pd.DataFrame:
    """
    Generate 30 days of synthetic vehicle utilisation data.

    Returns a DataFrame with columns:
      date, vehicle_name, capacity_kg, load_kg, utilisation_pct,
      km_driven, fuel_cost_inr, overtime_min

    Key design decision: Mahindra Van 2 is deliberately underutilised
    (~40% on average) to create a clear fleet right-sizing signal. The
    other vehicles run at 80-90% to show the fleet is otherwise well-used.

    The underutilisation is intentional: in practice, it often happens
    because a van was purchased for a large contract that later shrank,
    or because routing was never re-optimised after a warehouse move.
    """
    rng   = np.random.default_rng(seed)
    start = date(2026, 4, 12)
    rows  = []

    # Target average utilisation per vehicle (what the synthetic data aims for).
    # Mahindra Van 2 is deliberately underutilised at ~38% to create a clear
    # fleet right-sizing signal. The other vehicles run at 70-85% — healthy
    # but with enough spare capacity (10-20% headroom) to absorb redistribution.
    # At 90%+ the redistribution feasibility check fails because there is no
    # room to absorb Mahindra Van 2's load without exceeding the ceiling.
    target_util = {
        "Tata Ace 1":     0.78,
        "Tata Ace 2":     0.75,
        "Mahindra Van 1": 0.74,
        "Mahindra Van 2": 0.38,   # ← the under-utilised vehicle
        "Courier Bike":   0.68,
    }

    # Typical km per day per vehicle based on route optimizer results
    base_km = {
        "Tata Ace 1":     50,
        "Tata Ace 2":     65,
        "Mahindra Van 1": 54,
        "Mahindra Van 2": 38,
        "Courier Bike":   37,
    }

    for day_offset in range(days):
        current_date = start + timedelta(days=day_offset)
        wday_mult    = _weekly_multiplier(current_date.weekday())

        for v in VEHICLES:
            name     = v["name"]
            capacity = v["capacity_kg"]
            target   = target_util[name]

            # Load fluctuates around target utilisation with ±12% daily noise
            daily_util = float(np.clip(
                rng.normal(target * wday_mult, 0.08), 0.05, 0.99
            ))
            load_kg    = round(capacity * daily_util, 1)

            # km driven — scale with load and add noise
            km = float(np.clip(
                rng.normal(base_km[name] * wday_mult, 5), 5, 150
            ))

            # Fuel cost
            fuel = round(km * v["fuel_cost_per_km"], 0)

            # Overtime: only when utilisation is high; Mahindra Van 2 rarely has overtime
            if daily_util > 0.85 and name != "Mahindra Van 2":
                overtime_min = float(np.clip(rng.normal(45, 20), 0, 120))
            else:
                overtime_min = 0.0

            rows.append({
                "date":             current_date,
                "vehicle_name":     name,
                "vehicle_type":     v["type"],
                "capacity_kg":      capacity,
                "load_kg":          load_kg,
                "utilisation_pct":  round(daily_util * 100, 1),
                "km_driven":        round(km, 1),
                "fuel_cost_inr":    fuel,
                "overtime_min":     round(overtime_min, 1),
            })

    return pd.DataFrame(rows)


def get_demand_summary(demand_df: pd.DataFrame) -> Dict:
    """
    Compute summary statistics from the demand history.
    Used by the MEIO module to populate the Current Network Overview.
    """
    # Working days only (Mon-Fri), matching the route optimizer's assumption
    working_days = demand_df[demand_df["date"].apply(
        lambda d: d.weekday() < 5
    )]

    by_zone = (
        working_days
        .groupby("zone")
        .agg(
            avg_daily_deliveries=("deliveries", "mean"),
            total_deliveries=("deliveries", "sum"),
            avg_weight_kg=("weight_kg", "mean"),
        )
        .reset_index()
    )
    by_zone["avg_daily_deliveries"] = by_zone["avg_daily_deliveries"].round(1)
    by_zone["avg_weight_kg"]        = by_zone["avg_weight_kg"].round(0)

    total_avg_daily = working_days.groupby("date")["deliveries"].sum().mean()

    return {
        "by_zone":            by_zone,
        "total_avg_daily":    round(total_avg_daily, 0),
        "busiest_zone":       by_zone.loc[by_zone["avg_daily_deliveries"].idxmax(), "zone"],
        "quietest_zone":      by_zone.loc[by_zone["avg_daily_deliveries"].idxmin(), "zone"],
        "total_working_days": working_days["date"].nunique(),
    }


def get_utilisation_summary(util_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-vehicle average utilisation statistics over the history period.
    """
    # Again, working days only
    working = util_df[util_df["date"].apply(lambda d: d.weekday() < 5)]

    summary = (
        working
        .groupby("vehicle_name")
        .agg(
            avg_utilisation_pct=("utilisation_pct", "mean"),
            avg_km_driven=("km_driven", "mean"),
            avg_fuel_cost=("fuel_cost_inr", "mean"),
            total_overtime_min=("overtime_min", "sum"),
            avg_load_kg=("load_kg", "mean"),
        )
        .reset_index()
    )

    # Look up capacity for each vehicle
    cap_lookup = {v["name"]: v["capacity_kg"] for v in VEHICLES}
    summary["capacity_kg"]         = summary["vehicle_name"].map(cap_lookup)
    summary["avg_utilisation_pct"] = summary["avg_utilisation_pct"].round(1)
    summary["avg_km_driven"]       = summary["avg_km_driven"].round(1)
    summary["avg_fuel_cost"]       = summary["avg_fuel_cost"].round(0)
    summary["total_overtime_hrs"]  = (summary["total_overtime_min"] / 60).round(1)

    # Annual cost for each vehicle
    summary["annual_cost_inr"] = summary["vehicle_name"].apply(
        lambda n: sum(VEHICLE_ANNUAL_COSTS.get(n, {}).values())
    )

    return summary.drop(columns=["total_overtime_min"])





