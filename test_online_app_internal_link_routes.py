from __future__ import annotations

from fastapi.testclient import TestClient

import online_app.internal_link_service as internal_link_service
from online_app.app import app


class _FakeCore:
    SITES_NORMAL = {"2": {"name": "結びのマリッジ", "type": "normal"}}
    API_KEYS_NORMAL = [{"name": "テストキー", "key": "dummy"}]
    STEP10_FILE = ""

    def build_wp_search_queries(self, topic_title, proposal_text="", max_queries=6):
        return ["婚活疲れ"]

    def search_wordpress_posts(self, site_config, search_term, count=30):
        return [
            {
                "id": 1,
                "title": {"rendered": "婚活疲れを乗り越える記事"},
                "link": "https://example.test/article/",
                "date": "2026-05-20",
                "status": "publish",
                "content": {"rendered": "<p>候補本文</p>"},
            }
        ]

    def extract_topic_title(self, proposal):
        return "婚活疲れを乗り越える記事"


def test_internal_link_search_route_shows_candidate_selection():
    original_core = internal_link_service._CORE
    internal_link_service._CORE = _FakeCore()
    try:
        client = TestClient(app)
        response = client.post(
            "/internal-link/search",
            data={
                "site_key": "2",
                "keyword": "リング ベル 休会",
                "item_index": "1",
                "topic_title": "婚活疲れを乗り越える記事",
                "proposal": "- **リンク先トピック案:** 婚活疲れを乗り越える記事",
                "parent_html": "<h1>親記事</h1><p>親本文</p>",
                "search_query": "",
            },
        )
    finally:
        internal_link_service._CORE = original_core

    assert response.status_code == 200
    assert "婚活疲れを乗り越える記事" in response.text
    assert "/internal-link/from-candidate/jobs" in response.text
