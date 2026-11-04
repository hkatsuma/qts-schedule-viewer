# QNAP で worktree を一時起動する

main の Compose・`.env` を使い、ビルド元だけを worktree に差し替える。QNAP に SSH し、通常の Compose を実行する main のリポジトリルートで、同じシェルから順に実行する。プロキシはそのまま利用できる。

worktree は、`feature/` を除いたブランチ名を小文字化し、`/` 等を `-` に置き換えた名前で `.worktrees/` 配下に作成しておく。たとえば `feature/job-annotations` は `.worktrees/job-annotations`。

テスト用のプロジェクト名とイメージ名、DB volume を分ける。テスト中の注釈は main の DB に保存されない。通常動作へ戻すと main の注釈が表示される。

## 準備とビルド

先頭のブランチ名を対象に合わせる。ビルドは main を止める前に行う。

```sh
QSV_BRANCH="feature/job-annotations"
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
