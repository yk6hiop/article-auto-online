from __future__ import annotations

from pathlib import Path

import online_app.parent_service as parent_service


class _FakeCore:
    def __init__(self, root: Path):
        self.PROMPT_BASE_DIR = str(root / "prompts")
        self.RESEARCH_FILE = root / "research_LAPTOP.txt"
        self.SITES_NORMAL = {"marriage": {"name": "結びのマリッジ", "type": "normal"}}
        self.API_KEYS_NORMAL = [{"name": "テストキー", "key": "dummy"}]
        self.PROMPT_TYPES_PARENT_NORMAL = {"normal": {"1": {"path": "parent_standard"}}}

    def find_additions_folder(self, _base_dir):
        return str(Path(self.PROMPT_BASE_DIR) / "additions")

    def read_file(self, path):
        return Path(path).read_text(encoding="utf-8")


def test_plan_parent_article_job_does_not_call_real_generation(tmp_path):
    prompt_dir = tmp_path / "prompts" / "parent_standard"
    prompt_dir.mkdir(parents=True)
    for name in ["step01_persona.txt", "step02_research.txt", "step06_regenerate.txt"]:
        (prompt_dir / name).write_text("prompt", encoding="utf-8")

    additions_dir = tmp_path / "prompts" / "additions" / "結びのマリッジ"
    additions_dir.mkdir(parents=True)
    (additions_dir / "リングベル.txt").write_text("addition", encoding="utf-8")
    (tmp_path / "research_LAPTOP.txt").write_text("research", encoding="utf-8")

    original_core = parent_service._CORE
    parent_service._CORE = _FakeCore(tmp_path)
    try:
        logs: list[str] = []
        result = parent_service.plan_parent_article_job(
            {
                "site_key": "marriage",
                "keyword": "リング ベル プラン",
                "prompt_key": "1",
                "api_key_index": 0,
                "addition_file": "リングベル.txt",
                "dry_run": True,
            },
            logs.append,
        )
    finally:
        parent_service._CORE = original_core

    joined = "".join(logs)
    assert result["success"] is True
    assert result["dry_run"] is True
    assert result["step_count"] == 3
    assert "Gemini APIを使わず" in joined
    assert "step01_persona.txt" in joined
