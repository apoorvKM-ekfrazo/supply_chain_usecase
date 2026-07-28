"""
ui/load_optimizer.py
--------------------
Load Optimisation — Tab 1 of the Route Optimizer page.

Answers: given items with known dimensions and weight, which vehicle fits
them, what limits the load (volume vs weight), and what will the carrier bill?

Key concepts surfaced:
  Cube-out: the vehicle runs out of physical space before hitting payload limit.
            Typical for electronics (large boxes, light items).
  Weigh-out: the vehicle hits payload limit while space remains.
             Typical for FMCG (dense, heavy master cartons).
  Volumetric penalty: when the carrier's dimensional weight formula exceeds
                      actual weight, they bill the higher number.

Vehicle and carton data: Indian Logistics Fleet And Packaging research (2026).
Volumetric divisors: Delhivery, Blue Dart, Ekart, Shadowfax rate cards (2026).
"""

import math
import streamlit as st
import plotly.graph_objects as go


FT_TO_CM = 30.48


import os as _os, requests as _req


def _llm_call(user_prompt: str, cache_key: str, max_tokens: int = 180) -> str | None:
    """
    Single LLM call: OpenAI gpt-4o-mini first, Groq llama-3.3-70b fallback.
    Result cached in st.session_state[cache_key] so each card calls the API once.
    """
    if cache_key in st.session_state:
        return st.session_state.get(cache_key)

    _sys = (
        "You are advising a logistics manager in India. "
        "CRITICAL: never do arithmetic yourself — all numbers are pre-computed. "
        "Use every figure exactly as provided. 2-3 sentences only. "
        "No bullet points. No jargon."
    )
    _msgs = [{"role": "user", "content": user_prompt}]
    _res  = None

    _oai = _os.environ.get("OPENAI_API_KEY", "").strip()
    if _oai:
        try:
            _r = _req.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {_oai}",
                         "Content-Type": "application/json"},
                json={"model": "gpt-4o-mini", "max_tokens": max_tokens,
                      "temperature": 0.3,
                      "messages": [{"role": "system", "content": _sys}] + _msgs},
                timeout=15,
            )
            if _r.status_code == 200:
                _res = _r.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            pass

    if not _res:
        _gk = _os.environ.get("GROQ_API_KEY", "").strip()
        if _gk:
            try:
                _r = _req.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {_gk}",
                             "Content-Type": "application/json"},
                    json={"model": "llama-3.3-70b-versatile",
                          "max_tokens": max_tokens, "temperature": 0.3,
                          "messages": [{"role": "system", "content": _sys}] + _msgs},
                    timeout=15,
                )
                if _r.status_code == 200:
                    _res = _r.json()["choices"][0]["message"]["content"].strip()
            except Exception:
                pass

    st.session_state[cache_key] = _res
    return _res


def _ai_card(title: str, icon: str, border_color: str, body: str | None):
    """Render a small AI insight card. Shows 'Not applicable' when body is None."""
    text = body or "<span style='color:#94a3b8'>Not applicable for this load.</span>"
    st.markdown(
        f"<div style='background:#f8fafc;border-left:4px solid {border_color};"
        f"border-radius:6px;padding:12px 14px;font-size:12.5px;color:#1e293b'>"
        f"<div style='font-weight:700;color:{border_color};margin-bottom:6px'>"
        f"{icon} {title}</div>"
        + text + "</div>",
        unsafe_allow_html=True,
    )


# daily_cost_inr: conservative vehicle + driver cost per operating day (Indian market, 2026)
VEHICLES = [
    {
        "name": "Tata Ace / Ace Gold",
        "type": "SCV · Last Mile",
        "l_ft": 7.0, "w_ft": 4.8, "h_ft": 4.8,
        "payload_kg": 900,  "daily_cost_inr": 1200,
        "icon": "🛺",
        "best_for": "Dense urban lanes, FMCG, documents. Hits payload before filling space on heavy goods.",
    },
    {
        "name": "Ashok Leyland Dost",
        "type": "LCV · Last Mile",
        "l_ft": 7.0, "w_ft": 4.8, "h_ft": 4.8,
        "payload_kg": 1200, "daily_cost_inr": 1500,
        "icon": "🚐",
        "best_for": "Same box as Tata Ace, higher payload. Heavier FMCG runs and mixed parcels.",
    },
    {
        "name": "Ashok Leyland Bada Dost",
        "type": "LCV · Mid Mile",
        "l_ft": 9.5, "w_ft": 5.5, "h_ft": 5.0,
        "payload_kg": 2000, "daily_cost_inr": 1800,
        "icon": "🚐",
        "best_for": "Mixed loads that overflow an Ace. Bridges SCV and ICV scale.",
    },
    {
        "name": "Mahindra Bolero Pickup",
        "type": "LCV · Last/Rural Mile",
        "l_ft": 8.0, "w_ft": 5.0, "h_ft": 4.8,
        "payload_kg": 1500, "daily_cost_inr": 1600,
        "icon": "🚙",
        "best_for": "Rigid floor for heavy point-loads. White goods, construction, dense rural cargo.",
    },
    {
        "name": "Eicher 10.90 — 14 ft",
        "type": "ICV · Mid Mile",
        "l_ft": 14.0, "w_ft": 6.0, "h_ft": 6.5,
        "payload_kg": 3750, "daily_cost_inr": 2800,
        "icon": "🚛",
        "best_for": "Hub-to-hub consolidation. Electronics cube out here before weighing out.",
    },
    {
        "name": "Eicher 10.90 — 17 ft",
        "type": "ICV · Mid Mile",
        "l_ft": 17.0, "w_ft": 6.0, "h_ft": 7.0,
        "payload_kg": 5000, "daily_cost_inr": 3200,
        "icon": "🚛",
        "best_for": "Maximum mid-mile volume. Use when the 14-ft cubes out before the load ends.",
    },
]


PRESETS = {
    "Custom — enter your own dimensions": None,
    "FMCG — HUL Soap Carton (Dove/Pears, 72-bar master)":
        {"l": 43.0, "w": 29.5, "h": 15.0, "wt": 9.5,
         "industry": "fmcg"},
    "FMCG — Marico Oil Carton (5-ply, 10-25 kg liquid)":
        {"l": 50.8, "w": 35.5, "h": 33.0, "wt": 18.0,
         "industry": "fmcg"},
    "Electronics — Samsung 32\" LED TV":
        {"l": 80.8, "w": 51.6, "h": 13.0, "wt": 5.7,
         "industry": "electronics"},
    "Electronics — Samsung 55\" UHD TV":
        {"l": 139.6, "w": 85.2, "h": 15.8, "wt": 22.6,
         "industry": "electronics"},
    "Electronics — Samsung 12 kg Front Load Washer":
        {"l": 68.4, "w": 90.0, "h": 70.1, "wt": 74.5,
         "industry": "electronics"},
    "Apparel — Myntra Box (footwear / small orders)":
        {"l": 26.0, "w": 19.0, "h": 19.0, "wt": 0.8,
         "industry": "apparel"},
    "Apparel — Myntra Poly-Mailer MPB7 (soft goods, flat-packed)":
        {"l": 53.3, "w": 43.1, "h": 3.0, "wt": 0.3,
         "industry": "apparel"},
    "Parcel — Small Box (documents / accessories)":
        {"l": 25.0, "w": 20.0, "h": 10.0, "wt": 0.5,
         "industry": "parcel"},
    "Parcel — Medium Box":
        {"l": 40.0, "w": 30.0, "h": 20.0, "wt": 2.0,
         "industry": "parcel"},
    "Parcel — Large Box":
        {"l": 60.0, "w": 45.0, "h": 40.0, "wt": 8.0,
         "industry": "parcel"},
}


DIVISORS = {
    "B2C Standard — Delhivery / Blue Dart / Ekart (÷5000)": 5000,
    "B2B Surface — Delhivery / Blue Dart / Ekart (÷4500)": 4500,
    "Shadowfax Surface (÷4000 — most punitive)": 4000,
}

INDUSTRY_CONTEXT = {
    "fmcg": (
        "FMCG goods like this are **dense** — the vehicle will typically "
        "**weigh out** (hit payload limit) before running out of space. "
        "You will see high weight utilisation and low volume utilisation in the table below. "
        "This is why FMCG distributors prioritise chassis strength over container volume."
    ),
    "electronics": (
        "Electronics are **bulky but light** — the vehicle will typically "
        "**cube out** (fill the cargo bay) before approaching the payload limit. "
        "You will see high volume utilisation and low weight utilisation. "
        "This is why electronics distributors use large-format ICV trucks even for "
        "shipments well under the payload limit."
    ),
    "apparel": (
        "Apparel in rigid boxes creates significant **dead air** — empty space you pay for. "
        "Poly-mailers compress and avoid volumetric penalties; rigid boxes do not. "
        "Check the volumetric weight section — the carrier may be billing "
        "substantially more than the actual weight of the garments."
    ),
    "parcel": (
        "General parcels span a wide density range. "
        "Check whether the volumetric penalty is active below — "
        "if the carrier's dimensional weight exceeds actual weight, "
        "the package is too bulky for its weight and you are paying for empty space."
    ),
}


# ── Cargo adjustment (agentic action with human-in-the-loop) ─────────────────

_ADJUST_KEYWORDS = {
    "adjust", "change", "update", "set", "apply", "switch",
    "use", "send", "ship", "load", "configure",
}
_CARGO_KEYWORDS  = {
    "cargo", "dimension", "detail", "carton", "item", "box",
    "quantity", "weight", "height", "length", "width",
}


def _is_adjust_intent(message: str) -> bool:
    """True if the message is asking to change the cargo inputs."""
    words = set(message.lower().split())
    return bool(words & _ADJUST_KEYWORDS and
                (words & _CARGO_KEYWORDS or
                 any(p.lower().split(" — ")[-1].lower()
                     in message.lower() for p in PRESETS if p)))


def _extract_cargo_from_message(message: str, chat_history: list) -> dict | None:
    """
    Ask the LLM to extract cargo values from the user message + recent chat.
    Returns a dict with keys: preset, l, w, h, wt, qty — or None on failure.
    All returned values are used verbatim in the confirmation card.
    The LLM only parses text, never invents numbers not present in the input.
    """
    import hashlib, json

    # Build a short context from recent chat + current message
    recent = " | ".join(
        m["content"] for m in chat_history[-6:] if m["role"] == "user"
    )
    combined = f"Recent messages: {recent} | Current: {message}"

    _ck = "lo_extract_" + hashlib.md5(combined.encode()).hexdigest()[:12]
    if _ck in st.session_state:
        return st.session_state[_ck]

    preset_list = "\n".join(
        f'  "{k}": L={v["l"]}, W={v["w"]}, H={v["h"]}, wt={v["wt"]} kg'
        for k, v in PRESETS.items() if v is not None
    )

    prompt = (
        f"Extract cargo details from this text:\n{combined}\n\n"
        f"Known carton presets (match by name if mentioned):\n{preset_list}\n\n"
        f"Return ONLY valid JSON with these keys:\n"
        f"  preset: matched preset name string or null\n"
        f"  l: length in cm (float) or null if not found\n"
        f"  w: width in cm (float) or null if not found\n"
        f"  h: height in cm (float) or null if not found\n"
        f"  wt: weight per item in kg (float) or null if not found\n"
        f"  qty: number of items (int) or null if not found\n"
        f"If a preset name is matched, use its exact dimensions. "
        f"Only extract numbers actually stated in the text. "
        f"No preamble. No explanation. Return only the JSON object."
    )

    try:
        raw = _llm_call(prompt, _ck, max_tokens=120)
        if raw:
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            result = json.loads(raw)

            # If preset matched, fill in dimensions from PRESETS
            preset_name = result.get("preset")
            if preset_name and preset_name in PRESETS and PRESETS[preset_name]:
                p = PRESETS[preset_name]
                result["l"]  = result.get("l")  or p["l"]
                result["w"]  = result.get("w")  or p["w"]
                result["h"]  = result.get("h")  or p["h"]
                result["wt"] = result.get("wt") or p["wt"]

            # At least some values must be present to be useful
            if any(result.get(k) for k in ["l", "w", "h", "wt", "qty"]):
                st.session_state[_ck] = result
                return result
    except Exception:
        pass

    st.session_state[_ck] = None
    return None


def _render_cargo_confirmation():
    """
    Render the pending-cargo confirmation card in the sidebar.
    Shows extracted values, lets the user edit them, then applies on confirm.
    This is the human-in-the-loop gate — nothing changes until Apply is clicked.
    """
    pending = st.session_state.get("lo_pending_cargo")
    if not pending:
        return

    st.sidebar.markdown(
        "<div style='background:#e3f2fd;border:1px solid #1565C0;border-radius:8px;"
        "padding:12px;margin:8px 0;font-size:12px;color:#0d47a1'>"
        "<b>📋 Cargo to apply — review and confirm</b></div>",
        unsafe_allow_html=True,
    )

    # Editable fields pre-filled with extracted values
    with st.sidebar.form("lo_confirm_form"):
        if pending.get("preset"):
            st.markdown(
                f"<div style='font-size:11px;color:#1565C0;margin-bottom:4px'>"
                f"Preset: {pending['preset']}</div>",
                unsafe_allow_html=True,
            )
        new_l   = st.number_input("Length (cm)",   1.0, 400.0,
                                   value=float(pending.get("l") or st.session_state.lo_l),
                                   step=0.5)
        new_w   = st.number_input("Width (cm)",    1.0, 400.0,
                                   value=float(pending.get("w") or st.session_state.lo_w),
                                   step=0.5)
        new_h   = st.number_input("Height (cm)",   1.0, 400.0,
                                   value=float(pending.get("h") or st.session_state.lo_h),
                                   step=0.5)
        new_wt  = st.number_input("Weight/item (kg)", 0.1, 1000.0,
                                   value=float(pending.get("wt") or st.session_state.lo_wt),
                                   step=0.1)
        new_qty = st.number_input("Quantity",      1, 50_000,
                                   value=int(pending.get("qty") or st.session_state.lo_qty),
                                   step=1)
        ca, cb = st.columns(2)
        apply   = ca.form_submit_button("✅ Apply",  use_container_width=True)
        cancel  = cb.form_submit_button("✗ Cancel", use_container_width=True)

    if apply:
        st.session_state.lo_l            = float(new_l)
        st.session_state.lo_w            = float(new_w)
        st.session_state.lo_h            = float(new_h)
        st.session_state.lo_wt           = float(new_wt)
        st.session_state.lo_qty          = int(new_qty)
        st.session_state.lo_last_preset  = None  # reset preset selector
        st.session_state.lo_pending_cargo = None
        st.session_state.lo_chat.append({
            "role": "ai",
            "content": (
                f"Done — cargo updated to {new_l:.0f}×{new_w:.0f}×{new_h:.0f} cm, "
                f"{new_wt:.1f} kg/item, {new_qty} items. "
                "The analysis above has refreshed with the new values."
            ),
        })
        st.rerun()

    if cancel:
        st.session_state.lo_pending_cargo = None
        st.session_state.lo_chat.append({
            "role": "ai",
            "content": "No problem — cargo details unchanged.",
        })
        st.rerun()


def _fit(v, il, iw, ih, iwt, qty):
    vl = v["l_ft"] * FT_TO_CM
    vw = v["w_ft"] * FT_TO_CM
    vh = v["h_ft"] * FT_TO_CM
    v_vol = vl * vw * vh
    i_vol = il * iw * ih

    pl = math.floor(vl / il) if il > 0 else 0
    pw = math.floor(vw / iw) if iw > 0 else 0
    ph = math.floor(vh / ih) if ih > 0 else 0
    by_vol = pl * pw * ph
    by_wt  = math.floor(v["payload_kg"] / iwt) if iwt > 0 else 99_999

    fits     = min(by_vol, by_wt)
    lim      = "volume" if by_vol <= by_wt else "weight"
    v_needed = math.ceil(qty / fits) if fits > 0 else None

    vol_pct = (fits * i_vol / v_vol * 100) if v_vol > 0 and fits > 0 else 0
    wt_pct  = (fits * iwt / v["payload_kg"] * 100) if v["payload_kg"] > 0 and fits > 0 else 0

    return {
        "fits": fits, "by_vol": by_vol, "by_wt": by_wt,
        "lim": lim, "v_needed": v_needed,
        "vol_pct": min(vol_pct, 100.0), "wt_pct": min(wt_pct, 100.0),
        "vl": vl, "vh": vh,  # pass through for diagram
    }


def _vehicle_diagram(vl_cm, vh_cm, item_l, item_h, fits_per_layer_l, fits_per_layer_h, fits):
    """
    2D side cross-section: vehicle bay as grey rectangle, items as blue rectangles.
    Drawn to scale using the actual cm dimensions.
    """
    fig = go.Figure()

    # Vehicle bay outline
    fig.add_shape(type="rect", x0=0, y0=0, x1=vl_cm, y1=vh_cm,
                  fillcolor="#E2E8F0", line=dict(color="#94A3B8", width=2))

    # Draw items
    cols = fits_per_layer_l if fits_per_layer_l > 0 else 1
    rows = fits_per_layer_h if fits_per_layer_h > 0 else 1
    count = 0
    for row in range(rows):
        for col in range(cols):
            if count >= fits:
                break
            x0 = col * item_l + 1
            y0 = row * item_h + 1
            x1 = x0 + item_l - 2
            y1 = y0 + item_h - 2
            if x1 <= vl_cm and y1 <= vh_cm:
                fig.add_shape(type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
                              fillcolor="#1A237E", opacity=0.75,
                              line=dict(color="#0D47A1", width=1))
            count += 1

    # Dimension labels
    fig.add_annotation(x=vl_cm / 2, y=-8, text=f"{vl_cm:.0f} cm",
                       showarrow=False, font=dict(size=10, color="#64748B"))
    fig.add_annotation(x=-12, y=vh_cm / 2, text=f"{vh_cm:.0f} cm",
                       showarrow=False, font=dict(size=10, color="#64748B"),
                       textangle=-90)

    fig.update_layout(
        height=200, margin=dict(l=30, r=10, t=10, b=25),
        xaxis=dict(visible=False, range=[-15, vl_cm + 10]),
        yaxis=dict(visible=False, range=[-15, vh_cm + 10],
                   scaleanchor="x", scaleratio=1),
        plot_bgcolor="white", paper_bgcolor="white",
        showlegend=False,
    )
    return fig



# ── Fleet overview cards (Zone 1) ─────────────────────────────────────────────

def render_fleet_overview():
    """
    Brief fleet reference grid shown at the top of the Load Optimizer page.
    Gives the client a "see what you have" moment before entering cargo details.
    Three cards per row, each showing the vehicle's key logistics parameters.
    """
    st.markdown("#### 🚛 Your Fleet")
    st.caption(
        "Reference specs for each vehicle — dimensions, payload, and daily cost. "
        "The analysis below will show you exactly how your cargo fits across these options."
    )

    rows = [VEHICLES[:3], VEHICLES[3:]]
    for row in rows:
        cols = st.columns(len(row))
        for col, v in zip(cols, row):
            vl = round(v["l_ft"] * FT_TO_CM)
            vw = round(v["w_ft"] * FT_TO_CM)
            vh = round(v["h_ft"] * FT_TO_CM)
            col.markdown(
                f"<div style='background:white;border:1px solid #E2E8F0;border-radius:8px;"
                f"padding:12px;margin-bottom:8px;font-size:12px'>"
                f"<div style='font-size:20px;margin-bottom:4px'>{v['icon']}</div>"
                f"<div style='font-weight:700;font-size:13px;color:#1A237E'>{v['name']}</div>"
                f"<div style='color:#64748b;margin:2px 0'>{v['type']}</div>"
                f"<div style='color:#374151;margin-top:6px'>"
                f"Bay: {vl}×{vw}×{vh} cm<br>"
                f"Payload: {v['payload_kg']:,} kg<br>"
                f"Daily: ₹{v['daily_cost_inr']:,}"
                f"</div></div>",
                unsafe_allow_html=True,
            )

    st.markdown("---")


# ── Copilot sidebar ───────────────────────────────────────────────────────────

_CHIP_FALLBACK = {
    "billing":   ["What carton height eliminates the penalty?",
                  "What's the annual saving if I fix packaging?",
                  "Which carrier has the lowest volumetric rate?"],
    "vehicle":   ["What's the daily cost difference between options?",
                  "How many vehicles for double this quantity?",
                  "Which vehicle handles fragile stacking constraints?"],
    "packaging": ["What dimensions make this load penalty-free?",
                  "How does item density affect vehicle choice?",
                  "Can poly-mailers reduce my billing weight?"],
    "default":   ["Which vehicle is most cost-efficient for this cargo?",
                  "How much does adding 100 units change the recommendation?",
                  "What is my cost per item at full vehicle capacity?"],
}


def _static_chips(question: str, answer: str) -> list:
    """Keyword-mapped static fallback chips when LLM follow-up call fails."""
    text = (question + " " + answer).lower()
    for kw in ["billing", "penalty", "volumetric"]:
        if kw in text:
            return _CHIP_FALLBACK["billing"]
    for kw in ["vehicle", "eicher", "ace", "dost", "bolero"]:
        if kw in text:
            return _CHIP_FALLBACK["vehicle"]
    for kw in ["packaging", "carton", "poly", "height", "dimension"]:
        if kw in text:
            return _CHIP_FALLBACK["packaging"]
    return _CHIP_FALLBACK["default"]


def _layer2_chips(question: str, answer: str) -> list:
    """
    Layer 2: lightweight LLM call to generate contextual follow-up chips.
    Falls back to keyword-mapped static chips on any failure.
    """
    import hashlib, json
    _ck = "lo_chips_" + hashlib.md5((question + answer).encode()).hexdigest()[:10]
    if _ck in st.session_state:
        return st.session_state[_ck]

    _prompt = (
        f"Question: {question}\nAnswer: {answer[:300]}\n\n"
        f"Generate exactly 3 short follow-up questions (under 10 words each) "
        f"a logistics manager would ask next. Return ONLY a JSON array of 3 strings. "
        f"No preamble. No explanation."
    )
    try:
        raw = _llm_call(_prompt, _ck + "_gen", max_tokens=80)
        if raw:
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            chips = json.loads(raw)
            if isinstance(chips, list) and len(chips) >= 2:
                result = [str(c) for c in chips[:3]]
                st.session_state[_ck] = result
                return result
    except Exception:
        pass

    result = _static_chips(question, answer)
    st.session_state[_ck] = result
    return result


def _context_aware_chips() -> list:
    """
    Layer 1: Python scans live session state to generate chips.
    Ranks by business impact — billing penalty surfaced first if active.
    """
    analysis = st.session_state.get("lo_last_analysis", {})
    if not analysis:
        return [
            "Which vehicle fits 200 standard boxes (40×30×20 cm, 2 kg)?",
            "What is the Eicher 14-ft maximum payload in kg?",
            "How many Tata Aces do I need for 500 items at 5 kg each?",
        ]

    chips = []
    vol_penalty   = analysis.get("vol_penalty", False)
    lim           = analysis.get("lim", "volume")
    v_name        = analysis.get("rec_name", "")
    v_needed      = analysis.get("v_needed", 1)
    fits          = analysis.get("fits", 0)
    quantity      = analysis.get("quantity", 0)
    annual_pen    = analysis.get("annual_penalty", 0)
    unused        = max(0, fits * v_needed - quantity)

    if vol_penalty and annual_pen > 0:
        chips.append(
            f"How much would switching to poly-mailers save "
            f"vs the current ₹{annual_pen:,.0f} annual penalty?"
        )
    if lim == "volume" and v_needed > 1:
        chips.append(
            f"What single vehicle handles all {quantity} items "
            f"instead of {v_needed} {v_name}s?"
        )
    if unused > 20:
        chips.append(
            f"I have {unused} unused slots in the {v_name} — "
            f"what additional cargo could I add?"
        )
    if lim == "weight":
        chips.append(
            f"My load weighs out at {analysis.get('wt_pct', 0):.0f}% payload — "
            f"what lighter alternative fits more units?"
        )
    if len(chips) < 3:
        chips.append(
            "What is the cost per item if I increase batch size by 20%?"
        )

    return chips[:4]


def _build_context() -> str:
    """
    Build a structured facts sheet from session state for the copilot.
    All arithmetic is pre-computed here — the LLM only narrates.
    """
    a = st.session_state.get("lo_last_analysis", {})
    if not a:
        lines = ["NO CARGO ANALYSIS YET — client has not entered cargo details."]
        lines += ["", "FLEET REFERENCE:"]
        for v in VEHICLES:
            vl = round(v["l_ft"] * FT_TO_CM)
            vw = round(v["w_ft"] * FT_TO_CM)
            vh = round(v["h_ft"] * FT_TO_CM)
            lines.append(
                f"  {v['name']}: bay {vl}×{vw}×{vh} cm, "
                f"payload {v['payload_kg']} kg, ₹{v['daily_cost_inr']:,}/day"
            )
        return "\n".join(lines)

    lines = [
        "CURRENT CARGO:",
        f"  Preset: {a.get('preset_name','custom')}",
        f"  Dimensions: {a.get('item_l',0):.0f}×{a.get('item_w',0):.0f}"
        f"×{a.get('item_h',0):.0f} cm",
        f"  Weight per item: {a.get('item_wt',0):.1f} kg",
        f"  Quantity: {a.get('quantity',0)} items",
        f"  Total actual weight: {a.get('total_act',0):,.0f} kg",
        "",
        "VOLUMETRIC BILLING:",
        f"  Divisor: {a.get('divisor',5000)} (carrier pricing mode)",
        f"  Volumetric weight per item: {a.get('vol_wt_per',0):.2f} kg",
        f"  Penalty active: {'YES' if a.get('vol_penalty') else 'NO'}",
    ]
    if a.get("vol_penalty"):
        lines += [
            f"  Extra billed weight per dispatch: {a.get('penalty_batch_kg',0):.0f} kg",
            f"  Extra cost per dispatch: ₹{a.get('penalty_cost_rs',0):,}",
            f"  Monthly penalty (22 dispatches): ₹{a.get('monthly_penalty',0):,}",
            f"  Annual penalty: ₹{a.get('annual_penalty',0):,}",
            f"  Fix: reduce item height to {a.get('target_h_bill',0):.0f} cm "
            f"eliminates penalty",
        ]

    lines += [
        "",
        "RECOMMENDED VEHICLE:",
        f"  {a.get('rec_name','—')} ({a.get('rec_type','—')})",
        f"  Fits: {a.get('fits',0)} items per vehicle",
        f"  Constraint: {a.get('lim','—')}-limited",
        f"  Bay used: {a.get('vol_pct',0):.0f}% | Payload: {a.get('wt_pct',0):.0f}%",
        f"  Vehicles needed: {a.get('v_needed',1)}",
        f"  Daily cost: ₹{a.get('rec_daily_cost',0):,}",
        f"  Cost per item (current batch): ₹{a.get('cpi',0):.2f}",
        f"  Cost per item (full capacity): ₹{a.get('cpi_full',0):.2f}",
        "",
        "ALL VEHICLES:",
    ]
    for v in VEHICLES:
        vl = round(v["l_ft"] * FT_TO_CM)
        vw = round(v["w_ft"] * FT_TO_CM)
        vh = round(v["h_ft"] * FT_TO_CM)
        lines.append(
            f"  {v['name']}: bay {vl}×{vw}×{vh} cm, "
            f"payload {v['payload_kg']} kg, ₹{v['daily_cost_inr']:,}/day"
        )

    return "\n".join(lines)


def render_load_copilot_sidebar():
    """
    AI copilot sidebar for the Load Optimizer standalone page.

    Architecture (from Torrent pharma pattern):
    - Layer 1: Python scans live session state, surfaces context-aware chips
      before the client types anything.
    - Layer 2: After each answer, a lightweight LLM call generates 3 contextual
      follow-up chips. Static keyword-mapped fallback if LLM fails.
    - Math guard: all numbers pre-computed in Python. LLM only narrates.
    """
    import hashlib

    if "lo_chat" not in st.session_state:
        st.session_state.lo_chat = []
    if "lo_follow_chips" not in st.session_state:
        st.session_state.lo_follow_chips = []
    if "lo_pending_cargo" not in st.session_state:
        st.session_state.lo_pending_cargo = None

    ctx = _build_context()

    st.sidebar.markdown(
        "<div style='background:linear-gradient(135deg,#1A237E,#283593);"
        "color:white;padding:12px 14px;border-radius:8px;margin-bottom:12px'>"
        "<div style='font-size:14px;font-weight:700'>🤖 Load AI</div>"
        "<div style='font-size:11px;opacity:0.85;margin-top:2px'>"
        "Ask about cargo, vehicles, or billing</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    def _ask(question: str):
        """Handle a question: detect cargo adjustment intent or call LLM."""
        # ── Cargo adjustment: human-in-the-loop agentic flow ─────────────────
        if _is_adjust_intent(question):
            st.session_state.lo_chat.append({"role": "user", "content": question})
            extracted = _extract_cargo_from_message(
                question, st.session_state.lo_chat
            )
            if extracted:
                st.session_state.lo_chat.append({
                    "role": "ai",
                    "content": (
                        "I can do that. Here are the values I found — "
                        "review them below and click Apply to update the form. "
                        "Nothing changes until you confirm."
                    ),
                })
                st.session_state.lo_pending_cargo = extracted
                st.session_state.lo_follow_chips  = []
            else:
                st.session_state.lo_chat.append({
                    "role": "ai",
                    "content": (
                        "I can adjust the cargo details for you — "
                        "could you share the values? "
                        "For example: dimensions in cm (L×W×H), "
                        "weight per item in kg, and number of items."
                    ),
                })
            st.rerun()
            return

        # ── Normal answer ─────────────────────────────────────────────────────
        import hashlib as _h2
        _ck = "lo_ans_" + _h2.md5(
            (question + ctx[:200]).encode()
        ).hexdigest()[:12]

        system = (
            "You are a logistics advisor specialising in Indian last-mile delivery. "
            "CRITICAL: never do arithmetic yourself — all numbers in the context are "
            "pre-computed. Use them exactly as given. "
            "Answer in 2-4 sentences. Be specific and direct. No bullet points."
        )
        user = (
            f"FACTS (pre-computed, use verbatim):\n{ctx}\n\n"
            f"QUESTION: {question}"
        )

        answer = _llm_call(user, _ck, max_tokens=300)
        if not answer:
            answer = (
                "I need either an OpenAI or Groq API key to answer that. "
                "Add OPENAI_API_KEY or GROQ_API_KEY to your .env file."
            )

        st.session_state.lo_chat.append({"role": "user", "content": question})
        st.session_state.lo_chat.append({"role": "ai",   "content": answer})
        st.session_state.lo_follow_chips = _layer2_chips(question, answer)
        st.rerun()

    # Layer 1 chips (only when no conversation yet)
    if not st.session_state.lo_chat:
        chips = _context_aware_chips()
        for i, chip in enumerate(chips):
            if st.sidebar.button(chip, key=f"lo_chip_{i}",
                                  use_container_width=True):
                _ask(chip)

    # Conversation history (last 3 exchanges = 6 messages)
    history = st.session_state.lo_chat[-6:]
    for msg in history:
        if msg["role"] == "user":
            st.sidebar.markdown(
                f"<div style='background:#EEF2FF;border-radius:6px;"
                f"padding:8px 10px;font-size:12px;margin:4px 0;color:#1A237E'>"
                f"<b>You:</b> {msg['content']}</div>",
                unsafe_allow_html=True,
            )
        else:
            st.sidebar.markdown(
                f"<div style='background:#F0FDF4;border-radius:6px;"
                f"padding:8px 10px;font-size:12px;margin:4px 0;color:#1e293b'>"
                f"{msg['content']}</div>",
                unsafe_allow_html=True,
            )

    # Layer 2 follow-up chips (after conversation)
    if st.session_state.lo_chat and st.session_state.lo_follow_chips:
        st.sidebar.markdown(
            "<div style='font-size:11px;color:#64748b;margin:6px 0 2px'>Follow-up:</div>",
            unsafe_allow_html=True,
        )
        for i, chip in enumerate(st.session_state.lo_follow_chips):
            if st.sidebar.button(chip, key=f"lo_fchip_{i}",
                                  use_container_width=True):
                _ask(chip)

    # Confirmation card (human-in-the-loop)
    _render_cargo_confirmation()

    # Text input
    st.sidebar.markdown(
        "<div style='height:6px'></div>",
        unsafe_allow_html=True,
    )
    with st.sidebar.form("lo_copilot_form", clear_on_submit=True):
        q = st.text_input("Ask anything…", key="lo_q_input",
                          label_visibility="collapsed",
                          placeholder="Ask anything about this load…")
        submitted = st.form_submit_button("Ask →", use_container_width=True)
        if submitted and q.strip():
            _ask(q.strip())

    if st.session_state.lo_chat:
        if st.sidebar.button("↺ Clear conversation",
                              use_container_width=True, key="lo_clear"):
            st.session_state.lo_chat = []
            st.session_state.lo_follow_chips = []
            st.rerun()


def render_load_optimizer():
    """
    Main Load Optimizer content — Zone 1 fleet overview + Zone 2 cargo analysis.
    Called from the standalone Load Optimisation page in app.py.
    Stores computed results in st.session_state.lo_last_analysis after each
    analysis run so the sidebar copilot can read them on the next render.
    """

    render_fleet_overview()

    # Initialise session state keys
    for k, v in [("lo_l", 40.0), ("lo_w", 30.0), ("lo_h", 20.0),
                 ("lo_wt", 2.0), ("lo_last_preset", None), ("lo_qty", 50)]:
        if k not in st.session_state:
            st.session_state[k] = v

    st.markdown(
        "<div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;"
        "padding:14px 18px;margin-bottom:18px;font-size:13px;color:#374151'>"
        "Enter your cargo below. The system shows which vehicles from the Indian "
        "last-mile and mid-mile fleet can carry your shipment, whether the load is "
        "<b>volume-constrained</b> (cubes out) or <b>weight-constrained</b> (weighs out), "
        "and what the carrier will bill based on volumetric weight."
        "</div>",
        unsafe_allow_html=True,
    )

    # ── Cargo input ───────────────────────────────────────────────────────────
    st.markdown("#### 📦 Cargo Details")

    preset_name = st.selectbox(
        "Carton type",
        options=list(PRESETS.keys()),
        index=0,
        key="lo_preset_sel",
    )
    preset = PRESETS[preset_name]

    # Update dimension fields when preset changes — must happen BEFORE widgets render
    if preset is not None and st.session_state.lo_last_preset != preset_name:
        st.session_state.lo_l  = float(preset["l"])
        st.session_state.lo_w  = float(preset["w"])
        st.session_state.lo_h  = float(preset["h"])
        st.session_state.lo_wt = float(preset["wt"])
        st.session_state.lo_last_preset = preset_name
        st.rerun()

    if preset and "industry" in preset:
        st.info(INDUSTRY_CONTEXT.get(preset["industry"], ""))

    c1, c2, c3 = st.columns(3)
    c4, c5     = st.columns(2)

    with c1:
        item_l = st.number_input("Length (cm)", 1.0, 400.0, step=0.5, key="lo_l")
    with c2:
        item_w = st.number_input("Width (cm)",  1.0, 400.0, step=0.5, key="lo_w")
    with c3:
        item_h = st.number_input("Height (cm)", 1.0, 400.0, step=0.5, key="lo_h")
    with c4:
        item_wt = st.number_input("Weight per item (kg)", 0.1, 1000.0, step=0.1, key="lo_wt")
    with c5:
        quantity = st.number_input("Number of items", 1, 50_000,
                                   value=int(st.session_state.lo_qty),
                                   step=1, key="lo_qty")

    divisor_label = st.selectbox(
        "Carrier pricing mode",
        options=list(DIVISORS.keys()),
        index=0,
    )
    divisor = DIVISORS[divisor_label]

    st.markdown("---")

    # ── Volumetric weight ─────────────────────────────────────────────────────
    st.markdown("#### 💰 Volumetric Weight Analysis")

    vol_wt_per  = (item_l * item_w * item_h) / divisor
    chargeable  = max(item_wt, vol_wt_per)
    total_act   = item_wt * quantity
    total_chg   = chargeable * quantity
    vol_penalty = vol_wt_per > item_wt

    vm1, vm2, vm3 = st.columns(3)
    vm1.metric("Actual weight (total)",
               f"{total_act:,.1f} kg",
               delta=f"{item_wt:.1f} kg per item", delta_color="off")
    vm2.metric("Volumetric weight (per item)",
               f"{vol_wt_per:.2f} kg",
               delta="billing basis ↑" if vol_penalty else "below actual — no penalty",
               delta_color="inverse" if vol_penalty else "off")
    vm3.metric("Chargeable weight (total)",
               f"{total_chg:,.1f} kg",
               delta=(f"+{total_chg - total_act:,.1f} kg penalty"
                      if vol_penalty else "= actual weight"),
               delta_color="inverse" if vol_penalty else "off")

    if vol_penalty:
        st.markdown(
            f"<div style='background:#fff3e0;border-left:4px solid #e65100;"
            f"border-radius:6px;padding:10px 14px;font-size:13px;"
            f"color:#7c2d12;margin-bottom:8px'>"
            f"⚠️ <b>Volumetric penalty active.</b> "
            f"Your packaging is bulky relative to its weight. "
            f"The carrier bills <b>{vol_wt_per:.2f} kg</b> per item instead of the actual "
            f"<b>{item_wt:.1f} kg</b> — that is "
            f"<b>{total_chg - total_act:,.0f} kg</b> of extra billed weight across {quantity} items. "
            f"Switching to a compressed poly-mailer or reducing dead air in the box "
            f"would drop you back to billing by actual weight.</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<div style='background:#e8f5e9;border-left:4px solid #2e7d32;"
            f"border-radius:6px;padding:10px 14px;font-size:13px;"
            f"color:#1b5e20;margin-bottom:8px'>"
            f"✅ <b>No volumetric penalty.</b> "
            f"Your items are dense enough that actual weight ({item_wt:.1f} kg) "
            f"exceeds the dimensional weight ({vol_wt_per:.2f} kg). "
            f"Carrier bills by actual weight — no packaging redesign needed.</div>",
            unsafe_allow_html=True,
        )


    # ── AI: Carrier Billing card (inline with volumetric section) ────────────
    if vol_penalty:
        import hashlib as _hlib
        _CARRIER_RATE    = 45       # ₹45/kg B2C surface freight
        _penalty_per_kg  = round(vol_wt_per - item_wt, 2)
        _penalty_batch   = round(_penalty_per_kg * quantity, 1)
        _penalty_cost_rs = round(_penalty_batch * _CARRIER_RATE)
        _monthly_penalty = _penalty_cost_rs * 22
        _annual_penalty  = _monthly_penalty * 12
        _target_vol      = item_wt * divisor
        _target_h_bill   = round(_target_vol / (item_l * item_w), 1) if item_l * item_w > 0 else item_h
        _bill_h_cut      = round(item_h - _target_h_bill, 1)
        _bill_h_cut_pct  = round(_bill_h_cut / item_h * 100, 1) if item_h > 0 else 0
        _cargo_lbl_vol   = (
            preset_name.split(" — ")[-1] if " — " in preset_name else "custom cargo"
        )
        _p_bill = (
            f"Cargo: {_cargo_lbl_vol} | {quantity} items | "
            f"Actual weight: {item_wt:.1f} kg/item | Volumetric weight: {vol_wt_per:.2f} kg/item\n"
            f"Excess billing: {_penalty_per_kg:.2f} kg/item × {quantity} items = "
            f"{_penalty_batch:.0f} kg per dispatch × ₹{_CARRIER_RATE}/kg = "
            f"₹{_penalty_cost_rs:,} extra per dispatch\n"
            f"Monthly ({22} dispatches): ₹{_monthly_penalty:,} | Annual: ₹{_annual_penalty:,}\n"
            f"Pre-computed fix: reducing item height from {item_h:.0f}cm to "
            f"{_target_h_bill:.0f}cm (a cut of {_bill_h_cut:.0f}cm, {_bill_h_cut_pct:.0f}%) "
            f"would bring volumetric weight below actual weight, eliminating the penalty.\n\n"
            f"In 2-3 sentences: state the annual billing penalty, explain why it exists, "
            f"and give the specific packaging fix using these exact numbers."
        )
        _ck_bill = "lo_bill_" + _hlib.md5(
            f"{item_l}{item_w}{item_h}{item_wt}{quantity}{divisor}".encode()
        ).hexdigest()[:10]
        _ai_card("⚠️ Carrier Billing Alert", "🧾", "#E65100",
                 _llm_call(_p_bill, _ck_bill))


    st.markdown("---")

    # ── Vehicle fit analysis ──────────────────────────────────────────────────
    st.markdown("#### 🚛 Vehicle Fit Analysis")
    st.caption(
        f"{quantity} items · {item_l:.0f} × {item_w:.0f} × {item_h:.0f} cm · "
        f"{item_wt:.1f} kg each · {total_act:,.0f} kg total"
    )

    results = [{**v, **_fit(v, item_l, item_w, item_h, item_wt, quantity)}
               for v in VEHICLES]

    feasible = [r for r in results if r["fits"] > 0]
    recommended = (
        sorted(feasible, key=lambda x: (x["v_needed"], x["payload_kg"]))[0]
        if feasible else None
    )

    # Table
    html = (
        "<table style='width:100%;border-collapse:collapse;"
        "font-size:12px;font-family:sans-serif;margin-bottom:12px'>"
        "<tr style='background:#1A237E;color:white'>"
    )
    for h in ["", "Vehicle", "Type", "Fits (1 veh.)", "Limited by",
              "Bay used %", "Load used %", "Vehicles needed"]:
        html += f"<th style='padding:8px 10px;text-align:left'>{h}</th>"
    html += "</tr>"

    for r in results:
        is_rec = recommended and r["name"] == recommended["name"]
        bg     = "#e8f5e9" if is_rec else "white"
        star   = "⭐" if is_rec else ""

        if r["fits"] == 0:
            html += (
                f"<tr style='background:#fef2f2;border-bottom:1px solid #f1f5f9'>"
                f"<td style='padding:6px 8px'></td>"
                f"<td style='padding:6px 8px;font-weight:600;color:#64748b'>"
                f"{r['icon']} {r['name']}</td>"
                f"<td style='padding:6px 8px;color:#94a3b8'>{r['type']}</td>"
                f"<td colspan='5' style='padding:6px 8px;color:#94a3b8'>"
                f"Item dimensions exceed cargo bay</td></tr>"
            )
        else:
            lim_color = "#e65100" if r["lim"] == "volume" else "#1565C0"
            html += (
                f"<tr style='background:{bg};border-bottom:1px solid #f1f5f9'>"
                f"<td style='padding:6px 8px'>{star}</td>"
                f"<td style='padding:6px 8px;font-weight:600'>"
                f"{r['icon']} {r['name']}</td>"
                f"<td style='padding:6px 8px;color:#64748b'>{r['type']}</td>"
                f"<td style='padding:6px 8px'>{r['fits']}</td>"
                f"<td style='padding:6px 8px;color:{lim_color};font-weight:600'>"
                f"{r['lim'].title()}</td>"
                f"<td style='padding:6px 8px'>{r['vol_pct']:.0f}%</td>"
                f"<td style='padding:6px 8px'>{r['wt_pct']:.0f}%</td>"
                f"<td style='padding:6px 8px;font-weight:600'>"
                f"{'1' if r['v_needed'] == 1 else str(r['v_needed'])}</td>"
                f"</tr>"
            )
    html += "</table>"
    st.markdown(html, unsafe_allow_html=True)

    # Utilisation chart
    names   = [r["name"].replace("Ashok Leyland ", "AL ")
                        .replace("Tata ", "")
                        .replace("Mahindra ", "") for r in results]
    vol_pct = [r["vol_pct"] for r in results]
    wt_pct  = [r["wt_pct"]  for r in results]

    fig_util = go.Figure()
    fig_util.add_trace(go.Bar(name="Bay volume used %", x=names, y=vol_pct,
                              marker_color="#E65100", opacity=0.85))
    fig_util.add_trace(go.Bar(name="Payload used %",   x=names, y=wt_pct,
                              marker_color="#1A237E", opacity=0.85))
    fig_util.add_hline(y=100, line_dash="dot", line_color="#c62828", opacity=0.6)
    fig_util.update_layout(
        barmode="group", height=240,
        margin=dict(l=20, r=20, t=10, b=55),
        plot_bgcolor="#f8fafc", paper_bgcolor="white",
        yaxis=dict(range=[0, 115], title="Utilisation (%)"),
        legend=dict(orientation="h", y=1.1),
        font=dict(size=11),
    )
    st.plotly_chart(fig_util, use_container_width=True)
    st.caption(
        "🟠 Orange bar = cargo bay volume used. 🔵 Blue bar = payload capacity used. "
        "When orange is taller → vehicle cubes out (space is the limit). "
        "When blue is taller → vehicle weighs out (payload is the limit)."
    )

    # ── 2D cross-section diagram ──────────────────────────────────────────────
    if recommended:
        st.markdown("---")
        st.markdown(
            f"#### 📐 Load Diagram — {recommended['icon']} {recommended['name']}"
        )
        st.caption(
            "Side cross-section (length × height) showing items packed in the cargo bay. "
            "Each blue rectangle is one item. Grey is the vehicle interior."
        )

        r     = recommended
        vl_cm = r["l_ft"] * FT_TO_CM
        vh_cm = r["h_ft"] * FT_TO_CM

        per_l = math.floor(vl_cm / item_l) if item_l > 0 else 1
        per_h = math.floor(vh_cm / item_h) if item_h > 0 else 1
        fits_single = min(r["fits"], per_l * per_h)

        fig_diag = _vehicle_diagram(vl_cm, vh_cm, item_l, item_h,
                                    per_l, per_h, fits_single)
        st.plotly_chart(fig_diag, use_container_width=True)

        # Cube-out / weigh-out insight
        if r["lim"] == "volume":
            st.markdown(
                f"<div style='background:#fff3e0;border-left:4px solid #e65100;"
                f"border-radius:6px;padding:10px 14px;font-size:13px;color:#7c2d12'>"
                f"🟠 <b>This load cubes out.</b> The vehicle fills its cargo bay "
                f"({r['vol_pct']:.0f}% full) before reaching its payload limit "
                f"({r['wt_pct']:.0f}% loaded). You have payload headroom but no space. "
                f"Consider the <b>{results[results.index(r)+1]['name']}</b> if available "
                f"— its larger bay may carry the full quantity in one trip."
                f"</div>", unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"<div style='background:#e3f2fd;border-left:4px solid #1565C0;"
                f"border-radius:6px;padding:10px 14px;font-size:13px;color:#0d47a1'>"
                f"🔵 <b>This load weighs out.</b> The vehicle hits its payload limit "
                f"({r['wt_pct']:.0f}% loaded) before filling its cargo bay "
                f"({r['vol_pct']:.0f}% full). You have space to spare but no payload. "
                f"The unused bay volume is economically wasted — this vehicle is "
                f"well-matched to a denser cargo type."
                f"</div>", unsafe_allow_html=True,
            )


        # ── AI: Packaging / Batch Consolidation card ─────────────────────────
        # Only relevant when the load is volume-limited (cubes out).
        # When weight-limited, carton geometry is not the bottleneck — skip.
        if r["lim"] != "volume":
            _ai_card(
                "Packaging Geometry", "📦", "#94a3b8",
                "This load is weight-limited — the vehicle hits its payload "
                "ceiling before filling the bay. Carton dimensions are not "
                "the constraint here. See Fleet Economics below for the "
                "cost-per-item improvement available from larger batches.",
            )
        else:
            import hashlib as _hlib2
            _cargo_lbl_pkg = (
                preset_name.split(" — ")[-1] if " — " in preset_name else "custom cargo"
            )
            _vl_p = r["l_ft"] * FT_TO_CM
            _vw_p = r["w_ft"] * FT_TO_CM
            _vh_p = r["h_ft"] * FT_TO_CM
            _pl   = math.floor(_vl_p / item_l) if item_l > 0 else 0
            _pw   = math.floor(_vw_p / item_w) if item_w > 0 else 0
            _bwt  = math.floor(r["payload_kg"] / item_wt) if item_wt > 0 else 0
            _bvol = r["by_vol"]
            _gap  = (_bwt - _bvol) / max(_bvol, 1) if _bwt > _bvol else 0
            _cap  = r["fits"]
            _daily_c  = r.get("daily_cost_inr", 2000)
            _cpi_now  = round(_daily_c / max(quantity, 1), 2)
            _cpi_full = round(_daily_c / max(_cap, 1), 2)
            _saving   = round((_cpi_now - _cpi_full) / max(_cpi_now, 0.01) * 100)
            _ck_pkg = "lo_pkg_" + _hlib2.md5(
                f"{item_l}{item_w}{item_h}{item_wt}{quantity}{r['name']}".encode()
            ).hexdigest()[:10]

            if _gap > 0.5:
                _p_pkg = (
                    f"Cargo: {_cargo_lbl_pkg} | {quantity} items per run | "
                    f"Vehicle: {r['name']} | Max capacity: {_cap} items\n"
                    f"Unused capacity: {_cap - quantity} items "
                    f"({round((_cap-quantity)/_cap*100) if _cap else 0}% empty)\n"
                    f"Pre-computed costs: ₹{_daily_c:,}/day | "
                    f"₹{_cpi_now:.2f}/item at {quantity} items | "
                    f"₹{_cpi_full:.2f}/item at {_cap} items full capacity\n"
                    f"Increasing from {quantity} to {_cap} items saves {_saving}% cost per item\n\n"
                    f"In 2-3 sentences: explain the financial case for larger batches "
                    f"using these exact numbers."
                )
                _ai_card("📦 Batch Consolidation Opportunity", "📊", "#2e7d32",
                         _llm_call(_p_pkg, _ck_pkg))
            elif _h_cut > 1:
                # Only suggest a packaging change if the cut is meaningful (>1 cm)
                _needed_rows = math.ceil(_bwt / (_pl * _pw)) if _pl * _pw > 0 else 0
                _new_h = math.floor(_vh_p / _needed_rows) if _needed_rows > 0 else item_h
                _h_cut = round(item_h - _new_h, 1)
                _h_cut_pct = round(_h_cut / item_h * 100, 1) if item_h > 0 else 0
                _new_fits = _pl * _pw * _needed_rows if _pl > 0 else _cap
                _p_pkg = (
                    f"Cargo: {_cargo_lbl_pkg} | Vehicle: {r['name']}\n"
                    f"Volume capacity: {_bvol} items | Weight capacity: {_bwt} items\n"
                    f"Pre-computed fix: reducing height from {item_h:.0f}cm to "
                    f"{_new_h:.0f}cm ({_h_cut:.0f}cm cut, {_h_cut_pct:.0f}%) "
                    f"would allow {_new_fits} items, matching the weight limit.\n\n"
                    f"In 2-3 sentences: make a specific practical recommendation "
                    f"using exactly these numbers."
                )
                _ai_card("📦 Packaging Optimisation", "✂️", "#1565C0",
                         _llm_call(_p_pkg, _ck_pkg))
            else:
                _ai_card("📦 Packaging", "📦", "#94a3b8",
                         "Volume and weight capacity are already well-matched "
                         "for this cargo — no packaging redesign needed.")


    # ── Store results for copilot sidebar ────────────────────────────────────
    # The copilot reads lo_last_analysis on the next render to build context.
    if recommended:
        r = recommended
        _CARRIER_RATE_STORE = 45
        _pen_per_kg   = round(vol_wt_per - item_wt, 2) if vol_penalty else 0
        _pen_batch    = round(_pen_per_kg * quantity, 1)
        _pen_cost     = round(_pen_batch * _CARRIER_RATE_STORE)
        _monthly      = _pen_cost * 22
        _annual       = _monthly * 12
        _tgt_h        = round((item_wt * divisor) / (item_l * item_w), 1) if item_l*item_w > 0 else item_h
        _cpi          = round(r.get("daily_cost_inr", 2000) / max(quantity, 1), 2)
        _cpi_full     = round(r.get("daily_cost_inr", 2000) / max(r["fits"], 1), 2)
        st.session_state.lo_last_analysis = {
            "preset_name": preset_name, "item_l": item_l, "item_w": item_w,
            "item_h": item_h, "item_wt": item_wt, "quantity": quantity,
            "divisor": divisor, "vol_wt_per": vol_wt_per, "total_act": total_act,
            "vol_penalty": vol_penalty, "penalty_batch_kg": _pen_batch,
            "penalty_cost_rs": _pen_cost, "monthly_penalty": _monthly,
            "annual_penalty": _annual, "target_h_bill": _tgt_h,
            "rec_name": r["name"], "rec_type": r["type"],
            "fits": r["fits"], "lim": r["lim"], "v_needed": r["v_needed"],
            "vol_pct": r["vol_pct"], "wt_pct": r["wt_pct"],
            "rec_daily_cost": r.get("daily_cost_inr", 2000),
            "cpi": _cpi, "cpi_full": _cpi_full,
            "by_vol": r.get("by_vol", 0), "by_wt": r.get("by_wt", 0),
        }

    # ── Recommendation card ─────────────────────────────────────────────────────
    if recommended:
        r     = recommended
        lim   = r["lim"]
        vn    = r["v_needed"]
        other = "weight" if lim == "volume" else "volume"

        trips_str   = "1 vehicle needed" if vn == 1 else f"{vn} vehicles needed"
        carries_str = "in a single vehicle." if vn == 1 else f"across {vn} vehicles."
        penalty_html = (
            f"<br><br>⚠️ Carrier bills <b>{total_chg:,.0f} kg</b> volumetric "
            f"vs <b>{total_act:,.0f} kg</b> actual — "
            f"<b>{total_chg - total_act:,.0f} kg</b> extra billed weight on this shipment."
        ) if vol_penalty else ""

        st.markdown(
            "<div style='background:#1A237E;color:white;border-radius:8px;"
            "padding:16px 20px;margin-top:4px'>"
            "<div style='font-size:15px;font-weight:700;margin-bottom:6px'>"
            + r["icon"] + "&nbsp; Recommended: " + r["name"]
            + "&nbsp;·&nbsp;" + trips_str
            + "</div>"
            "<div style='font-size:13px;opacity:0.92;line-height:1.7'>"
            "Carries all " + f"{quantity:,}" + " items " + carries_str
            + " <b>" + lim.title() + "-limited</b> — "
            + f"bay {r['vol_pct']:.0f}%, payload {r['wt_pct']:.0f}%. "
            + r["best_for"]
            + penalty_html
            + "</div></div>",
            unsafe_allow_html=True,
        )


        # ── AI: Load Advisory and Fleet Economics ──────────────────────────────
        import hashlib as _hlib3
        _cargo_lbl_rec  = (
            preset_name.split(" — ")[-1] if " — " in preset_name else "custom cargo"
        )
        _daily_c_r = r.get("daily_cost_inr", 2000)
        _cpi_r     = round(_daily_c_r * vn / max(quantity, 1), 2)
        _cpi_full_r= round(_daily_c_r / max(r["fits"], 1), 2)
        _unused_r  = r["fits"] * vn - quantity
        _saving_r  = round((_cpi_r - _cpi_full_r) / max(_cpi_r, 0.01) * 100)
        _hdroom_kg = round(r["payload_kg"] * vn - total_act, 1)
        _hdroom_bay= round(100 - r["vol_pct"], 1)

        _ck_adv = "lo_adv_" + _hlib3.md5(
            f"{item_l}{item_w}{item_h}{item_wt}{quantity}{r['name']}".encode()
        ).hexdigest()[:10]
        _ck_eco = "lo_eco_" + _hlib3.md5(
            f"{item_l}{item_w}{item_h}{item_wt}{quantity}{r['name']}".encode()
        ).hexdigest()[:10]

        _p_adv = (
            f"Cargo: {_cargo_lbl_rec} | {item_l:.0f}×{item_w:.0f}×{item_h:.0f} cm | "
            f"{item_wt:.1f} kg/item | {quantity} items total\n"
            f"Vehicle: {r['name']} ({r['type']}) | {lim}-limited | "
            f"Bay {r['vol_pct']:.0f}% used | Payload {r['wt_pct']:.0f}% used | {vn} vehicle(s)\n"
            f"Payload headroom: {_hdroom_kg} kg | Bay headroom: {_hdroom_bay}%\n\n"
            f"In 2-3 sentences: what the {lim}-constraint reveals about this cargo category, "
            f"why the {r['name']} is the correct vehicle, "
            f"and what the {_hdroom_bay}% bay headroom and {_hdroom_kg} kg payload headroom "
            f"tell a dispatcher about operational flexibility."
        )
        _p_eco = (
            f"Cargo: {_cargo_lbl_rec} | {quantity} items per dispatch | {vn}× {r['name']}\n"
            f"Daily vehicle cost: ₹{_daily_c_r:,} | "
            f"Cost per item now: ₹{_cpi_r:.2f} ({quantity} items) | "
            f"Cost per item at full capacity: ₹{_cpi_full_r:.2f} ({r['fits']} items)\n"
            f"Unused capacity: {_unused_r} items per run ({round(_unused_r/max(r['fits'],1)*100)}% empty)\n"
            f"Filling to capacity saves {_saving_r}% cost per item\n\n"
            f"In 2-3 sentences: explain the fleet economics and the specific financial case "
            f"for increasing batch size. Use exactly these pre-computed numbers."
        )

        ai_l, ai_r = st.columns(2)
        with ai_l:
            _ai_card("Load Profile Advisory", "🧠", "#1565C0",
                     _llm_call(_p_adv, _ck_adv))
        with ai_r:
            _ai_card("Fleet Economics", "📊", "#6A1B9A",
                     _llm_call(_p_eco, _ck_eco))

    else:
        st.error(
            "No vehicle in the fleet can carry a single item at these dimensions. "
            "The item is larger than every vehicle's cargo bay — please check the dimensions."
        )