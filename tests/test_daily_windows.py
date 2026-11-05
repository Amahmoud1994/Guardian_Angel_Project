"""DAILY-mode window + day-of-week gating — subtle logic, worth locking down.

Unit-tests the pure functions directly (fast, deterministic), then one
integration test exercising the same logic through a real API call
(apply_safe_checkin's DORMANT-transition branch, reachable synchronously
without waiting on the 10s watchdog loop).
"""
from datetime import datetime, timedelta, timezone

from conftest import unique

import main


# ── in_window / in_any_window ──────────────────────────────
def test_in_window_simple_range():
    assert main.in_window(600, 480, 720) is True   # 10:00 within 08:00-12:00
    assert main.in_window(400, 480, 720) is False  # before start
    assert main.in_window(800, 480, 720) is False  # after end


def test_in_window_midnight_wraparound():
    # 22:00 (1320) -> 06:00 (360), overnight window
    assert main.in_window(1350, 1320, 360) is True   # 22:30, inside
    assert main.in_window(100, 1320, 360) is True    # 01:40, inside (past midnight)
    assert main.in_window(700, 1320, 360) is False   # 11:40, outside


def test_in_window_equal_bounds_means_always_open():
    assert main.in_window(0, 500, 500) is True
    assert main.in_window(1439, 500, 500) is True


def test_in_any_window_picks_up_any_match():
    windows = [{"start_min": 480, "end_min": 540}, {"start_min": 1200, "end_min": 1260}]
    assert main.in_any_window(500, windows) is True
    assert main.in_any_window(1230, windows) is True
    assert main.in_any_window(700, windows) is False


# ── is_active_day ──────────────────────────────────────────
def test_is_active_day_empty_means_every_day():
    monday = datetime(2026, 9, 21, tzinfo=timezone.utc)  # a Monday
    assert main.is_active_day(monday, None) is True
    assert main.is_active_day(monday, []) is True


def test_is_active_day_respects_explicit_list():
    monday = datetime(2026, 9, 21, tzinfo=timezone.utc)  # weekday() == 0
    tuesday = monday + timedelta(days=1)
    assert main.is_active_day(monday, [0, 2, 3, 4, 5, 6]) is True   # Monday included
    assert main.is_active_day(tuesday, [0, 2, 3, 4, 5, 6]) is False  # Tuesday excluded


# ── next_window_start / next_any_window_start ──────────────
def test_next_window_start_rolls_to_tomorrow_if_already_past():
    now = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)  # Monday 10:00
    nxt = main.next_window_start(now, 8 * 60)  # 08:00, already passed today
    assert nxt.date() == (now + timedelta(days=1)).date()
    assert nxt.hour == 8 and nxt.minute == 0


def test_next_window_start_skips_inactive_days():
    monday = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)  # Monday, weekday()==0
    # Only Wednesday (2) is active — Tue must be skipped
    active_days = [2]
    nxt = main.next_window_start(monday, 8 * 60, active_days)
    assert nxt.weekday() == 2
    assert nxt.date() > monday.date()


def test_next_any_window_start_picks_soonest_across_windows():
    now = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)
    windows = [{"start_min": 6 * 60}, {"start_min": 20 * 60}]  # 06:00 (passed), 20:00 (upcoming)
    nxt = main.next_any_window_start(now, windows)
    assert nxt.hour == 20


# ── Integration: a DAILY session outside its window/active-days goes DORMANT ──
async def test_daily_checkin_outside_window_and_day_goes_dormant(client):
    now = datetime.now(timezone.utc)
    today_weekday = now.weekday()
    other_day = (today_weekday + 1) % 7  # any day that isn't today

    body = {
        "user_name": unique("DailyTester"),
        "destination": "Daily Test",
        "check_in_interval_minutes": 30,
        "guardians": [],
        "session_type": "DAILY",
        "windows": [{"start_min": 0, "end_min": 1, "start_local": "00:00", "end_local": "00:01"}],
        "active_days": [other_day],  # today is deliberately excluded
    }
    from conftest import sign_in
    await sign_in(client)
    r = await client.post("/api/journey/start", json=body)
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]

    # Safe check-in should notice we're outside today's active days and go DORMANT,
    # scheduling the next check-in on the next *active* day, not just tomorrow.
    r = await client.post("/api/checkin", json={"session_id": sid, "code": "SAFE123"})
    assert r.status_code == 200, r.text

    s = (await client.get(f"/api/session/{sid}")).json()
    assert s["status"] == "DORMANT"
    next_checkin = datetime.fromisoformat(s["next_checkin"])
    assert next_checkin.weekday() == other_day
