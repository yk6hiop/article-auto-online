from __future__ import annotations

import copy
import json
import os
from typing import Any


def apply_environment_overrides(core: Any) -> Any:
    """オンライン版だけ、公開環境の秘密情報を環境変数から上書きする。

    ローカルCLIの既存設定はそのまま残し、Web起動時にだけ差し替える。
    公開サーバーでは `ONLINE_GEMINI_KEYS_NORMAL_JSON` などを使うことで、
    `auto_post_unified.py` 内の固定値に依存しない運用へ寄せられる。
    """
    if getattr(core, "_ONLINE_ENV_OVERRIDES_APPLIED", False):
        return core

    normal_keys = _json_list_env("ONLINE_GEMINI_KEYS_NORMAL_JSON")
    moechin_keys = _json_list_env("ONLINE_GEMINI_KEYS_MOECHIN_JSON")
    if normal_keys:
        core.API_KEYS_NORMAL = normal_keys
    if moechin_keys:
        core.API_KEYS_MOECHIN = moechin_keys

    site_overrides = _json_dict_env("ONLINE_WP_SITE_OVERRIDES_JSON")
    if site_overrides:
        _apply_site_overrides(core, site_overrides)

    core._ONLINE_ENV_OVERRIDES_APPLIED = True
    return core


def _json_list_env(name: str) -> list[dict[str, str]]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return []
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError(f"{name} はJSON配列で指定してください。")
    items: list[dict[str, str]] = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict) or not item.get("name") or not item.get("key"):
            raise ValueError(f"{name} の {index} 件目は name/key を持つオブジェクトにしてください。")
        items.append({"name": str(item["name"]), "key": str(item["key"])})
    return items


def _json_dict_env(name: str) -> dict[str, Any]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"{name} はJSONオブジェクトで指定してください。")
    return data


def _apply_site_overrides(core: Any, overrides: dict[str, Any]) -> None:
    sites_normal = copy.deepcopy(getattr(core, "SITES_NORMAL", {}))
    sites_moechin = copy.deepcopy(getattr(core, "SITES_MOECHIN", {}))

    for key, values in overrides.items():
        if not isinstance(values, dict):
            raise ValueError("ONLINE_WP_SITE_OVERRIDES_JSON の各値はオブジェクトで指定してください。")
        target = sites_moechin if str(key) in sites_moechin else sites_normal
        if str(key) not in target:
            raise ValueError(f"未登録のサイトキーです: {key}")
        for field in ("name", "url", "user", "pass", "type"):
            if field in values and values[field] is not None:
                target[str(key)][field] = str(values[field])

    core.SITES_NORMAL = sites_normal
    core.SITES_MOECHIN = sites_moechin
    core.SITES_ALL = {**sites_normal, **sites_moechin}
