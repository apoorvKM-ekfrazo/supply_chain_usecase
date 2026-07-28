"""
odoo_connector.py — Pulls live delivery orders from Odoo into DeliveryOS
------------------------------------------------------------------------
Produces a DataFrame compatible with Manifest Triage's expected input:
  - address     : full Indian address string with pincode (bharataddress parses this)
  - weight_kg   : parcel weight in kg
  - consignment_id : Odoo picking name (e.g. WH/OUT/00001)
  - customer_name  : partner name (pass-through column)
  - scheduled_date : delivery date (pass-through column)
  - city           : destination city (pass-through column)

Usage inside app.py:
    from odoo_connector import fetch_odoo_manifest
    df = fetch_odoo_manifest()
    if df is not None:
        st.session_state.odoo_manifest_df = df
"""

import os
import xmlrpc.client
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── Connection config (from .env) ─────────────────────────────────────────────
ODOO_URL      = os.getenv("ODOO_URL",      "https://ekfrazo.odoo.com")
ODOO_DB       = os.getenv("ODOO_DB",       "ekfrazo")
ODOO_USERNAME = os.getenv("ODOO_USERNAME", "")
ODOO_API_KEY  = os.getenv("ODOO_API_KEY",  "")


def _get_connection():
    """Authenticate and return (uid, models proxy). Raises on failure."""
    if not ODOO_USERNAME or not ODOO_API_KEY:
        raise EnvironmentError(
            "ODOO_USERNAME and ODOO_API_KEY must be set in .env"
        )
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_API_KEY, {})
    if not uid:
        raise ConnectionError(
            "Odoo authentication failed — check ODOO_USERNAME and ODOO_API_KEY"
        )
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
    return uid, models


def _call(models, uid, model, method, args=None, kwargs=None):
    return models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        model, method,
        args or [], kwargs or {}
    )


def fetch_odoo_manifest(
    states: list = None,
    limit: int = 100,
) -> pd.DataFrame | None:
    """
    Pull outgoing delivery orders from Odoo and return a manifest DataFrame.

    Parameters
    ----------
    states : list of str
        Odoo picking states to include.
        Default: ['draft', 'waiting', 'confirmed', 'assigned', 'ready']
        Use ['done'] to pull completed deliveries for analysis.
    limit  : int
        Max number of orders to pull. Default 100.

    Returns
    -------
    pd.DataFrame with columns:
        consignment_id, address, weight_kg, customer_name,
        scheduled_date, city
    Returns None if connection fails or no orders found.
    """
    if states is None:
        states = ["draft", "waiting", "confirmed", "assigned", "ready"]

    try:
        uid, models = _get_connection()
    except (EnvironmentError, ConnectionError) as e:
        print(f"[OdooConnector] Connection error: {e}")
        return None

    # ── Fetch outgoing pickings ───────────────────────────────────────────────
    domain = [
        ["picking_type_code", "=", "outgoing"],
        ["state", "in", states],
    ]

    try:
        pickings = _call(models, uid, "stock.picking", "search_read",
            [domain],
            {
                "fields": [
                    "name", "partner_id", "scheduled_date",
                    "state", "origin", "note",
                ],
                "limit": limit,
                "order": "scheduled_date asc",
            }
        )
    except Exception as e:
        print(f"[OdooConnector] Failed to fetch pickings: {e}")
        return None

    if not pickings:
        print("[OdooConnector] No delivery orders found in Odoo.")
        return None

    # ── Fetch partner details for all pickings ────────────────────────────────
    partner_ids = list({
        p["partner_id"][0] for p in pickings if p.get("partner_id")
    })

    partners_raw = _call(models, uid, "res.partner", "search_read",
        [[["id", "in", partner_ids]]],
        {"fields": ["id", "name", "street", "city", "zip", "state_id", "country_id"]}
    ) if partner_ids else []

    partner_map = {p["id"]: p for p in partners_raw}

    # ── Fetch stock moves (weights) ───────────────────────────────────────────
    picking_ids = [p["id"] for p in pickings]

    moves_raw = _call(models, uid, "stock.move", "search_read",
        [[["picking_id", "in", picking_ids], ["state", "!=", "cancel"]]],
        {"fields": ["picking_id", "product_uom_qty"]}
    )

    # Sum qty per picking (qty = weight in kg, set during seed)
    weight_map: dict[int, float] = {}
    for move in moves_raw:
        pid = move["picking_id"][0]
        weight_map[pid] = weight_map.get(pid, 0.0) + float(move["product_uom_qty"])

    # ── Build manifest DataFrame ──────────────────────────────────────────────
    rows = []
    for picking in pickings:
        picking_id  = picking["id"]
        partner_ref = picking.get("partner_id")

        if not partner_ref:
            continue  # skip orders with no delivery address

        partner = partner_map.get(partner_ref[0], {})

        # Build full address string — bharataddress needs pincode in the string
        parts = []
        if partner.get("street"): parts.append(partner["street"])
        if partner.get("city"):   parts.append(partner["city"])
        if partner.get("zip"):    parts.append(partner["zip"])
        if partner.get("state_id") and isinstance(partner["state_id"], list):
            parts.append(partner["state_id"][1])

        address = ", ".join(p.strip() for p in parts if p.strip())

        if not address:
            address = partner_ref[1]  # fallback to partner name

        # Scheduled date — format nicely
        sched_raw = picking.get("scheduled_date") or ""
        try:
            sched_dt   = datetime.strptime(sched_raw[:10], "%Y-%m-%d")
            sched_str  = sched_dt.strftime("%d %b %Y")
        except Exception:
            sched_str = sched_raw[:10] if sched_raw else ""

        rows.append({
            "consignment_id":  picking["name"],
            "address":         address,
            "weight_kg":       round(weight_map.get(picking_id, 0.0), 2),
            "customer_name":   partner.get("name", partner_ref[1]),
            "scheduled_date":  sched_str,
            "city":            partner.get("city", ""),
        })

    if not rows:
        print("[OdooConnector] Pickings found but no valid addresses.")
        return None

    df = pd.DataFrame(rows)
    print(f"[OdooConnector] Fetched {len(df)} delivery orders from Odoo.")
    return df


def test_connection() -> tuple[bool, str]:
    """
    Quick connection test. Returns (success: bool, message: str).
    Safe to call from Streamlit without raising exceptions.
    """
    try:
        uid, _ = _get_connection()
        return True, f"Connected to {ODOO_URL} as UID {uid}"
    except EnvironmentError as e:
        return False, f"Config error: {e}"
    except ConnectionError as e:
        return False, f"Auth failed: {e}"
    except Exception as e:
        return False, f"Unexpected error: {e}"


# ── Quick CLI test ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Testing Odoo connection...")
    ok, msg = test_connection()
    print(f"{'✅' if ok else '❌'} {msg}")

    if ok:
        print("\nFetching manifest...")
        df = fetch_odoo_manifest()
        if df is not None:
            print(f"\n{df.to_string(index=False)}")
            print(f"\nColumns: {list(df.columns)}")
            print(f"Rows: {len(df)}")