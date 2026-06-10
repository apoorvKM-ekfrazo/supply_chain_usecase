# data/forecasting_scenario.py
"""
data/forecasting_scenario.py
----------------------------
Synthetic 2-year weekly demand history generator for the Hierarchical SKU Demand 
Forecasting module.

This module generates a three-level hierarchical time series dataset containing
104 weeks of historical data for the Bengaluru distribution network.
The levels are:
  Level 1: City-wide total ("Total")
  Level 2: Zone-level totals (9 individual zones)
  Level 3: Zone-Category pairs (36 series: 9 zones x 4 categories)

The data model incorporates:
  1. Base daily demand from ZONE_BASE_DEMAND in data/meio_scenario.
  2. Category-specific splits (FMCG 40%, Electronics 25%, Apparel 20%, Home Goods 15%).
  3. Linear growth trends unique to each zone.
  4. Highly articulated Indian seasonal multipliers tied to calendar weeks.
  5. Gaussian random noise for realistic variability.
"""

import numpy as np
import pandas as pd
import streamlit as st
from datetime import date, timedelta
from data.meio_scenario import ZONE_BASE_DEMAND, ZONES

def generate_forecasting_history() -> pd.DataFrame:
    """
    Generate or retrieve 104 weeks of synthetic weekly demand history.
    
    The history ends on the most recent Monday before today.
    Results are cached in st.session_state.forecast_history_df to prevent
    regeneration during the same session.
    
    Returns:
        pd.DataFrame: Long-format DataFrame with columns:
                      ['unique_id', 'ds', 'y', 'zone', 'category']
    """
    # Check session state cache first
    if "forecast_history_df" in st.session_state and st.session_state.forecast_history_df is not None:
        return st.session_state.forecast_history_df

    # Establish timeline: 104 weeks ending on the most recent Monday
    today = date.today()
    days_since_monday = today.weekday()
    last_monday = today - timedelta(days=days_since_monday)
    
    mondays = [last_monday - timedelta(weeks=i) for i in range(104)]
    mondays.reverse()  # Chronological order from oldest to newest

    # SKU Category weights
    categories = ["FMCG", "Electronics", "Apparel", "Home Goods"]
    cat_weights = {
        "FMCG": 0.40,
        "Electronics": 0.25,
        "Apparel": 0.20,
        "Home Goods": 0.15
    }
    
    # Zone-specific monthly linear growth rates
    GROWTH_RATES = {
        "Koramangala": 0.005,
        "Indiranagar": 0.008,
        "Whitefield": 0.021,
        "Electronic City": 0.018,
        "Marathahalli": 0.015,
        "JP Nagar": 0.006,
        "Hebbal": 0.012,
        "Jayanagar": 0.004,
        "MG Road / CBD": 0.003,
    }

    rng = np.random.default_rng(42)
    bottom_rows = []

    # Generate bottom-level series (Zone/Category)
    for zone in ZONES:
        base_demand = ZONE_BASE_DEMAND[zone]
        monthly_growth = GROWTH_RATES[zone]
        # Weekly growth increment assuming 4 weeks per month
        weekly_growth = monthly_growth / 4.0
        
        for cat in categories:
            weight = cat_weights[cat]
            cat_base = base_demand * weight
            unique_id = f"{zone}/{cat}"
            
            for week_idx, m_date in enumerate(mondays):
                ds_str = m_date.isoformat()
                cal_week = m_date.isocalendar().week
                
                # Component 1: Linear Trend
                trend_val = cat_base * (1.0 + weekly_growth * week_idx)
                
                # Component 2: Indian Seasonality Multipliers
                seasonal_multiplier = 1.0
                
                if cal_week == 43:
                    # Diwali week (late October)
                    seasonal_multiplier = 1.85
                elif cal_week in (41, 42):
                    # Two weeks leading up to Diwali
                    seasonal_multiplier = 1.40
                elif cal_week == 12:
                    # Holi week (March)
                    seasonal_multiplier = 1.25
                elif cal_week == 36:
                    # Onam week (August/September) - applies mainly to Hebbal and JP Nagar
                    if zone in ("Hebbal", "JP Nagar"):
                        seasonal_multiplier = 1.20
                elif 24 <= cal_week <= 35:
                    # Heavy monsoon weeks (June through August)
                    if cat == "Electronics":
                        seasonal_multiplier = 0.60
                    elif cat == "FMCG":
                        seasonal_multiplier = 0.90
                    else:
                        seasonal_multiplier = 0.75
                elif 20 <= cal_week <= 23:
                    # Summer holidays (May/June)
                    seasonal_multiplier = 1.10
                elif m_date.month in (11, 12):
                    # Wedding season November through December
                    if cat == "Apparel":
                        seasonal_multiplier = 1.55
                    else:
                        seasonal_multiplier = 1.30
                        
                trended_seasonal = trend_val * seasonal_multiplier
                
                # Component 3: Gaussian Noise (sigma = 8% of trended-seasonal value)
                noise = rng.normal(0, 0.08 * trended_seasonal)
                y_val = max(0.0, trended_seasonal + noise)
                
                bottom_rows.append({
                    "unique_id": unique_id,
                    "ds": ds_str,
                    "y": y_val,
                    "zone": zone,
                    "category": cat
                })

    df_bottom = pd.DataFrame(bottom_rows)

    # Level 2 Aggregation: Zone Totals
    df_zone_totals = df_bottom.groupby(["zone", "ds"])["y"].sum().reset_index()
    df_zone_totals["unique_id"] = df_zone_totals["zone"]
    df_zone_totals["category"] = "Total"

    # Level 1 Aggregation: City-wide Total
    df_city_total = df_bottom.groupby("ds")["y"].sum().reset_index()
    df_city_total["unique_id"] = "Total"
    df_city_total["zone"] = "Total"
    df_city_total["category"] = "Total"

    # Concatenate all 3 levels of the hierarchy
    df_hierarchy = pd.concat([
        df_city_total[["unique_id", "ds", "y", "zone", "category"]],
        df_zone_totals[["unique_id", "ds", "y", "zone", "category"]],
        df_bottom[["unique_id", "ds", "y", "zone", "category"]]
    ], ignore_index=True)

    st.session_state.forecast_history_df = df_hierarchy
    return df_hierarchy