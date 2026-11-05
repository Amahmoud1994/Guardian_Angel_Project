"""Case file is encrypted at rest and only served to the journey's own owner or the admin."""
import main
from conftest import login_as_admin, new_client, sign_in, unique


async def make_duress_session(client, user_name="Owner"):
    await sign_in(client, "caseowner")
    r = await client.post("/api/journey/start", json={
        "user_name": user_name, "destination": "Case File Test", "guardians": [],
    })
    sid = r.json()["session_id"]
    await client.post("/api/checkin", json={"session_id": sid, "code": "HELP999"})
    return sid


async def test_case_file_is_encrypted_at_rest(client):
    sid = await make_duress_session(client)

    async with main.AsyncSessionLocal() as db:
        from sqlalchemy import select
        result = await db.execute(select(main.SessionModel).where(main.SessionModel.session_id == sid))
        s = result.scalar_one()
        assert s.case_file is not None
        assert "Case File Test" not in s.case_file  # plaintext destination shouldn't appear in the stored blob
        decrypted = main.decrypt_case_file(s.case_file)
        assert decrypted["destination"] == "Case File Test"


async def test_owner_can_view_their_own_case_file(client, app):
    async with new_client(app) as owner_client:
        owner = await owner_client.post("/api/register", json={"username": unique("caseowner"), "password": "pw123456", "accept_terms": True})
        owner = owner.json()

        r = await owner_client.post("/api/journey/start", json={
            "user_name": owner["username"], "destination": "Owner Case Test", "guardians": [],
        })
        sid = r.json()["session_id"]
        await owner_client.post("/api/checkin", json={"session_id": sid, "code": "HELP999"})

        case = await owner_client.get(f"/api/case/{sid}")
        assert case.status_code == 200
        assert case.json()["destination"] == "Owner Case Test"


async def test_non_owner_non_admin_cannot_view_case_file(client, app):
    async with new_client(app) as owner_client, new_client(app) as stranger_client:
        owner = (await owner_client.post("/api/register", json={"username": unique("caseowner2"), "password": "pw123456", "accept_terms": True})).json()
        await stranger_client.post("/api/register", json={"username": unique("stranger"), "password": "pw123456", "accept_terms": True})

        r = await owner_client.post("/api/journey/start", json={
            "user_name": owner["username"], "destination": "Private Case Test", "guardians": [],
        })
        sid = r.json()["session_id"]
        await owner_client.post("/api/checkin", json={"session_id": sid, "code": "HELP999"})

        r = await stranger_client.get(f"/api/case/{sid}")
        assert r.status_code == 403


async def test_admin_can_view_anyones_case_file(client, app):
    async with new_client(app) as owner_client, new_client(app) as admin_client:
        owner = (await owner_client.post("/api/register", json={"username": unique("caseowner3"), "password": "pw123456", "accept_terms": True})).json()
        await login_as_admin(admin_client)

        r = await owner_client.post("/api/journey/start", json={
            "user_name": owner["username"], "destination": "Admin View Test", "guardians": [],
        })
        sid = r.json()["session_id"]
        await owner_client.post("/api/checkin", json={"session_id": sid, "code": "HELP999"})

        r = await admin_client.get(f"/api/case/{sid}")
        assert r.status_code == 200
        assert r.json()["destination"] == "Admin View Test"


async def test_no_login_at_all_is_rejected(client):
    sid = await make_duress_session(client)
    await client.post("/api/logout")
    r = await client.get(f"/api/case/{sid}")
    assert r.status_code == 401


async def test_session_payload_no_longer_inlines_the_full_case_file(client):
    sid = await make_duress_session(client)
    s = (await client.get(f"/api/session/{sid}")).json()
    assert s["case_file_available"] is True
    assert "case_file" not in s
