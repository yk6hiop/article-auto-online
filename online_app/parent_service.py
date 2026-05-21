from __future__ import annotations

import contextlib
import glob
import io
import json
import os
from pathlib import Path
from typing import Any, Callable

from .runtime_config import apply_environment_overrides


LogFn = Callable[[str], None]
_CORE = None


def _core():
    global _CORE
    if _CORE is None:
        import auto_post_unified as imported_core

        _CORE = apply_environment_overrides(imported_core)
    return _CORE


class _LogCapture(io.TextIOBase):
    def __init__(self, log: LogFn):
        self._log = log
        self._buf = ""

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        if not text:
            return 0
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._log(line + "\n")
        return len(text)

    def flush(self) -> None:
        if self._buf:
            self._log(self._buf)
            self._buf = ""


def get_parent_options() -> dict[str, Any]:
    core = _core()
    sites = [
        {"key": key, "name": value["name"], "type": value["type"]}
        for key, value in core.SITES_NORMAL.items()
    ]
    api_keys = [
        {"index": i, "name": item["name"]}
        for i, item in enumerate(core.API_KEYS_NORMAL)
    ]
    additions = []
    additions_dir = core.find_additions_folder(core.PROMPT_BASE_DIR)
    if additions_dir:
        for path in sorted(Path(additions_dir).glob("**/*.txt")):
            additions.append(str(path.relative_to(additions_dir)))
    return {"sites": sites, "api_keys": api_keys, "additions": additions}


def _build_execution_list(selected_site: dict[str, Any], prompt_key: str, addition_path: str | None):
    core = _core()
    available = core.PROMPT_TYPES_PARENT_NORMAL.get(selected_site["type"], {})
    if prompt_key not in available:
        raise ValueError(f"未対応のプロンプトキーです: {prompt_key}")

    selected_prompt_path = os.path.join(core.PROMPT_BASE_DIR, available[prompt_key]["path"])
    step_files = sorted(glob.glob(os.path.join(selected_prompt_path, "step*.txt")))
    execution_list = []
    for path in step_files:
        fname = os.path.basename(path)
        if "step00" in fname or "step06_extract" in fname:
            continue
        if any(part in fname for part in ["step01", "step02", "step03", "step04", "step05"]):
            execution_list.append({"path": path, "type": "normal"})
        elif "step06" in fname:
            if addition_path:
                execution_list.append(
                    {
                        "path": path,
                        "type": "merged_addition",
                        "addition_path": addition_path,
                        "suppress_scroll_cta": False,
                    }
                )
            else:
                execution_list.append({"path": path, "type": "normal"})
    return execution_list, available[prompt_key]["path"]


def _resolve_addition_path(site_name: str, addition_file: str | None) -> str | None:
    core = _core()
    if not addition_file:
        return None
    additions_dir = core.find_additions_folder(core.PROMPT_BASE_DIR)
    if not additions_dir:
        return None
    raw = Path(addition_file)
    candidates = []
    if raw.is_absolute():
        candidates.append(raw)
    candidates.append(Path(additions_dir) / site_name / addition_file)
    candidates.append(Path(additions_dir) / addition_file)
    for path in candidates:
        if path.exists():
            return str(path)
    raise FileNotFoundError(f"足し算Promptが見つかりません: {addition_file}")


def _prepare_parent_article(payload: dict[str, Any]) -> dict[str, Any]:
    core = _core()
    resume_path = str(payload.get("resume_path") or "").strip()
    resume_data: dict[str, Any] | None = None
    resume_meta: dict[str, Any] = {}
    if resume_path:
        resume_file = Path(resume_path)
        if not resume_file.exists():
            raise FileNotFoundError(f"再開データが見つかりません: {resume_path}")
        with resume_file.open("r", encoding="utf-8") as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict):
            raise ValueError(f"再開データの形式が不正です: {resume_path}")
        resume_data = loaded
        resume_meta = loaded.get("metadata") if isinstance(loaded.get("metadata"), dict) else {}

    site_key = str(payload.get("site_key") or resume_meta.get("site_choice") or "").strip()
    keyword = str(payload.get("keyword") or (resume_data or {}).get("target_input") or "").strip()
    prompt_key = str(payload.get("prompt_key") or resume_meta.get("prompt_key") or "1").strip()
    api_key_index = int(payload.get("api_key_index") or 0)

    if not keyword:
        raise ValueError("キーワードが空です。")
    if site_key not in core.SITES_NORMAL:
        raise ValueError(f"未対応のサイトキーです: {site_key}")
    if api_key_index < 0 or api_key_index >= len(core.API_KEYS_NORMAL):
        raise ValueError(f"未対応のAPIキー番号です: {api_key_index}")

    selected_site = core.SITES_NORMAL[site_key]
    addition_file = payload.get("addition_file") or resume_meta.get("addition_path")
    addition_path = _resolve_addition_path(selected_site["name"], addition_file)
    execution_list, prompt_sub_path = _build_execution_list(selected_site, prompt_key, addition_path)
    return {
        "core": core,
        "site_key": site_key,
        "keyword": keyword,
        "prompt_key": prompt_key,
        "api_key_index": api_key_index,
        "selected_site": selected_site,
        "addition_path": addition_path,
        "execution_list": execution_list,
        "prompt_sub_path": prompt_sub_path,
        "resume_data": resume_data,
        "resume_path": resume_path,
    }


def plan_parent_article_job(payload: dict[str, Any], log: LogFn) -> dict[str, Any]:
    """API消費・WordPress投稿なしで、親記事生成ジョブの実行計画だけを確認する。"""
    prepared = _prepare_parent_article(payload)
    core = prepared["core"]
    keyword = prepared["keyword"]
    selected_site = prepared["selected_site"]
    api_key_index = prepared["api_key_index"]
    execution_list = prepared["execution_list"]
    resume_data = prepared["resume_data"]

    research_content = str(payload.get("research_content") or "").strip()
    research_source = "フォーム入力"
    if resume_data:
        research_source = prepared["resume_path"]
        research_content = str(resume_data.get("initial_instruction") or "")
    elif not research_content:
        research_source = str(core.RESEARCH_FILE)
        try:
            research_content = core.read_file(core.RESEARCH_FILE)
        except Exception:
            research_content = ""

    competitor_urls = str(payload.get("competitor_urls") or "").strip()
    competitor_note = "フォーム入力あり" if competitor_urls else "未入力。本番実行ではSearchAPI等で取得します。"

    log("【安全確認モード】親記事生成ジョブの実行計画\n")
    log("このモードではGemini APIを使わず、WordPressにも投稿しません。\n\n")
    log(f"対象サイト: {selected_site['name']}\n")
    log(f"キーワード: {keyword}\n")
    log(f"APIキー: {core.API_KEYS_NORMAL[api_key_index]['name']}（本番実行時のみ使用）\n")
    log(f"プロンプトキー: {prepared['prompt_key']}\n")
    log(f"足し算Prompt: {prepared['addition_path'] or '使用しない'}\n")
    if resume_data:
        log(f"再開データ: {prepared['resume_path']}\n")
    log(f"リサーチ情報: {research_source} / 文字数 {len(research_content.strip())}\n")
    log(f"競合URL: {competitor_note}\n\n")
    log("実行予定ステップ:\n")
    for i, step in enumerate(execution_list, 1):
        log(f"  {i}. {Path(step['path']).name} ({step['type']})\n")
    log("\n問題なければ、同じフォームで「本番実行」を選んでください。\n")

    return {
        "success": True,
        "dry_run": True,
        "keyword": keyword,
        "step_count": len(execution_list),
        "research_chars": len(research_content.strip()),
        "has_competitor_urls": bool(competitor_urls),
    }


def run_parent_article_job(payload: dict[str, Any], log: LogFn) -> dict[str, Any]:
    prepared = _prepare_parent_article(payload)
    core = prepared["core"]
    site_key = prepared["site_key"]
    keyword = prepared["keyword"]
    api_key_index = prepared["api_key_index"]
    selected_site = prepared["selected_site"]
    addition_path = prepared["addition_path"]
    execution_list = prepared["execution_list"]
    prompt_sub_path = prepared["prompt_sub_path"]
    resume_data = prepared["resume_data"]

    research_content = str(payload.get("research_content") or "").strip()
    if resume_data:
        initial_instruction = str(resume_data.get("initial_instruction") or "").strip()
        if not initial_instruction:
            raise ValueError("再開データに initial_instruction がありません。通常の親記事作成からやり直してください。")
    elif not research_content:
        research_content = core.read_file(core.RESEARCH_FILE)
    if not resume_data and not research_content.strip():
        raise ValueError("リサーチ内容が空です。research_*.txt またはフォームのリサーチ内容が必要です。")

    if not resume_data:
        competitor_urls = str(payload.get("competitor_urls") or "").strip()
        if not competitor_urls:
            competitor_urls = core.collect_competitor_urls(keyword, num_results=10)
        initial_instruction = f"前提情報:\nキーワード: {keyword}\n競合URL:\n{competitor_urls}\nリサーチ内容:\n{research_content}"
    resume_meta = core.build_parent_resume_metadata(
        site_key,
        selected_site,
        prepared["prompt_key"],
        prompt_sub_path,
        addition_path,
        False,
    )

    selected_api_key = core.API_KEYS_NORMAL[api_key_index]["key"]
    capture = _LogCapture(log)
    with contextlib.redirect_stdout(capture):
        print(f"オンライン親記事ジョブ開始: {keyword}")
        print(f"対象サイト: {selected_site['name']}")
        print(f"APIキー: {core.API_KEYS_NORMAL[api_key_index]['name']}")
        success, final_content, log_history, step_outputs = core.run_article_generation_parent(
            selected_api_key,
            initial_instruction,
            execution_list,
            selected_site,
            keyword,
            resume_data=resume_data,
            resume_metadata=resume_meta,
        )
        if not success:
            print("親記事生成が中断しました。resume_dataを確認してください。")
            return {"success": False, "posted_url": "", "keyword": keyword}
        print("WordPress下書き投稿を開始します。")
        posted_url = core.post_to_wordpress(selected_site, f"【自動生成】{keyword[:30]}...", final_content)
        core.save_log_parent(keyword, log_history)
        print(f"WordPress下書き投稿完了: {posted_url}")
    capture.flush()

    return {"success": True, "posted_url": posted_url if isinstance(posted_url, str) else "", "keyword": keyword}
