"""
ui/intercity_optimizer.py
--------------------------
Intercity Load Optimiser — Tab 2 of the supply chain pipeline.

Receives corridor groups from Manifest Triage (Tab 1), sizes intercity
vehicles per corridor, calculates spare capacity, and flags co-loading
opportunities worth advertising to freight partners.

Research basis: Indian Freight Co-loading Practices (2026)
  - Co-loading is the operational backbone of neutral courier consolidators
    like GMS Worldwide Express — this is their existing business model,
    not a new feature.
  - Minimum viable spare capacity for open-market co-loading: 50 kg.
  - Rates are composite averages from commercial carrier rate cards.
  - ShipBridge is the appropriate B2B co-loading platform (explicitly
    offers LTL/shared freight services, unlike BlackBuck/Vahak which
    handle FTL only and prohibit co-loading).
  - Delhi NCR corridor crosses 5 state borders — e-way bill documentation
    risk must be surfaced; this is why that corridor rate is 4x Hyderabad.
"""

import math
import pandas as pd
import streamlit as st
import plotly.graph_objects as go


# ── Intercity truck tiers (surface express, GMS / neutral consolidator scale) ──
TRUCK_TIERS = [
    {"name": "EV Courier Van",     "capacity_kg": 100,  "daily_cost_inr": 800,
     "icon": "🛵", "type": "EV · Short/Medium haul"},
    {"name": "LCV Medium Van",     "capacity_kg": 150,  "daily_cost_inr": 1200,
     "icon": "🚐", "type": "LCV · Medium haul"},
    {"name": "LCV Large Van",      "capacity_kg": 300,  "daily_cost_inr": 1800,
     "icon": "🚐", "type": "LCV · Medium haul"},
    {"name": "Tata Ace (SCV)",     "capacity_kg": 500,  "daily_cost_inr": 2200,
     "icon": "🛺", "type": "SCV · Long haul"},
    {"name": "Mahindra Bolero",    "capacity_kg": 1000, "daily_cost_inr": 3200,
     "icon": "🚙", "type": "LCV · Long haul"},
    {"name": "Eicher 14 ft (ICV)","capacity_kg": 3500, "daily_cost_inr": 5500,
     "icon": "🚛", "type": "ICV · Long haul"},
]

# ── Wholesale co-load rates from Indian Freight Co-loading research (2026) ─────
# These are the rates a carrier earns when selling spare linehaul capacity
# to a neutral consolidator — not retail rates which include last-mile.
CORRIDOR_RATES = {
    "Delhi NCR":       {
        "rate_per_kg": 80, "rate_range": "₹65–₹95/kg",
        "transit": "3–7 days", "risk": "high",
        "risk_note": "Crosses 5 state borders. E-way bill required per consignment >₹50,000. "
                     "Documentation failure can detain the full truck at a state checkpost.",
    },
    "Mumbai":          {
        "rate_per_kg": 52, "rate_range": "₹40–₹65/kg",
        "transit": "2–4 days", "risk": "low",
        "risk_note": "High-volume corridor. Strong institutional B2B traffic.",
    },
    "Hyderabad":       {
        "rate_per_kg": 17, "rate_range": "₹12–₹21/kg",
        "transit": "2–4 days", "risk": "low",
        "risk_note": "Highest-frequency South India corridor (~570 km). "
                     "Dense PTL volumes compress per-kg cost.",
    },
    "Kerala":          {
        "rate_per_kg": 35, "rate_range": "₹28–₹42/kg",
        "transit": "2–3 days", "risk": "low",
        "risk_note": "Single state transit. Strong e-commerce volumes from FMCG and pharma.",
    },
    "Chennai":         {
        "rate_per_kg": 25, "rate_range": "₹20–₹30/kg",
        "transit": "1–2 days", "risk": "low",
        "risk_note": "Short corridor (~350 km). High-frequency auto-component and garment traffic.",
    },
    "Pune":            {
        "rate_per_kg": 48, "rate_range": "₹40–₹56/kg",
        "transit": "2–3 days", "risk": "low",
        "risk_note": "Routed via Mumbai corridor. Strong manufacturing outbound.",
    },
    "Bengaluru Local": {
        "rate_per_kg": 0, "rate_range": "—",
        "transit": "Same day", "risk": "none",
        "risk_note": "Intracity — hand off to Load Optimiser and Route Optimizer.",
    },
    "Other":           {
        "rate_per_kg": 30, "rate_range": "₹25–₹35/kg",
        "transit": "Varies", "risk": "medium",
        "risk_note": "Non-standard corridor. Confirm route availability with carrier.",
    },
}

CO_LOAD_THRESHOLD_KG = 50   # minimum spare capacity worth advertising
WORKING_DAYS         = 22   # operational days per month
CARRIER_MARGIN_PCT   = 0.27 # 25-30% gross margin on co-loaded space (research avg)
FUEL_SURCHARGE_PCT   = 0.08 # 8% FSC (research range 5-12%)


# ── Demo data (used when Tab 1 has not been run) ───────────────────────────────
DEMO_CORRIDORS = {
    "Delhi NCR":       {"consignments": 3, "total_weight_kg": 148.0, "hub": "Ghaziabad DC"},
    "Mumbai":          {"consignments": 2, "total_weight_kg": 107.0, "hub": "Bhiwandi DC"},
    "Hyderabad":       {"consignments": 2, "total_weight_kg": 59.0,  "hub": "Hyderabad DC"},
    "Kerala":          {"consignments": 1, "total_weight_kg": 50.0,  "hub": "Kochi DC"},
    "Bengaluru Local": {"consignments": 2, "total_weight_kg": 20.0,  "hub": "Central Depot"},
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _select_truck(total_kg: float) -> dict:
    """
    Pick the smallest truck tier that fits the total weight with a 5% buffer.
    The buffer avoids running at exactly 100% which creates no room for
    documentation weight variance or last-minute additions at the hub.
    """
    for tier in TRUCK_TIERS:
        if tier["capacity_kg"] >= total_kg * 1.05:
            return tier
    return TRUCK_TIERS[-1]


def _corridor_analysis(corridor: str, total_kg: float) -> dict:
    """
    Full analysis for one corridor: truck selection, spare capacity,
    co-load threshold decision, and revenue projection.

    All arithmetic done in Python — no LLM involved in these numbers.
    """
    truck        = _select_truck(total_kg)
    spare_kg     = truck["capacity_kg"] - total_kg
    util_pct     = round(total_kg / truck["capacity_kg"] * 100, 1)
    rates        = CORRIDOR_RATES.get(corridor, CORRIDOR_RATES["Other"])
    rate_per_kg  = rates["rate_per_kg"]

    # Co-load viability
    advertise    = spare_kg >= CO_LOAD_THRESHOLD_KG and rate_per_kg > 0

    # Revenue (gross wholesale rate on spare kg)
    gross_rev    = round(spare_kg * rate_per_kg) if advertise else 0
    # Add fuel surcharge (carriers pass this to the co-load buyer)
    gross_with_fsc = round(gross_rev * (1 + FUEL_SURCHARGE_PCT))
    # Carrier net margin on co-loaded space
    net_margin   = round(gross_with_fsc * CARRIER_MARGIN_PCT)
    monthly_rev  = gross_with_fsc * WORKING_DAYS if advertise else 0

    return {
        "truck":          truck,
        "spare_kg":       round(spare_kg, 1),
        "util_pct":       util_pct,
        "rates":          rates,
        "advertise":      advertise,
        "gross_rev":      gross_rev,
        "gross_with_fsc": gross_with_fsc,
        "net_margin":     net_margin,
        "monthly_rev":    monthly_rev,
    }


def _load_corridor_data() -> dict:
    """
    Read corridor groups from Tab 1 session state if available.
    Falls back to demo data if Manifest Triage has not been run.
    Returns dict of {corridor_name: {consignments, total_weight_kg, hub}}.
    """
    result_df = st.session_state.get("triage_result_df")

    if result_df is None or "_corridor" not in result_df.columns:
        return DEMO_CORRIDORS, True  # (data, is_demo)

    # Build from triage session state
    corridors = {}
    for corridor, grp in result_df.groupby("_corridor"):
        if corridor in ("Unassigned", "Other"):
            continue
        hub = grp["_hub"].iloc[0] if "_hub" in grp.columns else "—"

        # Auto-detect weight column
        wt_col = next(
            (c for c in grp.columns
             if c.lower() in {"weight_kg", "weight", "wt", "kg"}),
            None,
        )
        total_wt = (
            grp[wt_col].apply(pd.to_numeric, errors="coerce").sum()
            if wt_col else 0.0
        )
        corridors[corridor] = {
            "consignments":   len(grp),
            "total_weight_kg": round(total_wt, 1),
            "hub":            hub,
        }

    return (corridors, False) if corridors else (DEMO_CORRIDORS, True)


# ── Corridor card ─────────────────────────────────────────────────────────────

def _render_corridor_card(corridor: str, data: dict, analysis: dict):
    """Render one corridor's full analysis as a structured card."""
    truck  = analysis["truck"]
    rates  = analysis["rates"]
    adv    = analysis["advertise"]
    spare  = analysis["spare_kg"]
    util   = analysis["util_pct"]

    # Card border colour by risk level
    border = {"high": "#E65100", "medium": "#F57C00",
               "low": "#2e7d32", "none": "#1565C0"}.get(rates["risk"], "#94a3b8")

    # Header
    st.markdown(
        f"<div style='border-left:4px solid {border};background:#f8fafc;"
        f"border-radius:0 8px 8px 0;padding:14px 18px;margin-bottom:8px'>"
        f"<div style='font-size:15px;font-weight:700;color:#1A237E'>"
        f"{truck['icon']} {corridor} — {data['hub']}</div>"
        f"<div style='font-size:12px;color:#64748b;margin-top:2px'>"
        f"{data['consignments']} consignment(s) · "
        f"{data['total_weight_kg']:.0f} kg total · "
        f"{rates['transit']} transit"
        f"</div></div>",
        unsafe_allow_html=True,
    )

    col_l, col_m, col_r = st.columns([3, 3, 4])

    with col_l:
        st.markdown(
            f"<div style='background:white;border:1px solid #E2E8F0;"
            f"border-radius:8px;padding:12px'>"
            f"<div style='font-size:11px;color:#64748b;font-weight:600;"
            f"text-transform:uppercase;letter-spacing:1px'>Vehicle</div>"
            f"<div style='font-size:16px;font-weight:700;color:#1A237E;margin-top:4px'>"
            f"{truck['icon']} {truck['name']}</div>"
            f"<div style='font-size:12px;color:#475569;margin-top:2px'>"
            f"Capacity: {truck['capacity_kg']} kg<br>"
            f"Daily cost: ₹{truck['daily_cost_inr']:,}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    with col_m:
        util_color = "#2e7d32" if util >= 70 else ("#E65100" if util < 40 else "#1565C0")
        st.markdown(
            f"<div style='background:white;border:1px solid #E2E8F0;"
            f"border-radius:8px;padding:12px'>"
            f"<div style='font-size:11px;color:#64748b;font-weight:600;"
            f"text-transform:uppercase;letter-spacing:1px'>Utilisation</div>"
            f"<div style='font-size:22px;font-weight:700;color:{util_color};margin-top:4px'>"
            f"{util:.0f}%</div>"
            f"<div style='font-size:12px;color:#475569;margin-top:2px'>"
            f"Loaded: {data['total_weight_kg']:.0f} kg<br>"
            f"Spare: <b>{spare:.0f} kg</b></div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    with col_r:
        if corridor == "Bengaluru Local":
            st.markdown(
                "<div style='background:#e3f2fd;border:1px solid #1565C0;"
                "border-radius:8px;padding:12px;font-size:13px;color:#0d47a1'>"
                "🏙️ <b>Intracity dispatch</b><br>"
                "Hand off to Load Optimisation (Tab 3) and Route Optimizer (Tab 4).</div>",
                unsafe_allow_html=True,
            )
        elif adv:
            rev = analysis["gross_with_fsc"]
            net = analysis["net_margin"]
            monthly = analysis["monthly_rev"]
            st.markdown(
                f"<div style='background:#e8f5e9;border:1px solid #2e7d32;"
                f"border-radius:8px;padding:12px'>"
                f"<div style='font-size:11px;color:#2e7d32;font-weight:700;"
                f"text-transform:uppercase;letter-spacing:1px'>Co-load opportunity</div>"
                f"<div style='font-size:16px;font-weight:700;color:#1b5e20;margin-top:4px'>"
                f"₹{rev:,} per trip</div>"
                f"<div style='font-size:12px;color:#2e7d32'>"
                f"({rates['rate_range']} · +{int(FUEL_SURCHARGE_PCT*100)}% FSC)<br>"
                f"Net margin: ₹{net:,} · Monthly: ₹{monthly:,.0f}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
            if st.button(
                f"📤 Post to ShipBridge — {spare:.0f} kg spare",
                key=f"post_{corridor}",
                use_container_width=True,
            ):
                st.session_state[f"shipbridge_posted_{corridor}"] = True

            # ShipBridge post preview (demo only, no actual API)
            if st.session_state.get(f"shipbridge_posted_{corridor}"):
                st.markdown(
                    f"<div style='background:#1A237E;color:white;border-radius:6px;"
                    f"padding:10px 14px;font-size:12px;margin-top:6px'>"
                    f"✅ <b>Draft posted to ShipBridge</b><br>"
                    f"Corridor: Bengaluru → {corridor}<br>"
                    f"Available: {spare:.0f} kg · Rate: {rates['rate_range']}<br>"
                    f"Hub: {data['hub']} · Transit: {rates['transit']}"
                    f"</div>",
                    unsafe_allow_html=True,
                )
        else:
            reason = (
                "Bengaluru Local — intracity only"
                if corridor == "Bengaluru Local"
                else f"Spare capacity ({spare:.0f} kg) is below the "
                     f"{CO_LOAD_THRESHOLD_KG} kg minimum threshold. "
                     "Administrative overhead exceeds co-load revenue at this volume."
            )
            st.markdown(
                f"<div style='background:#f8fafc;border:1px solid #E2E8F0;"
                f"border-radius:8px;padding:12px;font-size:12px;color:#64748b'>"
                f"⊘ <b>Not worth advertising</b><br>{reason}</div>",
                unsafe_allow_html=True,
            )

    # Risk note for high-risk corridors
    if rates["risk"] == "high":
        st.warning(
            f"⚠️ **Documentation risk — {corridor}:** {rates['risk_note']}",
            icon="📋",
        )

    st.markdown("---")


# ── Main render ───────────────────────────────────────────────────────────────

def render_intercity_optimizer():
    """
    Intercity Load Optimiser page.
    Called from app.py when '🚛 Intercity Load Optimiser' is selected.
    """
    corridors, is_demo = _load_corridor_data()

    if is_demo:
        st.info(
            "📋 **Showing demo data.** Run **Manifest Triage** (Tab 1) first "
            "to populate this page with your actual corridor groups.",
            icon="ℹ️",
        )

    # ── Summary header cards ──────────────────────────────────────────────────
    total_consignments = sum(d["consignments"]    for d in corridors.values())
    total_weight       = sum(d["total_weight_kg"] for d in corridors.values())
    n_intercity        = sum(
        1 for c in corridors if c not in ("Bengaluru Local", "Unassigned", "Other")
    )

    # Pre-compute all corridor analyses
    analyses = {
        corridor: _corridor_analysis(corridor, data["total_weight_kg"])
        for corridor, data in corridors.items()
    }

    total_monthly_rev  = sum(a["monthly_rev"]    for a in analyses.values())
    corridors_with_opp = sum(1 for a in analyses.values() if a["advertise"])

    h1, h2, h3, h4 = st.columns(4)
    h1.metric("Total consignments", total_consignments)
    h2.metric("Total weight",       f"{total_weight:.0f} kg")
    h3.metric("Intercity corridors", n_intercity)
    h4.metric("Co-load revenue/month",
              f"₹{total_monthly_rev:,.0f}",
              delta=f"{corridors_with_opp} corridor(s) viable",
              delta_color="off")

    if total_monthly_rev > 0:
        st.markdown(
            f"<div style='background:#1b5e20;color:white;border-radius:8px;"
            f"padding:12px 18px;margin:8px 0;font-size:13px'>"
            f"💡 <b>By advertising spare capacity on {corridors_with_opp} corridor(s) "
            f"through ShipBridge, GMS can generate approximately "
            f"<b>₹{total_monthly_rev:,.0f}/month</b> in additional revenue — "
            f"converting fixed linehaul costs into margin. "
            f"This is how neutral co-loaders like GMS structurally outperform "
            f"asset-heavy carriers on unit economics."
            f"</div>",
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # ── Per-corridor cards ────────────────────────────────────────────────────
    st.markdown("#### Corridor-by-Corridor Analysis")
    st.caption(
        f"Minimum viable spare capacity for advertising: {CO_LOAD_THRESHOLD_KG} kg. "
        "Rates are wholesale co-load rates (source: Indian Freight Co-loading research, 2026). "
        "Revenue estimates assume 22 working days/month and 8% fuel surcharge."
    )

    # Show intercity corridors first, local last
    order = sorted(
        corridors.keys(),
        key=lambda c: (
            0 if c not in ("Bengaluru Local", "Unassigned", "Other") else 1
        ),
    )

    for corridor in order:
        data     = corridors[corridor]
        analysis = analyses[corridor]
        _render_corridor_card(corridor, data, analysis)

    # ── Rate reference ────────────────────────────────────────────────────────
    with st.expander("📊 Wholesale co-load rate reference (Bengaluru origin)", expanded=False):
        rate_rows = [
            {
                "Corridor":      k,
                "Rate range":    v["rate_range"],
                "Transit":       v["transit"],
                "Risk level":    v["risk"].title(),
                "Key note":      v["risk_note"][:80] + "…" if len(v["risk_note"]) > 80 else v["risk_note"],
            }
            for k, v in CORRIDOR_RATES.items()
            if v["rate_per_kg"] > 0
        ]
        st.dataframe(
            pd.DataFrame(rate_rows),
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            "Source: Indian Freight Co-loading Practices research (2026). "
            "Composite averages from commercial carrier rate cards. "
            "Subject to fuel surcharge (5–12%) and 18% GST. "
            "PTL rates are 30–50% higher per MT than FTL equivalent."
        )

    with st.expander("📚  Data Sources", expanded=False):
        sources = [
            {
                "What it supports": "Corridor rates (Hyderabad, Mumbai, Delhi NCR)",
                "Source": "Indian Freight Co-loading Practices — Strategic Analysis (2026)",
                "Type": "Research / composite",
                "Link": "Commissioned research; underlying sources include ClickPost, iCarry.in, Tata nexarc rate cards",
            },
            {
                "What it supports": "PTL 30–50% more expensive per MT than FTL",
                "Source": "PTL vs FTL Logistics — Cost Comparison and Decision Guide India 2026",
                "Type": "Industry report",
                "Link": "safeandsecure.in/ptl-vs-ftl-cost-comparison-india",
            },
            {
                "What it supports": "Linehaul = 35–40% of total logistics expenditure",
                "Source": "Delhivery Annual Report 2021–22 and ValuePickr Forum analysis",
                "Type": "Company filing",
                "Link": "delhivery.com/wp-content/uploads/2022/09/Delhivery-AR-21-22.pdf",
            },
            {
                "What it supports": "Carrier EBITDA margin 14–20% on co-loaded space",
                "Source": "Delhivery operational model analysis, ValuePickr Forum",
                "Type": "Derived estimate",
                "Link": "forum.valuepickr.com/t/delhivery",
            },
            {
                "What it supports": "Minimum viable spare capacity 50–100 kg (open market)",
                "Source": "Indian Freight Co-loading Practices research (2026)",
                "Type": "Research",
                "Link": "See co-loading threshold discussion, Section: Economic Viability",
            },
            {
                "What it supports": "E-way bill risk on Delhi NCR corridor (5 state borders)",
                "Source": "Indian Freight Co-loading Practices research (2026)",
                "Type": "Regulatory context",
                "Link": "Section: Commission Structures and Per-Kilogram Rate Realization",
            },
            {
                "What it supports": "ShipBridge as B2B co-loading platform",
                "Source": "ShipBridge.in — platform description",
                "Type": "Primary source",
                "Link": "shipbridge.in",
            },
            {
                "What it supports": "GMS Worldwide operates as neutral courier consolidator",
                "Source": "Indian Freight Co-loading Practices research (2026) citing GMS Worldwide",
                "Type": "Research / primary",
                "Link": "gmsworldwide.com/domestic-services · Tracxn company profile",
            },
            {
                "What it supports": "Fuel surcharge range 5–12%",
                "Source": "Professional Courier Charges 2026 — ClickPost",
                "Type": "Industry pricing",
                "Link": "clickpost.ai/blog/professional-courier-charges",
            },
        ]
        st.dataframe(
            pd.DataFrame(sources),
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            "All rate figures are composite averages from published commercial rate cards and "
            "industry research as of 2026. Actual rates vary by weight slab, carrier, season, "
            "fuel surcharge, and GST. Figures used in revenue projections are mid-range estimates."
        )





