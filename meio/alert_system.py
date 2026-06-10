"""
meio/alert_system.py
---------------------
Strategic alert system for the MEIO module.

This module tracks which warehouse placement recommendation the optimiser
produces each day and escalates a recommendation to a "High Confidence
Alert" when it appears consistently — the feature the sales guy described
as "came 90% in a week, worth looking at."

The persistence mechanism is intentionally simple: a JSON file on disk.
For a demo this is perfect — it is invisible to the client, survives app
restarts, and requires zero database infrastructure. For a production
system you would replace this file with a SQLite or PostgreSQL table, but
the business logic in this module would be identical.

How the alert system works:
  Each time the MEIO page runs an analysis, it calls record_recommendation()
  with the top candidate from that run. The function appends a dated entry
  to the JSON history. When the page loads, load_alert_status() scans the
  last 7 days of history and counts how often each recommendation appeared.
  If any recommendation appeared in more than ALERT_THRESHOLD of those days,
  it is elevated to a High Confidence Alert and displayed prominently.

For the demo, we pre-seed the JSON file with 6 days of history all showing
Marathahalli as the top recommendation. When the user runs the analysis on
the demo day, it becomes 7/7 and the alert fires. This gives the client an
immediate "aha" moment: the system has been noticing this pattern all week
and is now telling you it is serious.
"""

import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# The alert history file lives in the project root alongside the cache files.
ALERT_HISTORY_FILE = Path(__file__).parent.parent / "meio_alert_history.json"

# Fire a High Confidence Alert when a recommendation appears this fraction
# of days in the look-back window. 5/7 = 71% — fires reliably after 5 of
# 7 days including weekends in the window (working days only get entries).
ALERT_THRESHOLD = 5 / 7

# How many days of history to look back when computing the alert.
LOOKBACK_DAYS = 7


def _load_history() -> List[Dict]:
    """Read the alert history from disk. Returns empty list if file missing."""
    if ALERT_HISTORY_FILE.exists():
        try:
            with open(ALERT_HISTORY_FILE) as f:
                data = json.load(f)
            return data.get("history", [])
        except Exception:
            return []
    return []


def _save_history(history: List[Dict]) -> None:
    """Write the alert history to disk."""
    try:
        with open(ALERT_HISTORY_FILE, "w") as f:
            json.dump({"history": history}, f, indent=2)
    except Exception as e:
        print(f"Alert system: could not save history: {e}")


def seed_demo_history(top_recommendation: str, net_saving: float) -> None:
    """
    Pre-seed 6 days of history so the 7th run (today's demo) triggers an alert.

    Uses the last 6 WORKING days (Mon-Fri only) before today, so the entries
    always fall within the 7-day lookback window regardless of what day the
    demo runs. This guarantees the alert fires on the first demo run.
    """
    if ALERT_HISTORY_FILE.exists():
        return   # don't overwrite existing history

    today   = date.today()
    history = []
    day     = today - timedelta(days=1)   # start from yesterday
    seeded  = 0

    while seeded < 6:
        if day.weekday() < 5:   # Mon-Fri only
            history.append({
                "date":               day.isoformat(),
                "top_recommendation": top_recommendation,
                "net_annual_saving":  round(net_saving, 0),
            })
            seeded += 1
        day -= timedelta(days=1)

    history.sort(key=lambda h: h["date"])
    _save_history(history)


def record_recommendation(top_recommendation: str, net_saving: float) -> None:
    """
    Record today's top recommendation in the alert history.

    If an entry for today already exists (e.g. the user ran the analysis
    twice), we update it rather than creating a duplicate.
    """
    history = _load_history()
    today   = date.today().isoformat()

    # Remove any existing entry for today
    history = [h for h in history if h.get("date") != today]

    history.append({
        "date":               today,
        "top_recommendation": top_recommendation,
        "net_annual_saving":  round(net_saving, 0),
    })

    # Keep only the last 30 days — older history is irrelevant for alerts
    history.sort(key=lambda h: h["date"])
    history = history[-30:]

    _save_history(history)


def load_alert_status() -> dict:
    """
    Scan the last LOOKBACK_DAYS of history and compute alert status.

    Returns a dict with:
      has_alert (bool): True if any recommendation meets the threshold
      alert_recommendation (str): the recommendation that triggered the alert
      alert_saving (float): its latest net annual saving figure
      frequency (float): fraction of days in the lookback window it appeared
      days_in_window (int): how many history entries fell in the window
      total_window_days (int): the full lookback window (LOOKBACK_DAYS)
      history (list): the recent entries for display in the UI
    """
    history  = _load_history()
    today    = date.today()
    cutoff   = today - timedelta(days=LOOKBACK_DAYS)

    # Filter to the lookback window
    recent   = [
        h for h in history
        if date.fromisoformat(h["date"]) >= cutoff
    ]

    if not recent:
        return {
            "has_alert":             False,
            "days_in_window":        0,
            "total_window_days":     LOOKBACK_DAYS,
            "history":               [],
            "alert_recommendation":  None,
            "alert_saving":          None,
            "frequency":             0.0,
        }

    # Count occurrences of each recommendation
    counts: Dict[str, int] = {}
    savings: Dict[str, float] = {}
    for entry in recent:
        rec = entry["top_recommendation"]
        counts[rec]  = counts.get(rec, 0) + 1
        savings[rec] = entry["net_annual_saving"]   # keep the latest saving figure

    # Find the most frequent recommendation
    top_rec   = max(counts, key=counts.get)
    frequency = counts[top_rec] / LOOKBACK_DAYS    # fraction of ALL days in window

    has_alert = frequency >= ALERT_THRESHOLD

    return {
        "has_alert":             has_alert,
        "alert_recommendation":  top_rec if has_alert else None,
        "alert_saving":          savings[top_rec] if has_alert else None,
        "frequency":             round(frequency * 100, 0),
        "days_appeared":         counts[top_rec],
        "days_in_window":        len(recent),
        "total_window_days":     LOOKBACK_DAYS,
        "history":               list(reversed(recent)),   # most recent first
        "all_counts":            counts,
    }


def clear_history() -> None:
    """Remove the alert history file. Used by the Reset button."""
    if ALERT_HISTORY_FILE.exists():
        ALERT_HISTORY_FILE.unlink()