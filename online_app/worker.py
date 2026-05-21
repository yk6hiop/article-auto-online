from __future__ import annotations

import threading
import time

from .job_store import append_job_log, claim_next_job, mark_stale_running_jobs, update_job_status
from .child_service import plan_child_article_job, run_child_article_job
from .internal_link_service import plan_internal_link_job, run_internal_link_job
from .meta_service import plan_meta_job, run_meta_job
from .parent_service import plan_parent_article_job, run_parent_article_job


_started = False
_lock = threading.Lock()


def start_worker() -> None:
    global _started
    with _lock:
        if _started:
            return
        mark_stale_running_jobs()
        thread = threading.Thread(target=_worker_loop, name="online-app-worker", daemon=True)
        thread.start()
        _started = True


def _worker_loop() -> None:
    while True:
        job = claim_next_job()
        if not job:
            time.sleep(2)
            continue
        try:
            append_job_log(job.id, "ジョブ実行を開始しました。\n")
            if job.kind == "parent_article":
                if job.payload.get("dry_run", True):
                    result = plan_parent_article_job(job.payload, lambda text: append_job_log(job.id, text))
                    status = "completed" if result.get("success") else "interrupted"
                    suffix = "\n安全確認モードを完了しました。\n" if result.get("success") else "\n安全確認モードを中断しました。\n"
                else:
                    result = run_parent_article_job(job.payload, lambda text: append_job_log(job.id, text))
                    status = "completed" if result.get("success") else "interrupted"
                    suffix = "\nジョブ完了。\n" if result.get("success") else "\nジョブ中断。\n"
                update_job_status(job.id, status, log=_current_log(job.id) + suffix)
            elif job.kind == "child_article":
                if job.payload.get("dry_run", True):
                    result = plan_child_article_job(job.payload, lambda text: append_job_log(job.id, text))
                    status = "completed" if result.get("success") else "interrupted"
                    suffix = "\n安全確認モードを完了しました。\n" if result.get("success") else "\n安全確認モードを中断しました。\n"
                else:
                    result = run_child_article_job(job.payload, lambda text: append_job_log(job.id, text))
                    status = "completed" if result.get("success") else "interrupted"
                    suffix = "\nジョブ完了。\n" if result.get("success") else "\nジョブ中断。\n"
                update_job_status(job.id, status, log=_current_log(job.id) + suffix)
            elif job.kind == "meta_entry":
                if job.payload.get("dry_run", True):
                    result = plan_meta_job(job.payload, lambda text: append_job_log(job.id, text))
                    status = "completed" if result.get("success") else "interrupted"
                    suffix = "\n安全確認モードを完了しました。\n" if result.get("success") else "\n安全確認モードを中断しました。\n"
                else:
                    result = run_meta_job(job.payload, lambda text: append_job_log(job.id, text))
                    status = "completed" if result.get("success") else "interrupted"
                    suffix = "\nジョブ完了。\n" if result.get("success") else "\nジョブ中断。\n"
                update_job_status(job.id, status, log=_current_log(job.id) + suffix)
            elif job.kind == "internal_link":
                if job.payload.get("dry_run", True):
                    result = plan_internal_link_job(job.payload, lambda text: append_job_log(job.id, text))
                    status = "completed" if result.get("success") else "interrupted"
                    suffix = "\n安全確認モードを完了しました。\n" if result.get("success") else "\n安全確認モードを中断しました。\n"
                else:
                    result = run_internal_link_job(job.payload, lambda text: append_job_log(job.id, text))
                    status = "completed" if result.get("success") else "interrupted"
                    suffix = "\nジョブ完了。\n" if result.get("success") else "\nジョブ中断。\n"
                update_job_status(job.id, status, log=_current_log(job.id) + suffix)
            else:
                raise ValueError(f"未対応のジョブ種別です: {job.kind}")
        except Exception as exc:
            append_job_log(job.id, f"\nエラー: {exc}\n")
            update_job_status(job.id, "failed", log=_current_log(job.id), error=str(exc))


def _current_log(job_id: str) -> str:
    from .job_store import get_job

    job = get_job(job_id)
    return job.log if job else ""
