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
