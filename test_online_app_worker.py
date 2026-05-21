from __future__ import annotations

import time

import online_app.worker as worker
from online_app.job_store import create_job, get_job


def test_worker_completes_dry_run_job(tmp_path, monkeypatch=None):
    db_path = tmp_path / "jobs.sqlite3"

    original_claim = worker.claim_next_job
    original_append = worker.append_job_log
    original_update = worker.update_job_status
    original_current = worker._current_log
    original_plan = worker.plan_parent_article_job
    original_sleep = time.sleep

    def claim():
        return original_claim(db_path=db_path)

    def append(job_id: str, text: str):
        return original_append(job_id, text, db_path=db_path)

    def update(job_id: str, status: str, log: str = "", error: str = ""):
        return original_update(job_id, status, log=log, error=error, db_path=db_path)

    def current_log(job_id: str):
        job = get_job(job_id, db_path=db_path)
        return job.log if job else ""

    def fake_plan(payload, log):
        log("安全確認モードのテスト\n")
        return {"success": True, "dry_run": True}

    def fake_sleep(_seconds):
        raise SystemExit

    worker.claim_next_job = claim
    worker.append_job_log = append
    worker.update_job_status = update
    worker._current_log = current_log
    worker.plan_parent_article_job = fake_plan
    time.sleep = fake_sleep
    try:
        job = create_job(
            "parent_article",
            "安全確認: 親記事作成: smoke",
            {"keyword": "リング ベル プラン", "dry_run": True},
            db_path=db_path,
        )
        try:
            worker._worker_loop()
        except SystemExit:
            pass
    finally:
        worker.claim_next_job = original_claim
        worker.append_job_log = original_append
        worker.update_job_status = original_update
        worker._current_log = original_current
        worker.plan_parent_article_job = original_plan
        time.sleep = original_sleep

    saved = get_job(job.id, db_path=db_path)
    assert saved is not None
    assert saved.status == "completed"
    assert "安全確認モードのテスト" in saved.log
