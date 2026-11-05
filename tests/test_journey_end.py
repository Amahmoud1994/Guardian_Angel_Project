from conftest import sign_in, unique


async def test_journey_can_only_end_once(client):
    await sign_in(client)
    body = {"user_name": unique("EndTester"), "destination": "Somewhere", "guardians": []}
    sid = (await client.post("/api/journey/start", json=body)).json()["session_id"]

    r1 = await client.post(f"/api/journey/end?session_id={sid}")
    assert r1.status_code == 200

    r2 = await client.post(f"/api/journey/end?session_id={sid}")
    assert r2.status_code == 400

    s = (await client.get(f"/api/session/{sid}")).json()
    assert s["status"] == "ENDED"
