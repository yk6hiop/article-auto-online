from pathlib import Path

from online_app.parent_service import plan_parent_article_job


def test_parent_plan_can_read_resume_data(tmp_path: Path):
    resume_path = tmp_path / "resume_normal_test_20260521_1100.json"
    resume_path.write_text(
        """{
  "target_input": "オンライン版 再開テスト",
  "initial_instruction": "前提情報: 再開テスト",
  "step_outputs": {"step01": "済み"},
  "final_content": "",
  "log_history": [],
  "metadata": {
    "resume_status": "interrupted",
    "site_choice": "2",
    "prompt_key": "1",
    "addition_path": ""
  }
}""",
        encoding="utf-8",
    )
    logs: list[str] = []

    result = plan_parent_article_job(
        {
            "resume_path": str(resume_path),
            "api_key_index": 0,
            "dry_run": True,
        },
        logs.append,
    )

    assert result["success"] is True
    assert result["keyword"] == "オンライン版 再開テスト"
    assert "再開データ" in "".join(logs)
