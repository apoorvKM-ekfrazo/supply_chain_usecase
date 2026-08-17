"""
ui/manifest_triage.py  —  Delivery Manifest Triage tab.
See inline comments for architecture decisions.
"""

import re, time, os, hashlib
import requests
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import bharataddress
from odoo_connector import fetch_odoo_manifest, test_connection

ROUTABLE    = "routable"
APPROXIMATE = "approximate"
BLOCKED     = "blocked"

BUCKET_LABELS = {
    ROUTABLE:    "✅ Routable",
    APPROXIMATE: "🟡 Approximate",
    BLOCKED:     "🔴 Blocked",
}
BUCKET_COLORS = {
    ROUTABLE: "#2e7d32", APPROXIMATE: "#e65100", BLOCKED: "#c62828",
}

INDIA_LAT  = (6.5, 37.5)
INDIA_LNG  = (68.0, 97.5)
LAT_ALIASES  = {"lat","latitude","y","lat_deg","delivery_lat","stop_lat"}
LNG_ALIASES  = {"lng","lon","longitude","long","x","lng_deg",
                "delivery_lng","stop_lng","stop_lon"}
ADDR_ALIASES = {"address","addr","delivery_address","stop_address",
                "full_address","location","destination","consignee_address"}

# ── Corridor → DC mapping (PIN prefix lookup) ─────────────────────────────────
# 20 PIN prefixes covering 5 intercity corridors from Bengaluru + local.
# bharataddress.parse() extracts the PIN; we look up the first 3 digits here.
CORRIDOR_MAP = {
    # Delhi NCR
    "110": ("Delhi NCR",    "Ghaziabad DC"),
    "111": ("Delhi NCR",    "Ghaziabad DC"),
    "120": ("Delhi NCR",    "Ghaziabad DC"),
    "121": ("Delhi NCR",    "Ghaziabad DC"),
    "122": ("Delhi NCR",    "Ghaziabad DC"),
    "201": ("Delhi NCR",    "Ghaziabad DC"),
    "202": ("Delhi NCR",    "Ghaziabad DC"),
    # Mumbai
    "400": ("Mumbai",       "Bhiwandi DC"),
    "401": ("Mumbai",       "Bhiwandi DC"),
    "402": ("Mumbai",       "Bhiwandi DC"),
    "421": ("Mumbai",       "Bhiwandi DC"),
    # Hyderabad
    "500": ("Hyderabad",    "Hyderabad DC"),
    "501": ("Hyderabad",    "Hyderabad DC"),
    "502": ("Hyderabad",    "Hyderabad DC"),
    # Chennai
    "600": ("Chennai",      "Chennai DC"),
    "601": ("Chennai",      "Chennai DC"),
    "602": ("Chennai",      "Chennai DC"),
    # Kerala
    "680": ("Kerala",       "Kochi DC"),
    "682": ("Kerala",       "Kochi DC"),
    "683": ("Kerala",       "Kochi DC"),
    "695": ("Kerala",       "Kochi DC"),
    "673": ("Kerala",       "Kochi DC"),
    # Bengaluru local
    "560": ("Bengaluru Local", "Central Depot"),
    "562": ("Bengaluru Local", "Central Depot"),
    "563": ("Bengaluru Local", "Central Depot"),
}


def _get_corridor(pin_str) -> tuple:
    """Return (corridor_name, hub_dc) for a PIN, or ('Other', '—') if unknown."""
    if not pin_str or str(pin_str) == "None":
        return ("Unassigned", "—")
    prefix = str(pin_str)[:3]
    return CORRIDOR_MAP.get(prefix, ("Other", "—"))


# ── Demo manifest — GMS-style intercity shipment batch ─────────────────────────
# Covers 5 corridors (Delhi NCR, Mumbai, Hyderabad, Kerala, Bengaluru local)
# plus one genuinely blocked row. Realistic weight distribution.
DEMO_MANIFEST = pd.DataFrame([
    # Delhi NCR corridor — 3 consignments, total 148 kg
    {"consignment_id":"GMS2026001","address":"Lajpat Nagar New Delhi 110024",
     "lat":None,"lng":None,"weight_kg":25.0},
    {"consignment_id":"GMS2026002","address":"Gurugram Sector 44 122003",
     "lat":None,"lng":None,"weight_kg":34.0},
    {"consignment_id":"GMS2026003","address":"Pratap Vihar Ghaziabad 201009",
     "lat":None,"lng":None,"weight_kg":89.0},
    # Mumbai corridor — 2 consignments, total 107 kg
    {"consignment_id":"GMS2026004","address":"Andheri East Mumbai 400069",
     "lat":None,"lng":None,"weight_kg":45.0},
    {"consignment_id":"GMS2026005","address":"Thane West 400601",
     "lat":None,"lng":None,"weight_kg":62.0},
    # Hyderabad corridor — 2 consignments, total 59 kg
    {"consignment_id":"GMS2026006","address":"Madhapur Hyderabad 500081",
     "lat":None,"lng":None,"weight_kg":31.0},
    {"consignment_id":"GMS2026007","address":"Secunderabad 500003",
     "lat":None,"lng":None,"weight_kg":28.0},
    # Kerala corridor — 1 consignment, 50 kg
    {"consignment_id":"GMS2026008","address":"Kakkanad Kochi Kerala 682030",
     "lat":None,"lng":None,"weight_kg":50.0},
    # Bengaluru local — already at DC, hand off to intracity
    {"consignment_id":"GMS2026009","address":"560034",
     "lat":None,"lng":None,"weight_kg":12.0},
    {"consignment_id":"GMS2026010","address":"HSR Layout Bengaluru 560102",
     "lat":12.91354,"lng":77.64837,"weight_kg":8.0},
    # Genuinely incomplete — PIN only, no street detail
    {"consignment_id":"GMS2026011","address":"682030",
     "lat":None,"lng":None,"weight_kg":2.1},
])


_WEIGHT_ALIASES = {"weight_kg","weight","wt","kg","package_weight","parcel_weight"}

def _detect_columns(df):
    cols_lower = {c.lower().strip(): c for c in df.columns}
    addr_col   = next((cols_lower[k] for k in ADDR_ALIASES   if k in cols_lower), None)
    lat_col    = next((cols_lower[k] for k in LAT_ALIASES    if k in cols_lower), None)
    lng_col    = next((cols_lower[k] for k in LNG_ALIASES    if k in cols_lower), None)
    weight_col = next((cols_lower[k] for k in _WEIGHT_ALIASES if k in cols_lower), None)
    return addr_col, lat_col, lng_col, weight_col


def _has_valid_coords(row, lat_col, lng_col):
    if lat_col is None or lng_col is None:
        return False
    try:
        lat, lng = float(row.get(lat_col)), float(row.get(lng_col))
        return (INDIA_LAT[0]<=lat<=INDIA_LAT[1] and INDIA_LNG[0]<=lng<=INDIA_LNG[1])
    except (TypeError, ValueError):
        return False


def _blocked(reason):
    return {"bucket":BLOCKED,"lat":None,"lng":None,
            "resolved_by":reason,"confidence":0.0,
            "pin_found":None,"locality":None}


def _triage_address(address_str, olamaps_key=""):
    text = str(address_str).strip()
    if not text or text.lower() in ("nan","none",""):
        return _blocked("Empty address")

    # Stage 2: bharataddress.parse — offline, no API cost
    try:
        parsed = bharataddress.parse(text)
        if parsed.latitude and parsed.longitude:
            n = len(parsed.components_found)
            c = parsed.confidence or 0.0
            pin = parsed.pincode
            locality = parsed.locality or parsed.sub_locality or parsed.city

            if c >= 0.75 and n >= 3:
                return {"bucket":ROUTABLE,"lat":parsed.latitude,"lng":parsed.longitude,
                        "resolved_by":f"Address enrichment ({', '.join(parsed.components_found)})",
                        "confidence":c,"pin_found":pin,"locality":locality}
            elif pin:
                return {"bucket":APPROXIMATE,"lat":parsed.latitude,"lng":parsed.longitude,
                        "resolved_by":f"PIN {pin} centroid (bharataddress offline)",
                        "confidence":c,"pin_found":pin,
                        "locality":locality or parsed.district or parsed.city}
            else:
                return {"bucket":APPROXIMATE,"lat":parsed.latitude,"lng":parsed.longitude,
                        "resolved_by":f"City-level match ({parsed.city})",
                        "confidence":c,"pin_found":None,"locality":parsed.city}
    except Exception:
        pass

    # Stage 3: Ola Maps fallback (only when bharataddress finds nothing)
    # Pre-check: skip the API call if the text is clearly not an address.
    # Strings like "customer refused" or "no address" return valid-looking
    # Indian coordinates from Ola Maps (a default city centroid) which is
    # worse than Blocked because it silently puts a stop in the wrong place.
    _GARBAGE = {"refused","no address","not available","n/a","nil",
                "none provided","unknown","not given","test","na","xxx"}
    _lower = text.lower()
    _is_garbage = (
        any(g in _lower for g in _GARBAGE) or
        len(text.strip()) < 8 or
        (not any(c.isdigit() for c in text) and len(text) < 15)
    )
    if olamaps_key and not _is_garbage:
        try:
            resp = requests.get(
                "https://api.olamaps.io/places/v1/geocode",
                params={"address":text,"language":"English","api_key":olamaps_key},
                timeout=8,
            )
            if resp.status_code == 200:
                results = resp.json().get("geocodingResults",[])
                if results:
                    loc = results[0].get("geometry",{}).get("location",{})
                    lat, lng = loc.get("lat"), loc.get("lng")
                    if lat and lng:
                        return {"bucket":APPROXIMATE,"lat":float(lat),"lng":float(lng),
                                "resolved_by":"Ola Maps geocoding (full address)",
                                "confidence":0.6,"pin_found":None,
                                "locality":results[0].get("name","")}
        except Exception:
            pass

    return _blocked("No PIN found and geocoding failed")


def _triage_map(result_df, addr_col, lat_col, lng_col):
    fig = go.Figure()
    for bucket, label in BUCKET_LABELS.items():
        sub  = result_df[result_df["_triage_bucket"]==bucket]
        lats = pd.to_numeric(sub[lat_col], errors="coerce")
        lngs = pd.to_numeric(sub[lng_col], errors="coerce")
        v    = lats.notna() & lngs.notna()
        if not v.any():
            continue
        hover = sub[addr_col].astype(str) + "<br>" + sub["_resolved_by"].astype(str)
        fig.add_trace(go.Scattermapbox(
            lat=lats[v], lon=lngs[v], mode="markers",
            marker=dict(size=11,color=BUCKET_COLORS[bucket]),
            name=label, text=hover[v],
            hovertemplate="%{text}<extra></extra>",
        ))
    fig.update_layout(
        mapbox=dict(style="carto-positron",center=dict(lat=12.97,lon=77.59),zoom=10),
        margin=dict(l=0,r=0,t=0,b=0), height=380,
        legend=dict(orientation="h",y=1.02),
    )
    return fig


def render_manifest_triage():
    """Delivery Manifest Triage — call inside with main_tabs[2]: in app.py."""

    olamaps_key = os.environ.get("OLAMAPS_API_KEY","").strip()

    st.markdown(
        "<div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;"
        "padding:14px 18px;margin-bottom:18px;font-size:13px;color:#374151'>"
        "Upload a delivery manifest to classify every row before it enters the "
        "route optimizer. Each row is triaged into: "
        "<b>✅ Routable</b> (precise coordinates), "
        "<b>🟡 Approximate</b> (PIN centroid — driver confirms on arrival), or "
        "<b>🔴 Blocked</b> (address enrichment required). "
        "Catching bad addresses <i>before dispatch</i> eliminates RTO risk and "
        "replaces reactive NDR management with proactive pre-dispatch enrichment."
        "</div>",
        unsafe_allow_html=True,
    )

    if not olamaps_key:
        st.caption(
            "ℹ️ Ola Maps fallback is inactive — "
            "add OLAMAPS_API_KEY to .env to enable Stage 3 geocoding."
        )

    st.markdown("#### 📂 Upload Delivery Manifest")

    # Example format guide — same pattern as Route Optimizer onboarding
    with st.expander("📋  What does the expected data format look like?", expanded=False):
        st.markdown(
            "Your manifest needs **at minimum** an address column. "
            "A weight column is used for corridor consolidation in Tab 2. "
            "Lat/lng columns are optional — missing ones are resolved by the triage engine."
        )
        col_info = {
            "consignment_id": ("Recommended", "Unique ID for each shipment"),
            "address":        ("Required",    "Delivery address — can be partial, messy, or PIN-only"),
            "weight_kg":      ("Recommended", "Package weight in kg — used for intercity vehicle sizing"),
            "lat":            ("Optional",    "Latitude — resolved automatically if missing"),
            "lng":            ("Optional",    "Longitude — resolved automatically if missing"),
        }
        st.dataframe(
            pd.DataFrame([
                {"Column": k, "Status": v[0], "Description": v[1]}
                for k, v in col_info.items()
            ]),
            hide_index=True, use_container_width=True,
        )
        st.markdown("**Sample rows (first 5 from the GMS demo manifest):**")
        st.dataframe(
            DEMO_MANIFEST.head(5)[["consignment_id","address","weight_kg"]],
            hide_index=True, use_container_width=True,
        )
        st.download_button(
            "⬇️  Download CSV Template",
            data=DEMO_MANIFEST[["consignment_id","address","weight_kg","lat","lng"]]
                 .to_csv(index=False).encode("utf-8"),
            file_name="manifest_template.csv",
            mime="text/csv",
        )

        # ── Odoo ERP import ───────────────────────────────────────────────────────────
    odoo_configured = bool(os.environ.get("ODOO_API_KEY") and os.environ.get("ODOO_USERNAME"))

    with st.expander("🔗 Import from Odoo ERP", expanded=False):
        if not odoo_configured:
            st.info("🔌 Odoo connection is not configured for this environment. Use the demo manifest below or upload your own file.")
        else:
            ok, msg = test_connection()
            if ok:
                st.success(f"✅ {msg}")
                col_imp, col_clear = st.columns([2, 1])
                with col_imp:
                    if st.button("📥 Import Live Delivery Orders from Odoo", type="primary", key="odoo_import_btn"):
                        with st.spinner("Fetching delivery orders from Odoo..."):
                            odoo_df = fetch_odoo_manifest()
                        if odoo_df is not None and not odoo_df.empty:
                            st.session_state.odoo_manifest_df = odoo_df
                            st.success(f"✅ Imported {len(odoo_df)} delivery orders from Odoo.")
                            st.rerun()
                        else:
                            st.error("No pending delivery orders found in Odoo.")
                with col_clear:
                    if st.session_state.get("odoo_manifest_df") is not None:
                        if st.button("✕ Clear Odoo Data", key="odoo_clear_btn"):
                            st.session_state.odoo_manifest_df = None
                            st.rerun()

            else:
                st.info(f"🔌 Odoo connection unavailable — credentials may have expired. Use the demo manifest below or upload your own file.")

        if st.session_state.get("odoo_manifest_df") is not None:
            odoo_df_preview = st.session_state.odoo_manifest_df
            st.markdown(f"**{len(odoo_df_preview)} orders loaded from Odoo** — will be used as manifest input.")
            st.dataframe(odoo_df_preview[["consignment_id","customer_name","city","weight_kg","scheduled_date"]].head(5),
                        hide_index=True)
        
    uploaded = st.file_uploader(
        "Drop your manifest CSV or Excel",
        type=["csv","xlsx"], key="triage_upload",
    )

    if uploaded:
        try:
            df = pd.read_excel(uploaded) if uploaded.name.endswith(".xlsx") else pd.read_csv(uploaded)
        except Exception as e:
            st.error(f"Could not read file: {e}")
            return
    else:
        st.caption("No file — showing GMS-style demo manifest with mixed address quality.")
        df = DEMO_MANIFEST.copy()
        if st.session_state.get("odoo_manifest_df") is not None:
            df = st.session_state.odoo_manifest_df.copy()
            st.info(f"📡 Using {len(df)} orders imported from Odoo ERP.")
        else:
            df = DEMO_MANIFEST.copy()

    addr_col, lat_col, lng_col, weight_col = _detect_columns(df)
    ca, cl, cll = st.columns(3)
    with ca:
        addr_col = st.selectbox("Address column",["(none)"]+list(df.columns),
            index=(list(df.columns).index(addr_col)+1) if addr_col else 0, key="t_addr")
        addr_col = None if addr_col=="(none)" else addr_col
    with cl:
        lat_col = st.selectbox("Latitude column (optional)",["(none)"]+list(df.columns),
            index=(list(df.columns).index(lat_col)+1) if lat_col else 0, key="t_lat")
        lat_col = None if lat_col=="(none)" else lat_col
    with cll:
        lng_col = st.selectbox("Longitude column (optional)",["(none)"]+list(df.columns),
            index=(list(df.columns).index(lng_col)+1) if lng_col else 0, key="t_lng")
        lng_col = None if lng_col=="(none)" else lng_col

    if not addr_col:
        st.warning("Select an address column to continue.")
        return

    for k in ["triage_result_df","triage_lat_col","triage_lng_col"]:
        if k not in st.session_state:
            st.session_state[k] = None

    if "odoo_manifest_df" not in st.session_state:
        st.session_state.odoo_manifest_df = None

    if st.button("🔍 Run Manifest Triage", type="primary"):
        result_df = df.copy()
        result_df["_lat_resolved"] = None if lat_col is None else result_df[lat_col].copy()
        result_df["_lng_resolved"] = None if lng_col is None else result_df[lng_col].copy()
        result_df["_triage_bucket"] = None
        result_df["_resolved_by"]   = None
        result_df["_confidence"]    = None
        result_df["_pin_found"]     = None

        prog  = st.progress(0, text="Triaging manifest rows…")
        total = len(result_df)

        for i, (idx, row) in enumerate(result_df.iterrows()):
            prog.progress((i+1)/total, text=f"Row {i+1} of {total}…")

            if _has_valid_coords(row, lat_col, lng_col):
                result_df.at[idx,"_triage_bucket"] = ROUTABLE
                result_df.at[idx,"_resolved_by"]   = "Existing coordinates (input file)"
                result_df.at[idx,"_confidence"]    = 1.0
                result_df.at[idx,"_lat_resolved"]  = float(row[lat_col])
                result_df.at[idx,"_lng_resolved"]  = float(row[lng_col])
                continue

            t = _triage_address(str(row.get(addr_col,"")), olamaps_key)
            result_df.at[idx,"_triage_bucket"] = t["bucket"]
            result_df.at[idx,"_resolved_by"]   = t["resolved_by"]
            result_df.at[idx,"_confidence"]    = t["confidence"]
            result_df.at[idx,"_pin_found"]     = t["pin_found"]
            if t["lat"] is not None:
                result_df.at[idx,"_lat_resolved"] = t["lat"]
                result_df.at[idx,"_lng_resolved"] = t["lng"]
            if olamaps_key:
                time.sleep(0.2)

        prog.empty()
        st.session_state.triage_result_df = result_df
        st.session_state.triage_lat_col   = "_lat_resolved"
        st.session_state.triage_lng_col   = "_lng_resolved"
        st.rerun()

    if st.session_state.triage_result_df is not None:
        result_df = st.session_state.triage_result_df
        lat_d     = st.session_state.triage_lat_col
        lng_d     = st.session_state.triage_lng_col

        counts       = result_df["_triage_bucket"].value_counts().to_dict()
        n_routable   = counts.get(ROUTABLE, 0)
        n_approx     = counts.get(APPROXIMATE, 0)
        n_blocked    = counts.get(BLOCKED, 0)
        total        = len(result_df)

        st.markdown("#### Triage Summary")
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Total consignments", total)
        c2.metric("✅ Routable", n_routable,
                  delta=f"{n_routable/total*100:.0f}% of manifest", delta_color="off")
        c3.metric("🟡 Approximate", n_approx,
                  delta=f"{n_approx/total*100:.0f}% — PIN centroid", delta_color="off")
        c4.metric("🔴 Blocked", n_blocked,
                  delta="RTO risk if dispatched",
                  delta_color="inverse" if n_blocked>0 else "off")

        if n_blocked > 0:
            st.markdown(
                f"<div style='background:#fef2f2;border-left:4px solid #c62828;"
                f"border-radius:6px;padding:10px 14px;font-size:13px;color:#7f1d1d;"
                f"margin-bottom:8px'>"
                f"⚠️ <b>{n_blocked} consignment(s) are Blocked.</b> "
                f"Dispatching without enrichment risks Return to Origin (RTO). "
                f"At ₹100 avg RTO cost: <b>₹{n_blocked*100:,} preventable loss</b> per batch."
                f"</div>", unsafe_allow_html=True,
            )

        if n_approx > 0:
            st.markdown(
                f"<div style='background:#fff3e0;border-left:4px solid #e65100;"
                f"border-radius:6px;padding:10px 14px;font-size:13px;color:#7c2d12;"
                f"margin-bottom:8px'>"
                f"🟡 <b>{n_approx} consignment(s) routed to PIN centroids.</b> "
                f"Industry-standard practice: route to postal zone hub, "
                f"driver calls customer for final 500m. Same workflow used by Delhivery and Ecom Express."
                f"</div>", unsafe_allow_html=True,
            )

        # ── Corridor grouping ─────────────────────────────────────────────────
        # Rows that had existing coordinates skip bharataddress.parse() entirely,
        # so _pin_found stays None and corridor assignment fails.
        # Fix: extract 6-digit PIN from address text via regex for those rows.
        import re as _re
        _PIN_RE = _re.compile(r'\b[1-9]\d{5}\b')
        for _idx, _row in result_df.iterrows():
            if not result_df.at[_idx, "_pin_found"]:
                _m = _PIN_RE.search(str(_row.get(addr_col, "")))
                if _m:
                    result_df.at[_idx, "_pin_found"] = _m.group(0)
        # Assign each row a corridor based on the PIN bharataddress extracted.
        result_df["_corridor"] = result_df["_pin_found"].apply(
            lambda p: _get_corridor(p)[0]
        )
        result_df["_hub"] = result_df["_pin_found"].apply(
            lambda p: _get_corridor(p)[1]
        )

        st.markdown("---")
        st.markdown("#### 🗺️ Corridor Grouping")
        st.caption(
            "Consignments grouped by destination corridor based on resolved PIN codes. "
            "Bengaluru Local rows go directly to intracity dispatch. "
            "All other corridors pass to the Intercity Load Optimiser."
        )

        # Build corridor summary
        wt_col_name = weight_col if weight_col and weight_col in result_df.columns else None
        corridor_rows = []
        for corridor, grp in result_df.groupby("_corridor"):
            hub        = grp["_hub"].iloc[0]
            count      = len(grp)
            total_wt   = (
                grp[wt_col_name].apply(pd.to_numeric, errors="coerce").sum()
                if wt_col_name else 0.0
            )
            routable_n = (grp["_triage_bucket"] == ROUTABLE).sum()
            approx_n   = (grp["_triage_bucket"] == APPROXIMATE).sum()
            blocked_n  = (grp["_triage_bucket"] == BLOCKED).sum()
            ready_n    = routable_n + approx_n

            if corridor == "Bengaluru Local":
                next_step = "→ Intracity dispatch"
            elif corridor in ("Unassigned", "Other"):
                next_step = "⚠️ Manual routing"
            else:
                next_step = "→ Intercity Load Optimiser"

            corridor_rows.append({
                "Corridor":        corridor,
                "Distribution Hub": hub,
                "Consignments":    count,
                "Total weight (kg)": f"{total_wt:.1f}" if total_wt else "—",
                "Routable":        routable_n,
                "Approximate":     approx_n,
                "Blocked":         blocked_n,
                "Next step":       next_step,
            })

        corridor_df = pd.DataFrame(corridor_rows).sort_values(
            "Consignments", ascending=False
        )
        st.dataframe(corridor_df, hide_index=True, use_container_width=True)

        # Handoff callout
        intercity_corridors = [
            r["Corridor"] for _, r in corridor_df.iterrows()
            if r["Next step"] == "→ Intercity Load Optimiser"
        ]
        local_count = int(
            corridor_df[corridor_df["Corridor"] == "Bengaluru Local"]["Consignments"].sum()
        ) if "Bengaluru Local" in corridor_df["Corridor"].values else 0

        if intercity_corridors:
            st.markdown(
                f"<div style='background:#e3f2fd;border-left:4px solid #1565C0;"
                f"border-radius:6px;padding:12px 16px;font-size:13px;color:#0d47a1;"
                f"margin-top:8px'>"
                f"📦 <b>{len(intercity_corridors)} corridor(s) ready for intercity planning:</b> "
                f"{', '.join(intercity_corridors)}. "
                f"Pass to the <b>Intercity Load Optimiser</b> to size vehicles "
                f"and check spare capacity for co-loading."
                + (
                    f"<br>🏙️ <b>{local_count} consignment(s) are Bengaluru Local</b> — "
                    f"hand off directly to intracity dispatch."
                    if local_count else ""
                )
                + "</div>",
                unsafe_allow_html=True,
            )

        st.markdown("---")
        st.plotly_chart(_triage_map(result_df, addr_col, lat_d, lng_d),
                        use_container_width=True)
        st.caption("✅ Green = Routable · 🟡 Orange = Approximate (PIN centroid) · 🔴 Red = Blocked")

        st.markdown("#### Row-Level Detail")
        show_cols = [addr_col,"_triage_bucket","_resolved_by","_confidence",
                     "_pin_found", lat_d, lng_d]
        show_cols = [c for c in show_cols if c in result_df.columns]
        disp = result_df[show_cols].copy()
        disp.columns = ["Address","Bucket","Resolved By","Confidence",
                        "PIN","Lat","Lng"][:len(show_cols)]
        disp["Bucket"]     = disp["Bucket"].map(BUCKET_LABELS)
        disp["Confidence"] = disp["Confidence"].apply(
            lambda x: f"{x:.0%}" if pd.notna(x) and x!="" else "—")
        st.dataframe(disp, use_container_width=True, hide_index=True)

        st.markdown("#### Download Enriched Manifest")
        out = result_df.drop(columns=["_lat_resolved","_lng_resolved"],errors="ignore")
        out = out.rename(columns={"_triage_bucket":"triage_bucket",
                                   "_resolved_by":"resolved_by",
                                   "_pin_found":"pin_found",
                                   "_confidence":"confidence"})
        st.download_button(
            "⬇️  Download Triaged Manifest CSV",
            data=out.to_csv(index=False).encode("utf-8"),
            file_name="manifest_triaged.csv", mime="text/csv",
        )

        if n_routable + n_approx > 0:
            st.info(
                f"✅ {n_routable+n_approx} of {total} consignments have coordinates. "
                "Import the downloaded CSV into **🚚 Route Optimisation** to run the solver."
            )

        if st.button("↺ Clear and triage a new manifest", key="triage_clear"):
            st.session_state.triage_result_df = None
            st.rerun()





