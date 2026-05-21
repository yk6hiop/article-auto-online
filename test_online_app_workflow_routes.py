from __future__ import annotations

from fastapi.testclient import TestClient

import online_app.app as app_module
from online_app.state_reader import WorkflowItem


def test_workflows_route_shows_next_action_links():
    original_load_workflows = app_module.load_workflows
    original_get_parent_options = app_module.get_parent_options
    app_module.load_workflows = lambda: [
        WorkflowItem(
            id="resume_normal_test",
            kind="normal",
            keyword="リング ベル 休会",
            status="完了",
            next_action="メタ情報・内部リンク判断へ進む",
            timestamp="2026-05-20 12:00:00",
            path="resume_normal_test.json",
            site_name="結びのマリッジ",
            completed=True,
        )
    ]
    app_module.get_parent_options = lambda: {
        "sites": [{"key": "2", "name": "結びのマリッジ"}],
        "api_keys": [],
        "additions": [],
    }
    try:
        client = TestClient(app_module.app)
        response = client.get("/workflows")
    finally:
        app_module.load_workflows = original_load_workflows
        app_module.get_parent_options = original_get_parent_options

    assert response.status_code == 200
    assert "/meta?site_key=2&keyword=%E3%83%AA%E3%83%B3%E3%82%B0+%E3%83%99%E3%83%AB+%E4%BC%91%E4%BC%9A" in response.text
    assert "/internal-link?site_key=2&keyword=%E3%83%AA%E3%83%B3%E3%82%B0+%E3%83%99%E3%83%AB+%E4%BC%91%E4%BC%9A" in response.text
