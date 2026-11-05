import pytest

import beta
import main
from conftest import login_as_admin, new_client, unique


@pytest.fixture
def sent_emails(monkeypatch):
    sent = []

    async def fake_send(to, subject, body_html):
        sent.append({"to": to, "subject": subject, "body": body_html})

    monkeypatch.setattr(main, "send_html_email", fake_send)
    return sent


def application(**over):
    data = {"name": "Mia", "email": f"{unique('mia')}@gmail.com", "country": "Austria", "platform": "android",
            "use_cases": ["hiking", "solo_travel"], "trip_frequency": "weekly", "guardian": "yes", "feedback": "survey",
            "motivation": "I hike alone most weekends and my partner always worries until I'm back home safely.",
            "heard_from": "facebook", "adult": "yes", "commit_14_days": "yes", "consent": "yes"}
    data.update(over)
    return data


async def flush():
    import asyncio
    for _ in range(3):
        await asyncio.sleep(0)


async def admin_list(app):
    async with new_client(app) as admin:
        await login_as_admin(admin)
        return (await admin.get("/api/admin/beta")).json()


# ── Scoring ───────────────────────────────────
def test_score_rewards_engaged_applicants():
    keen = beta.validate(application())[0]
    lukewarm = beta.validate(application(use_cases=["other"], trip_frequency="none", guardian="no",
                                         feedback="none", motivation=""))[0]
    assert beta.score(keen) == 95  # 20 use-case pts for two strong use cases (25 needs three)
    assert beta.score(lukewarm) == 3
    assert beta.is_eligible(keen) and beta.is_eligible(lukewarm)


def test_iphone_users_are_waitlisted_not_eligible():
    a, errors = beta.validate({"name": "Ian", "email": "ian@icloud.com", "country": "UK", "platform": "iphone", "consent": "yes"})
    assert errors == [] and not beta.is_eligible(a)


# ── Public form ───────────────────────────────
async def test_beta_form_renders(client):
    r = await client.get("/beta")
    assert r.status_code == 200 and "Become a Guardian Angel beta tester" in r.text


async def test_apply_stores_scored_application_and_confirms(client, app, sent_emails):
    data = application()
    r = await client.post("/beta", data=data)
    assert r.status_code == 200 and "Application received" in r.text
    await flush()
    assert sent_emails and sent_emails[0]["to"] == data["email"]

    mine = next(x for x in await admin_list(app) if x["email"] == data["email"])
    assert mine["score"] == 95 and mine["eligible"] and mine["status"] == "new"
    assert mine["answers"]["use_cases"] == ["solo_travel", "hiking"] or set(mine["answers"]["use_cases"]) == {"hiking", "solo_travel"}


async def test_missing_answers_show_errors_and_keep_values(client):
    r = await client.post("/beta", data=application(email="not-an-email", commit_14_days="", name="Keep&Me"))
    assert r.status_code == 400
    assert "valid email" in r.text and "14 days" in r.text
    assert "Keep&amp;Me" in r.text  # value kept, and escaped


async def test_reapplying_updates_instead_of_duplicating(client, app, sent_emails):
    data = application()
    await client.post("/beta", data=data)
    await client.post("/beta", data={**data, "feedback": "in_app"})
    mine = [x for x in await admin_list(app) if x["email"] == data["email"]]
    assert len(mine) == 1 and mine[0]["answers"]["feedback"] == "in_app"


async def test_honeypot_is_silently_ignored(client, app, sent_emails):
    data = application(website="http://spam.example")
    r = await client.post("/beta", data=data)
    assert r.status_code == 200
    assert not [x for x in await admin_list(app) if x["email"] == data["email"]]


# ── Admin ─────────────────────────────────────
async def test_beta_admin_requires_admin(client):
    await client.post("/api/register", json={"username": unique("plain"), "password": "pw123456", "accept_terms": True})
    assert (await client.get("/api/admin/beta")).status_code == 403
    assert (await client.post("/api/admin/beta/invite", json={"ids": [], "optin_url": "https://play.google.com/x"})).status_code == 403


async def test_shortlist_and_invite(client, app, sent_emails):
    android, iphone = application(), application(platform="iphone")
    await client.post("/beta", data=android)
    await client.post("/beta", data=iphone)
    async with new_client(app) as admin:
        await login_as_admin(admin)
        rows = {x["email"]: x for x in (await admin.get("/api/admin/beta")).json()}
        ids = [rows[android["email"]]["id"], rows[iphone["email"]]["id"]]

        assert (await admin.post("/api/admin/beta/status", json={"ids": ids[:1], "status": "shortlisted"})).status_code == 200
        bad = await admin.post("/api/admin/beta/invite", json={"ids": ids, "optin_url": "https://evil.example/join"})
        assert bad.status_code == 400

        sent_emails.clear()
        r = await admin.post("/api/admin/beta/invite", json={
            "ids": ids, "optin_url": "https://play.google.com/apps/testing/at.guardianangel.twa"})
        result = r.json()
        assert result["sent"] == [android["email"]]
        assert result["failed"][0]["email"] == iphone["email"]
        invite = next(m for m in sent_emails if m["to"] == android["email"])
        assert "https://play.google.com/apps/testing/at.guardianangel.twa" in invite["body"]
        assert "play.google.com/store/apps/details?id=" in invite["body"]

        rows = {x["email"]: x for x in (await admin.get("/api/admin/beta")).json()}
        assert rows[android["email"]]["status"] == "invited" and rows[android["email"]]["invited_at"]

        assert (await admin.delete(f"/api/admin/beta/{ids[1]}")).status_code == 200
        assert iphone["email"] not in {x["email"] for x in (await admin.get("/api/admin/beta")).json()}


# ── Invite-only registration ──────────────────
async def register_with(client, email, username=None):
    return await client.post("/api/register", json={"username": username or unique("u"), "password": "pw123456",
                                                    "email": email, "accept_terms": True})


async def set_status(app, email, status):
    async with new_client(app) as admin:
        await login_as_admin(admin)
        row = next(x for x in (await admin.get("/api/admin/beta")).json() if x["email"] == email)
        await admin.post("/api/admin/beta/status", json={"ids": [row["id"]], "status": status})


async def test_invite_only_blocks_strangers(client, monkeypatch):
    monkeypatch.setenv("BETA_INVITE_ONLY", "true")
    r = await register_with(client, f"{unique('stranger')}@gmail.com")
    assert r.status_code == 403 and "/beta" in r.json()["detail"]
    assert (await register_with(client, "")).status_code == 403


async def test_invite_only_lets_shortlisted_applicants_in_once(client, app, sent_emails, monkeypatch):
    data = application()
    async with new_client(app) as applicant:
        await applicant.post("/beta", data=data)
    monkeypatch.setenv("BETA_INVITE_ONLY", "true")

    assert (await register_with(client, data["email"])).status_code == 403  # applied, but not chosen yet
    await set_status(app, data["email"], "shortlisted")
    async with new_client(app) as tester:
        r = await register_with(tester, data["email"].upper())  # email match is case-insensitive
        assert r.status_code == 200, r.text
    async with new_client(app) as again:
        assert (await register_with(again, data["email"])).status_code == 400  # one account per invite


async def test_declined_applicants_stay_out(client, app, sent_emails, monkeypatch):
    data = application()
    await client.post("/beta", data=data)
    await set_status(app, data["email"], "declined")
    monkeypatch.setenv("BETA_INVITE_ONLY", "true")
    assert (await register_with(client, data["email"])).status_code == 403


async def test_allowlisted_emails_and_admins_bypass(client, app, monkeypatch):
    monkeypatch.setenv("BETA_INVITE_ONLY", "true")
    reviewer = f"{unique('reviewer')}@gmail.com"
    monkeypatch.setenv("BETA_ALLOWED_EMAILS", f"someone@example.com, {reviewer.upper()}")
    assert (await register_with(client, reviewer)).status_code == 200
    async with new_client(app) as admin:
        admin_name = sorted(main.ADMIN_USERNAMES)[-1]
        r = await admin.post("/api/register", json={"username": admin_name, "password": "admin-pw-123456", "accept_terms": True})
        assert r.status_code in (200, 400)  # 400 = admin already registered earlier in the run — never 403
        assert r.status_code != 403


async def test_login_still_works_when_invite_only(client, monkeypatch):
    name = unique("existing")
    await client.post("/api/register", json={"username": name, "password": "pw123456", "accept_terms": True})
    monkeypatch.setenv("BETA_INVITE_ONLY", "true")
    assert (await client.post("/api/login", json={"username": name, "password": "pw123456"})).status_code == 200


async def test_config_reports_invite_only(client, monkeypatch):
    monkeypatch.setenv("BETA_INVITE_ONLY", "true")
    assert '"inviteOnly": true' in (await client.get("/config.js")).text
    monkeypatch.delenv("BETA_INVITE_ONLY")
    assert '"inviteOnly": false' in (await client.get("/config.js")).text
