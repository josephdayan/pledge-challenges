from __future__ import annotations

import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, request, send_from_directory
from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, String, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload, sessionmaker
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "josephdayan").strip().lower()
BRAZIL_TZ = ZoneInfo("America/Sao_Paulo")


def _database_url() -> str:
    raw = os.environ.get("DATABASE_URL", "").strip()
    if raw:
        if raw.startswith("postgres://"):
            return raw.replace("postgres://", "postgresql+psycopg://", 1)
        if raw.startswith("postgresql://"):
            return raw.replace("postgresql://", "postgresql+psycopg://", 1)
        return raw
    return f"sqlite+pysqlite:///{BASE_DIR / 'data.db'}"


DATABASE_URL = _database_url()
ENGINE = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "pc_users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    username: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class AuthSession(Base):
    __tablename__ = "pc_sessions"

    token: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("pc_users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    user: Mapped[User] = relationship()


class Group(Base):
    __tablename__ = "pc_groups"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    owner_id: Mapped[str] = mapped_column(String, ForeignKey("pc_users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    owner: Mapped[User] = relationship()


class GroupMembership(Base):
    __tablename__ = "pc_group_memberships"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    group_id: Mapped[str] = mapped_column(String, ForeignKey("pc_groups.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("pc_users.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    invited_by_id: Mapped[str] = mapped_column(String, ForeignKey("pc_users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    approved_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    group: Mapped[Group] = relationship()
    user: Mapped[User] = relationship(foreign_keys=[user_id])


class Thread(Base):
    __tablename__ = "pc_threads"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    creator_id: Mapped[str] = mapped_column(String, ForeignKey("pc_users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    target_amount: Mapped[float] = mapped_column(Float, nullable=False)
    deadline_at: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    committed_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    committed_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    group_id: Mapped[str] = mapped_column(String, ForeignKey("pc_groups.id", ondelete="SET NULL"), nullable=True)
    audience_mode: Mapped[str] = mapped_column(String, nullable=False, default="open")

    creator: Mapped[User] = relationship()
    group: Mapped[Group] = relationship()
    pledges: Mapped[list["ThreadPledge"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan", order_by="desc(ThreadPledge.created_at)"
    )
    targets: Mapped[list["ThreadTarget"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan"
    )


class ThreadTarget(Base):
    __tablename__ = "pc_thread_targets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    thread_id: Mapped[str] = mapped_column(String, ForeignKey("pc_threads.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("pc_users.id", ondelete="CASCADE"), nullable=False)

    thread: Mapped[Thread] = relationship(back_populates="targets")
    user: Mapped[User] = relationship()


class ThreadPledge(Base):
    __tablename__ = "pc_thread_pledges"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    thread_id: Mapped[str] = mapped_column(String, ForeignKey("pc_threads.id", ondelete="CASCADE"), nullable=False)
    supporter_id: Mapped[str] = mapped_column(String, ForeignKey("pc_users.id", ondelete="CASCADE"), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    thread: Mapped[Thread] = relationship(back_populates="pledges")
    supporter: Mapped[User] = relationship()


class ReverseRequest(Base):
    __tablename__ = "pc_reverse_requests"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    creator_id: Mapped[str] = mapped_column(String, ForeignKey("pc_users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    group_id: Mapped[str] = mapped_column(String, ForeignKey("pc_groups.id", ondelete="SET NULL"), nullable=True)
    audience_mode: Mapped[str] = mapped_column(String, nullable=False, default="open")
    winner_bid_id: Mapped[str] = mapped_column(String, ForeignKey("pc_reverse_bids.id", ondelete="SET NULL"), nullable=True)

    creator: Mapped[User] = relationship()
    group: Mapped[Group] = relationship()
    bids: Mapped[list["ReverseBid"]] = relationship(
        back_populates="request",
        cascade="all, delete-orphan",
        order_by="ReverseBid.ask_amount.asc()",
        foreign_keys="ReverseBid.request_id",
    )
    pledges: Mapped[list["ReversePledge"]] = relationship(
        back_populates="request", cascade="all, delete-orphan", order_by="desc(ReversePledge.created_at)"
    )
    targets: Mapped[list["ReverseTarget"]] = relationship(
        back_populates="request", cascade="all, delete-orphan"
    )


class ReverseTarget(Base):
    __tablename__ = "pc_reverse_targets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(
        String, ForeignKey("pc_reverse_requests.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String, ForeignKey("pc_users.id", ondelete="CASCADE"), nullable=False)

    request: Mapped[ReverseRequest] = relationship(back_populates="targets")
    user: Mapped[User] = relationship()


class ReverseBid(Base):
    __tablename__ = "pc_reverse_bids"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(
        String, ForeignKey("pc_reverse_requests.id", ondelete="CASCADE"), nullable=False
    )
    bidder_id: Mapped[str] = mapped_column(String, ForeignKey("pc_users.id", ondelete="CASCADE"), nullable=False)
    ask_amount: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    request: Mapped[ReverseRequest] = relationship(back_populates="bids", foreign_keys=[request_id])
    bidder: Mapped[User] = relationship()


class ReversePledge(Base):
    __tablename__ = "pc_reverse_pledges"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(
        String, ForeignKey("pc_reverse_requests.id", ondelete="CASCADE"), nullable=False
    )
    supporter_id: Mapped[str] = mapped_column(String, ForeignKey("pc_users.id", ondelete="CASCADE"), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    request: Mapped[ReverseRequest] = relationship(back_populates="pledges")
    supporter: Mapped[User] = relationship()


class DealLock(Base):
    __tablename__ = "pc_deal_locks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    deal_type: Mapped[str] = mapped_column(String, nullable=False)
    deal_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class BalanceEntry(Base):
    __tablename__ = "pc_balance_entries"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    deal_type: Mapped[str] = mapped_column(String, nullable=False)
    deal_id: Mapped[str] = mapped_column(String, nullable=False)
    payer_id: Mapped[str] = mapped_column(String, ForeignKey("pc_users.id", ondelete="CASCADE"), nullable=False)
    payee_id: Mapped[str] = mapped_column(String, ForeignKey("pc_users.id", ondelete="CASCADE"), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    declared_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    payer: Mapped[User] = relationship(foreign_keys=[payer_id])
    payee: Mapped[User] = relationship(foreign_keys=[payee_id])


app = Flask(__name__)


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _token_from_request() -> str:
    auth = request.headers.get("Authorization", "").strip()
    if auth.startswith("Bearer "):
        return auth.removeprefix("Bearer ").strip()
    return ""


def _user_from_token(session, token: str) -> User | None:
    if not token:
        return None
    auth_session = session.get(AuthSession, token)
    return auth_session.user if auth_session else None


def _is_admin(user: User | None) -> bool:
    return bool(user and user.username.lower() == ADMIN_USERNAME)


def _parse_deadline_brasilia(date_str: str, hour_str: str) -> datetime | None:
    try:
        local_dt = datetime.strptime(f"{date_str} {hour_str}", "%Y-%m-%d %H:%M")
        return local_dt.replace(tzinfo=BRAZIL_TZ).astimezone(timezone.utc)
    except ValueError:
        return None


def _thread_status(thread: Thread, pledged_total: float) -> str:
    if thread.committed_current:
        return "committed_current"
    if pledged_total >= thread.target_amount:
        return "funded"
    deadline_ts = datetime.fromisoformat(thread.deadline_at).timestamp()
    return "expired" if time.time() > deadline_ts else "open"


def _is_group_member(session, group_id: str, user_id: str) -> bool:
    row = (
        session.query(GroupMembership)
        .filter(
            GroupMembership.group_id == group_id,
            GroupMembership.user_id == user_id,
            GroupMembership.status == "accepted",
        )
        .first()
    )
    return bool(row)


def _thread_user_allowed(session, thread: Thread, user: User) -> bool:
    if thread.audience_mode == "open":
        return True
    if thread.audience_mode == "group":
        return bool(thread.group_id and _is_group_member(session, thread.group_id, user.id))
    if thread.audience_mode == "specific":
        target_ids = {target.user_id for target in thread.targets}
        return user.id in target_ids
    return False


def _reverse_user_allowed_to_bid(session, req: ReverseRequest, user: User) -> bool:
    if req.audience_mode == "open":
        return True
    if req.audience_mode == "group":
        return bool(req.group_id and _is_group_member(session, req.group_id, user.id))
    if req.audience_mode == "specific":
        target_ids = {target.user_id for target in req.targets}
        return user.id in target_ids
    return False


def _lowest_active_bid(req: ReverseRequest) -> ReverseBid | None:
    active = [bid for bid in req.bids if bid.active]
    if not active:
        return None
    return sorted(active, key=lambda x: (x.ask_amount, x.created_at))[0]


def _deal_locked(session, deal_type: str, deal_id: str) -> bool:
    row = session.query(DealLock).filter(DealLock.deal_type == deal_type, DealLock.deal_id == deal_id).first()
    return bool(row)


def _lock_deal(session, deal_type: str, deal_id: str) -> None:
    session.add(DealLock(id=str(uuid.uuid4()), deal_type=deal_type, deal_id=deal_id, created_at=_now_ms()))


def _create_balance_entries(session, deal_type: str, deal_id: str, payee_id: str, items: list[tuple[str, float]]) -> None:
    for payer_id, amount in items:
        if amount <= 0:
            continue
        session.add(
            BalanceEntry(
                id=str(uuid.uuid4()),
                deal_type=deal_type,
                deal_id=deal_id,
                payer_id=payer_id,
                payee_id=payee_id,
                amount=amount,
                status="open",
                created_at=_now_ms(),
                declared_at=0,
            )
        )


def _try_close_thread_deal(session, thread: Thread) -> None:
    total = sum(float(pledge.amount) for pledge in thread.pledges)
    status = _thread_status(thread, total)
    if status not in {"funded", "committed_current"}:
        return
    if _deal_locked(session, "thread", thread.id):
        return
    items = [(pledge.supporter_id, float(pledge.amount)) for pledge in thread.pledges]
    _create_balance_entries(session, "thread", thread.id, thread.creator_id, items)
    _lock_deal(session, "thread", thread.id)


def _try_close_reverse_deal(session, req: ReverseRequest) -> None:
    if req.status != "open":
        return
    if _deal_locked(session, "reverse", req.id):
        return

    low_bid = _lowest_active_bid(req)
    if not low_bid:
        return

    pledged_total = sum(float(pledge.amount) for pledge in req.pledges)
    if pledged_total < float(low_bid.ask_amount):
        return

    req.status = "closed"
    req.winner_bid_id = low_bid.id

    items = [(pledge.supporter_id, float(pledge.amount)) for pledge in req.pledges]
    _create_balance_entries(session, "reverse", req.id, low_bid.bidder_id, items)
    _lock_deal(session, "reverse", req.id)


def _serialize_group(group: Group, memberships: list[GroupMembership], viewer: User) -> dict:
    accepted = [m.user.username for m in memberships if m.status == "accepted"]
    pending = [{"membershipId": m.id, "username": m.user.username} for m in memberships if m.status == "pending"]
    return {
        "id": group.id,
        "name": group.name,
        "ownerUsername": group.owner.username,
        "members": sorted(accepted),
        "pending": pending,
        "isOwner": group.owner_id == viewer.id,
    }


def _serialize_thread(thread: Thread, viewer: User | None) -> dict:
    pledges = [
        {
            "supporterUsername": pledge.supporter.username,
            "amount": float(pledge.amount),
            "createdAt": int(pledge.created_at),
        }
        for pledge in thread.pledges
    ]
    pledged_total = sum(x["amount"] for x in pledges)
    status = _thread_status(thread, pledged_total)
    can_delete = bool(viewer and (viewer.id == thread.creator_id or _is_admin(viewer)))
    can_commit_current = bool(
        viewer
        and viewer.id == thread.creator_id
        and not thread.committed_current
        and pledged_total > 0
        and pledged_total < float(thread.target_amount)
        and status in {"open", "expired"}
    )

    return {
        "id": thread.id,
        "creatorUsername": thread.creator.username,
        "title": thread.title,
        "description": thread.description,
        "targetAmount": float(thread.target_amount),
        "deadlineAt": thread.deadline_at,
        "createdAt": int(thread.created_at),
        "status": status,
        "pledgedTotal": pledged_total,
        "pledges": pledges,
        "committedAmount": float(thread.committed_amount),
        "canDelete": can_delete,
        "canCommitCurrent": can_commit_current,
        "audienceMode": thread.audience_mode,
        "groupName": thread.group.name if thread.group else None,
        "targets": sorted([target.user.username for target in thread.targets]),
    }


def _serialize_reverse(req: ReverseRequest) -> dict:
    pledges = [
        {
            "supporterUsername": pledge.supporter.username,
            "amount": float(pledge.amount),
            "createdAt": int(pledge.created_at),
        }
        for pledge in req.pledges
    ]
    bids = [
        {
            "bidderUsername": bid.bidder.username,
            "askAmount": float(bid.ask_amount),
            "active": bool(bid.active),
            "createdAt": int(bid.created_at),
        }
        for bid in req.bids
        if bid.active
    ]
    low = _lowest_active_bid(req)

    return {
        "id": req.id,
        "creatorUsername": req.creator.username,
        "title": req.title,
        "description": req.description,
        "status": req.status,
        "createdAt": int(req.created_at),
        "pledges": pledges,
        "pledgedTotal": sum(x["amount"] for x in pledges),
        "bids": sorted(bids, key=lambda x: x["askAmount"]),
        "lowestBid": (
            {"bidderUsername": low.bidder.username, "askAmount": float(low.ask_amount)} if low else None
        ),
        "audienceMode": req.audience_mode,
        "groupName": req.group.name if req.group else None,
        "targets": sorted([target.user.username for target in req.targets]),
        "canBid": False,
    }


# Helper for serialize_reverse without introducing global state.
def _serialize_reverse_with_perm(session, req: ReverseRequest, viewer: User | None) -> dict:
    payload = _serialize_reverse(req)
    payload["canBid"] = bool(viewer and req.status == "open" and _reverse_user_allowed_to_bid(session, req, viewer))
    return payload


def init_db() -> None:
    Base.metadata.create_all(ENGINE)
    _migrate_legacy_columns()


def _migrate_legacy_columns() -> None:
    inspector = inspect(ENGINE)
    tables = set(inspector.get_table_names())
    if "pc_threads" not in tables:
        return

    existing = {col["name"] for col in inspector.get_columns("pc_threads")}
    statements: list[str] = []

    if "group_id" not in existing:
        statements.append("ALTER TABLE pc_threads ADD COLUMN group_id VARCHAR")
    if "audience_mode" not in existing:
        statements.append("ALTER TABLE pc_threads ADD COLUMN audience_mode VARCHAR NOT NULL DEFAULT 'open'")

    if not statements:
        return

    with ENGINE.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))


@app.get("/")
def root() -> object:
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/styles.css")
def styles() -> object:
    return send_from_directory(BASE_DIR, "styles.css")


@app.get("/app.js")
def frontend_script() -> object:
    return send_from_directory(BASE_DIR, "app.js")


@app.post("/api/auth/register")
def register() -> object:
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip().lower()
    password = str(payload.get("password", "")).strip()

    if len(username) < 3 or len(password) < 6:
        return jsonify({"error": "Username minimo 3 chars e senha minima 6 chars."}), 400

    with session_scope() as session:
        exists = session.query(User).filter(User.username == username).first()
        if exists:
            return jsonify({"error": "Username ja existe."}), 409

        user = User(
            id=str(uuid.uuid4()), username=username, password_hash=generate_password_hash(password), created_at=_now_ms()
        )
        session.add(user)
        session.flush()

        token = str(uuid.uuid4())
        session.add(AuthSession(token=token, user_id=user.id, created_at=_now_ms()))

        return jsonify({"ok": True, "token": token, "user": {"username": user.username}}), 201


@app.post("/api/auth/login")
def login() -> object:
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip().lower()
    password = str(payload.get("password", "")).strip()

    with session_scope() as session:
        user = session.query(User).filter(User.username == username).first()
        if not user or not check_password_hash(user.password_hash, password):
            return jsonify({"error": "Credenciais invalidas."}), 401

        token = str(uuid.uuid4())
        session.add(AuthSession(token=token, user_id=user.id, created_at=_now_ms()))

        return jsonify({"ok": True, "token": token, "user": {"username": user.username}})


@app.post("/api/auth/logout")
def logout() -> object:
    token = _token_from_request()
    if not token:
        return jsonify({"ok": True})

    with session_scope() as session:
        auth_session = session.get(AuthSession, token)
        if auth_session:
            session.delete(auth_session)

    return jsonify({"ok": True})


@app.get("/api/auth/me")
def me() -> object:
    token = _token_from_request()
    with session_scope() as session:
        user = _user_from_token(session, token)
        if not user:
            return jsonify({"user": None})
        return jsonify({"user": {"username": user.username, "isAdmin": _is_admin(user)}})


@app.get("/api/users")
def list_users() -> object:
    token = _token_from_request()
    with session_scope() as session:
        user = _user_from_token(session, token)
        if not user:
            return jsonify({"error": "Login necessario."}), 401
        users = session.query(User).order_by(User.username.asc()).all()
        return jsonify({"users": [u.username for u in users]})


@app.post("/api/groups")
def create_group() -> object:
    token = _token_from_request()
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    invited_usernames = payload.get("invitedUsernames", []) or []

    if not name:
        return jsonify({"error": "Nome do grupo e obrigatorio."}), 400

    with session_scope() as session:
        owner = _user_from_token(session, token)
        if not owner:
            return jsonify({"error": "Login necessario."}), 401

        group = Group(id=str(uuid.uuid4()), name=name, owner_id=owner.id, created_at=_now_ms())
        session.add(group)
        session.flush()

        session.add(
            GroupMembership(
                id=str(uuid.uuid4()),
                group_id=group.id,
                user_id=owner.id,
                status="accepted",
                invited_by_id=owner.id,
                created_at=_now_ms(),
                approved_at=_now_ms(),
            )
        )

        for username in sorted({str(x).strip().lower() for x in invited_usernames if str(x).strip()}):
            invited = session.query(User).filter(User.username == username).first()
            if not invited or invited.id == owner.id:
                continue
            exists = (
                session.query(GroupMembership)
                .filter(GroupMembership.group_id == group.id, GroupMembership.user_id == invited.id)
                .first()
            )
            if exists:
                continue
            session.add(
                GroupMembership(
                    id=str(uuid.uuid4()),
                    group_id=group.id,
                    user_id=invited.id,
                    status="pending",
                    invited_by_id=owner.id,
                    created_at=_now_ms(),
                    approved_at=0,
                )
            )

    return jsonify({"ok": True}), 201


@app.post("/api/groups/<group_id>/invite")
def invite_to_group(group_id: str) -> object:
    token = _token_from_request()
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip().lower()

    if not username:
        return jsonify({"error": "Username obrigatorio."}), 400

    with session_scope() as session:
        owner = _user_from_token(session, token)
        if not owner:
            return jsonify({"error": "Login necessario."}), 401

        group = session.get(Group, group_id)
        if not group:
            return jsonify({"error": "Grupo nao encontrado."}), 404
        if group.owner_id != owner.id:
            return jsonify({"error": "So o dono do grupo pode convidar."}), 403

        invited = session.query(User).filter(User.username == username).first()
        if not invited:
            return jsonify({"error": "Usuario nao existe."}), 404

        exists = (
            session.query(GroupMembership)
            .filter(GroupMembership.group_id == group.id, GroupMembership.user_id == invited.id)
            .first()
        )
        if exists:
            return jsonify({"error": "Usuario ja esta no grupo ou pendente."}), 409

        session.add(
            GroupMembership(
                id=str(uuid.uuid4()),
                group_id=group.id,
                user_id=invited.id,
                status="pending",
                invited_by_id=owner.id,
                created_at=_now_ms(),
                approved_at=0,
            )
        )

    return jsonify({"ok": True}), 201


@app.post("/api/groups/<group_id>/approve")
def approve_group_member(group_id: str) -> object:
    token = _token_from_request()
    payload = request.get_json(silent=True) or {}
    membership_id = str(payload.get("membershipId", "")).strip()

    with session_scope() as session:
        owner = _user_from_token(session, token)
        if not owner:
            return jsonify({"error": "Login necessario."}), 401

        group = session.get(Group, group_id)
        if not group:
            return jsonify({"error": "Grupo nao encontrado."}), 404
        if group.owner_id != owner.id:
            return jsonify({"error": "So o dono do grupo pode aprovar."}), 403

        member = session.get(GroupMembership, membership_id)
        if not member or member.group_id != group.id:
            return jsonify({"error": "Convite nao encontrado."}), 404

        member.status = "accepted"
        member.approved_at = _now_ms()

    return jsonify({"ok": True})


@app.get("/api/groups")
def list_groups() -> object:
    token = _token_from_request()

    with session_scope() as session:
        viewer = _user_from_token(session, token)
        if not viewer:
            return jsonify({"error": "Login necessario."}), 401

        memberships = (
            session.query(GroupMembership)
            .options(selectinload(GroupMembership.group).selectinload(Group.owner), selectinload(GroupMembership.user))
            .filter(GroupMembership.user_id == viewer.id)
            .all()
        )

        group_ids = {m.group_id for m in memberships}
        if not group_ids:
            return jsonify({"groups": []})

        all_memberships = (
            session.query(GroupMembership)
            .options(selectinload(GroupMembership.user), selectinload(GroupMembership.group).selectinload(Group.owner))
            .filter(GroupMembership.group_id.in_(group_ids))
            .all()
        )

        by_group: dict[str, list[GroupMembership]] = {}
        for row in all_memberships:
            by_group.setdefault(row.group_id, []).append(row)

        groups: list[dict] = []
        seen: set[str] = set()
        for row in all_memberships:
            group = row.group
            if not group or group.id in seen:
                continue
            seen.add(group.id)
            groups.append(_serialize_group(group, by_group.get(group.id, []), viewer))

        groups.sort(key=lambda x: x["name"].lower())
        return jsonify({"groups": groups})


@app.get("/api/threads")
def get_threads() -> object:
    token = _token_from_request()

    with session_scope() as session:
        viewer = _user_from_token(session, token)
        threads = (
            session.query(Thread)
            .options(
                selectinload(Thread.creator),
                selectinload(Thread.group),
                selectinload(Thread.targets).selectinload(ThreadTarget.user),
                selectinload(Thread.pledges).selectinload(ThreadPledge.supporter),
            )
            .order_by(Thread.created_at.desc())
            .all()
        )
        return jsonify({"threads": [_serialize_thread(t, viewer) for t in threads]})


@app.post("/api/threads")
def create_thread() -> object:
    token = _token_from_request()
    payload = request.get_json(silent=True) or {}

    title = str(payload.get("title", "")).strip()
    description = str(payload.get("description", "")).strip()
    deadline_date = str(payload.get("deadlineDate", "")).strip()
    deadline_hour = str(payload.get("deadlineHour", "")).strip()
    audience_mode = str(payload.get("audienceMode", "open")).strip().lower()
    group_id = str(payload.get("groupId", "")).strip() or None
    target_usernames = payload.get("targetUsernames", []) or []

    try:
        target_amount = float(payload.get("targetAmount", 0))
    except (TypeError, ValueError):
        target_amount = 0

    deadline = _parse_deadline_brasilia(deadline_date, deadline_hour)
    if not title or not description or target_amount < 1 or not deadline:
        return jsonify({"error": "Dados invalidos para criar thread."}), 400

    if audience_mode not in {"open", "group", "specific"}:
        return jsonify({"error": "Audience invalido."}), 400

    with session_scope() as session:
        creator = _user_from_token(session, token)
        if not creator:
            return jsonify({"error": "Login necessario."}), 401

        group = None
        if audience_mode in {"group", "specific"}:
            if not group_id:
                return jsonify({"error": "Selecione um grupo."}), 400
            group = session.get(Group, group_id)
            if not group:
                return jsonify({"error": "Grupo nao encontrado."}), 404
            if not _is_group_member(session, group.id, creator.id):
                return jsonify({"error": "Voce nao faz parte desse grupo."}), 403

        thread = Thread(
            id=str(uuid.uuid4()),
            creator_id=creator.id,
            title=title,
            description=description,
            target_amount=target_amount,
            deadline_at=deadline.isoformat(),
            created_at=_now_ms(),
            committed_current=False,
            committed_amount=0,
            group_id=group.id if group else None,
            audience_mode=audience_mode,
        )
        session.add(thread)
        session.flush()

        if audience_mode == "specific":
            usernames = sorted({str(x).strip().lower() for x in target_usernames if str(x).strip()})
            if not usernames:
                return jsonify({"error": "Escolha ao menos um usuario alvo."}), 400

            for username in usernames:
                user = session.query(User).filter(User.username == username).first()
                if not user:
                    continue
                if not _is_group_member(session, group.id, user.id):
                    continue
                session.add(ThreadTarget(id=str(uuid.uuid4()), thread_id=thread.id, user_id=user.id))

    return jsonify({"ok": True}), 201


@app.post("/api/threads/<thread_id>/pledges")
def create_thread_pledge(thread_id: str) -> object:
    token = _token_from_request()
    payload = request.get_json(silent=True) or {}

    try:
        amount = float(payload.get("amount", 0))
    except (TypeError, ValueError):
        amount = 0

    if amount < 1:
        return jsonify({"error": "Valor invalido."}), 400

    with session_scope() as session:
        user = _user_from_token(session, token)
        if not user:
            return jsonify({"error": "Login necessario."}), 401

        thread = (
            session.query(Thread)
            .options(selectinload(Thread.pledges), selectinload(Thread.targets))
            .filter(Thread.id == thread_id)
            .first()
        )
        if not thread:
            return jsonify({"error": "Thread nao encontrada."}), 404

        if not _thread_user_allowed(session, thread, user):
            return jsonify({"error": "Voce nao pode participar dessa thread."}), 403

        pledged_total = sum(float(p.amount) for p in thread.pledges)
        if _thread_status(thread, pledged_total) != "open":
            return jsonify({"error": "Esta thread nao aceita novos pledges."}), 400

        remaining = float(thread.target_amount) - pledged_total
        if remaining <= 0:
            return jsonify({"error": "Meta ja atingida."}), 400
        if amount > remaining:
            return jsonify({"error": f"Valor maximo restante: {remaining:.2f}"}), 400

        session.add(
            ThreadPledge(
                id=str(uuid.uuid4()),
                thread_id=thread.id,
                supporter_id=user.id,
                amount=amount,
                created_at=_now_ms(),
            )
        )
        session.flush()
        session.refresh(thread)
        _try_close_thread_deal(session, thread)

    return jsonify({"ok": True}), 201


@app.post("/api/threads/<thread_id>/commit-current")
def commit_current(thread_id: str) -> object:
    token = _token_from_request()

    with session_scope() as session:
        user = _user_from_token(session, token)
        if not user:
            return jsonify({"error": "Login necessario."}), 401

        thread = session.query(Thread).options(selectinload(Thread.pledges)).filter(Thread.id == thread_id).first()
        if not thread:
            return jsonify({"error": "Thread nao encontrada."}), 404
        if thread.creator_id != user.id:
            return jsonify({"error": "Somente o dono da thread pode usar esse commit."}), 403

        pledged_total = sum(float(p.amount) for p in thread.pledges)
        if pledged_total <= 0 or pledged_total >= float(thread.target_amount):
            return jsonify({"error": "Commit atual so vale para valor parcial > 0 e abaixo da meta."}), 400
        if thread.committed_current:
            return jsonify({"error": "Thread ja committed."}), 400

        thread.committed_current = True
        thread.committed_amount = pledged_total
        _try_close_thread_deal(session, thread)

    return jsonify({"ok": True})


@app.delete("/api/threads/<thread_id>")
def delete_thread(thread_id: str) -> object:
    token = _token_from_request()

    with session_scope() as session:
        user = _user_from_token(session, token)
        if not user:
            return jsonify({"error": "Login necessario."}), 401

        thread = session.get(Thread, thread_id)
        if not thread:
            return jsonify({"error": "Thread nao encontrada."}), 404
        if not (thread.creator_id == user.id or _is_admin(user)):
            return jsonify({"error": "Sem permissao para apagar thread."}), 403

        session.delete(thread)

    return jsonify({"ok": True})


@app.get("/api/reverse")
def list_reverse() -> object:
    token = _token_from_request()

    with session_scope() as session:
        viewer = _user_from_token(session, token)
        rows = (
            session.query(ReverseRequest)
            .options(
                selectinload(ReverseRequest.creator),
                selectinload(ReverseRequest.group),
                selectinload(ReverseRequest.targets).selectinload(ReverseTarget.user),
                selectinload(ReverseRequest.bids).selectinload(ReverseBid.bidder),
                selectinload(ReverseRequest.pledges).selectinload(ReversePledge.supporter),
            )
            .order_by(ReverseRequest.created_at.desc())
            .all()
        )

        return jsonify({"requests": [_serialize_reverse_with_perm(session, row, viewer) for row in rows]})


@app.post("/api/reverse")
def create_reverse() -> object:
    token = _token_from_request()
    payload = request.get_json(silent=True) or {}

    title = str(payload.get("title", "")).strip()
    description = str(payload.get("description", "")).strip()
    audience_mode = str(payload.get("audienceMode", "group")).strip().lower()
    group_id = str(payload.get("groupId", "")).strip() or None
    target_usernames = payload.get("targetUsernames", []) or []

    try:
        seed_amount = float(payload.get("seedAmount", 0))
    except (TypeError, ValueError):
        seed_amount = 0

    if not title or not description:
        return jsonify({"error": "Titulo e descricao sao obrigatorios."}), 400
    if audience_mode not in {"open", "group", "specific"}:
        return jsonify({"error": "Audience invalido."}), 400
    if seed_amount < 0:
        return jsonify({"error": "Seed invalido."}), 400

    with session_scope() as session:
        creator = _user_from_token(session, token)
        if not creator:
            return jsonify({"error": "Login necessario."}), 401

        group = None
        if audience_mode in {"group", "specific"}:
            if not group_id:
                return jsonify({"error": "Selecione um grupo."}), 400
            group = session.get(Group, group_id)
            if not group:
                return jsonify({"error": "Grupo nao encontrado."}), 404
            if not _is_group_member(session, group.id, creator.id):
                return jsonify({"error": "Voce nao faz parte desse grupo."}), 403

        req = ReverseRequest(
            id=str(uuid.uuid4()),
            creator_id=creator.id,
            title=title,
            description=description,
            created_at=_now_ms(),
            status="open",
            group_id=group.id if group else None,
            audience_mode=audience_mode,
            winner_bid_id=None,
        )
        session.add(req)
        session.flush()

        if audience_mode == "specific":
            usernames = sorted({str(x).strip().lower() for x in target_usernames if str(x).strip()})
            if not usernames:
                return jsonify({"error": "Escolha ao menos um usuario alvo."}), 400

            for username in usernames:
                user = session.query(User).filter(User.username == username).first()
                if not user:
                    continue
                if group and not _is_group_member(session, group.id, user.id):
                    continue
                session.add(ReverseTarget(id=str(uuid.uuid4()), request_id=req.id, user_id=user.id))

        if seed_amount > 0:
            session.add(
                ReversePledge(
                    id=str(uuid.uuid4()),
                    request_id=req.id,
                    supporter_id=creator.id,
                    amount=seed_amount,
                    created_at=_now_ms(),
                )
            )

    return jsonify({"ok": True}), 201


@app.post("/api/reverse/<request_id>/bids")
def create_or_update_bid(request_id: str) -> object:
    token = _token_from_request()
    payload = request.get_json(silent=True) or {}

    try:
        ask_amount = float(payload.get("askAmount", 0))
    except (TypeError, ValueError):
        ask_amount = 0

    if ask_amount < 1:
        return jsonify({"error": "Valor da oferta invalido."}), 400

    with session_scope() as session:
        user = _user_from_token(session, token)
        if not user:
            return jsonify({"error": "Login necessario."}), 401

        req = (
            session.query(ReverseRequest)
            .options(selectinload(ReverseRequest.targets), selectinload(ReverseRequest.bids), selectinload(ReverseRequest.pledges))
            .filter(ReverseRequest.id == request_id)
            .first()
        )
        if not req:
            return jsonify({"error": "Pedido nao encontrado."}), 404
        if req.status != "open":
            return jsonify({"error": "Pedido ja encerrado."}), 400
        if not _reverse_user_allowed_to_bid(session, req, user):
            return jsonify({"error": "Voce nao pode dar lance nesse pedido."}), 403

        own_bid = (
            session.query(ReverseBid)
            .filter(ReverseBid.request_id == req.id, ReverseBid.bidder_id == user.id, ReverseBid.active.is_(True))
            .first()
        )
        if own_bid:
            own_bid.ask_amount = ask_amount
            own_bid.created_at = _now_ms()
        else:
            session.add(
                ReverseBid(
                    id=str(uuid.uuid4()),
                    request_id=req.id,
                    bidder_id=user.id,
                    ask_amount=ask_amount,
                    created_at=_now_ms(),
                    active=True,
                )
            )

        session.flush()
        session.refresh(req)
        _try_close_reverse_deal(session, req)

    return jsonify({"ok": True}), 201


@app.post("/api/reverse/<request_id>/pledges")
def create_reverse_pledge(request_id: str) -> object:
    token = _token_from_request()
    payload = request.get_json(silent=True) or {}

    try:
        amount = float(payload.get("amount", 0))
    except (TypeError, ValueError):
        amount = 0

    if amount < 1:
        return jsonify({"error": "Valor invalido."}), 400

    with session_scope() as session:
        user = _user_from_token(session, token)
        if not user:
            return jsonify({"error": "Login necessario."}), 401

        req = (
            session.query(ReverseRequest)
            .options(selectinload(ReverseRequest.bids), selectinload(ReverseRequest.pledges), selectinload(ReverseRequest.targets))
            .filter(ReverseRequest.id == request_id)
            .first()
        )
        if not req:
            return jsonify({"error": "Pedido nao encontrado."}), 404
        if req.status != "open":
            return jsonify({"error": "Pedido ja encerrado."}), 400

        low = _lowest_active_bid(req)
        current_total = sum(float(p.amount) for p in req.pledges)
        if low:
            remaining = float(low.ask_amount) - current_total
            if remaining <= 0:
                return jsonify({"error": "Meta atual ja batida."}), 400
            if amount > remaining:
                return jsonify({"error": f"Valor maximo restante para fechar: {remaining:.2f}"}), 400

        session.add(
            ReversePledge(
                id=str(uuid.uuid4()),
                request_id=req.id,
                supporter_id=user.id,
                amount=amount,
                created_at=_now_ms(),
            )
        )
        session.flush()
        session.refresh(req)
        _try_close_reverse_deal(session, req)

    return jsonify({"ok": True}), 201


@app.get("/api/balance")
def my_balance() -> object:
    token = _token_from_request()

    with session_scope() as session:
        user = _user_from_token(session, token)
        if not user:
            return jsonify({"error": "Login necessario."}), 401

        rows = (
            session.query(BalanceEntry)
            .options(selectinload(BalanceEntry.payer), selectinload(BalanceEntry.payee))
            .filter((BalanceEntry.payer_id == user.id) | (BalanceEntry.payee_id == user.id))
            .order_by(BalanceEntry.created_at.desc())
            .all()
        )

        entries = [
            {
                "id": row.id,
                "dealType": row.deal_type,
                "dealId": row.deal_id,
                "payerUsername": row.payer.username,
                "payeeUsername": row.payee.username,
                "amount": float(row.amount),
                "status": row.status,
                "createdAt": int(row.created_at),
                "canDeclareReceived": row.payee_id == user.id and row.status == "open",
            }
            for row in rows
        ]

        owes = sum(float(row.amount) for row in rows if row.payer_id == user.id and row.status == "open")
        to_receive = sum(float(row.amount) for row in rows if row.payee_id == user.id and row.status == "open")

        return jsonify({"owes": owes, "toReceive": to_receive, "entries": entries})


@app.post("/api/balance/<entry_id>/declare-received")
def declare_received(entry_id: str) -> object:
    token = _token_from_request()

    with session_scope() as session:
        user = _user_from_token(session, token)
        if not user:
            return jsonify({"error": "Login necessario."}), 401

        entry = session.get(BalanceEntry, entry_id)
        if not entry:
            return jsonify({"error": "Saldo nao encontrado."}), 404
        if entry.payee_id != user.id:
            return jsonify({"error": "Somente quem recebe pode declarar recebido."}), 403
        if entry.status != "open":
            return jsonify({"error": "Este item ja foi encerrado."}), 400

        entry.status = "received_declared"
        entry.declared_at = _now_ms()

    return jsonify({"ok": True})


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "4173"))
    app.run(host="0.0.0.0", port=port)
