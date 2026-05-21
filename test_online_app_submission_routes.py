from __future__ import annotations

from fastapi.testclient import TestClient

from online_app.app import app


def test_parent_and_child_forms_submit_with_post():
    client = TestClient(app)

    parent_response = client.post(
        "/parent/jobs",
        data={
            "execution_mode": "dry_run",
            "site_key": "2",
            "api_key_index": "0",
            "keyword": "オンライン版POSTテスト",
            "prompt_key": "1",
            "addition_file": "",
            "competitor_urls": "https://example.com",
            "research_content": "research",
        },
        follow_redirects=False,
    )
    child_response = client.post(
        "/child/jobs",
        data={
            "execution_mode": "dry_run",
            "site_key": "2",
            "api_key_index": "0",
            "prompt_key": "1",
            "topics": "子記事テスト",
        },
        follow_redirects=False,
    )

    assert parent_response.status_code == 303
    assert parent_response.headers["location"].startswith("/jobs/")
    assert child_response.status_code == 303
    assert child_response.headers["location"].startswith("/jobs/")
