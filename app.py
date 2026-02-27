from __future__ import annotations

import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from sqlalchemy import BigInteger, Float, ForeignKey, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

BASE_DIR = Path(__file__).resolve().parent


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


class Thread(Base):
    __tablename__ = "threads"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    creator_name: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    target_amount: Mapped[float] = mapped_column(Float, nullable=False)
    deadline: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    pledges: Mapped[list["Pledge"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan", order_by="desc(Pledge.created_at)"
    )


class Pledge(Base):
    __tablename__ = "pledges"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    thread_id: Mapped[str] = mapped_column(String, ForeignKey("threads.id", ondelete="CASCADE"), nullable=False)
    supporter_name: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    thread: Mapped[Thread] = relationship(back_populates="pledges")


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


def _status(target_amount: float, pledged_total: float, deadline: str) -> str:
    if pledged_total >= target_amount:
        return "funded"

    deadline_ts = datetime.strptime(deadline, "%Y-%m-%d").replace(hour=23, minute=59, second=59).timestamp()
    if time.time() > deadline_ts:
        return "expired"

    return "open"


def init_db() -> None:
    Base.metadata.create_all(ENGINE)

    with session_scope() as session:
        existing = session.query(Thread).count()
        if existing > 0:
            return

        seed_enabled = os.environ.get("SEED_DEMO", "true").lower() in {"1", "true", "yes"}
        if not seed_enabled:
            return

        seed_thread = Thread(
            id=str(uuid.uuid4()),
            creator_name="Lucas",
            title="Vou de Sao Paulo a Santos de bike",
            description="Saio as 6h da manha no domingo e posto comprovacao do trajeto.",
            target_amount=1000,
            deadline=datetime.fromtimestamp(time.time() + 5 * 24 * 3600).strftime("%Y-%m-%d"),
            created_at=int(time.time() * 1000),
        )
        session.add(seed_thread)
        session.flush()

        session.add(
            Pledge(
                id=str(uuid.uuid4()),
                thread_id=seed_thread.id,
                supporter_name="Ana",
                amount=150,
                created_at=seed_thread.created_at - 5400000,
            )
        )
        session.add(
            Pledge(
                id=str(uuid.uuid4()),
                thread_id=seed_thread.id,
                supporter_name="Rafa",
                amount=200,
                created_at=seed_thread.created_at - 3100000,
            )
        )


def _serialize_thread(thread: Thread) -> dict:
    pledges = [
        {
            "supporterName": pledge.supporter_name,
            "amount": float(pledge.amount),
            "createdAt": int(pledge.created_at),
        }
        for pledge in thread.pledges
    ]

    pledged_total = sum(pledge["amount"] for pledge in pledges)
    return {
        "id": thread.id,
        "creatorName": thread.creator_name,
        "title": thread.title,
        "description": thread.description,
        "targetAmount": float(thread.target_amount),
        "deadline": thread.deadline,
        "createdAt": int(thread.created_at),
        "pledges": pledges,
        "status": _status(float(thread.target_amount), pledged_total, thread.deadline),
    }


@app.get("/")
def root() -> object:
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/styles.css")
def styles() -> object:
    return send_from_directory(BASE_DIR, "styles.css")


@app.get("/app.js")
def frontend_script() -> object:
    return send_from_directory(BASE_DIR, "app.js")


@app.get("/api/threads")
def get_threads() -> object:
    with session_scope() as session:
        threads = session.query(Thread).order_by(Thread.created_at.desc()).all()
        payload = [_serialize_thread(thread) for thread in threads]
    return jsonify({"threads": payload})


@app.post("/api/threads")
def create_thread() -> object:
    payload = request.get_json(silent=True) or {}
    creator_name = str(payload.get("creatorName", "")).strip()
    title = str(payload.get("title", "")).strip()
    description = str(payload.get("description", "")).strip()
    deadline = str(payload.get("deadline", "")).strip()

    try:
        target_amount = float(payload.get("targetAmount", 0))
    except (TypeError, ValueError):
        target_amount = 0

    if not creator_name or not title or not description or target_amount < 1:
        return jsonify({"error": "Dados invalidos para criar thread."}), 400

    try:
        datetime.strptime(deadline, "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "Prazo invalido. Use formato YYYY-MM-DD."}), 400

    thread_id = str(uuid.uuid4())
    thread = Thread(
        id=thread_id,
        creator_name=creator_name,
        title=title,
        description=description,
        target_amount=target_amount,
        deadline=deadline,
        created_at=int(time.time() * 1000),
    )

    with session_scope() as session:
        session.add(thread)

    return jsonify({"ok": True, "id": thread_id}), 201


@app.post("/api/threads/<thread_id>/pledges")
def create_pledge(thread_id: str) -> object:
    payload = request.get_json(silent=True) or {}
    supporter_name = str(payload.get("supporterName", "")).strip()

    try:
        amount = float(payload.get("amount", 0))
    except (TypeError, ValueError):
        amount = 0

    if not supporter_name or amount < 1:
        return jsonify({"error": "Dados invalidos para criar pledge."}), 400

    with session_scope() as session:
        thread = session.get(Thread, thread_id)
        if not thread:
            return jsonify({"error": "Thread nao encontrada."}), 404

        pledged_total = sum(float(pledge.amount) for pledge in thread.pledges)
        if _status(float(thread.target_amount), pledged_total, thread.deadline) != "open":
            return jsonify({"error": "Este desafio nao aceita novos pledges."}), 400

        session.add(
            Pledge(
                id=str(uuid.uuid4()),
                thread_id=thread.id,
                supporter_name=supporter_name,
                amount=amount,
                created_at=int(time.time() * 1000),
            )
        )

    return jsonify({"ok": True}), 201


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "4173"))
    app.run(host="0.0.0.0", port=port)
