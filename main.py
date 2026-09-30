"""
Guardian Angel - Proof of Concept Backend
Dead Man's Switch safety escalation system
"""

import asyncio
import base64
import hashlib
import json
import os
import secrets
import smtplib
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import AsyncGenerator, Optional

import bcrypt
from dotenv import load_dotenv

load_dotenv(override=True)

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import Boolean, Column, Integer, String, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

BASE_DIR   = Path(__file__).resolve().parent
DB_PATH    = Path(os.getenv("GUARDIAN_DB_PATH", str(BASE_DIR / "guardian_angel.db")))
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
    session_type         = Column(String,  default="TRIP")  # "TRIP" | "DAILY"
    windows              = Column(String,  nullable=True)  # JSON list of {"start_min","end_min","start_local","end_local"}, DAILY only
    active_days          = Column(String,  nullable=True)  # JSON list of weekday ints (0=Mon..6=Sun), DAILY only; empty/null = every day
    maps_link            = Column(String,  nullable=True)  # Google Maps URL, TRIP only
    latitude             = Column(String,  nullable=True)  # destination coordinates, TRIP only
    longitude            = Column(String,  nullable=True)
    route                = Column(String,  nullable=True)  # planned route description, TRIP only
    communication_method = Column(String,  nullable=True)  # e.g. "Phone", "Satellite Phone", TRIP only
    companions           = Column(String,  nullable=True)  # JSON list of {"name","contact"}, TRIP only
    country              = Column(String,  nullable=True)  # destination country, TRIP only — drives emergency number lookup


class EventModel(Base):
    __tablename__ = "events"

    id         = Column(String,  primary_key=True)
    timestamp  = Column(String,  nullable=False)
    session_id = Column(String,  nullable=False)
    level      = Column(Integer, nullable=False)
    level_name = Column(String,  nullable=False)
    message    = Column(String,  nullable=False)
    silent     = Column(Boolean, default=False)


class MessageModel(Base):
    __tablename__ = "messages"

    id           = Column(String, primary_key=True)
    session_id   = Column(String, nullable=False)
    sender       = Column(String, nullable=False)  # "user" | "guardian"
    sender_label = Column(String, nullable=False)  # the user's name, or the guardian's name
    text         = Column(String, nullable=False)
    timestamp    = Column(String, nullable=False)


class UserModel(Base):
    __tablename__ = "users"

    id            = Column(String, primary_key=True)
    username      = Column(String, nullable=False, unique=True)
    password_hash = Column(String, nullable=False)
    reason        = Column(String, nullable=True)
    email         = Column(String, nullable=True, default="")
    phone         = Column(String, nullable=True, default="")
    address       = Column(String, nullable=True, default="")
    date_of_birth = Column(String, nullable=True, default="")
    blood_type    = Column(String, nullable=True, default="")
    medical_notes = Column(String, nullable=True, default="")  # allergies, conditions, etc.
    photo         = Column(String, nullable=True, default="")  # base64 data-URI, client-resized
    created_at    = Column(String, nullable=False)


class AuthSessionModel(Base):
    __tablename__ = "auth_sessions"

    token      = Column(String, primary_key=True)
    user_id    = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    expires_at = Column(String, nullable=False)


class UserGuardianModel(Base):
    __tablename__ = "user_guardians"

    id              = Column(String, primary_key=True)
    user_id         = Column(String, nullable=False)
    name            = Column(String, nullable=False)
    email           = Column(String, nullable=True, default="")
    phone           = Column(String, nullable=True, default="")
    linked_user_id  = Column(String, nullable=True, default="")  # set if this guardian is also a registered app user
    linked_username = Column(String, nullable=True, default="")
    status          = Column(String, nullable=False, default="accepted")  # "accepted" | "pending" | "declined"
    created_at      = Column(String, nullable=False)


class EmergencyNumberModel(Base):
    __tablename__ = "emergency_numbers"

    country       = Column(String, primary_key=True)  # lowercase-normalized
    number        = Column(String, nullable=False)
    last_verified = Column(String, nullable=False)


class LocationPingModel(Base):
    __tablename__ = "location_pings"

    id         = Column(String, primary_key=True)
    session_id = Column(String, nullable=False)
    lat        = Column(String, nullable=False)
    lng        = Column(String, nullable=False)
    timestamp  = Column(String, nullable=False)


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
#  Auth — password hashing + session cookies
# ─────────────────────────────────────────────
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, stored_hash: str) -> bool:
    if stored_hash.startswith("$2"):  # bcrypt hash
        try:
            return bcrypt.checkpw(password.encode(), stored_hash.encode())
        except ValueError:
            return False
    # Legacy unsalted-SHA256 hash from before the bcrypt migration — verified once,
    # then upgraded to bcrypt in login() on success.
    return hashlib.sha256(password.encode()).hexdigest() == stored_hash


async def create_auth_session(db: AsyncSession, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    db.add(AuthSessionModel(
        token=token,
        user_id=user_id,
        created_at=now.isoformat(),
        expires_at=(now + timedelta(days=SESSION_TTL_DAYS)).isoformat(),
    ))
    await db.commit()
    return token


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME, token,
        max_age=SESSION_TTL_DAYS * 86400,
        httponly=True, secure=COOKIE_SECURE, samesite="strict", path="/",
    )


async def get_current_user(
    ga_session: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db),
) -> UserModel:
    if not ga_session:
        raise HTTPException(401, "Not signed in")
    result = await db.execute(select(AuthSessionModel).where(AuthSessionModel.token == ga_session))
    sess = result.scalar_one_or_none()
    if not sess or datetime.fromisoformat(sess.expires_at) < datetime.now(timezone.utc):
        raise HTTPException(401, "Session expired — please sign in again")
    result = await db.execute(select(UserModel).where(UserModel.id == sess.user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(401, "Account not found")
    return user


async def get_current_user_optional(
    ga_session: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db),
) -> Optional[UserModel]:
    if not ga_session:
        return None
    try:
        return await get_current_user(ga_session, db)
    except HTTPException:
        return None


async def require_admin(user: UserModel = Depends(get_current_user)) -> UserModel:
    if user.username not in ADMIN_USERNAMES:
        raise HTTPException(403, "Admin only")
    return user


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
#  Case file encryption (at rest)
# ─────────────────────────────────────────────
CASE_KEY_PATH = BASE_DIR / "case_key.json"
CASE_CIPHER = {"fernet": None}


def _load_or_create_case_key():
    from cryptography.fernet import Fernet
    env_key = os.getenv("CASE_FILE_ENCRYPTION_KEY", "").strip()
    if env_key:
        CASE_CIPHER["fernet"] = Fernet(env_key.encode())
        print("[CASE FILE] Encryption key loaded from CASE_FILE_ENCRYPTION_KEY")
        return
    if CASE_KEY_PATH.exists():
        key = json.loads(CASE_KEY_PATH.read_text())["key"]
        CASE_CIPHER["fernet"] = Fernet(key.encode())
        print("[CASE FILE] Encryption key loaded from case_key.json")
        return
    key = Fernet.generate_key().decode()
    CASE_KEY_PATH.write_text(json.dumps({"key": key}))
    CASE_CIPHER["fernet"] = Fernet(key.encode())
    print("[CASE FILE] New encryption key generated and saved to case_key.json")


def encrypt_case_file(plaintext_json: str) -> str:
    return CASE_CIPHER["fernet"].encrypt(plaintext_json.encode()).decode()


def decrypt_case_file(ciphertext: str) -> dict:
    return json.loads(CASE_CIPHER["fernet"].decrypt(ciphertext.encode()).decode())


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

# The app's own public URL, used to build the guardian reply link in alert emails.
# Set APP_BASE_URL in .env to your real deployed URL (e.g. https://guardian-angel-xxxx.onrender.com).
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000").rstrip("/")

# ── Auth ────────────────────────────────────────────────────
SESSION_COOKIE_NAME = "ga_session"
SESSION_TTL_DAYS = 30
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() != "false"
ADMIN_USERNAMES = {"AAH_Test_02", "test_aah"}  # mirrors the client-side admin gate for the Monitor tab

# Not exhaustive — best-effort lookup so guardians know which number to dial.
# Falls back to a generic "check the local emergency number" message when the
# destination country isn't in this table or wasn't provided.
# Last verified: 2026-09-22. Emergency numbers do change — re-check periodically
# rather than treating this table as authoritative indefinitely.
EMERGENCY_NUMBERS = {
    "united states": "911", "usa": "911", "canada": "911", "mexico": "911",
    "united kingdom": "999", "uk": "999", "ireland": "999",
    "australia": "000", "new zealand": "111",
    "india": "112", "pakistan": "15", "bangladesh": "999", "sri lanka": "119",
    "china": "110", "japan": "110", "south korea": "112", "taiwan": "110",
    "singapore": "999", "malaysia": "999", "indonesia": "112", "philippines": "911",
    "thailand": "191", "vietnam": "113", "hong kong": "999",
    "germany": "112", "france": "112", "spain": "112", "italy": "112",
    "portugal": "112", "netherlands": "112", "belgium": "112", "switzerland": "112",
    "austria": "112", "sweden": "112", "norway": "112", "denmark": "112",
    "finland": "112", "poland": "112", "greece": "112", "turkey": "112",
    "russia": "112", "ukraine": "112", "romania": "112", "czech republic": "112",
    "hungary": "112", "iceland": "112", "croatia": "112",
    "brazil": "190", "argentina": "911", "chile": "133", "colombia": "123",
    "peru": "105", "venezuela": "911", "ecuador": "911", "uruguay": "911",
    "south africa": "10111", "nigeria": "112", "kenya": "999", "egypt": "122",
    "morocco": "19", "ghana": "112", "ethiopia": "991", "tanzania": "112",
    "uganda": "999", "algeria": "17",
    "israel": "100", "saudi arabia": "999", "uae": "999",
    "united arab emirates": "999", "qatar": "999", "jordan": "911", "lebanon": "112",
}


def get_emergency_number(country: str) -> str:
    if not country:
        return ""
    return EMERGENCY_NUMBERS.get(country.strip().lower(), "")


def format_duration(delta: timedelta) -> str:
    total_minutes = max(0, int(delta.total_seconds() // 60))
    days, rem = divmod(total_minutes, 1440)
    hours, minutes = divmod(rem, 60)
    parts = []
    if days:    parts.append(f"{days}d")
    if hours:   parts.append(f"{hours}h")
    if minutes or not parts: parts.append(f"{minutes}m")
    return " ".join(parts)


def unresponsive_duration(s: "SessionModel", now: datetime) -> str:
    since = s.last_checkin or s.started_at
    return format_duration(now - datetime.fromisoformat(since))


# ─────────────────────────────────────────────
#  Pydantic models
# ─────────────────────────────────────────────
class GuardianContact(BaseModel):
    name: str
    contact: str = ""
    email: str = ""
    linked_user_id: str = ""  # set if this guardian is also a registered app user


class Companion(BaseModel):
    name: str
    contact: str = ""


class JourneyStart(BaseModel):
    user_name: str
    destination: str
    check_in_interval_minutes: int = 30
    escalation_intervals: Optional[dict] = None  # {"1": mins, "2": mins, "3": mins}
    guardians: list[GuardianContact] = []
    safe_code: str = SAFE_CODE
    duress_code: str = DURESS_CODE
    session_type: str = "TRIP"  # "TRIP" | "DAILY"
    windows: Optional[list[dict]] = None  # DAILY only: [{"start_min","end_min","start_local","end_local"}, ...]
    active_days: Optional[list[int]] = None  # DAILY only: weekday ints (0=Mon..6=Sun); empty/None = every day
    maps_link: str = ""             # TRIP only: Google Maps URL
    latitude: str = ""              # TRIP only: destination coordinates
    longitude: str = ""
    route: str = ""                 # TRIP only: planned route description
    communication_method: str = ""  # TRIP only: e.g. "Phone", "Satellite Phone"
    companions: list[Companion] = []  # TRIP only: people traveling along
    country: str = ""               # TRIP only: destination country, drives emergency number lookup


class GuardianCreate(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    linked_username: str = ""  # their app username, if they're also a registered user


class GuardianRespond(BaseModel):
    accept: bool


class CheckIn(BaseModel):
    session_id: str
    code: str
    lat: Optional[float] = None
    lng: Optional[float] = None


class MessageSend(BaseModel):
    session_id: str
    code: str
    text: str = ""


class LocationPing(BaseModel):
    session_id: str
    lat: float
    lng: float


class GuardianReply(BaseModel):
    session_id: str
    guardian_name: str = ""
    guardian_user_id: str = ""  # set when replying from the in-app Guardian Inbox (trusted account identity)
    text: str = ""


class UserRegister(BaseModel):
    username: str
    password: str
    reason: str = ""
    email: str = ""


class UserLogin(BaseModel):
    username: str
    password: str


class PushSubscribe(BaseModel):
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
        "case_file_available":   bool(s.case_file),  # encrypted at rest — fetch the actual contents via GET /api/case/{id} (owner/admin only)
        "checkin_count":         s.checkin_count,
        "user_id":               s.user_id or "",
        "escalation_intervals":  json.loads(s.escalation_intervals) if s.escalation_intervals else {},
        "session_type":          s.session_type or "TRIP",
        "windows":               json.loads(s.windows) if s.windows else [],
        "active_days":           json.loads(s.active_days) if s.active_days else [],
        "maps_link":             s.maps_link or "",
        "latitude":              s.latitude or "",
        "longitude":             s.longitude or "",
        "route":                 s.route or "",
        "communication_method":  s.communication_method or "",
        "companions":            json.loads(s.companions) if s.companions else [],
        "country":               s.country or "",
        "emergency_number":      get_emergency_number(s.country or ""),
    }


def in_window(now_min: int, start_min: int, end_min: int) -> bool:
    """Whether `now_min` (UTC minute-of-day) falls inside [start_min, end_min), handling midnight wraparound."""
    if start_min == end_min:
        return True
    if start_min < end_min:
        return start_min <= now_min < end_min
    return now_min >= start_min or now_min < end_min


def in_any_window(now_min: int, windows: list) -> bool:
    """Whether `now_min` falls inside any of the given windows."""
    return any(in_window(now_min, w["start_min"], w["end_min"]) for w in windows)


def is_active_day(now: datetime, active_days: Optional[list]) -> bool:
    """Whether `now`'s weekday (0=Mon..6=Sun) is in `active_days`. Empty/None means every day."""
    return not active_days or now.weekday() in active_days


def next_window_start(now: datetime, start_min: int, active_days: Optional[list] = None) -> datetime:
    """The next UTC timestamp at which `start_min` (minute-of-day) occurs on an active day."""
    for day_offset in range(8):
        candidate = (now + timedelta(days=day_offset)).replace(
            hour=start_min // 60, minute=start_min % 60, second=0, microsecond=0
        )
        if candidate > now and is_active_day(candidate, active_days):
            return candidate
    return now + timedelta(days=1)  # unreachable unless active_days is malformed


def next_any_window_start(now: datetime, windows: list, active_days: Optional[list] = None) -> datetime:
    """The soonest upcoming start time across all of the given windows, respecting active_days."""
    return min(next_window_start(now, w["start_min"], active_days) for w in windows)


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
    companions = json.loads(s.companions) if s.companions else []
    formatted_companions = [
        f"{c.get('name','')} ({c.get('contact','')})" if c.get("contact") else c.get("name", "")
        for c in companions
    ]
    coords = f"{s.latitude}, {s.longitude}" if (s.latitude or s.longitude) else "Unknown"
    now = datetime.now(timezone.utc)
    emergency_number = get_emergency_number(s.country or "")
    return {
        "generated_at":          now.isoformat(),
        "subject":               s.user_name,
        "destination":           s.destination,
        "destination_country":   s.country or "Not provided",
        "journey_started":       s.started_at,
        "last_known_location":   s.last_location or "Unknown",
        "last_checkin":          s.last_checkin or "Never",
        "unresponsive_for":      unresponsive_duration(s, now),
        "guardians":             formatted,
        "destination_coordinates": coords,
        "google_maps_link":      s.maps_link or "Not provided",
        "planned_route":         s.route or "Not provided",
        "communication_method":  s.communication_method or "Not provided",
        "traveling_companions":  formatted_companions or ["None"],
        "local_emergency_number": emergency_number or "Unknown — check local emergency services",
        "secure_link":           f"https://guardian-angel.app/case/{s.session_id}",
    }


async def get_sender_label(s: SessionModel) -> str:
    if s.user_id:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(UserModel).where(UserModel.id == s.user_id))
            u = result.scalar_one_or_none()
            if u and u.email:
                return u.email
    return f"user {s.user_name}"


def build_email_body(level: int, s: SessionModel, sent_by: str, message_text: Optional[str] = None) -> str:
    level_info = {
        1: ("#6ec6ff", "⏰ Check-in Overdue",    "The user has missed their scheduled check-in. Please try to contact them."),
        2: ("#ffd32a", "⚠️ Warning Issued",       "No response after reminder. Immediate contact is recommended."),
        3: ("#ff8c42", "🚨 Guardian Alert",        "Multiple contact attempts failed. You are a designated guardian — please act now."),
        4: ("#ff4757", "🔴 Authority Dispatch",    "All contact attempts exhausted. Authorities have been dispatched. A digital case file has been generated."),
    }
    color, title, desc = level_info.get(level, ("#ffffff", "Alert", ""))
    now = datetime.now(timezone.utc)
    coords = f"{s.latitude}, {s.longitude}" if (s.latitude or s.longitude) else None

    rows = [
        ("Person",          f"<strong>{s.user_name}</strong>"),
        ("Sent By",         sent_by),
        ("Destination",     s.destination),
        ("Journey Started", f"<span style='font-family:monospace;font-size:11px;'>{s.started_at}</span>"),
        ("Last Check-In",   f"<span style='font-family:monospace;font-size:11px;'>{s.last_checkin or 'Never'}</span>"),
        ("Unresponsive For", f"<strong style='color:{color};'>{unresponsive_duration(s, now)}</strong>"),
        ("Last Location",   s.last_location or "Unknown"),
    ]
    if coords:
        rows.append(("Coordinates", f"<span style='font-family:monospace;'>{coords}</span>"))
    if s.maps_link:
        rows.append(("Google Maps", f"<a href='{s.maps_link}' style='color:{color};'>Open location →</a>"))
    if s.route:
        rows.append(("Planned Route", s.route))
    if s.communication_method:
        rows.append(("Communication Method", s.communication_method))
    rows.append(("Alert Level", f"<span style='color:{color};font-weight:bold;font-family:monospace;'>LEVEL {level} — {ESCALATION_LEVELS.get(level,'')}</span>"))

    rows_html = "".join(
        f"<tr><td style='padding:8px 0;color:#5a7080;border-bottom:1px solid #1f2a30;width:140px;'>{k}</td>"
        f"<td style='padding:8px 0;border-bottom:1px solid #1f2a30;'>{v}</td></tr>"
        for k, v in rows
    )

    def contact_list_block(label, items, get_name, get_contact, get_email=None):
        html = "".join(
            f"<li style='margin:4px 0;color:#a0b4c0;'>{get_name(x)} "
            f"{'· ' + get_contact(x) if get_contact(x) else ''} "
            f"{'· ' + get_email(x) if get_email and get_email(x) else ''}</li>"
            for x in items
        )
        if not html:
            return ""
        return (
            f"<div style='margin-top:16px;padding:12px 16px;background:#0a0d0f;border-radius:8px;border:1px solid #1f2a30;'>"
            f"<p style='margin:0 0 8px;font-size:11px;color:#5a7080;letter-spacing:1px;text-transform:uppercase;'>{label}</p>"
            f"<ul style='margin:0;padding-left:18px;'>{html}</ul></div>"
        )

    g_items = [g for g in json.loads(s.guardians) if isinstance(g, dict)]
    guardians_block = contact_list_block(
        "Guardian Network", g_items,
        lambda g: g.get("name", ""), lambda g: g.get("contact", ""), lambda g: g.get("email", "")
    )

    companions = json.loads(s.companions) if s.companions else []
    companions_block = contact_list_block(
        "Traveling With", companions,
        lambda c: c.get("name", ""), lambda c: c.get("contact", "")
    )

    action_block = ""
    if level >= 3:
        emergency_number = get_emergency_number(s.country or "")
        emergency_line = (
            f"<p style='margin:10px 0 0;font-size:13px;color:#ffb3b3;'>Local emergency number"
            f"{' for ' + s.country if s.country else ''}: <strong style='font-family:monospace;font-size:16px;'>{emergency_number}</strong></p>"
            if emergency_number else
            f"<p style='margin:10px 0 0;font-size:12px;color:#a0b4c0;'>Destination country not on file — please look up the local emergency number before calling.</p>"
        )
        action_block = f"""
    <div style="margin-top:16px;padding:16px;background:#1f0e0e;border-radius:8px;border:1px solid {color};">
      <p style="margin:0;font-size:13px;font-weight:bold;color:{color};">ACTION NEEDED</p>
      <p style="margin:8px 0 0;font-size:13px;color:#e8eef2;line-height:1.6;">
        Please try to reach <strong>{s.user_name}</strong> directly right away. If you cannot reach them,
        please contact the local authorities at the destination and share the details in this email
        (last known location, coordinates, and how long they've been unresponsive).
      </p>
      {emergency_line}
    </div>"""

    message_block = ""
    if message_text:
        message_block = f"""
    <div style="margin-top:16px;padding:14px 16px;background:#0e1a14;border-radius:8px;border:1px solid #1f4a38;">
      <p style="margin:0 0 6px;font-size:11px;color:#5a7080;letter-spacing:1px;text-transform:uppercase;">💬 Message from {s.user_name}</p>
      <p style="margin:0;font-size:14px;color:#e8eef2;line-height:1.6;font-style:italic;">"{message_text}"</p>
    </div>"""

    reply_url = f"{APP_BASE_URL}/guardian/{s.session_id}"
    reply_block = f"""
    <div style="margin-top:16px;text-align:center;">
      <a href="{reply_url}" style="display:inline-block;padding:10px 20px;border-radius:8px;background:{color};color:#0a0d0f;font-weight:bold;text-decoration:none;font-size:13px;">View Details &amp; Reply →</a>
    </div>"""

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
    {companions_block}
    {message_block}
    {action_block}
    {reply_block}
  </div>
  <div style="background:#111518;padding:14px 24px;border-top:1px solid #1f2a30;text-align:center;">
    <p style="margin:0;font-size:11px;color:#5a7080;">Guardian Angel · Automated Safety System</p>
    <p style="margin:4px 0 0;font-size:10px;color:#3a5060;font-family:monospace;">Session: {s.session_id}</p>
  </div>
</div>
</body></html>"""


async def send_alert_emails(s: SessionModel, level: int, message_text: Optional[str] = None) -> None:
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
    sent_by = await get_sender_label(s)
    body    = build_email_body(level, s, sent_by, message_text)

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


async def send_message_email(s: SessionModel, text: str) -> None:
    """Notify guardians the user sent a short message while checking in safe (no escalation email fires on its own for a safe check-in)."""
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
        print("[EMAIL] SMTP not configured — skipping message notification")
        return

    subject   = f"💬 {s.user_name} is safe — sent you a message"
    reply_url = f"{APP_BASE_URL}/guardian/{s.session_id}"
    body = f"""<!DOCTYPE html><html>
<body style="margin:0;padding:20px;font-family:Arial,sans-serif;background:#0a0d0f;color:#e8eef2;">
<div style="max-width:520px;margin:0 auto;background:#161b1f;border-radius:12px;overflow:hidden;border:2px solid #00e5a0;">
  <div style="background:#111518;padding:20px 24px;border-bottom:1px solid #1f2a30;">
    <p style="margin:0;font-size:20px;font-weight:bold;color:#00e5a0;">🛡 GUARDIAN ANGEL</p>
    <p style="margin:4px 0 0;font-size:11px;color:#5a7080;font-family:monospace;letter-spacing:1px;">✅ USER CHECKED IN SAFE</p>
  </div>
  <div style="padding:20px 24px;">
    <p style="margin:0 0 12px;font-size:14px;">
      <strong>{s.user_name}</strong> checked in safe and sent you a message:
    </p>
    <div style="padding:14px 16px;background:#0e1a14;border-radius:8px;border:1px solid #1f4a38;">
      <p style="margin:0;font-size:14px;color:#e8eef2;line-height:1.6;font-style:italic;">"{text}"</p>
    </div>
    <div style="margin-top:20px;text-align:center;">
      <a href="{reply_url}" style="display:inline-block;padding:10px 20px;border-radius:8px;background:#00e5a0;color:#0a0d0f;font-weight:bold;text-decoration:none;font-size:13px;">View Details &amp; Reply →</a>
    </div>
  </div>
  <div style="background:#111518;padding:14px 24px;border-top:1px solid #1f2a30;text-align:center;">
    <p style="margin:0;font-size:11px;color:#5a7080;">Guardian Angel · Automated Safety System</p>
  </div>
</div>
</body></html>"""

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
                print(f"[EMAIL] Message notification sent to {recipient}")

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
        s.case_file = encrypt_case_file(json.dumps(generate_case_file(s)))
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
                select(SessionModel).where(SessionModel.status.in_(["ACTIVE", "DORMANT"]))
            )
            sessions = result.scalars().all()
            now = datetime.now(timezone.utc)
            now_min = now.hour * 60 + now.minute
            for s in sessions:
                if s.session_type == "DAILY":
                    windows = json.loads(s.windows or '[]')
                    active_days = json.loads(s.active_days) if s.active_days else None
                    window_open = is_active_day(now, active_days) and in_any_window(now_min, windows)
                    if s.status == "DORMANT":
                        if window_open:
                            s.status = "ACTIVE"
                            s.escalation_level = 0
                            s.next_checkin = (now + timedelta(minutes=s.interval_minutes)).isoformat()
                            await log_event(db, s.session_id, 0, f"Daily window opened for {s.user_name} — monitoring resumed")
                            await db.commit()
                        continue
                    if not window_open and s.escalation_level == 0:
                        s.status = "DORMANT"
                        s.next_checkin = next_any_window_start(now, windows, active_days).isoformat()
                        await log_event(db, s.session_id, 0, f"Daily window closed for {s.user_name} — monitoring paused")
                        await db.commit()
                        continue

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
    _load_or_create_case_key()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for stmt in [
            "ALTER TABLE sessions ADD COLUMN user_id TEXT DEFAULT ''",
            "ALTER TABLE sessions ADD COLUMN escalation_intervals TEXT",
            "ALTER TABLE sessions ADD COLUMN session_type TEXT DEFAULT 'TRIP'",
            "ALTER TABLE sessions ADD COLUMN windows TEXT",
            "ALTER TABLE sessions ADD COLUMN active_days TEXT",
            "ALTER TABLE sessions ADD COLUMN maps_link TEXT",
            "ALTER TABLE sessions ADD COLUMN latitude TEXT",
            "ALTER TABLE sessions ADD COLUMN longitude TEXT",
            "ALTER TABLE sessions ADD COLUMN route TEXT",
            "ALTER TABLE sessions ADD COLUMN communication_method TEXT",
            "ALTER TABLE sessions ADD COLUMN companions TEXT",
            "ALTER TABLE sessions ADD COLUMN country TEXT",
            "ALTER TABLE users ADD COLUMN email TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN phone TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN address TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN date_of_birth TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN blood_type TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN medical_notes TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN photo TEXT DEFAULT ''",
            "ALTER TABLE user_guardians ADD COLUMN linked_user_id TEXT DEFAULT ''",
            "ALTER TABLE user_guardians ADD COLUMN linked_username TEXT DEFAULT ''",
            "ALTER TABLE user_guardians ADD COLUMN status TEXT DEFAULT 'accepted'",
        ]:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass

    # Emergency numbers live in the DB from here on (admin-editable without a redeploy) —
    # seed it from the built-in table on first boot, otherwise refresh the in-memory
    # lookup cache (EMERGENCY_NUMBERS) from whatever's in the DB.
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(EmergencyNumberModel))
        rows = result.scalars().all()
        if not rows:
            today = datetime.now(timezone.utc).date().isoformat()
            for country, number in EMERGENCY_NUMBERS.items():
                db.add(EmergencyNumberModel(country=country, number=number, last_verified=today))
            await db.commit()
            print(f"[EMERGENCY NUMBERS] Seeded {len(EMERGENCY_NUMBERS)} countries into the database")
        else:
            EMERGENCY_NUMBERS.clear()
            EMERGENCY_NUMBERS.update({r.country: r.number for r in rows})
            print(f"[EMERGENCY NUMBERS] Loaded {len(rows)} countries from the database")

    asyncio.create_task(watchdog())
    yield


app = FastAPI(title="Guardian Angel API", version="1.0.0-POC", lifespan=lifespan)

# Cookies + wildcard CORS is rejected by browsers once allow_credentials=True, so this is
# locked to the app's own origin(s) rather than "*". Override via ALLOWED_ORIGINS (comma-
# separated) if the app is ever served from more than one origin.
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", APP_BASE_URL).split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

limiter = Limiter(key_func=get_remote_address, enabled=os.getenv("DISABLE_RATE_LIMIT", "false").lower() != "true")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


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
async def start_journey(
    body: JourneyStart, db: AsyncSession = Depends(get_db),
    user: Optional[UserModel] = Depends(get_current_user_optional),
):
    if body.session_type == "DAILY" and not body.windows:
        raise HTTPException(400, "Daily Usage requires at least one active window")

    sid = str(uuid.uuid4())[:12]
    now = datetime.now(timezone.utc)
    # Starting a journey doesn't require an account (kept intentionally anonymous-capable —
    # you can still be found via the session_id itself) — but if you ARE signed in, the
    # journey is always attributed to your real account, never a client-supplied id.
    owner_id = user.id if user else ""
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
        user_id=owner_id,
        escalation_intervals=json.dumps(
            {str(k): v for k, v in body.escalation_intervals.items()}
        ) if body.escalation_intervals else json.dumps({"1": 1, "2": 1, "3": 1}),
        session_type=body.session_type,
        windows=json.dumps(body.windows) if body.windows else None,
        active_days=json.dumps(body.active_days) if body.active_days else None,
        maps_link=body.maps_link or None,
        latitude=body.latitude or None,
        longitude=body.longitude or None,
        route=body.route or None,
        communication_method=body.communication_method or None,
        companions=json.dumps([c.model_dump() for c in body.companions]) if body.companions else None,
        country=body.country or None,
    )
    db.add(s)
    label = f"Daily Usage \"{body.destination}\" started for {body.user_name}" if body.session_type == "DAILY" \
        else f"Journey started for {body.user_name} to {body.destination}"
    await log_event(db, sid, 0, label)
    await db.commit()
    return {
        "session_id": sid, "message": "Journey started. Stay safe.", "next_checkin": s.next_checkin,
        "emergency_number": get_emergency_number(body.country),
    }


async def trigger_duress(db: AsyncSession, s: SessionModel, message_text: Optional[str] = None) -> str:
    """Silently escalates to Level 4/DURESS. Commits. Returns the new next_checkin isoformat."""
    next_ci = (datetime.now(timezone.utc) + timedelta(minutes=s.interval_minutes)).isoformat()
    await log_event(db, s.session_id, 0, f"Check-in accepted for {s.user_name} (timer reset)")
    await log_event(db, s.session_id, 4, f"SILENT DURESS — immediate Level 4 for {s.user_name}", silent=True)
    s.escalation_level = 4
    s.status = "DURESS"
    s.case_file = encrypt_case_file(json.dumps(generate_case_file(s)))
    s.next_checkin = next_ci
    await db.commit()
    asyncio.create_task(send_alert_emails(s, 4, message_text=message_text))
    if s.user_id:
        asyncio.create_task(send_push_to_user(s.user_id, "🔴 Duress Alert Active", "Silent duress code entered. Guardian network alerted.", 4))
    return next_ci


async def apply_safe_checkin(db: AsyncSession, s: SessionModel, lat: Optional[float] = None, lng: Optional[float] = None) -> str:
    """Resets escalation for a valid safe-code check-in (DAILY window/day aware). Commits. Returns the new next_checkin isoformat."""
    now = datetime.now(timezone.utc)
    s.last_checkin = now.isoformat()
    s.escalation_level = 0
    s.checkin_count += 1
    if lat and lng:
        s.last_location = f"{lat},{lng}"

    now_min = now.hour * 60 + now.minute
    windows = json.loads(s.windows or '[]') if s.session_type == "DAILY" else []
    active_days = json.loads(s.active_days) if (s.session_type == "DAILY" and s.active_days) else None
    if s.session_type == "DAILY" and not (is_active_day(now, active_days) and in_any_window(now_min, windows)):
        s.status = "DORMANT"
        s.next_checkin = next_any_window_start(now, windows, active_days).isoformat()
    else:
        s.status = "ACTIVE"
        s.next_checkin = (now + timedelta(minutes=s.interval_minutes)).isoformat()

    await log_event(db, s.session_id, 0, f"Check-in #{s.checkin_count} by {s.user_name}")
    await db.commit()
    return s.next_checkin


@app.post("/api/checkin")
@limiter.limit("20/minute")
async def check_in(request: Request, body: CheckIn, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SessionModel).where(SessionModel.session_id == body.session_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Session not found")
    if s.status == "ENDED":
        raise HTTPException(400, "Journey already ended")

    if body.code == s.duress_code:
        next_ci = await trigger_duress(db, s)
        return {"status": "ok", "message": "Check-in received. Timer reset.", "next_checkin": next_ci}

    if body.code != s.safe_code:
        raise HTTPException(403, "Invalid code")

    next_ci = await apply_safe_checkin(db, s, body.lat, body.lng)
    return {"status": "ok", "message": "Check-in received. Timer reset.", "next_checkin": next_ci}


async def store_message(db: AsyncSession, session_id: str, sender: str, sender_label: str, text: str) -> dict:
    msg = MessageModel(
        id=str(uuid.uuid4())[:12],
        session_id=session_id,
        sender=sender,
        sender_label=sender_label,
        text=text,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    db.add(msg)
    await db.commit()
    return {"sender": msg.sender, "sender_label": msg.sender_label, "text": msg.text, "timestamp": msg.timestamp}


@app.post("/api/message/send")
@limiter.limit("20/minute")
async def send_message(request: Request, body: MessageSend, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SessionModel).where(SessionModel.session_id == body.session_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Session not found")
    if s.status == "ENDED":
        raise HTTPException(400, "Journey already ended")

    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Message text is required")

    if body.code == s.duress_code:
        next_ci = await trigger_duress(db, s, message_text=text)
        await store_message(db, s.session_id, "user", s.user_name, text)
        return {"status": "ok", "message": "Message sent.", "next_checkin": next_ci}

    if body.code != s.safe_code:
        raise HTTPException(403, "Invalid code")

    next_ci = await apply_safe_checkin(db, s)
    await store_message(db, s.session_id, "user", s.user_name, text)
    asyncio.create_task(send_message_email(s, text))
    return {"status": "ok", "message": "Message sent. You're marked safe.", "next_checkin": next_ci}


@app.post("/api/message/guardian-reply")
async def guardian_reply(body: GuardianReply, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SessionModel).where(SessionModel.session_id == body.session_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Session not found")

    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Message text is required")

    label = body.guardian_name.strip() or "A guardian"
    if body.guardian_user_id.strip():
        # Trust the logged-in account's real username over any typed name — same
        # client-trusted user_id model already used everywhere else in this app.
        result = await db.execute(select(UserModel).where(UserModel.id == body.guardian_user_id.strip()))
        linked_user = result.scalar_one_or_none()
        if linked_user:
            label = linked_user.username

    await store_message(db, s.session_id, "guardian", label, text)
    if s.user_id:
        asyncio.create_task(send_push_to_user(s.user_id, f"💬 Message from {label}", text, s.escalation_level))
    return {"status": "ok", "message": "Reply sent."}


@app.get("/api/messages")
async def list_messages(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(MessageModel).where(MessageModel.session_id == session_id).order_by(MessageModel.timestamp.asc())
    )
    return [
        {"sender": m.sender, "sender_label": m.sender_label, "text": m.text, "timestamp": m.timestamp}
        for m in result.scalars().all()
    ]


LOCATION_HISTORY_LIMIT = 200


@app.post("/api/location/ping")
@limiter.limit("30/minute")
async def location_ping(request: Request, body: LocationPing, db: AsyncSession = Depends(get_db)):
    """Passive GPS telemetry from the app while a session is active — not a trust action
    (no code required), just live tracking. Adaptive ping frequency is a client concern."""
    result = await db.execute(select(SessionModel).where(SessionModel.session_id == body.session_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Session not found")
    if s.status == "ENDED":
        raise HTTPException(400, "Journey already ended")

    now = datetime.now(timezone.utc).isoformat()
    s.last_location = f"{body.lat},{body.lng}"
    db.add(LocationPingModel(
        id=str(uuid.uuid4())[:12], session_id=body.session_id,
        lat=str(body.lat), lng=str(body.lng), timestamp=now,
    ))
    await db.commit()
    return {"ok": True}


@app.get("/api/location/history")
async def location_history(session_id: str, db: AsyncSession = Depends(get_db)):
    """Same trust level as /api/session/{id} and /api/messages — session ID is the
    capability token, so guardians can see it without an account."""
    result = await db.execute(
        select(LocationPingModel).where(LocationPingModel.session_id == session_id)
        .order_by(LocationPingModel.timestamp.desc()).limit(LOCATION_HISTORY_LIMIT)
    )
    pings = list(reversed(result.scalars().all()))
    return [{"lat": p.lat, "lng": p.lng, "timestamp": p.timestamp} for p in pings]


@app.get("/api/guardian-inbox")
async def guardian_inbox(db: AsyncSession = Depends(get_db), user: UserModel = Depends(get_current_user)):
    """Sessions where this app user is a CONFIRMED linked guardian — for the in-app Guardian Inbox.
    Only counts once the traveler's saved-guardian record for this user has status == 'accepted';
    pending/declined links stay invisible until accepted (see /api/guardian-requests)."""
    accepted_result = await db.execute(
        select(UserGuardianModel.user_id).where(
            UserGuardianModel.linked_user_id == user.id,
            UserGuardianModel.status == "accepted",
        )
    )
    accepted_traveler_ids = {row[0] for row in accepted_result.all()}
    if not accepted_traveler_ids:
        return []

    result = await db.execute(select(SessionModel).order_by(SessionModel.started_at.desc()))
    matches = []
    for s in result.scalars().all():
        if s.user_id not in accepted_traveler_ids:
            continue
        items = json.loads(s.guardians or "[]")
        if any(isinstance(g, dict) and g.get("linked_user_id") == user.id for g in items):
            matches.append({
                "session_id": s.session_id, "user": s.user_name, "destination": s.destination,
                "status": s.status, "level": s.escalation_level, "session_type": s.session_type or "TRIP",
                "started_at": s.started_at,
            })
    return matches


@app.get("/api/guardian-requests")
async def guardian_requests(db: AsyncSession = Depends(get_db), user: UserModel = Depends(get_current_user)):
    """People who've listed me as a guardian and are awaiting my confirmation."""
    result = await db.execute(
        select(UserGuardianModel).where(
            UserGuardianModel.linked_user_id == user.id,
            UserGuardianModel.status == "pending",
        )
    )
    rows = result.scalars().all()
    traveler_ids = {g.user_id for g in rows}
    travelers = {}
    if traveler_ids:
        tresult = await db.execute(select(UserModel).where(UserModel.id.in_(traveler_ids)))
        travelers = {u.id: u.username for u in tresult.scalars().all()}
    return [
        {"id": g.id, "traveler_username": travelers.get(g.user_id, "Unknown user"), "created_at": g.created_at}
        for g in rows
    ]


@app.post("/api/guardians/{guardian_id}/respond")
async def respond_to_guardian_request(
    guardian_id: str, body: GuardianRespond, db: AsyncSession = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    result = await db.execute(select(UserGuardianModel).where(UserGuardianModel.id == guardian_id))
    g = result.scalar_one_or_none()
    if not g:
        raise HTTPException(404, "Guardian request not found")
    if g.linked_user_id != user.id:
        raise HTTPException(403, "This request isn't addressed to you")
    if g.status != "pending":
        raise HTTPException(400, f"Already {g.status}")
    g.status = "accepted" if body.accept else "declined"
    await db.commit()
    return {"ok": True, "status": g.status}


@app.get("/guardian/{session_id}")
def serve_guardian_page(session_id: str):
    return FileResponse(BASE_DIR / "guardian.html")


@app.post("/api/journey/end")
async def end_journey(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SessionModel).where(SessionModel.session_id == session_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Session not found")
    if s.status == "ENDED":
        raise HTTPException(400, "Journey already ended")
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
async def get_case_file(
    session_id: str, db: AsyncSession = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    """Encrypted at rest — only the journey's own account or the admin can decrypt it."""
    result = await db.execute(select(SessionModel).where(SessionModel.session_id == session_id))
    s = result.scalar_one_or_none()
    if not s or not s.case_file:
        raise HTTPException(404, "No case file generated yet")
    # Anonymous journeys (no account) have no owner to check against — the session ID
    # itself is already their only credential, consistent with how /api/session/{id} and
    # /api/messages already work for them. Owned journeys require the real owner or admin.
    if s.user_id and s.user_id != user.id and user.username not in ADMIN_USERNAMES:
        raise HTTPException(403, "Not your case file")
    return decrypt_case_file(s.case_file)


@app.get("/api/sessions")
async def list_sessions(
    mine: bool = True, db: AsyncSession = Depends(get_db),
    user: Optional[UserModel] = Depends(get_current_user_optional),
):
    if mine:
        if not user:
            raise HTTPException(401, "Sign in to view your journeys")
        q = select(SessionModel).where(SessionModel.user_id == user.id)
    else:
        # The Monitor tab's "everything" view — admin only, not just "logged in".
        if not user or user.username not in ADMIN_USERNAMES:
            raise HTTPException(403, "Admin only")
        q = select(SessionModel)
    result = await db.execute(q.order_by(SessionModel.started_at.desc()))
    return [
        {"session_id": s.session_id, "user": s.user_name, "status": s.status,
         "level": s.escalation_level, "destination": s.destination, "started_at": s.started_at,
         "session_type": s.session_type or "TRIP",
         "windows": json.loads(s.windows) if s.windows else [],
         "active_days": json.loads(s.active_days) if s.active_days else []}
        for s in result.scalars().all()
    ]


class EmergencyNumberUpsert(BaseModel):
    country: str
    number: str


@app.get("/api/admin/emergency-numbers")
async def list_emergency_numbers(db: AsyncSession = Depends(get_db), _admin: UserModel = Depends(require_admin)):
    result = await db.execute(select(EmergencyNumberModel).order_by(EmergencyNumberModel.country.asc()))
    return [{"country": r.country, "number": r.number, "last_verified": r.last_verified} for r in result.scalars().all()]


@app.post("/api/admin/emergency-numbers")
async def upsert_emergency_number(
    body: EmergencyNumberUpsert, db: AsyncSession = Depends(get_db),
    _admin: UserModel = Depends(require_admin),
):
    country = body.country.strip().lower()
    number = body.number.strip()
    if not country or not number:
        raise HTTPException(400, "Country and number are required")
    today = datetime.now(timezone.utc).date().isoformat()

    result = await db.execute(select(EmergencyNumberModel).where(EmergencyNumberModel.country == country))
    row = result.scalar_one_or_none()
    if row:
        row.number = number
        row.last_verified = today
    else:
        db.add(EmergencyNumberModel(country=country, number=number, last_verified=today))
    await db.commit()

    EMERGENCY_NUMBERS[country] = number  # keep the in-process lookup cache in sync immediately
    return {"country": country, "number": number, "last_verified": today}


@app.delete("/api/admin/emergency-numbers/{country}")
async def delete_emergency_number(
    country: str, db: AsyncSession = Depends(get_db),
    _admin: UserModel = Depends(require_admin),
):
    country = country.strip().lower()
    result = await db.execute(select(EmergencyNumberModel).where(EmergencyNumberModel.country == country))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Not found")
    await db.delete(row)
    await db.commit()
    EMERGENCY_NUMBERS.pop(country, None)
    return {"ok": True}


@app.get("/api/guardians")
async def list_guardians(db: AsyncSession = Depends(get_db), user: UserModel = Depends(get_current_user)):
    result = await db.execute(
        select(UserGuardianModel).where(UserGuardianModel.user_id == user.id)
    )
    return [
        {"id": g.id, "name": g.name, "email": g.email or "", "phone": g.phone or "",
         "linked_user_id": g.linked_user_id or "", "linked_username": g.linked_username or "",
         "status": g.status or "accepted"}
        for g in result.scalars().all()
    ]


@app.post("/api/guardians")
async def create_guardian(
    body: GuardianCreate, db: AsyncSession = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    linked_user_id = ""
    linked_username = ""
    status = "accepted"  # no account on the other end to confirm with — matches today's behavior
    if body.linked_username.strip():
        result = await db.execute(select(UserModel).where(UserModel.username == body.linked_username.strip()))
        linked_user = result.scalar_one_or_none()
        if not linked_user:
            raise HTTPException(404, f"No app user found with username \"{body.linked_username.strip()}\"")
        if linked_user.id == user.id:
            raise HTTPException(400, "You can't add yourself as a guardian")
        linked_user_id = linked_user.id
        linked_username = linked_user.username
        status = "pending"  # they need to confirm before their Guardian Inbox shows anything of yours

    g = UserGuardianModel(
        id=str(uuid.uuid4())[:12],
        user_id=user.id,
        name=body.name,
        email=body.email,
        phone=body.phone,
        linked_user_id=linked_user_id,
        linked_username=linked_username,
        status=status,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    db.add(g)
    await db.commit()
    return {"id": g.id, "name": g.name, "email": g.email, "phone": g.phone,
            "linked_user_id": linked_user_id, "linked_username": linked_username, "status": status}


@app.delete("/api/guardians/{guardian_id}")
async def delete_guardian(
    guardian_id: str, db: AsyncSession = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    result = await db.execute(
        select(UserGuardianModel).where(UserGuardianModel.id == guardian_id)
    )
    g = result.scalar_one_or_none()
    if not g:
        raise HTTPException(404, "Guardian not found")
    if g.user_id != user.id:
        raise HTTPException(403, "Not your guardian to remove")
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
async def push_subscribe(
    body: PushSubscribe, db: AsyncSession = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    # Upsert: same user + same endpoint → update keys
    result = await db.execute(
        select(PushSubscriptionModel).where(
            PushSubscriptionModel.user_id  == user.id,
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
            user_id=user.id,
            endpoint=body.endpoint,
            p256dh=body.p256dh,
            auth=body.auth,
            created_at=datetime.now(timezone.utc).isoformat(),
        ))
    await db.commit()
    print(f"[PUSH] Subscription saved for user {user.id}")
    return {"ok": True}


@app.post("/api/register")
@limiter.limit("10/minute")
async def register(request: Request, body: UserRegister, response: Response, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserModel).where(UserModel.username == body.username))
    if result.scalar_one_or_none():
        raise HTTPException(400, "Username already taken")
    if len(body.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    user = UserModel(
        id=str(uuid.uuid4())[:12],
        username=body.username,
        password_hash=hash_password(body.password),
        reason=body.reason,
        email=body.email,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    db.add(user)
    await db.commit()
    token = await create_auth_session(db, user.id)
    set_session_cookie(response, token)
    return {"id": user.id, "username": user.username, "email": user.email or ""}


@app.post("/api/login")
@limiter.limit("10/minute")
async def login(request: Request, body: UserLogin, response: Response, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserModel).where(UserModel.username == body.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid username or password")
    if not user.password_hash.startswith("$2"):
        # Lazily upgrade legacy SHA-256 hashes to bcrypt now that we know the plaintext was correct.
        user.password_hash = hash_password(body.password)
    token = await create_auth_session(db, user.id)
    await db.commit()
    set_session_cookie(response, token)
    return {"id": user.id, "username": user.username, "reason": user.reason, "email": user.email or ""}


@app.post("/api/logout")
async def logout(response: Response, ga_session: Optional[str] = Cookie(None), db: AsyncSession = Depends(get_db)):
    if ga_session:
        result = await db.execute(select(AuthSessionModel).where(AuthSessionModel.token == ga_session))
        sess = result.scalar_one_or_none()
        if sess:
            await db.delete(sess)
            await db.commit()
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"ok": True}


@app.get("/api/me")
async def get_me(user: UserModel = Depends(get_current_user)):
    return {"id": user.id, "username": user.username, "reason": user.reason or "", "email": user.email or ""}


PROFILE_PHOTO_MAX_CHARS = 2_000_000  # ~2MB base64 data-URI


class ProfileUpdate(BaseModel):
    email: str = ""
    phone: str = ""
    address: str = ""
    date_of_birth: str = ""
    blood_type: str = ""
    medical_notes: str = ""
    photo: str = ""  # base64 data-URI, client-resized before upload


def user_to_profile_dict(u: UserModel) -> dict:
    return {
        "id":            u.id,
        "username":      u.username,
        "reason":        u.reason or "",
        "email":         u.email or "",
        "phone":         u.phone or "",
        "address":       u.address or "",
        "date_of_birth": u.date_of_birth or "",
        "blood_type":    u.blood_type or "",
        "medical_notes": u.medical_notes or "",
        "photo":         u.photo or "",
    }


@app.get("/api/profile")
async def get_profile(user: UserModel = Depends(get_current_user)):
    return user_to_profile_dict(user)


@app.post("/api/profile")
async def update_profile(
    body: ProfileUpdate, db: AsyncSession = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    if len(body.photo) > PROFILE_PHOTO_MAX_CHARS:
        raise HTTPException(400, "Photo is too large — please use a smaller image")
    result = await db.execute(select(UserModel).where(UserModel.id == user.id))
    u = result.scalar_one_or_none()
    if not u:
        raise HTTPException(404, "User not found")
    u.email         = body.email
    u.phone         = body.phone
    u.address       = body.address
    u.date_of_birth = body.date_of_birth
    u.blood_type    = body.blood_type
    u.medical_notes = body.medical_notes
    u.photo         = body.photo
    await db.commit()
    return user_to_profile_dict(u)


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
    requested_by: str = ""


@app.post("/api/test-email")
async def send_test_email(body: TestEmailBody):
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "").replace(" ", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user)

    if not smtp_user or not smtp_pass:
        raise HTTPException(400, "SMTP not configured. Create a .env file with SMTP_USER and SMTP_PASS.")

    sent_by = body.requested_by or "an unknown user"
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
      Sent by: {sent_by}
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
