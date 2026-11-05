from datetime import datetime, timedelta, timezone

from sqlalchemy import update

import main
from conftest import new_client, unique


async def register(client, username):
    r = await client.post("/api/register", json={"username": username, "password": "pw123456", "accept_terms": True})
    assert r.status_code == 200, r.text
    return r.json()


def journey(dest="Nairobi Field Office", **extra):
    return {"user_name": "Alex", "destination": dest, "check_in_interval_minutes": 30,
            "maps_link": "https://maps.google.com/?q=nairobi",
            "guardians": [{"name": "Grace", "email": "g@example.com"}], **extra}


def in_future(minutes=60):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


async def test_save_list_and_update_plan(client):
    await register(client, unique("trav"))
    r = await client.post("/api/plans", json={"journey": journey()})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["scheduled_start"] == ""
    assert plan["journey"]["maps_link"] == "https://maps.google.com/?q=nairobi"
    assert plan["journey"]["guardians"][0]["email"] == "g@example.com"

    r = await client.put(f"/api/plans/{plan['id']}", json={"journey": journey("Mombasa Port")})
    assert r.status_code == 200
    plans = (await client.get("/api/plans")).json()
    assert [p["journey"]["destination"] for p in plans] == ["Mombasa Port"]


async def test_start_plan_now_creates_session_and_keeps_plan(client):
    await register(client, unique("trav"))
    plan = (await client.post("/api/plans", json={"journey": journey(), "scheduled_start": in_future()})).json()

    r = await client.post(f"/api/plans/{plan['id']}/start")
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]

    s = (await client.get(f"/api/session/{sid}")).json()
    assert s["status"] == "ACTIVE" and s["destination"] == "Nairobi Field Office"
    assert s["maps_link"] == "https://maps.google.com/?q=nairobi"
    sessions = (await client.get("/api/sessions")).json()
    assert any(x["session_id"] == sid for x in sessions)  # attributed to the plan's owner

    plans = (await client.get("/api/plans")).json()
    assert plans[0]["last_session_id"] == sid
    assert plans[0]["scheduled_start"] == ""  # a manual start consumes the schedule


async def test_plan_can_be_started_again(client):
    await register(client, unique("trav"))
    plan = (await client.post("/api/plans", json={"journey": journey()})).json()
    first = (await client.post(f"/api/plans/{plan['id']}/start")).json()["session_id"]
    second = (await client.post(f"/api/plans/{plan['id']}/start")).json()["session_id"]
    assert first != second


async def test_schedule_must_be_in_future_and_timezone_aware(client):
    await register(client, unique("trav"))
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    r = await client.post("/api/plans", json={"journey": journey(), "scheduled_start": past})
    assert r.status_code == 400
    r = await client.post("/api/plans", json={"journey": journey(), "scheduled_start": "2099-01-01T10:00:00"})
    assert r.status_code == 400
    r = await client.post("/api/plans", json={"journey": journey(), "scheduled_start": "not-a-date"})
    assert r.status_code == 400


async def test_schedule_is_normalized_to_utc(client):
    await register(client, unique("trav"))
    r = await client.post("/api/plans", json={"journey": journey(), "scheduled_start": "2099-01-01T10:00:00+02:00"})
    assert r.status_code == 200
    assert r.json()["scheduled_start"] == "2099-01-01T08:00:00+00:00"


async def test_plan_requires_name_and_destination(client):
    await register(client, unique("trav"))
    r = await client.post("/api/plans", json={"journey": journey(dest="  ")})
    assert r.status_code == 400


async def test_daily_usage_cannot_be_saved_as_plan(client):
    await register(client, unique("trav"))
    r = await client.post("/api/plans", json={"journey": journey(session_type="DAILY")})
    assert r.status_code == 400


async def test_plans_are_private(client, app):
    await register(client, unique("owner"))
    plan = (await client.post("/api/plans", json={"journey": journey()})).json()
    async with new_client(app) as other:
        await register(other, unique("other"))
        assert (await other.get("/api/plans")).json() == []
        assert (await other.put(f"/api/plans/{plan['id']}", json={"journey": journey()})).status_code == 403
        assert (await other.post(f"/api/plans/{plan['id']}/start")).status_code == 403
        assert (await other.delete(f"/api/plans/{plan['id']}")).status_code == 403


async def test_plans_require_login(client):
    assert (await client.get("/api/plans")).status_code == 401


async def test_delete_plan(client):
    await register(client, unique("trav"))
    plan = (await client.post("/api/plans", json={"journey": journey()})).json()
    assert (await client.delete(f"/api/plans/{plan['id']}")).status_code == 200
    assert (await client.get("/api/plans")).json() == []


async def test_due_scheduled_plan_auto_starts(client, monkeypatch):
    pushes = []

    async def fake_push(user_id, title, body_text, level):
        pushes.append((user_id, title, body_text))

    monkeypatch.setattr(main, "send_push_to_user", fake_push)
    me = await register(client, unique("trav"))
    plan = (await client.post("/api/plans", json={"journey": journey(), "scheduled_start": in_future()})).json()

    await main.start_due_plans()  # not due yet
    assert (await client.get("/api/plans")).json()[0]["last_session_id"] == ""

    # Pretend the scheduled time has arrived.
    async with main.AsyncSessionLocal() as db:
        await db.execute(update(main.JourneyPlanModel).where(main.JourneyPlanModel.id == plan["id"])
                         .values(scheduled_start=(datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()))
        await db.commit()

    await main.start_due_plans()
    saved = (await client.get("/api/plans")).json()[0]
    assert saved["last_session_id"] and saved["scheduled_start"] == ""
    s = (await client.get(f"/api/session/{saved['last_session_id']}")).json()
    assert s["status"] == "ACTIVE"

    await main.start_due_plans()  # a consumed schedule never fires twice
    assert len([x for x in (await client.get("/api/sessions")).json()]) == 1

    import asyncio
    await asyncio.sleep(0)  # let the fire-and-forget push task run
    assert pushes and pushes[0][0] == me["id"] and "Nairobi" in pushes[0][2]
