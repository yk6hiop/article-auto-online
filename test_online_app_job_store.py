from __future__ import annotations

from datetime import datetime, timedelta

from online_app.job_store import create_job, get_job, mark_stale_running_jobs


def test_mark_stale_running_jobs_interrupts_old_running_job(tmp_path):
    db_path = tmp_path / "jobs.sqlite3"
    job = create_job("parent_article", "古い実行中ジョブ", {"dry_run": True}, db_path=db_path)

    old_time = (datetime.now() - timedelta(minutes=200)).strftime("%Y-%m-%d %H:%M:%S")
    import sqlite3

    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "UPDATE jobs SET status = 'running', updated_at = ? WHERE id = ?",
            (old_time, job.id),
        )
        conn.commit()

    fixed = mark_stale_running_jobs(minutes=180, db_path=db_path)
    updated = get_job(job.id, db_path=db_path)

    assert fixed == 1
    assert updated is not None
    assert updated.status == "interrupted"
    assert "長時間無更新" in updated.log


def test_mark_stale_running_jobs_keeps_fresh_running_job(tmp_path):
    db_path = tmp_path / "jobs.sqlite3"
    job = create_job("parent_article", "新しい実行中ジョブ", {"dry_run": True}, db_path=db_path)

    import sqlite3

    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("UPDATE jobs SET status = 'running' WHERE id = ?", (job.id,))
        conn.commit()

    fixed = mark_stale_running_jobs(minutes=180, db_path=db_path)
    updated = get_job(job.id, db_path=db_path)

    assert fixed == 0
    assert updated is not None
    assert updated.status == "running"
