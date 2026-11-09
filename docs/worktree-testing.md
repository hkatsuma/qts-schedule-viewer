# QNAP で worktree を一時起動する

main の Compose・`.env` を使い、ビルド元だけを worktree に差し替える。QNAP に SSH し、通常の Compose を実行する main のリポジトリルートで、同じシェルから順に実行する。プロキシはそのまま利用できる。

worktree は、`feature/` を除いたブランチ名を小文字化し、`/` 等を `-` に置き換えた名前で `.worktrees/` 配下に作成しておく。たとえば `feature/command-identity` は `.worktrees/command-identity`。

テスト用のプロジェクト名とイメージ名、DB volume を分ける。テスト中の注釈は main の DB に保存されない。通常動作へ戻すと main の注釈が表示される。

## 準備とビルド

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

## main の保存データで移行を確認する場合

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

確認時は、時刻だけが異なる同一コマンドの行で表示名とタグを共有し、実行予定は各行のままになっていることを確認する。QTS の crontab を試験のために変更する必要はない。

## 切り替えと確認

ビルド成功後、main を停止して起動する。

```sh
sudo docker compose down &&
qsv_test up -d --no-build

qsv_test ps
qsv_test logs --tail=50 qsv
```

通常のブラウザ URL を再読み込みして確認する。タグ・表示名を保存し、`qsv_test down && qsv_test up -d --no-build` で再作成した後も残ることを確認できる。テスト版の起動に失敗した場合も、次の復帰手順を実行する。

## main の通常動作へ戻す

```sh
qsv_test down &&
sudo docker compose up -d --no-build

sudo docker compose ps
sudo docker compose logs --tail=50 qsv
```

ブラウザも再読み込みし、main の画面と API の組み合わせに戻す。main の復帰を確認したら一時ファイルを削除する。

```sh
rm -f "$QSV_TEST_OVERRIDE"
```

テスト用 volume は保持する。次回同じプロジェクト名なら同じ注釈 DB を使う。不要になって明示的に破棄する場合だけ、main へ戻す前に `qsv_test down -v` を使う。このコマンドはテスト用プロジェクトに対して実行し、通常運用の `docker compose down` に `-v` を付けない。
