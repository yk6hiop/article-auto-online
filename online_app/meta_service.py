from __future__ import annotations

from typing import Any, Callable

from .runtime_config import apply_environment_overrides


LogFn = Callable[[str], None]
_CORE = None


def _core():
    global _CORE
    if _CORE is None:
        import auto_post_unified as imported_core

        _CORE = apply_environment_overrides(imported_core)
    return _CORE


def get_meta_options() -> dict[str, Any]:
    core = _core()
    sites = [
        {"key": key, "name": value["name"], "type": value["type"]}
        for key, value in core.SITES_NORMAL.items()
    ]
    api_keys = [
        {"index": i, "name": item["name"]}
        for i, item in enumerate(core.API_KEYS_NORMAL)
    ]
    return {"sites": sites, "api_keys": api_keys}


def _prepare_meta_job(payload: dict[str, Any]) -> dict[str, Any]:
    core = _core()
    site_key = str(payload.get("site_key") or "").strip()
    keyword = str(payload.get("keyword") or "").strip()
    article_html = str(payload.get("article_html") or "").strip()
    post_url = str(payload.get("post_url") or "").strip()
    api_key_index = int(payload.get("api_key_index") or 0)

    if not keyword:
        raise ValueError("キーワードが空です。")
    if not article_html:
        raise ValueError("記事HTMLが空です。")
    if site_key not in core.SITES_NORMAL:
        raise ValueError(f"未対応のサイトキーです: {site_key}")
    if api_key_index < 0 or api_key_index >= len(core.API_KEYS_NORMAL):
        raise ValueError(f"未対応のAPIキー番号です: {api_key_index}")

    selected_site = core.SITES_NORMAL[site_key]
    step9_template = core.read_file(core.STEP9_META_FILE)
    if not step9_template:
        step9_template = "【メタ情報テンプレート（step9_meta.txt）が見つかりません】"
    live_site_context = core.build_live_site_context_for_step9(selected_site)
    step9_prompt = f"""=== 処理対象記事のコンテキスト（自動生成） ===
記事種別: 親記事
キーワード: {keyword}
投稿URL: {post_url or '（未指定）'}

=== 対象記事HTML ===
{article_html}

=== サイト情報（WordPressから取得した最新候補） ===
{live_site_context}

=== メタ情報・入稿情報生成プロンプト ===
{step9_template}"""
    return {
        "core": core,
        "selected_site": selected_site,
        "keyword": keyword,
        "post_url": post_url,
        "api_key_index": api_key_index,
        "article_html": article_html,
        "step9_prompt": step9_prompt,
    }


def plan_meta_job(payload: dict[str, Any], log: LogFn) -> dict[str, Any]:
    prepared = _prepare_meta_job(payload)
    core = prepared["core"]
    log("【安全確認モード】メタ情報・入稿情報ジョブの実行計画\n")
    log("このモードではGemini APIを使わず、WordPressにも反映しません。\n\n")
    log(f"対象サイト: {prepared['selected_site']['name']}\n")
    log(f"キーワード: {prepared['keyword']}\n")
    log(f"投稿URL: {prepared['post_url'] or '未指定'}\n")
    log(f"APIキー: {core.API_KEYS_NORMAL[prepared['api_key_index']]['name']}（本番実行時のみ使用）\n")
    log(f"記事HTML文字数: {len(prepared['article_html'])}\n")
    log(f"メタ生成プロンプト文字数: {len(prepared['step9_prompt'])}\n")
    log("WordPress自動反映: v0では行いません（入稿用サマリーを見て手動反映）。\n")
    log("\n問題なければ、同じフォームで「本番実行」を選んでください。\n")
    return {"success": True, "dry_run": True}


def run_meta_job(payload: dict[str, Any], log: LogFn) -> dict[str, Any]:
    prepared = _prepare_meta_job(payload)
    core = prepared["core"]
    selected_api_key = core.API_KEYS_NORMAL[prepared["api_key_index"]]["key"]
    log("オンライン メタ情報・入稿情報ジョブ開始\n")
    log(f"対象サイト: {prepared['selected_site']['name']}\n")
    log(f"キーワード: {prepared['keyword']}\n")
    result = core.run_step9_prompt_with_gemini(
        prepared["step9_prompt"],
        prepared["selected_site"],
        prepared["keyword"],
        post_url=prepared["post_url"],
        rankmath_mode="manual",
        api_key=selected_api_key,
        api_key_label=core.API_KEYS_NORMAL[prepared["api_key_index"]]["name"],
        article_role="parent",
    )
    if isinstance(result, dict):
        log(f"メタ情報API結果: {result.get('result_path') or '未取得'}\n")
        log(f"入稿用サマリー: {result.get('entry_sheet_path') or '未取得'}\n")
        log(f"WordPress反映: {result.get('apply_message') or '自動反映なし'}\n")
        return {"success": True, "result": result}
    log(f"メタ情報API結果: {result}\n")
    return {"success": True, "result": result}
