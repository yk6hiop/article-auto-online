# オンライン移植メモ v0

## 現在の到達点

このv0は、ローカルCLIを丸ごと置き換える完成版ではありません。
ただし、記事作成自動化ツールをWeb画面へ移すための主要入口は揃っています。

- 親記事作成ジョブ
- 子記事作成ジョブ
- メタ情報・入稿情報ジョブ
- 内部リンク候補のWordPress検索
- 候補記事を選んだ内部リンク判断ジョブ
- ジョブ一覧・ログ確認
- 既存resume_dataの作業状況確認

## ローカル起動

```powershell
pip install -r online_app/requirements.txt
python -m uvicorn online_app.app:app --host 127.0.0.1 --port 8010
```

確認URL:

```text
http://127.0.0.1:8010/parent
http://127.0.0.1:8010/deployment-readiness
```

## PaaSへ載せる前の注意

Railway、Render、Fly.io などに載せる場合、先に下記を分離してください。

1. `auto_post_unified.py` 内のAPIキー・WordPress認証情報
2. Google Drive前提の保存パス
3. `pc_config.txt` 前提のPC識別子
4. 長時間ジョブの永続化先

オンライン版のジョブDBは `ONLINE_APP_DATA_DIR` 配下に保存します。
PaaSではこのディレクトリを永続ボリュームに置くか、外部DBへ移す必要があります。
一時ディスクのままにすると、デプロイや再起動でジョブ履歴が消えます。

ヘルスチェックURL:

```text
/healthz
```

公開前チェックURL:

```text
/deployment-readiness
```

この画面は、PaaSへ載せる直前に以下をまとめて確認します。

- `Procfile` / `requirements.txt` / `env.example`
- ジョブDB保存先の存在・書き込み可否
- `ONLINE_APP_DATA_DIR` の指定有無
- Geminiキー・WordPress認証の環境変数上書き有無
- `SEARCHAPI_API_KEY` の有無
- `/diagnostics` のエラー数

サーバー再起動などで `running` のまま残ったジョブは、起動時に
`ONLINE_APP_STALE_RUNNING_MINUTES` 分以上更新がなければ中断扱いへ戻します。
ジョブ一覧画面からも手動で復旧できます。

## 公開環境の秘密情報

オンライン版は、起動時に以下の環境変数があれば `auto_post_unified.py` の固定値を上書きします。
ローカルCLIを壊さずに、Web公開時だけ秘密情報管理へ寄せるための入口です。

```text
ONLINE_GEMINI_KEYS_NORMAL_JSON=[{"name":"結びのマリッジ用","key":"AIza..."}]
ONLINE_GEMINI_KEYS_MOECHIN_JSON=[{"name":"もえちん用","key":"AIza..."}]
ONLINE_WP_SITE_OVERRIDES_JSON={"2":{"url":"https://www.marriage-mr.com","user":"...","pass":"..."}}
```

`ONLINE_GEMINI_KEYS_NORMAL_JSON` を設定した場合、オンライン画面のAPIキー選択肢はその配列だけになります。
`ONLINE_WP_SITE_OVERRIDES_JSON` はサイトキー単位で `url` / `user` / `pass` など必要項目だけ上書きします。

現状はローカル共有フォルダ前提の実装をWeb UIで包んだ段階です。
公開サーバーへそのまま置くと、認証情報・保存先・長時間処理の扱いが弱いままになります。

## 起動コマンド例

Linux系PaaSで起動する場合の基本形:

```bash
uvicorn online_app.app:app --host 0.0.0.0 --port ${PORT:-8000}
```

リポジトリ直下に `Procfile` を置いてあります。

```text
web: uvicorn online_app.app:app --host 0.0.0.0 --port ${PORT:-8000}
```

Docker対応のPaaSでは、リポジトリ直下の `Dockerfile` を使えます。
コンテナは `PORT` 環境変数を読み、`0.0.0.0` で待ち受けます。

## Renderでの最小構成

`render.yaml` を追加済みです。

- Docker環境
- `/healthz` をヘルスチェックに使用
- `/var/data` を永続ディスクとして `ONLINE_APP_DATA_DIR` に指定
- 秘密情報は `sync: false` の環境変数として管理

Renderでは、FastAPIをデプロイする公式手順とヘルスチェックの仕組みに沿って、サービスがヘルスチェックに通った時点で新しいデプロイへルーティングされます。

## Cloud Run / Fly.io へ逃がす場合

`Dockerfile` があるため、基本は同じです。

必要なこと:

1. コンテナをビルドして公開先へ送る
2. `PORT` は公開先が渡す値を使う
3. `ONLINE_APP_DATA_DIR` を永続ストレージへ向ける
4. `/healthz` をヘルスチェックにする
5. 秘密情報を環境変数へ設定する

## 次にオンライン移植で固定すること

- 公開先を決め、`ONLINE_APP_DATA_DIR` を永続ボリュームへ向ける
- 公開先に `ONLINE_GEMINI_KEYS_NORMAL_JSON` と `ONLINE_WP_SITE_OVERRIDES_JSON` を設定する
- デプロイ後に `/healthz`、`/deployment-readiness`、安全確認ジョブ、本番小規模ジョブの順で確認する
- 生成結果の保存先をローカルGoogle Drive依存からサーバー保存先へ切り替える
- 内部リンク貼り付け指示まとめ・子記事作成リストまでWeb上で確認できるようにする
