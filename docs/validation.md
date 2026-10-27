# 開発環境での検証

人工 crontab を使い、Python 3.14.4 / FastAPI 0.162.0 / croniter 6.2.4 で pytest 10件成功。API の TestClient は、開発環境のサンドボックス内でスレッド間通知が停止したため、制限外で実行した。Starlette TestClient から httpx 連携の将来的な非推奨警告が1件出るがテストは成功。

検証内容：コメント・環境変数・不正記法、安定 ID、秘密情報の非表示、件数・サイズ上限、月日/曜日 OR、存在しない日付、DST ギャップと繰り返し、次回予定、7日分の API、CSV 数式対策、フィルタ、異なる Origin の拒否、Collector 例外の隔離、読み取り失敗時の古いキャッシュ表示。

旧構成を前提に `docker compose config --quiet` と nas-a-admin + 接続 override の Compose 構文・マージを確認済み。ただし、これは同一 Docker ホストを想定した検証であり、QNAP → LAN → server-a という新構成の成立を示さない。旧設定例は新構成には使用しない。既存サービスの変更・起動は行っていない。

2026-10-26 に新構成へドキュメントを訂正した後、プロキシ IP allowlist と LAN HTTP 公開を実装した。現在の全テストは **34件成功**（Python 3.14.4）。個別 IPv4/IPv6、IPv4-mapped IPv6、空の全拒否、不正な設定の起動拒否、全ルートの制限、転送ヘッダー偽装の無効化、loopback の healthz 例外、許可されたプロキシの中継を検証した。Starlette の非推奨警告1件は継続している。

新 Compose はサンプルの bind IP・プロキシ IP を指定して構文を確認。実際の IP が空のままなら Compose が設定エラーとなる。

実際の Uvicorn を開発環境の loopback で起動し、送信元を別の loopback IP に変えた TCP 接続でも検証した。許可 peer は200、非許可 peer は403、許可 IP の転送ヘッダー偽装は403、許可 peer の転送ヘッダーが非許可 IP でも200となること、healthz 以外には loopback の例外がないことを確認済み。旧同一ホスト用 override は無効化し、Caddy 例の upstream は QNAP の LAN HTTP に変更した。

未検証：Docker イメージのビルド・コンテナ起動（開発 PC の Docker daemon に接続権限なし）、Python 3.15 のコンテナ内実行、実ブラウザの描画と操作、QNAP の実設定・権限、server-a から QNAP への到達性と実際の送信元、他の LAN 端末への HTTP 403、Tailnet 内外からの到達性、server-a のプロキシ設定の実機適用、両ホストの再起動後の復旧。これらを済ませるまで初期バージョンの受け入れ完了とはしない。

## QNAP 起動時の PermissionError と Python 3.15 への更新

利用者の QNAP 上で `/app/src/__init__.py` の PermissionError を観測。アプリコードを非 root ユーザーが読めない状態だったため、Dockerfile で所有者とディレクトリ0755・ファイル0644を明示した。ホスト側のビルドコンテキストの正確なモード / ACL は未確認。非 root ユーザーに切り替えた後のビルド工程でアプリ import と全ソース・静的ファイルの読み取りを行い、再発時はビルドを失敗させる。

ベースイメージを `python:3.15-slim` に変更。[公式イメージ定義](https://github.com/docker-library/official-images/blob/master/library/python) で提供を確認。Python 3.15 / CPython / manylinux2014 x86_64 向けに requirements.txt の全依存 wheel をダウンロードできることを確認した。これは配布物の存在・依存解決の確認であり、Python 3.15 での実行検証や他 CPU 向けの検証ではない。

修正後も既存アプリテスト34件は Python 3.14.4 で成功。Docker build はサンドボックス外でも daemon socket の Permission denied で実行できなかったため、修正版イメージのビルド・非 root 起動・Python 3.15 の実行検証は QNAP 側で必要。再ビルド手順は deployment.md を参照。

## chmod 後にも残る拒否と ACL 対応

QNAP で chmod 修正後も非 root import が拒否され、ビルド時の読み取り検査が失敗した。POSIX ACL の名前付きユーザーエントリは chmod で消えないため、`deploy/prepare_image.py` を追加し、イメージ内 `/app` だけの access/default ACL を除去してからモードを設定する。ホストの設定・共有ディレクトリ・Docker の保存領域は変更しない。

実際に POSIX ACL を設定したテストで、chmod 後も named-user ACL が残ること、ヘルパーでアクセス ACL と継承 ACL を除去できることを確認。ファイル内容とモード、シンボリックリンク経由の対象外ファイルを変更しないことも検証。制限外の pytest は **37件成功**（Python 3.14.4、既存の非推奨警告1件）。サンドボックス内では ACL fixture 設定に EINVAL が出るため、その場合だけテストを skip するが、制限外では skip なしで成功した。

QNAP 実機の原因が POSIX ACL であることは未確定。修正版イメージの QNAP 上のビルド・起動は引き続き未検証。非 root のビルド検証を維持しており、権限問題を root 実行で回避しない。

## ホスト Tailscale の8443案の検証記録（撤回済み）

利用者の QNAP ログで Python 3.15 イメージのビルド・非 root import 検証・Uvicorn 起動成功を確認。server-a の curl でも QNAP の GUI / API の応答を確認済み。

server-a ホストの Tailscale Running・DNS 名・IP と未使用の8443番を読み取り確認し、既存ホスト Tailscale + Caddy の専用 Compose を追加。Compose 構文は成功、公式サイトから取得した Caddy の validate は Valid configuration。adapt 後の JSON でも Tailnet IPv4 の8443番だけの listen、管理 API と HTTP リダイレクトの無効化、LAN upstream を確認した。

sudo は対話認証が必要なためプロキシコンテナの起動は未実施。HTTPS 証明書取得、別の Tailnet 端末からのブラウザ表示・ACL 動作・LAN からの非到達性は起動後に確認する。

## 専用 Tailscale コンテナ + Caddy 443 への変更

利用者の例示に合わせ、compose.proxy.yaml を専用 Tailscale ノード + ネットワーク共有 Caddy に変更。ホスト Tailscale の8443案は撤回し、既存 tag:www-server で専用ホスト名の443へ接続する。初期登録用の deploy/.env.proxy.example と2段階のログイン・IP設定手順を追加。起動・登録・証明書取得・ブラウザ到達性は sudo と Tailnet ログインが必要なため未実施。

変更後の Compose も構文・JSON 展開を検証。専用 state/socket、service:tailscale のネットワーク共有、ホストポート非公開、カーネルモード、tag:www-server、Running を待つ health 依存を確認した。Caddy validate は成功し、adapt JSON でも新ノードのサンプル Tailnet IPv4:443 のみの待受・管理API/HTTPリダイレクト無効・LAN HTTP upstream を確認した。ホストの Tailscale socket を参照しないことも確認済み。
