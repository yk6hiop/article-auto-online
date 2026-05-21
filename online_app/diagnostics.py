from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import ONLINE_APP_DATA_DIR, PROJECT_ROOT
from .runtime_config import apply_environment_overrides


_CORE = None


@dataclass(frozen=True)
class DiagnosticItem:
    name: str
    status: str
    message: str


def _core():
    global _CORE
    if _CORE is None:
        import auto_post_unified as imported_core

        _CORE = apply_environment_overrides(imported_core)
    return _CORE


def _exists(path: str | Path) -> bool:
    try:
        return Path(path).exists()
    except Exception:
        return False


def _writable(path: str | Path) -> bool:
    try:
        p = Path(path)
        target = p if p.is_dir() else p.parent
        return target.exists() and os.access(target, os.W_OK)
    except Exception:
        return False


def _status(ok: bool, warn: bool = False) -> str:
    if ok:
        return "ok"
    return "warn" if warn else "error"


def collect_diagnostics() -> dict[str, Any]:
    """オンライン移植前に確認すべき設定・依存を一覧化する。"""
    core = _core()
    items: list[DiagnosticItem] = []

    items.append(
        DiagnosticItem(
            "実行OS",
            "ok",
            f"{platform.system()} / msvcrt={'あり' if getattr(core, 'msvcrt', None) else 'なし'}",
        )
    )
    items.append(
        DiagnosticItem(
            "プロジェクトルート",
            _status(_exists(PROJECT_ROOT)),
            str(PROJECT_ROOT),
        )
    )

    for label, path in [
        ("プロンプトフォルダ", getattr(core, "PROMPT_BASE_DIR", "")),
        ("生成結果フォルダ", getattr(core, "GOOGLE_DRIVE_BASE", "")),
        ("resume_data", PROJECT_ROOT / "resume_data"),
        ("オンラインジョブ保存先", ONLINE_APP_DATA_DIR),
    ]:
        exists = _exists(path)
        writable = _writable(path)
        items.append(
            DiagnosticItem(
                label,
                _status(exists and writable, warn=exists),
                f"{path} / 存在={'はい' if exists else 'いいえ'} / 書込={'はい' if writable else 'いいえ'}",
            )
        )

    searchapi_present = bool(os.environ.get("SEARCHAPI_API_KEY", "").strip())
    items.append(
        DiagnosticItem(
            "SearchAPI.ioキー",
            _status(searchapi_present, warn=True),
            "環境変数 SEARCHAPI_API_KEY は設定済みです。" if searchapi_present else "未設定です。空でも手動URL入力で親記事作成は可能ですが、競合URL自動取得は使えません。",
        )
    )

    normal_keys = getattr(core, "API_KEYS_NORMAL", [])
    moechin_keys = getattr(core, "API_KEYS_MOECHIN", [])
    hardcoded_gemini = sum(1 for item in [*normal_keys, *moechin_keys] if str(item.get("key", "")).startswith("AIza"))
    items.append(
        DiagnosticItem(
            "Gemini APIキー管理",
            "warn" if hardcoded_gemini else "ok",
            f"登録キー {len(normal_keys) + len(moechin_keys)}件。ハードコード検出 {hardcoded_gemini}件。本番公開前に環境変数または秘密情報管理へ移してください。",
        )
    )

    sites = getattr(core, "SITES_ALL", {})
    missing_site_fields = []
    for key, site in sites.items():
        missing = [field for field in ("name", "url", "user", "pass") if not site.get(field)]
        if missing:
            missing_site_fields.append(f"{key}:{','.join(missing)}")
    items.append(
        DiagnosticItem(
            "WordPress接続設定",
            "warn" if missing_site_fields else "ok",
            f"登録サイト {len(sites)}件。欠損: {', '.join(missing_site_fields) if missing_site_fields else 'なし'}。本番公開前に認証情報を環境変数へ移してください。",
        )
    )

    items.append(
        DiagnosticItem(
            "親記事モデル",
            "ok",
            str(getattr(core, "MODEL_PARENT", "")),
        )
    )
    items.append(
        DiagnosticItem(
            "子記事・メタ・内部リンクモデル",
            "ok",
            str(getattr(core, "MODEL_CHILD", "")),
        )
    )

    errors = sum(1 for item in items if item.status == "error")
    warnings = sum(1 for item in items if item.status == "warn")
    return {
        "items": items,
        "errors": errors,
        "warnings": warnings,
        "ready_for_local": errors == 0,
        "ready_for_public_deploy": errors == 0 and warnings == 0,
    }
