from __future__ import annotations

import html
import json
import urllib.parse
from pathlib import Path

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, RedirectResponse
    from pydantic import BaseModel
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "online_appを起動するには FastAPI が必要です。"
        " `pip install -r online_app/requirements.txt` を実行してください。"
    ) from exc

from .job_store import create_job, get_job, list_jobs, mark_stale_running_jobs
from .child_service import get_child_options
from .diagnostics import collect_diagnostics
from .deployment_readiness import collect_deployment_readiness
from .internal_link_service import (
    build_internal_link_prompt_from_candidate,
    get_internal_link_options,
    search_internal_link_candidates,
)
from .meta_service import get_meta_options
from .parent_service import get_parent_options
from .state_reader import WorkflowItem, load_workflows
from .worker import start_worker


app = FastAPI(title="記事自動生成ツール オンライン版 v0")


class ParentArticleRequest(BaseModel):
    site_key: str
    keyword: str
    prompt_key: str = "1"
    addition_file: str | None = None
    api_key_index: int = 0
    competitor_urls: str = ""
    research_content: str = ""
    resume_path: str = ""
    dry_run: bool = True


class ChildArticleRequest(BaseModel):
    site_key: str
    topics: str
    prompt_key: str = "1"
    api_key_index: int = 0
    dry_run: bool = True


class MetaEntryRequest(BaseModel):
    site_key: str
    keyword: str
    article_html: str
    post_url: str = ""
    api_key_index: int = 0
    dry_run: bool = True


class InternalLinkRequest(BaseModel):
    site_key: str
    keyword: str
    topic_title: str
    prompt: str
    item_index: int = 1
    api_key_index: int = 0
    dry_run: bool = True


class InternalLinkSearchRequest(BaseModel):
    site_key: str
    topic_title: str
    proposal: str = ""
    search_query: str = ""
    exclude_url: str = ""


@app.on_event("startup")
def _startup():
    start_worker()


def _page(title: str, body: str) -> HTMLResponse:
    html_doc = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; background: #f6f7f9; color: #1f2933; }}
    header {{ background: #102a43; color: #fff; padding: 16px 24px; }}
    main {{ padding: 24px; max-width: 1180px; margin: 0 auto; }}
    nav a {{ color: #d9e2ec; margin-right: 16px; text-decoration: none; }}
    label {{ font-weight: 650; }}
    input, select, textarea {{ box-sizing: border-box; width: 100%; max-width: 760px; padding: 8px; border: 1px solid #bcccdc; border-radius: 4px; }}
    textarea {{ max-width: 100%; font-family: ui-monospace, Consolas, monospace; }}
    button {{ padding: 10px 14px; border: 0; border-radius: 4px; background: #0b69a3; color: #fff; font-weight: 700; cursor: pointer; }}
    .panel {{ background: #fff; border: 1px solid #d9e2ec; border-radius: 6px; padding: 16px; margin-bottom: 16px; }}
    .notice {{ border-left: 5px solid #f0b429; background: #fffbea; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; }}
    th, td {{ border-bottom: 1px solid #e4e7eb; padding: 10px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px; background: #d9e2ec; }}
    .ok {{ background: #d3f9d8; }}
    .warn {{ background: #fff3bf; }}
    .error {{ background: #ffd8d8; }}
    code {{ background: #f0f4f8; padding: 2px 4px; border-radius: 4px; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; background: #f8fafc; border: 1px solid #d9e2ec; padding: 12px; }}
  </style>
</head>
<body>
  <header>
    <h1>記事自動生成ツール オンライン版 v0</h1>
    <nav><a href="/parent">親記事作成</a><a href="/child">子記事作成</a><a href="/meta">メタ情報</a><a href="/internal-link">内部リンク判断</a><a href="/jobs">ジョブ</a><a href="/workflows">作業状況</a><a href="/diagnostics">設定診断</a><a href="/deployment-readiness">デプロイ準備</a></nav>
  </header>
  <main>{body}</main>
</body>
</html>"""
    return HTMLResponse(html_doc)


def _status_class(item: WorkflowItem) -> str:
    if item.completed:
        return "ok"
    if item.status == "中断":
        return "error"
    return "warn"


async def _read_form_values(request: Request) -> dict[str, str]:
    body = (await request.body()).decode("utf-8", errors="replace")
    parsed = urllib.parse.parse_qs(body, keep_blank_values=True)
    return {key: values[0] if values else "" for key, values in parsed.items()}


def _selected(value: str, current: str) -> str:
    return " selected" if str(value) == str(current) else ""


def _site_key_from_name(site_name: str) -> str:
    if not site_name:
        return ""
    for site in get_parent_options()["sites"]:
        if site.get("name") == site_name:
            return str(site.get("key") or "")
    return ""


def _payload_preview(payload: dict, max_chars: int = 3000) -> str:
    """ジョブ詳細で巨大HTMLやプロンプトを丸ごと表示しないための要約。"""
    preview = {}
    for key, value in payload.items():
        if isinstance(value, str) and len(value) > 500:
            preview[key] = value[:500] + f"...（{len(value)}文字）"
        else:
            preview[key] = value
    text = json.dumps(preview, ensure_ascii=False, indent=2)
    if len(text) > max_chars:
        return text[:max_chars] + f"\n...（入力全体 {len(text)}文字）"
    return text


@app.get("/", response_class=HTMLResponse)
def index():
    return RedirectResponse(url="/parent")


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/parent", response_class=HTMLResponse)
def parent_form(site_key: str = "", keyword: str = ""):
    options = get_parent_options()
    site_options = "".join(
        f"<option value=\"{html.escape(site['key'])}\"{_selected(site['key'], site_key)}>{html.escape(site['name'])}</option>"
        for site in options["sites"]
    )
    api_options = "".join(
        f"<option value=\"{item['index']}\">{html.escape(item['name'])}</option>"
        for item in options["api_keys"]
    )
    addition_options = "<option value=\"\">使用しない</option>" + "".join(
        f"<option value=\"{html.escape(name)}\">{html.escape(name)}</option>"
        for name in options["additions"]
    )
    body = f"""
    <section class="panel">
      <h2>親記事作成 v0</h2>
      <p>ブラウザから親記事生成ジョブを登録します。最初は安全確認モードで、API消費もWordPress投稿も行わず、実行計画だけを確認します。</p>
    </section>
    <section class="panel notice">
      <h2>実行モード</h2>
      <p><strong>初回は「安全確認のみ」を使ってください。</strong> 本番実行を選ぶと、Gemini APIを消費し、成功時にWordPressへ下書き投稿します。</p>
    </section>
    <section class="panel">
      <form method="post" action="/parent/jobs">
        <p>
          <label>実行モード<br>
            <select name="execution_mode">
              <option value="dry_run" selected>安全確認のみ（API消費なし・WordPress投稿なし）</option>
              <option value="run">本番実行（Gemini API消費・WordPress下書き投稿あり）</option>
            </select>
          </label>
        </p>
        <p><label>対象サイト<br><select name="site_key">{site_options}</select></label></p>
        <p><label>APIキー<br><select name="api_key_index">{api_options}</select></label></p>
        <p><label>キーワード<br><input name="keyword" required value="{html.escape(keyword)}" placeholder="例: リング ベル プラン"></label></p>
        <p><label>プロンプトキー<br><input name="prompt_key" value="1"></label></p>
        <p><label>足し算Prompt<br><select name="addition_file">{addition_options}</select></label></p>
        <p><label>競合URL（任意。本番実行で空の場合はSearchAPI等で取得）<br><textarea name="competitor_urls" rows="4"></textarea></label></p>
        <p><label>リサーチ内容（任意。空の場合は現在のresearchファイルを使用）<br><textarea name="research_content" rows="8"></textarea></label></p>
        <p><button type="submit">親記事作成ジョブを登録する</button></p>
      </form>
    </section>
    <section class="panel">
      <h2>v0で扱う範囲</h2>
      <p>この画面の目的は、親記事作成の入口をオンラインへ移すことです。子記事作成、メタ情報、内部リンク、足し算Prompt編集、H2画像管理はこの工程では実装対象外です。</p>
    </section>
    """
    return _page("親記事作成", body)


@app.get("/parent/resume", response_class=HTMLResponse)
def parent_resume_form(resume_path: str, site_key: str = ""):
    options = get_parent_options()
    path = Path(resume_path)
    keyword = ""
    prompt_key = "1"
    detected_site_key = site_key
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            keyword = str(data.get("target_input") or "")
            meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
            prompt_key = str(meta.get("prompt_key") or "1")
            detected_site_key = detected_site_key or str(meta.get("site_choice") or "")
        except Exception:
            pass
    api_options = "".join(
        f"<option value=\"{item['index']}\">{html.escape(item['name'])}</option>"
        for item in options["api_keys"]
    )
    body = f"""
    <section class="panel">
      <h2>親記事作成の中断再開</h2>
      <p>Gemini混雑やAPI上限で止まった親記事生成を、保存済みの <code>resume_data</code> から再開します。</p>
      <p><strong>再開対象:</strong> {html.escape(keyword or path.name)}</p>
      <p><code>{html.escape(str(path))}</code></p>
    </section>
    <section class="panel notice">
      <h2>実行内容</h2>
      <p>完了済みステップはスキップし、止まった次のステップから再開します。成功時はWordPressへ下書き投稿します。</p>
    </section>
    <section class="panel">
      <form method="post" action="/parent/jobs">
        <input type="hidden" name="execution_mode" value="run">
        <input type="hidden" name="resume_path" value="{html.escape(str(path))}">
        <input type="hidden" name="site_key" value="{html.escape(detected_site_key)}">
        <input type="hidden" name="keyword" value="{html.escape(keyword)}">
        <input type="hidden" name="prompt_key" value="{html.escape(prompt_key)}">
        <p><label>再開に使うAPIキー<br><select name="api_key_index">{api_options}</select></label></p>
        <p><button type="submit">この再開データから親記事生成を続ける</button></p>
      </form>
    </section>
    """
    return _page("親記事作成の中断再開", body)


@app.get("/child", response_class=HTMLResponse)
def child_form(site_key: str = "", topics: str = ""):
    options = get_child_options()
    site_options = "".join(
        f"<option value=\"{html.escape(site['key'])}\"{_selected(site['key'], site_key)}>{html.escape(site['name'])}</option>"
        for site in options["sites"]
    )
    api_options = "".join(
        f"<option value=\"{item['index']}\">{html.escape(item['name'])}</option>"
        for item in options["api_keys"]
    )
    body = f"""
    <section class="panel">
      <h2>子記事作成 v0</h2>
      <p>子記事トピックを1行1件で入力し、子記事生成ジョブを登録します。初期値は安全確認モードです。</p>
    </section>
    <section class="panel notice">
      <h2>実行モード</h2>
      <p><strong>初回は「安全確認のみ」を使ってください。</strong> 本番実行を選ぶと、Gemini APIを消費し、成功時にWordPressへ下書き投稿します。</p>
    </section>
    <section class="panel">
      <form method="post" action="/child/jobs">
        <p>
          <label>実行モード<br>
            <select name="execution_mode">
              <option value="dry_run" selected>安全確認のみ（API消費なし・WordPress投稿なし）</option>
              <option value="run">本番実行（Gemini API消費・WordPress下書き投稿あり）</option>
            </select>
          </label>
        </p>
        <p><label>対象サイト<br><select name="site_key">{site_options}</select></label></p>
        <p><label>APIキー<br><select name="api_key_index">{api_options}</select></label></p>
        <p><label>子記事プロンプトキー<br><input name="prompt_key" value="1"></label></p>
        <p><label>子記事トピック（1行1件）<br><textarea name="topics" rows="8" required placeholder="例: リングベル復帰後に成婚を加速させるプロフィール戦略">{html.escape(topics)}</textarea></label></p>
        <p><button type="submit">子記事作成ジョブを登録する</button></p>
      </form>
    </section>
    """
    return _page("子記事作成", body)


@app.get("/meta", response_class=HTMLResponse)
def meta_form(site_key: str = "", keyword: str = ""):
    options = get_meta_options()
    site_options = "".join(
        f"<option value=\"{html.escape(site['key'])}\"{_selected(site['key'], site_key)}>{html.escape(site['name'])}</option>"
        for site in options["sites"]
    )
    api_options = "".join(
        f"<option value=\"{item['index']}\">{html.escape(item['name'])}</option>"
        for item in options["api_keys"]
    )
    body = f"""
    <section class="panel">
      <h2>メタ情報・入稿情報 v0</h2>
      <p>親記事HTMLを貼り付け、SEOタイトル・説明文・カテゴリ候補などの入稿用情報を生成します。初期値は安全確認モードです。</p>
    </section>
    <section class="panel notice">
      <h2>実行モード</h2>
      <p><strong>初回は「安全確認のみ」を使ってください。</strong> 本番実行を選ぶとGemini APIを消費し、メタ情報API結果と入稿用サマリーを保存します。v0ではWordPress標準項目の自動反映は行いません。</p>
    </section>
    <section class="panel">
      <form method="post" action="/meta/jobs">
        <p>
          <label>実行モード<br>
            <select name="execution_mode">
              <option value="dry_run" selected>安全確認のみ（API消費なし・WordPress反映なし）</option>
              <option value="run">本番実行（Gemini API消費あり）</option>
            </select>
          </label>
        </p>
        <p><label>対象サイト<br><select name="site_key">{site_options}</select></label></p>
        <p><label>APIキー<br><select name="api_key_index">{api_options}</select></label></p>
        <p><label>キーワード<br><input name="keyword" required value="{html.escape(keyword)}"></label></p>
        <p><label>投稿URL（任意）<br><input name="post_url" placeholder="https://example.com/?p=123"></label></p>
        <p><label>親記事HTML<br><textarea name="article_html" rows="14" required></textarea></label></p>
        <p><button type="submit">メタ情報ジョブを登録する</button></p>
      </form>
    </section>
    """
    return _page("メタ情報・入稿情報", body)


@app.get("/internal-link", response_class=HTMLResponse)
def internal_link_form(site_key: str = "", keyword: str = ""):
    options = get_internal_link_options()
    site_options = "".join(
        f"<option value=\"{html.escape(site['key'])}\"{_selected(site['key'], site_key)}>{html.escape(site['name'])}</option>"
        for site in options["sites"]
    )
    api_options = "".join(
        f"<option value=\"{item['index']}\">{html.escape(item['name'])}</option>"
        for item in options["api_keys"]
    )
    body = f"""
    <section class="panel">
      <h2>内部リンク判断 v0</h2>
      <p>親記事の内部リンク案に対して、WordPress検索でリンク先候補を探し、選んだ候補で内部リンク判断ジョブを登録します。</p>
    </section>
    <section class="panel notice">
      <h2>実行モード</h2>
      <p><strong>初回は「安全確認のみ」を使ってください。</strong> 本番実行を選ぶとGemini APIを消費し、内部リンク判断API結果ファイルを保存します。</p>
    </section>
    <section class="panel">
      <h2>WordPress検索から作る</h2>
      <form method="post" action="/internal-link/search">
        <p><label>対象サイト<br><select name="site_key">{site_options}</select></label></p>
        <p><label>親記事キーワード<br><input name="keyword" required value="{html.escape(keyword)}" placeholder="例: リング ベル 休会"></label></p>
        <p><label>候補番号<br><input name="item_index" value="1"></label></p>
        <p><label>内部リンク案タイトル<br><input name="topic_title" required></label></p>
        <p><label>内部リンク案ブロック<br><textarea name="proposal" rows="7" placeholder="- **リンク先トピック案:** ..."></textarea></label></p>
        <p><label>親記事HTML<br><textarea name="parent_html" rows="10" required placeholder="親記事本文のHTMLを貼り付け"></textarea></label></p>
        <p><label>親記事URL（任意。入力すると自己リンク候補を除外）<br><input name="exclude_url" placeholder="https://example.com/current-post/"></label></p>
        <p><label>検索キーワード（任意。空なら内部リンク案から自動候補を作成）<br><input name="search_query" placeholder="例: 婚活疲れ"></label></p>
        <p><button type="submit">WordPressで候補を検索する</button></p>
      </form>
    </section>
    <section class="panel">
      <h2>生成済みプロンプトを直接使う</h2>
      <form method="post" action="/internal-link/jobs">
        <p>
          <label>実行モード<br>
            <select name="execution_mode">
              <option value="dry_run" selected>安全確認のみ（API消費なし・結果保存なし）</option>
              <option value="run">本番実行（Gemini API消費・結果保存あり）</option>
            </select>
          </label>
        </p>
        <p><label>対象サイト<br><select name="site_key">{site_options}</select></label></p>
        <p><label>APIキー<br><select name="api_key_index">{api_options}</select></label></p>
        <p><label>親記事キーワード<br><input name="keyword" required value="{html.escape(keyword)}"></label></p>
        <p><label>候補番号<br><input name="item_index" value="1"></label></p>
        <p><label>内部リンク案タイトル<br><input name="topic_title" required></label></p>
        <p><label>内部リンク判断プロンプト<br><textarea name="prompt" rows="14" required></textarea></label></p>
        <p><button type="submit">内部リンク判断ジョブを登録する</button></p>
      </form>
    </section>
    """
    return _page("内部リンク判断", body)


@app.post("/internal-link/search", response_class=HTMLResponse)
async def internal_link_search(request: Request):
    values = await _read_form_values(request)
    options = get_internal_link_options()
    site_key = values.get("site_key", "")
    keyword = values.get("keyword", "").strip()
    topic_title = values.get("topic_title", "").strip()
    proposal = values.get("proposal", "").strip()
    parent_html = values.get("parent_html", "").strip()
    item_index = int(values.get("item_index") or 1)
    search_query = values.get("search_query", "").strip()
    exclude_url = values.get("exclude_url", "").strip()

    api_options = "".join(
        f"<option value=\"{item['index']}\">{html.escape(item['name'])}</option>"
        for item in options["api_keys"]
    )
    try:
        result = search_internal_link_candidates(
            site_key=site_key,
            topic_title=topic_title,
            proposal=proposal,
            search_query=search_query,
            exclude_url=exclude_url,
            count=10,
        )
        candidates = result["candidates"]
        queries = " / ".join(result["queries"])
    except Exception as exc:
        return _page(
            "内部リンク候補検索",
            f"""
            <section class="panel error">
              <h2>検索できませんでした</h2>
              <p>{html.escape(str(exc))}</p>
              <p><a href="/internal-link">内部リンク判断へ戻る</a></p>
            </section>
            """,
        )

    cards: list[str] = []
    for idx, candidate in enumerate(candidates, start=1):
        title = candidate.get("title") or "無題"
        url = candidate.get("url") or ""
        matched_query = candidate.get("matched_query") or ""
        char_count = candidate.get("char_count") or 0
        date = candidate.get("date") or ""
        content_html = candidate.get("content_html") or ""
        cards.append(
            f"""
            <section class="panel">
              <h3>{idx}. {html.escape(title)}</h3>
              <p><a href="{html.escape(url)}" target="_blank" rel="noopener">{html.escape(url)}</a></p>
              <p>検索語: <code>{html.escape(matched_query)}</code> / 本文: {html.escape(str(char_count))}字 / 日付: {html.escape(str(date))}</p>
              <form method="post" action="/internal-link/from-candidate/jobs">
                <p>
                  <label>実行モード<br>
                    <select name="execution_mode">
                      <option value="dry_run" selected>安全確認のみ（API消費なし・結果保存なし）</option>
                      <option value="run">本番実行（Gemini API消費・結果保存あり）</option>
                    </select>
                  </label>
                </p>
                <p><label>APIキー<br><select name="api_key_index">{api_options}</select></label></p>
                <input type="hidden" name="site_key" value="{html.escape(site_key)}">
                <input type="hidden" name="keyword" value="{html.escape(keyword)}">
                <input type="hidden" name="topic_title" value="{html.escape(topic_title)}">
                <input type="hidden" name="item_index" value="{html.escape(str(item_index))}">
                <input type="hidden" name="existing_post_url" value="{html.escape(url)}">
                <input type="hidden" name="existing_post_title" value="{html.escape(title)}">
                <textarea name="proposal" style="display:none">{html.escape(proposal)}</textarea>
                <textarea name="parent_html" style="display:none">{html.escape(parent_html)}</textarea>
                <textarea name="existing_post_html" style="display:none">{html.escape(content_html)}</textarea>
                <p><button type="submit">この候補で内部リンク判断ジョブを登録する</button></p>
              </form>
            </section>
            """
        )

    if not cards:
        cards.append(
            """
            <section class="panel notice">
              <h2>候補が見つかりませんでした</h2>
              <p>検索キーワードを変えて再検索してください。該当記事がない場合は、CLI同様に子記事作成候補として扱います。</p>
            </section>
            """
        )

    body = f"""
    <section class="panel">
      <h2>内部リンク候補検索結果</h2>
      <p>検索語: <code>{html.escape(queries or search_query or topic_title)}</code></p>
      <p>候補を選ぶと、その記事本文と親記事HTMLを使って内部リンク判断プロンプトを組み立て、ジョブへ渡します。</p>
      <p><a href="/internal-link">検索条件を入れ直す</a></p>
    </section>
    {''.join(cards)}
    """
    return _page("内部リンク候補検索", body)


@app.post("/parent/jobs")
async def create_parent_job(request: Request):
    values = await _read_form_values(request)
    site_key = values.get("site_key", "")
    keyword = values.get("keyword", "").strip()
    prompt_key = values.get("prompt_key") or "1"
    addition_file = values.get("addition_file") or ""
    api_key_index = int(values.get("api_key_index") or 0)
    competitor_urls = values.get("competitor_urls", "")
    research_content = values.get("research_content", "")
    resume_path = values.get("resume_path", "")
    execution_mode = values.get("execution_mode") or "dry_run"
    dry_run = execution_mode != "run"
    title_prefix = "安全確認" if dry_run else "本番実行"
    job = create_job(
        kind="parent_article",
        title=f"{title_prefix}: 親記事作成: {keyword}",
        payload={
            "site_key": site_key,
            "keyword": keyword,
            "prompt_key": prompt_key,
            "addition_file": addition_file or "",
            "api_key_index": api_key_index,
            "competitor_urls": competitor_urls,
            "research_content": research_content,
            "resume_path": resume_path,
            "dry_run": dry_run,
        },
    )
    return RedirectResponse(url=f"/jobs/{job.id}", status_code=303)


@app.post("/child/jobs")
async def create_child_job(request: Request):
    values = await _read_form_values(request)
    site_key = values.get("site_key", "")
    topics = values.get("topics", "")
    prompt_key = values.get("prompt_key") or "1"
    api_key_index = int(values.get("api_key_index") or 0)
    execution_mode = values.get("execution_mode") or "dry_run"
    dry_run = execution_mode != "run"
    title_prefix = "安全確認" if dry_run else "本番実行"
    first_topic = next((line.strip() for line in topics.splitlines() if line.strip()), "子記事")
    job = create_job(
        kind="child_article",
        title=f"{title_prefix}: 子記事作成: {first_topic}",
        payload={
            "site_key": site_key,
            "topics": topics,
            "prompt_key": prompt_key,
            "api_key_index": api_key_index,
            "dry_run": dry_run,
        },
    )
    return RedirectResponse(url=f"/jobs/{job.id}", status_code=303)


@app.post("/meta/jobs")
async def create_meta_job(request: Request):
    body = (await request.body()).decode("utf-8", errors="replace")
    parsed = urllib.parse.parse_qs(body, keep_blank_values=True)

    def value(name: str) -> str:
        values = parsed.get(name) or [""]
        return values[0]

    execution_mode = value("execution_mode") or "dry_run"
    dry_run = execution_mode != "run"
    keyword = value("keyword").strip()
    title_prefix = "安全確認" if dry_run else "本番実行"
    job = create_job(
        kind="meta_entry",
        title=f"{title_prefix}: メタ情報: {keyword}",
        payload={
            "site_key": value("site_key"),
            "keyword": keyword,
            "post_url": value("post_url"),
            "api_key_index": int(value("api_key_index") or 0),
            "article_html": value("article_html"),
            "dry_run": dry_run,
        },
    )
    return RedirectResponse(url=f"/jobs/{job.id}", status_code=303)


@app.post("/internal-link/jobs")
async def create_internal_link_job(request: Request):
    values = await _read_form_values(request)

    def value(name: str) -> str:
        return values.get(name, "")

    execution_mode = value("execution_mode") or "dry_run"
    dry_run = execution_mode != "run"
    keyword = value("keyword").strip()
    topic_title = value("topic_title").strip()
    title_prefix = "安全確認" if dry_run else "本番実行"
    job = create_job(
        kind="internal_link",
        title=f"{title_prefix}: 内部リンク判断: {topic_title or keyword}",
        payload={
            "site_key": value("site_key"),
            "keyword": keyword,
            "topic_title": topic_title,
            "item_index": int(value("item_index") or 1),
            "api_key_index": int(value("api_key_index") or 0),
            "prompt": value("prompt"),
            "dry_run": dry_run,
        },
    )
    return RedirectResponse(url=f"/jobs/{job.id}", status_code=303)


@app.post("/internal-link/from-candidate/jobs")
async def create_internal_link_job_from_candidate(request: Request):
    values = await _read_form_values(request)
    execution_mode = values.get("execution_mode") or "dry_run"
    dry_run = execution_mode != "run"
    try:
        built = build_internal_link_prompt_from_candidate(values)
    except Exception as exc:
        return _page(
            "内部リンク判断",
            f"""
            <section class="panel error">
              <h2>内部リンク判断プロンプトを作成できませんでした</h2>
              <p>{html.escape(str(exc))}</p>
              <p><a href="/internal-link">内部リンク判断へ戻る</a></p>
            </section>
            """,
        )
    title_prefix = "安全確認" if dry_run else "本番実行"
    job = create_job(
        kind="internal_link",
        title=f"{title_prefix}: 内部リンク判断: {built['topic_title']}",
        payload={
            "site_key": values.get("site_key", ""),
            "keyword": built["keyword"],
            "topic_title": built["topic_title"],
            "item_index": int(built["item_index"]),
            "api_key_index": int(values.get("api_key_index") or 0),
            "prompt": built["prompt"],
            "dry_run": dry_run,
            "existing_post_url": built["existing_post_url"],
            "existing_post_title": built["existing_post_title"],
        },
    )
    return RedirectResponse(url=f"/jobs/{job.id}", status_code=303)


@app.post("/api/parent/jobs")
def api_create_parent_job(request: ParentArticleRequest):
    payload = request.dict() if hasattr(request, "dict") else request.model_dump()
    title_prefix = "安全確認" if payload.get("dry_run", True) else "本番実行"
    return create_job(
        kind="parent_article",
        title=f"{title_prefix}: 親記事作成: {request.keyword}",
        payload=payload,
    )


@app.post("/api/child/jobs")
def api_create_child_job(request: ChildArticleRequest):
    payload = request.dict() if hasattr(request, "dict") else request.model_dump()
    title_prefix = "安全確認" if payload.get("dry_run", True) else "本番実行"
    first_topic = next((line.strip() for line in request.topics.splitlines() if line.strip()), "子記事")
    return create_job(
        kind="child_article",
        title=f"{title_prefix}: 子記事作成: {first_topic}",
        payload=payload,
    )


@app.post("/api/meta/jobs")
def api_create_meta_job(request: MetaEntryRequest):
    payload = request.dict() if hasattr(request, "dict") else request.model_dump()
    title_prefix = "安全確認" if payload.get("dry_run", True) else "本番実行"
    return create_job(
        kind="meta_entry",
        title=f"{title_prefix}: メタ情報: {request.keyword}",
        payload=payload,
    )


@app.post("/api/internal-link/jobs")
def api_create_internal_link_job(request: InternalLinkRequest):
    payload = request.dict() if hasattr(request, "dict") else request.model_dump()
    title_prefix = "安全確認" if payload.get("dry_run", True) else "本番実行"
    return create_job(
        kind="internal_link",
        title=f"{title_prefix}: 内部リンク判断: {request.topic_title}",
        payload=payload,
    )


@app.post("/api/internal-link/search")
def api_search_internal_link_candidates(request: InternalLinkSearchRequest):
    payload = request.dict() if hasattr(request, "dict") else request.model_dump()
    return search_internal_link_candidates(
        site_key=payload["site_key"],
        topic_title=payload["topic_title"],
        proposal=payload.get("proposal", ""),
        search_query=payload.get("search_query", ""),
        exclude_url=payload.get("exclude_url", ""),
        count=10,
    )


@app.get("/jobs", response_class=HTMLResponse)
def jobs():
    rows = []
    for job in list_jobs():
        rows.append(
            "<tr>"
            f"<td><a href=\"/jobs/{html.escape(job.id)}\"><code>{html.escape(job.id[:10])}</code></a></td>"
            f"<td>{html.escape(job.kind)}</td>"
            f"<td>{html.escape(job.status)}</td>"
            f"<td>{html.escape(job.title)}</td>"
            f"<td>{html.escape(job.created_at)}</td>"
            "</tr>"
        )
    if not rows:
        rows.append("<tr><td colspan=\"5\">ジョブはまだありません。</td></tr>")
    body = f"""
    <section class="panel">
      <h2>ジョブ一覧</h2>
      <p>ブラウザから登録した長時間処理を確認します。</p>
      <form method="post" action="/jobs/recover-stale?minutes=180" style="margin-top: 12px;">
        <button type="submit">3時間以上止まった実行中ジョブを中断扱いにする</button>
      </form>
    </section>
    <table>
      <thead><tr><th>ID</th><th>種別</th><th>状態</th><th>タイトル</th><th>作成日時</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    """
    return _page("ジョブ一覧", body)


@app.post("/jobs/recover-stale")
def recover_stale_jobs(minutes: int = 180):
    fixed = mark_stale_running_jobs(minutes=max(1, int(minutes)))
    return RedirectResponse(url=f"/jobs?recovered={fixed}", status_code=303)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail(job_id: str):
    job = get_job(job_id)
    if not job:
        return _page("ジョブ詳細", '<section class="panel"><h2>ジョブが見つかりません</h2></section>')
    payload = html.escape(_payload_preview(job.payload))
    mode = "安全確認のみ" if job.payload.get("dry_run", True) else "本番実行"
    body = f"""
    <section class="panel">
      <h2>{html.escape(job.title)}</h2>
      <p>状態: <span class="badge">{html.escape(job.status)}</span></p>
      <p>実行モード: <strong>{mode}</strong></p>
      <p>種別: {html.escape(job.kind)}</p>
      <p>作成: {html.escape(job.created_at)} / 更新: {html.escape(job.updated_at)}</p>
      <p>入力:</p>
      <pre>{payload}</pre>
    </section>
    <section class="panel">
      <h2>実行ログ</h2>
      <pre>{html.escape(job.log or "まだ実行されていません。数秒後に再読み込みしてください。")}</pre>
    </section>
    """
    return _page("ジョブ詳細", body)


@app.get("/workflows", response_class=HTMLResponse)
def workflows():
    rows = []
    for item in load_workflows():
        path = Path(item.path)
        site_key = _site_key_from_name(item.site_name)
        query = urllib.parse.urlencode({"site_key": site_key, "keyword": item.keyword})
        child_query = urllib.parse.urlencode({"site_key": site_key, "topics": item.keyword})
        action_links = (
            f"<a href=\"/meta?{query}\">メタ情報</a> / "
            f"<a href=\"/internal-link?{query}\">内部リンク</a> / "
            f"<a href=\"/child?{child_query}\">子記事</a>"
        )
        if item.status == "中断":
            resume_query = urllib.parse.urlencode({"resume_path": item.path, "site_key": site_key})
            action_links = f"<a href=\"/parent/resume?{resume_query}\">親記事生成を再開</a> / " + action_links
        rows.append(
            "<tr>"
            f"<td><span class=\"badge {_status_class(item)}\">{html.escape(item.status)}</span></td>"
            f"<td>{html.escape(item.kind)}</td>"
            f"<td>{html.escape(item.keyword)}</td>"
            f"<td>{html.escape(item.next_action)}</td>"
            f"<td>{html.escape(item.timestamp)}</td>"
            f"<td><code>{html.escape(path.name)}</code></td>"
            f"<td>{action_links}</td>"
            "</tr>"
        )
    if not rows:
        rows.append("<tr><td colspan=\"7\">resume_data はまだ見つかりません。</td></tr>")

    body = f"""
    <section class="panel">
      <h2>作業状況</h2>
      <p>既存の <code>resume_data</code> を読み取り、次に必要な画面へ進む入口を表示します。</p>
    </section>
    <table>
      <thead><tr><th>状態</th><th>種別</th><th>キーワード</th><th>次にやること</th><th>日時</th><th>resume</th><th>操作</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    """
    return _page("作業状況", body)


@app.get("/diagnostics", response_class=HTMLResponse)
def diagnostics():
    result = collect_diagnostics()
    rows = []
    for item in result["items"]:
        rows.append(
            "<tr>"
            f"<td><span class=\"badge {html.escape(item.status)}\">{html.escape(item.status)}</span></td>"
            f"<td>{html.escape(item.name)}</td>"
            f"<td>{html.escape(item.message)}</td>"
            "</tr>"
        )
    summary_class = "ok" if result["ready_for_public_deploy"] else ("warn" if result["ready_for_local"] else "error")
    if result["ready_for_public_deploy"]:
        summary = "公開デプロイ前の警告はありません。"
    elif result["ready_for_local"]:
        summary = "ローカルWeb版としては起動可能です。本番公開前に警告項目を整理してください。"
    else:
        summary = "起動または実行に影響するエラーがあります。"
    body = f"""
    <section class="panel">
      <h2>設定診断</h2>
      <p>オンライン移植前に、実行環境・保存先・認証情報の状態を確認します。</p>
      <p>総合: <span class="badge {summary_class}">{html.escape(summary)}</span></p>
      <p>警告: {result['warnings']} / エラー: {result['errors']}</p>
    </section>
    <table>
      <thead><tr><th>状態</th><th>項目</th><th>内容</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    """
    return _page("設定診断", body)


@app.get("/api/diagnostics")
def api_diagnostics():
    result = collect_diagnostics()
    return {
        "errors": result["errors"],
        "warnings": result["warnings"],
        "ready_for_local": result["ready_for_local"],
        "ready_for_public_deploy": result["ready_for_public_deploy"],
        "items": [
            {"name": item.name, "status": item.status, "message": item.message}
            for item in result["items"]
        ],
    }


@app.get("/deployment-readiness", response_class=HTMLResponse)
def deployment_readiness():
    result = collect_deployment_readiness()
    rows = []
    for item in result["items"]:
        rows.append(
            "<tr>"
            f"<td><span class=\"badge {html.escape(item.status)}\">{html.escape(item.status)}</span></td>"
            f"<td>{html.escape(item.name)}</td>"
            f"<td>{html.escape(item.message)}</td>"
            "</tr>"
        )
    if result["ready_for_public_real_run"]:
        summary_class = "ok"
        summary = "公開環境で本番実行するための必須項目は揃っています。"
    elif result["ready_for_deploy_smoke"]:
        summary_class = "warn"
        summary = "デプロイ先での起動テストは可能です。本番実行前に警告項目を解消してください。"
    else:
        summary_class = "error"
        summary = "デプロイ前に解消すべきエラーがあります。"
    body = f"""
    <section class="panel">
      <h2>デプロイ準備チェック</h2>
      <p>公開環境へ持ち出す前に、起動ファイル・ジョブ保存先・秘密情報の外出し状況を確認します。</p>
      <p>総合: <span class="badge {summary_class}">{html.escape(summary)}</span></p>
      <p>警告: {result['warnings']} / エラー: {result['errors']}</p>
    </section>
    <table>
      <thead><tr><th>状態</th><th>項目</th><th>内容</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    """
    return _page("デプロイ準備チェック", body)


@app.get("/api/deployment-readiness")
def api_deployment_readiness():
    result = collect_deployment_readiness()
    return {
        "errors": result["errors"],
        "warnings": result["warnings"],
        "ready_for_deploy_smoke": result["ready_for_deploy_smoke"],
        "ready_for_public_real_run": result["ready_for_public_real_run"],
        "items": [
            {"name": item.name, "status": item.status, "message": item.message}
            for item in result["items"]
        ],
    }
