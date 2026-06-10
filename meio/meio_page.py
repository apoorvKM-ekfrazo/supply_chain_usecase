"""
meio/meio_page.py
-----------------
The Network Intelligence (MEIO) Streamlit page.

This module renders the complete MEIO demo as a single function
render_meio_page() that app.py calls when the user switches pages.
All five modules are rendered here in sequence, with clear visual
separation between them so a client can follow the narrative.

The narrative flow of the page:
  1. Current Network — where are we today? (demand, costs, fleet)
  2. Warehouse Placement — where should we add capacity?
  3. Fleet Right-Sizing — are we over-invested in vehicles?
  4. Strategic Alerts — what is the system consistently telling us?
  5. Export — give me a document to take to the CFO.
"""

import os
import io
import json
import folium
import pandas as pd
import numpy as np
import streamlit as st
from streamlit_folium import st_folium
from datetime import date

# INTEGRATION NOTE: Added ZONE_BASE_DEMAND to the imports below
from data.meio_scenario import (
    DEPOT, CANDIDATE_WAREHOUSES, ZONES,
    generate_demand_history, generate_vehicle_utilisation,
    get_demand_summary, get_utilisation_summary,
    ZONE_BASE_DEMAND,
)
from meio.warehouse_optimizer import (
    run_placement_analysis, format_inr,
    compute_zone_distances, assign_zones_to_warehouses,
    ZONE_COORDS, BLENDED_FUEL_COST,
)
from meio.fleet_analyzer import (
    generate_fleet_recommendations, classify_utilisation,
    build_utilisation_chart_data, UNDERUTILISATION_THRESHOLD,
)
from ui.data_onboarding import render_ni_onboarding
from meio.alert_system import (
    seed_demo_history, record_recommendation,
    load_alert_status, clear_history,
)

VEHICLE_COLORS = ["red", "blue", "green", "orange", "purple"]

def _init_meio_state():
    """Initialise session state for the MEIO module."""
    if "meio_demand_df"     not in st.session_state:
        st.session_state.meio_demand_df    = None
    if "meio_util_df"       not in st.session_state:
        st.session_state.meio_util_df      = None
    if "meio_placement_df"  not in st.session_state:
        st.session_state.meio_placement_df = None
    if "meio_analysed"      not in st.session_state:
        st.session_state.meio_analysed     = False
    if "ni_onboarding_complete" not in st.session_state:
        st.session_state.ni_onboarding_complete = False
    if "ni_data_summary" not in st.session_state:
        st.session_state.ni_data_summary = None
    if "ni_upload_error" not in st.session_state:
        st.session_state.ni_upload_error = None

def _build_network_map(
    highlight_candidate: dict = None,
    zone_assignments: dict = None,
) -> folium.Map:
    """
    Build a Folium map showing the current network (depot + zones) and
    optionally highlighting a candidate warehouse with zone colouring.

    zone_assignments: dict mapping zone_name → "new_warehouse" | "depot"
    """
    m = folium.Map(
        location=[12.9350, 77.6500],
        zoom_start=11,
        tiles="CartoDB positron",
    )

    # Draw the depot marker
    folium.Marker(
        location=[DEPOT["lat"], DEPOT["lng"]],
        tooltip=f"Current Depot: {DEPOT['name']}",
        icon=folium.Icon(color="black", icon="home", prefix="glyphicon"),
    ).add_to(m)

    # Draw zone markers
    for zone, (lat, lng) in ZONE_COORDS.items():
        if zone_assignments:
            assignment = zone_assignments.get(zone, "depot")
            colour = "blue" if assignment == "new_warehouse" else "gray"
            icon   = "map-marker"
        else:
            colour = "blue"
            icon   = "map-marker"

        folium.CircleMarker(
            location=[lat, lng],
            radius=8,
            color=colour,
            fill=True,
            fill_color=colour,
            fill_opacity=0.7,
            tooltip=zone,
        ).add_to(m)

        folium.Tooltip(zone).add_to(
            folium.CircleMarker(location=[lat, lng], radius=0).add_to(m)
        )

    # Draw a line from depot to each zone centre (shows current routing scope)
    if zone_assignments is None:
        for zone, (lat, lng) in ZONE_COORDS.items():
            folium.PolyLine(
                locations=[[DEPOT["lat"], DEPOT["lng"]], [lat, lng]],
                color="gray",
                weight=1,
                opacity=0.3,
            ).add_to(m)

    # Highlight the candidate warehouse if provided
    if highlight_candidate:
        # Draw the candidate marker
        folium.Marker(
            location=[highlight_candidate["lat"], highlight_candidate["lng"]],
            tooltip=f"Proposed: {highlight_candidate['name']}",
            icon=folium.Icon(color="red", icon="star", prefix="glyphicon"),
        ).add_to(m)

        # Draw lines from new warehouse to zones it would serve (blue)
        # and from depot to its remaining zones (gray)
        if zone_assignments:
            for zone, assignment in zone_assignments.items():
                lat, lng = ZONE_COORDS[zone]
                if assignment == "new_warehouse":
                    src = [highlight_candidate["lat"], highlight_candidate["lng"]]
                    colour = "#1565c0"
                    weight = 2
                else:
                    src = [DEPOT["lat"], DEPOT["lng"]]
                    colour = "gray"
                    weight = 1
                folium.PolyLine(
                    locations=[src, [lat, lng]],
                    color=colour, weight=weight, opacity=0.6,
                ).add_to(m)

    return m

def render_meio_page():
    """Main render function — called from app.py when the MEIO page is selected."""

    _init_meio_state()

    st.markdown("""
    <div style="background:linear-gradient(135deg,#1a237e,#283593);
                color:white;padding:20px 28px;border-radius:10px;margin-bottom:20px">
        <div style="font-size:24px;font-weight:700">🏭 Network Intelligence</div>
        <div style="font-size:13px;opacity:0.85;margin-top:4px">
        Multi-Echelon Inventory Optimisation · Bengaluru Distribution Network
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(
        "This module analyses your **distribution network configuration** — "
        "not just today's routes, but whether your warehouses are in the right "
        "places, whether your fleet is the right size, and what the data has "
        "been consistently telling you this week. "
        "The P\\&G implementation of this approach freed **$1.5 billion in "
        "working capital** in a single year."
    )

    _ni_ready = render_ni_onboarding()
    if not _ni_ready:
        st.stop()

    fuel_cost = st.sidebar.slider(
        "Blended fuel cost (₹/km)", 5.0, 12.0,
        value=float(os.environ.get("MEIO_FUEL_COST", BLENDED_FUEL_COST)),
        step=0.25, key="meio_fuel_cost",
    )

    run_col, reset_col = st.columns([2, 1])
    with run_col:
        run_btn = st.button(
            "🔍 Run Network Analysis",
            type="primary",
            help="Analyses 30 days of demand history across all 9 Bengaluru zones",
        )
    with reset_col:
        if st.button("↺ Reset Analysis", key="meio_reset"):
            for k in ["meio_demand_df","meio_util_df","meio_placement_df","meio_analysed","ni_onboarding_complete","ni_data_summary"]:
                st.session_state[k] = None
            st.session_state.meio_analysed = False
            clear_history()
            st.rerun()

    if run_btn or st.session_state.meio_analysed:
        if run_btn or st.session_state.meio_demand_df is None:
            with st.spinner("Loading 30-day demand history..."):
                demand_df = generate_demand_history()
                util_df   = generate_vehicle_utilisation()
                demand_summary = get_demand_summary(demand_df)
                util_summary   = get_utilisation_summary(util_df)

            # Must happen before the forecast override mutates demand_summary.
            # These cached values power the before/after comparison panel.
            baseline_placement_df = run_placement_analysis(
                demand_summary["by_zone"].copy(), fuel_cost
            )
            st.session_state.meio_baseline_placement_df = baseline_placement_df
            st.session_state.meio_baseline_daily_volume = int(
                demand_summary["by_zone"]["avg_daily_deliveries"].sum()
            )

            # Uses the dynamic AI forecast demand when available, falling back to static assumptions.
            forecast_dict = st.session_state.get('meio_forecast_demand') or ZONE_BASE_DEMAND
            for zone_name in ZONES:
                if zone_name in forecast_dict:
                    demand_summary["by_zone"].loc[
                        demand_summary["by_zone"]["zone"] == zone_name, 
                        "avg_daily_deliveries"
                    ] = forecast_dict[zone_name]

            with st.spinner("Running warehouse placement analysis..."):
                placement_df = run_placement_analysis(
                    demand_summary["by_zone"], fuel_cost
                )

            st.session_state.meio_demand_df    = demand_df
            st.session_state.meio_util_df      = util_df
            st.session_state.meio_demand_summary = demand_summary
            st.session_state.meio_util_summary   = util_summary
            st.session_state.meio_placement_df   = placement_df
            st.session_state.meio_analysed       = True

            # Record today's top recommendation and seed alerts if first run
            top = placement_df.iloc[0]
            seed_demo_history(top["name"], float(top["net_annual_saving"]))
            record_recommendation(top["name"], float(top["net_annual_saving"]))

        # Retrieve from session state
        demand_df      = st.session_state.meio_demand_df
        util_df        = st.session_state.meio_util_df
        demand_summary = st.session_state.meio_demand_summary
        util_summary   = st.session_state.meio_util_summary
        placement_df   = st.session_state.meio_placement_df

        if st.session_state.get('meio_forecast_applied') is True:
            baseline_pl  = st.session_state.get('meio_baseline_placement_df')
            baseline_vol = st.session_state.get('meio_baseline_daily_volume', 311)

            if baseline_pl is not None:
                b_top     = baseline_pl.iloc[0]
                f_top     = placement_df.iloc[0]
                f_vol     = int(demand_summary["by_zone"]["avg_daily_deliveries"].sum())
                vol_delta  = f_vol - baseline_vol
                cost_delta = f_top["current_daily_cost"] - b_top["current_daily_cost"]

                st.markdown(
                    """
                    <div style="background:linear-gradient(135deg,#e8f5e9,#f0fdf4);
                                border:1px solid #a5d6a7;border-left:5px solid #2e7d32;
                                border-radius:8px;padding:14px 18px;margin-bottom:12px">
                        <div style="font-size:15px;font-weight:700;color:#1b5e20;margin-bottom:4px">
                            🔮 Forecast Applied — Here Is What Changed
                        </div>
                        <div style="font-size:12px;color:#2e7d32">
                            The AI forecast replaced 30-day historical averages with
                            90-day growth projections. The numbers below show the impact
                            on the warehouse recommendation.
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                col_b, col_arr, col_f = st.columns([5, 1, 5])
                with col_b:
                    st.markdown(
                        "<div style='background:#f8fafc;border:1px solid #e2e8f0;"
                        "border-radius:8px;padding:14px 16px'>"
                        "<div style='font-size:12px;font-weight:700;color:#64748b;"
                        "text-transform:uppercase;letter-spacing:1px;margin-bottom:10px'>"
                        "📊 Historical Baseline</div>",
                        unsafe_allow_html=True)
                    st.metric("Daily network volume", f"{baseline_vol:,} stops/day")
                    st.metric("Routing cost", format_inr(b_top["current_daily_cost"]))
                    st.metric(f"{b_top['name']} — payback",
                              f"{b_top['payback_months']} months")
                    st.metric(f"{b_top['name']} — net saving/yr",
                              format_inr(b_top["net_annual_saving"]))
                    st.markdown("</div>", unsafe_allow_html=True)

                with col_arr:
                    st.markdown(
                        "<div style='text-align:center;padding-top:90px;"
                        "font-size:28px;color:#2e7d32'>→</div>",
                        unsafe_allow_html=True)

                with col_f:
                    st.markdown(
                        "<div style='background:#f0fdf4;border:1px solid #a5d6a7;"
                        "border-radius:8px;padding:14px 16px'>"
                        "<div style='font-size:12px;font-weight:700;color:#2e7d32;"
                        "text-transform:uppercase;letter-spacing:1px;margin-bottom:10px'>"
                        "🔮 AI Forecast (Next Quarter)</div>",
                        unsafe_allow_html=True)
                    st.metric("Daily network volume", f"{f_vol:,} stops/day",
                              delta=f"+{vol_delta:,} ({vol_delta/max(baseline_vol,1)*100:.0f}%)")
                    st.metric("Routing cost",
                              format_inr(f_top["current_daily_cost"]),
                              delta=f"+{format_inr(cost_delta)} (higher demand)")
                    st.metric(f"{f_top['name']} — payback",
                              f"{f_top['payback_months']} months",
                              delta=f"{f_top['payback_months']-b_top['payback_months']:.1f} mo",
                              delta_color="inverse")
                    st.metric(f"{f_top['name']} — net saving/yr",
                              format_inr(f_top["net_annual_saving"]),
                              delta=format_inr(
                                  f_top["net_annual_saving"] - b_top["net_annual_saving"]))
                    st.markdown("</div>", unsafe_allow_html=True)

                # Shows which specific zones are driving the total change, so
                # the presenter can point to the eastern corridor directly.
                forecast_demand = st.session_state.get('meio_forecast_demand') or {}
                zone_changes = sorted([
                    {
                        "zone":    z,
                        "base":    ZONE_BASE_DEMAND[z],
                        "fcst":    round(forecast_demand.get(z, ZONE_BASE_DEMAND[z]), 1),
                        "pct":     (forecast_demand.get(z, ZONE_BASE_DEMAND[z])
                                    - ZONE_BASE_DEMAND[z]) / ZONE_BASE_DEMAND[z] * 100,
                    }
                    for z in ZONE_BASE_DEMAND
                ], key=lambda x: x["pct"], reverse=True)

                top_growers = [z for z in zone_changes if z["pct"] > 0][:3]
                if top_growers:
                    st.markdown(
                        "<div style='font-size:12px;font-weight:600;color:#374151;"
                        "margin:10px 0 6px 0'>📍 Zones driving the change — "
                        "these are the areas where forecast demand outgrew the "
                        "historical average:</div>",
                        unsafe_allow_html=True)
                    zc1, zc2, zc3 = st.columns(3)
                    for col, z in zip([zc1, zc2, zc3], top_growers):
                        col.markdown(
                            f"<div style='background:#f0fdf4;border:1px solid #a5d6a7;"
                            f"border-radius:6px;padding:10px;text-align:center'>"
                            f"<div style='font-size:11px;color:#374151;"
                            f"font-weight:600;margin-bottom:4px'>{z['zone']}</div>"
                            f"<div style='font-size:20px;font-weight:700;color:#1b5e20'>"
                            f"{z['base']:.0f} → {z['fcst']:.0f}</div>"
                            f"<div style='font-size:11px;color:#2e7d32;margin-top:2px'>"
                            f"▲ {z['pct']:.0f}% forecast growth</div>"
                            f"<div style='font-size:10px;color:#64748b'>"
                            f"stops/day</div>"
                            f"</div>",
                            unsafe_allow_html=True)

                payback_improvement = b_top["payback_months"] - f_top["payback_months"]
                saving_improvement  = f_top["net_annual_saving"] - b_top["net_annual_saving"]
                st.markdown(
                    f"""
                    <div style="background:#1b5e20;color:white;border-radius:8px;
                                padding:12px 18px;margin-top:8px;font-size:13px">
                        💡 <b>The story:</b> At forecast demand levels, the eastern
                        corridor is growing fast enough that <b>{f_top['name']}</b>
                        breaks even <b>{payback_improvement:.1f} months sooner</b> and
                        delivers <b>{format_inr(saving_improvement)} more per year</b>
                        than the historical baseline suggested. This is the value of
                        planning ahead rather than reacting to last month's numbers.
                    </div>
                    """, unsafe_allow_html=True)
                st.markdown("---")

        nm_tabs = st.tabs(["📊 Network Overview", "🏭 Warehouse Placement", "🚛 Fleet Right-Sizing", "🔔 Alerts", "📄 Export"])

        with nm_tabs[0]:
            st.markdown("## 📊 Current Network Overview")
            st.caption("30-day delivery history across 9 Bengaluru zones · Single warehouse at Bommanahalli")

            # KPI strip
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Avg daily deliveries",
                      f"{int(demand_summary['total_avg_daily'])} stops")
            k2.metric("Busiest zone",       demand_summary["busiest_zone"])
            k3.metric("History period",     f"{demand_summary['total_working_days']} working days")

            # Compute current daily routing cost for the KPI
            total_cost = placement_df.iloc[0]["current_daily_cost"]
            k4.metric("Est. daily routing cost", format_inr(total_cost))

            # Demand by zone chart — bar chart using Streamlit's native charting
            by_zone = demand_summary["by_zone"].sort_values(
                "avg_daily_deliveries", ascending=False
            )
            st.markdown("**Average daily deliveries by zone**")
            st.bar_chart(
                by_zone.set_index("zone")["avg_daily_deliveries"],
                use_container_width=True, height=220,
            )

            # Network map — current single-warehouse configuration
            col_map, col_info = st.columns([2, 1])
            with col_map:
                st.markdown("**Current network — single depot**")
                net_map = _build_network_map()
                st_folium(net_map, width=None, height=380,
                          returned_objects=[], key="meio_current_map")
            with col_info:
                st.markdown("**Zone coverage from Bommanahalli**")
                dist_from_depot = {
                    z: round(
                        ((DEPOT["lat"]-lat)**2 + (DEPOT["lng"]-lng)**2)**0.5 * 111, 1
                    )
                    for z, (lat, lng) in ZONE_COORDS.items()
                }
                far_zones = sorted(dist_from_depot, key=dist_from_depot.get, reverse=True)[:4]
                st.caption(
                    "The four zones farthest from the depot account for a large share "
                    "of total demand but require the longest drives. This is where a "
                    "second warehouse would have the biggest impact."
                )
                for z in far_zones:
                    row = by_zone[by_zone["zone"] == z]
                    deliveries = int(row.iloc[0]["avg_daily_deliveries"]) if not row.empty else "-"
                    st.markdown(
                        f"📍 **{z}** — {dist_from_depot[z]:.0f}km from depot · "
                        f"{deliveries} deliveries/day"
                    )

        with nm_tabs[1]:
            st.markdown("## 🏭 Warehouse Placement Optimiser")
            st.caption(
                "Adding a second warehouse reduces routing distance for zones closest to it. "
                "The net saving is routing cost reduction minus lease cost."
            )

            # Build the comparison table
            display_cols = {
                "name":                 "Candidate",
                "new_warehouse_zones":  "Zones Served",
                "annual_routing_saving":"Routing Saving/yr",
                "annual_facility_cost": "Lease Cost/yr",
                "net_annual_saving":    "Net Saving/yr",
                "payback_months":       "Payback (months)",
            }

            table_rows = []
            for _, row in placement_df.iterrows():
                badge = "⭐ Recommended" if row["rank"] == 1 else ""
                table_rows.append({
                    "":                  badge,
                    "Candidate":         row["name"],
                    "Zones Served":      f"{len(row['new_warehouse_zones'])} zones",
                    "Routing Saving/yr": format_inr(row["annual_routing_saving"]),
                    "Lease Cost/yr":     format_inr(row["annual_facility_cost"]),
                    "Net Saving/yr":     format_inr(row["net_annual_saving"]),
                    "Payback (months)":  f"{row['payback_months']} mo" if row["payback_months"] else "N/A",
                    "_net":              row["net_annual_saving"],  # for conditional styling
                })

            # Render as HTML table for colour coding
            table_html = """
            <table style="width:100%;border-collapse:collapse;font-size:13px;font-family:sans-serif">
              <thead><tr style="background:#f0f0f0">
                <th style="padding:7px 8px;text-align:left"></th>
                <th style="padding:7px 8px;text-align:left">Candidate</th>
                <th style="padding:7px 8px;text-align:center">Zones</th>
                <th style="padding:7px 8px;text-align:right">Routing Saving/yr</th>
                <th style="padding:7px 8px;text-align:right">Lease Cost/yr</th>
                <th style="padding:7px 8px;text-align:right;font-weight:700">Net Saving/yr</th>
                <th style="padding:7px 8px;text-align:right">Payback</th>
              </tr></thead><tbody>"""

            for r in table_rows:
                row_bg  = "#e8f5e9" if r[""] else "white"
                net_col = "#2e7d32" if r["_net"] > 0 else "#c62828"
                table_html += (
                    f"<tr style='background:{row_bg}'>"
                    f"<td style='padding:6px 8px;font-size:11px;color:#2e7d32'>{r['']}</td>"
                    f"<td style='padding:6px 8px;font-weight:600'>{r['Candidate']}</td>"
                    f"<td style='padding:6px 8px;text-align:center'>{r['Zones Served']}</td>"
                    f"<td style='padding:6px 8px;text-align:right'>{r['Routing Saving/yr']}</td>"
                    f"<td style='padding:6px 8px;text-align:right'>{r['Lease Cost/yr']}</td>"
                    f"<td style='padding:6px 8px;text-align:right;color:{net_col};font-weight:700'>"
                    f"{r['Net Saving/yr']}</td>"
                    f"<td style='padding:6px 8px;text-align:right'>{r['Payback (months)']}</td>"
                    f"</tr>"
                )
            table_html += "</tbody></table>"
            st.markdown(table_html, unsafe_allow_html=True)

            # Interactive: select a candidate to see the zone split on the map
            st.markdown("**Explore a candidate — see which zones it would serve**")
            selected_name = st.selectbox(
                "Select candidate warehouse",
                options=placement_df["name"].tolist(),
                index=0,
                key="meio_candidate_select",
            )

            selected_row  = placement_df[placement_df["name"] == selected_name].iloc[0]
            selected_cand = next(
                c for c in CANDIDATE_WAREHOUSES if c["name"] == selected_name
            )
            new_zones, depot_zones = assign_zones_to_warehouses(selected_cand)
            zone_assignments       = {z: "new_warehouse" for z in new_zones}
            zone_assignments.update({z: "depot" for z in depot_zones})

            map_col, detail_col = st.columns([2, 1])
            with map_col:
                proposal_map = _build_network_map(
                    highlight_candidate=selected_cand,
                    zone_assignments=zone_assignments,
                )
                st_folium(proposal_map, width=None, height=400,
                          returned_objects=[], key="meio_proposal_map")
            with detail_col:
                st.markdown(f"**{selected_row['name']}**")
                st.caption(selected_row["description"])

                st.markdown("🔵 **Served by new warehouse:**")
                for z in new_zones:
                    st.markdown(f"  · {z}")

                st.markdown("⚫ **Remain at current depot:**")
                for z in depot_zones:
                    st.markdown(f"  · {z}")

                savings_sign = "+" if selected_row["net_annual_saving"] > 0 else ""
                colour = "#2e7d32" if selected_row["net_annual_saving"] > 0 else "#c62828"
                st.markdown(
                    f"**Net annual saving: "
                    f"<span style='color:{colour}'>"
                    f"{savings_sign}{format_inr(selected_row['net_annual_saving'])}"
                    f"</span>**",
                    unsafe_allow_html=True,
                )
                if selected_row["payback_months"]:
                    st.markdown(
                        f"Payback period: **{selected_row['payback_months']} months**"
                    )

            # Connection button — the key demo moment
            st.info(
                f"💡 **Ready to see the route impact?** "
                f"The top recommendation is **{placement_df.iloc[0]['name']}**. "
                f"Click below to run the route optimizer from both warehouse locations "
                f"and see how daily routing costs change."
            )
            if st.button(
                f"🚚 Optimise Routes with {selected_row['name']} Added",
                type="primary",
                key="meio_connect_btn",
            ):
                top_row  = selected_row   # already the selected candidate from the dropdown
                top_cand = next(c for c in CANDIDATE_WAREHOUSES if c["name"] == selected_row["name"])

                # Store the pending depot AND the prediction so the Network
                # Decision Panel on the Route Optimizer page can compare
                # actual vs predicted when the simulation runs.
                st.session_state["meio_second_depot"] = {
                    "lat":  top_cand["lat"],
                    "lng":  top_cand["lng"],
                    "name": top_cand["name"],
                }
                st.session_state["meio_prediction"] = {
                    "name":                 top_row["name"],
                    "net_annual_saving":    float(top_row["net_annual_saving"]),
                    "annual_facility_cost": float(top_row["annual_facility_cost"]),
                    "annual_routing_saving":float(top_row["annual_routing_saving"]),
                    "predicted_daily_saving": float(top_row["daily_routing_saving"]),
                }
                st.session_state["meio_trigger_route"]  = True
                st.session_state["network_decision"]    = None  # clear any old verdict
                st.success(
                    f"✅ **{top_cand['name']}** queued for validation. "
                    "Switch to the **Route Optimizer** tab, run the optimisation, "
                    "and the Network Decision Panel will show whether this depot pays off."
                )

            accepted_depots = st.session_state.get("meio_accepted_depots", [])
            if accepted_depots:
                st.markdown("**✅ Accepted depots in current network:**")
                for d in accepted_depots:
                    st.markdown(f"  · **{d['name']}** — validated by Route Optimizer simulation")

            if st.session_state.get("network_decision"):
                with st.expander("📊 Last Route Optimizer validation result", expanded=False):
                    comparison_data = st.session_state.get("meio_comparison_data")

                    # Show break-even card if it exists
                    if comparison_data and comparison_data.get("break_even_stops"):
                        bev   = comparison_data["break_even_stops"]
                        stops = comparison_data["stops_served"]
                        months = comparison_data.get("months_to_breakeven", "?")
                        st.info(
                            f"📈 **Break-even:** At {stops} stops/day this hub doesn't cover its lease. "
                            f"Break-even volume: **~{bev} stops/day** (~{months} months at 12% monthly growth)."
                        )
                    elif comparison_data and comparison_data.get("daily_saving_per_stop", 0) <= 0:
                        threshold = comparison_data.get("stops_served", 120) * 3
                        st.warning(
                            f"⚠️ This depot increases routing cost at current volume. "
                            f"Viable at ~{threshold}+ stops/day."
                        )

                    # Then show the AI verdict text as before
                    verdict = st.session_state.get("network_decision")
                    if verdict:
                        st.markdown(verdict)

        with nm_tabs[2]:
            st.markdown("## 🚛 Fleet Right-Sizing")
            st.caption(
                "30-day average utilisation per vehicle. "
                f"Vehicles below {int(UNDERUTILISATION_THRESHOLD*100)}% are flagged for review."
            )

            recommendations = generate_fleet_recommendations(util_summary)

            # Utilisation bar chart
            util_chart_data = util_summary.copy()
            util_chart_data = util_chart_data.set_index("vehicle_name")["avg_utilisation_pct"]
            st.bar_chart(util_chart_data, use_container_width=True, height=200)

            # Vehicle summary table
            for _, vrow in util_summary.iterrows():
                label, colour = classify_utilisation(vrow["avg_utilisation_pct"])
                rec_for_v = next(
                    (r for r in recommendations if r["vehicle_name"] == vrow["vehicle_name"]),
                    None
                )

                with st.expander(
                    f"{vrow['vehicle_name']} — {vrow['avg_utilisation_pct']:.1f}% avg utilisation  {label}",
                    expanded=(rec_for_v is not None),
                ):
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Avg utilisation",  f"{vrow['avg_utilisation_pct']:.1f}%")
                    c2.metric("Avg load",         f"{vrow['avg_load_kg']:.0f} kg")
                    c3.metric("Capacity",         f"{vrow['capacity_kg']} kg")

                    c4, c5 = st.columns(2)
                    c4.metric("Avg km/day",      f"{vrow['avg_km_driven']:.0f} km")
                    c5.metric("Annual vehicle cost", format_inr(vrow["annual_cost_inr"]))

                    if rec_for_v:
                        if rec_for_v["feasible"]:
                            st.success(rec_for_v["recommendation"])
                            if rec_for_v["new_utilisation"]:
                                st.markdown("**Projected utilisation after redistribution:**")
                                for v_name, new_util in rec_for_v["new_utilisation"].items():
                                    delta = new_util - float(
                                        util_summary.loc[
                                            util_summary["vehicle_name"] == v_name,
                                            "avg_utilisation_pct"
                                        ].values[0]
                                    )
                                    st.markdown(
                                        f"  · {v_name}: {new_util:.1f}% "
                                        f"(+{delta:.1f}pp)"
                                    )
                        else:
                            st.warning(rec_for_v["recommendation"])

        with nm_tabs[3]:
            st.markdown("## 🔔 Strategic Alerts")
            st.caption(
                "When the optimiser consistently produces the same recommendation "
                "across multiple days, it is escalated here. Persistent signals "
                "deserve formal evaluation — they are not noise."
            )

            alert_status = load_alert_status()

            if alert_status["has_alert"]:
                st.markdown(
                    f"""
                    <div style="background:#fff3e0;border-left:5px solid #e65100;
                                border-radius:8px;padding:16px 20px;margin:12px 0">
                        <div style="font-size:16px;font-weight:700;color:#bf360c;margin-bottom:8px">
                            🚨 High Confidence Alert — Action Recommended
                        </div>
                        <div style="font-size:14px;color:#3e2723">
                            <b>{alert_status['alert_recommendation']}</b> has been the 
                            top recommendation in <b>{alert_status['days_appeared']} of 
                            the last {alert_status['total_window_days']} days</b> 
                            ({alert_status['frequency']:.0f}% frequency).<br><br>
                            Projected annual saving: 
                            <b style="color:#2e7d32">{format_inr(alert_status['alert_saving'])}</b><br><br>
                            This signal has stabilised. It is worth scheduling a formal 
                            evaluation with your logistics and finance teams.
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.info(
                    f"No alerts active. The optimiser has run for "
                    f"{alert_status['days_in_window']} of the last "
                    f"{alert_status['total_window_days']} days without a "
                    f"consistent recommendation reaching the alert threshold."
                )

            # Show recent recommendation history
            if alert_status["history"]:
                st.markdown("**Recent recommendation history:**")
                hist_rows = [
                    {
                        "Date":               h["date"],
                        "Top Recommendation": h["top_recommendation"],
                        "Net Annual Saving":  format_inr(h["net_annual_saving"]),
                    }
                    for h in alert_status["history"][:7]
                ]
                st.dataframe(
                    pd.DataFrame(hist_rows),
                    hide_index=True,
                    width="stretch",
                )

        with nm_tabs[4]:
            st.markdown("## 📄 Export Summary Report")
            st.caption(
                "Download a self-contained HTML report with all findings — "
                "suitable for sharing with the CFO or logistics director."
            )

            top_row = placement_df.iloc[0]
            fleet_recs = recommendations

            report_html = f"""<!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="UTF-8">
    <title>Network Intelligence Report — Bengaluru</title>
    <style>
      body {{ font-family: Arial, sans-serif; max-width: 900px; margin: 40px auto;
             color: #333; line-height: 1.6; }}
      h1   {{ color: #1a237e; }}
      h2   {{ color: #283593; border-bottom: 2px solid #e8eaf6; padding-bottom: 6px; }}
      .kpi {{ display:inline-block; background:#e8eaf6; border-radius:8px;
              padding:12px 20px; margin:8px; text-align:center; min-width:140px; }}
      .kpi .val {{ font-size:22px; font-weight:700; color:#1a237e; }}
      .kpi .lbl {{ font-size:12px; color:#555; }}
      .alert {{ background:#fff3e0; border-left:5px solid #e65100;
                 padding:12px 16px; border-radius:6px; margin:12px 0; }}
      table {{ width:100%; border-collapse:collapse; font-size:13px; }}
      th    {{ background:#e8eaf6; padding:8px; text-align:left; }}
      td    {{ padding:6px 8px; border-bottom:1px solid #eee; }}
      .rec  {{ background:#e8f5e9; border-left:4px solid #2e7d32;
                padding:10px 14px; border-radius:6px; margin:8px 0; }}
    </style>
    </head>
    <body>
    <h1>🏭 Network Intelligence Report</h1>
    <p><b>Generated:</b> {date.today().strftime('%d %B %Y')} &nbsp;|&nbsp;
       <b>Network:</b> Bengaluru Distribution &nbsp;|&nbsp;
       <b>Analysis period:</b> 30 days</p>

    <h2>Current Network</h2>
    <div>
      <div class="kpi">
        <div class="val">{int(demand_summary['total_avg_daily'])}</div>
        <div class="lbl">Avg daily deliveries</div>
      </div>
      <div class="kpi">
        <div class="val">{demand_summary['busiest_zone']}</div>
        <div class="lbl">Busiest zone</div>
      </div>
      <div class="kpi">
        <div class="val">{format_inr(top_row['current_daily_cost'])}</div>
        <div class="lbl">Est. daily routing cost</div>
      </div>
    </div>

    <h2>Warehouse Placement Recommendation</h2>
    <div class="rec">
      <b>⭐ Top Recommendation: {top_row['name']}</b><br>
      {top_row['description']}<br><br>
      Annual routing saving: <b>{format_inr(top_row['annual_routing_saving'])}</b><br>
      Annual lease cost: <b>{format_inr(top_row['annual_facility_cost'])}</b><br>
      <b style="color:#2e7d32">Net annual saving: {format_inr(top_row['net_annual_saving'])}</b><br>
      Payback period: <b>{top_row['payback_months']} months</b>
    </div>
    <p>Zones served by proposed warehouse: 
       <b>{', '.join(top_row['new_warehouse_zones'])}</b></p>

    <h2>All Candidates Ranked</h2>
    <table>
    <tr><th>Rank</th><th>Candidate</th><th>Net Saving/yr</th><th>Payback</th></tr>
    """
            for _, r in placement_df.iterrows():
                report_html += (
                    f"<tr><td>{r['rank']}</td><td>{r['name']}</td>"
                    f"<td>{format_inr(r['net_annual_saving'])}</td>"
                    f"<td>{'{}  mo'.format(r['payback_months']) if r['payback_months'] else 'N/A'}</td></tr>"
                )

            report_html += f"""
    </table>

    <h2>Fleet Right-Sizing</h2>
    """
            for rec in fleet_recs:
                if rec["feasible"]:
                    report_html += f"""
    <div class="rec">
      <b>{rec['vehicle_name']}</b> — avg utilisation {rec['avg_utilisation']:.1f}%<br>
      {rec['recommendation']}<br>
      <b>Annual saving: {format_inr(rec['annual_cost_inr'])}</b>
    </div>"""
            if not fleet_recs:
                report_html += "<p>All vehicles are running at healthy utilisation levels.</p>"

            report_html += f"""
    <h2>Strategic Alerts</h2>
    """
            if alert_status["has_alert"]:
                report_html += f"""
    <div class="alert">
      🚨 <b>High Confidence Alert:</b> {alert_status['alert_recommendation']} 
      has been the top recommendation {alert_status['days_appeared']} of the 
      last {alert_status['total_window_days']} days ({alert_status['frequency']:.0f}% frequency).<br>
      Projected annual saving: <b>{format_inr(alert_status['alert_saving'])}</b><br>
      <b>Recommended action:</b> Schedule formal evaluation with logistics and finance teams.
    </div>"""
            else:
                report_html += "<p>No active alerts this week.</p>"

            report_html += """
    <hr>
    <p style="font-size:11px;color:#888">
      This report was generated by the Supply Chain Intelligence Platform.
      All figures are based on 30-day synthetic demand history and approximate
      routing cost models. Actual savings will vary based on real traffic patterns,
      lease negotiations, and operational constraints.
    </p>
    </body></html>"""

            buf = io.BytesIO()
            buf.write(report_html.encode("utf-8"))
            buf.seek(0)
            st.download_button(
                label="📥 Download Report (HTML)",
                data=buf,
                file_name=f"network_intelligence_{date.today().isoformat()}.html",
                mime="text/html",
                help="Opens as a standalone page in your browser — shareable with stakeholders",
            )