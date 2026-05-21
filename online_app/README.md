# 記事自動生成ツール オンライン版 v0

## A地点

この段階のA地点は、ローカルCLI全体の完全移植ではありません。

ただし、単なる作業状況ビューでもありません。
親記事・子記事・メタ情報・内部リンク判断という、記事作成自動化の主要実行をブラウザから開始できるv0です。

- サイト、APIキー、プロンプト、足し算Prompt、キーワードをブラウザで指定できる
- 安全確認モードで、API消費・WordPress投稿なしに実行計画を確認できる
- 本番実行では、親記事生成ジョブをバックグラウンドで開始できる
- 子記事生成ジョブをブラウザから登録できる
- メタ情報・入稿情報ジョブをブラウザから登録できる
- 内部リンク案からWordPress検索を行い、候補記事を選んで内部リンク判断ジョブを登録できる
- 生成済み内部リンク判断プロンプトをブラウザから直接API実行できる
- ジョブ一覧とログをブラウザで確認できる
- 既存の `resume_data` を作業状況として読み、次の画面（子記事・メタ情報・内部リンク）へ移動できる
- 設定診断で、保存先・SearchAPI・Geminiキー・WordPress設定の公開前リスクを確認できる
- `/healthz` でPaaSのヘルスチェックを受けられる
- `ONLINE_APP_DATA_DIR` にジョブDBを置き、永続ボリュームへ逃がせる
- 公開環境ではGeminiキー・WordPress認証情報を環境変数から上書きできる

## この段階でまだやらないこと

- 足し算Prompt作成・案件管理・H2画像管理のオンライン実行
- 内部リンクの貼り付け指示まとめ生成と、非推奨候補の子記事作成リスト連携の完全Web化
- Railway専用の本番デプロイ

## 起動

```powershell
pip install -r online_app/requirements.txt
python -m uvicorn online_app.app:app --reload --host 127.0.0.1 --port 8000
```

PowerShellで起動する場合:

```powershell
powershell -ExecutionPolicy Bypass -File online_app/start.ps1 -Port 8010
```

PaaSではリポジトリ直下の `Procfile` を使い、`PORT` 環境変数に合わせて起動します。
Docker対応の公開先では、リポジトリ直下の `Dockerfile` も使えます。

## 画面

- `/parent`: 親記事作成ジョブの入口
- `/parent/jobs`: 親記事作成ジョブの登録
- `/child`: 子記事作成ジョブの入口
- `/meta`: メタ情報・入稿情報ジョブの入口
- `/internal-link`: 内部リンク判断ジョブの入口
- `/internal-link/search`: WordPress検索から内部リンク先候補を選択
- `/jobs`: ジョブ一覧
- `/workflows`: 既存 `resume_data` の作業状況表示
- `/diagnostics`: オンライン移植前の設定診断
- `/deployment-readiness`: 公開デプロイ前の準備チェック
- `/healthz`: PaaS用ヘルスチェック

## 安全確認モード

各入力画面の初期値は「安全確認のみ」です。

このモードでは以下を行いません。

- Gemini APIの実行
- SearchAPIによる競合取得
- WordPress下書き投稿
- WordPress標準項目の更新
- 内部リンク判断API結果の保存

本番実行に切り替える前に、対象サイト・キーワード・足し算Prompt・実行予定ステップを確認するためのモードです。

## v0受け入れ基準

このv0は、以下が通ったら一区切りです。

1. `/diagnostics` がエラー0で表示される
2. `/parent` で安全確認ジョブを登録し、ジョブ詳細が完了する
3. `/child` で安全確認ジョブを登録し、ジョブ詳細が完了する
4. `/meta` で安全確認ジョブを登録し、ジョブ詳細が完了する
5. `/internal-link` でWordPress検索から候補を選び、安全確認ジョブが完了する
6. 本番実行は、最初に親記事1本だけで確認する

## 現時点の本番実行ルール

- 親記事・子記事の本番実行は、Gemini APIを消費し、成功時にWordPress下書きを作成します。
- メタ情報の本番実行は、Gemini API結果と入稿用サマリーを保存します。v0ではWordPress標準項目の自動反映は行いません。
- 内部リンク判断の本番実行は、選択した既存記事候補を使ってGemini API判断結果を保存します。
- 足し算Prompt作成・案件管理・H2画像管理は、まだローカルCLI側で行います。
