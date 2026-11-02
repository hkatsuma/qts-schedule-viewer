# QTS Schedule Viewer
QNAP QTS 上の定期タスクを横断的に一覧・可視化するツール。

略称：QSV

QNAP 公式とは無関係のサードパーティーアプリです。

## 現在の実装

QNAP 上の Container Station / Docker で動く、読み取り専用の初期実装です。開発 PC への共有フォルダのマウントと、コンテナの実行場所は別です。

- cron 収集、次回予定の計算、週間タイムライン（月曜始まり / 指定日から7日間）
- 日本語の一覧・詳細、検索・カテゴリ・提供元・有効状態のフィルタ、CSV 出力
- 起動時 / 5分ごと / 手動の再取得、収集状態と古い情報の表示
- 非 root・read-only コンテナ、LAN HTTP バックエンドとプロキシ IP allowlist

電源・RAID・SMART・Snapshot・HBS 3 等は **実機調査待ちで未対応** です。cron は人工サンプルで検証しており、QTS 上の動作・Tailnet 到達性は未検証です。すべての cron は system 分類とし、実機確認なしのカテゴリ推定は行いません。コマンド引数は秘密情報保護のため一律非表示です。

## QNAP への導入

構成は次を前提とします。QNAP では Tailscale を動かしません。

```text
Tailnet のブラウザ
  → server-a（QSV 専用 Tailscale コンテナ / Caddy / HTTPS 443）
  → LAN 上の QNAP（QSV コンテナ：収集・API・Web UI）
```

[導入・Tailnet 公開設計](docs/deployment.md) を参照してください。Tailnet からリバースプロキシへのアクセスは Tailscale ACL で制御します。QNAP は信頼するホーム LAN 経由の HTTP 接続とし、バックエンドでは中継するプロキシの接続元 IP だけを allowlist で制限します。追加のパスワード・トークン認証は使いません。

QNAP 上で `.env.example` を `.env` にコピーし、`QSV_BIND_IP`（QNAP の LAN IP）と `QSV_ALLOWED_PROXY_IPS`（server-a の実際の接続元 LAN IP）を設定して `docker compose up -d --build` で起動します。空の allowlist は拒否、不正な IP は起動エラーになります。設定例の IP は実機の値に置き換えてください。

`deploy/Caddyfile.qsv.example` は server-a 上の Caddy 用の例です。プロキシ側に独自の IP allowlist は追加しません。

`QSV_CRONTAB_SOURCE` は **QNAP 側のパス** です。単一ファイルを読み取り専用で共有し、QTS の設定や権限は変更しません。

## 開発・テスト

コンテナは Python 3.15 を使用します。ローカル開発も Python 3.15 を推奨します（既存テストは 3.14 でも実施）。人工データでのローカル確認例：

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
QSV_CRONTAB_PATH=./samples/crontab QSV_TIMEZONE=Asia/Tokyo QSV_ALLOWED_PROXY_IPS=127.0.0.1 uvicorn src.api:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

`http://127.0.0.1:8000/` を開きます。テストは `python -m pytest -q`。本番用 Docker イメージの常駐 Node.js や外部 CDN は不要です。

## ドキュメント

- [仕様書](docs/SPEC.md)
- [構成・API・制限](docs/architecture.md)
- [QTS 実機調査状況](docs/qts-research.md)
- [導入・更新・削除](docs/deployment.md)
- [セキュリティ](docs/security.md)
- [Collector と対応形式](docs/collectors.md)
- [検証結果と未検証項目](docs/validation.md)

server-a での公開用に [deploy/compose.proxy.yaml](deploy/compose.proxy.yaml) を用意しています。専用 Tailscale ノードと Caddy を使う起動方法と公開 URL は [導入手順の公開設定](docs/deployment.md#server-a-の公開設定) を参照してください。

公開先は専用ノードの `https://qsv.tailnet-name.ts.net/`（実際の登録 DNS 名を確認）。既存の `tag:www-server` を使用するため、提示された grants では管理者と `tag:client` から443へ接続できます。Tailnet Lock が有効なら、初回ログイン後に既存の署名端末で QSV ノードを署名してください。
