"""
Guardian Angel - Proof of Concept Backend
Dead Man's Switch safety escalation system
"""

import asyncio
import base64
import hashlib
import json
import os
import smtplib
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import AsyncGenerator, Optional

from dotenv import load_dotenv

load_dotenv(override=True)

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import Boolean, Column, Integer, String, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

BASE_DIR   = Path(__file__).resolve().parent
DB_PATH    = BASE_DIR / "guardian_angel.db"
VAPID_PATH = BASE_DIR / "vapid.json"
ICONS_DIR  = BASE_DIR / "icons"


# ─────────────────────────────────────────────
#  Icon generation (pure stdlib — no Pillow)
# ─────────────────────────────────────────────
def _make_png(size: int) -> bytes:
    import struct, zlib
    cx = cy = size / 2
    outer, inner, dot_r = size * 0.40, size * 0.28, size * 0.11
    bg, ring, dot = (10, 13, 15), (0, 229, 160), (0, 180, 120)
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            d = ((x - cx + .5)**2 + (y - cy + .5)**2) ** .5
            if d <= dot_r:
                row.extend(dot)
            elif inner <= d <= outer:
                t = min(1.0, max(0.0, min(d - inner, outer - d) / 1.5))
                row.extend(int(bg[i] + t * (ring[i] - bg[i])) for i in range(3))
            else:
                row.extend(bg)
        rows.append(bytes(row))
    raw = b''.join(rows)
    def chunk(name, data):
        crc = zlib.crc32(name + data) & 0xffffffff
        return struct.pack('>I', len(data)) + name + data + struct.pack('>I', crc)
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 6))
            + chunk(b'IEND', b''))


def _ensure_icons():
    ICONS_DIR.mkdir(exist_ok=True)
    for size in (72, 96, 128, 144, 152, 192, 384, 512):
        p = ICONS_DIR / f"icon-{size}.png"
        if not p.exists():
            p.write_bytes(_make_png(size))
            print(f"[ICONS] Generated icon-{size}.png")

# ─────────────────────────────────────────────
#  Database
# ─────────────────────────────────────────────
engine            = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}", echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class SessionModel(Base):
    __tablename__ = "sessions"

    session_id           = Column(String,  primary_key=True)
    user_name            = Column(String,  nullable=False)
    destination          = Column(String,  nullable=False)
    interval_minutes     = Column(Integer, default=30)
    guardians            = Column(String,  default="[]")   # JSON list
    safe_code            = Column(String,  nullable=False)
    duress_code          = Column(String,  nullable=False)
    started_at           = Column(String,  nullable=False)
    next_checkin         = Column(String,  nullable=False)
    last_checkin         = Column(String,  nullable=True)
    last_location        = Column(String,  nullable=True)
    escalation_level     = Column(Integer, default=0)
    status               = Column(String,  default="ACTIVE")
    case_file            = Column(String,  nullable=True)  # JSON object
    checkin_count        = Column(Integer, default=0)
    user_id              = Column(String,  nullable=True,  default="")
    escalation_intervals = Column(String,  nullable=True)  # JSON {"1": mins, "2": mins, "3": mins}


class EventModel(Base):
    __tablename__ = "events"

    id         = Column(String,  primary_key=True)
    timestamp  = Column(String,  nullable=False)
    session_id = Column(String,  nullable=False)
    level      = Column(Integer, nullable=False)
    level_name = Column(String,  nullable=False)
    message    = Column(String,  nullable=False)
    silent     = Column(Boolean, default=False)


class UserModel(Base):
    __tablename__ = "users"

    id            = Column(String, primary_key=True)
    username      = Column(String, nullable=False, unique=True)
    password_hash = Column(String, nullable=False)
    reason        = Column(String, nullable=True)
    created_at    = Column(String, nullable=False)


class UserGuardianModel(Base):
    __tablename__ = "user_guardians"

    id         = Column(String, primary_key=True)
    user_id    = Column(String, nullable=False)
    name       = Column(String, nullable=False)
    email      = Column(String, nullable=True, default="")
    phone      = Column(String, nullable=True, default="")
    created_at = Column(String, nullable=False)


class PushSubscriptionModel(Base):
    __tablename__ = "push_subscriptions"

    id         = Column(String, primary_key=True)
    user_id    = Column(String, nullable=False)
    endpoint   = Column(String, nullable=False)
    p256dh     = Column(String, nullable=False)
    auth       = Column(String, nullable=False)
    created_at = Column(String, nullable=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as db:
        yield db


# ─────────────────────────────────────────────
#  VAPID keys for Web Push
# ─────────────────────────────────────────────
VAPID: dict = {"private": None, "public": None}


def _load_or_create_vapid():
    if VAPID_PATH.exists():
        keys = json.loads(VAPID_PATH.read_text())
        VAPID["private"] = keys["private"]
        VAPID["public"]  = keys["public"]
        print("[VAPID] Keys loaded from vapid.json")
        return
    try:
        from py_vapid import Vapid
        from cryptography.hazmat.primitives.serialization import (
            Encoding, PublicFormat, PrivateFormat, NoEncryption,
        )
        v = Vapid()
        v.generate_keys()
        pub_bytes = v.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        VAPID["public"]  = base64.urlsafe_b64encode(pub_bytes).rstrip(b"=").decode()
        VAPID["private"] = v.private_key.private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
        ).decode()
        VAPID_PATH.write_text(json.dumps(VAPID))
        print("[VAPID] New keys generated and saved to vapid.json")
    except Exception as exc:
        print(f"[VAPID] Key setup failed: {exc} — push notifications disabled")


# ─────────────────────────────────────────────
#  Constants
# ─────────────────────────────────────────────
ESCALATION_LEVELS = {
    0: "IDLE",
    1: "CHECK_IN_REQUESTED",
    2: "WARNING_ISSUED",
    3: "GUARDIAN_ALERTED",
    4: "AUTHORITY_DISPATCH",
}

SAFE_CODE   = "SAFE123"
DURESS_CODE = "HELP999"


# ─────────────────────────────────────────────
#  Pydantic models
# ─────────────────────────────────────────────
class GuardianContact(BaseModel):
    name: str
    contact: str = ""
    email: str = ""


class JourneyStart(BaseModel):
    user_name: str
    destination: str
    check_in_interval_minutes: int = 30
    escalation_intervals: Optional[dict] = None  # {"1": mins, "2": mins, "3": mins}
    guardians: list[GuardianContact] = []
    safe_code: str = SAFE_CODE
    duress_code: str = DURESS_CODE
    user_id: str = ""


class GuardianCreate(BaseModel):
    user_id: str
    name: str
    email: str = ""
    phone: str = ""


class CheckIn(BaseModel):
    session_id: str
    code: str
    lat: Optional[float] = None
    lng: Optional[float] = None


class UserRegister(BaseModel):
    username: str
    password: str
    reason: str = ""


class UserLogin(BaseModel):
    username: str
    password: str


class PushSubscribe(BaseModel):
    user_id: str
    endpoint: str
    p256dh: str
    auth: str


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────
def session_to_dict(s: SessionModel) -> dict:
    return {
        "session_id":            s.session_id,
        "user_name":             s.user_name,
        "destination":           s.destination,
        "interval_minutes":      s.interval_minutes,
        "guardians":             json.loads(s.guardians),
        "safe_code":             s.safe_code,
        "duress_code":           s.duress_code,
        "started_at":            s.started_at,
        "next_checkin":          s.next_checkin,
        "last_checkin":          s.last_checkin,
        "last_location":         s.last_location,
        "escalation_level":      s.escalation_level,
        "status":                s.status,
        "case_file":             json.loads(s.case_file) if s.case_file else None,
        "checkin_count":         s.checkin_count,
        "user_id":               s.user_id or "",
        "escalation_intervals":  json.loads(s.escalation_intervals) if s.escalation_intervals else {},
    }


async def log_event(db: AsyncSession, session_id: str, level: int, message: str, silent: bool = False):
    entry = EventModel(
        id=str(uuid.uuid4())[:8],
        timestamp=datetime.now(timezone.utc).isoformat(),
        session_id=session_id,
        level=level,
        level_name=ESCALATION_LEVELS.get(level, "UNKNOWN"),
        message=message,
        silent=silent,
    )
    db.add(entry)
    if not silent:
        print(f"[{entry.level_name}] {entry.timestamp} | {message}")


def guardian_names(s: SessionModel) -> str:
    items = json.loads(s.guardians)
    names = [g.get("name", "") if isinstance(g, dict) else str(g) for g in items]
    return ", ".join(n for n in names if n) or "None"


def generate_case_file(s: SessionModel) -> dict:
    items = json.loads(s.guardians)
    formatted = [
        f"{g.get('name','')} ({g.get('contact','')})" if isinstance(g, dict) else str(g)
        for g in items
    ]
    return {
        "generated_at":        datetime.now(timezone.utc).isoformat(),
        "subject":             s.user_name,
        "destination":         s.destination,
        "journey_started":     s.started_at,
        "last_known_location": s.last_location or "Unknown",
        "last_checkin":        s.last_checkin or "Never",
        "guardians":           formatted,
        "secure_link":         f"https://guardian-angel.app/case/{s.session_id}",
    }


def build_email_body(level: int, s: SessionModel) -> str:
    level_info = {
        1: ("#6ec6ff", "⏰ Check-in Overdue",    "The user has missed their scheduled check-in. Please try to contact them."),
        2: ("#ffd32a", "⚠️ Warning Issued",       "No response after reminder. Immediate contact is recommended."),
        3: ("#ff8c42", "🚨 Guardian Alert",        "Multiple contact attempts failed. You are a designated guardian — please act now."),
        4: ("#ff4757", "🔴 Authority Dispatch",    "All contact attempts exhausted. Authorities have been dispatched. A digital case file has been generated."),
    }
    color, title, desc = level_info.get(level, ("#ffffff", "Alert", ""))
    rows = [
        ("Person",          f"<strong>{s.user_name}</strong>"),
        ("Destination",     s.destination),
        ("Journey Started", f"<span style='font-family:monospace;font-size:11px;'>{s.started_at}</span>"),
        ("Last Check-In",   f"<span style='font-family:monospace;font-size:11px;'>{s.last_checkin or 'Never'}</span>"),
        ("Last Location",   s.last_location or "Unknown"),
        ("Alert Level",     f"<span style='color:{color};font-weight:bold;font-family:monospace;'>LEVEL {level} — {ESCALATION_LEVELS.get(level,'')}</span>"),
    ]
    rows_html = "".join(
        f"<tr><td style='padding:8px 0;color:#5a7080;border-bottom:1px solid #1f2a30;width:140px;'>{k}</td>"
        f"<td style='padding:8px 0;border-bottom:1px solid #1f2a30;'>{v}</td></tr>"
        for k, v in rows
    )
    g_items = json.loads(s.guardians)
    g_html = "".join(
        f"<li style='margin:4px 0;color:#a0b4c0;'>{g.get('name','')} "
        f"{'· ' + g.get('contact','') if g.get('contact') else ''} "
        f"{'· ' + g.get('email','') if g.get('email') else ''}</li>"
        if isinstance(g, dict) else f"<li style='margin:4px 0;color:#a0b4c0;'>{g}</li>"
        for g in g_items
    )
    guardians_block = (
        f"<div style='margin-top:16px;padding:12px 16px;background:#0a0d0f;border-radius:8px;border:1px solid #1f2a30;'>"
        f"<p style='margin:0 0 8px;font-size:11px;color:#5a7080;letter-spacing:1px;text-transform:uppercase;'>Guardian Network</p>"
        f"<ul style='margin:0;padding-left:18px;'>{g_html}</ul></div>"
    ) if g_html else ""

    return f"""<!DOCTYPE html><html>
<body style="margin:0;padding:20px;font-family:Arial,sans-serif;background:#0a0d0f;color:#e8eef2;">
<div style="max-width:520px;margin:0 auto;background:#161b1f;border-radius:12px;overflow:hidden;border:2px solid {color};">
  <div style="background:#111518;padding:20px 24px;border-bottom:1px solid #1f2a30;">
    <p style="margin:0;font-size:20px;font-weight:bold;color:{color};">🛡 GUARDIAN ANGEL</p>
    <p style="margin:4px 0 0;font-size:11px;color:#5a7080;font-family:monospace;letter-spacing:1px;">AUTOMATED SAFETY ALERT</p>
  </div>
  <div style="background:#0a0d0f;border-bottom:1px solid {color};padding:18px 24px;">
    <p style="margin:0;font-size:20px;font-weight:bold;">{title}</p>
    <p style="margin:8px 0 0;font-size:13px;color:#a0b4c0;line-height:1.6;">{desc}</p>
  </div>
  <div style="padding:20px 24px;">
    <table style="width:100%;border-collapse:collapse;font-size:13px;">{rows_html}</table>
    {guardians_block}
  </div>
  <div style="background:#111518;padding:14px 24px;border-top:1px solid #1f2a30;text-align:center;">
    <p style="margin:0;font-size:11px;color:#5a7080;">Guardian Angel · Automated Safety System</p>
    <p style="margin:4px 0 0;font-size:10px;color:#3a5060;font-family:monospace;">Session: {s.session_id}</p>
  </div>
</div>
</body></html>"""


async def send_alert_emails(s: SessionModel, level: int) -> None:
    items      = json.loads(s.guardians)
    recipients = [g.get("email", "").strip() for g in items if isinstance(g, dict) and g.get("email", "").strip()]
    if not recipients:
        return

    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "").replace(" ", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user)

    if not smtp_user or not smtp_pass:
        print(f"[EMAIL] SMTP not configured — skipping Level {level} alert")
        return

    subjects = {
        1: f"⏰ Check-in Overdue — {s.user_name}",
        2: f"⚠️ Warning: No Response from {s.user_name}",
        3: f"🚨 URGENT: Guardian Alert for {s.user_name}",
        4: f"🔴 CRITICAL: Authority Dispatch — {s.user_name} May Be in Danger",
    }
    subject = subjects.get(level, f"Guardian Angel Alert — Level {level}")
    body    = build_email_body(level, s)

    def _send():
        with smtplib.SMTP(smtp_host, smtp_port) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(smtp_user, smtp_pass)
            for recipient in recipients:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"]    = smtp_from
                msg["To"]      = recipient
                msg.attach(MIMEText(body, "html"))
                srv.sendmail(smtp_user, recipient, msg.as_string())
                print(f"[EMAIL] Level {level} alert sent to {recipient}")

    try:
        await asyncio.get_running_loop().run_in_executor(None, _send)
    except Exception as exc:
        print(f"[EMAIL ERROR] {exc}")


# ─────────────────────────────────────────────
#  Web Push
# ─────────────────────────────────────────────
async def send_push_to_user(user_id: str, title: str, body_text: str, level: int) -> None:
    if not VAPID["private"] or not VAPID["public"]:
        return
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PushSubscriptionModel).where(PushSubscriptionModel.user_id == user_id)
        )
        subs = result.scalars().all()

    if not subs:
        return

    smtp_user = os.getenv("SMTP_USER", "guardian@example.com")
    payload   = json.dumps({"title": title, "body": body_text, "level": level})

    def _send_one(sub: PushSubscriptionModel):
        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=payload,
            vapid_private_key=VAPID["private"],
            vapid_claims={"sub": f"mailto:{smtp_user}"},
        )

    for sub in subs:
        try:
            await asyncio.get_running_loop().run_in_executor(None, _send_one, sub)
            print(f"[PUSH] Sent level {level} alert to user {user_id}")
        except Exception as exc:
            print(f"[PUSH ERROR] user={user_id}: {exc}")


# ─────────────────────────────────────────────
#  Escalation
# ─────────────────────────────────────────────
async def escalate(db: AsyncSession, session_id: str):
    result = await db.execute(select(SessionModel).where(SessionModel.session_id == session_id))
    s = result.scalar_one_or_none()
    if not s or s.status == "ENDED":
        return
    next_level = min(s.escalation_level + 1, 4)
    s.escalation_level = next_level
    messages = {
        1: f"Check-in overdue for {s.user_name} — sending reminder.",
        2: f"No response from {s.user_name} — issuing WARNING.",
        3: f"Guardians alerted for {s.user_name}: {guardian_names(s)}",
        4: f"AUTHORITY DISPATCH triggered for {s.user_name} — Digital Case File generated.",
    }
    push_titles = {
        1: "⏰ Check-In Overdue",
        2: "⚠️ Warning Issued",
        3: "🚨 Guardian Alert",
        4: "🔴 Authority Dispatch",
    }
    await log_event(db, session_id, next_level, messages.get(next_level, "Escalation step"))
    if next_level == 4:
        s.case_file = json.dumps(generate_case_file(s))
    await db.commit()

    # Fire background notifications — email to guardians + push to journey user's device
    asyncio.create_task(send_alert_emails(s, next_level))
    if s.user_id:
        asyncio.create_task(send_push_to_user(
            s.user_id,
            push_titles.get(next_level, "Guardian Angel Alert"),
            messages.get(next_level, "Alert level changed"),
            next_level,
        ))


# ─────────────────────────────────────────────
#  Background watchdog
# ─────────────────────────────────────────────
async def watchdog():
    while True:
        await asyncio.sleep(10)
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(SessionModel).where(SessionModel.status == "ACTIVE")
            )
            active = result.scalars().all()
            now = datetime.now(timezone.utc)
            for s in active:
                if now >= datetime.fromisoformat(s.next_checkin):
                    await escalate(db, s.session_id)
                    refreshed = await db.execute(
                        select(SessionModel).where(SessionModel.session_id == s.session_id)
                    )
                    s = refreshed.scalar_one_or_none()
                    if s:
                        if s.escalation_level < 4:
                            intervals = json.loads(s.escalation_intervals or '{}')
                            next_mins = int(intervals.get(str(s.escalation_level), 1))
                            s.next_checkin = (now + timedelta(minutes=next_mins)).isoformat()
                        else:
                            s.status = "ESCALATED"
                        await db.commit()


# ─────────────────────────────────────────────
#  Lifespan
# ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(_):
    _ensure_icons()
    _load_or_create_vapid()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for stmt in [
            "ALTER TABLE sessions ADD COLUMN user_id TEXT DEFAULT ''",
            "ALTER TABLE sessions ADD COLUMN escalation_intervals TEXT",
        ]:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass
    asyncio.create_task(watchdog())
    yield


app = FastAPI(title="Guardian Angel API", version="1.0.0-POC", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
#  Static file serving (PWA assets)
# ─────────────────────────────────────────────
@app.get("/sw.js")
def serve_sw():
    return FileResponse(BASE_DIR / "sw.js", media_type="text/javascript",
                        headers={"Service-Worker-Allowed": "/"})


@app.get("/manifest.json")
def serve_manifest():
    return FileResponse(BASE_DIR / "manifest.json", media_type="application/manifest+json")


@app.get("/icons/{filename}")
def serve_icon(filename: str):
    path = BASE_DIR / "icons" / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "Icon not found")
    return FileResponse(path, media_type="image/png")


# ─────────────────────────────────────────────
#  API Routes
# ─────────────────────────────────────────────
@app.post("/api/journey/start")
async def start_journey(body: JourneyStart, db: AsyncSession = Depends(get_db)):
    sid = str(uuid.uuid4())[:12]
    now = datetime.now(timezone.utc)
    s = SessionModel(
        session_id=sid,
        user_name=body.user_name,
        destination=body.destination,
        interval_minutes=body.check_in_interval_minutes,
        guardians=json.dumps([g.model_dump() for g in body.guardians]),
        safe_code=body.safe_code,
        duress_code=body.duress_code,
        started_at=now.isoformat(),
        next_checkin=(now + timedelta(minutes=body.check_in_interval_minutes)).isoformat(),
        escalation_level=0,
        status="ACTIVE",
        checkin_count=0,
        user_id=body.user_id,
        escalation_intervals=json.dumps(
            {str(k): v for k, v in body.escalation_intervals.items()}
        ) if body.escalation_intervals else json.dumps({"1": 1, "2": 1, "3": 1}),
    )
    db.add(s)
    await log_event(db, sid, 0, f"Journey started for {body.user_name} to {body.destination}")
    await db.commit()
    return {"session_id": sid, "message": "Journey started. Stay safe.", "next_checkin": s.next_checkin}


@app.post("/api/checkin")
async def check_in(body: CheckIn, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SessionModel).where(SessionModel.session_id == body.session_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Session not found")
    if s.status == "ENDED":
        raise HTTPException(400, "Journey already ended")

    if body.code == s.duress_code:
        next_ci = (datetime.now(timezone.utc) + timedelta(minutes=s.interval_minutes)).isoformat()
        await log_event(db, body.session_id, 0, f"Check-in accepted for {s.user_name} (timer reset)")
        await log_event(db, body.session_id, 4, f"SILENT DURESS — immediate Level 4 for {s.user_name}", silent=True)
        s.escalation_level = 4
        s.status = "DURESS"
        s.case_file = json.dumps(generate_case_file(s))
        s.next_checkin = next_ci
        await db.commit()
        asyncio.create_task(send_alert_emails(s, 4))
        if s.user_id:
            asyncio.create_task(send_push_to_user(s.user_id, "🔴 Duress Alert Active", "Silent duress code entered. Guardian network alerted.", 4))
        return {"status": "ok", "message": "Check-in received. Timer reset.", "next_checkin": next_ci}

    if body.code != s.safe_code:
        raise HTTPException(403, "Invalid code")

    now = datetime.now(timezone.utc)
    s.last_checkin = now.isoformat()
    s.next_checkin = (now + timedelta(minutes=s.interval_minutes)).isoformat()
    s.escalation_level = 0
    s.status = "ACTIVE"
    s.checkin_count += 1
    if body.lat and body.lng:
        s.last_location = f"{body.lat},{body.lng}"
    await log_event(db, body.session_id, 0, f"Check-in #{s.checkin_count} by {s.user_name}")
    await db.commit()
    return {"status": "ok", "message": "Check-in received. Timer reset.", "next_checkin": s.next_checkin}


@app.post("/api/journey/end")
async def end_journey(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SessionModel).where(SessionModel.session_id == session_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Session not found")
    s.status = "ENDED"
    await log_event(db, session_id, 0, f"Journey ended safely for {s.user_name}")
    await db.commit()
    return {"message": "Journey ended. Glad you're safe!"}


@app.get("/api/session/{session_id}")
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SessionModel).where(SessionModel.session_id == session_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Session not found")
    return session_to_dict(s)


@app.get("/api/events")
async def get_events(session_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    if session_id:
        q = select(EventModel).where(EventModel.session_id == session_id).order_by(EventModel.timestamp.desc())
    else:
        q = select(EventModel).order_by(EventModel.timestamp.desc()).limit(50)
    result = await db.execute(q)
    events = result.scalars().all()
    return [
        {"id": e.id, "timestamp": e.timestamp, "session_id": e.session_id,
         "level": e.level, "level_name": e.level_name, "message": e.message, "silent": e.silent}
        for e in events
    ]


@app.get("/api/case/{session_id}")
async def get_case_file(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SessionModel).where(SessionModel.session_id == session_id))
    s = result.scalar_one_or_none()
    if not s or not s.case_file:
        raise HTTPException(404, "No case file generated yet")
    return json.loads(s.case_file)


@app.get("/api/sessions")
async def list_sessions(user_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    q = select(SessionModel)
    if user_id:
        q = q.where(SessionModel.user_id == user_id)
    result = await db.execute(q.order_by(SessionModel.started_at.desc()))
    return [
        {"session_id": s.session_id, "user": s.user_name, "status": s.status,
         "level": s.escalation_level, "destination": s.destination, "started_at": s.started_at}
        for s in result.scalars().all()
    ]


@app.get("/api/guardians")
async def list_guardians(user_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(UserGuardianModel).where(UserGuardianModel.user_id == user_id)
    )
    return [
        {"id": g.id, "name": g.name, "email": g.email or "", "phone": g.phone or ""}
        for g in result.scalars().all()
    ]


@app.post("/api/guardians")
async def create_guardian(body: GuardianCreate, db: AsyncSession = Depends(get_db)):
    g = UserGuardianModel(
        id=str(uuid.uuid4())[:12],
        user_id=body.user_id,
        name=body.name,
        email=body.email,
        phone=body.phone,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    db.add(g)
    await db.commit()
    return {"id": g.id, "name": g.name, "email": g.email, "phone": g.phone}


@app.delete("/api/guardians/{guardian_id}")
async def delete_guardian(guardian_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(UserGuardianModel).where(UserGuardianModel.id == guardian_id)
    )
    g = result.scalar_one_or_none()
    if not g:
        raise HTTPException(404, "Guardian not found")
    await db.delete(g)
    await db.commit()
    return {"ok": True}


# ── Push subscription endpoints ───────────────
@app.get("/api/push/vapid-key")
def get_vapid_key():
    if not VAPID["public"]:
        raise HTTPException(503, "Push notifications not configured")
    return {"public_key": VAPID["public"]}


@app.post("/api/push/subscribe")
async def push_subscribe(body: PushSubscribe, db: AsyncSession = Depends(get_db)):
    # Upsert: same user + same endpoint → update keys
    result = await db.execute(
        select(PushSubscriptionModel).where(
            PushSubscriptionModel.user_id  == body.user_id,
            PushSubscriptionModel.endpoint == body.endpoint,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.p256dh = body.p256dh
        existing.auth   = body.auth
    else:
        db.add(PushSubscriptionModel(
            id=str(uuid.uuid4())[:12],
            user_id=body.user_id,
            endpoint=body.endpoint,
            p256dh=body.p256dh,
            auth=body.auth,
            created_at=datetime.now(timezone.utc).isoformat(),
        ))
    await db.commit()
    print(f"[PUSH] Subscription saved for user {body.user_id}")
    return {"ok": True}


@app.post("/api/register")
async def register(body: UserRegister, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserModel).where(UserModel.username == body.username))
    if result.scalar_one_or_none():
        raise HTTPException(400, "Username already taken")
    user = UserModel(
        id=str(uuid.uuid4())[:12],
        username=body.username,
        password_hash=hashlib.sha256(body.password.encode()).hexdigest(),
        reason=body.reason,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    db.add(user)
    await db.commit()
    return {"id": user.id, "username": user.username}


@app.post("/api/login")
async def login(body: UserLogin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserModel).where(UserModel.username == body.username))
    user = result.scalar_one_or_none()
    if not user or hashlib.sha256(body.password.encode()).hexdigest() != user.password_hash:
        raise HTTPException(401, "Invalid username or password")
    return {"id": user.id, "username": user.username, "reason": user.reason}


@app.get("/api/email-status")
def email_status():
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    configured = bool(smtp_user and smtp_pass)
    return {
        "configured": configured,
        "smtp_host":  os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "smtp_port":  int(os.getenv("SMTP_PORT", "587")),
        "smtp_user":  smtp_user if configured else "",
    }


class TestEmailBody(BaseModel):
    to: str


@app.post("/api/test-email")
async def send_test_email(body: TestEmailBody):
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "").replace(" ", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user)

    if not smtp_user or not smtp_pass:
        raise HTTPException(400, "SMTP not configured. Create a .env file with SMTP_USER and SMTP_PASS.")

    html = f"""<!DOCTYPE html><html>
<body style="margin:0;padding:20px;font-family:Arial,sans-serif;background:#0a0d0f;color:#e8eef2;">
<div style="max-width:520px;margin:0 auto;background:#161b1f;border-radius:12px;overflow:hidden;border:2px solid #00e5a0;">
  <div style="background:#111518;padding:20px 24px;">
    <p style="margin:0;font-size:20px;font-weight:bold;color:#00e5a0;">🛡 GUARDIAN ANGEL</p>
    <p style="margin:4px 0 0;font-size:11px;color:#5a7080;font-family:monospace;letter-spacing:1px;">EMAIL CONFIGURATION TEST</p>
  </div>
  <div style="padding:24px;">
    <p style="font-size:16px;font-weight:bold;color:#00e5a0;">✅ Email is working correctly!</p>
    <p style="font-size:13px;color:#a0b4c0;margin-top:12px;line-height:1.6;">
      Your Guardian Angel SMTP configuration is set up correctly.<br/>
      Alert emails will be sent to guardian addresses when escalation events occur.
    </p>
    <div style="margin-top:20px;padding:12px 16px;background:#0a0d0f;border-radius:8px;border:1px solid #1f2a30;font-family:monospace;font-size:11px;color:#5a7080;">
      Sent via: {smtp_user}<br/>Server: {smtp_host}:{smtp_port}
    </div>
  </div>
  <div style="background:#111518;padding:14px 24px;border-top:1px solid #1f2a30;text-align:center;">
    <p style="margin:0;font-size:11px;color:#5a7080;">Guardian Angel · SMTP Configuration Test</p>
  </div>
</div>
</body></html>"""

    def _send():
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "🛡 Guardian Angel — Email Test"
        msg["From"]    = smtp_from
        msg["To"]      = body.to
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP(smtp_host, smtp_port) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(smtp_user, smtp_pass)
            srv.sendmail(smtp_user, body.to, msg.as_string())

    try:
        await asyncio.get_running_loop().run_in_executor(None, _send)
        print(f"[EMAIL] Test email sent to {body.to}")
        return {"ok": True, "message": f"Test email sent to {body.to}"}
    except Exception as exc:
        print(f"[EMAIL ERROR] Test failed: {exc}")
        raise HTTPException(500, f"Email failed: {exc}")


@app.get("/")
def serve_ui():
    return FileResponse(BASE_DIR / "index.html")


@app.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SessionModel).where(SessionModel.status == "ACTIVE"))
    return {"status": "ok", "active_sessions": len(result.scalars().all()), "push_enabled": bool(VAPID["public"])}
