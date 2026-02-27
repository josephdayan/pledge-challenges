from __future__ import annotations

import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload, sessionmaker
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "josephdayan").strip().lower()


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

    creator: Mapped[User] = relationship()
    pledges: Mapped[list["Pledge"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan", order_by="desc(Pledge.created_at)"
    )


class Pledge(Base):
    __tablename__ = "pc_pledges"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    thread_id: Mapped[str] = mapped_column(String, ForeignKey("pc_threads.id", ondelete="CASCADE"), nullable=False)
    supporter_id: Mapped[str] = mapped_column(String, ForeignKey("pc_users.id", ondelete="CASCADE"), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    thread: Mapped[Thread] = relationship(back_populates="pledges")
    supporter: Mapped[User] = relationship()


class Challenge(Base):
    __tablename__ = "pc_challenges"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    challenger_id: Mapped[str] = mapped_column(String, ForeignKey("pc_users.id", ondelete="CASCADE"), nullable=False)
    challenged_id: Mapped[str] = mapped_column(String, ForeignKey("pc_users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    offered_amount: Mapped[float] = mapped_column(Float, nullable=False)
    counter_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    agreed_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    challenger: Mapped[User] = relationship(foreign_keys=[challenger_id])
    challenged: Mapped[User] = relationship(foreign_keys=[challenged_id])


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


def _status(thread: Thread, pledged_total: float) -> str:
    if thread.committed_current:
        return "committed_current"
    if pledged_total >= thread.target_amount:
        return "funded"

    deadline_raw = thread.deadline_at.replace("Z", "+00:00")
    deadline_ts = datetime.fromisoformat(deadline_raw).timestamp()
    if time.time() > deadline_ts:
        return "expired"

    return "open"


def _parse_deadline(date_str: str, hour_str: str) -> datetime | None:
    try:
        return datetime.strptime(f"{date_str} {hour_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None


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
    if not auth_session:
        return None
    return auth_session.user


def _is_admin(user: User | None) -> bool:
    return bool(user and user.username.lower() == ADMIN_USERNAME)


def _serialize_thread(thread: Thread, viewer: User | None) -> dict:
    pledges = [
        {
            "supporterUsername": pledge.supporter.username,
            "amount": float(pledge.amount),
            "createdAt": int(pledge.created_at),
        }
        for pledge in thread.pledges
    ]

    pledged_total = sum(pledge["amount"] for pledge in pledges)
    status = _status(thread, pledged_total)
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
        "pledges": pledges,
        "pledgedTotal": pledged_total,
        "status": status,
        "committedAmount": float(thread.committed_amount),
        "canDelete": can_delete,
        "canCommitCurrent": can_commit_current,
    }


def _serialize_challenge(challenge: Challenge, viewer: User) -> dict:
    return {
        "id": challenge.id,
        "challengerUsername": challenge.challenger.username,
        "challengedUsername": challenge.challenged.username,
        "title": challenge.title,
        "description": challenge.description,
        "offeredAmount": float(challenge.offered_amount),
        "counterAmount": float(challenge.counter_amount),
        "agreedAmount": float(challenge.agreed_amount),
        "status": challenge.status,
        "createdAt": int(challenge.created_at),
        "updatedAt": int(challenge.updated_at),
        "canRespond": challenge.challenged_id == viewer.id and challenge.status in {"pending", "countered"},
        "canAcceptCounter": challenge.challenger_id == viewer.id and challenge.status == "countered",
    }


def _create_thread_from_challenge(session, challenge: Challenge, agreed_amount: float) -> None:
    now = datetime.utcnow()
    thread = Thread(
        id=str(uuid.uuid4()),
        creator_id=challenge.challenged_id,
        title=f"Desafio: {challenge.title}",
        description=challenge.description,
        target_amount=agreed_amount,
        deadline_at=(now + timedelta(days=7)).replace(second=0, microsecond=0).isoformat(),
        created_at=_now_ms(),
        committed_current=False,
        committed_amount=0,
    )
    session.add(thread)
    session.flush()

    session.add(
        Pledge(
            id=str(uuid.uuid4()),
            thread_id=thread.id,
            supporter_id=challenge.challenger_id,
            amount=agreed_amount,
            created_at=_now_ms(),
        )
    )


def init_db() -> None:
    Base.metadata.create_all(ENGINE)


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
            id=str(uuid.uuid4()),
            username=username,
            password_hash=generate_password_hash(password),
            created_at=_now_ms(),
        )
        session.add(user)

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


@app.get("/api/threads")
def get_threads() -> object:
    token = _token_from_request()
    with session_scope() as session:
        viewer = _user_from_token(session, token)
        threads = (
            session.query(Thread)
            .options(
                selectinload(Thread.creator),
                selectinload(Thread.pledges).selectinload(Pledge.supporter),
            )
            .order_by(Thread.created_at.desc())
            .all()
        )
        payload = [_serialize_thread(thread, viewer) for thread in threads]
    return jsonify({"threads": payload})


@app.post("/api/threads")
def create_thread() -> object:
    token = _token_from_request()
    payload = request.get_json(silent=True) or {}

    deadline_at_raw = str(payload.get("deadlineAt", "")).strip()
    title = str(payload.get("title", "")).strip()
    description = str(payload.get("description", "")).strip()
    deadline_date = str(payload.get("deadlineDate", "")).strip()
    deadline_hour = str(payload.get("deadlineHour", "")).strip()

    try:
        target_amount = float(payload.get("targetAmount", 0))
    except (TypeError, ValueError):
        target_amount = 0

    deadline: datetime | None = None
    if deadline_at_raw:
        try:
            parsed = datetime.fromisoformat(deadline_at_raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            deadline = parsed.astimezone(timezone.utc)
        except ValueError:
            deadline = None
    else:
        parsed_local = _parse_deadline(deadline_date, deadline_hour)
        if parsed_local:
            deadline = parsed_local.replace(tzinfo=timezone.utc)

    if not title or not description or target_amount < 1 or not deadline:
        return jsonify({"error": "Dados invalidos para criar thread."}), 400

    with session_scope() as session:
        user = _user_from_token(session, token)
        if not user:
            return jsonify({"error": "Login necessario."}), 401

        thread = Thread(
            id=str(uuid.uuid4()),
            creator_id=user.id,
            title=title,
            description=description,
            target_amount=target_amount,
            deadline_at=deadline.isoformat(),
            created_at=_now_ms(),
            committed_current=False,
            committed_amount=0,
        )
        session.add(thread)

        return jsonify({"ok": True, "id": thread.id}), 201


@app.post("/api/threads/<thread_id>/pledges")
def create_pledge(thread_id: str) -> object:
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
            .options(selectinload(Thread.pledges))
            .filter(Thread.id == thread_id)
            .first()
        )
        if not thread:
            return jsonify({"error": "Thread nao encontrada."}), 404

        pledged_total = sum(float(pledge.amount) for pledge in thread.pledges)
        if _status(thread, pledged_total) != "open":
            return jsonify({"error": "Esta thread nao aceita novos pledges."}), 400

        pledge = Pledge(
            id=str(uuid.uuid4()),
            thread_id=thread.id,
            supporter_id=user.id,
            amount=amount,
            created_at=_now_ms(),
        )
        session.add(pledge)

    return jsonify({"ok": True}), 201


@app.post("/api/threads/<thread_id>/commit-current")
def commit_current(thread_id: str) -> object:
    token = _token_from_request()

    with session_scope() as session:
        user = _user_from_token(session, token)
        if not user:
            return jsonify({"error": "Login necessario."}), 401

        thread = (
            session.query(Thread)
            .options(selectinload(Thread.pledges))
            .filter(Thread.id == thread_id)
            .first()
        )
        if not thread:
            return jsonify({"error": "Thread nao encontrada."}), 404
        if thread.creator_id != user.id:
            return jsonify({"error": "Somente o dono da thread pode usar esse commit."}), 403

        pledged_total = sum(float(pledge.amount) for pledge in thread.pledges)
        if pledged_total <= 0 or pledged_total >= float(thread.target_amount):
            return jsonify({"error": "Commit atual so vale para valor parcial > 0 e abaixo da meta."}), 400
        if thread.committed_current:
            return jsonify({"error": "Thread ja foi committed no valor atual."}), 400

        thread.committed_current = True
        thread.committed_amount = pledged_total

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


@app.get("/api/challenges")
def get_challenges() -> object:
    token = _token_from_request()

    with session_scope() as session:
        user = _user_from_token(session, token)
        if not user:
            return jsonify({"error": "Login necessario."}), 401

        items = (
            session.query(Challenge)
            .options(selectinload(Challenge.challenger), selectinload(Challenge.challenged))
            .filter((Challenge.challenger_id == user.id) | (Challenge.challenged_id == user.id))
            .order_by(Challenge.updated_at.desc())
            .all()
        )
        payload = [_serialize_challenge(item, user) for item in items]

    return jsonify({"challenges": payload})


@app.post("/api/challenges")
def create_challenge() -> object:
    token = _token_from_request()
    payload = request.get_json(silent=True) or {}

    challenged_username = str(payload.get("challengedUsername", "")).strip().lower()
    title = str(payload.get("title", "")).strip()
    description = str(payload.get("description", "")).strip()

    try:
        offered_amount = float(payload.get("offeredAmount", 0))
    except (TypeError, ValueError):
        offered_amount = 0

    if not challenged_username or not title or not description or offered_amount < 1:
        return jsonify({"error": "Dados invalidos para desafio."}), 400

    with session_scope() as session:
        user = _user_from_token(session, token)
        if not user:
            return jsonify({"error": "Login necessario."}), 401

        challenged = session.query(User).filter(User.username == challenged_username).first()
        if not challenged:
            return jsonify({"error": "Usuario desafiado nao existe."}), 404
        if challenged.id == user.id:
            return jsonify({"error": "Voce nao pode desafiar voce mesmo."}), 400

        challenge = Challenge(
            id=str(uuid.uuid4()),
            challenger_id=user.id,
            challenged_id=challenged.id,
            title=title,
            description=description,
            offered_amount=offered_amount,
            counter_amount=0,
            agreed_amount=0,
            status="pending",
            created_at=_now_ms(),
            updated_at=_now_ms(),
        )
        session.add(challenge)

    return jsonify({"ok": True}), 201


@app.post("/api/challenges/<challenge_id>/respond")
def respond_challenge(challenge_id: str) -> object:
    token = _token_from_request()
    payload = request.get_json(silent=True) or {}
    action = str(payload.get("action", "")).strip().lower()

    try:
        counter_amount = float(payload.get("counterAmount", 0))
    except (TypeError, ValueError):
        counter_amount = 0

    with session_scope() as session:
        user = _user_from_token(session, token)
        if not user:
            return jsonify({"error": "Login necessario."}), 401

        challenge = session.get(Challenge, challenge_id)
        if not challenge:
            return jsonify({"error": "Desafio nao encontrado."}), 404
        if challenge.challenged_id != user.id:
            return jsonify({"error": "Somente o desafiado pode responder."}), 403
        if challenge.status not in {"pending", "countered"}:
            return jsonify({"error": "Desafio ja foi encerrado."}), 400

        if action == "accept":
            agreed = challenge.counter_amount if challenge.status == "countered" and challenge.counter_amount > 0 else challenge.offered_amount
            challenge.status = "accepted"
            challenge.agreed_amount = agreed
            challenge.updated_at = _now_ms()
            _create_thread_from_challenge(session, challenge, agreed)
        elif action == "reject":
            challenge.status = "rejected"
            challenge.updated_at = _now_ms()
        elif action == "counter":
            if counter_amount < 1:
                return jsonify({"error": "Counteroffer invalida."}), 400
            challenge.status = "countered"
            challenge.counter_amount = counter_amount
            challenge.updated_at = _now_ms()
        else:
            return jsonify({"error": "Acao invalida."}), 400

    return jsonify({"ok": True})


@app.post("/api/challenges/<challenge_id>/accept-counter")
def accept_counter(challenge_id: str) -> object:
    token = _token_from_request()

    with session_scope() as session:
        user = _user_from_token(session, token)
        if not user:
            return jsonify({"error": "Login necessario."}), 401

        challenge = session.get(Challenge, challenge_id)
        if not challenge:
            return jsonify({"error": "Desafio nao encontrado."}), 404
        if challenge.challenger_id != user.id:
            return jsonify({"error": "Somente quem desafiou pode aceitar a counteroffer."}), 403
        if challenge.status != "countered" or challenge.counter_amount <= 0:
            return jsonify({"error": "Nao ha counteroffer pendente."}), 400

        challenge.status = "accepted"
        challenge.agreed_amount = challenge.counter_amount
        challenge.updated_at = _now_ms()
        _create_thread_from_challenge(session, challenge, challenge.counter_amount)

    return jsonify({"ok": True})


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "4173"))
    app.run(host="0.0.0.0", port=port)
