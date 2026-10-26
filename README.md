# QTS Schedule Viewer
QNAP QTS 上の定期タスクを横断的に一覧・可視化するツール。

略称：QSV

QNAP 公式とは無関係のサードパーティーアプリです。

## 現在の実装

QNAP 上の Container Station / Docker で動く、読み取り専用の初期実装です。開発 PC への共有フォルダのマウントと、コンテナの実行場所は別です。

- cron 収集、次回予定の計算、週間タイムライン（月曜始まり / 指定日から7日間）
- 日本語の一覧・詳細、検索・カテゴリ・提供元・有効状態のフィルタ、CSV 出力
- 起動時 / 5分ごと / 手動の再取得、収集状態と古い情報の表示
- 非 root・read-only コンテナ（公開用 Compose は新構成への変更待ち）

電源・RAID・SMART・Snapshot・HBS 3 等は **実機調査待ちで未対応** です。cron は人工サンプルで検証しており、QTS 上の動作・Tailnet 到達性は未検証です。すべての cron は system 分類とし、実機確認なしのカテゴリ推定は行いません。コマンド引数は秘密情報保護のため一律非表示です。

## QNAP への導入

構成は次を前提とします。QNAP では Tailscale を動かしません。

```text
Tailnet のブラウザ
  → server-a（Tailscale / リバースプロキシ / HTTPS 終端）
  → LAN 上の QNAP（QSV コンテナ：収集・API・Web UI）
```

[導入・Tailnet 公開設計](docs/deployment.md) を参照してください。QNAP のバックエンド入口は server-a からだけ接続できるよう制限します。Tailnet ACL だけでは QNAP への LAN からの直接接続は制限できません。

**現在の compose.yaml と deploy/ の設定例は旧構成用で、新構成には未対応です。そのまま導入しないでください。** 今回はドキュメントを先に更新しています。

`QSV_CRONTAB_SOURCE` は **QNAP 側のパス** です。単一ファイルを読み取り専用で共有し、QTS の設定や権限は変更しません。

## 開発・テスト

Python 3.13 以上を使用します。人工データでのローカル確認例：

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
QSV_CRONTAB_PATH=./samples/crontab QSV_TIMEZONE=Asia/Tokyo uvicorn src.api:app --host 127.0.0.1 --port 8000
```

`http://127.0.0.1:8000/` を開きます。テストは `python -m pytest -q`。本番用 Docker イメージの常駐 Node.js や外部 CDN は不要です。

## ドキュメント

- [仕様書](doc/SPEC.md)
- [構成・API・制限](docs/architecture.md)
- [QTS 実機調査状況](docs/qts-research.md)
- [導入・更新・削除](docs/deployment.md)
- [セキュリティ](docs/security.md)
- [Collector と対応形式](docs/collectors.md)
- [検証結果と未検証項目](docs/validation.md)
