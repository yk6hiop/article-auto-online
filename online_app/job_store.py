from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import ONLINE_APP_DATA_DIR


DB_PATH = ONLINE_APP_DATA_DIR / "jobs.sqlite3"
DEFAULT_STALE_RUNNING_MINUTES = int(os.environ.get("ONLINE_APP_STALE_RUNNING_MINUTES", "180"))


@dataclass(frozen=True)
class Job:
    id: str
    kind: str
    status: str
    title: str
    payload: dict[str, Any]
    created_at: str
    updated_at: str
    log: str = ""
    error: str = ""


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            title TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            log TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def create_job(kind: str, title: str, payload: dict[str, Any], db_path: Path = DB_PATH) -> Job:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    job = Job(
        id=uuid4().hex,
        kind=kind,
        status="queued",
        title=title,
        payload=payload,
        created_at=now,
        updated_at=now,
    )
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO jobs (id, kind, status, title, payload_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (job.id, job.kind, job.status, job.title, json.dumps(job.payload, ensure_ascii=False), job.created_at, job.updated_at),
        )
        conn.commit()
    return job


def list_jobs(db_path: Path = DB_PATH, limit: int = 50) -> list[Job]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY datetime(created_at) DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_job(row) for row in rows]


def claim_next_job(db_path: Path = DB_PATH) -> Job | None:
    """queuedのジョブを1件runningへ変更して取得する。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE status = 'queued' ORDER BY datetime(created_at) ASC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE jobs SET status = 'running', updated_at = ? WHERE id = ?",
            (now, row["id"]),
        )
        conn.commit()
        claimed = conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone()
    return _row_to_job(claimed)


def mark_stale_running_jobs(minutes: int = DEFAULT_STALE_RUNNING_MINUTES, db_path: Path = DB_PATH) -> int:
    """長時間更新されていないrunningジョブを中断扱いにする。

    PaaS再起動やローカル強制終了でrunningのまま残ると、画面では動いて
    いるように見えるため、起動時や手動復旧時に明示的に止める。
    """
    if minutes <= 0:
        return 0
    now_dt = datetime.now()
    threshold = (now_dt - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
    now = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    note = f"\nサーバー再起動または長時間無更新のため中断扱いにしました（{minutes}分以上更新なし）。\n"
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, log FROM jobs WHERE status = 'running' AND updated_at < ?",
            (threshold,),
        ).fetchall()
        if not rows:
            return 0
        for row in rows:
            conn.execute(
                """
                UPDATE jobs
                SET status = 'interrupted', log = ?, error = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    (row["log"] or "") + note,
                    "ジョブが長時間更新されなかったため中断扱いにしました。",
                    now,
                    row["id"],
                ),
            )
        conn.commit()
    return len(rows)


def get_job(job_id: str, db_path: Path = DB_PATH) -> Job | None:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row) if row else None


def update_job_status(job_id: str, status: str, log: str = "", error: str = "", db_path: Path = DB_PATH) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _connect(db_path) as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status = ?, log = ?, error = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, log, error, now, job_id),
        )
        conn.commit()


def append_job_log(job_id: str, text: str, db_path: Path = DB_PATH) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _connect(db_path) as conn:
        row = conn.execute("SELECT log FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return
        current = row["log"] or ""
        conn.execute(
            "UPDATE jobs SET log = ?, updated_at = ? WHERE id = ?",
            (current + text, now, job_id),
        )
        conn.commit()


def _row_to_job(row: sqlite3.Row) -> Job:
    try:
        payload = json.loads(row["payload_json"])
    except Exception:
        payload = {}
    return Job(
        id=row["id"],
        kind=row["kind"],
        status=row["status"],
        title=row["title"],
        payload=payload if isinstance(payload, dict) else {},
        log=row["log"],
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
