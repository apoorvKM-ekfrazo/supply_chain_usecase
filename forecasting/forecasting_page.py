"""
forecasting/forecasting_page.py
Hierarchical SKU Demand Forecasting — Page 3 of the Supply Chain Intelligence platform.
Closes the digital twin loop by feeding statistical forecasting outputs into the MEIO
warehouse placement model.
"""

import math
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from data.forecasting_scenario import generate_forecasting_history
from forecasting.forecasting_engine import run_forecast
from data.meio_scenario import ZONES, ZONE_BASE_DEMAND

from ui.data_onboarding import (
    NI_DEMO_SUMMARY as _FORECAST_DEMO_SUMMARY,
    _ni_summary_cards   as _forecast_summary_cards,
    _ni_compact_badge   as _forecast_compact_badge,
    _show_example_and_template,
    _validate_csv,
    _parse_csv,
)


def _render_forecast_onboarding() -> bool:
    if "forecast_onboarding_complete" not in st.session_state:
        st.session_state.forecast_onboarding_complete = False
    if "forecast_data_summary" not in st.session_state:
        st.session_state.forecast_data_summary = None
    if "forecast_upload_error" not in st.session_state:
        st.session_state.forecast_upload_error = None

    if st.session_state.forecast_onboarding_complete and st.session_state.forecast_data_summary:
        _forecast_compact_badge(st.session_state.forecast_data_summary)
        return True

    st.markdown(
        """
        <div style="background:linear-gradient(135deg,#1A237E,#283593);
                    color:white;padding:16px 22px;border-radius:10px 10px 0 0">
            <div style="font-size:17px;font-weight:700">
                📤&nbsp; Step 1 — Load Your Network Data
            </div>
            <div style="font-size:12px;opacity:0.85;margin-top:3px">
                Upload 30 days of delivery records from your WMS or TMS —
                or use the Bengaluru demo dataset to explore the platform.
            </div>
        </div>
        <div style="background:white;border:1px solid #E2E8F0;border-top:none;
                    border-radius:0 0 10px 10px;padding:18px 22px;margin-bottom:4px">
        """,
        unsafe_allow_html=True,
    )

    upload_col, or_col, demo_col = st.columns([5, 1, 3])
    with upload_col:
        uploaded = st.file_uploader(
            "forecast_upload", type=["csv", "xlsx"],
            label_visibility="collapsed", key="forecast_upload_widget",
        )
        st.caption("CSV / Excel · Must include lat & lng columns · Data stays in your browser")
    with or_col:
        st.markdown(
            "<div style='text-align:center;padding-top:18px;color:#94A3B8;font-weight:600'>— OR —</div>",
            unsafe_allow_html=True,
        )
    with demo_col:
        demo_clicked = st.button(
            "🗂️  Use Bengaluru Demo Dataset", use_container_width=True,
            key="forecast_demo_btn",
            help="311 avg daily stops · 9 zones · 30 days of demand history",
        )
        st.caption("Pre-loaded Bengaluru distribution network data")

    st.markdown("</div>", unsafe_allow_html=True)
    _show_example_and_template()

    if demo_clicked:
        st.session_state.forecast_data_summary = _FORECAST_DEMO_SUMMARY
        st.session_state.forecast_upload_error = None
        st.rerun()

    if uploaded is not None and st.session_state.forecast_data_summary is None:
        try:
            df = pd.read_excel(uploaded) if uploaded.name.endswith(".xlsx") else pd.read_csv(uploaded)
            is_valid, error_msg = _validate_csv(df)
            if not is_valid:
                st.session_state.forecast_upload_error = error_msg
                st.session_state.forecast_data_summary = None
            else:
                base = _parse_csv(df)
                base.update({
                    "daily_cost_inr": _FORECAST_DEMO_SUMMARY["daily_cost_inr"],
                    "depot":          _FORECAST_DEMO_SUMMARY["depot"],
                    "busiest_zone":   _FORECAST_DEMO_SUMMARY["busiest_zone"],
                    "furthest_zone":  _FORECAST_DEMO_SUMMARY["furthest_zone"],
                    "source":         "upload",
                })
                st.session_state.forecast_data_summary = base
                st.session_state.forecast_upload_error = None
        except Exception as exc:
            st.session_state.forecast_upload_error = f"Could not read the file: {exc}."
            st.session_state.forecast_data_summary = None
        st.rerun()

    if st.session_state.forecast_upload_error:
        st.error(
            f"**File not accepted.** {st.session_state.forecast_upload_error}\n\n"
            "See the format guide above for the column guide and a downloadable template.",
            icon="⚠️",
        )
        if st.button("↩  Try a different file", key="forecast_retry"):
            st.session_state.forecast_upload_error = None
            st.rerun()

    if st.session_state.forecast_data_summary is not None:
        summary = st.session_state.forecast_data_summary
        src = summary.get("source", "demo")
        label = (
            "Bengaluru demo dataset ready"
            if src in ("demo", "upload_fallback")
            else f"File validated — {summary['total_stops']} records accepted"
        )
        st.markdown(
            f"""
            <div style="background:#e8f5e9;border:1px solid #a5d6a7;border-radius:8px;
                        padding:10px 16px;margin:12px 0 8px 0">
                <span style="color:#2e7d32;font-weight:700;font-size:14px">
                    ✅&nbsp; {label}
                </span>
                <span style="color:#64748B;font-size:12px;margin-left:8px">
                    — here is what the system found in your network data:
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        _forecast_summary_cards(summary)
        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
        _, btn_col, _ = st.columns([2, 3, 2])
        with btn_col:
            if st.button(
                "Proceed to Demand Forecasting →", type="primary",
                use_container_width=True, key="forecast_onboarding_proceed",
            ):
                st.session_state.forecast_onboarding_complete = True
                st.rerun()

    return False


def render_forecasting_page():
    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d47a1,#1565c0);
                color:white;padding:20px 28px;border-radius:10px;margin-bottom:20px">
        <div style="font-size:24px;font-weight:700">📈 Demand Forecasting</div>
        <div style="font-size:13px;opacity:0.85;margin-top:4px">
        Hierarchical SKU Forecasting · Bengaluru Distribution Network
        </div>
    </div>
    """, unsafe_allow_html=True)

    if not _render_forecast_onboarding():
        st.stop()

    history_df = generate_forecasting_history()

    st.markdown(
        "Trains AutoETS on 2 years of weekly delivery data across 36 zone-category series "
        "and projects demand 13 weeks forward. Use the results to see which zones are growing "
        "fastest and whether that changes the warehouse recommendation."
    )

    if st.button("🚀 Run Forecast", type="primary"):
        with st.spinner("Training forecasting models across 36 zone-category series..."):
            run_forecast(history_df)
        st.rerun()

    forecast_res = st.session_state.get("forecast_result")
    if forecast_res is None:
        st.info("Click **Run Forecast** above to train the models and see the projections.")
        return

    meta = forecast_res["metadata"]
    recon_label = "applied" if meta["reconciliation_applied"] else "skipped (simple aggregation used)"
    st.markdown(
        f"<div style='background:#f1f5f9;padding:8px 14px;border-radius:6px;"
        f"font-size:12px;color:#475569;margin-bottom:15px'>"
        f"⚡ Forecast ready — trained in {meta['fit_time_seconds']}s · "
        f"Hierarchical reconciliation: {recon_label}</div>",
        unsafe_allow_html=True,
    )
    # ── AI interpretation of the forecast results ─────────────────────────────
    # Generated once per session and cached. Calls Groq with the zone-level
    # growth summary and asks for a plain-English briefing for a logistics exec.
    if "forecast_ai_summary" not in st.session_state:
        try:
            from groq import Groq
            import os
            _h = forecast_res["history"]
            _f = forecast_res["forecast"]
            zone_lines = []
            for zone in ZONES:
                zh = _h[_h["unique_id"] == zone].sort_values("ds")
                zf = _f[_f["unique_id"] == zone].sort_values("ds")
                if not zh.empty and not zf.empty:
                    cur = zh.iloc[-1]["y"]
                    proj = zf.iloc[-1]["P50"]
                    pct = (proj - cur) / cur * 100
                    zone_lines.append(f"{zone}: {cur:.0f}→{proj:.0f} stops/wk ({pct:+.1f}%)")

            prompt = (
                "You are briefing a logistics CFO on a Bengaluru delivery network forecast.\n\n"
                "Zone demand (current weekly → 13-week forecast):\n"
                + "\n".join(zone_lines) +
                "\n\nWrite 2-3 sentences in plain English. Name the fastest and slowest zones "
                "with specific numbers. State what this means for warehouse planning. "
                "No jargon. No bullet points."
            )
            client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
            resp = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=160, temperature=0.3,
            )
            st.session_state.forecast_ai_summary = resp.choices[0].message.content.strip()
        except Exception:
            st.session_state.forecast_ai_summary = None

    if st.session_state.get("forecast_ai_summary"):
        st.markdown(
            f"<div style='background:#f0fdf4;border-left:4px solid #16a34a;"
            f"border-radius:6px;padding:12px 16px;margin-bottom:16px;font-size:13px;"
            f"color:#1e293b'>🤖 <b>AI Insight:</b> "
            f"{st.session_state.forecast_ai_summary}</div>",
            unsafe_allow_html=True,
        )

    filter_zone = st.selectbox(
        "Select zone", options=["All Zones (Total)"] + ZONES, index=0,
    )

    f_tabs = st.tabs(["📊 Historical Demand", "🔮 Growth Trajectory", "🗺️ Zone Forecast", "🔗 Update MEIO"])

    history_data  = forecast_res["history"]
    forecast_data = forecast_res["forecast"]

    # ── TAB 1: Historical Demand ──────────────────────────────────────────────
    with f_tabs[0]:
        st.markdown("#### Weekly Delivery Volume History (Last 52 Weeks)")
        fig_hist = go.Figure()

        if filter_zone == "All Zones (Total)":
            df_plot = (history_data[history_data["unique_id"] == "Total"]
                       .sort_values("ds").tail(52))   # last 52 weeks only
            fig_hist.add_trace(go.Scatter(
                x=df_plot["ds"], y=df_plot["y"], name="City Total",
                line=dict(color="#0d47a1", width=2.5),
            ))
        else:
            cats   = ["FMCG", "Electronics", "Apparel", "Home Goods"]
            colors = ["#2e7d32", "#d32f2f", "#f57c00", "#7b1fa2"]
            df_zone = history_data[history_data["zone"] == filter_zone]
            for c_name, c_color in zip(cats, colors):
                df_c = (df_zone[df_zone["category"] == c_name]
                        .sort_values("ds").tail(52))
                fig_hist.add_trace(go.Scatter(
                    x=df_c["ds"], y=df_c["y"], name=c_name,
                    line=dict(color=c_color, width=1.8),
                ))

        # Seasonal landmarks (last 52 weeks only)
        unique_dates = sorted(df_plot["ds"].unique()) if filter_zone == "All Zones (Total)" else []
        for d_str in unique_dates:
            p_date = pd.to_datetime(d_str)
            c_week = p_date.isocalendar().week
            if c_week == 43:
                fig_hist.add_vline(x=d_str, line_dash="dot", line_color="#e65100", opacity=0.6)
            elif c_week == 12:
                fig_hist.add_vline(x=d_str, line_dash="dot", line_color="#2e7d32", opacity=0.6)

        fig_hist.update_layout(
            height=400, margin=dict(l=40, r=40, t=20, b=40),
            hovermode="x unified", paper_bgcolor="white", plot_bgcolor="#f8fafc",
        )
        st.plotly_chart(fig_hist, use_container_width=True)
        st.caption(
            "Orange dotted lines = Diwali week · Green dotted lines = Holi week · "
            "Showing last 52 weeks of history."
        )

    # ── TAB 2: Growth Trajectory (Forecast) ──────────────────────────────────
    with f_tabs[1]:
        st.markdown("#### Demand Forecast — Next 13 Weeks")
        fig_fcst = go.Figure()

        target_uid = "Total" if filter_zone == "All Zones (Total)" else filter_zone
        df_h_slice = (history_data[history_data["unique_id"] == target_uid]
                      .sort_values("ds").tail(26))
        df_f_slice = (forecast_data[forecast_data["unique_id"] == target_uid]
                      .sort_values("ds"))

        last_hist_row = df_h_slice.iloc[-1]
        cnt_ds  = [last_hist_row["ds"]] + list(df_f_slice["ds"])
        cnt_p50 = [last_hist_row["y"]]  + list(df_f_slice["P50"])
        cnt_p10 = [last_hist_row["y"]]  + list(df_f_slice["P10"])
        cnt_p90 = [last_hist_row["y"]]  + list(df_f_slice["P90"])

        fig_fcst.add_trace(go.Scatter(
            x=df_h_slice["ds"], y=df_h_slice["y"],
            name="Recent history", line=dict(color="#334155", width=2),
        ))
        fig_fcst.add_trace(go.Scatter(
            x=cnt_ds, y=cnt_p90, line=dict(width=0), hoverinfo="skip", showlegend=False,
        ))
        fig_fcst.add_trace(go.Scatter(
            x=cnt_ds, y=cnt_p10, fill="tonexty",
            fillcolor="rgba(13, 71, 161, 0.12)",
            line=dict(width=0), name="80% confidence band",
        ))
        fig_fcst.add_trace(go.Scatter(
            x=cnt_ds, y=cnt_p50, name="P50 forecast",
            line=dict(color="#0d47a1", dash="dash", width=2),
        ))

        fig_fcst.update_layout(
            height=400, margin=dict(l=40, r=40, t=20, b=40),
            hovermode="x unified", plot_bgcolor="#f8fafc",
        )
        st.plotly_chart(fig_fcst, use_container_width=True)
        st.caption(
            "The shaded band is the 80% confidence interval — demand is expected to fall "
            "within this range 8 times out of 10. The wide lower bound reflects statistical "
            "uncertainty after a seasonal peak, not a realistic worst case. Use the P50 "
            "(dashed line) for planning decisions."
        )

        st.markdown("**Top 3 fastest-growing zones**")
        rank_rows = []
        for z in ZONES:
            df_z_f = forecast_data[forecast_data["unique_id"] == z].sort_values("ds")
            df_z_h = history_data[history_data["unique_id"] == z].sort_values("ds")
            if df_z_f.empty or df_z_h.empty:
                continue
            h_val = df_z_h.iloc[-1]["y"]
            f_val = df_z_f.iloc[-1]["P50"]
            g_pct = ((f_val - h_val) / h_val) * 100
            rank_rows.append({"Zone": z, "Growth": g_pct})

        df_rank = pd.DataFrame(rank_rows).sort_values("Growth", ascending=False).head(3)
        rc1, rc2, rc3 = st.columns(3)
        for col, (_, r_item) in zip([rc1, rc2, rc3], df_rank.iterrows()):
            col.markdown(
                f"<div style='background:#f8fafc;border:1px solid #e2e8f0;padding:12px;"
                f"border-radius:8px;text-align:center'>"
                f"<div style='font-size:11px;color:#64748b;font-weight:600'>{r_item['Zone']}</div>"
                f"<div style='font-size:20px;font-weight:700;color:#16a34a;margin-top:4px'>"
                f"▲ {r_item['Growth']:.1f}%</div>"
                f"<div style='font-size:10px;color:#64748b'>over 13 weeks</div></div>",
                unsafe_allow_html=True,
            )

    # ── TAB 3: Zone Forecast ──────────────────────────────────────────────────
    with f_tabs[2]:
        st.markdown("#### Zone Demand Forecast")
        st.caption(
            "Each card shows a zone's current weekly demand and where the forecast says "
            "it will be at the end of the 13-week horizon. Fastest-growing zones are where "
            "expanded infrastructure pays off soonest."
        )

        for row_block in range(3):
            sc1, sc2, sc3 = st.columns(3)
            for col_block, s_col in enumerate([sc1, sc2, sc3]):
                z_idx = row_block * 3 + col_block
                if z_idx >= len(ZONES):
                    break
                zone_name = ZONES[z_idx]

                df_z_h = history_data[history_data["unique_id"] == zone_name].sort_values("ds")
                df_z_f = forecast_data[forecast_data["unique_id"] == zone_name].sort_values("ds")
                if df_z_f.empty or df_z_h.empty:
                    continue

                # Use last observed week vs week-13 forecast P50 — apples to apples.
                # 4w-mean vs 13w-mean produces a contradiction because the 13w mean
                # averages a period that includes the current low point, making the
                # "projected" number look lower even when growth is positive.
                current_demand   = df_z_h.iloc[-1]["y"]
                projected_demand = df_z_f.iloc[-1]["P50"]
                growth_pct       = (projected_demand - current_demand) / current_demand * 100
                monthly_approx   = growth_pct / 3.0

                arrow, a_color = (
                    ("▲", "#16a34a") if monthly_approx > 1.0
                    else (("▶", "#d97706") if monthly_approx >= 0
                    else ("▼", "#94a3b8"))
                )

                with s_col:
                    st.markdown(
                        f"<div style='background:white;border:1px solid #e2e8f0;"
                        f"border-radius:8px;padding:12px;margin-bottom:10px;"
                        f"box-shadow:0 1px 3px rgba(0,0,0,0.05)'>"
                        f"<span style='font-weight:700;font-size:13px;color:#1e293b'>{zone_name}</span>"
                        f"<div style='font-size:11px;color:#475569;margin-top:4px'>"
                        f"Now: <b>{current_demand:.0f} stops/wk</b></div>"
                        f"<div style='font-size:11px;color:#475569'>"
                        f"Week 13: <b>{projected_demand:.0f} stops/wk</b></div>"
                        f"<div style='font-size:12px;font-weight:600;color:{a_color};margin-top:2px'>"
                        f"{arrow} {monthly_approx:.1f}%/mo</div></div>",
                        unsafe_allow_html=True,
                    )
                    # Sparkline: 4 history weeks then beginning/middle/end of forecast
                    # so the line shows the actual trajectory, not just the starting dip.
                    spark_vals = (
                        list(df_z_h.tail(4)["y"].values) +
                        list(df_z_f.iloc[[0, 6, 12]]["P50"].values)
                    )
                    sp_fig = go.Figure(go.Scatter(
                        x=list(range(7)), y=spark_vals,
                        line=dict(color=a_color, width=1.5), hoverinfo="skip",
                    ))
                    sp_fig.update_layout(
                        margin=dict(l=0, r=0, t=0, b=0),
                        xaxis=dict(visible=False), yaxis=dict(visible=False),
                        showlegend=False, height=24, width=120,
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    )
                    st.plotly_chart(sp_fig, config={"displayModeBar": False},
                                    key=f"spark_{zone_name}")

        fastest_zone = (pd.DataFrame(rank_rows).sort_values("Growth", ascending=False)
                        .iloc[0]["Zone"]) if rank_rows else "—"
        max_ratio, seasonal_leader = -1.0, "—"
        for z in ZONES:
            df_z_h = history_data[history_data["unique_id"] == z]
            ratio = df_z_h["y"].max() / max(1.0, df_z_h["y"].min())
            if ratio > max_ratio:
                max_ratio, seasonal_leader = ratio, z

        st.markdown(
            f"<div style='background:#eff6ff;border-left:4px solid #3b82f6;"
            f"padding:12px 16px;border-radius:6px;margin-top:15px;font-size:13px;color:#1e3a8a'>"
            f"Fastest-growing zone: <b>{fastest_zone}</b> · "
            f"Most seasonal zone: <b>{seasonal_leader}</b> "
            f"(peak/trough ratio: {max_ratio:.1f}×)</div>",
            unsafe_allow_html=True,
        )

    # ── TAB 4: Update MEIO ────────────────────────────────────────────────────
    with f_tabs[3]:
        st.markdown("#### Connect Forecast to Network Planning")
        st.caption(
            "Send the forecast demand projections to Network Intelligence so its warehouse "
            "recommendation is based on where your business is going, not where it has been."
        )

        current_network_volume = 311
        breakeven_volume       = 401   # Route Optimizer break-even at 120-stop scenario scale

        zone_growth_rates = {}
        for zone in ZONES:
            z_hist = history_data[history_data["unique_id"] == zone].sort_values("ds")
            z_fcst = forecast_data[forecast_data["unique_id"] == zone].sort_values("ds")
            if len(z_hist) > 0 and len(z_fcst) > 0:
                total_pct    = (z_fcst.iloc[-1]["P50"] - z_hist.iloc[-1]["y"]) / z_hist.iloc[-1]["y"]
                monthly_rate = total_pct / 3.0
                zone_growth_rates[zone] = max(0.001, monthly_rate)

        total_current = sum(
            history_data[history_data["unique_id"] == z].iloc[-1]["y"]
            for z in zone_growth_rates
        )
        network_monthly_rate = sum(
            zone_growth_rates[z] *
            history_data[history_data["unique_id"] == z].iloc[-1]["y"] / total_current
            for z in zone_growth_rates
        )

        forecast_months = (
            math.log(breakeven_volume / current_network_volume) /
            math.log(1 + network_monthly_rate)
        )
        annual_rate_pct  = ((1 + network_monthly_rate) ** 12 - 1) * 100
        fastest_zone_key = max(zone_growth_rates, key=zone_growth_rates.get)
        fastest_zone_pct = zone_growth_rates[fastest_zone_key] * 100

        st.markdown("**When does Marathahalli Hub break even?**")
        mc1, mc2, mc3 = st.columns(3)
        mc1.metric("Current network", f"{current_network_volume} stops/day",
                   delta="MEIO 30-day average")
        mc2.metric("Break-even threshold", f"{breakeven_volume} stops/day",
                   delta="Route Optimizer scenario")
        mc3.metric("Forecast break-even", f"{forecast_months:.0f} months",
                   delta=f"{network_monthly_rate*100:.1f}%/mo · {annual_rate_pct:.0f}%/yr")

        st.caption(
            "Note: the 401-stop threshold comes from the Route Optimizer's 120-stop daily "
            "scenario — it is the volume at which adding Marathahalli Hub breaks even in that "
            "simulation. Network Intelligence uses the full 311-stop MEIO demand and may show "
            "a shorter payback because the network is already larger than the Route Optimizer scenario."
        )

        st.markdown(
            f"<div style='background:#eff6ff;border-left:4px solid #3b82f6;"
            f"padding:12px 16px;border-radius:6px;margin:12px 0;font-size:13px;color:#1e3a8a'>"
            f"📊 Fastest-growing zone: <b>{fastest_zone_key}</b> at "
            f"<b>{fastest_zone_pct:.1f}%/month</b> — if growth concentrates here, "
            f"the eastern corridor reaches break-even volume sooner.</div>",
            unsafe_allow_html=True,
        )

        if st.button("📥 Update MEIO with This Forecast", type="primary",
                     use_container_width=True):
            meio_payload = {
                zone: round(float(
                    forecast_data[forecast_data["unique_id"] == zone]["P50"].mean()
                ), 1)
                for zone in ZONES
            }
            st.session_state.meio_forecast_demand  = meio_payload
            st.session_state.meio_forecast_applied = True
            st.session_state.meio_analysed         = False
            st.session_state.meio_placement_df     = None
            st.success(
                "✅ Forecast applied. Switch to **Network Intelligence** and click "
                "**Run Analysis** to see the updated warehouse recommendation."
            )