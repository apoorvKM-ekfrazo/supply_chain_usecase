"""
optimizer/metrics.py
--------------------
Converts raw route output from baseline.py and solver.py into
business-meaningful metrics: rupees, hours, kilograms of CO₂.

Design principle:
  Both the baseline and the optimized solver return the same dict structure,
  so this module processes either one identically. The comparison is simply
  computed_metrics(optimized) vs computed_metrics(baseline), and the delta
  is what you show in the demo's hero panel.

Why convert to money?
  A logistics manager cares about "we saved ₹18,400 in fuel this week."
  They do not care about "we reduced total distance by 847 km." The number
  only becomes persuasive once it's in the same currency as their budget.
  This translation step is what separates a technical demo from a sales demo.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional
import pandas as pd


# ── CO₂ Equivalents (for tangible framing) ────────────────────────────────────
# These are published equivalence factors used in sustainability reporting.
# Source: EPA GHG Equivalencies Calculator (converted to metric/Indian context)
KG_CO2_PER_TREE_PER_YEAR    = 21.77   # One mature tree absorbs ~21.77 kg CO₂/year
KG_CO2_PER_MUMBAI_BLR_FLIGHT = 90.0  # Economy seat, one-way, ~90 kg CO₂
KG_CO2_PER_KWH              = 0.82    # India grid average emission factor


@dataclass
class RouteMetrics:
    """
    All metrics for a single routing solution (baseline or optimized).
    Stored as a dataclass so it's easy to serialize, compare, and display.
    """
    # ── Volume metrics ─────────────────────────────────────────────────────
    total_distance_km:    float = 0.0
    total_time_hours:     float = 0.0
    total_overtime_hours: float = 0.0
    stops_served:         int   = 0
    stops_dropped:        int   = 0
    tw_violations:        int   = 0
    on_time_pct:          float = 0.0

    # ── Cost metrics (INR) ────────────────────────────────────────────────
    fuel_cost_inr:     float = 0.0
    overtime_cost_inr: float = 0.0
    total_cost_inr:    float = 0.0
    cost_per_delivery: float = 0.0

    # ── Environmental metrics ─────────────────────────────────────────────
    co2_kg:            float = 0.0
    co2_trees_equiv:   float = 0.0
    co2_flights_equiv: float = 0.0

    # ── Per-vehicle breakdown ─────────────────────────────────────────────
    vehicle_breakdown: Dict = field(default_factory=dict)


def compute_metrics(
    result:            dict,
    total_stops:       int,
    fuel_cost_per_km:  float,
    hourly_wage_inr:   float,
    co2_per_km:        float,
) -> RouteMetrics:
    """
    Given a raw result dict from baseline.py or solver.py, compute the full
    set of business metrics and return a RouteMetrics dataclass.

    Parameters
    ----------
    result            : Output dict from run_baseline() or run_solver()
    total_stops       : Total stops in the scenario (to calculate drops)
    fuel_cost_per_km  : ₹ per km (from sidebar slider)
    hourly_wage_inr   : ₹ per driver per hour (from sidebar slider)
    co2_per_km        : kg CO₂ per km (from sidebar slider)
    """
    routes        = result["routes"]
    stops_served  = result["total_stops_served"]
    stops_dropped = total_stops - stops_served

    total_dist     = result["total_distance_km"]
    total_overtime = result["total_overtime_min"] / 60   # convert to hours
    total_time_hrs = sum(
        r["total_time_min"] / 60 for r in routes.values()
    )
    tw_violations  = result["total_tw_violations"]

    # On-time delivery % — what fraction of stops were served within their window
    # (lower tw_violations = higher on-time %)
    on_time_pct = round(
        ((stops_served - tw_violations) / max(stops_served, 1)) * 100, 1
    )

    # ── Cost calculations ─────────────────────────────────────────────────────
    fuel_cost      = round(total_dist * fuel_cost_per_km, 0)
    # Overtime cost: overtime hours across all drivers × hourly wage
    # (we use 1.5× rate for overtime, which is standard in Indian labour law)
    overtime_cost  = round(total_overtime * hourly_wage_inr * 1.5, 0)
    total_cost     = fuel_cost + overtime_cost
    cost_per_deliv = round(total_cost / max(stops_served, 1), 2)

    # ── CO₂ calculations ──────────────────────────────────────────────────────
    co2_kg          = round(total_dist * co2_per_km, 2)
    co2_trees       = round(co2_kg / KG_CO2_PER_TREE_PER_YEAR, 1)
    co2_flights     = round(co2_kg / KG_CO2_PER_MUMBAI_BLR_FLIGHT, 1)

    # ── Per-vehicle breakdown ─────────────────────────────────────────────────
    vehicle_breakdown = {}
    for v_id, route in routes.items():
        dist  = route["total_distance_km"]
        ot    = route["overtime_min"] / 60
        load  = route["load_kg"]
        n_stops = len(route["stop_sequence"])
        vehicle_breakdown[v_id] = {
            "stops":         n_stops,
            "distance_km":   dist,
            "load_kg":       load,
            "overtime_hrs":  round(ot, 2),
            "fuel_cost_inr": round(dist * fuel_cost_per_km, 0),
            "ot_cost_inr":   round(ot * hourly_wage_inr * 1.5, 0),
            "co2_kg":        round(dist * co2_per_km, 2),
            "tw_violations": route["tw_violations"],
        }

    return RouteMetrics(
        total_distance_km    = round(total_dist, 2),
        total_time_hours     = round(total_time_hrs, 2),
        total_overtime_hours = round(total_overtime, 2),
        stops_served         = stops_served,
        stops_dropped        = stops_dropped,
        tw_violations        = tw_violations,
        on_time_pct          = on_time_pct,
        fuel_cost_inr        = fuel_cost,
        overtime_cost_inr    = overtime_cost,
        total_cost_inr       = total_cost,
        cost_per_delivery    = cost_per_deliv,
        co2_kg               = co2_kg,
        co2_trees_equiv      = co2_trees,
        co2_flights_equiv    = co2_flights,
        vehicle_breakdown    = vehicle_breakdown,
    )


def compute_savings(
    optimized: RouteMetrics,
    baseline:  RouteMetrics,
) -> Dict:
    """
    Compute the delta between optimized and baseline metrics.
    All 'saved' values are positive when the optimizer did better.
    This dict is what populates the hero savings panel in the UI.
    """
    return {
        # Distance and time
        "distance_km_saved":    round(baseline.total_distance_km    - optimized.total_distance_km,    2),
        "overtime_hrs_saved":   round(baseline.total_overtime_hours - optimized.total_overtime_hours, 2),
        "time_hrs_saved":       round(baseline.total_time_hours     - optimized.total_time_hours,     2),

        # Quality
        "tw_violations_fixed":  baseline.tw_violations  - optimized.tw_violations,
        "on_time_improvement":  round(optimized.on_time_pct - baseline.on_time_pct, 1),
        "extra_stops_served":   optimized.stops_served  - baseline.stops_served,

        # Money
        "fuel_saved_inr":       round(baseline.fuel_cost_inr     - optimized.fuel_cost_inr,     0),
        "overtime_saved_inr":   round(baseline.overtime_cost_inr - optimized.overtime_cost_inr, 0),
        "total_saved_inr":      round(baseline.total_cost_inr    - optimized.total_cost_inr,    0),

        # Environment
        "co2_kg_saved":         round(baseline.co2_kg - optimized.co2_kg, 2),
        "co2_trees_saved":      round(baseline.co2_trees_equiv - optimized.co2_trees_equiv, 1),

        # Percentage improvements (for callout cards)
        "distance_pct_saved":   round(
            (baseline.total_distance_km - optimized.total_distance_km)
            / max(baseline.total_distance_km, 1) * 100, 1
        ),
        "cost_pct_saved":       round(
            (baseline.total_cost_inr - optimized.total_cost_inr)
            / max(baseline.total_cost_inr, 1) * 100, 1
        ),
    }


def format_inr(amount: float) -> str:
    """Format a rupee amount with Indian number formatting (lakhs, crores)."""
    amount = int(amount)
    if amount >= 10_000_000:
        return f"₹{amount/10_000_000:.2f} Cr"
    elif amount >= 100_000:
        return f"₹{amount/100_000:.2f} L"
    elif amount >= 1_000:
        return f"₹{amount:,}"
    return f"₹{amount}"


def get_weekly_projection(daily_savings_inr: float) -> Dict:
    """
    Project daily savings to weekly/monthly/annual figures.
    This is a powerful demo move — ₹18,000 saved today sounds modest,
    but ₹54 lakh saved annually lands very differently in a boardroom.
    """
    weekly  = daily_savings_inr * 5     # 5 working days
    monthly = daily_savings_inr * 22    # ~22 working days per month
    annual  = daily_savings_inr * 264   # 12 × 22

    return {
        "daily":   format_inr(daily_savings_inr),
        "weekly":  format_inr(weekly),
        "monthly": format_inr(monthly),
        "annual":  format_inr(annual),
    }





