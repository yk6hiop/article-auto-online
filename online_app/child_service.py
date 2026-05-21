from __future__ import annotations

import contextlib
import glob
import io
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


def get_child_options() -> dict[str, Any]:
    core = _core()
    sites = [
        {"key": key, "name": value["name"], "type": value["type"]}
        for key, value in core.SITES_NORMAL.items()
    ]
    api_keys = [
        {"index": i, "name": item["name"]}
        for i, item in enumerate(core.API_KEYS_NORMAL)
    ]
    return {"sites": sites, "api_keys": api_keys}


def _topics_from_payload(payload: dict[str, Any]) -> list[str]:
    raw = str(payload.get("topics") or payload.get("topic") or "").strip()
    topics = [line.strip(" -\t") for line in raw.splitlines() if line.strip(" -\t")]
    return topics


def _prepare_child_article(payload: dict[str, Any]) -> dict[str, Any]:
    core = _core()
    site_key = str(payload.get("site_key") or "").strip()
    prompt_key = str(payload.get("prompt_key") or "1").strip()
    api_key_index = int(payload.get("api_key_index") or 0)
    topics = _topics_from_payload(payload)

    if not topics:
        raise ValueError("子記事トピックが空です。")
    if site_key not in core.SITES_NORMAL:
        raise ValueError(f"未対応のサイトキーです: {site_key}")
    if api_key_index < 0 or api_key_index >= len(core.API_KEYS_NORMAL):
        raise ValueError(f"未対応のAPIキー番号です: {api_key_index}")

    selected_site = core.SITES_NORMAL[site_key]
    prompt_variants = core.PROMPT_TYPES_CHILD_NORMAL.get(selected_site["type"], {})
    if prompt_key not in prompt_variants:
        raise ValueError(f"未対応の子記事プロンプトキーです: {prompt_key}")

    selected_prompt_path = os.path.join(core.PROMPT_BASE_DIR, prompt_variants[prompt_key]["path"])
    step_files = sorted(glob.glob(os.path.join(selected_prompt_path, "step*.txt")))
    execution_list = []
    for path in step_files:
        fname = os.path.basename(path)
        if "step00" in fname:
            continue
        if any(part in fname for part in ["step01", "step02", "step03", "step04", "step05", "step06"]):
            execution_list.append({"path": path, "type": "normal"})

    return {
        "core": core,
        "site_key": site_key,
        "selected_site": selected_site,
        "prompt_key": prompt_key,
        "prompt_path": selected_prompt_path,
        "api_key_index": api_key_index,
        "topics": topics,
        "execution_list": execution_list,
    }


def plan_child_article_job(payload: dict[str, Any], log: LogFn) -> dict[str, Any]:
    prepared = _prepare_child_article(payload)
    core = prepared["core"]
    selected_site = prepared["selected_site"]
    topics = prepared["topics"]
    execution_list = prepared["execution_list"]

    log("【安全確認モード】子記事作成ジョブの実行計画\n")
    log("このモードではGemini APIを使わず、WordPressにも投稿しません。\n\n")
    log(f"対象サイト: {selected_site['name']}\n")
    log(f"APIキー: {core.API_KEYS_NORMAL[prepared['api_key_index']]['name']}（本番実行時のみ使用）\n")
    log(f"子記事プロンプトキー: {prepared['prompt_key']}\n")
    log("作成予定トピック:\n")
    for i, topic in enumerate(topics, 1):
        log(f"  {i}. {topic}\n")
    log("\n実行予定ステップ:\n")
    for i, step in enumerate(execution_list, 1):
        log(f"  {i}. {Path(step['path']).name} ({step['type']})\n")
    log("\n問題なければ、同じフォームで「本番実行」を選んでください。\n")
    return {"success": True, "dry_run": True, "topic_count": len(topics), "step_count": len(execution_list)}


def run_child_article_job(payload: dict[str, Any], log: LogFn) -> dict[str, Any]:
    prepared = _prepare_child_article(payload)
    core = prepared["core"]
    selected_site = prepared["selected_site"]
    topics = prepared["topics"]
    selected_api_key = core.API_KEYS_NORMAL[prepared["api_key_index"]]["key"]
    capture = _LogCapture(log)
    completed = []

    with contextlib.redirect_stdout(capture):
        print("オンライン子記事ジョブ開始")
        print(f"対象サイト: {selected_site['name']}")
        print(f"APIキー: {core.API_KEYS_NORMAL[prepared['api_key_index']]['name']}")
        for index, topic in enumerate(topics, 1):
            print(f"\n[{index}/{len(topics)}] トピック: {topic}")
            keyword = core.run_step00_keyword(selected_api_key, topic, prepared["prompt_path"])
            success, final_content, log_history = core.run_article_generation_child(
                selected_api_key,
                prepared["execution_list"],
                keyword,
                is_moechin=False,
                selected_site=selected_site,
            )
            if not success:
                print("子記事生成が中断しました。")
                if log_history:
                    core.save_log_child(keyword, log_history)
                return {"success": False, "completed": completed}
            print("WordPress下書き投稿を開始します。")
            child_url = core.post_to_wordpress(selected_site, f"【自動生成子記事】{keyword[:30]}...", final_content)
            if log_history:
                core.save_log_child(keyword, log_history)
            completed.append({"keyword": keyword, "url": child_url if isinstance(child_url, str) else ""})
            print(f"WordPress下書き投稿完了: {child_url}")
    capture.flush()
    return {"success": True, "completed": completed}
