"""Push notifications: the self-test endpoint and cleanup of subscriptions that can never work."""
import asyncio

import pytest
from sqlalchemy import func, select

import main
from conftest import new_client, sign_in


async def subscribe(client, endpoint="https://fcm.googleapis.com/fcm/send/abc"):
    r = await client.post("/api/push/subscribe", json={"endpoint": endpoint, "p256dh": "key", "auth": "auth"})
    assert r.status_code == 200, r.text


async def test_test_push_needs_login_and_a_device(client):
    assert (await client.post("/api/push/test")).status_code == 401
    await sign_in(client)
    r = await client.post("/api/push/test")
    assert r.status_code == 400 and "no device" in r.json()["detail"]


async def test_test_push_goes_only_to_own_devices(client, app, monkeypatch):
    sent = []

    async def fake_push(user_id, title, body_text, level):
        sent.append((user_id, title))

    monkeypatch.setattr(main, "send_push_to_user", fake_push)
    monkeypatch.setattr(main, "TEST_PUSH_DELAY_SECONDS", 0)
    me = await sign_in(client)
    await subscribe(client)
    async with new_client(app) as other:
        await sign_in(other)
        await subscribe(other, "https://fcm.googleapis.com/fcm/send/other")

    r = await client.post("/api/push/test")
    assert r.status_code == 200 and r.json()["devices"] == 1
    for _ in range(5):
        await asyncio.sleep(0)
    assert sent == [(me["id"], "🔔 Test notification")]


@pytest.mark.parametrize("status,removed", [(403, True), (404, True), (410, True), (500, False)])
async def test_unusable_subscriptions_are_removed(client, monkeypatch, status, removed):
    from pywebpush import WebPushException

    class Resp:
        status_code = status

    def failing_webpush(**kwargs):
        raise WebPushException("push failed", response=Resp())

    import pywebpush
    monkeypatch.setattr(pywebpush, "webpush", failing_webpush)
    me = await sign_in(client)
    await subscribe(client, f"https://fcm.googleapis.com/fcm/send/{status}")
    await main.send_push_to_user(me["id"], "t", "b", 1)
    async with main.AsyncSessionLocal() as db:
        left = (await db.execute(select(func.count()).select_from(main.PushSubscriptionModel)
                                 .where(main.PushSubscriptionModel.user_id == me["id"]))).scalar()
    assert left == (0 if removed else 1)


async def test_diagnostics_report_last_push_outcome(client, monkeypatch):
    from pywebpush import WebPushException

    class Resp:
        status_code = 403
        text = "the key in the authorization header does not correspond"

    def rejecting_webpush(**kwargs):
        raise WebPushException("push failed", response=Resp())

    import pywebpush
    me = await sign_in(client)
    assert (await client.get("/api/push/diagnostics")).json()["devices"] == 0

    await subscribe(client, "https://fcm.googleapis.com/fcm/send/diag")
    monkeypatch.setattr(pywebpush, "webpush", rejecting_webpush)
    await main.send_push_to_user(me["id"], "t", "b", 1)
    d = (await client.get("/api/push/diagnostics")).json()
    assert d["server_keys_ok"] is True
    res = d["last_attempt"]["results"][0]
    assert res == {"service": "fcm.googleapis.com", "ok": False, "status": 403,
                   "error": "the key in the authorization header does not correspond"}

    monkeypatch.setattr(pywebpush, "webpush", lambda **kw: None)
    await subscribe(client, "https://fcm.googleapis.com/fcm/send/diag2")
    await main.send_push_to_user(me["id"], "t", "b", 1)
    assert (await client.get("/api/push/diagnostics")).json()["last_attempt"]["results"][0]["ok"] is True


def test_mismatched_push_keys_are_detected(monkeypatch):
    assert main.vapid_keys_consistent() is True
    monkeypatch.setitem(main.VAPID, "public", "BAAAA" + main.VAPID["public"][5:])
    assert main.vapid_keys_consistent() is False


async def test_health_reports_push_keys(client):
    assert (await client.get("/health")).json()["push_keys_ok"] is True


async def test_real_push_library_signs_and_encrypts(client, monkeypatch):
    """Runs pywebpush for real (VAPID signing + payload encryption); only the HTTP call to Google is faked.
    Regression test: passing the PEM key as a string made every push fail with 'Could not deserialize key data'."""
    import base64
    import os as _os

    import requests
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()  # noqa: E731
    browser_key = ec.generate_private_key(ec.SECP256R1())
    p256dh = b64(browser_key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint))
    auth = b64(_os.urandom(16))

    sent = []

    class FakeResponse:
        status_code = 201
        text = ""
        headers = {}

    def fake_post(url, data=None, headers=None, timeout=None, **kw):
        sent.append({"url": url, "headers": headers, "body": data})
        return FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    me = await sign_in(client)
    r = await client.post("/api/push/subscribe", json={
        "endpoint": "https://fcm.googleapis.com/fcm/send/real-test", "p256dh": p256dh, "auth": auth})
    assert r.status_code == 200

    await main.send_push_to_user(me["id"], "🔔 Test", "hello", 1)

    last = (await client.get("/api/push/diagnostics")).json()["last_attempt"]
    assert last["results"][0]["ok"] is True, last
    assert sent and sent[0]["url"].endswith("/real-test")
    assert sent[0]["headers"]["Authorization"].startswith("vapid t=")  # signed with our key
    assert sent[0]["headers"]["Urgency"] == "high" and str(sent[0]["headers"]["ttl"]) == "3600"
    assert b"hello" not in sent[0]["body"]  # payload is encrypted
