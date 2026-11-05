"""Safe/duress code branching — the app's core duress-detection mechanic.

Both /api/checkin and /api/message/send share apply_safe_checkin/trigger_duress
in main.py; covering both endpoints locks in that the refactor didn't diverge them.
"""
from conftest import sign_in, unique


async def start_trip(client, **overrides):
    body = {
        "user_name": unique("Tester"),
        "destination": "Test Destination",
        "check_in_interval_minutes": 30,
        "guardians": [],
        **overrides,
    }
    await sign_in(client)
    r = await client.post("/api/journey/start", json=body)
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


async def test_safe_code_resets_to_active_level_zero(client):
    sid = await start_trip(client)

    r = await client.post("/api/checkin", json={"session_id": sid, "code": "SAFE123"})
    assert r.status_code == 200, r.text

    s = (await client.get(f"/api/session/{sid}")).json()
    assert s["escalation_level"] == 0
    assert s["status"] == "ACTIVE"
    assert s["last_checkin"] is not None


async def test_duress_code_silently_escalates_to_level_four(client):
    sid = await start_trip(client)

    r = await client.post("/api/checkin", json={"session_id": sid, "code": "HELP999"})
    assert r.status_code == 200, r.text
    # response is intentionally identical in shape to the safe-code response —
    # no visible tell for someone watching the screen
    assert "next_checkin" in r.json()

    s = (await client.get(f"/api/session/{sid}")).json()
    assert s["escalation_level"] == 4
    assert s["status"] == "DURESS"
    # The full case file is no longer inlined into the public session payload (it's
    # encrypted at rest and only served via the dedicated, access-controlled endpoint).
    assert s["case_file_available"] is True
    assert "case_file" not in s

    # The journey's own (signed-in) owner can open the case file.
    case = await client.get(f"/api/case/{sid}")
    assert case.status_code == 200, case.text
    assert case.json()["subject"]


async def test_wrong_code_is_rejected(client):
    sid = await start_trip(client)
    r = await client.post("/api/checkin", json={"session_id": sid, "code": "NOPE"})
    assert r.status_code == 403


async def test_ended_journey_cannot_be_checked_in(client):
    sid = await start_trip(client)
    r = await client.post(f"/api/journey/end?session_id={sid}")
    assert r.status_code == 200

    r = await client.post("/api/checkin", json={"session_id": sid, "code": "SAFE123"})
    assert r.status_code == 400


async def test_message_send_with_safe_code_resets_and_stores_message(client):
    sid = await start_trip(client)

    r = await client.post("/api/message/send", json={"session_id": sid, "code": "SAFE123", "text": "All good!"})
    assert r.status_code == 200, r.text

    s = (await client.get(f"/api/session/{sid}")).json()
    assert s["escalation_level"] == 0
    assert s["status"] == "ACTIVE"

    messages = (await client.get(f"/api/messages?session_id={sid}")).json()
    assert len(messages) == 1
    assert messages[0]["sender"] == "user"
    assert messages[0]["text"] == "All good!"


async def test_message_send_with_duress_code_still_delivers_but_escalates_silently(client):
    sid = await start_trip(client)

    r = await client.post("/api/message/send", json={"session_id": sid, "code": "HELP999", "text": "on my way home"})
    assert r.status_code == 200, r.text

    s = (await client.get(f"/api/session/{sid}")).json()
    assert s["escalation_level"] == 4
    assert s["status"] == "DURESS"

    messages = (await client.get(f"/api/messages?session_id={sid}")).json()
    assert any(m["text"] == "on my way home" for m in messages)


async def test_message_send_requires_text(client):
    sid = await start_trip(client)
    r = await client.post("/api/message/send", json={"session_id": sid, "code": "SAFE123", "text": "   "})
    assert r.status_code == 400


async def test_guardian_reply_never_changes_escalation(client):
    sid = await start_trip(client)
    r = await client.post("/api/message/guardian-reply", json={
        "session_id": sid, "guardian_name": "Mom", "text": "Call me!",
    })
    assert r.status_code == 200, r.text

    s = (await client.get(f"/api/session/{sid}")).json()
    assert s["escalation_level"] == 0
    assert s["status"] == "ACTIVE"
