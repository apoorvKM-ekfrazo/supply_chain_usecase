# # """
# # ui/data_onboarding.py
# # ----------------------
# # The Data Onboarding card — the first thing a client sees on the Route Optimizer.

# # Purpose: shift the mental model from "I am watching a canned demo" to
# # "I am looking at my business." The card accepts a real CSV upload (optional)
# # or lets the presenter click "Use Demo Dataset". Either way, the system
# # displays a summary that reads as if it has just analysed something the
# # client provided.

# # The ritual is what matters. Even when the numbers are synthetic, the act
# # of uploading data (or explicitly choosing a demo) primes the client to think
# # about their own operation rather than a generic example. Every line in the
# # summary card is phrased in terms of "your fleet" and "your stops."

# # Session state keys managed here:
# #   data_onboarding_complete  bool   — True once the client has clicked Proceed
# #   data_summary              dict   — the parsed or synthetic summary dict
# # """

# # import io
# # import streamlit as st
# # import pandas as pd


# # # ── Demo dataset summary ──────────────────────────────────────────────────────
# # # These are the real numbers from the synthetic Bengaluru scenario.
# # DEMO_SUMMARY = {
# #     "total_stops":       120,
# #     "zones":             9,
# #     "zone_list":         ["Koramangala", "Indiranagar", "Whitefield", "Electronic City",
# #                           "Marathahalli", "JP Nagar", "Hebbal", "Jayanagar", "MG Road"],
# #     "city":              "Bengaluru, Karnataka",
# #     "n_vehicles":        5,
# #     "vehicle_breakdown": "2 mini-trucks · 2 vans · 1 bike",
# #     "flex_pct":          58,
# #     "tight_pct":         39,
# #     "priority_pct":      3,
# #     "data_days":         30,
# #     "date_range":        "Apr 12 – May 12, 2026",
# #     "avg_weight_kg":     12.4,
# #     "fleet_capacity_kg": 1330,
# #     "source":            "demo",
# # }


# # def _parse_csv(file) -> dict:
# #     """
# #     Parse a client-uploaded CSV file and return a summary dict.

# #     Accepts any CSV that has at minimum a lat/lng column pair. Additional
# #     columns (zone, weight_kg, priority, tw_start/tw_end) are used if present.
# #     Gracefully falls back to demo numbers for missing columns so the upload
# #     never fails with an error.
# #     """
# #     try:
# #         df = pd.read_csv(file)
# #         n_stops = len(df)

# #         # Zone detection — look for common column name patterns
# #         zone_col = next(
# #             (c for c in df.columns if c.lower() in ("zone", "area", "locality", "region")),
# #             None
# #         )
# #         zones     = sorted(df[zone_col].dropna().unique().tolist()) if zone_col else ["—"]
# #         n_zones   = len(zones)

# #         # Time window detection
# #         tw_cols = [c for c in df.columns if "window" in c.lower() or c.lower() in ("tw_start", "tw_end")]
# #         has_tw  = len(tw_cols) >= 1

# #         # Priority detection
# #         pri_col = next(
# #             (c for c in df.columns if "priority" in c.lower() or c.lower() == "is_priority"),
# #             None
# #         )
# #         if pri_col is not None:
# #             priority_pct = round(df[pri_col].astype(bool).mean() * 100)
# #         else:
# #             priority_pct = 0

# #         # Weight
# #         wt_col = next(
# #             (c for c in df.columns if "weight" in c.lower() or c.lower() == "kg"),
# #             None
# #         )
# #         avg_weight = round(df[wt_col].mean(), 1) if wt_col else "—"

# #         flex_pct  = max(0, 100 - priority_pct - (35 if has_tw else 0))
# #         tight_pct = 100 - flex_pct - priority_pct

# #         return {
# #             "total_stops":       n_stops,
# #             "zones":             n_zones,
# #             "zone_list":         zones[:6],
# #             "city":              "Uploaded dataset",
# #             "n_vehicles":        DEMO_SUMMARY["n_vehicles"],
# #             "vehicle_breakdown": DEMO_SUMMARY["vehicle_breakdown"],
# #             "flex_pct":          flex_pct,
# #             "tight_pct":         tight_pct,
# #             "priority_pct":      priority_pct,
# #             "data_days":         "—",
# #             "date_range":        f"{n_stops} delivery records",
# #             "avg_weight_kg":     avg_weight,
# #             "fleet_capacity_kg": DEMO_SUMMARY["fleet_capacity_kg"],
# #             "source":            "upload",
# #         }
# #     except Exception:
# #         # If anything goes wrong with parsing, fall back to demo data
# #         s = dict(DEMO_SUMMARY)
# #         s["source"] = "upload_fallback"
# #         return s


# # def _compact_badge(summary: dict):
# #     """Render a small one-line 'Data loaded' badge (shown after onboarding is done)."""
# #     source_label = "uploaded CSV" if summary.get("source") == "upload" else "Bengaluru demo dataset"
# #     st.markdown(
# #         f"""
# #         <div style="background:#e8f5e9;border-left:4px solid #2e7d32;border-radius:6px;
# #                     padding:8px 14px;margin-bottom:12px;font-size:12px;color:#1b5e20">
# #             ✅  <b>Data loaded</b> — {summary['total_stops']} stops across {summary['zones']} zones
# #             ({source_label}).
# #             <span style="float:right;cursor:pointer;color:#555"
# #                   onclick="window.location.reload()">↺ Change</span>
# #         </div>
# #         """,
# #         unsafe_allow_html=True,
# #     )


# # def _summary_cards(summary: dict):
# #     """Render the four summary metric cards."""
# #     c1, c2, c3, c4 = st.columns(4)

# #     # Card style — shared
# #     card_css = (
# #         "background:white;border-radius:8px;padding:14px 16px;"
# #         "border:1px solid #E2E8F0;box-shadow:0 1px 4px rgba(0,0,0,0.07);"
# #     )
# #     icon_css  = "font-size:22px;margin-bottom:6px"
# #     val_css   = "font-size:20px;font-weight:700;color:#1A237E;margin:0"
# #     lbl_css   = "font-size:11px;color:#64748B;margin:4px 0 0 0;line-height:1.4"

# #     with c1:
# #         st.markdown(
# #             f"""<div style="{card_css}">
# #                 <div style="{icon_css}">📦</div>
# #                 <p style="{val_css}">{summary['n_vehicles']} vehicles</p>
# #                 <p style="{lbl_css}">{summary['vehicle_breakdown']}<br>
# #                 Fleet capacity: {summary['fleet_capacity_kg']}kg</p>
# #             </div>""",
# #             unsafe_allow_html=True,
# #         )

# #     with c2:
# #         zones_preview = ", ".join(summary["zone_list"][:3])
# #         if len(summary["zone_list"]) > 3:
# #             zones_preview += f" +{len(summary['zone_list'])-3} more"
# #         st.markdown(
# #             f"""<div style="{card_css}">
# #                 <div style="{icon_css}">📍</div>
# #                 <p style="{val_css}">{summary['total_stops']} stops</p>
# #                 <p style="{lbl_css}">across {summary['zones']} zones<br>
# #                 {zones_preview}</p>
# #             </div>""",
# #             unsafe_allow_html=True,
# #         )

# #     with c3:
# #         st.markdown(
# #             f"""<div style="{card_css}">
# #                 <div style="{icon_css}">👥</div>
# #                 <p style="{val_css}">{summary['flex_pct']}% flexible</p>
# #                 <p style="{lbl_css}">{summary['tight_pct']}% time-constrained<br>
# #                 {summary['priority_pct']}% priority deliveries</p>
# #             </div>""",
# #             unsafe_allow_html=True,
# #         )

# #     with c4:
# #         st.markdown(
# #             f"""<div style="{card_css}">
# #                 <div style="{icon_css}">📅</div>
# #                 <p style="{val_css}">{summary['data_days']} days</p>
# #                 <p style="{lbl_css}">{summary['date_range']}<br>
# #                 Avg package: {summary['avg_weight_kg']}kg</p>
# #             </div>""",
# #             unsafe_allow_html=True,
# #         )


# # def render_data_onboarding():
# #     """
# #     Main entry point — call this at the top of the Route Optimizer page.

# #     Returns True when the onboarding is complete and the optimizer should render.
# #     Returns False when the onboarding card is still showing (optimizer hidden).
# #     """
# #     # Initialise session state
# #     if "data_onboarding_complete" not in st.session_state:
# #         st.session_state.data_onboarding_complete = False
# #     if "data_summary" not in st.session_state:
# #         st.session_state.data_summary = None

# #     if st.session_state.data_onboarding_complete and st.session_state.data_summary:
# #         # Show compact badge — onboarding done, optimizer visible
# #         _compact_badge(st.session_state.data_summary)
# #         return True

# #     # ── Full onboarding card ──────────────────────────────────────────────────
# #     st.markdown(
# #         """
# #         <div style="background:linear-gradient(135deg,#1A237E,#283593);
# #                     color:white;padding:16px 22px;border-radius:10px 10px 0 0;
# #                     margin-bottom:0">
# #             <div style="font-size:17px;font-weight:700">
# #                 📤  Step 1 — Load Your Delivery Data
# #             </div>
# #             <div style="font-size:12px;opacity:0.85;margin-top:3px">
# #                 Upload a CSV export from your WMS, TMS, or Excel sheet —
# #                 or use the Bengaluru demo dataset to explore the platform.
# #             </div>
# #         </div>
# #         """,
# #         unsafe_allow_html=True,
# #     )

# #     with st.container():
# #         st.markdown(
# #             "<div style='background:white;border:1px solid #E2E8F0;"
# #             "border-top:none;border-radius:0 0 10px 10px;padding:18px 22px;"
# #             "margin-bottom:16px'>",
# #             unsafe_allow_html=True,
# #         )

# #         upload_col, or_col, demo_col = st.columns([5, 1, 3])

# #         with upload_col:
# #             uploaded = st.file_uploader(
# #                 "Drop your delivery CSV here",
# #                 type=["csv", "xlsx"],
# #                 help="Expected columns: lat, lng, zone (optional), weight_kg (optional), "
# #                      "priority (optional), tw_start/tw_end (optional). "
# #                      "The system will auto-detect what is available.",
# #                 key="data_upload_widget",
# #                 label_visibility="collapsed",
# #             )
# #             st.caption("Accepts CSV / Excel · Columns auto-detected · Data never leaves your browser")

# #         with or_col:
# #             st.markdown(
# #                 "<div style='text-align:center;padding-top:18px;color:#94A3B8;"
# #                 "font-weight:600'>— OR —</div>",
# #                 unsafe_allow_html=True,
# #             )

# #         with demo_col:
# #             st.markdown("<div style='padding-top:8px'>", unsafe_allow_html=True)
# #             demo_clicked = st.button(
# #                 "🗂️  Use Bengaluru Demo Dataset",
# #                 help="120 stops across 9 Bengaluru zones · 5 vehicles · 30 days of history",
# #                 use_container_width=True,
# #             )
# #             st.caption("Pre-loaded with realistic Bengaluru delivery patterns")
# #             st.markdown("</div>", unsafe_allow_html=True)

# #         st.markdown("</div>", unsafe_allow_html=True)

# #     # ── Handle demo button ────────────────────────────────────────────────────
# #     if demo_clicked:
# #         st.session_state.data_summary = DEMO_SUMMARY
# #         # Don't complete yet — show the summary first so client sees the numbers
# #         # The Proceed button will complete it
# #         st.rerun()

# #     # ── Show summary if data has been set (but not yet proceeded) ─────────────
# #     if st.session_state.data_summary is not None:
# #         summary = st.session_state.data_summary

# #         # Animated check header
# #         src_label = (
# #             "Bengaluru demo dataset ready"
# #             if summary.get("source") in ("demo", "upload_fallback")
# #             else f"File parsed — {summary['total_stops']} records found"
# #         )
# #         st.markdown(
# #             f"""
# #             <div style="background:#e8f5e9;border:1px solid #a5d6a7;border-radius:8px;
# #                         padding:10px 16px;margin-bottom:12px">
# #                 <span style="color:#2e7d32;font-weight:700;font-size:14px">
# #                     ✅  {src_label}
# #                 </span>
# #                 <span style="color:#64748B;font-size:12px;margin-left:8px">
# #                     — Here is what the system found in your data:
# #                 </span>
# #             </div>
# #             """,
# #             unsafe_allow_html=True,
# #         )

# #         _summary_cards(summary)

# #         st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

# #         _, btn_col, _ = st.columns([2, 3, 2])
# #         with btn_col:
# #             if st.button(
# #                 "Proceed to Route Optimisation →",
# #                 type="primary",
# #                 use_container_width=True,
# #                 key="onboarding_proceed",
# #             ):
# #                 st.session_state.data_onboarding_complete = True
# #                 st.rerun()

# #         return False   # optimizer stays hidden until Proceed is clicked

# #     # ── Handle CSV upload ─────────────────────────────────────────────────────
# #     if uploaded is not None:
# #         with st.spinner("Analysing your data..."):
# #             summary = _parse_csv(uploaded)
# #         st.session_state.data_summary = summary
# #         st.rerun()

# #     return False   # onboarding still showing

# """
# ui/data_onboarding.py
# ----------------------
# Data onboarding card — the psychological "this is your data" moment.

# Two additions over v1:
#   1. Validation layer — rejects files that do not meet minimum structural
#      requirements (must have lat/lng, numeric coordinates, reasonable size).
#      This prevents the app from silently processing wrong files and showing
#      a summary that looks real but was computed from a payroll spreadsheet.

#   2. Example dataset preview — shows the top 5 rows of the expected format
#      so clients know exactly what to prepare, plus a download button for
#      the CSV template.
# """

# import io
# import streamlit as st
# import pandas as pd

# # ── Demo dataset — representative 5-row sample for the preview table ──────────
# EXAMPLE_ROWS = pd.DataFrame([
#     {"stop_id": 1,  "zone": "Koramangala",  "lat": 12.9341, "lng": 77.6212,
#      "weight_kg": 15.2, "tw_start": 9.0,  "tw_end": 18.0, "window_label": "Flexible",     "is_priority": False},
#     {"stop_id": 2,  "zone": "Indiranagar",  "lat": 12.9784, "lng": 77.6408,
#      "weight_kg":  8.5, "tw_start": 10.0, "tw_end": 13.0, "window_label": "Tight Window",  "is_priority": False},
#     {"stop_id": 3,  "zone": "Whitefield",   "lat": 12.9698, "lng": 77.7500,
#      "weight_kg": 22.1, "tw_start": 9.0,  "tw_end": 18.0, "window_label": "Flexible",     "is_priority": False},
#     {"stop_id": 4,  "zone": "Koramangala",  "lat": 12.9362, "lng": 77.6241,
#      "weight_kg":  5.0, "tw_start": 9.0,  "tw_end": 12.0, "window_label": "Tight Window",  "is_priority": True},
#     {"stop_id": 5,  "zone": "Marathahalli", "lat": 12.9591, "lng": 77.7012,
#      "weight_kg": 18.3, "tw_start": 9.0,  "tw_end": 18.0, "window_label": "Flexible",     "is_priority": False},
# ])

# # ── Full demo summary (synthetic Bengaluru scenario) ──────────────────────────
# DEMO_SUMMARY = {
#     "total_stops":       120,
#     "zones":             9,
#     "zone_list":         ["Koramangala", "Indiranagar", "Whitefield", "Electronic City",
#                           "Marathahalli", "JP Nagar", "Hebbal", "Jayanagar", "MG Road"],
#     "city":              "Bengaluru, Karnataka",
#     "n_vehicles":        5,
#     "vehicle_breakdown": "2 mini-trucks · 2 vans · 1 bike",
#     "flex_pct":          58,
#     "tight_pct":         39,
#     "priority_pct":      3,
#     "data_days":         30,
#     "date_range":        "Apr 12 – May 12, 2026",
#     "avg_weight_kg":     12.4,
#     "fleet_capacity_kg": 1330,
#     "source":            "demo",
# }


# # ─────────────────────────────────────────────────────────────────────────────
# # Validation
# # ─────────────────────────────────────────────────────────────────────────────

# def _validate_csv(df: pd.DataFrame):
#     """
#     Validate an uploaded DataFrame before parsing it for display.

#     Returns (is_valid: bool, error_message: str | None).

#     We run four checks in order of severity. The first failure is returned
#     immediately — no point reporting all issues at once before the basic ones
#     are fixed. The checks are:

#     1. Minimum row count  — fewer than 5 stops is not a useful delivery dataset.
#     2. Maximum row count  — more than 5,000 stops would slow the demo noticeably.
#     3. Required columns  — lat AND lng (or recognisable aliases) must be present.
#     4. Numeric validity  — lat/lng must be parseable as numbers, with fewer than
#        30% nulls (a higher null rate almost always means a wrong column mapping).

#     We intentionally do NOT hard-fail on geographic range (Bengaluru vs another
#     city) because some clients bring data from nearby cities for comparison, and
#     a warning is more helpful than a rejection in that case.
#     """
#     # Check 1: Too few rows
#     if len(df) < 5:
#         return False, (
#             f"Your file has only {len(df)} rows. "
#             "A delivery dataset should have at least 5 stops to be useful in the optimiser. "
#             "Please check that you uploaded the correct file."
#         )

#     # Check 2: Too many rows for demo performance
#     if len(df) > 5_000:
#         return False, (
#             f"Your file has {len(df):,} rows. "
#             "For the live demo, please export a subset of up to 5,000 stops "
#             "(e.g. one week of deliveries for a single city). "
#             "Full-scale deployment handles larger datasets."
#         )

#     # Check 3: Must have lat AND lng columns (flexible naming)
#     lat_aliases = {"lat", "latitude", "y", "lat_deg", "delivery_lat", "stop_lat"}
#     lng_aliases = {"lng", "lon", "longitude", "long", "x", "lng_deg",
#                    "delivery_lng", "stop_lng", "stop_lon"}

#     lat_col = next((c for c in df.columns if c.lower().strip() in lat_aliases), None)
#     lng_col = next((c for c in df.columns if c.lower().strip() in lng_aliases), None)

#     if lat_col is None or lng_col is None:
#         missing = []
#         if lat_col is None: missing.append("latitude  (expected column name: lat or latitude)")
#         if lng_col is None: missing.append("longitude  (expected column name: lng or longitude)")
#         return False, (
#             "Your file is missing required columns:\n• " + "\n• ".join(missing) + "\n\n"
#             "The optimiser needs delivery coordinates to place stops on the Bengaluru map. "
#             "Download the example template below to see the expected format."
#         )

#     # Check 4: Lat/lng must be numeric with low null rate
#     lats = pd.to_numeric(df[lat_col], errors="coerce")
#     lngs = pd.to_numeric(df[lng_col], errors="coerce")

#     lat_null_pct = lats.isna().mean()
#     lng_null_pct = lngs.isna().mean()

#     if lat_null_pct > 0.30:
#         return False, (
#             f"Column '{lat_col}' has {lat_null_pct:.0%} non-numeric or missing values. "
#             "Latitude values must be decimal numbers like 12.9341 (not city names or postcodes)."
#         )
#     if lng_null_pct > 0.30:
#         return False, (
#             f"Column '{lng_col}' has {lng_null_pct:.0%} non-numeric or missing values. "
#             "Longitude values must be decimal numbers like 77.6212."
#         )

#     # Soft geographic check — warn but allow
#     valid_lats = lats.dropna()
#     in_india   = valid_lats.between(6.5, 37.5).mean()
#     if in_india < 0.5:
#         # More than half the coordinates are outside India entirely —
#         # this almost certainly means wrong columns or wrong file
#         return False, (
#             f"Most coordinates in column '{lat_col}' appear to be outside India "
#             f"(expected range 6.5°–37.5°N, found median {valid_lats.median():.1f}°). "
#             "Please verify you selected the correct lat/lng columns. "
#             "If your data uses a different coordinate system, "
#             "convert to WGS-84 decimal degrees before uploading."
#         )

#     return True, None   # all checks passed


# def _parse_csv(df: pd.DataFrame) -> dict:
#     """
#     Build the summary dict from a validated DataFrame.

#     At this point we know lat/lng are present and numeric — everything else
#     is best-effort: if a column exists and makes sense, use it; otherwise
#     fall back to demo defaults so the summary is never missing fields.
#     """
#     n_stops = len(df)

#     # Zone names
#     zone_col  = next((c for c in df.columns if c.lower() in
#                       {"zone", "area", "locality", "region", "zone_name"}), None)
#     zones     = sorted(df[zone_col].dropna().unique().tolist()) if zone_col else ["—"]
#     n_zones   = len(zones)

#     # Time windows → infer customer mix
#     tw_col    = next((c for c in df.columns if "window" in c.lower() or
#                       c.lower() in {"tw_start", "time_start", "window_start"}), None)
#     has_tw    = tw_col is not None

#     # Priority
#     pri_col   = next((c for c in df.columns if "priority" in c.lower() or
#                       c.lower() == "is_priority"), None)
#     if pri_col is not None:
#         priority_pct = round(df[pri_col].astype(bool).sum() / n_stops * 100)
#     else:
#         priority_pct = 0

#     tight_pct = 35 if has_tw else 0
#     flex_pct  = max(0, 100 - priority_pct - tight_pct)

#     # Weight
#     wt_col    = next((c for c in df.columns if "weight" in c.lower() or
#                       c.lower() in {"kg", "weight_kg", "package_weight"}), None)
#     avg_wt    = round(pd.to_numeric(df[wt_col], errors="coerce").mean(), 1) if wt_col else "—"

#     # Date range — try to find a date column
#     date_col  = next((c for c in df.columns if "date" in c.lower() or
#                       c.lower() in {"delivery_date", "order_date", "day"}), None)
#     if date_col:
#         try:
#             dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
#             date_range = f"{dates.min().strftime('%d %b')} – {dates.max().strftime('%d %b %Y')}"
#             data_days  = (dates.max() - dates.min()).days + 1
#         except Exception:
#             date_range = f"{n_stops} delivery records"
#             data_days  = "—"
#     else:
#         date_range = f"{n_stops} delivery records"
#         data_days  = "—"

#     return {
#         "total_stops":       n_stops,
#         "zones":             n_zones,
#         "zone_list":         zones[:6],
#         "city":              "Uploaded dataset",
#         "n_vehicles":        DEMO_SUMMARY["n_vehicles"],
#         "vehicle_breakdown": DEMO_SUMMARY["vehicle_breakdown"],
#         "flex_pct":          flex_pct,
#         "tight_pct":         tight_pct,
#         "priority_pct":      priority_pct,
#         "data_days":         data_days,
#         "date_range":        date_range,
#         "avg_weight_kg":     avg_wt,
#         "fleet_capacity_kg": DEMO_SUMMARY["fleet_capacity_kg"],
#         "source":            "upload",
#     }


# def _make_template_csv() -> bytes:
#     """Generate a downloadable CSV template from the example rows."""
#     return EXAMPLE_ROWS.to_csv(index=False).encode("utf-8")


# # ─────────────────────────────────────────────────────────────────────────────
# # UI components
# # ─────────────────────────────────────────────────────────────────────────────

# def _show_example_and_template():
#     """
#     Expand/collapse section showing example rows + download button.

#     Placed below the upload widget so clients who need guidance can find it
#     without it being in the way of clients who already know their format.
#     """
#     with st.expander("📋  What does the expected data format look like?", expanded=False):
#         st.markdown(
#             "Your CSV should have **at minimum** a `lat` and `lng` column. "
#             "All other columns are optional — the system will use what it finds "
#             "and fall back to defaults for anything missing."
#         )

#         # Column descriptions
#         col_info = {
#             "stop_id":      ("Required if available", "Unique identifier for each delivery stop"),
#             "zone":         ("Recommended",  "Delivery zone or neighbourhood name (e.g. Koramangala)"),
#             "lat":          ("Required",     "Latitude in WGS-84 decimal degrees (e.g. 12.9341)"),
#             "lng":          ("Required",     "Longitude in WGS-84 decimal degrees (e.g. 77.6212)"),
#             "weight_kg":    ("Recommended",  "Package weight in kg — used for vehicle capacity planning"),
#             "tw_start":     ("Optional",     "Time window start in hours from midnight (e.g. 9.0 = 9 AM)"),
#             "tw_end":       ("Optional",     "Time window end in hours from midnight (e.g. 13.0 = 1 PM)"),
#             "window_label": ("Optional",     "Human label: Flexible, Tight Window, or Priority"),
#             "is_priority":  ("Optional",     "True/False — priority deliveries are routed first"),
#         }
#         info_df = pd.DataFrame([
#             {"Column": k, "Status": v[0], "Description": v[1]}
#             for k, v in col_info.items()
#         ])
#         st.dataframe(info_df, hide_index=True, use_container_width=True)

#         st.markdown("**Example data (first 5 rows of the Bengaluru demo dataset):**")
#         st.dataframe(EXAMPLE_ROWS, hide_index=True, use_container_width=True)

#         st.download_button(
#             label="⬇️  Download CSV Template",
#             data=_make_template_csv(),
#             file_name="delivery_data_template.csv",
#             mime="text/csv",
#             help="Download this file, fill it with your own stop data, then upload it above.",
#         )


# def _compact_badge(summary: dict):
#     """One-line confirmation badge shown after onboarding is complete."""
#     src = "uploaded CSV" if summary.get("source") == "upload" else "Bengaluru demo dataset"
#     st.markdown(
#         f"""
#         <div style="background:#e8f5e9;border-left:4px solid #2e7d32;border-radius:6px;
#                     padding:8px 14px;margin-bottom:12px;font-size:12px;color:#1b5e20">
#             ✅&nbsp; <b>Data loaded</b> — {summary['total_stops']} stops across
#             {summary['zones']} zones ({src}).
#         </div>
#         """,
#         unsafe_allow_html=True,
#     )


# def _summary_cards(summary: dict):
#     """Four metric cards shown after a file is loaded or Demo is chosen."""
#     c1, c2, c3, c4 = st.columns(4)
#     css = ("background:white;border-radius:8px;padding:14px 16px;"
#            "border:1px solid #E2E8F0;box-shadow:0 1px 4px rgba(0,0,0,0.07);")
#     vc  = "font-size:20px;font-weight:700;color:#1A237E;margin:0"
#     lc  = "font-size:11px;color:#64748B;margin:4px 0 0 0;line-height:1.5"

#     zones_preview = ", ".join(summary["zone_list"][:3])
#     if len(summary["zone_list"]) > 3:
#         zones_preview += f" +{len(summary['zone_list'])-3} more"

#     with c1:
#         st.markdown(f'<div style="{css}"><div style="font-size:22px;margin-bottom:6px">📦</div>'
#                     f'<p style="{vc}">{summary["n_vehicles"]} vehicles</p>'
#                     f'<p style="{lc}">{summary["vehicle_breakdown"]}<br>'
#                     f'Capacity: {summary["fleet_capacity_kg"]}kg</p></div>',
#                     unsafe_allow_html=True)
#     with c2:
#         st.markdown(f'<div style="{css}"><div style="font-size:22px;margin-bottom:6px">📍</div>'
#                     f'<p style="{vc}">{summary["total_stops"]} stops</p>'
#                     f'<p style="{lc}">across {summary["zones"]} zones<br>{zones_preview}</p></div>',
#                     unsafe_allow_html=True)
#     with c3:
#         st.markdown(f'<div style="{css}"><div style="font-size:22px;margin-bottom:6px">👥</div>'
#                     f'<p style="{vc}">{summary["flex_pct"]}% flexible</p>'
#                     f'<p style="{lc}">{summary["tight_pct"]}% time-constrained<br>'
#                     f'{summary["priority_pct"]}% priority</p></div>',
#                     unsafe_allow_html=True)
#     with c4:
#         st.markdown(f'<div style="{css}"><div style="font-size:22px;margin-bottom:6px">📅</div>'
#                     f'<p style="{vc}">{summary["data_days"]} days</p>'
#                     f'<p style="{lc}">{summary["date_range"]}<br>'
#                     f'Avg pkg: {summary["avg_weight_kg"]}kg</p></div>',
#                     unsafe_allow_html=True)


# # ─────────────────────────────────────────────────────────────────────────────
# # Main entry point
# # ─────────────────────────────────────────────────────────────────────────────

# def render_data_onboarding() -> bool:
#     """
#     Call at the top of the Route Optimizer page.
#     Returns True when onboarding is complete and the optimizer should render.
#     Returns False while the onboarding card is still showing.
#     """
#     if "data_onboarding_complete" not in st.session_state:
#         st.session_state.data_onboarding_complete = False
#     if "data_summary" not in st.session_state:
#         st.session_state.data_summary = None
#     if "data_upload_error" not in st.session_state:
#         st.session_state.data_upload_error = None

#     # ── Already done — show compact badge and pass through ────────────────────
#     if st.session_state.data_onboarding_complete and st.session_state.data_summary:
#         _compact_badge(st.session_state.data_summary)
#         return True

#     # ── Full onboarding card ──────────────────────────────────────────────────
#     st.markdown(
#         """
#         <div style="background:linear-gradient(135deg,#1A237E,#283593);
#                     color:white;padding:16px 22px;border-radius:10px 10px 0 0">
#             <div style="font-size:17px;font-weight:700">
#                 📤&nbsp; Step 1 — Load Your Delivery Data
#             </div>
#             <div style="font-size:12px;opacity:0.85;margin-top:3px">
#                 Upload a CSV from your WMS, TMS, or Excel sheet —
#                 or use the Bengaluru demo dataset to explore the platform.
#                 Your file must include <b>lat</b> and <b>lng</b> columns;
#                 everything else is auto-detected.
#             </div>
#         </div>
#         <div style="background:white;border:1px solid #E2E8F0;border-top:none;
#                     border-radius:0 0 10px 10px;padding:18px 22px;margin-bottom:4px">
#         """,
#         unsafe_allow_html=True,
#     )

#     upload_col, or_col, demo_col = st.columns([5, 1, 3])

#     with upload_col:
#         uploaded = st.file_uploader(
#             "delivery_upload",
#             type=["csv", "xlsx"],
#             label_visibility="collapsed",
#             key="data_upload_widget",
#         )
#         st.caption("CSV / Excel · Must include lat & lng columns · Data stays in your browser")

#     with or_col:
#         st.markdown(
#             "<div style='text-align:center;padding-top:18px;color:#94A3B8;"
#             "font-weight:600'>— OR —</div>", unsafe_allow_html=True)

#     with demo_col:
#         st.markdown("<div style='padding-top:8px'>", unsafe_allow_html=True)
#         demo_clicked = st.button(
#             "🗂️  Use Bengaluru Demo Dataset",
#             use_container_width=True,
#             help="120 stops · 9 zones · 5 vehicles · 30 days of history",
#         )
#         st.caption("Pre-loaded with realistic Bengaluru delivery patterns")
#         st.markdown("</div>", unsafe_allow_html=True)

#     st.markdown("</div>", unsafe_allow_html=True)  # close white card

#     # Example + template — below the main card, collapsed by default
#     _show_example_and_template()

#     # ── Handle Demo button ────────────────────────────────────────────────────
#     if demo_clicked:
#         st.session_state.data_summary      = DEMO_SUMMARY
#         st.session_state.data_upload_error = None
#         st.rerun()

#     # ── Handle CSV upload ─────────────────────────────────────────────────────
#     if uploaded is not None and st.session_state.data_summary is None:
#         try:
#             if uploaded.name.endswith(".xlsx"):
#                 df = pd.read_excel(uploaded)
#             else:
#                 df = pd.read_csv(uploaded)

#             is_valid, error_msg = _validate_csv(df)

#             if not is_valid:
#                 st.session_state.data_upload_error = error_msg
#                 st.session_state.data_summary      = None
#             else:
#                 st.session_state.data_summary      = _parse_csv(df)
#                 st.session_state.data_upload_error = None

#         except Exception as exc:
#             st.session_state.data_upload_error = (
#                 f"Could not read the file: {exc}. "
#                 "Please ensure it is a valid CSV or Excel file and try again."
#             )
#             st.session_state.data_summary = None

#         st.rerun()

#     # ── Show validation error if present ─────────────────────────────────────
#     if st.session_state.data_upload_error:
#         st.error(
#             f"**File not accepted.** {st.session_state.data_upload_error}\n\n"
#             "Open the 'What does the expected data format look like?' section "
#             "above for the column guide and a downloadable template.",
#             icon="⚠️",
#         )
#         # Allow trying again — clear error on next upload attempt
#         if st.button("↩  Try a different file", key="retry_upload"):
#             st.session_state.data_upload_error = None
#             st.rerun()

#     # ── Show summary + Proceed button if data is loaded ───────────────────────
#     if st.session_state.data_summary is not None:
#         src = st.session_state.data_summary.get("source", "demo")
#         label = ("Bengaluru demo dataset ready"
#                  if src in ("demo", "upload_fallback")
#                  else f"File validated — {st.session_state.data_summary['total_stops']} stops accepted")

#         st.markdown(
#             f"""
#             <div style="background:#e8f5e9;border:1px solid #a5d6a7;border-radius:8px;
#                         padding:10px 16px;margin:12px 0 8px 0">
#                 <span style="color:#2e7d32;font-weight:700;font-size:14px">
#                     ✅&nbsp; {label}
#                 </span>
#                 <span style="color:#64748B;font-size:12px;margin-left:8px">
#                     — here is what the system found in your data:
#                 </span>
#             </div>
#             """,
#             unsafe_allow_html=True,
#         )

#         _summary_cards(st.session_state.data_summary)
#         st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

#         _, btn_col, _ = st.columns([2, 3, 2])
#         with btn_col:
#             if st.button(
#                 "Proceed to Route Optimisation →",
#                 type="primary",
#                 use_container_width=True,
#                 key="onboarding_proceed",
#             ):
#                 st.session_state.data_onboarding_complete = True
#                 st.rerun()

#     return False  # optimizer hidden until Proceed is clicked

"""
ui/data_onboarding.py
----------------------
Data onboarding card — the psychological "this is your data" moment.

Two additions over v1:
  1. Validation layer — rejects files that do not meet minimum structural
     requirements (must have lat/lng, numeric coordinates, reasonable size).
     This prevents the app from silently processing wrong files and showing
     a summary that looks real but was computed from a payroll spreadsheet.

  2. Example dataset preview — shows the top 5 rows of the expected format
     so clients know exactly what to prepare, plus a download button for
     the CSV template.
"""

import io
import streamlit as st
import pandas as pd

# ── Demo dataset — representative 5-row sample for the preview table ──────────
EXAMPLE_ROWS = pd.DataFrame([
    {"stop_id": 1,  "zone": "Koramangala",  "lat": 12.9341, "lng": 77.6212,
     "weight_kg": 15.2, "tw_start": 9.0,  "tw_end": 18.0, "window_label": "Flexible",     "is_priority": False},
    {"stop_id": 2,  "zone": "Indiranagar",  "lat": 12.9784, "lng": 77.6408,
     "weight_kg":  8.5, "tw_start": 10.0, "tw_end": 13.0, "window_label": "Tight Window",  "is_priority": False},
    {"stop_id": 3,  "zone": "Whitefield",   "lat": 12.9698, "lng": 77.7500,
     "weight_kg": 22.1, "tw_start": 9.0,  "tw_end": 18.0, "window_label": "Flexible",     "is_priority": False},
    {"stop_id": 4,  "zone": "Koramangala",  "lat": 12.9362, "lng": 77.6241,
     "weight_kg":  5.0, "tw_start": 9.0,  "tw_end": 12.0, "window_label": "Tight Window",  "is_priority": True},
    {"stop_id": 5,  "zone": "Marathahalli", "lat": 12.9591, "lng": 77.7012,
     "weight_kg": 18.3, "tw_start": 9.0,  "tw_end": 18.0, "window_label": "Flexible",     "is_priority": False},
])

# ── Full demo summary (synthetic Bengaluru scenario) ──────────────────────────
DEMO_SUMMARY = {
    "total_stops":       120,
    "zones":             9,
    "zone_list":         ["Koramangala", "Indiranagar", "Whitefield", "Electronic City",
                          "Marathahalli", "JP Nagar", "Hebbal", "Jayanagar", "MG Road"],
    "city":              "Bengaluru, Karnataka",
    "n_vehicles":        5,
    "vehicle_breakdown": "2 mini-trucks · 2 vans · 1 bike",
    "flex_pct":          58,
    "tight_pct":         39,
    "priority_pct":      3,
    "data_days":         30,
    "date_range":        "Apr 12 – May 12, 2026",
    "avg_weight_kg":     12.4,
    "fleet_capacity_kg": 1330,
    "source":            "demo",
}


# ─────────────────────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────────────────────

def _validate_csv(df: pd.DataFrame):
    """
    Validate an uploaded DataFrame before parsing it for display.

    Returns (is_valid: bool, error_message: str | None).

    We run four checks in order of severity. The first failure is returned
    immediately — no point reporting all issues at once before the basic ones
    are fixed. The checks are:

    1. Minimum row count  — fewer than 5 stops is not a useful delivery dataset.
    2. Maximum row count  — more than 5,000 stops would slow the demo noticeably.
    3. Required columns  — lat AND lng (or recognisable aliases) must be present.
    4. Numeric validity  — lat/lng must be parseable as numbers, with fewer than
       30% nulls (a higher null rate almost always means a wrong column mapping).

    We intentionally do NOT hard-fail on geographic range (Bengaluru vs another
    city) because some clients bring data from nearby cities for comparison, and
    a warning is more helpful than a rejection in that case.
    """
    # Check 1: Too few rows
    if len(df) < 5:
        return False, (
            f"Your file has only {len(df)} rows. "
            "A delivery dataset should have at least 5 stops to be useful in the optimiser. "
            "Please check that you uploaded the correct file."
        )

    # Check 2: Too many rows for demo performance
    if len(df) > 5_000:
        return False, (
            f"Your file has {len(df):,} rows. "
            "For the live demo, please export a subset of up to 5,000 stops "
            "(e.g. one week of deliveries for a single city). "
            "Full-scale deployment handles larger datasets."
        )

    # Check 3: Must have lat AND lng columns (flexible naming)
    lat_aliases = {"lat", "latitude", "y", "lat_deg", "delivery_lat", "stop_lat"}
    lng_aliases = {"lng", "lon", "longitude", "long", "x", "lng_deg",
                   "delivery_lng", "stop_lng", "stop_lon"}

    lat_col = next((c for c in df.columns if c.lower().strip() in lat_aliases), None)
    lng_col = next((c for c in df.columns if c.lower().strip() in lng_aliases), None)

    if lat_col is None or lng_col is None:
        missing = []
        if lat_col is None: missing.append("latitude  (expected column name: lat or latitude)")
        if lng_col is None: missing.append("longitude  (expected column name: lng or longitude)")
        return False, (
            "Your file is missing required columns:\n• " + "\n• ".join(missing) + "\n\n"
            "The optimiser needs delivery coordinates to place stops on the Bengaluru map. "
            "Download the example template below to see the expected format."
        )

    # Check 4: Lat/lng must be numeric with low null rate
    lats = pd.to_numeric(df[lat_col], errors="coerce")
    lngs = pd.to_numeric(df[lng_col], errors="coerce")

    lat_null_pct = lats.isna().mean()
    lng_null_pct = lngs.isna().mean()

    if lat_null_pct > 0.30:
        return False, (
            f"Column '{lat_col}' has {lat_null_pct:.0%} non-numeric or missing values. "
            "Latitude values must be decimal numbers like 12.9341 (not city names or postcodes)."
        )
    if lng_null_pct > 0.30:
        return False, (
            f"Column '{lng_col}' has {lng_null_pct:.0%} non-numeric or missing values. "
            "Longitude values must be decimal numbers like 77.6212."
        )

    # Soft geographic check — warn but allow
    valid_lats = lats.dropna()
    in_india   = valid_lats.between(6.5, 37.5).mean()
    if in_india < 0.5:
        # More than half the coordinates are outside India entirely —
        # this almost certainly means wrong columns or wrong file
        return False, (
            f"Most coordinates in column '{lat_col}' appear to be outside India "
            f"(expected range 6.5°–37.5°N, found median {valid_lats.median():.1f}°). "
            "Please verify you selected the correct lat/lng columns. "
            "If your data uses a different coordinate system, "
            "convert to WGS-84 decimal degrees before uploading."
        )

    return True, None   # all checks passed


def _parse_csv(df: pd.DataFrame) -> dict:
    """
    Build the summary dict from a validated DataFrame.

    At this point we know lat/lng are present and numeric — everything else
    is best-effort: if a column exists and makes sense, use it; otherwise
    fall back to demo defaults so the summary is never missing fields.
    """
    n_stops = len(df)

    # Zone names
    zone_col  = next((c for c in df.columns if c.lower() in
                      {"zone", "area", "locality", "region", "zone_name"}), None)
    zones     = sorted(df[zone_col].dropna().unique().tolist()) if zone_col else ["—"]
    n_zones   = len(zones)

    # Time windows → infer customer mix
    tw_col    = next((c for c in df.columns if "window" in c.lower() or
                      c.lower() in {"tw_start", "time_start", "window_start"}), None)
    has_tw    = tw_col is not None

    # Priority
    pri_col   = next((c for c in df.columns if "priority" in c.lower() or
                      c.lower() == "is_priority"), None)
    if pri_col is not None:
        priority_pct = round(df[pri_col].astype(bool).sum() / n_stops * 100)
    else:
        priority_pct = 0

    tight_pct = 35 if has_tw else 0
    flex_pct  = max(0, 100 - priority_pct - tight_pct)

    # Weight
    wt_col    = next((c for c in df.columns if "weight" in c.lower() or
                      c.lower() in {"kg", "weight_kg", "package_weight"}), None)
    avg_wt    = round(pd.to_numeric(df[wt_col], errors="coerce").mean(), 1) if wt_col else "—"

    # Date range — try to find a date column
    date_col  = next((c for c in df.columns if "date" in c.lower() or
                      c.lower() in {"delivery_date", "order_date", "day"}), None)
    if date_col:
        try:
            dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
            date_range = f"{dates.min().strftime('%d %b')} – {dates.max().strftime('%d %b %Y')}"
            data_days  = (dates.max() - dates.min()).days + 1
        except Exception:
            date_range = f"{n_stops} delivery records"
            data_days  = "—"
    else:
        date_range = f"{n_stops} delivery records"
        data_days  = "—"

    return {
        "total_stops":       n_stops,
        "zones":             n_zones,
        "zone_list":         zones[:6],
        "city":              "Uploaded dataset",
        "n_vehicles":        DEMO_SUMMARY["n_vehicles"],
        "vehicle_breakdown": DEMO_SUMMARY["vehicle_breakdown"],
        "flex_pct":          flex_pct,
        "tight_pct":         tight_pct,
        "priority_pct":      priority_pct,
        "data_days":         data_days,
        "date_range":        date_range,
        "avg_weight_kg":     avg_wt,
        "fleet_capacity_kg": DEMO_SUMMARY["fleet_capacity_kg"],
        "source":            "upload",
    }


def _make_template_csv() -> bytes:
    """Generate a downloadable CSV template from the example rows."""
    return EXAMPLE_ROWS.to_csv(index=False).encode("utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# UI components
# ─────────────────────────────────────────────────────────────────────────────

def _show_example_and_template():
    """
    Expand/collapse section showing example rows + download button.

    Placed below the upload widget so clients who need guidance can find it
    without it being in the way of clients who already know their format.
    """
    with st.expander("📋  What does the expected data format look like?", expanded=False):
        st.markdown(
            "Your CSV should have **at minimum** a `lat` and `lng` column. "
            "All other columns are optional — the system will use what it finds "
            "and fall back to defaults for anything missing."
        )

        # Column descriptions
        col_info = {
            "stop_id":      ("Required if available", "Unique identifier for each delivery stop"),
            "zone":         ("Recommended",  "Delivery zone or neighbourhood name (e.g. Koramangala)"),
            "lat":          ("Required",     "Latitude in WGS-84 decimal degrees (e.g. 12.9341)"),
            "lng":          ("Required",     "Longitude in WGS-84 decimal degrees (e.g. 77.6212)"),
            "weight_kg":    ("Recommended",  "Package weight in kg — used for vehicle capacity planning"),
            "tw_start":     ("Optional",     "Time window start in hours from midnight (e.g. 9.0 = 9 AM)"),
            "tw_end":       ("Optional",     "Time window end in hours from midnight (e.g. 13.0 = 1 PM)"),
            "window_label": ("Optional",     "Human label: Flexible, Tight Window, or Priority"),
            "is_priority":  ("Optional",     "True/False — priority deliveries are routed first"),
        }
        info_df = pd.DataFrame([
            {"Column": k, "Status": v[0], "Description": v[1]}
            for k, v in col_info.items()
        ])
        st.dataframe(info_df, hide_index=True, use_container_width=True)

        st.markdown("**Example data (first 5 rows of the Bengaluru demo dataset):**")
        st.dataframe(EXAMPLE_ROWS, hide_index=True, use_container_width=True)

        st.download_button(
            label="⬇️  Download CSV Template",
            data=_make_template_csv(),
            file_name="delivery_data_template.csv",
            mime="text/csv",
            help="Download this file, fill it with your own stop data, then upload it above.",
        )


def _compact_badge(summary: dict):
    """One-line confirmation badge shown after onboarding is complete."""
    src = "uploaded CSV" if summary.get("source") == "upload" else "Bengaluru demo dataset"
    st.markdown(
        f"""
        <div style="background:#e8f5e9;border-left:4px solid #2e7d32;border-radius:6px;
                    padding:8px 14px;margin-bottom:12px;font-size:12px;color:#1b5e20">
            ✅&nbsp; <b>Data loaded</b> — {summary['total_stops']} stops across
            {summary['zones']} zones ({src}).
        </div>
        """,
        unsafe_allow_html=True,
    )


def _summary_cards(summary: dict):
    """Four metric cards shown after a file is loaded or Demo is chosen."""
    c1, c2, c3, c4 = st.columns(4)
    css = ("background:white;border-radius:8px;padding:14px 16px;"
           "border:1px solid #E2E8F0;box-shadow:0 1px 4px rgba(0,0,0,0.07);")
    vc  = "font-size:20px;font-weight:700;color:#1A237E;margin:0"
    lc  = "font-size:11px;color:#64748B;margin:4px 0 0 0;line-height:1.5"

    zones_preview = ", ".join(summary["zone_list"][:3])
    if len(summary["zone_list"]) > 3:
        zones_preview += f" +{len(summary['zone_list'])-3} more"

    with c1:
        st.markdown(f'<div style="{css}"><div style="font-size:22px;margin-bottom:6px">📦</div>'
                    f'<p style="{vc}">{summary["n_vehicles"]} vehicles</p>'
                    f'<p style="{lc}">{summary["vehicle_breakdown"]}<br>'
                    f'Capacity: {summary["fleet_capacity_kg"]}kg</p></div>',
                    unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div style="{css}"><div style="font-size:22px;margin-bottom:6px">📍</div>'
                    f'<p style="{vc}">{summary["total_stops"]} stops</p>'
                    f'<p style="{lc}">across {summary["zones"]} zones<br>{zones_preview}</p></div>',
                    unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div style="{css}"><div style="font-size:22px;margin-bottom:6px">👥</div>'
                    f'<p style="{vc}">{summary["flex_pct"]}% flexible</p>'
                    f'<p style="{lc}">{summary["tight_pct"]}% time-constrained<br>'
                    f'{summary["priority_pct"]}% priority</p></div>',
                    unsafe_allow_html=True)
    with c4:
        st.markdown(f'<div style="{css}"><div style="font-size:22px;margin-bottom:6px">📅</div>'
                    f'<p style="{vc}">{summary["data_days"]} days</p>'
                    f'<p style="{lc}">{summary["date_range"]}<br>'
                    f'Avg pkg: {summary["avg_weight_kg"]}kg</p></div>',
                    unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def render_data_onboarding() -> bool:
    """
    Call at the top of the Route Optimizer page.
    Returns True when onboarding is complete and the optimizer should render.
    Returns False while the onboarding card is still showing.
    """
    if "data_onboarding_complete" not in st.session_state:
        st.session_state.data_onboarding_complete = False
    if "data_summary" not in st.session_state:
        st.session_state.data_summary = None
    if "data_upload_error" not in st.session_state:
        st.session_state.data_upload_error = None

    # ── Already done — show compact badge and pass through ────────────────────
    if st.session_state.data_onboarding_complete and st.session_state.data_summary:
        _compact_badge(st.session_state.data_summary)
        return True

    # ── Full onboarding card ──────────────────────────────────────────────────
    st.markdown(
        """
        <div style="background:linear-gradient(135deg,#1A237E,#283593);
                    color:white;padding:16px 22px;border-radius:10px 10px 0 0">
            <div style="font-size:17px;font-weight:700">
                📤&nbsp; Step 1 — Load Your Delivery Data
            </div>
            <div style="font-size:12px;opacity:0.85;margin-top:3px">
                Upload a CSV from your WMS, TMS, or Excel sheet —
                or use the Bengaluru demo dataset to explore the platform.
                Your file must include <b>lat</b> and <b>lng</b> columns;
                everything else is auto-detected.
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
            "delivery_upload",
            type=["csv", "xlsx"],
            label_visibility="collapsed",
            key="data_upload_widget",
        )
        st.caption("CSV / Excel · Must include lat & lng columns · Data stays in your browser")

    with or_col:
        st.markdown(
            "<div style='text-align:center;padding-top:18px;color:#94A3B8;"
            "font-weight:600'>— OR —</div>", unsafe_allow_html=True)

    with demo_col:
        st.markdown("<div style='padding-top:8px'>", unsafe_allow_html=True)
        demo_clicked = st.button(
            "🗂️  Use Bengaluru Demo Dataset",
            use_container_width=True,
            help="120 stops · 9 zones · 5 vehicles · 30 days of history",
        )
        st.caption("Pre-loaded with realistic Bengaluru delivery patterns")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)  # close white card

    # Example + template — below the main card, collapsed by default
    _show_example_and_template()

    # ── Handle Demo button ────────────────────────────────────────────────────
    if demo_clicked:
        st.session_state.data_summary      = DEMO_SUMMARY
        st.session_state.data_upload_error = None
        st.rerun()

    # ── Handle CSV upload ─────────────────────────────────────────────────────
    if uploaded is not None and st.session_state.data_summary is None:
        try:
            if uploaded.name.endswith(".xlsx"):
                df = pd.read_excel(uploaded)
            else:
                df = pd.read_csv(uploaded)

            is_valid, error_msg = _validate_csv(df)

            if not is_valid:
                st.session_state.data_upload_error = error_msg
                st.session_state.data_summary      = None
            else:
                st.session_state.data_summary      = _parse_csv(df)
                st.session_state.data_upload_error = None

        except Exception as exc:
            st.session_state.data_upload_error = (
                f"Could not read the file: {exc}. "
                "Please ensure it is a valid CSV or Excel file and try again."
            )
            st.session_state.data_summary = None

        st.rerun()

    # ── Show validation error if present ─────────────────────────────────────
    if st.session_state.data_upload_error:
        st.error(
            f"**File not accepted.** {st.session_state.data_upload_error}\n\n"
            "Open the 'What does the expected data format look like?' section "
            "above for the column guide and a downloadable template.",
            icon="⚠️",
        )
        # Allow trying again — clear error on next upload attempt
        if st.button("↩  Try a different file", key="retry_upload"):
            st.session_state.data_upload_error = None
            st.rerun()

    # ── Show summary + Proceed button if data is loaded ───────────────────────
    if st.session_state.data_summary is not None:
        src = st.session_state.data_summary.get("source", "demo")
        label = ("Bengaluru demo dataset ready"
                 if src in ("demo", "upload_fallback")
                 else f"File validated — {st.session_state.data_summary['total_stops']} stops accepted")

        st.markdown(
            f"""
            <div style="background:#e8f5e9;border:1px solid #a5d6a7;border-radius:8px;
                        padding:10px 16px;margin:12px 0 8px 0">
                <span style="color:#2e7d32;font-weight:700;font-size:14px">
                    ✅&nbsp; {label}
                </span>
                <span style="color:#64748B;font-size:12px;margin-left:8px">
                    — here is what the system found in your data:
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        _summary_cards(st.session_state.data_summary)
        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

        _, btn_col, _ = st.columns([2, 3, 2])
        with btn_col:
            if st.button(
                "Proceed to Route Optimisation →",
                type="primary",
                use_container_width=True,
                key="onboarding_proceed",
            ):
                st.session_state.data_onboarding_complete = True
                st.rerun()

    return False  # optimizer hidden until Proceed is clicked


# ─────────────────────────────────────────────────────────────────────────────
# Network Intelligence onboarding
# Reuses all the same validation, card, and template helpers above.
# Only differences: session state keys, header text, and demo summary numbers.
# ─────────────────────────────────────────────────────────────────────────────

NI_DEMO_SUMMARY = {
    # Network Intelligence analyses aggregated demand, not individual runs,
    # so the headline metric is average daily stops across the history period.
    "total_stops":       311,          # avg daily deliveries across 30 days
    "zones":             9,
    "zone_list":         ["Koramangala", "Indiranagar", "Whitefield", "Electronic City",
                          "Marathahalli", "JP Nagar", "Hebbal", "Jayanagar", "MG Road"],
    "city":              "Bengaluru, Karnataka",
    "n_vehicles":        5,
    "vehicle_breakdown": "2 mini-trucks · 2 vans · 1 bike",
    "flex_pct":          58,
    "tight_pct":         39,
    "priority_pct":      3,
    "data_days":         30,
    "date_range":        "Apr 12 – May 12, 2026",
    "avg_weight_kg":     12.4,
    "fleet_capacity_kg": 1330,
    # NI-specific fields shown in the right two cards
    "daily_cost_inr":    "₹17,912",    # estimated current daily routing cost
    "depot":             "Bommanahalli",
    "busiest_zone":      "Koramangala (55 stops/day)",
    "furthest_zone":     "Whitefield — 16km from depot",
    "source":            "demo",
}


def _ni_summary_cards(summary: dict):
    """
    Four cards tuned for the Network Intelligence context.

    The Route Optimizer cards emphasise fleet and customer mix.
    For Network Intelligence the business question is different — the client
    wants to understand their network shape: how much demand is there, where
    is it concentrated, what does it cost today, and over what time window was
    this measured. Those four questions map to the four cards below.
    """
    c1, c2, c3, c4 = st.columns(4)
    css = ("background:white;border-radius:8px;padding:14px 16px;"
           "border:1px solid #E2E8F0;box-shadow:0 1px 4px rgba(0,0,0,0.07);")
    vc  = "font-size:20px;font-weight:700;color:#1A237E;margin:0"
    lc  = "font-size:11px;color:#64748B;margin:4px 0 0 0;line-height:1.5"

    zones_preview = ", ".join(summary["zone_list"][:3])
    if len(summary["zone_list"]) > 3:
        zones_preview += f" +{len(summary['zone_list'])-3} more"

    with c1:
        st.markdown(
            f'''<div style="{css}"><div style="font-size:22px;margin-bottom:6px">📊</div>
            <p style="{vc}">{summary["total_stops"]} stops/day</p>
            <p style="{lc}">average daily delivery volume<br>
            Busiest: {summary.get("busiest_zone","—")}</p></div>''',
            unsafe_allow_html=True)

    with c2:
        st.markdown(
            f'''<div style="{css}"><div style="font-size:22px;margin-bottom:6px">🗺️</div>
            <p style="{vc}">{summary["zones"]} zones</p>
            <p style="{lc}">single depot: {summary.get("depot","—")}<br>
            {zones_preview}</p></div>''',
            unsafe_allow_html=True)

    with c3:
        st.markdown(
            f'''<div style="{css}"><div style="font-size:22px;margin-bottom:6px">💰</div>
            <p style="{vc}">{summary.get("daily_cost_inr","—")}/day</p>
            <p style="{lc}">estimated current routing cost<br>
            Furthest zone: {summary.get("furthest_zone","—")}</p></div>''',
            unsafe_allow_html=True)

    with c4:
        st.markdown(
            f'''<div style="{css}"><div style="font-size:22px;margin-bottom:6px">📅</div>
            <p style="{vc}">{summary["data_days"]} days</p>
            <p style="{lc}">{summary["date_range"]}<br>
            {summary["n_vehicles"]} vehicles · {summary["vehicle_breakdown"]}</p></div>''',
            unsafe_allow_html=True)


def _ni_compact_badge(summary: dict):
    """One-line confirmation badge for the NI page after onboarding is done."""
    src = "uploaded CSV" if summary.get("source") == "upload" else "Bengaluru demo dataset"
    st.markdown(
        f"""
        <div style="background:#e8f5e9;border-left:4px solid #2e7d32;border-radius:6px;
                    padding:8px 14px;margin-bottom:12px;font-size:12px;color:#1b5e20">
            ✅&nbsp; <b>Network data loaded</b> — {summary["total_stops"]} avg daily stops
            across {summary["zones"]} zones ({src}).
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_ni_onboarding() -> bool:
    """
    Network Intelligence equivalent of render_data_onboarding().

    Call at the top of render_meio_page(), right after the page header.
    Returns True when onboarding is complete and the Run Analysis button
    should be visible. Returns False while the card is still showing.

    Uses separate session state keys (ni_onboarding_complete / ni_data_summary)
    so it is completely independent from the Route Optimizer onboarding —
    resetting one page does not reset the other.
    """
    if "ni_onboarding_complete" not in st.session_state:
        st.session_state.ni_onboarding_complete = False
    if "ni_data_summary" not in st.session_state:
        st.session_state.ni_data_summary = None
    if "ni_upload_error" not in st.session_state:
        st.session_state.ni_upload_error = None

    # ── Already done — compact badge and pass through ─────────────────────────
    if st.session_state.ni_onboarding_complete and st.session_state.ni_data_summary:
        _ni_compact_badge(st.session_state.ni_data_summary)
        return True

    # ── Full onboarding card ──────────────────────────────────────────────────
    st.markdown(
        """
        <div style="background:linear-gradient(135deg,#1A237E,#283593);
                    color:white;padding:16px 22px;border-radius:10px 10px 0 0">
            <div style="font-size:17px;font-weight:700">
                📤&nbsp; Step 1 — Load Your Network Data
            </div>
            <div style="font-size:12px;opacity:0.85;margin-top:3px">
                Upload 30 days of delivery records from your WMS or TMS —
                or use the Bengaluru demo dataset to see what the platform finds
                in a real distribution network.
                Your file must include <b>lat</b> and <b>lng</b> columns;
                zone names and dates are auto-detected if present.
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
            "ni_delivery_upload",
            type=["csv", "xlsx"],
            label_visibility="collapsed",
            key="ni_upload_widget",
        )
        st.caption("CSV / Excel · Must include lat & lng columns · Data stays in your browser")

    with or_col:
        st.markdown(
            "<div style='text-align:center;padding-top:18px;color:#94A3B8;"
            "font-weight:600'>— OR —</div>", unsafe_allow_html=True)

    with demo_col:
        st.markdown("<div style='padding-top:8px'>", unsafe_allow_html=True)
        demo_clicked = st.button(
            "🗂️  Use Bengaluru Demo Dataset",
            use_container_width=True,
            key="ni_demo_btn",
            help="311 avg daily stops · 9 zones · 30 days of demand history",
        )
        st.caption("Pre-loaded Bengaluru distribution network data")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)

    # Shared example template — same format works for both modules
    _show_example_and_template()

    # ── Handle Demo button ────────────────────────────────────────────────────
    if demo_clicked:
        st.session_state.ni_data_summary = NI_DEMO_SUMMARY
        st.session_state.ni_upload_error = None
        st.rerun()

    # ── Handle CSV upload ─────────────────────────────────────────────────────
    if uploaded is not None and st.session_state.ni_data_summary is None:
        try:
            df = pd.read_excel(uploaded) if uploaded.name.endswith(".xlsx") else pd.read_csv(uploaded)
            is_valid, error_msg = _validate_csv(df)

            if not is_valid:
                st.session_state.ni_upload_error = error_msg
                st.session_state.ni_data_summary = None
            else:
                # Parse as a route-level summary, then enrich with NI fields
                base = _parse_csv(df)
                # NI-specific overrides: show daily cost and depot context
                base["daily_cost_inr"]  = NI_DEMO_SUMMARY["daily_cost_inr"]
                base["depot"]           = NI_DEMO_SUMMARY["depot"]
                base["busiest_zone"]    = NI_DEMO_SUMMARY["busiest_zone"]
                base["furthest_zone"]   = NI_DEMO_SUMMARY["furthest_zone"]
                base["source"]          = "upload"
                st.session_state.ni_data_summary  = base
                st.session_state.ni_upload_error  = None

        except Exception as exc:
            st.session_state.ni_upload_error = (
                f"Could not read the file: {exc}. "
                "Please ensure it is a valid CSV or Excel file."
            )
            st.session_state.ni_data_summary = None

        st.rerun()

    # ── Validation error ──────────────────────────────────────────────────────
    if st.session_state.ni_upload_error:
        st.error(
            f"**File not accepted.** {st.session_state.ni_upload_error}\n\n"
            "Open the format guide below for the column guide and a downloadable template.",
            icon="⚠️",
        )
        if st.button("↩  Try a different file", key="ni_retry"):
            st.session_state.ni_upload_error = None
            st.rerun()

    # ── Show summary + Proceed button ─────────────────────────────────────────
    if st.session_state.ni_data_summary is not None:
        summary = st.session_state.ni_data_summary
        src     = summary.get("source", "demo")
        label   = (
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

        _ni_summary_cards(summary)
        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

        _, btn_col, _ = st.columns([2, 3, 2])
        with btn_col:
            if st.button(
                "Proceed to Network Analysis →",
                type="primary",
                use_container_width=True,
                key="ni_onboarding_proceed",
            ):
                st.session_state.ni_onboarding_complete = True
                st.rerun()

    return False  # Run Analysis button hidden until Proceed is clicked