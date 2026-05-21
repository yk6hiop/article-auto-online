from __future__ import annotations

from auto_post_unified import force_cleanup_html_child, force_cleanup_html_parent


def test_parent_cleanup_repairs_nested_heading_tags():
    html = "<h1>テスト</h1><h2>概要</h2><h3><h3>1. テストの目的</h3><p>本文</p>"

    cleaned = force_cleanup_html_parent(html)

    assert "<h3><h3>" not in cleaned
    assert "<h3>1. テストの目的</h3>" in cleaned


def test_child_cleanup_repairs_nested_heading_tags():
    html = "<h1>テスト</h1><h2>概要</h2><h3><h3>子記事の見出し</h3><p>本文</p>"

    cleaned = force_cleanup_html_child(html)

    assert "<h3><h3>" not in cleaned
    assert "<h3>子記事の見出し</h3>" in cleaned
