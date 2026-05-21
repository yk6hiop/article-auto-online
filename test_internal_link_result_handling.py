import auto_post_unified as tool
import os
import tempfile


def test_warning_result_is_not_actionable_and_needs_child():
    text = """■■■ 内部リンク判断API実行結果 ■■■
内部リンク案: オンライン結婚相談所の選び方と成功のコツ

【警告】指定された既存記事への内部リンクは推奨しません。新規記事の作成が最適です。

推奨H1タイトル案：オンライン結婚相談所の選び方と成婚率を上げる成功のコツ
"""
    fields = tool._extract_internal_link_result_fields(text)
    assert fields["actionable"] is False
    assert fields["needs_child_article"] is True


def test_actionable_result_is_kept_for_apply_summary():
    text = """■■■ 内部リンク判断API実行結果 ■■■
内部リンク案: サンプル記事

【対象見出し】
<h2>料金を比較する前に確認したいこと</h2>

【この文章の直後に挿入】
<p>ここで基礎知識を確認しておくと判断しやすくなります。</p>

【挿入するHTMLコード】
<p>あわせて読みたい：<a href="https://example.com/sample/" target="_blank" rel="noopener">サンプル記事</a></p>
"""
    fields = tool._extract_internal_link_result_fields(text)
    assert fields["actionable"] is True
    assert fields["needs_child_article"] is False


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def test_manual_prompt_only_is_not_treated_as_api_done():
    with tempfile.TemporaryDirectory() as td:
        topic = "オンラインお見合い成功のコツ：初対面で好印象を与える会話術とマナー"
        keyword = "オンライン 結婚 相談 所 人気"
        prompt_path = os.path.join(td, "[子]internal_link_prompt_3_オンラインお見合い成功のコツ：_20260519_181734.txt")
        _write(prompt_path, "手動用プロンプト")

        manual_files, api_files = tool.find_existing_internal_link_artifacts(
            topic,
            keyword,
            3,
            base_dirs=(td,),
        )

        assert manual_files == [prompt_path]
        assert api_files == []


def test_new_internal_link_prompt_prefix_is_detected_as_manual_prompt():
    with tempfile.TemporaryDirectory() as td:
        topic = "オンラインお見合い成功のコツ：初対面で好印象を与える会話術とマナー"
        keyword = "オンライン 結婚 相談 所 人気"
        prompt_path = os.path.join(td, "[内部リンク]internal_link_prompt_3_オンラインお見合い成功のコツ：_20260520_010000.txt")
        _write(prompt_path, "手動用プロンプト")

        manual_files, api_files = tool.find_existing_internal_link_artifacts(
            topic,
            keyword,
            3,
            base_dirs=(td,),
        )

        assert manual_files == [prompt_path]
        assert api_files == []


def test_step9_10_save_uses_unified_output_and_parent_child_prefixes():
    with tempfile.TemporaryDirectory() as td:
        old_unified = tool.UNIFIED_OUTPUT_DIR
        try:
            tool.UNIFIED_OUTPUT_DIR = os.path.join(td, "作業結果")
            parent_path = tool._save_step9_10_result(
                "結びのマリッジ",
                "meta_entry_sheet",
                "オンライン 結婚 相談 所 人気",
                "parent",
                article_role="parent",
            )
            child_path = tool._save_step9_10_result(
                "結びのマリッジ",
                "meta_entry_sheet",
                "オンライン結婚相談所の無料相談",
                "child",
                article_role="child",
            )
        finally:
            tool.UNIFIED_OUTPUT_DIR = old_unified

        assert os.path.basename(parent_path).startswith("[親]メタ入稿用サマリー_")
        assert os.path.basename(child_path).startswith("[子]メタ入稿用サマリー_")
        assert os.path.join("作業結果", "結びのマリッジ") in parent_path
        assert os.path.exists(parent_path)
        assert os.path.exists(child_path)


def test_api_keys_for_site_is_available_for_step9_10_internal_link_route():
    assert tool.api_keys_for_site({"name": "結びのマリッジ", "type": "normal"}) == tool.API_KEYS_NORMAL
    assert tool.api_keys_for_site({"name": "もえちん", "type": "C"}) == tool.API_KEYS_MOECHIN
    assert tool.api_keys_for_site(None) == tool.API_KEYS_NORMAL


def test_meta_only_mode_does_not_build_internal_link_proposals():
    source = open("auto_post_unified.py", encoding="utf-8").read()
    assert "proposals = [] if (child_article or _skip_step10)" in source


def test_force_cleanup_repairs_heading_inside_empty_paragraph():
    broken = """<h1>タイトル</h1>
<h2>制度</h2>
<h3>休会中の費用と活動制限</h3>
<p><h3>休会条件と手続きの流れ</h3>
<p>休会を申し出る際には、いくつかの条件と手続きがあります。</p>
<ol><li>担当者へ相談</li></ol>
<h2>まとめ</h2><p>まとめです。</p>
<h2>FAQ</h2><p>FAQです。</p>"""
    fixed = tool.force_cleanup_html_parent(broken)
    assert "<p><h3>" not in fixed
    assert "<h3>休会条件と手続きの流れ</h3>" in fixed
    assert not tool._block_tag_paragraph_nesting_report(fixed)
    assert tool._is_valid_parent_html(fixed)


def test_parent_html_validity_rejects_block_tag_inside_paragraph():
    broken = """<h1>タイトル</h1>
<h2>一</h2><p>本文</p>
<h2>二</h2><p><h3>壊れた見出し</h3><p>本文</p>
<h2>三</h2><p>本文</p>"""
    assert tool._block_tag_paragraph_nesting_report(broken)
    assert not tool._is_valid_parent_html(broken)


def test_back_input_accepts_full_width_b():
    assert tool.is_back_input("b")
    assert tool.is_back_input("B")
    assert tool.is_back_input("ｂ")
    assert tool.is_back_input("Ｂ")
    assert not tool.is_back_input("button")


def test_author_box_is_removed_when_publishpress_shortcode_is_inserted():
    html = """<h1>タイトル</h1>
<p>導入文です。</p>
<div class="author-box">
    <p><strong>執筆者：結城 誠</strong></p>
    <p>オンライン婚活アドバイザー / 元結婚相談所カウンセラー</p>
</div>
<h2>本文見出し</h2>
<p>本文です。</p>"""
    fixed = tool.replace_author_block_with_shortcodes(html, "結びのマリッジ")
    assert "author-box" not in fixed
    assert "執筆者：結城 誠" not in fixed
    assert "publishpress_authors_box" in fixed


def test_low_authority_citation_links_are_unlinked_but_public_sources_remain():
    html = """<h1>タイトル</h1>
<h2>本文</h2>
<blockquote>
    <p>口コミの引用です。</p>
    <cite>出典: <a href="https://marri-marri.jp/media/marriage/ringbell/" target="_blank" rel="noopener">マリマリ</a></cite>
</blockquote>
<blockquote>
    <cite>出典: <a href="https://www.caa.go.jp/policies/policy/consumer_transaction/" target="_blank" rel="noopener">消費者庁</a></cite>
</blockquote>"""
    fixed, removed = tool._strip_low_authority_citation_links(html)
    assert removed == 1
    assert "https://marri-marri.jp/media/marriage/ringbell/" not in fixed
    assert "<cite>出典: マリマリ</cite>" in fixed
    assert "https://www.caa.go.jp/policies/policy/consumer_transaction/" in fixed


def test_api_result_detection_is_separate_from_manual_prompt():
    with tempfile.TemporaryDirectory() as td:
        topic = "オンラインお見合い成功のコツ：初対面で好印象を与える会話術とマナー"
        keyword = "オンライン 結婚 相談 所 人気"
        prompt_path = os.path.join(td, "[子]internal_link_prompt_3_オンラインお見合い成功のコツ：_20260519_181734.txt")
        api_path = os.path.join(td, "内部リンク判断API結果_3_オンライン 結婚 相談 所 人気_20260519_232400.txt")
        _write(prompt_path, "手動用プロンプト")
        _write(api_path, "API結果")

        manual_files, api_files = tool.find_existing_internal_link_artifacts(
            topic,
            keyword,
            3,
            base_dirs=(td,),
        )

        assert manual_files == [prompt_path]
        assert api_files == [api_path]


def test_apply_summary_keeps_multiple_actionable_api_results():
    text1 = """■■■ 内部リンク判断API実行結果 ■■■
内部リンク案: オンライン結婚相談所の無料相談

【対象見出し】
<h2>無料相談を使う前に</h2>

【この文章の直後に挿入】
<p>無料相談の前に確認します。</p>

【挿入するHTMLコード】
<p>あわせて読みたい：<a href="https://example.com/free/" target="_blank" rel="noopener">無料相談</a></p>
"""
    text3 = """■■■ 内部リンク判断API実行結果 ■■■
内部リンク案: オンラインお見合い成功のコツ

【対象見出し】
<h2>オンラインお見合いで失敗しないために</h2>

【この文章の直後に挿入】
<p>会話の準備も重要です。</p>

【挿入するHTMLコード】
<p>関連記事：<a href="https://example.com/talk/" target="_blank" rel="noopener">会話術</a></p>
"""
    with tempfile.TemporaryDirectory() as td:
        p1 = os.path.join(td, "内部リンク判断API結果_1_オンライン 結婚 相談 所 人気_1.txt")
        p3 = os.path.join(td, "内部リンク判断API結果_3_オンライン 結婚 相談 所 人気_3.txt")
        out = os.path.join(td, "summary.txt")
        _write(p1, text1)
        _write(p3, text3)

        old_save = tool._save_step9_10_result
        try:
            def fake_save(site_name, kind, keyword, content, article_role=""):
                _write(out, content)
                return out
            tool._save_step9_10_result = fake_save
            result = tool.save_internal_link_apply_summary(
                {"name": "結びのマリッジ"},
                "オンライン 結婚 相談 所 人気",
                [p1, p3],
            )
        finally:
            tool._save_step9_10_result = old_save

        assert result == out
        summary = open(out, encoding="utf-8").read()
        assert "無料相談" in summary
        assert "会話術" in summary
        assert "候補1" in summary
        assert "候補3" in summary


def test_apply_summary_lists_non_recommended_api_result_as_excluded():
    actionable = """■■■ 内部リンク判断API実行結果 ■■■
内部リンク案: オンライン結婚相談所の無料相談

【対象見出し】
<h2>無料相談を使う前に</h2>

【この文章の直後に挿入】
<p>無料相談の前に確認します。</p>

【挿入するHTMLコード】
<p>あわせて読みたい：<a href="https://example.com/free/" target="_blank" rel="noopener">無料相談</a></p>
"""
    non_recommended = """■■■ 内部リンク判断API実行結果 ■■■
内部リンク案: オンラインお見合い成功のコツ

【警告】指定された既存記事への内部リンクは推奨しません。新規記事の作成が最適です。

ご指定の既存記事は属性と検索意図が異なるため、今回の親記事からの内部リンク先としては不適切です。

推奨H1タイトル案: オンラインお見合い成功のコツ｜初対面で好印象を与える会話術
記事が持つべき独自の切り口: オンライン相談所利用者向けに、画面越しのお見合い準備と会話の進め方へ絞る。
"""
    with tempfile.TemporaryDirectory() as td:
        p1 = os.path.join(td, "内部リンク判断API結果_1_オンライン 結婚 相談 所 人気_1.txt")
        p3 = os.path.join(td, "内部リンク判断API結果_3_オンライン 結婚 相談 所 人気_3.txt")
        out = os.path.join(td, "summary.txt")
        _write(p1, actionable)
        _write(p3, non_recommended)

        old_save = tool._save_step9_10_result
        try:
            def fake_save(site_name, kind, keyword, content, article_role=""):
                _write(out, content)
                return out
            tool._save_step9_10_result = fake_save
            result = tool.save_internal_link_apply_summary(
                {"name": "結びのマリッジ"},
                "オンライン 結婚 相談 所 人気",
                [p1, p3],
            )
        finally:
            tool._save_step9_10_result = old_save

        assert result == out
        summary = open(out, encoding="utf-8").read()
        assert "無料相談" in summary
        assert "【最終貼り付け案に含めていない候補】" in summary
        assert "【候補3: 非推奨のため未反映】" in summary
        assert "オンラインお見合い成功のコツ" in summary
        assert "指定された既存記事への内部リンクは推奨しません" in summary
        assert "推奨H1タイトル案:" in summary
        assert "画面越しのお見合い準備" in summary


def test_apply_summary_repairs_result_when_anchor_is_not_in_parent_html():
    result_text = """■■■ 内部リンク判断API実行結果 ■■■
内部リンク案: リングベル復帰後、成婚を加速させるプロフィール戦略

【判断結果】既存記事への内部リンク設置が最適です。

【対象見出し】
<h2>復帰後の成婚戦略：休会期間を「最強の武器」に変える方法</h2>

【この文章の直後に挿入】
<p>休会は単なる休息ではなく、次なる飛躍のための準備期間です。</p>

【挿入するHTMLコード】
<p>あわせて読みたい：<a href="https://example.com/restart/" target="_blank" rel="noopener">復帰後の戦略</a></p>
"""
    parent_html = """
<h2>後悔しない！休会中の過ごし方と復帰後の成婚戦略</h2>
<h3>復帰後の成婚戦略：無理なく、賢く活動を再開する</h3>
<p>心身が回復し、自己分析が深まったら、いよいよ復帰後の成婚戦略を立てましょう。</p>
"""
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "内部リンク判断API結果_2_リング ベル 休会_1.txt")
        out = os.path.join(td, "summary.txt")
        _write(p, result_text)

        old_save = tool._save_step9_10_result
        try:
            def fake_save(site_name, kind, keyword, content, article_role=""):
                _write(out, content)
                return out
            tool._save_step9_10_result = fake_save
            tool.save_internal_link_apply_summary(
                {"name": "結びのマリッジ"},
                "リング ベル 休会",
                [p],
                parent_html=parent_html,
            )
        finally:
            tool._save_step9_10_result = old_save

        summary = open(out, encoding="utf-8").read()
        assert "【貼り付け案 1: 個別に挿入】" in summary
        assert "<h3>復帰後の成婚戦略：無理なく、賢く活動を再開する</h3>" in summary
        assert "<p>心身が回復し、自己分析が深まったら、いよいよ復帰後の成婚戦略を立てましょう。</p>" in summary
        assert "ツールが親記事本文内の実在する見出し・段落へ補正しました" in summary
        assert "元の対象見出し: <h2>復帰後の成婚戦略：休会期間を「最強の武器」に変える方法</h2>" in summary
        final_block = summary.split("【最終貼り付け案】", 1)[1].split("【最終貼り付け案に含めていない候補】", 1)[0]
        assert "復帰後の戦略" in final_block


def test_apply_summary_excludes_result_when_location_cannot_be_repaired():
    result_text = """■■■ 内部リンク判断API実行結果 ■■■
内部リンク案: リングベル復帰後、成婚を加速させるプロフィール戦略

【判断結果】既存記事への内部リンク設置が最適です。

【対象見出し】
<h2>復帰後の成婚戦略：休会期間を「最強の武器」に変える方法</h2>

【この文章の直後に挿入】
<p>休会は単なる休息ではなく、次なる飛躍のための準備期間です。</p>

【挿入するHTMLコード】
<p>あわせて読みたい：<a href="https://example.com/restart/" target="_blank" rel="noopener">復帰後の戦略</a></p>
"""
    parent_html = """
<h2>料金の確認</h2>
<p>月額料金と支払い方法を確認します。</p>
"""
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "内部リンク判断API結果_2_リング ベル 休会_1.txt")
        out = os.path.join(td, "summary.txt")
        _write(p, result_text)

        old_save = tool._save_step9_10_result
        try:
            def fake_save(site_name, kind, keyword, content, article_role=""):
                _write(out, content)
                return out
            tool._save_step9_10_result = fake_save
            tool.save_internal_link_apply_summary(
                {"name": "結びのマリッジ"},
                "リング ベル 休会",
                [p],
                parent_html=parent_html,
            )
        finally:
            tool._save_step9_10_result = old_save

        summary = open(out, encoding="utf-8").read()
        assert "貼り付け可能な内部リンク案はありません" in summary
        assert "親記事本文内に見つかりません" in summary


def test_apply_summary_puts_manual_wait_warning_near_final_plan():
    actionable = """■■■ 内部リンク判断API実行結果 ■■■
内部リンク案: オンライン結婚相談所の無料相談

【対象見出し】
<h2>無料相談を使う前に</h2>

【この文章の直後に挿入】
<p>無料相談の前に確認します。</p>

【挿入するHTMLコード】
<p>あわせて読みたい：<a href="https://example.com/free/" target="_blank" rel="noopener">無料相談</a></p>
"""
    with tempfile.TemporaryDirectory() as td:
        p1 = os.path.join(td, "内部リンク判断API結果_1_オンライン 結婚 相談 所 人気_1.txt")
        manual_path = os.path.join(td, "[子]internal_link_prompt_3_オンラインお見合い成功のコツ：_20260520_001146.txt")
        out = os.path.join(td, "summary.txt")
        _write(p1, actionable)
        _write(manual_path, "手動用")

        old_save = tool._save_step9_10_result
        try:
            def fake_save(site_name, kind, keyword, content, article_role=""):
                _write(out, content)
                return out
            tool._save_step9_10_result = fake_save
            result = tool.save_internal_link_apply_summary(
                {"name": "結びのマリッジ"},
                "オンライン 結婚 相談 所 人気",
                [p1],
                manual_wait_paths=[(3, "オンラインお見合い成功のコツ：初対面で好印象を与える会話術とマナー", manual_path, "手動用ファイルのみ作成")],
            )
        finally:
            tool._save_step9_10_result = old_save

        assert result == out
        summary = open(out, encoding="utf-8").read()
        final_pos = summary.index("【貼り付け案 1: 個別に挿入】")
        warning_pos = summary.index("【最終貼り付け案に含めていない候補】")
        api_files_pos = summary.index("【個別API結果ファイル】")
        assert final_pos < warning_pos < api_files_pos
        between = summary[final_pos:warning_pos]
        assert "================================================================================" not in between
        assert "【候補3: API判断なしのため未反映】" in summary
        assert "親記事に貼る最終案へ入れるには" in summary


def _patch_workflow_dirs(td):
    old = {
        "UNIFIED_OUTPUT_DIR": tool.UNIFIED_OUTPUT_DIR,
        "LEGACY_AI_STUDIO_PROMPTS_DIR": tool.LEGACY_AI_STUDIO_PROMPTS_DIR,
        "LEGACY_STEP9_10_RESULTS_DIR": tool.LEGACY_STEP9_10_RESULTS_DIR,
        "PARENT_LOGS": tool.PARENT_LOGS,
        "WORKFLOW_DONE_FILE": tool.WORKFLOW_DONE_FILE,
        "WORKFLOW_PROGRESS_FILE": tool.WORKFLOW_PROGRESS_FILE,
    }
    tool.UNIFIED_OUTPUT_DIR = os.path.join(td, "作業結果")
    tool.LEGACY_AI_STUDIO_PROMPTS_DIR = os.path.join(td, "ai_studio_prompts")
    tool.LEGACY_STEP9_10_RESULTS_DIR = os.path.join(td, "step9_10_results")
    tool.PARENT_LOGS = os.path.join(td, "親記事", "logs")
    tool.WORKFLOW_DONE_FILE = os.path.join(td, "resume_data", "workflow_done.json")
    tool.WORKFLOW_PROGRESS_FILE = os.path.join(td, "resume_data", "workflow_progress.json")
    for path in (
        tool.UNIFIED_OUTPUT_DIR,
        tool.LEGACY_AI_STUDIO_PROMPTS_DIR,
        tool.LEGACY_STEP9_10_RESULTS_DIR,
        tool.PARENT_LOGS,
        os.path.dirname(tool.WORKFLOW_DONE_FILE),
    ):
        os.makedirs(path, exist_ok=True)
    return old


def _restore_workflow_dirs(old):
    for key, value in old.items():
        setattr(tool, key, value)


def test_workflow_status_does_not_keep_pending_when_same_candidate_has_actionable_api_result():
    pending = """■ 子記事作成が必要な内部リンクトピック案
  親記事キーワード: オンライン 結婚 相談 所 人気

【トピック案 3】オンラインお見合い成功のコツ：初対面で好印象を与える会話術とマナー
判定理由: ユーザー操作: 対応する子記事をまだ作成していないためスキップ
"""
    actionable = """■■■ 内部リンク判断API実行結果 ■■■
内部リンク案: オンラインお見合い成功のコツ：初対面で好印象を与える会話術とマナー

【対象見出し】
<h2>オンラインお見合いで失敗しないために</h2>

【この文章の直後に挿入】
<p>会話の準備も重要です。</p>

【挿入するHTMLコード】
<p>関連記事：<a href="https://example.com/talk/" target="_blank" rel="noopener">会話術</a></p>
"""
    with tempfile.TemporaryDirectory() as td:
        old = _patch_workflow_dirs(td)
        try:
            site_dir = os.path.join(tool.UNIFIED_OUTPUT_DIR, "結びのマリッジ")
            os.makedirs(site_dir, exist_ok=True)
            _write(os.path.join(site_dir, "子記事作成リスト_オンライン 結婚 相談 所 人気_20260520_000000.txt"), pending)
            _write(os.path.join(site_dir, "内部リンク判断API結果_3_オンライン 結婚 相談 所 人気_20260520_000001.txt"), actionable)

            items = tool._workflow_collect_status_items(limit=10)
        finally:
            _restore_workflow_dirs(old)

        target = next(x for x in items if x["site"] == "結びのマリッジ")
        assert target["pending_topics"] == []
        assert target["manual_wait_count"] == 0
        assert target["next_action"] == "内部リンク結果を確認・親記事へ反映"


def test_workflow_status_does_not_hide_pending_only_because_candidate_number_matches():
    pending = """■ 子記事作成が必要な内部リンクトピック案
  親記事キーワード: オンライン 結婚 相談 所 人気

【トピック案 3】オンラインお見合い成功のコツ：初対面で好印象を与える会話術とマナー
判定理由: ユーザー操作: 対応する子記事をまだ作成していないためスキップ
"""
    actionable_different_topic_same_index = """■■■ 内部リンク判断API実行結果 ■■■
内部リンク案: 婚活プロフィール作成術：オンライン結婚相談所で「選ばれる」秘訣

【対象見出し】
<h2>プロフィールを整える</h2>

【この文章の直後に挿入】
<p>プロフィールは重要です。</p>

【挿入するHTMLコード】
<p>関連記事：<a href="https://example.com/profile/" target="_blank" rel="noopener">プロフィール作成術</a></p>
"""
    with tempfile.TemporaryDirectory() as td:
        old = _patch_workflow_dirs(td)
        try:
            site_dir = os.path.join(tool.UNIFIED_OUTPUT_DIR, "結びのマリッジ")
            os.makedirs(site_dir, exist_ok=True)
            _write(os.path.join(site_dir, "子記事作成リスト_オンライン 結婚 相談 所 人気_20260520_000000.txt"), pending)
            _write(os.path.join(site_dir, "内部リンク判断API結果_3_オンライン 結婚 相談 所 人気_20260520_000001.txt"), actionable_different_topic_same_index)

            items = tool._workflow_collect_status_items(limit=10)
        finally:
            _restore_workflow_dirs(old)

        target = next(x for x in items if x["site"] == "結びのマリッジ")
        assert target["pending_topics"] == ["オンラインお見合い成功のコツ：初対面で好印象を与える会話術とマナー"]


def test_workflow_status_keeps_pending_when_api_result_is_non_recommended():
    pending = """■ 子記事作成が必要な内部リンクトピック案
  親記事キーワード: オンライン 結婚 相談 所 人気

【トピック案 3】オンラインお見合い成功のコツ：初対面で好印象を与える会話術とマナー
判定理由: API判断: 選択した既存記事への内部リンクは非推奨
選択済み既存記事: 30代女性の結婚相談所プロフィール作成とお見合い会話術のコツ
選択済みURL: https://www.marriage-mr.com/marriage-strategy-30s-women/
"""
    non_recommended = """■■■ 内部リンク判断API実行結果 ■■■
内部リンク案: オンラインお見合い成功のコツ：初対面で好印象を与える会話術とマナー

【警告】指定された既存記事への内部リンクは推奨しません。新規記事の作成が最適です。

既存記事は30代女性のプロフィール作成が中心で、オンラインお見合いの会話術とは検索意図がずれます。
"""
    with tempfile.TemporaryDirectory() as td:
        old = _patch_workflow_dirs(td)
        try:
            site_dir = os.path.join(tool.UNIFIED_OUTPUT_DIR, "結びのマリッジ")
            os.makedirs(site_dir, exist_ok=True)
            _write(os.path.join(site_dir, "子記事作成リスト_オンライン 結婚 相談 所 人気_20260520_000000.txt"), pending)
            _write(os.path.join(site_dir, "内部リンク判断API結果_3_オンライン 結婚 相談 所 人気_20260520_000001.txt"), non_recommended)

            items = tool._workflow_collect_status_items(limit=10)
        finally:
            _restore_workflow_dirs(old)

        target = next(x for x in items if x["site"] == "結びのマリッジ")
        assert target["pending_topics"] == ["オンラインお見合い成功のコツ：初対面で好印象を与える会話術とマナー"]
        assert "既存記事非推奨1件" in target["next_action"]
        assert "30代女性の結婚相談所プロフィール作成" in target["pending_entries"][0]["existing_title"]


def test_internal_link_result_state_helper_distinguishes_actionable_and_child_needed():
    actionable = """【対象見出し】
<h2>見出し</h2>
【この文章の直後に挿入】
<p>本文です。</p>
【挿入するHTMLコード】
<p><a href="https://example.com/">関連記事</a></p>
"""
    non_recommended = """【警告】指定された既存記事への内部リンクは推奨しません。新規記事の作成が最適です。"""
    with tempfile.TemporaryDirectory() as td:
        p1 = os.path.join(td, "内部リンク判断API結果_1_kw.txt")
        p2 = os.path.join(td, "内部リンク判断API結果_2_kw.txt")
        _write(p1, actionable)
        _write(p2, non_recommended)

        assert tool._internal_link_result_state(tool._read_internal_link_result_fields_from_path(p1)) == "actionable"
        assert tool._internal_link_result_state(tool._read_internal_link_result_fields_from_path(p2)) == "needs_child"


def test_completion_attention_block_is_explicit_and_mentions_summary_file():
    lines = tool._format_step10_attention_event_lines(
        [
            {
                "type": "non_recommended",
                "num": 3,
                "title": "オンラインお見合い成功のコツ",
                "existing_title": "30代女性の結婚相談所プロフィール作成とお見合い会話術のコツ",
                "existing_url": "https://example.com/existing/",
                "source": r"G:\tmp\内部リンク判断API結果_3_kw.txt",
            },
            {
                "type": "manual_wait",
                "num": 2,
                "title": "婚活プロフィール作成術",
                "reason": "手動用ファイルのみ作成",
                "source": r"G:\tmp\[子]internal_link_prompt_2.txt",
            },
        ],
        r"G:\tmp\内部リンク貼り付け指示まとめ_kw.txt",
    )
    text = "\n".join(lines)
    assert "最終貼り付け案に入っていない内部リンク候補があります" in text
    assert "既存記事への内部リンクは非推奨" in text
    assert "API判断結果がないため未反映" in text
    assert "内部リンク貼り付け指示まとめ_kw.txt" in text


def test_prefill_child_candidate_does_not_suggest_unrelated_child_from_same_run():
    candidates = tool._rank_prefill_child_posts_for_topic(
        "婚活プロフィール作成術：オンライン結婚相談所で「選ばれる」秘訣",
        "プロフィール写真の選び方、自己紹介文の書き方、希望条件の伝え方を解説する新規記事作成を推奨する。",
        [
            {
                "keyword": "オンライン結婚相談所の「無料相談」を最大限に活用する方法",
                "html": "無料相談の準備、質問リスト、比較検討のチェックポイントを解説します。",
                "url": "https://example.com/free-consultation/",
            }
        ],
    )
    assert candidates == []


if __name__ == "__main__":
    for name, func in sorted(globals().items()):
        if name.startswith("test_"):
            func()
            print(f"OK {name}")
