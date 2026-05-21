from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ONLINE_APP_DATA_DIR = Path(os.environ.get("ONLINE_APP_DATA_DIR", PROJECT_ROOT / "online_app_data"))
if not ONLINE_APP_DATA_DIR.is_absolute():
    ONLINE_APP_DATA_DIR = PROJECT_ROOT / ONLINE_APP_DATA_DIR
RESUME_DIR = ONLINE_APP_DATA_DIR / "resume_data"
PARENT_LOGS_DIR = ONLINE_APP_DATA_DIR / "記事生成結果" / "親記事" / "logs"
WORK_RESULTS_DIR = ONLINE_APP_DATA_DIR / "記事生成結果" / "作業結果"
PROMPT_BASE_DIR = PROJECT_ROOT / "prompts"


def resolve_project_path(path: str | Path) -> Path:
    """プロジェクト内の相対パスを絶対パスへ解決する。"""
    path = Path(path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path
