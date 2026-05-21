from __future__ import annotations

import html
import re
from pathlib import Path
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


def get_internal_link_options() -> dict[str, Any]:
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


def _plain_text(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("rendered", "")
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _rendered_html(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("rendered", "") or "")
    return str(value or "")


def _char_count(article_html: str) -> int:
    text = re.sub(r"<[^>]+>", "", article_html or "")
    return len(re.sub(r"\s+", "", text))


def _resolve_site(site_key: str) -> dict[str, Any]:
    core = _core()
    if site_key not in core.SITES_NORMAL:
        raise ValueError(f"未対応のサイトキーです: {site_key}")
    return core.SITES_NORMAL[site_key]


def build_search_queries(topic_title: str, proposal: str = "") -> list[str]:
    core = _core()
    topic_title = (topic_title or "").strip()
    proposal = (proposal or "").strip()
    if not topic_title and proposal:
        topic_title = core.extract_topic_title(proposal)
    if not topic_title:
        raise ValueError("内部リンク案タイトルが空です。")
    if hasattr(core, "build_wp_search_queries"):
        return core.build_wp_search_queries(topic_title, proposal, max_queries=6)
    return [topic_title]


def search_internal_link_candidates(
    site_key: str,
    topic_title: str,
    proposal: str = "",
    search_query: str = "",
    exclude_url: str = "",
    count: int = 10,
) -> dict[str, Any]:
    """内部リンク候補になるWordPress記事を検索する。"""
    core = _core()
    site = _resolve_site(str(site_key))
    queries = [search_query.strip()] if search_query.strip() else build_search_queries(topic_title, proposal)
    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    used_queries: list[str] = []
    exclude_norm = _normalize_url_for_compare(exclude_url)
    for query in queries:
        if not query:
            continue
        used_queries.append(query)
        for post in core.search_wordpress_posts(site, query, count=count):
            link = str(post.get("link") or "").strip()
            post_id = str(post.get("id") or "").strip()
            if exclude_norm and _normalize_url_for_compare(link) == exclude_norm:
                continue
            dedupe_key = link or post_id
            if not dedupe_key or dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            content_html = _rendered_html(post.get("content"))
            candidates.append(
                {
                    "id": post.get("id"),
                    "title": _plain_text(post.get("title")),
                    "url": link,
                    "date": post.get("date", ""),
                    "status": post.get("status", ""),
                    "char_count": _char_count(content_html),
                    "content_html": content_html,
                    "matched_query": query,
                }
            )
            if len(candidates) >= count:
                return {"queries": used_queries, "candidates": candidates}
    return {"queries": used_queries, "candidates": candidates}


def _normalize_url_for_compare(url: str) -> str:
    url = str(url or "").strip()
    if not url:
        return ""
    url = url.split("#", 1)[0].rstrip("/")
    return url.lower()


def build_internal_link_prompt_from_candidate(payload: dict[str, Any]) -> dict[str, Any]:
    """選択した既存記事候補から、内部リンク判断プロンプトを組み立てる。"""
    core = _core()
    keyword = str(payload.get("keyword") or "").strip()
    topic_title = str(payload.get("topic_title") or "").strip()
    proposal = str(payload.get("proposal") or "").strip()
    parent_html = str(payload.get("parent_html") or "").strip()
    existing_post_url = str(payload.get("existing_post_url") or "").strip()
    existing_post_title = str(payload.get("existing_post_title") or "").strip()
    existing_post_html = str(payload.get("existing_post_html") or "").strip()
    item_index = int(payload.get("item_index") or 1)

    if not keyword:
        raise ValueError("キーワードが空です。")
    if not topic_title and proposal:
        topic_title = core.extract_topic_title(proposal)
    if not topic_title:
        raise ValueError("内部リンク案タイトルが空です。")
    if not proposal:
        proposal = f"- **リンク先トピック案:** {topic_title}"
    if not parent_html:
        raise ValueError("親記事HTMLが空です。")
    if not existing_post_url or not existing_post_title:
        raise ValueError("既存記事候補が選択されていません。")

    template = ""
    step10_file = getattr(core, "STEP10_FILE", "")
    if step10_file and Path(step10_file).exists():
        template = Path(step10_file).read_text(encoding="utf-8", errors="replace")

    if template:
        prompt = template
        prompt = re.sub(r"キーワード：[^\n]+", f"キーワード：{keyword}", prompt)
        prompt = prompt.replace("既存記事のURL:", f"既存記事のURL: {existing_post_url}")
        prompt = prompt.replace("既存記事のタイトル:", f"既存記事のタイトル: {existing_post_title}")
        prompt = prompt.replace(
            "既存記事のHTML全文（任意・精度向上用）：",
            f"既存記事のHTML全文（任意・精度向上用）：\n{existing_post_html or '（省略）'}",
        )
        prompt = prompt.replace(
            "（構成案で示された[内部リンク案]のブロック全体を、ここに貼り付けてください）",
            proposal,
        )
        prompt += f"\n\n=== 親記事本文（判断用・冒頭3,000文字） ===\n{parent_html[:3000]}"
    else:
        prompt = (
            f"【内部リンク案 {item_index}】{topic_title}\n\n"
            f"既存記事のURL: {existing_post_url}\n"
            f"既存記事のタイトル: {existing_post_title}\n\n"
            f"既存記事のHTML全文:\n{existing_post_html or '（省略）'}\n\n"
            f"内部リンク案:\n{proposal}\n\n"
            f"親記事本文（冒頭3,000文字）:\n{parent_html[:3000]}"
        )

    return {
        "keyword": keyword,
        "topic_title": topic_title,
        "item_index": item_index,
        "prompt": prompt,
        "existing_post_url": existing_post_url,
        "existing_post_title": existing_post_title,
    }


def _prepare_internal_link_job(payload: dict[str, Any]) -> dict[str, Any]:
    core = _core()
    site_key = str(payload.get("site_key") or "").strip()
    keyword = str(payload.get("keyword") or "").strip()
    topic_title = str(payload.get("topic_title") or "").strip()
    prompt = str(payload.get("prompt") or "").strip()
    item_index = int(payload.get("item_index") or 1)
    api_key_index = int(payload.get("api_key_index") or 0)

    if not keyword:
        raise ValueError("キーワードが空です。")
    if not topic_title:
        raise ValueError("内部リンク案タイトルが空です。")
    if not prompt:
        raise ValueError("内部リンク判断プロンプトが空です。")
    if site_key not in core.SITES_NORMAL:
        raise ValueError(f"未対応のサイトキーです: {site_key}")
    if api_key_index < 0 or api_key_index >= len(core.API_KEYS_NORMAL):
        raise ValueError(f"未対応のAPIキー番号です: {api_key_index}")

    return {
        "core": core,
        "selected_site": core.SITES_NORMAL[site_key],
        "keyword": keyword,
        "topic_title": topic_title,
        "prompt": prompt,
        "item_index": item_index,
        "api_key_index": api_key_index,
    }


def plan_internal_link_job(payload: dict[str, Any], log: LogFn) -> dict[str, Any]:
    prepared = _prepare_internal_link_job(payload)
    core = prepared["core"]
    log("【安全確認モード】内部リンク判断ジョブの実行計画\n")
    log("このモードではGemini APIを使わず、結果ファイルも作成しません。\n\n")
    log(f"対象サイト: {prepared['selected_site']['name']}\n")
    log(f"親記事キーワード: {prepared['keyword']}\n")
    log(f"内部リンク案: {prepared['topic_title']}\n")
    log(f"候補番号: {prepared['item_index']}\n")
    log(f"APIキー: {core.API_KEYS_NORMAL[prepared['api_key_index']]['name']}（本番実行時のみ使用）\n")
    log(f"プロンプト文字数: {len(prepared['prompt'])}\n")
    log("\n問題なければ、同じフォームで「本番実行」を選んでください。\n")
    return {"success": True, "dry_run": True}


def run_internal_link_job(payload: dict[str, Any], log: LogFn) -> dict[str, Any]:
    prepared = _prepare_internal_link_job(payload)
    core = prepared["core"]
    api_key = core.API_KEYS_NORMAL[prepared["api_key_index"]]["key"]
    log("オンライン 内部リンク判断ジョブ開始\n")
    path = core.run_step10_prompt_with_gemini(
        prepared["prompt"],
        prepared["selected_site"],
        prepared["keyword"],
        prepared["topic_title"],
        prepared["item_index"],
        api_key,
    )
    if path:
        log(f"内部リンク判断API結果: {path}\n")
        return {"success": True, "result_path": path}
    log("内部リンク判断API結果を作成できませんでした。\n")
    return {"success": False}
