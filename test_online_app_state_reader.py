from __future__ import annotations

import json
from pathlib import Path

from online_app.state_reader import load_workflows


def _write_resume(path: Path, keyword: str, status: str, failed_step: str = ""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "target_input": keyword,
                "initial_instruction": "前提情報",
                "step_outputs": {"step01": "persona"},
                "final_content": "<h1>記事</h1><h2>見出し</h2><p>本文</p>" if status == "completed" else "",
                "log_history": [],
                "timestamp": "2026-05-20 12:00:00",
                "metadata": {
                    "resume_status": status,
                    "completed": status == "completed",
                    "failed_step": failed_step,
                    "site_name": "結びのマリッジ",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_load_workflows_marks_completed_and_interrupted(tmp_path):
    _write_resume(tmp_path / "resume_normal_リング ベル 休会_20260520_1200.json", "リング ベル 休会", "completed")
    _write_resume(
        tmp_path / "resume_normal_リング ベル プラン_20260520_1607.json",
        "リング ベル プラン",
        "interrupted",
        "step01_persona.txt",
    )

    items = load_workflows(tmp_path)

    assert len(items) == 2
    assert items[0].status in {"完了", "中断"}
    by_keyword = {item.keyword: item for item in items}
    assert by_keyword["リング ベル 休会"].completed is True
    assert by_keyword["リング ベル プラン"].status == "中断"
    assert "step01_persona.txt" in by_keyword["リング ベル プラン"].next_action
