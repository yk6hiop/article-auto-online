from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import RESUME_DIR


_RESUME_RE = re.compile(r"resume_(?P<kind>normal|moechin|child)_(?P<keyword>.+?)_(?P<ts>\d{8}_\d{4})\.json$")


@dataclass(frozen=True)
class WorkflowItem:
    """オンライン版で扱う既存作業の最小状態。"""

    id: str
    kind: str
    keyword: str
    status: str
    next_action: str
    timestamp: str
    path: str
    site_name: str = ""
    prompt_name: str = ""
    completed: bool = False
    failed_step: str = ""
    last_error: str = ""


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _safe_id(path: Path) -> str:
    return path.stem.replace(" ", "_")


def _keyword_from_path(path: Path) -> str:
    match = _RESUME_RE.match(path.name)
    if not match:
        return path.stem
    return match.group("keyword")


def _kind_from_path(path: Path) -> str:
    match = _RESUME_RE.match(path.name)
    if not match:
        return "unknown"
    return match.group("kind")


def _parse_time(value: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d_%H%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return datetime.min


def _derive_status(data: dict[str, Any]) -> tuple[str, bool]:
    meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    raw_status = str(meta.get("resume_status") or "").strip().lower()
    if raw_status == "completed" or meta.get("completed") is True:
        return "完了", True
    if raw_status == "interrupted":
        return "中断", False
    if data.get("final_content"):
        return "本文生成済み", False
    step_outputs = data.get("step_outputs") if isinstance(data.get("step_outputs"), dict) else {}
    if step_outputs:
        return "生成途中", False
    return "未確認", False


def _derive_next_action(status: str, data: dict[str, Any], kind: str) -> str:
    if kind == "child":
        if status == "完了":
            return "メタ情報・内部リンク確認へ進む"
        if status == "中断":
            return "子記事作成を再開する"
        return "子記事作成を確認する"
    if status == "完了":
        return "メタ情報・内部リンク判断へ進む"
    if status == "本文生成済み":
        return "WordPress投稿またはメタ情報へ進む"
    if status == "中断":
        meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        failed_step = str(meta.get("failed_step") or "")
        suffix = f"（停止: {failed_step}）" if failed_step else ""
        return f"親記事作成を再開する{suffix}"
    return "状態を確認する"


def load_workflows(resume_dir: Path = RESUME_DIR, limit: int = 50) -> list[WorkflowItem]:
    """既存resume_dataから、オンライン画面に出す作業状態を読み取る。"""
    if not resume_dir.exists():
        return []

    items: list[WorkflowItem] = []
    for path in sorted(resume_dir.glob("resume_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        data = _read_json(path)
        if not data:
            continue
        kind = _kind_from_path(path)
        keyword = str(data.get("target_input") or _keyword_from_path(path))
        meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        status, completed = _derive_status(data)
        items.append(
            WorkflowItem(
                id=_safe_id(path),
                kind=kind,
                keyword=keyword,
                status=status,
                next_action=_derive_next_action(status, data, kind),
                timestamp=str(data.get("timestamp") or ""),
                path=str(path),
                site_name=str(meta.get("site_name") or meta.get("selected_site_name") or ""),
                prompt_name=str(meta.get("prompt_key") or ""),
                completed=completed,
                failed_step=str(meta.get("failed_step") or ""),
                last_error=str(meta.get("last_error") or ""),
            )
        )
        if len(items) >= limit:
            break

    return sorted(items, key=lambda item: _parse_time(item.timestamp), reverse=True)
