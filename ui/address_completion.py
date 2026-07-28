"""
ui/address_completion.py
------------------------
Address Completion tab — converts incomplete delivery addresses to coordinates.

The problem: clients upload CSVs where addresses are written as free text
("near old bus stand, Kondapur") without lat/lng coordinates. The route
optimizer cannot place these stops on the map without coordinates.

The solution:
  1. Upload CSV with an address column.
  2. System identifies which rows are missing coordinates.
  3. Geocoding calls (Ola Maps API) convert text addresses to lat/lng.
  4. Failures are flagged for manual review.
  5. Completed CSV can be downloaded and used in the Route Optimizer.

Geocoding API: Ola Maps (500k free requests/month, first year free).
Set OLAMAPS_API_KEY in your .env file to enable live geocoding.
Without a key, the module shows the workflow with demo data.

Address parsing note: Shiprocket's open-source NER models
(open-indicbert-indian-address-ner on HuggingFace) can be used to
pre-structure messy addresses before the geocoding API call, improving
hit rate on informal Indian addresses. This is noted here as a Phase 2
enhancement — the current implementation sends addresses directly to Ola Maps.
"""

import os
import time
import requests
import pandas as pd
import streamlit as st
import plotly.graph_objects as go


# ── Config ────────────────────────────────────────────────────────────────────
OLAMAPS_GEOCODE_URL = "https://api.olamaps.io/places/v1/geocode"
LAT_ALIASES  = {"lat", "latitude", "y", "lat_deg", "delivery_lat", "stop_lat"}
LNG_ALIASES  = {"lng", "lon", "longitude", "long", "x", "lng_deg",
                "delivery_lng", "stop_lng", "stop_lon"}
ADDR_ALIASES = {"address", "addr", "delivery_address", "stop_address",
                "full_address", "location", "destination"}

# India bounding box for coordinate validation
INDIA_LAT = (6.5, 37.5)
INDIA_LNG = (68.0, 97.5)


# ── Demo data — shown when no file is uploaded ────────────────────────────────
DEMO_DATA = pd.DataFrame([
    {"stop_id": 1, "zone": "Koramangala",
     "address": "5th Block Koramangala, near Sony World Signal, Bengaluru",
     "lat": None, "lng": None, "weight_kg": 12.0},
    {"stop_id": 2, "zone": "Indiranagar",
     "address": "100 Feet Road, Indiranagar, near Leela Palace",
     "lat": None, "lng": None, "weight_kg": 5.5},
    {"stop_id": 3, "zone": "Whitefield",
     "address": "ITPL Main Road, Whitefield, Bengaluru 560066",
     "lat": 12.9698, "lng": 77.7500, "weight_kg": 8.2},
    {"stop_id": 4, "zone": "Electronic City",
     "address": "Phase 1, Electronic City, Hosur Road",
     "lat": None, "lng": None, "weight_kg": 3.1},
    {"stop_id": 5, "zone": "Marathahalli",
     "address": "Marathahalli Bridge, Outer Ring Road, Bengaluru",
     "lat": 12.9591, "lng": 77.7012, "weight_kg": 15.0},
    {"stop_id": 6, "zone": "JP Nagar",
     "address": "near Arekere Gate, JP Nagar 7th Phase",
     "lat": None, "lng": None, "weight_kg": 6.8},
    {"stop_id": 7, "zone": "Hebbal",
     "address": "Hebbal Flyover area, Bellary Road, Bengaluru",
     "lat": 13.0358, "lng": 77.5970, "weight_kg": 9.3},
])

# Simulated geocode results for demo mode
DEMO_GEOCODED = {
    "5th Block Koramangala, near Sony World Signal, Bengaluru":
        (12.9352, 77.6245),
    "100 Feet Road, Indiranagar, near Leela Palace":
        (12.9784, 77.6408),
    "Phase 1, Electronic City, Hosur Road":
        (12.8406, 77.6770),
    "near Arekere Gate, JP Nagar 7th Phase":
        (12.9102, 77.5836),
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _detect_columns(df: pd.DataFrame):
    """
    Auto-detect address, lat, and lng columns from a DataFrame.
    Returns (addr_col, lat_col, lng_col) — any may be None if not found.
    """
    cols_lower = {c.lower().strip(): c for c in df.columns}
    addr_col = next((cols_lower[k] for k in ADDR_ALIASES if k in cols_lower), None)
    lat_col  = next((cols_lower[k] for k in LAT_ALIASES  if k in cols_lower), None)
    lng_col  = next((cols_lower[k] for k in LNG_ALIASES  if k in cols_lower), None)
    return addr_col, lat_col, lng_col


def _needs_geocoding(row, lat_col, lng_col):
    """True if row is missing valid coordinates."""
    if lat_col is None or lng_col is None:
        return True
    lat = row.get(lat_col)
    lng = row.get(lng_col)
    if pd.isna(lat) or pd.isna(lng):
        return True
    try:
        lat, lng = float(lat), float(lng)
        return not (INDIA_LAT[0] <= lat <= INDIA_LAT[1] and
                    INDIA_LNG[0] <= lng <= INDIA_LNG[1])
    except (ValueError, TypeError):
        return True


def _geocode_ola(address: str, api_key: str):
    """
    Single geocoding call to Ola Maps.
    Returns (lat, lng) on success, (None, None) on failure.
    Rate: conservative 2 req/sec to stay within Ola's fair use.
    """
    try:
        resp = requests.get(
            OLAMAPS_GEOCODE_URL,
            params={"address": address, "language": "English"},
            headers={"X-Request-Id": "ekfrazo-demo",
                     "Authorization": f"Bearer {api_key}"},
            timeout=8,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("geocodingResults"):
                loc = data["geocodingResults"][0]["geometry"]["location"]
                return float(loc["lat"]), float(loc["lng"])
    except Exception:
        pass
    return None, None


def _geocode_demo(address: str):
    """Return pre-computed demo coordinates (no API call)."""
    result = DEMO_GEOCODED.get(address)
    if result:
        return result
    return None, None


def _map_figure(df, lat_col, lng_col, addr_col=None, status_col=None):
    """
    Plot geocoded stops on a Plotly map.
    Green = has valid coordinates. Red = geocoding failed. Orange = not attempted.
    """
    fig = go.Figure()

    colors = {"success": "#2e7d32", "failed": "#c62828", "skipped": "#e65100"}

    for status, color in colors.items():
        if status_col:
            subset = df[df[status_col] == status]
        else:
            subset = df

        if subset.empty:
            continue

        lats = pd.to_numeric(subset[lat_col], errors="coerce")
        lngs = pd.to_numeric(subset[lng_col], errors="coerce")
        valid = lats.notna() & lngs.notna()

        if not valid.any():
            continue

        hover = (subset[addr_col].fillna("—") if addr_col
                 else subset.index.astype(str))

        fig.add_trace(go.Scattermapbox(
            lat=lats[valid], lon=lngs[valid],
            mode="markers",
            marker=dict(size=10, color=color),
            name=status.title(),
            text=hover[valid],
            hovertemplate="%{text}<extra></extra>",
        ))

    fig.update_layout(
        mapbox=dict(style="carto-positron",
                    center=dict(lat=12.97, lon=77.59), zoom=10),
        margin=dict(l=0, r=0, t=0, b=0),
        height=380,
        legend=dict(orientation="h", y=1.02),
    )
    return fig


# ── Main render function ──────────────────────────────────────────────────────

def render_address_completion():
    """
    Address Completion tab — call inside with main_tabs[2]: in app.py.
    (Or whatever tab index you assign.)
    """
    st.markdown(
        "<div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;"
        "padding:14px 18px;margin-bottom:18px;font-size:13px;color:#374151'>"
        "Upload a delivery CSV that contains addresses but is missing latitude/longitude "
        "coordinates. The system identifies incomplete rows and geocodes them using "
        "<b>Ola Maps</b> — converting text like "
        "\"near old bus stand, Kondapur\" into precise coordinates the route optimizer can use."
        "</div>",
        unsafe_allow_html=True,
    )

    api_key = os.environ.get("OLAMAPS_API_KEY", "")
    demo_mode = not bool(api_key)

    if demo_mode:
        st.info(
            "🔑 **Demo mode** — Ola Maps API key not found in environment. "
            "Add `OLAMAPS_API_KEY=your_key` to your `.env` file to enable live geocoding. "
            "Ola Maps offers **500,000 free requests/month** and the first year is free. "
            "The workflow below uses pre-computed demo results.",
            icon="ℹ️",
        )

    # ── File upload ───────────────────────────────────────────────────────────
    st.markdown("#### 📂 Upload Delivery Data")

    uploaded = st.file_uploader(
        "Drop your delivery CSV or Excel file",
        type=["csv", "xlsx"],
        key="addr_upload",
        help="Must have an address column. Lat/lng columns optional — missing ones will be geocoded.",
    )

    if uploaded:
        try:
            if uploaded.name.endswith(".xlsx"):
                df = pd.read_excel(uploaded)
            else:
                df = pd.read_csv(uploaded)
        except Exception as e:
            st.error(f"Could not read file: {e}")
            return
    else:
        st.caption("No file uploaded — showing Bengaluru demo dataset.")
        df = DEMO_DATA.copy()

    # ── Column detection ──────────────────────────────────────────────────────
    addr_col, lat_col, lng_col = _detect_columns(df)

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        addr_col = st.selectbox(
            "Address column",
            options=["(none)"] + list(df.columns),
            index=(list(df.columns).index(addr_col) + 1) if addr_col else 0,
            key="addr_col_sel",
        )
        addr_col = None if addr_col == "(none)" else addr_col
    with col_b:
        lat_col = st.selectbox(
            "Latitude column (if exists)",
            options=["(none)"] + list(df.columns),
            index=(list(df.columns).index(lat_col) + 1) if lat_col else 0,
            key="lat_col_sel",
        )
        lat_col = None if lat_col == "(none)" else lat_col
    with col_c:
        lng_col = st.selectbox(
            "Longitude column (if exists)",
            options=["(none)"] + list(df.columns),
            index=(list(df.columns).index(lng_col) + 1) if lng_col else 0,
            key="lng_col_sel",
        )
        lng_col = None if lng_col == "(none)" else lng_col

    if addr_col is None:
        st.warning("Select an address column to continue.")
        return

    # ── Summary cards ─────────────────────────────────────────────────────────
    needs_geocoding = [
        i for i, row in df.iterrows()
        if _needs_geocoding(row, lat_col, lng_col)
    ]
    already_has = len(df) - len(needs_geocoding)

    s1, s2, s3 = st.columns(3)
    s1.metric("Total stops", len(df))
    s2.metric("Already have coordinates", already_has,
              delta="no geocoding needed", delta_color="off")
    s3.metric("Need geocoding", len(needs_geocoding),
              delta="addresses to resolve",
              delta_color="inverse" if len(needs_geocoding) > 0 else "off")

    if len(needs_geocoding) == 0:
        st.success("✅ All stops already have valid coordinates. No geocoding needed.")
        _show_map_and_download(df, addr_col, lat_col, lng_col)
        return

    # ── Preview incomplete addresses ──────────────────────────────────────────
    st.markdown("#### 🔍 Addresses Needing Geocoding")

    preview_rows = df.iloc[needs_geocoding[:10]][[addr_col]].copy()
    preview_rows.index = range(1, len(preview_rows) + 1)
    preview_rows.columns = ["Address"]
    st.dataframe(preview_rows, use_container_width=True)

    if len(needs_geocoding) > 10:
        st.caption(f"Showing first 10 of {len(needs_geocoding)} addresses needing geocoding.")

    st.markdown("---")

    # ── Geocoding action ──────────────────────────────────────────────────────
    st.markdown("#### 🌐 Run Geocoding")

    if demo_mode:
        btn_label = "🔮 Run Demo Geocoding (simulated)"
        btn_help  = "Uses pre-computed coordinates for the demo addresses. Real geocoding requires OLAMAPS_API_KEY."
    else:
        btn_label = f"🌐 Geocode {len(needs_geocoding)} Addresses with Ola Maps"
        btn_help  = "Live geocoding via Ola Maps API. Approximately 2 requests/sec to stay within rate limits."

    if "geocoding_done" not in st.session_state:
        st.session_state.geocoding_done = False
    if "geocoding_result_df" not in st.session_state:
        st.session_state.geocoding_result_df = None

    if st.button(btn_label, type="primary", help=btn_help):
        result_df = df.copy()

        # Ensure lat/lng columns exist
        if lat_col is None:
            result_df["lat"] = None
            lat_col_out = "lat"
        else:
            lat_col_out = lat_col
        if lng_col is None:
            result_df["lng"] = None
            lng_col_out = "lng"
        else:
            lng_col_out = lng_col

        result_df["_geocode_status"] = "skipped"
        for i, row in df.iterrows():
            if not _needs_geocoding(row, lat_col, lng_col):
                result_df.at[i, "_geocode_status"] = "success"

        success_count = 0
        fail_count    = 0

        prog = st.progress(0, text="Geocoding addresses...")
        total = len(needs_geocoding)

        for step, idx in enumerate(needs_geocoding):
            addr = str(df.at[idx, addr_col])
            prog.progress((step + 1) / total,
                          text=f"Geocoding {step+1}/{total}: {addr[:50]}...")

            if demo_mode:
                lat, lng = _geocode_demo(addr)
                time.sleep(0.1)  # simulate API call
            else:
                lat, lng = _geocode_ola(addr, api_key)
                time.sleep(0.5)  # respect rate limits

            if lat is not None and lng is not None:
                result_df.at[idx, lat_col_out] = lat
                result_df.at[idx, lng_col_out] = lng
                result_df.at[idx, "_geocode_status"] = "success"
                success_count += 1
            else:
                result_df.at[idx, "_geocode_status"] = "failed"
                fail_count += 1

        prog.empty()
        st.session_state.geocoding_result_df = result_df
        st.session_state.geocoding_lat_col   = lat_col_out
        st.session_state.geocoding_lng_col   = lng_col_out
        st.session_state.geocoding_done      = True
        st.session_state.geocoding_success   = success_count
        st.session_state.geocoding_fail      = fail_count
        st.rerun()

    # ── Show results ──────────────────────────────────────────────────────────
    if st.session_state.geocoding_done and st.session_state.geocoding_result_df is not None:
        result_df   = st.session_state.geocoding_result_df
        lat_col_out = st.session_state.geocoding_lat_col
        lng_col_out = st.session_state.geocoding_lng_col
        success     = st.session_state.geocoding_success
        fail        = st.session_state.geocoding_fail

        r1, r2, r3 = st.columns(3)
        r1.metric("Successfully geocoded", success,
                  delta="coordinates resolved", delta_color="off")
        r2.metric("Failed to geocode", fail,
                  delta="manual review needed" if fail > 0 else "none",
                  delta_color="inverse" if fail > 0 else "off")
        r3.metric("Already had coordinates", already_has,
                  delta="unchanged", delta_color="off")

        if fail > 0:
            failed_rows = result_df[result_df["_geocode_status"] == "failed"][[addr_col]]
            failed_rows.columns = ["Address — could not geocode"]
            st.warning(
                f"⚠️ {fail} address(es) could not be resolved. "
                "These rows need manual coordinate entry before use in the route optimizer."
            )
            st.dataframe(failed_rows, use_container_width=True)

        st.markdown("#### 🗺️ Geocoded Stops")
        fig_map = _map_figure(result_df, lat_col_out, lng_col_out,
                              addr_col=addr_col, status_col="_geocode_status")
        st.plotly_chart(fig_map, use_container_width=True)
        st.caption("🟢 Green = geocoded successfully · 🔴 Red = failed · 🟠 Orange = not attempted")

        # Download
        st.markdown("#### ⬇️ Download Completed CSV")
        output_df = result_df.drop(columns=["_geocode_status"], errors="ignore")
        csv_bytes = output_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="⬇️  Download CSV with Coordinates",
            data=csv_bytes,
            file_name="deliveries_geocoded.csv",
            mime="text/csv",
            help="Import this file into the Route Optimizer.",
        )

        if success > 0:
            st.info(
                "✅ Download the completed CSV above. "
                "Upload it to the **🚚 Route Optimisation** tab to run the solver "
                "with the resolved stop coordinates."
            )

        if st.button("↺ Clear and geocode a different file", key="addr_clear"):
            st.session_state.geocoding_done       = False
            st.session_state.geocoding_result_df  = None
            st.rerun()


def _show_map_and_download(df, addr_col, lat_col, lng_col):
    """Show map and download when all stops already have coordinates."""
    if lat_col and lng_col:
        fig = _map_figure(df, lat_col, lng_col, addr_col=addr_col)
        st.plotly_chart(fig, use_container_width=True)

    csv_bytes = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️  Download CSV",
        data=csv_bytes,
        file_name="deliveries_complete.csv",
        mime="text/csv",
    )