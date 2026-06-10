"""
optimizer/solver.py  (v3 — cost vs time objective toggle)
----------------------------------------------------------
What changed from v2:
  - run_solver() now accepts an 'objective' parameter: "cost" or "time".
  - "cost" (default): minimises total distance in metres — same as before.
  - "time": minimises total travel + service time in minutes. The arc cost
    evaluator is switched from the distance callback to the time callback.
    One line change. Everything else (constraints, penalties, search) is
    identical between the two modes.

This is the cleanest possible demonstration that the solver is flexible —
same constraints, same data, different goal, visibly different routes.
"""

import numpy as np
import pandas as pd
from math import radians, sin, cos, sqrt, atan2
from typing import Dict, Optional
from ortools.constraint_solver import routing_enums_pb2, pywrapcp

AVG_SPEED_KMH         = 25.0
MAX_SHIFT_MIN         = 8 * 60
LUNCH_BREAK_MIN       = 30
SOLVER_TIME_LIMIT_SEC = 60
REGULAR_DROP_PENALTY  = 500_000
PRIORITY_DROP_PENALTY = 1_000_000


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    R = 6371
    lat1, lng1, lat2, lng2 = map(radians, [lat1, lng1, lat2, lng2])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlng/2)**2
    return 2 * R * atan2(sqrt(a), sqrt(1-a))


def build_distance_matrix(stops_df, depot, penalised_arcs=None, extra_depots=None):
    """
    Build the all-pairs distance matrix in integer metres.

    extra_depots: optional list of additional depot dicts. When provided,
      these are inserted as additional nodes at the front of the node list
      (indices 0, 1, 2... for the depots, then N+1 onward for stops).
      This is how multi-depot routing is implemented: OR-Tools is given
      a start/end node index per vehicle that points to the correct depot.

    penalised_arcs: list of (from_stop_id, to_stop_id) tuples whose distance
      is set to near-infinity, forcing the solver to route around them.
    """
    # Build the node list: depots first, then delivery stops
    depot_nodes = [{"lat": depot["lat"], "lng": depot["lng"], "type": "depot"}]
    if extra_depots:
        for ed in extra_depots:
            depot_nodes.append({"lat": ed["lat"], "lng": ed["lng"], "type": "depot"})

    stop_nodes = []
    for _, row in stops_df.iterrows():
        stop_nodes.append({
            "lat":              row["lat"],
            "lng":              row["lng"],
            "stop_id":          row["stop_id"],
            "weight_kg":        row["weight_kg"],
            "tw_start_min":     int(row["tw_start"] * 60),
            "tw_end_min":       int(row["tw_end"]   * 60),
            "service_time_min": int(row["service_time_min"]),
            "is_priority":      row["is_priority"],
            "is_slow_client":   row["is_slow_client"],
            "name":             row["name"],
            "zone":             row["zone"],
            "window_label":     row["window_label"],
            "type":             "stop",
        })

    nodes = depot_nodes + stop_nodes
    n     = len(nodes)
    matrix = np.zeros((n, n), dtype=int)

    for i in range(n):
        for j in range(n):
            if i != j:
                matrix[i][j] = int(
                    haversine_km(nodes[i]["lat"], nodes[i]["lng"],
                                 nodes[j]["lat"], nodes[j]["lng"]) * 1000
                )

    # Apply road-blocked penalties
    if penalised_arcs:
        stop_id_to_idx = {}
        for idx, node in enumerate(nodes):
            if node["type"] == "depot":
                stop_id_to_idx[None] = idx   # last depot written wins — acceptable
            else:
                stop_id_to_idx[node["stop_id"]] = idx

        BLOCKED_COST = 1_000_000_000
        for from_sid, to_sid in penalised_arcs:
            from_idx = stop_id_to_idx.get(from_sid)
            to_idx   = stop_id_to_idx.get(to_sid)
            if from_idx is not None and to_idx is not None:
                matrix[from_idx][to_idx] = BLOCKED_COST
                print(f"  Blocked arc: {from_sid} → {to_sid}")

    return matrix, nodes


def build_time_matrix(distance_matrix):
    speed_m_per_min = (AVG_SPEED_KMH * 1000) / 60
    return (distance_matrix / speed_m_per_min).astype(int)


def run_solver(
    stops_df:       pd.DataFrame,
    vehicles_df:    pd.DataFrame,
    depot:          dict,
    objective:      str  = "cost",
    penalised_arcs: list = None,
    vehicle_depots: list = None,
) -> Optional[Dict]:
    """
    Run the OR-Tools VRP solver.

    vehicle_depots: optional list of depot dicts, one per vehicle. When
      provided (by the MEIO connection button), each vehicle starts and
      ends its route at its assigned depot rather than the shared default.
      This implements two-depot routing: some vehicles depart from the
      original Bommanahalli warehouse, others from the MEIO-recommended
      second warehouse. The solver treats each vehicle independently
      with its own start/end node, producing routes that fan out from
      two different geographic origins.

    penalised_arcs: optional list of (from_stop_id, to_stop_id) tuples.
      When provided, those arcs are set to near-infinite cost, forcing
      the solver to find alternative paths. Used by the Road Blocked feature.
    """
    # ── Build the node list ────────────────────────────────────────────────────
    # In single-depot mode, node 0 is the depot and nodes 1..N are stops.
    # In multi-depot mode, we add one depot node per unique depot location,
    # then assign each vehicle a start and end node index into that list.
    if vehicle_depots:
        # Collect unique depot locations
        unique_depots = []
        seen          = set()
        for vd in vehicle_depots:
            key = (vd["lat"], vd["lng"])
            if key not in seen:
                unique_depots.append(vd)
                seen.add(key)

        # Map vehicle → depot index in unique_depots
        depot_key_to_idx = {(d["lat"], d["lng"]): i for i, d in enumerate(unique_depots)}
        vehicle_start_depot_idx = [
            depot_key_to_idx[(vd["lat"], vd["lng"])]
            for vd in vehicle_depots
        ]

        # Build the distance matrix with multiple depot nodes at the front
        dist_matrix, nodes = build_distance_matrix(
            stops_df, unique_depots[0], penalised_arcs,
            extra_depots=unique_depots[1:],
        )
        num_depot_nodes = len(unique_depots)

        # OR-Tools start/end node indices for each vehicle
        starts = [vehicle_start_depot_idx[v] for v in range(len(vehicles_df))]
        ends   = starts   # vehicles return to their own depot
    else:
        dist_matrix, nodes = build_distance_matrix(stops_df, depot, penalised_arcs)
        num_depot_nodes    = 1
        starts             = [0] * len(vehicles_df)
        ends               = [0] * len(vehicles_df)

    time_matrix  = build_time_matrix(dist_matrix)
    num_nodes    = len(nodes)
    num_vehicles = len(vehicles_df)

    manager = pywrapcp.RoutingIndexManager(num_nodes, num_vehicles, starts, ends)
    routing = pywrapcp.RoutingModel(manager)

    # ── Callbacks ─────────────────────────────────────────────────────────────
    def distance_callback(from_idx, to_idx):
        return dist_matrix[manager.IndexToNode(from_idx)][manager.IndexToNode(to_idx)]

    def time_callback(from_idx, to_idx):
        i = manager.IndexToNode(from_idx)
        j = manager.IndexToNode(to_idx)
        service = nodes[i].get("service_time_min", 0) if nodes[i]["type"] == "stop" else 0
        return time_matrix[i][j] + service

    def demand_callback(from_idx):
        i = manager.IndexToNode(from_idx)
        return int(nodes[i].get("weight_kg", 0)) if nodes[i]["type"] == "stop" else 0

    dist_cb   = routing.RegisterTransitCallback(distance_callback)
    time_cb   = routing.RegisterTransitCallback(time_callback)
    demand_cb = routing.RegisterUnaryTransitCallback(demand_callback)

    # ── THE KEY LINE — one change, two completely different objectives ─────────
    # "cost" mode: solver treats every metre of distance as cost to minimise.
    # "time" mode: solver treats every minute of travel+service as cost to minimise.
    # The mathematical search is identical — only what "cost" means has changed.
    if objective == "time":
        routing.SetArcCostEvaluatorOfAllVehicles(time_cb)
        print(f"Solver objective: MINIMISE TIME")
    else:
        routing.SetArcCostEvaluatorOfAllVehicles(dist_cb)
        print(f"Solver objective: MINIMISE DISTANCE (cost)")

    # ── Capacity dimension ────────────────────────────────────────────────────
    vehicle_capacities = [int(v) for v in vehicles_df["capacity_kg"].tolist()]
    routing.AddDimensionWithVehicleCapacity(
        demand_cb, 0, vehicle_capacities, True, "Capacity"
    )

    # ── Time dimension ────────────────────────────────────────────────────────
    max_time_horizon = (MAX_SHIFT_MIN + LUNCH_BREAK_MIN) * 3
    routing.AddDimension(
        time_cb,
        120,
        max_time_horizon,
        False,
        "Time",
    )
    time_dim = routing.GetDimensionOrDie("Time")

    for node_idx, node in enumerate(nodes):
        if node["type"] != "stop":
            continue
        index    = manager.NodeToIndex(node_idx)
        tw_start = node["tw_start_min"]
        tw_end   = node["tw_end_min"]
        if node["is_slow_client"]:
            tw_end = min(tw_end + 30, max_time_horizon)
        time_dim.CumulVar(index).SetRange(tw_start, tw_end)

    for v_id in range(num_vehicles):
        routing.AddVariableMinimizedByFinalizer(time_dim.CumulVar(routing.Start(v_id)))
        routing.AddVariableMinimizedByFinalizer(time_dim.CumulVar(routing.End(v_id)))
        time_dim.CumulVar(routing.End(v_id)).SetMax(MAX_SHIFT_MIN + LUNCH_BREAK_MIN)

    # ── Disjunctions ──────────────────────────────────────────────────────────
    for node_idx, node in enumerate(nodes):
        if node["type"] != "stop":
            continue
        index   = manager.NodeToIndex(node_idx)
        penalty = PRIORITY_DROP_PENALTY if node["is_priority"] else REGULAR_DROP_PENALTY
        routing.AddDisjunction([index], penalty)

    # ── Search parameters ─────────────────────────────────────────────────────
    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_params.time_limit.seconds = SOLVER_TIME_LIMIT_SEC
    search_params.log_search = False

    # ── Solve ─────────────────────────────────────────────────────────────────
    solution = routing.SolveWithParameters(search_params)

    if not solution:
        print("OR-Tools: No feasible solution found.")
        return None

    status_map = {
        0: "ROUTING_NOT_SOLVED",
        1: "ROUTING_SUCCESS",
        2: "ROUTING_PARTIAL_SUCCESS_LOCAL_OPTIMUM_NOT_REACHED",
        3: "ROUTING_FAIL",
        4: "ROUTING_FAIL_TIMEOUT",
        5: "ROUTING_INVALID",
    }
    print(f"Solver status: {status_map.get(routing.status(), routing.status())}")

    # ── Extract results ───────────────────────────────────────────────────────
    routes     = {}
    stops_copy = stops_df.copy()
    stops_copy["vehicle_id"] = -1

    for v_id in range(num_vehicles):
        index        = routing.Start(v_id)
        sequence     = []
        arrivals     = {}
        total_dist_m = 0
        load_kg      = 0

        while not routing.IsEnd(index):
            node_idx = manager.IndexToNode(index)
            node     = nodes[node_idx]
            if node["type"] == "stop":
                stop_id = node["stop_id"]
                sequence.append(stop_id)
                stops_copy.loc[stops_copy["stop_id"] == stop_id, "vehicle_id"] = v_id
                arrivals[stop_id] = solution.Value(time_dim.CumulVar(index))
                load_kg += node["weight_kg"]
            next_index    = solution.Value(routing.NextVar(index))
            total_dist_m += routing.GetArcCostForVehicle(index, next_index, v_id)
            index         = next_index

        # Note: when objective="time", GetArcCostForVehicle returns minutes not metres.
        # We always compute actual distance separately for the metrics display so that
        # both modes report distance in km regardless of which objective was used.
        if objective == "time":
            # Recompute actual distance by summing haversine distances along the route
            actual_dist_km = 0.0
            prev_lat, prev_lng = depot["lat"], depot["lng"]
            stops_lu = stops_df.set_index("stop_id")
            for sid in sequence:
                if sid in stops_lu.index:
                    r = stops_lu.loc[sid]
                    actual_dist_km += haversine_km(prev_lat, prev_lng, r["lat"], r["lng"])
                    prev_lat, prev_lng = r["lat"], r["lng"]
            actual_dist_km += haversine_km(prev_lat, prev_lng, depot["lat"], depot["lng"])
        else:
            actual_dist_km = total_dist_m / 1000

        end_time     = solution.Value(time_dim.CumulVar(routing.End(v_id)))
        overtime_min = max(0.0, end_time - (MAX_SHIFT_MIN + LUNCH_BREAK_MIN))

        tw_violations = 0
        for stop_id in sequence:
            node_data  = next(n for n in nodes if n.get("stop_id") == stop_id)
            arrival_hr = arrivals[stop_id] / 60
            if (arrival_hr < node_data["tw_start_min"] / 60 or
                    arrival_hr > node_data["tw_end_min"] / 60):
                tw_violations += 1

        routes[v_id] = {
            "stop_sequence":     sequence,
            "total_distance_km": round(actual_dist_km, 2),
            "total_time_min":    round(end_time, 1),
            "load_kg":           round(load_kg, 1),
            "tw_violations":     tw_violations,
            "overtime_min":      round(overtime_min, 1),
            "arrivals":          arrivals,
        }
        print(f"  Vehicle {v_id}: {len(sequence)} stops, "
              f"{actual_dist_km:.1f}km, {end_time:.0f}min, "
              f"OT={overtime_min:.0f}min, TW_viol={tw_violations}")

    total_served = sum(len(r["stop_sequence"]) for r in routes.values())
    print(f"  Total served: {total_served} / {len(stops_df)}")

    return {
        "routes":              routes,
        "stops_df":            stops_copy,
        "total_distance_km":   round(sum(r["total_distance_km"] for r in routes.values()), 2),
        "total_overtime_min":  round(sum(r["overtime_min"]      for r in routes.values()), 1),
        "total_tw_violations": sum(r["tw_violations"]           for r in routes.values()),
        "total_stops_served":  total_served,
        "method":              f"or_tools_guided_local_search_{objective}",
        "objective":           objective,
        "nodes":               nodes,
    }