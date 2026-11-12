"""Regression tests for the November 2026 security review — each test is an attack that must keep failing."""
from datetime import datetime, timezone

import pytest

import main
from conftest import login_as_admin, new_client, sign_in, unique


async def start(client, **extra):
    r = await client.post("/api/journey/start", json={"user_name": "Mia", "destination": "Peak", **extra})
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


# ── Nobody but an admin can make the app send arbitrary email ──
async def test_test_email_is_admin_only(client, app, monkeypatch):
    payload = {"to": "victim@example.com", "requested_by": "<a href='http://evil'>click</a>"}
    assert (await client.post("/api/test-email", json=payload)).status_code == 401
    await sign_in(client)
    assert (await client.post("/api/test-email", json=payload)).status_code == 403

    monkeypatch.setenv("SMTP_USER", "")  # admin passes the auth check, but nothing is actually sent
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    async with new_client(app) as admin:
        await login_as_admin(admin)
        assert (await admin.post("/api/test-email", json={"to": "not-an-email"})).status_code == 400
        r = await admin.post("/api/test-email", json=payload)
        assert r.status_code == 400 and "not configured" in r.json()["detail"]


async def test_email_status_is_admin_only(client):
    assert (await client.get("/api/email-status")).status_code == 401
    await sign_in(client)
    assert (await client.get("/api/email-status")).status_code == 403


async def test_anonymous_journeys_are_refused(client):
    r = await client.post("/api/journey/start", json={
        "user_name": "x", "destination": "y", "guardians": [{"name": "Victim", "email": "victim@example.com"}]})
    assert r.status_code == 401


@pytest.mark.parametrize("extra", [
    {"destination": "x" * 201},
    {"guardians": [{"name": f"g{i}", "email": f"g{i}@example.com"} for i in range(11)]},
    {"guardians": [{"name": "Bad", "email": "not an email"}]},
    {"maps_link": "https://maps.example/" + "x" * 600},
])
async def test_journey_input_limits(client, extra):
    await sign_in(client)
    body = {"user_name": "Mia", "destination": "Peak", **extra}
    assert (await client.post("/api/journey/start", json=body)).status_code == 400
    assert (await client.post("/api/plans", json={"journey": body})).status_code == 400


# ── A leaked session link reveals trip details, never the codes, and can't switch alerts off ──
async def test_session_link_hides_codes_and_contacts(client, app):
    await sign_in(client)
    sid = await start(client, safe_code="BLUEBIRD", duress_code="REDFOX",
                      guardians=[{"name": "Grace", "contact": "+43 600", "email": "grace@example.com"}],
                      companions=[{"name": "Sam", "contact": "+43 700"}])
    mine = (await client.get(f"/api/session/{sid}")).json()
    assert mine["safe_code"] == "BLUEBIRD" and mine["duress_code"] == "REDFOX"

    async with new_client(app) as stranger:
        seen = (await stranger.get(f"/api/session/{sid}")).json()
        assert "safe_code" not in seen and "duress_code" not in seen and "user_id" not in seen
        assert seen["guardians"] == [{"name": "Grace"}] and seen["companions"] == [{"name": "Sam"}]
        assert seen["destination"] == "Peak"  # what guardians need is still there
        await sign_in(stranger)
        seen = (await stranger.get(f"/api/session/{sid}")).json()
        assert "safe_code" not in seen  # another account is still not the owner


async def test_only_owner_or_admin_can_end_a_journey(client, app):
    await sign_in(client)
    sid = await start(client)
    async with new_client(app) as stranger:
        assert (await stranger.post(f"/api/journey/end?session_id={sid}")).status_code == 401
        await sign_in(stranger)
        assert (await stranger.post(f"/api/journey/end?session_id={sid}")).status_code == 403
    assert (await client.get(f"/api/session/{sid}")).json()["status"] == "ACTIVE"
    async with new_client(app) as admin:
        await login_as_admin(admin)
        assert (await admin.post(f"/api/journey/end?session_id={sid}")).status_code == 200


async def test_only_owner_can_send_locations(client, app):
    await sign_in(client)
    sid = await start(client)
    async with new_client(app) as stranger:
        await sign_in(stranger)
        r = await stranger.post("/api/location/ping", json={"session_id": sid, "lat": 1.0, "lng": 1.0})
        assert r.status_code == 404
    assert (await client.post("/api/location/ping", json={"session_id": sid, "lat": 99.0, "lng": 1.0})).status_code == 400
    assert (await client.get(f"/api/location/history?session_id={sid}")).json() == []


# ── The event log is private, and silent duress never shows on the user's own screen ──
async def test_event_log_is_private_and_hides_silent_duress(client, app):
    assert (await client.get("/api/events")).status_code == 401
    await sign_in(client)
    sid = await start(client)
    await client.post("/api/checkin", json={"session_id": sid, "code": "HELP999"})

    mine = (await client.get("/api/events")).json()
    assert mine and all(e["session_id"] == sid for e in mine)
    assert not any(e["silent"] for e in mine)
    assert not any("DURESS" in e["message"] for e in mine)

    async with new_client(app) as stranger:
        await sign_in(stranger)
        assert (await stranger.get(f"/api/events?session_id={sid}")).status_code == 404
        assert all(e["session_id"] != sid for e in (await stranger.get("/api/events")).json())

    async with new_client(app) as admin:
        await login_as_admin(admin)
        everything = (await admin.get(f"/api/events?session_id={sid}")).json()
        assert any(e["silent"] for e in everything)  # admins still see it for investigations


# ── Case files of journeys without an owner: admin only ──
async def test_ownerless_case_file_is_admin_only(client, app):
    sid = unique("legacy")
    now = datetime.now(timezone.utc).isoformat()
    async with main.AsyncSessionLocal() as db:
        db.add(main.SessionModel(session_id=sid, user_name="Old", destination="Legacy", safe_code="SAFE123",
                                 duress_code="HELP999", started_at=now, next_checkin=now, user_id="",
                                 case_file=main.encrypt_case_file('{"destination": "Legacy"}')))
        await db.commit()
    await sign_in(client)
    assert (await client.get(f"/api/case/{sid}")).status_code == 403
    async with new_client(app) as admin:
        await login_as_admin(admin)
        assert (await admin.get(f"/api/case/{sid}")).status_code == 200


# ── Emails never carry user-supplied HTML or script links ──
def test_alert_email_escapes_user_input():
    s = main.SessionModel(
        session_id="abc", user_name="<a href='http://evil.example'>Click</a>", destination="<script>x</script>",
        guardians='[{"name": "<b>G</b>", "email": "g@example.com"}]', safe_code="S", duress_code="D",
        started_at="2026-11-04T10:00:00+00:00", next_checkin="2026-11-04T10:30:00+00:00",
        maps_link="javascript:alert(1)", route="<img src=x onerror=alert(1)>", companions=None, country="",
        last_location=None, last_checkin=None, latitude=None, longitude=None, communication_method=None)
    html = main.build_email_body(3, s, "<i>sender</i>", message_text="<a href='http://evil'>help</a>")
    for bad in ("<a href='http://evil", "<script>", "<img", "javascript:", "<b>G</b>", "<i>sender</i>"):
        assert bad not in html, bad
    assert "&lt;script&gt;" in html


def test_email_subjects_cannot_inject_headers():
    assert "\n" not in main._header_safe("Mia\r\nBcc: everyone@example.com")


# ── The beta form can't be used to email-bomb an address ──
async def test_beta_confirmation_only_on_first_application(client, monkeypatch):
    sent = []

    async def fake_send(to, subject, body_html):
        sent.append(to)

    monkeypatch.setattr(main, "send_html_email", fake_send)
    import asyncio
    form = {"name": "Mia", "email": f"{unique('mia')}@gmail.com", "country": "AT", "platform": "iphone", "consent": "yes"}
    for _ in range(3):
        await client.post("/beta", data=form)
    for _ in range(3):
        await asyncio.sleep(0)
    assert sent == [form["email"]]
