"""Real authentication — the fix for 'every endpoint trusts a client-supplied user_id'."""
from conftest import new_client, unique


async def test_register_sets_an_httponly_session_cookie(client):
    r = await client.post("/api/register", json={"username": unique("cookietest"), "password": "pw123456", "accept_terms": True})
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "")
    assert "ga_session=" in set_cookie
    assert "httponly" in set_cookie.lower()


async def test_me_reflects_the_logged_in_user(client):
    username = unique("metest")
    await client.post("/api/register", json={"username": username, "password": "pw123456", "accept_terms": True})
    me = (await client.get("/api/me")).json()
    assert me["username"] == username


async def test_me_requires_a_session(client):
    r = await client.get("/api/me")
    assert r.status_code == 401


async def test_logout_clears_the_session(client):
    await client.post("/api/register", json={"username": unique("logouttest"), "password": "pw123456", "accept_terms": True})
    assert (await client.get("/api/me")).status_code == 200

    r = await client.post("/api/logout")
    assert r.status_code == 200
    assert (await client.get("/api/me")).status_code == 401


async def test_wrong_password_is_rejected(client):
    username = unique("badpwtest")
    await client.post("/api/register", json={"username": username, "password": "correct-password", "accept_terms": True})
    await client.post("/api/logout")

    r = await client.post("/api/login", json={"username": username, "password": "wrong-password"})
    assert r.status_code == 401


async def test_account_scoped_endpoints_reject_a_client_supplied_user_id(client, app):
    """The exact vulnerability this migration closes: a stranger can no longer just
    say 'I am user X' by putting X's id in the request body."""
    async with new_client(app) as attacker_client:
        victim = await client.post("/api/register", json={"username": unique("victim"), "password": "pw123456", "accept_terms": True})
        victim_id = victim.json()["id"]

        # attacker_client is a fresh, logged-OUT client — no cookie at all
        r = await attacker_client.post("/api/guardians", json={
            "user_id": victim_id, "name": "Injected Guardian",
        })
        assert r.status_code == 401

        r = await attacker_client.get("/api/profile")
        assert r.status_code == 401


async def test_legacy_sha256_password_still_verifies_and_gets_upgraded(client):
    """Accounts created before the bcrypt migration must keep working, and get
    silently upgraded to bcrypt on their next successful login."""
    import hashlib
    import main

    username = unique("legacyuser")
    legacy_hash = hashlib.sha256(b"legacy-password").hexdigest()

    async with main.AsyncSessionLocal() as db:
        db.add(main.UserModel(
            id=unique("legacyid"), username=username, password_hash=legacy_hash,
            created_at="2020-01-01T00:00:00+00:00",
        ))
        await db.commit()

    r = await client.post("/api/login", json={"username": username, "password": "legacy-password"})
    assert r.status_code == 200, r.text

    async with main.AsyncSessionLocal() as db:
        from sqlalchemy import select
        result = await db.execute(select(main.UserModel).where(main.UserModel.username == username))
        user = result.scalar_one()
        assert user.password_hash.startswith("$2"), "should have been upgraded to bcrypt"
