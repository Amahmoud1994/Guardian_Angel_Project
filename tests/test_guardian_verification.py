from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import main
from conftest import new_client, unique


async def register(client, username):
    r = await client.post("/api/register", json={"username": username, "password": "pw123456", "accept_terms": True})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def sent_emails(monkeypatch):
    """Capture verification emails instead of talking to a real SMTP server."""
    sent = []

    async def fake_send(to, subject, body_html):
        sent.append({"to": to, "subject": subject, "body": body_html})

    monkeypatch.setattr(main, "send_html_email", fake_send)
    return sent


async def add_guardian(client, email="g@example.com"):
    r = await client.post("/api/guardians", json={"name": "Grace", "email": email})
    assert r.status_code == 200, r.text
    return r.json()


async def token_for(guardian_id):
    async with main.AsyncSessionLocal() as db:
        g = (await db.execute(
            select(main.UserGuardianModel).where(main.UserGuardianModel.id == guardian_id)
        )).scalar_one()
        return g.verify_token


async def test_new_guardian_starts_unverified(client):
    await register(client, unique("trav"))
    g = await add_guardian(client)
    assert g["verified"] is False
    assert g["verification"] == ""


async def test_accepting_verification_marks_guardian_verified(client, sent_emails):
    await register(client, unique("trav"))
    g = await add_guardian(client)

    r = await client.post(f"/api/guardians/{g['id']}/verify")
    assert r.status_code == 200, r.text
    assert r.json()["verification"] == "pending"
    assert r.json()["verified"] is False
    assert len(sent_emails) == 1 and sent_emails[0]["to"] == "g@example.com"

    token = await token_for(g["id"])
    assert token and f"/verify-guardian/{token}" in sent_emails[0]["body"]

    # Opening the link (or an email scanner prefetching it) must NOT accept on its own.
    page = await client.get(f"/verify-guardian/{token}")
    assert page.status_code == 200 and "Accept" in page.text
    listed = (await client.get("/api/guardians")).json()
    assert listed[0]["verified"] is False

    done = await client.post(f"/verify-guardian/{token}/accept")
    assert done.status_code == 200 and "verified" in done.text

    listed = (await client.get("/api/guardians")).json()
    assert listed[0]["verified"] is True
    assert listed[0]["verification"] == "verified"


async def test_declining_verification(client, sent_emails):
    await register(client, unique("trav"))
    g = await add_guardian(client)
    await client.post(f"/api/guardians/{g['id']}/verify")
    token = await token_for(g["id"])

    await client.post(f"/verify-guardian/{token}/decline")
    listed = (await client.get("/api/guardians")).json()
    assert listed[0]["verified"] is False
    assert listed[0]["verification"] == "declined"


async def test_verification_link_is_single_use(client, sent_emails):
    await register(client, unique("trav"))
    g = await add_guardian(client)
    await client.post(f"/api/guardians/{g['id']}/verify")
    token = await token_for(g["id"])

    await client.post(f"/verify-guardian/{token}/accept")
    again = await client.post(f"/verify-guardian/{token}/decline")
    assert "Link not valid" in again.text
    assert (await client.get("/api/guardians")).json()[0]["verified"] is True


async def test_expired_verification_link_is_rejected(client, sent_emails):
    await register(client, unique("trav"))
    g = await add_guardian(client)
    await client.post(f"/api/guardians/{g['id']}/verify")
    token = await token_for(g["id"])

    async with main.AsyncSessionLocal() as db:
        row = (await db.execute(
            select(main.UserGuardianModel).where(main.UserGuardianModel.id == g["id"])
        )).scalar_one()
        row.verify_sent_at = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        await db.commit()

    r = await client.post(f"/verify-guardian/{token}/accept")
    assert "Link not valid" in r.text
    assert (await client.get("/api/guardians")).json()[0]["verified"] is False


async def test_bogus_token_is_rejected(client):
    r = await client.get("/verify-guardian/not-a-real-token")
    assert r.status_code == 200 and "Link not valid" in r.text


async def test_verify_requires_guardian_email(client, sent_emails):
    await register(client, unique("trav"))
    g = await add_guardian(client, email="")
    r = await client.post(f"/api/guardians/{g['id']}/verify")
    assert r.status_code == 400
    assert sent_emails == []


async def test_cannot_verify_someone_elses_guardian(client, app, sent_emails):
    await register(client, unique("owner"))
    g = await add_guardian(client)
    async with new_client(app) as other:
        await register(other, unique("other"))
        r = await other.post(f"/api/guardians/{g['id']}/verify")
        assert r.status_code == 403
    assert sent_emails == []


async def test_email_failure_leaves_guardian_unverified(client, monkeypatch):
    async def failing_send(*_):
        raise RuntimeError("SMTP down")

    monkeypatch.setattr(main, "send_html_email", failing_send)
    await register(client, unique("trav"))
    g = await add_guardian(client)
    r = await client.post(f"/api/guardians/{g['id']}/verify")
    assert r.status_code == 502
    assert (await client.get("/api/guardians")).json()[0]["verification"] == ""


async def test_linked_app_user_who_accepted_counts_as_verified(client, app):
    traveler_name, guardian_name = unique("trav"), unique("guard")
    async with new_client(app) as guardian:
        await register(guardian, guardian_name)
        await register(client, traveler_name)
        r = await client.post("/api/guardians", json={"name": "Gus", "linked_username": guardian_name})
        g = r.json()
        assert g["verified"] is False  # still pending their in-app confirmation

        r = await guardian.post(f"/api/guardians/{g['id']}/respond", json={"accept": True})
        assert r.status_code == 200
    assert (await client.get("/api/guardians")).json()[0]["verified"] is True
