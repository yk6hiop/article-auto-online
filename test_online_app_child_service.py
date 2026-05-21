from __future__ import annotations

from pathlib import Path

import online_app.child_service as child_service


class _FakeCore:
    def __init__(self, root: Path):
        self.PROMPT_BASE_DIR = str(root / "prompts")
        self.SITES_NORMAL = {"2": {"name": "結びのマリッジ", "type": "A"}}
        self.API_KEYS_NORMAL = [{"name": "テストキー", "key": "dummy"}]
        self.PROMPT_TYPES_CHILD_NORMAL = {"A": {"1": {"name": "標準（子記事）", "path": "child_standard"}}}


def test_plan_child_article_job_does_not_call_real_generation(tmp_path):
    prompt_dir = tmp_path / "prompts" / "child_standard"
    prompt_dir.mkdir(parents=True)
    for name in ["step01_outline.txt", "step02_write.txt", "step03_review.txt"]:
        (prompt_dir / name).write_text("prompt", encoding="utf-8")

    original_core = child_service._CORE
    child_service._CORE = _FakeCore(tmp_path)
    try:
        logs: list[str] = []
        result = child_service.plan_child_article_job(
            {
                "site_key": "2",
                "topics": "リングベル復帰後のプロフィール戦略\nカウンセラー活用術",
                "prompt_key": "1",
                "api_key_index": 0,
                "dry_run": True,
            },
            logs.append,
        )
    finally:
        child_service._CORE = original_core

    joined = "".join(logs)
    assert result["success"] is True
    assert result["dry_run"] is True
    assert result["topic_count"] == 2
    assert "Gemini APIを使わず" in joined
    assert "step02_write.txt" in joined
