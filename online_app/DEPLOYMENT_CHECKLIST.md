# オンライン版 デプロイ前チェックリスト

## A地点の定義

このチェックリストでのA地点は、以下です。

```text
親記事・子記事・メタ情報・内部リンク判断の主要処理をWeb画面/APIから実行でき、
公開環境でも起動・ジョブ保存・秘密情報管理の最低限が破綻しない状態。
```

足し算Prompt作成、案件管理、H2画像管理、内部リンク貼り付け指示まとめの完全Web化は次フェーズです。

## デプロイ前

1. `/deployment-readiness` を開く
2. `error` が0であることを確認する
3. 本番実行する場合は、以下の警告も解消する

```text
ONLINE_APP_DATA_DIR
ONLINE_GEMINI_KEYS_NORMAL_JSON
ONLINE_WP_SITE_OVERRIDES_JSON
SEARCHAPI_API_KEY
```

## 公開先に設定する環境変数

```text
ONLINE_APP_DATA_DIR=/永続ボリューム上のパス
ONLINE_APP_STALE_RUNNING_MINUTES=180
SEARCHAPI_API_KEY=...
ONLINE_GEMINI_KEYS_NORMAL_JSON=[{"name":"結びのマリッジ用","key":"AIza..."}]
ONLINE_WP_SITE_OVERRIDES_JSON={"2":{"url":"https://www.marriage-mr.com","user":"...","pass":"..."}}
```

## デプロイ後の確認順

1. `/healthz` が200を返す
2. `/deployment-readiness` でerrorが0
3. `/parent` で安全確認ジョブを1件実行
4. `/child` で安全確認ジョブを1件実行
5. `/meta` で安全確認ジョブを1件実行
6. `/internal-link` で安全確認ジョブを1件実行
7. 最後に、API消費ありの小規模ジョブを1件だけ実行

## Railway等のホスティング障害時

ホスティング側に障害がある場合は、アプリ修正ではなく公開先の問題です。
その場合でも、以下が揃っていれば別PaaSへ移しやすい状態です。

- `Procfile`
- `Dockerfile`
- `.dockerignore`
- `render.yaml`
- `online_app/requirements.txt`
- `/healthz`
- `ONLINE_APP_DATA_DIR`
- 秘密情報の環境変数上書き
