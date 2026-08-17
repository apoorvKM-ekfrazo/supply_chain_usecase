"""
check_tokens.py
───────────────
A standalone diagnostic script for checking your Groq API token budget.
Run this from the project root — it needs nothing from the app itself.

Usage:
    python check_tokens.py                  # today's summary
    python check_tokens.py --history        # all-time usage log
    python check_tokens.py --models         # list all Groq models + their limits
    python check_tokens.py --verify         # verify your API key is valid

What this script does:
  1. Reads your local usage log (data/token_usage.jsonl) for today's calls
  2. Combines that with Groq's published daily limits per model
  3. Estimates how many queries of each type you have left today
  4. Shows a clear picture of which model to use for which task

What it CANNOT do (and why):
  Groq does not expose a "remaining tokens" API endpoint. The estimate
  here is based entirely on calls that went through this app.
  If you used the same API key from another tool, that usage won't appear
  here. The Groq Console is the only authoritative source:
  → https://console.groq.com/settings/billing

Requirements:
  pip install groq python-dotenv   (both already in requirements.txt)
"""

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Load the API key from .env or environment
# We use python-dotenv so the script works the same way as the app does.
# ─────────────────────────────────────────────────────────────────────────────

try:
    from dotenv import load_dotenv
    load_dotenv()   # reads .env file in the current directory
except ImportError:
    pass  # dotenv not installed; rely on environment variables directly

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Groq model catalogue with daily limits
#
# These limits are from Groq's published documentation (free "on_demand" tier).
# They are TOKENS PER DAY (TPD) — the rolling 24-hour window Groq uses.
#
# The "best_for" column is a practical guide for our O'Reilly app specifically:
#   parse_order()   → simple extraction, short input/output → 8B is perfect
#   copilot_query() → long context, reasoning → 70B is noticeably better
#
# Note: Groq also has tokens-per-minute (TPM) limits. If you fire many
# requests in rapid succession you can hit TPM even with TPD remaining.
# For interactive demo use this is unlikely to matter.
# ─────────────────────────────────────────────────────────────────────────────

OPENAI_MODELS = {
    "gpt-4o-mini": {
        "tpd": 100_000,
        "tpm": 6_000,
        "params": "70B",
        "best_for": "Copilot queries — complex reasoning over long context",
        "our_use":  "copilot_query()",
    },
    "llama-3.1-70b-versatile": {
        "tpd": 100_000,
        "tpm": 6_000,
        "params": "70B",
        "best_for": "Older 70B — same limit as 3.3, slightly less capable",
        "our_use":  "not currently used",
    },
    "llama-3.1-8b-instant": {
        "tpd": 500_000,
        "tpm": 20_000,
        "params": "8B",
        "best_for": "Order parsing — structured extraction, short tasks",
        "our_use":  "parse_order()",
    },
    "llama3-8b-8192": {
        "tpd": 500_000,
        "tpm": 20_000,
        "params": "8B",
        "best_for": "Older 8B — same limit as 3.1-8B",
        "our_use":  "not currently used",
    },
    "mixtral-8x7b-32768": {
        "tpd": 500_000,
        "tpm": 5_000,
        "params": "8x7B MoE",
        "best_for": "Good all-rounder, large context window (32k), 500k TPD",
        "our_use":  "fallback option if 70B TPD exhausted",
    },
    "gemma2-9b-it": {
        "tpd": 500_000,
        "tpm": 15_000,
        "params": "9B",
        "best_for": "Google's Gemma 2 — solid instruction following",
        "our_use":  "not currently used",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Typical token cost per call type in our app
#
# These are averages derived from our actual usage logs, not estimates pulled
# from thin air. The breakdown is:
#
#   parse_order:
#     input  = system prompt (~300) + today's date (~10) + order text (~150)
#     output = JSON with ~8 fields (~130 tokens)
#     total  ≈ 500 tokens
#
#   copilot_query:
#     input  = system prompt (~500) + RAG chunks 4×200 (~800) + JSON context (~1500) + question (~50)
#     output = up to max_tokens=1500, typically 400–800 in practice
#     total  ≈ 4500 tokens
#
# These numbers let us answer "how many more questions can I ask today?"
# ─────────────────────────────────────────────────────────────────────────────

TYPICAL_COST = {
    "parse_order":    500,
    "copilot_query": 4500,
}


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: READ THE LOCAL USAGE LOG
# ─────────────────────────────────────────────────────────────────────────────

LOG_FILE = Path("data") / "token_usage.jsonl"

def read_today_usage() -> list:
    """
    Reads today's records from the local token log.

    Each record is a dict written by utils/token_tracker.py after every
    successful Groq API call. If the log doesn't exist yet (first run,
    or Ollama-only usage), this returns an empty list gracefully.
    """
    today = date.today().isoformat()

    if not LOG_FILE.exists():
        return []

    records = []
    with open(LOG_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                # Only include today's records
                if record.get("date") == today:
                    records.append(record)
            except json.JSONDecodeError:
                continue   # silently skip any malformed lines

    return records


def read_all_usage() -> list:
    """Reads the entire usage log regardless of date."""
    if not LOG_FILE.exists():
        return []

    records = []
    with open(LOG_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def aggregate_by_model(records: list) -> dict:
    """
    Groups usage records by model name and sums up their token counts.

    Returns a dict like:
    {
      "gpt-4o-mini": {"calls": 8, "total_tokens": 40000, ...},
      "llama-3.1-8b-instant":    {"calls": 4, "total_tokens": 2000, ...},
    }
    """
    by_model = {}
    for r in records:
        model = r.get("model", "unknown")
        if model not in by_model:
            by_model[model] = {
                "calls": 0,
                "prompt_tokens":     0,
                "completion_tokens": 0,
                "total_tokens":      0,
                "call_types":        {},
            }

        by_model[model]["calls"]             += 1
        by_model[model]["prompt_tokens"]     += r.get("prompt_tokens",     0)
        by_model[model]["completion_tokens"] += r.get("completion_tokens", 0)
        by_model[model]["total_tokens"]      += r.get("total_tokens",      0)

        # Also track call type breakdown so we can say
        # "you made 3 copilot_query calls on this model"
        ct = r.get("call_type", "unknown")
        by_model[model]["call_types"][ct] = by_model[model]["call_types"].get(ct, 0) + 1

    return by_model


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: VISUAL FORMATTING
# ─────────────────────────────────────────────────────────────────────────────

def progress_bar(used: int, total: int, width: int = 35) -> str:
    """
    Builds an ASCII progress bar showing used / total.

    Example for 40% used:
      [▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░] 40.0%

    The filled character changes colour-coded by urgency:
      < 60%  → ▓  (safe, normal)
      60-80% → █  (getting busy)
      > 80%  → ■  (danger zone)
    """
    if total == 0:
        return "[" + "?" * width + "] n/a"

    pct     = min(used / total * 100, 100.0)
    filled  = int(pct / 100 * width)
    empty   = width - filled

    char = "▓" if pct < 60 else ("█" if pct < 80 else "■")
    bar  = char * filled + "░" * empty

    return f"[{bar}] {pct:.1f}%"


def divider(char="─", width=62):
    return char * width


# ─────────────────────────────────────────────────────────────────────────────
# MAIN REPORT: TODAY'S BUDGET
# ─────────────────────────────────────────────────────────────────────────────

def report_today():
    """
    The main report — prints today's usage, remaining budget, and estimated
    queries left for each model we actually use in the app.
    """
    today   = date.today().isoformat()
    records = read_today_usage()
    usage   = aggregate_by_model(records)

    print()
    print(divider("═"))
    print(f"  🔋  Groq Token Budget — {today}")
    print(f"      API key: {'✅ loaded from .env' if OPENAI_API_KEY else '❌ not set (set OPENAI_API_KEY in .env)'}")
    print(f"      Local log: {LOG_FILE}  ({len(records)} calls logged today)")
    print()
    print("  ⚠️  IMPORTANT: This estimate only covers calls made through this app.")
    print("     If you used the same key elsewhere, your actual remaining budget")
    print("     may be lower. Check the authoritative source:")
    print("     → https://console.groq.com/settings/billing")
    print(divider("═"))

    # Report on each model that's relevant to our app
    relevant_models = [
        "gpt-4o-mini",
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768",
    ]

    for model_name in relevant_models:
        model_info  = OPENAI_MODELS.get(model_name, {})
        daily_limit = model_info.get("tpd", 100_000)
        used_today  = usage.get(model_name, {}).get("total_tokens", 0)
        remaining   = max(0, daily_limit - used_today)
        calls_today = usage.get(model_name, {}).get("calls", 0)
        call_types  = usage.get(model_name, {}).get("call_types", {})

        print()
        print(f"  📌  {model_name}")
        print(f"      {model_info.get('params','?')} params  ·  {model_info.get('best_for','')}")
        print(f"      Used in our app for: {model_info.get('our_use','?')}")
        print()
        print(f"      {progress_bar(used_today, daily_limit)}")
        print(f"      Used today:   {used_today:>8,} / {daily_limit:,} tokens  ({calls_today} API calls)")
        print(f"      Remaining:    {remaining:>8,} tokens")

        # Show how many more queries of each type are possible.
        # We iterate over our app's known call types and compute how many
        # more could fit in the remaining budget at each type's average cost.
        print(f"      Estimated queries remaining at average cost:")
        for call_type, avg_cost in TYPICAL_COST.items():
            queries_left = remaining // avg_cost
            avg_actual   = (
                usage.get(model_name, {}).get("total_tokens", 0) //
                max(calls_today, 1)
            ) if calls_today > 0 else avg_cost
            print(f"        • {call_type:<20} ~{queries_left:>5} more  (avg {avg_cost:,} tokens/call)")

        # Show breakdown of what was called today if there were calls
        if call_types:
            print(f"      Calls made today by type:")
            for ct, count in sorted(call_types.items(), key=lambda x: -x[1]):
                print(f"        • {ct:<30} {count} call(s)")

        print(f"      {divider()}")

    # Summary row comparing the two models we actually use
    used_70b  = usage.get("gpt-4o-mini", {}).get("total_tokens", 0)
    used_8b   = usage.get("llama-3.1-8b-instant",    {}).get("total_tokens", 0)
    rem_70b   = max(0, 100_000 - used_70b)
    rem_8b    = max(0, 500_000 - used_8b)

    print()
    print(f"  📊  Summary — Our App's Two Active Models")
    print(f"      Model routing: parse_order → 8B (500k/day) | copilot → 70B (100k/day)")
    print()
    print(f"      70B remaining → ~{rem_70b // TYPICAL_COST['copilot_query']:>3} copilot queries left today")
    print(f"       8B remaining → ~{rem_8b  // TYPICAL_COST['parse_order']:>3} order parses   left today")
    print()
    print(f"      If 70B runs out, switch the app to mixtral-8x7b-32768 (500k/day)")
    print(f"      in utils/llm_client.py — it handles copilot queries acceptably.")
    print(divider("═"))
    print()


# ─────────────────────────────────────────────────────────────────────────────
# MODELS REPORT: ALL AVAILABLE GROQ MODELS + LIMITS
# ─────────────────────────────────────────────────────────────────────────────

def report_models():
    """Prints all known Groq models with their daily limits and our usage notes."""
    print()
    print(divider("═"))
    print("  📋  Groq Model Directory — Free Tier Limits")
    print(divider("═"))
    print()
    print(f"  {'Model':<35} {'TPD':>8}  {'TPM':>7}  {'Params':<10}  Use in our app")
    print(f"  {divider('-', 35)} {'───────':>8}  {'──────':>7}  {'──────':<10}  ──────────────")
    for name, info in OPENAI_MODELS.items():
        our_use = info.get("our_use", "")
        marker  = "◀ ACTIVE" if "our_use" in info and "()" in our_use else ""
        print(
            f"  {name:<35} {info['tpd']:>8,}  {info['tpm']:>7,}  {info['params']:<10}  {our_use} {marker}"
        )
    print()
    print("  TPD = Tokens Per Day  |  TPM = Tokens Per Minute  |  Free on_demand tier")
    print("  Source: https://console.groq.com/docs/rate-limits")
    print(divider("═"))
    print()


# ─────────────────────────────────────────────────────────────────────────────
# HISTORY REPORT: ALL-TIME USAGE LOG
# ─────────────────────────────────────────────────────────────────────────────

def report_history():
    """
    Shows usage grouped by calendar date so you can see usage trends
    across days — useful for understanding your typical daily consumption
    pattern and planning accordingly.
    """
    all_records = read_all_usage()

    if not all_records:
        print("\n  No usage history found.")
        print(f"  Expected log file at: {LOG_FILE}")
        print("  The log is created automatically after the first API call.\n")
        return

    # Group by date
    by_date = {}
    for r in all_records:
        d = r.get("date", "unknown")
        if d not in by_date:
            by_date[d] = {"records": [], "total_tokens": 0, "calls": 0}
        by_date[d]["records"].append(r)
        by_date[d]["total_tokens"] += r.get("total_tokens", 0)
        by_date[d]["calls"] += 1

    print()
    print(divider("═"))
    print(f"  📅  Usage History — All Time  ({len(all_records)} total API calls)")
    print(divider("═"))
    print()

    for day in sorted(by_date.keys(), reverse=True):
        day_data    = by_date[day]
        total       = day_data["total_tokens"]
        calls       = day_data["calls"]
        by_model    = aggregate_by_model(day_data["records"])

        print(f"  {day}   {total:>7,} tokens across {calls} calls")

        for model, stats in sorted(by_model.items(), key=lambda x: -x[1]["total_tokens"]):
            pct_of_limit = stats["total_tokens"] / OPENAI_MODELS.get(model, {}).get("tpd", 100_000) * 100
            short_model  = model.replace("gpt-4o-mini", "70B-versatile") \
                                .replace("llama-3.1-8b-instant",    "8B-instant") \
                                .replace("mixtral-8x7b-32768",      "mixtral-8x7b")
            print(f"      {short_model:<22} {stats['total_tokens']:>7,} tokens  "
                  f"({pct_of_limit:4.1f}% of daily limit)  {stats['calls']} calls")

        print()

    print(divider("═"))
    print()


# ─────────────────────────────────────────────────────────────────────────────
# API KEY VERIFICATION
# ─────────────────────────────────────────────────────────────────────────────

def verify_key():
    """
    Makes a tiny test call to Groq to confirm the API key is valid and
    the account is active. Uses the 8B model with max_tokens=1 so it
    consumes essentially zero tokens (about 50 prompt tokens).

    This is useful when you get unexpected 401/403 errors — it confirms
    the key itself is the problem rather than your prompts or rate limits.
    """
    if not OPENAI_API_KEY:
        print("\n  ❌  No API key found. Set OPENAI_API_KEY in your .env file.\n")
        return

    print(f"\n  🔑  Verifying API key (ends in ...{OPENAI_API_KEY[-6:]})")
    print(f"      Making a minimal test call to llama-3.1-8b-instant (~50 tokens)...")

    try:
        from groq import Groq, AuthenticationError, RateLimitError
    except ImportError:
        print("  ❌  groq package not installed. Run: pip install groq\n")
        return

    try:
        client   = Groq(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": "Reply with the single word: OK"}],
            max_tokens=5,      # tiny output — we only need to confirm the key works
            temperature=0.0,
        )
        reply  = response.choices[0].message.content.strip()
        tokens = response.usage.total_tokens
        print(f"  ✅  API key valid — model responded: '{reply}' ({tokens} tokens used)")
        print(f"      Key is active and the 8B model is reachable.")

    except AuthenticationError:
        print("  ❌  Authentication failed — the API key is invalid or revoked.")
        print("      Get a new key at: https://console.groq.com/keys")

    except RateLimitError as e:
        print(f"  ⚠️   Key is valid but you're rate limited: {e}")
        print("      Wait for the cooldown window and try again.")

    except Exception as e:
        print(f"  ❌  Unexpected error: {e}")

    print()


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if "--models" in args:
        # Just show the model catalogue — no log reading needed
        report_models()

    elif "--history" in args:
        # Show all-time usage grouped by day
        report_history()

    elif "--verify" in args:
        # Verify the API key works with a tiny test call
        verify_key()

    elif "--help" in args or "-h" in args:
        print(__doc__)

    else:
        # Default: today's usage + budget remaining
        # If they pass --history or --models alongside, show both
        report_today()
        if "--models" in args:
            report_models()

    # If no arguments given, also show a one-line hint about other modes
    if not args:
        print("  Other modes:")
        print("    python check_tokens.py --models    → full Groq model catalogue")
        print("    python check_tokens.py --history   → usage across all days")
        print("    python check_tokens.py --verify    → test if your API key works")
        print()





