import builtins
import os
import tempfile

import auto_post_unified as tool


class Patch:
    def __init__(self, **changes):
        self.changes = changes
        self.old = {}

    def __enter__(self):
        for name, value in self.changes.items():
            owner, attr = name.rsplit(".", 1)
            obj = builtins if owner == "builtins" else tool
            self.old[name] = getattr(obj, attr)
            setattr(obj, attr, value)
        return self

    def __exit__(self, exc_type, exc, tb):
        for name, value in reversed(list(self.old.items())):
            owner, attr = name.rsplit(".", 1)
            obj = builtins if owner == "builtins" else tool
            setattr(obj, attr, value)


def test_moechin_parent_passes_post_url_to_step9_10_after_post():
    captured = {}

    def fake_arrow(title, options, allow_back=False, context=None, back_label="前の画面へ戻る"):
        if "リサーチファイル内のURL" in title:
            return 1
        if "完了:" in title:
            return 0
        return 0

    def fake_run_parent(*args, **kwargs):
        return True, "<h1>テスト</h1><h2>本文</h2><p>本文です。</p>", [], {"step03": ""}

    def fake_step9_10(**kwargs):
        captured.update(kwargs)

    with Patch(
        **{
            "tool.load_resume_data": lambda path: None,
            "tool.select_api_key": lambda keys: "dummy-api-key",
            "tool.find_additions_folder": lambda base: None,
            "tool.collect_competitor_urls": lambda keyword, num_results=10: "",
            "tool.open_file_for_user": lambda path: None,
            "tool.read_file": lambda path: "",
            "tool.arrow_menu": fake_arrow,
            "tool.check_urls_in_research": lambda text: text,
            "tool.run_article_generation_parent": fake_run_parent,
            "tool.print_article_output_summary": lambda *args, **kwargs: None,
            "tool.extract_internal_links": lambda step_outputs: "",
            "tool.check_keyword_density": lambda *args, **kwargs: None,
            "tool.validate_final_html_links": lambda html, label: (html, []),
            "tool.post_to_wordpress": lambda *args, **kwargs: "https://example.com/?p=123",
            "tool.save_log_parent": lambda *args, **kwargs: None,
            "tool.run_step9_10": fake_step9_10,
            "builtins.input": lambda prompt="": "テストKW",
        }
    ):
        tool.run_mode_parent_moechin()

    assert captured["prefill_keyword"] == "テストKW"
    assert captured["prefill_post_url"] == "https://example.com/?p=123"


def test_parent_resume_restores_site_prompt_and_addition_without_reasking():
    seen_titles = []
    resume_data = {
        "timestamp": "2026-05-20 10:00:00",
        "target_input": "再開KW",
        "initial_instruction": "前提情報",
        "metadata": {
            "site_choice": "2",
            "prompt_key": "1",
            "prompt_sub_path": "dummy",
            "addition_path": "will-be-filled",
            "suppress_scroll_cta": False,
        },
    }

    with tempfile.TemporaryDirectory() as td:
        add_path = os.path.join(td, "addition.txt")
        with open(add_path, "w", encoding="utf-8") as f:
            f.write("足し算")
        resume_data["metadata"]["addition_path"] = add_path

        def fake_arrow(title, options, allow_back=False, context=None, back_label="前の画面へ戻る"):
            seen_titles.append(title)
            forbidden = ("サイト選択", "プロンプト選択", "足し算ファイル選択")
            assert not any(x in title for x in forbidden), title
            return 1

        def fake_run_parent(*args, **kwargs):
            assert kwargs.get("resume_metadata") is not None
            return False, "", [], {}

        with Patch(
            **{
                "tool.load_resume_data": lambda path: resume_data,
                "tool.select_api_key": lambda keys: "dummy-api-key",
                "tool.arrow_menu": fake_arrow,
                "tool.run_article_generation_parent": fake_run_parent,
                "tool.save_log_parent": lambda *args, **kwargs: None,
                "builtins.input": lambda prompt="": "y",
            }
        ):
            tool.run_mode_parent_normal()

    assert seen_titles == []


def test_child_prefill_filters_done_topics_before_creation_menu():
    topics_seen = {}

    def fake_multi(title, options, default_checked=None):
        topics_seen["options"] = list(options)
        return list(range(len(options)))

    with Patch(
        **{
            "tool._workflow_completed_child_topic_norms": lambda site, parent: {
                tool._result_history_normalize_keyword("既存記事で対応済みトピック")
            },
            "tool.arrow_menu": lambda *args, **kwargs: 0,
            "tool.arrow_menu_multiselect": fake_multi,
            "tool.select_api_key": lambda keys: None,
            "builtins.input": lambda prompt="": "",
        }
    ):
        tool.run_mode_child_normal(
            prefill_site_key="2",
            prefill_parent_keyword="親KW",
            prefill_topics=[
                "既存記事で対応済みトピック",
                "これから作るトピック",
            ],
        )

    assert topics_seen["options"] == ["これから作るトピック"]


def test_step9_10_does_not_ask_internal_link_site_again():
    with open("auto_post_unified.py", encoding="utf-8") as f:
        src = f.read()
    assert "内部リンク先を検索するサイトを選択" not in src
    assert "内部リンク検索サイト:" in src


def test_parent_resume_status_distinguishes_completed_and_interrupted():
    interrupted_empty = {
        "target_input": "リング ベル プラン",
        "initial_instruction": "前提情報",
        "step_outputs": {},
        "final_content": "",
        "metadata": {"resume_status": "interrupted", "completed": False},
    }
    assert tool._is_interrupted_parent_resume(interrupted_empty)
    assert not tool._is_completed_parent_resume(interrupted_empty)

    completed_new = {
        "target_input": "リング ベル 休会",
        "initial_instruction": "前提情報",
        "step_outputs": {"step06": "<h1>完了</h1><h2>本文1</h2><p>本文です。</p><h2>本文2</h2><p>本文です。</p><h2>本文3</h2><p>本文です。</p>"},
        "final_content": "<h1>完了</h1><h2>本文1</h2><p>本文です。</p><h2>本文2</h2><p>本文です。</p><h2>本文3</h2><p>本文です。</p>",
        "metadata": {"resume_status": "completed", "completed": True},
    }
    assert tool._is_completed_parent_resume(completed_new)
    assert not tool._is_interrupted_parent_resume(completed_new)

    completed_legacy = {
        "target_input": "旧完了",
        "initial_instruction": "前提情報",
        "step_outputs": {"step06": "<h1>完了</h1><h2>本文1</h2><p>本文です。</p><h2>本文2</h2><p>本文です。</p><h2>本文3</h2><p>本文です。</p>"},
        "final_content": "<h1>完了</h1><h2>本文1</h2><p>本文です。</p><h2>本文2</h2><p>本文です。</p><h2>本文3</h2><p>本文です。</p>",
    }
    assert tool._is_completed_parent_resume(completed_legacy)
    assert not tool._is_interrupted_parent_resume(completed_legacy)

    partial_legacy = {
        "target_input": "途中",
        "initial_instruction": "前提情報",
        "step_outputs": {"step01": "途中出力"},
        "final_content": "途中出力",
    }
    assert tool._is_interrupted_parent_resume(partial_legacy)
    assert not tool._is_completed_parent_resume(partial_legacy)


def test_completed_parent_resume_is_not_offered_for_generation_resume():
    prompts = []
    resume_data = {
        "timestamp": "2026-05-20 11:59:55",
        "target_input": "リング ベル 休会",
        "initial_instruction": "前提情報",
        "step_outputs": {"step06": "<h1>完了</h1><h2>本文1</h2><p>本文です。</p><h2>本文2</h2><p>本文です。</p><h2>本文3</h2><p>本文です。</p>"},
        "final_content": "<h1>完了</h1><h2>本文1</h2><p>本文です。</p><h2>本文2</h2><p>本文です。</p><h2>本文3</h2><p>本文です。</p>",
        "metadata": {"resume_status": "completed", "completed": True},
    }

    def fake_input(prompt=""):
        prompts.append(prompt)
        if "【キーワード】" in prompt:
            return "新規KW"
        return "y"

    def fake_arrow(title, options, allow_back=False, context=None, back_label="前の画面へ戻る"):
        if "リサーチファイル内のURL" in title:
            return 1
        return 0

    def fake_run_parent(*args, **kwargs):
        assert kwargs.get("resume_data") is None
        assert args[4] == "新規KW"
        return False, "", [], {}

    with Patch(
        **{
            "tool.load_resume_data": lambda path: resume_data,
            "tool.select_api_key": lambda keys: "dummy-api-key",
            "tool.arrow_menu": fake_arrow,
            "tool.select_addition_file": lambda site: None,
            "tool.collect_competitor_urls": lambda keyword, num_results=10: "",
            "tool.open_file_for_user": lambda path: None,
            "tool.read_file": lambda path: "",
            "tool.check_urls_in_research": lambda text: text,
            "tool.run_article_generation_parent": fake_run_parent,
            "tool.save_log_parent": lambda *args, **kwargs: None,
            "builtins.input": fake_input,
        }
    ):
        tool.run_mode_parent_normal()

    assert not any("続きから再開" in p for p in prompts)


def test_parent_generation_saves_current_keyword_when_first_step_fails():
    saved = {}

    class DummyChats:
        def create(self, model=None, config=None):
            return object()

    class DummyClient:
        def __init__(self, api_key=None):
            self.chats = DummyChats()

    class DummyGenai:
        Client = DummyClient

    with tempfile.TemporaryDirectory() as td:
        prompt_path = os.path.join(td, "step01_persona.txt")
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write("step01")

        def fake_save(resume_file, target_input, initial_instruction, step_outputs, final_content, log_history, metadata=None):
            saved["target_input"] = target_input
            saved["initial_instruction"] = initial_instruction
            saved["step_outputs"] = dict(step_outputs)
            saved["final_content"] = final_content
            saved["metadata"] = dict(metadata or {})

        with Patch(
            **{
                "tool._load_genai": lambda: None,
                "tool.genai": DummyGenai,
                "tool._send_message_with_retry": lambda *args, **kwargs: (_ for _ in ()).throw(Exception("503 UNAVAILABLE")),
                "tool.save_resume_data": fake_save,
            }
        ):
            success, _, _, _ = tool.run_article_generation_parent(
                "dummy-api-key",
                "前提情報",
                [{"path": prompt_path, "type": "normal"}],
                {"name": "結びのマリッジ", "type": "B"},
                "リング ベル プラン",
                resume_data=None,
                resume_metadata={"site_choice": "2", "prompt_key": "1"},
            )

    assert success is False
    assert saved["target_input"] == "リング ベル プラン"
    assert saved["initial_instruction"] == "前提情報"
    assert saved["step_outputs"] == {}
    assert saved["metadata"]["resume_status"] == "interrupted"
    assert saved["metadata"]["completed"] is False
    assert saved["metadata"]["failed_step"] == "step01_persona.txt"


if __name__ == "__main__":
    tests = [
        test_moechin_parent_passes_post_url_to_step9_10_after_post,
        test_parent_resume_restores_site_prompt_and_addition_without_reasking,
        test_child_prefill_filters_done_topics_before_creation_menu,
        test_step9_10_does_not_ask_internal_link_site_again,
        test_parent_resume_status_distinguishes_completed_and_interrupted,
        test_completed_parent_resume_is_not_offered_for_generation_resume,
        test_parent_generation_saves_current_keyword_when_first_step_fails,
    ]
    for test in tests:
        test()
        print(f"OK {test.__name__}")
