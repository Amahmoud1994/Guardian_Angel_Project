# 🛡 Guardian Angel — POC

A "Dead Man's Switch" personal safety app. Server-side escalation engine.

## Features

- **Trip journeys** — one-off check-ins with a destination, route, coordinates, a Google Maps link, communication method, traveling companions, and a destination country (drives an emergency-number lookup for guardians).
- **Daily Usage** — a recurring, always-on alternative to one-off trips: define one or more active time windows and which days of the week they apply, and the app checks in on you automatically every day within those windows.
- **4-level escalation ladder** — check-in reminder → warning → guardian alert (email) → digital case file, with a Safe Code / Duress Code pair at every check-in so a duress situation escalates silently while looking identical to a normal check-in.
- **Two-way messaging** — send guardians a short message alongside your Safe Code (resets the escalation exactly like a normal check-in) or your Duress Code (still delivers, but keeps escalating silently). Guardians reply via a no-login link in their alert email, or — if they're also a Guardian Angel user — natively in their own account's **Guardian Inbox**.
- **Profile** — photo, address, phone, date of birth, blood type, and medical notes, surfaced to guardians in the case file when it matters.
- **PWA + push** — installable on a phone, Web Push notifications, and repeating vibration/sound/popup alerts for high-severity escalations until acknowledged.
- **Real accounts** — bcrypt-hashed passwords, httpOnly session cookies, and guardians can optionally be linked to their own account by username, with a **consent step**: linking is `pending` until the other account accepts it — they never appear in a stranger's Guardian Inbox without agreeing first.
- **Live location** — opt-in, adaptive-frequency GPS pinging (more often as the alert level rises) instead of a single manual coordinate, with a trail guardians can see on the no-login guardian page.
- **Encrypted case files** — the Level-4 digital case file is encrypted at rest and only decryptable by the journey's own account or the admin.
- **Admin-editable emergency numbers** — the per-country emergency-number table lives in the database, not hardcoded, so it can be corrected/extended without a redeploy.

## Quick Start

```bash
pip install -r requirements.txt
bash run.sh
# → Open http://localhost:8000
```

## Tests

```bash
pytest
```

49 tests, runs against an isolated temp SQLite DB (not `guardian_angel.db`), with rate limiting disabled by default so the suite can register/check-in as fast as it needs to — `tests/test_rate_limiting.py` re-enables it just for itself to prove the throttle actually works.

## Architecture

```
guardian_angel/
├── main.py               # FastAPI backend — escalation engine, all API routes
├── index.html            # Mobile-responsive PWA (main app)
├── guardian.html         # No-login page guardians use to view a case + reply
├── sw.js                 # Service worker — offline cache + Web Push
├── manifest.json         # PWA manifest
├── tests/                # pytest suite (safety logic, auth, rate limiting)
├── pytest.ini
├── .gitignore
├── .env.example           # copy to .env — SMTP + APP_BASE_URL config
├── requirements.txt
└── run.sh
```

## API Endpoints

**Account**
| Method | Path | Description |
|--------|------|-------------|
| POST | /api/register | Create an account (sets a session cookie) |
| POST | /api/login | Sign in (sets a session cookie) |
| POST | /api/logout | Clear the session |
| GET  | /api/me | Who am I signed in as |
| GET/POST | /api/profile | Read/update photo, address, phone, DOB, blood type, medical notes |

**Journeys & Daily Usage**
| Method | Path | Description |
|--------|------|-------------|
| POST | /api/journey/start | Start a Trip or a Daily Usage profile |
| POST | /api/checkin | Submit a check-in (safe or duress code) |
| POST | /api/journey/end | End a journey (once only) |
| GET  | /api/session/{id} | Get session state |
| GET  | /api/sessions | List journeys — `?mine=true` (default, requires login) or `?mine=false` (admin-only, all sessions) |
| GET  | /api/events | Server event log |
| GET  | /api/case/{id} | Encrypted-at-rest case file, decrypted for the owner or admin only |
| POST | /api/location/ping | Log a GPS point (no code needed — passive telemetry) |
| GET  | /api/location/history?session_id= | The session's location trail |

**Guardians & messaging**
| Method | Path | Description |
|--------|------|-------------|
| GET/POST | /api/guardians | List / add a saved guardian (optionally linked to their app username, starts `pending` until they accept) |
| DELETE | /api/guardians/{id} | Remove a saved guardian (owner only) |
| GET  | /api/guardian-requests | Pending "someone added you as a guardian" requests awaiting your response |
| POST | /api/guardians/{id}/respond | Accept or decline a guardian request |
| POST | /api/message/send | Send guardians a message + your Safe/Duress code |
| GET  | /api/messages?session_id= | Read a session's message thread |
| POST | /api/message/guardian-reply | A guardian's reply (never changes escalation) |
| GET  | /api/guardian-inbox | Sessions where I'm an **accepted** linked guardian (requires login) |
| GET  | /guardian/{session_id} | No-login page for a guardian to view the case + reply |

**Push & admin**
| Method | Path | Description |
|--------|------|-------------|
| GET  | /api/push/vapid-key | Web Push public key |
| POST | /api/push/subscribe | Register this device for push (requires login) |
| GET/POST/DELETE | /api/admin/emergency-numbers | Admin-only: view/add/update/remove a country's emergency number |
| GET  | /api/email-status, POST /api/test-email | SMTP config check / send a test email |
| GET  | /docs | Interactive Swagger UI |

## Escalation Logic

Both Trip journeys and Daily Usage profiles run the same ladder — Daily Usage just runs it repeatedly, only within your configured time windows/days (an unresolved alert keeps escalating even past a window's end, until you check in safe):

```
L0  Active, timer running
L1  Timer expired → check-in reminder
L2  No response   → warning issued
L3  Still silent  → guardians alerted (email, or in-app if they're a linked user)
L4  No reply      → digital case file generated + guardians alerted
```

Levels 3–4 (and Duress) repeat their vibration/sound/popup every ~18s in the app until you check in or dismiss — not just a single buzz.

## Duress Code

Enter the duress code at check-in — or alongside a message via "Send & Check In":
- User sees: the exact same "✅ Check-in received." response either way — no visible tell
- Server does: silently jumps to Level 4/DURESS, generates a case file, alerts guardians — any message you typed still sends normally

## Is This Ready to Publish? — Honest Assessment

The underlying problem ("let someone know if I go silent") is real, but the category is **saturated, not empty** — Kitestring has gone dormant, Companion shut down, and Google discontinued its own Trusted Contacts feature. The bigger threat: **Apple shipped "Check In" natively in iOS 17/Messages, and Android has an equivalent Personal Safety feature** — both free, pre-installed, and the guardian doesn't need to install anything either. That kills the core adoption mechanic third-party safety apps (this one included) depend on.

More features don't move that number. What would matter more is a distribution angle other than consumer app stores (see below), or accepting this as a portfolio/demo piece rather than a product people are asked to depend on.

**Status update (2026-09-23):** Priority 1 (auth + security review) and Priority 2 (consent, encryption, admin-editable data, live location) are both done now — see what changed underneath each. Storage durability and SMS/voice fallback are intentionally still open (deferred by request, not forgotten).

**Originally, this was not safe to publish as a real safety product people rely on:**
- ~~**No real authentication**~~ — **closed.** Every account-scoped endpoint (`/api/guardians`, `/api/profile`, `/api/sessions`, `/api/guardian-inbox`, `/api/push/subscribe`) now derives identity from an httpOnly, Secure, SameSite=Strict session cookie (`main.py`: `get_current_user`) instead of a client-supplied `user_id` — verified live that the old "just put someone else's id in the request body" trick now gets a 401. Passwords upgraded from unsalted SHA-256 to bcrypt, with existing accounts lazily migrated on their next successful login. `/api/journey/start` deliberately stays usable without an account (by design — you can still be found via the session ID alone), but is always attributed to your real session if you're signed in, never a client-supplied id.
- **Storage is still ephemeral on the free tier this is deployed to** (SQLite on Render's free tier, no persistent disk) — a routine redeploy still wipes every journey, guardian, and message. **Deferred.**
- **Still email + WebPush only — no SMS/voice fallback.** For the target users (solo travelers, journalists, duress situations), a missed/delayed email remains the single most likely failure mode. **Deferred.**
- ~~**No tests, no rate limiting, no security review**~~ — **closed.** A pytest suite (49 tests) now covers the safety-critical logic (safe/duress code branching, DAILY window/day-of-week gating, the journey-can-only-end-once guard, guardian-inbox/consent scoping, case-file access control, admin endpoints, auth). Rate limiting (`slowapi`) throttles `/api/login`, `/api/register`, `/api/checkin`, `/api/message/send`, `/api/location/ping`. CORS is locked to the app's real origin instead of `*`. A `.gitignore` now actually exists. The review also turned up and fixed a stored-XSS gap — user-controlled text was being written straight into `innerHTML` across `index.html` and `guardian.html`; everything user-controlled is now escaped through a shared `esc()` helper.
- ~~**No guardian consent, plaintext case files, hardcoded emergency numbers, single manual coordinate**~~ — **closed** (Priority 2, below).

**Honest ratings:** as a portfolio/engineering exercise (safety-domain UX judgment — e.g. preserving duress-code detection when messaging was added, window/day-aware escalation, the guardian-inbox consent model, case-file encryption scoped correctly for anonymous vs. owned journeys) — **8.5/10**. As a product with a real future in the market, worth publishing for people to depend on today — still **3/10**: the market/competition problem (free OS-level Check In features) hasn't moved, and that's a distribution problem no amount of backend hardening fixes. Durable storage + a non-email fallback channel are also still open.

## Path Forward — Priority Order

Ordered by what's actually blocking trust, not by what's easiest to build:

### Priority 1 — Trust-critical (do before asking anyone to rely on this)
- [x] Real authentication (session cookies) — stop trusting client-supplied `user_id`
- [ ] Durable storage — move off ephemeral SQLite-on-free-tier to Postgres with a real persistent disk/managed DB *(deferred by request)*
- [ ] SMS/voice fallback (e.g. Twilio) — email/WebPush alone is the single biggest real-world failure mode *(deferred by request)*
- [x] A real security review — input validation, rate limiting on auth/check-in endpoints, secrets handling, stored-XSS fix

### Priority 2 — Strengthen the core loop
- [x] Verified guardian mutual-trust flow — linking now starts `pending`; the linked account must accept via `/api/guardian-requests` before appearing in anyone's Guardian Inbox
- [x] Encrypted case file delivery — Fernet at rest, decrypted only for the journey's owner or the admin (anonymous, account-less journeys keep the session-ID-as-credential model, since there's no owner account to check against)
- [x] Emergency-number table moved from hardcoded Python to the database, with admin CRUD endpoints (`/api/admin/emergency-numbers`) — updates take effect immediately, no redeploy
- [x] GPS location tracking with adaptive pinging — opt-in per session, ping frequency scales with escalation level (5 min calm → 30s at Level 3+/Duress), visible to guardians as a trail

### Priority 3 — Distribution (matters more than more features)
- [ ] Don't compete head-on with Apple/Android's free built-in Check In — pivot toward a niche where a third party still adds value: NGO/journalist-safety orgs, corporate travel-risk teams, insurance bundling
- [ ] If mobile-native is still the goal, React Native (iOS + Android) — but only after Priority 1 is done, not before
- [ ] Wearable integration (e.g. Apple Watch heartbeat check-in) as a differentiator once the core is trustworthy

## Tech Stack for the Above

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + PostgreSQL + Redis |
| Mobile | React Native (Expo) |
| Auth | ~~JWT~~ Session cookies — done; 2FA still open |
| SMS | Twilio Programmable Messaging |
| Push | Firebase Cloud Messaging |
| Hosting | AWS ECS (99.99% SLA) or GCP Cloud Run |
| DB | AWS RDS PostgreSQL (Multi-AZ) |
