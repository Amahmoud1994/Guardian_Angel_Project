from conftest import new_client, unique


async def register(client, username):
    r = await client.post("/api/register", json={"username": username, "password": "pw123456", "accept_terms": True})
    assert r.status_code == 200, r.text
    return r.json()


async def test_guardian_inbox_hidden_until_accepted_then_visible(client, app):
    # Three independent cookie jars — three simultaneously logged-in identities,
    # exactly like three different browsers/people.
    async with new_client(app) as guardian_client, new_client(app) as bystander_client:
        traveler = await register(client, unique("traveler"))
        guardian_user = await register(guardian_client, unique("guardianuser"))
        await register(bystander_client, unique("bystander"))

        saved = await client.post("/api/guardians", json={
            "name": "Linked Friend", "linked_username": guardian_user["username"],
        })
        assert saved.status_code == 200, saved.text
        assert saved.json()["linked_user_id"] == guardian_user["id"]
        assert saved.json()["status"] == "pending"
        guardian_row_id = saved.json()["id"]

        r = await client.post("/api/journey/start", json={
            "user_name": traveler["username"], "destination": "Inbox Test",
            "guardians": [{"name": "Linked Friend", "linked_user_id": guardian_user["id"]}],
        })
        assert r.status_code == 200, r.text
        sid = r.json()["session_id"]

        # Not accepted yet — must not show up, even though the link exists.
        inbox_before = (await guardian_client.get("/api/guardian-inbox")).json()
        assert not any(s["session_id"] == sid for s in inbox_before)

        # The guardian sees it as a pending request and accepts it.
        requests = (await guardian_client.get("/api/guardian-requests")).json()
        assert any(r["id"] == guardian_row_id for r in requests)
        resp = await guardian_client.post(f"/api/guardians/{guardian_row_id}/respond", json={"accept": True})
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "accepted"

        inbox_after = (await guardian_client.get("/api/guardian-inbox")).json()
        assert any(s["session_id"] == sid for s in inbox_after)

        bystander_inbox = (await bystander_client.get("/api/guardian-inbox")).json()
        assert not any(s["session_id"] == sid for s in bystander_inbox)


async def test_declined_guardian_request_never_shows_in_inbox(client, app):
    async with new_client(app) as guardian_client:
        await register(client, unique("traveler4"))
        guardian_user = await register(guardian_client, unique("guardianuser4"))

        saved = await client.post("/api/guardians", json={
            "name": "Linked Friend", "linked_username": guardian_user["username"],
        })
        guardian_row_id = saved.json()["id"]

        r = await client.post("/api/journey/start", json={
            "user_name": "traveler4", "destination": "Decline Test",
            "guardians": [{"name": "Linked Friend", "linked_user_id": guardian_user["id"]}],
        })
        sid = r.json()["session_id"]

        resp = await guardian_client.post(f"/api/guardians/{guardian_row_id}/respond", json={"accept": False})
        assert resp.json()["status"] == "declined"

        inbox = (await guardian_client.get("/api/guardian-inbox")).json()
        assert not any(s["session_id"] == sid for s in inbox)


async def test_cannot_respond_to_someone_elses_guardian_request(client, app):
    async with new_client(app) as guardian_client, new_client(app) as intruder_client:
        await register(client, unique("traveler5"))
        guardian_user = await register(guardian_client, unique("guardianuser5"))
        await register(intruder_client, unique("intruder2"))

        saved = await client.post("/api/guardians", json={
            "name": "Linked Friend", "linked_username": guardian_user["username"],
        })
        guardian_row_id = saved.json()["id"]

        r = await intruder_client.post(f"/api/guardians/{guardian_row_id}/respond", json={"accept": True})
        assert r.status_code == 403


async def test_guardian_inbox_requires_login(client):
    r = await client.get("/api/guardian-inbox")
    assert r.status_code == 401


async def test_linking_unknown_username_is_rejected(client):
    await register(client, unique("traveler2"))
    r = await client.post("/api/guardians", json={
        "name": "Ghost", "linked_username": unique("nobody_by_this_name"),
    })
    assert r.status_code == 404


async def test_cannot_delete_someone_elses_guardian(client, app):
    async with new_client(app) as other_client:
        await register(client, unique("owner"))
        g = (await client.post("/api/guardians", json={"name": "Mine"})).json()

        await register(other_client, unique("intruder"))
        r = await other_client.delete(f"/api/guardians/{g['id']}")
        assert r.status_code == 403


async def test_guardian_reply_uses_real_account_identity_not_spoofed_name(client, app):
    async with new_client(app) as guardian_client:
        traveler = await register(client, unique("traveler3"))
        guardian_user = await register(guardian_client, unique("guardianuser3"))
        g = (await client.post("/api/guardians", json={"name": "Gus", "linked_username": guardian_user["username"]})).json()
        await guardian_client.post(f"/api/guardians/{g['id']}/respond", json={"accept": True})

        r = await client.post("/api/journey/start", json={
            "user_name": traveler["username"], "destination": "Identity Test", "guardians": [],
        })
        sid = r.json()["session_id"]

        # The linked guardian, logged in, shows up under their real account name whatever they type.
        await guardian_client.post("/api/message/guardian-reply", json={
            "session_id": sid, "guardian_name": "Totally Someone Else", "text": "hi",
        })
        messages = (await client.get(f"/api/messages?session_id={sid}")).json()
        assert messages[-1]["sender_label"] == guardian_user["username"]


async def test_guardian_reply_cannot_borrow_someone_elses_account_name(client, app):
    async with new_client(app) as guardian_client:
        await register(client, unique("traveler4"))
        guardian_user = await register(guardian_client, unique("guardianuser4"))
        sid = (await client.post("/api/journey/start", json={"user_name": "T", "destination": "Spoof Test"})).json()["session_id"]

        # Anyone can pass someone's account id — it must be ignored (only a logged-in, linked guardian counts).
        async with new_client(app) as stranger:
            await stranger.post("/api/message/guardian-reply", json={
                "session_id": sid, "guardian_user_id": guardian_user["id"], "guardian_name": "Stranger", "text": "hi",
            })
        messages = (await client.get(f"/api/messages?session_id={sid}")).json()
        assert messages[-1]["sender_label"] == "Stranger"
