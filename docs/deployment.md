# QNAP と server-a への配置・Tailnet 公開

## 採用する構成と制御の分担

```text
ブラウザ ── Tailnet / HTTPS ── server-a ── ホーム LAN / HTTP ── QNAP / QSV
             Tailscale ACL       リバースプロキシ                    プロキシ IP 制限
```

- QNAP：Container Station / Docker で収集・キャッシュ・API・Web UI を同じコンテナに置く。Tailscale は動かさない。
- server-a：既存の Tailscale とリバースプロキシを使い、ブラウザ向け HTTPS を終端する。ここへのアクセスは **Tailscale ACL** で制御し、プロキシ側に独自の IP allowlist は追加しない。
- QSV：バックエンドに直接接続する **中継プロキシの IP だけ** を allowlist で制限する。Tailnet の各クライアント IP は検査しない。
- ホーム LAN は信頼する。バックエンドは HTTP + プロキシ IP 制限とし、パスワード・トークン等の追加認証情報は使わない。
- 開発 PC：QNAP のディレクトリをマウントして編集する。コンテナ実行ホストではない。

新しい Tailscale ノードや設定ファイルの server-a への共有は不要。同名 Docker bridge network で別ホストは接続できないため、QNAP の LAN IP・専用ポートを upstream にする。

## QNAP 上での設定・起動

`/etc/config/crontab` 1ファイルを読み取り専用 bind mount する。非 root、capabilities 全削除、privileged・Docker socket 不使用、root filesystem 読み取り専用を維持する。QTS の設定やファイル権限をアプリから変更しない。読み取り権限がなければ収集状況に表示する。

QNAP のシェルで実行する。Container Station から Compose を登録する場合も QNAP 上のファイルと同じ設定値を使う。

```sh
cp .env.example .env
# 下表に従い .env を編集する
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail=50 qsv
```

| 環境変数 | 意味 | 設定例（実機値に置換） |
|---|---|---|
| QSV_BIND_IP | ポートを公開する QNAP の LAN IP。必須 | 192.168.0.1 |
| QSV_BIND_PORT | 未使用のバックエンド HTTP ポート | 18080 |
| QSV_ALLOWED_PROXY_IPS | QNAP から見たプロキシの接続元 IP。必須 | 192.168.0.2 |
| QSV_CRONTAB_SOURCE | QNAP 上の参照ファイル | /etc/config/crontab |
| QSV_TIMEZONE | NAS のタイムゾーン | Asia/Tokyo |
| QSV_REFRESH_SECONDS | 収集周期。最小30秒 | 300 |
| QSV_UID / QSV_GID | コンテナの非 root 実行ユーザー | 10001 / 10001 |

QSV_BIND_IP は LAN の特定アドレスにする。`0.0.0.0` や全 IPv6 への無条件の公開を避ける。localhost だけへの bind では別ホストから接続できない。IP は DHCP 予約等で安定させる。

QSV_ALLOWED_PROXY_IPS はカンマ区切りの個別 IPv4 / IPv6 アドレス。前後の空白は除去する。CIDR・ホスト名・ワイルドカード・末尾の空要素は不正として起動エラーにする。IPv4-mapped IPv6 は IPv4 と同一視する。Compose では未設定・空を設定エラーにする。アプリ単体で未設定・空の場合は全拒否になる。

例：`QSV_ALLOWED_PROXY_IPS=192.168.0.2,192.168.0.3` は2台の中継プロキシを許可する。Tailnet クライアントのアドレスを列挙する設定ではない。

設定変更後は `docker compose up -d` でコンテナを再作成する。単なる restart では変更後の環境変数は反映されない。

## IP 判定とヘルスチェック

QSV は実際の TCP 接続元を判定する。`X-Forwarded-For`、`Forwarded`、`X-Real-IP` は一切 allowlist 判定に使わない。Dockerfile の Uvicorn `--no-proxy-headers` を外さない。

許可外の接続からの画面・API・CSV・静的ファイルへの要求には **HTTP 403** を返す。アプリ層の制限であり、TCP 接続を遮断する firewall ではない。唯一の例外はコンテナ内 loopback からの `/healthz` で、Docker HEALTHCHECK のために許可する。loopback でも他の API・画面は通常の制限対象。

コンテナ / NAT / 複数 NIC により実際の接続元が想定と異なる場合がある。許可元・拒否元の両方から実測し、server-a だけを識別できることを確認する。複数の送信元が共通の gateway IP に見える場合は、その gateway を安易に許可しない。経路の見直しや既存のネットワーク制限でプロキシを区別する。

Docker と firewall の経路については [Docker のポート公開](https://docs.docker.com/engine/network/port-publishing/) と [firewall の説明](https://docs.docker.com/engine/network/packet-filtering-firewalls/) を参照。QSV が QTS の firewall を書き換える機能は持たない。

## server-a のリバースプロキシ

`deploy/Caddyfile.qsv.example` は Caddy の設定例。実際のプロキシ製品・配置・Tailscale モード・IP・ドメイン・証明書はまだ未確認であり、既存方式に合わせる。

1. upstream を `http://<QNAP の LAN IP>:<専用ポート>` にする。Docker サービス名 `qsv:8000` や server-a 自身の localhost には向けない。
2. 既存の Tailnet 専用入口にサイトを追加し、Tailscale ACL で利用者を制限する。独自の IP allowlist や追加の認証情報はプロキシに設けない。Funnel は使わない。
3. Tailnet IP へ直接 bind する設定例は、その IP がプロキシのネットワーク名前空間に存在する場合に使う。userspace モードなら既存の検証済み Tailnet 受信方式に合わせる。
4. ブラウザ向け HTTPS は既存の証明書運用に合わせる。例の `get_certificate tailscale` は既存構成同様に Tailscale socket へのアクセスが必要。
5. 元の Host を保持する。手動再取得の Origin 検査に必要。現状の UI はルート `/` 配下用なので、専用ドメインまたは専用ポートを使う。`/qsv/` のようなサブパス配置は未対応。
6. 設定を検証してから既存の手順で reload する。QSV の導入のために既存 Tailscale インスタンスを増やさない。

Caddy の参考：[reverse_proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)。

旧 `deploy/admin.compose.override.yaml` は同一ホスト用だったため、現在は無効な移行案内として `services: {}` のみを残している。両ホストの起動ファイルへ組み込む必要はない。

## 実機での検証

1. QNAP の bind IP・ポート・マウント・権限・タイムゾーンを確認する。
2. server-a の実際のプロキシ実行環境から QNAP の `/healthz`、画面、API が HTTP 200 になることを確認する。
3. 許可していない LAN 端末から QNAP の画面・API・CSV が HTTP 403 になることを確認する。許可 IP を X-Forwarded-For に偽装しても拒否されることを確認する。IPv6・別 NIC 経路も確認する。
4. 許可された Tailnet 端末から HTTPS で閲覧・手動再取得・CSV 出力できることを確認する。許可されない端末は Tailscale ACL で拒否されることを確認する。
5. Tailnet を切った端末から server-a の LAN IP や公開 IP で入口を利用できず、ルーターのポート転送や Funnel 等でも一般公開されていないことを確認する。
6. QTS の設定と収集結果を照合し、設定変更後の再取得も確認する。
7. 両ホストをそれぞれ再起動し、QSV・proxy・Tailscale・設定値が復旧することを確認する。

LAN 区間は HTTP であり Tailscale による暗号化の対象外。信頼するホーム LAN と許可したプロキシを前提とする。実機検証は未実施。

## ファイル更新・運用

単一ファイルの bind mount は、QTS が rename で設定を置換すると古い inode を参照し続ける可能性がある。更新方法は実機未確認。反映されない場合は QNAP 上で `docker compose up -d --force-recreate qsv` によりマウントし直す。`/etc/config` 全体の共有で回避しない。

更新は QNAP 上でコード取得後 `docker compose up -d --build`。削除時は server-a の QSV 向けサイトを除去し、QNAP で `docker compose down` を実行する。既存 Tailscale state・証明書・QTS 設定は削除しない。

## アプリ読み込み時の PermissionError

`Permission denied: '/app/src/__init__.py'` は、アプリ自身のイメージ内ファイルを非 root ユーザーが読めない起動エラー。crontab の読み取り権限不足とは別の問題である。通常の chmod だけでは、名前付きユーザーへの拒否 ACL が残る場合がある。Dockerfile はビルド用 `deploy/prepare_image.py` で、イメージ内 `/app` の POSIX アクセス ACL・ディレクトリのデフォルト ACL を除去してから、ディレクトリ0755・ファイル0644へ正規化する。所有者は COPY で root に明示する。ACL の除去に失敗した場合はビルドを止める。ビルド中に非 root ユーザーで import と静的ファイルの読み取りを検証する。QTS 側の設定ファイルや共有フォルダの権限は変更しない。

chmod のみの前回修正でも同じエラーが発生したため、ACL の除去を追加した。QNAP 実機の ACL 値は未取得であり、これが実機の原因であることは未確定。POSIX ACL とモードの相互作用は [Moby の報告](https://github.com/moby/moby/issues/49766) も参照。

修正版は Python 3.15 の公式 slim イメージを使用する。Dockerfile の修正を反映するには QNAP 上でイメージの再ビルドが必要。

```sh
docker compose build --pull --no-cache qsv
docker compose up -d --force-recreate qsv
docker compose logs --tail=50 qsv
```

再ビルド後も同じエラーが出る場合は、実際に使用している Compose プロジェクトとイメージが修正版であること、追加の override で `/app` をホストからマウントしていないことを確認する。

ログの `git was not found` はビルド時にコミット情報を付与できない警告であり、今回の PermissionError の原因ではない。

## server-a での今回の公開設定

2026-10-26 にホスト Tailscale の Running 状態と DNS 名 `server-a.tailnet-name.ts.net`、IPv4 `100.101.102.103` を確認。ホストの8443番は未使用。QNAP `http://192.168.0.1:18080/` から HTTP 200 を確認した。Docker は sudo 認証が必要で、ここからの起動は未実施。

`deploy/compose.proxy.yaml` は既存の **ホスト Tailscale** を使う Caddy だけの構成。起動場所は server-a。QNAP 用のルート compose.yaml とは別プロジェクトであり、アプリは再起動しない。

```sh
# server-a 上、本リポジトリのディレクトリで実行
sudo docker compose -f deploy/compose.proxy.yaml run --rm --no-deps proxy caddy validate --config /etc/caddy/Caddyfile
sudo docker compose -f deploy/compose.proxy.yaml up -d
sudo docker compose -f deploy/compose.proxy.yaml logs --tail=50 proxy
```

ブラウザで `https://server-a.tailnet-name.ts.net:8443/` を開く。利用端末は Tailnet に接続し、既存 Tailscale ACL が server-a の TCP 8443 を許可している必要がある。ACL の設定自体はこの Compose から変更しない。

Caddy は host network を使い、Tailnet IPv4 の8443だけに bind する。HTTPリダイレクト用の80番と管理APIは無効化。証明書は既存 tailscaled の socket 経由で取得し、Tailnet の HTTPS 設定が有効であることが前提。LAN upstream の実送信元は server-a のホスト側 LAN IP になるため、既に curl で許可を確認した接続元と同じ経路を使える。

設定値は `QSV_PUBLIC_HOST`、`QSV_PUBLIC_PORT`、`QSV_TAILNET_IP`、`QSV_UPSTREAM` で上書きできる。既定値は上記の実測環境用。socket は証明書取得に使うため、共有先はこのプロキシだけとし、ほかのコンテナに共有しない。

起動後、同じホストからの確認例：

```sh
curl -fsS -o /dev/null -w '%{http_code}\n' https://server-a.tailnet-name.ts.net:8443/
curl -fsS -X POST -H 'Origin: https://server-a.tailnet-name.ts.net:8443' https://server-a.tailnet-name.ts.net:8443/api/refresh
```

最終確認は別の許可済み Tailnet 端末のブラウザで行う。LAN だけの端末から `https://192.168.0.2:8443/` へ接続できないことも確認する。設定変更の反映は `sudo docker compose -f deploy/compose.proxy.yaml restart proxy`。停止は同じファイルを指定して `down` とし、QNAP の QSV や既存のほかのプロキシは停止しない。
