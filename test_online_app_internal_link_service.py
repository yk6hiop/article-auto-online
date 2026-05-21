from __future__ import annotations

import online_app.internal_link_service as internal_link_service


class _FakeCore:
    def __init__(self):
        self.SITES_NORMAL = {"2": {"name": "結びのマリッジ", "type": "A"}}
        self.API_KEYS_NORMAL = [{"name": "テストキー", "key": "dummy"}]
        self.STEP10_FILE = ""

    def build_wp_search_queries(self, topic_title, proposal_text="", max_queries=6):
        return ["婚活疲れ", "プロフィール"][:max_queries]

    def search_wordpress_posts(self, site_config, search_term, count=30):
        if search_term == "婚活疲れ":
            return [
                {
                    "id": 10,
                    "title": {"rendered": "婚活疲れを乗り越える方法"},
                    "link": "https://example.test/burnout/",
                    "date": "2026-05-20",
                    "status": "publish",
                    "content": {"rendered": "<p>本文テスト</p>"},
                }
            ]
        return []

    def extract_topic_title(self, proposal):
        return "婚活疲れを乗り越える方法"


def test_plan_internal_link_job_does_not_call_real_generation():
    original_core = internal_link_service._CORE
    internal_link_service._CORE = _FakeCore()
    try:
        logs: list[str] = []
        result = internal_link_service.plan_internal_link_job(
            {
                "site_key": "2",
                "keyword": "リング ベル プラン",
                "topic_title": "復帰後プロフィール戦略",
                "prompt": "内部リンク判断プロンプト",
                "item_index": 1,
                "api_key_index": 0,
                "dry_run": True,
            },
            logs.append,
        )
    finally:
        internal_link_service._CORE = original_core

    joined = "".join(logs)
    assert result["success"] is True
    assert result["dry_run"] is True
    assert "Gemini APIを使わず" in joined
    assert "プロンプト文字数" in joined


def test_search_internal_link_candidates_uses_wordpress_search():
    original_core = internal_link_service._CORE
    internal_link_service._CORE = _FakeCore()
    try:
        result = internal_link_service.search_internal_link_candidates(
            "2",
            "婚活疲れを乗り越える方法",
            "",
            "",
        )
    finally:
        internal_link_service._CORE = original_core

    assert result["queries"][0] == "婚活疲れ"
    assert result["candidates"][0]["title"] == "婚活疲れを乗り越える方法"
    assert result["candidates"][0]["url"] == "https://example.test/burnout/"
    assert result["candidates"][0]["char_count"] == 5


def test_search_internal_link_candidates_excludes_parent_url():
    original_core = internal_link_service._CORE
    internal_link_service._CORE = _FakeCore()
    try:
        result = internal_link_service.search_internal_link_candidates(
            "2",
            "婚活疲れを乗り越える方法",
            "",
            "",
            exclude_url="https://example.test/burnout",
        )
    finally:
        internal_link_service._CORE = original_core

    assert result["candidates"] == []


def test_build_internal_link_prompt_from_candidate_contains_parent_and_candidate():
    original_core = internal_link_service._CORE
    internal_link_service._CORE = _FakeCore()
    try:
        result = internal_link_service.build_internal_link_prompt_from_candidate(
            {
                "keyword": "リング ベル 休会",
                "topic_title": "婚活疲れを乗り越える方法",
                "proposal": "- **リンク先トピック案:** 婚活疲れを乗り越える方法",
                "parent_html": "<h1>親記事</h1><p>親本文</p>",
                "existing_post_url": "https://example.test/burnout/",
                "existing_post_title": "婚活疲れを乗り越える方法",
                "existing_post_html": "<p>候補本文</p>",
                "item_index": 2,
            }
        )
    finally:
        internal_link_service._CORE = original_core

    assert result["item_index"] == 2
    assert "既存記事のURL: https://example.test/burnout/" in result["prompt"]
    assert "親記事本文" in result["prompt"]
    assert "候補本文" in result["prompt"]
