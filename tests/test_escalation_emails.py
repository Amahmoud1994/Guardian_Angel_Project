"""Guardians are emailed from escalation Level 2 on; Level 1 only reminds the traveler. Duress always emails."""
import asyncio

from conftest import sign_in

import main


async def test_guardian_emails_start_at_level_two(client, monkeypatch):
    emailed = []

    async def fake_alert(s, level, message_text=None):
        emailed.append(level)

    async def no_push(*a, **k):
        pass

    monkeypatch.setattr(main, "send_alert_emails", fake_alert)
    monkeypatch.setattr(main, "send_push_to_user", no_push)
    await sign_in(client)
    sid = (await client.post("/api/journey/start", json={
        "user_name": "Mia", "destination": "Peak", "guardians": [{"name": "Grace", "email": "grace@example.com"}],
    })).json()["session_id"]

    for _ in range(4):
        async with main.AsyncSessionLocal() as db:
            await main.escalate(db, sid)
        await asyncio.sleep(0)
    assert emailed == [2, 3, 4]


async def test_duress_still_emails_immediately(client, monkeypatch):
    emailed = []

    async def fake_alert(s, level, message_text=None):
        emailed.append(level)

    async def no_push(*a, **k):
        pass

    monkeypatch.setattr(main, "send_alert_emails", fake_alert)
    monkeypatch.setattr(main, "send_push_to_user", no_push)
    await sign_in(client)
    sid = (await client.post("/api/journey/start", json={"user_name": "Mia", "destination": "Peak"})).json()["session_id"]
    await client.post("/api/checkin", json={"session_id": sid, "code": "HELP999"})
    await asyncio.sleep(0)
    assert emailed == [4]
