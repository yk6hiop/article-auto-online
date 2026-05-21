import auto_post_unified as tool


def test_online_marriage_topic_drops_noisy_single_word():
    queries = tool.build_wp_search_queries(
        "オンライン結婚相談所の選び方と成功のコツ",
        "オンライン結婚相談所の選び方、カウンセラーとの連携方法、プロフィール作成のポイントなど。",
        max_queries=6,
    )
    assert queries[:5] == [
        "オンライン結婚相談所 選び方",
        "オンライン結婚相談所 コツ",
        "オンライン結婚相談所",
        "オンライン結婚相談所 プロフィール",
        "オンライン結婚相談所 カウンセラー",
    ]
    assert "コツ" not in queries
    assert "選び方" not in queries


def test_antenna_topic_keeps_multiple_specific_queries():
    queries = tool.build_wp_search_queries(
        "アンテナの種類と自宅に最適な選び方（地デジ・BS/CS・デザインアンテナ徹底解説）",
        "",
        max_queries=6,
    )
    assert queries[:4] == ["アンテナ 種類", "デザインアンテナ 八木式", "地デジ アンテナ", "BS CS アンテナ"]


def test_tv_error_topic_keeps_specific_queries():
    queries = tool.build_wp_search_queries(
        "テレビが映らない時に自分でできる初期診断と対処法",
        "E202以外のエラーコード、ケーブル接続の確認、テレビ設定のリセット。",
        max_queries=6,
    )
    assert queries[:2] == ["テレビ 映らない", "E202 エラー"]


def test_old_sequential_auto_search_wording_removed():
    with open("auto_post_unified.py", encoding="utf-8") as f:
        src = f.read()
    assert "Enterで候補を上から自動検索" not in src
    assert "候補で見つからないため次の検索語へ切替" not in src


if __name__ == "__main__":
    for name, func in sorted(globals().items()):
        if name.startswith("test_"):
            func()
            print(f"OK {name}")
