"""Emergency numbers are now admin-editable data (DB-backed), not hardcoded code."""
import main
from conftest import login_as_admin, new_client, unique


async def test_non_admin_cannot_manage_emergency_numbers(client):
    await client.post("/api/register", json={"username": unique("regularjoe"), "password": "pw123456", "accept_terms": True})
    r = await client.get("/api/admin/emergency-numbers")
    assert r.status_code == 403
    r = await client.post("/api/admin/emergency-numbers", json={"country": "Wakanda", "number": "911"})
    assert r.status_code == 403


async def test_admin_can_upsert_and_it_takes_effect_immediately(client, app):
    async with new_client(app) as admin_client:
        await login_as_admin(admin_client)

        r = await admin_client.post("/api/admin/emergency-numbers", json={"country": "Testlandia", "number": "123"})
        assert r.status_code == 200, r.text
        assert r.json()["number"] == "123"

        # Takes effect immediately in the live lookup used by emails/case files — no restart needed.
        assert main.get_emergency_number("Testlandia") == "123"
        assert main.get_emergency_number("TESTLANDIA") == "123"  # case-insensitive

        listing = (await admin_client.get("/api/admin/emergency-numbers")).json()
        assert any(e["country"] == "testlandia" and e["number"] == "123" for e in listing)


async def test_admin_can_update_an_existing_entry(client, app):
    async with new_client(app) as admin_client:
        await login_as_admin(admin_client)
        await admin_client.post("/api/admin/emergency-numbers", json={"country": "Updateland", "number": "111"})
        r = await admin_client.post("/api/admin/emergency-numbers", json={"country": "Updateland", "number": "222"})
        assert r.status_code == 200
        assert main.get_emergency_number("Updateland") == "222"


async def test_admin_can_delete_an_entry(client, app):
    async with new_client(app) as admin_client:
        await login_as_admin(admin_client)
        await admin_client.post("/api/admin/emergency-numbers", json={"country": "Deleteland", "number": "999"})
        assert main.get_emergency_number("Deleteland") == "999"

        r = await admin_client.delete("/api/admin/emergency-numbers/Deleteland")
        assert r.status_code == 200
        assert main.get_emergency_number("Deleteland") == ""


async def test_seeded_from_the_original_static_table_on_first_boot(client, app):
    async with new_client(app) as admin_client:
        await login_as_admin(admin_client)
        listing = (await admin_client.get("/api/admin/emergency-numbers")).json()
        # Kenya was one of the original hardcoded entries — confirms the DB got seeded, not empty.
        assert any(e["country"] == "kenya" for e in listing)


async def test_every_configured_admin_username_has_admin_rights(client, app):
    for admin_username in main.ADMIN_USERNAMES:
        async with new_client(app) as admin_client:
            await login_as_admin(admin_client, username=admin_username)
            r = await admin_client.get("/api/admin/emergency-numbers")
            assert r.status_code == 200, f"{admin_username} should have admin access"
