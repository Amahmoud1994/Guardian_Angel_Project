from conftest import sign_in, unique


async def start_trip(client):
    await sign_in(client)
    r = await client.post("/api/journey/start", json={
        "user_name": unique("LocTester"), "destination": "Somewhere", "guardians": [],
    })
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


async def test_ping_updates_last_location_and_is_recorded_in_history(client):
    sid = await start_trip(client)

    r = await client.post("/api/location/ping", json={"session_id": sid, "lat": 1.2921, "lng": 36.8219})
    assert r.status_code == 200, r.text

    s = (await client.get(f"/api/session/{sid}")).json()
    assert s["last_location"] == "1.2921,36.8219"

    history = (await client.get(f"/api/location/history?session_id={sid}")).json()
    assert len(history) == 1
    assert history[0]["lat"] == "1.2921"
    assert history[0]["lng"] == "36.8219"


async def test_history_keeps_multiple_points_in_chronological_order(client):
    sid = await start_trip(client)
    points = [(1.0, 1.0), (2.0, 2.0), (3.0, 3.0)]
    for lat, lng in points:
        r = await client.post("/api/location/ping", json={"session_id": sid, "lat": lat, "lng": lng})
        assert r.status_code == 200

    history = (await client.get(f"/api/location/history?session_id={sid}")).json()
    assert len(history) == 3
    assert [float(p["lat"]) for p in history] == [1.0, 2.0, 3.0]


async def test_ping_requires_no_code_but_rejects_ended_journeys(client):
    sid = await start_trip(client)
    await client.post(f"/api/journey/end?session_id={sid}")

    r = await client.post("/api/location/ping", json={"session_id": sid, "lat": 1.0, "lng": 1.0})
    assert r.status_code == 400


async def test_ping_on_unknown_session_404s(client):
    await sign_in(client)
    r = await client.post("/api/location/ping", json={"session_id": "does-not-exist", "lat": 1.0, "lng": 1.0})
    assert r.status_code == 404
