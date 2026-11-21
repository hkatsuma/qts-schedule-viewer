# QNAP で worktree を一時起動する

| 作業場所 | この手順で行うこと |
| --- | --- |
| QNAP（SSH） | このページの全コマンドを、通常の QSV 用 `compose.yaml` と `.env` がある main のリポジトリルートで、同じシェルから順に実行する。 |
| beelinkminis12（導入手順の `server-a`） | 稼働中の Tailscale と Caddy をそのまま使う。この手順での操作は不要。 |
| Tailnet に接続した端末のブラウザ | 普段の QSV の HTTPS URL で、テスト版の動作と main への復帰を確認する。 |

既存の保存データでスキーマ1から2への移行を確認するには、手順1から4まで順に行う。手順2で稼働中の main の DB をコピーし、手順3でテスト版を初めて起動したときにコピーが移行される。main の DB がすでにスキーマ2の場合は、そのコピーで注釈の表示を確認できる。スキーマ1からの移行を再現するには、移行前のバックアップを使う。既存データを使わずに動作確認する場合は手順2を飛ばす。

worktree は、`feature/` を除いたブランチ名を小文字化し、`/` 等を `-` に置き換えた名前で `.worktrees/` 配下に作成しておく。たとえば `feature/command-identity` は `.worktrees/command-identity`。

テスト用のプロジェクト名とイメージ名、DB volume を分ける。テスト中の注釈は main の DB に保存されない。通常動作へ戻すと main の注釈が表示される。

## 1. QNAP で準備とビルド

先頭のブランチ名を対象に合わせる。ビルドは main を止める前に行う。

```sh
QSV_BRANCH="feature/command-identity"
QSV_MAIN_DIR="$(pwd -P)"
QSV_WORKTREE_NAME="$(
  printf '%s' "${QSV_BRANCH#feature/}" |
    tr '[:upper:]' '[:lower:]' |
    tr -c 'a-z0-9_-' '-'
)"
QSV_TEST_DIR="$QSV_MAIN_DIR/.worktrees/$QSV_WORKTREE_NAME"
QSV_TEST_PROJECT="qsv-test-$QSV_WORKTREE_NAME"
QSV_TEST_IMAGE="$QSV_TEST_PROJECT:local"
QSV_TEST_OVERRIDE="$(mktemp /tmp/qsv-test.XXXXXX)"

cat > "$QSV_TEST_OVERRIDE" <<EOF_COMPOSE
services:
  qsv:
    image: "$QSV_TEST_IMAGE"
    build:
      context: "$QSV_TEST_DIR"
    environment:
      QSV_DB_PATH: /data/qsv.sqlite3
    volumes:
      - type: volume
        source: qsv-test-data
        target: /data
volumes:
  qsv-test-data:
EOF_COMPOSE

qsv_test() {
  sudo docker compose \
    --project-directory "$QSV_MAIN_DIR" \
    --env-file "$QSV_MAIN_DIR/.env" \
    -f "$QSV_MAIN_DIR/compose.yaml" \
    -f "$QSV_TEST_OVERRIDE" \
    -p "$QSV_TEST_PROJECT" \
    "$@"
}

test -d "$QSV_TEST_DIR/src" &&
qsv_test config --quiet && qsv_test build qsv
```

## 2. QNAP で main の保存データをテスト用 DB に復元

準備とビルド後、main が動いている間にバックアップを作る。以下はテスト用 DB の内容を置き換えるため、残したいテスト用データがあれば先にバックアップする。main の DB は置き換えない。

```sh
QSV_SOURCE_BACKUP="qsv-test-source-$(date +%Y%m%d-%H%M%S).sqlite3"
sudo docker compose exec -T qsv python -m src.manage_db backup "/data/$QSV_SOURCE_BACKUP"
sudo docker compose cp "qsv:/data/$QSV_SOURCE_BACKUP" "./$QSV_SOURCE_BACKUP"

qsv_test stop qsv
sudo cat "./$QSV_SOURCE_BACKUP" | qsv_test run --rm -T --interactive --no-deps --entrypoint python qsv -c '
import os, sys, shutil, tempfile
from pathlib import Path
from src.manage_db import restore
with tempfile.NamedTemporaryFile(dir="/data", suffix=".sqlite3") as source:
    shutil.copyfileobj(sys.stdin.buffer, source)
    source.flush()
    restore(Path(source.name), Path(os.environ["QSV_DB_PATH"]), offline=True)
print("テスト用DBへの復元完了")
'
```

一時コンテナはポートを公開せず、復元先はテスト用の /data volume。次の起動時にスキーマ1はバックアップ後に2へ更新される。現在の cron 行で旧 ID を確認できる表示名・タグはコマンド単位の ID へ移る。対応不明の旧 ID は残り、異なる保存内容が競合する場合は画面に選択待ちが表示される。

## 3. テスト版への切り替えと確認

### QNAP でテスト版を起動

ビルド成功後、main を停止し、同じポートでテスト版を起動する。切り替え中は QSV に一時的にアクセスできなくなる。テスト版の起動に失敗した場合は手順4へ進む。

```sh
sudo docker compose down &&
qsv_test up -d --no-build

qsv_test ps
qsv_test logs --tail=50 qsv
```

### ブラウザでテスト版を確認

普段の QSV の HTTPS URL を再読み込みする。main で表示名やタグを設定済みで、現在も一覧にあるジョブをいくつか開き、切り替え前と同じ表示名・タグが付いていることを確認する。必要なら手順4で main に戻った後に照合する。

時刻だけが異なる同一コマンドの行があれば、表示名とタグは共有され、実行予定は各行に表示されることも確認する。該当する行がなければ、この確認は省略して手順4に進める。共有の挙動は [人工 crontab を使う自動テスト](../tests/test_identity_migration.py) で確認できる。QTS の crontab を試験のために変更する必要はない。

再作成後の保持も確認する場合は、ブラウザで表示名・タグを保存し、QNAP の同じ SSH シェルで `qsv_test down && qsv_test up -d --no-build` を実行する。起動後、ブラウザを再読み込みして保存内容を確認する。

## 4. main の通常動作へ戻す

### QNAP で main を起動

```sh
qsv_test down &&
sudo docker compose up -d --no-build

sudo docker compose ps
sudo docker compose logs --tail=50 qsv
```

### ブラウザで main への復帰を確認

普段の QSV の HTTPS URL を再読み込みし、main の画面と保存データに戻ったことを確認する。

### QNAP で一時ファイルを削除

```sh
rm -f "$QSV_TEST_OVERRIDE"
```

テスト用 volume は保持する。次回同じプロジェクト名なら同じ注釈 DB を使う。不要になって明示的に破棄する場合だけ、main へ戻す前に `qsv_test down -v` を使う。このコマンドはテスト用プロジェクトに対して実行し、通常運用の `docker compose down` に `-v` を付けない。
