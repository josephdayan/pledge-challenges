from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data.db"

app = Flask(__name__)
_db_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _status(target_amount: float, pledged_total: float, deadline: str) -> str:
    if pledged_total >= target_amount:
        return "funded"

    deadline_ts = datetime.strptime(deadline, "%Y-%m-%d").replace(hour=23, minute=59, second=59).timestamp()
    if time.time() > deadline_ts:
        return "expired"

    return "open"


def init_db() -> None:
    with _db_lock:
        conn = _connect()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS threads (
                id TEXT PRIMARY KEY,
                creator_name TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                target_amount REAL NOT NULL,
                deadline TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pledges (
                id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                supporter_name TEXT NOT NULL,
                amount REAL NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE CASCADE
            );
            """
        )

        exists = conn.execute("SELECT COUNT(*) AS c FROM threads").fetchone()["c"]
        if exists == 0:
            seed_thread_id = str(uuid.uuid4())
            now_ms = int(time.time() * 1000)
            conn.execute(
                """
                INSERT INTO threads (id, creator_name, title, description, target_amount, deadline, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    seed_thread_id,
                    "Lucas",
                    "Vou de Sao Paulo a Santos de bike",
                    "Saio as 6h da manha no domingo e posto comprovacao do trajeto.",
                    1000,
                    datetime.fromtimestamp(time.time() + 5 * 24 * 3600).strftime("%Y-%m-%d"),
                    now_ms,
                ),
            )
            conn.execute(
                """
                INSERT INTO pledges (id, thread_id, supporter_name, amount, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), seed_thread_id, "Ana", 150, now_ms - 5400000),
            )
            conn.execute(
                """
                INSERT INTO pledges (id, thread_id, supporter_name, amount, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), seed_thread_id, "Rafa", 200, now_ms - 3100000),
            )

        conn.commit()
        conn.close()


def _list_threads() -> list[dict]:
    with _db_lock:
        conn = _connect()
        thread_rows = conn.execute(
            """
            SELECT id, creator_name, title, description, target_amount, deadline, created_at
            FROM threads
            ORDER BY created_at DESC
            """
        ).fetchall()

        result: list[dict] = []
        for row in thread_rows:
            pledge_rows = conn.execute(
                """
                SELECT supporter_name, amount, created_at
                FROM pledges
                WHERE thread_id = ?
                ORDER BY created_at DESC
                """,
                (row["id"],),
            ).fetchall()

            pledges = [
                {
                    "supporterName": p["supporter_name"],
                    "amount": p["amount"],
                    "createdAt": p["created_at"],
                }
                for p in pledge_rows
            ]

            pledged_total = sum(p["amount"] for p in pledge_rows)
            result.append(
                {
                    "id": row["id"],
                    "creatorName": row["creator_name"],
                    "title": row["title"],
                    "description": row["description"],
                    "targetAmount": row["target_amount"],
                    "deadline": row["deadline"],
                    "createdAt": row["created_at"],
                    "pledges": pledges,
                    "status": _status(row["target_amount"], pledged_total, row["deadline"]),
                }
            )

        conn.close()
        return result


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
    return jsonify({"threads": _list_threads()})


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
    now_ms = int(time.time() * 1000)

    with _db_lock:
        conn = _connect()
        conn.execute(
            """
            INSERT INTO threads (id, creator_name, title, description, target_amount, deadline, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (thread_id, creator_name, title, description, target_amount, deadline, now_ms),
        )
        conn.commit()
        conn.close()

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

    with _db_lock:
        conn = _connect()
        thread_row = conn.execute(
            "SELECT id, target_amount, deadline FROM threads WHERE id = ?",
            (thread_id,),
        ).fetchone()

        if not thread_row:
            conn.close()
            return jsonify({"error": "Thread nao encontrada."}), 404

        total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM pledges WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()["total"]

        if _status(thread_row["target_amount"], total, thread_row["deadline"]) != "open":
            conn.close()
            return jsonify({"error": "Este desafio nao aceita novos pledges."}), 400

        conn.execute(
            """
            INSERT INTO pledges (id, thread_id, supporter_name, amount, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), thread_id, supporter_name, amount, int(time.time() * 1000)),
        )
        conn.commit()
        conn.close()

    return jsonify({"ok": True}), 201


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "4173"))
    app.run(host="0.0.0.0", port=port)
