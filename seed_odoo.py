"""
seed_odoo.py — One-time script to populate Odoo with realistic Indian delivery data
------------------------------------------------------------------------------------
Run once from the route-optimizer_Odoo folder:
    conda activate route-optimizer
    python seed_odoo.py

What it creates:
  - 1 product: "Delivery Parcel"
  - 20 partners (customers) with real Indian addresses across 5 corridors
  - 20 outgoing delivery orders (stock.picking) with weights and scheduled dates

Safe to re-run — checks for existing data before creating.
"""

import xmlrpc.client
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
import random

load_dotenv()

# ── Odoo connection ───────────────────────────────────────────────────────────
URL      = os.getenv("ODOO_URL", "https://ekfrazo.odoo.com")
DB       = os.getenv("ODOO_DB", "ekfrazo")
USERNAME = os.getenv("ODOO_USERNAME")
API_KEY  = os.getenv("ODOO_API_KEY")

if not USERNAME or not API_KEY:
    raise EnvironmentError("ODOO_USERNAME and ODOO_API_KEY must be set in .env")

common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
uid    = common.authenticate(DB, USERNAME, API_KEY, {})
if not uid:
    raise ConnectionError("Odoo authentication failed. Check credentials in .env")

models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")
print(f"✅ Connected to Odoo as UID {uid}")

def odoo(model, method, args=None, kwargs=None):
    return models.execute_kw(DB, uid, API_KEY, model, method,
                              args or [], kwargs or {})

# ── 20 realistic Indian partners across 5 corridors ──────────────────────────
PARTNERS = [
    # Bengaluru corridor (PIN prefix 560)
    {"name": "Rajesh Textiles",        "street": "42 Commercial Street, Shivajinagar",     "city": "Bengaluru", "zip": "560001", "state": "Karnataka"},
    {"name": "Meena Electronics",      "street": "15 Brigade Road, MG Road",               "city": "Bengaluru", "zip": "560025", "state": "Karnataka"},
    {"name": "Suresh Auto Parts",      "street": "88 Old Madras Road, Whitefield",         "city": "Bengaluru", "zip": "560066", "state": "Karnataka"},
    {"name": "Priya Pharma Stores",    "street": "23 Jayanagar 4th Block",                 "city": "Bengaluru", "zip": "560041", "state": "Karnataka"},
    # Chennai corridor (PIN prefix 600)
    {"name": "Chennai Traders Co",     "street": "12 Anna Salai, Triplicane",              "city": "Chennai",   "zip": "600005", "state": "Tamil Nadu"},
    {"name": "Southern Steel Works",   "street": "78 GST Road, Chrompet",                  "city": "Chennai",   "zip": "600044", "state": "Tamil Nadu"},
    {"name": "Lakshmi Garments",       "street": "34 T Nagar, Pondy Bazaar",               "city": "Chennai",   "zip": "600017", "state": "Tamil Nadu"},
    {"name": "KSR Logistics Hub",      "street": "5 Ambattur Industrial Estate",           "city": "Chennai",   "zip": "600058", "state": "Tamil Nadu"},
    # Hyderabad corridor (PIN prefix 500)
    {"name": "Hyderabad Spices Ltd",   "street": "67 Secunderabad Main Road, Bolarum",    "city": "Hyderabad", "zip": "500010", "state": "Telangana"},
    {"name": "Deccan Auto Supplies",   "street": "14 HITEC City, Madhapur",               "city": "Hyderabad", "zip": "500081", "state": "Telangana"},
    {"name": "Nizams Furniture",       "street": "9 Charminar Road, Old City",             "city": "Hyderabad", "zip": "500002", "state": "Telangana"},
    {"name": "Golkonda Ceramics",      "street": "22 Uppal Industrial Area",               "city": "Hyderabad", "zip": "500039", "state": "Telangana"},
    # Mumbai corridor (PIN prefix 400)
    {"name": "Mumbai Marine Exports",  "street": "3 Nariman Point, Churchgate",            "city": "Mumbai",    "zip": "400021", "state": "Maharashtra"},
    {"name": "Dharavi Leather Works",  "street": "56 Dharavi Main Road",                   "city": "Mumbai",    "zip": "400017", "state": "Maharashtra"},
    {"name": "Andheri Auto Zone",      "street": "11 MIDC, Andheri East",                  "city": "Mumbai",    "zip": "400093", "state": "Maharashtra"},
    {"name": "Borivali Plastics",      "street": "78 Link Road, Borivali West",            "city": "Mumbai",    "zip": "400092", "state": "Maharashtra"},
    # Delhi corridor (PIN prefix 110)
    {"name": "Delhi Garment Hub",      "street": "45 Gandhi Nagar, Shahdara",              "city": "Delhi",     "zip": "110031", "state": "Delhi"},
    {"name": "Karol Bagh Electronics", "street": "12 Ajmal Khan Road, Karol Bagh",        "city": "Delhi",     "zip": "110005", "state": "Delhi"},
    {"name": "Okhla Industrial Corp",  "street": "34 Okhla Phase 2 Industrial Area",      "city": "Delhi",     "zip": "110020", "state": "Delhi"},
    {"name": "Connaught Traders",      "street": "7 Connaught Place, Inner Circle",       "city": "Delhi",     "zip": "110001", "state": "Delhi"},
]

# ── Weights per order (kg) ────────────────────────────────────────────────────
WEIGHTS = [12.5, 8.0, 22.0, 5.5, 31.0, 18.5, 9.0, 45.0, 14.0, 27.5,
           6.5, 38.0, 11.0, 19.5, 7.0, 52.0, 23.0, 16.5, 33.0, 10.0]

# ── Step 1: Get or create product ────────────────────────────────────────────
print("\n📦 Setting up product...")
existing_product = odoo("product.product", "search",
    [[["name", "=", "Delivery Parcel"]]])

if existing_product:
    product_id = existing_product[0]
    print(f"   Product already exists (ID: {product_id})")
else:
    product_id = odoo("product.product", "create", [{
        "name":     "Delivery Parcel",
        "type":     "consu",
        "categ_id": 1,
    }])
    print(f"   Created product (ID: {product_id})")

# ── Step 2: Get country India ─────────────────────────────────────────────────
india_ids = odoo("res.country", "search", [[["name", "=", "India"]]])
india_id  = india_ids[0] if india_ids else None

# ── Step 3: Get state IDs ─────────────────────────────────────────────────────
state_cache = {}
def get_state_id(state_name):
    if state_name not in state_cache:
        ids = odoo("res.country.state", "search",
                   [[["name", "=", state_name], ["country_id", "=", india_id]]])
        state_cache[state_name] = ids[0] if ids else None
    return state_cache[state_name]

# ── Step 4: Get outgoing picking type ────────────────────────────────────────
print("\n🏭 Finding warehouse picking type...")
picking_types = odoo("stock.picking.type", "search_read",
    [[["code", "=", "outgoing"], ["warehouse_id", "!=", False]]],
    {"fields": ["id", "name", "warehouse_id"], "limit": 1})

if not picking_types:
    raise RuntimeError("No outgoing picking type found. Make sure Inventory module is set up.")

picking_type_id = picking_types[0]["id"]
print(f"   Using picking type: {picking_types[0]['name']} (ID: {picking_type_id})")

# ── Step 5: Get source location (WH/Output or WH/Stock) ──────────────────────
locations = odoo("stock.location", "search_read",
    [[["usage", "=", "internal"], ["active", "=", True]]],
    {"fields": ["id", "complete_name"], "limit": 1})
src_location_id = locations[0]["id"] if locations else 8  # fallback to stock

dest_location_id = odoo("stock.location", "search",
    [[["usage", "=", "customer"]]])[0]

# ── Step 6: Create partners + delivery orders ─────────────────────────────────
print("\n👥 Creating partners and delivery orders...")
created_partners  = 0
created_pickings  = 0
skipped_partners  = 0

today = datetime.now()

for i, partner_data in enumerate(PARTNERS):
    weight = WEIGHTS[i]

    # Check if partner already exists
    existing = odoo("res.partner", "search",
        [[["name", "=", partner_data["name"]]]])

    if existing:
        partner_id = existing[0]
        skipped_partners += 1
        print(f"   ↩ Partner exists: {partner_data['name']}")
    else:
        state_id = get_state_id(partner_data["state"])
        partner_id = odoo("res.partner", "create", [{
            "name":       partner_data["name"],
            "street":     partner_data["street"],
            "city":       partner_data["city"],
            "zip":        partner_data["zip"],
            "country_id": india_id,
            "state_id":   state_id,
            "customer_rank": 1,
        }])
        created_partners += 1
        print(f"   ✅ Created partner: {partner_data['name']} ({partner_data['zip']})")

    # Check if a picking already exists for this partner today
    existing_picking = odoo("stock.picking", "search",
        [[["partner_id", "=", partner_id],
          ["picking_type_id", "=", picking_type_id],
          ["state", "not in", ["done", "cancel"]]]])

    if existing_picking:
        print(f"      ↩ Delivery order already exists for {partner_data['name']}")
        continue

    # Scheduled date: spread across next 3 days
    scheduled_date = today + timedelta(days=(i % 3) + 1)
    scheduled_str  = scheduled_date.strftime("%Y-%m-%d %H:%M:%S")

    # Create outgoing delivery order
    picking_id = odoo("stock.picking", "create", [{
        "picking_type_id":   picking_type_id,
        "partner_id":        partner_id,
        "location_id":       src_location_id,
        "location_dest_id":  dest_location_id,
        "scheduled_date":    scheduled_str,
        "origin":            f"DeliveryOS-SEED-{i+1:03d}",
        "note":              f"Weight: {weight} kg | Corridor: {partner_data['zip'][:3]}",
    }])

    # Create stock move (product + quantity = weight)
    odoo("stock.move", "create", [{
        "picking_id":        picking_id,
        "product_id":        product_id,
        "product_uom_qty":   weight,
        "location_id":       src_location_id,
        "location_dest_id":  dest_location_id,
    }])

    created_pickings += 1
    print(f"      📦 Created delivery order #{picking_id} — {weight} kg → {partner_data['city']} {partner_data['zip']}")

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ Odoo seed complete
   Partners created  : {created_partners}
   Partners skipped  : {skipped_partners} (already existed)
   Delivery orders   : {created_pickings}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
You can now run the DeliveryOS app and connect to Odoo.
In Odoo, go to Inventory → Transfers to see the created orders.
""")





