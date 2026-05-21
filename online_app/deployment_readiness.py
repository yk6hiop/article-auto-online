from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import ONLINE_APP_DATA_DIR, PROJECT_ROOT
from .diagnostics import collect_diagnostics


@dataclass(frozen=True)
class ReadinessItem:
    name: str
    status: str
    message: str


def collect_deployment_readiness() -> dict[str, Any]:
    """公開デプロイ直前に見るべき項目をまとめる。

    `/diagnostics` はローカル起動可否も含めた設定診断。
    こちらは、PaaSへ載せる時に詰まりやすい項目だけを別枠で確認する。
    """
    diagnostics = collect_diagnostics()
    items: list[ReadinessItem] = []

    _add_path_check(items, "Procfile", PROJECT_ROOT / "Procfile")
    _add_path_check(items, "Dockerfile", PROJECT_ROOT / "Dockerfile")
    _add_path_check(items, ".dockerignore", PROJECT_ROOT / ".dockerignore")
    _add_path_check(items, "render.yaml", PROJECT_ROOT / "render.yaml")
    _add_path_check(items, "requirements.txt", PROJECT_ROOT / "online_app" / "requirements.txt")
    _add_path_check(items, "env.example", PROJECT_ROOT / "online_app" / "env.example")
    leaked = _find_public_secret_literals()
    items.append(
        ReadinessItem(
            "公開対象の秘密情報スキャン",
            "error" if leaked else "ok",
            "実キーらしき文字列は見つかりません。"
            if not leaked
            else "公開対象ファイルに実キーらしき文字列があります: " + ", ".join(leaked[:5]),
        )
    )
    is_railway = bool(os.environ.get("RAILWAY_PROJECT_ID") or os.environ.get("RAILWAY_SERVICE_ID"))
    has_git = (PROJECT_ROOT / ".git").exists()
    items.append(
        ReadinessItem(
            "Gitリポジトリ",
            "ok" if has_git or is_railway else "warn",
            "Gitリポジトリです。"
            if has_git
            else "Railway上では.gitが含まれないため、GitHub連携済みデプロイとして扱います。"
            if is_railway
            else "まだGitリポジトリではありません。GitHub連携型PaaSではGit化とリモート登録が必要です。",
        )
    )

    data_dir_exists = ONLINE_APP_DATA_DIR.exists()
    data_dir_writable = _writable(ONLINE_APP_DATA_DIR)
    items.append(
        ReadinessItem(
            "ジョブDB保存先",
            "ok" if data_dir_exists and data_dir_writable else "error",
            f"{ONLINE_APP_DATA_DIR} / 存在={'はい' if data_dir_exists else 'いいえ'} / 書込={'はい' if data_dir_writable else 'いいえ'}",
        )
    )

    items.append(
        ReadinessItem(
            "ONLINE_APP_DATA_DIR",
            "ok" if os.environ.get("ONLINE_APP_DATA_DIR") else "warn",
            "環境変数で指定済みです。PaaSでは永続ボリュームに向けてください。"
            if os.environ.get("ONLINE_APP_DATA_DIR")
            else "未指定です。ローカルでは問題ありませんが、公開環境では永続ボリュームのパスを指定してください。",
        )
    )
    items.append(
        ReadinessItem(
            "Geminiキー外出し",
            "ok" if os.environ.get("ONLINE_GEMINI_KEYS_NORMAL_JSON") else "warn",
            "ONLINE_GEMINI_KEYS_NORMAL_JSON が設定済みです。"
            if os.environ.get("ONLINE_GEMINI_KEYS_NORMAL_JSON")
            else "未設定です。公開環境では固定キーに依存せず、環境変数で上書きしてください。",
        )
    )
    items.append(
        ReadinessItem(
            "WordPress認証外出し",
            "ok" if os.environ.get("ONLINE_WP_SITE_OVERRIDES_JSON") else "warn",
            "ONLINE_WP_SITE_OVERRIDES_JSON が設定済みです。"
            if os.environ.get("ONLINE_WP_SITE_OVERRIDES_JSON")
            else "未設定です。公開環境ではWordPress認証情報を環境変数で上書きしてください。",
        )
    )
    items.append(
        ReadinessItem(
            "SearchAPI.io",
            "ok" if os.environ.get("SEARCHAPI_API_KEY") else "warn",
            "SEARCHAPI_API_KEY が設定済みです。"
            if os.environ.get("SEARCHAPI_API_KEY")
            else "未設定です。手動URL入力は可能ですが、競合URL自動取得は使えません。",
        )
    )

    items.append(
        ReadinessItem(
            "設定診断",
            "ok" if diagnostics["errors"] == 0 else "error",
            f"/diagnostics: エラー {diagnostics['errors']} / 警告 {diagnostics['warnings']}",
        )
    )

    errors = sum(1 for item in items if item.status == "error")
    warnings = sum(1 for item in items if item.status == "warn")
    return {
        "items": items,
        "errors": errors,
        "warnings": warnings,
        "ready_for_deploy_smoke": errors == 0,
        "ready_for_public_real_run": errors == 0 and warnings == 0,
    }


def _add_path_check(items: list[ReadinessItem], name: str, path: Path) -> None:
    items.append(
        ReadinessItem(
            name,
            "ok" if path.exists() else "error",
            str(path),
        )
    )


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _find_public_secret_literals() -> list[str]:
    candidates = [
        PROJECT_ROOT / "auto_post_unified.py",
        PROJECT_ROOT / "online_app",
        PROJECT_ROOT / "Dockerfile",
        PROJECT_ROOT / "Procfile",
        PROJECT_ROOT / "render.yaml",
    ]
    ignore_names = {"local_private_config.json"}
    findings: list[str] = []
    pattern = re.compile(r"AIza[0-9A-Za-z_-]{20,}")
    for base in candidates:
        paths = [base]
        if base.is_dir():
            paths = [p for p in base.rglob("*") if p.is_file()]
        for path in paths:
            if path.name in ignore_names or path.suffix.lower() in {".pyc", ".sqlite3"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if pattern.search(text):
                findings.append(str(path.relative_to(PROJECT_ROOT)))
    return findings
