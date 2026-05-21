from __future__ import annotations

from fastapi.testclient import TestClient

import online_app.diagnostics as diagnostics
from online_app.app import app


class _FakeCore:
    msvcrt = None
    PROMPT_BASE_DIR = "."
    GOOGLE_DRIVE_BASE = "."
    API_KEYS_NORMAL = [{"name": "テスト", "key": "AIzaDummy"}]
    API_KEYS_MOECHIN = []
    SITES_ALL = {
        "2": {
            "name": "結びのマリッジ",
            "url": "https://example.test",
            "user": "user",
            "pass": "pass",
        }
    }
    MODEL_PARENT = "gemini-parent"
    MODEL_CHILD = "gemini-child"


def test_collect_diagnostics_reports_hardcoded_key_warning():
    original_core = diagnostics._CORE
    diagnostics._CORE = _FakeCore()
    try:
        result = diagnostics.collect_diagnostics()
    finally:
        diagnostics._CORE = original_core

    messages = "\n".join(item.message for item in result["items"])
    assert result["warnings"] >= 1
    assert "ハードコード検出" in messages


def test_diagnostics_route_renders():
    client = TestClient(app)
    response = client.get("/diagnostics")

    assert response.status_code == 200
    assert "設定診断" in response.text
