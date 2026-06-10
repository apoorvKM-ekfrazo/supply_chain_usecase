"""
data/scenario.py
----------------
Generates a realistic delivery scenario anchored to real Bengaluru geography.

Design philosophy:
- Coordinates come from real Bengaluru commercial/residential hubs via a
  mixture-of-Gaussians model. Each Gaussian is centred on a real neighbourhood,
  so stops cluster the way actual orders do — dense in Koramangala, sparser
  toward Whitefield — without needing to clean an external dataset.
- Operational attributes (time windows, weights, priorities) are generated
  synthetically but follow real-world distributions documented in last-mile
  logistics research (20% tight windows, 5% VIP/priority, etc.).
- A deliberate "slow client" (CLIENT_X) is seeded into the data so the
  anomaly-flagging module has something meaningful to detect.
- Random seed is fixed so the scenario is reproducible across demo runs.
  Change RANDOM_SEED to get a different-but-equally-valid scenario.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Tuple

# ── Reproducibility ──────────────────────────────────────────────────────────
RANDOM_SEED = 42
rng = np.random.default_rng(RANDOM_SEED)

# ── Depot (Central Warehouse) ─────────────────────────────────────────────────
# Placed near Bommanahalli — a real industrial/logistics corridor in south Bengaluru
# that sits roughly central to all our delivery zones.
DEPOT = {
    "name": "Central Warehouse",
    "lat": 12.8958,
    "lng": 77.6180,
}

# ── Bengaluru Neighbourhood Hubs ──────────────────────────────────────────────
# Each hub is a real Bengaluru landmark / commercial cluster.
# 'weight' controls how many stops spawn around each hub.
# 'spread' is the standard deviation in degrees.
#
# Previous spreads were 0.008–0.015° (≈ 900m–1.7km radius), which caused stops
# to land in lakes, on highways, and in open land — producing strange ORS routes.
# New spreads are 0.003–0.005° (≈ 330m–550m radius), keeping every stop within
# the walkable street grid of its neighbourhood.
#
# Reference: 1° latitude ≈ 111km, so 0.005° ≈ 555m. At 2σ that means 95% of
# stops land within about 1.1km of the hub centre — well within neighbourhood
# boundaries and away from lakes, highway medians, and open land.
HUBS = [
    {"name": "Koramangala",    "lat": 12.9352, "lng": 77.6245, "weight": 0.18, "spread": 0.004},
    {"name": "Indiranagar",    "lat": 12.9784, "lng": 77.6408, "weight": 0.15, "spread": 0.004},
    {"name": "Whitefield",     "lat": 12.9698, "lng": 77.7500, "weight": 0.12, "spread": 0.005},
    {"name": "Electronic City","lat": 12.8406, "lng": 77.6770, "weight": 0.10, "spread": 0.004},
    {"name": "Marathahalli",   "lat": 12.9591, "lng": 77.7012, "weight": 0.10, "spread": 0.004},
    {"name": "JP Nagar",       "lat": 12.9102, "lng": 77.5836, "weight": 0.10, "spread": 0.004},
    {"name": "Hebbal",         "lat": 13.0358, "lng": 77.5970, "weight": 0.08, "spread": 0.003},
    {"name": "Jayanagar",      "lat": 12.9299, "lng": 77.5831, "weight": 0.09, "spread": 0.004},
    {"name": "MG Road / CBD",  "lat": 12.9716, "lng": 77.6099, "weight": 0.08, "spread": 0.003},
]

# ── Fleet Configuration ───────────────────────────────────────────────────────
# Real mixed fleets have heterogeneous vehicles. A small courier bike can't
# carry the same load as a Tata Ace. We model three vehicle types.
VEHICLES = [
    {"id": 0, "name": "Tata Ace 1",     "capacity_kg": 400, "type": "mini-truck"},
    {"id": 1, "name": "Tata Ace 2",     "capacity_kg": 400, "type": "mini-truck"},
    {"id": 2, "name": "Mahindra Van 1", "capacity_kg": 250, "type": "van"},
    {"id": 3, "name": "Mahindra Van 2", "capacity_kg": 250, "type": "van"},
    {"id": 4, "name": "Courier Bike",   "capacity_kg": 30,  "type": "bike"},
]

# ── Scenario Parameters ───────────────────────────────────────────────────────
NUM_STOPS       = 120
MAX_SHIFT_HOURS = 8          # Max working hours per driver before overtime
LUNCH_BREAK_MIN = 30         # Mandatory break baked into shift time

# Time window definitions (hours from 08:00 start of day)
# A "tight" window means the customer has a specific requirement.
# A "flexible" window covers the entire working day.
FLEXIBLE_WINDOW  = (0, 8)    # Any time during the shift
MORNING_WINDOW   = (0, 3)    # Must arrive before 11:00
AFTERNOON_WINDOW = (4, 7)    # Must arrive after 12:00

# Package weight distribution by stop type (kg)
# Most deliveries are light parcels; some are heavy commercial shipments.
WEIGHT_LIGHT    = (1,  10)   # Small parcels
WEIGHT_MEDIUM   = (10, 50)   # Mid-size commercial
WEIGHT_HEAVY    = (50, 150)  # Large commercial — only for mini-trucks


@dataclass
class Stop:
    """A single delivery stop with all attributes the optimizer needs."""
    stop_id:          int
    name:             str          # Human-readable label (neighbourhood + index)
    lat:              float
    lng:              float
    weight_kg:        float        # Package weight
    time_window:      Tuple[int, int]  # (earliest, latest) hours from shift start
    is_priority:      bool         # VIP / must-serve flag
    is_slow_client:   bool         # CLIENT_X flag for anomaly demo
    service_time_min: int          # Estimated unloading time at stop (minutes)
    zone:             str          # Neighbourhood name — used for baseline routing


def _assign_time_window() -> Tuple[Tuple[int, int], str]:
    """
    Randomly assign a time window following realistic distribution:
    - 60% flexible (all day)
    - 25% morning window (tight)
    - 15% afternoon window (tight)
    Returns the window tuple and a label string for UI display.
    """
    roll = rng.random()
    if roll < 0.60:
        return FLEXIBLE_WINDOW,  "Flexible"
    elif roll < 0.85:
        return MORNING_WINDOW,   "Morning (tight)"
    else:
        return AFTERNOON_WINDOW, "Afternoon (tight)"


def generate_stops() -> pd.DataFrame:
    """
    Generate NUM_STOPS delivery stops anchored to Bengaluru geography.

    The mixture-of-Gaussians approach works like this:
    1. For each stop, pick a hub according to hub weights (like a weighted dice roll).
    2. Add Gaussian noise around that hub's centre — spread controls how tightly
       stops cluster around the hub.
    3. This gives us geographic distributions that look like real order data:
       dense clusters near commercial hubs, natural thinning toward edges.
    """
    hub_weights = np.array([h["weight"] for h in HUBS])
    hub_weights /= hub_weights.sum()  # Normalise to sum=1

    stops = []
    slow_client_assigned = False   # We seed exactly ONE slow client for the demo

    for i in range(NUM_STOPS):
        # Step 1: pick a hub
        hub_idx = rng.choice(len(HUBS), p=hub_weights)
        hub = HUBS[hub_idx]

        # Step 2: scatter around that hub
        lat = rng.normal(hub["lat"], hub["spread"])
        lng = rng.normal(hub["lng"], hub["spread"])

        # Step 3: assign operational attributes
        time_window, window_label = _assign_time_window()

        # Priority stops (5% of total) — must-serve, flagged in red on the map
        is_priority = (rng.random() < 0.05)

        # The slow client — exactly one stop, placed in Koramangala (hub 0)
        # so it's in a busy area where the delay ripple is realistic.
        # This stop is what the anomaly flagging module will learn to detect.
        is_slow_client = False
        service_time = int(rng.integers(8, 18))   # Normal: 8–17 min unloading

        if not slow_client_assigned and hub_idx == 0 and i > 10:
            is_slow_client    = True
            slow_client_assigned = True
            service_time      = 35   # CLIENT_X: always takes ~35 min
            is_priority       = True  # They're also a priority client

        # Weight: bike stops only get light packages (enforced in solver too)
        weight = float(rng.integers(*WEIGHT_LIGHT))

        stops.append({
            "stop_id":          i + 1,
            "name":             f"{hub['name']} #{i+1}",
            "lat":              round(lat, 6),
            "lng":              round(lng, 6),
            "weight_kg":        weight,
            "tw_start":         time_window[0],   # hours from shift start
            "tw_end":           time_window[1],
            "window_label":     window_label,
            "is_priority":      is_priority,
            "is_slow_client":   is_slow_client,
            "service_time_min": service_time,
            "zone":             hub["name"],
        })

    df = pd.DataFrame(stops)

    # One last pass: mark 5 random stops as heavy commercial and ensure
    # they will only be assigned to mini-trucks (capacity check in solver).
    heavy_indices = rng.choice(df.index, size=5, replace=False)
    df.loc[heavy_indices, "weight_kg"] = rng.uniform(80, 150, size=5).round(1)

    return df


def get_depot() -> dict:
    """Return depot configuration — single source of truth used by all modules."""
    return DEPOT.copy()


def get_vehicles() -> pd.DataFrame:
    """Return fleet configuration as a DataFrame."""
    return pd.DataFrame(VEHICLES)


def get_scenario_summary(stops_df: pd.DataFrame) -> dict:
    """
    Compute high-level scenario stats displayed in the sidebar.
    Helps orient the client before optimization runs.
    """
    return {
        "total_stops":      len(stops_df),
        "priority_stops":   int(stops_df["is_priority"].sum()),
        "tight_windows":    int((stops_df["window_label"] != "Flexible").sum()),
        "total_weight_kg":  round(stops_df["weight_kg"].sum(), 1),
        "slow_clients":     int(stops_df["is_slow_client"].sum()),
        "zones_covered":    stops_df["zone"].nunique(),
    }


if __name__ == "__main__":
    # Quick sanity check — run this file directly to verify data looks correct
    stops = generate_stops()
    depot = get_depot()
    vehicles = get_vehicles()
    summary = get_scenario_summary(stops)

    print("\n── Depot ────────────────────────────────")
    print(f"  {depot['name']}  ({depot['lat']}, {depot['lng']})")

    print("\n── Fleet ────────────────────────────────")
    print(vehicles.to_string(index=False))

    print("\n── Scenario Summary ─────────────────────")
    for k, v in summary.items():
        print(f"  {k:<20} {v}")

    print("\n── First 5 Stops ────────────────────────")
    print(stops[["stop_id", "name", "lat", "lng",
                 "weight_kg", "window_label", "is_priority",
                 "is_slow_client", "service_time_min"]].head().to_string(index=False))

    print(f"\n── Total weight across all stops: {stops['weight_kg'].sum():.1f} kg")
    print(f"── Fleet total capacity: {vehicles['capacity_kg'].sum()} kg")