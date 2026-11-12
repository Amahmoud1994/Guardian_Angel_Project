from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, update

import main
from conftest import login_as_admin, new_client, unique


async def register(client, username, email="", password="pw123456"):
    r = await client.post("/api/register", json={"username": username, "password": password,
                                                 "email": email, "accept_terms": True})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def sent_emails(monkeypatch):
    sent = []

    async def fake_send(to, subject, body_html):
        sent.append({"to": to, "subject": subject, "body": body_html})

    monkeypatch.setattr(main, "send_html_email", fake_send)
    return sent


async def flush_tasks():
    import asyncio
    for _ in range(3):
        await asyncio.sleep(0)


# ── Registration ──────────────────────────────
async def test_register_requires_terms_consent(client):
    r = await client.post("/api/register", json={"username": unique("noconsent"), "password": "pw123456"})
    assert r.status_code == 400 and "Terms" in r.json()["detail"]


async def test_register_requires_8_char_password(client):
    r = await client.post("/api/register", json={"username": unique("short"), "password": "1234567", "accept_terms": True})
    assert r.status_code == 400


async def test_consent_time_is_recorded(client):
    me = await register(client, unique("consent"))
    async with main.AsyncSessionLocal() as db:
        u = (await db.execute(select(main.UserModel).where(main.UserModel.id == me["id"]))).scalar_one()
        assert u.consented_at


async def test_admin_flag_comes_from_config(client, app):
    assert (await register(client, unique("plain")))["is_admin"] is False
    async with new_client(app) as admin_client:
        assert (await login_as_admin(admin_client))["is_admin"] is True


# ── Password reset ────────────────────────────
async def reset_token_from(sent):
    import re
    return re.search(r"/reset-password/([\w-]+)", sent[-1]["body"]).group(1)


async def test_password_reset_flow(client, app, sent_emails):
    name = unique("forgetful")
    await register(client, name, email="forgetful@example.com", password="old-password")

    r = await client.post("/api/password/forgot", json={"identifier": "forgetful@example.com"})
    assert r.status_code == 200
    await flush_tasks()
    assert len(sent_emails) == 1 and sent_emails[0]["to"] == "forgetful@example.com"
    token = await reset_token_from(sent_emails)

    assert "new password" in (await client.get(f"/reset-password/{token}")).text.lower()

    mismatch = await client.post(f"/reset-password/{token}", data={"password": "new-password", "password_confirm": "nope-nope"})
    assert "don&#x27;t match" in mismatch.text  # HTML-escaped error message

    done = await client.post(f"/reset-password/{token}", data={"password": "new-password", "password_confirm": "new-password"})
    assert "Password changed" in done.text

    # Every existing session is signed out, the old password no longer works, the new one does.
    assert (await client.get("/api/me")).status_code == 401
    assert (await client.post("/api/login", json={"username": name, "password": "old-password"})).status_code == 401
    assert (await client.post("/api/login", json={"username": name, "password": "new-password"})).status_code == 200

    # Single use.
    again = await client.post(f"/reset-password/{token}", data={"password": "another-pw", "password_confirm": "another-pw"})
    assert "Link not valid" in again.text


async def test_password_reset_by_username(client, sent_emails):
    name = unique("byname")
    await register(client, name, email="byname@example.com")
    await client.post("/api/password/forgot", json={"identifier": name})
    await flush_tasks()
    assert sent_emails and sent_emails[0]["to"] == "byname@example.com"


async def test_forgot_password_does_not_reveal_accounts(client, sent_emails):
    name = unique("noemail")
    await register(client, name)  # no email on file
    a = await client.post("/api/password/forgot", json={"identifier": name})
    b = await client.post("/api/password/forgot", json={"identifier": "nobody-at-all@example.com"})
    await flush_tasks()
    assert a.status_code == b.status_code == 200 and a.json() == b.json()
    assert sent_emails == []


async def test_expired_reset_link_is_rejected(client, sent_emails):
    name = unique("slow")
    await register(client, name, email="slow@example.com")
    await client.post("/api/password/forgot", json={"identifier": name})
    await flush_tasks()
    token = await reset_token_from(sent_emails)
    async with main.AsyncSessionLocal() as db:
        await db.execute(update(main.PasswordResetModel).where(main.PasswordResetModel.token_hash == main._hash_token(token))
                         .values(expires_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()))
        await db.commit()
    r = await client.post(f"/reset-password/{token}", data={"password": "new-password", "password_confirm": "new-password"})
    assert "Link not valid" in r.text


# ── Export + deletion ─────────────────────────
async def make_user_with_data(client):
    me = await register(client, unique("full"), email="full@example.com")
    await client.post("/api/profile", json={"phone": "+1 555", "medical_notes": "Penicillin allergy"})
    await client.post("/api/guardians", json={"name": "Grace", "email": "g@example.com"})
    await client.post("/api/plans", json={"journey": {"user_name": "Alex", "destination": "Plan Peak"}})
    sid = (await client.post("/api/journey/start", json={"user_name": "Alex", "destination": "Summit"})).json()["session_id"]
    await client.post("/api/location/ping", json={"session_id": sid, "lat": 1.5, "lng": 2.5})
    await client.post("/api/message/send", json={"session_id": sid, "code": "SAFE123", "text": "all good"})
    await client.post("/api/feedback", json={"message": "Love it", "rating": 5})
    return me, sid


async def test_export_contains_all_user_data(client):
    me, sid = await make_user_with_data(client)
    r = await client.get("/api/account/export")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    data = r.json()
    assert data["account"]["medical_notes"] == "Penicillin allergy" and data["account"]["consented_at"]
    assert [g["name"] for g in data["guardians"]] == ["Grace"]
    assert [p["journey"]["destination"] for p in data["saved_journeys"]] == ["Plan Peak"]
    assert [j["session_id"] for j in data["journeys"]] == [sid]
    assert data["location_history"] and data["messages"] and data["events"]


async def count(model, *where):
    async with main.AsyncSessionLocal() as db:
        return (await db.execute(select(func.count()).select_from(model).where(*where))).scalar()


async def test_delete_account_removes_everything(client):
    me, sid = await make_user_with_data(client)
    uid = me["id"]

    assert (await client.request("DELETE", "/api/account", json={"password": "wrong-password"})).status_code == 403
    assert (await client.get("/api/me")).status_code == 200  # still there after a wrong password

    r = await client.request("DELETE", "/api/account", json={"password": "pw123456"})
    assert r.status_code == 200
    assert (await client.get("/api/me")).status_code == 401

    M = main
    assert await count(M.UserModel, M.UserModel.id == uid) == 0
    for model in (M.UserGuardianModel, M.JourneyPlanModel, M.PushSubscriptionModel, M.AuthSessionModel):
        assert await count(model, model.user_id == uid) == 0, model.__name__
    assert await count(M.SessionModel, M.SessionModel.session_id == sid) == 0
    for model in (M.EventModel, M.MessageModel, M.LocationPingModel):
        assert await count(model, model.session_id == sid) == 0, model.__name__
    # Feedback is kept, but no longer linked to the person.
    assert await count(M.FeedbackModel, M.FeedbackModel.user_id == uid) == 0
    assert await count(M.FeedbackModel, M.FeedbackModel.message == "Love it", M.FeedbackModel.username == "") >= 1


async def test_deleting_a_linked_guardian_keeps_travelers_entry(client, app):
    guardian_name = unique("gdn")
    async with new_client(app) as guardian:
        await register(guardian, guardian_name)
        await register(client, unique("trav"))
        g = (await client.post("/api/guardians", json={"name": "Gus", "linked_username": guardian_name})).json()
        await guardian.request("DELETE", "/api/account", json={"password": "pw123456"})
    listed = (await client.get("/api/guardians")).json()
    assert [x["id"] for x in listed] == [g["id"]]
    assert listed[0]["linked_user_id"] == "" and listed[0]["name"] == "Gus"


# ── Feedback ──────────────────────────────────
async def test_feedback_validation_and_admin_listing(client, app, monkeypatch):
    emailed = []

    async def fake_send(to, subject, body_html):
        emailed.append(body_html)

    monkeypatch.setattr(main, "send_html_email", fake_send)
    monkeypatch.setenv("FEEDBACK_EMAIL", "owner@example.com")
    await register(client, unique("tester"))
    assert (await client.post("/api/feedback", json={"message": "  "})).status_code == 400
    assert (await client.post("/api/feedback", json={"message": "x", "rating": 9})).status_code == 400
    marker = unique("great-app")
    r = await client.post("/api/feedback", json={"message": f"<b>{marker}</b>", "rating": 4, "app_version": "1.0.0-test"},
                          headers={"user-agent": "TestPhone/1.0"})
    assert r.status_code == 200
    await flush_tasks()
    assert emailed and "&lt;b&gt;" in emailed[-1]  # escaped in the email

    assert (await client.get("/api/admin/feedback")).status_code == 403
    async with new_client(app) as admin:
        await login_as_admin(admin)
        items = (await admin.get("/api/admin/feedback")).json()
    mine = next(f for f in items if marker in f["message"])
    assert mine["rating"] == 4 and mine["app_version"] == "1.0.0-test" and mine["user_agent"] == "TestPhone/1.0"


async def test_feedback_requires_login(client):
    assert (await client.post("/api/feedback", json={"message": "hi"})).status_code == 401


# ── Public pages / config ─────────────────────
@pytest.mark.parametrize("path,text", [("/privacy", "Privacy Policy"), ("/terms", "not an emergency service"),
                                       ("/delete-account", "Delete your Guardian Angel account")])
async def test_public_pages(client, path, text):
    r = await client.get(path)
    assert r.status_code == 200 and text in r.text


async def test_client_config(client):
    r = await client.get("/config.js")
    assert r.status_code == 200 and f'"appVersion": "{main.APP_VERSION}"' in r.text


async def test_assetlinks(client, monkeypatch):
    monkeypatch.delenv("ANDROID_PACKAGE_NAME", raising=False)
    assert (await client.get("/.well-known/assetlinks.json")).json() == []
    monkeypatch.setenv("ANDROID_PACKAGE_NAME", "app.guardianangel.twa")
    monkeypatch.setenv("ANDROID_CERT_SHA256", "aa:bb:cc, DD:EE:FF")
    data = (await client.get("/.well-known/assetlinks.json")).json()
    assert data[0]["target"]["package_name"] == "app.guardianangel.twa"
    assert data[0]["target"]["sha256_cert_fingerprints"] == ["AA:BB:CC", "DD:EE:FF"]
    assert data[0]["relation"] == ["delegate_permission/common.handle_all_urls"]


@pytest.mark.parametrize("name", ["..%5C.env", "..%5Cvapid.json", "..%5Cmain.py", "icon-192.svg", "%2E%2E%5C.env"])
async def test_icon_route_cannot_escape_icons_folder(client, name):
    assert (await client.get(f"/icons/{name}")).status_code == 404


async def test_icon_route_serves_icons(client):
    r = await client.get("/icons/icon-192.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


async def test_health_reports_storage_type(client):
    data = (await client.get("/health")).json()
    assert data["status"] == "ok" and data["persistent_storage"] is main.IS_POSTGRES
