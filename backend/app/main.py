from __future__ import annotations

import base64
import asyncio
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, create_engine, delete, desc, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from .weather_view import build_overview


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://weather:weather@db:5432/weather_dashboard")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
MONITOR_INGEST_TOKEN = os.environ.get("MONITOR_INGEST_TOKEN", "")
CONTROL_TOKEN = os.environ.get("CONTROL_TOKEN", "")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").lower() == "true"
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "90"))
SHUTDOWN_ENABLED = os.environ.get("SHUTDOWN_ENABLED", "false").lower() == "true"

if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET must be configured")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class AdminUser(Base):
    __tablename__ = "admin_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MonitoringRun(Base):
    __tablename__ = "monitoring_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(30), default="completed")
    decision: Mapped[str] = mapped_column(String(40), default="no_alert")
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProviderReading(Base):
    __tablename__ = "provider_readings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_key: Mapped[str] = mapped_column(String(120), index=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    precipitation_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    precipitation_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    weather_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thunder: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class EndpointCall(Base):
    __tablename__ = "endpoint_calls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_key: Mapped[str] = mapped_column(String(120), index=True)
    category: Mapped[str] = mapped_column(String(80), index=True)
    endpoint: Mapped[str] = mapped_column(String(160), index=True)
    called_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(30), default="success")
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class WarningEvent(Base):
    __tablename__ = "warning_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_key: Mapped[str] = mapped_column(String(120), index=True)
    source: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(255))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AlertEvent(Base):
    __tablename__ = "alert_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_key: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    reason: Mapped[str] = mapped_column(String(255))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(40))
    delivery_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_eligible_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class ShutdownRequest(Base):
    __tablename__ = "shutdown_requests"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    requested_by: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), default="pending")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    cancel_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)


class ApiToken(Base):
    __tablename__ = "api_tokens"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    prefix: Mapped[str] = mapped_column(String(16))
    scopes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(120))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class LoginBody(BaseModel):
    username: str
    password: str


class TokenCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = ["weather:read", "alerts:read", "status:read"]
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class IngestProvider(BaseModel):
    provider: str
    observed_at: datetime
    temperature_c: float | None = None
    precipitation_mm: float | None = None
    precipitation_probability: float | None = None
    wind_speed: float | None = None
    weather_code: int | None = None
    thunder: bool = False
    error: str | None = None


class IngestEndpointCall(BaseModel):
    category: str = Field(min_length=1, max_length=80)
    endpoint: str = Field(min_length=1, max_length=160)
    called_at: datetime
    status: str = "success"
    duration_ms: int | None = Field(default=None, ge=0)
    summary: str | None = None
    response_data: dict[str, Any] = Field(default_factory=dict)


class IngestBody(BaseModel):
    run_key: str = Field(min_length=1, max_length=120)
    observed_at: datetime
    decision: str = "no_alert"
    providers: list[IngestProvider]
    endpoint_calls: list[IngestEndpointCall] = Field(default_factory=list)
    official_warnings: list[str] = []
    alert_reason: str | None = None
    alert_detail: str | None = None
    telegram_status: str | None = None
    telegram_detail: str | None = Field(default=None, max_length=500)
    next_eligible_at: datetime | None = None


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    iterations = 310_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode())
        expected = base64.urlsafe_b64decode(digest_text.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def sign_session(username: str) -> str:
    payload = f"{username}|{int(time.time()) + 8 * 3600}".encode()
    body = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    signature = hmac.new(SESSION_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def session_username(value: str | None) -> str | None:
    if not value or "." not in value:
        return None
    body, signature = value.rsplit(".", 1)
    expected = hmac.new(SESSION_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        username, expiry = base64.urlsafe_b64decode((body + "===").encode()).decode().split("|", 1)
        return username if int(expiry) > int(time.time()) else None
    except (ValueError, TypeError):
        return None


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def db() -> Session:
    return SessionLocal()


def seed_admin() -> None:
    if not ADMIN_PASSWORD:
        return
    with db() as session:
        existing = session.scalar(select(AdminUser).where(AdminUser.username == ADMIN_USERNAME))
        if not existing:
            session.add(AdminUser(username=ADMIN_USERNAME, password_hash=hash_password(ADMIN_PASSWORD)))
            session.commit()


def cleanup_old_data() -> None:
    cutoff = utcnow() - timedelta(days=RETENTION_DAYS)
    with db() as session:
        session.execute(delete(ProviderReading).where(ProviderReading.observed_at < cutoff))
        session.execute(delete(WarningEvent).where(WarningEvent.observed_at < cutoff))
        session.execute(delete(EndpointCall).where(EndpointCall.called_at < cutoff))
        session.execute(delete(AlertEvent).where(AlertEvent.sent_at < cutoff))
        session.execute(delete(MonitoringRun).where(MonitoringRun.observed_at < cutoff))
        session.commit()


def current_admin(request: Request) -> str | None:
    return session_username(request.cookies.get("weather_dashboard_session"))


def require_admin(request: Request) -> str:
    username = current_admin(request)
    if not username:
        raise HTTPException(status_code=401, detail="Administrator login required")
    return username


def has_scope(request: Request, scope: str) -> str:
    username = current_admin(request)
    if username:
        return username
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="API token required")
    digest = token_digest(authorization[7:].strip())
    with db() as session:
        token = session.scalar(select(ApiToken).where(ApiToken.token_hash == digest))
        if not token or token.revoked_at or (token.expires_at and token.expires_at <= utcnow()):
            raise HTTPException(status_code=401, detail="Invalid or expired API token")
        if scope not in (token.scopes or []):
            raise HTTPException(status_code=403, detail="Token scope is insufficient")
        token.last_used_at = utcnow()
        session.commit()
        return f"token:{token.prefix}"


def require_internal_token(value: str | None) -> None:
    if not CONTROL_TOKEN or not value or not hmac.compare_digest(value, CONTROL_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid internal control token")


def require_scope(scope: str):
    def dependency(request: Request) -> str:
        return has_scope(request, scope)
    return dependency


app = FastAPI(title="Weather Monitoring API", version="1.0.0", openapi_url="/api/v1/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=[], allow_credentials=True, allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type", "X-Monitor-Token"])
event_subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[str]]] = set()
event_subscribers_lock = threading.Lock()


def publish_monitor_event(run_key: str, observed_at: datetime) -> None:
    message = json.dumps({"run_key": run_key, "observed_at": observed_at.isoformat()})
    with event_subscribers_lock:
        subscribers = list(event_subscribers)
    for loop, queue in subscribers:
        if not loop.is_closed():
            loop.call_soon_threadsafe(queue.put_nowait, message)


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE alert_events ADD COLUMN IF NOT EXISTS delivery_detail TEXT"))
        connection.execute(text("ALTER TABLE alert_events ADD COLUMN IF NOT EXISTS next_eligible_at TIMESTAMPTZ"))
    seed_admin()
    cleanup_old_data()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    with db() as session:
        session.execute(select(1))
    return {"status": "ok"}


@app.post("/api/v1/auth/login")
def login(body: LoginBody, response: Response) -> dict[str, str]:
    with db() as session:
        user = session.scalar(select(AdminUser).where(AdminUser.username == body.username, AdminUser.active.is_(True)))
        if not user or not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid username or password")
        session.add(AuditEvent(actor=user.username, action="login"))
        session.commit()
    response.set_cookie("weather_dashboard_session", sign_session(body.username), httponly=True, secure=COOKIE_SECURE, samesite="lax", max_age=8 * 3600)
    return {"status": "ok"}


@app.post("/api/v1/auth/logout")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie("weather_dashboard_session")
    return {"status": "ok"}


@app.get("/api/v1/auth/me")
def me(request: Request) -> dict[str, Any]:
    username = current_admin(request)
    if not username:
        raise HTTPException(status_code=401, detail="Not logged in")
    return {"username": username}


@app.get("/api/v1/status")
def status_view(_: str = Depends(require_scope("status:read"))) -> dict[str, Any]:
    with db() as session:
        latest_run = session.scalar(select(MonitoringRun).order_by(desc(MonitoringRun.observed_at)))
        latest_alert = session.scalar(select(AlertEvent).order_by(desc(AlertEvent.sent_at)))
        recent_runs = session.scalars(select(MonitoringRun.observed_at).order_by(desc(MonitoringRun.observed_at)).limit(8)).all()
    gaps = [(recent_runs[i] - recent_runs[i + 1]).total_seconds() for i in range(len(recent_runs) - 1)]
    interval = sorted(gaps)[len(gaps) // 2] if gaps else None
    next_run = latest_run.observed_at + timedelta(seconds=interval) if latest_run and interval else None
    return {"status": "ok", "retention_days": RETENTION_DAYS, "shutdown_enabled": SHUTDOWN_ENABLED, "latest_run": latest_run.observed_at if latest_run else None, "latest_alert": latest_alert.sent_at if latest_alert else None, "estimated_interval_seconds": round(interval) if interval else None, "next_run_estimate": next_run}


@app.get("/api/v1/monitoring/endpoint-calls")
def endpoint_calls(limit: int = 100, category: str | None = None, _: str = Depends(require_scope("status:read"))) -> list[dict[str, Any]]:
    with db() as session:
        query = select(EndpointCall).order_by(desc(EndpointCall.called_at)).limit(min(max(limit, 1), 1000))
        if category:
            query = query.where(EndpointCall.category == category)
        rows = session.scalars(query).all()
    return [{"id": row.id, "run_key": row.run_key, "category": row.category, "endpoint": row.endpoint, "called_at": row.called_at, "status": row.status, "duration_ms": row.duration_ms, "summary": row.summary, "response_data": row.response_data} for row in rows]


@app.get("/api/v1/monitoring/events")
async def monitoring_events(request: Request, _: str = Depends(require_admin)) -> StreamingResponse:
    """Notify authenticated browsers only after a monitoring run commits."""
    queue: asyncio.Queue[str] = asyncio.Queue()
    subscription = (asyncio.get_running_loop(), queue)

    async def stream():
        with event_subscribers_lock:
            event_subscribers.add(subscription)
        try:
            yield "retry: 3000\n: connected\n\n"
            while not await request.is_disconnected():
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20)
                    yield f"event: monitoring\ndata: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            with event_subscribers_lock:
                event_subscribers.discard(subscription)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


@app.get("/api/v1/weather/current")
def current_weather(_: str = Depends(require_scope("weather:read"))) -> list[dict[str, Any]]:
    with db() as session:
        rows = session.scalars(select(ProviderReading).order_by(desc(ProviderReading.observed_at)).limit(100)).all()
    seen: set[str] = set()
    result = []
    for row in rows:
        if row.provider in seen:
            continue
        seen.add(row.provider)
        result.append(reading_dict(row))
    return result


@app.get("/api/v1/weather/overview")
def weather_overview(_: str = Depends(require_scope("weather:read"))) -> dict[str, Any]:
    with db() as session:
        latest = session.scalar(select(ProviderReading).order_by(desc(ProviderReading.observed_at)))
        if latest is None:
            return {"available": False, "freshness": "unavailable", "message": "Waiting for the first successful weather check.", "forecast": [], "warnings": [], "source": None}
        readings = session.scalars(select(ProviderReading).where(ProviderReading.run_key == latest.run_key)).all()
        calls = session.scalars(select(EndpointCall).where(EndpointCall.run_key == latest.run_key).order_by(desc(EndpointCall.called_at))).all()
        warnings = session.scalars(select(WarningEvent).where(WarningEvent.run_key == latest.run_key).order_by(desc(WarningEvent.observed_at))).all()
    reading_rows = [reading_dict(row) for row in readings]
    call_rows = [{"endpoint": row.endpoint, "status": row.status, "response_data": row.response_data} for row in calls]
    return build_overview(reading_rows, call_rows, [row.title for row in warnings])


@app.get("/api/v1/weather/history")
def weather_history(provider: str | None = None, limit: int = 500, _: str = Depends(require_scope("weather:read"))) -> list[dict[str, Any]]:
    limit = min(max(limit, 1), 5000)
    with db() as session:
        query = select(ProviderReading).order_by(desc(ProviderReading.observed_at)).limit(limit)
        if provider:
            query = query.where(ProviderReading.provider == provider)
        rows = session.scalars(query).all()
    return [reading_dict(row) for row in rows]


@app.get("/api/v1/weather/providers")
def providers(_: str = Depends(require_scope("weather:read"))) -> list[str]:
    with db() as session:
        return list(session.scalars(select(ProviderReading.provider).distinct().order_by(ProviderReading.provider)).all())


@app.get("/api/v1/alerts")
def alerts(limit: int = 100, _: str = Depends(require_scope("alerts:read"))) -> list[dict[str, Any]]:
    with db() as session:
        rows = session.scalars(select(AlertEvent).order_by(desc(AlertEvent.sent_at)).limit(min(max(limit, 1), 1000))).all()
    return [{"id": row.id, "run_key": row.run_key, "reason": row.reason, "detail": row.detail, "delivery_status": row.delivery_status, "delivery_detail": row.delivery_detail, "next_eligible_at": row.next_eligible_at, "sent_at": row.sent_at} for row in rows]


@app.get("/api/v1/monitoring/runs")
def runs(limit: int = 100, _: str = Depends(require_scope("status:read"))) -> list[dict[str, Any]]:
    with db() as session:
        rows = session.scalars(select(MonitoringRun).order_by(desc(MonitoringRun.observed_at)).limit(min(max(limit, 1), 1000))).all()
    return [{"run_key": row.run_key, "observed_at": row.observed_at, "status": row.status, "decision": row.decision, "error_count": row.error_count} for row in rows]


@app.post("/api/v1/tokens")
def create_token(body: TokenCreateBody, request: Request, username: str = Depends(require_admin)) -> dict[str, Any]:
    allowed = {"weather:read", "alerts:read", "status:read"}
    if not set(body.scopes).issubset(allowed):
        raise HTTPException(status_code=400, detail="Unsupported token scope")
    raw = "wd_" + secrets.token_urlsafe(32)
    token_id = secrets.token_urlsafe(16)
    expires = utcnow() + timedelta(days=body.expires_in_days) if body.expires_in_days else None
    with db() as session:
        session.add(ApiToken(id=token_id, name=body.name, token_hash=token_digest(raw), prefix=raw[:11], scopes=body.scopes, expires_at=expires))
        session.add(AuditEvent(actor=username, action="api_token_created", detail=json.dumps({"token_id": token_id, "name": body.name, "scopes": body.scopes})))
        session.commit()
    return {"id": token_id, "name": body.name, "token": raw, "scopes": body.scopes, "expires_at": expires}


@app.get("/api/v1/tokens")
def list_tokens(username: str = Depends(require_admin)) -> list[dict[str, Any]]:
    with db() as session:
        rows = session.scalars(select(ApiToken).order_by(desc(ApiToken.created_at))).all()
    return [{"id": row.id, "name": row.name, "prefix": row.prefix, "scopes": row.scopes, "created_at": row.created_at, "expires_at": row.expires_at, "revoked_at": row.revoked_at, "last_used_at": row.last_used_at} for row in rows]


@app.post("/api/v1/tokens/{token_id}/revoke")
def revoke_token(token_id: str, username: str = Depends(require_admin)) -> dict[str, str]:
    with db() as session:
        row = session.get(ApiToken, token_id)
        if not row:
            raise HTTPException(status_code=404, detail="Token not found")
        row.revoked_at = utcnow()
        session.add(AuditEvent(actor=username, action="api_token_revoked", detail=token_id))
        session.commit()
    return {"status": "revoked"}


@app.post("/api/v1/shutdown/requests", status_code=202)
def request_shutdown(username: str = Depends(require_admin)) -> dict[str, Any]:
    request_id = "shutdown_" + secrets.token_urlsafe(16)
    deadline = utcnow() + timedelta(seconds=30)
    with db() as session:
        session.add(ShutdownRequest(id=request_id, requested_by=username, cancel_deadline=deadline))
        session.add(AuditEvent(actor=username, action="shutdown_requested", detail=request_id))
        session.commit()
    return {"id": request_id, "status": "pending", "cancel_deadline": deadline, "execution_enabled": SHUTDOWN_ENABLED, "message": "A host-side shutdown helper must process this request; no container has poweroff privileges."}


@app.get("/api/v1/shutdown/requests")
def shutdown_requests(username: str = Depends(require_admin)) -> list[dict[str, Any]]:
    with db() as session:
        rows = session.scalars(select(ShutdownRequest).order_by(desc(ShutdownRequest.requested_at)).limit(100)).all()
    return [{"id": row.id, "requested_by": row.requested_by, "status": row.status, "requested_at": row.requested_at, "cancel_deadline": row.cancel_deadline, "completed_at": row.completed_at, "result": row.result} for row in rows]


@app.post("/api/v1/shutdown/requests/{request_id}/cancel")
def cancel_shutdown(request_id: str, username: str = Depends(require_admin)) -> dict[str, str]:
    with db() as session:
        row = session.get(ShutdownRequest, request_id)
        if not row:
            raise HTTPException(status_code=404, detail="Shutdown request not found")
        if row.status != "pending":
            raise HTTPException(status_code=409, detail="Shutdown request is no longer pending")
        row.status = "cancelled"
        row.completed_at = utcnow()
        row.result = "Cancelled by administrator"
        session.add(AuditEvent(actor=username, action="shutdown_cancelled", detail=request_id))
        session.commit()
    return {"status": "cancelled"}


@app.get("/internal/v1/shutdown/pending")
def pending_shutdowns(x_control_token: str | None = Header(default=None)) -> list[dict[str, Any]]:
    require_internal_token(x_control_token)
    with db() as session:
        rows = session.scalars(select(ShutdownRequest).where(ShutdownRequest.status == "pending").order_by(ShutdownRequest.requested_at).limit(20)).all()
    return [{"id": row.id, "cancel_deadline": row.cancel_deadline, "requested_by": row.requested_by} for row in rows]


@app.post("/internal/v1/shutdown/requests/{request_id}/claim")
def claim_shutdown(request_id: str, x_control_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_internal_token(x_control_token)
    with db() as session:
        row = session.get(ShutdownRequest, request_id)
        if not row or row.status != "pending":
            raise HTTPException(status_code=409, detail="Shutdown request is not pending")
        if row.cancel_deadline > utcnow():
            raise HTTPException(status_code=409, detail="Cancellation window is still open")
        row.status = "executing"
        session.commit()
    return {"id": request_id, "execute": SHUTDOWN_ENABLED}


@app.post("/internal/v1/shutdown/requests/{request_id}/complete")
def complete_shutdown(request_id: str, result: str = "dry_run", x_control_token: str | None = Header(default=None)) -> dict[str, str]:
    require_internal_token(x_control_token)
    with db() as session:
        row = session.get(ShutdownRequest, request_id)
        if not row or row.status != "executing":
            raise HTTPException(status_code=409, detail="Shutdown request is not executing")
        row.status = "completed" if result in {"powered_off", "dry_run"} else "failed"
        row.completed_at = utcnow()
        row.result = result
        session.commit()
    return {"status": "recorded"}


@app.post("/internal/v1/monitoring/ingest", status_code=202)
def ingest(body: IngestBody, x_monitor_token: str | None = Header(default=None)) -> dict[str, str]:
    if not MONITOR_INGEST_TOKEN or not x_monitor_token or not hmac.compare_digest(x_monitor_token, MONITOR_INGEST_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid monitor token")
    with db() as session:
        existing = session.scalar(select(MonitoringRun).where(MonitoringRun.run_key == body.run_key))
        if existing:
            return {"status": "already_ingested"}
        error_count = sum(bool(item.error) for item in body.providers) + sum(item.status != "success" for item in body.endpoint_calls)
        session.add(MonitoringRun(run_key=body.run_key, observed_at=body.observed_at, status="partial_failure" if error_count else "completed", decision=body.decision, error_count=error_count))
        for item in body.providers:
            session.add(ProviderReading(run_key=body.run_key, provider=item.provider, observed_at=item.observed_at, temperature_c=item.temperature_c, precipitation_mm=item.precipitation_mm, precipitation_probability=item.precipitation_probability, wind_speed=item.wind_speed, weather_code=item.weather_code, thunder=item.thunder, error=item.error))
        for item in body.endpoint_calls:
            session.add(EndpointCall(run_key=body.run_key, category=item.category, endpoint=item.endpoint, called_at=item.called_at, status=item.status, duration_ms=item.duration_ms, summary=item.summary, response_data=item.response_data))
        for warning in body.official_warnings:
            session.add(WarningEvent(run_key=body.run_key, source="sri_lanka_official", title=warning, observed_at=body.observed_at))
        if body.alert_reason or body.telegram_status:
            session.add(AlertEvent(run_key=body.run_key, reason=body.alert_reason or "weather alert", detail=body.alert_detail, delivery_status=body.telegram_status or "not_sent", delivery_detail=body.telegram_detail, next_eligible_at=body.next_eligible_at, sent_at=body.observed_at))
        session.commit()
    publish_monitor_event(body.run_key, body.observed_at)
    return {"status": "ingested"}


def reading_dict(row: ProviderReading) -> dict[str, Any]:
    return {"provider": row.provider, "run_key": row.run_key, "observed_at": row.observed_at, "temperature_c": row.temperature_c, "precipitation_mm": row.precipitation_mm, "precipitation_probability": row.precipitation_probability, "wind_speed": row.wind_speed, "weather_code": row.weather_code, "thunder": row.thunder, "error": row.error}

