# 🛡 Guardian Angel — POC

A "Dead Man's Switch" personal safety app. Server-side escalation engine.

## Quick Start

```bash
pip install -r requirements.txt
bash run.sh
# → Open http://localhost:8000
```

## Architecture

```
guardian_angel/
├── server/
│   └── main.py          # FastAPI backend — escalation engine
├── static/
│   └── index.html       # Mobile-responsive web UI (demo app)
├── requirements.txt
└── run.sh
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /api/journey/start | Start a new journey session |
| POST | /api/checkin | Submit a check-in (safe or duress code) |
| POST | /api/journey/end | End journey safely |
| GET  | /api/session/{id} | Get session state |
| GET  | /api/sessions | List all sessions |
| GET  | /api/events | Server event log |
| GET  | /api/case/{id} | Get digital case file (L4 only) |
| GET  | /docs | Interactive Swagger UI |

## Escalation Logic (POC = 1 min intervals, prod = configurable)

```
L0  Journey active, timer running
L1  Timer expired → Check-in reminder
L2  No response   → Warning issued
L3  Still silent  → Guardian network alerted
L4  No reply      → Authority dispatch + Case File generated
```

## Duress Code

Enter the duress code at check-in:
- User sees: "✅ Check-in received. Timer reset."
- Server does: Silent Level 4 trigger, case file generated, authorities alerted

## Roadmap to Production

### Phase 1 (This POC → Beta)
- [ ] Replace in-memory store with PostgreSQL (SQLAlchemy)
- [ ] Add JWT auth (FastAPI-Users)
- [ ] Twilio SMS gateway integration (for offline mode)
- [ ] Push notifications via Firebase Cloud Messaging

### Phase 2 (Beta → v1)
- [ ] React Native mobile app (iOS + Android)
- [ ] GPS location tracking with adaptive pinging
- [ ] Verified Guardian mutual-trust flow
- [ ] Encrypted case file delivery

### Phase 3 (v1 → Enterprise)
- [ ] Centralized NGO/newsroom dashboard
- [ ] Wearable integration (Apple Watch heartbeat check-in)
- [ ] Satellite/SMS fallback for war zones
- [ ] AI-predictive battery management

## Tech Stack for Production

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + PostgreSQL + Redis |
| Mobile | React Native (Expo) |
| Auth | JWT + 2FA |
| SMS | Twilio Programmable Messaging |
| Push | Firebase Cloud Messaging |
| Hosting | AWS ECS (99.99% SLA) or GCP Cloud Run |
| DB | AWS RDS PostgreSQL (Multi-AZ) |
