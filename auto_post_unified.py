#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
記事自動生成ツール 統合版 (auto_post_unified.py)
旧4スクリプトを1つに集約 + メタ情報・入稿情報／内部リンク判断機能

モード選択:
  [1] 親記事作成（通常サイト）  ← 旧 auto_post_normal.py
  [2] 親記事作成（もえちん）    ← 旧 auto_post_moechin.py
  [3] 子記事作成（通常サイト）  ← 旧 auto_post_child_normal.py
  [4] 子記事作成（もえちん）    ← 旧 auto_post_child_moechin.py
  [5] メタ情報・入稿情報／内部リンク判断
  [7] 案件名抽出＆関連語付与
"""

import os
import glob
import time
import base64
import requests
import datetime
import subprocess
import sys
import re
import json
import html
try:
    import msvcrt
except ImportError:  # Linux系のオンライン環境では存在しない
    msvcrt = None
import concurrent.futures
import webbrowser
import urllib.parse
import unicodedata
# google.genai は起動を速くするため遅延インポート（_load_genai()で初回のみ読み込む）
genai = None
types = None

# ── 自動データ収集用（オプション）──
try:
    from ddgs import DDGS
    HAS_DDGS = True
except ImportError:
    try:
        from duckduckgo_search import DDGS
        HAS_DDGS = True
    except ImportError:
        HAS_DDGS = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

# ============================================================
# PC識別子
# ============================================================
def load_pc_identifier():
    # ローカル（ホームフォルダ）を優先して読む → PCごとに別の値を持てる（Googleドライブ同期の影響なし）
    local_config = os.path.join(os.path.expanduser("~"), "pc_config.txt")
    if os.path.exists(local_config):
        try:
            with open(local_config, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        return line
        except Exception as e:
            print(f"⚠️ 設定ファイル読み込みエラー: {e}")
    return None  # 未設定

def setup_pc_identifier():
    """PC識別子が未設定の場合、初回起動時にセットアップする。"""
    local_config = os.path.join(os.path.expanduser("~"), "pc_config.txt")
    print("\n" + "="*60)
    print("  【初回セットアップ】このPCの識別子が設定されていません")
    print("="*60)
    print(f"  保存先: {local_config}")
    print()
    options = ["DESKTOP（メインデスクトップPC）",
               "GAMING（ゲーミングPC）",
               "LAPTOP（ノートPC）",
               "その他（手動入力）"]
    idx = arrow_menu("このPCの種別を選択してください", options, allow_back=False)
    if idx == 3:
        identifier = input("  識別子を入力（例: PC2）: ").strip().upper()
        if not identifier:
            identifier = "PC"
    else:
        identifier = ["DESKTOP", "GAMING", "LAPTOP"][idx]
    try:
        with open(local_config, "w", encoding="utf-8") as f:
            f.write(f"# PC識別子設定ファイル（ローカル保存 - Googleドライブに同期されません）\n")
            f.write(f"# このPCの識別子\n")
            f.write(f"{identifier}\n")
        print(f"\n  ✅ 識別子 [{identifier}] を保存しました: {local_config}")
        print("  次回起動からは自動で読み込まれます。")
        input("  Enterキーで続行...")
    except Exception as e:
        print(f"  ❌ 保存エラー: {e}")
        input("  Enterキーで続行（この起動では識別子なしで動作します）...")
        identifier = "UNKNOWN"
    return identifier

_raw_identifier = load_pc_identifier()
# arrow_menuはまだ定義されていないため、UNKNOWN判定は main() 起動時に行う
PC_IDENTIFIER = _raw_identifier if _raw_identifier else "UNKNOWN"

# ============================================================
# パス設定
# ============================================================
BASE_DIR = r"G:\マイドライブ\claude-work-shared"
PROMPT_BASE_DIR = os.path.join(BASE_DIR, "prompts")
GOOGLE_DRIVE_BASE = os.path.join(BASE_DIR, "記事生成結果")
PARENT_WORDPRESS_DATA = os.path.join(GOOGLE_DRIVE_BASE, "親記事", "wordpress_data")
PARENT_LOGS           = os.path.join(GOOGLE_DRIVE_BASE, "親記事", "logs")
CHILD_WORDPRESS_DATA  = os.path.join(GOOGLE_DRIVE_BASE, "子記事", "wordpress_data")
CHILD_LOGS            = os.path.join(GOOGLE_DRIVE_BASE, "子記事", "logs")
# メタ情報・入稿情報／内部リンク判断の出力は、探しやすさを優先して1か所へ集約する。
# 旧フォルダは過去履歴読み込み用としてだけ参照する。
UNIFIED_OUTPUT_DIR    = os.path.join(GOOGLE_DRIVE_BASE, "作業結果")
LEGACY_AI_STUDIO_PROMPTS_DIR = os.path.join(GOOGLE_DRIVE_BASE, "ai_studio_prompts")
LEGACY_STEP9_10_RESULTS_DIR  = os.path.join(GOOGLE_DRIVE_BASE, "step9_10_results")
AI_STUDIO_PROMPTS_DIR = UNIFIED_OUTPUT_DIR
STEP9_10_RESULTS_DIR  = UNIFIED_OUTPUT_DIR
RESEARCH_FILE         = os.path.join(BASE_DIR, f"research_{PC_IDENTIFIER}.txt")
STEP9_META_FILE       = os.path.join(BASE_DIR, "step9_meta.txt")
STEP10_FILE           = os.path.join(BASE_DIR, "step10.txt")
REVIEWER_MASTER_FILE  = os.path.join(BASE_DIR, "reviewer_master.json")
RESUME_NORMAL         = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume_normal.json")
RESUME_MOECHIN        = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume_moechin.json")
RESUME_CHILD_NORMAL   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume_child_normal.json")
RESUME_CHILD_MOECHIN  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume_child_moechin.json")
RESUME_DIR            = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume_data")
WORKFLOW_DONE_FILE    = os.path.join(RESUME_DIR, "workflow_done.json")
WORKFLOW_PROGRESS_FILE = os.path.join(RESUME_DIR, "workflow_progress.json")
AIO_WORK_DIR          = os.path.join(GOOGLE_DRIVE_BASE, "aio_enhancement")
SERP_WORK_DIR         = os.path.join(GOOGLE_DRIVE_BASE, "serp_results")

# ============================================================
# Geminiモデル
# ============================================================
MODEL_PARENT = "gemini-2.5-flash"
MODEL_CHILD  = "gemini-3-flash-preview"

SAFETY_SETTINGS = None
GEN_CONFIG = None

def _load_genai():
    """google.genai を遅延インポートし、SAFETY_SETTINGS/GEN_CONFIG を初期化する（初回のみ）"""
    global genai, types, SAFETY_SETTINGS, GEN_CONFIG
    if genai is not None:
        return
    from google import genai as _genai
    from google.genai import types as _types
    genai = _genai
    types = _types
    SAFETY_SETTINGS = [
        types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH",        threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT",  threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT",  threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_HARASSMENT",         threshold="BLOCK_NONE"),
    ]
    GEN_CONFIG = types.GenerateContentConfig(
        temperature=0.1, top_p=0.95, safety_settings=SAFETY_SETTINGS
    )

# ============================================================
# APIキー
# ============================================================
LOCAL_PRIVATE_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_private_config.json")


def _load_private_config():
    """ローカル用の秘密情報を、公開対象外ファイルまたは環境変数から読む。"""
    raw = os.environ.get("AUTO_POST_PRIVATE_CONFIG_JSON", "").strip()
    if raw:
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"⚠️ AUTO_POST_PRIVATE_CONFIG_JSON の読み込みに失敗しました: {e}")
            return {}
    if os.path.exists(LOCAL_PRIVATE_CONFIG_FILE):
        try:
            with open(LOCAL_PRIVATE_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"⚠️ local_private_config.json の読み込みに失敗しました: {e}")
    return {}


def _load_json_env(name, default):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        data = json.loads(raw)
        return data if data is not None else default
    except Exception as e:
        print(f"⚠️ {name} のJSON読み込みに失敗しました: {e}")
        return default


_PRIVATE_CONFIG = _load_private_config()
API_KEYS_NORMAL = _load_json_env("ONLINE_GEMINI_KEYS_NORMAL_JSON", _PRIVATE_CONFIG.get("api_keys_normal", []))
API_KEYS_MOECHIN = _load_json_env("ONLINE_GEMINI_KEYS_MOECHIN_JSON", _PRIVATE_CONFIG.get("api_keys_moechin", []))

# 有料（従量課金）APIキー ― 現在未使用。設定すると sleep 時間が短縮される
API_KEY_PAID = os.environ.get("GEMINI_API_KEY_PAID", "").strip() or _PRIVATE_CONFIG.get("api_key_paid")

# ============================================================
# サイト設定
# ============================================================
SITES_NORMAL = _PRIVATE_CONFIG.get("sites_normal") or {
    "1": {"name": "病院探し",      "url": "https://byouin-sagashi.com",   "user": "", "pass": "", "type": "A"},
    "2": {"name": "結びのマリッジ", "url": "https://www.marriage-mr.com",  "user": "", "pass": "", "type": "A"},
    "3": {"name": "LearnBiz",     "url": "https://learnbiz.jp",          "user": "", "pass": "", "type": "A"},
    "4": {"name": "便利屋",        "url": "https://benriya-otasuke.jp",   "user": "", "pass": "", "type": "A"},
    "5": {"name": "ジャズ",        "url": "https://jazzmistake.com",      "user": "", "pass": "", "type": "A"},
    "6": {"name": "くるまの縁",    "url": "https://kurumanoen.com",       "user": "", "pass": "", "type": "A"},
    "8": {"name": "占いの手引書",   "url": "https://uranai1.xsrv.jp",     "user": "", "pass": "", "type": "B"},
}

SITES_MOECHIN = _PRIVATE_CONFIG.get("sites_moechin") or {
    "7": {"name": "もえちん",      "url": "https://www.moechin.com",      "user": "", "pass": "", "type": "C"},
}

_SITE_ENV_OVERRIDES = _load_json_env("ONLINE_WP_SITE_OVERRIDES_JSON", {})
if isinstance(_SITE_ENV_OVERRIDES, dict):
    for _site_key, _site_values in _SITE_ENV_OVERRIDES.items():
        if not isinstance(_site_values, dict):
            continue
        _target_sites = SITES_MOECHIN if str(_site_key) in SITES_MOECHIN else SITES_NORMAL
        if str(_site_key) in _target_sites:
            for _field in ("name", "url", "user", "pass", "type"):
                if _field in _site_values and _site_values[_field] is not None:
                    _target_sites[str(_site_key)][_field] = str(_site_values[_field])

SITES_ALL = {**SITES_NORMAL, **SITES_MOECHIN}

# PublishPress Authors ショートコード レイアウトID（サイトごとに異なる）
# プロンプト内のデフォルト ppma_boxes_774 / ppma_boxes_775 を各サイトの正しいIDに置換する
PPMA_LAYOUT_MAP = {
    "病院探し":       {"author": "609",  "reviewer": "610"},
    "結びのマリッジ": {"author": "808",  "reviewer": "809"},
    "LearnBiz":      {"author": "774",  "reviewer": "775"},
    "便利屋":         {"author": "475",  "reviewer": "486"},
    "ジャズ":         {"author": "1858", "reviewer": "1864"},
    "くるまの縁":     {"author": "318",  "reviewer": "319"},
    "占いの手引書":   {"single": "38796"},
    "もえちん":       {"author": "73",   "reviewer": "78"},
}

# ============================================================
# 足し算ファイルはサイト別サブフォルダに格納（自動検出）
# 📂 00_additions/{サイト名}/*.txt
# サブフォルダが見つからない場合はルート直下のファイルをフォールバック表示

# ============================================================
# プロンプトタイプ
# ============================================================
PROMPT_TYPES_PARENT_NORMAL = {
    "A": {
        "1": {"name": "標準",         "path": "01_general"},
        "2": {"name": "ランキング",    "path": "02_ranking （ランキング版）"},
        "3": {"name": "口コミ",        "path": "03_review （口コミ・レビュー版）"},
    },
    "B": {
        "1": {"name": "手引書(標準)",   "path": "05_tebikisyo （手引書・電話占い用）"},
        "2": {"name": "手引書(ランキング)", "path": "06_tebikisyo-ranking （手引書ランキング用）"},
        "3": {"name": "手引書(口コミ)", "path": "07_tebikisyo-review （手引書口コミレビュー用）"},
    },
}

PROMPT_TYPES_PARENT_MOECHIN = {
    "C": {"1": {"name": "もえちん専用", "path": "04_moechin （もえちん専用）"}},
}

PROMPT_TYPES_CHILD_NORMAL = {
    "A": {"1": {"name": "標準（子記事）",   "path": "01_general_child"},
          "2": {"name": "⚡高速版（子記事）", "path": "01_general_child_fast"}},
    "B": {"1": {"name": "手引書（子記事）", "path": "05_tebikisyo_child"}},
}

PROMPT_TYPES_CHILD_MOECHIN = {
    "C": {"1": {"name": "標準（もえちん子記事）",   "path": "04_moechin_child"},
          "2": {"name": "⚡高速版（もえちん子記事）", "path": "04_moechin_child_fast"}},
}


# ============================================================
# 共通ユーティリティ
# ============================================================
def read_file(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f: return f.read()
    except:
        try:
            with open(filepath, "r", encoding="shift_jis") as f: return f.read()
        except: return ""

def get_multiline_input(prompt_text, eof_mode=False):
    """複数行入力を受け取る。
    eof_mode=True  : Enter5回連続 or EOF入力 で確定（HTML貼り付け専用。空行2-3行で誤終了しない）
    eof_mode=False : Enter3回連続 で確定（URL等の短い入力向け）
    どちらのモードでも EOF 入力で即確定可能。
    """
    if prompt_text:
        print(prompt_text)
    lines, empty_count = [], 0
    threshold = 5 if eof_mode else 3
    while True:
        line = input()
        if line.strip() == 'EOF':
            break
        if line == "":
            empty_count += 1
            if empty_count >= threshold:
                break
        else:
            empty_count = 0
            lines.append(line)
    # stdinバッファをフラッシュ
    if msvcrt:
        while msvcrt.kbhit():
            msvcrt.getwch()
    return "\n".join(lines)

def clear_console_input_buffer():
    """直前のキー入力が次のメニューに残らないようにする。"""
    if not msvcrt:
        return
    try:
        while msvcrt.kbhit():
            msvcrt.getwch()
    except Exception:
        pass

def get_file_content_with_notepad(filename, instruction_text):
    filepath = os.path.join(BASE_DIR, filename)
    if not os.path.exists(filepath):
        with open(filepath, "w", encoding="utf-8") as f: f.write("")
    print("\n" + "="*60)
    print(f"🛑 {instruction_text}")
    print(f"   自動的に開かれるメモ帳 ({filename}) にデータを貼り付けて、")
    print("   上書き保存(Ctrl+S) してから 閉じてください。")
    print("="*60 + "\n")
    try:
        subprocess.call(['notepad.exe', filepath])
    except Exception as e:
        print(f"⚠️ メモ帳起動エラー: {e}")
        input(f"手動で {filename} を編集し、Enterを押してください...")
    input(">> 編集・保存が終わったら Enter キーを押してください <<")
    return read_file(filepath)

def select_addition_file(site_config, purpose_text=None, skip_label="スキップ"):
    """サイト名に連動した足し算ファイルをarrow_menuで選択して返す。
    サイト名のサブフォルダがあればその中から、なければルート直下から選択。
    スキップ選択時はNone、ESCはNone（戻る）。"""
    additions_dir = find_additions_folder(PROMPT_BASE_DIR)
    if not additions_dir:
        return None

    site_name = site_config.get("name", "")

    # サイト名サブフォルダを検索
    site_subdir = os.path.join(additions_dir, site_name)
    if os.path.isdir(site_subdir):
        filtered = sorted(glob.glob(os.path.join(site_subdir, "*.txt")))
    else:
        # サブフォルダなし → ルート直下の .txt をフォールバック表示
        filtered = sorted(glob.glob(os.path.join(additions_dir, "*.txt")))

    if not filtered:
        print(f"\n   ℹ️ {site_name} 用の足し算ファイルはありません。スキップします。")
        return None

    options = [os.path.basename(f) for f in filtered] + [skip_label]
    title = purpose_text or (
        f"足し算ファイル選択（{site_name} 用）\n"
        "  記事に追加する案件/CTA指示のPromptを選びます。不要ならスキップしてください。"
    )
    idx = arrow_menu(title, options, allow_back=True)
    if idx == -1:
        return None  # 前の画面へ戻る
    if idx >= len(filtered):
        return None  # スキップ
    return filtered[idx]


def find_additions_folder(base_path):
    candidates = glob.glob(os.path.join(base_path, "*00_additions*"))
    dirs = [d for d in candidates if os.path.isdir(d)]
    return dirs[0] if dirs else None


# ============================================================
# 自動データ収集ヘルパー（爆サイ・店舗URL）
# ============================================================
def web_search(query, max_results=10):
    """DuckDuckGo検索でタイトル・スニペット・URLを取得"""
    if not HAS_DDGS:
        return []
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            results = DDGS().text(query, max_results=max_results)
        return results if results else []
    except Exception as e:
        print(f"   ⚠️ 検索エラー: {e}")
        return []


def fetch_page_text(url, max_chars=4000):
    """URLからテキストを抽出（爆サイ等の口コミページ用）"""
    if not HAS_BS4:
        return ""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        # 不要な定型文・サイトUIテキストを除去
        noise = [
            "こちらは会員限定", "ログインして爆サイ", "SNSでログイン", "新規会員登録",
            "マルチデバイス版", "PC版で見る", "次回からこの表示", "LINEでログイン",
            "Googleでログイン", "Xでログイン", "メールアドレスでログイン",
            "アカウントをお持ちでない方", "上記SNSアカウント", "メールアドレスの入力不要",
            "最新ニュース", "フォロワー", "Follow @", "いいね！", "お知らせ",
            "スレ作成", "スレ検索", "レス検索", "HOT!", "オススメ！",
            "最初から表示", "最新レス", "スレ一覧", "前のページに戻る",
            "URLコピー", "タグコピー", "友達に教える", "QRコード",
            "この掲示板のURL", "件のレスがあります", "この掲示板",
            "PC版の表示が選べます", "Please Wait", "画面が切り替わるまで",
            "閉じないでください", "閉じる", "北部九州", "南部九州",
            "投稿規制解除について", "レス投稿", "無料掲載あり",
            "この店のオーナーですか", "閉店・休業報告", "検索について",
            "11位以下を見る", "更新", "おすすめ度",
            "フレーム対応ブラウザ", "Internet Explorer",
            "ログインしてより快適に",
        ]
        # HTMLタグの残骸を除去する関数
        import re
        tag_pattern = re.compile(r'<[^>]{5,}>')  # 5文字以上のHTMLタグ
        # 爆サイがページ上部に挿入するニュース見出しを検出するパターン
        # 特徴: メンエス口コミとは無関係な芸能・事件・政治ニュース
        news_keywords = [
            "逮捕", "容疑", "事件", "判決", "裁判", "検察", "警視庁",  # 事件系
            "アナ、", "アナウンサー", "女優", "俳優", "タレント",  # 芸能系
            "選挙", "国会", "内閣", "首相", "大臣",  # 政治系
            "ドラレコ", "万引き", "強盗", "暴行",  # 犯罪ニュース
            "失恋カルタ", "梅澤美波",  # 特定のニュース
        ]
        lines = []
        for line in text.split("\n"):
            line = line.strip()
            if not line or len(line) <= 3:
                continue
            if any(n in line for n in noise):
                continue
            # HTMLタグの残骸が含まれる行をスキップ
            if tag_pattern.search(line):
                continue
            # ナビゲーションリンクっぽい短い行をスキップ
            if len(line) < 8 and not any(c.isdigit() for c in line):
                continue
            # 爆サイ挿入ニュース見出し判定：
            # ページ先頭付近（まだ口コミ投稿が始まる前）に出現する、
            # メンエスと無関係なニュース行を除去
            # ※口コミ投稿内（#番号の後）のテキストは絶対に消さない
            if len(lines) < 5 and any(nk in line for nk in news_keywords):
                continue
            lines.append(line)
        return "\n".join(lines)[:max_chars]
    except Exception as e:
        return f"(取得エラー: {e})"


def auto_fetch_bakusai_data(area):
    """爆サイデータを自動検索・取得して bakusai_log 形式で返す"""
    if not HAS_DDGS:
        print("   ❌ 自動取得に必要なライブラリがありません。pip install ddgs を実行してください。")
        return None

    # エリア名と関連地域名のマッピング（他地域の結果を除外するため）
    area_aliases = {
        "西宮": ["西宮", "兵庫", "関西", "阪神", "尼崎", "芦屋", "宝塚"],
        "堺": ["堺", "大阪", "関西", "南大阪", "泉州", "泉北"],
        "梅田": ["梅田", "大阪", "関西", "北新地", "キタ"],
        "難波": ["難波", "なんば", "ナンバ", "大阪", "関西", "ミナミ"],
        "神戸": ["神戸", "兵庫", "関西", "三宮", "元町"],
        "京都": ["京都", "関西", "四条", "河原町"],
        "姫路": ["姫路", "兵庫", "関西", "播磨"],
        "三宮": ["三宮", "神戸", "兵庫", "関西"],
        "天王寺": ["天王寺", "大阪", "関西", "阿倍野"],
        "日本橋": ["日本橋", "大阪", "関西", "ミナミ"],
    }
    # エリアに対応するキーワードリスト（マッピングになければエリア名そのものを使用）
    area_keywords = area_aliases.get(area, [area])

    categories = [
        ("摘発情報", f"{area} メンエス 摘発 site:bakusai.com"),
        ("地雷情報", f"{area} メンエス 地雷 site:bakusai.com"),
        ("大当たり情報", f"{area} メンエス 大当たり site:bakusai.com"),
    ]

    all_sections = []
    total_results = 0
    seen_urls = set()  # URL重複排除用

    for cat_name, query in categories:
        print(f"   🔍 {cat_name}を検索中...")
        results = web_search(query, max_results=8)
        section = f"## ■ {cat_name}（{query}）\n"

        if not results:
            section += "(検索結果なし)\n"
        else:
            result_num = 0
            for r in results:
                title = r.get("title", "")
                href = r.get("href", "")
                body = r.get("body", "")

                # --- URL重複チェック ---
                if href in seen_urls:
                    continue
                seen_urls.add(href)

                # --- URLパターンフィルタリング ---
                # 爆サイのトップページや雑談板はスキップ
                if "/areatop/" in href or "/ctgid=104/" in href:
                    continue
                # 「友達に教える」ページはスキップ
                if "/thr_teach/" in href:
                    continue
                # 掲示板一覧ページはスキップ
                if "/thr_tl/" in href:
                    continue

                # --- コンテンツフィルタリング ---
                combined = title + " " + body
                # 検索結果なしページはスキップ
                if "見つかりませんでした" in body:
                    continue

                # --- エリア関連性チェック ---
                # タイトル・スニペット・URLのいずれかにエリア関連キーワードが含まれるか確認
                area_match = False
                check_text = (title + " " + body + " " + href).lower()
                for kw in area_keywords:
                    if kw.lower() in check_text:
                        area_match = True
                        break
                if not area_match:
                    print(f"      ⏭️ エリア外スキップ: {title[:40]}...")
                    continue

                result_num += 1
                section += f"\n--- 結果{result_num}: {title} ---\n"
                section += f"URL: {href}\n"
                section += f"{body}\n"

                # 爆サイURLなら個別投稿の取得を試みる
                if "bakusai.com" in href and HAS_BS4:
                    page_text = fetch_page_text(href, max_chars=2000)
                    if page_text and len(page_text) > 50:
                        section += f"\n【ページ内容】\n{page_text}\n"
                total_results += 1
        all_sections.append(section)
        time.sleep(1)  # レートリミット

    if total_results == 0:
        print("   ⚠️ 検索結果が0件でした。手動入力に切り替えてください。")
        return None

    header = (
        f"# 爆サイ口コミデータ（{area} メンエス）- 自動取得\n"
        f"# 取得日時: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"# 合計 {total_results} 件の検索結果を取得\n\n"
    )
    return header + "\n\n".join(all_sections)


def auto_resolve_shop_urls(shop_names, area):
    """店名リストからDuckDuckGo検索で公式URLを自動取得"""
    if not HAS_DDGS:
        print("   ❌ 自動取得に必要なライブラリがありません。pip install ddgs を実行してください。")
        return None

    # ポータル・レビューサイトのドメイン（公式URLではないもの）
    portal_domains = [
        "bakusai.com", "5ch.net", "twitter.com", "x.com", "google.com",
        "youtube.com", "instagram.com", "facebook.com", "ameblo.jp",
        "esthe-ranking", "es-maniax", "f-esthe-ranking", "es-ban.com",
        "es-king", "aromafudge", "fuzokuex", "futomo", "ura-info",
        "refle.info", "go-mensesthe", "dougo-yuuzuki", "cityheaven",
        "wikipedia.org", "tabelog.com", "hot-pepper",
        # ECサイト・汎用ポータル（店舗の公式サイトではない）
        "rakuten.co.jp", "amazon.co.jp", "yahoo.co.jp",
        # メンエス系ポータル・レビューサイト
        "iromachi.jp", "men-esthe.jp", "oreno-esthe.com",
        # ブログ・SNS・旅行口コミ
        "blog.jp", "tiktok.com", "tripadvisor.jp", "tripadvisor.com",
        # その他の誤ヒットドメイン
        "eslove.jp", "town-night.jp", "mens-mg.com",
        # kking.jp（エステアイ）と biiina.com（口コミ広場）は除外しない
        # → メンエス情報が正確なポータルのため、名前検証でカバーする
    ]

    verified = {}
    for shop_name in shop_names:
        query = f"{shop_name} {area} メンズエステ 公式"
        print(f"   🔍 {shop_name} の公式URL検索中...")
        results = web_search(query, max_results=10)

        official_url = "URLなし"
        for r in results:
            url = r.get("href", "")
            url_lower = url.lower()
            if any(p in url_lower for p in portal_domains):
                continue

            # 店名検証: スニペット（タイトル+本文）に店名が含まれるか確認
            # エリア名は除外し、残りのパーツが全て含まれる必要がある（AND論理）
            snippet = (r.get("title", "") + " " + r.get("body", "")).lower()
            name_parts = [
                p for p in re.split(r'[\s　]+', shop_name)
                if len(p) >= 2 and p != area
            ]
            if name_parts and not all(p.lower() in snippet for p in name_parts):
                missing = [p for p in name_parts if p.lower() not in snippet]
                print(f"      ⚠ 名前不一致スキップ [{','.join(missing)}]: {url[:60]}")
                continue

            official_url = url
            break

        verified[f"{shop_name}（{area}）"] = official_url
        status = "✅" if official_url != "URLなし" else "❌"
        print(f"      {status} {shop_name}: {official_url[:70]}")
        if official_url == "URLなし":
            print(f"         👉 手動検索: {shop_name} {area} メンズエステ 公式")
        time.sleep(0.8)

    return verified


def open_file_for_user(filepath):
    print(f"\n📂 {os.path.basename(filepath)} を開きます。")
    try: os.startfile(filepath)
    except: subprocess.call(['notepad.exe', filepath])
    input(">> 編集が終わったら Enter キーを押してください <<")

def post_to_wordpress(site_config, title, content):
    wp_url = site_config['url'].rstrip('/') + "/wp-json/wp/v2/posts"
    credentials = f"{site_config['user']}:{site_config['pass'].replace(' ', '')}"
    token = base64.b64encode(credentials.encode()).decode('utf-8')
    headers = {'Authorization': f'Basic {token}', 'Content-Type': 'application/json'}
    post_data = {'title': title, 'content': content, 'status': 'draft'}
    print(f"\n📤 WordPressへ送信中... ({site_config['name']})")
    try:
        res = requests.post(wp_url, headers=headers, json=post_data, timeout=60)
        if res.status_code in [200, 201]:
            data = res.json()
            post_link = data.get('link', '')
            print(f"✅ 下書き投稿成功！ ID: {data.get('id')}  URL: {post_link}")
            return post_link or True
        else:
            print(f"❌ 投稿失敗: HTTP {res.status_code}\n{res.text[:200]}")
            return False
    except Exception as e:
        print(f"❌ 投稿エラー: {e}")
        return False

def arrow_menu(title, options, allow_back=False, context=None, back_label="前の画面へ戻る"):
    """矢印キーで選択するメニュー。戻る場合は -1 を返す。
    - ANSI clear でフリッカーを抑制
    - ターミナル幅に応じて説明文と選択肢を省略せず折り返す
    - カーソルが常に画面内に表示されるようビューポートをスクロール
    """
    selected = 0
    clear_console_input_buffer()
    if not msvcrt:
        print("\n" + "="*60)
        print(title)
        print("="*60)
        if context:
            print(context)
        for idx, option in enumerate(options, start=1):
            print(f"  {idx}. {option}")
        if allow_back:
            print("  0. 戻る")
        while True:
            raw = input("番号を入力: ").strip()
            if allow_back and raw in {"0", "b", "B"}:
                return -1
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                return int(raw) - 1
            print("有効な番号を入力してください。")

    def _term_size():
        try:
            return os.get_terminal_size()
        except Exception:
            class _S:
                columns, lines = 80, 30
            return _S()

    def _dw(s):
        """文字列の表示幅（全角=2, 半角=1）"""
        return sum(2 if ord(c) > 0x2E7F else 1 for c in s)

    def _trunc(s, max_w):
        """表示幅 max_w に収まるよう末尾を切る"""
        w, out = 0, []
        for c in s:
            cw = 2 if ord(c) > 0x2E7F else 1
            if w + cw > max_w - 1:
                out.append('…'); break
            out.append(c); w += cw
        return ''.join(out)

    def _wrap_display(s, max_w):
        """表示幅 max_w に収まるよう、全角幅を考慮して折り返す。"""
        s = str(s)
        max_w = max(8, int(max_w or 8))
        if s == "":
            return [""]
        m = re.match(r'^(\s*)', s)
        indent = m.group(1) if m else ""
        if _dw(indent) >= max_w // 2:
            indent = ""
        lines = []
        cur, w = "", 0
        for c in s:
            cw = 2 if ord(c) > 0x2E7F else 1
            if cur and w + cw > max_w:
                lines.append(cur.rstrip())
                cur = indent + c
                w = _dw(indent) + cw
            else:
                cur += c
                w += cw
        if cur or not lines:
            lines.append(cur.rstrip())
        return lines

    while True:
        # 画面を完全クリアしてから描画（スクロール後の残像を防止）
        sys.stdout.write('\033[2J\033[H')
        sys.stdout.flush()

        # 各行末を消去しながら出力するヘルパー（残像防止）
        def _p(s=""):
            sys.stdout.write(str(s) + '\033[K\n')

        ts = _term_size()
        rows, cols = ts.lines, ts.columns
        sep60 = "─" * min(60, cols)
        sep60e = "=" * min(60, cols)

        # --- コンテキスト表示（省略なし・折り返し許可） ---
        overhead = 0
        if context:
            _p(sep60)
            for line in context.split('\n'):
                wrapped = _wrap_display(line, cols - 1)
                for wl in wrapped:
                    _p(wl)
                overhead += len(wrapped)
            _p(sep60)
            _p()
            overhead += 3

        # --- ヘッダー（複数行タイトル対応） ---
        title_lines = []
        for tl in title.split('\n'):
            title_lines.extend(_wrap_display(tl, cols - 4))
        _p(sep60e)
        for tl in title_lines:
            _p(f"  {tl}")
        _p(sep60e)
        _p()
        overhead += 2 + len(title_lines) + 1

        # --- ビューポート計算 ---
        hint_rows = 2
        max_visible = max(5, rows - overhead - hint_rows)

        # --- 番号幅を事前計算（1→" 1."  10→"10." のように桁を揃える） ---
        num_w = len(str(len(options)))
        prefix_total = 4 + num_w + 2

        # --- 折り返し行数計算（番号プレフィックス込み） ---
        def _opt_lines(opt):
            eff_w = max(1, cols - prefix_total)
            wrapped = []
            for raw_line in str(opt).split('\n'):
                wrapped.extend(_wrap_display(raw_line, eff_w))
            return wrapped or [""]

        def _opt_rows(opt):
            return len(_opt_lines(opt))

        cum_rows = [0]
        for o in options:
            cum_rows.append(cum_rows[-1] + _opt_rows(o))
        total_opt_rows = cum_rows[-1]

        # --- ビューポート: selectedが中央付近に来るようtopを決定 ---
        if total_opt_rows <= max_visible:
            top = 0
        else:
            sel_start     = cum_rows[selected]
            ideal_top_row = max(0, sel_start - max_visible // 2)
            ideal_top_row = min(ideal_top_row, total_opt_rows - max_visible)
            top = 0
            for t in range(len(options)):
                if cum_rows[t] >= ideal_top_row:
                    top = t
                    break

        # --- 選択肢表示 ---
        used_rows = 0
        for idx in range(top, len(options)):
            r = _opt_rows(options[idx])
            if used_rows + r > max_visible:
                break
            marker = "▶" if idx == selected else " "
            num_str = f"{idx + 1:{num_w}}."
            prefix = f"  {marker} {num_str} "
            cont_prefix = " " * _dw(prefix)
            for line_no, opt_line in enumerate(_opt_lines(options[idx])):
                _p((prefix if line_no == 0 else cont_prefix) + opt_line)
            used_rows += r

        # --- インジケーター ---
        if total_opt_rows > max_visible:
            _p(f"  （{selected + 1} / {len(options)} 件）")
        _p()
        hint = "  ↑↓: 選択   Enter: 決定"
        if allow_back:
            hint += f"   ESC: {back_label or '前の画面へ戻る'}"
        _p(hint)
        # 残像を消去（メニューより下の残り行を一括消去）
        sys.stdout.write('\033[J')
        sys.stdout.flush()

        key = msvcrt.getwch()
        if key in ('\xe0', '\x00'):
            key2 = msvcrt.getwch()
            if key2 in ('H', 'P'):
                # 連打・押しっぱなし対策: キューに溜まったキーをまとめて処理
                delta = 0
                direction = key2
                delta += -1 if direction == 'H' else 1
                while msvcrt.kbhit():
                    nk = msvcrt.getwch()
                    if nk in ('\xe0', '\x00') and msvcrt.kbhit():
                        nk2 = msvcrt.getwch()
                        if nk2 == 'H':
                            delta -= 1
                        elif nk2 == 'P':
                            delta += 1
                selected = (selected + delta) % len(options)
        elif key == '\r':      # Enter
            return selected
        elif key == '\x1b' and allow_back:  # ESC
            return -1


def menu_back(choice):
    """arrow_menu系の戻る/キャンセル判定を統一する。"""
    return choice is None or choice == -1


def select_api_key(api_keys_list, title="APIキー選択"):
    names = [k['name'] for k in api_keys_list]
    choice = arrow_menu(title, names, allow_back=True, back_label="キャンセル")
    if choice == -1:
        return None
    return api_keys_list[choice]["key"]


def api_keys_for_site(site_config):
    """サイト種別から使用するGemini APIキー候補を返す。"""
    return API_KEYS_MOECHIN if (site_config or {}).get("type") == "C" else API_KEYS_NORMAL


# ============================================================
# 親記事用ユーティリティ
# ============================================================
def save_log_parent(title, conversation_history):
    os.makedirs(PARENT_LOGS, exist_ok=True)
    safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '_', '-')).strip()
    filename = f"log_PARENT_{safe_title}_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    filepath = os.path.join(PARENT_LOGS, filename)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"Title: {title}\n{'='*50}\n\n")
            for entry in conversation_history:
                f.write(f"--- {entry.get('role','Unknown')} ---\n{entry.get('text','')}\n\n")
        print(f"📄 ログ保存: {filename}")
    except Exception as e:
        print(f"⚠️ ログ保存エラー: {e}")

def save_resume_data(resume_file, target_input, initial_instruction, step_outputs, final_content, log_history, metadata=None):
    data = {
        "target_input": target_input,
        "initial_instruction": initial_instruction,
        "step_outputs": step_outputs,
        "final_content": final_content,
        "log_history": log_history,
        "timestamp": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    if metadata:
        data["metadata"] = metadata
    # 従来の1ファイル上書き（後方互換）
    with open(resume_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # resume_dataフォルダにも蓄積保存（キーワード+タイムスタンプ付き）
    os.makedirs(RESUME_DIR, exist_ok=True)
    _safe_kw = re.sub(r'[\\/:*?"<>|]', '', target_input[:25]).strip() if target_input else "nokw"
    # 親/もえちん/子の判別をファイル名に含める
    if "moechin" in os.path.basename(resume_file):
        _prefix = "moechin"
    elif "child" in os.path.basename(resume_file):
        _prefix = "child"
    else:
        _prefix = "normal"
    _ts = datetime.datetime.now().strftime('%Y%m%d_%H%M')
    _accum_path = os.path.join(RESUME_DIR, f"resume_{_prefix}_{_safe_kw}_{_ts}.json")
    with open(_accum_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 7日超の古いresumeファイルを自動削除
    try:
        _cutoff = time.time() - 7 * 86400  # 7日前のUNIXタイムスタンプ
        for _old_f in glob.glob(os.path.join(RESUME_DIR, "resume_*.json")):
            if os.path.getmtime(_old_f) < _cutoff:
                os.remove(_old_f)
    except Exception:
        pass  # クリーンアップ失敗は無視

def load_resume_data(resume_file):
    if os.path.exists(resume_file):
        try:
            with open(resume_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return None


def build_parent_resume_metadata(site_choice, selected_site, prompt_key, prompt_sub_path, addition_path=None, suppress_scroll_cta=False):
    return {
        "site_choice": site_choice,
        "site_name": selected_site.get("name", "") if selected_site else "",
        "site_type": selected_site.get("type", "") if selected_site else "",
        "prompt_key": prompt_key,
        "prompt_sub_path": prompt_sub_path,
        "addition_path": addition_path or "",
        "addition_name": os.path.basename(addition_path) if addition_path else "",
        "suppress_scroll_cta": bool(suppress_scroll_cta),
    }


def _resume_metadata(resume_data):
    return (resume_data or {}).get("metadata") or {}


def _parent_resume_status(resume_data):
    return str(_resume_metadata(resume_data).get("resume_status", "") or "").strip().lower()


def _is_completed_parent_resume(resume_data):
    """親記事生成の完了済みデータを、中断再開候補から除外するための判定。"""
    if not resume_data:
        return False
    meta = _resume_metadata(resume_data)
    status = _parent_resume_status(resume_data)
    if status == "completed" or meta.get("completed") is True:
        return True
    if status == "interrupted" or meta.get("completed") is False:
        return False

    # 旧データ互換: metadataがない完了済みresumeは、step06出力と有効HTMLで判断する。
    step_outputs = resume_data.get("step_outputs", {}) or {}
    final_content = resume_data.get("final_content", "") or ""
    if "step06" in step_outputs and final_content:
        try:
            return _is_valid_parent_html(final_content)
        except Exception:
            return False
    return False


def _is_interrupted_parent_resume(resume_data):
    """親記事生成で「続きから再開しますか？」を出してよい中断データだけを通す。"""
    if not resume_data:
        return False
    status = _parent_resume_status(resume_data)
    meta = _resume_metadata(resume_data)
    if status == "interrupted" or meta.get("completed") is False:
        return True
    if _is_completed_parent_resume(resume_data):
        return False

    step_outputs = resume_data.get("step_outputs", {}) or {}
    final_content = resume_data.get("final_content", "") or ""
    # 旧データ互換: 途中ステップがあるがstep06まで到達していないものは再開候補。
    if step_outputs and "step06" not in step_outputs:
        return True
    # 失敗直後にstep_outputsが空でも、キーワード等が保存されていれば再開候補。
    if resume_data.get("target_input") and resume_data.get("initial_instruction") and not final_content:
        return True
    return False


def is_yes_input(value):
    """再開確認などの yes 判定。全角入力や日本語入力にも対応する。"""
    v = normalize_user_input(value).lower()
    return v in ("y", "yes", "はい", "は", "再開", "続行")


def is_back_input(value):
    """戻る入力の判定。全角ｂ/Ｂも b として扱う。"""
    return normalize_user_input(value).lower() == "b"


def normalize_user_input(value):
    """ユーザー入力の判定用に全角英数字などを半角相当に正規化する。自由文の保存前加工には使わない。"""
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def parse_menu_number(value, min_value=None, max_value=None):
    """番号入力を全角/半角どちらでも受け取り、範囲外や想定外は None にする。"""
    text = normalize_user_input(value)
    if not re.fullmatch(r"\d+", text):
        return None
    number = int(text)
    if min_value is not None and number < min_value:
        return None
    if max_value is not None and number > max_value:
        return None
    return number

def fetch_competitor_urls(keyword, num_results=10):
    """SearchAPI.io優先で競合URLを取得する。失敗時はDDG、最後は手動入力へ戻す。"""
    keyword = (keyword or "").strip()
    if not keyword:
        return []

    urls = []
    api_key = _get_secret_from_env("SEARCHAPI_API_KEY")
    if api_key:
        print(f"   🔎 SearchAPI.ioで競合URLを取得中...（{keyword}）")
        try:
            res = requests.get(
                "https://www.searchapi.io/api/v1/search",
                params={
                    "engine": "google",
                    "q": keyword,
                    "api_key": api_key,
                    "google_domain": "google.co.jp",
                    "hl": "ja",
                    "gl": "jp",
                    "num": min(max(num_results, 1), 20),
                },
                timeout=10,
            )
            if res.status_code in (401, 403):
                print("   ⚠️ SearchAPI.io認証エラー。手動入力に切り替えます。")
            elif res.status_code in (429, 402):
                print("   ⚠️ SearchAPI.ioの上限/課金エラー。手動入力に切り替えます。")
            elif res.status_code != 200:
                print(f"   ⚠️ SearchAPI.io HTTP {res.status_code}。手動入力に切り替えます。")
            else:
                data = res.json()
                raw_path = _save_serp_work_file(keyword, "competitor_searchapi_raw", data, "json")
                organic = data.get("organic_results") or []
                for item in organic:
                    if not isinstance(item, dict):
                        continue
                    link = (item.get("link") or item.get("url") or "").strip()
                    if not link or not link.startswith(("http://", "https://")):
                        continue
                    if "google." in urllib.parse.urlparse(link).netloc:
                        continue
                    urls.append(link)
                    if len(urls) >= num_results:
                        break
                if urls:
                    print(f"   ✅ 競合URL候補 {len(urls)}件を取得しました。raw保存: {raw_path}")
                    return list(dict.fromkeys(urls))
                print("   ⚠️ SearchAPI.ioで競合URL候補が見つかりませんでした。")
        except requests.exceptions.RequestException as e:
            reason = str(e)
            if "Failed to resolve" in reason or "NameResolutionError" in reason or "getaddrinfo failed" in reason:
                print("   ⚠️ SearchAPI.ioに接続できませんでした（DNS/ネットワーク解決エラー）。")
            elif "timed out" in reason.lower() or "timeout" in reason.lower():
                print("   ⚠️ SearchAPI.ioの応答が時間内に返りませんでした。")
            else:
                print(f"   ⚠️ SearchAPI.io取得エラー: {type(e).__name__}")
            print("      → 自動取得を中止し、手動確認へ切り替えます。")
        except Exception as e:
            print(f"   ⚠️ SearchAPI.io取得エラー: {type(e).__name__}")
            print("      → 自動取得を中止し、手動確認へ切り替えます。")
    else:
        print("   ℹ️ SEARCHAPI_API_KEY未設定のため、SearchAPI.io自動取得はスキップします。")

    if HAS_DDGS:
        print("   🔎 DuckDuckGoで競合URL候補を取得中...")
        results = web_search(keyword, max_results=num_results)
        for item in results:
            link = (item.get("href") or item.get("url") or "").strip()
            if link and link.startswith(("http://", "https://")):
                urls.append(link)
        urls = list(dict.fromkeys(urls))[:num_results]
        if urls:
            print(f"   ✅ DuckDuckGoで競合URL候補 {len(urls)}件を取得しました。")
            return urls

    print("   ℹ️ 自動取得できなかったため、従来どおり手動入力へ切り替えます。")
    return []


def collect_competitor_urls(keyword, num_results=10):
    """競合URLを取得する。自動取得成功時はChromeを開かず、失敗時だけ手動方法を選ぶ。"""
    auto_urls = fetch_competitor_urls(keyword, num_results=num_results)
    if auto_urls:
        chosen_indices = arrow_menu_multiselect(
            "競合URLを選択（Space: 選択切替、Enter: 確定）",
            auto_urls,
            default_checked=[i < min(5, len(auto_urls)) for i in range(len(auto_urls))],
        )
        chosen_urls = [auto_urls[i] for i in chosen_indices]
        print(f"\n   ✅ {len(chosen_urls)}件のURLを使用します")
        extra = get_multiline_input("\n追加したいURLがあれば入力してください（不要ならそのままEnter3回）:")
        competitor_urls = "\n".join(chosen_urls)
        if extra.strip():
            competitor_urls += "\n" + extra.strip()
        return competitor_urls

    manual_idx = arrow_menu(
        "競合URLの取得方法を選択してください\n"
        "  自動取得に失敗しました。必要な場合だけChromeを開きます。",
        [
            "ChromeでGoogle検索を開き、URLを手動で貼り付ける",
            "Chromeを開かず、手元のURLを貼り付ける",
            "競合URLなしで続行する",
        ],
        allow_back=False
    )
    if manual_idx == 0 and keyword:
        search_url = "https://www.google.com/search?" + urllib.parse.urlencode({"q": keyword})
        print(f"\n   🔍 Chromeで「{keyword}」のGoogle検索を開きます...")
        webbrowser.open(search_url)
        print("   ※ 検索結果から競合URLをコピーして、次の入力欄へ貼り付けてください。")

    if manual_idx in (0, 1):
        return get_multiline_input("\n【競合URL】(Enter3回):")

    print("   ℹ️ 競合URLなしで続行します。")
    return ""


def check_urls_in_research(content):
    """リサーチファイル内のURLを並列チェックし、問題URLを除去するか選択させる。修正後のcontentを返す。"""
    url_pattern = re.compile(r'https?://[^\s\u3000、。」」"\'<>\]）)]+')
    urls = list(dict.fromkeys(url_pattern.findall(content)))  # 重複除去・順序保持

    if not urls:
        print("   リサーチファイル内にURLが見つかりませんでした。")
        return content

    print(f"   {len(urls)}件のURLをチェック中...")

    def _check(url):
        alive, status, _err = _check_url_alive(url, timeout=6)
        return (url, status, "ok" if alive else "dead")

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(_check, urls))

    dead = [(u, s) for u, s, st in results if st in ("dead", "error")]
    ok_count = len(urls) - len(dead)
    print(f"\n   ✅ アクセス可能: {ok_count}件 / ⚠️ 到達不可または要確認: {len(dead)}件")

    if not dead:
        print("   すべてのURLは正常にアクセスできました。")
        return content

    print("\n   ⚠️ 読者が開けない可能性があるURL:")
    for url, status in dead:
        label = f"HTTP {status}" if status else "到達不可（DNS/SSL/タイムアウト等）"
        print(f"      [{label}] {url}")

    choice = arrow_menu(
        "問題URLの処理方法",
        ["リサーチ内容から除去する（読者が開けないURLを材料にしない）", "そのまま使用する"],
        allow_back=False
    )
    if choice == 0:
        for url, _ in dead:
            content = content.replace(url, "（アクセス不可のためURLを削除）")
        print(f"   ✅ {len(dead)}件の到達不可URLを材料から除外しました。")
    else:
        print("   ⚠️ 問題URLをそのまま使用します（記事内に404リンクが生成される可能性があります）。")

    return content


def _extract_html_http_links(html):
    """最終HTML内の外部HTTPリンクを重複なしで抽出する。アフィリエイトショートコードは対象外。"""
    links = re.findall(r'<a\b[^>]*\bhref=["\'](https?://[^"\']+)["\']', html or "", flags=re.IGNORECASE)
    cleaned = []
    for url in links:
        url = url.strip()
        if not url:
            continue
        if url.startswith("[af_url"):
            continue
        cleaned.append(url)
    return list(dict.fromkeys(cleaned))


def _check_url_alive(url, timeout=8):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; article-link-checker/1.0)"}
    try:
        r = requests.head(url, headers=headers, timeout=timeout, allow_redirects=True)
        if r.status_code < 400:
            return True, r.status_code, ""
        # HEADだけ弾くサイトがあるため、GETで一度だけ確認する。
        if r.status_code in (403, 405, 406, 429):
            g = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True, stream=True)
            g.close()
            return g.status_code < 400, g.status_code, ""
        return False, r.status_code, ""
    except Exception as e:
        try:
            g = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True, stream=True)
            g.close()
            return g.status_code < 400, g.status_code, ""
        except Exception as e2:
            return False, 0, str(e2 or e)


def _unlink_url_in_html(html, url):
    """壊れたURLのaタグだけ解除し、アンカーテキストは残す。"""
    escaped_url = re.escape(url)
    pattern = re.compile(
        rf'<a\b[^>]*\bhref=["\']{escaped_url}["\'][^>]*>(.*?)</a>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    return pattern.sub(lambda m: m.group(1), html)


PUBLIC_REFERENCE_DOMAIN_SUFFIXES = (
    ".go.jp",
    ".lg.jp",
    ".ac.jp",
    ".ed.jp",
    ".gov",
    ".edu",
    ".int",
)

PUBLIC_REFERENCE_DOMAINS = {
    "caa.go.jp",
    "e-stat.go.jp",
    "jftc.go.jp",
    "jma.go.jp",
    "kokusen.go.jp",
    "meti.go.jp",
    "mhlw.go.jp",
    "mlit.go.jp",
    "nhk.or.jp",
    "nta.go.jp",
    "soumu.go.jp",
    "jeita.or.jp",
}


def _reference_link_should_remain_clickable(url):
    """参考文献リストでクリック可能な外部リンクとして残すか判定する。

    競合記事・アフィリエイト記事・個人ブログへリンクパワーを流さないため、
    原則として公的機関・教育機関・主要な準公的団体だけリンクを維持する。
    それ以外は出典名テキストとして残し、aタグだけ解除する。
    """
    try:
        host = urllib.parse.urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
    except Exception:
        return False
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return False
    if host in PUBLIC_REFERENCE_DOMAINS:
        return True
    return any(host.endswith(suffix) for suffix in PUBLIC_REFERENCE_DOMAIN_SUFFIXES)


def _strip_low_authority_reference_links(html_text):
    """参考文献リスト内の低権威・競合系リンクを解除する。

    本文中の通常リンクやCTAには触らず、参考文献セクション内の<a>だけを対象にする。
    """
    if not html_text or "参考文献" not in html_text:
        return html_text, 0

    parts = re.split(
        r'(<h[23][^>]*>.*?参考文献.*?</h[23]>|\[参考文献リスト\])',
        html_text,
        maxsplit=1,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if len(parts) != 3:
        return html_text, 0

    before, heading, refs = parts
    removed_count = 0

    def repl_link(match):
        nonlocal removed_count
        url = match.group(1).strip()
        text = match.group(2)
        if _reference_link_should_remain_clickable(url):
            return match.group(0)
        removed_count += 1
        return text

    refs = re.sub(
        r'<a\b[^>]*\bhref=["\'](https?://[^"\']+)["\'][^>]*>(.*?)</a>',
        repl_link,
        refs,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return before + heading + refs, removed_count


def _strip_low_authority_citation_links(html_text):
    """本文中の引用・出典ブロック内にある低権威・競合系リンクを解除する。

    参考文献リストだけでなく、blockquote/cite 内に競合記事やアフィリエイト記事への
    リンクが残ると本文から外部へリンクパワーを渡してしまうため、出典名テキストだけ残す。
    CTA、通常本文リンク、[af_url] ショートコードには触らない。
    """
    if not html_text:
        return html_text, 0

    removed_count = 0

    def unlink_low_authority_links(block):
        nonlocal removed_count

        def repl_link(match):
            nonlocal removed_count
            url = match.group(1).strip()
            text = match.group(2)
            if _reference_link_should_remain_clickable(url):
                return match.group(0)
            removed_count += 1
            return text

        return re.sub(
            r'<a\b[^>]*\bhref=["\'](https?://[^"\']+)["\'][^>]*>(.*?)</a>',
            repl_link,
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )

    def repl_cite(match):
        return unlink_low_authority_links(match.group(0))

    # citeを先に処理して、blockquote全体の処理時に二重カウントされないようにする。
    html_text = re.sub(r'<cite\b[^>]*>[\s\S]*?</cite>', repl_cite, html_text, flags=re.IGNORECASE)
    html_text = re.sub(
        r'<blockquote\b[^>]*>[\s\S]*?</blockquote>',
        repl_cite,
        html_text,
        flags=re.IGNORECASE,
    )
    return html_text, removed_count


def validate_final_html_links(html, label="最終HTML"):
    """投稿直前に最終HTML内リンクを検査し、読者が開けない可能性のあるリンクだけ解除する。"""
    links = _extract_html_http_links(html)
    if not links:
        print(f"   ℹ️ {label}: チェック対象の外部リンクはありません。")
        return html, []

    print(f"\n🔗 {label}のリンク安全チェック: {len(links)}件")
    print("   ※ 読者が開けない可能性があるURLは、本文リンクだけ解除します（文字は残します）。")

    def _check(url):
        alive, status, err = _check_url_alive(url)
        return url, alive, status, err

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(_check, links))

    broken = [(u, s, e) for u, ok, s, e in results if not ok]
    ok_count = len(links) - len(broken)
    print(f"   ✅ アクセス可能: {ok_count}件 / ⚠️ 到達不可または要確認: {len(broken)}件")

    if not broken:
        return html, []

    print("   ⚠️ 読者保護のためリンク解除するURL:")
    fixed = html
    for url, status, err in broken:
        reason = f"HTTP {status}" if status else f"到達不可（DNS/SSL/タイムアウト等）: {err[:80]}"
        print(f"      [{reason}] {url}")
        fixed = _unlink_url_in_html(fixed, url)

    print(f"   ✅ {len(broken)}件を安全化しました（リンクだけ解除し、アンカーテキストは本文に残します）。")
    return fixed, broken


def _extract_image_urls_from_text(text):
    """足し算PromptやJSONから画像URLだけを重複なしで抽出する。"""
    if not text:
        return []
    urls = []
    patterns = [
        r'<img\b[^>]*\bsrc=["\']([^"\']+)["\']',
        r'"url"\s*:\s*"(https?://[^"]+)"',
        r"'url'\s*:\s*'(https?://[^']+)'",
    ]
    for pattern in patterns:
        urls.extend(re.findall(pattern, text, flags=re.IGNORECASE))
    image_urls = []
    for url in urls:
        clean = (url or "").strip()
        if not clean:
            continue
        if re.search(r'\.(?:jpg|jpeg|png|webp|gif)(?:[?#].*)?$', clean, flags=re.IGNORECASE):
            image_urls.append(clean)
    return list(dict.fromkeys(image_urls))


def _has_embedded_h2_image_set(add_prompt):
    """足し算Prompt内にジャンル専用のH2画像セットが直接入っているか判定する。"""
    if not add_prompt:
        return False
    if "H2見出し直下への画像自動挿入" not in add_prompt:
        return False
    return len(_extract_image_urls_from_text(add_prompt)) >= 2


def _extract_h2_image_objects(add_prompt):
    """足し算Prompt内のH2画像JSON配列を、可能な範囲で取り出す。"""
    if not add_prompt:
        return []
    arrays = re.findall(r'\[\s*\{[\s\S]*?\}\s*\]', add_prompt)
    candidates = []
    for block in arrays:
        if '"url"' not in block:
            continue
        try:
            parsed = json.loads(block)
        except Exception:
            continue
        if isinstance(parsed, list):
            imgs = [x for x in parsed if isinstance(x, dict) and x.get("url")]
            if imgs:
                candidates.append(imgs)
    if not candidates:
        return []
    return max(candidates, key=len)


def _replace_first_h2_image_array(add_prompt, images):
    """足し算Prompt内の最初の画像JSON配列を置換する。失敗時は元テキストを返す。"""
    if not add_prompt:
        return add_prompt
    new_json = json.dumps(images, ensure_ascii=False, indent=2)
    arrays = re.findall(r'\[\s*\{[\s\S]*?\}\s*\]', add_prompt)
    for block in arrays:
        if '"url"' not in block:
            continue
        try:
            parsed = json.loads(block)
        except Exception:
            continue
        if isinstance(parsed, list) and any(isinstance(x, dict) and x.get("url") for x in parsed):
            return add_prompt.replace(block, new_json, 1)
    return add_prompt


def _topic_text_for_image_filter(target_input, addition_path):
    parts = [target_input or ""]
    if addition_path:
        base = os.path.basename(addition_path)
        parts.append(os.path.splitext(base)[0])
    return " ".join(parts)


def _is_generic_image_keyword(keyword):
    generic = {
        "相談", "料金", "費用", "価格", "比較", "検討", "選択", "方法",
        "プロ", "信頼", "安心", "不安", "悩み", "期待", "一歩",
        "専門", "説明", "サービス", "満足", "感謝", "対応", "迅速",
        "透明性", "納得", "解決", "希望", "未来", "幸せ", "家族",
        "トラブル", "困惑", "突然", "故障", "壊れた", "作業員",
    }
    return str(keyword).strip() in generic


def _focus_embedded_h2_images(add_prompt, target_input, addition_path, broad_threshold=12):
    """広すぎる埋め込み画像セットは、記事テーマに合う画像だけへ絞る。"""
    images = _extract_h2_image_objects(add_prompt)
    if len(images) <= broad_threshold:
        return add_prompt, _extract_image_urls_from_text(add_prompt), "embedded"

    topic = _topic_text_for_image_filter(target_input, addition_path)
    focused = []
    for img in images:
        keywords = img.get("keywords", [])
        if not isinstance(keywords, list):
            keywords = []
        meaningful = [str(k).strip() for k in keywords if str(k).strip() and not _is_generic_image_keyword(k)]
        if any(k and (k in topic or topic in k) for k in meaningful):
            focused.append(img)

    if focused:
        focused_prompt = _replace_first_h2_image_array(add_prompt, focused)
        return focused_prompt, _extract_image_urls_from_text(json.dumps(focused, ensure_ascii=False)), "focused"

    empty_prompt = _replace_first_h2_image_array(add_prompt, [])
    return empty_prompt, [], "empty"


def _addition_keys_from_path(addition_path):
    """足し算Prompt名から、画像JSONとの紐づけに使う候補キーを作る。"""
    if not addition_path:
        return set()
    base = os.path.basename(addition_path)
    stem = os.path.splitext(base)[0]
    keys = {base, stem, base.lower(), stem.lower()}
    return {k for k in keys if k}


def _image_matches_addition(img, addition_keys):
    """h2_images.jsonの画像が選択中の足し算Prompt専用かを判定する。"""
    if not addition_keys:
        return False
    fields = [
        img.get("addition_file", ""),
        img.get("addition_key", ""),
        img.get("genre", ""),
        img.get("genre_id", ""),
        img.get("category", ""),
    ]
    normalized = {str(v).strip() for v in fields if str(v).strip()}
    normalized |= {v.lower() for v in normalized}
    return bool(normalized & addition_keys)


def _select_h2_images_for_addition(all_images, site_name, addition_path):
    """選択中の足し算Promptに対応するH2画像だけを選ぶ。広すぎるサイト全体注入は避ける。"""
    site_images = [img for img in all_images if img.get("source") == site_name]
    addition_keys = _addition_keys_from_path(addition_path)
    addition_images = [
        img for img in site_images
        if _image_matches_addition(img, addition_keys)
    ]
    if addition_images:
        return addition_images, "addition"
    return [], "none"


def _remove_disallowed_h2_images(html, allowed_urls):
    """H2直下の画像が許可リスト外なら削除する。本文中の通常画像までは触らない。"""
    allowed = {u.strip() for u in (allowed_urls or []) if u and u.strip()}
    if not html or not allowed:
        return html, []

    removed = []
    pattern = re.compile(
        r'(<h2\b[^>]*>.*?</h2>\s*)(<img\b[^>]*\bsrc=["\']([^"\']+)["\'][^>]*>\s*)',
        flags=re.IGNORECASE | re.DOTALL,
    )

    def repl(match):
        src = (match.group(3) or "").strip()
        if src in allowed:
            return match.group(0)
        removed.append(src)
        return match.group(1)

    fixed = pattern.sub(repl, html)
    return fixed, removed


def arrow_menu_multiselect(title, options, default_checked=None):
    """矢印キー移動 + Space で選択切替 + Enter で確定する複数選択メニュー。
    戻り値: 選択されたインデックスのリスト
    default_checked: bool のリスト。None の場合は全て未選択。
    """
    cursor  = 0
    checked = list(default_checked) if default_checked else [False] * len(options)
    clear_console_input_buffer()
    if not msvcrt:
        print("\n" + "="*60)
        print(title)
        print("="*60)
        for idx, option in enumerate(options, start=1):
            mark = "[選択]" if checked[idx - 1] else "[----]"
            print(f"  {idx}. {mark} {option}")
        raw = input("開く番号をカンマ区切りで入力（空Enter=現在の選択）: ").strip()
        if raw:
            checked = [False] * len(options)
            for part in re.split(r"[,、\s]+", raw):
                if part.isdigit() and 1 <= int(part) <= len(options):
                    checked[int(part) - 1] = True
        return [i for i, value in enumerate(checked) if value]

    def _term_size():
        try:    return os.get_terminal_size()
        except:
            class _S: columns, lines = 80, 30
            return _S()
    def _dw(s):
        return sum(2 if ord(c) > 0x2E7F else 1 for c in s)

    def _wrap_display(s, max_w):
        s = str(s)
        max_w = max(8, int(max_w or 8))
        if s == "":
            return [""]
        m = re.match(r'^(\s*)', s)
        indent = m.group(1) if m else ""
        if _dw(indent) >= max_w // 2:
            indent = ""
        lines = []
        cur, w = "", 0
        for c in s:
            cw = 2 if ord(c) > 0x2E7F else 1
            if cur and w + cw > max_w:
                lines.append(cur.rstrip())
                cur = indent + c
                w = _dw(indent) + cw
            else:
                cur += c
                w += cw
        if cur or not lines:
            lines.append(cur.rstrip())
        return lines

    PAGE_SIZE = 15
    while True:
        sys.stdout.write('\033[2J\033[H')
        sys.stdout.flush()
        def _p(s=""):
            sys.stdout.write(str(s) + '\033[K\n')

        ts = _term_size()
        cols = ts.columns
        sep = "=" * min(60, cols)

        _p(sep)
        for tl in title.split('\n'):
            for wl in _wrap_display(tl, cols - 4):
                _p(f"  {wl}")
        _p(sep)
        _p()

        # ページング
        total = len(options)
        page  = cursor // PAGE_SIZE
        start = page * PAGE_SIZE
        end   = min(start + PAGE_SIZE, total)

        for i in range(start, end):
            marker = "▶" if i == cursor else " "
            check  = "選択" if checked[i] else "----"
            label  = options[i]
            prefix = f"  {marker} [{check}] "
            cont_prefix = " " * _dw(prefix)
            wrapped_label = []
            for raw_line in str(label).split('\n'):
                wrapped_label.extend(_wrap_display(raw_line, cols - _dw(prefix) - 1))
            for line_no, wl in enumerate(wrapped_label or [""]):
                _p((prefix if line_no == 0 else cont_prefix) + wl)

        _p()
        page_info = f"  {start+1}〜{end} / 全{total}件"
        if total > PAGE_SIZE:
            page_info += "  （↑↓でページ送り）"
        _p(page_info)
        _p("  Space: 選択切替   Enter: 決定   ESC: キャンセル")
        _p("  [選択] = 対象   [----] = 対象外")
        sys.stdout.write('\033[J')
        sys.stdout.flush()

        key = msvcrt.getwch()
        if key in ('\xe0', '\x00'):
            key2 = msvcrt.getwch()
            if key2 == 'H':   cursor = (cursor - 1) % total
            elif key2 == 'P': cursor = (cursor + 1) % total
        elif key == ' ':
            checked[cursor] = not checked[cursor]
        elif key == '\r':
            return [i for i in range(total) if checked[i]]
        elif key == '\x1b':
            return []


def extract_internal_links(step_outputs):
    """ステップ出力から内部リンク案を抽出"""
    all_text = "\n".join(step_outputs.values())
    lines = all_text.split('\n')
    extracted = []
    is_extracting = False
    for line in lines:
        if not is_extracting:
            if re.search(r'内部リンク.*案', line) or "内部リンクトピック" in line:
                is_extracting = True
                extracted.append(line)
        else:
            if re.match(r'^#{1,3}\s', line) and "内部リンク" not in line:
                break
            extracted.append(line)
    return "\n".join(extracted).strip()

def extract_wp_search_keywords(topic_title):
    """
    内部リンクトピック案のタイトルからWordPress検索用キーワードを抽出する。
    例: 「ED治療のオンライン診療ガイド：メリット・デメリットと…」
      → 「ED治療 オンライン診療」
    """
    # ：｜【】の前だけ取る
    base = re.split(r'[：｜【】\|]', topic_title)[0].strip()
    # よく使われる末尾の不要語を除去
    base = re.sub(r'(ガイド|解説|方法|選び方|進め方|まとめ|について|とは|入門|活用|比較|完全版|全知識|徹底|一覧)$', '', base).strip()
    # 助詞・接続詞で分割して名詞句を取り出す
    parts = re.split(r'[のとがをにでやへたも]', base)
    # 2文字以上の部分のみ採用
    keywords = [p.strip() for p in parts if len(p.strip()) >= 2]
    # 先頭3語までをスペース区切りで結合
    result = ' '.join(keywords[:3])
    # 万一空になったら元のbase先頭15文字にフォールバック
    return result if result else base[:15]


def _clean_internal_link_topic_text(text):
    """WordPress検索用に、内部リンク案タイトルから装飾と不要語を落とす。"""
    text = re.sub(r'<[^>]+>', ' ', text or "")
    text = re.sub(r'\*\*|__|`|#|>|\[|\]', ' ', text)
    text = re.sub(r'リンク先トピック案|この記事内での役割|担当者へのアクション提案', ' ', text)
    text = re.sub(r'[：:｜|].*$', ' ', text)
    text = re.sub(r'（.*?）|\(.*?\)', ' ', text)
    text = re.sub(r'[「」『』]', ' ', text)
    text = re.sub(r'[!！?？、。，．・/／]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _wp_search_terms_from_text(text):
    """長い日本語タイトルから、WordPress検索に使う短い語句を抽出する。"""
    cleaned = _clean_internal_link_topic_text(text)
    cleaned = re.sub(r'自分でできる|自力でできる|最大限に活用する|最大限に活用|具体的な|失敗しないための|後悔しないための', ' ', cleaned)
    stop_terms = {
        "完全", "徹底", "解説", "ガイド", "まとめ", "比較", "方法", "選び方",
        "進め方", "入門", "一覧", "全知識", "活用", "秘訣", "ポイント",
        "メリット", "デメリット", "チェックリスト", "完全ガイド", "徹底解説",
        "成功", "失敗", "向け", "ため", "する", "できる", "知っておきたい",
        "対処法", "活用術", "具体", "最大限", "徹底解説", "自分", "抑える", "節約術",
        "完了", "流れ", "注意点", "自宅", "最適", "最適な", "良い", "良いのか",
        "初期診断", "診断", "確認", "事項", "手順", "ステップ", "プロセス",
        "映らない時",
        "コツ",
    }
    broad_single_terms = {
        "費用", "料金", "比較", "方法", "選び方", "使い方", "ポイント", "注意点",
        "口コミ", "評判", "完了", "流れ", "種類", "自宅", "テレビ", "アンテナ",
        "工事", "依頼", "診断", "対処", "確認", "保証", "支払い", "映らない時",
        "コツ",
    }
    suffix_pattern = re.compile(
        r'(完全ガイド|徹底解説|チェックリスト|ガイド|解説|方法|選び方|進め方|まとめ|入門|一覧|全知識|活用術|秘訣|ポイント|対処法)$'
    )
    # 「できる」の「で」など、語の一部を助詞として割ってしまうと
    # 「きる対処法」のような検索候補が出るため、単独の「で」は分割対象にしない。
    raw_parts = re.split(r'\s+|と|や|から|まで|なら|とは|での|の|を|に|へ|が|は|も', cleaned)
    terms = []
    for part in raw_parts:
        t = part.strip()
        if not t:
            continue
        t = suffix_pattern.sub('', t).strip()
        t = re.sub(r'^(きる|する|なる|できる)', '', t).strip()
        t = re.sub(r'(する|できる|したい|した|して)$', '', t).strip()
        t = re.sub(r'(以外|向け)$', '', t).strip()
        if len(t) < 2:
            continue
        if t in stop_terms:
            continue
        if t in broad_single_terms:
            continue
        if re.fullmatch(r'[0-9]+', t):
            continue
        terms.append(t)
    return list(dict.fromkeys(terms))


def build_wp_search_queries(topic_title, proposal_text="", max_queries=6):
    """内部リンク案から、WordPress検索用の候補クエリを複数作る。"""
    quoted = []
    # 役割説明文中の引用（例: 「どんなアンテナが良いのか」）は
    # 検索語として弱いことが多いため、基本はトピック名の引用だけ使う。
    quoted.extend([q.strip() for q in re.findall(r'[「『](.*?)[」』]', topic_title or "") if len(q.strip()) >= 2])

    terms = _wp_search_terms_from_text(topic_title)
    # proposal内のトピック行から補完
    topic_match = re.search(r'リンク先トピック案[:：]\s*(.+)', proposal_text or "")
    if topic_match:
        quoted.extend([q.strip() for q in re.findall(r'[「『](.*?)[」』]', topic_match.group(1)) if len(q.strip()) >= 2])
        for t in _wp_search_terms_from_text(topic_match.group(1)):
            if t not in terms:
                terms.append(t)

    queries = []

    def add(q):
        q = re.sub(r'\s+', ' ', (q or "").strip())
        if q and q not in queries:
            queries.append(q)

    topic_for_rules = f"{topic_title or ''} {proposal_text or ''}"
    if "アンテナ" in topic_for_rules and "種類" in topic_for_rules:
        add("アンテナ 種類")
        if re.search(r'デザインアンテナ|八木式', topic_for_rules):
            add("デザインアンテナ 八木式")
        if "地デジ" in topic_for_rules:
            add("地デジ アンテナ")
        if re.search(r'BS|CS', topic_for_rules):
            add("BS CS アンテナ")
    if "テレビ" in topic_for_rules and re.search(r'映らない|映らなく', topic_for_rules):
        add("テレビ 映らない")
        if re.search(r'E202|エラーコード', topic_for_rules):
            add("E202 エラー")
    if "オンライン結婚相談所" in topic_for_rules:
        if re.search(r'選び方|選ぶ|比較検討', topic_for_rules):
            add("オンライン結婚相談所 選び方")
        if re.search(r'成功|コツ|活動方法|ノウハウ', topic_for_rules):
            add("オンライン結婚相談所 コツ")
        add("オンライン結婚相談所")
        if "プロフィール" in topic_for_rules:
            add("オンライン結婚相談所 プロフィール")
        if "カウンセラー" in topic_for_rules:
            add("オンライン結婚相談所 カウンセラー")
        if "お見合い" in topic_for_rules:
            add("オンライン結婚相談所 お見合い")
    if "アンテナ工事" in topic_for_rules and "依頼" in topic_for_rules:
        add("アンテナ工事 依頼")
        if "流れ" in topic_for_rules:
            add("アンテナ工事 流れ")
        if "見積" in topic_for_rules or "見積もり" in topic_for_rules:
            add("アンテナ工事 見積もり")
        if "保証" in topic_for_rules:
            add("アンテナ工事 保証")

    #  quoted terms are often the core intent: 「費用」「お見合い」など
    broad_quoted_terms = {"費用", "料金", "方法", "選び方", "ポイント", "注意点", "口コミ", "評判", "流れ", "完了", "種類", "コツ"}
    for q in quoted:
        if q not in broad_quoted_terms and not re.search(r'どんな|良いのか|何を|どう', q):
            add(q)
        if terms and terms[0] != q:
            add(f"{terms[0]} {q}")

    if len(terms) >= 2:
        add(" ".join(terms[:2]))
    if len(terms) >= 3:
        add(" ".join(terms[:3]))
    too_broad_single = broad_quoted_terms | {"自分", "抑える", "相場", "節約術", "アンテナ", "テレビ", "種類", "完了", "流れ", "自宅", "コツ"}
    for t in terms[:4]:
        if t not in too_broad_single:
            add(t)

    fallback = extract_wp_search_keywords(topic_title)
    if not queries:
        add(fallback)
    return queries[:max_queries]


def parse_internal_link_proposals(text):
    """内部リンク案テキストを個別提案に分割する（2〜3件）
    Geminiの出力形式は「- **リンク先トピック案:**」または「-   **リンク先トピック案:**」など
    スペース数が可変なため、柔軟なパターンで分割する。
    """
    proposals = []

    # 方法1: **[内部リンク案]** マーカーで分割（最も確実）
    marker_blocks = re.split(r'\n\*\*\[内部リンク案\]\*\*\n?', text)
    for block in marker_blocks:
        block = block.strip()
        if 'リンク先トピック案' in block:
            proposals.append(block)

    if len(proposals) >= 2:
        return proposals

    # 方法2: スペース可変の「- **リンク先トピック案」行で分割
    proposals = []
    blocks = re.split(r'\n(?=-\s*\*\*リンク先トピック案[：:])', text)
    for block in blocks:
        block = block.strip()
        if 'リンク先トピック案' in block:
            proposals.append(block)

    return proposals

def extract_topic_title(proposal_text):
    """内部リンク案からトピックタイトルを抽出"""
    m = re.search(r'リンク先トピック案\d*[：:]\*?\*?\s*(.+)', proposal_text)
    if m:
        return m.group(1).strip().strip('*').strip()
    return "不明なトピック"

def extract_model_text_from_log(log_text):
    """親記事ログからModel出力部分だけを抽出する。User側に混じるプロンプト例を避けるため。"""
    blocks = []
    parts = re.split(r'\n---\s+', "\n" + (log_text or ""))
    for part in parts:
        if part.startswith("Model"):
            body = re.sub(r'^Model[^\n]*---\n?', '', part, count=1)
            body = re.split(r'\n---\s+', body, maxsplit=1)[0]
            blocks.append(body.strip())
    return "\n\n".join(blocks).strip()


def extract_latest_article_html_from_log(log_text):
    """親記事ログから、最後に出た記事HTMLらしいModel出力だけを取り出す。"""
    blocks = []
    parts = re.split(r'\n---\s+', "\n" + (log_text or ""))
    for part in parts:
        if part.startswith("Model"):
            body = re.sub(r'^Model[^\n]*---\n?', '', part, count=1).strip()
            body = re.split(r'\n---\s+', body, maxsplit=1)[0].strip()
            if "<h1" in body.lower() and "<h2" in body.lower():
                blocks.append(body)
    return blocks[-1].strip() if blocks else ""

def extract_child_topic_labels_from_links_text(links_text):
    """内部リンク案テキストから子記事作成用トピック名を重複なしで抽出する。"""
    topics = []
    seen = set()
    for m in re.finditer(r'リンク先トピック案\d*[：:]\*?\*?\s*(.+)', links_text or ""):
        topic = m.group(1).strip()
        topic = re.sub(r'^[「『"\']+|[」』"\']+$', '', topic).strip()
        topic = topic.strip('*').strip()
        if not topic or "〇〇" in topic or topic.startswith("（例") or topic.startswith("(例"):
            continue
        key = re.sub(r'\s+', '', topic)
        if key not in seen:
            seen.add(key)
            topics.append(topic)
    return topics

def _internal_links_text_from_parent_log(log_path):
    """親記事ログから内部リンク案を復元し、internal_linksファイル互換のテキストにする。"""
    raw = read_file(log_path)
    model_text = extract_model_text_from_log(raw)
    topics = extract_child_topic_labels_from_links_text(model_text)
    if not topics:
        # 後続ステップのUserプロンプトには「前ステップのModel出力」が再注入されるため、
        # 最終HTMLで内部リンク案が消えていてもログ全体から復元できる場合がある。
        topics = extract_child_topic_labels_from_links_text(raw)
    if not topics:
        return ""

    title = os.path.basename(log_path)
    m = re.match(r'log_PARENT_(.+?)_\d{8}_\d{4}\.txt$', title)
    keyword = m.group(1).strip() if m else title
    blocks = [f"【ターゲットキーワード】 {keyword}", "=" * 50, ""]
    for topic in topics:
        blocks.append("**[内部リンク案]**")
        blocks.append(f"*   **リンク先トピック案:** {topic}")
        blocks.append("*   **この記事内での役割:** 親記事ログから復元した内部リンク候補です。子記事作成後、内部リンク判断で親記事への挿入可否を判断してください。")
        blocks.append("*   **担当者へのアクション提案:** このトピックで子記事を作成し、親記事の関連箇所から内部リンクできるか確認してください。")
        blocks.append("")
        blocks.append("---")
        blocks.append("")
    return "\n".join(blocks).strip()

def _internal_links_candidate_keyword(candidate):
    """内部リンク候補から親記事キーワードを推定する。重複表示の整理に使う。"""
    if not candidate:
        return ""
    content = candidate.get("content") or ""
    if not content and candidate.get("path") and os.path.exists(candidate.get("path")):
        try:
            content = read_file(candidate.get("path"))
        except Exception:
            content = ""
    m = re.search(r'【ターゲットキーワード】\s*(.+)', content or "")
    if m:
        return m.group(1).strip()

    name = os.path.basename(candidate.get("source_log") or candidate.get("path") or "")
    m = re.match(r'log_PARENT_(.+?)_\d{8}_\d{4}\.txt$', name)
    if m:
        return m.group(1).strip()
    m = re.match(r'internal_links_[^_]+_[^_]+_(.+?)_\d{8}_\d{6}\.txt$', name)
    if m:
        return m.group(1).strip()
    m = re.match(r'internal_links_[^_]+_[^_]+_(.+?)_\d{8}_\d{4}\.txt$', name)
    if m:
        return m.group(1).strip()
    return ""


def _dedupe_internal_link_candidates_by_keyword(candidates):
    """同一親キーワードの候補を最新1件に絞る。必要なら全件表示に切り替えられる前提の整理。"""
    deduped = []
    seen = set()
    for cand in candidates:
        kw = _internal_links_candidate_keyword(cand)
        key = re.sub(r'\s+', '', kw).lower() if kw else os.path.abspath(cand.get("path", "")).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cand)
    return deduped


def format_internal_links_candidate_label(candidate, is_recommended=False):
    """内部リンクファイル選択肢を、人間が判断しやすい表示に整える。"""
    keyword = _internal_links_candidate_keyword(candidate) or "親キーワード不明"
    mtime = candidate.get("mtime") or 0
    dt = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M") if mtime else "日時不明"
    kind = "親ログから復元" if candidate.get("kind") == "parent_log" else "内部リンク案ファイル"

    content = candidate.get("content") or ""
    if not content and candidate.get("path") and os.path.exists(candidate.get("path")):
        content = read_file(candidate.get("path"))
    topics = extract_child_topic_labels_from_links_text(content)
    topic_count = len(topics)
    topic_preview = " / ".join(t[:24] for t in topics[:2])
    if topic_count > 2:
        topic_preview += " / ..."
    if not topic_preview:
        topic_preview = "子記事候補を自動抽出できませんでした（選択後に手動入力へ進む場合があります）"

    prefix = "【最新候補】" if is_recommended else "【候補】"
    filename = os.path.basename(candidate.get("source_log") or candidate.get("path") or "")
    return (
        f"{prefix} {dt} / 親記事: {keyword} / 子記事候補: {topic_count}件\n"
        f"    {topic_preview}\n"
        f"    種類: {kind} / 元ファイル: {filename}"
    )

def confirm_non_recommended_internal_link_choice(candidates, selected_idx):
    """最新候補以外を選んだとき、誤選択でないか確認する。"""
    if not candidates or selected_idx <= 0 or selected_idx >= len(candidates):
        return selected_idx
    chosen_kw = _internal_links_candidate_keyword(candidates[selected_idx]) or "親キーワード不明"
    recommended_kw = _internal_links_candidate_keyword(candidates[0]) or "親キーワード不明"
    choice = arrow_menu(
        "選択した子記事候補リストは、一番上の最新候補ではありません。\n"
        f"  選択中 : {chosen_kw}\n"
        f"  最新候補: {recommended_kw}\n"
        "  違う親記事の子記事を作る場合だけ、このまま進んでください。",
        [
            "一番上の最新候補に戻す",
            "この候補で続ける（違う親記事の子記事を作る）",
            "手動入力へ進む",
        ],
        allow_back=False,
    )
    if choice == 0:
        return 0
    if choice == 1:
        return selected_idx
    return -2


def _parent_log_matches_site(log_path, site_filter):
    """親記事ログが選択サイトのものかを判定する。子記事作成時の候補混入を防ぐ。"""
    if not site_filter:
        return True
    site = SITES_ALL.get(site_filter)
    if site_filter == "moechin":
        site = SITES_ALL.get("moechin") or site
    if not site:
        return True
    try:
        raw = read_file(log_path)
    except Exception:
        return False
    site_name = str(site.get("name", ""))
    site_url = str(site.get("url", "")).rstrip("/")
    domain = re.sub(r'^https?://', '', site_url).split('/')[0]
    # プロンプト本文には全サイト一覧が含まれるため、単純なサイト名/URL一致では誤判定する。
    # 実際の投稿ログ行だけを手がかりにする。
    if site_name and f"WordPressへ送信中... ({site_name})" in raw:
        return True
    if domain and re.search(rf"下書き投稿成功！.*URL:\s*https?://{re.escape(domain)}", raw):
        return True
    if domain and re.search(rf"URL:\s*https?://{re.escape(domain)}", raw):
        return True
    return False


def get_internal_links_source_candidates(site_filter=None, limit=40, dedupe_keyword=False, max_parent_logs_scan=20):
    """子記事作成用の内部リンク候補を取得する。
    wordpress_data内の専用ファイルを優先し、なければ親記事ログから復元する。
    """
    candidates = []
    seen = set()

    files = sorted(
        glob.glob(os.path.join(PARENT_WORDPRESS_DATA, "internal_links_*.txt")),
        key=os.path.getmtime, reverse=True
    )
    for path in files:
        name = os.path.basename(path)
        if site_filter and f"_{site_filter}_" not in name and not (site_filter == "moechin" and "_moechin_" in name):
            continue
        key = os.path.abspath(path).lower()
        seen.add(key)
        candidates.append({
            "label": f"【内部リンク】{name}",
            "path": path,
            "kind": "internal_links",
            "mtime": os.path.getmtime(path),
        })

    logs = sorted(
        glob.glob(os.path.join(PARENT_LOGS, "log_PARENT_*.txt")),
        key=os.path.getmtime, reverse=True
    )
    if max_parent_logs_scan is not None:
        logs = logs[:max(0, int(max_parent_logs_scan))]
    for path in logs:
        if site_filter and not _parent_log_matches_site(path, site_filter):
            continue
        if os.path.getsize(path) < 1000:
            continue
        restored = _internal_links_text_from_parent_log(path)
        if not restored:
            continue
        topics = extract_child_topic_labels_from_links_text(restored)
        if not topics:
            continue
        key = os.path.abspath(path).lower()
        if key in seen:
            continue
        safe_kw = _aio_safe_name(re.sub(r'^log_PARENT_|_\d{8}_\d{4}\.txt$', '', os.path.basename(path)), 28)
        cache_path = os.path.join(
            PARENT_WORDPRESS_DATA,
            f"internal_links_from_log_{PC_IDENTIFIER}_{safe_kw}_{datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y%m%d_%H%M%S')}.txt"
        )
        candidates.append({
            "label": f"【親ログ復元】{os.path.basename(path)}（{len(topics)}件）",
            "path": cache_path,
            "kind": "parent_log",
            "source_log": path,
            "content": restored,
            "mtime": os.path.getmtime(path),
        })

    candidates.sort(key=lambda x: x.get("mtime", 0), reverse=True)
    if dedupe_keyword:
        candidates = _dedupe_internal_link_candidates_by_keyword(candidates)
    return candidates[:limit]

def read_internal_links_candidate(candidate):
    """内部リンク候補を読み込む。親ログ復元候補はwordpress_dataへ保存してから返す。"""
    if candidate.get("kind") == "parent_log":
        os.makedirs(PARENT_WORDPRESS_DATA, exist_ok=True)
        path = candidate.get("path")
        content = candidate.get("content", "")
        if path and content and not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"   [OK] 親ログから内部リンクファイルを復元: {os.path.basename(path)}")
        return content
    return read_file(candidate.get("path", ""))

def find_internal_links_text_for_keyword(keyword, site_filter=None):
    """親記事キーワードに対応する内部リンク案を、専用ファイル/親ログ復元から探す。"""
    if not keyword:
        return "", ""
    key_norm = re.sub(r'\s+', '', keyword)
    base_norm = re.sub(r'\s+', '', keyword.replace("怪しい", "").replace("口コミ", "").strip())
    candidates = get_internal_links_source_candidates(site_filter=site_filter, limit=80)

    scored = []
    for cand in candidates:
        label = cand.get("label", "")
        content = cand.get("content") if cand.get("kind") == "parent_log" else read_file(cand.get("path", ""))
        hay = re.sub(r'\s+', '', f"{label}\n{content}")
        score = 0
        if key_norm and key_norm in hay:
            score += 100
        if base_norm and base_norm in hay:
            score += 30
        if "【ターゲットキーワード】" in content:
            score += 5
        if score:
            scored.append((score, cand, content))

    if not scored:
        return "", ""
    scored.sort(key=lambda x: (x[0], x[1].get("mtime", 0)), reverse=True)
    best = scored[0][1]
    text = read_internal_links_candidate(best)
    return text, best.get("label", os.path.basename(best.get("path", "")))

def _resume_has_complete_parent_article(resume_data):
    """内部リンク判断の親記事候補に出してよいresumeかを判定する。途中保存データを除外する。"""
    if not isinstance(resume_data, dict):
        return False
    html = resume_data.get("final_content", "") or ""
    if len(html) < 2000:
        return False
    if "<h1" not in html.lower() or "<h2" not in html.lower():
        return False
    if len(re.findall(r'<h2\b', html, flags=re.IGNORECASE)) < 2:
        return False
    if re.search(r'続きをそのまま出力|生成中断|CRITICAL ERROR|step\d+_', html, flags=re.IGNORECASE):
        return False
    return True

def get_complete_parent_resume_candidates(site_config, limit=5):
    """子記事完了後の内部リンク判断用に、完成済み親記事resumeだけを新しい順に返す。"""
    resume_prefix = "resume_moechin" if site_config.get("type") == "C" else "resume_normal"
    paths = sorted(
        [p for p in glob.glob(os.path.join(RESUME_DIR, f"{resume_prefix}_*.json"))],
        key=os.path.getmtime, reverse=True
    ) if os.path.isdir(RESUME_DIR) else []

    fallback = RESUME_MOECHIN if site_config.get("type") == "C" else RESUME_NORMAL
    if os.path.exists(fallback):
        paths.append(fallback)

    candidates = []
    seen = set()
    seen_keywords = set()
    for path in paths:
        ap = os.path.abspath(path).lower()
        if ap in seen:
            continue
        seen.add(ap)
        data = load_resume_data(path)
        if not _resume_has_complete_parent_article(data):
            continue
        kw_key = re.sub(r'\s+', '', str(data.get("target_input", "") or "")).lower()
        if kw_key and kw_key in seen_keywords:
            continue
        if kw_key:
            seen_keywords.add(kw_key)
        candidates.append({"path": path, "data": data, "mtime": os.path.getmtime(path)})
        if len(candidates) >= limit:
            break
    return candidates

def html_to_char_count(html):
    """HTMLタグを除いた文字数を返す"""
    text = re.sub(r'<[^>]+>', '', html or '')
    text = re.sub(r'\s+', '', text)
    return len(text)

def search_wordpress_posts(site_config, search_term, count=30, include_drafts=False):
    """WordPress REST APIでキーワード検索して記事一覧を取得（関連度順・文字数付き）。

    内部リンク先として使う通常検索では公開済み記事だけを対象にする。
    メタ情報の反映先確認など、下書きへ反映する用途だけ include_drafts=True を渡す。
    """
    import urllib.parse
    encoded = urllib.parse.quote(search_term)
    status = "publish,draft" if include_drafts else "publish"
    # orderby=relevance で検索語に近い記事を上位に、_fields で必要なフィールドのみ取得
    url = (site_config['url'].rstrip('/') +
           f"/wp-json/wp/v2/posts"
           f"?search={encoded}"
           f"&per_page={count}"
           f"&status={status}"
           f"&orderby=relevance"
           f"&_fields=id,title,date,link,content,status")
    credentials = f"{site_config['user']}:{site_config['pass'].replace(' ', '')}"
    token = base64.b64encode(credentials.encode()).decode('utf-8')
    headers = {'Authorization': f'Basic {token}'}
    try:
        res = requests.get(url, headers=headers, timeout=60)
        if res.status_code == 200:
            return res.json()
        return []
    except:
        return []


def fetch_wordpress_categories(site_config, limit=100):
    """WordPress上の現在のカテゴリ一覧を取得する。step9_meta.txt内の固定リストより優先して使う。"""
    if not site_config or not site_config.get("url"):
        return []
    url = site_config['url'].rstrip('/') + f"/wp-json/wp/v2/categories?per_page={limit}&orderby=count&order=desc&_fields=id,name,slug,count,parent"
    credentials = f"{site_config['user']}:{site_config['pass'].replace(' ', '')}"
    token = base64.b64encode(credentials.encode()).decode('utf-8')
    headers = {'Authorization': f'Basic {token}'}
    try:
        res = requests.get(url, headers=headers, timeout=30)
        if res.status_code == 200:
            cats = res.json()
            return [
                {
                    "id": c.get("id"),
                    "name": html.unescape(re.sub(r'<[^>]+>', '', c.get("name", "") or "")).strip(),
                    "slug": c.get("slug", ""),
                    "count": c.get("count", 0),
                    "parent": c.get("parent", 0),
                }
                for c in cats
                if (c.get("name") or "").strip()
            ]
        print(f"   ⚠️ WordPressカテゴリ取得に失敗しました HTTP {res.status_code}")
        return []
    except Exception as e:
        print(f"   ⚠️ WordPressカテゴリ取得に失敗しました: {str(e)[:120]}")
        return []


def load_reviewer_master_for_site(site_config):
    """外部JSONの監修者マスターから、対象サイトの監修者一覧を取得する。"""
    if not site_config:
        return []
    if not os.path.exists(REVIEWER_MASTER_FILE):
        return []
    try:
        with open(REVIEWER_MASTER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"   ⚠️ 監修者マスターの読み込みに失敗しました: {str(e)[:120]}")
        return []

    site_name = site_config.get("name", "")
    site_url = (site_config.get("url", "") or "").replace("https://", "").replace("http://", "").strip("/")
    entry = data.get(site_name)
    if not entry:
        for value in data.values():
            domain = str(value.get("domain", "") or "").strip()
            url = str(value.get("url", "") or "").replace("https://", "").replace("http://", "").strip("/")
            if domain and domain in site_url:
                entry = value
                break
            if url and url in site_url:
                entry = value
                break
    reviewers = (entry or {}).get("reviewers", [])
    return [r for r in reviewers if isinstance(r, dict) and (r.get("profile") or r.get("display_name"))]


def build_live_site_context_for_step9(site_config):
    """Step9へ渡す、WordPressから取得した最新のサイト情報。固定プロンプトの古い情報を補正する。"""
    cats = fetch_wordpress_categories(site_config)
    reviewers = load_reviewer_master_for_site(site_config)
    site_name = site_config.get("name", "") if site_config else ""
    author_display_mode = get_author_display_mode_for_site(site_name) if site_name else "author_reviewer"
    lines = []
    lines.append("=== WordPressから取得した現在のサイト情報（自動生成・固定テンプレートより優先） ===")
    if cats:
        lines.append("【現在のカテゴリ一覧】")
        for c in cats:
            count = c.get("count", 0)
            slug = c.get("slug", "")
            lines.append(f"- {c['name']}（slug: {slug}, 記事数: {count}）")
        lines.append("")
        lines.append("カテゴリ選定では、下記テンプレート内の古いカテゴリ一覧ではなく、この【現在のカテゴリ一覧】を最優先してください。")
        lines.append("記事テーマに合うカテゴリがこの一覧に存在する場合、無難な汎用カテゴリではなく、その具体カテゴリを選んでください。")
        lines.append("")
        lines.append("【カテゴリ判断の追加ルール】")
        lines.append("- 入稿時にすぐ選ぶ既存カテゴリと、長期運用上のカテゴリ新設候補を分けて判断してください。")
        lines.append("- 既存カテゴリに入稿できる場合でも、記事テーマが独立した情報群として今後3本以上に広がるなら、カテゴリ新設候補を出してください。")
        lines.append("- 新設候補は自動作成ではなく、人間が採用判断するための候補です。既存カテゴリへの入稿候補と併記してください。")
        lines.append("- 出力には必ず「最適な既存カテゴリ名」と「カテゴリ新設候補」を含めてください。新設不要なら「カテゴリ新設候補: なし」と書いてください。")
    else:
        lines.append("【現在のカテゴリ一覧】取得できませんでした。テンプレート内のカテゴリ一覧を参考にしてください。")
        lines.append("")
        lines.append("【カテゴリ判断の追加ルール】")
        lines.append("- 入稿時にすぐ選ぶ既存カテゴリと、長期運用上のカテゴリ新設候補を分けて判断してください。")
        lines.append("- 既存カテゴリに入稿できる場合でも、記事テーマが独立した情報群として今後3本以上に広がるなら、カテゴリ新設候補を出してください。")
        lines.append("- 新設候補は自動作成ではなく、人間が採用判断するための候補です。既存カテゴリへの入稿候補と併記してください。")
        lines.append("- 出力には必ず「最適な既存カテゴリ名」と「カテゴリ新設候補」を含めてください。新設不要なら「カテゴリ新設候補: なし」と書いてください。")
    lines.append("")
    lines.append("【現在の著者・監修者表示モード】")
    if author_display_mode == "author_only":
        lines.append("- 著者プロフィールのみ表示します。監修者プロフィール・監修者の新規作成提案は不要です。")
    elif author_display_mode == "single":
        lines.append("- author/reviewerを分けない単独プロフィール表示です。監修者プロフィール・監修者の新規作成提案は不要です。")
    else:
        lines.append("- 著者プロフィールと監修者プロフィールを表示します。既存監修者の流用を優先してください。")
    lines.append("")
    if reviewers:
        lines.append("【現在の監修者マスター】")
        for r in reviewers:
            profile = str(r.get("profile") or r.get("display_name") or "").strip()
            if profile:
                lines.append(f"- {profile}")
        lines.append("")
        lines.append("監修者選定では、下記テンプレート内の古い監修者一覧ではなく、この【現在の監修者マスター】を最優先してください。")
        lines.append("記事テーマに合う監修者がこの一覧に存在する場合、新規作成ではなく既存監修者の流用を優先してください。")
    else:
        lines.append("【現在の監修者マスター】取得できませんでした。テンプレート内の監修者一覧を参考にしてください。")
    return "\n".join(lines)


def select_wordpress_post_url_for_meta_apply(site_config, keyword):
    """メタ情報を自動反映する投稿URLが未取得のとき、WordPress検索結果から選んでもらう。"""
    if not site_config or not keyword:
        return ""
    print("   ℹ️ 自動反映先の確認: 対象投稿をまだ特定できないため、WordPressから候補を表示します。")
    posts = search_wordpress_posts(site_config, keyword, count=10, include_drafts=True)
    if not posts:
        print("   ⚠️ WordPress検索で候補記事が見つかりませんでした。")
        return ""
    options = []
    for post in posts:
        title = re.sub(r'<[^>]+>', '', post.get('title', {}).get('rendered', '') or '')
        title = html.unescape(title)
        status = post.get('status', '')
        status_label = "公開済み・注意" if status == "publish" else ("下書き" if status == "draft" else status)
        date = str(post.get('date', ''))[:16].replace('T', ' ')
        link = post.get('link', '')
        options.append(f"[{status_label}] {date} ID:{post.get('id')} {title[:46]}\n    {link}")
    options.append("選ばない（自動反映せず、入稿用サマリーだけ作る）")
    idx = arrow_menu(
        "メタ情報・入稿情報を反映するWordPress投稿を選択してください\n"
        "  ※ 投稿タイトル・日付・URLを確認してください。違う記事を選ぶとSEO情報が上書きされます。\n"
        "  ※ 不安な場合は一番下の「選ばない」を選ぶと、入稿用サマリーだけ作ります。",
        options,
        allow_back=False,
    )
    if 0 <= idx < len(posts):
        return posts[idx].get("link", "")
    return ""


def load_reviewer_master():
    """監修者マスターJSON全体を読み込む。"""
    if not os.path.exists(REVIEWER_MASTER_FILE):
        return {}
    try:
        with open(REVIEWER_MASTER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"   ⚠️ 監修者マスターの読み込みに失敗しました: {str(e)[:120]}")
        return {}


def backup_reviewer_master_file():
    """監修者マスター編集前にバックアップを作る。"""
    if not os.path.exists(REVIEWER_MASTER_FILE):
        return ""
    backup_dir = os.path.join(BASE_DIR, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"reviewer_master_before_edit_{ts}.json")
    try:
        with open(REVIEWER_MASTER_FILE, "r", encoding="utf-8") as src:
            content = src.read()
        with open(backup_path, "w", encoding="utf-8") as dst:
            dst.write(content)
        return backup_path
    except Exception as e:
        print(f"   ⚠️ 監修者マスターのバックアップに失敗しました: {str(e)[:120]}")
        return ""


def save_reviewer_master(data):
    """監修者マスターJSONを保存する。保存前にバックアップを作る。"""
    backup_path = backup_reviewer_master_file()
    try:
        with open(REVIEWER_MASTER_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        if backup_path:
            print(f"   ✅ バックアップ保存: {backup_path}")
        print(f"   ✅ 監修者マスター保存: {REVIEWER_MASTER_FILE}")
        return True
    except Exception as e:
        print(f"   ❌ 監修者マスターの保存に失敗しました: {e}")
        return False


def ensure_reviewer_master_site_entry(data, site_config):
    """対象サイトの監修者マスター枠を用意する。"""
    site_name = site_config.get("name", "")
    ppma = PPMA_LAYOUT_MAP.get(site_name, {})
    default_mode = "single" if ppma.get("single") else "author_reviewer"
    if site_name not in data or not isinstance(data.get(site_name), dict):
        data[site_name] = {
            "domain": (site_config.get("url", "") or "").replace("https://", "").replace("http://", "").strip("/"),
            "url": site_config.get("url", ""),
            "author_display_mode": default_mode,
            "reviewers": [],
        }
    entry = data[site_name]
    entry.setdefault("domain", (site_config.get("url", "") or "").replace("https://", "").replace("http://", "").strip("/"))
    entry.setdefault("url", site_config.get("url", ""))
    entry.setdefault("author_display_mode", default_mode)
    if not isinstance(entry.get("reviewers"), list):
        entry["reviewers"] = []
    return entry


def get_author_display_mode_for_site(site_name):
    """サイトごとの著者表示モードを取得する。
    author_reviewer: 著者＋監修者
    author_only    : 著者のみ
    single         : author/reviewer区別なしの単独プロフィール
    """
    ppma = PPMA_LAYOUT_MAP.get(site_name, {})
    default_mode = "single" if ppma.get("single") else "author_reviewer"
    data = load_reviewer_master()
    entry = data.get(site_name, {}) if isinstance(data, dict) else {}
    mode = str(entry.get("author_display_mode") or default_mode).strip()
    if mode not in {"author_reviewer", "author_only", "single"}:
        mode = default_mode
    if mode == "single" and not ppma.get("single"):
        # 単独プロフィール用レイアウトIDがないサイトでは著者のみへ安全に倒す。
        mode = "author_only"
    return mode


def build_publishpress_shortcodes(site_name):
    """サイト設定と表示モードに応じてPublishPressショートコードを作る。"""
    ppma = PPMA_LAYOUT_MAP.get(site_name)
    if not ppma:
        return "", ""
    mode = get_author_display_mode_for_site(site_name)
    if mode == "single" and ppma.get("single"):
        return f'[publishpress_authors_box layout="ppma_boxes_{ppma["single"]}"]\n', mode
    if mode == "author_only" or not ppma.get("reviewer"):
        return f'[publishpress_authors_box author_categories="author" layout="ppma_boxes_{ppma["author"]}"]\n', mode
    return (
        f'[publishpress_authors_box author_categories="author" layout="ppma_boxes_{ppma["author"]}"]\n'
        f'[publishpress_authors_box author_categories="reviewer" layout="ppma_boxes_{ppma["reviewer"]}" show_title="false"]\n',
        mode,
    )


def normalize_publishpress_shortcodes(html_content, site_name):
    """既存のPublishPressショートコードをサイトの表示モードに合わせて整える。"""
    if 'publishpress_authors_box' not in html_content:
        return html_content
    expected, mode = build_publishpress_shortcodes(site_name)
    if not expected:
        return html_content

    shortcode_pattern = re.compile(r'\[publishpress_authors_box[^\]]*\]\s*', re.IGNORECASE)
    matches = list(shortcode_pattern.finditer(html_content))
    if not matches:
        return html_content

    first_start = matches[0].start()
    last_end = matches[-1].end()
    html_content = html_content[:first_start] + expected + html_content[last_end:]
    print(f"   ✅ PublishPressショートコードを表示モードに合わせて整理（{site_name}: {mode}）")
    return html_content


def select_site_for_reviewer_master():
    """監修者マスター管理用のサイト選択。"""
    site_keys = list(SITES_ALL.keys())
    site_names = [SITES_ALL[k]["name"] for k in site_keys]
    idx = arrow_menu("監修者マスターを管理するサイトを選択してください", site_names, allow_back=True)
    if menu_back(idx):
        return None
    return SITES_ALL[site_keys[idx]]


def print_reviewers_for_site(site_name, reviewers):
    print("\n" + "=" * 60)
    print(f"  監修者マスター一覧: {site_name}")
    print("=" * 60)
    if not reviewers:
        print("  （登録なし）")
        return
    for i, reviewer in enumerate(reviewers, 1):
        display_name = str(reviewer.get("display_name") or "").strip()
        profile = str(reviewer.get("profile") or "").strip()
        print(f"\n  {i}. {display_name or '（表示名なし）'}")
        if profile:
            preview = profile[:180] + ("..." if len(profile) > 180 else "")
            print(f"     {preview}")


def add_reviewer_to_master(data, site_config):
    entry = ensure_reviewer_master_site_entry(data, site_config)
    site_name = site_config.get("name", "")
    reviewers = entry["reviewers"]

    print("\n新しい監修者を追加します。")
    print("※ WordPress / PublishPress Authors側にも同じ人物を登録してください。")
    display_name = input("表示名（例: 山田 太郎（住宅設備アドバイザー））: ").strip()
    if not display_name:
        print("   → 表示名が空のためキャンセルしました。")
        return False

    for reviewer in reviewers:
        existing = str(reviewer.get("display_name") or "").strip()
        if existing == display_name:
            print("   ⚠️ 同じ表示名の監修者がすでに登録されています。")
            overwrite = input("   この監修者のプロフィールを更新しますか？ (y/N): ").strip().lower()
            if overwrite != "y":
                print("   → キャンセルしました。")
                return False
            print("プロフィール全文を貼り付けてください。Enter3回で確定します。")
            profile = get_multiline_input("")
            reviewer["profile"] = profile.strip() or display_name
            print(f"   ✅ 更新対象: {site_name} / {display_name}")
            return True

    print("プロフィール全文を貼り付けてください。Enter3回で確定します。")
    print("例: 山田 太郎（住宅設備アドバイザー）：住宅設備会社で15年...")
    profile = get_multiline_input("")
    reviewers.append({
        "display_name": display_name,
        "profile": profile.strip() or display_name,
    })
    print(f"   ✅ 追加対象: {site_name} / {display_name}")
    return True


def edit_reviewer_in_master(data, site_config):
    entry = ensure_reviewer_master_site_entry(data, site_config)
    reviewers = entry["reviewers"]
    site_name = site_config.get("name", "")
    if not reviewers:
        print("   → このサイトには監修者が登録されていません。")
        input("Enterで戻ります...")
        return False

    options = [str(r.get("display_name") or r.get("profile") or "（表示名なし）")[:90] for r in reviewers]
    idx = arrow_menu("編集する監修者を選択してください", options, allow_back=True)
    if menu_back(idx):
        return False

    reviewer = reviewers[idx]
    current_name = str(reviewer.get("display_name") or "").strip()
    current_profile = str(reviewer.get("profile") or "").strip()
    print("\n現在の表示名:")
    print(current_name)
    new_name = input("新しい表示名（変更しない場合はEnter）: ").strip()
    if new_name:
        reviewer["display_name"] = new_name

    print("\n現在のプロフィール:")
    print(current_profile or "（空）")
    print("\n新しいプロフィール全文を貼り付けてください。変更しない場合はEnter3回だけ押してください。")
    new_profile = get_multiline_input("")
    if new_profile.strip():
        reviewer["profile"] = new_profile.strip()

    print(f"   ✅ 更新対象: {site_name} / {reviewer.get('display_name')}")
    return True


def change_author_display_mode(data, site_config):
    """サイトごとの著者・監修者ショートコード表示モードを変更する。"""
    entry = ensure_reviewer_master_site_entry(data, site_config)
    site_name = site_config.get("name", "")
    current = str(entry.get("author_display_mode") or get_author_display_mode_for_site(site_name)).strip()
    mode_labels = {
        "author_reviewer": "著者＋監修者（通常）",
        "author_only": "著者のみ（監修者なし）",
        "single": "単独プロフィール（author/reviewerを分けない）",
    }
    options = [
        "著者＋監修者（通常）",
        "著者のみ（監修者なし）",
    ]
    modes = ["author_reviewer", "author_only"]
    ppma = PPMA_LAYOUT_MAP.get(site_name, {})
    if ppma.get("single"):
        options.append("単独プロフィール（author/reviewerを分けない）")
        modes.append("single")

    print("\n現在の表示モード:")
    print(f"  {mode_labels.get(current, current)}")
    idx = arrow_menu(
        f"著者・監修者の表示モードを選択してください: {site_name}\n"
        "  ※ 投稿前クリーンアップでAI生成プロフィールを削除し、ここで選んだPublishPressショートコードに置換します。",
        options,
        allow_back=True,
    )
    if menu_back(idx):
        return False
    entry["author_display_mode"] = modes[idx]
    print(f"   ✅ 表示モードを変更: {mode_labels[modes[idx]]}")
    return True


def run_reviewer_master_manager():
    """Step9で使う監修者候補をJSONで管理する。"""
    while True:
        site_config = select_site_for_reviewer_master()
        if not site_config:
            return

        data = load_reviewer_master()
        entry = ensure_reviewer_master_site_entry(data, site_config)
        site_name = site_config.get("name", "")
        reviewers = entry.get("reviewers", [])
        current_mode = get_author_display_mode_for_site(site_name)
        mode_label = {
            "author_reviewer": "著者＋監修者",
            "author_only": "著者のみ",
            "single": "単独プロフィール",
        }.get(current_mode, current_mode)

        action = arrow_menu(
            f"監修者マスター管理: {site_name}\n"
            "  ※ ここは「ツールがStep9で候補として認識する監修者」の管理です。\n"
            "  ※ WordPress上に表示するには、PublishPress Authors側の登録も別途必要です。\n"
            f"  ※ 現在の著者表示モード: {mode_label}",
            [
                "監修者一覧を見る",
                "新しい監修者を追加する",
                "既存監修者のプロフィールを編集する",
                "著者・監修者の表示モードを変更する",
                "サイト選択へ戻る",
            ],
            allow_back=True,
        )
        if menu_back(action) or action == 4:
            continue
        if action == 0:
            print_reviewers_for_site(site_name, reviewers)
            input("\nEnterで戻ります...")
        elif action == 1:
            if add_reviewer_to_master(data, site_config):
                save_reviewer_master(data)
            input("\nEnterで戻ります...")
        elif action == 2:
            if edit_reviewer_in_master(data, site_config):
                save_reviewer_master(data)
            input("\nEnterで戻ります...")
        elif action == 3:
            if change_author_display_mode(data, site_config):
                save_reviewer_master(data)
            input("\nEnterで戻ります...")


# ============================================================
# AIO補強（Google AI Overview取得 → 充足チェック → 追記/一石候補）
# ============================================================
def _aio_safe_name(text, max_len=40):
    safe = re.sub(r'[\\/:*?"<>|\r\n]+', '_', text or "keyword").strip()
    safe = re.sub(r'\s+', '_', safe)
    return safe[:max_len] if safe else "keyword"


def _get_secret_from_env(name):
    """環境変数を取得。Windowsのsetx反映待ち対策としてHKCU\\Environmentも読む。"""
    value = os.environ.get(name, "").strip()
    if value:
        return value
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                value, _ = winreg.QueryValueEx(key, name)
                return str(value).strip()
        except Exception:
            return ""
    return ""


def _aio_work_path(keyword, suffix, ext="txt"):
    os.makedirs(AIO_WORK_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    return os.path.join(AIO_WORK_DIR, f"aio_{PC_IDENTIFIER}_{_aio_safe_name(keyword)}_{suffix}_{ts}.{ext}")


def _save_aio_work_file(keyword, suffix, content, ext="txt"):
    path = _aio_work_path(keyword, suffix, ext)
    mode = "w"
    if ext.lower() == "json":
        with open(path, mode, encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2)
    else:
        with open(path, mode, encoding="utf-8") as f:
            f.write(content or "")
    return path


def _serp_work_path(keyword, suffix, ext="json"):
    os.makedirs(SERP_WORK_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(SERP_WORK_DIR, f"serp_{PC_IDENTIFIER}_{_aio_safe_name(keyword)}_{suffix}_{ts}.{ext}")


def _save_serp_work_file(keyword, suffix, content, ext="json"):
    path = _serp_work_path(keyword, suffix, ext)
    if ext.lower() == "json":
        with open(path, "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2)
    else:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content or "")
    return path


def _flatten_searchapi_aio_text(ai_overview):
    if not isinstance(ai_overview, dict):
        return ""
    markdown = (ai_overview.get("markdown") or "").strip()
    if markdown:
        return markdown

    def block_to_text(block):
        if not isinstance(block, dict):
            return ""
        if block.get("answer"):
            return str(block.get("answer")).strip()
        items = block.get("items")
        if isinstance(items, list):
            item_lines = []
            for item in items:
                t = block_to_text(item)
                if t:
                    item_lines.append(f"- {t}")
            return "\n".join(item_lines)
        return ""

    lines = []
    for block in ai_overview.get("text_blocks") or []:
        t = block_to_text(block)
        if t:
            lines.append(t)
    return "\n\n".join(lines).strip()


def _aio_reference_summary(ai_overview):
    refs = []
    if isinstance(ai_overview, dict):
        for ref in ai_overview.get("reference_links") or []:
            title = ref.get("title") or ref.get("source") or "参照元"
            link = ref.get("link") or ""
            source = ref.get("source") or ""
            refs.append(f"- {title} / {source}\n  {link}".strip())
    return "\n".join(refs[:12])


def fetch_aio_from_searchapi(keyword):
    """SearchAPI.ioで本物のGoogle AI Overviewを取得する。
    戻り値 status:
      success          AIO本文取得成功
      aio_fetch_failed AIOの存在は見えたが本文取得失敗
      aio_none         検索結果にAIOなし
      api_missing      APIキー未設定
      api_error        API自体の失敗
    """
    api_key = _get_secret_from_env("SEARCHAPI_API_KEY")
    if not api_key:
        return {"status": "api_missing", "message": "SEARCHAPI_API_KEY が未設定です。"}

    url = "https://www.searchapi.io/api/v1/search"
    headers = {"Authorization": f"Bearer {api_key}", "User-Agent": "auto_post_unified/1.0"}
    params = {
        "engine": "google",
        "q": keyword,
        "google_domain": "google.co.jp",
        "gl": "jp",
        "hl": "ja",
        "num": 10,
    }
    try:
        res = requests.get(url, headers=headers, params=params, timeout=45)
        if res.status_code in (401, 403):
            return {"status": "api_error", "message": "SearchAPI.ioの認証に失敗しました。APIキーを確認してください。"}
        if res.status_code == 429:
            return {"status": "api_error", "message": "SearchAPI.ioの利用上限またはレート制限に達しました。"}
        if res.status_code >= 400:
            return {"status": "api_error", "message": f"SearchAPI.io HTTP {res.status_code}: {res.text[:300]}"}
        data = res.json()
        raw_path = _save_aio_work_file(keyword, "searchapi_google_raw", data, "json")

        ai_overview = data.get("ai_overview")
        organic_results = data.get("organic_results") or []
        if not ai_overview:
            return {
                "status": "aio_none",
                "message": "検索結果にAI Overviewが見つかりませんでした。",
                "organic_results": organic_results,
                "raw_path": raw_path,
            }

        aio_text = _flatten_searchapi_aio_text(ai_overview)
        if aio_text:
            return {
                "status": "success",
                "message": "AI Overview本文を取得しました。",
                "aio_text": aio_text,
                "references": _aio_reference_summary(ai_overview),
                "organic_results": organic_results,
                "raw_path": raw_path,
            }

        page_token = ai_overview.get("page_token") or ai_overview.get("token")
        if page_token:
            detail_params = {"engine": "google_ai_overview", "page_token": page_token}
            detail_res = requests.get(url, headers=headers, params=detail_params, timeout=45)
            if detail_res.status_code == 200:
                detail_data = detail_res.json()
                detail_path = _save_aio_work_file(keyword, "searchapi_aio_raw", detail_data, "json")
                detail_aio = detail_data.get("ai_overview") or detail_data
                aio_text = _flatten_searchapi_aio_text(detail_aio)
                if aio_text:
                    return {
                        "status": "success",
                        "message": "AI Overview本文を詳細APIから取得しました。",
                        "aio_text": aio_text,
                        "references": _aio_reference_summary(detail_aio),
                        "organic_results": organic_results,
                        "raw_path": raw_path,
                        "detail_path": detail_path,
                    }
            return {
                "status": "aio_fetch_failed",
                "message": "AI Overviewの存在は確認できましたが、本文取得に失敗しました。手動貼り付けが必要です。",
                "organic_results": organic_results,
                "raw_path": raw_path,
            }

        return {
            "status": "aio_fetch_failed",
            "message": "AI Overviewの存在は確認できましたが、本文またはpage_tokenが取得できませんでした。",
            "organic_results": organic_results,
            "raw_path": raw_path,
        }
    except Exception as e:
        return {"status": "api_error", "message": f"SearchAPI.io取得エラー: {e}"}


def _organic_results_summary(results, limit=5):
    lines = []
    for i, item in enumerate((results or [])[:limit], 1):
        title = item.get("title") or ""
        link = item.get("link") or ""
        snippet = item.get("snippet") or item.get("description") or ""
        lines.append(f"{i}. {title}\nURL: {link}\n要約: {snippet}".strip())
    return "\n\n".join(lines)


def _is_quota_error_message(message):
    msg = (message or "").lower()
    return any(x in msg for x in ["429", "quota", "rate limit", "resource_exhausted", "exceeded"])


def _is_transient_gemini_error(message):
    msg = (message or "").lower()
    return any(x in msg for x in [
        "503", "unavailable", "high demand", "temporarily", "timeout", "deadline",
        "internal error", "500", "502", "504"
    ])


def _send_message_with_retry(chat, prompt, label="Gemini生成", max_retries=3):
    """Geminiの一時的な高負荷エラーだけを段階的に待って再試行する。"""
    waits = [20, 60, 120]
    attempt = 0
    while True:
        try:
            return chat.send_message(prompt)
        except Exception as e:
            err = str(e)
            if not _is_transient_gemini_error(err) or attempt >= max_retries:
                raise
            wait = waits[min(attempt, len(waits) - 1)]
            attempt += 1
            print(f"   ⚠️ {label}が一時的に混雑しています（{attempt}/{max_retries}）。{wait}秒後に再試行します...")
            print(f"      理由: {err[:180]}")
            time.sleep(wait)


def _send_gemini_with_manual_resume(api_key, api_keys_list, prompt, keyword, state):
    current_key = api_key
    while True:
        try:
            _load_genai()
            client = genai.Client(api_key=current_key)
            chat = client.chats.create(model=MODEL_PARENT, config=GEN_CONFIG)
            response = _send_message_with_retry(chat, prompt, "AIO補強")

            if response.candidates and response.candidates[0].finish_reason not in [
                types.FinishReason.STOP, types.FinishReason.MAX_TOKENS
            ]:
                raise RuntimeError(f"生成中断: {response.candidates[0].finish_reason}")

            text = response.text or ""
            cnt = 0
            while response.candidates and response.candidates[0].finish_reason == types.FinishReason.MAX_TOKENS and cnt < 5:
                print("   ⚠️ AIO補強が長文のため続きを取得します...")
                time.sleep(5)
                response = _send_message_with_retry(chat, "続きをそのまま出力してください", "AIO補強の続き")
                if response.text:
                    text += response.text
                cnt += 1
            return text, current_key
        except Exception as e:
            err = str(e)
            if not _is_quota_error_message(err):
                raise

            state = dict(state or {})
            state.update({
                "keyword": keyword,
                "prompt": prompt,
                "error": err,
                "timestamp": datetime.datetime.now().isoformat(),
            })
            resume_path = _save_aio_work_file(keyword, "gemini_quota_resume", state, "json")
            print("\n   ❌ Gemini APIの上限またはレート制限に達しました。")
            print(f"   💾 AIO補強の再開用データを保存しました: {resume_path}")
            idx = arrow_menu(
                "Gemini APIキーの扱いを選択してください",
                ["別のGemini APIキーを手動選択してAIO補強を再開", "AIO補強を中止して投稿前へ戻る"],
                allow_back=False
            )
            if idx == 0:
                new_key = select_api_key(api_keys_list)
                if not new_key:
                    return "", current_key
                current_key = new_key
                print("   🔁 選択したキーでAIO補強を再開します（自動ローテーションは行いません）。")
                continue
            return "", current_key


def _extract_enhanced_html(ai_output):
    if not ai_output:
        return ""
    marker = "=== 最終版HTML ==="
    if marker in ai_output:
        return ai_output.split(marker, 1)[1].strip()
    m = re.search(r'(<h1[\s\S]+)$', ai_output.strip(), flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return ""

def _extract_aio_report_only(ai_output):
    marker = "=== 最終版HTML ==="
    report = (ai_output or "").split(marker, 1)[0].strip()
    return report if report else "AIO補強レポートを抽出できませんでした。"

def _html_paragraph_texts(html):
    blocks = re.findall(r'<(?:h[1-6]|p|li|td|blockquote)[^>]*>(.*?)</(?:h[1-6]|p|li|td|blockquote)>', html or "", flags=re.IGNORECASE | re.DOTALL)
    texts = []
    for block in blocks:
        text = re.sub(r'<[^>]+>', '', block)
        text = re.sub(r'\s+', ' ', text).strip()
        if len(text) >= 18:
            texts.append(text)
    return texts

def _summarize_aio_html_changes(before_html, after_html, max_items=12):
    before_set = set(_html_paragraph_texts(before_html))
    after_texts = _html_paragraph_texts(after_html)
    added = [t for t in after_texts if t not in before_set]

    lines = [
        "=== AIO補強で追加・変更された可能性が高い本文 ===",
        "※ HTML全文ではなく、補強後の記事に新しく入った可能性が高い見出し・段落だけを抜粋しています。",
        "※ 表のセルや言い換えも含まれるため、最終確認はWordPress下書きで行ってください。",
        "",
    ]
    if not added:
        lines.append("大きな追加段落は検出できませんでした。主に既存文の軽微な言い換え・整理の可能性があります。")
    else:
        for i, text in enumerate(added[:max_items], 1):
            if len(text) > 320:
                text = text[:320] + "..."
            lines.append(f"{i}. {text}")
        if len(added) > max_items:
            lines.append(f"\n...ほか {len(added) - max_items} 件")
    return "\n".join(lines)

def _freshness_guard_prompt():
    today = datetime.datetime.now().strftime("%Y年%m月%d日")
    return f"""

# 【システム追加指示】日付・最新データの扱い（最優先・本文出力禁止）
- 内部参照日: {today}
- この内部参照日は判断材料です。記事本文に「現在日は...です」「内部参照日」などの文言を絶対に出力しない。
- 「最新」「最新版」「2026最新」「2025最新」「2024最新」のような年付き最新表現は、根拠データがその年に更新済みだと確認できる場合だけ使う。
- 根拠が2024年データなら「2024年時点」「公表時点」「確認できる最新公表値」と書き、「2024最新」とは書かない。
- 現在年より古い年を見出しに付けて「最新」と表現することは禁止。
- 会員数・成婚数・料金・キャンペーン・法制度など変わりやすい数値は、根拠年または確認時点を本文中に明記する。
- 最新値を確認できない場合は、無理に数値を更新せず「各公式サイトで最新情報を確認してください」と添える。
""".strip()


def _build_aio_enhancement_prompt(keyword, final_content, aio_mode, aio_text, references, organic_summary, initial_instruction):
    context = (initial_instruction or "")
    if len(context) > 12000:
        context = context[:12000] + "\n\n（前提情報は長いためここで切り詰め）"
    html = final_content or ""
    return f"""
あなたは日本語SEO記事の編集者です。既存記事を、実際のGoogle AI Overview（AI要約）または検索結果に基づいて監査し、必要な場合だけ補強してください。

# 絶対ルール
- 回答・本文・コメントはすべて日本語。
- 捏造禁止。AIO本文、参照元、検索結果、前提情報、既存本文にない具体的な口コミ・数字・会社情報を断定しない。
- AIOがある場合は、AIO本文を「本物の検索結果に表示されたAI要約」として扱い、そこに含まれる論点を最小単位に分解する。
- 「特徴と評判」のような複合語は必ず「特徴」「評判」のように分けて、それぞれ既存記事の充足を判定する。
- 既存記事で十分に回答済みの論点は、無理に追記しない。
- ただし、追記の有無に関係なく「著者の一言アドバイス」で人間が書くべき観点は必ず提案する。
- 既存記事と追記のファクト矛盾を必ずチェックする。矛盾があれば本文側を修正するか、断定を避ける。
- インフォグラフィック指示が残る場合は、画像指示のまま残さず、HTMLの表または短い図解ボックスに変換する。
- WordPressに貼れるHTMLだけを最終HTMLに含める。Markdownコードフェンスは禁止。
- <h1>から最後まで、記事全文を省略せず出力する。
{_freshness_guard_prompt()}

# AIO取得モード
{aio_mode}

# ターゲットキーワード
{keyword}

# AIO本文または手動貼り付け本文
{aio_text or "（AIO本文なし。AIOなしの場合のみ検索結果から補強論点を推定する）"}

# AIO参照元
{references or "（参照元なし）"}

# 検索上位サマリー
{organic_summary or "（検索上位サマリーなし）"}

# 元の前提情報（競合URL・リサーチ内容など）
{context}

# 既存記事HTML（監査・修正対象）
{html}

# 出力形式
最初に短いレポートを書き、その後に区切り行を置いて、最終版HTML全文を書いてください。

=== AIO補強レポート ===
1. AIO論点の分解
2. 既存記事で足りていた論点
3. 追記または修正した論点
4. ファクト矛盾チェック
5. 著者の一言アドバイス候補（人間が手書きすべき具体的な観点を3つ）

=== 最終版HTML ===
<h1>...
""".strip()


def run_aio_enhancement_flow(api_key, api_keys_list, keyword, final_content, selected_site, initial_instruction):
    """投稿前に任意でAIO補強を実行し、投稿可否と本文を返す。"""
    idx = arrow_menu(
        "AIO補強を実行しますか？\n  SearchAPI.ioで本物のAI Overview取得を試し、取得できない場合は条件に応じて手動/推定へ分岐します。",
        ["AIO補強を実行する", "AIO補強なしで投稿へ進む"],
        allow_back=False
    )
    if idx == 1:
        return final_content, True, []

    print("\n🔎 SearchAPI.ioでGoogle検索結果とAI Overviewを確認中...")
    aio_result = fetch_aio_from_searchapi(keyword)
    status = aio_result.get("status")
    print(f"   状態: {status} / {aio_result.get('message', '')}")

    aio_text = ""
    aio_mode = ""
    references = aio_result.get("references", "")
    organic_summary = _organic_results_summary(aio_result.get("organic_results"), limit=5)

    if status == "success":
        aio_text = aio_result.get("aio_text", "")
        aio_mode = "AIO取得成功：以下のAIO本文を本物のAI Overviewとして分解する。"
        _save_aio_work_file(keyword, "aio_text", aio_text)
    elif status == "aio_fetch_failed":
        print("\n   ⚠️ AIOの存在は確認できましたが本文取得に失敗しました。推定補強には進みません。")
        manual = get_multiline_input(
            "\n【AI Overview本文を手動貼り付け】\nGoogle検索画面のAI要約を貼り付けてください（Enter5回で確定）。空ならAIO補強を中止します:",
            eof_mode=True
        )
        if not manual.strip():
            print("   ℹ️ AIO補強を中止します。")
            return final_content, True, []
        aio_text = manual.strip()
        aio_mode = "AIOあり・本文取得失敗：ユーザーが手動貼り付けした本物のAIO本文を分解する。"
        _save_aio_work_file(keyword, "aio_manual", aio_text)
    elif status == "aio_none":
        none_idx = arrow_menu(
            "SearchAPI.io上ではAIOなしでした。実際の検索画面でAI要約が見えている場合は手動貼り付けに切り替えられます。",
            ["AIOなしとして推定補強に進む", "実際の検索画面にはAIOがあるので手動貼り付けする", "AIO補強を中止する"],
            allow_back=False
        )
        if none_idx == 0:
            aio_mode = "AIOなし：検索結果にAI Overviewがないため、検索上位サマリーと前提情報から補強論点を推定する。"
        elif none_idx == 1:
            aio_text = get_multiline_input("\n【AI Overview本文を手動貼り付け】Enter5回で確定:", eof_mode=True).strip()
            if not aio_text:
                print("   ℹ️ AIO本文が空のため中止します。")
                return final_content, True, []
            aio_mode = "SearchAPI上はAIOなしだが、ユーザーが実際の検索画面から手動貼り付けした本物のAIO本文を分解する。"
            _save_aio_work_file(keyword, "aio_manual", aio_text)
        else:
            return final_content, True, []
    elif status in ("api_missing", "api_error"):
        print("\n   ⚠️ 自動取得できないため手動モードへ切り替えます。")
        print("   ※ これは「AIOが存在しない」という意味ではありません。")
        print("   ※ APIキー未設定・APIエラー等で、Google検索結果上のAIO有無を自動確認できなかった状態です。")
        manual_idx = arrow_menu(
            "AIO本文の扱いを選択してください\n"
            "  1: 実際のGoogle検索画面にAI要約が出ている場合\n"
            "  2: 実際に検索してAI要約が出ていないと確認できた場合だけ選択\n"
            "     （本物のAIO分解ではなく、検索上位/既存リサーチから不足論点を推定します）",
            ["AIO本文を手動で貼り付ける", "AIOなし確認済みとして推定補強する", "AIO補強を中止する"],
            allow_back=False
        )
        if manual_idx == 0:
            aio_text = get_multiline_input("\n【AI Overview本文を手動貼り付け】Enter5回で確定:", eof_mode=True).strip()
            if not aio_text:
                print("   ℹ️ AIO本文が空のため中止します。")
                return final_content, True, []
            aio_mode = "AIO取得API未設定/失敗：ユーザーが手動貼り付けした本物のAIO本文を分解する。"
            _save_aio_work_file(keyword, "aio_manual", aio_text)
        elif manual_idx == 1:
            aio_mode = "AIO取得API未設定/失敗：ユーザー判断によりAIOなしとして、検索結果と前提情報から補強論点を推定する。"
        else:
            return final_content, True, []
    else:
        print("   ⚠️ 想定外の状態のためAIO補強を中止します。")
        return final_content, True, []

    prompt = _build_aio_enhancement_prompt(
        keyword=keyword,
        final_content=final_content,
        aio_mode=aio_mode,
        aio_text=aio_text,
        references=references,
        organic_summary=organic_summary,
        initial_instruction=initial_instruction,
    )
    state = {
        "aio_status": status,
        "aio_mode": aio_mode,
        "raw_path": aio_result.get("raw_path", ""),
        "site": selected_site.get("name", "") if selected_site else "",
    }
    print("\n🧠 GeminiでAIO論点分解・充足チェック・補強HTML生成中...")
    ai_output, used_key = _send_gemini_with_manual_resume(api_key, api_keys_list, prompt, keyword, state)
    if not ai_output.strip():
        print("   ℹ️ AIO補強は未適用です。")
        return final_content, True, []

    report_path = _save_aio_work_file(keyword, "report_and_html", ai_output)
    report_only = _extract_aio_report_only(ai_output)
    enhanced_html = _extract_enhanced_html(ai_output)
    if not enhanced_html or len(enhanced_html) < 500:
        print("   ⚠️ 最終版HTMLの抽出に失敗しました。AIO補強は未適用です。")
        print(f"   レポート保存先: {report_path}")
        open_file_for_user(report_path)
        return final_content, True, [{"role": "Model (AIO補強失敗)", "text": ai_output}]

    enhanced_html = force_cleanup_html_parent(enhanced_html)
    if selected_site:
        enhanced_html = replace_author_block_with_shortcodes(enhanced_html, selected_site.get("name", ""))
    enhanced_path = _save_aio_work_file(keyword, "enhanced_html", enhanced_html)
    review_text = (
        report_only
        + "\n\n"
        + _summarize_aio_html_changes(final_content, enhanced_html)
        + "\n\n=== 保存ファイル ===\n"
        + f"補強済みHTML: {enhanced_path}\n"
        + f"全文レポート: {report_path}\n"
    )
    review_path = _save_aio_work_file(keyword, "review", review_text)
    print(f"   ✅ AIO補強結果を保存しました: {enhanced_path}")
    print(f"   ✅ AIO補強レビューを保存しました: {review_path}")
    print("\n   【このあと開くメモ帳について】")
    print("   - 開くのはHTML全文ではなく、AIO補強レポートと追加・変更点の抜粋です。")
    print("   - 補強済みHTMLを細かく直したい場合は、表示されているHTMLファイルを直接開いて編集してください。")
    print("   - Enterを押すと次に「補強済みで投稿」「元HTMLで投稿」「投稿しない」を選べます。")
    open_file_for_user(review_path)
    refreshed_html = read_file(enhanced_path)
    if refreshed_html.strip():
        enhanced_html = force_cleanup_html_parent(refreshed_html)
        if selected_site:
            enhanced_html = replace_author_block_with_shortcodes(enhanced_html, selected_site.get("name", ""))

    post_idx = arrow_menu(
        "AIO補強結果の扱いを選択してください\n"
        "  1は補強済みHTMLを使います。2は補強前の記事に戻します。3は投稿せず確認で止めます。",
        ["補強済みHTMLでWordPress下書き投稿へ進む", "元のHTMLでWordPress下書き投稿へ進む", "投稿せず、補強HTMLを確認してメニューへ戻る"],
        allow_back=False
    )
    log_extra = [
        {"role": "User (AIO補強)", "text": prompt},
        {"role": "Model (AIO補強)", "text": ai_output},
    ]
    if post_idx == 0:
        return enhanced_html, True, log_extra
    if post_idx == 1:
        return final_content, True, log_extra
    return enhanced_html, False, log_extra

def _remove_author_reviewer_div_blocks(html_content):
    """本文中に残存するdivベースの著者・監修者プロフィールブロックを除去する。
    著者プロフィール、著者情報、監修者情報、監修者プロフィール等のキーワードを含む
    <div>...</div> ブロックを検出して削除する。
    """
    # 著者・監修者ブロックを示すキーワード群。絵文字や装飾の有無に左右されないよう広めに見る。
    author_keywords = (
        r'著者プロフィール|著者情報|監修者情報|監修者プロフィール|'
        r'執筆者プロフィール|執筆者情報|この記事を書いた人|この記事の著者|この記事の監修者|'
        r'執筆者\s*[:：]|著者\s*[:：]|監修者\s*[:：]|監修\s*[:：]|'
        r'Author Profile|Reviewer Profile'
    )
    class_keywords = (
        r'author-profile|reviewer-profile|author_profile|reviewer_profile|'
        r'authorProfile|reviewerProfile|author-box|reviewer-box|writer-box|supervisor-box|'
        r'authorBox|reviewerBox|writerBox|supervisorBox'
    )
    # AI生成のプロフィールdivは基本的に入れ子を持たないため、div単位で安全に除去する。
    div_pattern = re.compile(r'<div\b[^>]*>[\s\S]*?</div>', re.IGNORECASE)
    removed_count = 0
    def _check_and_remove(match):
        nonlocal removed_count
        block = match.group(0)
        if re.search(class_keywords, block, re.IGNORECASE) or re.search(author_keywords, block, re.IGNORECASE):
            removed_count += 1
            return ''
        return block
    html_content = div_pattern.sub(_check_and_remove, html_content)
    if removed_count:
        print(f"   🗑️ div型の著者・監修者ブロックを {removed_count} 件削除")
    return html_content


def replace_author_block_with_shortcodes(html_content, site_name):
    """AI生成の著者・監修者テキストブロックをPublishPressショートコードに自動置換する。
    - 最初の<h2>直前にある <hr>著者テキスト<hr>監修者テキスト<hr> ブロックを検出して置換
    - <div style="...">型の著者・監修者ブロックも検出して削除
    - 既にpublishpress_authors_boxが存在する場合は何もしない（二重挿入防止）
    - ブロック検出失敗時は最初の<h2>直前にショートコードを挿入（フォールバック）
    """
    if not html_content or not site_name:
        return html_content

    # Step 1: div型の著者・監修者ブロックを先に除去（本文中どこにあっても削除）。
    # 既にPublishPressショートコードがある場合でも、AI生成プロフィールが併存していれば消す。
    html_content = _remove_author_reviewer_div_blocks(html_content)

    # 二重挿入防止
    if 'publishpress_authors_box' in html_content:
        html_content = normalize_publishpress_shortcodes(html_content, site_name)
        print("   ℹ️ PublishPressショートコード検出済み → 追加挿入はスキップ")
        return html_content

    ppma = PPMA_LAYOUT_MAP.get(site_name)
    if not ppma:
        print(f"   ⚠️ {site_name} のPublishPressレイアウトIDが未設定 → 著者ブロック置換スキップ")
        return html_content

    shortcodes, display_mode = build_publishpress_shortcodes(site_name)
    if not shortcodes:
        print(f"   ⚠️ {site_name} のPublishPress表示モードが不正です → 著者ブロック置換スキップ")
        return html_content

    # 最初の<h2>を見つける
    h2_match = re.search(r'<h2[\s>]', html_content)
    if not h2_match:
        print("   ⚠️ <h2>タグが見つかりません → 著者ブロック置換スキップ")
        return html_content

    before_h2 = html_content[:h2_match.start()]
    after_h2  = html_content[h2_match.start():]

    # Step 2: HR区切り型の著者・監修者ブロックを検出（最初の<h2>直前にある）
    # パターンA: <hr> + 段落群 + <hr>（2つのHR、著者+監修者が一塊）
    # パターンB: <hr> + 段落群 + <hr> + 段落群 + <hr>（3つのHR、著者と監修者が分離）
    # → 共通: <hr> で始まり、段落と<hr>が混在し、最後が <hr> で終わる
    block_pattern = r'<hr>\s*\n*(?:(?:<p>[\s\S]*?</p>|<hr>)\s*\n*)+<hr>\s*$'
    block_match = re.search(block_pattern, before_h2)

    if block_match:
        # ブロック検出成功 → 置換
        new_before = before_h2[:block_match.start()] + '\n' + shortcodes + '\n'
        html_content = new_before + after_h2
        ppma_label = ppma.get('single') or f"{ppma.get('author')}/{ppma.get('reviewer')}"
        print(f"   ✅ 著者・監修者ブロック → PublishPressショートコードに置換完了（{site_name}: {display_mode}, ppma_{ppma_label}）")
    else:
        # フォールバック: ブロック検出失敗 → <h2>直前に挿入
        html_content = before_h2.rstrip() + '\n\n' + shortcodes + '\n' + after_h2
        ppma_label = ppma.get('single') or f"{ppma.get('author')}/{ppma.get('reviewer')}"
        print(f"   ℹ️ 著者ブロック未検出 → <h2>直前にショートコード挿入（{site_name}: {display_mode}, ppma_{ppma_label}）")

    return html_content


def _extract_images_from_divs(content):
    """div.image-description 内に誤配置された<img>を抽出し、div直後にスタンドアロン配置する。
    Geminiが画像をdivやli内に埋め込んでしまう問題への対策。
    """
    def _process_div_block(match):
        div_html = match.group(0)
        # div内の全<img>タグを抽出
        imgs = re.findall(r'<img\s+[^>]+>', div_html, flags=re.IGNORECASE)
        if not imgs:
            return div_html  # 画像なし → そのまま
        # div内から<img>タグを削除
        cleaned_div = re.sub(r'\s*<img\s+[^>]+>\s*', '', div_html, flags=re.IGNORECASE)
        # 重複URL除去（同じsrcの画像は1枚だけ残す）
        seen_srcs = set()
        unique_imgs = []
        for img in imgs:
            src_match = re.search(r'src=["\']([^"\']+)["\']', img)
            if src_match:
                src = src_match.group(1)
                if src not in seen_srcs:
                    seen_srcs.add(src)
                    unique_imgs.append(img)
            else:
                unique_imgs.append(img)
        if not unique_imgs:
            return cleaned_div
        # div直後にスタンドアロン画像として1枚だけ配置（H2画像の本来の形式）
        standalone_img = unique_imgs[0]
        # margin-topを20pxに統一（div内のスタイルとの差異を吸収）
        standalone_img = re.sub(r'margin-top:\s*\d+px', 'margin-top: 20px', standalone_img)
        if 'margin-bottom' not in standalone_img:
            standalone_img = standalone_img.replace('margin-top: 20px', 'margin-top: 20px; margin-bottom: 20px')
        return cleaned_div + '\n' + standalone_img
    # <div class="image-description"...>...</div> ブロックを処理
    content = re.sub(
        r'<div\s+class=["\']image-description["\'][^>]*>[\s\S]*?</div>',
        _process_div_block,
        content,
        flags=re.IGNORECASE
    )
    return content


def _markdownish_to_html_if_needed(content):
    """最終出力にMarkdown見出しが残った場合の保険変換。"""
    text = content or ""
    text = re.sub(r'^\s*現在日は\s*\d{4}年\d{2}月\d{2}日\s*です。\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*内部参照日\s*[:：]\s*\d{4}年\d{2}月\d{2}日\s*$', '', text, flags=re.MULTILINE)
    needs_convert = (
        not re.search(r'<h1[^>]*>', text, flags=re.IGNORECASE)
        and re.search(r'(?m)^\s*#\s+\S+', text)
    ) or re.search(r'(?m)^\s*#{1,3}\s+\S+', text)
    if not needs_convert:
        return text

    def inline_md(s):
        s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
        s = re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)', r'<a href="\2">\1</a>', s)
        return s

    block_tags = re.compile(
        r'^\s*</?(?:h[1-6]|p|div|table|thead|tbody|tr|th|td|ul|ol|li|blockquote|cite|img|a|strong|span|br|hr|script|style|figure|figcaption)\b',
        re.IGNORECASE
    )
    lines = text.splitlines()
    out = []
    paragraph = []
    table_rows = []

    def flush_paragraph():
        if paragraph:
            body = inline_md(" ".join(x.strip() for x in paragraph if x.strip()))
            if body:
                out.append(f"<p>{body}</p>")
            paragraph.clear()

    def flush_table():
        if not table_rows:
            return
        rows = []
        for row in table_rows:
            cells = [inline_md(c.strip()) for c in row.strip().strip("|").split("|")]
            if all(re.fullmatch(r':?-{3,}:?', c.replace(" ", "")) for c in cells):
                continue
            tag = "th" if not rows else "td"
            rows.append("<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>")
        if rows:
            if rows[0].startswith("<tr><th>"):
                out.append("<table><thead>" + rows[0] + "</thead><tbody>" + "".join(rows[1:]) + "</tbody></table>")
            else:
                out.append("<table><tbody>" + "".join(rows) + "</tbody></table>")
        table_rows.clear()

    for raw in lines:
        line = raw.strip()
        if not line:
            flush_paragraph()
            flush_table()
            continue
        if re.match(r'^\|.+\|$', line):
            flush_paragraph()
            table_rows.append(line)
            continue
        flush_table()
        m = re.match(r'^(#{1,6})\s+(.+)$', line)
        if m:
            flush_paragraph()
            level = len(m.group(1))
            out.append(f"<h{level}>{inline_md(m.group(2).strip())}</h{level}>")
            continue
        if re.match(r'^[-*]\s+', line):
            flush_paragraph()
            item_text = re.sub(r'^[-*]\s+', '', line)
            out.append(f"<ul><li>{inline_md(item_text)}</li></ul>")
            continue
        if block_tags.match(line) or line.startswith("[publishpress_") or line.startswith("[af_url"):
            flush_paragraph()
            out.append(raw)
            continue
        paragraph.append(line)
    flush_paragraph()
    flush_table()
    return "\n".join(out)


def _convert_markdown_tables_to_html(content):
    text = content or ""
    lines = text.splitlines()
    out = []
    table_rows = []

    def inline_md(s):
        s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
        s = re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)', r'<a href="\2">\1</a>', s)
        return s

    def flush_table():
        if len(table_rows) < 2:
            out.extend(table_rows)
            table_rows.clear()
            return
        rows = []
        for row in table_rows:
            cells = [inline_md(c.strip()) for c in row.strip().strip("|").split("|")]
            if len(cells) < 2:
                continue
            if all(re.fullmatch(r':?-{3,}:?', c.replace(" ", "")) for c in cells):
                continue
            tag = "th" if not rows else "td"
            rows.append("<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>")
        if rows:
            if rows[0].startswith("<tr><th>"):
                out.append("<table><thead>" + rows[0] + "</thead><tbody>" + "".join(rows[1:]) + "</tbody></table>")
            else:
                out.append("<table><tbody>" + "".join(rows) + "</tbody></table>")
        table_rows.clear()

    for line in lines:
        if re.match(r'^\s*\|.+\|\s*$', line):
            table_rows.append(line.strip())
        else:
            flush_table()
            out.append(line)
    flush_table()
    return "\n".join(out)


def _article_output_stats(content):
    html = content or ""
    text = re.sub(r'<[^>]+>', '', html)
    text = re.sub(r'\s+', '', text)
    return {
        "html_chars": len(html),
        "plain_chars": len(text),
        "h1": len(re.findall(r'<h1[^>]*>', html, flags=re.IGNORECASE)),
        "h2": len(re.findall(r'<h2[^>]*>', html, flags=re.IGNORECASE)),
        "h3": len(re.findall(r'<h3[^>]*>', html, flags=re.IGNORECASE)),
        "markdown_h1": len(re.findall(r'(?m)^\s*#\s+', html)),
        "markdown_h2": len(re.findall(r'(?m)^\s*##\s+', html)),
        "date_leak": bool(re.search(r'現在日は\s*\d{4}年\d{2}月\d{2}日\s*です', html)),
    }


def _inline_tag_balance_report(html):
    """本文全体へ装飾タグが漏れる原因になりやすいタグの開閉数を返す。"""
    report = {}
    for tag in ["strong", "b", "em", "i", "u", "mark", "span", "a"]:
        opens = len(re.findall(fr'<{tag}\b[^>]*>', html or "", flags=re.IGNORECASE))
        closes = len(re.findall(fr'</{tag}>', html or "", flags=re.IGNORECASE))
        if opens != closes:
            report[tag] = (opens, closes)
    return report


_BLOCK_TAG_IN_P_PATTERN = r'(?:h[1-6]|table|thead|tbody|tr|ul|ol|blockquote|div|section|figure)'


def _repair_nested_heading_tags(html):
    """`<h3><h3>...` のような見出しタグの入れ子を補正する。"""
    content = html or ""
    # 外側の空見出しが内側の見出しを包んでいるケースを、内側だけに戻す。
    content = re.sub(
        r'<h[1-6]\b[^>]*>\s*(?=<h[1-6]\b)',
        '',
        content,
        flags=re.IGNORECASE,
    )
    # 上の補正後に残る余分な閉じタグを除去する。
    content = re.sub(
        r'(</h[1-6]>)\s*</h[1-6]>',
        r'\1',
        content,
        flags=re.IGNORECASE,
    )
    return content


def _nested_heading_report(html):
    """見出しタグの中に別の見出しタグが残っていないかを検出する。"""
    issues = []
    # 閉じタグをまたいで次の見出しまで拾うと、正常な <h1>...</h1><h2>...</h2> まで
    # 入れ子扱いしてしまうため、同じ見出しの閉じタグより前だけを検査する。
    for m in re.finditer(r'<(h[1-6])\b[^>]*>(?:(?!</\1>).)*<h[1-6]\b', html or "", flags=re.IGNORECASE | re.DOTALL):
        issues.append(f"<{m.group(1).lower()}>内に見出しタグ")
    return issues


def _repair_block_tags_inside_paragraphs(html):
    """`<p><h3>` や `<p><table>` など、段落内へブロック要素が入る破損を補正する。"""
    content = html or ""
    block = _BLOCK_TAG_IN_P_PATTERN

    # 空の<p>がブロック要素を包んでしまったケース: <p><h3>... → <h3>...
    content = re.sub(
        rf'<p\b[^>]*>\s*(?=<{block}\b)',
        '',
        content,
        flags=re.IGNORECASE,
    )

    # 文字の後ろにブロック要素が入り込んだケース: <p>本文<h3>... → <p>本文</p><h3>...
    content = re.sub(
        rf'(<p\b[^>]*>(?:(?!</p>|<{block}\b)[\s\S])*?\S)\s*(?=<{block}\b)',
        r'\1</p>',
        content,
        flags=re.IGNORECASE,
    )

    # ブロック要素の後ろに余った</p>を除去: </h3></p> / </table></p>
    content = re.sub(
        rf'(</{block}>)\s*</p>',
        r'\1',
        content,
        flags=re.IGNORECASE,
    )

    # pタグの二重閉じなどを軽く整える。
    content = re.sub(r'</p>\s*</p>', '</p>', content, flags=re.IGNORECASE)
    return content


def _block_tag_paragraph_nesting_report(html):
    """段落内にブロックタグが残っていないかを検出する。"""
    content = html or ""
    block = _BLOCK_TAG_IN_P_PATTERN
    issues = []
    for m in re.finditer(rf'<p\b[^>]*>\s*<({block})\b', content, flags=re.IGNORECASE):
        issues.append(f"<p>直下に<{m.group(1).lower()}>")
    for m in re.finditer(rf'</({block})>\s*</p>', content, flags=re.IGNORECASE):
        issues.append(f"</{m.group(1).lower()}>直後に余分な</p>")
    for m in re.finditer(rf'<p\b[^>]*>(?:(?!</p>).)*?<({block})\b', content, flags=re.IGNORECASE | re.DOTALL):
        label = f"<p>内に<{m.group(1).lower()}>"
        if label not in issues:
            issues.append(label)
    return issues


def _plain_char_count_from_html(html):
    text = re.sub(r'<[^>]+>', '', html or '')
    text = re.sub(r'\s+', '', text)
    return len(text)


def _is_parent_step06_too_short(step_outputs, final_html, min_ratio=0.85, min_loss=1500):
    """Step06がStep04本文を大きく削った場合に検知する。"""
    if not step_outputs or "step04" not in step_outputs or not final_html:
        return False, ""
    base_chars = _plain_char_count_from_html(step_outputs.get("step04", ""))
    final_chars = _plain_char_count_from_html(final_html)
    if base_chars <= 0 or final_chars <= 0:
        return False, ""
    loss = base_chars - final_chars
    ratio = final_chars / base_chars
    if loss >= min_loss and ratio < min_ratio:
        return True, f"Step06で本文量が大きく減っています（Step04 {base_chars:,}文字 → Step06 {final_chars:,}文字 / {ratio:.0%}）。"
    return False, ""


def _is_valid_parent_html(content):
    st = _article_output_stats(content)
    return (
        st["h1"] >= 1
        and st["h2"] >= 3
        and st["markdown_h1"] == 0
        and st["markdown_h2"] == 0
        and not st["date_leak"]
        and not _block_tag_paragraph_nesting_report(content)
        and not _nested_heading_report(content)
    )


def _parent_expected_table(step_outputs):
    step03 = step_outputs.get("step03", "")
    step04 = step_outputs.get("step04", "")
    article_body_has_table = (
        "<table" in step04.lower()
        or bool(_extract_markdown_table_blocks(step04))
    )
    blueprint_requests_table = any(x in step03 for x in ["比較表", "料金表", "一覧表", "表作成指示", "HTML表"])
    return bool(
        article_body_has_table
        or blueprint_requests_table
    )


def _extract_markdown_table_blocks(text, limit=3):
    blocks = []
    current = []
    for line in (text or "").splitlines():
        if re.match(r'^\s*\|.+\|\s*$', line):
            current.append(line.strip())
        else:
            if len(current) >= 2:
                blocks.append("\n".join(current))
            current = []
    if len(current) >= 2:
        blocks.append("\n".join(current))
    return blocks[:limit]


def _extract_html_table_blocks(text, limit=3):
    blocks = re.findall(r'<table\b[^>]*>.*?</table>', text or "", flags=re.IGNORECASE | re.DOTALL)
    return blocks[:limit]


def _is_article_markdown_table_candidate(block):
    """記事本文の表だけを復元対象にする。品質レビューやプロンプト説明用の表は除外する。"""
    compact = re.sub(r'\s+', '', block or "")
    if not compact:
        return False
    review_markers = [
        "評価観点", "評価サブ項目", "評価結果", "ペルソナとしての所感",
        "URL(ドメイン)", "語彙・構成の特徴", "ユーザーの状況",
        "用語|定義", "要件|中核的要請", "法的・倫理的",
    ]
    if any(marker in compact for marker in review_markers):
        return False
    article_markers = [
        "料金", "費用", "会員数", "連盟", "比較", "メリット", "デメリット",
        "特徴", "おすすめ", "成婚", "サービス", "項目",
    ]
    return any(marker in compact for marker in article_markers)


def _is_article_html_table_candidate(block):
    compact = re.sub(r'\s+', '', re.sub(r'<[^>]+>', '', block or ""))
    if not compact:
        return False
    review_markers = [
        "評価観点", "評価サブ項目", "評価結果", "ペルソナとしての所感",
        "URL(ドメイン)", "語彙・構成の特徴", "ユーザーの状況",
    ]
    if any(marker in compact for marker in review_markers):
        return False
    article_markers = [
        "料金", "費用", "会員数", "連盟", "比較", "メリット", "デメリット",
        "特徴", "おすすめ", "成婚", "サービス", "項目",
    ]
    return any(marker in compact for marker in article_markers)


def _build_table_preservation_retry_prompt(base_prompt, step_outputs):
    tables_text = _build_parent_table_preservation_payload(step_outputs)
    return base_prompt + f"""

# 【再生成時の最重要追加指示：表落ち修正】
直前の出力では、前工程に存在する比較表・表データが最終HTMLから消えていました。
この出力では、以下の表データを必ずHTMLの<table>に変換し、関連するH2セクション内に挿入してください。
表を文章に置き換えたり、省略したり、箇条書きへ変換したりしてはいけません。

【必ずHTML表として残す表データ】
{tables_text}
"""


def _build_parent_table_preservation_payload(step_outputs):
    """Step06へ明示的に渡す記事本文用の表データ。品質レビュー表は除外する。"""
    tables = []
    html_tables = []
    for key in ["step04"]:
        html_tables.extend(_extract_html_table_blocks(step_outputs.get(key, ""), limit=3))
        tables.extend(_extract_markdown_table_blocks(step_outputs.get(key, "")))
    html_tables = [t for t in html_tables if _is_article_html_table_candidate(t)]
    tables = [t for t in tables if _is_article_markdown_table_candidate(t)]
    if html_tables:
        tables_text = "\n\n".join(html_tables[:2])
    elif tables:
        tables_text = "\n\n".join(tables[:3])
    else:
        tables_text = "（Step03のブループリントで指定された比較表・一覧表を、Step04本文の内容に基づいてHTML表として作成してください。品質レビュー用の評価表は記事本文に入れないでください。）"
    return tables_text


def _build_missing_tables_html(step_outputs):
    html_tables = []
    seen_html = set()
    for key in ["step04"]:
        for block in _extract_html_table_blocks(step_outputs.get(key, ""), limit=10):
            if not _is_article_html_table_candidate(block):
                continue
            normalized = re.sub(r'\s+', '', block)
            if normalized in seen_html:
                continue
            seen_html.add(normalized)
            html_tables.append(block)
    if html_tables:
        return "\n".join([
            '<div class="auto-restored-table" style="margin: 20px 0;">',
            '<p><strong>比較表</strong></p>',
            "\n".join(html_tables[:2]),
            "</div>",
        ])

    tables = []
    seen = set()
    for key in ["step04"]:
        for block in _extract_markdown_table_blocks(step_outputs.get(key, ""), limit=10):
            if not _is_article_markdown_table_candidate(block):
                continue
            normalized = re.sub(r'\s+', '', block)
            if normalized in seen:
                continue
            seen.add(normalized)
            if len(block.splitlines()) >= 3:
                tables.append(block)
    html_tables = []
    for block in tables[:2]:
        converted = _convert_markdown_tables_to_html(block)
        if "<table" in converted.lower():
            html_tables.append(converted)
    if not html_tables:
        return ""
    return "\n".join([
        '<div class="auto-restored-table" style="margin: 20px 0;">',
        '<p><strong>比較表</strong></p>',
        "\n".join(html_tables),
        "</div>",
    ])


def _insert_missing_parent_tables(final_html, step_outputs):
    if "<table" in (final_html or "").lower():
        return final_html
    tables_html = _build_missing_tables_html(step_outputs)
    if not tables_html:
        return final_html
    html = final_html or ""
    h2_matches = list(re.finditer(r'<h2[^>]*>.*?</h2>', html, flags=re.IGNORECASE | re.DOTALL))
    target = None
    for m in h2_matches:
        heading_text = re.sub(r'<[^>]+>', '', m.group(0))
        if any(x in heading_text for x in ["比較", "連盟", "主要"]):
            target = m
            break
    if target is None and h2_matches:
        target = h2_matches[min(1, len(h2_matches) - 1)]
    if target:
        return html[:target.end()] + "\n" + tables_html + "\n" + html[target.end():]
    return tables_html + "\n" + html


def print_article_output_summary(content, label="生成結果"):
    st = _article_output_stats(content)
    print(f"\n📄 {label}: HTML {st['html_chars']:,}文字 / 本文 {st['plain_chars']:,}文字 / H1 {st['h1']} / H2 {st['h2']} / H3 {st['h3']}")
    if st["markdown_h1"] or st["markdown_h2"] or st["date_leak"]:
        print("   ⚠️ Markdown見出しまたは内部日付メモの混入を検出しました。HTML整形を確認してください。")


def _is_bad_parent_step_output(filename, content):
    """プロンプト復唱・空コードフェンスなど、次工程に渡すと壊れる出力を検出する。"""
    name = filename.lower()
    text = (content or "").strip()
    compact = re.sub(r'\s+', '', text)
    if len(compact) < 80:
        return True, "出力が短すぎます"
    if re.fullmatch(r'```(?:html|markdown)?', text, flags=re.IGNORECASE):
        return True, "コードフェンスだけの出力です"
    if "START OF FILE" in text or "END OF FILE" in text:
        return True, "プロンプト本文を復唱しています"
    if "## INPUT" in text and ("本プロンプト" in text or "手順" in text):
        return True, "プロンプト指示を本文として返しています"
    if "step03" in name:
        has_blueprint = any(x in text for x in ["コンテンツブループリント", "H1:", "H2-", "【コンテンツブループリント詳細】"])
        has_prompt_echo = "共通コンポーネント" in text and "引用・参考文献・出典の完全ガイド" in text
        if not has_blueprint or has_prompt_echo:
            return True, "Step03のブループリント生成に失敗しています"
    if "step05" in name:
        has_review = any(x in text for x in ["品質評価", "改善提案", "修正指示", "評価レポート", "自動修正用"])
        if not has_review:
            return True, "Step05の品質レビュー生成に失敗しています"
    return False, ""


def _normalize_prompt_template_text(text):
    """プロンプトファイル外側のコードフェンス/START-ENDマーカーを除去する。"""
    if not text:
        return ""
    cleaned = text.strip()
    fence_match = re.match(r'^```(?:markdown|html|text)?\s*\n([\s\S]*?)\n```\s*$', cleaned, flags=re.IGNORECASE)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    cleaned = re.sub(r'^\s*---\s*START OF FILE[^\n]*---\s*\n?', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\n?\s*---\s*END OF FILE[^\n]*---\s*$', '', cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _build_step05_fallback_review(step04_html):
    """Step05がGemini混雑で落ちた時の最小レビュー。Step06へ進めるためのローカル安全弁。"""
    stats = _article_output_stats(step04_html or "")
    table_note = "HTML表は検出済みです。" if "<table" in (step04_html or "").lower() else "比較表・一覧表が必要な記事では、Step06でHTML表を補ってください。"
    return f"""【品質チェック結果】
- 総合判定: 簡易チェックで続行
- 主な問題点: Step05品質チェックAPIが一時的な503混雑で実行できなかったため、ローカル簡易レビューとして扱います。
- 優れている点: Step04本文HTMLは生成済みです。HTML {stats['html_chars']:,}文字 / 本文 {stats['plain_chars']:,}文字 / H1 {stats['h1']} / H2 {stats['h2']} / H3 {stats['h3']}。
- 優先修正項目: Markdown混入、内部メモ混入、見出し切れ、表落ち、古い年のデータへの「最新」表記をStep06で確認してください。

【自動修正用プロンプト】
あなたはプロの編集者です。提供された記事本文HTMLを、公開可能なWordPress本文HTMLとして整えてください。

修正ルール:
- 出力は完成版の記事本文HTMLだけにしてください。
- 先頭は必ず `<h1>` から始めてください。
- Markdownは禁止です。Markdown見出し、Markdown表、Markdownリンク、コードフェンスは出力しないでください。
- `<h1>`、`<h2>`、`<h3>`、`<p>`、`<table>`、`<blockquote>`、`<ul><li>` などのHTML構造を維持してください。
- 見出しが途中で切れていないか確認し、切れている場合は自然な見出しへ修正してください。
- 「現在日は」「プロンプト」「ディープリサーチ」「ペルソナ」「UVP」「ブループリント」などの内部メモは本文から削除してください。
- 古い年のデータに「最新」と書かず、確認時点を明記してください。
- {table_note}
- 良い文章や自然なCTAはむやみに変えず、記事全体を省略せずに完成版として出力してください。
"""


def _repair_inline_tag_leaks(html):
    """<strong>などの装飾タグが段落や表セルをまたいで漏れる事故を防ぐ。"""
    if not html:
        return html

    inline_tags = {"strong", "b", "em", "i", "u", "mark", "span", "a"}
    block_tags = {
        "p", "li", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6",
        "blockquote", "div", "section", "article", "ul", "ol", "table",
        "thead", "tbody", "tfoot", "tr",
    }
    void_tags = {"br", "hr", "img", "input", "meta", "link", "source", "track", "wbr"}
    tag_re = re.compile(r'<!--.*?-->|<![^>]*>|<[^>]+>', re.DOTALL)

    out = []
    stack = []
    pos = 0

    def close_open_inline():
        while stack:
            out.append(f"</{stack.pop()}>")

    for m in tag_re.finditer(html):
        text = html[pos:m.start()]
        if text:
            out.append(text)
        tag = m.group(0)
        pos = m.end()

        if tag.startswith("<!--") or tag.startswith("<!"):
            out.append(tag)
            continue

        name_match = re.match(r'</?\s*([a-zA-Z0-9]+)', tag)
        if not name_match:
            out.append(tag)
            continue
        name = name_match.group(1).lower()
        is_close = tag.startswith("</")
        is_self_close = tag.rstrip().endswith("/>") or name in void_tags

        if is_close:
            if name in inline_tags:
                if name in stack:
                    # 入れ子が崩れている場合も、対象タグまで閉じて漏れを止める。
                    while stack:
                        top = stack.pop()
                        out.append(f"</{top}>")
                        if top == name:
                            break
                else:
                    # 対応する開始タグがない閉じタグは捨てる。
                    pass
                continue
            if name in block_tags:
                close_open_inline()
            out.append(tag)
            continue

        if name in block_tags:
            close_open_inline()
            out.append(tag)
            continue

        out.append(tag)
        if name in inline_tags and not is_self_close:
            stack.append(name)

    out.append(html[pos:])
    close_open_inline()
    repaired = "".join(out)
    return re.sub(r'<(strong|b|em|i|u|mark|span|a)>\s*</\1>', '', repaired, flags=re.IGNORECASE)


def force_cleanup_html_parent(html_content):
    """親記事用HTMLクリーンアップ（旧auto_post_normal.pyのforce_cleanup_html）"""
    content = _markdownish_to_html_if_needed(html_content)
    content = _convert_markdown_tables_to_html(content)

    # div.image-description / li 内に誤配置された<img>を抽出してdiv直後にスタンドアロン配置
    content = _extract_images_from_divs(content)

    # --- AI要約h2の順序修正 ---
    # Geminiが「💡💡 このパートをまとめると！」をh2タグとして出力し、
    # 画像挿入ロジックがそのh2に画像を付けてしまう問題を修正。
    # パターン: <h2>💡💡 summary</h2> <img.../> <h2>real heading</h2>
    # 修正後:   <h2>real heading</h2> <img.../> <p class="section-summary">💡💡 summary</p>
    def _fix_summary_h2_order(html):
        # 💡💡要約h2 → (任意の空白/img) → 実際のh2 のパターンを検出して並べ替え
        pattern = re.compile(
            r'<h2[^>]*>\s*(💡💡[^<]+)</h2>'       # Group 1: 💡💡要約テキスト
            r'(\s*(?:<img[^>]*/?>\s*)?)'            # Group 2: 任意のimg+空白
            r'(<h2[^>]*>[^<]+</h2>)',               # Group 3: 実際のh2タグ
            re.DOTALL
        )
        def _reorder(m):
            summary_text = m.group(1).strip()
            img_and_ws = m.group(2)
            real_h2 = m.group(3)
            summary_box = (
                f'<p style="background-color: #f0f8ff; border-left: 4px solid #007bff; '
                f'padding: 10px 15px; margin: 15px 0; font-weight: bold;">'
                f'{summary_text}</p>'
            )
            return f'{real_h2}{img_and_ws}{summary_box}'
        html = pattern.sub(_reorder, html)
        return html
    content = _fix_summary_h2_order(content)

    # AI要約がh2/h3タグに混入している場合の修正（上記で漏れたケースのフォールバック）
    def fix_summary_in_heading(match):
        tag_name = match.group(1)
        inner_content = match.group(2)
        for pattern in [r'(?:💡💡|💡|👉)\s*このパートをまとめると！?\s*', r'(?:\?\?|👉)\s*このパートをまとめると！?\s*']:
            if re.search(pattern, inner_content):
                clean_heading = re.sub(pattern, '', inner_content).strip()
                if not clean_heading:
                    # 見出し全体がAI要約だった場合 → pタグに変換
                    summary_text = inner_content.strip()
                    return (
                        f'<p style="background-color: #f0f8ff; border-left: 4px solid #007bff; '
                        f'padding: 10px 15px; margin: 15px 0; font-weight: bold;">'
                        f'{summary_text}</p>'
                    )
                return f'<{tag_name}>{clean_heading}</{tag_name}>'
        return match.group(0)

    content = re.sub(r'<(h[23])[^>]*>(.*?)</\1>', fix_summary_in_heading, content, flags=re.DOTALL)
    content = re.sub(r'\?{1,5}\s*このパートをまとめると', '👉 このパートをまとめると', content)
    content = re.sub(r'\?{1,5}\s*ここが他と違う', '☝ ここが他と違う', content)
    content = re.sub(r'\?{1,5}\s*定量スペック', '📊 定量スペック', content)
    content = re.sub(r'\?{1,5}\s*ユーザーのリアルな声', '🗣 ユーザーのリアルな声', content)
    content = re.sub(r'\?{1,5}♀\??\s*良い点', '🙆‍♀️ 良い点', content)
    content = re.sub(r'\?{1,5}♀\??\s*気になる点', '🙅‍♀️ 気になる点', content)
    content = re.sub(r'\?{1,5}\s*結論：こんな人', '👉 結論：こんな人', content)
    content = re.sub(r'\?{2,5}(?=\s*[\u3000-\u9fff\uff00-\uffef])', '👉', content)

    # Markdownコードブロック削除
    content = re.sub(r'```html\s*', '', content, flags=re.IGNORECASE)
    content = re.sub(r'```\s*$', '', content, flags=re.MULTILINE)
    content = re.sub(r'^```\s*', '', content, flags=re.MULTILINE)

    # Markdown水平線（--- / *** / ___）の除去
    # h2/h3直前に残るセパレータがWordPressで「---」として表示される問題を防ぐ
    content = re.sub(r'^\s*-{3,}\s*$', '', content, flags=re.MULTILINE)
    content = re.sub(r'^\s*\*{3,}\s*$', '', content, flags=re.MULTILINE)
    content = re.sub(r'^\s*_{3,}\s*$', '', content, flags=re.MULTILINE)

    # インフォグラフィック指示書削除
    content = re.sub(r'🎨.*?(?=<h[23]|$)', '', content, flags=re.DOTALL)
    content = re.sub(r'デザイナー向け指示書.*?(?=<h[23]|$)', '', content, flags=re.DOTALL)
    content = re.sub(r'📊.*?(?=<h[23]|<table>|$)', '', content, flags=re.DOTALL)
    content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
    # 閉じられていない <!-- を除去（記事が途中で途切れる致命的バグの防止）
    content = content.replace('<!--', '')
    content = re.sub(r'\[図解提案:.*?\]', '', content)
    content = re.sub(r'\[画像指示:.*?\]', '', content)

    # 不要ラッパータグ削除
    content = re.sub(r'<!DOCTYPE[^>]*>', '', content, flags=re.IGNORECASE)
    content = re.sub(r'<html[^>]*>|</html>', '', content, flags=re.IGNORECASE)
    content = re.sub(r'<head>.*?</head>', '', content, flags=re.DOTALL | re.IGNORECASE)
    content = re.sub(r'<body[^>]*>|</body>', '', content, flags=re.IGNORECASE)
    content = re.sub(r'<style>.*?</style>', '', content, flags=re.DOTALL | re.IGNORECASE)

    # 内部指示・メタ情報削除
    content = re.sub(r'「〇〇([^」]*)」', r'\1', content)
    content = re.sub(r'参加者XXXX名', '', content)
    content = re.sub(r'図解：|表タイトル:|【[^】]*の要点】|図解のポイント：|表の概要：', '', content)
    content = re.sub(r'\(ここに.*?を挿入\)', '', content)
    content = re.sub(r'※詳細は後述', '', content)
    content = re.sub(r'\[コメント挿入:\s*([^\]]*?)\]', r'\1', content)
    content = re.sub(r'\([^)]*医師コメント[^)]*\)', '', content)
    content = re.sub(r'<p>\s*<strong>\s*CTA\s*\(Call to Action\)\s*[:\s]*</strong>\s*</p>', '', content, flags=re.IGNORECASE)
    content = re.sub(r'<p>\s*(リード文|まとめ|導入|本文)\s*</p>', '', content)
    content = re.sub(r'\(\s*\)', '', content)
    content = re.sub(r'\[\s*\]', '', content)
    content = re.sub(r'(?<!\.)\.\.\.(?!\.)', '', content)

    # ダミーリンク・画像削除
    for domain in ['example.com', 'example.org', 'example.net', 'yourdomain.com', 'placeholder.com', 'localhost', '127.0.0.1']:
        content = re.sub(rf'<a\s+href=["\']https?://{re.escape(domain)}[^"\']*["\'][^>]*>.*?</a>', '', content, flags=re.IGNORECASE)
        content = re.sub(rf'<img\s+[^>]*src=["\']https?://{re.escape(domain)}[^"\']*["\'][^>]*>', '', content, flags=re.IGNORECASE)
    content = re.sub(r'<a\s+href=["\']#internal-link-[^"\']*["\'][^>]*>.*?</a>', '', content)

    # 見出し内装飾タグ削除
    content = re.sub(r'(<h[1-6][^>]*>)\s*<strong>(.*?)</strong>\s*(</h[1-6]>)', r'\1\2\3', content)
    content = re.sub(r'(<h[1-6][^>]*>)\s*<span[^>]*>(.*?)</span>\s*(</h[1-6]>)', r'\1\2\3', content)
    before_nested_headings = _nested_heading_report(content)
    content = _repair_nested_heading_tags(content)
    after_nested_headings = _nested_heading_report(content)
    if before_nested_headings and not after_nested_headings:
        print(f"   ℹ️ HTML整形: 入れ子になった見出しタグを補正しました（{len(before_nested_headings)}件）。")

    # 引用符アーティファクト削除
    content = re.sub(r'\[\d+\]', '', content)
    content = re.sub(r'\[\[[^\]]+\]\]', '', content)
    content = re.sub(r'<a\s+href=["\'][^"\']*vertexaisearch[^"\']*["\'][^>]*>\s*\[\d+\]\s*</a>', '', content)
    content = re.sub(r'<a\s+href=["\'][^"\']*google\.com/url\?sa=[^"\']*["\'][^>]*>\s*\[\d+\]\s*</a>', '', content)
    content = re.sub(r'<strong>\s*(<h[23][^>]*>)', r'\1', content)
    content = re.sub(r'<strong>\s*</strong>', '', content)

    # 空タグ・空行
    content = re.sub(r'<h[1-6][^>]*>\s*</h[1-6]>', '', content)
    content = re.sub(r'<p>\s*</p>', '', content)
    content = re.sub(r'<li>\s*</li>', '', content)
    content = re.sub(r'\n\s*\n\s*\n+', '\n\n', content)
    before_block_nesting = _block_tag_paragraph_nesting_report(content)
    content = _repair_block_tags_inside_paragraphs(content)
    after_block_nesting = _block_tag_paragraph_nesting_report(content)
    if before_block_nesting and not after_block_nesting:
        print(f"   ℹ️ HTML整形: 段落内に入り込んだ見出し/表/リストタグを補正しました（{len(before_block_nesting)}件）。")
    content = _repair_inline_tag_leaks(content)
    content, unlinked_cite_count = _strip_low_authority_citation_links(content)
    if unlinked_cite_count:
        print(f"   ℹ️ 引用・出典ブロック: 公的・準公的情報源以外の外部リンクを{unlinked_cite_count}件解除しました（出典名は残します）。")

    return content.strip()

def check_introduction_in_html(generated_text):
    """Step6の導入文チェック"""
    if "```html" in generated_text or "```" in generated_text:
        code_match = re.search(r'```(?:html)?\s*(.*?)```', generated_text, re.DOTALL | re.IGNORECASE)
        content = code_match.group(1).strip() if code_match else generated_text
    else:
        content = generated_text
    h1_match = re.search(r'<h1[^>]*>(.*?)</h1>', content, re.DOTALL | re.IGNORECASE)
    if not h1_match:
        print("   ❌ <h1>タイトルタグが見つかりません。")
        return False
    print(f'   ✅ <h1>タグを検出')
    content_after_h1 = content[h1_match.end():]
    first_section = re.search(r'<h[23][^>]*>', content_after_h1, re.IGNORECASE)
    if not first_section:
        return True
    introduction_part = content_after_h1[:first_section.start()]
    text_only = re.sub(r'\s+', '', re.sub(r'<[^>]+>', '', introduction_part))
    char_count = len(text_only)
    print(f"   📊 導入文: {char_count}文字")
    if char_count < 40:
        print(f"   ❌ 導入文不足（最低40文字必要）")
        return False
    print(f"   ✅ 導入文チェック合格")
    return True

def run_article_generation_parent(target_api_key, initial_instruction, execution_list, selected_site, target_input, resume_data=None, resume_metadata=None):
    """親記事生成（モード1/2共通）"""
    model = MODEL_PARENT
    log_history  = []
    step_outputs = {}
    final_content = ""
    allowed_h2_image_urls = set()
    resume_file = RESUME_MOECHIN if selected_site.get("type") == "C" else RESUME_NORMAL

    def _resume_meta_with_status(status, **extra):
        meta = dict(resume_metadata or {})
        meta["resume_status"] = status
        meta["completed"] = (status == "completed")
        for key, value in extra.items():
            if value is not None:
                meta[key] = value
        return meta

    def _save_interrupted_resume(reason="", failed_step=""):
        meta = _resume_meta_with_status("interrupted", last_error=reason, failed_step=failed_step)
        save_resume_data(
            resume_file,
            target_input,
            initial_instruction,
            step_outputs,
            final_content,
            log_history,
            metadata=meta,
        )

    is_paid = (API_KEY_PAID is not None and target_api_key == API_KEY_PAID)
    sleep_continue, sleep_step = (3, 5) if is_paid else (15, 35)

    if is_paid:
        print(f"\n🚀 【有料枠モード】待機時間短縮")
    else:
        print(f"\n🐢 【無料枠モード】標準待機時間")

    if resume_data:
        step_outputs  = resume_data.get("step_outputs", {})
        final_content = resume_data.get("final_content", "")
        log_history   = resume_data.get("log_history", [])

    for item in execution_list:
        filename = os.path.basename(item["path"])
        step_key = filename[:6]

        if resume_data and step_key in step_outputs:
            print(f"\n⏭️  {filename} はスキップ（再開データあり）")
            final_content = step_outputs.get(step_key, final_content)
            continue

        # ── pre_action: ステップ実行前の追加データ収集（もえちん専用）──
        pre_action = item.get("pre_action")
        if pre_action and not (resume_data and step_key in step_outputs):
            if pre_action == "bakusai":
                area = target_input.split()[0] if target_input else "対象地域"

                # ── 爆サイデータ収集方法を選択 ──
                bakusai_options = [
                    "自動取得（DuckDuckGo検索で爆サイデータを自動収集）",
                    "Chromeで爆サイ検索タブを一括オープン（3タブ自動で開きます）",
                    "手動のみ（従来通り自分で検索・コピペ）",
                ]
                # 自動取得が使えない場合は選択肢から除外
                if not HAS_DDGS:
                    bakusai_options.pop(0)
                bakusai_idx = arrow_menu(f"爆サイデータ収集方法（{area}）", bakusai_options, allow_back=False)
                # HAS_DDGSがFalseの場合はインデックスを+1して従来ロジックに合わせる
                if not HAS_DDGS:
                    bakusai_idx += 1

                bakusai_path = os.path.join(BASE_DIR, "bakusai_log.txt")

                if bakusai_idx == 0:
                    # ── 自動取得 ──
                    print(f"\n   🤖 爆サイデータを自動取得中（{area}）...")
                    auto_data = auto_fetch_bakusai_data(area)
                    if auto_data:
                        with open(bakusai_path, "w", encoding="utf-8") as f:
                            f.write(auto_data)
                        print(f"\n   ✅ 自動取得完了！ bakusai_log.txt に保存しました。")
                        print(f"   📄 内容を確認・編集しますか？")
                        review_options = ["このまま使用する（確認不要）", "メモ帳で確認・編集してから使用する"]
                        review_idx = arrow_menu("確認方法", review_options, allow_back=False)
                        if review_idx == 1:
                            item["_extra_context"] = get_file_content_with_notepad(
                                "bakusai_log.txt",
                                "【自動取得済み】内容を確認・追記してください。そのままでもOKです"
                            )
                        else:
                            item["_extra_context"] = auto_data
                    else:
                        print(f"   ⚠️ 自動取得に失敗しました。手動入力に切り替えます。")
                        bakusai_idx = 1  # Chromeタブオープンにフォールバック

                if bakusai_idx == 1:
                    # Chromeタブ一括オープン
                    search_queries = [
                        f"{area} メンエス 摘発 site:bakusai.com",
                        f"{area} メンエス 地雷 site:bakusai.com",
                        f"{area} メンエス 大当たり site:bakusai.com",
                    ]
                    print(f"\n   🌐 爆サイ検索タブを3つ開いています...")
                    for q in search_queries:
                        search_url = "https://www.google.com/search?" + urllib.parse.urlencode({"q": q})
                        webbrowser.open(search_url)
                        time.sleep(0.5)
                    print(f"   ✅ 検索タブを開きました。各タブの内容をメモ帳にコピペしてください。\n")

                if bakusai_idx >= 1 and "_extra_context" not in item:
                    # テンプレート生成（Chrome / 手動 共通）
                    bakusai_template = (
                        f"# 爆サイ口コミデータ（{area} メンエス）\n"
                        f"# ── 貼り付け方 ──────────────────────────────\n"
                        f"# 1. 下記3つのセクション見出しはそのまま残してください\n"
                        f"# 2. 各見出しの下に、爆サイの検索結果をそのままコピペするだけでOKです\n"
                        f"# 3. URLは貼っても貼らなくてもどちらでも構いません\n"
                        f"# 4. フォーマットや形式は一切不要。テキストをそのまま貼るだけ。\n"
                        f"# ───────────────────────────────────────────\n\n"
                        f"## ■ 摘発情報（{area} メンエス 摘発 site:bakusai.com）\n"
                        f"↓ここに上位10件の内容を順番に貼り付け↓\n\n\n\n\n"
                        f"## ■ 地雷情報（{area} メンエス 地雷 site:bakusai.com）\n"
                        f"↓ここに上位10件の内容を順番に貼り付け↓\n\n\n\n\n"
                        f"## ■ 大当たり情報（{area} メンエス 大当たり site:bakusai.com）\n"
                        f"↓ここに上位10件の内容を順番に貼り付け↓\n\n\n\n\n"
                    )
                    with open(bakusai_path, "w", encoding="utf-8") as f:
                        f.write(bakusai_template)

                    print(f"\n   ⚠️  【重要】メモ帳が開く前にポップアップが表示された場合：")
                    print(f"      「ファイルを再度開く」を選択してください。")
                    print(f"      （「変更内容を維持する」は古いキーワードのテンプレートになるため NG）\n")
                    item["_extra_context"] = get_file_content_with_notepad(
                        "bakusai_log.txt",
                        f"【Step2実行前】爆サイデータを貼り付けてください\n"
                        f"   Chromeタブが開いている場合: 各タブの内容をコピペ\n"
                        f"   各セクション見出しの下に、検索結果をそのままコピペするだけでOKです\n"
                        f"   ★ポップアップが出たら「ファイルを再度開く」を選択してください"
                    )
            elif pre_action == "shop_list":
                # ── step03出力から手動検索用リストを抽出してJSONテンプレート化 ──
                step03_out = step_outputs.get("step03", "")
                shop_queries = []
                if step03_out:
                    last_fence = step03_out.rfind("```")
                    if last_fence >= 0:
                        after_json = step03_out[last_fence + 3:].strip()
                        for line in after_json.splitlines():
                            line = line.strip()
                            if line and not line.startswith("#") and not line.startswith("-") and not line.startswith("---"):
                                shop_queries.append(line)

                area = target_input.split()[0] if target_input else ""

                if shop_queries:
                    print("\n" + "=" * 60)
                    print("  📋 【Step3出力】手動検索用リスト")
                    print("=" * 60)
                    for q in shop_queries:
                        print(f"  🔍 {q}")
                    print("=" * 60 + "\n")

                    # ── 検索方法を選択 ──
                    search_options = [
                        "自動取得（DuckDuckGo検索で公式URLを自動検索）",
                        "Chromeで全店舗を一括Google検索（タブが自動で開きます）",
                        "手動で検索する（自分でコピペして検索）",
                    ]
                    # 自動取得が使えない場合は選択肢から除外
                    if not HAS_DDGS:
                        search_options.pop(0)
                    search_idx = arrow_menu("店舗URL検索方法を選択", search_options, allow_back=False)
                    if not HAS_DDGS:
                        search_idx += 1

                    if search_idx == 0:
                        # ── 自動取得 ──
                        # shop_queriesから店名を抽出
                        shop_names = []
                        for q in shop_queries:
                            name = q.replace(f" {area} メンエス", "").replace(" メンエス", "").strip()
                            shop_names.append(name)

                        print(f"\n   🤖 {len(shop_names)} 店舗の公式URLを自動検索中...")
                        auto_verified = auto_resolve_shop_urls(shop_names, area)

                        if auto_verified:
                            found = sum(1 for v in auto_verified.values() if v != "URLなし")
                            print(f"\n   ✅ 自動取得完了！ {found}/{len(auto_verified)} 店舗のURLを発見")

                            # JSONテンプレート生成
                            shop_json = {"verifiedUrls": auto_verified}
                            shop_template = (
                                "# ── 自動取得済み ──────────────────────────────────\n"
                                '# URLが正しいか確認し、必要に応じて修正してください\n'
                                '# "URLなし" の店舗は手動で公式URLを探すか、そのままでOK\n'
                                '# 閉店・除外したい場合は "閉店" または "除外" と記入\n'
                                "# ──────────────────────────────────────────────\n\n"
                            )
                            shop_template += json.dumps(shop_json, ensure_ascii=False, indent=2)

                            shop_path = os.path.join(BASE_DIR, "shop_list.txt")
                            with open(shop_path, "w", encoding="utf-8") as f:
                                f.write(shop_template)

                            # URLなし の店舗だけ Google検索タブを自動で開く
                            missing_shops = [
                                k for k, v in auto_verified.items()
                                if v == "URLなし"
                            ]
                            if missing_shops:
                                print(f"\n   🌐 URL未取得 {len(missing_shops)} 店舗のGoogle検索タブを開きます...")
                                for shop_key in missing_shops:
                                    # "店名（エリア）" → "店名 エリア メンズエステ 公式" に変換
                                    shop_q = shop_key.replace("（", " ").replace("）", "") + " メンズエステ 公式"
                                    search_url = "https://www.google.com/search?" + urllib.parse.urlencode({"q": shop_q})
                                    webbrowser.open(search_url)
                                    time.sleep(0.5)
                                print(f"   ✅ {len(missing_shops)} タブを開きました。URLを確認してshop_list.txtに貼り付けてください。")

                            # 確認画面
                            # URLなし店舗のタブを開いた場合は自動でメモ帳へ（URLを貼り付けてもらう必要があるため）
                            if missing_shops:
                                item["_extra_context"] = get_file_content_with_notepad(
                                    "shop_list.txt",
                                    "【URLなし店舗あり】Google検索タブで確認したURLを貼り付けて上書き保存(Ctrl+S)してください"
                                )
                            else:
                                review_options = ["このまま使用する（確認不要）", "メモ帳で確認・編集してから使用する"]
                                review_idx = arrow_menu("確認方法", review_options, allow_back=False)
                                if review_idx == 1:
                                    item["_extra_context"] = get_file_content_with_notepad(
                                        "shop_list.txt",
                                        "【自動取得済み】URLが正しいか確認してください。そのままでもOKです"
                                    )
                                else:
                                    item["_extra_context"] = shop_template
                        else:
                            print("   ⚠️ 自動取得に失敗しました。Chrome検索に切り替えます。")
                            search_idx = 1  # フォールバック

                    if search_idx == 1:
                        # ── Chrome一括検索 ──
                        print(f"\n   🌐 {len(shop_queries)} 件の検索タブを開いています...")
                        for i, q in enumerate(shop_queries):
                            search_url = "https://www.google.com/search?" + urllib.parse.urlencode({"q": q})
                            webbrowser.open(search_url)
                            if i < len(shop_queries) - 1:
                                time.sleep(0.5)
                        print(f"   ✅ 全 {len(shop_queries)} タブを開きました。各タブで公式URLを確認してください。\n")
                    elif search_idx == 2:
                        # ── 手動 ──
                        print("\n   ↑ 上記クエリをそのままGoogleに貼り付けて検索してください\n")

                    if "_extra_context" not in item:
                        # Chrome/手動の場合: デフォルトの verified dict を生成
                        verified = {}
                        for q in shop_queries:
                            shop_key = q.replace(f" {area} メンエス", "").replace(" メンエス", "").strip()
                            shop_key_with_area = f"{shop_key}（{area}）"
                            verified[shop_key_with_area] = "URLなし"

                        shop_json = {"verifiedUrls": verified}
                        shop_template = (
                            "# ── 手順 ──────────────────────────────────────────\n"
                            '# 1. 公式サイトが見つかったら "URLなし" をURLに書き換える\n'
                            '# 2. 見つからない店舗は "URLなし" のままでOK（決して空欄にしない）\n'
                            '# 3. 閉店・除外したい場合は "閉店" または "除外" と記入\n'
                            "# ──────────────────────────────────────────────\n\n"
                        )
                        shop_template += json.dumps(shop_json, ensure_ascii=False, indent=2)

                        shop_path = os.path.join(BASE_DIR, "shop_list.txt")
                        with open(shop_path, "w", encoding="utf-8") as f:
                            f.write(shop_template)

                        print("   ⚠️  【重要】ポップアップが出たら「ファイルを再度開く」を選択してください。\n")
                        item["_extra_context"] = get_file_content_with_notepad(
                            "shop_list.txt",
                            "【Step4実行前】各店舗のURLを shop_list.txt に入力してください\n"
                            '   公式URLに書き換えてください。不明なら "URLなし" のままでOK（空欄は不可）\n'
                            "   ★ポップアップが出たら「ファイルを再度開く」を選択してください"
                        )
                else:
                    print("\n   ⚠️  step03出力から店舗リストを自動抽出できませんでした。")
                    print("   手動でJSONを編集してください。\n")
                    shop_template = (
                        "# 店名とURLを記入してください（URLなし/閉店/除外 も使用可）\n\n"
                        '{\n  "verifiedUrls": {\n'
                        '    "店名（地域名）": "URLなし"\n'
                        '  }\n}'
                    )

                    shop_path = os.path.join(BASE_DIR, "shop_list.txt")
                    with open(shop_path, "w", encoding="utf-8") as f:
                        f.write(shop_template)

                    print("   ⚠️  【重要】ポップアップが出たら「ファイルを再度開く」を選択してください。\n")
                    item["_extra_context"] = get_file_content_with_notepad(
                        "shop_list.txt",
                        "【Step4実行前】各店舗のURLを shop_list.txt に入力してください\n"
                        '   公式URLに書き換えてください。不明なら "URLなし" のままでOK（空欄は不可）\n'
                        "   ★ポップアップが出たら「ファイルを再度開く」を選択してください"
                    )

        prompt_text = _normalize_prompt_template_text(read_file(item["path"]))
        prompt_text += "\n\n" + _freshness_guard_prompt()
        addition_text = ""

        if item["type"] == "merged_addition":
            add_prompt = read_file(item["addition_path"])
            # 商標記事モード: スクロールCTAボックスのみ除外（アフィリエイトボタンは維持）
            if item.get("suppress_scroll_cta"):
                add_prompt = (
                    "【最重要・上書き指示（以下の全指示より最優先）】\n"
                    "■ スクロールCTAボックスに関する指示のみ無効化します：\n"
                    "  - スクロールCTAショートコード（[page_scode ...]）は記事内に一切挿入しないでください。\n"
                    "  - 「セット出力の鉄の掟」は無効です。ボタンだけの単独出力を許可します。\n"
                    "  - スクロールCTAボックス（program-selection-scroll-container）関連のHTML・CSSは生成不要です。\n"
                    "■ ただし以下は通常通り生成してください：\n"
                    "  - アフィリエイトリンクボタン（<div class=\"affiliate-button-container\">）は"
                    "指示通り3箇所（リード文直下・中間部・まとめ直後）に必ず配置すること。\n"
                    "  - ボタンの色・スタイルはCSS情報から抽出した色で統一すること。\n"
                    "この上書き指示は以下のすべての内容より優先されます。\n\n"
                ) + add_prompt
            if _has_embedded_h2_image_set(add_prompt):
                add_prompt, embedded_image_urls, embedded_mode = _focus_embedded_h2_images(
                    add_prompt, target_input, item.get("addition_path", "")
                )
                allowed_h2_image_urls.update(embedded_image_urls)
                if embedded_mode == "focused":
                    print(f"   📷 画像: 広い埋め込み画像セットから記事テーマ一致の {len(embedded_image_urls)}枚に絞り込み")
                elif embedded_mode == "empty":
                    print("   ℹ️ 画像: 足し算Prompt内の広い画像セットは記事テーマと合わないため使いません。登録済みの専用画像セットがあればそちらを使用します。")
                else:
                    print(f"   📷 画像: 足し算Prompt内の専用画像セット {len(embedded_image_urls)}枚を使用")

            # h2_images.json から、選択中の足し算Promptに紐づく画像だけを読み込む
            h2_images_path = os.path.join(PROMPT_BASE_DIR, "📂 00_additions （足し算指示専用）", "h2_images.json")
            if os.path.exists(h2_images_path) and not _has_embedded_h2_image_set(add_prompt):
                try:
                    with open(h2_images_path, "r", encoding="utf-8") as img_f:
                        h2_data = json.load(img_f)
                    img_list = h2_data.get("images", [])
                    if img_list:
                        _img_site = selected_site.get("name", "") if selected_site else ""
                        selected_images, image_mode = _select_h2_images_for_addition(
                            img_list, _img_site, item.get("addition_path", "")
                        )
                        if selected_images:
                            print(f"   📷 画像: {os.path.basename(item.get('addition_path', ''))}専用画像 {len(selected_images)}枚を使用")
                        else:
                            print("   ℹ️ 足し算Prompt専用のH2画像セットが未登録です。サイト全体画像の混入を避けるため自動注入は行いません。")
                        img_json = json.dumps(selected_images, ensure_ascii=False, indent=2)
                        allowed_h2_image_urls.update(_extract_image_urls_from_text(img_json))
                        # 既存の {{H2見出し用_汎用画像リスト}} プレースホルダーを置換
                        if "{{H2見出し用_汎用画像リスト}}" in add_prompt:
                            add_prompt = add_prompt.replace("{{H2見出し用_汎用画像リスト}}", img_json)
                        elif selected_images:
                            # プレースホルダーがない場合（古い足し算Prompt）は末尾に追加
                            add_prompt += f"\n\n【H2見出し用_汎用画像リスト（自動注入・{len(selected_images)}枚）】\n{img_json}"
                except Exception as e:
                    print(f"   ⚠️ h2_images.json読み込みエラー: {e}（画像注入スキップ）")
            addition_text = f"\n\n【特殊プロット・追加データ】\n{add_prompt}"
            prompt_text += f"\n\n上記修正に加えて、以下の【特殊プロット】の内容も完全に反映して【最終版のHTML】を出力してください。{addition_text}"

        if "step01" in filename:
            prompt_text = initial_instruction + "\n\n" + prompt_text
        elif "step08" in filename:
            # step08（引き算処理）: step06の最終HTML出力のみを渡す
            if "step06" in step_outputs:
                prompt_text += f"\n\n【〈step06の出力結果（修正対象のHTML）〉】\n{step_outputs['step06']}"
        elif any(x in filename for x in ["step02", "step03", "step04", "step05", "step06"]):
            for prev in ["step01", "step02", "step03", "step04", "step05"]:
                if prev in step_outputs:
                    prompt_text += f"\n\n【〈{prev}の出力結果〉】\n{step_outputs[prev]}"

        # ── pre_actionで収集した追加コンテキストをプロンプトに追加 ──
        extra_ctx = item.get("_extra_context", "")
        if extra_ctx.strip():
            if "step02" in filename:
                prompt_text += f"\n\n【口コミ掲示板データ（爆サイ等）】\n{extra_ctx}"
            elif "step04" in filename:
                prompt_text += f"\n\n【店舗URLリスト】\n{extra_ctx}"

        if any(x in filename for x in ["step06", "step08"]):
            prompt_text += """

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 【緊急システム命令】記事全文の完全出力
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ 以下を最優先で実行してください。
❌ 禁止: 修正箇所だけの部分出力
❌ 禁止: H1タイトルや導入文の省略
❌ 禁止: 記事途中からの出力開始
✅ 必須: <h1>から最後のセクションまで全文出力
✅ 必須: H1直後に必ず40文字以上の導入文を配置
✅ 必須: 前工程の本文量・H2/H3構成・主要な段落を維持し、要約や短縮をしない
✅ 必須: <strong>、<b>、<em>、<a> などの装飾タグは、必ず同じ段落・セル・見出し内で閉じる
"""
            if "step06" in filename and _parent_expected_table(step_outputs):
                tables_text = _build_parent_table_preservation_payload(step_outputs)
                prompt_text += f"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 【表保持の絶対条件】
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
前工程の本文には、記事本文用の比較表・一覧表が含まれています。
以下の表データを、完成版HTML内の関連するH2セクションに必ず `<table>` として残してください。
表を削除・要約・箇条書き化・文章化してはいけません。
品質チェック用の評価表ではなく、読者に見せる記事本文の表だけを残してください。

【必ず保持する記事本文用の表データ】
{tables_text}
"""

        if any(x in filename for x in ["step04", "step05", "step06", "step08"]):
            prompt_text += "\n# 【システム強制介入1】FAQ: <h3><strong>Q. 質問</strong></h3><p>A. 回答</p> 形式厳守\n# 【システム強制介入2】比較表: 最大4列まで。セル内は簡潔にするが、表そのものは省略せず、必要な比較項目を保持する"

        print(f"\n▶ {filename} を実行中...")
        try:
            _load_genai()
            client = genai.Client(api_key=target_api_key)
            chat = client.chats.create(model=model, config=GEN_CONFIG)
            retry_prompt = prompt_text
            response = _send_message_with_retry(chat, retry_prompt, f"{filename}")

            if response.candidates and response.candidates[0].finish_reason not in [
                types.FinishReason.STOP, types.FinishReason.MAX_TOKENS
            ]:
                print(f"   ❌ 生成中断: {response.candidates[0].finish_reason}")
                _save_interrupted_resume(f"生成中断: {response.candidates[0].finish_reason}", filename)
                return False, final_content, log_history, step_outputs

            part_content = ""
            for quality_retry in range(3):
                part_content = response.text or ""
                if not part_content or len(part_content.strip()) < 10:
                    bad, reason = True, "生成結果が空です"
                else:
                    cnt = 0
                    while response.candidates and response.candidates[0].finish_reason == types.FinishReason.MAX_TOKENS and cnt < 5:
                        print(f"   ⚠️ 長文のため続きを取得 ({sleep_continue}秒待機)...")
                        time.sleep(sleep_continue)
                        response = _send_message_with_retry(chat, "続きをそのまま出力してください", f"{filename} の続き")
                        if response.text: part_content += response.text
                        cnt += 1
                    bad, reason = _is_bad_parent_step_output(filename, part_content)
                    if not bad and "step06" in filename and _parent_expected_table(step_outputs):
                        checked_html = force_cleanup_html_parent(part_content)
                        if "<table" not in checked_html.lower():
                            protected_html = _insert_missing_parent_tables(checked_html, step_outputs)
                            protected_html = force_cleanup_html_parent(protected_html)
                            if "<table" in protected_html.lower():
                                part_content = protected_html
                                print("   ℹ️ 表保護: Step04で生成済みの本文用HTML表を保持して最終HTMLへ戻しました。")
                            else:
                                bad, reason = True, "本文用HTML表の保護復元に失敗しました"
                    if not bad and "step06" in filename:
                        checked_html = force_cleanup_html_parent(part_content)
                        too_short, short_reason = _is_parent_step06_too_short(step_outputs, checked_html)
                        if too_short:
                            bad, reason = True, short_reason

                if not bad:
                    break
                if quality_retry >= 2 or ("step06" in filename and "表" in reason and quality_retry >= 1):
                    if "step06" in filename and "表" in reason:
                        print(f"   ⚠️ {filename} の本文用HTML表を保護できませんでした。API消費を抑えるため再生成を止め、最終チェックで検証します。")
                        break
                    print(f"   ❌ {filename} の出力異常: {reason}")
                    _save_interrupted_resume(f"{filename} の出力異常: {reason}", filename)
                    return False, final_content, log_history, step_outputs
                print(f"   ⚠️ {filename} の出力異常: {reason}。{sleep_continue}秒後に再生成します...")
                time.sleep(sleep_continue)
                chat = client.chats.create(model=model, config=GEN_CONFIG)
                if "step06" in filename and "表" in reason:
                    retry_prompt = _build_table_preservation_retry_prompt(prompt_text, step_outputs)
                elif "step06" in filename and "本文量" in reason:
                    retry_prompt = prompt_text + """

# 【再生成時の最重要追加指示：本文量維持】
直前の出力では、前工程の本文量に対して最終HTMLが大きく短くなっていました。
この出力では、Step04で作成済みの本文の情報量・H2/H3構成・主要段落を削らず、要約せず、完成版HTMLとして全文を維持してください。
文章を整えることは許可しますが、見出しや説明段落を減らすことは禁止です。
"""
                response = _send_message_with_retry(chat, retry_prompt, f"{filename} 再生成")

            if any(x in filename for x in ["step06", "step08"]):
                print("🔍 [導入文チェック]")
                if not check_introduction_in_html(part_content):
                    print("   ⚠️ 導入文チェック問題あり（処理続行）")

            final_content = part_content
            step_outputs[step_key] = final_content
            log_history.append({"role": f"User ({filename})", "text": prompt_text})
            log_history.append({"role": "Model", "text": final_content})
            save_resume_data(resume_file, target_input, initial_instruction, step_outputs, final_content, log_history, metadata=resume_metadata)
            print(f"   ✅ 完了。待機中({sleep_step}秒)...")
            time.sleep(sleep_step)

        except Exception as e:
            err_msg = str(e)
            print(f"\n   ❌ エラー: {err_msg}")
            if "429" in err_msg or "quota" in err_msg.lower():
                print("   ⏳ API制限。時間を置いて再試行してください。")
            if "step05" in filename and _is_transient_gemini_error(err_msg) and "step04" in step_outputs:
                print("   ⚠️ Step05品質チェックがGemini混雑で失敗しました。Step04本文は生成済みのため、ローカル簡易レビューで代替してStep06へ進みます。")
                final_content = _build_step05_fallback_review(step_outputs.get("step04", ""))
                step_outputs[step_key] = final_content
                log_history.append({"role": f"User ({filename})", "text": prompt_text})
                log_history.append({"role": "Model", "text": final_content})
                save_resume_data(resume_file, target_input, initial_instruction, step_outputs, final_content, log_history, metadata=resume_metadata)
                continue
            _save_interrupted_resume(err_msg, filename)
            return False, final_content, log_history, step_outputs

    try:
        inline_before = _inline_tag_balance_report(final_content)
        final_content = force_cleanup_html_parent(final_content)
        inline_after = _inline_tag_balance_report(final_content)
        if inline_before and not inline_after:
            fixed = "、".join(f"{tag}: 開始{v[0]} / 終了{v[1]}" for tag, v in inline_before.items())
            print(f"   ℹ️ HTML整形: 装飾タグの閉じ忘れを補正しました（{fixed}）。")
        elif inline_after:
            remaining = "、".join(f"{tag}: 開始{v[0]} / 終了{v[1]}" for tag, v in inline_after.items())
            print(f"   ❌ HTML整形後も装飾タグの開閉が不一致です（{remaining}）。")
            _save_interrupted_resume(f"HTML整形後も装飾タグの開閉が不一致です（{remaining}）", "final_cleanup")
            return False, final_content, log_history, step_outputs
        block_nesting_after = _block_tag_paragraph_nesting_report(final_content)
        if block_nesting_after:
            print(f"   ❌ HTML整形後も段落内に見出し/表/リストタグが入り込んでいます（{', '.join(block_nesting_after[:5])}）。")
            print("   ❌ WordPressで本文構造が崩れるため、投稿を止めます。別APIキーまたは再実行で作り直してください。")
            _save_interrupted_resume("HTML整形後も段落内に見出し/表/リストタグが入り込んでいます", "final_cleanup")
            return False, final_content, log_history, step_outputs
        if _parent_expected_table(step_outputs) and "<table" not in final_content.lower():
            print("   ℹ️ 表保護: Step04で生成済みの本文用HTML表を保持して最終HTMLへ戻します。")
            final_content = _insert_missing_parent_tables(final_content, step_outputs)
            final_content = force_cleanup_html_parent(final_content)
        too_short, short_reason = _is_parent_step06_too_short(step_outputs, final_content)
        if too_short:
            print(f"   ❌ {short_reason}")
            print("   ❌ 本文量が大きく落ちているため、投稿を止めます。別APIキーまたは再実行で作り直してください。")
            print_article_output_summary(final_content, "最終出力チェック")
            _save_interrupted_resume(short_reason, "final_cleanup")
            return False, final_content, log_history, step_outputs
        # 著者・監修者テキストをPublishPressショートコードに自動置換
        site_name = selected_site.get("name", "") if selected_site else ""
        if site_name:
            final_content = replace_author_block_with_shortcodes(final_content, site_name)
        if allowed_h2_image_urls:
            final_content, removed_images = _remove_disallowed_h2_images(final_content, allowed_h2_image_urls)
            if removed_images:
                print(f"   ⚠️ 許可外のH2直下画像を{len(removed_images)}件削除しました。")
                for url in removed_images[:5]:
                    print(f"      - {url}")
        final_content, unlinked_ref_count = _strip_low_authority_reference_links(final_content)
        if unlinked_ref_count:
            print(f"   ℹ️ 参考文献リスト: 公的・準公的情報源以外の外部リンクを{unlinked_ref_count}件解除しました（出典名は残します）。")
        final_content, unlinked_cite_count = _strip_low_authority_citation_links(final_content)
        if unlinked_cite_count:
            print(f"   ℹ️ 引用・出典ブロック: 公的・準公的情報源以外の外部リンクを{unlinked_cite_count}件解除しました（出典名は残します）。")
        if log_history:
            log_history[-1]["text"] = final_content
        if not _is_valid_parent_html(final_content):
            print("   ❌ 最終出力がHTML記事として不完全です。Markdown混入または<h1>/<h2>不足を検出しました。")
            print_article_output_summary(final_content, "最終出力チェック")
            _save_interrupted_resume("最終出力がHTML記事として不完全です", "final_cleanup")
            return False, final_content, log_history, step_outputs
        if _parent_expected_table(step_outputs) and "<table" not in final_content.lower():
            print("   ❌ 最終出力に表がありません。前工程には比較表・表データがあるため、表落ちとして処理を中止します。")
            print_article_output_summary(final_content, "最終出力チェック")
            _save_interrupted_resume("最終出力に表がありません", "final_cleanup")
            return False, final_content, log_history, step_outputs
    except Exception as e:
        print(f"   ❌ 最終後処理でエラー: {e}")
        _save_interrupted_resume(str(e), "final_cleanup")
        return False, final_content, log_history, step_outputs
    save_resume_data(
        resume_file,
        target_input,
        initial_instruction,
        step_outputs,
        final_content,
        log_history,
        metadata=_resume_meta_with_status("completed"),
    )
    return True, final_content, log_history, step_outputs


# ============================================================
# 子記事用ユーティリティ
# ============================================================
def save_log_child(title, conversation_history):
    os.makedirs(CHILD_LOGS, exist_ok=True)
    safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '_', '-')).strip()
    filename = f"log_CHILD_{safe_title}_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    filepath = os.path.join(CHILD_LOGS, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"Mode: 子記事\nTitle: {title}\n{'='*50}\n\n")
        for entry in conversation_history:
            f.write(f"--- {entry['role']} ---\n{entry['text']}\n\n")
    print(f"📄 ログ保存: {filename}")

def validate_article_completeness(content, min_h2_count=3, check_name="記事"):
    checks = {
        "has_h1":            '<h1>' in content[:500],
        "has_author":        '<blockquote>' in content[:1500],
        "has_lead_paragraphs": len(re.findall(r'<p>.*?</p>', content[:2000], re.DOTALL)) >= 2,
        "h2_count":          len(re.findall(r'<h2[^>]*>', content)) >= min_h2_count,
        "min_length":        len(content) >= 3000,
        "has_faq_or_qa":     'Q.' in content or 'Q:' in content or 'FAQ' in content,
    }
    is_valid = (
        checks["has_lead_paragraphs"] and
        checks["h2_count"] and
        checks["min_length"] and
        checks["has_faq_or_qa"]
    )
    if not is_valid:
        print(f"   ⚠️ {check_name}の検証失敗:")
        for key, value in checks.items():
            print(f"      {'✅' if value else '❌'} {key}")
    return is_valid, checks


def check_keyword_density(html_content, keyword):
    """記事内のキーワード密度をチェックし、過剰な場合に警告を表示する。
    引継書（KWツール→記事生成ツール）提案1: キーワード飽和/スタッフィング自動チェック。
    """
    # HTMLタグを除去してプレーンテキストを取得
    text_all = re.sub(r'<[^>]+>', ' ', html_content)
    text_all = re.sub(r'\s+', '', text_all)  # 空白除去（日本語文字数ベース）
    if not text_all or not keyword:
        return
    total_chars = len(text_all)
    kw_len = len(keyword)
    if kw_len == 0 or total_chars == 0:
        return
    # 全体でのKW出現回数
    count_all = text_all.count(keyword)
    density_all = (count_all * kw_len) / total_chars * 100
    # 見出し(h1-h6)を除外した本文のみ
    text_no_headings = re.sub(r'<h[1-6][^>]*>.*?</h[1-6]>', '', html_content, flags=re.DOTALL)
    text_no_headings = re.sub(r'<[^>]+>', ' ', text_no_headings)
    text_no_headings = re.sub(r'\s+', '', text_no_headings)
    count_body = text_no_headings.count(keyword)
    body_chars = len(text_no_headings)
    density_body = (count_body * kw_len) / body_chars * 100 if body_chars > 0 else 0
    # 結果表示
    print(f"\n📊 KW密度チェック: 「{keyword}」")
    print(f"   全体: {count_all}回 / {total_chars}文字 → {density_all:.1f}%")
    print(f"   本文のみ（見出し除外）: {count_body}回 / {body_chars}文字 → {density_body:.1f}%")
    if density_all >= 3.0:
        print(f"   🚨 危険: KW密度が高すぎます（3%以上）。スタッフィングと判定されるリスクがあります。")
    elif density_all >= 2.0:
        print(f"   ⚠️ 注意: KW密度がやや高めです（2-3%）。自然な表現への修正を検討してください。")
    else:
        print(f"   ✅ 健全な密度です（2%未満）。")


def force_cleanup_html_child(html_text):
    """子記事用HTMLクリーンアップ（旧auto_post_child_normal.pyのforce_cleanup_html）"""
    print("\n🧹 [Python自動クリーンアップ] 実行中...")
    if not html_text:
        print("   ⚠️ 入力が空です")
        return ""

    # div.image-description内の誤配置画像を抽出・再配置
    html_text = _extract_images_from_divs(html_text)

    # HTMLコメント削除
    html_text = re.sub(r'<!--.*?-->', '', html_text, flags=re.DOTALL)
    html_text = html_text.replace('<!--', '')  # 閉じられていない <!-- も除去

    # HTMLドキュメント構造削除
    match_body = re.search(r'<body[^>]*>(.*?)</body>', html_text, re.IGNORECASE | re.DOTALL)
    if match_body: html_text = match_body.group(1)
    html_text = re.sub(r'<!DOCTYPE[^>]*>', '', html_text, flags=re.IGNORECASE)
    html_text = re.sub(r'<html[^>]*>', '', html_text, flags=re.IGNORECASE)
    html_text = re.sub(r'</html>', '', html_text, flags=re.IGNORECASE)
    html_text = re.sub(r'<head[\s>].*?</head>', '', html_text, flags=re.IGNORECASE | re.DOTALL)
    html_text = re.sub(r'^\s*<div[^>]*class\s*=\s*["\']?container["\']?[^>]*>\s*', '', html_text, flags=re.IGNORECASE)
    html_text = re.sub(r'\s*</div>\s*$', '', html_text, flags=re.IGNORECASE)

    # Markdownコードブロック削除
    pattern = r'```(?:html)?\s*(.*?)\s*```'
    match = re.search(pattern, html_text, re.DOTALL | re.IGNORECASE)
    if match:
        html_text = match.group(1)
    else:
        html_text = re.sub(r'```(?:html)?\s*', '', html_text, flags=re.IGNORECASE)
        html_text = re.sub(r'```\s*$', '', html_text)

    # AI思考プロセス削除
    for pat in [r'^\s*\*\s*\*Wait.*$', r'^\s*\*\s*\*Final check.*$', r'^\s*\*\s*\*One last check.*$', r'^\s*\*\s*\*Checking.*$']:
        html_text = re.sub(pat, '', html_text, flags=re.MULTILINE | re.IGNORECASE)

    # デザイナー向け指示書削除
    html_text = re.sub(
        r'<(p|div|blockquote)[^>]*>(?:(?!<(?:p|div|blockquote)[ >])[\s\S])*?(?:デザイナー向け指示書|インフォグラフィック|図解指示|画像挿入|※\s*デザイン\s*：|※\s*イメージ\s*：|参考altテキスト)[\s\S]*?<\/\1>',
        '', html_text, flags=re.IGNORECASE)
    html_text = re.sub(
        r'\[(?:デザイナー向け指示書|インフォグラフィック|図解指示|画像挿入|※\s*デザイン\s*：|※\s*イメージ\s*：).*?\]',
        '', html_text, flags=re.IGNORECASE)
    html_text = re.sub(r'^\s*※\s*(?:デザイン|イメージ)\s*：.*$', '', html_text, flags=re.MULTILINE | re.IGNORECASE)

    # 注釈記号削除
    html_text = re.sub(r'\[\d+\]', '', html_text)
    html_text = re.sub(r'\[\[\d+\]\([^)]+\)\]', '', html_text)
    html_text = re.sub(r'\s+\d+(?=[。、，．])', '', html_text)

    # ダミー人名削除
    surnames = '(?:山田|田中|佐藤|鈴木|高橋|伊藤|渡辺|中村|小林|加藤|吉田|ケンジ)'
    given_names = '(?:健太|太郎|花子|美咲|翔太|優子|大輔|真理子|和也|愛|健一|恵|直樹|綾|拓海|麻衣|隆|由美|武|絵理|哲也|沙織|雅之|奈々|浩二|理恵|慎一|明美|秀樹|裕子)'
    honorifics = '(?:さん|様|氏)'
    html_text = re.sub(f'{surnames}{given_names}{honorifics}(?:[、，\\s]*)', '', html_text)
    html_text = re.sub(f'{surnames}{honorifics}(?:[、，\\s]*)', '', html_text)
    html_text = re.sub(r'[―]', '', html_text)

    # まとめ見出しからCTA文言を除去（「まとめ & 公式サイトで詳細を見る」→「まとめ」）
    html_text = re.sub(
        r'(<h2[^>]*>)\s*まとめ\s*[&＆].*?(</h2>)',
        r'\1まとめ\2',
        html_text,
        flags=re.IGNORECASE
    )

    # 参考文献の未使用URL削除
    parts = re.split(r'(<h[23][^>]*>.*?参考文献.*?</h[23]>|\[参考文献リスト\])', html_text, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) == 3:
        body_text, heading, ref_text = parts
        used_urls = set(re.findall(r'href="(http[^"]+)"', body_text))
        def filter_ref(match):
            li_html = match.group(0)
            # プロンプト指示文由来のダミー参考文献を除去
            dummy_patterns = [
                r'著作権法第?\d*条',
                r'Google検索品質評価ガイドライン',
                r'ここに記載されます',
                r'信頼できる情報源が.*記載',
                r'学術論文.*記載',
            ]
            for pat in dummy_patterns:
                if re.search(pat, li_html):
                    return ""
            li_urls = re.findall(r'href="(http[^"]+)"', li_html)
            if not li_urls: return li_html
            for u in li_urls:
                if u in used_urls: return li_html
            return ""
        ref_text = re.sub(r'<li>.*?</li>', filter_ref, ref_text, flags=re.DOTALL)
        html_text = body_text + heading + ref_text

    html_text, unlinked_ref_count = _strip_low_authority_reference_links(html_text)
    if unlinked_ref_count:
        print(f"   ℹ️ 参考文献リスト: 公的・準公的情報源以外の外部リンクを{unlinked_ref_count}件解除しました（出典名は残します）。")
    html_text, unlinked_cite_count = _strip_low_authority_citation_links(html_text)
    if unlinked_cite_count:
        print(f"   ℹ️ 引用・出典ブロック: 公的・準公的情報源以外の外部リンクを{unlinked_cite_count}件解除しました（出典名は残します）。")

    html_text = _repair_nested_heading_tags(html_text)
    html_text = re.sub(r'\n{3,}', '\n\n', html_text)
    html_text = _repair_inline_tag_leaks(html_text)
    print("   ✅ クリーンアップ完了（API消費ゼロ）")
    return html_text.strip()

def run_step00_keyword(api_key, topic, prompt_path):
    step00_file = os.path.join(prompt_path, "step00_keyword.txt")
    if not os.path.exists(step00_file):
        return topic
    step00_prompt = read_file(step00_file)
    if not step00_prompt:
        return topic
    print(f"\n▶ Step 00: キーワード生成中...")
    try:
        _load_genai()
        client = genai.Client(api_key=api_key)
        chat = client.chats.create(model=MODEL_CHILD, config=GEN_CONFIG)
        response = _send_message_with_retry(chat, f"【トピック案】\n{topic}\n\n{step00_prompt}", "子記事Step00キーワード生成")
        keyword = response.text.strip()
        print(f"   ✅ キーワード: {keyword}")
        return keyword
    except Exception as e:
        print(f"   ❌ エラー: {e}。トピックをそのまま使用します。")
        return topic

def run_article_generation_child(target_api_key, execution_list, keyword, is_moechin=False, selected_site=None):
    """子記事生成（モード3/4共通）"""
    log_history  = []
    step_outputs = {}
    final_content = ""

    is_paid = (API_KEY_PAID is not None and target_api_key == API_KEY_PAID)
    sleep_continue, sleep_step, sleep_error = (3, 5, 10) if is_paid else (15, 35, 30)

    if is_paid:
        print(f"\n🚀 【有料枠モード】待機時間短縮")
    else:
        print(f"\n🐢 【無料枠モード】標準待機時間")
    print(f"🤖 使用モデル: {MODEL_CHILD}（子記事）")

    for item in execution_list:
        filename = os.path.basename(item["path"])
        step_key = filename[:6]
        prompt_text = _normalize_prompt_template_text(read_file(item["path"]))
        prompt_text += "\n\n" + _freshness_guard_prompt()
        build_prompt = ""

        # PublishPress ショートコードIDをサイトに応じて置換（高速版プロンプトのデフォルトは774/775）
        site_name = selected_site.get("name", "") if selected_site else ""
        ppma_ids = PPMA_LAYOUT_MAP.get(site_name, {})
        if ppma_ids.get("single"):
            # author/reviewer区別なしのサイト → 2行のショートコードを1行に置換
            single_sc = f'[publishpress_authors_box layout="ppma_boxes_{ppma_ids["single"]}"]'
            prompt_text = re.sub(
                r'\[publishpress_authors_box\s+author_categories="author"[^\]]*\]\s*\n*'
                r'\[publishpress_authors_box\s+author_categories="reviewer"[^\]]*\]',
                single_sc,
                prompt_text
            )
        else:
            if ppma_ids.get("author") and ppma_ids["author"] != "774":
                prompt_text = prompt_text.replace("ppma_boxes_774", f"ppma_boxes_{ppma_ids['author']}")
            if ppma_ids.get("reviewer") and ppma_ids["reviewer"] != "775":
                prompt_text = prompt_text.replace("ppma_boxes_775", f"ppma_boxes_{ppma_ids['reviewer']}")

        # --- 前ステップの出力が空なら即停止（時間の無駄を防ぐ） ---
        required_prev = {}  # filename pattern → required step_outputs keys
        if "step02_write" in filename:
            required_prev = {"step01": "Step1（構成案）"}
        elif "step03_review" in filename:
            required_prev = {"step02": "Step2（本文）"}
        elif "step02" in filename and "step02_write" not in filename:
            required_prev = {"step01": "Step1（ペルソナ）"}
        elif "step03" in filename and "step03_review" not in filename:
            required_prev = {"step01": "Step1", "step02": "Step2"}
        elif "step04" in filename:
            required_prev = {"step01": "Step1", "step02": "Step2", "step03": "Step3（構成案）"}
        elif "step05" in filename:
            required_prev = {"step04": "Step4（初稿）"}
        elif "step06" in filename:
            required_prev = {"step04": "Step4（初稿）", "step05": "Step5（品質チェック）"}

        missing_steps = []
        for key, label in required_prev.items():
            prev_output = step_outputs.get(key, "")
            if not prev_output or len(prev_output.strip()) < 10:
                missing_steps.append(label)
        if missing_steps:
            missing_str = "、".join(missing_steps)
            print(f"\n▶ {filename} をスキップ")
            print(f"   ❌ 前ステップの出力が空のため実行不可: {missing_str}")
            print(f"   💡 原因: APIの過負荷、またはコンテンツフィルターによるブロックの可能性があります。")
            print(f"   💡 対策: 時間を空けて再実行してください。")
            return False, final_content, log_history

        # --- 高速版（child_fast）の3ステップ分岐 ---
        if "step01_plan" in filename:
            build_prompt = f"【前提情報】\nキーワード: {keyword}\n\n{prompt_text}"
        elif "step02_write" in filename:
            today_str = datetime.datetime.now().strftime("%Y年%m月%d日")
            build_prompt = f"【構成案JSON】\n{step_outputs.get('step01', '')}\n\n今日の日付: {today_str}\n\n{prompt_text}"
        elif "step03_review" in filename:
            build_prompt = f"【記事HTML】\n{step_outputs.get('step02', '')}\n\n{prompt_text}"
            build_prompt += """

# ═══════════════════════════════════════════════════════════
# 【絶対厳守】記事全文の完全出力
# ═══════════════════════════════════════════════════════════
## 【ルール1】全文を省略せずに出力すること
## 【ルール2】完全なHTMLタグで出力すること（Markdown禁止）
## 【ルール3】構文エラーを起こさないこと
## 【ルール4】作業メモや思考過程を出力しないこと
"""
        # --- 標準版の6ステップ分岐 ---
        elif "step01" in filename:
            build_prompt = f"【前提情報】\nキーワード: {keyword}\n\n{prompt_text}"
        elif "step02" in filename:
            build_prompt = f"【Step1の出力結果】\n{step_outputs.get('step01', '')}\n\n{prompt_text}"
        elif "step03" in filename:
            guide = "\n【重要ガイド】シミュレーション表は2-3個まで、各H3は3-5段落とし、1,500-2,000行程度に収めてください。"
            build_prompt = f"【Step1出力】\n{step_outputs.get('step01', '')}\n\n【Step2出力】\n{step_outputs.get('step02', '')}\n{guide}\n\n{prompt_text}"
        elif "step04" in filename:
            build_prompt = f"【Step1出力】\n{step_outputs.get('step01', '')}\n\n【Step2出力】\n{step_outputs.get('step02', '')}\n\n【Step3出力】\n{step_outputs.get('step03', '')}\n\n{prompt_text}"
        elif "step05" in filename:
            # step05は品質チェックのみ → Step4出力だけ渡す（Step1〜3はコンテキスト肥大の原因になるため除外）
            build_prompt = f"【Step4初稿】\n{step_outputs.get('step04', '')}\n\n{prompt_text}"
        elif "step06" in filename:
            build_prompt = f"【修正指示】\n{step_outputs.get('step05', '')}\n\n【初稿全文】\n{step_outputs.get('step04', '')}\n\n{prompt_text}"

        if "step06" in filename:
            build_prompt += """

# ═══════════════════════════════════════════════════════════
# 【絶対厳守】記事全文の完全出力
# ═══════════════════════════════════════════════════════════
## 【ルール1】全文を省略せずに出力すること
## 【ルール2】完全なHTMLタグで出力すること（Markdown禁止）
## 【ルール3】構文エラーを起こさないこと
## 【ルール4】作業メモや思考過程を出力しないこと
"""

        if any(x in filename for x in ["step04", "step05", "step06", "step02_write", "step03_review"]):
            build_prompt += "\n\n# 【システム強制介入】\n1. FAQは <h3><strong>Q. 質問</strong></h3><p>A. 回答</p> 形式厳守\n2. 表は最大4列まで、文字数を極限まで減らす"

        print(f"\n▶ {filename} を実行中...")
        _load_genai()
        client = genai.Client(api_key=target_api_key)
        step_success = False
        retry_count = 0

        while True:
            try:
                chat = client.chats.create(model=MODEL_CHILD, config=GEN_CONFIG)
                response = _send_message_with_retry(chat, build_prompt, f"{filename}")

                if response.candidates and response.candidates[0].finish_reason not in [
                    types.FinishReason.STOP, types.FinishReason.MAX_TOKENS
                ]:
                    print(f"   ❌ 生成中断: {response.candidates[0].finish_reason}")
                    return False, final_content, log_history

                part_content = response.text
                if not part_content or len(part_content.strip()) < 10:
                    retry_count += 1
                    if retry_count <= 2:
                        print(f"   ⚠️ 生成結果が空です（{retry_count}回目）。{sleep_error}秒後にリトライします...")
                        time.sleep(sleep_error)
                        continue
                    print(f"   ❌ 生成結果が空です（リトライ上限）。")
                    return False, final_content, log_history

                cnt = 0
                while response.candidates and response.candidates[0].finish_reason == types.FinishReason.MAX_TOKENS and cnt < 5:
                    print(f"   ⚠️ 長文のため続きを取得 ({sleep_continue}秒待機)...")
                    time.sleep(sleep_continue)
                    response = _send_message_with_retry(chat, "続きをそのまま出力してください", f"{filename} の続き")
                    if response.text: part_content += response.text
                    cnt += 1

                final_content = part_content
                step_outputs[step_key] = final_content
                log_history.append({"role": f"User ({filename})", "text": build_prompt})
                log_history.append({"role": "Model", "text": final_content})

                # 高速版: step03_review_fix 後も清書を実行（標準版step06と同等の処理）
                if "step03_review" in filename:
                    print(f"   🔍 高速版Step3（品質チェック+修正）出力を検証中...")
                    step3_content = final_content
                    is_valid, _ = validate_article_completeness(step3_content, min_h2_count=3, check_name="高速版Step3出力")
                    if not is_valid:
                        print(f"   ❌ CRITICAL ERROR: 高速版Step3出力が不完全。処理を中止します。")
                        return False, final_content, log_history
                    print(f"   ✅ 高速版Step3出力: 合格")

                    # 清書
                    print(f"   📝 全文清書を実行中...")
                    time.sleep(3)
                    rewrite_prompt = """上記の修正内容を完全に反映した上で、記事の【完全版】を出力してください。

【絶対厳守】
- リード文から参考文献リストまで全文を省略せずに出力すること
- すべてのH2セクションを含めること
- 完全なHTMLタグを使用すること（Markdown記法は禁止）
- 「🎨 デザイナー向け指示書」「インフォグラフィック」「図解指示」を含む段落は除外すること

今すぐ、読者向けの記事本文のみを、最初から最後まで出力してください。"""
                    try:
                        rw_chat = client.chats.create(model=MODEL_CHILD, config=GEN_CONFIG)
                        rw_resp = _send_message_with_retry(
                            rw_chat,
                            f"【元記事（以下を修正・清書してください）】\n{step3_content}\n\n{rewrite_prompt}"
                            ,
                            "高速版Step3清書"
                        )
                        if rw_resp.text:
                            rw_content = rw_resp.text
                            cnt2 = 0
                            while rw_resp.candidates and rw_resp.candidates[0].finish_reason == types.FinishReason.MAX_TOKENS and cnt2 < 5:
                                time.sleep(sleep_continue)
                                rw_resp = _send_message_with_retry(rw_chat, "続きをそのまま出力してください", "高速版Step3清書の続き")
                                if rw_resp.text: rw_content += rw_resp.text
                                cnt2 += 1
                            is_valid2, _ = validate_article_completeness(rw_content, min_h2_count=3, check_name="高速版清書結果")
                            if is_valid2:
                                final_content = rw_content
                                step_outputs[step_key] = final_content
                                log_history.append({"role": "User (清書指示)", "text": rewrite_prompt})
                                log_history.append({"role": "Model (清書結果)", "text": final_content})
                                print(f"   ✅ 全文清書完了")
                            else:
                                print(f"   ⚠️ 清書が不完全 → Step3出力を使用")
                                final_content = step3_content
                    except Exception as e:
                        print(f"   ⚠️ 清書エラー（Step3出力を使用）: {e}")
                        final_content = step3_content

                # Step6専用処理
                if "step06" in filename:
                    print(f"   🔍 Step6出力を検証中...")
                    step6_content = final_content
                    is_valid, _ = validate_article_completeness(step6_content, min_h2_count=3, check_name="Step6出力")
                    if not is_valid:
                        print(f"   ❌ CRITICAL ERROR: Step6出力が不完全。処理を中止します。")
                        return False, final_content, log_history
                    print(f"   ✅ Step6出力: 合格")

                    # 清書（もえちんは常にスキップ）
                    if not is_moechin:
                        print(f"   📝 全文清書を実行中...")
                        time.sleep(3)
                        rewrite_prompt = """上記の修正内容を完全に反映した上で、記事の【完全版】を出力してください。

【絶対厳守】
- リード文から参考文献リストまで全文を省略せずに出力すること
- すべてのH2セクションを含めること
- 完全なHTMLタグを使用すること（Markdown記法は禁止）
- 「🎨 デザイナー向け指示書」「インフォグラフィック」「図解指示」を含む段落は除外すること

今すぐ、読者向けの記事本文のみを、最初から最後まで出力してください。"""
                        try:
                            rw_chat = client.chats.create(model=MODEL_CHILD, config=GEN_CONFIG)
                            rw_resp = _send_message_with_retry(
                                rw_chat,
                                f"【元記事（以下を修正・清書してください）】\n{step6_content}\n\n{rewrite_prompt}"
                                ,
                                "Step6清書"
                            )
                            if rw_resp.text:
                                rw_content = rw_resp.text
                                cnt2 = 0
                                while rw_resp.candidates and rw_resp.candidates[0].finish_reason == types.FinishReason.MAX_TOKENS and cnt2 < 5:
                                    time.sleep(sleep_continue)
                                    rw_resp = _send_message_with_retry(rw_chat, "続きをそのまま出力してください", "Step6清書の続き")
                                    if rw_resp.text: rw_content += rw_resp.text
                                    cnt2 += 1
                                is_valid2, _ = validate_article_completeness(rw_content, min_h2_count=3, check_name="清書結果")
                                if is_valid2:
                                    final_content = rw_content
                                    step_outputs[step_key] = final_content
                                    log_history.append({"role": "User (清書指示)", "text": rewrite_prompt})
                                    log_history.append({"role": "Model (清書結果)", "text": final_content})
                                    print(f"   ✅ 全文清書完了")
                                else:
                                    print(f"   ⚠️ 清書が不完全 → Step6出力を使用")
                                    final_content = step6_content
                        except Exception as e:
                            print(f"   ⚠️ 清書エラー（Step6出力を使用）: {e}")
                            final_content = step6_content
                    else:
                        print(f"   ℹ️ もえちんモード: 清書をスキップ")

                print(f"   ✅ 完了。待機中({sleep_step}秒)...")
                time.sleep(sleep_step)
                step_success = True
                break

            except Exception as e:
                retry_count += 1
                err_msg = str(e)
                print(f"   ❌ エラー発生 ({retry_count}回目): {err_msg}")
                if "429" in err_msg or "quota" in err_msg.lower():
                    print("   ⏳ API制限。")
                    return False, final_content, log_history
                if "PROHIBITED_CONTENT" in err_msg:
                    print("   🚫 ポリシー違反でブロック。強制終了します。")
                    return False, final_content, log_history
                is_503 = "503" in err_msg or "UNAVAILABLE" in err_msg
                max_retry = 10 if is_503 else 5
                if retry_count >= max_retry:
                    print(f"   ❌ エラー{max_retry}回連続。強制終了します。")
                    return False, final_content, log_history
                # 503エラー時: 段階的待機（5秒→10秒→20秒→40秒→60秒）
                if is_503:
                    wait_503 = min(5 * (2 ** (retry_count - 1)), 60)
                    print(f"   ⏳ {wait_503}秒待機後リトライ...")
                    time.sleep(wait_503)
                else:
                    time.sleep(sleep_error)

        if not step_success:
            return False, final_content, log_history

    # 最終クリーンアップ
    print("\n🧹 記事の最終クリーンアップを実行中...")
    before_cleanup = final_content
    final_content = force_cleanup_html_child(final_content)
    # 著者・監修者テキストをPublishPressショートコードに自動置換
    site_name = selected_site.get("name", "") if selected_site else ""
    if site_name:
        final_content = replace_author_block_with_shortcodes(final_content, site_name)
    is_valid, _ = validate_article_completeness(final_content, min_h2_count=2, check_name="最終出力")
    if not is_valid:
        print(f"   ⚠️ クリーンアップで記事が破損 → クリーンアップ前に戻します")
        final_content = before_cleanup
    else:
        print(f"   ✅ 最終出力: 合格")
    if log_history: log_history[-1]["text"] = final_content
    return True, final_content, log_history


# ============================================================
# メタ情報・内部リンク プロンプト自動生成
# ============================================================
def fetch_wordpress_posts(site_config, count=50):
    """WordPress REST APIで既存記事一覧を取得"""
    url = site_config['url'].rstrip('/') + f"/wp-json/wp/v2/posts?per_page={count}&status=publish&orderby=date&order=desc"
    credentials = f"{site_config['user']}:{site_config['pass'].replace(' ', '')}"
    token = base64.b64encode(credentials.encode()).decode('utf-8')
    headers = {'Authorization': f'Basic {token}'}
    try:
        res = requests.get(url, headers=headers, timeout=30)
        if res.status_code == 200:
            posts = res.json()
            print(f"   ✅ {len(posts)}件の記事を取得しました")
            return posts
        else:
            print(f"   ❌ 取得失敗: HTTP {res.status_code}")
            return []
    except Exception as e:
        print(f"   ❌ 通信エラー: {e}")
        return []

def fetch_post_content(site_config, post_id):
    """WordPressから指定IDの記事本文を取得"""
    url = site_config['url'].rstrip('/') + f"/wp-json/wp/v2/posts/{post_id}"
    credentials = f"{site_config['user']}:{site_config['pass'].replace(' ', '')}"
    token = base64.b64encode(credentials.encode()).decode('utf-8')
    headers = {'Authorization': f'Basic {token}'}
    try:
        res = requests.get(url, headers=headers, timeout=30)
        if res.status_code == 200:
            return res.json().get('content', {}).get('rendered', '')
        return ''
    except:
        return ''


def _step9_10_site_dirs(site_folder):
    """新しい集約先を先頭に、旧フォルダも履歴読み込み用に返す。"""
    dirs = [
        os.path.join(UNIFIED_OUTPUT_DIR, site_folder),
        os.path.join(LEGACY_STEP9_10_RESULTS_DIR, site_folder),
        os.path.join(LEGACY_AI_STUDIO_PROMPTS_DIR, site_folder),
    ]
    unique = []
    for d in dirs:
        if d not in unique:
            unique.append(d)
    return unique


def _save_step9_10_result(site_name, kind, keyword, content, ext="txt", article_role=""):
    """メタ情報・内部リンクをAPI実行した結果を保存する。"""
    site_folder = re.sub(r'[\\/:*?"<>|]', '', site_name or "site")
    out_dir = os.path.join(UNIFIED_OUTPUT_DIR, site_folder)
    os.makedirs(out_dir, exist_ok=True)
    safe_kw = re.sub(r'[\\/:*?"<>|]', '', (keyword or "nokw")[:30]).strip() or "nokw"
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    kind_labels = {
        "meta_result": "メタ情報API結果",
        "meta_entry_sheet": "メタ入稿用サマリー",
        "internal_link_apply_summary": "内部リンク貼り付け指示まとめ",
    }
    if str(kind).startswith("internal_link_result"):
        label = str(kind).replace("internal_link_result", "内部リンク判断API結果")
    else:
        label = kind_labels.get(kind, str(kind))
    if article_role in ("parent", "child") and kind in ("meta_result", "meta_entry_sheet"):
        label = ("[親]" if article_role == "parent" else "[子]") + label
    label = re.sub(r'[\\/:*?"<>|]', '', label).strip() or str(kind)
    path = os.path.join(out_dir, f"{label}_{safe_kw}_{ts}.{ext}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content or "")
    return path


def refresh_organized_view_safely(verbose=True):
    """生成結果のコピー用ビューを更新する。元ファイルは移動・削除しない。"""
    organizer_path = os.path.join(BASE_DIR, "tools", "organize_generated_results.py")
    if not os.path.exists(organizer_path):
        return ""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("organize_generated_results", organizer_path)
        if not spec or not spec.loader:
            return ""
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        count, warnings = module.build_view(dry_run=False, clean=False)
        view_root = str(module.VIEW_ROOT)
        if verbose:
            print(f"   ✅ 整理済みビュー更新: {view_root}（{count}件）")
            empty_warnings = [w for w in warnings if "空の可能性" in w]
            if empty_warnings:
                print(f"   ℹ️ 空の可能性がある貼り付け指示まとめ: {len(empty_warnings)}件")
        return view_root
    except Exception as e:
        if verbose:
            print(f"   ⚠️ 整理済みビューの更新をスキップしました: {str(e)[:160]}")
        return ""


def _is_meta_entry_sheet_path(path):
    """新旧どちらのファイル名でも、入稿用サマリーか判定する。"""
    bname = os.path.basename(path or "")
    return ("entry_sheet" in bname) or ("メタ入稿用サマリー" in bname) or ("入稿用サマリー" in bname)


def _is_meta_api_result_path(path):
    """新旧どちらのファイル名でも、メタ情報API結果か判定する。"""
    bname = os.path.basename(path or "")
    return ("meta_result" in bname) or ("step9_result" in bname) or ("メタ情報API結果" in bname)


def _is_internal_link_api_result_path(path):
    """新旧どちらのファイル名でも、内部リンクAPI結果か判定する。"""
    bname = os.path.basename(path or "")
    return ("internal_link_result" in bname) or ("内部リンク判断API結果" in bname)


def _is_internal_link_apply_summary_path(path):
    """親記事へ貼る内部リンク判断結果を1本にまとめたファイルか判定する。"""
    bname = os.path.basename(path or "")
    return "内部リンク貼り付け指示まとめ" in bname


def _is_empty_internal_link_apply_summary_path(path):
    """貼り付け可能なリンクがない内部リンク指示まとめか判定する。"""
    if not _is_internal_link_apply_summary_path(path) or not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except Exception:
        return False
    no_anchor = ("対象見出しを取得できませんでした" in text) or ("挿入位置の目印を取得できませんでした" in text)
    no_link = ("リンクHTMLを抽出できませんでした" in text) or ("<a " not in text)
    return no_anchor and no_link


def _result_history_file_kind(path):
    """履歴表示用に、ファイルの役割を日本語で返す。"""
    bname = os.path.basename(path or "")
    if _is_meta_entry_sheet_path(path):
        return "入稿用サマリー（SEO/カテゴリ手動コピペ用）"
    if _is_meta_api_result_path(path):
        return "メタ情報API結果（生データ）"
    if _is_internal_link_apply_summary_path(path):
        return "内部リンク貼り付け指示まとめ"
    if _is_internal_link_api_result_path(path):
        return "内部リンク判断API結果"
    if "meta_prompt" in bname or "step9_prompt" in bname:
        return "手動用プロンプト（AI Studio貼り付け用）"
    if "internal_link_prompt" in bname or "step10_" in bname:
        return "内部リンク判断ファイル"
    if bname.startswith("run_summary_") or bname.startswith("今回の結果まとめ_") or bname.startswith("処理結果まとめ_"):
        return "結果まとめ"
    if bname.startswith("pending_internal_links_") or bname.startswith("子記事作成リスト_"):
        return "子記事作成リスト"
    if bname.startswith("log_PARENT_"):
        return "親記事ログ"
    if bname.startswith("log_CHILD_"):
        return "子記事ログ"
    if bname.startswith("internal_links_"):
        return "親記事の子記事候補リスト"
    return "その他"


def _result_history_collect_files(site_config, keyword_filter="", limit=80):
    """サイトとキーワードで、後から開きたい生成結果ファイルを集める。"""
    site_name = site_config.get("name", "") if site_config else ""
    site_folder = re.sub(r'[\\/:*?"<>|]', '', site_name or "site")
    kw = (keyword_filter or "").strip().lower()

    patterns = []
    site_dirs = _step9_10_site_dirs(site_folder)
    for d in site_dirs:
        patterns.append(os.path.join(d, "*.txt"))

    # ログ類はサイト別フォルダではないため、キーワード絞り込みと併用すると見つけやすい。
    patterns += [
        os.path.join(PARENT_LOGS, "log_PARENT_*.txt"),
        os.path.join(CHILD_LOGS, "log_CHILD_*.txt"),
        os.path.join(PARENT_WORDPRESS_DATA, "internal_links_*.txt"),
    ]

    paths = []
    seen = set()
    for pattern in patterns:
        for p in glob.glob(pattern):
            ap = os.path.abspath(p)
            if ap in seen or not os.path.isfile(p):
                continue
            bname = os.path.basename(p)
            if kw and kw not in bname.lower():
                continue
            seen.add(ap)
            paths.append(p)

    paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return paths[:limit]


def _result_history_label(path):
    """履歴メニューで一目で用途がわかるラベルを作る。"""
    kind = _result_history_file_kind(path)
    bname = os.path.basename(path)
    try:
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        mtime = "日時不明"
    return f"{mtime} / {kind} / {bname}"


def _result_history_keyword_from_filename(path):
    """生成結果ファイル名から親記事キーワードらしき部分を抜き出す。"""
    name = os.path.splitext(os.path.basename(path or ""))[0]
    prefixes = [
        "log_PARENT_",
        "internal_links_from_log_",
        "internal_links_",
        "run_summary_",
        "今回の結果まとめ_",
        "処理結果まとめ_",
        "pending_internal_links_",
        "子記事作成リスト_",
        "[親]meta_prompt_",
        "meta_prompt_",
        "メタ入稿用サマリー_",
        "メタ情報API結果_",
        "内部リンク貼り付け指示まとめ_",
        "meta_entry_sheet_",
        "meta_result_",
    ]
    for prefix in prefixes:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break

    # internal_links_LAPTOP_4_キーワード_20260516_161552 のPC/サイト番号部分を落とす
    name = re.sub(r'^(?:DESKTOP|LAPTOP|GAMING|UNKNOWN)_(?:moechin|\d+)_', '', name)
    # internal_links_from_log_LAPTOP_キーワード_20260512_165838
    name = re.sub(r'^(?:DESKTOP|LAPTOP|GAMING|UNKNOWN)_', '', name)
    name = re.sub(r'_\d{8}_\d{4,6}$', '', name)
    name = name.replace("_", " ").strip()
    return name or "キーワード不明"


def _result_history_normalize_keyword(keyword):
    return re.sub(r'\s+', '', str(keyword or "")).lower()


def _result_history_related_to_keyword(path, keyword, extra_topics=None):
    """親キーワードまたは子記事トピックに関連するファイルか判定する。"""
    bname = os.path.basename(path or "")
    hay = _result_history_normalize_keyword(bname)
    targets = [keyword] + list(extra_topics or [])
    for target in targets:
        target_norm = _result_history_normalize_keyword(target)
        if not target_norm:
            continue
        # ファイル名は途中で切られることがあるため、先頭12文字程度でも拾う
        short_norm = target_norm[:12]
        if target_norm in hay or (len(short_norm) >= 6 and short_norm in hay):
            return True
    return False


def _result_history_filename_has_keyword_exact(path, keyword):
    """ファイル名に親キーワードが省略なしで入っているか判定する。"""
    hay = _result_history_normalize_keyword(os.path.basename(path or ""))
    target = _result_history_normalize_keyword(keyword)
    return bool(target and target in hay)


def _result_history_extract_topics_from_file(path):
    """内部リンク案/保留リストから子記事トピックを抜き出す。"""
    text = read_file(path)
    topics = extract_child_topic_labels_from_links_text(text)
    if topics:
        return topics

    # pending_internal_links / 子記事作成リスト系の素朴な箇条書きにも対応
    found = []
    for line in text.splitlines():
        s = line.strip()
        s = re.sub(r'^[\-\*・\d\.\)【】\[\]\s]+', '', s).strip()
        if not s or len(s) < 6:
            continue
        if any(x in s for x in ("子記事作成リスト", "親記事", "キーワード", "保存先", "===")):
            continue
        if s not in found:
            found.append(s)
    return found[:10]


def _result_history_extract_pending_entries_from_file(path):
    """子記事作成リストから、トピックと保留理由をセットで抜き出す。"""
    text = read_file(path)
    entries = []
    current = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        m = re.match(r"^【トピック案\s*(\d+)】\s*(.+)$", line)
        if m:
            if current and current.get("topic"):
                entries.append(current)
            current = {
                "index": m.group(1),
                "topic": m.group(2).strip(),
                "reason": "",
                "existing_title": "",
                "existing_url": "",
                "source_path": path,
            }
            continue

        if not current:
            continue
        if line.startswith("判定理由:"):
            current["reason"] = line.split(":", 1)[-1].strip()
        elif line.startswith("選択済み既存記事:"):
            current["existing_title"] = line.split(":", 1)[-1].strip()
        elif line.startswith("選択済みURL:"):
            current["existing_url"] = line.split(":", 1)[-1].strip()

    if current and current.get("topic"):
        entries.append(current)

    if entries:
        return entries

    return [
        {
            "index": "",
            "topic": topic,
            "reason": "",
            "existing_title": "",
            "existing_url": "",
            "source_path": path,
        }
        for topic in _result_history_extract_topics_from_file(path)
    ]


def _result_history_parent_sessions(site_config, limit=30):
    """最近の親記事単位で履歴をまとめる。"""
    site_filter = None
    for k, v in SITES_ALL.items():
        if v.get("name") == site_config.get("name"):
            site_filter = "moechin" if k == "7" else k
            break

    source_paths = []
    if site_filter:
        for cand in get_internal_links_source_candidates(site_filter=site_filter, limit=80, dedupe_keyword=True):
            path = cand.get("source_log") or cand.get("path")
            if path:
                source_paths.append(path)

    site_folder = re.sub(r'[\\/:*?"<>|]', '', site_config.get("name", "") or "site")
    for site_dir in _step9_10_site_dirs(site_folder):
        source_paths += glob.glob(os.path.join(site_dir, "run_summary_*.txt"))
        source_paths += glob.glob(os.path.join(site_dir, "今回の結果まとめ_*.txt"))
        source_paths += glob.glob(os.path.join(site_dir, "処理結果まとめ_*.txt"))
        source_paths += glob.glob(os.path.join(site_dir, "pending_internal_links_*.txt"))
        source_paths += glob.glob(os.path.join(site_dir, "子記事作成リスト_*.txt"))
        source_paths += glob.glob(os.path.join(site_dir, "[親]meta_prompt_*.txt"))

    sessions = {}
    for path in source_paths:
        if not path or not os.path.exists(path):
            continue
        keyword = _result_history_keyword_from_filename(path)
        key = _result_history_normalize_keyword(keyword)
        if not key:
            continue
        sess = sessions.setdefault(key, {"keyword": keyword, "mtime": 0, "seed_paths": []})
        try:
            mtime = os.path.getmtime(path)
        except Exception:
            mtime = 0
        sess["mtime"] = max(sess["mtime"], mtime)
        sess["seed_paths"].append(path)

    result = sorted(sessions.values(), key=lambda x: x.get("mtime", 0), reverse=True)
    return result[:limit]


def _result_history_collect_session_files(site_config, keyword, limit=120):
    """親記事キーワードを起点に、親/子の関連ファイルを集める。"""
    site_folder = re.sub(r'[\\/:*?"<>|]', '', site_config.get("name", "") or "site")
    all_paths = []
    patterns = [os.path.join(d, "*.txt") for d in _step9_10_site_dirs(site_folder)]
    patterns += [
        os.path.join(PARENT_LOGS, "log_PARENT_*.txt"),
        os.path.join(CHILD_LOGS, "log_CHILD_*.txt"),
        os.path.join(PARENT_WORDPRESS_DATA, "internal_links_*.txt"),
    ]
    for pattern in patterns:
        all_paths.extend(glob.glob(pattern))

    child_topics = []
    for p in all_paths:
        if (
            _result_history_filename_has_keyword_exact(p, keyword)
            and _result_history_file_kind(p) in ("親記事の子記事候補リスト", "子記事作成リスト")
        ):
            child_topics.extend(_result_history_extract_topics_from_file(p))
    # 順序を保って重複削除
    seen_topics = set()
    child_topics = [t for t in child_topics if not (_result_history_normalize_keyword(t) in seen_topics or seen_topics.add(_result_history_normalize_keyword(t)))]

    related = []
    seen = set()
    for p in all_paths:
        ap = os.path.abspath(p)
        if ap in seen or not os.path.isfile(p):
            continue
        parent_exact = _result_history_filename_has_keyword_exact(p, keyword)
        child_related = _result_history_related_to_keyword(p, "", extra_topics=child_topics)
        if parent_exact or child_related:
            seen.add(ap)
            related.append(p)

    def sort_key(path):
        kind = _result_history_file_kind(path)
        order = {
            "親記事ログ": 0,
            "親記事の子記事候補リスト": 1,
            "結果まとめ": 2,
            "子記事作成リスト": 3,
            "入稿用サマリー（SEO/カテゴリ手動コピペ用）": 4,
            "子記事ログ": 5,
            "手動用プロンプト（AI Studio貼り付け用）": 6,
            "メタ情報API結果（生データ）": 7,
            "内部リンク判断ファイル": 8,
            "内部リンク貼り付け指示まとめ": 9,
            "内部リンク判断API結果": 10,
        }.get(kind, 99)
        return (order, -os.path.getmtime(path))

    related.sort(key=sort_key)
    return related[:limit], child_topics


def _result_history_tree_label(path, parent_keyword, child_topics):
    """親記事/子記事ツリー風の表示ラベルを作る。"""
    kind = _result_history_file_kind(path)
    bname = os.path.basename(path)
    try:
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%m/%d %H:%M")
    except Exception:
        mtime = "--/-- --:--"

    owner = "親記事"
    for topic in child_topics:
        if _result_history_related_to_keyword(path, topic):
            owner = f"子記事: {topic[:34]}"
            break
    return f"{owner}  >  {kind}  [{mtime}]\n    {bname}"


def _result_history_compact_file_label(path):
    """階層メニュー内で読みやすい短いファイルラベルを作る。"""
    kind = _result_history_file_kind(path)
    try:
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%m/%d %H:%M")
    except Exception:
        mtime = "--/-- --:--"
    return f"{kind}  [{mtime}]\n    {os.path.basename(path)}"


def _result_history_owner_label(path, parent_keyword, child_topics):
    """ファイルが親記事/どの子記事に属するかを短く返す。"""
    if _result_history_filename_has_keyword_exact(path, parent_keyword):
        return "親記事"
    for topic in child_topics:
        if _result_history_related_to_keyword(path, topic):
            return f"子記事: {topic[:30]}"
    kind = _result_history_file_kind(path)
    if kind == "子記事ログ" or _is_meta_entry_sheet_path(path):
        guessed = _result_history_keyword_from_filename(path)
        if guessed and _result_history_normalize_keyword(guessed) != _result_history_normalize_keyword(parent_keyword):
            return f"子記事: {guessed[:30]}"
    return "親記事"


def _result_history_compact_file_label_with_owner(path, parent_keyword, child_topics):
    """入稿用まとめ表示で、親/子の所属が一目で分かるラベルを作る。"""
    owner = _result_history_owner_label(path, parent_keyword, child_topics)
    kind = _result_history_file_kind(path)
    try:
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%m/%d %H:%M")
    except Exception:
        mtime = "--/-- --:--"
    return f"{owner}  >  {kind}  [{mtime}]\n    {os.path.basename(path)}"


def _result_history_entry_sheet_label(path, parent_keyword, child_topics):
    """入稿用サマリー専用の短い表示ラベルを作る。"""
    owner = _result_history_owner_label(path, parent_keyword, child_topics)
    try:
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%m/%d %H:%M")
    except Exception:
        mtime = "--/-- --:--"
    article = _result_history_keyword_from_filename(path)
    if owner == "親記事":
        return f"親記事  >  入稿用サマリー（SEO/カテゴリ確認用）  [{mtime}]"
    return f"{owner}  >  {article[:46]}  [{mtime}]"


def _result_history_latest_entry_defaults(paths, parent_keyword="", child_topics=None):
    """親記事・子記事ごとに最新の入稿用サマリーだけを既定選択する。"""
    checked = [False] * len(paths)
    latest_by_owner = {}
    child_topics = child_topics or []

    for idx, path in enumerate(paths):
        if not _is_meta_entry_sheet_path(path):
            continue
        owner = _result_history_owner_label(path, parent_keyword, child_topics) if parent_keyword else "入稿用サマリー"
        try:
            mtime = os.path.getmtime(path)
        except Exception:
            mtime = 0
        if owner not in latest_by_owner or mtime > latest_by_owner[owner][0]:
            latest_by_owner[owner] = (mtime, idx)

    for _mtime, idx in latest_by_owner.values():
        checked[idx] = True
    if not any(checked) and paths:
        checked[0] = True
    return checked


def _result_history_group_session_files(paths, parent_keyword, child_topics):
    """親記事ファイルと子記事ファイルを別階層に分ける。"""
    parent_files = []
    child_groups = {}
    child_order = []

    child_file_kinds = {
        "子記事ログ",
        "入稿用サマリー（SEO/カテゴリ手動コピペ用）",
        "メタ情報API結果（生データ）",
        "手動用プロンプト（AI Studio貼り付け用）",
        "内部リンク判断ファイル",
        "内部リンク貼り付け指示まとめ",
        "内部リンク判断API結果",
    }

    for p in paths:
        kind = _result_history_file_kind(p)
        parent_exact = _result_history_filename_has_keyword_exact(p, parent_keyword)
        child_key = ""

        if not parent_exact:
            for topic in child_topics:
                if _result_history_related_to_keyword(p, topic):
                    child_key = topic
                    break
            if not child_key and kind in child_file_kinds:
                child_key = _result_history_keyword_from_filename(p)

        if child_key and _result_history_normalize_keyword(child_key) != _result_history_normalize_keyword(parent_keyword):
            key_norm = _result_history_normalize_keyword(child_key)
            if key_norm not in child_groups:
                child_groups[key_norm] = {"title": child_key, "paths": [], "mtime": 0}
                child_order.append(key_norm)
            child_groups[key_norm]["paths"].append(p)
            try:
                child_groups[key_norm]["mtime"] = max(child_groups[key_norm]["mtime"], os.path.getmtime(p))
            except Exception:
                pass
        else:
            parent_files.append(p)

    def _file_sort_key(path):
        kind = _result_history_file_kind(path)
        order = {
            "入稿用サマリー（SEO/カテゴリ手動コピペ用）": 0,
            "子記事ログ": 1,
            "親記事ログ": 1,
            "親記事の子記事候補リスト": 2,
            "子記事作成リスト": 3,
            "結果まとめ": 4,
            "手動用プロンプト（AI Studio貼り付け用）": 5,
            "メタ情報API結果（生データ）": 6,
            "内部リンク判断ファイル": 7,
            "内部リンク貼り付け指示まとめ": 8,
            "内部リンク判断API結果": 9,
        }.get(kind, 99)
        return (order, -os.path.getmtime(path))

    parent_files.sort(key=_file_sort_key)
    for group in child_groups.values():
        group["paths"].sort(key=_file_sort_key)

    child_list = list(child_groups.values())
    child_list.sort(key=lambda g: g.get("mtime", 0), reverse=True)
    return parent_files, child_list


def _result_history_open_file_menu(title, paths, default_entry_sheets=True, parent_keyword="", child_topics=None, default_checked_override=None):
    """ファイル一覧を複数選択で開く。"""
    if not paths:
        print("\n   ⚠️ 開けるファイルがありません。")
        input("   Enterで戻ります...")
        return
    if parent_keyword:
        if paths and all(_is_meta_entry_sheet_path(p) for p in paths):
            labels = [_result_history_entry_sheet_label(p, parent_keyword, child_topics or []) for p in paths]
        else:
            labels = [_result_history_compact_file_label_with_owner(p, parent_keyword, child_topics or []) for p in paths]
    else:
        labels = [_result_history_compact_file_label(p) for p in paths]
    if default_checked_override is not None:
        default_checked = list(default_checked_override)
    elif default_entry_sheets:
        default_checked = _result_history_latest_entry_defaults(paths, parent_keyword, child_topics or [])
    else:
        default_checked = [False] * len(paths)
    selected = arrow_menu_multiselect(
        title + "\n"
        "  Space: 選択切替   Enter: 選択したファイルを開く   ESC: 開かずに戻る",
        labels,
        default_checked=default_checked
    )
    try:
        for idx in selected:
            p = paths[idx]
            if os.path.exists(p):
                os.startfile(p)
                time.sleep(0.25)
    except Exception as e:
        print(f"\n   ⚠️ ファイルを開けませんでした: {e}")
        input("   Enterで戻ります...")


def run_result_history_browser():
    """閉じてしまった入稿用サマリーやログを履歴から開く。"""
    os.system('cls')
    print("=" * 60)
    print("  生成結果・入稿ファイルを履歴から開く")
    print("=" * 60)
    print("  メタディスクリプションやカテゴリを後から確認したい時は、")
    print("  ここで「入稿用サマリー」を開いてください。")
    print()

    site_keys = list(SITES_ALL.keys())
    site_names = [SITES_ALL[k]["name"] for k in site_keys]
    site_idx = arrow_menu(
        "対象サイトを選択してください",
        site_names,
        allow_back=True
    )
    if menu_back(site_idx):
        return

    site_config = SITES_ALL[site_keys[site_idx]]
    sessions = _result_history_parent_sessions(site_config)
    if not sessions:
        print("\n   ⚠️ 親記事単位の履歴が見つかりませんでした。")
        print("   直近ファイル一覧へ切り替えます。")
        paths = _result_history_collect_files(site_config)
        if not paths:
            print("   履歴ファイルも見つかりませんでした。")
            input("   Enterで戻ります...")
            return
        labels = [_result_history_label(p) for p in paths]
        default_checked = [_is_meta_entry_sheet_path(p) for p in paths]
        if not any(default_checked):
            default_checked[0] = True
        selected = arrow_menu_multiselect(
            "開く履歴ファイルを選択してください",
            labels,
            default_checked=default_checked
        )
        for idx in selected:
            if os.path.exists(paths[idx]):
                os.startfile(paths[idx])
                time.sleep(0.25)
        return

    parent_labels = []
    for sess in sessions:
        mtime = datetime.datetime.fromtimestamp(sess.get("mtime", 0)).strftime("%Y-%m-%d %H:%M")
        paths, topics = _result_history_collect_session_files(site_config, sess["keyword"], limit=200)
        entry_count = sum(1 for p in paths if _is_meta_entry_sheet_path(p))
        child_log_count = sum(1 for p in paths if _result_history_file_kind(p) == "子記事ログ")
        parent_labels.append(
            f"{mtime} / 親記事: {sess['keyword']}\n"
            f"    子記事候補: {len(topics)}件 / 子記事ログ: {child_log_count}件 / 入稿用サマリー: {entry_count}件"
        )
    parent_labels.append("キーワードで絞り込んでファイル一覧を開く")

    parent_idx = arrow_menu(
        "親記事を選択してください\n"
        "  親記事を選ぶと、その親記事・子記事・メタ情報をまとめて表示します。",
        parent_labels,
        allow_back=True
    )
    if menu_back(parent_idx):
        return
    if parent_idx == len(sessions):
        keyword_filter = input("\n絞り込みキーワード（記事名の一部）: ").strip()
        paths = _result_history_collect_files(site_config, keyword_filter=keyword_filter)
        if not paths:
            print("\n   ⚠️ 該当する履歴ファイルが見つかりませんでした。")
            input("   Enterで戻ります...")
            return
        labels = [_result_history_label(p) for p in paths]
        default_checked = [_is_meta_entry_sheet_path(p) for p in paths]
        if not any(default_checked):
            default_checked[0] = True
        selected = arrow_menu_multiselect(
            "開く履歴ファイルを選択してください\n"
            "  ※ 入稿用サマリー = SEOプラグイン欄・カテゴリを手動入力するための最小シート",
            labels,
            default_checked=default_checked
        )
        for idx in selected:
            if os.path.exists(paths[idx]):
                os.startfile(paths[idx])
                time.sleep(0.25)
        return

    parent_keyword = sessions[parent_idx]["keyword"]
    paths, child_topics = _result_history_collect_session_files(site_config, parent_keyword, limit=200)
    if not paths:
        print("\n   ⚠️ この親記事に関連する履歴ファイルが見つかりませんでした。")
        input("   Enterで戻ります...")
        return

    parent_files, child_groups = _result_history_group_session_files(paths, parent_keyword, child_topics)
    display_child_topics = [g["title"] for g in child_groups]
    all_entry_sheets = [p for p in paths if _is_meta_entry_sheet_path(p)]
    internal_apply_summaries = [p for p in paths if _is_internal_link_apply_summary_path(p)]

    while True:
        action_items = [
            ("parent", f"親記事のファイルを見る（{len(parent_files)}件）"),
            ("child", f"子記事を選んでファイルを見る（{len(child_groups)}件）"),
        ]
        if internal_apply_summaries:
            action_items.append((
                "internal_apply_summary",
                f"内部リンク貼り付け指示まとめを開く（親記事に貼るリンク判断 / {len(internal_apply_summaries)}件）",
            ))
        action_items.extend([
            ("entry_sheets", f"SEO/カテゴリ確認用ファイルを選ぶ（親記事＋子記事・最新のみ既定選択 / 全{len(all_entry_sheets)}件）"),
            ("all", f"全ファイル一覧から選ぶ（{len(paths)}件）"),
            ("exit", "履歴メニューを終了する"),
        ])
        action_options = [
            label for _, label in action_items
        ]
        action = arrow_menu(
            f"開く対象を選択してください\n"
            f"  親記事: {parent_keyword}\n"
            f"  ※ SEOタイトル/メタディスクリプション/カテゴリは「入稿用サマリー」を見ます。",
            action_options,
            allow_back=True,
            back_label="履歴メニューを終了"
        )
        if menu_back(action):
            return
        action_key = action_items[action][0]
        if action_key == "exit":
            return
        if action_key == "parent":
            _result_history_open_file_menu(
                f"親記事のファイルを選択\n  親記事: {parent_keyword}",
                parent_files,
                default_entry_sheets=True,
                parent_keyword=parent_keyword,
                child_topics=display_child_topics
            )
        elif action_key == "child":
            if not child_groups:
                print("\n   ⚠️ 子記事ファイルが見つかりませんでした。")
                input("   Enterで戻ります...")
                continue
            child_labels = []
            for idx, group in enumerate(child_groups, 1):
                entry_count = sum(1 for p in group["paths"] if _is_meta_entry_sheet_path(p))
                log_count = sum(1 for p in group["paths"] if _result_history_file_kind(p) == "子記事ログ")
                child_labels.append(
                    f"子記事{idx}: {group['title']}\n"
                    f"    ログ: {log_count}件 / 入稿用サマリー: {entry_count}件 / 関連ファイル: {len(group['paths'])}件"
                )
            child_idx = arrow_menu(
                f"子記事を選択してください\n  親記事: {parent_keyword}",
                child_labels,
                allow_back=True
            )
            if menu_back(child_idx):
                continue
            group = child_groups[child_idx]
            _result_history_open_file_menu(
                f"子記事のファイルを選択\n  子記事: {group['title']}",
                group["paths"],
                default_entry_sheets=True,
                parent_keyword=parent_keyword,
                child_topics=display_child_topics
            )
        elif action_key == "internal_apply_summary":
            _result_history_open_file_menu(
                f"内部リンク貼り付け指示まとめを選択\n  親記事: {parent_keyword}",
                internal_apply_summaries,
                default_entry_sheets=False,
                parent_keyword=parent_keyword,
                child_topics=display_child_topics,
                default_checked_override=[idx == 0 for idx, _ in enumerate(internal_apply_summaries)],
            )
        elif action_key == "entry_sheets":
            _result_history_open_file_menu(
                f"SEO/カテゴリ確認用ファイルを選択\n  親記事: {parent_keyword}",
                all_entry_sheets,
                default_entry_sheets=True,
                parent_keyword=parent_keyword,
                child_topics=display_child_topics
            )
        elif action_key == "all":
            _result_history_open_file_menu(
                f"全ファイル一覧から選択\n  親記事: {parent_keyword}",
                paths,
                default_entry_sheets=True,
                parent_keyword=parent_keyword,
                child_topics=display_child_topics
            )


def _extract_post_id_from_url(url):
    """WordPressの投稿URLから投稿IDを推定する。?p=123 形式を優先する。"""
    if not url:
        return None
    m = re.search(r'[?&]p=(\d+)', str(url))
    if m:
        return int(m.group(1))
    m = re.search(r'/wp-admin/post\.php\?post=(\d+)', str(url))
    if m:
        return int(m.group(1))
    return None


def fetch_wordpress_post_brief(site_config, post_url):
    """投稿URLからWordPress投稿の状態を取得する。公開済み誤更新の事前警告に使う。"""
    post_id = _extract_post_id_from_url(post_url)
    if not post_id or not site_config:
        return {}
    base = site_config['url'].rstrip('/')
    credentials = f"{site_config['user']}:{site_config['pass'].replace(' ', '')}"
    token = base64.b64encode(credentials.encode()).decode('utf-8')
    headers = {'Authorization': f'Basic {token}'}
    fields = "id,status,title,slug,link,date,modified"
    for context in ("edit", "view"):
        url = f"{base}/wp-json/wp/v2/posts/{post_id}?context={context}&_fields={fields}"
        try:
            res = requests.get(url, headers=headers, timeout=20)
            if res.status_code == 200:
                post = res.json()
                title = post.get("title", {})
                if isinstance(title, dict):
                    title = title.get("rendered", "")
                post["plain_title"] = html.unescape(re.sub(r'<[^>]+>', '', str(title or ""))).strip()
                return post
        except Exception:
            continue
    return {}


def find_recent_meta_entry_sheets(site_name, keyword, limit=5):
    """同じサイト・キーワードの入稿用サマリーが既にあるかを探す。"""
    site_folder = re.sub(r'[\\/:*?"<>|]', '', site_name or "site")
    safe_kw = re.sub(r'[\\/:*?"<>|]', '', (keyword or "")[:30]).strip()
    paths = []
    for out_dir in _step9_10_site_dirs(site_folder):
        if os.path.isdir(out_dir):
            paths.extend(glob.glob(os.path.join(out_dir, "*.txt")))
    if safe_kw:
        paths = [p for p in paths if safe_kw in os.path.basename(p)]
    paths = [p for p in paths if _is_meta_entry_sheet_path(p) or _is_meta_api_result_path(p)]
    paths.sort(key=os.path.getmtime, reverse=True)
    return paths[:limit]


def preflight_meta_generation_guard(site_config, keyword, post_url, rankmath_mode):
    """メタ情報API実行前に、公開済み/処理済みらしき記事への誤実行を防ぐ。"""
    if rankmath_mode not in ("auto", "ask"):
        return rankmath_mode

    site_name = site_config.get("name", "") if site_config else ""
    post = fetch_wordpress_post_brief(site_config, post_url) if post_url else {}
    status = str(post.get("status") or "").strip()
    title = post.get("plain_title") or ""
    existing_sheets = find_recent_meta_entry_sheets(site_name, keyword)

    risky_reasons = []
    if status and status != "draft":
        risky_reasons.append(f"対象投稿が下書きではありません（status: {status}）")
    if existing_sheets:
        latest = os.path.basename(existing_sheets[0])
        risky_reasons.append(f"同じキーワードのメタ情報/入稿用サマリーが既にあります（最新: {latest}）")

    if not risky_reasons:
        return rankmath_mode

    print("\n" + "=" * 60)
    print("  ⚠️ メタ情報・入稿情報の再実行確認")
    print("=" * 60)
    if post_url:
        print(f"  投稿URL: {post_url}")
    if title:
        print(f"  投稿タイトル: {title}")
    if status:
        label = "公開済み" if status == "publish" else status
        print(f"  投稿状態: {label}")
    print("\n  注意:")
    for reason in risky_reasons:
        print(f"  - {reason}")
    print("\n  すでに入稿済みの記事なら、ここで中止するのが安全です。")

    idx = arrow_menu(
        "このままメタ情報・入稿情報のAPI生成を続けますか？",
        [
            "中止する（API消費なし・既存内容を守る）",
            "API生成だけ行う（WordPress自動反映なし）",
            "API生成し、投稿タイトル/スラッグの自動反映も許可する（既存内容を上書きする可能性あり）",
        ],
        allow_back=False,
    )
    if idx == 0:
        print("   → メタ情報・入稿情報のAPI生成を中止しました。")
        return None
    if idx == 1:
        print("   → API生成だけ行い、WordPressへの自動反映は行いません。")
        return "manual"
    print("   → 自動反映も許可して続行します。")
    return rankmath_mode


def find_latest_post_url_for_keyword(keyword, site_config, log_dir=PARENT_LOGS):
    """親記事ログから、指定キーワード・サイトに対応する最新のWordPress投稿URLを補完する。"""
    if not keyword or not site_config or not os.path.isdir(log_dir):
        return "", ""
    keyword_key = re.sub(r'\s+', '', str(keyword)).lower()
    site_url = str(site_config.get("url", "")).rstrip("/")
    domain = re.sub(r'^https?://', '', site_url).split('/')[0]
    logs = sorted(
        glob.glob(os.path.join(log_dir, "log_PARENT_*.txt")),
        key=os.path.getmtime,
        reverse=True,
    )
    for log_path in logs:
        base_key = re.sub(r'\s+', '', os.path.basename(log_path)).lower()
        if keyword_key and keyword_key not in base_key:
            continue
        try:
            raw = read_file(log_path)
        except Exception:
            continue
        url_matches = re.findall(r'URL:\s*(https?://[^\s]+)', raw)
        for url in reversed(url_matches):
            clean_url = url.strip().rstrip('。,.、')
            if not domain or domain in clean_url:
                return clean_url, os.path.basename(log_path)
    return "", ""


def _extract_step9_value(text, label_patterns, stop_patterns=None):
    """メタ情報生成結果から、指定ラベル直下の値を抜き出す。"""
    if not text:
        return ""
    if isinstance(label_patterns, str):
        label_patterns = [label_patterns]
    stop_patterns = stop_patterns or [
        r'\n\d+\.\s',
        r'\n【',
        r'\n■ ',
        r'\n────────────────',
        r'\n={5,}',
    ]
    for label in label_patterns:
        inline_pattern = rf'{label}\s*[：:]\s*(?P<value>[^\n]+)'
        m_inline = re.search(inline_pattern, text, flags=re.DOTALL)
        if m_inline:
            value = m_inline.group('value').strip()
            if value:
                return value
        pattern = rf'{label}\s*[：:]*\s*\n(?P<value>.*?)(?=' + '|'.join(stop_patterns) + r'|\Z)'
        m = re.search(pattern, text, flags=re.DOTALL)
        if m:
            value = m.group('value').strip()
            value = re.sub(r'^\s*[（(].*?[）)]\s*$', '', value).strip()
            return value
    return ""


def parse_step9_result_for_entry(step9_result_text, keyword=""):
    """メタ情報API結果から、WordPress入稿に必要な最小情報を抽出する。"""
    title = _extract_step9_value(
        step9_result_text,
        [r'最終決定したH1記事タイトル（絵文字除去済み）', r'最終決定したH1記事タイトル'],
    )
    slug = _extract_step9_value(step9_result_text, [r'パーマリンク（スラッグ）案', r'パーマリンク案'])
    description = _extract_step9_value(step9_result_text, [r'メタディスクリプション案'])
    image_prompt = _extract_step9_value(step9_result_text, [r'3\.\s*アイキャッチ画像生成AI向けの指示プロンプト', r'アイキャッチ画像生成AI向けの指示プロンプト'])
    existing_category = _extract_step9_value(step9_result_text, [r'最適な既存カテゴリ名'])
    new_category = _extract_step9_value(step9_result_text, [r'カテゴリ新設候補', r'新しい親カテゴリ名'])
    new_category_slug = _extract_step9_value(step9_result_text, [r'新設候補スラッグ', r'新しいスラッグ名'])
    reviewer = _extract_step9_value(step9_result_text, [r'Display name publicly as'])

    # SEOプラグイン用タイトルは、専用欄がない場合はH1案をそのまま使う。
    seo_title = title
    focus_keyword = keyword or ""

    def one_line(s):
        return re.sub(r'\s+', ' ', (s or '').strip())

    def optional_candidate(s):
        s = one_line(s)
        if not s:
            return ""
        if re.search(r'(なし|不要|該当なし|新設不要|推奨しない|推奨しません)', s):
            return ""
        return s

    new_category = optional_candidate(new_category)
    new_category_slug = optional_candidate(new_category_slug)
    category = one_line(existing_category) or new_category

    return {
        "title": one_line(title),
        "seo_title": one_line(seo_title),
        "slug": one_line(slug),
        "description": one_line(description),
        "focus_keyword": one_line(focus_keyword),
        "category": category,
        "new_category": new_category,
        "new_category_slug": new_category_slug,
        "image_prompt": image_prompt.strip(),
        "reviewer": one_line(reviewer),
    }


def find_recent_parent_new_category_hint(site_name, limit=20):
    """直近の親記事入稿用サマリーから、カテゴリ新設候補を確認用に拾う。"""
    site_folder = re.sub(r'[\\/:*?"<>|]', '', site_name or "site")
    paths = []
    for out_dir in _step9_10_site_dirs(site_folder):
        if os.path.isdir(out_dir):
            paths.extend(glob.glob(os.path.join(out_dir, "[親]メタ入稿用サマリー_*.txt")))
            paths.extend(glob.glob(os.path.join(out_dir, "メタ入稿用サマリー_*.txt")))
    paths = [p for p in paths if os.path.isfile(p)]
    paths.sort(key=os.path.getmtime, reverse=True)
    for path in paths[:limit]:
        try:
            text = read_file(path)
            candidate = _extract_step9_value(text, [r'カテゴリ新設候補'])
            candidate = re.sub(r'\s+', ' ', (candidate or "").strip())
            if candidate and not re.search(r'(なし|不要|該当なし|新設不要|推奨しない|推奨しません)', candidate):
                return candidate
        except Exception:
            continue
    return ""


def build_step9_entry_sheet(info, site_config, keyword, post_url="", source_path="", parent_category_hint=""):
    """手動反映用に、必要項目だけの短い入稿シートを作る。"""
    def _fit_description(text, limit=160):
        text = re.sub(r'\s+', ' ', (text or '').strip())
        if not text or len(text) <= limit:
            return text
        sentences = re.split(r'(?<=[。！？!?])', text)
        picked = ""
        for sentence in sentences:
            if not sentence:
                continue
            if len(picked + sentence) <= limit:
                picked += sentence
            else:
                break
        if picked:
            return picked
        return text[:max(0, limit - 1)].rstrip("、。,. ") + "…"

    raw_description = info.get("description") or ""
    fitted_description = _fit_description(raw_description)
    lines = [
        "【WordPress入稿用サマリー】",
        "",
        f"サイト: {site_config.get('name', '')} ({site_config.get('url', '')})",
        f"投稿URL: {post_url or '（未取得）'}",
        f"元キーワード: {keyword or '（未入力）'}",
        f"メタ情報・入稿情報API結果ファイル: {source_path or '（なし）'}",
        "",
        "────────────────────────────────────────",
        "【WordPress本文上部】",
        "",
        "投稿タイトル:",
        info.get("title") or "（抽出できませんでした）",
        "",
        "スラッグ:",
        info.get("slug") or "（抽出できませんでした）",
        "",
        "カテゴリ（既存候補）:",
        info.get("category") or "（抽出できませんでした）",
        "",
        "カテゴリ新設候補:",
        info.get("new_category") or "なし",
        "",
        "新設候補スラッグ:",
        info.get("new_category_slug") or "なし",
        "",
        "※ カテゴリ新設候補は自動作成されません。既存カテゴリでは記事群を整理しにくい場合だけ、WordPress側で新設を検討してください。",
        "",
    ]
    if parent_category_hint:
        lines += [
            "カテゴリ連動候補（親記事で新設予定）:",
            parent_category_hint,
            "※ 子記事側のAI判定が「カテゴリ新設候補: なし」でも、この子記事が親記事と同じ記事群なら、親記事で新設予定のカテゴリへの入稿候補として確認してください。",
            "",
        ]
    lines += [
        "────────────────────────────────────────",
        "【SEOプラグイン用】",
        "",
        "SEOタイトル:",
        info.get("seo_title") or "（抽出できませんでした）",
        "",
        "メタディスクリプション（推奨・160字以内）:",
        fitted_description or "（抽出できませんでした）",
        "",
        "メタディスクリプション（AI原文）:",
        raw_description if raw_description and raw_description != fitted_description else "（推奨版と同じ）",
        "",
        "フォーカスキーワード:",
        info.get("focus_keyword") or "（未入力）",
        "",
        "────────────────────────────────────────",
        "【画像】",
        "",
        "アイキャッチ画像プロンプト:",
        info.get("image_prompt") or "（抽出できませんでした）",
        "",
        "────────────────────────────────────────",
        "【監修者】",
        "",
        "推奨監修者:",
        info.get("reviewer") or "（抽出できませんでした）",
        "",
    ]
    return "\n".join(lines)


def save_step9_entry_sheet(site_config, keyword, step9_result_text, post_url="", source_path="", article_role=""):
    """メタ情報API結果から短い入稿シートを保存する。"""
    info = parse_step9_result_for_entry(step9_result_text, keyword)
    parent_category_hint = ""
    if article_role == "child":
        parent_category_hint = find_recent_parent_new_category_hint(site_config.get("name", "") if site_config else "")
    sheet = build_step9_entry_sheet(
        info,
        site_config,
        keyword,
        post_url=post_url,
        source_path=source_path,
        parent_category_hint=parent_category_hint,
    )
    path = _save_step9_10_result(site_config.get("name", ""), "meta_entry_sheet", keyword, sheet, article_role=article_role)
    print(f"   ✅ 入稿用サマリー保存: {os.path.basename(path)}")
    return path, info


def update_wordpress_basic_post_info(site_config, post_url, info):
    """WordPress標準項目（投稿タイトル・スラッグ）だけを下書き投稿へ反映する。SEOプラグイン欄は入稿用サマリーで手動反映する。"""
    post_id = _extract_post_id_from_url(post_url)
    if not post_id:
        return False, "投稿IDをURLから取得できませんでした。"
    wp_url = site_config['url'].rstrip('/') + f"/wp-json/wp/v2/posts/{post_id}"
    credentials = f"{site_config['user']}:{site_config['pass'].replace(' ', '')}"
    token = base64.b64encode(credentials.encode()).decode('utf-8')
    headers = {'Authorization': f'Basic {token}', 'Content-Type': 'application/json'}
    payload = {}
    if info.get("title"):
        payload["title"] = info["title"]
    if info.get("slug"):
        payload["slug"] = info["slug"]
    if not payload:
        return False, "反映できる投稿タイトル・スラッグが抽出できませんでした。"
    try:
        res = requests.post(wp_url, headers=headers, json=payload, timeout=60)
        if res.status_code not in [200, 201]:
            return False, f"WordPress基本項目の更新失敗 HTTP {res.status_code}: {res.text[:300]}"
        return True, f"WordPress標準項目へ反映しました（投稿ID: {post_id} / 投稿タイトル・スラッグ）。"
    except Exception as e:
        return False, str(e)


def update_rank_math_meta(site_config, post_url, info):
    """後方互換用。現在はSEOプラグイン固定を避け、WordPress標準項目だけを更新する。"""
    return update_wordpress_basic_post_info(site_config, post_url, info)


def select_step9_10_execution_mode(scope_label="メタ情報・入稿情報／内部リンク判断"):
    """メタ情報・入稿情報まわりの自動/確認/手動モードを1回だけ選ぶ。"""
    has_internal = "内部リンク" in scope_label
    if has_internal:
        auto_detail = (
            "     Gemini APIでメタ情報・入稿情報を生成し、続けて内部リンク判断も実行します。\n"
            "     WordPress標準項目（投稿タイトル・スラッグ）まで自動反映します。\n"
            "     SEOプラグイン欄とカテゴリは、入稿用サマリーを見て手動反映します。\n"
            "     ※ API無料枠を消費します。内部リンク判断は候補件数分だけ消費します。"
        )
        auto_option = "自動実行（API消費あり・投稿タイトル/スラッグまで自動反映）"
    else:
        auto_detail = (
            "     Gemini APIでメタ情報・入稿情報を生成します。\n"
            "     WordPress標準項目（投稿タイトル・スラッグ）まで自動反映します。\n"
            "     SEOプラグイン欄とカテゴリは、入稿用サマリーを見て手動反映します。\n"
            "     ※ API無料枠を消費します。"
        )
        auto_option = "自動実行（API消費あり・投稿タイトル/スラッグまで自動反映）"
    idx = arrow_menu(
        f"{scope_label}の実行モードを選択してください\n"
        "\n"
        "  ■ 自動実行\n"
        f"{auto_detail}\n"
        "     ※ 失敗した場合は手動用ファイルで復旧できます。\n"
        "\n"
        "  ■ 確認しながら進める\n"
        "     各ステップでAPI実行やWordPress反映を確認しながら進めます。\n"
        "\n"
        "  ■ 手動用ファイルのみ\n"
        "     APIを使わず、AI Studio貼り付け用プロンプトと入稿用サマリーだけ作ります。",
        [
            auto_option,
            "確認しながら進める",
            "手動用ファイルのみ（API消費なし）",
        ],
        allow_back=True,
    )
    if idx == -1:
        return None
    return ["auto", "review", "manual"][idx]


def select_internal_link_execution_mode():
    """内部リンク判断だけを行う場合の実行モードを選ぶ。"""
    idx = arrow_menu(
        "内部リンク判断ファイルの作り方を選択してください\n"
        "\n"
        "  ■ 手動用ファイルのみ\n"
        "     APIを使わず、AI Studioに貼り付ける内部リンク判断ファイルだけ作ります。\n"
        "     親記事本文へのリンク挿入は自動では行いません。\n"
        "\n"
        "  ■ Gemini APIで判断結果まで作る\n"
        "     内部リンク判断ファイルを作ったうえで、Gemini APIでも実行し、判断結果を保存します。\n"
        "     親記事本文へのリンク挿入は自動では行いません。\n"
        "     メタ情報・投稿タイトル・スラッグ・カテゴリは変更しません。\n"
        "     ※ 内部リンク案の件数分だけAPI無料枠を消費します。",
        [
            "手動用ファイルのみ（API消費なし・AI Studioで判断）",
            "Gemini APIで判断結果まで作る（API消費あり・本文は変更しない）",
        ],
        allow_back=True,
    )
    if idx == -1:
        return None
    return ["manual", "auto"][idx]


def run_step9_prompt_with_gemini(step9_prompt, site_config, keyword, post_url="", rankmath_mode="ask", api_key=None, api_key_label="", article_role=""):
    """生成済みメタ情報プロンプトをGemini APIで実行し、結果を保存する。"""
    if not post_url:
        m_url = re.search(r'投稿URL:\s*(https?://\S+)', step9_prompt or "")
        if m_url:
            post_url = m_url.group(1).strip()
    if not post_url and rankmath_mode in ("auto", "ask"):
        found_url, found_log = find_latest_post_url_for_keyword(keyword, site_config)
        if found_url:
            post_url = found_url
            print(f"   ✅ 投稿URLを親記事ログから補完しました: {post_url}")
            print(f"      参照ログ: {found_log}")
    rankmath_mode = preflight_meta_generation_guard(site_config, keyword, post_url, rankmath_mode)
    if rankmath_mode is None:
        return {
            "result_path": "",
            "entry_sheet_path": "",
            "info": {},
            "applied": False,
            "apply_message": "公開済み/処理済みの可能性があるため、API生成前に中止",
            "post_url": post_url,
            "skipped": True,
        }
    api_keys = API_KEYS_MOECHIN if site_config.get("type") == "C" else API_KEYS_NORMAL
    if not api_key:
        print("   ℹ️ ここからGemini APIでメタ情報・入稿情報を生成します。WordPressへの反映は生成後に別途確認します。")
        title = "APIキー選択"
        if api_key_label:
            title = f"APIキー選択\n  {api_key_label}"
        api_key = select_api_key(api_keys, title=title)
    if not api_key:
        print("   ℹ️ APIキーが選択されませんでした。メタ情報のAPI実行をスキップします。")
        return None
    try:
        _load_genai()
        client = genai.Client(api_key=api_key)
        chat = client.chats.create(model=MODEL_CHILD, config=GEN_CONFIG)
        print(f"\n🤖 メタ情報・入稿情報をGemini APIで生成中... 使用モデル: {MODEL_CHILD}")
        response = _send_message_with_retry(chat, step9_prompt, "メタ情報・入稿情報生成", max_retries=2)
        result = (response.text or "").strip()
        if not result:
            print("   ⚠️ メタ情報・入稿情報のAPI出力が空でした。")
            return None
        header = (
            f"■■■ メタ情報・入稿情報API生成結果 ■■■\n"
            f"生成日時: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"PC識別子: {PC_IDENTIFIER}\n"
            f"サイト: {site_config.get('name', '')} ({site_config.get('url', '')})\n"
            f"キーワード: {keyword}\n"
            f"使用モデル: {MODEL_CHILD}\n"
            f"{'='*80}\n\n"
        )
        path = _save_step9_10_result(site_config.get("name", ""), "meta_result", keyword, header + result + "\n", article_role=article_role)
        print(f"   ✅ メタ情報・入稿情報API結果を保存しました: {os.path.basename(path)}")
        result_text = header + result + "\n"
        entry_info = parse_step9_result_for_entry(result_text, keyword)
        applied = False
        apply_message = ""
        do_apply = False
        if rankmath_mode in ("auto", "ask"):
            if rankmath_mode == "auto":
                do_apply = True
                print("   ℹ️ 自動実行モード: 生成したメタ情報・入稿情報のWordPress標準項目反映へ進みます。")
            else:
                apply_idx = arrow_menu(
                    "生成したメタ情報・入稿情報をWordPressへ自動反映しますか？\n"
                    "  ※ Gemini APIでの生成は完了済みです。ここから先はWordPress投稿の更新確認です。\n"
                    "  ※ 自動反映するのは投稿タイトル・スラッグだけです。\n"
                    "  ※ SEOプラグイン欄とカテゴリは、入稿用サマリーを見て手動入力してください。\n"
                    "  ※ 不安な場合は「自動反映しない」を選ぶと、入稿用サマリーだけ保存します。",
                    [
                        "自動反映する（反映先投稿を確認してから更新）",
                        "自動反映しない（入稿用サマリーだけ保存）",
                    ],
                    allow_back=False,
                )
                do_apply = (apply_idx == 0)
            if do_apply and not post_url:
                post_url = select_wordpress_post_url_for_meta_apply(site_config, keyword)
            if do_apply and post_url:
                applied, apply_message = update_rank_math_meta(site_config, post_url, entry_info)
                if applied:
                    print(f"   ✅ {apply_message}")
                    print("   ℹ️ SEOプラグイン欄・カテゴリは自動反映していません。入稿用サマリーを見て手動入力してください。")
                else:
                    print(f"   ⚠️ WordPress標準項目の自動反映に失敗: {apply_message}")
                    print("   ℹ️ 入稿用サマリーを使って手動反映してください。")
            elif do_apply:
                print("   ℹ️ 反映先投稿を選ばなかったため、自動反映は行いません。")
        entry_path, entry_info = save_step9_entry_sheet(
            site_config, keyword, result_text, post_url=post_url, source_path=path, article_role=article_role
        )
        return {
            "result_path": path,
            "entry_sheet_path": entry_path,
            "info": entry_info,
            "applied": applied,
            "apply_message": apply_message,
            "post_url": post_url,
        }
    except Exception as e:
        err = str(e)
        if _is_quota_error_message(err):
            print("   ❌ Gemini APIの上限/クォータに達した可能性があります。手動用ファイルは保存済みなので、AI Studio実行に切り替えられます。")
        else:
            print(f"   ❌ メタ情報・入稿情報のAPI生成エラー: {err[:300]}")
        return None


def run_step10_prompt_with_gemini(step10_prompt, site_config, keyword, topic_title, item_index, api_key):
    """生成済み内部リンク判断プロンプトをGemini APIで実行し、結果を保存する。"""
    try:
        _load_genai()
        client = genai.Client(api_key=api_key)
        chat = client.chats.create(model=MODEL_CHILD, config=GEN_CONFIG)
        print(f"\n🤖 内部リンク判断をGemini APIで実行中... 候補 {item_index}: {topic_title[:40]}")
        response = _send_message_with_retry(chat, step10_prompt, f"内部リンク判断 {item_index}", max_retries=2)
        result = clean_internal_link_api_text(response.text or "")
        if not result:
            print("   ⚠️ 内部リンク判断API出力が空でした。")
            return None
        header = (
            f"■■■ 内部リンク判断API実行結果 ■■■\n"
            f"生成日時: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"PC識別子: {PC_IDENTIFIER}\n"
            f"サイト: {site_config.get('name', '')} ({site_config.get('url', '')})\n"
            f"キーワード: {keyword}\n"
            f"内部リンク案: {topic_title}\n"
            f"使用モデル: {MODEL_CHILD}\n"
            f"{'='*80}\n\n"
        )
        path = _save_step9_10_result(site_config.get("name", ""), f"internal_link_result_{item_index}", keyword, header + result + "\n")
        print(f"   ✅ 内部リンク判断API結果を保存しました: {os.path.basename(path)}")
        return path
    except KeyboardInterrupt:
        print("\n   ⚠️ 内部リンク判断APIを中断しました。")
        print("      内部リンク判断ファイルは保存済みです。必要ならAI Studioで手動実行できます。")
        return None
    except Exception as e:
        err = str(e)
        if _is_quota_error_message(err):
            print("   ❌ Gemini APIの上限/クォータに達した可能性があります。以降は手動用ファイル作成のみで続行できます。")
        else:
            print(f"   ❌ 内部リンク判断API実行エラー: {err[:300]}")
        return None


def clean_internal_link_api_text(text):
    """内部リンク判断結果から、貼り付けに不要なMarkdown装飾を除去する。"""
    text = (text or "").strip()
    if not text:
        return ""
    # コードフェンスで全体やHTML断片を囲まれた場合の保険。
    text = re.sub(r'```(?:html|HTML)?\s*', '', text)
    text = text.replace('```', '')

    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        # GeminiがHTML断片を `<p>...</p>` のようにインラインコード化することがある。
        # WordPressへ貼る指示としてはバッククォートは不要なので、HTML行だけ外す。
        if len(stripped) >= 3 and stripped.startswith("`") and stripped.endswith("`"):
            inner = stripped[1:-1].strip()
            if inner.startswith("<") and inner.endswith(">"):
                indent = line[:len(line) - len(line.lstrip())]
                line = indent + inner
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


def _extract_internal_link_result_fields(text):
    """内部リンク判断API結果から、設置位置と挿入HTMLを抜き出す。"""
    text = clean_internal_link_api_text(text)

    def section_value(label):
        pattern = rf'【{re.escape(label)}】\s*\n([\s\S]*?)(?=\n【[^】]+】|\Z)'
        m = re.search(pattern, text)
        return m.group(1).strip() if m else ""

    topic = ""
    m = re.search(r"内部リンク案:\s*(.+)", text)
    if m:
        topic = m.group(1).strip()
    heading = section_value("対象見出し")
    anchor = section_value("この文章の直後に挿入")
    insert_html = section_value("挿入するHTMLコード")
    fields = {
        "topic": topic,
        "heading": heading,
        "anchor": anchor,
        "insert_html": insert_html,
        "text": text,
    }
    fields["actionable"] = _internal_link_result_is_actionable(fields)
    fields["needs_child_article"] = _internal_link_result_needs_child_article(fields)
    return fields


def _internal_link_result_is_actionable(fields):
    """親記事にそのまま貼れる内部リンク指示かどうか。"""
    if not fields:
        return False
    text = clean_internal_link_api_text(fields.get("text", ""))
    warning_like = re.search(
        r'【警告】|推奨しません|新規記事の作成が最適|新しい記事の作成|子記事の作成|内部リンクは推奨しません',
        text,
    )
    heading = fields.get("heading", "") or ""
    anchor = fields.get("anchor", "") or ""
    insert_html = fields.get("insert_html", "") or ""
    missing_markers = "取得できませんでした|抽出できませんでした|該当なし|（なし）"
    has_required_parts = bool(
        heading.strip()
        and anchor.strip()
        and re.search(r'<a\s+[^>]*href=', insert_html, re.I)
        and not re.search(missing_markers, heading + anchor + insert_html)
    )
    return bool(has_required_parts and not warning_like)


def _internal_link_result_needs_child_article(fields):
    """API結果が、新規子記事作成へ回すべき判断かどうか。"""
    if not fields:
        return False
    text = clean_internal_link_api_text(fields.get("text", ""))
    if _internal_link_result_is_actionable(fields):
        return False
    return bool(
        re.search(r'新規記事|新しい記事|子記事|記事を作成', text)
        and re.search(r'推奨|最適|必要|作成', text)
    )


def _internal_link_location_error(fields, parent_html):
    """内部リンクの貼り付け位置が親記事本文に実在するか確認する。"""
    if not parent_html:
        return ""
    parent_norm = _normalize_internal_link_location(parent_html)
    heading = (fields or {}).get("heading", "") or ""
    anchor = (fields or {}).get("anchor", "") or ""
    heading_norm = _normalize_internal_link_location(heading)
    anchor_norm = _normalize_internal_link_location(anchor)
    missing = []
    if heading_norm and heading_norm not in parent_norm:
        missing.append("対象見出し")
    if anchor_norm and anchor_norm not in parent_norm:
        missing.append("挿入位置の目印段落")
    if not missing:
        return ""
    return f"{'・'.join(missing)}が親記事本文内に見つかりません。AIが親記事本文にない文章を目印として生成した可能性があります。"


def _iter_parent_internal_link_locations(parent_html):
    """親記事HTMLから、内部リンクの貼り付け候補になる実在の見出し・段落を列挙する。"""
    if not parent_html:
        return []
    locations = []
    if BeautifulSoup:
        try:
            soup = BeautifulSoup(parent_html, "html.parser")
            for heading in soup.find_all(["h2", "h3"]):
                heading_html = str(heading).strip()
                heading_text = heading.get_text(" ", strip=True)
                for sibling in heading.next_siblings:
                    sibling_name = getattr(sibling, "name", None)
                    if sibling_name in {"h1", "h2", "h3"}:
                        break
                    if sibling_name != "p":
                        continue
                    para_text = sibling.get_text(" ", strip=True)
                    if not para_text:
                        continue
                    locations.append({
                        "heading": heading_html,
                        "anchor": str(sibling).strip(),
                        "heading_text": heading_text,
                        "anchor_text": para_text,
                    })
            if locations:
                return locations
        except Exception:
            pass

    # BeautifulSoupが使えない/解析できない場合の最低限フォールバック。
    chunks = re.split(r'(?=<h[23]\b)', parent_html or "", flags=re.I)
    for chunk in chunks:
        heading_match = re.search(r'(<h[23]\b[^>]*>[\s\S]*?</h[23]>)', chunk, re.I)
        if not heading_match:
            continue
        heading_html = heading_match.group(1).strip()
        heading_text = re.sub(r'<[^>]+>', '', heading_html)
        heading_text = html.unescape(re.sub(r'\s+', ' ', heading_text)).strip()
        for para_match in re.finditer(r'(<p\b[^>]*>[\s\S]*?</p>)', chunk, re.I):
            anchor_html = para_match.group(1).strip()
            anchor_text = re.sub(r'<[^>]+>', '', anchor_html)
            anchor_text = html.unescape(re.sub(r'\s+', ' ', anchor_text)).strip()
            if anchor_text:
                locations.append({
                    "heading": heading_html,
                    "anchor": anchor_html,
                    "heading_text": heading_text,
                    "anchor_text": anchor_text,
                })
    return locations


def _internal_link_location_terms(fields):
    """壊れた貼り付け位置を補正するための、トピック寄りの語句を抽出する。"""
    source = "\n".join([
        (fields or {}).get("topic", "") or "",
        (fields or {}).get("heading", "") or "",
        (fields or {}).get("anchor", "") or "",
        (fields or {}).get("insert_html", "") or "",
    ])
    source = re.sub(r'<[^>]+>', ' ', source)
    source = html.unescape(source)
    terms = []
    for term in _wp_search_terms_from_text(source):
        if len(term) >= 2 and term not in terms:
            terms.append(term)
    # _wp_search_terms_from_text が落としやすい重要語を補完する。
    for term in re.findall(r'[一-龥ぁ-んァ-ンA-Za-z0-9]{2,}', source):
        if term in {"target", "blank", "noopener", "https", "html", "href"}:
            continue
        if term not in terms:
            terms.append(term)
    return terms[:24]


def _suggest_internal_link_location_from_parent(fields, parent_html):
    """
    AIが親記事に存在しない貼り付け位置を返した場合に、
    親記事本文内の実在する見出し・段落から近い位置を補正候補として返す。
    """
    if not fields or not parent_html:
        return None
    locations = _iter_parent_internal_link_locations(parent_html)
    if not locations:
        return None

    terms = _internal_link_location_terms(fields)
    if not terms:
        return None

    target_heading_norm = _normalize_internal_link_location(fields.get("heading", ""))
    best = None
    for loc in locations:
        heading_text = loc.get("heading_text", "")
        anchor_text = loc.get("anchor_text", "")
        heading_norm = _normalize_internal_link_location(heading_text)
        anchor_norm = _normalize_internal_link_location(anchor_text)
        score = 0

        # 元の見出しと近い見出しを強く優先する。
        if target_heading_norm and heading_norm:
            common_len = 0
            for term in terms:
                if term in target_heading_norm and term in heading_norm:
                    common_len += len(term)
            score += common_len * 3

        for term in terms:
            if term in heading_text:
                score += 8
            if term in anchor_text:
                score += 3
            if term in heading_norm:
                score += 5
            if term in anchor_norm:
                score += 2

        # 短すぎる段落やCTA的な短文より、本文中の説明段落を少し優先する。
        if len(_normalize_internal_link_location(anchor_text)) >= 35:
            score += 2
        if len(_normalize_internal_link_location(anchor_text)) >= 70:
            score += 1

        if not best or score > best["score"]:
            best = {**loc, "score": score}

    # 低スコアで無理に補正すると、別の場所へ誤誘導するため止める。
    if not best or best["score"] < 12:
        return None
    return best


def _summarize_internal_link_exclusion(fields):
    """貼り付けまとめから除外した内部リンク判断の理由を短く返す。"""
    if fields and fields.get("location_error"):
        return fields.get("location_error")
    text = clean_internal_link_api_text((fields or {}).get("text", ""))
    if not text:
        return "API結果が空、または読み取れませんでした。"
    warning = re.search(r'【警告】\s*([^\n]+)', text)
    if warning:
        return warning.group(1).strip()
    first_reason = re.search(r'(指定された既存記事への内部リンクは推奨しません。?[^\n]*)', text)
    if first_reason:
        return first_reason.group(1).strip()
    if _internal_link_result_needs_child_article(fields):
        return "既存記事への内部リンクは非推奨で、新規子記事作成が推奨されています。"
    return "貼り付け位置または挿入HTMLを取得できなかったため、最終貼り付け案から除外しました。"


def _extract_internal_link_warning_body(fields):
    """非推奨判断の本文を、貼り付けまとめに出せる形で短く抜き出す。"""
    text = clean_internal_link_api_text((fields or {}).get("text", ""))
    if not text:
        return ""
    m = re.search(
        r'【警告】[^\n]*\n+([\s\S]*?)(?=\n【INPUT】|\n推奨H1タイトル案:|\n記事が持つべき独自の切り口:|\Z)',
        text,
    )
    if m:
        body = re.sub(r'\n{3,}', '\n\n', m.group(1).strip())
        return body[:900].strip()
    return ""


def _extract_internal_link_recommendation_details(fields):
    """非推奨時の新規記事提案（H1/切り口）があれば抜き出す。"""
    text = clean_internal_link_api_text((fields or {}).get("text", ""))
    if not text:
        return "", ""
    h1 = ""
    angle = ""
    m_h1 = re.search(r'推奨H1タイトル案\s*[:：]\s*(.+)', text)
    if m_h1:
        h1 = m_h1.group(1).strip()
    m_angle = re.search(r'記事が持つべき独自の切り口\s*[:：]\s*([\s\S]*?)(?=\n\s*<br\b|\n\s*【|\Z)', text)
    if m_angle:
        angle = re.sub(r'\n{3,}', '\n\n', m_angle.group(1).strip())[:700].strip()
    return h1, angle


def _build_internal_link_not_reflected_lines(excluded_items=None, manual_wait_paths=None):
    """最終貼り付け案の中に続けて出す、未反映/除外候補の注意書きを作る。"""
    excluded_items = excluded_items or []
    manual_wait_paths = manual_wait_paths or []
    if not excluded_items and not manual_wait_paths:
        return []

    lines = [
        "",
        "【最終貼り付け案に含めていない候補】",
        "下記も今回確認対象だった内部リンク案です。",
        "ただし、親記事にそのまま貼れる状態ではないため、上の貼り付けHTMLには入れていません。",
    ]

    for item in excluded_items:
        fields = item.get("fields") or {}
        topic = fields.get("topic") or "（内部リンク案名を取得できませんでした）"
        if _internal_link_result_needs_child_article(fields):
            lines.extend([
                "",
                f"【候補{item.get('idx')}: 非推奨のため未反映】",
                f"内部リンク案: {topic}",
                "状態: 指定された既存記事への内部リンクは推奨しません。新規記事の作成が最適です。",
            ])
            warning_body = _extract_internal_link_warning_body(fields)
            if warning_body:
                lines.extend(["", "理由:", warning_body])
            h1, angle = _extract_internal_link_recommendation_details(fields)
            if h1:
                lines.extend(["", "推奨H1タイトル案:", h1])
            if angle:
                lines.extend(["", "記事が持つべき独自の切り口:", angle])
            lines.extend([
                "",
                "次にやること:",
                "この内部リンク案のトピックで子記事を作成し、作成後にメニュー5で内部リンクだけ再確認してください。",
                f"判断元ファイル: {os.path.basename(item.get('path') or '')}",
            ])
        else:
            lines.extend([
                "",
                f"【候補{item.get('idx')}: 未反映】",
                f"内部リンク案: {topic}",
                f"状態: {_summarize_internal_link_exclusion(fields)}",
                "次にやること: 個別API結果を確認し、必要なら再検索して判断を作り直してください。",
                f"判断元ファイル: {os.path.basename(item.get('path') or '')}",
            ])

    for num, title, path, reason in manual_wait_paths:
        lines.extend([
            "",
            f"【候補{num}: API判断なしのため未反映】",
            f"内部リンク案: {title}",
            f"状態: {reason}",
            "この候補は、まだ「既存記事に貼るべきか / 新規子記事に回すべきか」のAPI判断がありません。",
            "親記事に貼る最終案へ入れるには、メニュー5で内部リンクだけ再確認し、この候補をGemini APIで判断してください。",
            f"手動用ファイル: {os.path.basename(path)}",
        ])

    lines.append("")
    return lines


def _format_step10_attention_event_lines(step10_attention_events, step10_apply_summary_path=""):
    """完了画面で、最終貼り付け案に入っていない候補を見落とさない形に整える。"""
    events = step10_attention_events or []
    if not events:
        return []
    lines = [
        "!" * 60,
        "⚠️  最終貼り付け案に入っていない内部リンク候補があります",
        "   下記は親記事へそのまま貼る対象ではありません。",
    ]
    for event in events:
        lines.append("")
        lines.append(f"   【{event.get('num')}】{event.get('title')}")
        if event.get("type") == "non_recommended":
            lines.append("      状態: 既存記事への内部リンクは非推奨です。子記事作成リストへ入れました。")
            if event.get("existing_title"):
                lines.append(f"      選択済み既存記事: {event.get('existing_title')}")
            if event.get("existing_url"):
                lines.append(f"      URL: {event.get('existing_url')}")
        else:
            lines.append(f"      状態: {event.get('reason')}。API判断結果がないため未反映です。")
        if event.get("source"):
            lines.append(f"      判断元/手動用: {os.path.basename(event.get('source'))}")
    if step10_apply_summary_path:
        lines.append("")
        lines.append(f"   詳細は貼り付け指示まとめにも記載しています: {os.path.basename(step10_apply_summary_path)}")
    lines.append("!" * 60)
    return lines


def _internal_link_candidate_number_from_path(path, fallback):
    """内部リンク判断API結果ファイル名から候補番号を取り出す。"""
    m = re.search(r'内部リンク判断API結果_(\d+)_', os.path.basename(path or ""))
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    return fallback


def _read_internal_link_result_fields_from_path(path):
    """内部リンクAPI結果ファイルを読み、貼り付け可否の判定フィールドを返す。"""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return _extract_internal_link_result_fields(f.read())
    except Exception:
        return {}


def _internal_link_result_state(fields):
    """内部リンクAPI結果の状態を、UI/続き判定で使いやすい短い種別へ正規化する。"""
    if _internal_link_result_is_actionable(fields):
        return "actionable"
    if _internal_link_result_needs_child_article(fields):
        return "needs_child"
    return "not_actionable"


def _normalize_internal_link_location(text):
    text = clean_internal_link_api_text(text)
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    text = re.sub(r'\s+', '', text)
    return text


def _internal_link_locations_overlap(a, b):
    """2つの挿入位置が実質同じ場所を指しているか判定する。"""
    na = _normalize_internal_link_location(a)
    nb = _normalize_internal_link_location(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    short, long = (na, nb) if len(na) <= len(nb) else (nb, na)
    # 片方がもう片方の段落に含まれる場合は、同じ周辺位置への指示とみなす。
    if len(short) >= 28 and short in long:
        return True
    return False


def _extract_first_link_from_html(html_text):
    m = re.search(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html_text or "", re.I | re.S)
    if not m:
        return None
    title = re.sub(r'<[^>]+>', '', m.group(2))
    return {"url": m.group(1).strip(), "title": html.unescape(title).strip()}


def _group_internal_link_placements(items):
    """同じ見出し内でも、挿入位置が実質重複する候補だけをまとめる。"""
    groups = []
    for item in items:
        fields = item.get("fields") or {}
        heading_key = _normalize_internal_link_location(fields.get("heading", ""))
        anchor = fields.get("anchor", "")
        if not heading_key or not anchor:
            groups.append([item])
            continue
        placed = False
        for group in groups:
            base = group[0].get("fields") or {}
            same_heading = heading_key == _normalize_internal_link_location(base.get("heading", ""))
            overlaps = any(
                _internal_link_locations_overlap(anchor, (g.get("fields") or {}).get("anchor", ""))
                for g in group
            )
            if same_heading and overlaps:
                group.append(item)
                placed = True
                break
        if not placed:
            groups.append([item])
    return groups


def _build_related_links_block(links):
    if not links:
        return "（リンクHTMLを抽出できませんでした。各候補の【挿入するHTMLコード】を確認してください。）"
    lines = [
        '<div class="related-links">',
        '<p><strong>あわせて読みたい：</strong></p>',
        '<ul>',
    ]
    for link in links:
        lines.append(f'<li><a href="{link["url"]}" target="_blank" rel="noopener">{link["title"]}</a></li>')
    lines.extend(['</ul>', '</div>'])
    return "\n".join(lines)


def _build_internal_link_final_plan(items, has_not_reflected=False):
    """内部リンクの最終貼り付け案だけを作る。重複位置だけ統合し、別位置は分ける。"""
    groups = _group_internal_link_placements(items)
    lines = [
        "【最終貼り付け案】",
        "下記だけを親記事に反映してください。",
        "同じ挿入位置を指す内部リンクだけ統合しています。別位置が適切なリンクは個別の貼り付け案として残しています。",
        "",
    ]
    for group_no, group in enumerate(groups, start=1):
        first = group[0].get("fields") or {}
        heading = first.get("heading", "")
        # 重複統合時は、本文内で目印として見つけやすい長い段落を優先する。
        anchors = [(item.get("fields") or {}).get("anchor", "") for item in group]
        anchor = max(anchors, key=lambda x: len(_normalize_internal_link_location(x) or ""))
        links = []
        seen_urls = set()
        for item in group:
            link = _extract_first_link_from_html((item.get("fields") or {}).get("insert_html", ""))
            if link and link["url"] not in seen_urls:
                seen_urls.add(link["url"])
                links.append(link)

        if len(group) >= 2:
            title = f"貼り付け案 {group_no}: 重複位置のため関連記事ブロックに統合"
            html_code = _build_related_links_block(links)
        else:
            title = f"貼り付け案 {group_no}: 個別に挿入"
            html_code = first.get("insert_html", "") or _build_related_links_block(links)

        lines.extend([
            f"【{title}】",
            f"対象候補: {', '.join(str(item.get('idx')) for item in group)}",
            "",
            "対象見出し:",
            heading or "（対象見出しを取得できませんでした）",
            "",
            "この文章の直後に挿入:",
            anchor or "（挿入位置の目印を取得できませんでした）",
            "",
            "挿入するHTMLコード:",
            html_code,
            "",
            "参考ファイル:",
        ])
        for item in group:
            lines.append(f"- {os.path.basename(item.get('path') or '')}")
        repaired = [item for item in group if (item.get("fields") or {}).get("location_repaired")]
        if repaired:
            lines.extend(["", "補正メモ:"])
            for item in repaired:
                fields = item.get("fields") or {}
                lines.append(
                    f"- 候補{item.get('idx')}: AIが出した貼り付け位置が親記事本文に存在しなかったため、"
                    "ツールが親記事本文内の実在する見出し・段落へ補正しました。"
                )
                if fields.get("original_heading"):
                    lines.append(f"  元の対象見出し: {fields.get('original_heading')}")
                if fields.get("original_anchor"):
                    lines.append(f"  元の目印段落: {fields.get('original_anchor')}")
        if group_no < len(groups) or not has_not_reflected:
            lines.extend(["", "-" * 80, ""])
        else:
            lines.extend([
                "",
                "※下に、今回の最終貼り付け案へ入れていない候補を続けて表示します。",
            ])
    return lines


def save_internal_link_apply_summary(site_config, keyword, result_paths, manual_wait_paths=None, parent_html=""):
    """親記事へ内部リンクを入れるため、案ごとのAPI結果を1本にまとめる。"""
    paths = [p for p in (result_paths or []) if p and os.path.exists(p)]
    manual_wait_paths = manual_wait_paths or []
    if not paths and not manual_wait_paths:
        return None
    result_items = []
    excluded_items = []
    for idx, path in enumerate(paths, start=1):
        candidate_num = _internal_link_candidate_number_from_path(path, idx)
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = clean_internal_link_api_text(f.read())
        except Exception as e:
            text = f"（読み込み失敗: {e}）"
        fields = _extract_internal_link_result_fields(text)
        location_error = _internal_link_location_error(fields, parent_html)
        if location_error:
            repair = _suggest_internal_link_location_from_parent(fields, parent_html)
            if repair and _internal_link_result_is_actionable(fields):
                fields = dict(fields)
                fields["location_error"] = location_error
                fields["location_repaired"] = True
                fields["original_heading"] = fields.get("heading", "")
                fields["original_anchor"] = fields.get("anchor", "")
                fields["heading"] = repair.get("heading", "")
                fields["anchor"] = repair.get("anchor", "")
                result_items.append({"idx": candidate_num, "path": path, "text": text, "fields": fields})
            else:
                fields = dict(fields)
                fields["location_error"] = location_error
                excluded_items.append({"idx": candidate_num, "path": path, "text": text, "fields": fields})
        elif _internal_link_result_is_actionable(fields):
            result_items.append({"idx": candidate_num, "path": path, "text": text, "fields": fields})
        else:
            excluded_items.append({"idx": candidate_num, "path": path, "text": text, "fields": fields})

    if not result_items:
        lines = [
            "■■■ 内部リンク貼り付け指示まとめ ■■■",
            f"生成日時: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"PC識別子: {PC_IDENTIFIER}",
            f"対象サイト: {site_config.get('name', '') if site_config else ''}",
            f"親記事キーワード: {keyword}",
            "",
            "【このファイルの役割】",
            "この親記事に入れる内部リンクの最終貼り付け案です。",
            "今回は親記事へ貼り付け可能な案がありませんでした。",
            "",
            "=" * 80,
            "",
            "【最終貼り付け案】",
            "貼り付け可能な内部リンク案はありません。",
        ]
        lines.extend(_build_internal_link_not_reflected_lines(excluded_items, manual_wait_paths))
        return _save_step9_10_result(
            site_config.get("name", "") if site_config else "",
            "internal_link_apply_summary",
            keyword,
            "\n".join(lines) + "\n",
        )

    lines = [
        "■■■ 内部リンク貼り付け指示まとめ ■■■",
        f"生成日時: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"PC識別子: {PC_IDENTIFIER}",
        f"対象サイト: {site_config.get('name', '') if site_config else ''}",
        f"親記事キーワード: {keyword}",
        "",
        "【このファイルの役割】",
        "この親記事に入れる内部リンクの最終貼り付け案です。",
        "親記事本文へ自動挿入はしていません。ここに出ている【最終貼り付け案】だけを手動で反映してください。",
        "",
        "=" * 80,
    ]

    has_not_reflected = bool(excluded_items or manual_wait_paths)
    lines.extend([""] + _build_internal_link_final_plan(result_items, has_not_reflected=has_not_reflected) + [""])
    lines.extend(_build_internal_link_not_reflected_lines(excluded_items, manual_wait_paths))
    lines.extend([
        "【個別API結果ファイル】",
        "詳細な判断理由を確認したい場合だけ、下記の個別ファイルを開いてください。",
    ])
    for item in result_items:
        lines.append(f"- 候補{item['idx']}: {os.path.basename(item['path'])}")
    if excluded_items:
        lines.extend([
            "",
            "=" * 80,
            "",
            "【除外・未反映候補の一覧】",
            "上の重要欄と同じ内容を、ファイル確認用に一覧化しています。",
        ])
        for item in excluded_items:
            fields = item["fields"]
            lines.append(f"\n- 候補{item['idx']}: {fields.get('topic') or '（内部リンク案名を取得できませんでした）'}")
            lines.append(f"  除外理由: {_summarize_internal_link_exclusion(fields)}")
            lines.append(f"  判断元ファイル: {os.path.basename(item.get('path') or '')}")
    if manual_wait_paths:
        if not excluded_items:
            lines.extend([
                "",
                "=" * 80,
                "",
                "【除外・未反映候補の一覧】",
                "上の重要欄と同じ内容を、ファイル確認用に一覧化しています。",
            ])
        for num, title, p, reason in manual_wait_paths:
            lines.append(f"\n- 候補{num}: {title}")
            lines.append(f"  状態: {reason}")
            lines.append(f"  手動用ファイル: {os.path.basename(p)}")
    return _save_step9_10_result(
        site_config.get("name", "") if site_config else "",
        "internal_link_apply_summary",
        keyword,
        "\n".join(lines) + "\n",
    )


def find_existing_internal_link_artifacts(topic_title, keyword, item_index, base_dirs=None):
    """内部リンク案ごとの手動プロンプト/API結果を分けて検出する。"""
    safe_topic_check = re.sub(r'[\\/:*?"<>|]', '', (topic_title or "")[:15])
    safe_kw_for_existing_api = re.sub(r'[\\/:*?"<>|]', '', (keyword or "")[:20])
    search_dirs = base_dirs or (UNIFIED_OUTPUT_DIR, LEGACY_AI_STUDIO_PROMPTS_DIR, LEGACY_STEP9_10_RESULTS_DIR)
    prompt_files = []
    api_files = []
    for base_dir in search_dirs:
        prompt_files += glob.glob(os.path.join(base_dir, "**", f"*step10_*{safe_topic_check}*.txt"), recursive=True)
        prompt_files += glob.glob(os.path.join(base_dir, "**", f"*internal_link_prompt_*{safe_topic_check}*.txt"), recursive=True)
        api_files += glob.glob(os.path.join(base_dir, "**", f"内部リンク判断API結果_{item_index}_{safe_kw_for_existing_api}*.txt"), recursive=True)
    prompt_files = sorted(set(prompt_files), key=os.path.getmtime)
    api_files = sorted(set(api_files), key=os.path.getmtime)
    return prompt_files, api_files


def _normalize_completed_child(child):
    """子記事完了データを、旧tuple形式/新dict形式の両方から同じ形に整える。"""
    if isinstance(child, dict):
        return {
            "keyword": str(child.get("keyword") or child.get("title") or "").strip(),
            "html": str(child.get("html") or child.get("content") or child.get("final_content") or "").strip(),
            "url": str(child.get("url") or child.get("post_url") or "").strip(),
        }
    if isinstance(child, (list, tuple)):
        keyword = child[0] if len(child) > 0 else ""
        html = child[1] if len(child) > 1 else ""
        url = child[2] if len(child) > 2 else ""
        return {
            "keyword": str(keyword or "").strip(),
            "html": str(html or "").strip(),
            "url": str(url or "").strip(),
        }
    return {"keyword": "", "html": "", "url": ""}


def _prefill_child_key(child):
    child = _normalize_completed_child(child)
    return (child.get("url") or child.get("keyword") or "").strip()


def _rank_prefill_child_posts_for_topic(topic_title, proposal, child_posts, limit=5):
    """この実行で作成した子記事の中から、内部リンク案に近いものを優先候補として返す。"""
    normalized = [_normalize_completed_child(c) for c in (child_posts or [])]
    topic_text = f"{topic_title}\n{proposal}"
    topic_queries = build_wp_search_queries(topic_title, proposal, max_queries=8)
    generic_terms = {
        "オンライン", "結婚相談所", "オンライン結婚相談所", "婚活",
        "方法", "コツ", "秘訣", "活用", "選び方", "比較", "徹底",
        "サービス", "記事", "読者", "新規", "作成",
    }
    topic_terms = []
    for q in topic_queries:
        for part in re.split(r"[\s　/・｜|、。:：（）()\[\]【】「」『』]+", q):
            part = part.strip()
            if len(part) >= 2 and part not in topic_terms:
                topic_terms.append(part)
    if topic_title and topic_title not in topic_terms:
        topic_terms.insert(0, topic_title)
    title_terms = []
    for part in re.split(r"[\s　/・｜|、。:：（）()\[\]【】「」『』]+", topic_title or ""):
        part = part.strip()
        if len(part) >= 2 and part not in generic_terms and part not in title_terms:
            title_terms.append(part)

    scored = []
    for idx, child in enumerate(normalized):
        haystack = f"{child.get('keyword', '')}\n{child.get('html', '')[:2000]}".lower()
        score = 0
        distinctive_hits = 0
        keyword_lower = child.get("keyword", "").lower()
        for term in title_terms:
            t = term.lower()
            if t in keyword_lower:
                score += 10
                distinctive_hits += 1
            elif t in haystack:
                score += 4
                distinctive_hits += 1
        for term in topic_terms:
            t = term.lower()
            if not t:
                continue
            if t in keyword_lower:
                score += 6
            elif t in haystack:
                score += 2
        if topic_title and topic_title.lower() in haystack:
            score += 10
            distinctive_hits += 1
        if distinctive_hits > 0 and score >= 8:
            scored.append((score, idx, child))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return [child for _, _, child in scored[:limit]]


def _generate_step9_batch(completed_children, site_config):
    """複数の子記事のメタ情報プロンプトを一括生成し、1つのファイルセレクターで表示する。"""
    _site_folder = re.sub(r'[\\/:*?"<>|]', '', site_config['name'])
    output_dir = os.path.join(AI_STUDIO_PROMPTS_DIR, _site_folder)
    os.makedirs(output_dir, exist_ok=True)

    step9_template = read_file(STEP9_META_FILE)
    if not step9_template:
        step9_template = "【メタ情報テンプレート（step9_meta.txt）が見つかりません】"
    live_site_context = build_live_site_context_for_step9(site_config)

    child_items = [_normalize_completed_child(c) for c in completed_children]
    generated_items = []
    for child in child_items:
        ckw = child.get("keyword", "")
        chtml = child.get("html", "")
        curl = child.get("url", "")
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        safe_kw = re.sub(r'[\\/:*?"<>|]', '', ckw[:20]) if ckw else "nokw"
        kw_line = f"キーワード: {ckw}" if ckw else "キーワード: （未入力）"
        url_line = f"投稿URL: {curl}" if curl else "投稿URL: （未取得）"
        step9_prompt = f"""=== 処理対象記事のコンテキスト（自動生成） ===
{kw_line}
{url_line}
生成日時: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}

{live_site_context}

=== 記事本文（HTML全文） ===
{chtml}

================================================================================
上記の記事に対して、以下の指示に従って処理を行ってください:
================================================================================

{step9_template}"""
        path = os.path.join(output_dir, f"[子]meta_prompt_{safe_kw}_{ts}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(step9_prompt)
        print(f"   ✅ メタ情報プロンプト保存: {os.path.basename(path)}")
        generated_items.append({"path": path, "keyword": ckw, "prompt": step9_prompt, "html": chtml, "url": curl})
        import time as _t; _t.sleep(1)  # タイムスタンプ重複防止
    generated_paths = [item["path"] for item in generated_items]

    # ── まとめてファイルセレクター表示 ──
    print("\n" + "="*60)
    print(f"✅ メタ情報プロンプト {len(generated_paths)}件 生成完了！")
    print("="*60)
    print(f"\n📁 保存先: {output_dir}")
    for p in generated_paths:
        print(f"  メタ情報: {os.path.basename(p)}")

    result_paths = []
    execution_mode = select_step9_10_execution_mode(f"子記事メタ情報 {len(generated_items)}件")
    if execution_mode is None:
        return
    batch_api_key = None
    if execution_mode in ("auto", "review"):
        api_keys = API_KEYS_MOECHIN if site_config.get("type") == "C" else API_KEYS_NORMAL
        batch_api_key = select_api_key(
            api_keys,
            title=(
                f"APIキー選択\n"
                f"  子記事メタ情報 {len(generated_items)}件をまとめて実行します。\n"
                f"  ここで選んだAPIキーを全件に使用します。"
            ),
        )
        if not batch_api_key:
            print("   ℹ️ APIキーが選択されなかったため、メタ情報API実行はスキップします。")
            execution_mode = "manual"
        for idx_item, item in enumerate(generated_items, start=1):
            if execution_mode not in ("auto", "review"):
                break
            print(f"\n--- 子記事メタ情報 {idx_item}/{len(generated_items)}: {item['keyword'][:50]} ---")
            result_data = run_step9_prompt_with_gemini(
                item["prompt"],
                site_config,
                item["keyword"],
                post_url=item.get("url", ""),
                rankmath_mode="auto" if execution_mode == "auto" else "ask",
                api_key=batch_api_key,
                article_role="child",
            )
            if result_data:
                if isinstance(result_data, dict):
                    if result_data.get("result_path"):
                        result_paths.append(result_data["result_path"])
                    if result_data.get("entry_sheet_path"):
                        result_paths.append(result_data["entry_sheet_path"])
                else:
                    result_paths.append(result_data)
            else:
                cont_idx = arrow_menu(
                    "子記事のメタ情報・入稿情報API生成に失敗しました。続けますか？",
                    [
                        "残りは実行せず、手動用ファイル作成のみで続行する",
                        "次の子記事でAPI実行を続ける",
                    ],
                    allow_back=False,
                )
                if cont_idx == 0:
                    break
    else:
        print("   ℹ️ 手動用ファイルのみ作成しました。Gemini APIは使用していません。")
        if result_paths:
            print("\n  ▼ メタ情報・入稿情報のAPI生成結果")
            for p in result_paths:
                print(f"  メタ情報関連ファイル: {os.path.basename(p)}")

    print()
    print("  ▼ 以下で開くファイルを選択してください（Space: 選択切替）")
    api_or_review = execution_mode in ("auto", "review") and bool(result_paths)
    entry_paths = [p for p in result_paths if _is_meta_entry_sheet_path(p)]
    if api_or_review and entry_paths:
        # API実行済みなら、通常確認に必要な入稿用サマリーだけを開く候補に出す。
        # 手動用プロンプト/API生ログは保存だけ行い、画面上の選択肢からは引く。
        open_paths = entry_paths
        labels = [f"【入稿用】{os.path.basename(p)}" for p in open_paths]
        defaults = [True] * len(open_paths)
        help_line = "  ※ API実行済みのため、通常確認に必要な入稿用サマリーだけ表示しています"
    elif api_or_review:
        open_paths = result_paths
        labels = [f"【API結果】{os.path.basename(p)}" for p in open_paths]
        defaults = [True] * len(open_paths)
        help_line = "  ※ 入稿用サマリーがないため、API結果だけ表示しています"
    else:
        open_paths = generated_paths + result_paths
        labels = [f"【プロンプト】{os.path.basename(p)}" for p in generated_paths]
        for p in result_paths:
            prefix = "【入稿用】" if _is_meta_entry_sheet_path(p) else "【API結果】"
            labels.append(f"{prefix}{os.path.basename(p)}")
        defaults = ([False] * len(generated_paths)) + [_is_meta_entry_sheet_path(p) for p in result_paths]
        help_line = "  ※ 手動実行時はAI Studio貼り付け用プロンプトも表示します"
    selected = arrow_menu_multiselect(
        "開くファイルを選択してください\n"
        "  Space: 選択切替   Enter: 選択したファイルを開く   ESC: 開かずに終了\n"
        f"{help_line}",
        labels, default_checked=defaults
    )
    for idx in selected:
        os.startfile(open_paths[idx])

    # ── 内部リンク判断プロンプト生成への導線 ──
    # 完成済み親記事のresumeだけを表示する（途中保存・空ログ相当は除外）
    _parent_candidates = get_complete_parent_resume_candidates(site_config, limit=5)
    if _parent_candidates:
        print()
        # 親記事候補を一覧表示（最新5件）
        _pr_options = []
        for _cand in _parent_candidates:
            try:
                _prd = _cand["data"]
                _pr_kw = _prd.get("target_input", "不明")[:30]
                _pr_ts = _prd.get("timestamp", "")
                _pr_time = _pr_ts.split(" ")[-1][:5] if " " in _pr_ts else ""
                _chars = html_to_char_count(_prd.get("final_content", ""))
                _pr_options.append(f"[{_pr_time}] KW: {_pr_kw}（本文{_chars:,}字）")
            except Exception:
                _pr_options.append(os.path.basename(_cand["path"]))
        _pr_options.append("終了（メインメニューへ戻る）")
        next_step = arrow_menu(
            "内部リンク判断も生成しますか？\n  対応する親記事を選択してください",
            _pr_options,
            allow_back=False
        )
        if next_step < len(_parent_candidates):
            _resume_data = _parent_candidates[next_step]["data"]
            if _resume_data:
                _parent_kw   = _resume_data.get("target_input", "")
                _parent_html = _resume_data.get("final_content", "")
                _step_outputs = _resume_data.get("step_outputs", {})
                run_step9_10(
                    prefill_keyword=_parent_kw,
                    prefill_html=_parent_html,
                    prefill_step_outputs=_step_outputs,
                    prefill_site=site_config,
                    skip_step9=True,
                    prefill_child_posts=generated_items,
                )
                return  # メタ情報・内部リンク処理内で完了表示されるので直接戻る
            else:
                print("   ⚠️ 親記事のresumeファイル読み込みに失敗しました")
    else:
        print("\n   ℹ️ 完成済みの親記事resumeが見つからないため、内部リンク判断はスキップします。")
    input("\nEnterでメインメニューに戻ります...")


def _extract_resume_article_title(data):
    """保存済み記事データから、利用者に見せる記事タイトルを取り出す。"""
    if not isinstance(data, dict):
        return ""
    for key in ("article_title", "post_title", "final_title", "title", "h1"):
        val = str(data.get(key) or "").strip()
        if val:
            return html.unescape(re.sub(r'<[^>]+>', '', val)).strip()
    content = str(data.get("final_content") or "")
    m = re.search(r'<h1[^>]*>(.*?)</h1>', content, re.DOTALL | re.IGNORECASE)
    if m:
        return html.unescape(re.sub(r'<[^>]+>', '', m.group(1))).strip()
    return ""


def _resume_data_matches_site(data, filename, output_site):
    """選択中サイトに対応する保存済み記事データだけを表示する。"""
    site_name = (output_site or {}).get("name", "")
    meta = data.get("metadata", {}) if isinstance(data, dict) else {}
    saved_site = str(meta.get("site_name") or "").strip()
    if saved_site:
        return saved_site == site_name

    bname = os.path.basename(filename or "")
    if site_name == "もえちん":
        return bname.startswith("resume_moechin") or bname.startswith("resume_child_moechin")
    return not (bname.startswith("resume_moechin") or bname.startswith("resume_child_moechin"))


def _build_resume_option_label(kind_label, data, fallback_filename=""):
    """保存済み記事データの選択肢を、記事タイトル優先で作る。"""
    keyword = str(data.get("target_input") or data.get("keyword") or "不明").strip()
    title = _extract_resume_article_title(data)
    timestamp = str(data.get("timestamp") or "").strip()
    time_part = timestamp.split(" ")[-1][:5] if " " in timestamp else ""
    date_part = timestamp.split(" ")[0].replace("-", "/") if " " in timestamp else ""
    head = f"{kind_label}"
    if date_part or time_part:
        head += f"  [{date_part} {time_part}]".rstrip()
    if title:
        return f"{head}\n    記事タイトル: {title[:70]}\n    キーワード: {keyword[:50]}"
    return f"{head}\n    キーワード: {keyword[:50]}\n    ファイル: {os.path.basename(fallback_filename)}"


def run_step9_10(prefill_keyword="", prefill_html="", prefill_step_outputs=None, prefill_site=None, child_article=False, skip_step9=False, prefill_child_posts=None, prefill_post_url=""):
    """モード5: メタ情報・内部リンク用プロンプト自動生成

    メタ情報: 監修者・カテゴリ・画像指示 → AI Studio貼り付け用プロンプト生成
    内部リンク: 内部リンク案ごとに既存記事と照合 → 判断プロンプト生成（1提案1ファイル）

    prefill_* が渡された場合はresumeファイル選択をスキップしてデータを直接使用する。
    skip_step9=True の場合はメタ情報をスキップして内部リンク判断のみ実行。
    child_article=True の場合は内部リンク判断をスキップしてメタ情報のみ実行。
    """
    prefill_child_posts = [_normalize_completed_child(c) for c in (prefill_child_posts or [])]
    # skip_step9 はメニュー選択で上書きされる場合があるので、引数の値を初期値として保持
    _skip_step9 = skip_step9
    _skip_step10 = child_article
    os.system('cls')
    print("=" * 60)
    print("  メタ情報・入稿情報／内部リンク判断")
    print("=" * 60)
    print()
    print("【メタ情報・入稿情報】SEOタイトル・説明文・カテゴリ等を生成（API/手動両対応）")
    print("【内部リンク判断】内部リンク案ごとに既存記事と照合し、挿入可否を判断（API/手動両対応）")
    print()

    # ─── サイト選択（保存先フォルダ決定・prefill_siteがない場合のみ） ───
    output_site = prefill_site
    if not output_site:
        _site_keys_all  = list(SITES_ALL.keys())
        _site_names_all = [v['name'] for v in SITES_ALL.values()]
        _site_sel = arrow_menu(
            "対象サイトを選択してください\n"
            "  ※ 保存先フォルダの整理に使用します（サイトごとにフォルダを分けます）",
            _site_names_all, allow_back=True
        )
        if _site_sel == -1:
            return
        output_site = SITES_ALL[_site_keys_all[_site_sel]]
    api_keys = api_keys_for_site(output_site)

    # サイト名でサブフォルダを作成
    _site_folder = re.sub(r'[\\/:*?"<>|]', '', output_site['name'])
    output_dir   = os.path.join(AI_STUDIO_PROMPTS_DIR, _site_folder)
    os.makedirs(output_dir, exist_ok=True)

    article_html = ""
    keyword      = ""
    step_outputs = {}
    article_post_url = prefill_post_url or ""

    # 直前の記事生成からデータを引き継いだ場合はresumeファイル選択をスキップ
    if prefill_keyword or prefill_html:
        keyword      = prefill_keyword
        article_html = prefill_html
        step_outputs = prefill_step_outputs or {}
        inherited_title = _extract_resume_article_title({"final_content": article_html, "target_input": keyword})
        if inherited_title:
            print(f"   ✅ 直前の記事データを引き継ぎました（記事タイトル: {inherited_title[:60]}）")
            print(f"      キーワード: {keyword[:50]}")
        else:
            print(f"   ✅ 直前の記事データを引き継ぎました（キーワード: {keyword[:40]}）")
        if article_post_url:
            print(f"   ✅ 投稿URLを引き継ぎました: {article_post_url}")
    else:
        # resume_dataフォルダ内のファイルを新しい順に収集
        # 同じキーワード＋種別の組み合わせは最新のみ表示（ステップごとの重複を排除）
        resume_options = []
        resume_files   = []
        if os.path.isdir(RESUME_DIR):
            _resume_glob = sorted(
                glob.glob(os.path.join(RESUME_DIR, "resume_*.json")),
                key=os.path.getmtime, reverse=True
            )
            _seen_keys = set()  # 種別+キーワードの重複排除用
            for rpath in _resume_glob:
                _bname = os.path.basename(rpath)
                try:
                    with open(rpath, "r", encoding="utf-8") as rf:
                        rd = json.load(rf)
                    if not _resume_data_matches_site(rd, _bname, output_site):
                        continue
                    rkw = str(rd.get("target_input", "不明"))[:50]
                except Exception:
                    rd = {}
                    rkw = "読込エラー"
                # ファイル名から種別を判別
                if _bname.startswith("resume_moechin"):
                    rlabel = "親記事・もえちん"
                    is_child = False
                elif _bname.startswith("resume_child"):
                    rlabel = "子記事★メタ情報のみ"
                    is_child = True
                else:
                    rlabel = "親記事・通常"
                    is_child = False
                # 同じ種別+キーワードは最新（最初に見つかったもの）のみ表示
                _dedup_key = f"{rlabel}|{rkw}"
                if _dedup_key in _seen_keys:
                    continue
                _seen_keys.add(_dedup_key)
                resume_options.append(_build_resume_option_label(rlabel, rd, rpath))
                resume_files.append((rpath, is_child))

        # resume_dataフォルダが空 or 無い場合は旧来のファイルもフォールバック表示
        if not resume_files:
            for rpath, rlabel, is_child in [
                (RESUME_NORMAL,       "親記事・通常",   False),
                (RESUME_MOECHIN,      "親記事・もえちん", False),
                (RESUME_CHILD_NORMAL, "子記事・通常★メタ情報のみ", True),
                (RESUME_CHILD_MOECHIN,"子記事・もえちん★メタ情報のみ", True),
            ]:
                if os.path.exists(rpath):
                    try:
                        with open(rpath, "r", encoding="utf-8") as rf:
                            rd = json.load(rf)
                        if not _resume_data_matches_site(rd, os.path.basename(rpath), output_site):
                            continue
                    except Exception:
                        rd = {"target_input": "読込エラー"}
                    resume_options.append(_build_resume_option_label(rlabel, rd, rpath))
                    resume_files.append((rpath, is_child))

        if not resume_files:
            # resumeファイルが1本もない → メニューを出さず直接入力へ
            print("   ℹ️  resumeファイルが見つかりません → 記事本文を手動入力します")
        else:
            resume_options.append("スキップ（記事本文を手動入力）")
            resume_idx = arrow_menu(
                "処理対象の記事を選択してください\n"
                "  ※ 内部リンク判断では、ここで選んだ親記事に内部リンクを入れる前提です。",
                resume_options,
                allow_back=True
            )
            if resume_idx == -1:
                return

            if resume_idx < len(resume_files):
                fpath, is_child = resume_files[resume_idx]
                data = load_resume_data(fpath)
                if data:
                    keyword      = data.get("target_input", "")
                    article_html = data.get("final_content", "")
                    step_outputs = data.get("step_outputs", {})
                    article_post_url = (
                        data.get("post_url")
                        or data.get("wordpress_url")
                        or data.get("url")
                        or ""
                    )
                    if is_child:
                        child_article = True
                        _skip_step10 = True
                    loaded_title = _extract_resume_article_title(data)
                    if loaded_title:
                        print(f"   ✅ {os.path.basename(fpath)} 読み込み完了")
                        print(f"      記事タイトル: {loaded_title[:70]}")
                        print(f"      キーワード: {keyword[:50]}")
                    else:
                        print(f"   ✅ {os.path.basename(fpath)} 読み込み完了（キーワード: {keyword[:30]}）")
                    if child_article:
                        print("   ℹ️  子記事モード: メタ情報のみ生成します（内部リンクはスキップ）")
            else:
                print("   → 記事本文を手動入力します")

    if not article_html:
        # child_article が未確定の場合（手動入力モード）は先に種別を選んでもらう
        if not child_article:
            art_choice = arrow_menu(
                "実行内容を選択してください\n"
                "\n"
                "  ■ 1: 親記事を作成した直後\n"
                "       → メタ情報＋内部リンク を両方実行\n"
                "\n"
                "  ■ 2: 子記事作成後・親記事に内部リンクを追加したい\n"
                "       → 内部リンクのみ実行（メタ情報はスキップ）\n"
                "       ※ 子記事を作ってペンディングの内部リンクを処理する場合もこれ\n"
                "\n"
                "  ■ 3: 子記事を作成した直後\n"
                "       → メタ情報のみ実行（内部リンクはスキップ）",
                [
                    "メタ情報＋内部リンク を両方実行（親記事作成直後・初回）",
                    "内部リンクのみ実行（子記事作成後・内部リンク追加）",
                    "メタ情報のみ実行（子記事作成直後）",
                ],
                allow_back=True
            )
            if art_choice == -1:
                return  # メインメニューへ戻る
            if art_choice == 1:
                _skip_step9 = True   # 内部リンク判断のみ
            elif art_choice == 2:
                child_article = True  # メタ情報のみ（内部リンク判断スキップ）
                _skip_step10 = True
            else:
                _skip_step9 = False  # メタ情報＋内部リンク判断（デフォルト）

        # ── 親記事モード（内部リンク判断あり）は先に内部リンクファイルを選択しキーワードを自動取得 ──
        # （子記事メタ情報のみモードは内部リンク不要のためスキップ）
        internal_links_text = ""
        if step_outputs:
            internal_links_text = extract_internal_links(step_outputs)
            if internal_links_text:
                print(f"   ✅ 内部リンク案を自動抽出しました")

        if not internal_links_text and not child_article:
            # 今日の日付でフィルタリング（例: _20260401_）。無ければ全件表示
            today_str = datetime.datetime.now().strftime('%Y%m%d')
            all_raw = sorted(
                glob.glob(os.path.join(PARENT_WORDPRESS_DATA, "internal_links_*.txt")),
                key=os.path.getmtime, reverse=True
            )
            today_files = [f for f in all_raw if f"_{today_str}_" in os.path.basename(f)]
            show_all = False
            if today_files:
                all_links_files = today_files
            else:
                all_links_files = all_raw
                show_all = True

            if all_links_files:
                file_options = [os.path.basename(f) for f in all_links_files]
                if today_files and all_raw != today_files:
                    file_options.append("📅 過去の日付も表示する")
                file_options.append("読み込まない（スキップ）")
                header = "【内部リンクファイルを選択してください】\n"
                if not show_all:
                    header += f"  ※ 今日（{today_str[:4]}/{today_str[4:6]}/{today_str[6:]}）のファイルのみ表示中\n"
                header += "  ※ キーワードと内部リンク案もここから自動取得されます"
                file_idx = arrow_menu(header, file_options, allow_back=True)

                # 「過去の日付も表示する」が選ばれた場合
                if not show_all and today_files and file_idx == len(today_files):
                    all_links_files = all_raw
                    file_options = [os.path.basename(f) for f in all_links_files]
                    file_options.append("読み込まない（スキップ）")
                    file_idx = arrow_menu(
                        "【内部リンクファイルを選択（全件表示）】\n"
                        "  ※ キーワードと内部リンク案もここから自動取得されます",
                        file_options, allow_back=True
                    )
                if file_idx == -1:
                    return
                if file_idx < len(all_links_files):
                    internal_links_text = read_file(all_links_files[file_idx])
                    if internal_links_text:
                        print(f"   ✅ 読み込み完了: {file_options[file_idx]}")
                        # ファイルヘッダーからキーワードを自動抽出
                        if not keyword:
                            kw_m = re.search(r'【ターゲットキーワード】\s*(.+)', internal_links_text)
                            if kw_m:
                                keyword = kw_m.group(1).strip()
                                print(f"   ✅ キーワードを自動取得: {keyword}")
            else:
                print("   ℹ️ 内部リンクファイルが見つかりませんでした")

        # ── HTML入力 ──
        article_type = "子記事" if child_article else "親記事"
        print(f"\n【{article_type}の記事本文HTML を貼り付けてください】")
        print(f"  Step8まで生成した{article_type}の完成HTMLをそのまま貼り付けてください。")
        print(f"  （WordPressに投稿済みの本文HTMLでOKです）")
        print(f"  ※ 貼り付け後、Enter を5回連続で押すと確定します（または EOF と入力してEnter）")
        article_html = get_multiline_input("", eof_mode=True)

        # 子記事メタ情報: <h1>タグからキーワード（トピック）を自動抽出
        if child_article and not keyword and article_html:
            h1_m = re.search(r'<h1[^>]*>(.*?)</h1>', article_html, re.DOTALL | re.IGNORECASE)
            if h1_m:
                keyword = re.sub(r'<[^>]+>', '', h1_m.group(1)).strip()
                print(f"   ✅ タイトルを自動取得: {keyword}")

    else:
        # prefillあり（親記事生成直後の引き継ぎ）: step_outputsから内部リンクを抽出
        internal_links_text = ""
        if step_outputs:
            internal_links_text = extract_internal_links(step_outputs)
            if internal_links_text:
                print(f"   ✅ 内部リンク案を自動抽出しました")

    # キーワードが依然として未取得の場合のみ手動入力を求める
    if not keyword:
        if child_article:
            print("\n【トピック案入力（省略可）】")
            print("  子記事のタイトル（トピック案）をそのまま入力してください。")
            print("  ※ Enterのみで省略できます")
            keyword = input("  トピック案: ").strip()
        else:
            print("\n【キーワード入力（省略可）】")
            print("  記事作成時に入力したキーワードをそのまま入力してください。")
            print("  ※ Enterのみで省略できます")
            keyword = input("  キーワード: ").strip()

    # prefillありの場合で内部リンクがまだ未取得なら、ファイルから補完
    if not internal_links_text and not child_article:
        _site_filter = None
        if output_site:
            for _k, _v in SITES_ALL.items():
                if _v.get("name") == output_site.get("name"):
                    _site_filter = "moechin" if output_site.get("type") == "C" else _k
                    break
        found_links_text, found_label = find_internal_links_text_for_keyword(keyword, site_filter=_site_filter)
        if found_links_text:
            internal_links_text = found_links_text
            print(f"   ✅ 内部リンク案を補完しました: {found_label}")

    if not internal_links_text and not child_article and not step_outputs:
        safe_kw_search = keyword[:10] if keyword else ""
        links_files = sorted(
            glob.glob(os.path.join(PARENT_WORDPRESS_DATA, f"internal_links_*{safe_kw_search}*.txt")),
            key=os.path.getmtime, reverse=True
        )
        if links_files:
            file_options = [os.path.basename(f) for f in links_files]
            file_options.append("読み込まない（スキップ）")
            file_idx = arrow_menu(
                "内部リンクファイルを選択してください\n"
                "  ※ PC識別子・タイムスタンプを確認して対象の作業に対応するファイルを選択",
                file_options, allow_back=True
            )
            if file_idx == -1:
                return
            if file_idx < len(links_files):
                internal_links_text = read_file(links_files[file_idx])
                if internal_links_text:
                    print(f"   ✅ 読み込み完了: {file_options[file_idx]}")

    if not internal_links_text and not child_article:
        print("   ℹ️ 内部リンク案が見つかりませんでした（内部リンク判定はスキップされます）")

    if not article_post_url and keyword and output_site and not child_article:
        found_url, found_log = find_latest_post_url_for_keyword(keyword, output_site)
        if found_url:
            article_post_url = found_url
            print(f"   ✅ 投稿URLを親記事ログから補完しました: {article_post_url}")
            print(f"      参照ログ: {found_log}")

    if not child_article and internal_links_text:
        existing_meta_files = find_recent_meta_entry_sheets(output_site.get("name", "") if output_site else "", keyword)
        post_brief = fetch_wordpress_post_brief(output_site, article_post_url) if article_post_url and output_site else {}
        post_status = str(post_brief.get("status") or "").strip()
        meta_done = bool(existing_meta_files) or (post_status and post_status != "draft")

        if meta_done:
            mode_title = (
                "親記事の次に行う作業を選択してください\n"
                "\n"
                "  ⚠️ この親記事には、メタ情報・入稿情報の作成履歴があります。\n"
                "     ここでメタ情報を再生成すると、SEOタイトル/説明文/カテゴリ候補を作り直します。\n"
            )
            if post_status:
                mode_title += f"     投稿状態: {'公開済み' if post_status == 'publish' else post_status}\n"
            if existing_meta_files:
                mode_title += f"     既存のSEO/カテゴリ確認用ファイル: {os.path.basename(existing_meta_files[0])}\n"
            mode_title += (
                "\n"
                "  ─ 選び方の目安 ─\n"
                "  ・SEOタイトル/説明文/カテゴリ確認用ファイルを作成済みなら、基本は 1 です。\n"
                "  ・SEOタイトルや説明文を作り直したい時だけ、2 または 3 を選びます。\n"
                "\n"
                "  ■ 1. 内部リンクだけ確認する\n"
                "     使う場面: メタ情報は終わっていて、親記事に貼る内部リンクだけ確認したい時。\n"
                "     既存記事や作成済み子記事を探し、親記事へリンクするか判断します。\n"
                "     メタ情報・投稿タイトル・スラッグ・カテゴリ候補は作り直しません。\n"
                "\n"
                "  ■ 2. メタ情報を作り直して、内部リンクも確認する\n"
                "     使う場面: 親記事のSEOタイトル/説明文/カテゴリ候補を作り直し、内部リンクも確認したい時。\n"
                "     既存のメタ情報・入稿用サマリーとは別に、新しい結果を生成します。\n"
                "\n"
                "  ■ 3. メタ情報だけ作り直す\n"
                "     使う場面: 親記事のSEOタイトル/説明文/カテゴリ候補だけ作り直したい時。\n"
                "     内部リンク検索はしません。"
            )
            mode_options = [
                "内部リンクだけ確認（メタ情報は触らない）",
                "メタ情報を作り直し＋内部リンクも確認",
                "メタ情報だけ作り直し（内部リンクなし）",
            ]
            mode_actions = ["internal_only", "both", "meta_only"]
        else:
            mode_title = (
                "親記事の次に行う作業を選択してください\n"
                "\n"
                "  ─ 選び方の目安 ─\n"
                "  ・親記事を作成した直後の通常の続きは 1 です。\n"
                "  ・メタ情報をあとで作る、または入稿済みで内部リンクだけ確認したい時は 2 です。\n"
                "  ・内部リンクを後回しにして、親記事のメタ情報だけ作りたい時は 3 です。\n"
                "\n"
                "  ■ 1. メタ情報を作成して、内部リンクも確認する\n"
                "     使う場面: 親記事作成後の通常の続きとして、入稿用情報と内部リンクをまとめて進めたい時。\n"
                "     SEOタイトル/説明文/カテゴリ候補を作成してから、内部リンクも確認します。\n"
                "\n"
                "  ■ 2. 内部リンクだけ確認する\n"
                "     使う場面: 親記事のメタ情報は作らず、内部リンク候補だけ確認したい時。\n"
                "     既存記事や作成済み子記事を探し、親記事へリンクするか判断します。\n"
                "     SEOタイトル/説明文/カテゴリ候補は作りません。\n"
                "\n"
                "  ■ 3. メタ情報だけ作成する\n"
                "     使う場面: 親記事のSEOタイトル/説明文/カテゴリ候補だけ先に作りたい時。\n"
                "     内部リンク検索はしません。子記事のメタ情報作成ではありません。"
            )
            mode_options = [
                "メタ情報を作成＋内部リンクも確認",
                "内部リンクだけ確認（メタ情報は作らない）",
                "メタ情報だけ作成（内部リンクなし）",
            ]
            mode_actions = ["both", "internal_only", "meta_only"]

        mode_idx = arrow_menu(
            mode_title,
            mode_options,
            allow_back=True,
        )
        if mode_idx == -1:
            return
        mode_action = mode_actions[mode_idx]
        if mode_action == "internal_only":
            _skip_step9 = True
        elif mode_action == "meta_only":
            _skip_step10 = True

    needs_step9 = not _skip_step9
    needs_step10 = (not _skip_step10 and bool(internal_links_text))
    execution_mode = "review"
    if needs_step9 and needs_step10:
        execution_mode = select_step9_10_execution_mode("メタ情報・入稿情報／内部リンク判断")
        if execution_mode is None:
            return
    elif needs_step9:
        execution_mode = select_step9_10_execution_mode("メタ情報・入稿情報")
        if execution_mode is None:
            return
    elif needs_step10:
        execution_mode = select_internal_link_execution_mode()
        if execution_mode is None:
            return

    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_kw = re.sub(r'[\\/:*?"<>|]', '', keyword[:20]) if keyword else "nokw"
    os.makedirs(output_dir, exist_ok=True)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # メタ情報プロンプト生成
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    step9_output_path = None
    step9_api_result_path = None
    step9_entry_sheet_path = None
    step9_apply_status = "未実行"
    if _skip_step9:
        print("\n" + "="*60)
        print("  【メタ情報】スキップ（内部リンクのみ実行モード）")
        print("="*60)
    else:
        print("\n" + "="*60)
        print("  【メタ情報】プロンプトを生成中...")
        print("="*60)

        step9_template = read_file(STEP9_META_FILE)
        if not step9_template:
            print(f"   ❌ {STEP9_META_FILE} が見つかりません。")
            step9_template = "【メタ情報テンプレート（step9_meta.txt）が見つかりません。手動でプロンプトを入力してください】"
        live_site_context = build_live_site_context_for_step9(output_site)

        kw_line = f"キーワード: {keyword}" if keyword else "キーワード: （未入力）"
        url_line = f"投稿URL: {article_post_url}" if article_post_url else "投稿URL: （未取得）"
        step9_prompt = f"""=== 処理対象記事のコンテキスト（自動生成） ===
{kw_line}
{url_line}
生成日時: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}

{live_site_context}

=== 記事本文（HTML全文） ===
{article_html}

================================================================================
上記の記事に対して、以下の指示に従って処理を行ってください:
================================================================================

{step9_template}"""

        article_prefix = "[子]" if child_article else "[親]"
        step9_output_path = os.path.join(output_dir, f"{article_prefix}meta_prompt_{safe_kw}_{ts}.txt")
        with open(step9_output_path, "w", encoding="utf-8") as f:
            f.write(step9_prompt)
        print(f"   ✅ メタ情報プロンプト保存: {os.path.basename(step9_output_path)}")
        run_step9_api = False
        if execution_mode == "auto":
            run_step9_api = True
        elif execution_mode == "review":
            run_idx = arrow_menu(
                "メタ情報・入稿情報をGemini APIで今すぐ生成しますか？\n"
                "  ※ API無料枠を少し消費します。上限が心配な場合は手動用ファイルのみを選んでください。",
                [
                    "手動用ファイルのみ作る（AI Studioで実行・API消費なし）",
                    "Gemini APIでメタ情報・入稿情報を生成する",
                ],
                allow_back=False,
            )
            run_step9_api = (run_idx == 1)
        else:
            print("   ℹ️ 手動用ファイルのみ作成しました。メタ情報・入稿情報のAPI生成は使用していません。")

        if run_step9_api:
            step9_data = run_step9_prompt_with_gemini(
                step9_prompt,
                output_site,
                keyword,
                post_url=article_post_url,
                rankmath_mode="auto" if execution_mode == "auto" else "ask",
                article_role="child" if child_article else "parent",
            )
            if isinstance(step9_data, dict):
                step9_api_result_path = step9_data.get("result_path")
                step9_entry_sheet_path = step9_data.get("entry_sheet_path")
                if step9_data.get("applied"):
                    step9_apply_status = step9_data.get("apply_message") or "WordPress標準項目へ反映済み"
                elif step9_data.get("post_url"):
                    step9_apply_status = "自動反映なし（入稿用サマリーで手動反映）"
                else:
                    step9_apply_status = "投稿URL未取得のため自動反映なし"
            else:
                step9_api_result_path = step9_data

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 内部リンク案ごとに個別プロンプト生成
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    step10_output_paths = []
    step10_api_result_paths = []
    skipped_proposals   = []
    step10_attention_events = []
    skipped_existing_internal_links = []
    pending_path        = None
    proposals = [] if (child_article or _skip_step10) else (
        parse_internal_link_proposals(internal_links_text) if internal_links_text else []
    )

    if not proposals:
        if child_article:
            print(f"\n   ℹ️  子記事モード: 内部リンク判定をスキップします")
        elif _skip_step10:
            print(f"\n   ℹ️  メタ情報のみ実行モード: 内部リンク判定をスキップします")
        else:
            print(f"\n   ℹ️ 内部リンク案が見つからないため内部リンク判定をスキップします。")
    else:
        print(f"\n{'='*60}")
        print(f"  【内部リンク】判断プロンプト生成")
        print(f"  内部リンク案: {len(proposals)}件")
        print(f"{'='*60}")

        # 内部リンク先検索は、対象記事のサイトをそのまま使う。
        # ここで再度サイトを選ばせると、同じ作業内でサイト選択が重複して迷いの原因になる。
        step10_site = output_site
        print(f"   ℹ️ 内部リンク検索サイト: {step10_site.get('name', '')}（対象サイトを使用）")

        step10_template = read_file(STEP10_FILE)
        if not step10_template:
            print(f"   ❌ {STEP10_FILE} が見つかりません。")
            step10_template = ""
        step10_completed_fields = []
        step10_manual_wait_paths = []

        step10_api_key = None
        run_step10_api = False
        if execution_mode == "auto":
            run_step10_api = True
            print(f"   ℹ️ Gemini APIで内部リンク判断結果まで作ります（内部リンク案 {len(proposals)}件分のAPI無料枠を消費します）。")
            print("      ※ 親記事本文へのリンク挿入は自動では行いません。")
        elif execution_mode == "review":
            step10_run_idx = arrow_menu(
                "内部リンク判断結果をGemini APIで作りますか？\n"
                "  ※ 手動用ファイルはどちらでも作成します。\n"
                "  ※ Gemini APIを選ぶと、内部リンク案ごとにAPI無料枠を消費します。\n"
                "  ※ 親記事本文へのリンク挿入は自動では行いません。",
                [
                    "手動用ファイルのみ作る（API消費なし・AI Studioで判断）",
                    "Gemini APIで判断結果まで作る（API消費あり・本文は変更しない）",
                ],
                allow_back=False,
            )
            run_step10_api = (step10_run_idx == 1)
        else:
            print("   ℹ️ 手動用ファイルのみ: Gemini APIは使用しません。AI Studioで判断してください。")

        if run_step10_api:
            step10_api_key = select_api_key(api_keys)
            if not step10_api_key:
                print("   ℹ️ APIキーが選択されなかったため、内部リンク判断は手動用ファイル作成のみで続行します。")

        PAGE_SIZE = 10

        def _skipped_num(item):
            return item.get("num") if isinstance(item, dict) else item[0]

        def _skipped_title(item):
            return item.get("title") if isinstance(item, dict) else item[1]

        def _skipped_proposal(item):
            return item.get("proposal") if isinstance(item, dict) else item[2]

        def _add_skipped_proposal(num, title, proposal, reason="", existing_title="", existing_url="", source_path=""):
            """子記事作成リストへ回す理由も一緒に保持する。"""
            for item in skipped_proposals:
                if _skipped_num(item) == num:
                    if isinstance(item, dict) and reason and not item.get("reason"):
                        item["reason"] = reason
                    return
            skipped_proposals.append({
                "num": num,
                "title": title,
                "proposal": proposal,
                "reason": reason,
                "existing_title": existing_title,
                "existing_url": existing_url,
                "source_path": source_path,
            })

        def make_post_label(p):
            t    = p.get('title', {}).get('rendered', '')
            dt   = p.get('date', '')[:10]
            cd   = p.get('content', {})
            html = cd.get('rendered', '') if isinstance(cd, dict) else ''
            wc   = html_to_char_count(html)
            status_tag = "📝下書き " if p.get('status') == 'draft' else ""
            return f"[{status_tag}本文:{wc:,}文字 / {dt}] {t}"

        def rank_posts_for_internal_link(posts, topic_title, proposal, search_kw):
            """WordPress検索結果を内部リンク案との一致度で並べ直し、明らかに薄い候補を落とす。"""
            if not posts:
                return []
            def _norm_match_text(s):
                s = html.unescape(re.sub(r'<[^>]+>', '', str(s or "")))
                s = re.sub(r'[\s　、。，．・/／｜|:：;；!！?？「」『』【】\[\]（）()〜～ー\-]+', '', s)
                return s.lower()

            broad_terms = {
                "結婚相談所", "アンテナ", "アンテナ工事", "費用", "料金", "方法", "比較",
                "選び方", "口コミ", "評判", "トラブル", "業者", "相談所",
            }
            terms = []
            for src in (topic_title, proposal, search_kw):
                for term in _wp_search_terms_from_text(src or ""):
                    if term not in terms:
                        terms.append(term)
            specific_terms = [t for t in terms if t not in broad_terms and len(t) >= 3]
            quoted_terms = []
            # 役割説明文中の「どんなアンテナが良いのか」等は検索意図の説明であり、
            # 候補記事タイトルに含まれないことが多いため、必須語にはしない。
            for src in (topic_title or "",):
                for q in re.findall(r'[「『](.*?)[」』]', src):
                    q = q.strip()
                    if q and q not in broad_terms and not re.search(r'どんな|良いのか|何を|どう', q) and q not in quoted_terms:
                        quoted_terms.append(q)
            required_terms = specific_terms[:4] or terms[:3]
            topic_norm = _norm_match_text(topic_title)
            topic_core_norm = topic_norm[:18]

            ranked = []
            for post in posts:
                title = re.sub(r'<[^>]+>', '', post.get('title', {}).get('rendered', '') or '')
                cd = post.get('content', {})
                body_html = cd.get('rendered', '') if isinstance(cd, dict) else ''
                body = re.sub(r'<[^>]+>', ' ', body_html or '')
                hay_title = html.unescape(title)
                hay_body = html.unescape(body[:4000])
                hay_title_norm = _norm_match_text(hay_title)
                exactish_title_match = bool(
                    topic_core_norm and len(topic_core_norm) >= 8 and topic_core_norm in hay_title_norm
                )
                score = 0
                hits = []
                for term in terms:
                    if not term:
                        continue
                    if term in hay_title:
                        score += 5 if term in specific_terms else 2
                        hits.append(term)
                    elif term in hay_body:
                        score += 2 if term in specific_terms else 1
                        hits.append(term)
                if exactish_title_match:
                    score += 30
                if quoted_terms and not any(q in hay_title or q in hay_body for q in quoted_terms):
                    continue
                # 特定語があるのに1つも当たらない記事は、広い検索語だけで拾われた可能性が高い。
                if specific_terms and not exactish_title_match and not any(t in hits for t in specific_terms):
                    continue
                if required_terms and not exactish_title_match and not any(t in hits for t in required_terms):
                    continue
                ranked.append((score, post))
            ranked.sort(key=lambda x: x[0], reverse=True)
            return [p for _, p in ranked]

        def merge_internal_link_search_results(search_terms, topic_title, proposal):
            """複数の検索語を一括検索し、同じ投稿を1件にまとめる。"""
            merged = []
            fallback = []
            seen = set()
            fallback_seen = set()

            def _post_key(post):
                return str(post.get("id") or post.get("link") or post.get("slug") or post.get("date") or post.get("title", {}).get("rendered", ""))

            for term in search_terms:
                term = (term or "").strip()
                if not term:
                    continue
                print(f"   🔍 '{term}'")
                raw_posts = search_wordpress_posts(step10_site, term)
                ranked_posts = rank_posts_for_internal_link(raw_posts, topic_title, proposal, term)
                for post in ranked_posts:
                    key = _post_key(post)
                    if key and key not in seen:
                        seen.add(key)
                        merged.append(post)
                for post in raw_posts:
                    key = _post_key(post)
                    if key and key not in seen and key not in fallback_seen:
                        fallback_seen.add(key)
                        fallback.append(post)

            if not merged and fallback:
                print("   ℹ️ 一致度の高い候補は見つかりませんでした。確認用に検索結果をまとめて表示します。")
                return fallback
            return merged

        used_prefill_child_keys = set()
        for i, proposal in enumerate(proposals):
            topic_title = extract_topic_title(proposal)
            ts_item = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')

            print(f"\n{'─'*60}")
            print(f"  内部リンク案 {i+1}/{len(proposals)}: {topic_title}")
            print(f"{'─'*60}")
            for line in proposal.split('\n')[:5]:
                if line.strip():
                    print(f"  {line.strip()}")
            print()

            # ─── 既存の内部リンク判断ファイルの検出 ───
            existing_step10_files, existing_step10_api_files = find_existing_internal_link_artifacts(
                topic_title,
                keyword,
                i + 1,
            )
            already_done_note = ""
            # ─── 処理方法を先に選択 ───
            action_kind = "generate"
            if existing_step10_api_files:
                existing_fname = os.path.basename(existing_step10_api_files[-1])
                existing_api_fields_for_menu = _read_internal_link_result_fields_from_path(existing_step10_api_files[-1])
                existing_location_error_for_menu = _internal_link_location_error(existing_api_fields_for_menu, article_html)
                existing_api_state_for_menu = _internal_link_result_state(existing_api_fields_for_menu)
                existing_api_menu_mode = ""
                if existing_location_error_for_menu:
                    repair_candidate = _suggest_internal_link_location_from_parent(existing_api_fields_for_menu, article_html)
                    if repair_candidate and existing_api_state_for_menu == "actionable":
                        existing_api_menu_mode = "repairable_location"
                        action_ctx = (
                            f"【内部リンク案 {i+1}/{len(proposals)}】\n{topic_title}\n"
                            f"\n"
                            f"  ⚠️ 既存API結果の貼り付け位置が親記事本文に見つかりません:\n"
                            f"     {existing_fname}\n"
                            f"\n"
                            f"  理由: {existing_location_error_for_menu}\n"
                            f"  ただし、親記事本文内に近い実在位置を検出しました。\n"
                            f"  補正先見出し: {repair_candidate.get('heading_text')}\n"
                            f"  補正先段落: {repair_candidate.get('anchor_text')}"
                        )
                        action_options = [
                            "推奨: 親記事本文の実在位置へ補正して使う",
                            "再検索して内部リンク判断を作り直す",
                            "ここまで保存して今回の内部リンク処理を終了する",
                        ]
                        action_menu_title = (
                            "この内部リンク案の処理方法を選択\n"
                            "\n"
                            "  既存API結果の貼り付け位置は壊れていますが、ツールが親記事本文内の補正先を見つけました。\n"
                            "  そのまま進む場合は、補正済みの貼り付け案として保存します。"
                        )
                    else:
                        existing_api_menu_mode = "invalid_location"
                        action_ctx = (
                            f"【内部リンク案 {i+1}/{len(proposals)}】\n{topic_title}\n"
                            f"\n"
                            f"  ⚠️ 既存API結果の貼り付け位置が親記事本文に見つかりません:\n"
                            f"     {existing_fname}\n"
                            f"\n"
                            f"  理由: {existing_location_error_for_menu}\n"
                            f"  このまま使うと、親記事内で貼り付け場所を探せません。"
                        )
                        action_options = [
                            "推奨: 再検索して内部リンク判断を作り直す",
                            "この壊れた位置の結果を未反映として残す（貼り付け案には入れない）",
                            "ここまで保存して今回の内部リンク処理を終了する",
                        ]
                        action_menu_title = (
                            "この内部リンク案の処理方法を選択\n"
                            "\n"
                            "  既存API結果はありますが、貼り付け位置が親記事本文に存在しません。\n"
                            "  親記事へ貼るには、再検索して判断を作り直してください。"
                        )
                elif existing_api_state_for_menu == "needs_child":
                    existing_api_menu_mode = "normal"
                    action_ctx = (
                        f"【内部リンク案 {i+1}/{len(proposals)}】\n{topic_title}\n"
                        f"\n"
                        f"  ⚠️ 既存のAPI判断結果は「非推奨」です:\n"
                        f"     {existing_fname}\n"
                        f"\n"
                        f"  この結果を使う場合、この候補は【最終貼り付け案】には入りません。\n"
                        f"  子記事作成リストへ回します。"
                    )
                    action_options = [
                        "この非推奨結果を使う（子記事作成リストへ回す・再生成しない）",
                        "別の既存記事で再検索して判断を作り直す",
                        "ここまで保存して今回の内部リンク処理を終了する",
                    ]
                    action_menu_title = (
                        "この内部リンク案の処理方法を選択\n"
                        "\n"
                        "  既存API結果は、選択済み既存記事への内部リンクを非推奨と判断しています。\n"
                        "  貼り付けHTMLには入りません。別記事で試す場合だけ「再検索」を選びます。"
                    )
                elif existing_api_state_for_menu == "actionable":
                    existing_api_menu_mode = "normal"
                    action_ctx = (
                        f"【内部リンク案 {i+1}/{len(proposals)}】\n{topic_title}\n"
                        f"\n"
                        f"  ✅ 親記事へ貼れるAPI判断結果がすでに存在します:\n"
                        f"     {existing_fname}"
                    )
                    action_options = [
                        "このAPI結果を使う（再生成しない）",
                        "再検索して内部リンク判断ファイルを上書き生成する",
                        "ここまで保存して今回の内部リンク処理を終了する",
                    ]
                    action_menu_title = (
                        "この内部リンク案の処理方法を選択\n"
                        "\n"
                        "  親記事へ貼るAPI判断結果がすでにあります。\n"
                        "  子記事を作り直した等で再生成が必要な場合のみ「再検索」を選択します。"
                    )
                else:
                    existing_api_menu_mode = "normal"
                    action_ctx = (
                        f"【内部リンク案 {i+1}/{len(proposals)}】\n{topic_title}\n"
                        f"\n"
                        f"  ⚠️ API判断結果はありますが、貼り付けHTMLを確定できていません:\n"
                        f"     {existing_fname}"
                    )
                    action_options = [
                        "この未確定結果を使う（貼り付け案には入れず、理由だけ残す）",
                        "再検索して内部リンク判断ファイルを上書き生成する",
                        "ここまで保存して今回の内部リンク処理を終了する",
                    ]
                    action_menu_title = (
                        "この内部リンク案の処理方法を選択\n"
                        "\n"
                        "  既存API結果から、貼り付け位置または挿入HTMLを確定できていません。\n"
                        "  最終貼り付け案に入れたい場合は「再検索」を選びます。"
                    )
            elif existing_step10_files:
                existing_fname = os.path.basename(sorted(existing_step10_files, key=os.path.getmtime)[-1])
                action_ctx = (
                    f"【内部リンク案 {i+1}/{len(proposals)}】\n{topic_title}\n"
                    f"\n"
                    f"  ⚠️ 手動用の内部リンク判断ファイルはありますが、API判断結果はありません:\n"
                    f"     {existing_fname}"
                )
                if step10_api_key:
                    action_options = [
                        "検索して内部リンク判断を作る（API結果まで作る）",
                        "スキップ（対応する子記事をまだ作成していない）",
                        "ここまで保存して今回の内部リンク処理を終了する",
                    ]
                else:
                    action_options = [
                        "Gemini APIで判断結果まで作る（貼り付け指示まとめに入れる）",
                        "手動用ファイルだけ作る（貼り付け指示まとめには入らない）",
                        "スキップ（対応する子記事をまだ作成していない）",
                        "ここまで保存して今回の内部リンク処理を終了する",
                    ]
                action_menu_title = (
                    "この内部リンク案の処理方法を選択\n"
                    "\n"
                    "  手動用ファイルだけでは、親記事に貼る最終案には入りません。\n"
                    "  貼り付け指示まとめに入れるには、既存記事または作成済み子記事を選び、API判断結果を作る必要があります。"
                )
            else:
                action_ctx = (
                    f"【内部リンク案 {i+1}/{len(proposals)}】\n{topic_title}"
                )
                action_options = [
                    "検索して内部リンク判断ファイルを生成（子記事作成済みの場合もこれ）",
                    "スキップ（対応する子記事をまだ作成していない）",
                    "ここまで保存して今回の内部リンク処理を終了する",
                ]
                action_menu_title = (
                    "この内部リンク案の処理方法を選択\n"
                    "\n"
                    "  ■ 1: WordPressで既存記事または新規作成した子記事を検索し\n"
                    "       内部リンク判断ファイルを生成する\n"
                    "       （子記事を作成済みでここに戻ってきた場合もこちら）\n"
                    "\n"
                    "  ■ 2: スキップ\n"
                    "       （対応する子記事をまだ作成していない場合）"
                )

            action_choice = arrow_menu(
                action_menu_title,
                action_options,
                allow_back=False,
                context=action_ctx
            )

            item_step10_api_key = step10_api_key
            if existing_step10_api_files:
                if existing_api_menu_mode == "repairable_location":
                    if action_choice == 0:
                        action_kind = "use_existing_api"
                    elif action_choice == 1:
                        action_kind = "generate"
                    else:
                        action_kind = "stop"
                elif existing_api_menu_mode == "invalid_location":
                    if action_choice == 0:
                        action_kind = "generate"
                    elif action_choice == 1:
                        action_kind = "use_existing_api"
                    else:
                        action_kind = "stop"
                else:
                    if action_choice == 0:
                        action_kind = "use_existing_api"
                    elif action_choice == 1:
                        action_kind = "generate"
                    else:
                        action_kind = "stop"
            elif existing_step10_files:
                if step10_api_key:
                    if action_choice == 0:
                        action_kind = "generate"
                    elif action_choice == 1:
                        action_kind = "skip_pending"
                    else:
                        action_kind = "stop"
                else:
                    if action_choice == 0:
                        action_kind = "generate"
                        item_step10_api_key = select_api_key(api_keys)
                        if not item_step10_api_key:
                            print("   ⚠️ APIキーが選択されなかったため、この候補は手動用ファイルのみ作成します。")
                    elif action_choice == 1:
                        action_kind = "generate"
                    elif action_choice == 2:
                        action_kind = "skip_pending"
                    else:
                        action_kind = "stop"
            else:
                if action_choice == 0:
                    action_kind = "generate"
                elif action_choice == 1:
                    action_kind = "skip_pending"
                else:
                    action_kind = "stop"

            if action_kind == "stop":
                print(f"\n   → 内部リンク処理を終了し、ここまでの結果を保存します")
                break

            if action_kind == "use_existing_api":
                existing_result_path = existing_step10_api_files[-1]
                print(f"\n   → 既存API結果を使います（再生成しません）")
                skipped_existing_internal_links.append((i+1, topic_title, existing_fname))
                step10_api_result_paths.append(existing_result_path)
                try:
                    with open(existing_result_path, "r", encoding="utf-8") as f:
                        result_fields = _extract_internal_link_result_fields(f.read())
                    existing_location_error = _internal_link_location_error(result_fields, article_html)
                    if existing_location_error:
                        repair_candidate = _suggest_internal_link_location_from_parent(result_fields, article_html)
                        if repair_candidate and _internal_link_result_is_actionable(result_fields):
                            print("   ⚠️ 既存API結果の貼り付け位置が親記事本文に見つかりません。")
                            print("      貼り付け指示まとめでは、親記事本文内の実在位置へ補正して出力します。")
                            print(f"      補正先見出し: {repair_candidate.get('heading_text')}")
                            print(f"      補正先段落: {repair_candidate.get('anchor_text')}")
                        else:
                            print("   ⚠️ 既存API結果の貼り付け位置が親記事本文に見つかりません。")
                            print("      この候補は貼り付け指示まとめの【最終貼り付け案】には入りません。")
                            print(f"      理由: {existing_location_error}")
                    elif _internal_link_result_is_actionable(result_fields):
                        step10_completed_fields.append(result_fields)
                    elif _internal_link_result_needs_child_article(result_fields):
                        if not any(_skipped_num(existing) == i + 1 for existing in skipped_proposals):
                            _add_skipped_proposal(
                                i + 1,
                                topic_title,
                                proposal,
                                reason="API判断: 選択した既存記事への内部リンクは非推奨",
                                source_path=existing_result_path,
                            )
                        step10_attention_events.append({
                            "type": "non_recommended",
                            "num": i + 1,
                            "title": topic_title,
                            "existing_title": "",
                            "existing_url": "",
                            "source": existing_result_path,
                            "reason": "既存API判断: 選択した既存記事への内部リンクは非推奨",
                        })
                        print("\n" + "!" * 60)
                        print("   ⚠️ 既存API判断: この既存記事への内部リンクは非推奨です")
                        print("      この候補は【最終貼り付け案】には入りません。")
                        print("      子記事作成リストへ追加し、貼り付け指示まとめにも未反映理由を明記します。")
                        print(f"      判断元: {os.path.basename(existing_result_path)}")
                        print("!" * 60)
                        input("   Enterで確認して次へ進みます...")
                    else:
                        print("   ⚠️ 既存API結果はありますが、貼り付け位置を抽出できません。貼り付け指示まとめには未反映として記載します。")
                except Exception:
                    pass
                continue

            if action_kind == "skip_pending":
                print(f"\n   → スキップします（後で子記事を作成し再実行してください）")
                _add_skipped_proposal(
                    i + 1,
                    topic_title,
                    proposal,
                    reason="ユーザー操作: 対応する子記事をまだ作成していないためスキップ",
                )
                continue  # 内部リンク判断プロンプトは生成しない

            # ─── 既存記事を検索 ───
            existing_post_url   = ""
            existing_post_title = ""
            existing_post_html  = ""
            skip_this = False
            search_done = False
            proposal_ctx = f"【内部リンク案 {i+1}/{len(proposals)}】\n{proposal}"

            available_prefill_child_posts = [
                child for child in prefill_child_posts
                if _prefill_child_key(child) not in used_prefill_child_keys
            ]
            current_child_candidates = _rank_prefill_child_posts_for_topic(
                topic_title, proposal, available_prefill_child_posts, limit=5
            )
            if current_child_candidates:
                child_labels = []
                for child in current_child_candidates:
                    ckw = child.get("keyword") or "（キーワード未取得）"
                    curl = child.get("url") or "URL未取得"
                    cchars = html_to_char_count(child.get("html", ""))
                    child_labels.append(f"【この実行で作成】{ckw[:45]} / 本文{cchars:,}字 / {curl}")
                child_labels.append("WordPress検索へ進む")
                child_labels.append("ここまで保存して今回の内部リンク処理を終了する")
                child_idx = arrow_menu(
                    "この実行で作成した子記事候補があります\n"
                    "  対応する子記事ならここで選ぶと、WordPress検索を省略して内部リンク判断へ進めます。",
                    child_labels,
                    allow_back=False,
                    context=proposal_ctx,
                )
                if child_idx < len(current_child_candidates):
                    selected_child = current_child_candidates[child_idx]
                    existing_post_url = selected_child.get("url", "")
                    existing_post_title = selected_child.get("keyword", "")
                    existing_post_html = selected_child.get("html", "")
                    selected_child_key = _prefill_child_key(selected_child)
                    if selected_child_key:
                        used_prefill_child_keys.add(selected_child_key)
                    print(f"\n   選択: {existing_post_title}")
                    print(f"   URL : {existing_post_url or '（未取得）'}")
                    if existing_post_html:
                        print(f"   本文: {html_to_char_count(existing_post_html):,}文字（この実行で作成したデータを使用）")
                    search_done = True
                elif child_idx == len(current_child_candidates) + 1:
                    print(f"\n   → 内部リンク処理を終了し、ここまでの結果を保存します")
                    break

            search_candidates = build_wp_search_queries(topic_title, proposal, max_queries=6)
            default_search = search_candidates[0] if search_candidates else extract_wp_search_keywords(topic_title)
            if not search_done:
                if msvcrt:
                    while msvcrt.kbhit(): msvcrt.getwch()  # stdinバッファクリア
                print("  WordPress検索キーワード候補:")
                for _qi, _q in enumerate(search_candidates[:6], start=1):
                    print(f"    {_qi}. {_q}")
                print(f"  Enterで候補をまとめて検索 / 番号で1つだけ検索 / 手入力で検索: ", end="")
                search_kw = normalize_user_input(input())
                combined_search_terms = []
                combined_search = False
                if search_kw:
                    chosen_number = parse_menu_number(search_kw, 1, len(search_candidates))
                    if chosen_number is not None:
                        chosen_idx = chosen_number - 1
                        search_kw = search_candidates[chosen_idx]
                        combined_search_terms = [search_kw]
                        print(f"   ✅ 検索候補{chosen_idx + 1}を使用: {search_kw}")
                    elif search_kw not in search_candidates:
                        combined_search_terms = [search_kw]
                    else:
                        combined_search_terms = [search_kw]
                else:
                    combined_search_terms = search_candidates[:] or [default_search]
                    search_kw = "候補まとめ"
                    combined_search = True
            else:
                search_kw = default_search
                combined_search_terms = [search_kw]
                combined_search = False
            posts_cache  = None  # 同じ検索結果をページ切り替えで再利用
            page         = 0

            while not search_done and not skip_this:
                if posts_cache is None:
                    if combined_search:
                        shown_terms = " / ".join(combined_search_terms[:6])
                        print(f"\n   🔍 {step10_site['name']} を候補まとめ検索中: {shown_terms}")
                        posts_cache = merge_internal_link_search_results(combined_search_terms, topic_title, proposal)
                    else:
                        print(f"\n   🔍 '{search_kw}' で {step10_site['name']} を検索中...")
                        raw_posts = search_wordpress_posts(step10_site, search_kw)
                        posts_cache = rank_posts_for_internal_link(raw_posts, topic_title, proposal, search_kw)
                        if raw_posts and not posts_cache:
                            print("   ℹ️ 一致度の高い候補は見つかりませんでした。確認用に検索結果をそのまま表示します。")
                            posts_cache = raw_posts
                    page = 0

                posts = posts_cache

                if posts:
                    total = len(posts)
                    start = page * PAGE_SIZE
                    end   = min(start + PAGE_SIZE, total)
                    page_posts = posts[start:end]

                    display    = [make_post_label(p) for p in page_posts]
                    extra_map  = {}
                    base       = len(display)
                    if end < total:
                        display.append(f"次の10件 → ({end+1}〜{min(end+PAGE_SIZE, total)}件目)")
                        extra_map[base] = 'next'; base += 1
                    if page > 0:
                        display.append(f"← 前の10件 ({max(1, start-PAGE_SIZE+1)}〜{start}件目)")
                        extra_map[base] = 'prev'; base += 1
                    display.append("← 別のキーワードで検索し直す")
                    extra_map[base] = 'retry'; base += 1
                    display.append("→ 該当する公開済み記事なし（子記事作成リストへ追加）")
                    extra_map[base] = 'none'

                    if combined_search:
                        menu_title = f"検索KW: 候補まとめ  全{total}件 ({start+1}〜{end}件目)"
                    else:
                        menu_title = f"検索KW: '{search_kw}'  全{total}件 ({start+1}〜{end}件目)"
                    post_idx = arrow_menu(menu_title, display, allow_back=False, context=proposal_ctx)

                    if post_idx in extra_map:
                        act = extra_map[post_idx]
                        if act == 'next':
                            page += 1
                            continue
                        elif act == 'prev':
                            page -= 1
                            continue
                        elif act == 'retry':
                            posts_cache = None  # リトライメニューへ fall-through
                        elif act == 'none':
                            posts_cache = None  # リトライメニューへ fall-through
                    else:
                        sel = page_posts[post_idx]
                        existing_post_url   = sel.get('link', '')
                        existing_post_title = sel.get('title', {}).get('rendered', '')
                        cd = sel.get('content', {})
                        existing_post_html  = cd.get('rendered', '') if isinstance(cd, dict) else ''
                        print(f"\n   選択: {existing_post_title}")
                        print(f"   URL : {existing_post_url}")
                        if existing_post_html:
                            print(f"   本文: {html_to_char_count(existing_post_html):,}文字（取得済み）")
                        search_done = True
                        continue

                # 結果なし / 該当なし / 検索し直し → リトライメニュー
                if posts_cache is not None and posts:
                    # 検索結果はあったが該当なし/検索し直しで到達 → キャッシュをクリアして再表示回避
                    posts_cache = None

                retry_label = "候補まとめ" if combined_search else search_kw
                retry_choice = arrow_menu(
                    f"'{retry_label}' ─ 次のアクションを選択",
                    [
                        "🔍 別のキーワードで再検索する",
                        "⏭️  該当する公開済み記事なし → 子記事作成リストへ追加",
                    ],
                    allow_back=False,
                    context=proposal_ctx
                )
                if retry_choice == 0:
                    if msvcrt:
                        while msvcrt.kbhit(): msvcrt.getwch()
                    print(f"   検索キーワード: ", end="")
                    new_kw = input().strip()
                    if new_kw:
                        search_kw  = new_kw
                        combined_search_terms = [new_kw]
                        combined_search = False
                        posts_cache = None  # 再検索
                    else:
                        search_kw = "候補まとめ"
                        combined_search_terms = search_candidates[:] or [default_search]
                        combined_search = True
                        posts_cache = None
                else:
                    print("   → 該当する公開済み記事なしとして、子記事作成リストへ追加します")
                    skip_this = True

            if skip_this:
                _add_skipped_proposal(
                    i + 1,
                    topic_title,
                    proposal,
                    reason="ユーザー操作: 該当する公開済み記事なし",
                )
                print(f"   📋 保留リストへ追加: {topic_title}")
                continue  # 内部リンク判断プロンプトは生成しない

            # ─── 内部リンク判断プロンプト組み立て ───
            if step10_template:
                p10 = step10_template
                p10 = re.sub(r'キーワード：[^\n]+', f'キーワード：{keyword}', p10)
                p10 = p10.replace(
                    '既存記事のURL:',
                    f'既存記事のURL: {existing_post_url}' if existing_post_url else '既存記事のURL: （該当なし）'
                )
                p10 = p10.replace(
                    '既存記事のタイトル:',
                    f'既存記事のタイトル: {existing_post_title}' if existing_post_title else '既存記事のタイトル: （該当なし）'
                )
                p10 = p10.replace(
                    '既存記事のHTML全文（任意・精度向上用）：',
                    f'既存記事のHTML全文（任意・精度向上用）：\n{existing_post_html}' if existing_post_html else '既存記事のHTML全文（任意・精度向上用）：（省略）'
                )
                p10 = p10.replace(
                    '（構成案で示された[内部リンク案]のブロック全体を、ここに貼り付けてください）',
                    proposal
                )
                p10 += f"\n\n=== 親記事本文（判断用・冒頭3,000文字） ===\n{article_html[:3000]}"
            else:
                p10 = f"【内部リンク案 {i+1}】{topic_title}\n\n既存記事のURL: {existing_post_url or '（該当なし）'}\n既存記事のタイトル: {existing_post_title or '（該当なし）'}\n\n内部リンク案:\n{proposal}\n\n親記事本文（冒頭3,000文字）:\n{article_html[:3000]}"

            if step10_completed_fields:
                prior_lines = [
                    "",
                    "=== 既に提案済みの内部リンク設置位置（重複回避用） ===",
                    "以下と同じ見出し・同じ段落直後に設置する場合は、リンクを別々に乱立させず、既存の関連記事ブロックへ統合するか、より自然な別位置を選んでください。",
                    "最終提案は1案だけにしてください。",
                ]
                for done_idx, done in enumerate(step10_completed_fields, start=1):
                    prior_lines.extend([
                        f"【提案済み {done_idx}】{done.get('topic') or ''}",
                        f"対象見出し: {done.get('heading') or '（未取得）'}",
                        f"挿入位置: {done.get('anchor') or '（未取得）'}",
                        f"挿入HTML: {done.get('insert_html') or '（未取得）'}",
                    ])
                p10 += "\n" + "\n".join(prior_lines)

            safe_topic = re.sub(r'[\\/:*?"<>|]', '', topic_title[:15])
            step10_output_path = os.path.join(
                output_dir,
                f"[内部リンク]internal_link_prompt_{i+1}_{safe_topic}_{ts_item}.txt"
            )
            with open(step10_output_path, "w", encoding="utf-8") as f:
                f.write(p10)
            print(f"   ✅ 内部リンク判断ファイル保存: {os.path.basename(step10_output_path)}")
            step10_output_paths.append(step10_output_path)
            if item_step10_api_key:
                stop_after_api_failure = False
                while True:
                    result_path = run_step10_prompt_with_gemini(
                        p10, output_site, keyword, topic_title, i + 1, item_step10_api_key
                    )
                    if result_path:
                        step10_api_result_paths.append(result_path)
                        try:
                            with open(result_path, "r", encoding="utf-8") as f:
                                result_fields = _extract_internal_link_result_fields(f.read())
                            if _internal_link_result_is_actionable(result_fields):
                                step10_completed_fields.append(result_fields)
                            elif _internal_link_result_needs_child_article(result_fields):
                                if not any(_skipped_num(existing) == i + 1 for existing in skipped_proposals):
                                    _add_skipped_proposal(
                                        i + 1,
                                        topic_title,
                                        proposal,
                                        reason="API判断: 選択した既存記事への内部リンクは非推奨",
                                        existing_title=existing_post_title,
                                        existing_url=existing_post_url,
                                        source_path=result_path,
                                    )
                                step10_attention_events.append({
                                    "type": "non_recommended",
                                    "num": i + 1,
                                    "title": topic_title,
                                    "existing_title": existing_post_title,
                                    "existing_url": existing_post_url,
                                    "source": result_path,
                                    "reason": "API判断: 選択した既存記事への内部リンクは非推奨",
                                })
                                print("\n" + "!" * 60)
                                print("   ⚠️ API判断: 選択した既存記事への内部リンクは非推奨です")
                                print("      この候補は内部リンク貼り付け指示まとめの【最終貼り付け案】には入りません。")
                                print("      子記事作成リストへ追加し、貼り付け指示まとめにも未反映理由を明記します。")
                                if existing_post_title:
                                    print(f"      選択済み既存記事: {existing_post_title}")
                                if existing_post_url:
                                    print(f"      URL: {existing_post_url}")
                                print(f"      判断元: {os.path.basename(result_path)}")
                                print("!" * 60)
                                input("   Enterで確認して次へ進みます...")
                            else:
                                print("   ⚠️ API結果から貼り付け位置を抽出できませんでした。個別API結果を確認してください。")
                        except Exception:
                            pass
                        break

                    cont_idx = arrow_menu(
                        "内部リンク判断APIが混雑または一時エラーで失敗しました\n"
                        "\n"
                        "  ここまでに選んだ既存記事候補の手動判断用ファイルは保存済みです。\n"
                        "  一時混雑の可能性があるため、この場でもう一度試せます。\n"
                        "  APIキー上限が疑わしい場合は、APIキーを選び直して再試行できます。\n"
                        "\n"
                        "  ※ 503 UNAVAILABLE / 500 INTERNAL はGemini側の一時混雑でも発生します。",
                        [
                            "同じAPIキーでもう一度試す",
                            "APIキーを選び直してもう一度試す",
                            "手動判断用ファイルを保存して残りも進める（API消費なし）",
                            "ここで内部リンク処理を終了する",
                        ],
                        allow_back=False,
                    )
                    if cont_idx == 0:
                        continue
                    if cont_idx == 1:
                        new_api_key = select_api_key(api_keys)
                        if new_api_key:
                            item_step10_api_key = new_api_key
                        continue
                    step10_manual_wait_paths.append((i + 1, topic_title, step10_output_path, "API実行失敗または中断"))
                    step10_attention_events.append({
                        "type": "manual_wait",
                        "num": i + 1,
                        "title": topic_title,
                        "source": step10_output_path,
                        "reason": "API実行失敗または中断",
                    })
                    step10_api_key = None
                    if cont_idx == 3:
                        stop_after_api_failure = True
                    break
                if stop_after_api_failure:
                    break
            else:
                step10_manual_wait_paths.append((i + 1, topic_title, step10_output_path, "手動用ファイルのみ作成"))
                step10_attention_events.append({
                    "type": "manual_wait",
                    "num": i + 1,
                    "title": topic_title,
                    "source": step10_output_path,
                    "reason": "手動用ファイルのみ作成",
                })

        # ─── スキップ済みトピック案を pending ファイルに保存 ───
        if skipped_proposals:
            ts_p     = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            safe_kw  = re.sub(r'[\\/:*?"<>|]', '', keyword[:20])
            pending_path = os.path.join(output_dir, f"子記事作成リスト_{safe_kw}_{ts_p}.txt")
            lines = [
                "■ 子記事作成が必要な内部リンクトピック案",
                f"  親記事キーワード: {keyword}",
                f"  保存日時: {ts_p}",
                f"  件数: {len(skipped_proposals)}件",
                "",
                "【次の手順】",
                "  1. 下記トピック案をもとに子記事を作成する",
                "  2. ツールのメニュー5（メタ情報・入稿情報／内部リンク判断）を再実行する",
                "  3. resumeデータを選択し、このpendingファイルを読み込むと",
                "     メタ情報をスキップして内部リンクのみ処理できます",
                "",
                "="*60,
            ]
            for item in skipped_proposals:
                num = _skipped_num(item)
                title = _skipped_title(item)
                prop = _skipped_proposal(item)
                lines.append(f"\n【トピック案 {num}】{title}")
                if isinstance(item, dict) and item.get("reason"):
                    lines.append(f"判定理由: {item.get('reason')}")
                if isinstance(item, dict) and item.get("existing_title"):
                    lines.append(f"選択済み既存記事: {item.get('existing_title')}")
                if isinstance(item, dict) and item.get("existing_url"):
                    lines.append(f"選択済みURL: {item.get('existing_url')}")
                if isinstance(item, dict) and item.get("source_path"):
                    lines.append(f"判断元ファイル: {item.get('source_path')}")
                lines.append(prop)
                lines.append("-"*40)
            with open(pending_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            print(f"\n   📋 子記事作成リスト保存: {os.path.basename(pending_path)}")

    step10_apply_summary_path = None
    if step10_api_result_paths or step10_manual_wait_paths:
        try:
            step10_apply_summary_path = save_internal_link_apply_summary(
                output_site,
                keyword,
                step10_api_result_paths,
                manual_wait_paths=step10_manual_wait_paths,
                parent_html=article_html,
            )
            if step10_apply_summary_path:
                print(f"\n   ✅ 内部リンク貼り付け指示まとめ保存: {os.path.basename(step10_apply_summary_path)}")
            else:
                print("\n   ℹ️ 親記事に貼り付ける内部リンク案はありませんでした。")
        except Exception as e:
            print(f"   ⚠️ 内部リンク貼り付け指示まとめを保存できませんでした: {e}")

    summary_path = None
    try:
        summary_lines = [
            "■■■ 処理結果まとめ ■■■",
            f"生成日時: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"PC識別子: {PC_IDENTIFIER}",
            f"対象サイト: {output_site.get('name', '')}",
            f"キーワード: {keyword}",
            f"保存先: {output_dir}",
            "",
            "【メタ情報・入稿情報】",
        ]
        if step9_output_path:
            summary_lines.append(f"AI Studio貼り付け用プロンプト: {step9_output_path}")
        else:
            summary_lines.append("AI Studio貼り付け用プロンプト: スキップ")
        if step9_api_result_path:
            summary_lines.append(f"Gemini API結果: {step9_api_result_path}")
        if step9_entry_sheet_path:
            summary_lines.append(f"入稿用サマリー: {step9_entry_sheet_path}")
        summary_lines.append(f"WordPress標準項目の反映: {step9_apply_status}")
        summary_lines.extend(["", "【内部リンク判断】"])
        if step10_output_paths:
            for p in step10_output_paths:
                summary_lines.append(f"AI Studio貼り付け用プロンプト: {p}")
        else:
            summary_lines.append("AI Studio貼り付け用プロンプト: 生成なし")
        if skipped_existing_internal_links:
            summary_lines.append(f"既存の内部リンク判断API結果を再利用: {len(skipped_existing_internal_links)}件")
            for num, title, fname in skipped_existing_internal_links:
                summary_lines.append(f"  【{num}】{title} / 再利用ファイル: {fname}")
        if step10_api_result_paths:
            if step10_apply_summary_path:
                summary_lines.append(f"内部リンク貼り付け指示まとめ: {step10_apply_summary_path}")
            else:
                summary_lines.append("内部リンク貼り付け指示まとめ: 生成なし（親記事へ貼り付け可能な案なし）")
            for p in step10_api_result_paths:
                summary_lines.append(f"Gemini API結果: {p}")
        if step10_manual_wait_paths:
            summary_lines.append("内部リンク判断状態: 手動判断待ちあり（貼り付け指示まとめには未反映）")
            for num, title, p, reason in step10_manual_wait_paths:
                summary_lines.append(f"  【{num}】{title} / {reason}: {p}")
        elif step10_output_paths and not step10_api_result_paths:
            summary_lines.append("内部リンク判断状態: 手動判断待ち（API結果なし）")
        if skipped_proposals:
            summary_lines.extend(["", "【子記事作成が必要なトピック案】"])
            for item in skipped_proposals:
                num = _skipped_num(item)
                title = _skipped_title(item)
                summary_lines.append(f"【{num}】{title}")
                if isinstance(item, dict) and item.get("reason"):
                    summary_lines.append(f"  判定理由: {item.get('reason')}")
            if pending_path:
                summary_lines.append(f"子記事作成リスト: {pending_path}")
        summary_lines.extend([
            "",
            "【次の操作】",
            "1. 入稿用サマリーがある場合は、SEOプラグイン欄・カテゴリなど手動入稿が必要な項目を確認してください。",
            "2. 内部リンク貼り付け指示まとめがある場合は、そこに出ている貼り付け案だけを親記事へ反映してください。",
            "3. 子記事作成リストがある場合は、該当子記事を作ったあとメニュー5を再実行してください。",
            "4. API結果ファイルは、判断理由を確認したい場合だけ開いてください。",
        ])
        summary_path = os.path.join(output_dir, f"処理結果まとめ_{safe_kw}_{ts}.txt")
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write("\n".join(summary_lines) + "\n")
    except Exception as e:
        print(f"   ⚠️ 処理結果まとめを保存できませんでした: {e}")

    # 新規出力は「作業結果」に集約したため、整理済みビューへの自動コピーは行わない。
    # 旧ファイルの棚卸しが必要な時だけ、tools/organize_generated_results.py を手動実行する。
    organized_view_path = ""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 完了表示
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n" + "="*60)
    print("✅ メタ情報・入稿情報／内部リンク判断 完了！")
    print("="*60)
    print(f"\n📁 保存先: {output_dir}")
    if organized_view_path:
        print(f"📁 整理済みビュー: {organized_view_path}")
    if summary_path:
        print(f"\n  処理結果まとめ: {os.path.basename(summary_path)}")
    if step9_output_path:
        print(f"\n  メタ情報: {os.path.basename(step9_output_path)}")
        if step9_api_result_path:
            print(f"  メタ情報・入稿情報API結果: {os.path.basename(step9_api_result_path)}")
        if step9_entry_sheet_path:
            print(f"  入稿用サマリー: {os.path.basename(step9_entry_sheet_path)}")
    else:
        print(f"\n  メタ情報: スキップ")
    for p in step10_output_paths:
        print(f"  内部リンク判断: {os.path.basename(p)}")
    for p in step10_api_result_paths:
        print(f"  内部リンク判断API結果: {os.path.basename(p)}")
    if step10_apply_summary_path:
        print(f"  内部リンク貼り付け指示まとめ: {os.path.basename(step10_apply_summary_path)}")
    if step10_attention_events:
        print()
        for line in _format_step10_attention_event_lines(step10_attention_events, step10_apply_summary_path):
            print(line)
        input("   Enterで確認してファイル選択へ進みます...")
    if step10_manual_wait_paths:
        print(f"\n⚠️  貼り付け指示まとめに未反映の内部リンク案（{len(step10_manual_wait_paths)}件）:")
        for num, title, p, reason in step10_manual_wait_paths:
            print(f"    【{num}】{title}")
            print(f"       状態: {reason} / API判断結果なし")
            print("       対応: 親記事に貼る最終案へ入れるには、内部リンク判断をGemini APIで実行してください。")
    if skipped_proposals:
        print(f"\n⚠️  子記事作成が必要なトピック案（{len(skipped_proposals)}件）:")
        for item in skipped_proposals:
            num = _skipped_num(item)
            title = _skipped_title(item)
            print(f"    【{num}】{title}")
            if isinstance(item, dict) and item.get("reason"):
                print(f"       理由: {item.get('reason')}")
        if pending_path:
            print(f"\n  📋 子記事作成リスト: {os.path.basename(pending_path)}")
        print("\n  ▶ 子記事を作成後、メニュー5を再実行してください")
        print("    （pendingファイルを読み込むとメタ情報をスキップできます）")
    print()
    print("【次のステップ】")
    if step10_manual_wait_paths:
        print("  API判断結果がない内部リンク案があります。貼り付け指示まとめへ入れる場合は、メニュー5で内部リンクだけ再確認し、該当案をGemini APIで判断してください。")
        if pending_path:
            print("  子記事作成リストもあります。子記事を作る案と、既存記事で判断する案を分けて処理してください。")
    elif pending_path:
        print("  子記事作成リストを確認し、必要な子記事を作成してください。作成後にメニュー5を再実行します。")
    elif step10_apply_summary_path:
        print("  内部リンク貼り付け指示まとめを確認し、親記事へ手動で反映してください。")
    elif step10_api_result_paths:
        print("  親記事へ貼り付ける内部リンク案はありませんでした。必要ならAPI結果の判断理由だけ確認してください。")
    elif step9_entry_sheet_path:
        print("  メタ情報・入稿情報: 入稿用サマリーを確認してください。自動反映しない場合は手動入力します。")
    else:
        print("  必要な生成物はありません。続ける場合はメニューから次の作業を選択してください。")
    print()
    print("  ─ 各ファイルの役割 ─────────────────────────────────")
    print("  手動用    : AI Studioに貼り付けるためのプロンプト（APIを使わない保険）")
    print("  入稿用    : SEOプラグイン欄・カテゴリなど、手動入稿が必要な項目だけを抜き出した短いシート")
    print("  内部リンク: 親記事と子記事/既存記事の関係を分析し、リンク挿入可否を判断")
    print("  ────────────────────────────────────────────────────")
    print()
    print("  ▼ 以下で開くファイルを選択してください（Space: 選択切替）")
    print()

    # ファイルを開く（複数選択）
    # --- この実行で生成したファイル ---
    current_paths = (
        ([summary_path] if summary_path else []) +
        ([step9_output_path] if step9_output_path else []) +
        ([step9_api_result_path] if step9_api_result_path else []) +
        ([step9_entry_sheet_path] if step9_entry_sheet_path else []) +
        ([step10_apply_summary_path] if step10_apply_summary_path else []) +
        ([pending_path] if pending_path else []) +
        step10_output_paths +
        step10_api_result_paths
    )

    # --- 過去セッションの内部リンク判断ファイルは履歴メニューから開く ---
    # 完了直後の画面では、今回必要なファイルだけに絞る。
    current_set = set(os.path.abspath(p) for p in current_paths)
    past_step10_paths = []

    # --- 選択肢を構築（セパレータなし・全て個別） ---
    all_file_paths   = []
    open_labels      = []
    default_checked  = []

    has_meta_api_or_entry = bool(step9_api_result_path or step9_entry_sheet_path)
    has_internal_link_api = bool(step10_api_result_paths)
    has_pending_children = bool(pending_path)
    has_unfinished_internal = bool(step10_manual_wait_paths or skipped_proposals or pending_path)
    for p in current_paths:
        all_file_paths.append(p)
        bname = os.path.basename(p)
        if bname.startswith("run_summary_") or bname.startswith("今回の結果まとめ_") or bname.startswith("処理結果まとめ_"):
            open_labels.append(f"【任意・処理ログ】{bname}")
            default_checked.append(False)
        elif _is_meta_entry_sheet_path(p):
            open_labels.append(f"【開く推奨・親記事の入稿用メモ】{bname}")
            default_checked.append(True)
        elif _is_meta_api_result_path(p):
            open_labels.append(f"【任意・メタAPIの生結果】{bname}")
            default_checked.append(False)
        elif _is_internal_link_apply_summary_path(p):
            if has_unfinished_internal:
                open_labels.append(f"【後で確認・内部リンク貼り付け案（子記事未完了のため最終版ではありません）】{bname}")
                default_checked.append(False)
            else:
                open_labels.append(f"【開く推奨・内部リンク貼り付け最終案】{bname}")
                default_checked.append(not _is_empty_internal_link_apply_summary_path(p))
        elif bname.startswith("子記事作成リスト_") or bname.startswith("pending_internal_links_"):
            open_labels.append(f"【次工程・子記事作成リスト（続き確認からも引き継ぎます）】{bname}")
            default_checked.append(False)
        elif "meta_prompt" in bname or "step9_prompt" in bname:
            if has_meta_api_or_entry:
                open_labels.append(f"【任意・メタ情報手動用プロンプト】{bname}")
            else:
                open_labels.append(f"【未完了・メタ情報手動用プロンプト（入稿用サマリー未生成）】{bname}")
            default_checked.append(not has_meta_api_or_entry)
        elif "internal_link_prompt" in bname or "step10_" in bname:
            open_labels.append(f"【任意・内部リンク手動判断用】{bname}")
            default_checked.append(False)
        elif _is_internal_link_api_result_path(p):
            open_labels.append(f"【任意・内部リンクAPI判断の生結果】{bname}")
            default_checked.append(False)
        else:
            open_labels.append(f"【任意】{bname}")
            default_checked.append(False)

    for p in past_step10_paths:
        all_file_paths.append(p)
        open_labels.append(f"【過去】{os.path.basename(p)}")
        default_checked.append(False)  # 過去分はデフォルト未選択

    if open_labels:
        file_select_title = (
            "開くファイルを選択してください\n"
            "  Space: 選択切替   Enter: 選択したファイルを開く   ESC: 開かずに終了\n"
            "  ※ [開く推奨] だけを初期選択しています。迷ったらそのままEnterで大丈夫です"
        )
        if has_pending_children:
            file_select_title += (
                "\n  ※ 子記事が未完了のため、内部リンク貼り付け案と子記事作成リストは自動では開きません。"
                "\n     続き確認から子記事作成へ進めます。"
            )
        if step10_attention_events:
            file_select_title += (
                "\n  ※重要: 最終貼り付け案に入っていない候補があります。"
                "貼り付け指示まとめと子記事作成リストを確認してください。"
            )
        selected_indices = arrow_menu_multiselect(
            file_select_title,
            open_labels,
            default_checked=default_checked
        )
        try:
            selected_paths = []
            for idx in selected_indices:
                selected_paths.append(all_file_paths[idx])
            for p in list(dict.fromkeys(selected_paths)):
                if p and os.path.exists(p):
                    os.startfile(p)
                    time.sleep(0.3)
        except Exception as e:
            print(f"   ⚠️ ファイルを開けませんでした: {e}")


# ============================================================
# モード1: 親記事作成（通常サイト）
# ============================================================
def run_mode_parent_normal():
    print("\n" + "="*60)
    print("  親記事作成（通常サイト）")
    print(f"  PC識別子: {PC_IDENTIFIER}")
    print("="*60)
    os.makedirs(PARENT_WORDPRESS_DATA, exist_ok=True)
    os.makedirs(PARENT_LOGS, exist_ok=True)

    loaded_resume_data = load_resume_data(RESUME_NORMAL)
    resume_data = loaded_resume_data if _is_interrupted_parent_resume(loaded_resume_data) else None
    use_resume  = False
    if loaded_resume_data and not resume_data:
        print("ℹ️ 前回データは完了済みまたは再開不要のため、親記事生成の中断再開候補にはしません。")
    if resume_data:
        print(f"💡 前回の中断データ: {resume_data.get('timestamp')}")
        if is_yes_input(input("\n続きから再開しますか？ (y/n): ")):
            use_resume = True

    selected_api_key = select_api_key(API_KEYS_NORMAL)
    if selected_api_key is None:
        return  # メインメニューへ戻る

    site_keys  = list(SITES_NORMAL.keys())
    site_names = [v['name'] for v in SITES_NORMAL.values()]
    resume_meta = _resume_metadata(resume_data) if use_resume else {}

    # kw_classifier連携: サイトが環境変数で指定されている場合は自動選択
    _kw_site = os.environ.get("KW_CLASSIFIER_SITE", "")
    if use_resume and resume_meta.get("site_choice") in SITES_NORMAL:
        site_choice = resume_meta.get("site_choice")
        selected_site = SITES_NORMAL[site_choice]
        print(f"\n✅ サイト復元: {selected_site['name']}")
    elif _kw_site and _kw_site in SITES_NORMAL:
        site_choice = _kw_site
        selected_site = SITES_NORMAL[site_choice]
        print(f"\n✅ サイト自動選択: {selected_site['name']}")
    else:
        site_idx   = arrow_menu("サイト選択", site_names, allow_back=True)
        if site_idx == -1:
            return  # メインメニューへ戻る
        site_choice   = site_keys[site_idx]
        selected_site = SITES_NORMAL[site_choice]

    available     = PROMPT_TYPES_PARENT_NORMAL.get(selected_site['type'], {})
    avail_keys    = list(available.keys())
    avail_names   = [v['name'] for v in available.values()]
    if use_resume and resume_meta.get("prompt_key") in available:
        prompt_key = resume_meta.get("prompt_key")
        sub_path = available[prompt_key]['path']
        print(f"✅ プロンプト復元: {available[prompt_key]['name']}")
    else:
        prompt_idx    = arrow_menu("プロンプト選択", avail_names, allow_back=True)
        if prompt_idx == -1:
            return  # メインメニューへ戻る
        prompt_key = avail_keys[prompt_idx]
        sub_path             = available[prompt_key]['path']
    selected_prompt_path = os.path.join(PROMPT_BASE_DIR, sub_path)

    selected_addition_file = None
    suppress_scroll_cta    = False
    restored_addition = resume_meta.get("addition_path", "") if use_resume else ""
    if restored_addition and os.path.exists(restored_addition):
        selected_addition_file = restored_addition
        suppress_scroll_cta = bool(resume_meta.get("suppress_scroll_cta", False))
        print(f"✅ 足し算ファイル復元: {os.path.basename(selected_addition_file)}")
    elif use_resume and restored_addition:
        print(f"⚠️ 前回の足し算ファイルが見つかりません: {restored_addition}")
    if not use_resume or (use_resume and not resume_meta) or (restored_addition and not selected_addition_file):
        sel_add = select_addition_file(
            selected_site,
            f"足し算Promptを選択（{selected_site.get('name', '')} 用）\n"
            "  この記事に挿入する案件CTA・比較表・補足指示を選びます。\n"
            "  使わない場合は「スキップ」を選んでください。",
        )
        # ESCで戻るかスキップかの判定：select_addition_file はNoneを返すが、
        # 「ESCで前の画面に戻りたい」場合のため、ユーザーが ESC を押した場合は
        # arrow_menuが-1を返し、select_addition_fileもNoneを返す。
        # ここでは「足し算なし」として続行（戻る場合は sel_add==Noneで通過）
        selected_addition_file = sel_add
        if selected_addition_file:
            # 口コミ（商標記事）の場合のみスクロールCTA除外オプションを表示
            is_review = "review" in sub_path.lower() or "口コミ" in sub_path
            if is_review:
                cta_idx = arrow_menu(
                    "記事タイプを選択\n"
                    "  （スクロールCTAボックス = アフィリボタン下の比較スクロール枠）",
                    [
                        "一般口コミ記事 → スクロールCTAボックスあり",
                        "商標記事（特定商品・先生専用）→ スクロールCTAボックスなし",
                    ],
                    allow_back=False
                )
                suppress_scroll_cta = (cta_idx == 1)

    if use_resume:
        target_input         = resume_data.get("target_input", "")
        initial_instruction  = resume_data.get("initial_instruction", "")
    else:
        # kw_classifier連携: キーワードが環境変数で指定されている場合は自動入力
        _kw_keyword = os.environ.get("KW_CLASSIFIER_KEYWORD", "")
        if _kw_keyword:
            target_input = _kw_keyword
            print(f"\n【キーワード（自動入力）】: {target_input}")
            # 環境変数をクリア（次回の手動起動に影響しないように）
            os.environ.pop("KW_CLASSIFIER_KEYWORD", None)
            os.environ.pop("KW_CLASSIFIER_SITE", None)
        else:
            target_input = input(f"\n【キーワード】: ").strip()

        # 競合URL: SearchAPI.io等で自動取得 → 失敗時だけChrome/手動入力を選択
        competitor_urls = collect_competitor_urls(target_input, num_results=10)

        open_file_for_user(RESEARCH_FILE)
        research_content   = read_file(RESEARCH_FILE)

        # ── ディープリサーチURLチェック ──
        do_check = arrow_menu(
            "リサーチファイル内のURLを事前チェックしますか？\n  （壊れたURLを材料から除外します。最終HTMLのリンクは投稿前に再チェックします）",
            ["チェックする（リンク切れURLを材料から除外）", "スキップする"],
            allow_back=False
        )
        if do_check == 0:
            research_content = check_urls_in_research(research_content)

        initial_instruction = f"前提情報:\nキーワード:{target_input}\n競合URL:\n{competitor_urls}\nリサーチ内容:\n{research_content}"

    step_files = sorted(glob.glob(os.path.join(selected_prompt_path, "step*.txt")))
    execution_list = []
    for f in step_files:
        fname = os.path.basename(f)
        if "step00" in fname: continue
        if "step06_extract" in fname: continue  # 画像/地図用抽出ステップはスキップ
        if any(x in fname for x in ["step01", "step02", "step03", "step04", "step05"]):
            execution_list.append({"path": f, "type": "normal"})
        elif "step06" in fname:
            # step06_extract は上で除外済み → step06.txt / step06_regenerate.txt 等が対象
            if selected_addition_file:
                execution_list.append({"path": f, "type": "merged_addition", "addition_path": selected_addition_file, "suppress_scroll_cta": suppress_scroll_cta})
            else:
                execution_list.append({"path": f, "type": "normal"})
        # step08は旧システムと同様にPython関数force_cleanup_html_parent()で処理するため
        # APIでの実行は不要（APIに送ると指示文の復唱で終わる問題が発生する）

    print("\n🚀 記事生成開始...")
    print(f"🤖 使用モデル: {MODEL_PARENT}（親記事）")
    parent_resume_meta = build_parent_resume_metadata(
        site_choice, selected_site, prompt_key, sub_path, selected_addition_file, suppress_scroll_cta
    )
    success, final_content, log_history, step_outputs = run_article_generation_parent(
        selected_api_key, initial_instruction, execution_list, selected_site, target_input,
        resume_data if use_resume else None,
        resume_metadata=parent_resume_meta,
    )

    if success:
        print("\n✅ 記事本文の生成が完了しました！")
        print_article_output_summary(final_content, "親記事生成結果")
        # 内部リンクトピック案を保存
        os.makedirs(PARENT_WORDPRESS_DATA, exist_ok=True)
        links_text = extract_internal_links(step_outputs)
        if links_text:
            ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            links_file = os.path.join(PARENT_WORDPRESS_DATA, f"internal_links_{PC_IDENTIFIER}_{site_choice}_{target_input[:20]}_{ts}.txt")
            with open(links_file, "w", encoding="utf-8") as f:
                f.write(f"【ターゲットキーワード】 {target_input}\n{'='*50}\n\n{links_text}")
            print(f"✅ 内部リンク案保存: {os.path.basename(links_file)}")

        check_keyword_density(final_content, target_input)
        final_content, broken_links = validate_final_html_links(final_content, "投稿前HTML")
        if broken_links and log_history:
            log_history[-1]["text"] = final_content
            log_history.append({
                "role": "System (投稿前リンクチェック)",
                "text": "投稿前リンク安全チェックで、読者が開けない可能性がある以下のURLのリンクだけを解除しました（アンカーテキストは本文に残しています）。\n" + "\n".join(u for u, _, _ in broken_links)
            })
        print("\n📤 WordPress下書き投稿中...")
        _wp_result = post_to_wordpress(selected_site, f"【自動生成】{target_input[:30]}...", final_content)
        save_log_parent(target_input, log_history)
        # resume_normal.json は削除しない（後からメタ情報モードで読み込めるよう保持。次回記事生成時に自動上書き）

        # 順位チェッカー連動
        _posted_url = _wp_result if isinstance(_wp_result, str) else ""
        if _posted_url:
            try:
                _rc_dir = r"G:\マイドライブ\kw_app_dev\kw_classifier"
                # フォールバック: 相対パスも試す
                if not os.path.exists(os.path.join(_rc_dir, "rank_checker.py")):
                    _alt = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "kw_app_dev", "kw_classifier")
                    if os.path.exists(os.path.join(_alt, "rank_checker.py")):
                        _rc_dir = _alt

                sys.path.insert(0, _rc_dir)
                import rank_checker as _rc

                # sheet_idファイルから直接読み込み（UIをスキップ）
                _rc_sheet_id_file = os.path.join(_rc_dir, "rank_checker_sheet_id.txt")
                if not os.path.exists(_rc_sheet_id_file):
                    print("\n  ※ 順位チェッカー連動スキップ: スプシ未作成（先に順位チェッカーを1回起動してください）")
                else:
                    with open(_rc_sheet_id_file, "r") as f:
                        _rc_sheet_id = f.read().strip()
                    _rc_creds = _rc.get_credentials()
                    _rc_sheets = build("sheets", "v4", credentials=_rc_creds)
                    _rc.register_from_auto_post(
                        _rc_sheets, _rc_sheet_id,
                        url=_posted_url,
                        title=f"【自動生成】{target_input[:30]}...",
                        keyword=target_input,
                        site_name=selected_site.get('name', ''),
                    )
            except Exception as _rc_err:
                print(f"\n  ※ 順位チェッカー連動スキップ: {_rc_err}")

        # 完了後の選択
        next_options = [
            "メタ情報・入稿情報／内部リンク判断へ続ける",
            "メインメニューへ戻る",
        ]
        next_idx = arrow_menu(f"✅ 完了: {target_input[:30]}  ─ 次のステップを選んでください", next_options, allow_back=False)
        if next_idx == 0:
            run_step9_10(
                prefill_keyword=target_input,
                prefill_html=final_content,
                prefill_step_outputs=step_outputs,
                prefill_site=selected_site,
                prefill_post_url=_posted_url,
            )
        # next_idx == 1 → そのままreturnしてメインメニューへ
    else:
        print("\n⚠️ 中断されました。再開データ保存済み。")
        save_log_parent(target_input if target_input else "failed", log_history)
        input("\nEnterを押してメインメニューへ戻ります...")


# ============================================================
# モード2: 親記事作成（もえちん）
# ============================================================
def run_mode_parent_moechin():
    print("\n" + "="*60)
    print("  親記事作成（もえちん専用）")
    print(f"  PC識別子: {PC_IDENTIFIER}")
    print("="*60)
    os.makedirs(PARENT_WORDPRESS_DATA, exist_ok=True)
    os.makedirs(PARENT_LOGS, exist_ok=True)

    loaded_resume_data = load_resume_data(RESUME_MOECHIN)
    resume_data = loaded_resume_data if _is_interrupted_parent_resume(loaded_resume_data) else None
    use_resume  = False
    if loaded_resume_data and not resume_data:
        print("ℹ️ 前回データは完了済みまたは再開不要のため、親記事生成の中断再開候補にはしません。")
    if resume_data:
        print(f"💡 前回の中断データ: {resume_data.get('timestamp')}")
        if is_yes_input(input("\n続きから再開しますか？ (y/n): ")):
            use_resume = True

    selected_api_key = select_api_key(API_KEYS_MOECHIN)
    if selected_api_key is None:
        return  # メインメニューへ戻る

    resume_meta = _resume_metadata(resume_data) if use_resume else {}
    selected_site = SITES_MOECHIN["7"]
    print(f"\n✅ サイト: {selected_site['name']}")

    prompt_key = "1"
    sub_path = PROMPT_TYPES_PARENT_MOECHIN["C"]["1"]["path"]
    selected_prompt_path = os.path.join(PROMPT_BASE_DIR, sub_path)

    # もえちん親記事: 足し算ファイルを自動検出（HTML出力に必須）
    selected_addition_file = None
    restored_addition = resume_meta.get("addition_path", "") if use_resume else ""
    if restored_addition and os.path.exists(restored_addition):
        selected_addition_file = restored_addition
        print(f"   📎 足し算ファイル復元: {os.path.basename(selected_addition_file)}")
    else:
        if use_resume and restored_addition:
            print(f"   ⚠️ 前回の足し算ファイルが見つかりません: {restored_addition}")
        additions_dir = find_additions_folder(PROMPT_BASE_DIR)
        if additions_dir:
            moechin_add_dir = os.path.join(additions_dir, "もえちん")
            if os.path.isdir(moechin_add_dir):
                add_files = sorted(glob.glob(os.path.join(moechin_add_dir, "*.txt")))
                if len(add_files) == 1:
                    selected_addition_file = add_files[0]
                    print(f"   📎 足し算ファイル自動適用: {os.path.basename(selected_addition_file)}")
                elif len(add_files) > 1:
                    options = [os.path.basename(f) for f in add_files]
                    idx = arrow_menu(
                        "足し算Promptを選択（もえちん用）\n"
                        "  もえちん親記事のHTML出力に使う案件CTA・補足指示を選びます。",
                        options,
                        allow_back=False,
                    )
                    selected_addition_file = add_files[idx]
    if not selected_addition_file:
        print("   ⚠️ 足し算ファイルが見つかりません。HTML出力はstep06の基本指示に依存します。")

    if use_resume:
        target_input        = resume_data.get("target_input", "")
        initial_instruction = resume_data.get("initial_instruction", "")
    else:
        target_input = input(f"\n【キーワード】: ").strip()

        # 競合URL: SearchAPI.io等で自動取得 → 失敗時だけChrome/手動入力を選択
        competitor_urls = collect_competitor_urls(target_input, num_results=10)

        open_file_for_user(RESEARCH_FILE)
        research_content  = read_file(RESEARCH_FILE)

        # ── ディープリサーチURLチェック ──
        do_check = arrow_menu(
            "リサーチファイル内のURLを事前チェックしますか？\n  （壊れたURLを材料から除外します。最終HTMLのリンクは投稿前に再チェックします）",
            ["チェックする（リンク切れURLを材料から除外）", "スキップする"],
            allow_back=False
        )
        if do_check == 0:
            research_content = check_urls_in_research(research_content)

        initial_instruction = f"前提情報:\nキーワード:{target_input}\n競合URL:\n{competitor_urls}\nリサーチ内容:\n{research_content}"

    step_files = sorted(glob.glob(os.path.join(selected_prompt_path, "step*.txt")))
    execution_list = []
    for f in step_files:
        fname = os.path.basename(f)
        if "step00" in fname: continue
        # ★ step06_extract.txt はスキップ（画像/地図埋め込み用で現在未使用）
        if "step06_extract" in fname: continue
        if "step01" in fname:
            execution_list.append({"path": f, "type": "normal"})
        elif "step02" in fname:
            # ★ もえちん専用: step02実行前に爆サイデータを収集
            execution_list.append({"path": f, "type": "normal", "pre_action": "bakusai"})
        elif "step03" in fname:
            execution_list.append({"path": f, "type": "normal"})
        elif "step04" in fname:
            # ★ もえちん専用: step04実行前にショップリストを確認
            execution_list.append({"path": f, "type": "normal", "pre_action": "shop_list"})
        elif "step05" in fname:
            execution_list.append({"path": f, "type": "normal"})
        elif "step06" in fname:
            # ★ step06_extract は上で除外済み → step06.txt / step06_regenerate.txt 等が対象
            if selected_addition_file:
                execution_list.append({"path": f, "type": "merged_addition", "addition_path": selected_addition_file, "suppress_scroll_cta": False})
            else:
                execution_list.append({"path": f, "type": "normal"})
        # step08は旧システムと同様にPython関数force_cleanup_html_parent()で処理するため
        # APIでの実行は不要

    print("\n🚀 記事生成開始...")
    print(f"🤖 使用モデル: {MODEL_PARENT}（親記事・もえちん）")
    parent_resume_meta = build_parent_resume_metadata(
        "7", selected_site, prompt_key, sub_path, selected_addition_file, False
    )
    success, final_content, log_history, step_outputs = run_article_generation_parent(
        selected_api_key, initial_instruction, execution_list, selected_site, target_input,
        resume_data if use_resume else None,
        resume_metadata=parent_resume_meta,
    )

    if success:
        print("\n✅ 記事本文の生成が完了しました！")
        print_article_output_summary(final_content, "親記事生成結果")
        links_text = extract_internal_links(step_outputs)
        if links_text:
            ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            links_file = os.path.join(PARENT_WORDPRESS_DATA, f"internal_links_{PC_IDENTIFIER}_moechin_{target_input[:20]}_{ts}.txt")
            with open(links_file, "w", encoding="utf-8") as f:
                f.write(f"【ターゲットキーワード】 {target_input}\n{'='*50}\n\n{links_text}")
            print(f"✅ 内部リンク案保存: {os.path.basename(links_file)}")

        check_keyword_density(final_content, target_input)
        final_content, broken_links = validate_final_html_links(final_content, "投稿前HTML")
        if broken_links and log_history:
            log_history[-1]["text"] = final_content
            log_history.append({
                "role": "System (投稿前リンクチェック)",
                "text": "投稿前リンク安全チェックで、読者が開けない可能性がある以下のURLのリンクだけを解除しました（アンカーテキストは本文に残しています）。\n" + "\n".join(u for u, _, _ in broken_links)
            })
        print("\n📤 WordPress下書き投稿中...")
        _wp_result = post_to_wordpress(selected_site, f"【自動生成】{target_input[:30]}...", final_content)
        _posted_url = _wp_result if isinstance(_wp_result, str) else ""
        save_log_parent(target_input, log_history)
        # resume_moechin.json は削除しない（後からメタ情報モードで読み込めるよう保持。次回記事生成時に自動上書き）

        # 完了後の選択
        next_options = [
            "メタ情報・入稿情報／内部リンク判断へ続ける",
            "メインメニューへ戻る",
        ]
        next_idx = arrow_menu(f"✅ 完了: {target_input[:30]}  ─ 次のステップを選んでください", next_options, allow_back=False)
        if next_idx == 0:
            run_step9_10(
                prefill_keyword=target_input,
                prefill_html=final_content,
                prefill_step_outputs=step_outputs,
                prefill_site=selected_site,
                prefill_post_url=_posted_url,
            )
    else:
        print("\n⚠️ 中断されました。再開データ保存済み。")
        save_log_parent(target_input if target_input else "failed", log_history)
        input("\nEnterを押してメインメニューへ戻ります...")


# ============================================================
# モード3: 子記事作成（通常サイト）
# ============================================================
def run_mode_child_normal(prefill_site_key=None, prefill_topics=None, prefill_parent_keyword=None):
    print("\n" + "="*60)
    print("  子記事作成（通常サイト）")
    print("="*60)
    os.makedirs(CHILD_WORDPRESS_DATA, exist_ok=True)
    os.makedirs(CHILD_LOGS, exist_ok=True)

    site_keys  = list(SITES_NORMAL.keys())
    site_names = [v['name'] for v in SITES_NORMAL.values()]
    if prefill_site_key in SITES_NORMAL:
        selected_site_key = prefill_site_key
        print(f"   対象サイト: {SITES_NORMAL[selected_site_key]['name']}（続き確認から引き継ぎ）")
    else:
        site_idx   = arrow_menu("サイト選択", site_names, allow_back=True)
        if site_idx == -1:
            return  # メインメニューへ戻る
        selected_site_key = site_keys[site_idx]
    selected_site = SITES_NORMAL[selected_site_key]

    prompt_variants = PROMPT_TYPES_CHILD_NORMAL.get(selected_site['type'], {})
    if not prompt_variants:
        return print("❌ プロンプト設定が見つかりません。")
    if len(prompt_variants) == 1:
        prompts_info = list(prompt_variants.values())[0]
    else:
        variant_names = [v['name'] for v in prompt_variants.values()]
        v_idx = arrow_menu("プロンプト版を選択", variant_names, allow_back=True)
        if v_idx == -1:
            return
        prompts_info = list(prompt_variants.values())[v_idx]
    selected_prompt_path = os.path.join(PROMPT_BASE_DIR, prompts_info['path'])

    # ── internal_linksファイルからトピック案を自動取得（複数選択対応） ──
    selected_topics = list(prefill_topics or [])
    if selected_topics:
        done_norms = _workflow_completed_child_topic_norms(selected_site.get("name", ""), prefill_parent_keyword)
        if done_norms:
            before_count = len(selected_topics)
            selected_topics = [
                topic for topic in selected_topics
                if _result_history_normalize_keyword(topic) not in done_norms
            ]
            skipped_count = before_count - len(selected_topics)
            if skipped_count:
                print(f"\n   ✅ 既に完了/既存記事対応済みの子記事候補を除外しました: {skipped_count}件")
        if not selected_topics:
            print("\n   ✅ この親記事の子記事候補はすべて完了または既存記事対応済みです。")
            input("   Enterで戻ります...")
            return
        print("\n   続き確認で検出した子記事候補を使用します:")
        for idx, topic in enumerate(selected_topics, 1):
            print(f"    {idx}. {topic}")
        checked_indices = arrow_menu_multiselect(
            "今回作成する子記事候補を確認\n"
            "  Space: 作成する/しないを切替   Enter: この内容で開始\n"
            "  既存記事で対応済みの候補は[----]にしてください。",
            selected_topics,
            default_checked=[True] * len(selected_topics),
        )
        if not checked_indices:
            print("\n   子記事作成対象が0件のため戻ります。")
            input("   Enterで戻ります...")
            return
        excluded_topics = [
            topic for idx, topic in enumerate(selected_topics)
            if idx not in checked_indices
        ]
        for topic in excluded_topics:
            _mark_workflow_child_topic(
                selected_site.get("name", ""),
                prefill_parent_keyword,
                topic,
                "existing",
            )
        selected_topics = [selected_topics[i] for i in checked_indices]
        if excluded_topics:
            print(f"\n   ✅ 既存記事対応済みとして除外しました: {len(excluded_topics)}件")

    links_candidates = [] if selected_topics else get_internal_links_source_candidates(site_filter=selected_site_key, limit=20, dedupe_keyword=True)
    if links_candidates:
        file_options = [
            format_internal_links_candidate_label(c, is_recommended=(i == 0))
            for i, c in enumerate(links_candidates)
        ]
        file_options.append("過去・重複候補もすべて表示する（時間がかかる場合あり）")
        file_options.append("手動入力（ファイルを使わない）")
        f_idx = arrow_menu(
            "【内部リンクファイルを選択】\n"
            "  親記事作成後に保存された「子記事候補リスト」を選びます。\n"
            "  一番上は、このサイトで最後に作成された親記事の候補です。\n"
            "  ※ 違う親記事の子記事を作る場合だけ、別候補を選びます。",
            file_options, allow_back=False
        )
        f_idx = confirm_non_recommended_internal_link_choice(links_candidates, f_idx)
        if f_idx == len(links_candidates):
            print("\n   🔎 過去ログを含めて全件復元中です。ログ数が多い場合は少し時間がかかります...")
            links_candidates = get_internal_links_source_candidates(
                site_filter=selected_site_key,
                limit=80,
                dedupe_keyword=False,
                max_parent_logs_scan=None,
            )
            file_options = [
                format_internal_links_candidate_label(c, is_recommended=(i == 0))
                for i, c in enumerate(links_candidates)
            ]
            file_options.append("手動入力（ファイルを使わない）")
            f_idx = arrow_menu(
                "【内部リンクファイルを選択（全件表示）】\n"
                "  過去・重複候補も含めて表示しています。\n"
                "  親記事名と作成日時を確認して選んでください。",
                file_options, allow_back=False
            )
            f_idx = confirm_non_recommended_internal_link_choice(links_candidates, f_idx)
        if 0 <= f_idx < len(links_candidates):
            links_text = read_internal_links_candidate(links_candidates[f_idx])
            topic_labels = extract_child_topic_labels_from_links_text(links_text)
            if topic_labels:
                while True:
                    checked_indices = arrow_menu_multiselect(
                        "作成するトピック案を選択（複数可）\n"
                        "  Space: 選択切替   Enter: 開始   ESC: 手動入力へ\n"
                        "  [選択] = 作成する   [----] = この処理では作成しない",
                        topic_labels,
                        default_checked=[False] * len(topic_labels)
                    )
                    if checked_indices:
                        break
                    retry_idx = arrow_menu(
                        "作成するトピック案が選択されていません。\n"
                        "  Spaceで[選択]に切り替えてからEnterを押してください。",
                        [
                            "選択画面に戻る",
                            "手動入力へ進む",
                            "子記事作成を中止する",
                        ],
                        allow_back=False,
                    )
                    if retry_idx == 0:
                        continue
                    if retry_idx == 1:
                        checked_indices = []
                        break
                    return
                selected_topics = [topic_labels[i] for i in checked_indices]

    if not selected_topics:
        manual = input(f"\n【トピック案（文章OK）】: ").strip()
        if not manual: return
        selected_topics = [manual]

    selected_api_key = select_api_key(API_KEYS_NORMAL)
    if selected_api_key is None:
        return  # メインメニューへ戻る

    # ── 選択トピックを順番に処理 ──
    step_files = sorted(glob.glob(os.path.join(selected_prompt_path, "step*.txt")))
    execution_list = []
    for f in step_files:
        fname = os.path.basename(f)
        if "step00" in fname: continue
        if any(x in fname for x in ["step01", "step02", "step03", "step04", "step05", "step06"]):
            execution_list.append({"path": f, "type": "normal"})

    total = len(selected_topics)
    completed_children = []  # {"keyword", "html", "url"} を蓄積

    for idx_t, topic in enumerate(selected_topics, 1):
        print(f"\n{'='*60}")
        print(f"  [{idx_t}/{total}] トピック: {topic[:50]}")
        print(f"{'='*60}")
        keyword = run_step00_keyword(selected_api_key, topic, selected_prompt_path)

        print("\n🚀 子記事生成を開始します...")
        success, final_content, log_history = run_article_generation_child(
            selected_api_key, execution_list, keyword, is_moechin=False, selected_site=selected_site
        )

        if success:
            print("\n🎉 本文生成が完了しました！")
            check_keyword_density(final_content, keyword)
            print("\n📤 WordPress下書き投稿中...")
            child_post_url = post_to_wordpress(selected_site, f"【自動生成子記事】{keyword[:30]}...", final_content)
            if log_history: save_log_child(keyword, log_history)
            completed_children.append({
                "keyword": keyword,
                "html": final_content,
                "url": child_post_url if isinstance(child_post_url, str) else "",
            })
            _mark_workflow_child_topic(
                selected_site.get("name", ""),
                prefill_parent_keyword,
                topic,
                "done",
                child_post_url if isinstance(child_post_url, str) else "",
            )
            if idx_t < total:
                print(f"\n⏭️  次のトピックへ進みます（残り{total - idx_t}件）...")
                time.sleep(3)
        else:
            print("\n⚠️ 処理が中断されました。")
            if log_history: save_log_child(keyword, log_history)
            if idx_t < total:
                cont = arrow_menu("次のトピックを続けますか？", ["続ける", "終了"], allow_back=False)
                if cont != 0:
                    break

    # ── 全子記事完了後: まとめてメタ情報プロンプトを生成 ──
    if completed_children:
        after = arrow_menu(
            f"子記事 {len(completed_children)}件 完了 ─ 次のステップ",
            [f"メタ情報プロンプトをまとめて生成（{len(completed_children)}件分）", "終了"],
            allow_back=False
        )
        if after == 0:
            _generate_step9_batch(completed_children, selected_site)
        else:
            input("\nEnterで終了...")
    else:
        input("\n子記事が1件も完了しませんでした。Enterで終了...")


# ============================================================
# モード4: 子記事作成（もえちん）
# ============================================================
def run_mode_child_moechin():
    print("\n" + "="*60)
    print("  子記事作成（もえちん専用）")
    print("="*60)
    os.makedirs(CHILD_WORDPRESS_DATA, exist_ok=True)
    os.makedirs(CHILD_LOGS, exist_ok=True)

    selected_api_key = select_api_key(API_KEYS_MOECHIN)
    if selected_api_key is None:
        return  # メインメニューへ戻る

    selected_site = SITES_MOECHIN["7"]
    print(f"\n✅ サイト: {selected_site['name']}")

    prompt_variants = PROMPT_TYPES_CHILD_MOECHIN.get(selected_site['type'], {})
    if not prompt_variants:
        return print("❌ プロンプト設定が見つかりません。")
    if len(prompt_variants) == 1:
        prompts_info = list(prompt_variants.values())[0]
    else:
        variant_names = [v['name'] for v in prompt_variants.values()]
        v_idx = arrow_menu("プロンプト版を選択", variant_names, allow_back=True)
        if v_idx == -1:
            return
        prompts_info = list(prompt_variants.values())[v_idx]
    selected_prompt_path = os.path.join(PROMPT_BASE_DIR, prompts_info['path'])

    # ── internal_linksファイルからトピック案を自動取得（複数選択対応） ──
    selected_topics = []
    links_candidates = get_internal_links_source_candidates(site_filter="moechin", limit=20, dedupe_keyword=True)
    if links_candidates:
        file_options = [
            format_internal_links_candidate_label(c, is_recommended=(i == 0))
            for i, c in enumerate(links_candidates)
        ]
        file_options.append("過去・重複候補もすべて表示する（時間がかかる場合あり）")
        file_options.append("手動入力（ファイルを使わない）")
        f_idx = arrow_menu(
            "【内部リンクファイルを選択】\n"
            "  親記事作成後に保存された「子記事候補リスト」を選びます。\n"
            "  一番上は、このサイトで最後に作成された親記事の候補です。\n"
            "  ※ 違う親記事の子記事を作る場合だけ、別候補を選びます。",
            file_options, allow_back=False
        )
        f_idx = confirm_non_recommended_internal_link_choice(links_candidates, f_idx)
        if f_idx == len(links_candidates):
            print("\n   🔎 過去ログを含めて全件復元中です。ログ数が多い場合は少し時間がかかります...")
            links_candidates = get_internal_links_source_candidates(
                site_filter="moechin",
                limit=80,
                dedupe_keyword=False,
                max_parent_logs_scan=None,
            )
            file_options = [
                format_internal_links_candidate_label(c, is_recommended=(i == 0))
                for i, c in enumerate(links_candidates)
            ]
            file_options.append("手動入力（ファイルを使わない）")
            f_idx = arrow_menu(
                "【内部リンクファイルを選択（全件表示）】\n"
                "  過去・重複候補も含めて表示しています。\n"
                "  親記事名と作成日時を確認して選んでください。",
                file_options, allow_back=False
            )
            f_idx = confirm_non_recommended_internal_link_choice(links_candidates, f_idx)
        if 0 <= f_idx < len(links_candidates):
            links_text = read_internal_links_candidate(links_candidates[f_idx])
            topic_labels = extract_child_topic_labels_from_links_text(links_text)
            if topic_labels:
                while True:
                    checked_indices = arrow_menu_multiselect(
                        "作成するトピック案を選択（複数可）\n"
                        "  Space: 選択切替   Enter: 開始   ESC: 手動入力へ\n"
                        "  [選択] = 作成する   [----] = この処理では作成しない",
                        topic_labels,
                        default_checked=[False] * len(topic_labels)
                    )
                    if checked_indices:
                        break
                    retry_idx = arrow_menu(
                        "作成するトピック案が選択されていません。\n"
                        "  Spaceで[選択]に切り替えてからEnterを押してください。",
                        [
                            "選択画面に戻る",
                            "手動入力へ進む",
                            "子記事作成を中止する",
                        ],
                        allow_back=False,
                    )
                    if retry_idx == 0:
                        continue
                    if retry_idx == 1:
                        checked_indices = []
                        break
                    return
                selected_topics = [topic_labels[i] for i in checked_indices]

    if not selected_topics:
        manual = input(f"\n【トピック案（文章OK）】: ").strip()
        if not manual: return
        selected_topics = [manual]

    # ── 選択トピックを順番に処理 ──
    step_files = sorted(glob.glob(os.path.join(selected_prompt_path, "step*.txt")))
    execution_list = []
    for f in step_files:
        fname = os.path.basename(f)
        if "step00" in fname: continue
        if any(x in fname for x in ["step01", "step02", "step03", "step04", "step05", "step06"]):
            execution_list.append({"path": f, "type": "normal"})

    total = len(selected_topics)
    completed_children = []  # {"keyword", "html", "url"} を蓄積

    for idx_t, topic in enumerate(selected_topics, 1):
        print(f"\n{'='*60}")
        print(f"  [{idx_t}/{total}] トピック: {topic[:50]}")
        print(f"{'='*60}")
        keyword = run_step00_keyword(selected_api_key, topic, selected_prompt_path)

        print("\n🚀 子記事生成を開始します...")
        success, final_content, log_history = run_article_generation_child(
            selected_api_key, execution_list, keyword, is_moechin=True, selected_site=selected_site
        )

        if success:
            print("\n🎉 本文生成が完了しました！")
            check_keyword_density(final_content, keyword)
            print("\n📤 WordPress下書き投稿中...")
            child_post_url = post_to_wordpress(selected_site, f"【自動生成子記事】{keyword[:30]}...", final_content)
            if log_history: save_log_child(keyword, log_history)
            completed_children.append({
                "keyword": keyword,
                "html": final_content,
                "url": child_post_url if isinstance(child_post_url, str) else "",
            })
            if idx_t < total:
                print(f"\n⏭️  次のトピックへ進みます（残り{total - idx_t}件）...")
                time.sleep(3)
        else:
            print("\n⚠️ 処理が中断されました。")
            if log_history: save_log_child(keyword, log_history)
            if idx_t < total:
                cont = arrow_menu("次のトピックを続けますか？", ["続ける", "終了"], allow_back=False)
                if cont != 0:
                    break

    # ── 全子記事完了後: まとめてメタ情報プロンプトを生成 ──
    if completed_children:
        after = arrow_menu(
            f"子記事 {len(completed_children)}件 完了 ─ 次のステップ",
            [f"メタ情報プロンプトをまとめて生成（{len(completed_children)}件分）", "終了"],
            allow_back=False
        )
        if after == 0:
            _generate_step9_batch(completed_children, selected_site)
        else:
            input("\nEnterで終了...")
    else:
        input("\n子記事が1件も完了しませんでした。Enterで終了...")


# ============================================================
# 足し算Promptジェネレーター
# ============================================================

def _tashizan_hex_darken(hex_color, factor=0.75):
    """16進数カラーコードを暗くする (factor: 0.0=黒 〜 1.0=元の色)"""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) != 6:
        return f"#{hex_color}"
    r = max(0, min(255, int(int(hex_color[0:2], 16) * factor)))
    g = max(0, min(255, int(int(hex_color[2:4], 16) * factor)))
    b = max(0, min(255, int(int(hex_color[4:6], 16) * factor)))
    return f"#{r:02x}{g:02x}{b:02x}"


def _tashizan_palette_from_theme(theme_hex):
    """テーマカラー1色からCSSパレット情報を生成する"""
    dark = _tashizan_hex_darken(theme_hex, 0.75)
    return {
        "theme_color":  theme_hex,
        "border_color": theme_hex,
        "bg_color":     "#f8f9fa",
        "header_bg":    f"linear-gradient(135deg, {theme_hex} 0%, {dark} 100%)",
        "btn_colors": [
            theme_hex,
            _tashizan_hex_darken(theme_hex, 0.88),
            _tashizan_hex_darken(theme_hex, 0.76),
            _tashizan_hex_darken(theme_hex, 0.64),
            _tashizan_hex_darken(theme_hex, 0.52),
            _tashizan_hex_darken(theme_hex, 0.40),
        ]
    }


# --- 案件データ管理 (cases.json) ---

def _tashizan_cases_path(site_name):
    """サイト別の cases.json パスを返す"""
    additions_dir = find_additions_folder(PROMPT_BASE_DIR)
    if not additions_dir:
        return None
    return os.path.join(additions_dir, site_name, "cases.json")


def _tashizan_load_cases(site_name):
    """cases.json から案件リストを読み込む。未存在なら空リスト。"""
    path = _tashizan_cases_path(site_name)
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("cases", [])
    except Exception:
        return []


def _tashizan_save_cases(site_name, cases):
    """案件リストを cases.json に保存する"""
    path = _tashizan_cases_path(site_name)
    if not path:
        print("   ⚠️ 保存先パスが解決できません。")
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {"site_name": site_name, "cases": cases}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


_SITE_SLUG_MAP = {
    "病院探し": "byouin",  "結びのマリッジ": "marriage",
    "LearnBiz": "learnbiz", "便利屋": "benriya",
    "ジャズ": "jazz",       "くるまの縁": "kuruma",
    "もえちん": "moechin",  "占いの手引書": "uranai",
}

# カタカナ→ローマ字変換テーブル（ヘボン式ベース）
_KANA_ROMAJI = {
    'ア':'a','イ':'i','ウ':'u','エ':'e','オ':'o',
    'カ':'ka','キ':'ki','ク':'ku','ケ':'ke','コ':'ko',
    'サ':'sa','シ':'shi','ス':'su','セ':'se','ソ':'so',
    'タ':'ta','チ':'chi','ツ':'tsu','テ':'te','ト':'to',
    'ナ':'na','ニ':'ni','ヌ':'nu','ネ':'ne','ノ':'no',
    'ハ':'ha','ヒ':'hi','フ':'fu','ヘ':'he','ホ':'ho',
    'マ':'ma','ミ':'mi','ム':'mu','メ':'me','モ':'mo',
    'ヤ':'ya','ユ':'yu','ヨ':'yo',
    'ラ':'ra','リ':'ri','ル':'ru','レ':'re','ロ':'ro',
    'ワ':'wa','ヲ':'wo','ン':'n',
    'ガ':'ga','ギ':'gi','グ':'gu','ゲ':'ge','ゴ':'go',
    'ザ':'za','ジ':'ji','ズ':'zu','ゼ':'ze','ゾ':'zo',
    'ダ':'da','ヂ':'di','ヅ':'du','デ':'de','ド':'do',
    'バ':'ba','ビ':'bi','ブ':'bu','ベ':'be','ボ':'bo',
    'パ':'pa','ピ':'pi','プ':'pu','ペ':'pe','ポ':'po',
    'キャ':'kya','キュ':'kyu','キョ':'kyo',
    'シャ':'sha','シュ':'shu','ショ':'sho',
    'チャ':'cha','チュ':'chu','チョ':'cho',
    'ニャ':'nya','ニュ':'nyu','ニョ':'nyo',
    'ヒャ':'hya','ヒュ':'hyu','ヒョ':'hyo',
    'ミャ':'mya','ミュ':'myu','ミョ':'myo',
    'リャ':'rya','リュ':'ryu','リョ':'ryo',
    'ギャ':'gya','ギュ':'gyu','ギョ':'gyo',
    'ジャ':'ja','ジュ':'ju','ジョ':'jo',
    'ビャ':'bya','ビュ':'byu','ビョ':'byo',
    'ピャ':'pya','ピュ':'pyu','ピョ':'pyo',
    'ヴァ':'va','ヴィ':'vi','ヴ':'vu','ヴェ':'ve','ヴォ':'vo',
    'ファ':'fa','フィ':'fi','フェ':'fe','フォ':'fo',
    'ティ':'ti','ディ':'di','デュ':'du',
    'ー':'',  # 長音符は無視
}
# ひらがなも対応（カタカナに変換してから処理）
_HIRA_OFFSET = ord('ア') - ord('あ')

def _to_romaji_slug(text):
    """日本語テキストをローマ字slugに変換する。
    カタカナ・ひらがな→ローマ字、英数字はそのまま、記号は-に。"""
    result = []
    i = 0
    # ひらがな→カタカナに統一
    normalized = ""
    for ch in text:
        if 'ぁ' <= ch <= 'ん':
            normalized += chr(ord(ch) + _HIRA_OFFSET)
        else:
            normalized += ch

    while i < len(normalized):
        # 2文字の拗音を先にチェック
        if i + 1 < len(normalized):
            two = normalized[i:i+2]
            if two in _KANA_ROMAJI:
                result.append(_KANA_ROMAJI[two])
                i += 2
                continue
        # 促音（ッ）: 次の子音を重ねる
        if normalized[i] == 'ッ' and i + 1 < len(normalized):
            nxt = normalized[i+1:i+2]
            if nxt in _KANA_ROMAJI and _KANA_ROMAJI[nxt]:
                result.append(_KANA_ROMAJI[nxt][0])  # 子音を重ねる
            i += 1
            continue
        # 1文字カナ
        if normalized[i] in _KANA_ROMAJI:
            result.append(_KANA_ROMAJI[normalized[i]])
            i += 1
            continue
        # ASCII英数字
        ch = normalized[i].lower()
        if ch.isascii() and ch.isalnum():
            result.append(ch)
        else:
            result.append('-')
        i += 1

    slug = ''.join(result)
    slug = re.sub(r'-{2,}', '-', slug).strip('-')
    return slug


def _default_h2_image_genre_id(genre_label):
    """H2画像ジャンル用のIDを作る。主要ジャンルは英語IDへ寄せる。"""
    label = genre_label or ""
    presets = [
        ("アンテナ", "antenna"),
        ("水", "water"),
        ("水漏れ", "water"),
        ("エアコン", "aircon"),
        ("給湯器", "heater"),
        ("結婚", "marriage"),
        ("婚活", "marriage"),
    ]
    for key, value in presets:
        if key in label:
            return value
    return _to_romaji_slug(label) or label


def _tashizan_add_case_wizard(site_name):
    """対話式で案件データを1件収集して返す。キャンセル時はNone。
    各ステップで 'b' を入力すると一つ前に戻れる。"""

    def _input_with_back(prompt_text):
        """入力を受け取る。'b' で戻る指示を返す。"""
        val = input(f"   {prompt_text}  (b=戻る): ").strip()
        if is_back_input(val):
            return None  # 戻る
        return val

    # ステップ管理
    step = 1
    name = url_af = url_gen = theme_color = lp_info = ""

    while True:
        os.system('cls')
        print("=" * 60)
        print(f"  新規案件の追加 ({site_name})")
        print("=" * 60)
        print("   ※ 各ステップで b を入力すると前に戻れます\n")

        if step == 1:
            # ① 案件名（必須）
            val = _input_with_back("① 案件名（サービス名）")
            if val is None:
                return None  # 最初のステップなのでキャンセル
            if not val:
                print("   ⚠️ 案件名は必須です。")
                input("   Enter...")
                continue
            name = val
            step = 2

        elif step == 2:
            print(f"   ① 案件名: {name}")
            # ② 一般URL（必須）
            print("   ────────────────────────────────────")
            print("   ※ AIが商品・サービス内容を確認するための公式/一般ページURLです。")
            print("   ※ 記事内CTAボタンには使いません。CTAには③のアフィリエイトURLを使います。")
            print("   ※ ASPの計測URLが読み取れない場合でも、ここに公式URLがあると記事品質が安定します。")
            print("   ────────────────────────────────────")
            val = _input_with_back("② 一般URL（AIが内容確認に使う公式ページURL）")
            if val is None:
                step = 1; continue
            if not val:
                print("   ⚠️ 一般URLは必須です（AIが商品・サービス内容を確認するために使います）。")
                input("   Enter...")
                continue
            url_gen = val
            step = 3

        elif step == 3:
            print(f"   ① 案件名: {name}")
            print(f"   ② 一般URL: {url_gen}")
            # ③ アフィリエイトURL（任意）
            print("   ────────────────────────────────────")
            print("   ※ ASPからまだ付与されていない場合は空Enterで一般URLを使用。")
            print("   ※ 記事内CTAボタンはこちらのURL、または後で変更したURLへ向きます。")
            print("     後で「アフィリエイトURL管理」メニューからいつでも変更できます。")
            print("   ────────────────────────────────────")
            val = _input_with_back("③ アフィリエイトURL（空Enter → 一般URLと同じ）")
            if val is None:
                step = 2; continue
            url_af = val if val else url_gen
            if url_af == url_gen:
                print("   ℹ️ 一般URLをアフィリエイトURLとして登録します（後で変更可）。")
            step = 4

        elif step == 4:
            print(f"   ① 案件名: {name}")
            print(f"   ② 一般URL: {url_gen}")
            print(f"   ③ アフィリエイトURL: {url_af}")
            # ④ テーマカラー
            print("   ────────────────────────────────────")
            print("   ※ 迷ったらデフォルト(#2E5C8A)でOK。後で変更できます。")
            print("   ────────────────────────────────────")
            val = _input_with_back("④ テーマカラー #RRGGBB（空Enter → #2E5C8A）")
            if val is None:
                step = 3; continue
            if not val:
                theme_color = "#2E5C8A"
                step = 5
            elif re.match(r'^#[0-9A-Fa-f]{6}$', val):
                theme_color = val
                step = 5
            else:
                print("   ⚠️ #RRGGBB 形式で入力してください（例: #008080）")
                input("   Enter...")
                continue

        elif step == 5:
            print(f"   ① 案件名: {name}")
            print(f"   ② 一般URL: {url_gen}")
            print(f"   ③ アフィリエイトURL: {url_af}")
            print(f"   ④ テーマカラー: {theme_color}")
            # ⑤ LP情報（任意）
            lp_choice = arrow_menu(
                "⑤ LP情報を追加しますか？\n\n"
                "    ■ 1. NotebookLM等の要約を貼り付ける（推奨）\n"
                "       画像LP・縦長LP・ASP計測URLなど、AIが直接読み取りにくいLPではこれが安定します。\n"
                "       公式URLだけでは拾えない料金・特徴・注意点を補足できます。\n\n"
                "    ■ 2. テキストファイルから読み込む\n"
                "       NotebookLM要約をtxt保存している場合はこちら。\n\n"
                "    ■ 3. 省略する\n"
                "       一般URLだけで十分読めるLP、または後で足し算Promptを手修正する場合はこちら。",
                [
                    "NotebookLM等の要約を貼り付ける（画像LPなら推奨）",
                    "テキストファイルから読み込む",
                    "省略する（URLだけで進める）",
                    "前の画面へ戻る",
                ],
                allow_back=True,
            )
            if lp_choice in (-1, 3):
                step = 4; continue
            if lp_choice == 0:
                print("\n   ⑤ LP要約テキストを貼り付けてください。")
                print("      NotebookLM等で作った要約を貼ると安定します。Enter3回で確定します。")
                lp_info = get_multiline_input("", eof_mode=False).strip()
            elif lp_choice == 1:
                file_path = _input_with_back("⑤ LP要約テキストファイルのパス")
                if file_path is None:
                    step = 4; continue
                potential_path = file_path.strip('"').strip("'")
                if not os.path.isfile(potential_path):
                    print("   ⚠️ ファイルが見つかりません。")
                    input("   Enter...")
                    continue
                try:
                    for enc in ['utf-8', 'utf-8-sig', 'cp932', 'shift_jis']:
                        try:
                            with open(potential_path, 'r', encoding=enc) as f:
                                lp_info = f.read().strip()
                            break
                        except UnicodeDecodeError:
                            continue
                    else:
                        lp_info = ""
                    if lp_info:
                        print(f"   ✅ ファイルから読み込みました（{len(lp_info)}文字）")
                    else:
                        print("   ⚠️ ファイルの読み込みに失敗しました。")
                        input("   Enter...")
                        continue
                except Exception as e:
                    print(f"   ⚠️ ファイル読み込みエラー: {e}")
                    input("   Enter...")
                    continue
            else:
                lp_info = ""
            step = 6

        elif step == 6:
            # 確認画面
            os.system('cls')
            print("=" * 60)
            print("  入力内容の確認")
            print("=" * 60)
            af_note = "  ※一般URLと同じ（後で変更可）" if url_af == url_gen else ""
            print(f"\n   ① 案件名:           {name}")
            print(f"   ② 一般URL:           {url_gen}")
            print(f"   ③ アフィリエイトURL: {url_af}{af_note}")
            print(f"   ④ テーマカラー:      {theme_color}")
            print(f"   ⑤ LP情報:            {'あり (' + str(len(lp_info)) + '文字)' if lp_info else 'なし'}")
            print()
            confirm_opts = ["この内容で案件登録する", "最初から入力し直す", "キャンセル"]
            c_idx = arrow_menu(
                "新規案件の登録内容を確認してください\n"
                "  登録すると cases.json と WordPress の [af_url] に保存されます。",
                confirm_opts,
                allow_back=True,
                back_label="キャンセル",
            )
            if c_idx == 0:
                break  # 登録確定
            elif c_idx == 1:
                step = 1; continue
            else:
                return None  # キャンセル

    created = datetime.datetime.now().strftime("%Y-%m-%d")
    af_slug = _af_link_generate_slug(site_name, name)
    case = {
        "name": name, "url_af": url_af, "url_gen": url_gen,
        "theme_color": theme_color,
        "lp_info": lp_info, "created": created,
        "af_slug": af_slug,
    }
    print(f"\n   ✅ 案件「{name}」を登録しました。")
    print(f"\n   " + "-" * 50)
    print(f"   【コピー用】案件: {name}")
    print(f"   アフィリエイトURL: {url_af}")
    print(f"   テーマカラー: {theme_color}")
    print(f"   アフィリエイトリンクSC: [af_url slug='{af_slug}']")
    print(f"   " + "-" * 50)

    # WordPressにアフィリエイトリンクを自動登録（環境未整備なら自動セットアップ）
    print(f"\n   📤 WordPressにアフィリエイトリンクを登録中...")
    if _af_link_ensure_setup(site_name):
        _af_link_register(site_name, af_slug, url_af)
    else:
        print(f"   ⚠️ WordPress連携に失敗しました。ツールの「アフィリエイトURL管理」から後で登録できます。")

    return case


# --- ショートコード自動生成 & WordPress固定ページ登録 ---

def _tashizan_generate_shortcode(site_name, cases):
    """複数案件モード用のショートコードslugを自動生成する"""
    site_prefix = _SITE_SLUG_MAP.get(site_name, "site")
    main_slug = _to_romaji_slug(cases[0]["name"])
    if not main_slug:
        main_slug = "cta"
    slug = f"{site_prefix}-{main_slug}-scroll-cta-v1"
    return f"[page_scode slug='{slug}']", slug


def _tashizan_get_site_config(site_name):
    """サイト名から SITES_ALL の設定を取得"""
    for cfg in SITES_ALL.values():
        if cfg["name"] == site_name:
            return cfg
    return None


# --- アフィリエイトリンク ショートコード管理 (af_url) ---

def _af_link_generate_slug(site_name, case_name):
    """案件名からアフィリエイトリンク用slugを自動生成する。
    形式: {site_prefix}-{romaji_name}-af"""
    site_prefix = _SITE_SLUG_MAP.get(site_name, "site")
    name_slug = _to_romaji_slug(case_name)
    if not name_slug:
        name_slug = "link"
    return f"{site_prefix}-{name_slug}-af"


def _af_link_api_headers(site_cfg):
    """WordPress REST API 用のヘッダーを生成"""
    credentials = f"{site_cfg['user']}:{site_cfg['pass'].replace(' ', '')}"
    token = base64.b64encode(credentials.encode()).decode('utf-8')
    return {'Authorization': f'Basic {token}', 'Content-Type': 'application/json'}


_AF_SNIPPET_CODE = r'''
// Affiliate Link Shortcode: [af_url slug='xxx']
function af_url_shortcode($atts) {
    $atts = shortcode_atts(['slug' => ''], $atts);
    $slug = sanitize_title($atts['slug']);
    if (empty($slug)) return '#';
    $urls = get_option('af_link_urls', []);
    return isset($urls[$slug]) ? esc_url($urls[$slug]) : '#';
}
add_shortcode('af_url', 'af_url_shortcode');

add_action('rest_api_init', function () {
    register_rest_route('af-links/v1', '/urls', [
        ['methods' => 'GET', 'callback' => function () {
            return new WP_REST_Response(get_option('af_link_urls', []), 200);
        }, 'permission_callback' => function () { return current_user_can('manage_options'); }],
        ['methods' => 'POST', 'callback' => function (WP_REST_Request $request) {
            $slug = sanitize_title($request->get_param('slug'));
            $url  = esc_url_raw($request->get_param('url'));
            if (empty($slug) || empty($url)) return new WP_REST_Response(['error' => 'slug and url required'], 400);
            $urls = get_option('af_link_urls', []);
            $is_update = isset($urls[$slug]); $old_url = $is_update ? $urls[$slug] : null;
            $urls[$slug] = $url; update_option('af_link_urls', $urls);
            return new WP_REST_Response(['action' => $is_update ? 'updated' : 'created', 'slug' => $slug, 'url' => $url, 'old_url' => $old_url], 200);
        }, 'permission_callback' => function () { return current_user_can('manage_options'); }],
    ]);
    register_rest_route('af-links/v1', '/urls/(?P<slug>[a-z0-9\-]+)', [
        'methods' => 'DELETE', 'callback' => function (WP_REST_Request $request) {
            $slug = sanitize_title($request['slug']);
            $urls = get_option('af_link_urls', []);
            if (!isset($urls[$slug])) return new WP_REST_Response(['error' => 'not found'], 404);
            $old_url = $urls[$slug]; unset($urls[$slug]); update_option('af_link_urls', $urls);
            return new WP_REST_Response(['action' => 'deleted', 'slug' => $slug, 'old_url' => $old_url], 200);
        }, 'permission_callback' => function () { return current_user_can('manage_options'); },
    ]);
});
'''


def _af_link_ensure_setup(site_name):
    """サイトに af_url ショートコード環境が整っているか確認し、なければ自動セットアップする。
    1. af-links REST API の疎通確認
    2. Code Snippets プラグインのインストール・有効化
    3. af_url ショートコードスニペットの登録
    戻り値: True=使用可能, False=セットアップ失敗"""
    site_cfg = _tashizan_get_site_config(site_name)
    if not site_cfg:
        return False
    base = site_cfg['url'].rstrip('/')
    headers = _af_link_api_headers(site_cfg)

    # ① af-links エンドポイントが既に存在するか確認
    try:
        r = requests.get(f"{base}/wp-json/af-links/v1/urls", headers=headers, timeout=15)
        if r.status_code == 200:
            return True  # 既にセットアップ済み
    except Exception:
        pass

    print(f"\n   ⚙️ {site_name}: af_url ショートコード環境をセットアップします...")

    # ② Code Snippets プラグインのインストール・有効化
    try:
        # まずプラグイン一覧を確認
        r_plugins = requests.get(f"{base}/wp-json/wp/v2/plugins", headers=headers, timeout=15)
        if r_plugins.status_code != 200:
            print(f"   ❌ プラグインAPI非対応 (HTTP {r_plugins.status_code})")
            return False

        installed = {p.get("plugin", ""): p for p in r_plugins.json()}
        cs_key = None
        for k in installed:
            if "code-snippets" in k:
                cs_key = k
                break

        if cs_key and installed[cs_key].get("status") == "active":
            print(f"   ℹ️ Code Snippets: 既にインスト   ル済み・有効")
        elif cs_key:
            # インストール済みだが無効 → 有効化
            print(f"   📤 Code Snippets を有効化中...")
            r_act = requests.put(
                f"{base}/wp-json/wp/v2/plugins/{cs_key}",
                headers=headers, json={"status": "active"}, timeout=30
            )
            if r_act.status_code not in [200, 201]:
                print(f"   ❌ 有効化失敗: HTTP {r_act.status_code}")
                return False
            print(f"   ✅ Code Snippets 有効化完了")
        else:
            # 未インストール → インストール＆有効化
            print(f"   📥 Code Snippets をインストール中...")
            r_inst = requests.post(
                f"{base}/wp-json/wp/v2/plugins",
                headers=headers,
                json={"slug": "code-snippets", "status": "active"},
                timeout=120
            )
            if r_inst.status_code not in [200, 201]:
                print(f"   ❌ インストール失敗: HTTP {r_inst.status_code}")
                print(f"      {r_inst.text[:200]}")
                return False
            print(f"   ✅ Code Snippets インストール・有効化完了")
    except Exception as e:
        print(f"   ❌ プラグイン操作エラー: {e}")
        return False

    # ③ af_url ショートコードスニペットを登録
    try:
        # 既に同名スニペットがあるか確認
        r_snips = requests.get(f"{base}/wp-json/code-snippets/v1/snippets", headers=headers, timeout=15)
        if r_snips.status_code == 200:
            for s in r_snips.json():
                if "Affiliate Link Manager" in s.get("name", ""):
                    if s.get("active"):
                        print(f"   ℹ️ af_url スニペット: 既に登録済み (ID: {s['id']})")
                    else:
                        # 無効なら有効化
                        requests.put(
                            f"{base}/wp-json/code-snippets/v1/snippets/{s['id']}",
                            headers=headers, json={"active": True}, timeout=15
                        )
                        print(f"   ✅ af_url スニペット有効化 (ID: {s['id']})")
                    # 疎通確認
                    import time; time.sleep(1)
                    r_check = requests.get(f"{base}/wp-json/af-links/v1/urls", headers=headers, timeout=15)
                    return r_check.status_code == 200

        print(f"   📤 af_url スニペットを登録中...")
        r_create = requests.post(
            f"{base}/wp-json/code-snippets/v1/snippets",
            headers=headers,
            json={
                "name": "Affiliate Link Manager (af_url shortcode + REST API)",
                "desc": "アフィリエイトリンクをショートコード[af_url]で管理",
                "code": _AF_SNIPPET_CODE.strip(),
                "active": True, "scope": "global", "priority": 10,
            },
            timeout=30
        )
        if r_create.status_code in [200, 201]:
            print(f"   ✅ af_url スニペット登録完了 (ID: {r_create.json().get('id')})")
        else:
            print(f"   ❌ スニペット登録失敗: HTTP {r_create.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ スニペット操作エラー: {e}")
        return False

    # 最終疎通確認
    import time; time.sleep(1)
    try:
        r_final = requests.get(f"{base}/wp-json/af-links/v1/urls", headers=headers, timeout=15)
        if r_final.status_code == 200:
            print(f"   ✅ セットアップ完了！af-links API 疎通確認OK")
            return True
        else:
            print(f"   ⚠️ セットアップは完了し  したが、API疎通に失敗 (HTTP {r_final.status_code})")
            return False
    except Exception:
        print(f"   ⚠️ 最終疎通確認に失敗しましたが、スニペットは登録済みです。")
        return True


def _af_link_list(site_name):
    """WordPress上の全アフィリエイトリンクを取得"""
    site_cfg = _tashizan_get_site_config(site_name)
    if not site_cfg:
        return None
    api_url = site_cfg['url'].rstrip('/') + "/wp-json/af-links/v1/urls"
    headers = _af_link_api_headers(site_cfg)
    try:
        res = requests.get(api_url, headers=headers, timeout=30)
        if res.status_code == 200:
            return res.json()
        else:
            print(f"   ⚠️ リンク一覧取得失敗: HTTP {res.status_code}")
            return None
    except Exception as e:
        print(f"   ⚠️ 通信エラー: {e}")
        return None


def _af_link_register(site_name, slug, url):
    """WordPress にアフィリエイトリンクを登録/更新"""
    site_cfg = _tashizan_get_site_config(site_name)
    if not site_cfg:
        print(f"   ⚠️ サイト「{site_name}」の設定が見つかりません。")
        return False
    api_url = site_cfg['url'].rstrip('/') + "/wp-json/af-links/v1/urls"
    headers = _af_link_api_headers(site_cfg)
    try:
        res = requests.post(api_url, headers=headers, json={"slug": slug, "url": url}, timeout=30)
        if res.status_code == 200:
            data = res.json()
            action = data.get("action", "unknown")
            if action == "updated":
                old = data.get("old_url", "?")
                print(f"   ✅ リンク更新: {slug}")
                print(f"      旧URL: {old}")
                print(f"      新URL: {url}")
            else:
                print(f"   ✅ リンク登録: {slug} → {url}")
            return True
        else:
            print(f"   ❌ リンク登録失敗: HTTP {res.status_code}")
            print(f"      {res.text[:200]}")
            return False
    except Exception as e:
        print(f"   ❌ 通信エラー: {e}")
        return False


def _af_link_delete(site_name, slug):
    """WordPress からアフィリエイトリンクを削除"""
    site_cfg = _tashizan_get_site_config(site_name)
    if not site_cfg:
        return False
    api_url = site_cfg['url'].rstrip('/') + f"/wp-json/af-links/v1/urls/{slug}"
    headers = _af_link_api_headers(site_cfg)
    try:
        res = requests.delete(api_url, headers=headers, timeout=30)
        if res.status_code == 200:
            print(f"   ✅ リンク削除: {slug}")
            return True
        else:
            print(f"   ❌ 削除失敗: HTTP {res.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ 通信エラー: {e}")
        return False


def _tashizan_register_shortcode_page(site_name, shortcode, title_label):
    """WordPressに固定ページを非公開で自動登録し、ショートコードを有効化する"""
    site_cfg = _tashizan_get_site_config(site_name)
    if not site_cfg:
        print(f"   ⚠️ サイト「{site_name}」の設定が見つかりません。手動で固定ページを作成してください。")
        return False

    # ショートコードからslugを抽出: [page_scode slug='xxx'] → xxx
    slug_match = re.search(r"slug=['\"]([^'\"]+)['\"]", shortcode)
    if not slug_match:
        print(f"   ⚠️ ショートコードからslugを抽出できません: {shortcode}")
        return False
    slug = slug_match.group(1)

    wp_url = site_cfg['url'].rstrip('/') + "/wp-json/wp/v2/pages"
    credentials = f"{site_cfg['user']}:{site_cfg['pass'].replace(' ', '')}"
    token = base64.b64encode(credentials.encode()).decode('utf-8')
    headers = {'Authorization': f'Basic {token}', 'Content-Type': 'application/json'}

    # まず同じslugの固定ページが既に存在するかチェック
    try:
        check_res = requests.get(
            wp_url, headers=headers,
            params={"slug": slug, "status": "private,publish,draft"},
            timeout=30
        )
        if check_res.status_code in [200, 201]:
            existing = check_res.json()
            if existing:
                print(f"   ℹ️ slug「{slug}」の固定ページは既に存在します（ID: {existing[0]['id']}）")
                return True
    except Exception:
        pass  # チェック失敗しても登録は試みる

    page_data = {
        "title": f"{title_label} スクロールCTA",
        "slug": slug,
        "content": f"<!-- スクロールCTAボックス用固定ページ -->\n<p>このページはショートコード [{shortcode}] 用です。CTAコンテンツは記事作成時に設定されます。</p>",
        "status": "private",
    }

    print(f"   📤 WordPress固定ページを登録中... ({site_cfg['name']})")
    try:
        res = requests.post(wp_url, headers=headers, json=page_data, timeout=60)
        if res.status_code in [200, 201]:
            data = res.json()
            print(f"   ✅ 固定ページ登録成功！ ID: {data.get('id')}  slug: {slug}")
            return True
        else:
            print(f"   ❌ 固定ページ登録失敗: HTTP {res.status_code}")
            print(f"      {res.text[:200]}")
            return False
    except Exception as e:
        print(f"   ❌ 通信エラー: {e}")
        return False


# --- h2_images フィルタリング ---

def _h2_images_json_path():
    additions_dir = find_additions_folder(PROMPT_BASE_DIR)
    if not additions_dir:
        return None
    return os.path.join(additions_dir, "h2_images.json")


def _load_h2_images_data():
    h2_path = _h2_images_json_path()
    if not h2_path or not os.path.exists(h2_path):
        return {"_meta": {}, "images": []}, h2_path
    with open(h2_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        data = {"_meta": {}, "images": []}
    if not isinstance(data.get("images"), list):
        data["images"] = []
    return data, h2_path


def _save_h2_images_data(data):
    h2_path = _h2_images_json_path()
    if not h2_path:
        raise RuntimeError("00_additionsフォルダが見つかりません。")
    meta = data.setdefault("_meta", {})
    meta["schema_note"] = (
        "source=サイト名、addition_file/addition_key=足し算Prompt紐づけ、"
        "genre/genre_label=画像セット分類。未設定の既存画像も後方互換で利用可能。"
    )
    with open(h2_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return h2_path


def _list_h2_image_source_sets(site_name):
    """流用元として選べる、実際に画像が登録済みのH2画像セット一覧を返す。"""
    data, _ = _load_h2_images_data()
    images = data.get("images", []) if isinstance(data, dict) else []
    groups = {}
    legacy = []

    for img in images:
        if not isinstance(img, dict) or img.get("source") != site_name:
            continue
        addition_file = str(img.get("addition_file") or "").strip()
        addition_key = str(img.get("addition_key") or "").strip()
        if addition_file or addition_key:
            key = addition_file or addition_key
            groups.setdefault(key, []).append(img)
        else:
            legacy.append(img)

    results = []
    for key, group in sorted(groups.items(), key=lambda kv: kv[0]):
        label = f"{key}（登録画像 {len(group)}枚）"
        results.append({"label": label, "source_label": key, "images": group})
    if legacy:
        results.append({
            "label": f"サイト共通画像セット（旧登録・{len(legacy)}枚）",
            "source_label": "サイト共通画像セット（旧登録）",
            "images": legacy,
        })
    return results


def _select_h2_image_source_set(site_name, target_base=None):
    """画像セット流用元を、登録済み画像が存在するものだけから選ばせる。"""
    source_sets = _list_h2_image_source_sets(site_name)
    if not source_sets:
        print(f"   ⚠️ {site_name} に流用できるH2画像セットが登録されていません。")
        print("      先に「新しいH2画像セット作成」または「作成済み画像を登録」を実行してください。")
        return None

    target_line = f"  流用先: {target_base}\n" if target_base else ""
    labels = [s["label"] for s in source_sets] + ["キャンセル"]
    idx = arrow_menu(
        f"流用元の画像セットを選択（{site_name} 用）\n"
        f"{target_line}"
        "  実際に画像が登録済みのセットだけを表示しています。\n"
        "  旧形式のサイト共通画像は「サイト共通画像セット」として表示します。",
        labels,
        allow_back=True,
    )
    if idx == -1 or idx >= len(source_sets):
        return None
    return source_sets[idx]


def _remove_h2_image_mappings_for_addition(site_name, addition_name):
    """削除した案件に紐づくH2画像マッピングだけを解除する。

    画像ファイルやWordPressメディア本体は削除しない。再テスト時に
    旧Prompt名の画像セットが自動流用されるのを避けるための掃除。
    """
    if not addition_name:
        return 0
    data, h2_path = _load_h2_images_data()
    images = data.get("images", [])
    if not images:
        return 0

    safe_name = re.sub(r'[\\/:*?"<>|&]+', "_", str(addition_name)).strip()
    candidates = {
        str(addition_name).strip(),
        safe_name,
        f"{str(addition_name).strip()}.txt",
        f"{safe_name}.txt",
    }
    stems = {os.path.splitext(x)[0] for x in candidates}

    kept = []
    removed = 0
    for img in images:
        if not isinstance(img, dict):
            kept.append(img)
            continue
        if img.get("source") != site_name:
            kept.append(img)
            continue
        addition_file = str(img.get("addition_file") or "")
        addition_key = str(img.get("addition_key") or "")
        file_base = os.path.basename(addition_file)
        file_stem = os.path.splitext(file_base)[0]
        if addition_file in candidates or file_base in candidates or addition_key in candidates or file_stem in stems:
            removed += 1
            continue
        kept.append(img)

    if removed:
        data["images"] = kept
        _save_h2_images_data(data)
    return removed


def _extract_image_urls_from_pasted_text(text):
    urls = _extract_image_urls_from_text(text)
    plain_urls = re.findall(r'https?://[^\s<>"\']+', text or "")
    for url in plain_urls:
        clean = url.strip().rstrip("),.、。")
        if re.search(r'\.(?:jpg|jpeg|png|webp|gif)(?:[?#].*)?$', clean, flags=re.IGNORECASE):
            urls.append(clean)
    return list(dict.fromkeys(urls))


def _h2_image_registry_wizard(site_name):
    """足し算Promptに紐づくH2画像セットをh2_images.jsonへ登録する。"""
    site_cfg = next((cfg for cfg in SITES_ALL.values() if cfg.get("name") == site_name), None)
    if not site_cfg:
        print(f"   ⚠️ サイト設定が見つかりません: {site_name}")
        input("   Enterで戻ります...")
        return

    addition_path = select_addition_file(
        site_cfg,
        f"H2画像セットを登録する足し算Promptを選択（{site_name} 用）\n"
        "  このPromptを選んだ記事だけで使うH2画像セットとして登録します。\n"
        "  新しいジャンル画像を登録したいPromptを選んでください。",
    )
    if not addition_path:
        print("   ℹ️ 足し算Promptが選択されませんでした。")
        input("   Enterで戻ります...")
        return

    addition_base = os.path.basename(addition_path)
    addition_key = os.path.splitext(addition_base)[0]
    default_genre = _to_romaji_slug(addition_key) or addition_key

    os.system('cls')
    print("=" * 60)
    print("  H2画像セット登録")
    print("=" * 60)
    print(f"  サイト: {site_name}")
    print(f"  足し算Prompt: {addition_base}")
    print()
    genre_label = input(f"  画像ジャンル名 [{addition_key}]: ").strip() or addition_key
    genre = normalize_user_input(input(f"  genre ID（半角推奨） [{default_genre}]: ")) or default_genre
    common_keywords_raw = input("  共通キーワード（カンマ区切り・任意）: ").strip()
    common_keywords = [x.strip() for x in common_keywords_raw.replace("、", ",").split(",") if x.strip()]

    pasted = get_multiline_input(
        "\n【画像URLまたはWordPressの<img>タグを貼り付け】\n"
        "ImageFX等で作成し、WordPressメディアへアップロード済みの画像URL/<img>タグを貼ってください。\n"
        "複数行OK。Enter 5回で確定します:"
    )
    urls = _extract_image_urls_from_pasted_text(pasted)
    if not urls:
        print("   ⚠️ 画像URLが見つかりませんでした。")
        input("   Enterで戻ります...")
        return

    data, h2_path = _load_h2_images_data()
    images = data.setdefault("images", [])
    existing = {
        (
            img.get("source", ""),
            img.get("addition_file", ""),
            img.get("url", ""),
        )
        for img in images if isinstance(img, dict)
    }

    added = 0
    skipped = 0
    for i, url in enumerate(urls, start=1):
        os.system('cls')
        print("=" * 60)
        print(f"  H2画像 {i}/{len(urls)}")
        print("=" * 60)
        print(f"  URL: {url}")
        print(f"  サイト: {site_name}")
        print(f"  足し算Prompt: {addition_base}")
        print(f"  ジャンル: {genre_label} ({genre})")
        print()
        kw_raw = input("  この画像のキーワード（空なら共通+ジャンル名）: ").strip()
        kws = [x.strip() for x in kw_raw.replace("、", ",").split(",") if x.strip()]
        if not kws:
            kws = list(dict.fromkeys(common_keywords + [genre_label, addition_key]))
        memo = input("  メモ/用途（任意）: ").strip()

        key = (site_name, addition_base, url)
        if key in existing:
            skipped += 1
            print("   ℹ️ 既に同じURLが登録済みのためスキップしました。")
            input("   Enterで次へ...")
            continue

        images.append({
            "keywords": kws,
            "url": url,
            "source": site_name,
            "genre": genre,
            "genre_label": genre_label,
            "addition_file": addition_base,
            "addition_key": addition_key,
            "memo": memo,
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        existing.add(key)
        added += 1

    saved_path = _save_h2_images_data(data)
    print("\n" + "=" * 60)
    print("  H2画像セット登録 完了")
    print("=" * 60)
    print(f"  追加: {added}件 / スキップ: {skipped}件")
    print(f"  保存先: {saved_path}")
    print(f"  次回以降、{addition_base} 選択時にこの画像セットが優先候補になります。")
    input("\n   Enterで戻ります...")


def _h2_image_reuse_existing_set_wizard(site_name):
    """既存のH2画像セットを、別の足し算Promptにも紐づけて流用する。"""
    site_cfg = next((cfg for cfg in SITES_ALL.values() if cfg.get("name") == site_name), None)
    if not site_cfg:
        print(f"   ⚠️ サイト設定が見つかりません: {site_name}")
        input("   Enterで戻ります...")
        return

    source_set = _select_h2_image_source_set(site_name)
    if not source_set:
        print("   ℹ️ 流用元が選択されませんでした。")
        input("   Enterで戻ります...")
        return

    target_path = select_addition_file(
        site_cfg,
        f"流用先のPromptを選択（{site_name} 用）\n"
        "  上で選んだ画像セットを、このPromptでも使えるようにします。\n"
        "  例: 流用先はリングベルライト.txt です。",
        skip_label="キャンセル",
    )
    if not target_path:
        print("   ℹ️ 流用先が選択されませんでした。")
        input("   Enterで戻ります...")
        return

    source_base = source_set["source_label"]
    target_base = os.path.basename(target_path)
    if source_base == target_base:
        print("   ⚠️ 流用元と流用先が同じです。別のPromptを選んでください。")
        input("   Enterで戻ります...")
        return

    result = _h2_image_reuse_images_to_addition(
        site_name,
        None,
        target_base,
        confirm=True,
        source_images_override=source_set["images"],
        source_label=source_base,
    )
    if result:
        input("\n   Enterで戻ります...")


def _h2_image_reuse_images_to_addition(site_name, source_path, target_base, confirm=False, source_images_override=None, source_label=None):
    """既存Promptの画像セットを target_base の足し算Prompt名へ紐づけて流用する。"""
    data, h2_path = _load_h2_images_data()
    images = data.setdefault("images", [])
    source_base = source_label or (os.path.basename(source_path) if source_path else "選択した画像セット")
    if source_images_override is not None:
        source_images = list(source_images_override)
    else:
        source_keys = _addition_keys_from_path(source_path)
        source_images = [
            img for img in images
            if isinstance(img, dict)
            and img.get("source") == site_name
            and _image_matches_addition(img, source_keys)
        ]
    if not source_images:
        print(f"   ⚠️ {source_base} に紐づく画像セットが見つかりません。")
        return False

    target_key = os.path.splitext(target_base)[0]
    existing = {
        (
            img.get("source", ""),
            img.get("addition_file", ""),
            img.get("url", ""),
        )
        for img in images if isinstance(img, dict)
    }

    os.system('cls')
    print("=" * 60)
    print("  既存H2画像セットの流用登録")
    print("=" * 60)
    print(f"  サイト: {site_name}")
    print(f"  流用元: {source_base}")
    print(f"  流用先: {target_base}")
    print(f"  流用対象画像: {len(source_images)}件")
    print()
    if confirm:
        confirm_idx = arrow_menu(
            "この内容で、同じ画像URLを流用先Promptにも紐づけますか？\n"
            "  画像ファイル自体は複製せず、h2_images.json上の紐づけだけ追加します。\n"
            "  リングベルとリングベルライトのように同じ素材を使い回す時に使います。",
            ["流用登録する", "やめる"],
            allow_back=False,
        )
        if confirm_idx != 0:
            return False

    added = 0
    skipped = 0
    for img in source_images:
        url = img.get("url", "")
        key = (site_name, target_base, url)
        if key in existing:
            skipped += 1
            continue
        copied = dict(img)
        copied["addition_file"] = target_base
        copied["addition_key"] = target_key
        copied["genre_label"] = copied.get("genre_label") or target_key
        copied["genre"] = copied.get("genre") or (_to_romaji_slug(target_key) or target_key)
        copied["memo"] = (copied.get("memo") or "") + f" / {source_base} から流用"
        copied["created_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        images.append(copied)
        existing.add(key)
        added += 1

    saved_path = _save_h2_images_data(data)
    print("\n" + "=" * 60)
    print("  H2画像セット流用登録 完了")
    print("=" * 60)
    print(f"  追加: {added}件 / 既存スキップ: {skipped}件")
    print(f"  保存先: {saved_path}")
    print(f"  次回以降、{target_base} 選択時にも {source_base} の画像セットを使えます。")
    return True


def _wp_basic_auth_header(site_cfg):
    credentials = f"{site_cfg['user']}:{site_cfg['pass'].replace(' ', '')}"
    token = base64.b64encode(credentials.encode()).decode('utf-8')
    return {'Authorization': f'Basic {token}'}


def _prepare_image_upload_file(src_path, compress=True, max_width=1408, quality=82):
    """WordPressアップロード用画像を用意する。Pillowがなければ原本を使う。"""
    import tempfile
    import mimetypes

    src_path = os.path.abspath(src_path.strip().strip('"'))
    if not os.path.exists(src_path):
        return None, None, f"ファイルが見つかりません: {src_path}"

    if not compress:
        mime = mimetypes.guess_type(src_path)[0] or "application/octet-stream"
        return src_path, mime, ""

    try:
        from PIL import Image
    except Exception:
        mime = mimetypes.guess_type(src_path)[0] or "application/octet-stream"
        return src_path, mime, "Pillow未導入のため、圧縮せず原本をアップロードします。"

    try:
        img = Image.open(src_path)
        if img.width > max_width:
            ratio = max_width / float(img.width)
            new_h = int(img.height * ratio)
            img = img.resize((max_width, new_h), Image.LANCZOS)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        base = os.path.splitext(os.path.basename(src_path))[0]
        safe_base = re.sub(r'[^A-Za-z0-9_-]+', '-', base).strip("-") or "h2-image"
        out_path = os.path.join(tempfile.gettempdir(), f"{safe_base}_wp_{int(time.time())}.jpg")
        img.save(out_path, "JPEG", quality=quality, optimize=True)
        return out_path, "image/jpeg", ""
    except Exception as e:
        mime = mimetypes.guess_type(src_path)[0] or "application/octet-stream"
        return src_path, mime, f"画像圧縮に失敗したため原本を使います: {e}"


def _upload_media_to_wordpress(site_cfg, file_path, title=None, compress=True):
    upload_path, mime, warn = _prepare_image_upload_file(file_path, compress=compress)
    if warn:
        print(f"   ⚠️ {warn}")
    if not upload_path:
        print(f"   ❌ {mime}")
        return None

    endpoint = site_cfg["url"].rstrip("/") + "/wp-json/wp/v2/media"
    headers = _wp_basic_auth_header(site_cfg)
    filename = os.path.basename(upload_path)
    headers.update({
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": mime,
    })
    try:
        with open(upload_path, "rb") as f:
            res = requests.post(endpoint, headers=headers, data=f, timeout=120)
        if res.status_code not in (200, 201):
            print(f"   ❌ メディアアップロード失敗: HTTP {res.status_code}")
            print(f"      {res.text[:200]}")
            return None
        data = res.json()
        media_id = data.get("id")
        media_url = data.get("source_url") or data.get("guid", {}).get("rendered", "")
        if title and media_id:
            try:
                requests.post(
                    f"{endpoint}/{media_id}",
                    headers={**_wp_basic_auth_header(site_cfg), "Content-Type": "application/json"},
                    json={"title": title, "alt_text": title},
                    timeout=30,
                )
            except Exception:
                pass
        print(f"   ✅ アップロード成功: ID {media_id} / {media_url}")
        return media_url
    except Exception as e:
        print(f"   ❌ メディアアップロードエラー: {e}")
        return None


def _h2_image_upload_and_register_wizard(site_name):
    """ローカル画像ファイルをWordPressへアップロードし、H2画像セットへ登録する。"""
    site_cfg = next((cfg for cfg in SITES_ALL.values() if cfg.get("name") == site_name), None)
    if not site_cfg:
        print(f"   ⚠️ サイト設定が見つかりません: {site_name}")
        input("   Enterで戻ります...")
        return

    addition_path = select_addition_file(
        site_cfg,
        f"アップロード画像を登録する足し算Promptを選択（{site_name} 用）\n"
        "  WordPressへアップロードした画像を、どのPrompt専用のH2画像セットにするか選びます。",
    )
    if not addition_path:
        print("   ℹ️ 足し算Promptが選択されませんでした。")
        input("   Enterで戻ります...")
        return

    os.system('cls')
    print("=" * 60)
    print("  H2画像アップロード＆登録")
    print("=" * 60)
    print(f"  サイト: {site_name}")
    print(f"  足し算Prompt: {os.path.basename(addition_path)}")
    print("  ※ WordPressアプリケーションパスワードが設定済みのサイトで利用できます。")
    print()
    genre_label = input(f"  画像ジャンル名 [{os.path.splitext(os.path.basename(addition_path))[0]}]: ").strip()
    if not genre_label:
        genre_label = os.path.splitext(os.path.basename(addition_path))[0]
    default_genre = _default_h2_image_genre_id(genre_label)
    genre = normalize_user_input(input(f"  genre ID（半角推奨） [{default_genre}]: "))
    if not genre:
        genre = default_genre
    common_keywords_raw = input("  共通キーワード（カンマ区切り・任意）: ").strip()
    common_keywords = [x.strip() for x in common_keywords_raw.replace("、", ",").split(",") if x.strip()]
    compress_idx = arrow_menu("画像を圧縮/リサイズしてアップロードしますか？", ["圧縮する（表示速度と容量を優先）", "原本のままアップロード"], allow_back=False)
    compress = (compress_idx == 0)

    paths_text = get_multiline_input(
        "\n【アップロードする画像ファイルパス】\n"
        "ImageFX等で作った画像ファイルのフルパスを1行に1つずつ貼ってください。\n"
        "Enter 5回で確定します:"
    )
    file_paths = [line.strip().strip('"') for line in paths_text.splitlines() if line.strip()]
    if not file_paths:
        print("   ⚠️ ファイルパスが入力されませんでした。")
        input("   Enterで戻ります...")
        return

    data, _ = _load_h2_images_data()
    images = data.setdefault("images", [])
    existing_urls = {img.get("url") for img in images if isinstance(img, dict)}
    addition_base = os.path.basename(addition_path)
    addition_key = os.path.splitext(addition_base)[0]
    added = 0
    failed = 0
    uploaded_urls = []

    for i, file_path in enumerate(file_paths, start=1):
        print("\n" + "-" * 60)
        print(f"  [{i}/{len(file_paths)}] {file_path}")
        title = f"{genre_label} H2画像 {i}"
        media_url = _upload_media_to_wordpress(site_cfg, file_path, title=title, compress=compress)
        if not media_url:
            failed += 1
            continue
        uploaded_urls.append(media_url)
        if media_url in existing_urls:
            print("   ℹ️ 同じURLが登録済みのためh2_images.json登録はスキップしました。")
            continue
        kw_raw = input("   この画像のキーワード（空なら共通+ジャンル名）: ").strip()
        kws = [x.strip() for x in kw_raw.replace("、", ",").split(",") if x.strip()]
        if not kws:
            kws = list(dict.fromkeys(common_keywords + [genre_label, addition_key]))
        memo = input("   メモ/用途（任意）: ").strip()
        images.append({
            "keywords": kws,
            "url": media_url,
            "source": site_name,
            "genre": genre,
            "genre_label": genre_label,
            "addition_file": addition_base,
            "addition_key": addition_key,
            "memo": memo,
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        existing_urls.add(media_url)
        added += 1

    saved_path = _save_h2_images_data(data)
    print("\n" + "=" * 60)
    print("  H2画像アップロード＆登録 完了")
    print("=" * 60)
    print(f"  アップロード成功: {len(uploaded_urls)}件 / 失敗: {failed}件")
    print(f"  h2_images.json追加: {added}件")
    print(f"  保存先: {saved_path}")
    input("\n   Enterで戻ります...")


def _build_h2_image_prompt_generation_prompt(site_name, addition_name, genre_label, target_keyword, sample_info, image_count):
    """H2画像セット作成用のImageFXプロンプト生成依頼文。"""
    return f"""
あなたはSEO記事用のH2直下画像セットを設計する、ビジュアル戦略担当者です。

目的:
指定されたサイト/ジャンルの記事で使い回せる「定番H2画像セット」を作ります。
毎記事・毎H2で画像を生成するのではなく、7〜10枚程度の画像を先に作り、記事生成時にH2見出しへ合う画像を選ぶ運用です。

前提:
- 画像生成ツールは ImageFX を想定します。
- ただし画像内に文字、ロゴ、企業名、看板、読める書類文言は入れないでください。
- 横長16:9、実写風、日本の生活感、清潔感、信頼感を重視してください。
- 原則として読者が共感しやすい日本人女性、家族、専門スタッフを自然に配置してください。
- 固有サービス名や商標名を画像に出さないでください。
- 画像はWordPressメディアにアップロードしてURL登録する前提です。

入力情報:
- サイト名: {site_name}
- 足し算Prompt: {addition_name}
- 画像ジャンル: {genre_label}
- 想定キーワード/案件名: {target_keyword}
- 参考情報:
{sample_info or "（なし）"}
- 作成枚数: {image_count}枚

出力形式:
以下の形式で、画像{image_count}枚分を出力してください。
余計な前置きやMarkdown表は不要です。

1. [画像テーマ名]
用途:
[どんなH2見出しに使う画像か]

ImageFXプロンプト:
[ImageFXにそのまま貼れる日本語プロンプト。1段落。]

登録キーワード案:
[H2照合用キーワードをカンマ区切りで8〜12個]

メモ:
[登録時の補足。短く]

設計条件:
- 記事のH2に自然に対応できるよう、悩み導入、原因/仕組み、料金/比較、専門家/作業、注意点、解決後、まとめ向けをバランスよく含めてください。
- 同じ構図ばかりにしないでください。
- 「料金」「相談」「比較」など汎用語だけに寄らず、ジャンル固有語を必ず含めてください。
- 1枚はデフォルト画像候補として、まとめ/解決後に使いやすい画像にしてください。
""".strip()


def _save_h2_image_prompt_output(site_name, genre_label, output_text):
    out_dir = os.path.join(GOOGLE_DRIVE_BASE, "h2_image_prompts")
    os.makedirs(out_dir, exist_ok=True)
    safe_site = re.sub(r'[\\/:*?"<>|]', '', site_name).strip() or "site"
    safe_genre = re.sub(r'[\\/:*?"<>|]', '', genre_label).strip() or "genre"
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(out_dir, f"h2_image_prompts_{safe_site}_{safe_genre}_{ts}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(output_text)
    return path


def _h2_image_prompt_output_header(site_name, addition_path, genre_label, target_keyword, image_count):
    return (
        f"H2画像生成プロンプト\n"
        f"作成日: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"サイト: {site_name}\n"
        f"足し算Prompt: {os.path.basename(addition_path)}\n"
        f"画像ジャンル: {genre_label}\n"
        f"想定キーワード/案件名: {target_keyword}\n"
        f"作成枚数: {image_count}\n\n"
        f"登録時の推奨情報:\n"
        f"source: {site_name}\n"
        f"genre: {_default_h2_image_genre_id(genre_label)}\n"
        f"genre_label: {genre_label}\n"
        f"addition_file: {os.path.basename(addition_path)}\n"
        f"addition_key: {os.path.splitext(os.path.basename(addition_path))[0]}\n"
        f"\n{'='*60}\n\n"
    )


def _h2_image_prompt_generator_wizard(site_name):
    """Gemini APIでImageFX向けH2画像生成プロンプトを作る。"""
    site_cfg = next((cfg for cfg in SITES_ALL.values() if cfg.get("name") == site_name), None)
    if not site_cfg:
        print(f"   ⚠️ サイト設定が見つかりません: {site_name}")
        input("   Enterで戻ります...")
        return

    addition_path = select_addition_file(
        site_cfg,
        f"H2画像生成プロンプトを作る足し算Promptを選択（{site_name} 用）\n"
        "  これから作る画像を使いたい案件/ジャンルのPromptを選んでください。",
    )
    if not addition_path:
        print("   ℹ️ 足し算Promptが選択されませんでした。")
        input("   Enterで戻ります...")
        return

    os.system('cls')
    print("=" * 60)
    print("  H2画像生成プロンプト作成")
    print("=" * 60)
    print(f"  サイト: {site_name}")
    print(f"  足し算Prompt: {os.path.basename(addition_path)}")
    print()
    genre_label = input("  画像ジャンル名（例: アンテナ工事）: ").strip()
    if not genre_label:
        genre_label = os.path.splitext(os.path.basename(addition_path))[0]
    target_keyword = input("  想定キーワード/案件名（任意）: ").strip() or genre_label
    count_raw = normalize_user_input(input("  作成枚数 [10]: "))
    image_count = parse_menu_number(count_raw, 1, 99) if count_raw else 10
    if image_count is None:
        print("   ⚠️ 作成枚数を認識できませんでした。既定値の10枚で進めます。")
        image_count = 10
    image_count = max(5, min(12, image_count))

    sample_info = get_multiline_input(
        "\n【参考情報】\n"
        "代表記事URL、案件情報、避けたい画像、ターゲット読者などがあれば貼ってください。\n"
        "空でも実行できます。Enter 5回で確定します:"
    )

    prompt = _build_h2_image_prompt_generation_prompt(
        site_name,
        os.path.basename(addition_path),
        genre_label,
        target_keyword,
        sample_info,
        image_count,
    )

    print("\n  生成方法を選択してください。")
    print("  目安: Gemini APIで自動生成する場合、概算で入力1,000〜2,500トークン + 出力1,500〜3,000トークン程度です。")
    print("        画像を生成するのではなく、ImageFXへ貼る文章を作るだけなので、記事本文生成よりは軽めです。")
    mode_idx = arrow_menu(
        "H2画像生成プロンプト作成方法",
        [
            "Gemini APIで自動生成する（無料枠を少し消費）",
            "AI Studio/Claude貼り付け用プロンプトだけ保存する（API消費なし）",
        ],
        allow_back=True,
    )
    if mode_idx == -1:
        return

    header = _h2_image_prompt_output_header(site_name, addition_path, genre_label, target_keyword, image_count)
    if mode_idx == 1:
        save_path = _save_h2_image_prompt_output(
            site_name,
            genre_label,
            header
            + "以下をAI StudioまたはClaudeに貼り付けて実行してください。\n"
            + "実行後に出力されたImageFX向けプロンプトを使って画像を作成します。\n\n"
            + "=" * 60
            + "\n\n"
            + prompt
        )
        print(f"   ✅ API消費なしプロンプトを保存しました: {save_path}")
        open_file(save_path)
        input("\n   Enterで戻ります...")
        return

    api_key = select_api_key(API_KEYS_NORMAL if site_cfg.get("type") != "C" else API_KEYS_MOECHIN)
    if not api_key:
        print("   ℹ️ APIキーが選択されませんでした。")
        input("   Enterで戻ります...")
        return

    try:
        _load_genai()
        client = genai.Client(api_key=api_key)
        chat = client.chats.create(model=MODEL_CHILD, config=GEN_CONFIG)
        print("\n🖼️ GeminiでImageFX向け画像生成プロンプトを作成中...")
        response = _send_message_with_retry(chat, prompt, "H2画像生成プロンプト作成")
        output = response.text or ""
        if not output.strip():
            print("   ⚠️ 出力が空でした。")
            input("   Enterで戻ります...")
            return
        save_path = _save_h2_image_prompt_output(site_name, genre_label, header + output)
        print(f"   ✅ 保存しました: {save_path}")
        open_file(save_path)
        input("\n   Enterで戻ります...")
    except Exception as e:
        print(f"   ❌ H2画像生成プロンプト作成エラー: {e}")
        input("   Enterで戻ります...")


def _build_h2_image_prompt_revision_prompt(original_prompt, problem_text, desired_text):
    """失敗した画像生成プロンプトを作り直すための依頼文。"""
    return f"""
あなたはSEO記事用のH2直下画像セットを改善する、画像生成プロンプト編集者です。

目的:
Flow/ImageFX等で生成した画像に不自然な点が出たため、元の画像生成プロンプトを作り直します。
画像生成ツールへそのまま貼れる、1段落の日本語プロンプトだけを作ってください。

元の画像生成プロンプト:
{original_prompt}

発生した問題:
{problem_text}

希望する修正:
{desired_text or "元の用途を保ったまま、不自然な構図・文字・ロゴ・読める画面表示を避けてください。"}

必ず守る条件:
- 画像内に読める文字、ロゴ、ブランド名、会社名、看板、雑誌、新聞、書類の本文を入れない
- スマートフォンやタブレットを入れる場合、画面は「抽象的な光」「ぼかしたUI」「無地に近い表示」にする
- 手や指、端末の向きが自然に見える構図にする
- 日本の生活感、清潔感、信頼感を重視する
- 横長16:9、実写風、高画質
- 固有サービス名や商標名は出さない

出力:
修正版プロンプトのみ。説明、箇条書き、見出し、引用符は不要。
""".strip()


def _h2_image_prompt_revision_wizard(site_name):
    """不自然に生成された画像用に、ImageFX/Flow向けプロンプトを作り直す。"""
    os.system('cls')
    print("=" * 60)
    print("  H2画像プロンプト作り直し")
    print("=" * 60)
    print(f"  対象サイト: {site_name}")
    print()
    print("  画像生成で不自然な結果になった時に使います。")
    print("  例: スマホの背面に画面が出る、読める文字が入る、手が不自然、構図が用途と違う")
    print()

    original_prompt = get_multiline_input(
        "【元のImageFX/Flowプロンプト】\n"
        "作り直したい1枚分のプロンプトを貼ってください。\n"
        "Enter 5回で確定します:"
    ).strip()
    if not original_prompt:
        print("   ⚠️ 元プロンプトが入力されませんでした。")
        input("   Enterで戻ります...")
        return

    problem_text = get_multiline_input(
        "\n【何が不自然でしたか？】\n"
        "例: スマホの背面にグラフが表示された。画面や文字が不自然。\n"
        "Enter 5回で確定します:"
    ).strip()
    if not problem_text:
        problem_text = "生成画像に不自然な構図や読める文字が入った。"

    desired_text = get_multiline_input(
        "\n【どう直したいですか？ 任意】\n"
        "例: スマホ画面を見せず、机上の比較メモと悩む表情で業者比較を表現したい。\n"
        "Enter 5回で確定します:"
    ).strip()

    prompt = _build_h2_image_prompt_revision_prompt(original_prompt, problem_text, desired_text)
    mode_idx = arrow_menu(
        "作り直し方法",
        [
            "Gemini APIで修正版プロンプトを作る（無料枠を少し消費）",
            "AI Studio/Claude貼り付け用プロンプトだけ保存する（API消費なし）",
        ],
        allow_back=True,
    )
    if mode_idx == -1:
        return

    header = (
        f"H2画像プロンプト作り直し\n"
        f"作成日: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"サイト: {site_name}\n\n"
        f"元プロンプト:\n{original_prompt}\n\n"
        f"問題:\n{problem_text}\n\n"
        f"{'='*60}\n\n"
    )

    if mode_idx == 1:
        save_path = _save_h2_image_prompt_output(
            site_name,
            "prompt_revision",
            header + "以下をAI StudioまたはClaudeに貼り付けて実行してください。\n\n" + prompt
        )
        print(f"   ✅ API消費なしの作り直しプロンプトを保存しました: {save_path}")
        open_file(save_path)
        input("\n   Enterで戻ります...")
        return

    api_key = select_api_key(API_KEYS_NORMAL)
    if not api_key:
        print("   ℹ️ APIキーが選択されませんでした。")
        input("   Enterで戻ります...")
        return

    try:
        _load_genai()
        client = genai.Client(api_key=api_key)
        chat = client.chats.create(model=MODEL_CHILD, config=GEN_CONFIG)
        print("\n🖼️ Geminiで修正版プロンプトを作成中...")
        response = _send_message_with_retry(chat, prompt, "H2画像プロンプト作り直し")
        output = (response.text or "").strip()
        if not output:
            print("   ⚠️ 出力が空でした。")
            input("   Enterで戻ります...")
            return
        save_path = _save_h2_image_prompt_output(site_name, "prompt_revision", header + "修正版プロンプト:\n" + output + "\n")
        print("\n" + "=" * 60)
        print("  修正版プロンプト")
        print("=" * 60)
        print(output)
        print()
        print(f"   ✅ 保存しました: {save_path}")
        open_file(save_path)
        input("\n   Enterで戻ります...")
    except Exception as e:
        print(f"   ❌ H2画像プロンプト作り直しエラー: {e}")
        input("   Enterで戻ります...")


def _h2_image_quick_start_wizard(site_name):
    """H2画像セット作成の入口。初見でも次の操作を選べるようにする。"""
    while True:
        os.system('cls')
        print("=" * 60)
        print("  H2画像セット作成（初めての方はこちら）")
        print("=" * 60)
        print(f"  対象サイト: {site_name}")
        print()
        print("  目的:")
        print("    新しいジャンル用の画像を先に7〜10枚ほど用意し、")
        print("    親記事作成時にH2見出しへ合う画像だけを自動で使えるようにします。")
        print()
        print("  基本の流れ:")
        print("    1. 画像生成プロンプトを作る")
        print("    2. ImageFX等で画像を作る")
        print("    3. 作った画像をWordPressへアップロードして画像セット登録する")
        print("    4. 次回の記事生成から、そのジャンルの画像だけが優先候補になります")
        print()
        print("  迷ったら、まず 1 を選んでください。")
        print()

        action = arrow_menu(
            "今やりたいことを選んでください",
            [
                "推奨: 新しい画像セットを作る（まず画像生成プロンプトを作成）",
                "作成済み画像を登録する（WordPressアップロードまたはURL登録）",
                "既存画像セットを別Promptへ流用登録する",
                "補助操作を開く（確認・作り直しなど）",
                "戻る",
            ],
            allow_back=True,
        )
        if action in (-1, 4):
            return
        if action == 0:
            _h2_image_prompt_generator_wizard(site_name)
            continue
        if action == 1:
            reg_action = arrow_menu(
                "画像の登録方法を選んでください\n"
                "  画像ファイルがPCにあるなら1、すでにWordPress等にアップロード済みなら2です。",
                [
                    "作成済み画像をWordPressへアップロードして登録する",
                    "アップロード済み画像URLを登録する",
                    "戻る",
                ],
                allow_back=True,
            )
            if reg_action in (-1, 2):
                continue
            if reg_action == 0:
                _h2_image_upload_and_register_wizard(site_name)
            elif reg_action == 1:
                _h2_image_registry_wizard(site_name)
            continue
        if action == 2:
            _h2_image_reuse_existing_set_wizard(site_name)
            continue
        if action == 3:
            sub_action = arrow_menu(
                "補助操作を選んでください\n"
                "  通常の新規作成では使いません。確認や作り直しが必要な時だけ使います。",
                [
                    "登録済み画像セットを確認する",
                    "不自然だった画像プロンプトを作り直す",
                    "画像生成プロンプトだけ作る",
                    "戻る",
                ],
                allow_back=True,
            )
            if sub_action in (-1, 3):
                continue
            if sub_action == 0:
                _h2_image_status_wizard(site_name)
            elif sub_action == 1:
                _h2_image_prompt_revision_wizard(site_name)
            elif sub_action == 2:
                _h2_image_prompt_generator_wizard(site_name)
            continue


def _h2_image_status_wizard(site_name):
    """足し算Promptに紐づくH2画像セットの登録状況を確認する。"""
    site_cfg = next((cfg for cfg in SITES_ALL.values() if cfg.get("name") == site_name), None)
    if not site_cfg:
        print(f"   ⚠️ サイト設定が見つかりません: {site_name}")
        input("   Enterで戻ります...")
        return

    addition_path = select_addition_file(
        site_cfg,
        f"H2画像登録状況を確認する足し算Promptを選択（{site_name} 用）\n"
        "  どのPromptに画像セットが紐づいているか確認します。",
    )
    if not addition_path:
        print("   ℹ️ 足し算Promptが選択されませんでした。")
        input("   Enterで戻ります...")
        return

    data, h2_path = _load_h2_images_data()
    images = data.get("images", []) if isinstance(data, dict) else []
    addition_base = os.path.basename(addition_path)
    addition_keys = _addition_keys_from_path(addition_path)
    exact = []
    site_only = []
    legacy = []

    for img in images:
        if not isinstance(img, dict):
            continue
        if img.get("source") != site_name:
            continue
        addition_values = [
            str(img.get("addition_file", "") or ""),
            str(img.get("addition_key", "") or ""),
        ]
        if any(v and v in addition_keys for v in addition_values):
            exact.append(img)
        elif img.get("addition_file") or img.get("addition_key"):
            site_only.append(img)
        else:
            legacy.append(img)

    os.system('cls')
    print("=" * 60)
    print("  H2画像登録状況")
    print("=" * 60)
    print(f"  サイト: {site_name}")
    print(f"  足し算Prompt: {addition_base}")
    print(f"  h2_images.json: {h2_path or '未検出'}")
    print()
    print(f"  このPromptに紐づく画像: {len(exact)}件")
    print(f"  同サイトの別Prompt画像: {len(site_only)}件")
    print(f"  旧形式の同サイト画像: {len(legacy)}件")
    print()

    if exact:
        print("  ▼ このPromptで優先される画像")
        for i, img in enumerate(exact[:20], start=1):
            label = img.get("genre_label") or img.get("genre") or "未分類"
            kws = ", ".join((img.get("keywords") or [])[:5]) if isinstance(img.get("keywords"), list) else ""
            url = str(img.get("url") or "")
            print(f"    {i}. {label} / {kws}")
            print(f"       {url[:100]}")
        if len(exact) > 20:
            print(f"    ...ほか {len(exact) - 20}件")
    else:
        print("  ⚠️ この足し算Prompt専用のH2画像セットはまだ登録されていません。")
        print("     合わない画像を入れるくらいなら、画像なしで生成される方が安全です。")
        print("     必要な場合は「画像生成プロンプトを作る」から画像セット作成を始めてください。")

    print()
    input("   Enterで戻ります...")


def _tashizan_filter_h2_images(site_name, addition_path=None):
    """h2_images.json から選択中の足し算Prompt専用画像だけを返す。

    サイト全体の画像を無差別に入れると、複数ジャンルサイトで水道/アンテナ等が混ざるため、
    addition_file/addition_key が一致する画像だけをPromptへ注入する。
    """
    h2_path = _h2_images_json_path()
    if not h2_path or not os.path.exists(h2_path):
        return "[]"
    try:
        with open(h2_path, "r", encoding="utf-8") as f:
            h2_data = json.load(f)
        all_images = h2_data.get("images", [])
        if addition_path:
            filtered, image_mode = _select_h2_images_for_addition(all_images, site_name, addition_path)
        else:
            filtered, image_mode = [], "none"
        if not filtered:
            print(f"   ℹ️ この足し算Prompt専用のH2画像は未登録です（ジャンル混入防止のためサイト全体画像は入れません）。")
            return "[]"
        print(f"   画像プール: {len(filtered)}枚 ({site_name} / {image_mode})")
        return json.dumps(filtered, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"   ⚠️ h2_images.json読み込みエラー: {e}")
        return "[]"


# --- CSS自動生成 ---

def _tashizan_generate_css_block(palette, multi_case):
    """テーマカラーから足し算Prompt用CSSブロックを生成"""
    tc = palette["theme_color"]
    bc = palette["border_color"]
    dark = _tashizan_hex_darken(tc, 0.75)
    css = (
        f"/* 【足し算プロンプト連携用】色定義コメント */\n"
        f"/* メインボタン色: {tc} */\n"
        f"/* ボーダー色: {bc} */\n"
    )
    if multi_case:
        css += (
            f".program-selection-scroll-container {{\n"
            f"    border: 2px solid {bc};\n"
            f"}}\n"
            f".btn-primary {{\n"
            f"    background: linear-gradient(135deg, {tc} 0%, {dark} 100%);\n"
            f"}}\n"
        )
        for i, c in enumerate(palette['btn_colors'][1:], start=2):
            css += f".btn-color{i} {{ background-color: {c}; }}\n"
    css += (
        f".affiliate-button-container {{\n"
        f"    border-color: {bc} !important;\n"
        f"    background-color: #ffffff !important;\n"
        f"}}\n"
        f".affiliate-button-container a {{\n"
        f"    background-color: {tc} !important;\n"
        f"}}\n"
    )
    return css


# --- テンプレート組み立て ---

def _tashizan_build_prompt(cases, site_name, multi_case, shortcode="", addition_path=None):
    """tashizan-moto.txt をベースに足し算Promptを組み立てる。
    multi_case=False: スクロールCTA除去のシンプル版
    multi_case=True:  スクロールCTA付きのフル版（shortcode必須）"""
    additions_dir = find_additions_folder(PROMPT_BASE_DIR)
    if not additions_dir:
        print("   ⚠️ 足し算フォルダが見つかりません。")
        return ""

    moto_path = os.path.join(additions_dir, "tashizan-moto.txt")
    template = read_file(moto_path)
    if not template:
        print(f"   ⚠️ tashizan-moto.txt が読めません: {moto_path}")
        return ""

    main_case = cases[0]
    palette = _tashizan_palette_from_theme(main_case["theme_color"])

    # --- 1. h2_images.json プレースホルダー置換 ---
    images_json = _tashizan_filter_h2_images(site_name, addition_path=addition_path)
    if "{{H2見出し用_汎用画像リスト}}" in template:
        template = template.replace("{{H2見出し用_汎用画像リスト}}", images_json)
    else:
        template += f"\n\n【H2見出し用_汎用画像リスト（自動注入）】\n{images_json}"

    # --- 2. CSS色抽出ルール → 自動生成CSS で置換 ---
    css_block = _tashizan_generate_css_block(palette, multi_case)
    css_info = (
        f"CSS色情報（自動設定済み）\n"
        f"メインボタン色: {palette['theme_color']}\n"
        f"コンテナ枠線色: {palette['border_color']}\n"
        f"背景色: {palette['bg_color']}\n"
    )
    pattern = r'CSS色情報の自動抽出ルール.*?(?=生成するHTMLブロック構造)'
    template = re.sub(pattern, css_info + '\n', template, flags=re.DOTALL)

    # --- 3. 入力情報セクションのプレースホルダー置換 ---
    # af_slug がある場合はショートコード [af_url slug='xxx'] をhrefに使用
    main_af_slug = main_case.get("af_slug")
    if main_af_slug:
        af_url_display = f"[af_url slug='{main_af_slug}']"
        template = template.replace(
            "紹介先URL: （アフィリエイトリンクURL）（一般用URL: 情報取得用の公式サイトURL）",
            f"紹介先URL（ショートコード）: {af_url_display}（一般用URL: {main_case['url_gen']}）\n"
            f"※ 重要: <a>タグのhref属性には上記ショートコード {af_url_display} をそのまま使用してください。生のURLに展開しないこと。"
        )
    else:
        template = template.replace(
            "紹介先URL: （アフィリエイトリンクURL）（一般用URL: 情報取得用の公式サイトURL）",
            f"紹介先URL: {main_case['url_af']}（一般用URL: {main_case['url_gen']}）"
        )
    lp_text = main_case.get("lp_info", "") or "（LP情報未入力 - 一般URLから自動取得してください）"
    template = template.replace(
        "上記一般URL情報のコピペ：",
        f"上記一般URL情報のコピペ：\n{lp_text}"
    )
    template = template.replace(
        "スクロールCTAボックスの該当箇所CSSコード: （クロードが生成したCSSコードをそのまま貼り付け）",
        f"スクロールCTAボックスの該当箇所CSSコード:\n{css_block}"
    )

    # --- 4. モード別処理 ---
    if not multi_case:
        # === 1案件モード: スクロールCTA / ショートコード指示を除去 ===
        template = re.sub(r'\[page_scode[^\]]*\]', '', template)
        template = re.sub(r'\[挿入するショートコード\]', '', template)
        lines = template.split('\n')
        filtered_lines = []
        for line in lines:
            if any(kw in line for kw in [
                'scroll-container', 'selection-card', 'program-selection',
                'スクロールCTA', 'スクロールボックス', '1位案件ボタン色',
                'page_scode',
            ]):
                continue
            filtered_lines.append(line)
        template = '\n'.join(filtered_lines)
        # セット出力の鉄の掟 → 簡略化
        template = re.sub(
            r'【セット出力の鉄の掟】.*?(?=【まとめ下の)',
            '【CTAブロック配置ルール】: CTAブロック（<div>...</div>）を3箇所に配置してください。ショートコードは不要です。\n',
            template, flags=re.DOTALL
        )
        # ショートコード入力欄を除去
        template = template.replace(
            "挿入するショートコード: （例: [page_scode slug='fukuchan-cta-box']）\n", ""
        )
    else:
        # === 複数案件モード: ショートコードを埋め込み ===
        template = template.replace(
            "挿入するショートコード: （例: [page_scode slug='fukuchan-cta-box']）",
            f"挿入するショートコード: {shortcode}"
        )

    # --- 5. 案件データブロックを末尾に追加 ---
    case_block = "\n\n" + "=" * 50 + "\n"
    case_block += "【足し算案件データ（自動生成）】\n"
    case_block += "=" * 50 + "\n"
    has_af_shortcode = False
    for i, c in enumerate(cases):
        tag = "（メイン案件）" if i == 0 else ""
        case_block += f"\n■ 案件{i+1}{tag}: {c['name']}\n"
        c_af_slug = c.get("af_slug")
        if c_af_slug:
            case_block += f"  アフィリエイトURL（ショートコード）: [af_url slug='{c_af_slug}']\n"
            case_block += f"  ※ <a>タグの href には [af_url slug='{c_af_slug}'] をそのまま記述すること\n"
            has_af_shortcode = True
        else:
            case_block += f"  アフィリエイトURL: {c['url_af']}\n"
        case_block += f"  一般URL: {c['url_gen']}\n"
        case_block += f"  テーマカラー: {c['theme_color']}\n"
    case_block += "\n"
    if has_af_shortcode:
        case_block += "【重要】アフィリエイトリンクのショートコード使用ルール:\n"
        case_block += "  - CTAボタンの <a href=\"...\"> には [af_url slug='xxx'] をそのまま記述してください。\n"
        case_block += "  - WordPressが自動的にショートコードを実際のURLに変換します。\n"
        case_block += "  - 生のURLに展開・置換しないでください。\n\n"
    if multi_case:
        case_block += f"※ スクロールCTAボックス用ショートコード: {shortcode}\n"
        case_block += "※ メイン案件（案件1）のURLをCTAボタンおよびスクロールCTAボックスの1位に使用してください。\n"
        case_block += "※ 他の案件はスクロールCTAボックス内に順位順で表示してください。\n"
    else:
        case_block += "※ 上記案件のURLをCTAブロックの href に使用してください。\n"
        case_block += "※ スクロールCTAボックスは不要です。シンプルなCTAブロックを3箇所に配置してください。\n"

    template += case_block
    return template


def _tashizan_run_prompt_generation(site_name, cases, preselected_indices=None):
    """Prompt生成の共通ロジック。
    preselected_indices が指定されていれば案件選択をスキップする。
    戻り値: 生成成功ならTrue、キャンセル/失敗ならFalse。
    """
    if preselected_indices is not None:
        selected_indices = preselected_indices
    else:
        # 案件選択（マルチセレクト）
        case_labels = [f"{c['name']}  {c['theme_color']}" for c in cases]
        selected_indices = arrow_menu_multiselect(
            "Promptに含める案件を選択\n（Space: 選択/解除  Enter: 確定）",
            case_labels
        )
    if not selected_indices:
        print("\n   案件が選択されませんでした。")
        input("   Enterで戻る...")
        return False

    selected_cases = [cases[i] for i in selected_indices]
    multi_case = len(selected_cases) >= 2

    # ファイル名を先に決める。H2画像セットは足し算Prompt名に紐づくため、
    # Prompt生成前に保存予定ファイル名を確定しないとジャンル画像を安全に選べない。
    additions_dir = find_additions_folder(PROMPT_BASE_DIR)
    if not additions_dir:
        print("   ⚠️ 保存先フォルダが見つかりません。")
        input("   Enterで戻る...")
        return False
    site_subdir = os.path.join(additions_dir, site_name)
    os.makedirs(site_subdir, exist_ok=True)

    _bad_chars = r'[\\/:*?"<>|&]'
    default_name = re.sub(_bad_chars, '_', selected_cases[0]["name"])
    if multi_case:
        default_name = re.sub(_bad_chars, '_',
            "_".join(c["name"][:10] for c in selected_cases[:3]))
    default_filename = f"{default_name}.txt"

    print(f"\n   保存ファイル名（デフォルト: {default_filename}）")
    custom_name = input("   変更する場合は入力（空Enterでデフォルト）: ").strip()
    if custom_name:
        if not custom_name.endswith(".txt"):
            custom_name += ".txt"
        filename = re.sub(_bad_chars, '_', custom_name)
    else:
        filename = default_filename

    save_path = os.path.join(site_subdir, filename)

    # このPrompt専用の画像セットがない場合、サイト全体画像を混ぜずに事前選択させる。
    # 新規画像セット作成画面から「戻る」を選んだ場合は、サイトメニューまで戻らず
    # ここへ戻して、流用・新規作成・画像なしの選び直しができるようにする。
    while True:
        h2_data, _ = _load_h2_images_data()
        h2_images = h2_data.get("images", []) if isinstance(h2_data, dict) else []
        exact_images, _ = _select_h2_images_for_addition(h2_images, site_name, save_path)
        if exact_images:
            break
        image_idx = arrow_menu(
            "この足し算Prompt専用のH2画像セットが未登録です\n"
            "  複数ジャンルサイトで別ジャンル画像が混ざらないよう、サイト全体画像は自動注入しません。\n"
            "  既存案件と同じ画像でよい場合は1、新しいジャンル画像が必要なら2を選んでください。",
            [
                "既存画像セットをこのPromptへ流用登録する",
                "新しいH2画像セット作成へ進む（Prompt生成は後で再実行）",
                "画像なしでPromptを生成する",
            ],
            allow_back=False,
        )
        if image_idx == 0:
            source_set = _select_h2_image_source_set(site_name, target_base=filename)
            if source_set:
                _h2_image_reuse_images_to_addition(
                    site_name,
                    None,
                    filename,
                    confirm=True,
                    source_images_override=source_set["images"],
                    source_label=source_set["source_label"],
                )
            continue
        elif image_idx == 1:
            _h2_image_quick_start_wizard(site_name)
            continue
        else:
            break

    # モード表示
    mode_label = "複数案件モード（スクロールCTAボックス付き）" if multi_case else "単一案件モード（シンプルCTAブロックのみ）"
    print(f"\n   モード: {mode_label}")
    print(f"   選択案件:")
    for c in selected_cases:
        print(f"     - {c['name']}")

    # 複数案件モード: ショートコード自動生成 & WordPress登録
    shortcode = ""
    if multi_case:
        shortcode, sc_slug = _tashizan_generate_shortcode(site_name, selected_cases)
        print(f"\n   ショートコード: {shortcode}")
        _tashizan_register_shortcode_page(site_name, shortcode, selected_cases[0]["name"])

    # Prompt生成
    print("\n   Prompt生成中...")
    prompt_text = _tashizan_build_prompt(selected_cases, site_name, multi_case, shortcode, addition_path=save_path)
    if not prompt_text:
        input("   Enterで戻る...")
        return False

    # 同名ファイル確認
    if os.path.exists(save_path):
        print(f"\n   ⚠️ 既存ファイルがあります: {filename}")
        ow_opts = ["上書き保存", "別名で保存", "キャンセル"]
        ow_idx = arrow_menu(
            f"同名の足し算Promptが既にあります: {filename}\n"
            "  既存Promptを置き換えるなら上書き、過去版を残すなら別名で保存してください。",
            ow_opts,
            allow_back=True,
            back_label="キャンセル",
        )
        if ow_idx == -1 or ow_idx == 2:
            return False
        if ow_idx == 1:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            base, ext = os.path.splitext(filename)
            filename = f"{base}_{ts}{ext}"
            save_path = os.path.join(site_subdir, filename)

    with open(save_path, "w", encoding="utf-8") as f:
        f.write(prompt_text)

    print(f"\n   ✅ 保存完了: {save_path}")
    print(f"   📄 {len(prompt_text):,} 文字")
    print(f"\n   このファイルは親記事作成時の足し算ファイル選択で表示されます。")
    input("\n   Enterで続行...")
    return True


# --- メインフロー ---

def run_tashizan_generator():
    """足し算Promptジェネレーター: 案件登録 → Prompt自動生成"""
    while True:
        os.system('cls')
        print("=" * 60)
        print("  足し算Prompt・画像セット管理")
        print("=" * 60)

        # 1. サイト選択（全サイト一覧オプション付き）
        site_names = [SITES_ALL[k]["name"] for k in sorted(SITES_ALL.keys())]
        site_keys  = sorted(SITES_ALL.keys())
        top_menu = ["全サイト案件一覧を表示"] + site_names
        idx = arrow_menu("サイトを選択", top_menu, allow_back=True)
        if idx == -1:
            return

        # --- 全サイト案件一覧 ---
        if idx == 0:
            os.system('cls')
            print("=" * 60)
            print("  全サイト 登録案件一覧")
            print("=" * 60)
            total = 0
            for sk in sorted(SITES_ALL.keys()):
                sn = SITES_ALL[sk]["name"]
                sc_list = _tashizan_load_cases(sn)
                if not sc_list:
                    continue
                sp = _SITE_SLUG_MAP.get(sn, "site")
                print(f"\n  ━━ {sn} ({len(sc_list)}件) ━━")
                for i, c in enumerate(sc_list):
                    ns = _to_romaji_slug(c["name"]) or "cta"
                    sc_slug = f"{sp}-{ns}-scroll-cta-v1"
                    af_slug = c.get("af_slug") or _af_link_generate_slug(sn, c["name"])
                    print(f"   {i+1}. {c['name']}")
                    print(f"      URL: {c['url_af']}")
                    print(f"      AF SC: [af_url slug='{af_slug}']")
                    print(f"      色: {c['theme_color']}  CTA SC: [page_scode slug='{sc_slug}']")
                    total += 1
            if total == 0:
                print("\n   (どのサイトにも案件が登録されていません)")
            else:
                print(f"\n  合計: {total}件")
            print()
            input("   Enterで戻る...")
            continue

        site_name = SITES_ALL[site_keys[idx - 1]]["name"]

        # 2. 案件一覧を読み込み
        cases = _tashizan_load_cases(site_name)

        # サイト操作ループ
        while True:
            os.system('cls')
            print(f"\n  【{site_name}】 登録案件: {len(cases)}件")
            if cases:
                for i, c in enumerate(cases):
                    print(f"    {i+1}. {c['name']}  ({c['url_af'][:50]}...)  {c['theme_color']}")
            else:
                print("    (まだ案件が登録されていません)")
            print()

            # 3. 操作メニュー
            if cases:
                menu_opts = [
                    "新規案件を追加",
                    "Prompt生成",
                    "H2画像セット管理",
                    "案件情報を表示（コピー用）",
                    "アフィリエイトURL管理",
                    "案件を削除",
                    "戻る",
                ]
            else:
                menu_opts = [
                    "新規案件を追加",
                    "H2画像セット管理",
                    "戻る",
                ]

            action = arrow_menu(
                f"{site_name} - 足し算Prompt・案件・H2画像セット管理\n"
                "  新規案件追加、Prompt生成、H2画像セット管理、アフィリエイトURL変更を行います。",
                menu_opts,
                allow_back=True,
            )
            if action == -1:
                break

            action_name = menu_opts[action]

            # --- 新規案件を追加 ---
            if action_name == "新規案件を追加":
                new_case = _tashizan_add_case_wizard(site_name)
                if new_case:
                    cases.append(new_case)
                    _tashizan_save_cases(site_name, cases)
                    print(f"\n   ✅ cases.json に保存しました（合計 {len(cases)} 件）")
                    # 足し算Promptファイルも生成するか確認
                    print()
                    gen_opts = ["この案件の足し算Promptを今すぐ生成", "後で生成する"]
                    gen_idx = arrow_menu("足し算Promptファイルの生成", gen_opts, allow_back=False)
                    if gen_idx == 0:
                        new_idx = len(cases) - 1  # 今追加した案件のインデックス
                        _tashizan_run_prompt_generation(site_name, cases, preselected_indices=[new_idx])
                continue

            # --- H2画像セット管理 ---
            if action_name == "H2画像セット管理":
                _h2_image_quick_start_wizard(site_name)
                continue

            # --- 案件情報を表示（コピー用） ---
            if action_name == "案件情報を表示（コピー用）":
                os.system('cls')
                print("=" * 60)
                print(f"  【{site_name}】 登録案件一覧（コピー用）")
                print("=" * 60)
                site_prefix = _SITE_SLUG_MAP.get(site_name, "site")

                # 各案件の情報を表示
                af_slugs_map = {}  # name → af_slug のマッピング
                for i, c in enumerate(cases):
                    tag = " (メイン)" if i == 0 else ""
                    name_slug = _to_romaji_slug(c["name"]) or "cta"
                    af_slug = c.get("af_slug") or _af_link_generate_slug(site_name, c["name"])
                    af_slugs_map[c["name"]] = af_slug
                    print(f"\n   {'='*50}")
                    print(f"   案件{i+1}{tag}: {c['name']}")
                    print(f"   {'='*50}")
                    print(f"   アフィリエイトURL: {c['url_af']}")
                    print(f"   一般URL:           {c['url_gen']}")
                    print(f"   テーマカラー:      {c['theme_color']}")
                    print(f"   登録日:            {c.get('created', '不明')}")
                    print(f"   ---")
                    print(f"   AFリンクSC:        [af_url slug='{af_slug}']")
                    print(f"     -> 記事内: <a href=\"[af_url slug='{af_slug}']\">...")

                # スクロールCTA情報（2件以上のときのみ意味がある）
                if len(cases) >= 2:
                    print(f"\n\n   {'*'*50}")
                    print(f"   スクロールCTAボックス構成（複数案件モード時）")
                    print(f"   {'*'*50}")
                    main_slug = _to_romaji_slug(cases[0]["name"]) or "cta"
                    scroll_slug = f"{site_prefix}-{main_slug}-scroll-cta-v1"
                    print(f"\n   SC: [page_scode slug='{scroll_slug}']")
                    print(f"   ボックス内の案件:")
                    for i, c in enumerate(cases):
                        rank = f"  {i+1}位"
                        af_s = af_slugs_map.get(c["name"], "?")
                        print(f"     {rank}: {c['name']}")
                        print(f"           AFリンクSC: [af_url slug='{af_s}']")
                        print(f"           URL: {c['url_af']}")
                else:
                    print(f"\n\n   ※ 案件1件のため、スクロールCTAボックスは不要です。")
                    print(f"     CTAブロック（ボタン3箇所）のみが記事に配置されます。")

                # WordPress側の登録状況
                print(f"\n\n   {'-'*50}")
                print(f"   WordPress登録状況:")
                wp_links = _af_link_list(site_name)
                if wp_links is not None:
                    for c in cases:
                        af_s = af_slugs_map.get(c["name"], "?")
                        if af_s in wp_links:
                            print(f"     [af_url slug='{af_s}'] -> {wp_links[af_s][:60]}")
                        else:
                            print(f"     [af_url slug='{af_s}'] -> !! 未登録 !! (一括登録が必要)")
                else:
                    print(f"     (WordPress接続に失敗。環境未セットアップの可能性あり)")
                print(f"   {'-'*50}")
                print(f"   cases.json: {_tashizan_cases_path(site_name)}")
                print(f"   {'-'*50}")
                input("\n   Enterで戻る...")
                continue

            # --- アフィリエイトURL管理 ---
            if action_name == "アフィリエイトURL管理":
                while True:
                    os.system('cls')
                    print("=" * 60)
                    print(f"  【{site_name}】 アフィリエイトURL管理")
                    print("=" * 60)

                    # 案件一覧とaf_slug表示
                    for i, c in enumerate(cases):
                        af_slug = c.get("af_slug") or _af_link_generate_slug(site_name, c["name"])
                        print(f"\n   {i+1}. {c['name']}")
                        print(f"      現在のURL: {c['url_af']}")
                        print(f"      SC slug:   [af_url slug='{af_slug}']")

                    # WordPress側の登録状況を取得
                    print(f"\n   " + "-" * 50)
                    print(f"   WordPress登録状況を確認中...")
                    wp_links = _af_link_list(site_name)
                    if wp_links is not None:
                        site_prefix = _SITE_SLUG_MAP.get(site_name, "site")
                        my_links = {k: v for k, v in wp_links.items() if k.startswith(site_prefix)}
                        if my_links:
                            print(f"   WordPress上の登録リンク ({len(my_links)}件):")
                            for slug, url in my_links.items():
                                print(f"      {slug} → {url[:60]}...")
                        else:
                            print(f"   WordPress上にこのサイトのリンクはまだありません。")
                    print()

                    af_opts = [
                        "通常はこちら: 案件URLとWordPressリンクを両方変更",
                        "テーマカラーだけ変更（次回Prompt生成から反映）",
                        "登録用: 未登録の案件URLをWordPressへ一括登録",
                        "応急用: WordPress上のリンクURLだけ変更",
                        "戻る"
                    ]
                    af_idx = arrow_menu(
                        "アフィリエイトURL管理の操作を選択\n\n"
                        "    ■ 1. 通常はこちら\n"
                        "       cases.json の案件URLと、WordPress上の [af_url] リンク先を両方更新します。\n\n"
                        "    ■ 2. テーマカラーだけ変更\n"
                        "       既存記事は変わりません。次回の足し算Prompt生成から反映されます。\n\n"
                        "    ■ 3. 登録用\n"
                        "       cases.json にある案件URLをWordPressへまとめて登録します。未登録補完用です。\n\n"
                        "    ■ 4. 応急用\n"
                        "       WordPress上の [af_url] リンク先だけを直接変更します。slug単位の緊急修正向けです。",
                        af_opts,
                        allow_back=True,
                    )
                    if af_idx == -1 or af_opts[af_idx] == "戻る":
                        break

                    # --- 案件のアフィリエイトURLを変更 ---
                    if af_opts[af_idx].startswith("通常はこちら"):
                        c_labels = [f"{c['name']}  ({c['url_af'][:40]}...)" for c in cases]
                        c_idx = arrow_menu(
                            "URLを変更する案件を選択\n"
                            "  cases.json と WordPress の [af_url] を両方更新します。",
                            c_labels,
                            allow_back=True,
                        )
                        if c_idx == -1:
                            continue
                        target = cases[c_idx]
                        print(f"\n   案件: {target['name']}")
                        print(f"   現在のURL: {target['url_af']}")
                        new_url = input("   新しいURL: ").strip()
                        if not new_url:
                            print("   キャンセルしました。")
                            input("   Enter...")
                            continue
                        old_url = target['url_af']
                        target['url_af'] = new_url
                        # af_slug がなければ自動生成して追加
                        if not target.get("af_slug"):
                            target["af_slug"] = _af_link_generate_slug(site_name, target["name"])
                        _tashizan_save_cases(site_name, cases)
                        print(f"\n   ✅ cases.json を更新しました。")
                        print(f"      旧: {old_url}")
                        print(f"      新: {new_url}")

                        # WordPress側も更新
                        print(f"\n   📤 WordPress側のリンクも更新中...")
                        _af_link_register(site_name, target["af_slug"], new_url)
                        input("\n   Enterで続行...")

                    # --- 案件のテーマカラーを変更 ---
                    elif af_opts[af_idx].startswith("テーマカラーだけ変更"):
                        c_labels = [f"{c['name']}  ({c['theme_color']})" for c in cases]
                        c_idx = arrow_menu(
                            "テーマカラーを変更する案件を選択\n"
                            "  次回の足し算Prompt生成から反映されます。既存記事の色は変わりません。",
                            c_labels,
                            allow_back=True,
                        )
                        if c_idx == -1:
                            continue
                        target = cases[c_idx]
                        print(f"\n   案件: {target['name']}")
                        print(f"   現在のテーマカラー: {target['theme_color']}")
                        new_color = input("   新しいテーマカラー #RRGGBB: ").strip()
                        if not new_color:
                            print("   キャンセルしました。")
                            input("   Enter...")
                            continue
                        if not re.match(r'^#[0-9A-Fa-f]{6}$', new_color):
                            print("   ⚠️ #RRGGBB 形式で入力してください。")
                            input("   Enter...")
                            continue
                        old_color = target['theme_color']
                        target['theme_color'] = new_color
                        _tashizan_save_cases(site_name, cases)
                        print(f"\n   ✅ テーマカラーを変更しました。")
                        print(f"      旧: {old_color}")
                        print(f"      新: {new_color}")
                        print(f"\n   ※ 次回のPrompt生成から新しい色が適用されます。")
                        print(f"     既存の記事のボタン色は変わりません。")
                        input("\n   Enterで続行...")

                    # --- WordPressへ一括登録 ---
                    elif af_opts[af_idx].startswith("登録用"):
                        if not _af_link_ensure_setup(site_name):
                            print("   ❌ WordPress環境セットアップに失敗しました。")
                            input("   Enter...")
                            continue
                        print(f"\n   全{len(cases)}件のアフィリエイトリンクをWordPressに登録します...")
                        for c in cases:
                            af_slug = c.get("af_slug") or _af_link_generate_slug(site_name, c["name"])
                            if not c.get("af_slug"):
                                c["af_slug"] = af_slug
                            _af_link_register(site_name, af_slug, c["url_af"])
                        _tashizan_save_cases(site_name, cases)
                        print(f"\n   ✅ 一括登録完了。")
                        input("   Enterで続行...")

                    # --- WordPress上のリンクURL変更 ---
                    elif af_opts[af_idx].startswith("応急用"):
                        if wp_links is None:
                            print("   ⚠️ WordPress上のリンク情報を取得できませんでした。")
                            input("   Enter...")
                            continue
                        site_prefix = _SITE_SLUG_MAP.get(site_name, "site")
                        my_links = {k: v for k, v in wp_links.items() if k.startswith(site_prefix)}
                        if not my_links:
                            print("   ⚠️ このサイトのリンクはWordPressに登録されていません。")
                            input("   Enter...")
                            continue
                        slug_list = list(my_links.keys())
                        wp_labels = [f"{s} → {my_links[s][:50]}..." for s in slug_list]
                        wp_idx = arrow_menu(
                            "WordPress上で直接変更する [af_url] リンクを選択\n"
                            "  cases.json 側も同じ slug が見つかれば同期します。",
                            wp_labels,
                            allow_back=True,
                        )
                        if wp_idx == -1:
                            continue
                        sel_slug = slug_list[wp_idx]
                        print(f"\n   slug: {sel_slug}")
                        print(f"   現在のURL: {my_links[sel_slug]}")
                        new_url = input("   新しいURL: ").strip()
                        if not new_url:
                            print("   キャンセルしました。")
                            input("   Enter...")
                            continue
                        _af_link_register(site_name, sel_slug, new_url)
                        # cases.json側も同期
                        for c in cases:
                            if c.get("af_slug") == sel_slug:
                                c["url_af"] = new_url
                                _tashizan_save_cases(site_name, cases)
                                print(f"   ✅ cases.json も同期しました。")
                                break
                        input("\n   Enterで続行...")
                continue

            # --- 案件を削除 ---
            if action_name == "案件を削除":
                del_labels = [f"{c['name']}  ({c['url_af'][:40]}...)" for c in cases]
                del_idx = arrow_menu("削除する案件を選択", del_labels, allow_back=True)
                if del_idx != -1:
                    target = cases[del_idx]
                    af_slug = target.get("af_slug") or _af_link_generate_slug(site_name, target["name"])
                    confirm_idx = arrow_menu(
                        "この案件を削除しますか？\n\n"
                        f"  案件名: {target['name']}\n"
                        f"  cases.json: 削除します\n"
                        f"  WordPress [af_url slug='{af_slug}']: 次画面で削除するか選べます\n\n"
                        "  ※ 既に保存済みの足し算Prompt txt や記事本文は自動削除しません。",
                        ["削除する", "やめる"],
                        allow_back=False,
                    )
                    if confirm_idx != 0:
                        continue
                    removed = cases.pop(del_idx)
                    _tashizan_save_cases(site_name, cases)
                    print(f"\n   🗑 cases.json から「{removed['name']}」を削除しました。")
                    removed_h2 = _remove_h2_image_mappings_for_addition(site_name, removed.get("name"))
                    if removed_h2:
                        print(f"   🗑 H2画像セットの紐づけも解除しました（{removed_h2}件）。")
                    wp_delete_idx = arrow_menu(
                        "WordPress側のアフィリエイトリンク登録も削除しますか？\n"
                        f"  対象: [af_url slug='{af_slug}']\n"
                        "  テスト登録をやり直す場合は削除してください。",
                        ["WordPress側も削除する", "cases.jsonだけ削除済みで終了"],
                        allow_back=False,
                    )
                    if wp_delete_idx == 0:
                        _af_link_delete(site_name, af_slug)
                    input("   Enterで続行...")
                continue

            # --- 戻る ---
            if action_name == "戻る":
                break

            # --- Prompt生成 ---
            if action_name == "Prompt生成":
                _tashizan_run_prompt_generation(site_name, cases)
                continue


def run_affiliate_url_manager_entry():
    """アフィリエイトURL管理だけを直接開く入口。

    実体は足し算Prompt作成で登録した案件データ（cases.json）と
    WordPress上の [af_url] 登録URLを更新する。
    """
    while True:
        site_names = [SITES_ALL[k]["name"] for k in sorted(SITES_ALL.keys())]
        site_keys = sorted(SITES_ALL.keys())
        idx = arrow_menu(
            "アフィリエイトURLを管理するサイトを選択\n"
            "  記事内の [af_url slug='...'] が参照するURLを確認・変更します。",
            site_names + ["戻る"],
            allow_back=True,
        )
        if idx == -1 or idx == len(site_names):
            return

        site_name = SITES_ALL[site_keys[idx]]["name"]
        cases = _tashizan_load_cases(site_name)
        if not cases:
            print(f"\n   ⚠️ {site_name} には登録案件がありません。")
            print("   先に足し算Prompt作成で案件を登録してください。")
            input("\n   Enterで戻る...")
            continue

        while True:
            os.system('cls')
            print("=" * 60)
            print(f"  【{site_name}】 アフィリエイトURL管理")
            print("=" * 60)
            print("  記事内の href=\"[af_url slug='...']\" は、ここで登録したURLへ展開されます。")
            print()

            for i, c in enumerate(cases):
                af_slug = c.get("af_slug") or _af_link_generate_slug(site_name, c["name"])
                print(f"\n   {i+1}. {c['name']}")
                print(f"      cases.json URL: {c['url_af']}")
                print(f"      SC slug:        [af_url slug='{af_slug}']")

            print(f"\n   " + "-" * 50)
            print(f"   WordPress登録状況を確認中...")
            wp_links = _af_link_list(site_name)
            if wp_links is not None:
                site_prefix = _SITE_SLUG_MAP.get(site_name, "site")
                my_links = {k: v for k, v in wp_links.items() if k.startswith(site_prefix)}
                if my_links:
                    print(f"   WordPress上の登録リンク ({len(my_links)}件):")
                    for slug, url in my_links.items():
                        print(f"      {slug} → {url[:80]}...")
                else:
                    print(f"   WordPress上にこのサイトのリンクはまだありません。")
            print()

            af_opts = [
                "通常はこちら: 案件URLとWordPressリンクを両方変更",
                "応急用: WordPress上のリンクURLだけ変更",
                "登録用: 未登録の案件URLをWordPressへ一括登録",
                "戻る",
            ]
            af_idx = arrow_menu(
                "アフィリエイトURL管理の操作を選択\n\n"
                "    ■ 1. 通常はこちら\n"
                "       cases.json の案件URLと、WordPress上の [af_url] リンク先を両方更新します。\n"
                "       既存記事のボタンURLを正しいアフィリエイトURLへ変えたい時はこれです。\n\n"
                "    ■ 2. 応急用\n"
                "       WordPress上の [af_url] リンク先だけを直接変更します。\n"
                "       cases.json は原則同期しますが、slug単位で緊急修正したい時向けです。\n\n"
                "    ■ 3. 登録用\n"
                "       cases.json にある案件URLをWordPressへまとめて登録します。\n"
                "       URL変更ではなく、未登録リンクを作る・補完するための操作です。",
                af_opts,
                allow_back=True,
            )
            if af_idx == -1 or af_opts[af_idx] == "戻る":
                break

            if af_opts[af_idx].startswith("通常はこちら"):
                c_labels = [f"{c['name']}  ({c['url_af'][:50]}...)" for c in cases]
                c_idx = arrow_menu(
                    "URLを変更する案件を選択\n"
                    "  cases.json と WordPress の [af_url] を両方更新します。",
                    c_labels,
                    allow_back=True,
                )
                if c_idx == -1:
                    continue
                target = cases[c_idx]
                if not target.get("af_slug"):
                    target["af_slug"] = _af_link_generate_slug(site_name, target["name"])
                print(f"\n   案件: {target['name']}")
                print(f"   SC slug: [af_url slug='{target['af_slug']}']")
                print(f"   現在のURL: {target['url_af']}")
                new_url = input("   新しいアフィリエイトURL: ").strip()
                if not new_url:
                    print("   キャンセルしました。")
                    input("   Enter...")
                    continue
                old_url = target["url_af"]
                target["url_af"] = new_url
                _tashizan_save_cases(site_name, cases)
                print(f"\n   ✅ cases.json を更新しました。")
                print(f"      旧: {old_url}")
                print(f"      新: {new_url}")
                print(f"\n   📤 WordPress側のリンクも更新中...")
                _af_link_register(site_name, target["af_slug"], new_url)
                input("\n   Enterで続行...")
                continue

            if af_opts[af_idx].startswith("応急用"):
                if wp_links is None:
                    print("   ⚠️ WordPress上のリンク情報を取得できませんでした。")
                    input("   Enter...")
                    continue
                site_prefix = _SITE_SLUG_MAP.get(site_name, "site")
                my_links = {k: v for k, v in wp_links.items() if k.startswith(site_prefix)}
                if not my_links:
                    print("   ⚠️ このサイトのリンクはWordPressに登録されていません。")
                    input("   Enter...")
                    continue
                slug_list = list(my_links.keys())
                wp_labels = [f"{s} → {my_links[s][:70]}..." for s in slug_list]
                wp_idx = arrow_menu(
                    "WordPress上で直接変更する [af_url] リンクを選択\n"
                    "  cases.json 側も同じ slug が見つかれば同期します。",
                    wp_labels,
                    allow_back=True,
                )
                if wp_idx == -1:
                    continue
                sel_slug = slug_list[wp_idx]
                print(f"\n   slug: {sel_slug}")
                print(f"   現在のURL: {my_links[sel_slug]}")
                new_url = input("   新しいURL: ").strip()
                if not new_url:
                    print("   キャンセルしました。")
                    input("   Enter...")
                    continue
                _af_link_register(site_name, sel_slug, new_url)
                for c in cases:
                    if c.get("af_slug") == sel_slug:
                        c["url_af"] = new_url
                        _tashizan_save_cases(site_name, cases)
                        print(f"   ✅ cases.json も同期しました。")
                        break
                input("\n   Enterで続行...")
                continue

            if af_opts[af_idx].startswith("登録用"):
                if not _af_link_ensure_setup(site_name):
                    print("   ❌ WordPress環境セットアップに失敗しました。")
                    input("   Enter...")
                    continue
                print(f"\n   全{len(cases)}件のアフィリエイトリンクをWordPressに登録します...")
                for c in cases:
                    af_slug = c.get("af_slug") or _af_link_generate_slug(site_name, c["name"])
                    if not c.get("af_slug"):
                        c["af_slug"] = af_slug
                    _af_link_register(site_name, af_slug, c["url_af"])
                _tashizan_save_cases(site_name, cases)
                print(f"\n   ✅ 一括登録完了。")
                input("   Enterで続行...")


# ============================================================
# 案件名抽出＆関連語付与 (Mode 7)
# ============================================================
def _anken_preprocess_asp_text(raw_text):
    """ASPテキストから長い説明文を除去し、商品名が含まれる行だけを残す前処理。
    Gemini APIに送るテキスト量を削減し、高速化する。"""
    filtered = []
    for line in raw_text.split('\n'):
        line = line.strip()
        # 空行はそのまま（区切りとして有用）
        if not line:
            filtered.append("")
            continue
        # 長い行は説明文 → 除外（商品名は通常40文字以内）
        if len(line) > 80:
            continue
        # 「バナーを取得」「詳細を見る」等のUI要素を除外
        if line in ("バナーを取得", "詳細を見る", "売り切れ"):
            continue
        # 純粋な数値行を除外（価格、報酬額など）
        cleaned = line.replace(',', '').replace('.', '').replace('¥', '').replace('～', '').replace('%', '')
        if cleaned.isdigit():
            continue
        filtered.append(line)
    return "\n".join(filtered)


def _anken_extract_names_via_gemini(raw_text, api_key):
    """Gemini APIでASPテキストから案件名/商品名/ブランド名を抽出する。"""
    # 前処理: 長い説明文を除去してAPI送信量を削減
    preprocessed = _anken_preprocess_asp_text(raw_text)
    char_count = len(preprocessed)
    print(f"   （前処理後: {char_count:,}文字）")

    prompt = """以下はアフィリエイトASPサイトからコピーしたテキストです。
このテキストから「商品名」「サービス名」「ブランド名」だけを抽出してください。

ルール:
1. 各エントリから正式な商品名/サービス名/ブランド名のみを1行1つで出力
2. カテゴリ名、タグ、価格、レビュー数、説明文、報酬額、EPC等の数値データは除外
3. プログラムIDや管理番号（例: 21-0727, s00000012789015）は除外
4. 【】や（）内にブランド名がある場合はそのブランド名だけを抽出（例: 【トラキャリ】→ トラキャリ）
5. 「〜プロモーション」「〜促進」「申込促進プロモーション」等の広告用語は除外
6. [ブランド名]商品名 の形式の場合は商品名全体を抽出（例: [BIHAKUEN]ビハクエン ハイドロキノンソープ → ビハクエン ハイドロキノンソープ）
7. 重複は排除
8. 出力は商品名のリストのみ。番号や説明は不要

テキスト:
---
""" + preprocessed + """
---

抽出結果（1行1商品名）:"""

    # スレッドでAPI呼び出し（タイムアウト付き）
    import threading
    _result_box = [None]  # [response] or remains [None]
    _error_box = [None]

    def _call_gemini():
        try:
            _load_genai()
            client = genai.Client(api_key=api_key)
            chat = client.chats.create(model=MODEL_CHILD, config=GEN_CONFIG)
            _result_box[0] = _send_message_with_retry(chat, prompt, "案件名抽出")
        except Exception as ex:
            _error_box[0] = ex

    t = threading.Thread(target=_call_gemini, daemon=True)
    t.start()
    t.join(timeout=90)  # 90秒待つ

    if t.is_alive():
        print(f"\n   ❌ Gemini API タイムアウト（90秒）。")
        print("   APIキーを変えるか、テキストを短くして再試行してください。")
        return []
    if _error_box[0] is not None:
        print(f"\n   ❌ Gemini APIエラー: {_error_box[0]}")
        return []
    if _result_box[0] is None:
        print(f"\n   ❌ Gemini APIから応答がありませんでした。")
        return []

    try:
        response = _result_box[0]
        # セーフティブロックの検出
        if hasattr(response, 'candidates') and response.candidates:
            cand = response.candidates[0]
            if hasattr(cand, 'finish_reason') and cand.finish_reason and 'SAFETY' in str(cand.finish_reason):
                print(f"\n   ⚠️ Geminiのセーフティフィルターでブロックされました。")
                print("   テキスト内の表現が原因の可能性があります。")
                print("   別のAPIキーか、テキストを分割して再試行してください。")
                return []
        result_text = response.text.strip()
    except Exception as e:
        print(f"\n   ❌ レスポンス読み取りエラー: {e}")
        print(f"   （詳細: {type(e).__name__}: {e}）")
        # レスポンスオブジェクトの情報をダンプ
        resp = _result_box[0]
        if hasattr(resp, 'candidates'):
            for i, c in enumerate(resp.candidates):
                print(f"   candidate[{i}]: finish_reason={getattr(c, 'finish_reason', '?')}")
        return []

    # 後処理: 番号や記号を除去、空行・重複を排除
    names = []
    seen = set()
    for line in result_text.split('\n'):
        line = re.sub(r'^[\d]+[.．)）]\s*', '', line)  # 先頭番号除去
        line = re.sub(r'^[-・•]\s*', '', line)           # 先頭記号除去
        line = line.strip()
        if not line or len(line) > 60:
            continue
        if line not in seen:
            seen.add(line)
            names.append(line)
    return names


def _anken_copy_to_clipboard(text):
    """Windowsクリップボードにテキストをコピーする。"""
    try:
        process = subprocess.Popen(['clip.exe'], stdin=subprocess.PIPE, shell=False)
        process.communicate(text.encode('utf-16le'))
        return True
    except Exception as e:
        print(f"   ⚠️ クリップボードコピー失敗: {e}")
        return False


def _anken_parse_planner_csv(filepath):
    """キーワードプランナーCSV（UTF-16 TSV）を読み込み、(Keyword, Volume, Competition) のリストを返す。
    ヘッダー行やサマリー行はスキップする。"""
    # エンコーディングを自動判定
    with open(filepath, 'rb') as f:
        raw = f.read(4)
    enc = 'utf-16' if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8-sig'

    with open(filepath, 'r', encoding=enc) as f:
        lines = f.readlines()

    # ヘッダー行を探す（"Keyword" で始まる行）
    header_idx = -1
    for i, line in enumerate(lines):
        cols = line.strip().split('\t')
        if cols[0].strip().lower() == 'keyword':
            header_idx = i
            break

    if header_idx == -1:
        # ヘッダーがない場合（既に整形済み）→ 3カラムTSVとして読む
        results = []
        for line in lines:
            cols = line.strip().split('\t')
            if len(cols) >= 1 and cols[0].strip():
                kw = cols[0].strip()
                vol = cols[1].strip() if len(cols) > 1 else ''
                comp = cols[2].strip() if len(cols) > 2 else ''
                results.append((kw, vol, comp))
        return results

    # ヘッダーからカラムインデックスを特定
    header_cols = [c.strip() for c in lines[header_idx].strip().split('\t')]
    kw_idx = 0  # Keyword は常に先頭
    vol_idx = next((i for i, c in enumerate(header_cols) if 'avg' in c.lower() and 'search' in c.lower()), 3)
    comp_idx = next((i for i, c in enumerate(header_cols) if c.lower() == 'competition'), 6)

    results = []
    for line in lines[header_idx + 1:]:
        cols = line.strip().split('\t')
        if len(cols) <= kw_idx:
            continue
        kw = cols[kw_idx].strip()
        if not kw:
            continue  # サマリー行（キーワード空欄）をスキップ
        vol_raw = cols[vol_idx].strip() if len(cols) > vol_idx else ''
        comp = cols[comp_idx].strip() if len(cols) > comp_idx else ''
        # ボリュームを整数に変換（"50.0" → "50"）
        try:
            vol = str(int(float(vol_raw))) if vol_raw else ''
        except ValueError:
            vol = vol_raw
        results.append((kw, vol, comp))
    return results


def _anken_find_chrome():
    """Chromeの実行パスを探す。見つからなければNoneを返す。"""
    candidates = [
        os.path.expandvars(r'%ProgramFiles%\Google\Chrome\Application\chrome.exe'),
        os.path.expandvars(r'%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe'),
        os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe'),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _anken_get_gspread_client():
    """gspread認証クライアントを取得する。rank_checkerの既存認証情報を流用する。"""
    try:
        import gspread
    except ImportError:
        print("   ❌ gspread がインストールされていません。")
        print("   pip install gspread でインストールしてください。")
        return None

    # rank_checkerの既存client_secretを流用（プロジェクト: balmy-vehicle-492405-d9）
    rc_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "..", "kw_app_dev", "kw_classifier")
    rc_dir = os.path.normpath(rc_dir)
    creds_path = os.path.join(rc_dir,
        "client_secret_332765888009-7emun0d2f7dieg01df0u4b3vtadcp891.apps.googleusercontent.com.json")

    # トークンはauto_post側に別途保存（rank_checkerのトークンに影響しない）
    script_dir = os.path.dirname(os.path.abspath(__file__))
    authorized_path = os.path.join(script_dir, "_anken_gspread_token.json")

    if not os.path.exists(creds_path):
        print(f"\n   ❌ rank_checkerのclient_secretが見つかりません:")
        print(f"      {creds_path}")
        print("   rank_checker のフォルダを確認してください。")
        return None

    try:
        gc = gspread.oauth(
            credentials_filename=creds_path,
            authorized_user_filename=authorized_path,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive.file",
            ],
        )
        return gc
    except Exception as e:
        print(f"\n   ❌ Google認証エラー: {e}")
        print("   もう一度お試しください。")
        return None


def _anken_save_to_spreadsheet(rows, title_prefix="商標KW"):
    """選択したキーワードをGoogleスプレッドシートに保存する。
    rows: [(keyword, volume, competition), ...]
    """
    gc = _anken_get_gspread_client()
    if gc is None:
        input("   Enterで戻ります...")
        return

    # ── 保存先選択 ──
    save_options = [
        "新しいスプレッドシートを作成",
        "既存のスプレッドシートに追加（URLを入力）",
        "キャンセル",
    ]
    save_choice = arrow_menu("スプレッドシート保存先", save_options, allow_back=False)

    if save_choice == 2:
        return

    today = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    default_name = datetime.datetime.now().strftime("%Y%m%d_%H%M")

    # ── シート名（タブ名）を入力 ──
    print(f"\n  シート名を入力してください（空Enterで「{default_name}」）:")
    sheet_name_input = input("  シート名: ").strip()
    if not sheet_name_input:
        sheet_name_input = default_name

    if save_choice == 0:
        # 新規作成
        sheet_title = sheet_name_input
        try:
            print(f"\n   🔄 スプレッドシート「{sheet_title}」を作成中...")
            sh = gc.create(sheet_title)
            ws = sh.sheet1
            ws.update_title(sheet_name_input)
            print(f"   ✅ 作成完了")
        except Exception as e:
            print(f"   ❌ 作成エラー: {e}")
            input("   Enterで戻ります...")
            return
    else:
        # 既存に追加
        print("\n  スプレッドシートのURLを入力してください:")
        url = input("  URL: ").strip()
        if not url:
            return
        try:
            import gspread
            sh = gc.open_by_url(url)
            ws = sh.add_worksheet(title=sheet_name_input, rows=len(rows) + 10, cols=10)
            print(f"   ✅ シート「{sheet_name_input}」を追加しました。")
        except Exception as e:
            print(f"   ❌ スプレッドシートを開けませんでした: {e}")
            input("   Enterで戻ります...")
            return

    # ── データ書き込み ──
    try:
        print("   🔄 データ書き込み中...")
        # ヘッダー
        header = ["キーワード", "ボリューム", "競合度", "KW追加日"]
        all_data = [header]
        for kw, vol, comp in rows:
            all_data.append([kw, vol, comp, today])

        ws.update(range_name="A1", values=all_data)

        # ヘッダー行を太字に
        ws.format("A1:D1", {"textFormat": {"bold": True}})

        url = sh.url
        print(f"\n   ✅ {len(rows)}件のキーワードを保存しました。")
        print(f"   📄 {url}")

        # URLをクリップボードにコピー
        _anken_copy_to_clipboard(url)
        print("   （URLをクリップボードにコピーしました）")

        # ブラウザで開く
        open_options = ["ブラウザで開く", "戻る"]
        if arrow_menu("スプレッドシートを確認しますか？", open_options, allow_back=False) == 0:
            webbrowser.open(url)

    except Exception as e:
        print(f"   ❌ 書き込みエラー: {e}")

    input("   Enterで戻ります...")


def _anken_run_csv_formatter():
    """キーワードプランナーCSV整形 → Google検索オープンのサブフロー。"""
    os.system('cls')
    print("=" * 60)
    print("  プランナーCSV整形＆SERPs確認")
    print("=" * 60)

    # ── ファイルパス入力 ──
    print("\n  キーワードプランナーのCSVファイルパスを入力してください。")
    print("  （ファイルをドラッグ＆ドロップでもOK）")
    filepath = input("  パス: ").strip().strip('"').strip("'")
    if not filepath:
        print("   ⚠️ パスが入力されませんでした。")
        input("   Enterで戻ります...")
        return
    if not os.path.exists(filepath):
        print(f"   ❌ ファイルが見つかりません: {filepath}")
        input("   Enterで戻ります...")
        return

    # ── CSV解析 ──
    print("\n   🔄 CSV解析中...")
    try:
        rows = _anken_parse_planner_csv(filepath)
    except Exception as e:
        print(f"   ❌ CSV読み込みエラー: {e}")
        input("   Enterで戻ります...")
        return

    if not rows:
        print("   ❌ データが見つかりませんでした。")
        input("   Enterで戻ります...")
        return

    # ボリューム降順ソート（空文字は最後）
    def _vol_sort_key(row):
        try:
            return -int(row[1]) if row[1] else 0
        except ValueError:
            return 0
    rows.sort(key=_vol_sort_key)

    # ── 結果表示 ──
    os.system('cls')
    print("=" * 60)
    print(f"  CSV整形結果（{len(rows)}キーワード）")
    print("=" * 60)
    print(f"  {'Keyword':<40} {'Vol':>8}  {'Competition'}")
    print("  " + "-" * 58)
    display_count = min(40, len(rows))
    for kw, vol, comp in rows[:display_count]:
        kw_disp = kw[:38] + '..' if len(kw) > 40 else kw
        print(f"  {kw_disp:<40} {vol:>8}  {comp}")
    if len(rows) > display_count:
        print(f"  ... 他 {len(rows) - display_count}件")

    # ── CSV保存（カンマ区切り）──
    import csv as _csv
    print()
    out_dir = os.path.dirname(filepath)
    base_name = os.path.splitext(os.path.basename(filepath))[0]
    out_filename = f"{base_name}_整形済.csv"
    out_path = os.path.join(out_dir, out_filename)

    try:
        with open(out_path, 'w', encoding='utf-8-sig', newline='') as f:
            writer = _csv.writer(f)
            writer.writerow(["Keyword", "Avg. monthly searches", "Competition"])
            for kw, vol, comp in rows:
                writer.writerow([kw, vol, comp])
        print(f"   ✅ 整形済CSV保存: {out_path}")
    except Exception as e:
        print(f"   ❌ 保存エラー: {e}")

    # ── Google検索オープン（オプション）──
    next_options = [
        "選択したキーワードでGoogle検索を開く（シークレット）",
        "選択したキーワードでGoogle検索を開く（通常ウィンドウ）",
        "Googleスプレッドシートにコピー用データをクリップボードへ",
        "スプレッドシートに直接保存（Google Sheets API）",
        "戻る",
    ]
    next_choice = arrow_menu("次のアクション", next_options, allow_back=False)

    if next_choice == 4:
        return

    if next_choice == 3:
        # スプレッドシートに直接保存
        _anken_save_to_spreadsheet(rows)
        return

    if next_choice == 2:
        # スプレッドシート用：タブ区切りでクリップボードにコピー
        tsv_lines = ["Keyword\tAvg. monthly searches\tCompetition"]
        for kw, vol, comp in rows:
            tsv_lines.append(f"{kw}\t{vol}\t{comp}")
        tsv_text = "\n".join(tsv_lines)
        if _anken_copy_to_clipboard(tsv_text):
            print(f"\n   ✅ {len(rows)}行をクリップボードにコピーしました。")
            print("   Googleスプレッドシートで Ctrl+V で貼り付けてください。")
            print("   （3列に自動分割されます）")
        input("   Enterで戻ります...")
        return

    use_incognito = (next_choice == 0)

    # キーワード選択（multiselect）— ボリュームありのものだけデフォルトチェック
    display_labels = []
    default_checks = []
    for kw, vol, comp in rows:
        vol_str = f" [{vol}]" if vol else " [-]"
        comp_str = f" ({comp})" if comp else ""
        display_labels.append(f"{kw}{vol_str}{comp_str}")
        default_checks.append(bool(vol))  # ボリュームがあるものだけデフォルトON

    selected = arrow_menu_multiselect(
        "Google検索で開くキーワードを選択\n（Space: 切替 → Enter: 検索開始）",
        display_labels,
        default_checked=default_checks
    )

    if not selected:
        print("\n   ⚠️ キーワードが選択されませんでした。")
        input("   Enterで戻ります...")
        return

    selected_keywords = [rows[i][0] for i in selected]

    # Chrome検出
    chrome_path = _anken_find_chrome()

    print(f"\n   🔍 {len(selected_keywords)}件のキーワードでGoogle検索を開きます...")
    if use_incognito and chrome_path:
        print("   （シークレットモード）")
    elif use_incognito and not chrome_path:
        print("   ⚠️ Chromeが見つからないため通常ブラウザで開きます。")
        use_incognito = False

    for kw in selected_keywords:
        url = "https://www.google.com/search?" + urllib.parse.urlencode({"q": kw})
        if use_incognito and chrome_path:
            subprocess.Popen([chrome_path, "--incognito", url])
        else:
            webbrowser.open(url)
        time.sleep(0.3)  # タブが一気に開きすぎないよう少し待つ

    print(f"\n   ✅ {len(selected_keywords)}件の検索タブを開きました。")
    print("\n   SERPs画面を確認してください。")
    input("   確認が終わったら Enter を押してください...")

    # ── SERPs確認後：狙い目キーワードをスプレッドシートに保存 ──
    after_options = [
        "狙い目キーワードを選んでスプレッドシートに保存",
        "戻る（保存しない）",
    ]
    after_choice = arrow_menu("SERPs確認後のアクション", after_options, allow_back=False)

    if after_choice == 1:
        return

    # 検索したキーワードから狙い目を選択
    save_labels = []
    for i in selected:
        kw, vol, comp = rows[i]
        vol_str = f" [{vol}]" if vol else " [-]"
        comp_str = f" ({comp})" if comp else ""
        save_labels.append(f"{kw}{vol_str}{comp_str}")

    save_indices = arrow_menu_multiselect(
        "スプレッドシートに保存するキーワードを選択\n"
        "（SERPsで狙い目と判断したものだけチェック）",
        save_labels,
        default_checked=[True] * len(save_labels)
    )

    if not save_indices:
        print("\n   ⚠️ キーワードが選択されませんでした。")
        input("   Enterで戻ります...")
        return

    save_rows = [rows[selected[i]] for i in save_indices]
    _anken_save_to_spreadsheet(save_rows)


def run_anken_extractor():
    """案件名抽出＆関連語付与モードのメインフロー。"""
    while True:
        # ── サブメニュー ──
        sub_options = [
            "ASPテキストから案件名を抽出＆関連語付与",
            "プランナーCSV整形＆SERPs確認",
            "アフィリエイトURL管理（[af_url] のリンク先変更）",
            "メインメニューへ戻る",
        ]
        sub_choice = arrow_menu("案件名抽出＆関連語付与", sub_options, allow_back=False)

        if sub_choice == 3:
            return
        if sub_choice == 2:
            run_affiliate_url_manager_entry()
            continue
        if sub_choice == 1:
            _anken_run_csv_formatter()
            continue

        # ── 以下: ASPテキストから案件名を抽出 ──
        os.system('cls')
        print("=" * 60)
        print("  ASPテキストから案件名を抽出")
        print("=" * 60)

        # ── Step 0: APIキー選択 ──
        api_key = select_api_key(API_KEYS_NORMAL)
        if api_key is None:
            continue

        # ── Step 1: テキスト入力 → Gemini抽出 ──
        print("\n" + "-" * 60)
        print("  Step 1: ASPページのテキストを貼り付けてください")
        print("  （Enter3回連続 or EOF で確定）")
        print("-" * 60)
        raw_text = get_multiline_input("", eof_mode=False)
        if not raw_text.strip():
            print("\n   ⚠️ テキストが入力されませんでした。")
            input("   Enterで戻ります...")
            continue

        print("\n   🔄 Gemini APIで案件名を抽出中...")
        names = _anken_extract_names_via_gemini(raw_text, api_key)

        if not names:
            print("   ❌ 案件名を抽出できませんでした。")
            input("   Enterで戻ります...")
            continue

        print(f"\n   ✅ {len(names)}件の案件名を抽出しました:")
        for i, name in enumerate(names, 1):
            print(f"      {i}. {name}")

        # ── Step 2: 案件名の合否判定（フィルタリング）──
        print()
        input("   Enterで案件名の合否判定画面へ進みます...")

        filter_indices = arrow_menu_multiselect(
            "Step 2: 抽出結果の合否判定\n"
            "正しく抽出できた案件名だけを残してください\n"
            "（誤抽出・不要なものは Space で除外）",
            names,
            default_checked=[True] * len(names)
        )

        if not filter_indices:
            print("\n   ⚠️ すべて除外されました。")
            input("   Enterで戻ります...")
            continue

        validated_names = [names[i] for i in filter_indices]
        removed_count = len(names) - len(validated_names)

        # ── Step 2.5: 編集ループ（追加・削除・変更）──
        while True:
            os.system('cls')
            print("=" * 60)
            print(f"  合否判定結果: {len(validated_names)}件 採用")
            if removed_count > 0:
                print(f"  （{removed_count}件 除外）")
            print("=" * 60)
            for i, name in enumerate(validated_names, 1):
                print(f"    {i}. {name}")
            print()

            edit_options = [
                "このまま続行（関連語付与へ）",
                "メモ帳で編集（追加・削除・名前変更）",
                "最初からやり直す",
            ]
            edit_choice = arrow_menu("案件名リストの確認", edit_options, allow_back=False)

            if edit_choice == 2:
                break  # while を抜けて continue で最初から
            if edit_choice == 0:
                break  # while を抜けて Step 3 へ
            if edit_choice == 1:
                # メモ帳で編集
                temp_path = os.path.join(BASE_DIR, "_anken_edit_temp.txt")
                with open(temp_path, "w", encoding="utf-8") as f:
                    f.write("# 案件名リスト（1行1件）\n")
                    f.write("# 追加・削除・名前変更が可能です\n")
                    f.write("# #で始まる行はコメント（無視されます）\n")
                    f.write("# 編集後、上書き保存(Ctrl+S)してメモ帳を閉じてください\n\n")
                    for name in validated_names:
                        f.write(name + "\n")
                print("\n   🛑 メモ帳が開きます。編集して保存→閉じてください。")
                try:
                    subprocess.call(['notepad.exe', temp_path])
                except Exception as e:
                    print(f"   ⚠️ メモ帳起動エラー: {e}")
                input("   >> 編集が終わったら Enter キーを押してください <<")
                # 編集結果を読み込み
                try:
                    with open(temp_path, "r", encoding="utf-8") as f:
                        edited_lines = f.readlines()
                    new_names = []
                    for line in edited_lines:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            new_names.append(line)
                    if new_names:
                        validated_names = new_names
                        print(f"\n   ✅ {len(validated_names)}件に更新されました。")
                    else:
                        print("\n   ⚠️ 有効な案件名がありません。変更前のリストを維持します。")
                except Exception as e:
                    print(f"   ❌ ファイル読み込みエラー: {e}")
                input("   Enterで続行...")
                # ループ先頭に戻って再表示
                continue

        if edit_choice == 2:
            continue  # run_anken_extractor の while ループ先頭へ（やり直し）

        # ── Step 3: 関連語を付ける案件名の選択 ──
        kw_scope_options = [
            f"全件（{len(validated_names)}件すべて）に関連語を付ける",
            "一部の案件名だけに関連語を付ける",
            "関連語なし（案件名のみ出力 → クリップボード）",
            "最初からやり直す",
        ]
        scope_choice = arrow_menu("関連語の付与範囲を選択", kw_scope_options, allow_back=False)

        if scope_choice == 3:
            continue

        if scope_choice == 2:
            output_text = "\n".join(validated_names)
            if _anken_copy_to_clipboard(output_text):
                print(f"\n   ✅ {len(validated_names)}件の案件名をクリップボードにコピーしました。")
            input("   Enterで続行...")
            continue

        if scope_choice == 1:
            kw_target_indices = arrow_menu_multiselect(
                "Step 3: 関連語を付与する案件名を選択\n"
                "（関連語が不要な案件名は Space で除外）",
                validated_names,
                default_checked=[True] * len(validated_names)
            )
            if not kw_target_indices:
                print("\n   ⚠️ 選択されませんでした。")
                input("   Enterで戻ります...")
                continue
            kw_target_names = [validated_names[i] for i in kw_target_indices]
            kw_skip_names = [n for n in validated_names if n not in kw_target_names]
        else:
            kw_target_names = validated_names
            kw_skip_names = []

        # ── Step 4: 関連語入力 → リスト生成 ──
        os.system('cls')
        print("=" * 60)
        print(f"  関連語付与対象: {len(kw_target_names)}件")
        print("=" * 60)
        for name in kw_target_names:
            print(f"    ・{name}")
        print("\n" + "-" * 60)
        print("  関連語をカンマ区切りで入力してください")
        print("  （例: 効果,口コミ,評判）")
        print("-" * 60)
        kw_input = input("  関連語: ").strip()

        related_keywords = []
        if kw_input:
            related_keywords = [kw.strip() for kw in kw_input.replace('、', ',').split(',') if kw.strip()]

        # リスト生成
        output_lines = []
        for name in kw_target_names:
            output_lines.append(name)
            for kw in related_keywords:
                output_lines.append(f"{name} {kw}")
        for name in kw_skip_names:
            output_lines.append(name)
        output_text = "\n".join(output_lines)

        # 結果表示
        os.system('cls')
        print("=" * 60)
        print("  生成結果")
        print("=" * 60)
        total = len(output_lines)
        if total <= 40:
            for line in output_lines:
                print(f"    {line}")
        else:
            for line in output_lines[:20]:
                print(f"    {line}")
            print(f"    ... (中略 {total - 40}行) ...")
            for line in output_lines[-20:]:
                print(f"    {line}")

        print(f"\n  合計: {total}行")
        if related_keywords:
            print(f"  （関連語付き {len(kw_target_names)}案件 × {1 + len(related_keywords)}パターン"
                  + (f" + 案件名のみ {len(kw_skip_names)}件" if kw_skip_names else "")
                  + "）")

        # ── 出力 ──
        output_options = [
            "クリップボードにコピー",
            "案件名のみコピー（関連語なし）",
            "最初からやり直す",
            "メインメニューへ戻る",
        ]
        out_choice = arrow_menu("出力方法を選択", output_options, allow_back=False)

        if out_choice == 0:
            if _anken_copy_to_clipboard(output_text):
                print(f"\n   ✅ {total}行をクリップボードにコピーしました。")
                print("   キーワードプランナーに貼り付けてください。")
            input("   Enterで続行...")
        elif out_choice == 1:
            names_only = "\n".join(validated_names)
            if _anken_copy_to_clipboard(names_only):
                print(f"\n   ✅ {len(validated_names)}件の案件名をクリップボードにコピーしました。")
            input("   Enterで続行...")
        elif out_choice == 2:
            continue
        elif out_choice == 3:
            return


def run_mode_aio_standalone():
    print("\n" + "=" * 60)
    print("  AIO補強（個別実行）")
    print("=" * 60)
    print("  既存の親記事ログを選び、必要な時だけAIO補強を実行します。")

    site_labels = [v["name"] for v in SITES_ALL.values()]
    site_keys = list(SITES_ALL.keys())
    site_idx = arrow_menu("対象サイトを選択してください", site_labels, allow_back=True)
    if site_idx == -1:
        return
    site_key = site_keys[site_idx]
    selected_site = SITES_ALL[site_key]
    api_keys = API_KEYS_MOECHIN if selected_site.get("type") == "C" else API_KEYS_NORMAL

    selected_api_key = select_api_key(api_keys)
    if selected_api_key is None:
        return

    logs = sorted(
        glob.glob(os.path.join(PARENT_LOGS, "log_PARENT_*.txt")),
        key=os.path.getmtime,
        reverse=True,
    )
    candidates = []
    for path in logs:
        if os.path.getsize(path) < 1000:
            continue
        html = extract_latest_article_html_from_log(read_file(path))
        if not html:
            continue
        m = re.match(r'log_PARENT_(.+?)_\d{8}_\d{4}\.txt$', os.path.basename(path))
        keyword = m.group(1).strip() if m else os.path.basename(path)
        label = f"[{datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime('%m/%d %H:%M')}] {keyword}"
        candidates.append({"path": path, "keyword": keyword, "html": html, "label": label})
        if len(candidates) >= 30:
            break

    if not candidates:
        print("   ⚠️ AIO補強に使える親記事ログが見つかりませんでした。")
        input("\nEnterを押してメインメニューへ戻ります...")
        return

    log_idx = arrow_menu("AIO補強する親記事ログを選択してください", [c["label"] for c in candidates], allow_back=True)
    if log_idx == -1:
        return
    item = candidates[log_idx]
    keyword = item["keyword"]
    final_content = item["html"]
    initial_instruction = f"既存親記事ログからAIO補強を個別実行します。\nログ: {item['path']}\nキーワード: {keyword}"

    print(f"\n✅ 対象記事: {keyword}")
    print_article_output_summary(final_content, "補強前HTML")
    enhanced_content, should_post, aio_log_extra = run_aio_enhancement_flow(
        selected_api_key,
        api_keys,
        keyword,
        final_content,
        selected_site,
        initial_instruction,
    )
    if not aio_log_extra:
        print("\n   ℹ️ AIO補強は実行されませんでした。")
        input("\nEnterを押してメインメニューへ戻ります...")
        return
    if not should_post:
        print("\n📝 AIO補強HTMLを保存しました。WordPress投稿は行いません。")
        input("\nEnterを押してメインメニューへ戻ります...")
        return

    enhanced_content, broken_links = validate_final_html_links(enhanced_content, "AIO補強後HTML")
    if broken_links:
        aio_log_extra.append({
            "role": "System (投稿前リンクチェック)",
            "text": "投稿前リンク安全チェックで、読者が開けない可能性がある以下のURLのリンクだけを解除しました（アンカーテキストは本文に残しています）。\n" + "\n".join(u for u, _, _ in broken_links)
        })
    print("\n📤 WordPress下書き投稿中...")
    post_to_wordpress(selected_site, f"【AIO補強】{keyword[:30]}...", enhanced_content)
    save_log_parent(f"AIO補強_{keyword}", aio_log_extra)
    input("\nEnterを押してメインメニューへ戻ります...")


def _workflow_done_key(site_name, keyword):
    return f"{site_name or '_サイト未分類'}::{_result_history_normalize_keyword(keyword)}"


def _load_workflow_done_map():
    try:
        with open(WORKFLOW_DONE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_workflow_done_map(done_map):
    os.makedirs(os.path.dirname(WORKFLOW_DONE_FILE), exist_ok=True)
    with open(WORKFLOW_DONE_FILE, "w", encoding="utf-8") as f:
        json.dump(done_map, f, ensure_ascii=False, indent=2)


def _set_workflow_done(site_name, keyword, done=True):
    done_map = _load_workflow_done_map()
    key = _workflow_done_key(site_name, keyword)
    if done:
        done_map[key] = {
            "site": site_name,
            "keyword": keyword,
            "done_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pc": PC_IDENTIFIER,
        }
    else:
        done_map.pop(key, None)
    _save_workflow_done_map(done_map)


def _load_workflow_progress_map():
    try:
        with open(WORKFLOW_PROGRESS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_workflow_progress_map(progress_map):
    os.makedirs(os.path.dirname(WORKFLOW_PROGRESS_FILE), exist_ok=True)
    with open(WORKFLOW_PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress_map, f, ensure_ascii=False, indent=2)


def _workflow_progress_entry(site_name, keyword):
    progress = _load_workflow_progress_map()
    key = _workflow_done_key(site_name, keyword)
    entry = progress.setdefault(key, {
        "site": site_name,
        "keyword": keyword,
        "child_done_topics": [],
        "child_existing_topics": [],
        "child_skipped_topics": [],
        "updated_at": "",
    })
    return progress, key, entry


def _mark_workflow_child_topic(site_name, keyword, topic, status, url=""):
    if not keyword or not topic:
        return
    progress, key, entry = _workflow_progress_entry(site_name, keyword)
    field_map = {
        "done": "child_done_topics",
        "existing": "child_existing_topics",
        "skipped": "child_skipped_topics",
    }
    field = field_map.get(status)
    if not field:
        return
    record = {"topic": topic, "url": url or "", "at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    norm_topic = _result_history_normalize_keyword(topic)
    existing = entry.setdefault(field, [])
    if not any(_result_history_normalize_keyword(x.get("topic", "")) == norm_topic for x in existing if isinstance(x, dict)):
        existing.append(record)
    entry["updated_at"] = record["at"]
    progress[key] = entry
    _save_workflow_progress_map(progress)


def _workflow_completed_child_topic_norms(site_name, keyword):
    progress = _load_workflow_progress_map()
    entry = progress.get(_workflow_done_key(site_name, keyword), {})
    norms = set()
    for field in ("child_done_topics", "child_existing_topics", "child_skipped_topics"):
        for record in entry.get(field, []) if isinstance(entry.get(field, []), list) else []:
            topic = record.get("topic", "") if isinstance(record, dict) else str(record)
            norm = _result_history_normalize_keyword(topic)
            if norm:
                norms.add(norm)
    return norms


def _workflow_collect_status_items(limit=20):
    """生成済みファイルを親記事キーワード単位に集め、次にやる作業を推定する。"""
    sessions = {}
    done_map = _load_workflow_done_map()

    def _workflow_keyword_from_filename(path):
        bname = os.path.basename(path)
        stem = os.path.splitext(bname)[0]
        stem = re.sub(r"^\[[^\]]+\]", "", stem)
        prefixes = [
            "内部リンク判断API結果_",
            "内部リンク貼り付け指示まとめ_",
            "メタ入稿用サマリー_",
            "メタ情報API結果_",
            "処理結果まとめ_",
            "子記事作成リスト_",
        ]
        for prefix in prefixes:
            if stem.startswith(prefix):
                stem = stem[len(prefix):]
                stem = re.sub(r"^\d+_", "", stem)
                stem = re.sub(r"_\d{8}_\d{4,6}$", "", stem)
                return stem.strip()
        return _result_history_keyword_from_filename(path)

    def _touch(site_name, keyword, path):
        keyword = (keyword or "").strip()
        if not keyword:
            return None
        key = (site_name or "_サイト未分類", _result_history_normalize_keyword(keyword))
        item = sessions.setdefault(key, {
            "site": site_name or "_サイト未分類",
            "keyword": keyword,
            "mtime": 0,
            "paths": [],
            "kinds": set(),
            "pending_paths": [],
            "pending_topics": [],
            "pending_entries": [],
            "manual_internal_prompts": [],
            "api_internal_results": [],
            "apply_summaries": [],
            "parent_logs": [],
        })
        item["keyword"] = keyword if len(keyword) > len(item.get("keyword", "")) else item.get("keyword", keyword)
        item["paths"].append(path)
        try:
            item["mtime"] = max(item["mtime"], os.path.getmtime(path))
        except Exception:
            pass
        return item

    def _parse_workflow_summary(path):
        """処理結果まとめから、内部リンクの未完了状態を拾う。"""
        state = {
            "manual_internal_prompts": [],
            "api_internal_results": [],
            "apply_summaries": [],
        }
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:
            return state

        in_internal = False
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if line.startswith("【内部リンク判断】"):
                in_internal = True
                continue
            if in_internal and line.startswith("【") and not line.startswith("【内部リンク判断】"):
                in_internal = False

            if in_internal and "AI Studio貼り付け用プロンプト:" in line and "生成なし" not in line:
                val = line.split(":", 1)[-1].strip()
                if val:
                    state["manual_internal_prompts"].append(val)
            if in_internal and "Gemini API結果:" in line:
                val = line.split(":", 1)[-1].strip()
                if val:
                    state["api_internal_results"].append(val)
            if in_internal and "内部リンク貼り付け指示まとめ:" in line and "生成なし" not in line:
                val = line.split(":", 1)[-1].strip()
                if val:
                    state["apply_summaries"].append(val)
        return state

    def _parent_keyword_from_internal_prompt(path):
        """途中終了で処理結果まとめが無い場合に、内部リンク手動用ファイルから親記事KWを拾う。"""
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read(4000)
        except Exception:
            return ""
        patterns = [
            r'親記事キーワード\s*[:：]\s*([^\n\r]+)',
            r'キーワード\s*[:：]\s*([^\n\r]+)',
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                val = re.sub(r'\s+', ' ', m.group(1)).strip()
                if val and "（" not in val[:2]:
                    return val
        return ""

    # 作業結果/旧フォルダ内のメタ・内部リンク・子記事作成リスト
    for base_dir in (UNIFIED_OUTPUT_DIR, LEGACY_AI_STUDIO_PROMPTS_DIR, LEGACY_STEP9_10_RESULTS_DIR):
        if not os.path.isdir(base_dir):
            continue
        for site_dir in glob.glob(os.path.join(base_dir, "*")):
            if not os.path.isdir(site_dir):
                continue
            site_name = os.path.basename(site_dir)
            for path in glob.glob(os.path.join(site_dir, "*.txt")):
                bname = os.path.basename(path)
                if "internal_link_prompt_" in bname or bname.startswith("[子]step10_"):
                    keyword = _parent_keyword_from_internal_prompt(path)
                    item = _touch(site_name, keyword, path)
                    if item:
                        item["kinds"].add("内部リンク判断ファイル")
                        item["manual_internal_prompts"].append(path)
                    continue
                if bname.startswith("[子]meta_prompt_"):
                    continue
                keyword = _workflow_keyword_from_filename(path)
                item = _touch(site_name, keyword, path)
                if not item:
                    continue
                kind = _result_history_file_kind(path)
                item["kinds"].add(kind)
                if kind == "子記事作成リスト":
                    item["pending_paths"].append(path)
                    pending_entries = _result_history_extract_pending_entries_from_file(path)
                    item["pending_entries"].extend(pending_entries)
                    item["pending_topics"].extend([x.get("topic", "") for x in pending_entries if x.get("topic")])
                elif kind == "結果まとめ":
                    summary_state = _parse_workflow_summary(path)
                    item["manual_internal_prompts"].extend(summary_state["manual_internal_prompts"])
                    item["api_internal_results"].extend(summary_state["api_internal_results"])
                    item["apply_summaries"].extend(summary_state["apply_summaries"])
                elif kind == "内部リンク判断API結果":
                    item["api_internal_results"].append(path)
                elif kind == "内部リンク貼り付け指示まとめ":
                    item["apply_summaries"].append(path)

    # 親記事ログ
    if os.path.isdir(PARENT_LOGS):
        for path in glob.glob(os.path.join(PARENT_LOGS, "log_PARENT_*.txt")):
            keyword = _result_history_keyword_from_filename(path)
            item = _touch("_サイト未分類", keyword, path)
            if not item:
                continue
            item["kinds"].add("親記事ログ")
            item["parent_logs"].append(path)

    # サイト名が分からない親記事ログを、同じキーワードのサイト別セッションへ寄せる。
    for key, item in list(sessions.items()):
        site_name, norm_kw = key
        if site_name != "_サイト未分類":
            continue
        target_key = next((k for k in sessions.keys() if k[0] != "_サイト未分類" and k[1] == norm_kw), None)
        if not target_key:
            continue
        target = sessions[target_key]
        target["paths"].extend(item.get("paths", []))
        target["kinds"].update(item.get("kinds", set()))
        target["pending_paths"].extend(item.get("pending_paths", []))
        target["pending_topics"].extend(item.get("pending_topics", []))
        target["pending_entries"].extend(item.get("pending_entries", []))
        target["manual_internal_prompts"].extend(item.get("manual_internal_prompts", []))
        target["api_internal_results"].extend(item.get("api_internal_results", []))
        target["apply_summaries"].extend(item.get("apply_summaries", []))
        target["parent_logs"].extend(item.get("parent_logs", []))
        target["mtime"] = max(target.get("mtime", 0), item.get("mtime", 0))
        sessions.pop(key, None)

    result = []
    for item in sessions.values():
        kinds = item["kinds"]
        def _internal_candidate_index_from_path(path):
            bname = os.path.basename(path or "")
            m = re.search(r'(?:internal_link_prompt|step10|内部リンク判断API結果)_(\d+)_', bname)
            if m:
                try:
                    return int(m.group(1))
                except Exception:
                    return None
            return None

        pending_topics = []
        pending_entries = []
        seen = set()
        done_child_norms = _workflow_completed_child_topic_norms(item.get("site", ""), item.get("keyword", ""))
        raw_pending_entries = item.get("pending_entries") or [
            {"topic": topic, "reason": "", "existing_title": "", "existing_url": "", "source_path": ""}
            for topic in item.get("pending_topics", [])
        ]
        for entry in raw_pending_entries:
            topic = entry.get("topic", "")
            norm = _result_history_normalize_keyword(topic)
            if norm in done_child_norms:
                continue
            if norm and norm not in seen:
                seen.add(norm)
                pending_topics.append(topic)
                pending_entries.append(entry)
        item["pending_topics"] = pending_topics
        item["pending_entries"] = pending_entries

        has_meta = "入稿用サマリー（SEO/カテゴリ手動コピペ用）" in kinds
        has_meta_prompt_only = (
            any("[親]meta_prompt_" in os.path.basename(p) or os.path.basename(p).startswith("[親]meta_prompt_") for p in item["paths"])
            and not has_meta
        )
        manual_internal_files = list(dict.fromkeys(item.get("manual_internal_prompts", [])))
        api_internal_files = list(dict.fromkeys(item.get("api_internal_results", [])))
        apply_summary_files = list(dict.fromkeys(item.get("apply_summaries", [])))
        item["manual_internal_prompts"] = manual_internal_files
        item["api_internal_results"] = api_internal_files
        item["apply_summaries"] = apply_summary_files
        api_result_states_by_index = {}
        api_result_topic_norms_by_index = {}
        api_actionable_topic_norms = set()
        for p in sorted(api_internal_files, key=lambda x: os.path.getmtime(x) if os.path.exists(x) else 0):
            idx = _internal_candidate_index_from_path(p)
            fields = _read_internal_link_result_fields_from_path(p)
            state = _internal_link_result_state(fields)
            topic_norm = _result_history_normalize_keyword(fields.get("topic", ""))
            if idx is not None:
                api_result_states_by_index[idx] = state
                api_result_topic_norms_by_index[idx] = topic_norm
            if state == "actionable":
                if topic_norm:
                    api_actionable_topic_norms.add(topic_norm)

        # 古い子記事作成リストに残っていても、後続の内部リンク判断で
        # 「既存記事への貼り付け可」と確定した候補は、続き作業の子記事対象から外す。
        filtered_pending_entries = []
        filtered_pending_topics = []
        filtered_seen = set()
        for entry in item.get("pending_entries", []):
            topic = entry.get("topic", "")
            norm = _result_history_normalize_keyword(topic)
            idx = None
            try:
                idx = int(entry.get("index") or 0)
            except Exception:
                idx = None
            if idx is not None and api_result_states_by_index.get(idx) == "actionable":
                api_topic_norm = api_result_topic_norms_by_index.get(idx, "")
                if not api_topic_norm or not norm or api_topic_norm == norm:
                    continue
            if norm and norm in api_actionable_topic_norms:
                continue
            if norm and norm not in filtered_seen:
                filtered_seen.add(norm)
                filtered_pending_entries.append(entry)
                filtered_pending_topics.append(topic)
        item["pending_entries"] = filtered_pending_entries
        item["pending_topics"] = filtered_pending_topics
        pending_entries = filtered_pending_entries
        pending_topics = filtered_pending_topics

        api_internal_indices = {
            idx for idx in (_internal_candidate_index_from_path(p) for p in api_internal_files)
            if idx is not None
        }
        manual_wait_files = []
        for p in manual_internal_files:
            idx = _internal_candidate_index_from_path(p)
            if idx is None or idx not in api_internal_indices:
                manual_wait_files.append(p)
        manual_internal_count = len(manual_internal_files)
        api_internal_count = len(api_internal_files)
        apply_summary_count = len(apply_summary_files)
        manual_wait_count = len(manual_wait_files)
        has_internal = bool({"内部リンク貼り付け指示まとめ", "内部リンク判断API結果", "内部リンク判断ファイル"} & kinds) or manual_internal_count > 0
        has_parent = "親記事ログ" in kinds or any("[親]meta_prompt_" in os.path.basename(p) for p in item["paths"])
        done_key = _workflow_done_key(item.get("site"), item.get("keyword"))
        is_done = done_key in done_map
        pending_entries_for_status = item.get("pending_entries", [])
        non_recommended_pending_count = sum(
            1 for entry in pending_entries_for_status
            if "非推奨" in (entry.get("reason", "") or "")
        )
        skipped_pending_count = sum(
            1 for entry in pending_entries_for_status
            if "スキップ" in (entry.get("reason", "") or "") or "該当する公開済み記事なし" in (entry.get("reason", "") or "")
        )

        if is_done:
            next_action = "完了済み"
            next_detail = "人間が完了済みにした案件です。必要なら完了を取り消せます。"
            status = "完了"
        elif has_parent and not has_meta:
            if has_meta_prompt_only:
                next_action = "メタ情報未完了（手動用プロンプトのみ作成済み）"
                next_detail = "SEOタイトル/説明文/カテゴリ用の入稿用サマリーが未生成です。まずメニュー5でメタ情報だけ作成してください。"
            else:
                next_action = "メタ情報作成"
                next_detail = "SEOタイトル/説明文/カテゴリ用の入稿用サマリーが未生成です。まずメニュー5でメタ情報を作成してください。"
            status = "途中"
        elif pending_topics and manual_wait_count:
            next_action = f"内部リンク未完了（{manual_wait_count}件）＋子記事作成候補（{len(pending_topics)}件）"
            next_detail = "まずメニュー5で内部リンクだけ再確認します。不要な候補はそこでスキップし、必要な子記事だけ作成へ回してください。"
            status = "途中"
        elif pending_topics:
            reason_parts = []
            if skipped_pending_count:
                reason_parts.append(f"未作成/スキップ{skipped_pending_count}件")
            if non_recommended_pending_count:
                reason_parts.append(f"既存記事非推奨{non_recommended_pending_count}件")
            reason_note = f"（{ ' / '.join(reason_parts) }）" if reason_parts else ""
            next_action = f"子記事作成が必要（{len(pending_topics)}件）{reason_note}"
            next_detail = "残っている候補は、未作成または既存記事が非推奨になったものです。子記事を作成し、その後メニュー5で内部リンクだけ再確認します。"
            status = "途中"
        elif manual_wait_count:
            next_action = f"内部リンク手動判断待ち（{manual_wait_count}件）"
            next_detail = "API結果がない内部リンク判断ファイルがあります。メニュー5で内部リンクだけ再確認してください。"
            status = "途中"
        elif has_internal:
            next_action = "内部リンク結果を確認・親記事へ反映"
            next_detail = "貼り付け指示まとめがある場合は、その内容を親記事へ手動反映します。"
            status = "確認待ち"
        elif has_meta and has_parent:
            next_action = "内部リンク判断"
            next_detail = "メニュー5で内部リンクだけ確認します。"
            status = "途中"
        elif has_parent:
            next_action = "メタ情報作成＋内部リンク判断"
            next_detail = "メニュー5で通常の続きとしてメタ情報と内部リンクを進めます。"
            status = "途中"
        else:
            next_action = "状況確認"
            next_detail = "親記事ログが見つからないため、生成結果ファイルを確認してください。"
            status = "要確認"

        if not has_parent and not pending_topics and not has_internal:
            continue

        item.update({
            "status": status,
            "has_parent": has_parent,
            "has_meta": has_meta,
            "has_meta_prompt_only": has_meta_prompt_only,
            "has_internal": has_internal,
            "manual_internal_count": manual_internal_count,
            "api_internal_count": api_internal_count,
            "apply_summary_count": apply_summary_count,
            "manual_wait_count": manual_wait_count,
            "manual_wait_files": manual_wait_files,
            "done_key": done_key,
            "is_done": is_done,
            "next_action": next_action,
            "next_detail": next_detail,
        })
        result.append(item)

    result.sort(key=lambda x: x.get("mtime", 0), reverse=True)
    return result[:limit]


def run_workflow_status_dashboard():
    """親記事から内部リンク完了までの作業状況を一覧表示する。"""
    def _site_key_from_name(site_name):
        for key, info in SITES_NORMAL.items():
            if info.get("name") == site_name:
                return key
        return None

    def _open_paths(paths):
        opened = 0
        for path in list(dict.fromkeys(paths or [])):
            if path and os.path.exists(path):
                try:
                    os.startfile(path)
                    opened += 1
                except Exception as e:
                    print(f"   ⚠️ 開けませんでした: {path} / {e}")
        if opened:
            print(f"   ✅ {opened}件のファイルを開きました。")
        else:
            print("   ⚠️ 開けるファイルが見つかりませんでした。")
        input("\nEnterで戻ります...")

    show_completed = False
    while True:
        os.system('cls')
        print("=" * 60)
        print("  作業状況・続き確認")
        print("=" * 60)
        print("  親記事ごとに、完了済みの工程と次にやる作業を表示します。")
        print("  案件を選ぶと、そのまま次の作業へ進めます。")
        if show_completed:
            print("  ※ 完了済みも表示中です。")
        else:
            print("  ※ 完了済みにした案件は非表示です。")
        print()

        all_items = _workflow_collect_status_items(limit=30)
        items = all_items if show_completed else [x for x in all_items if not x.get("is_done")]
        if not items:
            print("  表示できる未完了の作業はありません。")
            empty_options = [
                "完了済みも表示する" if not show_completed else "完了済みを隠す",
                "メインメニューへ戻る",
            ]
            empty_idx = arrow_menu("次の操作", empty_options, allow_back=False)
            if empty_idx == 0:
                show_completed = not show_completed
                continue
            return

        labels = []
        for idx, item in enumerate(items, 1):
            mtime = datetime.datetime.fromtimestamp(item["mtime"]).strftime("%m/%d %H:%M") if item.get("mtime") else "--/-- --:--"
            print("─" * 60)
            print(f"{idx}. [{mtime}] {item['site']} / {item['keyword']}")
            print(f"   状態: {item['status']}")
            print(
                "   工程: "
                f"親記事 {'済' if item['has_parent'] else '未確認'} / "
                f"メタ情報 {'済' if item['has_meta'] else '未'} / "
                f"内部リンク {'済または途中' if item['has_internal'] else '未'}"
                f"（手動待ち{item.get('manual_wait_count', 0)}件 / API結果{item.get('api_internal_count', 0)}件 / 貼付まとめ{item.get('apply_summary_count', 0)}件） / "
                f"子記事作成リスト {len(item['pending_topics'])}件"
            )
            print(f"   次にやること: {item['next_action']}")
            print(f"   手順: {item['next_detail']}")
            if item["pending_topics"]:
                print("   残っている子記事候補:")
                pending_entries = item.get("pending_entries") or [
                    {"topic": topic, "reason": ""} for topic in item["pending_topics"]
                ]
                for entry in pending_entries[:5]:
                    print(f"     - {entry.get('topic', '')}")
                    if entry.get("reason"):
                        print(f"       理由: {entry.get('reason')}")
                if len(item["pending_topics"]) > 5:
                    print(f"     ...ほか {len(item['pending_topics']) - 5}件")
            manual_wait_files = list(dict.fromkeys(item.get("manual_wait_files", [])))
            if item.get("manual_wait_count", 0) and manual_wait_files:
                print("   内部リンク手動判断待ち:")
                for path in manual_wait_files[:3]:
                    print(f"     - {os.path.basename(path)}")
                if len(manual_wait_files) > 3:
                    print(f"     ...ほか {len(manual_wait_files) - 3}件")

            labels.append(f"[{mtime}] {item['site']} / {item['keyword']} → {item['next_action']}")

        print("─" * 60)
        labels.append("完了済みも表示する" if not show_completed else "完了済みを隠す")
        labels.append("メインメニューへ戻る")
        selected_idx = arrow_menu(
            "続き作業を選択してください\n"
            "  案件を選ぶと、次にできる操作を表示します。",
            labels,
            allow_back=False,
        )
        if selected_idx == len(items):
            show_completed = not show_completed
            continue
        if selected_idx == len(items) + 1:
            return

        item = items[selected_idx]
        site_key = _site_key_from_name(item.get("site"))
        manual_wait_files = list(dict.fromkeys(item.get("manual_wait_files", [])))

        def _execute_workflow_action(kind, payload):
            if kind == "back":
                return "back"
            if kind == "open":
                _open_paths(payload)
                return "continue"
            if kind == "child":
                if not site_key:
                    print("   ⚠️ サイトを特定できません。通常の子記事作成メニューを開きます。")
                    input("\nEnterで進みます...")
                    run_mode_child_normal()
                else:
                    run_mode_child_normal(
                        prefill_site_key=site_key,
                        prefill_topics=item.get("pending_topics", []),
                        prefill_parent_keyword=item.get("keyword", ""),
                    )
                return "exit"
            if kind == "step9_10":
                run_step9_10()
                return "exit"
            if kind == "done":
                confirm_idx = arrow_menu(
                    "この記事を完了済みにしますか？\n"
                    "  完了済みにすると通常の続き確認一覧から隠れます。\n"
                    "  必要になれば「完了済みも表示する」から取り消せます。",
                    ["完了済みにする", "やめる"],
                    allow_back=False,
                )
                if confirm_idx == 0:
                    _set_workflow_done(item.get("site"), item.get("keyword"), done=True)
                    print("   ✅ 完了済みにしました。")
                    input("\nEnterで一覧へ戻ります...")
                return "continue"
            if kind == "undone":
                _set_workflow_done(item.get("site"), item.get("keyword"), done=False)
                print("   ✅ 完了を取り消しました。")
                input("\nEnterで一覧へ戻ります...")
                return "continue"
            return "continue"

        primary_label = None
        primary_handler = None
        if item.get("is_done"):
            primary_label = "完了を取り消す（未完了一覧に戻す）"
            primary_handler = ("undone", None)
        elif item.get("has_parent") and not item.get("has_meta"):
            if item.get("has_meta_prompt_only"):
                primary_label = "推奨: メタ情報だけ作成する（入稿用サマリー未生成）"
            else:
                primary_label = "推奨: メタ情報を作成する（入稿用サマリー未生成）"
            primary_handler = ("step9_10", None)
        elif item.get("manual_wait_count", 0) and manual_wait_files:
            primary_label = f"推奨: 内部リンクだけ再確認する（未完了{item.get('manual_wait_count', 0)}件）"
            primary_handler = ("step9_10", None)
        elif item.get("pending_topics"):
            pending_entries_for_menu = item.get("pending_entries", [])
            has_non_recommended_pending = any("非推奨" in (entry.get("reason", "") or "") for entry in pending_entries_for_menu)
            reason_note = "既存記事非推奨/未作成の候補" if has_non_recommended_pending else "未作成の候補"
            primary_label = f"推奨: 子記事を作成する（{reason_note} 残り{len(item['pending_topics'])}件。次画面で対象を確認）"
            primary_handler = ("child", None)
        elif item.get("has_parent") and item.get("has_meta"):
            primary_label = "推奨: 内部リンク判断へ進む"
            primary_handler = ("step9_10", None)
        else:
            primary_label = "推奨: 関連ファイルを開いて確認する"
            primary_handler = ("open", item.get("paths", []))

        action_idx = arrow_menu(
            f"{item['site']} / {item['keyword']} ─ 次の操作\n"
            f"  次にやること: {item['next_action']}\n"
            "  迷ったら1を選んでください。\n"
            "  別の既存記事で再確認したい場合や、完了済みにする場合だけ補助操作を開いてください。",
            [
                primary_label,
                "補助操作を開く（ファイル確認・完了処理など）",
                "一覧へ戻る",
            ],
            allow_back=False,
        )
        if action_idx == 0:
            result = _execute_workflow_action(*primary_handler)
            if result == "exit":
                return
            continue
        if action_idx == 2:
            continue

        support_labels = []
        support_handlers = []
        if item.get("pending_topics"):
            support_labels.append("子記事作成リストを開く")
            support_handlers.append(("open", item.get("pending_paths", [])))
            support_labels.append("別の既存記事で内部リンクを再確認する")
            support_handlers.append(("step9_10", None))
            support_labels.append("子記事候補を既存記事対応済みにする（子記事作成対象から外す）")
            support_handlers.append(("mark_existing", None))
        if item.get("manual_wait_count", 0) and manual_wait_files:
            support_labels.append(f"内部リンク手動判断ファイルを開く（{item.get('manual_wait_count', 0)}件）")
            support_handlers.append(("open", manual_wait_files))
        support_labels.append("この案件の関連ファイルを開く")
        support_handlers.append(("open", item.get("paths", [])))
        if item.get("is_done"):
            support_labels.append("完了を取り消す（未完了一覧に戻す）")
            support_handlers.append(("undone", None))
        else:
            support_labels.append("この記事を完了済みにする（通常一覧から隠す）")
            support_handlers.append(("done", None))
        support_labels.append("前の画面へ戻る")
        support_handlers.append(("back", None))

        support_idx = arrow_menu(
            f"{item['site']} / {item['keyword']} ─ 補助操作",
            support_labels,
            allow_back=False,
        )
        kind, payload = support_handlers[support_idx]
        if kind == "mark_existing":
            topic_idx = arrow_menu(
                "既存記事で対応済みにする子記事候補を選択\n"
                "  ここで選んだ候補は、次回の子記事作成対象から外れます。",
                item.get("pending_topics", []) + ["やめる"],
                allow_back=False,
            )
            if topic_idx < len(item.get("pending_topics", [])):
                topic = item["pending_topics"][topic_idx]
                _mark_workflow_child_topic(item.get("site"), item.get("keyword"), topic, "existing")
                print(f"   ✅ 既存記事対応済みにしました: {topic}")
                input("\nEnterで一覧へ戻ります...")
            continue
        result = _execute_workflow_action(kind, payload)
        if result == "exit":
            return
        continue


# ============================================================
# メイン
# ============================================================
def main():
    global PC_IDENTIFIER, RESEARCH_FILE
    # PC識別子が未設定の場合、初回セットアップを実行
    if PC_IDENTIFIER == "UNKNOWN":
        PC_IDENTIFIER = setup_pc_identifier()
        # RESEARCH_FILE はモジュール読み込み時に "UNKNOWN" で固定されているため再設定
        RESEARCH_FILE = os.path.join(BASE_DIR, f"research_{PC_IDENTIFIER}.txt")

    options = [
        "親記事作成（通常サイト）",
        "親記事作成（もえちん）",
        "子記事作成（通常サイト）",
        "子記事作成（もえちん）",
        "メタ情報・入稿情報／内部リンク判断",
        "足し算Prompt・画像セット管理",
        "案件名抽出＆関連語付与",
        "ディープリサーチ支援",
        "AIO補強（個別実行）",
        "監修者マスター管理",
        "作業状況・続き確認",
        "生成結果・入稿ファイルを開く",
        "終了",
    ]
    while True:
        choice = arrow_menu(
            f"記事自動生成ツール 統合版   PC: {PC_IDENTIFIER}",
            options,
            allow_back=False
        )
        if   choice == 0: run_mode_parent_normal()
        elif choice == 1: run_mode_parent_moechin()
        elif choice == 2: run_mode_child_normal()
        elif choice == 3: run_mode_child_moechin()
        elif choice == 4: run_step9_10()
        elif choice == 5: run_tashizan_generator()
        elif choice == 6: run_anken_extractor()
        elif choice == 7:
            try:
                import deep_research_helper
                deep_research_helper.run_deep_research_mode(current_pc_identifier=PC_IDENTIFIER)
            except Exception as _dr_e:
                print(f"\n  ❌ ディープリサーチ支援でエラー: {_dr_e}")
                input("  Enterで戻ります...")
        elif choice == 8:
            run_mode_aio_standalone()
        elif choice == 9:
            run_reviewer_master_manager()
        elif choice == 10:
            run_workflow_status_dashboard()
        elif choice == 11:
            run_result_history_browser()
        elif choice == 12:
            os.system('cls')
            print("終了します。")
            break

if __name__ == "__main__":
    import argparse as _argparse
    _parser = _argparse.ArgumentParser(description="記事自動生成ツール 統合版")
    _parser.add_argument("--keyword", type=str, default="", help="キーワード（kw_classifierからの連携用）")
    _parser.add_argument("--site", type=str, default="", help="サイト番号（1=病院探し, 2=マリッジ, 3=LearnBiz等）")
    _args = _parser.parse_args()

    if _args.keyword:
        # kw_classifierからの連携起動: キーワードとサイトが渡されている
        print("\n" + "=" * 60)
        print("  【kw_classifier 連携モード】")
        print(f"  キーワード: {_args.keyword}")
        if _args.site:
            print(f"  サイト番号: {_args.site}")
        print("=" * 60)
        # 環境変数にセットして run_mode_parent_normal() に渡す
        os.environ["KW_CLASSIFIER_KEYWORD"] = _args.keyword
        os.environ["KW_CLASSIFIER_SITE"] = _args.site or ""
        run_mode_parent_normal()
    else:
        main()
