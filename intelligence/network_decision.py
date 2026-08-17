"""
intelligence/network_decision.py
---------------------------------
AI-powered comparison between MEIO predictions and Route Optimizer results.

This module powers the Network Decision Panel — the core of the two-way
communication loop between the Network Intelligence and Route Optimizer pages.

The panel answers one question: did the simulation validate the prediction?

MEIO predicted adding Marathahalli Hub would save ₹8.4L per year.
The Route Optimizer ran from two depots and produced actual metrics.
This module computes the gap between prediction and reality, then uses
GPT-4o-mini to give a plain-English verdict that a non-technical
operations manager can act on.

The AI prompt is carefully structured to:
  1. Give the model all the numbers it needs in one shot
  2. Ask for three specific outputs (verdict, recommendation, caveat)
  3. Keep the response short enough to display in a panel

Why an LLM here and not just a threshold check?
  A 15% gap between predicted and actual saving could mean:
    - The prediction model was slightly optimistic (acceptable)
    - Traffic on a specific corridor adds more time than haversine suggests
    - The fleet split chosen by the solver was suboptimal
    - The zone assignment logic in MEIO was wrong
  These have different implications for whether to accept the depot.
  The LLM can reason about which interpretation is most likely given the
  specific pattern of which metrics diverged and in which direction.
  A threshold check cannot do this.
"""

import os
import json
import requests
from typing import Optional, Dict


OPENAI_URL   = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = "gpt-4o-mini"


def _call_groq(prompt: str) -> Optional[str]:
    """Call the OpenAI API and return the response text."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    try:
        resp = requests.post(
            OPENAI_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model":       OPENAI_MODEL,
                "max_tokens":  400,
                "temperature": 0.3,   # low temperature for analytical consistency
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=20,
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"Network decision AI: {e}")
    return None


def compute_comparison(
    single_result:    dict,
    two_depot_result: dict,
    meio_prediction:  dict,
    fuel_cost_per_km: float = 7.23,
    hourly_wage:      float = 150.0,
    working_days:     int   = 264,
) -> dict:
    """
    Compute the actual vs predicted comparison metrics.

    Returns a dict with everything the Network Decision Panel needs to render
    the comparison table and feed the AI analysis.

    single_result:    OR-Tools result from the last single-depot run
    two_depot_result: OR-Tools result from the two-depot run
    meio_prediction:  dict with keys from the MEIO placement analysis
    """
    def _daily_cost(result: dict) -> float:
        # Use total operational cost per km matching MEIO's warehouse_optimizer.py
        # formula: fuel + driver wage (₹18/km) × road distance multiplier (1.4×)
        TOTAL_COST_PER_KM = fuel_cost_per_km + 18.0
        ROAD_MULTIPLIER   = 1.4
        total_km   = sum(r.get("total_distance_km", 0) for r in result["routes"].values())
        route_cost = total_km * TOTAL_COST_PER_KM * ROAD_MULTIPLIER
        total_ot   = sum(r.get("overtime_min", 0)      for r in result["routes"].values())
        ot_cost    = (total_ot / 60) * hourly_wage * 1.5
        return round(route_cost + ot_cost, 0)

    single_dist      = single_result.get("total_distance_km", 0)
    two_depot_dist   = two_depot_result.get("total_distance_km", 0)
    single_overtime  = single_result.get("total_overtime_min", 0)
    two_depot_overtime = two_depot_result.get("total_overtime_min", 0)
    single_tw_viol   = single_result.get("total_tw_violations", 0)
    two_depot_tw_viol = two_depot_result.get("total_tw_violations", 0)

    single_daily_cost    = _daily_cost(single_result)
    two_depot_daily_cost = _daily_cost(two_depot_result)

    actual_daily_saving  = single_daily_cost - two_depot_daily_cost
    actual_annual_saving = round(actual_daily_saving * working_days, 0)
    annual_facility_cost = meio_prediction.get("annual_facility_cost", 0)
    actual_net_saving    = actual_annual_saving - annual_facility_cost

    predicted_net_saving = meio_prediction.get("net_annual_saving", 0)

    # Number of stops in the Route Optimizer run
    stops_served = single_result.get("total_stops_served", 120)
    meio_assumed_stops = 311   # what MEIO's prediction was based on
    scale_factor = round(stops_served / meio_assumed_stops, 2)

    # Match percentage: how close did the simulation come to the prediction?
    # We cap at 200% to handle cases where simulator outperforms prediction.
    if predicted_net_saving != 0:
        match_pct = min(200, round(actual_net_saving / predicted_net_saving * 100, 1))
    else:
        match_pct = 100.0 if actual_net_saving >= 0 else 0.0

    # Break-even analysis — how many stops/day does this depot need to pay for itself?
    # Derived from: break_even_stops × (saving_per_stop/day) × working_days = facility_cost
    # This tells the client not just whether the depot is viable today, but when it becomes viable.
    if stops_served > 0 and actual_daily_saving > 0:
        daily_saving_per_stop = actual_daily_saving / stops_served
        break_even_stops = round(annual_facility_cost / (daily_saving_per_stop * working_days))
    else:
        # If the two-depot run was worse than single-depot (negative saving),
        # break-even is theoretically infinite — the depot doesn't help at any scale
        # with the current fleet split. Flag this distinctly from the volume-scaling case.
        daily_saving_per_stop = 0
        break_even_stops = None

    # Months to break-even at a typical Indian logistics growth rate of 12% monthly
    # (conservative for a growing Bengaluru B2B distributor)
    MONTHLY_GROWTH_RATE = 0.12
    if break_even_stops and break_even_stops > stops_served:
        import math
        months_to_breakeven = math.ceil(
            math.log(break_even_stops / stops_served) / math.log(1 + MONTHLY_GROWTH_RATE)
        )
    else:
        months_to_breakeven = 0   # already at or past break-even

    return {
        # Single-depot actuals
        "single_dist_km":       round(single_dist, 1),
        "single_overtime_min":  round(single_overtime, 1),
        "single_tw_violations": single_tw_viol,
        "single_daily_cost":    single_daily_cost,

        # Two-depot actuals
        "two_depot_dist_km":       round(two_depot_dist, 1),
        "two_depot_overtime_min":  round(two_depot_overtime, 1),
        "two_depot_tw_violations": two_depot_tw_viol,
        "two_depot_daily_cost":    two_depot_daily_cost,

        # Deltas (positive = improvement)
        "dist_saving_km":        round(single_dist - two_depot_dist, 1),
        "overtime_saving_min":   round(single_overtime - two_depot_overtime, 1),
        "tw_viol_reduction":     single_tw_viol - two_depot_tw_viol,
        "daily_cost_saving":     round(actual_daily_saving, 0),

        # Annual financials
        "actual_annual_saving":  actual_annual_saving,
        "annual_facility_cost":  annual_facility_cost,
        "actual_net_saving":     actual_net_saving,
        "predicted_net_saving":  predicted_net_saving,
        "match_pct":             match_pct,

        "stops_served":      stops_served,
        "meio_assumed_stops": meio_assumed_stops,
        "scale_factor":       scale_factor,
        "scaled_predicted_saving": round(predicted_net_saving * scale_factor, 0),

        # Context
        "candidate_name":        meio_prediction.get("name", "Proposed Hub"),
        "working_days":          working_days,

        "break_even_stops":      break_even_stops,
        "months_to_breakeven":   months_to_breakeven,
        "daily_saving_per_stop": round(daily_saving_per_stop, 2),
        "monthly_growth_rate":   MONTHLY_GROWTH_RATE,
    }


def generate_ai_verdict(comparison: dict) -> str:
    """
    Call GPT-4o-mini to produce a plain-English verdict on the comparison.

    Returns a string with the AI analysis, or a fallback rule-based verdict
    if the API key is not available.
    """
    c = comparison

    def _fmt_inr(x):
        if abs(x) >= 100_000:
            return f"₹{x/100_000:.1f}L"
        return f"₹{x:,.0f}"

    prompt = f"""You are a logistics network analyst reviewing a warehouse addition decision.

MEIO (Multi-Echelon Inventory Optimisation) predicted:
  - Adding {c['candidate_name']} as a second warehouse
  - Predicted net annual saving after lease: {_fmt_inr(c['predicted_net_saving'])}

Route Optimizer simulation results:
  - Single depot: {c['single_dist_km']}km/day, {_fmt_inr(c['single_daily_cost'])} daily cost, {c['single_overtime_min']:.0f}min overtime, {c['single_tw_violations']} time-window violations
  - Two depots:   {c['two_depot_dist_km']}km/day, {_fmt_inr(c['two_depot_daily_cost'])} daily cost, {c['two_depot_overtime_min']:.0f}min overtime, {c['two_depot_tw_violations']} time-window violations

  - Actual daily cost saving:  {_fmt_inr(c['daily_cost_saving'])}
  - Actual annual saving:      {_fmt_inr(c['actual_annual_saving'])}
  - Annual facility cost:      {_fmt_inr(c['annual_facility_cost'])}
  - Actual net annual saving:  {_fmt_inr(c['actual_net_saving'])}
  - Match vs prediction:       {c['match_pct']}%

Important context: The MEIO prediction assumed {c['meio_assumed_stops']} stops/day 
using a naive routing baseline (dedicated round trips per zone). The Route Optimizer 
demo ran {c['stops_served']} stops/day (scale factor {c['scale_factor']}x) with 
VRP-optimised routing, which is already more efficient than the naive baseline — 
meaning the marginal saving from a warehouse is smaller in the simulation. 
{"Break-even for this hub with optimised routing is approximately " + str(c.get('break_even_stops')) + " stops/day. At " + str(c['stops_served']) + " stops/day the hub is premature; it becomes financially justified as volume grows toward that threshold." if c.get('break_even_stops') else "At current scale the additional depot increases routing cost because the fleet is split too thinly — this location becomes viable as total network volume grows."}

Respond in exactly this format (3 short paragraphs, plain English, no bullet points, no headers):

VERDICT: [One sentence stating whether the simulation validates the prediction and by how much.]

RECOMMENDATION: [One sentence — Accept, Reject, or Investigate — with the key reason.]

CAVEAT: [One sentence on the most important thing the operations team should watch for if they proceed.]"""

    ai_text = _call_groq(prompt)

    if ai_text:
        return ai_text

    # Fallback: rule-based verdict when no API key is present
    # Check whether the scale difference alone explains the negative result.
    # If the scaled prediction (adjusted to demo volume) is also negative,
    # the warehouse genuinely doesn't pay off even at full scale — real Reject.
    # If the scaled prediction is close to zero or positive, the result is
    # scale-driven, not a model failure — this is an Investigate case.
    scaled_saving  = c.get("scaled_predicted_saving", c["actual_net_saving"])
    scale_explains = c["scale_factor"] < 0.6 and c["actual_net_saving"] < 0 and scaled_saving > -500_000

    if c["match_pct"] >= 80 and c["actual_net_saving"] > 0:
        verdict = "VERDICT: The simulation confirms the MEIO prediction — actual net saving is within acceptable variance of the forecast."
        rec     = f"RECOMMENDATION: Accept. The {c['candidate_name']} addition delivers positive returns with a {c['match_pct']:.0f}% match against prediction."
        caveat  = "CAVEAT: Monitor actual lease terms and review again after 30 days of real operations to validate these numbers."
    elif c["actual_net_saving"] > 0:
        verdict = f"VERDICT: The simulation shows a positive net saving ({_fmt_inr(c['actual_net_saving'])}), though only {c['match_pct']:.0f}% of the predicted value was achieved."
        rec     = "RECOMMENDATION: Investigate. The saving is real but lower than predicted — understand why before committing to the lease."
        caveat  = "CAVEAT: The gap between prediction and simulation often reflects real road distances being longer than the straight-line model assumes."
    elif scale_explains:
        verdict = (
            f"VERDICT: The simulation ran at {c['stops_served']} stops/day versus the "
            f"MEIO prediction which assumed {c['meio_assumed_stops']} stops/day "
            f"({c['scale_factor']}x scale difference). At demo volume the hub appears "
            f"borderline; at full network volume the economics improve significantly."
        )
        rec     = (
            f"RECOMMENDATION: Investigate before deciding. The {c['candidate_name']} "
            f"addition may be justified at your full network scale — validate with "
            f"real traffic data before committing to the lease."
        )
        caveat  = (
            "CAVEAT: The Route Optimizer demo uses a reduced stop count for visual "
            "clarity. Run the analysis again with your actual daily delivery volume "
            "to get a comparison that matches the MEIO projection basis."
        )
    else:
        verdict = f"VERDICT: The simulation did not confirm the prediction — actual net saving is {_fmt_inr(c['actual_net_saving'])}, which does not justify the facility cost."
        rec     = "RECOMMENDATION: Reject this location. Return to the Network Intelligence module and evaluate the next candidate."
        caveat  = "CAVEAT: This result may reflect the fleet split chosen by the solver being suboptimal — try running with a different vehicle-to-depot assignment."
    return f"{verdict}\n\n{rec}\n\n{caveat}"






