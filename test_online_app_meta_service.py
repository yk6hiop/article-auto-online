from __future__ import annotations

from pathlib import Path

import online_app.meta_service as meta_service


class _FakeCore:
    def __init__(self):
        self.SITES_NORMAL = {"2": {"name": "結びのマリッジ", "type": "A"}}
        self.API_KEYS_NORMAL = [{"name": "テストキー", "key": "dummy"}]
        self.STEP9_META_FILE = "step9_meta.txt"

    def read_file(self, _path):
        return "メタ情報テンプレート"

    def build_live_site_context_for_step9(self, _site):
        return "カテゴリ候補"


def test_plan_meta_job_does_not_call_real_generation():
    original_core = meta_service._CORE
    meta_service._CORE = _FakeCore()
    try:
        logs: list[str] = []
        result = meta_service.plan_meta_job(
            {
                "site_key": "2",
                "keyword": "リング ベル プラン",
                "post_url": "https://example.com/?p=1",
                "api_key_index": 0,
                "article_html": "<h1>記事</h1><h2>見出し</h2><p>本文</p>",
                "dry_run": True,
            },
            logs.append,
        )
    finally:
        meta_service._CORE = original_core

    joined = "".join(logs)
    assert result["success"] is True
    assert result["dry_run"] is True
    assert "Gemini APIを使わず" in joined
    assert "メタ生成プロンプト文字数" in joined
    assert "WordPress自動反映: v0では行いません" in joined


def test_run_meta_job_uses_non_interactive_manual_mode():
    class _RunCore(_FakeCore):
        def run_step9_prompt_with_gemini(self, *args, **kwargs):
            self.kwargs = kwargs
            return {
                "result_path": "meta_result.txt",
                "entry_sheet_path": "entry.txt",
                "apply_message": "自動反映なし",
            }

    fake = _RunCore()
    original_core = meta_service._CORE
    meta_service._CORE = fake
    try:
        logs: list[str] = []
        result = meta_service.run_meta_job(
            {
                "site_key": "2",
                "keyword": "リング ベル プラン",
                "post_url": "https://example.com/?p=1",
                "api_key_index": 0,
                "article_html": "<h1>記事</h1><p>本文</p>",
                "dry_run": False,
            },
            logs.append,
        )
    finally:
        meta_service._CORE = original_core

    assert result["success"] is True
    assert fake.kwargs["rankmath_mode"] == "manual"
