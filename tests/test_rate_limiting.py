"""Rate limiting is disabled globally for the rest of the suite (tests legitimately
register/check-in far faster than a real user would) — this file re-enables it just
for itself, to prove the throttle on the guessable safe/duress codes actually works.
"""
import main
from conftest import sign_in, unique


async def test_checkin_gets_rate_limited_after_repeated_guessing(client):
    await sign_in(client)
    r = await client.post("/api/journey/start", json={
        "user_name": unique("RateLimitTest"), "destination": "Somewhere", "guardians": [],
    })
    sid = r.json()["session_id"]

    main.limiter.enabled = True
    try:
        statuses = []
        for _ in range(25):
            resp = await client.post("/api/checkin", json={"session_id": sid, "code": "WRONGCODE"})
            statuses.append(resp.status_code)
        assert 429 in statuses, f"expected a 429 somewhere in {statuses} after 25 rapid guesses"
    finally:
        main.limiter.enabled = False
