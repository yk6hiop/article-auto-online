from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_CONFIG = ROOT / "local_private_config.json"
DEFAULT_OUTPUT = ROOT / "online_app_data" / "deploy_env.private.txt"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="公開環境へ貼り付ける環境変数ファイルを、ローカル秘密設定から生成します。"
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="出力先。既定は online_app_data/deploy_env.private.txt（Git対象外）です。",
    )
    parser.add_argument(
        "--data-dir",
        default="/var/data",
        help="公開環境の ONLINE_APP_DATA_DIR。Render Disk想定の既定値は /var/data です。",
    )
    args = parser.parse_args()

    if not PRIVATE_CONFIG.exists():
        raise SystemExit(f"local_private_config.json が見つかりません: {PRIVATE_CONFIG}")

    config = json.loads(PRIVATE_CONFIG.read_text(encoding="utf-8"))
    env = build_env(config, args.data_dir)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(format_env(env), encoding="utf-8")

    print("公開環境用envファイルを生成しました。")
    print(f"保存先: {output}")
    print("このファイルには秘密情報が含まれます。Gitには入れないでください。")
    print(f"Geminiキー: 通常 {len(config.get('api_keys_normal') or [])} 件 / もえちん {len(config.get('api_keys_moechin') or [])} 件")
    print(f"WordPressサイト設定: {len(_site_overrides(config))} 件")
    print("値の中身は表示していません。公開先の環境変数画面へ必要項目を転記してください。")


def build_env(config: dict[str, Any], data_dir: str) -> dict[str, str]:
    env: dict[str, str] = {
        "ONLINE_APP_DATA_DIR": data_dir,
        "ONLINE_GEMINI_KEYS_NORMAL_JSON": _compact_json(config.get("api_keys_normal") or []),
        "ONLINE_GEMINI_KEYS_MOECHIN_JSON": _compact_json(config.get("api_keys_moechin") or []),
        "ONLINE_WP_SITE_OVERRIDES_JSON": _compact_json(_site_overrides(config)),
    }
    search_api_key = os.environ.get("SEARCHAPI_API_KEY", "").strip()
    if search_api_key:
        env["SEARCHAPI_API_KEY"] = search_api_key
    paid_key = str(config.get("api_key_paid") or "").strip()
    if paid_key:
        env["GEMINI_API_KEY_PAID"] = paid_key
    return env


def _site_overrides(config: dict[str, Any]) -> dict[str, dict[str, str]]:
    merged: dict[str, Any] = {}
    merged.update(config.get("sites_normal") or {})
    merged.update(config.get("sites_moechin") or {})
    result: dict[str, dict[str, str]] = {}
    for key, site in merged.items():
        if not isinstance(site, dict):
            continue
        result[str(key)] = {
            field: str(site.get(field) or "")
            for field in ("name", "url", "user", "pass", "type")
            if field in site
        }
    return result


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def format_env(env: dict[str, str]) -> str:
    lines = [
        "# 公開環境へ転記する環境変数",
        "# このファイルは秘密情報を含むため、Gitに入れないでください。",
        "",
    ]
    for key, value in env.items():
        lines.append(f"{key}={value}")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
