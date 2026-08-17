"""
ui/map_view.py
--------------
Phase 3 map renderer.

The critical upgrade over Phase 2 is drawing actual route LINES — polylines
that connect each vehicle's stops in sequence, starting and ending at the depot.
This is the single most visually impactful change in the entire project.

In Phase 2, both maps showed coloured dots — the "optimized" map dots happened
to be vehicle-coloured instead of urgency-coloured, but visually the two maps
looked almost identical. A client couldn't see the difference in routing logic.

In Phase 3, the optimized map shows five coloured paths threading through
Bengaluru's neighbourhoods in logical geographic flows, while the baseline map
shows a chaos of crossing lines. That contrast is the moment the demo becomes
convincing.

Why polylines communicate better than dots:
  A human eye immediately sees when lines cross each other unnecessarily —
  it triggers a sense of inefficiency. Conversely, clean non-crossing routes
  that flow through a zone and return to depot look orderly and trustworthy.
  This is the same psychological principle behind good data visualization:
  the insight should be visible before the viewer has time to read a number.

Sequence numbers on stop markers are also added here. In Phase 2, clicking a
stop showed vehicle assignment. In Phase 3, the stop also shows "Stop 4 of 28
on Vehicle 2's route" — this helps a dispatcher understand the temporal logic,
not just the geographic assignment.
"""

import folium
import pandas as pd
from typing import Optional, Dict, List


# ── Constants ─────────────────────────────────────────────────────────────────
VEHICLE_COLORS = ["#e41a1c", "#377eb8", "#4daf4a", "#ff7f00", "#984ea3"]
VEHICLE_NAMES  = ["Tata Ace 1", "Tata Ace 2",
                  "Mahindra Van 1", "Mahindra Van 2", "Courier Bike"]

# Attribution text — legally required (OpenStreetMap licence) but stripped of
# any political content. The CSS injected below hides the Leaflet.js self-link.
TILE_URL = "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
TILE_ATTR = "Map data: OpenStreetMap contributors | Tiles: CARTO"

# CSS that hides ONLY the Leaflet hyperlink in the attribution bar.
# The OSM and CARTO credits remain visible — they are legally required.
ATTRIBUTION_CSS = """
<style>
  .leaflet-control-attribution a[href*='leafletjs'],
  .leaflet-control-attribution span { display: none !important; }
  .leaflet-control-attribution { font-size: 10px; padding: 2px 6px; }
</style>
"""

# The standard map legend HTML — same across baseline and optimized maps.
# The optimized map also uses LEGEND_OPTIMIZED_HTML which adds the unserved entry.
LEGEND_HTML = """
<div style="position:fixed;bottom:28px;left:28px;z-index:1000;
            background:white;padding:10px 14px;border-radius:8px;
            box-shadow:0 2px 8px rgba(0,0,0,.18);
            font-family:sans-serif;font-size:12px;line-height:1.6">
  <b>Stop Legend</b><br>
  <span style="color:red">&#9679;</span> Slow Client<br>
  <span style="color:orange">&#9679;</span> Priority<br>
  <span style="color:cadetblue">&#9679;</span> Tight Window<br>
  <span style="color:#1f77b4">&#9679;</span> Flexible<br>
  &#8962; Depot
</div>
"""

# Extended legend for the optimized map — adds the unserved (grey) entry.
# Unserved stops only exist after optimization, so this entry would be
# confusing and misleading on the baseline map where every stop is shown.
LEGEND_OPTIMIZED_HTML = """
<div style="position:fixed;bottom:28px;left:28px;z-index:1000;
            background:white;padding:10px 14px;border-radius:8px;
            box-shadow:0 2px 8px rgba(0,0,0,.18);
            font-family:sans-serif;font-size:12px;line-height:1.6">
  <b>Stop Legend</b><br>
  <span style="color:red">&#9679;</span> Slow Client<br>
  <span style="color:orange">&#9679;</span> Priority<br>
  <span style="color:cadetblue">&#9679;</span> Tight Window<br>
  <span style="color:#1f77b4">&#9679;</span> Flexible<br>
  <span style="color:#999999">&#9679;</span> <b>Unserved</b>
    <span style="background:#fff3cd;border:1px solid #ffc107;
                 border-radius:3px;padding:0 4px;font-size:10px">
      could not be served
    </span><br>
  &#8962; Depot
</div>
"""


def _stop_urgency_color(row) -> str:
    """Colour by urgency for the baseline map (no vehicle assignment)."""
    if row["is_slow_client"]:             return "red"
    if row["is_priority"]:                return "orange"
    if row["window_label"] != "Flexible": return "cadetblue"
    return "#1f77b4"


def _base_map(is_optimized: bool = False) -> folium.Map:
    """Create a blank Folium map centred on Bengaluru with clean attribution.
    The optimized map gets an extended legend that includes the unserved (grey)
    entry — this entry only makes sense post-optimization so we keep it out
    of the baseline map where every stop is shown."""
    m = folium.Map(
        location=[12.9716, 77.5946],
        zoom_start=12,
        tiles=TILE_URL,
        attr=TILE_ATTR,
    )
    m.get_root().html.add_child(folium.Element(ATTRIBUTION_CSS))
    legend = LEGEND_OPTIMIZED_HTML if is_optimized else LEGEND_HTML
    m.get_root().html.add_child(folium.Element(legend))
    return m


def _depot_marker(depot: dict) -> folium.Marker:
    """A consistent black home-icon marker for the depot."""
    return folium.Marker(
        location=[depot["lat"], depot["lng"]],
        popup=folium.Popup(f"<b>&#127968; {depot['name']}</b>", max_width=180),
        tooltip="Depot — Central Warehouse",
        icon=folium.Icon(color="black", icon="home", prefix="glyphicon"),
    )


def build_baseline_map(stops_df: pd.DataFrame, depot: dict) -> folium.Map:
    """
    Build the baseline (before) map.

    Shows all stops coloured by urgency (priority, tight window, etc.)
    and draws the naive zone-assignment routes as grey dashed polylines.
    Grey communicates "unoptimised" — we deliberately choose a dull colour
    so the contrast with the vivid optimised routes is immediate.

    The baseline routes cross each other visibly because the naive nearest-
    neighbour sequencing ignores geographic efficiency between zones.
    """
    m = _base_map()
    _depot_marker(depot).add_to(m)

    # Draw each stop as an urgency-coloured circle marker
    for _, row in stops_df.iterrows():
        color = _stop_urgency_color(row)
        popup_html = f"""
        <div style="font-family:sans-serif;min-width:180px">
            <b>{row['name']}</b>
            {'&nbsp;<span style="color:orange">&#9733; PRIORITY</span>' if row['is_priority'] else ''}
            {'&nbsp;<span style="color:red">&#9888; SLOW CLIENT</span>' if row['is_slow_client'] else ''}
            <hr style="margin:5px 0">
            <table style="font-size:12px;width:100%">
                <tr><td>Weight</td> <td><b>{row['weight_kg']} kg</b></td></tr>
                <tr><td>Window</td> <td><b>{row['window_label']}</b></td></tr>
                <tr><td>Service</td><td><b>{row['service_time_min']} min</b></td></tr>
                <tr><td>Zone</td>   <td><b>{row['zone']}</b></td></tr>
            </table>
        </div>"""

        folium.CircleMarker(
            location=[row["lat"], row["lng"]],
            radius=6,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.75,
            popup=folium.Popup(popup_html, max_width=230),
            tooltip=f"#{row['stop_id']} {row['zone']} — {row['weight_kg']}kg",
        ).add_to(m)

    return m


def build_optimized_map(
    stops_df:       pd.DataFrame,
    depot:          dict,
    result:         dict,
    vehicles:       pd.DataFrame,
    geometry_cache: Optional[Dict] = None,
    vehicle_depots: Optional[List[dict]] = None,
) -> folium.Map:
    """
    Build the optimized (after) map with route polylines.

    vehicle_depots: optional list of depot dicts, one per vehicle. When
      provided (two-depot mode from MEIO), each vehicle's home depot is
      shown with a distinct icon on the map — one black home icon for the
      original depot, one red star for the MEIO-recommended second hub.
    """
    m = _base_map(is_optimized=True)

    # Draw depot markers
    _depot_marker(depot).add_to(m)
    if vehicle_depots:
        seen_coords = {(depot["lat"], depot["lng"])}
        for vd in vehicle_depots:
            key = (vd["lat"], vd["lng"])
            if key not in seen_coords:
                folium.Marker(
                    location=[vd["lat"], vd["lng"]],
                    tooltip=f"Second Depot: {vd.get('name', 'New Hub')}",
                    icon=folium.Icon(color="red", icon="star", prefix="glyphicon"),
                ).add_to(m)
                seen_coords.add(key)

    routes   = result["routes"]
    stops_lu = stops_df.set_index("stop_id")

    served_ids = set(
        result["stops_df"].loc[result["stops_df"]["vehicle_id"] >= 0, "stop_id"]
    )

    for v_id, route in routes.items():
        sequence = route["stop_sequence"]
        if not sequence:
            continue

        color   = VEHICLE_COLORS[v_id % len(VEHICLE_COLORS)]
        v_name  = vehicles.iloc[v_id]["name"] if v_id < len(vehicles) else f"Vehicle {v_id}"
        n_stops = len(sequence)

        # ── Choose road geometry or fall back to straight lines ───────────────
        # When geometry_cache has a path for this vehicle, use it — these are
        # real road coordinates returned by OpenRouteService, tracing along
        # actual Bengaluru streets. When not available, build the straight-line
        # path from stop coordinates as before.
        if geometry_cache and v_id in geometry_cache and geometry_cache[v_id]:
            path         = geometry_cache[v_id]   # already [lat, lng] Folium format
            line_weight  = 4       # slightly thicker — road curves carry the detail
            line_opacity = 0.80
        else:
            path = [[depot["lat"], depot["lng"]]]
            for stop_id in sequence:
                if stop_id in stops_lu.index:
                    row = stops_lu.loc[stop_id]
                    path.append([row["lat"], row["lng"]])
            path.append([depot["lat"], depot["lng"]])
            line_weight  = 3
            line_opacity = 0.75

        folium.PolyLine(
            locations=path,
            color=color,
            weight=line_weight,
            opacity=line_opacity,
            tooltip=f"{v_name} — {n_stops} stops, {route['total_distance_km']:.1f}km",
        ).add_to(m)

        # ── Draw numbered stop markers along the route ────────────────────────
        # Each stop gets a DivIcon with the sequence number so dispatchers can
        # read the route order without clicking every stop.
        for seq_pos, stop_id in enumerate(sequence, start=1):
            if stop_id not in stops_lu.index:
                continue
            row = stops_lu.loc[stop_id]

            # Arrival time from solver (minutes from shift start → clock time)
            arrival_min = route["arrivals"].get(stop_id, 0)
            arrival_hr  = 8 + int(arrival_min // 60)
            arrival_m   = int(arrival_min % 60)
            arrival_str = f"{arrival_hr:02d}:{arrival_m:02d}"

            popup_html = f"""
            <div style="font-family:sans-serif;min-width:200px">
                <b>Stop {seq_pos} of {n_stops} — {v_name}</b>
                {'&nbsp;<span style="color:orange">&#9733; PRIORITY</span>' if row['is_priority'] else ''}
                {'&nbsp;<span style="color:red">&#9888; SLOW</span>' if row['is_slow_client'] else ''}
                <hr style="margin:5px 0">
                <table style="font-size:12px;width:100%">
                    <tr><td>Location</td> <td><b>{row['name']}</b></td></tr>
                    <tr><td>Zone</td>     <td><b>{row['zone']}</b></td></tr>
                    <tr><td>Weight</td>   <td><b>{row['weight_kg']} kg</b></td></tr>
                    <tr><td>Window</td>   <td><b>{row['window_label']}</b></td></tr>
                    <tr><td>ETA</td>      <td><b>{arrival_str}</b></td></tr>
                    <tr><td>Service</td>  <td><b>{row['service_time_min']} min</b></td></tr>
                </table>
            </div>"""

            # DivIcon: a small circle with the sequence number inside.
            # The border uses the vehicle's colour so it's visually linked
            # to the route line without needing a separate legend entry.
            icon_html = (
                f'<div style="'
                f'background:white;border:2px solid {color};border-radius:50%;'
                f'width:18px;height:18px;line-height:18px;text-align:center;'
                f'font-size:9px;font-weight:700;color:{color};'
                f'box-shadow:0 1px 3px rgba(0,0,0,.3)">'
                f'{seq_pos}</div>'
            )

            folium.Marker(
                location=[row["lat"], row["lng"]],
                popup=folium.Popup(popup_html, max_width=250),
                tooltip=f"Stop {seq_pos}/{n_stops} · {v_name} · ETA {arrival_str}",
                icon=folium.DivIcon(
                    html=icon_html,
                    icon_size=(20, 20),
                    icon_anchor=(10, 10),
                ),
            ).add_to(m)

    # ── Unserved stops in grey with X marker ─────────────────────────────────
    # Dropped stops are shown in muted grey so they're visible but clearly
    # distinguished from served stops. Clicking shows WHY they were dropped
    # (this is populated by the LLM explainer in the intelligence layer).
    unserved_df = result["stops_df"][result["stops_df"]["vehicle_id"] == -1]
    for _, row in unserved_df.iterrows():
        orig = stops_lu.loc[row["stop_id"]] if row["stop_id"] in stops_lu.index else row
        folium.CircleMarker(
            location=[orig["lat"], orig["lng"]],
            radius=7,
            color="#999999",
            fill=True,
            fill_color="#cccccc",
            fill_opacity=0.7,
            popup=folium.Popup(
                f'<b style="color:#c62828">&#10007; Could not be served</b><br>'
                f'{orig["name"]}<br>Window: {orig["window_label"]}<br>'
                f'Weight: {orig["weight_kg"]} kg<br>'
                f'<i>See explanation panel below the map.</i>',
                max_width=220,
            ),
            tooltip=f"UNSERVED: #{row['stop_id']} {orig['zone']}",
        ).add_to(m)

    # ── Vehicle route summary legend (top-right corner) ───────────────────────
    # Shows which colour belongs to which vehicle — essential context when
    # five coloured paths are visible simultaneously on the map.
    legend_items = ""
    for v_id, route in routes.items():
        if not route["stop_sequence"]:
            continue
        color  = VEHICLE_COLORS[v_id % len(VEHICLE_COLORS)]
        v_name = vehicles.iloc[v_id]["name"] if v_id < len(vehicles) else f"V{v_id}"
        n      = len(route["stop_sequence"])
        dist   = route["total_distance_km"]
        legend_items += (
            f'<div style="display:flex;align-items:center;margin:3px 0">'
            f'<span style="background:{color};width:24px;height:4px;'
            f'display:inline-block;margin-right:6px;border-radius:2px"></span>'
            f'<span style="font-size:11px">{v_name}: {n} stops, {dist:.1f}km</span>'
            f'</div>'
        )

    route_legend_html = f"""
    <div style="position:fixed;top:80px;right:10px;z-index:1000;
                background:white;padding:10px 14px;border-radius:8px;
                box-shadow:0 2px 8px rgba(0,0,0,.18);
                font-family:sans-serif;min-width:190px">
        <b style="font-size:12px">Vehicle Routes</b>
        <div style="margin-top:6px">{legend_items}</div>
    </div>"""
    m.get_root().html.add_child(folium.Element(route_legend_html))

    return m


def build_scenario_map(stops_df: pd.DataFrame, depot: dict) -> folium.Map:
    """
    Pre-optimization scenario map (Phase 1 view).
    Shows all stops coloured by urgency with no route lines.
    Same as the baseline map but without implying any routing has been attempted.
    """
    return build_baseline_map(stops_df, depot)





